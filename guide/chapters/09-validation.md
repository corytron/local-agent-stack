title: Validating the deployment

# Validating the deployment

This chapter confirms that the whole stack works from the workstation, end to end, and records the
performance of your system as a baseline for later comparisons. You run the smoke tests, check
each endpoint by hand, test tool calling and retrieval over your documents, and record a benchmark
baseline. The last topic describes how changes are checked for regressions: what the repository
provides in this release, and the evaluation suites and regression gate that are planned.

Repeat this chapter after every change to the stack: a new release, a new model file, a new
llama.cpp image, or changed server flags. Before you start, check the following:

- The four apps run on TrueNAS: `ai-inference` (Chapter 4), `ai-edge` with its certificate
  (Chapter 5), and `ai-rag` and `ai-web` with the Open WebUI service users and the `rag-docs`
  knowledge base (Chapter 6).
- On `c4dev`, `~/.config/local-agent-stack/client.env` holds `LAB_DOMAIN`, the `c4dev` key as
  `LOCAL_LLM_KEY`, and `MCP_HUB_TOKEN`, and OpenCode is installed (Chapter 7).
- On `c4dev`, the clone of the repository at `~/local-agent-stack` is at the same release tag as the
  clone on TrueNAS (Chapter 3).

Table: Values used in this chapter

| Value | Meaning |
|---|---|
| `lab.example.com` | Your domain (`LAB_DOMAIN`) |
| `192.0.2.10` | LAN address of the TrueNAS server |
| `sk-local-...` | A LiteLLM key |
| `<n>`, `<s>` | A number or a duration in seconds that varies from run to run |

## Run the smoke tests

`tools/smoke.py` checks every endpoint of the deployed stack from the workstation, through Caddy,
with the same names and keys that the clients use. It needs only the Python standard library.

### Smoke test checks

Table: Checks of smoke.py

| Check | Request | Passes when |
|---|---|---|
| `tls` | A TLS handshake with `chat.`, `llm.`, `models.`, `mcp.` and `search.<LAB_DOMAIN>` on port 443 | Each certificate verifies for its name, and expires in seven days or more |
| `models` | `GET https://llm.<LAB_DOMAIN>/v1/models` with `LOCAL_LLM_KEY` | All eight LiteLLM names are listed |
| `chat` | `POST /v1/chat/completions` (OpenAI format), `local-fast`, a few tokens | The answer has text |
| `messages` | `POST /v1/messages` (Anthropic format, as Claude Code sends it), `local-haiku`, a few tokens | The answer is an Anthropic message with text |
| `embeddings` | `POST /v1/embeddings`, `local-embed` | The answer holds one numeric vector |
| `rerank` | `POST /v1/rerank` (or `/rerank` if that answers 404), `local-rerank`, a question and two documents | Both documents are scored, and the matching one scores highest |
| `search` | `GET https://search.<LAB_DOMAIN>/search?q=local+agent+stack&format=json` | SearXNG answers JSON with a results list |
| `mcp` | An MCP `initialize` request (protocol `2025-06-18`) to `https://mcp.<LAB_DOMAIN>/servers/<name>/mcp` for `searxng`, `fetch` and `kb`, with `MCP_HUB_TOKEN` | Each server answers with an initialize result |

How `smoke.py` runs:

- **Settings.** It reads `LAB_DOMAIN`, `LOCAL_LLM_KEY` and `MCP_HUB_TOKEN` from the environment, and
  then from `~/.config/local-agent-stack/client.env` for any value the environment lacks. A check
  whose key is missing fails and names the variable to set. Keys are never printed.
- **Order.** The two checks that make the GPU generate, `chat` and `messages`, run one after the
  other; every other check runs at the same time as them. The report lists the checks in the order
  of the table.
- **Options.** `--only <check> ...` runs a subset. `--timeout <seconds>` sets the limit per request
  (default 120). `--cafile <file>` trusts a private CA, for the internal CA of Appendix D.
  `--env-file <file>` reads another settings file.
- **Exit codes.** `0` when every check passed, `1` when a check failed, `2` for a usage error, such
  as a missing `LAB_DOMAIN`.

### Run smoke.py from the workstation

#### Steps

1. On `c4dev`, change to the clone:

        cd ~/local-agent-stack

2. Check the Python version:

        python3 --version

    The version is 3.11 or later; `smoke.py` uses features of Python 3.11.

