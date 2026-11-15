title: Validating the deployment

# Validating the deployment

This chapter confirms that the whole stack works from the workstation, end to end, and records the
performance of your system as a baseline for later comparisons. You run the smoke tests, check
each endpoint by hand, test tool calling and retrieval over your documents, and record a benchmark
baseline. The last topic runs the evaluation suites of `tools/eval.py`, records an evaluation
baseline per model, and compares every later change with it through a regression gate.

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

#### Results

LiteLLM is alive and reaches its database, your key lists the eight names, both API formats
answer, embeddings and reranking work, and an invalid key is refused.

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
    closed on 14 November 2026 by commit `3c31179`). The llama.cpp build of the stack, `b12407`,
    contains that commit (checked in the llama.cpp repository), but the commit changes only the
    Ministral-3 parser and the chat tests, so whether it ends the problem for these models is not
    confirmed. Follow [Tool calls fail or loop](#tool-calls-fail-or-loop).

#### Results

`local-coder` and `local-fast` return a structured `get_weather` call with valid JSON arguments on
the OpenAI route in every run.

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

#### Results

The test document is indexed in the `rag-docs` knowledge base.

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

#### Results

Open WebUI and OpenCode both answer from the planted document and name it as the source.

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
`-c 49152` for fallback B. The llama-bench run uses five repetitions per test (`-r 5`; the default
of `bench.sh` is three), so that one slow run weighs less in each speed.

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

As in that task, list the override in the `overrides` line of `[apps.ai-inference]` in your
desired-state file ([Create your desired-state file](#create-your-desired-state-file)), so that
`tools/deploy.py apply` keeps it. `deploy.py` does not detect a change to the copy: redeploy
`ai-inference` by hand after you change it ([Redeploy one app](#redeploy-one-app)).

### Compare a new run with the baseline

#### Steps

1. Repeat the benchmark tasks of this topic with the same commands. The new files carry the new
   date.

2. Compare the tables of the same run, for example:

        diff /mnt/tank/ai/appdata/benchmarks/<baseline-date>-coder-bench.md \
          /mnt/tank/ai/appdata/benchmarks/<new-date>-coder-bench.md

    The lines that differ show the speeds of both runs.

3. Treat a drop of more than 5% in generation or prompt speed at any depth as a regression to
   explain before you accept the change. This is a manual rule for the engine speeds that
   `bench.sh` measures; the evaluation gate applies its own rule, 15%, to the end-to-end speed of
   the evaluation cases ([Regression gate rules](#regression-gate-rules)). Also compare the
   **GPU MiB used** column of the server-mode runs: less headroom than before can make the model
   fail to load after the next change.

4. When a change is accepted, the new files become the baseline. Keep the old files; they record
   the history of the system.

#### Results

You know whether the change made the stack slower, and by how much.

## Evaluations and the regression gate

A change to the inference settings can make the stack slower or the model worse at its work.
`tools/eval.py` runs fixed evaluation suites from the workstation against the gateway, stores the
outcome in a results file tied to a checksum of the configuration, and compares two results files
with a regression gate. It needs only the Python 3.11 standard library, like `smoke.py`.

### Validation tools in this release

Table: Validation tools

| Tool | What it checks |
|---|---|
| `tools/smoke.py` | Every endpoint, end to end, from the workstation ([Run the smoke tests](#run-the-smoke-tests)) |
| `tools/bench.sh` | Fit in VRAM, GPU memory, prompt and generation speed ([Record a benchmark baseline](#record-a-benchmark-baseline)) |
| Tool-calling and retrieval tests | Structured tool calls on both API formats; retrieval of a planted document (procedures in this chapter) |
| `tools/eval.py` and `evals/` | Model quality on fixed suites: tool calling, output format, small coding tasks, answers from documents; the regression gate |
| `tools/tests/` | Unit tests of the repository's tools, run by `tools/check.sh` and CI; they use no model |

None of the CI jobs runs a model: CI has no GPU. Evaluations run from the workstation, by hand.

### Evaluation suites

Table: Evaluation suites

| Suite | Cases | What a case checks |
|---|---|---|
| `tools` | 20 | A structured tool call with the right name and arguments: single calls, parallel calls, no call when none is needed, nested arguments, and calls that follow a tool result; 13 on the OpenAI route (`/v1/chat/completions`), 7 on the Anthropic route (`/v1/messages`) |
| `format` | 10 | Exact output: JSON with no code fence, exact text, a number of lines, JSON that fits a schema |
| `coding` | 8 | A small Python function, run against hidden unit tests on the workstation |
| `rag` | 6 | Answers from four sample documents placed in the request, with the source file named; one question the documents cannot answer |

Two sets select the cases: `smoke`, a fixed subset of 15 cases from every suite, and `full`, all
44 cases. Each case has a fixed ID, such as `tools-005`, that never changes. The suites are the
files `evals/suites/<suite>.jsonl`, the sets are defined in `evals/sets.toml`, and the sample
documents of the `rag` suite are `evals/rag-docs/eval-*.md`; Appendix E prints the set and gate
files and the sample documents.

How `eval.py` runs:

- **Settings.** As `smoke.py`: `LAB_DOMAIN` and `LOCAL_LLM_KEY` from the environment, then from
  `~/.config/local-agent-stack/client.env` (or the file of `--env-file`). The key must allow the
  models of the run; the `c4dev` key allows all eight names. With the internal CA of Appendix D,
  add `--cafile ~/caddy-root.crt`, as for `smoke.py`.
- **Models.** `--model` names the model of the OpenAI-route cases (default `local-coder`). The
  Anthropic-route cases, which the `tools`, `format` and `coding` suites contain, use
  `local-sonnet` with `local-coder`, `local-haiku` with `local-fast`, and otherwise the same name;
  `--anthropic-model` overrides it.
- **One request at a time.** The server has one slot, so parallel requests only queue and distort
  the timings. A warm-up request per route comes first, so a model swap is not measured.
- **Sampling.** The server's production settings are used unless you pass `--temperature` or
  `--seed` (the seed applies to the OpenAI route only). At the default temperature the answers vary
  from run to run, so a single case can pass in one run and fail in the next.
- **Parallel tool calls.** The OpenAI-route cases `tools-005` and `tools-006` ask for several calls
  in one answer and send `"parallel_tool_calls": true`, because the sources disagree on whether
  llama-server allows parallel calls without it. The Anthropic route has no such field; its parallel
  case is `tools-015`.
- **Coding tests.** The tests run on the workstation, on all cores, each in a temporary directory
  with a 10-second limit (`--test-timeout`); the test process may not open network connections,
  start processes or write outside its directory. The first output line names the protection as
  `coding sandbox audit-hook`, or `netns+audit-hook` when the workstation also allows a private
  network namespace. These rules protect against accidents; the code runs as your user.
- **Results file.** `evals/results/<UTC time>-<model>-<set>.json` in the clone. It records, per
  case, pass, fail or error, a short reason, the latency and the tokens; per suite, the pass rate
  with a 95% interval and the median output tokens per second; and the configuration checksum. It
  holds no prompt, no answer, no key and no domain. A run limited with `--case` is partial: its file
  goes to `build/evals/` and never counts as a baseline.
- **Exit codes.** `0` when the results file was written (and, with `--baseline`, the gate passed),
  `1` when the run stopped or the gate failed, `2` for a usage error, such as a missing
  `LOCAL_LLM_KEY`.

!!! note
    `tools/eval.py` has not yet been run against a deployed stack. It was tested only against a fake
    gateway on the loopback address, with its unit tests. Three behaviours of the real gateway are
    assumed, not verified: that LiteLLM passes `seed` and `parallel_tool_calls` on to llama-server
    on the `openai/` route, and that it passes llama-server's `timings` back. If `seed` does not
    arrive, `--seed` has no effect and two runs with the same seed differ. If `parallel_tool_calls`
    does not arrive, `tools-005` and `tools-006` can fail with `expected 2 call(s) ..., got 1`. If
    `timings` do not arrive, the results file has no `server_tokens_per_s`; the gate does not use
    that figure. [Evaluation issues](#evaluation-issues) lists what to do in each case. Report any
    other problem to the project as an issue, with the output of the run and the results file,
    which holds no key, prompt or answer.

Table: Options of eval.py run

| Option | Meaning |
|---|---|
| `--suite <set>` | The set to run, `smoke` or `full` (required) |
| `--model <name>` | The model of the OpenAI-route cases; default `local-coder` |
| `--anthropic-model <name>` | The model of the Anthropic-route cases; default `local-sonnet` for `local-coder`, `local-haiku` for `local-fast`, otherwise the `--model` name |
| `--case <id>` | Run only this case; repeat it for several. The run is partial and its file goes to `build/evals/` |
| `--baseline <file>` | After the run, compare with this results file; the exit code is the gate's |
| `--gate <file>` | The gate thresholds; default `evals/gate.toml` |
| `--out <file>` | The results file; default `evals/results/<UTC time>-<model>-<set>.json` |
| `--temperature <t>`, `--seed <n>` | Sampling; default the server's settings. The seed applies to the OpenAI route only |
| `--max-tokens <n>` | `max_tokens` of every case; default per suite, 4096, and 8192 for `coding` |
| `--timeout <s>` | Seconds per request; default 600 |
| `--test-timeout <s>` | Seconds per run of a coding case's tests; default 10 |
| `--rag-source <source>` | `bundled` (default): the sample documents in the request; `openwebui`: the passages Open WebUI retrieves ([Evaluate retrieval through Open WebUI](#evaluate-retrieval-through-open-webui)) |
| `--kb-k <n>` | Passages to retrieve with `openwebui`; default 5 |
| `--base-url <url>` | The gateway; default `https://llm.<LAB_DOMAIN>`. Only `https://` is accepted, or `http://` on the loopback address |
| `--webui-url <url>` | Open WebUI, for `openwebui` retrieval; default `https://chat.<LAB_DOMAIN>` |
| `--cafile <file>` | A CA certificate to trust, for the internal CA of Appendix D |
| `--env-file <file>` | A `KEY=value` file read after the environment; default `~/.config/local-agent-stack/client.env` |
| `--no-warmup` | Skip the warm-up request of each route; the first case then can include a model swap in its time |
| `--save-responses <dir>` | Save every raw answer in this directory, for debugging |
| `--jobs <n>` | Coding tests run at the same time; default the `JOBS` environment variable, otherwise the number of cores |
| `--root <dir>` | The repository root; default the clone that holds `eval.py` |

The other commands take fewer options. `compare <baseline> <result>` takes `--gate <file>`;
`verify [<file> ...]` takes `--current` and `--jobs <n>`; `config-hash` takes `--files`; `suites`
takes `--jobs <n>` and `--test-timeout <s>`. Every command takes `--root <dir>`, and
`python3 tools/eval.py <command> --help` lists the options of each.

### Run the smoke evaluation

#### About this task

The smoke set takes a few minutes and tells you whether a change broke tool calling, output format,
coding or answers from documents. Run it after every change to the inference settings, a model file
or the llama.cpp image, after [Run the smoke tests](#run-the-smoke-tests) has passed.

#### Steps

1. On `c4dev`, change to the clone:

        cd ~/local-agent-stack

2. Check that the suites are intact:

        python3 tools/eval.py suites

    Every suite line starts with `ok`, and the last lines read `set smoke: 15 cases` and
    `set full: 44 cases`.

3. Run the smoke set with the agent model:

        python3 tools/eval.py run --suite smoke

    The output has this shape:

        eval: set smoke, 15 cases, model local-coder (Anthropic route: local-sonnet), config <hash>, coding sandbox audit-hook
        warm-up: local-coder (openai) answered in <s> s
        warm-up: local-sonnet (anthropic) answered in <s> s
        [ 1/15] tools-001    pass       <s> s   <n> tok   <n> tok/s  1 call(s) matched
        ...
        [12/15] coding-001   testing    <s> s   <n> tok   <n> tok/s  hidden tests queued
        ...
        tests coding-001   pass    tests passed in <s> s
        suite      cases  pass     rate         95% CI    tok/s   latency
        tools          8     8   100.0%        68-100%      <n>     <s> s
        format         3     3   100.0%        44-100%      <n>     <s> s
        coding         2     2   100.0%        34-100%      <n>     <s> s
        rag            2     2   100.0%        34-100%      <n>     <s> s
        overall       15    15   100.0%        80-100%      <n>     <s> s
        results: /home/<user>/local-agent-stack/evals/results/<UTC time>-local-coder-smoke.json

4. Check that the results file is complete:

        python3 tools/eval.py verify evals/results/<file>.json

    The output starts with `ok`, followed by the file, the set, the model, the passed cases and
    the configuration checksum.

#### Results

The smoke results are stored. A failed case shows `fail` or `error` and its reason; see
[Act on failed evaluation cases](#act-on-failed-evaluation-cases).

### Record an evaluation baseline

#### Prerequisites

- The workstation clone is checked out at the release that the server runs (Chapter 3), with the
  same configuration files.
- [Run the smoke evaluation](#run-the-smoke-evaluation) has passed.

#### About this task

The baseline is the full set's results in a known-good state, one per model. Later runs are
compared with it. Record it after the deployment passes this chapter, and again whenever you accept
a change.

!!! caution
    An evaluation occupies the GPU for its whole run. Run it while no agent or Open WebUI user is
    working.

#### Steps

1. Run the full set:

        python3 tools/eval.py run --suite full

    With `local-coder`, the run takes about 10 to 20 minutes (an estimate; the model thinks before
    it answers).

2. Verify the results files against the configuration of the clone:

        python3 tools/eval.py verify --current

    Each line starts with `ok` and names a results file of this configuration: the full run, and
    the smoke run of the previous task. `--current` requires the results files to carry the
    configuration checksum of the files in the clone.

3. Keep the full run's file as the baseline:

        mkdir -p evals/baselines
        cp evals/results/<file>.json evals/baselines/local-coder-full.json

4. Repeat steps 1 to 3 for the thinking-off model, which runs faster:

        python3 tools/eval.py run --suite full --model local-fast

    Copy its file to `evals/baselines/local-fast-full.json`.

5. If you track your configuration in a repository, commit the results and the baselines with the
   change that produced them (Chapter 8). In a clone that only follows the release tags, the two
   directories stay untracked files, and `git checkout` of a new tag keeps them.

#### Results

Each model has a baseline that later runs are compared with.

### Compare a change with the baseline

#### Prerequisites

- A baseline of the model, from [Record an evaluation baseline](#record-an-evaluation-baseline).
- The workstation clone is checked out at the change: the new release tag, or the branch of the
  change. The results file takes its configuration checksum from the files in the clone, so the
  clone must hold the configuration that the server runs.

#### Steps

1. Deploy the change on the server: a release as in
   [Updating to a new release](#updating-to-a-new-release), or a branch for testing as in step 1
   of [Pass the evaluation gate](#pass-the-evaluation-gate).

2. Run the full set and compare it with the baseline in one command:

        python3 tools/eval.py run --suite full --baseline evals/baselines/local-coder-full.json

    After the run, the output ends with the comparison:

        compare: baseline local-coder full <time> -> result local-coder full <time>
        config: <old hash> -> <new hash>; changed: stack/inference/llama-swap/config.yaml
        suite             baseline          result     change    limit  verdict
        tools         20/20 100.0%    19/20  95.0%    -5.0 pt     5 pt  ok
        format        10/10 100.0%     9/10  90.0%   -10.0 pt     5 pt  FAIL
        coding          8/8 100.0%      8/8 100.0%    +0.0 pt     5 pt  ok
        rag             6/6 100.0%      6/6 100.0%    +0.0 pt     5 pt  ok
        tok/s              <n>             <n>         <n>%      15%  ok
        newly failing: tools-005, format-003
          tools-005: fail: no tool call (finish: stop)
          format-003: fail: not JSON: ```json
        gate: FAIL (1 rule(s) failed)

    The `changed:` list names the configuration files that differ from the baseline. With no
    change, the line reads `config: same (<hash>)`.

3. Confirm the exit code:

        echo $?

    `0` means that the gate passed; `1` means that a rule failed.

4. To compare two existing results files, run:

        python3 tools/eval.py compare evals/baselines/local-coder-full.json evals/results/<file>.json

    The output is the comparison of step 2, with the same exit codes.

#### Results

You know which suites and cases got worse and whether the speed dropped. A failed gate means: find
the cause, or accept the regression in the pull request and in the change's `CHANGELOG.md` line,
with the issue number (Chapter 8), and record a new baseline.

### Regression gate rules

`tools/eval.py compare` reads its thresholds from `evals/gate.toml`:

{{ include evals/gate.toml }}

- **Pass rate.** For each suite, over the cases both files contain, the gate fails when the pass
  rate drops by more than `pass_rate_drop_points` percentage points. One case is 5 points of the
  `tools` suite, 10 of `format`, 12.5 of `coding` and about 16.7 of `rag`, so in the three small
  suites a single newly failing case fails the gate. Run the full set again before you act on a
  single case: answers vary between runs.
- **Speed.** The gate fails when the median output tokens per second, over the cases both files
  contain, drops by more than `tokens_per_second_drop_percent`. The speed is the output tokens over
  the request time, prompt processing included, for answers of 32 tokens or more. The rule applies
  only when both files have at least `min_cases_for_speed` such cases. For the exact engine speed,
  use `tools/bench.sh` ([Compare a new run with the baseline](#compare-a-new-run-with-the-baseline)).
- **Context.** `compare` also reports, in `note:` lines, a different model, sampling or suite
  version, and in the `config:` line a different configuration. It does not fail on them. A `rag`
  suite answered from Open WebUI retrieval is not compared with one answered from the bundled
  documents.

To allow a suite one case of noise, add a section such as `[gate.suites.coding]` with
`pass_rate_drop_points = 12.5`.

### Check the configuration checksum

#### About this task

Every results file carries the SHA-256 checksum of the files that decide its outcome:
`stack/inference/llama-swap/config.yaml`, `stack/inference/litellm/config.yaml`,
`stack/inference/compose.yaml`, `stack/inference/models.sha256`, `evals/sets.toml`, the suite
files and the sample documents. A change to any of them gives a new checksum. `evals/gate.toml` is
not part of it: a threshold changes the verdict, not the results.

#### Steps

1. Display the checksum of the clone and of each file:

        python3 tools/eval.py config-hash --files

    The last line is the checksum; the lines above it give each file's checksum and path.

2. Find and verify a results file for the clone's configuration:

        python3 tools/eval.py verify --current

    Each line starts with `ok`. `FAIL no results file in evals/results/ for configuration <hash>`
    means that no evaluation has been run since the configuration changed.

#### Results

You know whether the stored results belong to the deployed configuration.

### Evaluate retrieval through Open WebUI

#### About this task

By default, the `rag` suite places the sample documents in the request, which tests the model's
answers. This optional task instead answers the questions with the passages that Open WebUI's
knowledge base retrieves, which tests indexing, embedding and reranking too. The sample documents
of `evals/rag-docs/` are fictional and are named `eval-*.md`.

!!! note
    The retrieval request of this task was not tested against a running Open WebUI. If it fails,
    use [Test retrieval over your documents](#test-retrieval-over-your-documents) instead.

#### Steps

1. Copy the four files `evals/rag-docs/eval-*.md` from the clone to the `rag-docs` share, as in
   [Copy documents to the rag-docs share](#copy-documents-to-the-rag-docs-share). Appendix E prints
   them ([Evaluation files](#evaluation-files)).

2. Start a sync and wait for its result, as in [Follow the oikb sync](#follow-the-oikb-sync).

    **Workspace** > **Knowledge** > `rag-docs` in Open WebUI lists the four files.

3. On `c4dev`, add the knowledge base ID (`OIKB_KB_ID` in `rag.env`) and the `kb-reader` user's
   API key (`KB_READER_TOKEN` in `web.env`) to `client.env` as `EVAL_KB_ID` and `EVAL_KB_KEY`,
   without printing them:

        { sed -n 's/^OIKB_KB_ID=/EVAL_KB_ID=/p' ~/.config/local-agent-stack/secrets/rag.env
          sed -n 's/^KB_READER_TOKEN=/EVAL_KB_KEY=/p' ~/.config/local-agent-stack/secrets/web.env
        } >> ~/.config/local-agent-stack/client.env
        grep -c '^EVAL_KB_\(ID\|KEY\)=.' ~/.config/local-agent-stack/client.env

    The output is `2`.

4. Run the six retrieval cases:

        python3 tools/eval.py run --suite full --rag-source openwebui \
          --case rag-001 --case rag-002 --case rag-003 --case rag-004 --case rag-005 --case rag-006

    The summary table has a `rag` row. The results file, under `build/evals/` with a name that ends
    in `-partial.json`, records `"source": "openwebui"` and a `retrieval_hit_rate`: the share of
    questions for which the expected file was among the retrieved passages.

5. Delete the four `eval-*.md` files from the share and start a sync.

6. Remove the two lines from `client.env`:

        sed -i '/^EVAL_KB_\(ID\|KEY\)=/d' ~/.config/local-agent-stack/client.env

#### Results

The retrieval path answers the sample questions. A run with `--case` is partial: it is stored
under `build/evals/` and is not used as a baseline.

### Act on failed evaluation cases

Table: Failed evaluation cases

| Reason | Likely cause | What to do |
|---|---|---|
| `run aborted, no results written: HTTP 401` | The key does not allow a model of the run | Check `LOCAL_LLM_KEY` ([Verify a LiteLLM key](#verify-a-litellm-key)) |
| `run aborted ... cannot reach` | The gateway or the network is down | Run `python3 tools/smoke.py` |
| `no answer within 600 s` | A model swap or a very long answer | Run again with `--timeout 1200` |
| `max_tokens reached before an answer` | The model thought too long | Run the case again; with `--max-tokens 16384` if it repeats |
| `no tool call ...; the text holds a tool call` | The model wrote the call as text | [Tool calls fail or loop](#tool-calls-fail-or-loop) |
| `tests failed: ...` or `the tests timed out after 10 s` | The generated code is wrong or loops | Check the case's reason; repeat the run before you act on one case |
| `not JSON` | The answer had a code fence or extra text | A format regression if it repeats |
| `eval.py: LOCAL_LLM_KEY is not set` or `LAB_DOMAIN is not set` | `client.env` lacks the value | Complete `client.env` (Chapter 7) |
| `verify` prints `FAIL` and `made with configuration ..., the working tree is ...` | The results file belongs to another configuration than the clone | Check out the tag or branch that the results file was made with, or run the evaluation again |

To repeat one case, add `--case <id>` (repeatable). To keep the raw answers for inspection, add
`--save-responses <dir>` with a directory outside the clone, such as `/tmp/eval-responses`; those
files contain the model's answers, so do not commit them.

### Run the regression check

#### About this task

Check a change with the tools of this release. Chapter 10 applies this check to model changes in
its evaluation gate ([Pass the evaluation gate](#pass-the-evaluation-gate)).

#### Steps

1. Deploy the change on the server, as Chapter 10 describes for releases and model changes, and
   check out the same tag or branch in the workstation clone.

2. From the workstation, run the smoke tests:

        python3 tools/smoke.py

    The last line starts with `smoke: 8 passed, 0 failed`.

3. Run the full evaluation set and compare it with the baseline, as in
   [Compare a change with the baseline](#compare-a-change-with-the-baseline). The last line reads
   `gate: pass`.

4. Run [Test tool calling](#test-tool-calling), including a real agent session.

5. Run [Test retrieval over your documents](#test-retrieval-over-your-documents).

6. Benchmark the changed configuration and compare it with the baseline, as in
   [Compare a new run with the baseline](#compare-a-new-run-with-the-baseline).

7. Write the results into the pull request of the change: the benchmark tables, the smoke summary,
   the `compare` output and the outcome of the tests. Commit the new results file from
   `evals/results/` with the change. If you accept a regression, state it in the pull request and
   in the change's `CHANGELOG.md` line, with the issue number (Chapter 8).

#### Results

The change is accepted with known effects on speed and function, and the record of the decision is
in the repository's history.