3. Run every check:

        python3 tools/smoke.py

    The output has this shape:

        ok tls
          chat.lab.example.com: certificate valid, <n> days left
          llm.lab.example.com: certificate valid, <n> days left
          models.lab.example.com: certificate valid, <n> days left
          mcp.lab.example.com: certificate valid, <n> days left
          search.lab.example.com: certificate valid, <n> days left
        ok models
          /v1/models lists all 8 names
        ok chat
          local-fast answered 'OK' in <s> s
        ok messages
          local-haiku answered 'OK' in <s> s
        ok embeddings
          local-embed returned a 1024-dimension vector
        ok rerank
          local-rerank ranked the matching document first (/v1/rerank)
        ok search
          SearXNG answered JSON with <n> results
        ok mcp
          searxng: <server name> <version>, <protocol version>
          fetch: <server name> <version>, <protocol version>
          kb: <server name> <version>, <protocol version>
        smoke: 8 passed, 0 failed, <s> s (lab.example.com)

    The exact text of the answers can differ, for example `'OK.'`.

4. Confirm the exit code:

        echo $?

    The output is `0`.

5. If the stack uses the internal CA of Appendix D and the workstation does not trust its root in
   the system store, pass the root certificate that you exported in
   [Export the root certificate from TrueNAS](#export-the-root-certificate-from-truenas):

        python3 tools/smoke.py --cafile ~/caddy-root.crt

6. If a client has just switched the GPU model, the first generating check waits for the swap.
   Give it more time:

        python3 tools/smoke.py --timeout 600

7. To repeat only some checks, name them:

        python3 tools/smoke.py --only chat messages

#### Results

Every endpoint answers through Caddy with the clients' names and keys. The last line reads
`smoke: 8 passed, 0 failed`.

### Act on a failed smoke check

A failed check prints `FAIL <check>` and the reason on the next line.

Table: Failed smoke checks

| Check | Likely cause | What to check |
|---|---|---|
| `tls` | A host name does not resolve to the server, or Caddy has no valid certificate; fewer than seven days left means that renewals fail | The DNS records and the `caddy` log (Chapter 5) |
| `models` | The key does not allow every name, or LiteLLM is not running | That `LOCAL_LLM_KEY` is the `c4dev` key with all eight names ([Verify a LiteLLM key](#verify-a-litellm-key)) |
| `chat`, `messages` | `coder` did not load, or the request timed out during a model swap | The `/running` list and the GPU memory ([Verify the models load](#verify-the-models-load)); run again with `--timeout 600` |
| `embeddings`, `rerank` | The CPU models of the `rag` group are not loaded | The `/running` list: `embed` and `rerank` are `ready` |
| `search` | SearXNG does not serve JSON, or `ai-web` is not running | The SearXNG checks of Chapter 6 |
| `mcp` | Wrong `MCP_HUB_TOKEN`, or a hub server failed to start | `MCP_HUB_TOKEN` in `client.env` matches `web.env`; the MCP hub checks of Chapter 6 |

Chapter 11 describes the causes in more detail.

## Check each endpoint by hand

These checks show the raw answers of each endpoint, which helps when a smoke check fails or when a
client misbehaves. They run on `c4dev`.

### Check the gateway endpoints

#### Prerequisites

`LAB_DOMAIN` and `LOCAL_LLM_KEY` are in the environment. The shell block that Chapter 7 adds to your
shell profile exports them in every new terminal. In a shell without it, run:

```
set -a; . ~/.config/local-agent-stack/client.env; set +a
```

#### Steps

1. Check that LiteLLM is alive. The probe needs no key and makes no model call:

        curl -sS https://llm.$LAB_DOMAIN/health/liveliness

    The output is `"I'm alive!"`.

2. Check that LiteLLM is ready and reaches its database:

        curl -sS https://llm.$LAB_DOMAIN/health/readiness

    The output contains `"status":"healthy"` and `"db":"connected"`.

3. List the model names that your key may use:

        curl -sS -H "Authorization: Bearer $LOCAL_LLM_KEY" https://llm.$LAB_DOMAIN/v1/models |
          python3 -c "import json, sys; \
            print(' '.join(sorted(m['id'] for m in json.load(sys.stdin)['data'])))"

    The output is the eight names, from `local-coder` to `local-sonnet`.

4. Display your key's record:

        curl -sS -H "Authorization: Bearer $LOCAL_LLM_KEY" https://llm.$LAB_DOMAIN/key/info |
          python3 -c "import json, sys; i = json.load(sys.stdin)['info']; \
            print(i.get('key_alias'), i.get('status'), i.get('spend'), i.get('models'))"

    The output starts with `c4dev active`, followed by the spend so far and the allowed names.

5. Ask `local-coder`, the agent model with thinking on, a question in the OpenAI format:

        curl -sS -H "Authorization: Bearer $LOCAL_LLM_KEY" -H 'Content-Type: application/json' \
          -d '{"model": "local-coder", "max_tokens": 2048, "messages": [{"role": "user",
               "content": "What is 17 * 23? Answer with the number only."}]}' \
          https://llm.$LAB_DOMAIN/v1/chat/completions |
          python3 -c "import json, sys; m = json.load(sys.stdin)['choices'][0]['message']; \
            print(repr(m.get('content')), 'reasoning characters:', \
            len(m.get('reasoning_content') or ''))"

    The answer is `'391'`. The model returns its thinking separately from the answer
    (`--reasoning-format deepseek`), so `content` holds only the answer; the second figure is the
    length of the thinking text, if the gateway passes it on.

6. Ask `local-sonnet` the same question in the Anthropic format, as Claude Code does:

        curl -sS -H "Authorization: Bearer $LOCAL_LLM_KEY" -H 'Content-Type: application/json' \
          -H 'anthropic-version: 2023-06-01' \
          -d '{"model": "local-sonnet", "max_tokens": 2048, "messages": [{"role": "user",
               "content": "What is 17 * 23? Answer with the number only."}]}' \
          https://llm.$LAB_DOMAIN/v1/messages |
          python3 -c "import json, sys; d = json.load(sys.stdin); c = d.get('content', []); \
            print(d.get('type'), [b.get('type') for b in c], \
            ''.join(b.get('text', '') for b in c if b.get('type') == 'text'))"

    The output starts with `message`, lists the content block types (a `text` block, possibly
    after a `thinking` block), and ends with `391`.

7. Request an embedding:

        curl -sS -H "Authorization: Bearer $LOCAL_LLM_KEY" -H 'Content-Type: application/json' \
          -d '{"model": "local-embed", "input": "local agent stack"}' \
          https://llm.$LAB_DOMAIN/v1/embeddings |
          python3 -c "import json, sys; \
            print(len(json.load(sys.stdin)['data'][0]['embedding']))"

    The output is `1024`.

8. Rerank two documents:

        curl -sS -H "Authorization: Bearer $LOCAL_LLM_KEY" -H 'Content-Type: application/json' \
          -d '{"model": "local-rerank", "query": "What is pgvector?", "top_n": 2,
               "documents": ["pgvector adds vector search to PostgreSQL.",
                             "Bananas are yellow."]}' \
          https://llm.$LAB_DOMAIN/v1/rerank |
          python3 -c "import json, sys; \
            print([(r['index'], round(r['relevance_score'], 3)) \
            for r in json.load(sys.stdin)['results']])"

    Document `0` has the higher score.

9. Confirm that the gateway refuses an invalid key:

        curl -sS -o /dev/null -w '%{http_code}\n' \
          -H 'Authorization: Bearer sk-local-xxxxxxxxxxxxxxxx' https://llm.$LAB_DOMAIN/v1/models

    The output is `401`.

!!! warning
    Do not call `https://llm.lab.example.com/health` without a model parameter. It sends a real
    request to every model, which loads `coder-moe` and swaps `coder` out of the GPU for every
    client. Use `/health/liveliness`, `/health/readiness`, or `/health?model=local-coder`.

### Check the chat, models, MCP and search host names

#### Steps

1. Check Open WebUI:

        curl -sS https://chat.$LAB_DOMAIN/health

    The output is `{"status":true}`.

2. Confirm that the llama-swap host refuses requests without its key:

        curl -sS -o /dev/null -w '%{http_code}\n' https://models.$LAB_DOMAIN/running

    The output is `401`.

3. List the loaded models through the llama-swap host, with `LLAMA_SWAP_API_KEY` from your copy of
   `inference.env`. The key is passed to `curl` on standard input:

        LSK=$(sed -n 's/^LLAMA_SWAP_API_KEY=//p' \
          ~/.config/local-agent-stack/secrets/inference.env)
        printf 'Authorization: Bearer %s\n' "$LSK" |
          curl -sS -H @- https://models.$LAB_DOMAIN/running |
          python3 -c "import json, sys; \
            [print(m['model'], m['state']) for m in json.load(sys.stdin)['running']]"
        unset LSK

    The output lists `coder`, `embed` and `rerank` as `ready`. In a browser,
    `https://models.lab.example.com/ui` opens llama-swap's interface; it asks for a user name and
    password, and accepts the key as the password.

4. Confirm that the MCP hub refuses requests without its token:

        curl -sS -o /dev/null -w '%{http_code}\n' -X POST \
          https://mcp.$LAB_DOMAIN/servers/fetch/mcp

    The output is `401`.

5. Send an MCP `initialize` request to the hub's `fetch` server with the token:

        curl -sS https://mcp.$LAB_DOMAIN/servers/fetch/mcp \
          -H "Authorization: Bearer $MCP_HUB_TOKEN" -H 'Content-Type: application/json' \
          -H 'Accept: application/json, text/event-stream' \
          -d '{"jsonrpc": "2.0", "id": 1, "method": "initialize",
               "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                          "clientInfo": {"name": "check", "version": "0"}}}'

    The answer is a JSON-RPC result, possibly in a `data:` line of an event stream, that names the
    server `mcp-fetch` with version `2026.11.11`.

6. Query SearXNG:

        curl -sS "https://search.$LAB_DOMAIN/search?q=test&format=json" | head -c 300

    The output starts with a JSON object that contains the query and a `results` list.

#### Results

Each host name reaches its service, and the services that need a key refuse requests without one.

## Test tool calling

Agents work through tool calls, and tool calls are where a model file, a chat template or a
llama.cpp build most often breaks. Run this test after every change to any of them, and whenever
an agent writes tool calls as text instead of running them. A model at temperature 1.0 does not
answer the same way every time, so send each request three times.

### Test tool calls on the OpenAI route

#### About this task

The request offers one tool, `get_weather`, and asks a question that needs it. A working stack
returns a structured tool call with valid JSON arguments, not text.

#### Steps

1. On `c4dev`, write the request:

        cat > /tmp/toolcall-openai.json <<'EOF'
        {
          "model": "local-coder",
          "max_tokens": 2048,
          "messages": [
            {"role": "user", "content": "What is the weather in Paris right now? Use the tool."}
          ],
          "tools": [
            {
              "type": "function",
              "function": {
                "name": "get_weather",
                "description": "Get the current weather for a city",
                "parameters": {
                  "type": "object",
                  "properties": {"city": {"type": "string", "description": "The city name"}},
                  "required": ["city"]
                }
              }
            }
          ]
        }
        EOF

2. Send it:

        curl -sS -H "Authorization: Bearer $LOCAL_LLM_KEY" -H 'Content-Type: application/json' \
          -d @/tmp/toolcall-openai.json -o /tmp/toolcall-openai.out \
          https://llm.$LAB_DOMAIN/v1/chat/completions

3. Display the finish reason and the tool calls:

        python3 -c "import json; c = json.load(open('/tmp/toolcall-openai.out'))['choices'][0]; \
          print(c['finish_reason']); print(c['message'].get('tool_calls'))"

    The first line is `tool_calls`. The second line is a list with one call whose function `name`
    is `get_weather` and whose `arguments` are a JSON string such as `{"city": "Paris"}`.

4. Repeat steps 2 and 3 twice.

5. Repeat the test with thinking off, through `local-fast`:

        sed 's/"local-coder"/"local-fast"/' /tmp/toolcall-openai.json \
          > /tmp/toolcall-openai-fast.json
        curl -sS -H "Authorization: Bearer $LOCAL_LLM_KEY" -H 'Content-Type: application/json' \
          -d @/tmp/toolcall-openai-fast.json -o /tmp/toolcall-openai.out \
          https://llm.$LAB_DOMAIN/v1/chat/completions

    Then run the command of step 3 again. The result is the same.

6. If a run shows `stop` and `None` instead, display the whole answer:

        python3 -m json.tool /tmp/toolcall-openai.out

    If the message's `content` or `reasoning_content` holds a `<tool_call>` text, the model wrote
    the call into its text, a known llama.cpp problem with Qwen models (llama.cpp issue 20837,
    closed on 14 November 2026; whether the fix covers these models was not confirmed). Follow
    [Tool calls fail or loop](#tool-calls-fail-or-loop).

### Test tool calls on the Anthropic route

#### Steps

1. On `c4dev`, write the request in the Anthropic format:

        cat > /tmp/toolcall-anthropic.json <<'EOF'
        {
          "model": "local-sonnet",
          "max_tokens": 2048,
          "messages": [
            {"role": "user", "content": "What is the weather in Paris right now? Use the tool."}
          ],
          "tools": [
            {
              "name": "get_weather",
              "description": "Get the current weather for a city",
              "input_schema": {
                "type": "object",
                "properties": {"city": {"type": "string", "description": "The city name"}},
                "required": ["city"]
              }
            }
          ]
        }
        EOF

2. Send it:

        curl -sS -H "Authorization: Bearer $LOCAL_LLM_KEY" -H 'Content-Type: application/json' \
          -H 'anthropic-version: 2023-06-01' \
          -d @/tmp/toolcall-anthropic.json -o /tmp/toolcall-anthropic.out \
          https://llm.$LAB_DOMAIN/v1/messages

3. Display the stop reason and the tool calls:

        python3 -c "import json; d = json.load(open('/tmp/toolcall-anthropic.out')); \
          print(d.get('stop_reason')); \
          print([b for b in d.get('content', []) if b.get('type') == 'tool_use'])"

    The first line is `tool_use`. The second line is a list with one `tool_use` block whose `name`
    is `get_weather` and whose `input` is `{'city': 'Paris'}`.

4. Repeat steps 2 and 3 twice.

5. Delete the test files:

        rm -f /tmp/toolcall-openai.json /tmp/toolcall-openai-fast.json /tmp/toolcall-openai.out \
          /tmp/toolcall-anthropic.json /tmp/toolcall-anthropic.out

#### Results

Both API formats return structured tool calls, with thinking on and off.

### Watch a real agent session for tool-call problems

#### About this task

Single requests do not show the failures of long agent sessions. Run a real task in OpenCode with
tool calls for about 30 minutes, then check the server log and the session.

#### Steps

1. On TrueNAS, after the session, count the full prompt re-processing events of the last 30
   minutes:

        sudo docker logs --since 30m llama-swap 2>&1 |
          grep -c 'Forcing full prompt re-processing'

    A few events are normal. A count that grows with every turn means that the model or the harness
    rewrites the conversation history, which makes every turn process the whole prompt again.

2. In the session, look for three signs of trouble: tool calls written into the reasoning text
   instead of being run, the same tool call repeated with the same arguments, and calls with
   malformed arguments.

#### Results

If any sign appears, follow [Tool calls fail or loop](#tool-calls-fail-or-loop) and
[Every turn re-processes the whole prompt](#every-turn-re-processes-the-whole-prompt).

## Test retrieval over your documents

This test places a document with a fact that no model can know into the `rag-docs` share, and checks
that Open WebUI and the coding agent retrieve it. It exercises the whole retrieval path: the share,
`oikb`, `docling`, the embedding model, pgvector, the reranker, and the `kb` tool of the MCP hub.

### Index a test document

#### Steps

1. On a client, create a text file named `rag-sanity-check.md` with the following content:

        # RAG sanity check

        The maintenance window code of the lab is ORCHID-4417.

2. Copy the file to the `rag-docs` share, as in
   [Copy documents to the rag-docs share](#copy-documents-to-the-rag-docs-share).

3. Start a sync at once and check its result, as in [Follow the oikb sync](#follow-the-oikb-sync),
   or wait up to 15 minutes for the next scheduled sync.

    The health report shows a new last-sync time for `rag-docs` and no error.

4. In Open WebUI, open **Workspace** > **Knowledge** > `rag-docs`.

    The knowledge base lists `rag-sanity-check.md`.

### Retrieve the test document

#### Steps

1. In Open WebUI, start a new chat with `local-coder` and ask:

        What is the maintenance window code of the lab? Search the knowledge base.

    The answer is `ORCHID-4417` and names `rag-sanity-check.md` as its source. If the answer does
    not use the document, select the knowledge base as in
    [Search the knowledge base from a chat](#search-the-knowledge-base-from-a-chat) and ask again.

2. On `c4dev`, start an OpenCode session in any repository and send:

        Find the lab's maintenance window code with search_knowledge_base. Name the file.

    The session shows a call to `search_knowledge_base`, and the answer is `ORCHID-4417` from
    `rag-sanity-check.md`.

### Remove the test document

#### Steps

1. Delete `rag-sanity-check.md` from the `rag-docs` share.

2. Start a sync at once, as in [Follow the oikb sync](#follow-the-oikb-sync), or wait for the next
   scheduled sync.

3. In Open WebUI, open **Workspace** > **Knowledge** > `rag-docs`.

    The file is no longer listed: `oikb` removes deleted files from the knowledge base.

#### Results

Documents copied to the share reach the knowledge base, both clients retrieve them, and deleted
documents leave it.

## Record a benchmark baseline

A baseline is the benchmark of your system in a known-good state. Every later benchmark is compared
with it, after a release update, a new llama.cpp image, a power limit change or a model change
(Chapter 10). `tools/bench.sh` (Chapter 4, [How bench.sh works](#how-benchsh-works)) prints Markdown
tables; this topic stores them in `/mnt/tank/ai/appdata/benchmarks`, on a dataset that the backup
tasks of Appendix A protect.

!!! caution
    The benchmarks unload the GPU model and occupy the GPU for their whole run. Run them while no
    agent or Open WebUI user is working, one at a time.

### Record the default profile baseline

#### About this task

The baseline uses the production flags of each model. If you applied a fallback in
[Apply a fallback when coder does not fit](#apply-a-fallback-when-coder-does-not-fit), use the
flags of the fallback instead: without `--spec-type draft-mtp` for fallback A, and also
`-c 49152` for fallback B. The llama-bench run uses five repetitions per test, the number that the
planned regression gate uses for its medians.

#### Steps

1. On TrueNAS, change to the clone and refresh the `sudo` credentials, so that the commands with
   pipes below do not prompt:

        cd /mnt/tank/ai/stacks/local-agent-stack
        sudo -v

2. Create the directory for the results, and a name prefix with today's date:

        sudo install -d /mnt/tank/ai/appdata/benchmarks
        D=/mnt/tank/ai/appdata/benchmarks/$(date +%F)

3. Record the release, the GPU, the driver and the power limit:

        { git describe --tags
          nvidia-smi --query-gpu=name,driver_version,power.limit --format=csv,noheader
        } | sudo tee "$D-system.txt"

4. Record the fit and speed of `coder` at its production context, with speculative decoding:

        sudo bash tools/bench.sh --mode server \
          -m Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf -c 65536 -u 512 \
          -- -ngl 99 -fa on -ctk q8_0 -ctv q8_0 -ot token_embd.weight=CPU --spec-type draft-mtp |
          sudo tee "$D-coder-server.md"

5. Record the prompt and generation speed of `coder` at three depths:

        sudo bash tools/bench.sh -m Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf \
          -c 0,16384,32768 -u 512 -r 5 | sudo tee "$D-coder-bench.md"

6. Record the speed of the embedding model on the CPU. The GPU model stays loaded for this run:

        sudo bash tools/bench.sh -m Qwen3-Embedding-0.6B-Q8_0.gguf \
          -c 0 -u 512,2048 -g 0 --unload none -- -dev none -embd 1 -t 8,16 |
          sudo tee "$D-embed-bench.md"

7. Load the production model again, so that it is ready for clients:

        echo '{"model": "coder-fast", "max_tokens": 16,
          "messages": [{"role": "user", "content": "Reply with the single word OK."}]}' |
          sudo docker exec -i llama-swap sh -c 'curl -sS -o /dev/null -w "%{http_code}\n" \
            -d @- -H "Authorization: Bearer $LLAMA_SWAP_API_KEY" \
            -H "Content-Type: application/json" http://127.0.0.1:8080/v1/chat/completions'

    The output is `200` once the model has loaded.

8. List the recorded files:

        ls -l /mnt/tank/ai/appdata/benchmarks

#### Results

The baseline files of today are stored. Compare them with the expected values in
[Read the benchmark results](#read-the-benchmark-results).

### Tune and record the fast profile

#### About this task

`coder-moe` keeps the experts of 16 layers in system RAM and decodes with 8 threads. Both values are
starting points: in the published measurement, 14 layers overflowed the VRAM, and the best thread
count on two memory channels lies between about 6 and 16. This task sweeps both with llama-bench,
then confirms the best combination at the full 64K context in server mode. llama-bench sizes its
context to the test (prompt, generated tokens and depth), so it does not show whether a combination
fits at 64K.

#### Steps

1. In the clone on TrueNAS, with `D` set as in the previous task, run the sweep:

        sudo bash tools/bench.sh -m Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf -c 0,16384 -u 2048 \
          -- -ngl 99 -fa on -ctk q8_0 -ctv q8_0 -ncmoe 14,16,18,20 -t 8,12,16 -lm none |
          sudo tee "$D-coder-moe-sweep.md"

    The table has one `pp2048` and one `tg128` row per combination of `n_cpu_moe`, threads and
    depth: 12 combinations at two depths. The run takes much longer than the runs of the default
    profile. If it stops with an out-of-memory error, remove `14` from the `-ncmoe` list and run it
    again.

2. Choose the combination with the highest `tg128 @ d16384` speed whose `pp2048` speed is not far
   below the others. Expect about 65 to 80 tokens per second of generation.

3. Confirm that the chosen combination fits at 64K. Replace `<n>` with the chosen `-ncmoe` value and
   `<t>` with the chosen thread count:

        sudo bash tools/bench.sh --mode server \
          -m Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf -c 65536 -u 2048 \
          -- -ngl 99 --n-cpu-moe <n> -fa on -ctk q8_0 -ctv q8_0 -t <t> -tb 16 -lm none |
          sudo tee "$D-coder-moe-server.md"

    The row shows `yes` under **starts**. If it shows `no`, raise `<n>` by 2 and run the step again.

4. Load the production model again, as in step 7 of the previous task.

#### Results

The fast profile's baseline is stored. If the best combination differs from `--n-cpu-moe 16` and
`-t 8`, change the `coder-moe` entry of `stack/inference/llama-swap/config.yaml` in the repository
through the workflow of Chapter 8. To use the values before the next release, use the override of
[Apply a fallback when coder does not fit](#apply-a-fallback-when-coder-does-not-fit), with this
`sed` command in its step 2 instead (replace `<n>` and `<t>`):

```
sudo sed -e '/^  coder-moe:$/,/^    ttl: 0$/s/--n-cpu-moe 16/--n-cpu-moe <n>/' \
  -e '/^  coder-moe:$/,/^    ttl: 0$/s/-t 8 -tb 16/-t <t> -tb 16/' \
  /mnt/tank/ai/stacks/local-agent-stack/stack/inference/llama-swap/config.yaml |
  sudo tee /mnt/tank/ai/appdata/llama-swap/config.yaml > /dev/null
```

The cautions of that task apply: `tools/deploy.py apply` removes the override.

### Compare a new run with the baseline

#### Steps

1. Repeat the benchmark tasks of this topic with the same commands. The new files carry the new
   date.

2. Compare the tables of the same run, for example:

        diff /mnt/tank/ai/appdata/benchmarks/<baseline-date>-coder-bench.md \
          /mnt/tank/ai/appdata/benchmarks/<new-date>-coder-bench.md

    The lines that differ show the speeds of both runs.

3. Treat a drop of more than 5% in generation or prompt speed at any depth as a regression to
   explain before you accept the change. This is the threshold that the planned regression gate
   uses. Also compare the **GPU MiB used** column of the server-mode runs: less headroom than
   before can make the model fail to load after the next change.

4. When a change is accepted, the new files become the baseline. Keep the old files; they record
   the history of the system.

#### Results

You know whether the change made the stack slower, and by how much.

## Evaluations and the regression gate

A change to the inference settings can make the stack slower or the model worse at its work. The
repository's design checks every such change against stored results before it is accepted. This
release ships the tools for speed and for end-to-end function; the evaluation suites that measure
model quality are planned and are not in the repository yet.

### Validation tools in this release

Table: Validation tools

| Tool | In this release | What it checks |
|---|---|---|
| `tools/smoke.py` | Yes | Every endpoint, end to end, from the workstation ([Run the smoke tests](#run-the-smoke-tests)) |
| `tools/bench.sh` | Yes | Fit in VRAM, GPU memory, prompt and generation speed ([Record a benchmark baseline](#record-a-benchmark-baseline)) |
| Tool-calling and retrieval tests | Yes, as procedures in this chapter | Structured tool calls on both API formats; retrieval of a planted document |
| `tools/tests/` | Yes | Unit tests of the repository's tools, `smoke.py` among them, run by `tools/check.sh` and CI; they use no model |
| `evals/` and `tools/eval.py` | No, planned | Model quality: tool calling, agentic coding, retrieval; the regression gate |

None of the CI jobs runs a model: CI has no GPU. Model checks run on your server, by hand.

### Planned evaluation suites

The design keeps the evaluation suites in `evals/` and runs them with `tools/eval.py`, with three
commands: `run`, `compare` and `verify`. Neither exists in this release.

Table: Planned evaluation suites

| Area | Harness (pinned version) | Planned content |
|---|---|---|
| Throughput | llama-bench in the server's image; `llama-benchy` 0.4.0 from the workstation | The llama-bench grid with five repetitions; end-to-end prompt and generation speed and time to the first token at several depths |
| Tool calling | Berkeley Function Calling Leaderboard, `bfcl-eval` 2026.3.23 | 50 tasks each of `simple_python`, `multiple`, `parallel`, `parallel_multiple`, `irrelevance`, `live_simple` and `live_multiple`, plus 40 of `multi_turn_base`, measured through the server's own tool-call parsing |
| Agentic coding | Harbor 0.26.0 | Smoke suite: `terminal-bench-sample@2.0` (10 tasks) and 20 pinned `aider-polyglot` tasks. Full suite, overnight: `terminal-bench@2.0` (89 tasks), 60 `aider-polyglot` tasks and 20 pinned `swebench-verified` tasks |
| Retrieval quality | ragas 0.4.4 | A golden set of 30 to 50 questions over your own documents, with reference answers and source passages; metrics such as faithfulness and context precision and recall |

Each planned results file records a checksum of the configuration (the rendered inference compose
file, the server flags and the model files' checksums), the harness versions, the GPU and driver,
the server's slots and context, the temperature and seed, and for each metric its value, the
number of tasks and a 95% interval. The files would be committed under `evals/results/`, with one
baseline per model profile under `evals/baselines/`.

### Planned regression gate rules

`tools/eval.py compare` is designed to fail a change when any of these holds. The thresholds are
proposals.

- The median generation or prompt speed falls below 0.95 times the baseline at any depth
  (llama-bench with five repetitions).
- The tool-calling score drops by more than 2 points, and a two-proportion test finds the drop
  significant.
- The agentic pass rate of the smoke suite drops by more than one task. The smoke suite is small
  and catches only gross regressions; the full suite decides.
- Any retrieval metric drops by more than 0.05.

`tools/eval.py verify` is designed to run in CI, offline: a pull request that changes the inference
settings must carry a passing results file for its own configuration checksum, or a line in
`CHANGELOG.md` with an issue number that accepts the regression.

The design also fixes how evaluations share the one GPU:

- A speed measurement has the server to itself, with no other suite running.
- Functional suites share the server, with no more concurrent requests than the server has slots.
- Two models are never loaded at once; a judge model runs after the generation phase.
- Work that needs only the CPU, such as test containers and scoring, runs on the workstation.

### Run the manual regression check

#### About this task

Until `tools/eval.py` exists, check a change by hand with the tools of this release. Chapter 10
applies this check to model changes in its evaluation gate.

#### Steps

1. Deploy the change on the server, as Chapter 10 describes for releases and model changes.

2. From the workstation, run the smoke tests:

        python3 tools/smoke.py

    The last line starts with `smoke: 8 passed, 0 failed`.

3. Run [Test tool calling](#test-tool-calling), including a real agent session.

4. Run [Test retrieval over your documents](#test-retrieval-over-your-documents).

5. Benchmark the changed configuration and compare it with the baseline, as in
   [Compare a new run with the baseline](#compare-a-new-run-with-the-baseline).

6. Write the results into the pull request of the change: the benchmark tables, the smoke summary
   and the outcome of the tests. If you accept a regression, state it in the pull request and in
   the change's `CHANGELOG.md` line, with the issue number (Chapter 8).

#### Results

The change is accepted with known effects on speed and function, and the record of the decision is
in the repository's history.
