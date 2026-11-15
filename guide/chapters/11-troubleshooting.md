title: Troubleshooting

# Troubleshooting

This chapter helps you find and fix problems with the stack. Start by collecting the diagnostics:
most problems show up in a container's health, its log or the end-to-end checks. Then look up the
symptom in the table of the affected component. The last topic explains the problems that need
more than one step to fix.

Run TrueNAS commands in **System** > **Shell** or in an SSH session as `truenas_admin`, and
workstation commands in the workstation clone, `~/local-agent-stack`. Commands that start with
`sudo` prompt for the `truenas_admin` password.

## Collecting diagnostics

Collect the same information every time, before you change anything. It shows which component
fails, and it is what an issue report needs.

### Collect the server diagnostics

#### About this task

The commands write one file per item into a new directory in the home directory of
`truenas_admin`, then pack the directory. None of them prints a secret value, but container logs
can contain request details: review them before you share them, as described in
[Remove secrets before you share diagnostics](#remove-secrets-before-you-share-diagnostics).

#### Steps

1. Create the directory and refresh the `sudo` credentials:

        D=~/diag-$(date +%Y%m%d-%H%M)
        mkdir -p "$D"
        sudo -v

2. Record the versions, the GPU and the release of the clone:

        midclt call system.version > "$D/truenas-version.txt"
        nvidia-smi > "$D/nvidia-smi.txt" 2>&1
        midclt call docker.config > "$D/docker-config.json"
        git -C /mnt/tank/ai/stacks/local-agent-stack describe --tags --always > "$D/release.txt"
        git -C /mnt/tank/ai/stacks/local-agent-stack status --porcelain >> "$D/release.txt"

3. Record the containers, the network, the memory and the datasets:

        sudo docker ps -a --format '{{.Names}} {{.Image}} {{.Status}}' > "$D/containers.txt"
        sudo docker stats --no-stream > "$D/stats.txt"
        sudo docker network inspect ai-net --format '{{range .Containers}}{{println .Name}}{{end}}' > "$D/ai-net.txt"
        cat /sys/module/zfs/parameters/zfs_arc_max > "$D/arc-max.txt"
        head -n 5 /proc/meminfo > "$D/memory.txt"
        sudo zfs list -r -o name,used,avail,mountpoint tank/ai > "$D/datasets.txt"

4. Save the last two hours of every container's log:

        for c in llama-swap litellm litellm-db pgvector docling oikb open-webui searxng mcp-hub caddy gpu-exporter; do sudo docker logs --since 2h "$c" > "$D/$c.log" 2>&1; done

5. Save the TrueNAS logs that concern the apps and the driver:

        sudo tail -n 300 /var/log/app_lifecycle.log > "$D/app_lifecycle.log"
        sudo dmesg | grep -i nvrm > "$D/dmesg-nvrm.txt"
        sudo journalctl -u middlewared --since "2 hours ago" > "$D/middlewared.log"

6. Pack the directory:

        tar -C ~ -czf "$D.tar.gz" "$(basename "$D")"
        ls -l "$D.tar.gz"

#### Results

`~/diag-<date>.tar.gz` holds the server diagnostics. Copy it to the workstation with
`scp truenas_admin@192.0.2.10:diag-*.tar.gz .`.

!!! warning
    Do not add the output of `docker inspect` or `docker compose config` to the diagnostics: both
    print the containers' environment, which holds the keys and database passwords. Never add a
    file from `/mnt/tank/ai/secrets`.

### Collect the workstation diagnostics

#### Steps

1. Run the end-to-end checks and save the result:

        cd ~/local-agent-stack
        python3 tools/smoke.py > ~/diag-smoke.txt 2>&1; echo "exit $?" >> ~/diag-smoke.txt

2. Record the state of the server as `deploy.py` sees it:

        ~/.local/share/local-agent-stack/deploy-venv/bin/python tools/deploy.py --file ~/.config/local-agent-stack/desired.toml status > ~/diag-deploy.txt 2>&1

3. Record name resolution and the certificate of the gateway:

        getent hosts chat.lab.example.com llm.lab.example.com models.lab.example.com mcp.lab.example.com search.lab.example.com > ~/diag-dns.txt
        echo | openssl s_client -connect llm.lab.example.com:443 -servername llm.lab.example.com 2>/dev/null | openssl x509 -noout -subject -issuer -enddate >> ~/diag-dns.txt

4. Record the client versions and the MCP connections:

        { opencode --version; opencode mcp list; } > ~/diag-opencode.txt 2>&1

5. If the problem concerns the answers of a model, copy the newest evaluation results file
   (Chapter 9):

        cp "$(ls -t ~/local-agent-stack/evals/results/*.json | head -n 1)" ~/diag-eval.json

#### Results

The `~/diag-*` files hold the workstation's view of the stack. `smoke.py` and `deploy.py` never
print keys, and an evaluation results file holds no prompt, answer, key or domain.

### Remove secrets before you share diagnostics

The repository is public, and so are its issues and discussions. Before you attach any
diagnostics, search them for keys and tokens, and replace every private value with the guide's
placeholders: `192.0.2.10` for the server, `lab.example.com` for your domain, `sk-local-...` for a
key.

```
tar -xzf diag-<date>.tar.gz
grep -rIl -e 'sk-' -e 'Bearer ' -e 'api_key' diag-<date> ~/diag-*
```

Open every file that the second command lists and remove the values. Also replace your domain
and LAN addresses throughout.

## Troubleshooting deployment issues

Each table lists a symptom, its cause and the resolution. Where a resolution needs several steps,
it points to [Common problems and solutions](#common-problems-and-solutions).

Where a resolution changes an environment file and redeploys the app, change your copy on the
workstation, install it on the server as in
[Copy the environment files to TrueNAS](#copy-the-environment-files-to-truenas), and run
`deploy.py apply` ([Apply the release](#apply-the-release)), which recreates the app and records the
file's new checksum. A redeploy by hand works as well; the next `deploy.py plan` then reports
`update` for the app until you run `apply`.

### GPU and driver issues

Table: GPU and driver problems

| Symptom | Cause | Resolution |
|---|---|---|
| **Install NVIDIA Drivers** is missing from **Apps** > **Installed** > **Configuration** > **Settings** | TrueNAS detected no NVIDIA GPU, the GPU is isolated, or the debug kernel is on | Remove the GPU from **System** > **Advanced Settings** > **Isolated GPU Device(s)**, and turn off the debug kernel under **System** > **Advanced Settings** > **Kernel** |
| `nvidia-smi` reports that no devices were found | The driver did not load | Clear **Install NVIDIA Drivers**, click **Save**, select it again and click **Save**. Then read the `NVRM` lines of the kernel log and the middleware log (step 5 of [Collect the server diagnostics](#collect-the-server-diagnostics)) |
| A container does not start, with an error that names `NVIDIA_REQUIRE_CUDA` or `cuda>=` | The image needs a newer CUDA version than the driver's 13.0 | Use a tag built on CUDA 12.x or 13.0. Never use llama.cpp `server-cuda13` or llama-swap `unified-cuda13` images |
| `nvidia-smi` lists processes of a container that should not use the GPU | The image sets `NVIDIA_VISIBLE_DEVICES=all`, and `nvidia` is TrueNAS's default Docker runtime | Set `NVIDIA_VISIBLE_DEVICES: void` in that service's environment |
| `nvidia-smi` lists `llama-server` processes for `embed` or `rerank` | The CPU-only models created a CUDA context. The stack sets `CUDA_VISIBLE_DEVICES=-1` for them to prevent this; that it does was not verified | Each such context costs about 0.3 GiB of VRAM (estimate). If `coder` no longer fits, open an issue with the `nvidia-smi` output |
| Persistence mode reads `Disabled` after a restart | The Post Init command is missing, disabled or timed out | In **System** > **Advanced Settings** > **Init/Shutdown Scripts**, check `GPU persistence mode`: **When** `Post Init`, **Enabled**, **Timeout** `120` |
| The power limit is back at the default after a restart | The Post Init command does not end with `nvidia-smi -pl <watts>` | Add it to the command, as in [Cap the GPU power limit](#cap-the-gpu-power-limit) |
| The GPU worked before a TrueNAS update and not after | The update changed the driver, or the setting did not carry over | Run [Check the stack after a TrueNAS update](#check-the-stack-after-a-truenas-update) |

!!! caution
    Never replace `/usr/share/truenas/sysext-extensions/nvidia.raw` with another driver build, as
    some community scripts do. Systems changed this way have needed a fresh installation of the
    boot device.

### Inference issues

Table: Model loading and memory

| Symptom | Cause | Resolution |
|---|---|---|
| `coder` does not load; the `llama-swap` log shows an out-of-memory or allocation error | The weights, the 64K KV cache and the MTP draft do not fit, or another process holds VRAM | See [The model runs out of GPU memory at load](#the-model-runs-out-of-gpu-memory-at-load) |
| `coder-moe` does not load with an out-of-memory error | Too many expert layers stay on the GPU | Raise `--n-cpu-moe` by 2 (from 16 to 18): on the server with the override copy that the Results of [Tune and record the fast profile](#tune-and-record-the-fast-profile) describe, and for good in `stack/inference/llama-swap/config.yaml` through a pull request. With 14, the model overflowed VRAM in the published measurement |
| `llama-swap` does not start; its log reports a configuration error | `LLAMA_SWAP_API_KEY` is not set (the configuration refers to it), or `config.yaml` has a YAML error | Check `/mnt/tank/ai/secrets/inference.env`, and that the TrueNAS clone has no local changes (`git status --porcelain`) |
| The log says the model file cannot be opened | The file is missing from `/mnt/tank/ai/models/gguf/` or its name differs | Compare `ls -l /mnt/tank/ai/models/gguf/` with the `-m` lines of the configuration; download the file as in [Download a model file](#download-a-model-file) |
| A model never becomes ready, and requests fail after about ten minutes | Loading took longer than `healthCheckTimeout` (600 seconds), or `llama-server` stopped during start-up | Read the `llama-swap` log for the `llama-server` error. A first load from a cold disk cache is the slowest |
| The first request after a restart takes a minute or more | `llama-swap` loads `coder` from disk at start | Wait. The `/running` command of [Monitor the model server](#monitor-the-model-server) shows `ready` when the model is loaded |
| A request for `local-coder-moe` takes tens of seconds, and the next request of another client is slow too | The two GPU models share the `llm` group: each switch unloads one and loads the other | Switch profiles for a whole working session, not per request |
| `llama-swap` restarts under load, and `sudo docker inspect --format '{{.State.OOMKilled}}' llama-swap` prints `true` | The container reached its 32 GiB memory limit. The peak of about 18 GiB for `coder-moe` is an estimate | Lower `--cache-ram` of the model, or raise the limit in `stack/inference/compose.yaml` within the system RAM budget, through a pull request |

Table: Generation speed

| Symptom | Cause | Resolution |
|---|---|---|
| Every turn takes as long as the first, and the log shows "Forcing full prompt re-processing" | The harness changed earlier messages, which the model's hybrid layers cannot roll back | See [Every turn re-processes the whole prompt](#every-turn-re-processes-the-whole-prompt) |
| Requests wait before they start | `coder` runs one slot (`-np 1`); concurrent requests queue | Run at most two to three agents at the same time |
| Generation of `coder-moe` falls to a few tokens per second after hours | The expert weights in RAM were evicted | Keep `-lm none` in its command, check the ARC cap (`cat /sys/module/zfs/parameters/zfs_arc_max`), and keep the container's memory limit above the experts plus `--cache-ram` |
| Generation is slower than the benchmark of [Measure the model with bench.sh](#measure-the-model-with-benchsh) | A power limit, the other GPU model, or a second client | Check `nvidia-smi --query-gpu=power.limit,power.default_limit --format=csv`, the `/running` list, and the other clients |
| Reranking takes more than ten seconds per question | Reranking 20 chunks on the CPU takes about 3 to 8 seconds (estimate); the CPU backend may not use AMX | Check the CPU backend line ([Monitor the model server](#monitor-the-model-server)). Rerank fewer candidates (`RAG_TOP_K`, set in Open WebUI's **Documents** settings), or move the reranker to the GPU (Appendix B) |

Table: Tool calls and chat templates

| Symptom | Cause | Resolution |
|---|---|---|
| Tool calls fail, loop or come back malformed | Several causes | See [Tool calls fail or loop](#tool-calls-fail-or-loop) |
| Tool calls come back as plain text | The model was started without `--jinja` | Keep `--jinja` in every model's command |
| Tool calling became worse after a change of the KV cache type | The KV cache is quantized below `q8_0` | Keep `-ctk q8_0 -ctv q8_0` or larger |
| The client shows no reasoning, or shows it as part of the answer | `--reasoning-format deepseek` returns the reasoning in the `reasoning_content` field | Use a client that reads `reasoning_content`; OpenCode does |

### LiteLLM gateway issues

Table: LiteLLM problems

| Symptom | Cause | Resolution |
|---|---|---|
| `litellm-db` stops on its first start with a permission error on its data directory, and `litellm` never starts | The PostgreSQL entrypoint changes the mode of `PGDATA` to 0700, which the NFSv4 ACL of the **Apps** preset may refuse (not verified); `litellm` waits for a healthy database | While the dataset holds no data, follow [Recreate the litellm-db dataset with the Generic preset](#recreate-the-litellm-db-dataset-with-the-generic-preset) |
| Every client fails, and `curl -sS https://llm.lab.example.com/health/liveliness` does not print `"I'm alive!"`, while `llama-swap` is healthy | `litellm` or `litellm-db` is down | Read their logs and find the cause in this table. The stack has no fallback route for clients: llama-swap at `https://models.lab.example.com` serves the OpenAI `/v1` routes and the Anthropic `/v1/messages` route itself, but only with `LLAMA_SWAP_API_KEY`, the administrator key, and without per-key model lists, budgets or usage logs. Never give that key to a client; use the host only to check that the models answer, as in step 3 of [Check the chat, models, MCP and search host names](#check-the-chat-models-mcp-and-search-host-names) |
| `coder-moe` loads although nobody asked for it, and `coder` is swapped out | Something calls `GET /health` on LiteLLM | See [LiteLLM health checks swap the GPU model](#litellm-health-checks-swap-the-gpu-model) |
| Requests fail with HTTP 401 | The key is missing, wrong or deleted | Use a LiteLLM virtual key for the client (`LOCAL_LLM_KEY` on the workstation), never the master key |
| Requests for one model name fail while others work | The key's model list does not include the name | Add the name to the key, as in [Make the model available to clients](#make-the-model-available-to-clients) |
| A key stops working after heavy use | Its budget is used up. Each GPU model costs 0.0001 per second of request time, so the budget is a GPU-time quota | Raise the key's budget or create a new key |
| `litellm` does not start, and the log names the master key | `LITELLM_MASTER_KEY` is empty or a known unsafe value | Set a generated value in `inference.env` and redeploy `ai-inference` |
| `litellm` does not start with a database authentication error | `LITELLM_DB_PASSWORD` differs from the password `litellm-db` was created with; PostgreSQL uses the variable only when it creates the database | Put the original value back from the `tank/ai/secrets` snapshots (Appendix A), or set the role's password to the value in `inference.env`, as in [Set the LiteLLM database password again](#set-the-litellm-database-password-again) |
| LiteLLM cannot read credentials it stored earlier | `LITELLM_SALT_KEY` changed | Put the original value back from the `tank/ai/secrets` snapshots. Never change this key |
| `litellm` is unhealthy for up to two minutes on its first start | It runs its database migrations | Wait; the health check allows 120 seconds |
| A streamed answer ends with an error event although the request returned status 200 | LiteLLM sends keep-alive comments every 30 seconds, so the status is 200 before the model answers; a later failure arrives inside the stream | Read the `litellm` and `llama-swap` logs for the error |
| Requests end after 15 minutes | The request time-out is 900 seconds | Split the task, or shorten the prompt |
| Claude Code requests fail with "Extra inputs are not permitted" | A newer Claude Code sends request fields the gateway rejects | Set `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`, and pin the Claude Code version you tested |
| Claude Code requests fail over `output_config` | A Claude Code name routes through an `openai/` model | Keep `local-opus`, `local-sonnet` and `local-haiku` on the `anthropic/` route, as the stack ships them |

### RAG issues

Table: PostgreSQL and pgvector problems

| Symptom | Cause | Resolution |
|---|---|---|
| `pgvector` stops on its first start with a permission error on its data directory | The entrypoint changes the mode of `PGDATA` to 0700, which the NFSv4 ACL of the Apps preset may refuse (not verified) | While the dataset holds no data, follow [Recreate the pgvector dataset with the Generic preset](#recreate-the-pgvector-dataset-with-the-generic-preset) |
| The `open-webui` log shows `password authentication failed for user "openwebui"` | `PG_PASSWORD` differs between `rag.env` and `web.env`, or changed after the database was created | See [Change the Open WebUI database password](#change-the-open-webui-database-password) |
| `open-webui` does not start and cannot reach `pgvector` | `ai-rag` is not running | Start `ai-rag` first; Open WebUI cannot start without its database |
| The `vector` extension is missing in `pgvector` | Open WebUI creates it on its first start | Start `ai-web` once |

Table: Docling problems

| Symptom | Cause | Resolution |
|---|---|---|
| A large PDF never appears in the knowledge base; the `docling` log shows a time-out | The conversion on the CPU took longer than `DOCLING_SERVE_MAX_SYNC_WAIT` (600 seconds) | Split the document, or raise the value in `stack/rag/compose.yaml` through a pull request |
| `docling` restarts during large conversions | It reached its 8 GB memory limit with two workers | Split the document, or copy large documents to the share one at a time. The limit and the two workers are sized for the 64 GB minimum of Chapter 2 ([System RAM budget](#system-ram-budget)); raise the limit only within that budget, through a pull request |
| Uploads fail, and the `docling` log shows rejected requests without a valid key | Open WebUI sends another `DOCLING_API_KEY` than `docling` expects. Open WebUI stored the key on its first start | Enter the value from `rag.env` in Open WebUI's **Documents** settings; see [Open WebUI ignores changed environment variables](#open-webui-ignores-changed-environment-variables) |

Table: Knowledge sync problems

| Symptom | Cause | Resolution |
|---|---|---|
| The `oikb` log shows a failed sync every 15 minutes | `OIKB_TOKEN` or `OIKB_KB_ID` is not set yet | Create the `indexer` key and the knowledge base in Open WebUI, put both values into `rag.env`, and redeploy `ai-rag` |
| `oikb` cannot read `/data/docs` | The `apps` group has no Read entry in the ACL of `rag-docs` | Add it as in [Give the apps group read access to rag-docs](#give-the-apps-group-read-access-to-rag-docs) |
| `oikb` cannot write its history | `tank/ai/appdata/oikb` is not writable by UID and GID 568 | Create the dataset with the **Apps** preset, which grants the `apps` group Modify |
| `oikb` uploads the same files on every run | Files that Open WebUI rejects (size or extension) fail on every run; files uploaded before Open WebUI 0.9.6 are replaced once | Exclude rejected files in the `filter` of `stack/rag/oikb/oikb.yaml` through a pull request |
| A new document does not appear yet | `oikb` syncs every 15 minutes | Wait, or start a sync as in [Start a knowledge sync now](#start-a-knowledge-sync-now) |
| Answers ignore the documents after a change of the embedding model | The index holds vectors of the old model | Reindex, as in [Change the embedding or reranker model](#change-the-embedding-or-reranker-model) |
| Reranking fails | The reranker URL lacks `/v1/rerank`, or an input is longer than the reranker's `-ub` (4,096 tokens) | Use `http://litellm:4000/v1/rerank` in Open WebUI's **Documents** settings, and keep chunks well below 4,096 tokens |

### Web app issues

Table: Open WebUI problems

| Symptom | Cause | Resolution |
|---|---|---|
| A changed variable in `web.env` or `compose.yaml` has no effect | Open WebUI keeps most settings in its database after the first start | See [Open WebUI ignores changed environment variables](#open-webui-ignores-changed-environment-variables) |
| Sign-in fails or the browser reports a cross-origin error | Open WebUI accepts only `https://chat.lab.example.com` (`CORS_ALLOW_ORIGIN`, secure session cookie) | Open it by that name, never by IP address or another name |
| Every user is signed out, and MCP connections fail with "Error decrypting tokens" | `WEBUI_SECRET_KEY` changed | Put the original value back from the `tank/ai/secrets` snapshots and redeploy `ai-web`. Never change this key |
| New users cannot sign up | Sign-up is closed after the first account (`ENABLE_SIGNUP=false`) | The administrator creates users in **Admin Panel** > **Users** > **Add User** |
| The model selector is empty or lacks names | The key in **Admin Panel** > **Settings** > **Connections** does not allow the names | Allow the names in that LiteLLM key, or enter a key that allows them |
| Open WebUI is stuck loading after a tool server was added | The server was added as type OpenAPI | Disable it in **Admin Panel** > **Settings** > **Integrations** and add it again as type **MCP (Streamable HTTP)** |
| "Failed to connect to MCP server" in Open WebUI | Bearer authentication with an empty key, an empty **Function Name Filter List**, or a slow start of the server | Enter `MCP_HUB_TOKEN` as the key, put `,` in the filter list, or raise `MCP_INITIALIZE_TIMEOUT` |

Table: SearXNG problems

| Symptom | Cause | Resolution |
|---|---|---|
| Web search fails, and the `open-webui` log shows HTTP 403 from SearXNG | `json` is missing from `search.formats` | See [SearXNG answers 403 to JSON requests](#searxng-answers-403-to-json-requests) |
| Web search returns no results | Upstream engines are suspended for an hour after a CAPTCHA | Read the `searxng` log for suspended engines, wait, or enable more engines in `stack/web/searxng/settings.yml` through a pull request |
| `searxng` does not start and refers to its secret | `SEARXNG_SECRET` is empty or SearXNG's built-in value | Set a generated value in `web.env` and redeploy `ai-web` |
| Wikipedia, Wikidata and OpenStreetMap results are missing | `SEARXNG_CONTACT_URL` is empty; those engines require it | Set it in `web.env` to a `mailto:` address or a web page, and redeploy `ai-web` |
| `searxng` logs an ownership warning at start | The configuration is a read-only mount, and `FORCE_OWNERSHIP` is `false` | None; the warning is expected |

Table: MCP hub problems

| Symptom | Cause | Resolution |
|---|---|---|
| The hub answers HTTP 401 | The bearer token is missing or wrong | See [The MCP hub answers 401 or 421](#the-mcp-hub-answers-401-or-421) |
| The hub answers HTTP 421 | The request's Host header is not `mcp-hub:8096` | See [The MCP hub answers 401 or 421](#the-mcp-hub-answers-401-or-421) |
| `mcp-hub` is unhealthy | One of `searxng`, `fetch` or `kb` did not start | Run `sudo docker exec mcp-hub mcp-hub-healthcheck`; it prints `unhealthy:` and the failed servers. Read the `mcp-hub` log |
| The `kb` tools fail with an authentication error | `KB_READER_TOKEN` is empty or wrong | Create the `kb-reader` key in Open WebUI, put it into `web.env`, and redeploy `ai-web` |
| The `mcp-hub` log shows "Failed to parse JSONRPC message" | The `kb` server prints start-up lines; the image moves them to standard error | None, as long as the health check prints `ok: fetch, kb, searxng` |
| The `fetch` tool refuses an address | It refuses private, loopback and link-local addresses and honours `robots.txt` | None; this is by design |
| Installing `ai-web` fails at `mcp-hub` | The image `ghcr.io/corytron/local-agent-stack-mcp-hub` could not be pulled, and building it from `stack/web/mcp-hub/` on TrueNAS failed (that build was not tested on TrueNAS) | Read `/var/log/app_lifecycle.log` for the pull or build error, then follow [Build or pull the MCP hub image](#build-or-pull-the-mcp-hub-image) |

### Edge app issues

[Certificate issuance errors](#certificate-issuance-errors) lists the messages of the Caddy log
with their causes as well.

Table: Certificate problems

| Symptom | Cause | Resolution |
|---|---|---|
| `caddy` stops with `File to import not found: dns-<name>` | `DNS_PROVIDER` is not one of `cloudflare`, `route53`, `digitalocean`, `porkbun`, `namecheap`, `duckdns`, `desec` and `ovh` | Correct `DNS_PROVIDER` in `edge.env` and redeploy `ai-edge` |
| `caddy` does not start and reports the Cloudflare token | `DNS_PROVIDER_TOKEN` still holds the placeholder; the module checks the token's shape | Put the real token into `edge.env` |
| Issuance fails with `expected 1 zone, got 0` or `timed out waiting for record to fully propagate` | Local DNS answers for your domain and hides the public zone (split-horizon DNS) | See [Certificates are not issued](#certificates-are-not-issued) |
| Issuance fails with an authentication or permission error from the DNS provider | The token lacks a permission or the zone | See [Certificates are not issued](#certificates-are-not-issued) |
| Browsers report an untrusted certificate whose issuer contains "STAGING" | `ACME_CA` still points to Let's Encrypt's staging service | Remove the `ACME_CA` line from `edge.env` and redeploy `ai-edge`; Caddy then obtains a production certificate |
| Issuance fails with a rate-limit error | Too many failed attempts against the production service | Set the staging `ACME_CA` until issuance works, then remove it |
| `caddy` logs permission errors for `/data` or `/config` | `/mnt/tank/ai/appdata/caddy/data` or `/config` is missing or not writable by UID 568 | Create them as in [Prepare the Caddy data directories](#prepare-the-caddy-data-directories), and redeploy `ai-edge` |
| Pulling `ghcr.io/corytron/local-agent-stack-caddy` is denied | The container package is private | Make the package public on GitHub (**Package settings** > **Danger Zone** > **Change visibility** > **Public**) |
| `tools/smoke.py --only tls` reports fewer than seven days left | Renewals fail | Read the `caddy` log; check that the DNS token still exists and still has its permissions |

Table: Name resolution and connection problems

| Symptom | Cause | Resolution |
|---|---|---|
| A lab name does not resolve on a client (`getent hosts chat.lab.example.com` prints nothing) | The local DNS server has no A record for it | Add A records for `chat`, `llm`, `models`, `mcp` and `search` under your domain, all pointing to `192.0.2.10` |
| A lab name resolves to another address | The client uses a resolver without the local records | Point the client at your local DNS server |
| The connection is closed without any HTTP answer | The client's address is outside `EDGE_ALLOWED_CIDRS` (by default the private ranges), or the name is not one of the five lab names | Set `EDGE_ALLOWED_CIDRS` in `edge.env` to your LAN, for example `192.0.2.0/24`, and redeploy `ai-edge`; use the five names only |
| `ai-edge` does not start because ports 80 or 443 are in use | The TrueNAS web interface still uses them | Move it as in [Change the web interface ports](#change-the-web-interface-ports) |
| Long answers stop after five minutes in Claude Code | Claude Code gives up after 300 seconds without data | LiteLLM's keep-alive comments every 30 seconds prevent this; check that `sse_keepalive_ping_interval_seconds: 30` is in `stack/inference/litellm/config.yaml` of the running release |

### Workstation issues

Table: OpenCode and the endpoint

| Symptom | Cause | Resolution |
|---|---|---|
| `opencode: command not found` | The shell profile block is not loaded yet | Open a new terminal. If the problem stays, check that `~/.bashrc` (or `~/.zshrc`) holds the block that starts with `# >>> local-agent-stack` |
| OpenCode cannot reach `https://llm.<domain>` | `LAB_DOMAIN` is unset or still the placeholder | Check `echo $LAB_DOMAIN`, then edit `~/.config/local-agent-stack/client.env` and open a new terminal |
| OpenCode gets HTTP 401 | `LOCAL_LLM_KEY` is the placeholder or wrong | Put your LiteLLM virtual key into `client.env`; test it with `curl -s -H "Authorization: Bearer $LOCAL_LLM_KEY" https://llm.$LAB_DOMAIN/v1/models` |
| `opencode models` lists no `local/` model | OpenCode cannot reach the gateway, or the key allows none of the names | Run the `curl` test above; it lists the names the key allows |
| Requests overflow the 64K window, or compaction never starts | The model's context is not declared | Keep `limit.context` at 65536 in `opencode.jsonc`, as the stack ships it |
| OpenCode warns about a second configuration file | An `opencode.json` sits next to the linked `opencode.jsonc` | Run `clients/install.sh` again; it moves the file aside |

Table: TLS trust on clients

| Symptom | Cause | Resolution |
|---|---|---|
| Certificate errors name an issuer with "STAGING" | Caddy still uses Let's Encrypt staging | Remove `ACME_CA` from `edge.env` and redeploy `ai-edge` |
| Certificate errors with the internal CA of Appendix D | The client does not trust the Caddy root | Install the root and set `NODE_EXTRA_CA_CERTS`, as in [Certificates from the internal CA](#certificates-from-the-internal-ca) |
| The browser trusts the site, but a command-line tool does not | Node.js and Python tools can use their own trust store | Set `NODE_EXTRA_CA_CERTS` for Node.js tools such as Claude Code, `REQUESTS_CA_BUNDLE` for Python `requests`, and run `tools/smoke.py --cafile <root.crt>` |
| The certificate names another host | The name is not under your lab domain, or it resolves to another server | Use the five lab names; check the address with `getent hosts` |

Table: MCP tools and the SSH tool

| Symptom | Cause | Resolution |
|---|---|---|
| `opencode mcp list` shows `searxng`, `fetch` or `kb` as failed | `MCP_HUB_TOKEN` in `client.env` differs from `web.env`, or the hub is unhealthy | Copy the value from `/mnt/tank/ai/secrets/web.env` into `client.env`; check the hub as in [The MCP hub answers 401 or 421](#the-mcp-hub-answers-401-or-421) |
| `opencode mcp list` shows `ssh` as disabled | The SSH tool is off until you enable it in a project | Write its policy file and enable it as in [Enable the SSH tool in a project](#enable-the-ssh-tool-in-a-project) |
| `ssh-mcp-stdio: ... not found; run clients/install.sh (needs Node.js 20.6 or newer)` | ssh-mcp is not installed | Install Node.js 20.6 or later and npm, then run `clients/install.sh` again |
| ssh-mcp refuses to start | Its policy file is readable by others, or its directory is | `chmod 600` the file and `chmod 700` its directory (`~/.config/ssh-mcp/`, or `~/Library/Application Support/ssh-mcp/` on macOS) |
| Every SSH call to a host is refused | The host has no profile, or its key is not pinned; the launcher runs ssh-mcp in strict host-key mode | Add the profile and pin the host key, as in [Pin the host key and edit the policy](#pin-the-host-key-and-edit-the-policy) |
| Destructive commands are refused without a question | The policy refuses them unless the profile asks for approval | Set `approvalPolicy = "ask-destructive"` on the profile, and approve each command in OpenCode |

Table: Claude Code through the gateway

| Symptom | Cause | Resolution |
|---|---|---|
| `claude-local: set LAB_DOMAIN in ...` or `set LOCAL_LLM_KEY in ...` | `client.env` lacks the value | Edit `~/.config/local-agent-stack/client.env` |
| `claude-local: Claude Code (claude) is not installed` | Claude Code is missing | Install Claude Code, at the version you tested |
| Claude Code compacts far too late and requests overflow | It assumes a 1,000,000-token window for unknown model names | Start it through `claude-local`, which sets `CLAUDE_CODE_MAX_CONTEXT_TOKENS=65536` |
| WebSearch, Remote Control or fast mode do not work | These need Anthropic's servers | Use the SearXNG MCP server for search; the others are unavailable |

### deploy.py issues

Table: deploy.py problems

| Symptom | Cause | Resolution |
|---|---|---|
| `truenas_api_client is not installed in this Python` | `deploy.py` runs with another Python than the virtual environment | Run it with `~/.local/share/local-agent-stack/deploy-venv/bin/python` |
| `... truenas.toml does not exist: write it as tools/deploy.py's docstring shows (mode 0600)` | The connection settings are missing | Create them as in [Create the connection settings](#create-the-connection-settings) |
| `uri must start with wss://` | The address uses `ws://` or `https://` | Use `wss://192.0.2.10:8443/api/current`; TrueNAS revokes a key sent over plain HTTP or `ws://` |
| `API key file ... is readable by others` or `belongs to another user` | The key file's mode or owner | `chmod 600` the file; keep it in your own home directory |
| `login as deploy-read failed` | The key is wrong or was revoked; TrueNAS revokes a key that was sent unencrypted | Create a new key, as in [Create the API keys and store them on the workstation](#create-the-api-keys-and-store-them-on-the-workstation) |
| `cannot connect to the NAS:` followed by a certificate error | `truenas-ca.pem` is not the certificate the web interface presents, or the certificate does not name the address in `uri` | Repeat [Create the connection settings](#create-the-connection-settings). If the certificate names only a host name, set `uri` to that name and make it resolve to `192.0.2.10`; or run `deploy.py --local` on TrueNAS, which needs no certificate |
| `the NAS reports TrueNAS '...', deploy/truenas.toml says '...'` | TrueNAS was updated | Read the release notes for API changes, then set `truenas_version` in your desired-state file |
| `note: files not compared: tag ... is not in this clone (git fetch --tags)`, and the same for the images | The clone lacks the release tag | Run `git -C ~/local-agent-stack fetch --tags` |
| `note: images not compared: cannot run docker: ...` or `docker compose config failed` | The Docker CLI with the Compose plugin is missing on the machine that runs `deploy.py` | Install it as in steps 1 to 4 of [Install the TrueNAS API client on the workstation](#install-the-truenas-api-client-on-the-workstation). Without it, `plan` and `drift` never see an image update; the YAML, the hashes and the app states are still compared |
| `note: env file not compared: cannot read ~/.config/local-agent-stack/secrets/<stack>.env` | Your copy of the environment file is missing, or `env_dir` names another folder | Restore the copy from the server's file, or correct `env_dir` in your desired-state file |
| `note: env file not compared: env_dir is not set in the desired state` | Your desired-state file has no `env_dir` line | Add `env_dir = "~/.config/local-agent-stack/secrets"`, as in [Create your desired-state file](#create-your-desired-state-file) |
| `plan` reports `update (RUNNING) no hash of the files of stack/<stack>/ recorded (installed by hand?)` | The app was installed by hand from `truenas-app.yaml` and has no content hashes yet | [Record the content hashes](#record-the-content-hashes) |
| `apply` reports `<app>: FAILED: app.update:` with `Invalid compose configuration` for every app | The Compose version of TrueNAS refused the `x-local-agent-stack` block that holds the content hashes; nothing changed on the server | Do not repeat the apply; follow [Update the apps without content hashes](#update-the-apps-without-content-hashes) |
| `plan` reports `update ... its env file differs from the one hashed at the last apply`, and you changed nothing | Your copy of the environment file differs from the one hashed at the last apply, or (with `--local`) the server's file differs from the copy that the workstation hashed | Compare the checksums of both copies as in steps 1 and 2 of [Record the content hashes](#record-the-content-hashes), make them identical, then run `apply` |
| `plan` reports `update ... its YAML differs from the include wrapper` for `ai-edge` or `ai-inference` | The app runs with an override file that your desired-state file does not list: the internal CA of Appendix D, or the `coder` fallback of Chapter 4 | Add an `overrides` line to the app's table, as in [Create your desired-state file](#create-your-desired-state-file). Do not run `apply` before: it would replace the YAML and drop the override |
| `validate` reports `apps.<app>.overrides ...` | An `overrides` entry is not an absolute path, is not in a list, or is listed twice | Write `overrides = ["/mnt/tank/ai/appdata/..."]` with each path once |
| `plan` and `drift` always report `ai-edge` with `redeploy (RUNNING) runs images other than <tag>'s`, and `apply` ends with exit code `1` | The app runs the Caddy image built on the server; `deploy.py` compares running images with the release's compose file, not with the override | Expected. Name the other apps with `--app` for `apply` and `drift`, as the note in [How deploy.py works](#how-deploypy-works) describes |
| `plan` reports `conflict` for an app | A catalog app has the same name | `deploy.py` never touches it. Remove or rename the catalog app in **Apps** > **Installed** |
| `note: STOPPED: not started by apply` | Someone stopped the app | Start it in **Apps** > **Installed** if it should run |
| `apply` reports `<app>: FAILED: <app>: CRASHED after the change` | The app did not start | Read `/var/log/app_lifecycle.log` and the logs of its containers |
| `apply` reports `<app>: FAILED: <app>: DEPLOYING after the change (waited up to 600 s)` | The app takes longer to start than `--timeout`, for example while Compose builds the MCP hub image | Wait until the app runs, then run `plan`; next time pass `--timeout 1200` |
| `plan` reports `none`, but the containers run an old configuration | An override file or its copy changed, or the MCP hub image was rebuilt; `deploy.py` does not detect these changes | Redeploy the app by hand, as in [Redeploy one app](#redeploy-one-app) |

### Evaluation issues

[Act on failed evaluation cases](#act-on-failed-evaluation-cases) in Chapter 9 lists the reasons
that `tools/eval.py` gives for a failed case.

Table: Evaluation problems

| Symptom | Cause | Resolution |
|---|---|---|
| `eval.py run` ends with `run aborted, no results written:` and a reason | The gateway refused the key, or could not be reached | See [Act on failed evaluation cases](#act-on-failed-evaluation-cases); run `python3 tools/smoke.py` |
| `compare` ends with `gate: FAIL` | A suite's pass rate or the median speed dropped by more than `evals/gate.toml` allows | Read the `newly failing:` lines and their reasons. Run the full set again before you act on a single case, as [Regression gate rules](#regression-gate-rules) explains |
| `tools` cases fail with `the text holds a tool call` | The model wrote the call into its text | See [Tool calls fail or loop](#tool-calls-fail-or-loop) |
| The `tok/s` row fails, but `bench.sh` shows the usual speeds | Another client used the GPU during the run, or a model swap was measured | Run the evaluation again while no agent or Open WebUI user works |
| `verify --current` prints `FAIL no results file in evals/results/ for configuration <hash>` | No evaluation was run since the configuration changed, or the clone is not at the configuration that the server runs | Check out the tag or branch that the server runs, then run the evaluation ([Check the configuration checksum](#check-the-configuration-checksum)) |
| `eval.py suites` prints `FAIL` for a suite | A file under `evals/` was changed in the clone | Restore it with `git -C ~/local-agent-stack checkout -- evals/suites evals/sets.toml evals/rag-docs` |
| `--rag-source openwebui` aborts with `HTTP 401 from Open WebUI` or `HTTP 403 from Open WebUI` | `EVAL_KB_KEY` is wrong, or the `kb-reader` user cannot read the knowledge base | Repeat step 3 of [Evaluate retrieval through Open WebUI](#evaluate-retrieval-through-open-webui) |
| `tools-005` and `tools-006` fail with `expected 2 call(s) ..., got 1`, while the other `tools` cases pass | The model made one call where two were expected, or LiteLLM does not pass `parallel_tool_calls` on to llama-server (assumed, not verified) | If `tools-015`, the parallel case of the Anthropic route, passes, report the two failures to the project as an issue. Otherwise see step 5 of [Tool calls fail or loop](#tool-calls-fail-or-loop) |
| Cases end with `error` and `HTTP 400:` followed by a message that names `seed` or `parallel_tool_calls` | The gateway refused a field that `eval.py` sends | Run again without `--seed`. If the message names `parallel_tool_calls`, report it to the project as an issue with the message |
| Two runs with the same `--seed` and `--temperature` differ | LiteLLM does not pass `seed` on, or llama-server does not apply it (assumed, not verified) | Treat the runs as unseeded: run the full set again before you act on a single case, and report it as an issue |
| The results file has no `server_tokens_per_s` | LiteLLM does not pass llama-server's `timings` through (assumed, not verified) | None; the gate uses the speed that `eval.py` measures itself |
| A run fails in a way that this table and Chapter 9 do not describe | `eval.py` has not yet been run against a deployed stack (see the note in [Evaluation suites](#evaluation-suites)) | Report it to the project as an issue, with the output of the run and the results file, which holds no key, prompt or answer |

## Common problems and solutions

### The model runs out of GPU memory at load

#### About this task

The default `coder` model needs about 14.3 GiB of the card's roughly 15.5 usable GiB (estimate), and
the MTP draft context adds to it. If anything else holds VRAM, or the estimate is low, the load
fails with an out-of-memory error in the `llama-swap` log.

#### Steps

1. List the processes on the GPU:

        nvidia-smi

    Only `llama-server` processes of the `llama-swap` container belong there. Stop anything else,
    such as a leftover benchmark container (`sudo docker ps` shows containers named
    `las-bench-<number>`) or a test container.

2. If the load still fails, remove the speculative decoding from `coder` (fallback A), and if that
   is not enough, also lower its context to 49,152 tokens (fallback B). Apply the fallback on the
   server as in [Apply a fallback when coder does not fit](#apply-a-fallback-when-coder-does-not-fit).
   Fallback A lowers generation from an estimated 50 to 65 tokens per second to 40 to 45.

3. To make a fallback permanent, change `stack/inference/llama-swap/config.yaml` through a pull
   request and a release. A lower context also lowers every declared context: LiteLLM
   `max_input_tokens`, OpenCode `limit.context` and Claude Code `CLAUDE_CODE_MAX_CONTEXT_TOKENS`.

4. Measure the result with `tools/bench.sh --mode server`, as in
   [Measure the model with bench.sh](#measure-the-model-with-benchsh).

5. While `coder` is loaded, verify the memory use:

        nvidia-smi --query-gpu=memory.total,memory.used --format=csv

    `memory.used` is roughly 14,000 to 15,500 MiB.

#### Results

`coder` loads, with or without a fallback, and stays below the card's memory.

### Every turn re-processes the whole prompt

#### About this task

`llama-server` keeps the processed prompt and reuses it for the next turn, so only new tokens cost
time. The default model has hybrid layers that cannot roll their state back to an arbitrary
position: when a harness changes an earlier message, `llama-server` logs
"Forcing full prompt re-processing" and processes everything again, which takes 20 to 35 seconds
for 30,000 tokens (estimate).

#### Steps

1. Count the re-processing events in the last half hour:

        sudo docker logs --since 30m llama-swap 2>&1 | grep -c 'Forcing full prompt re-processing'

2. For Claude Code, make sure `CLAUDE_CODE_ATTRIBUTION_HEADER=0` is set, so that the system prompt
   starts identically in every request. `claude-local` sets it.

3. Make sure no proxy between the client and LiteLLM reorders or merges the system messages.

4. Keep the history append-only: compact rarely, and avoid tools or plugins that rewrite earlier
   messages.

5. Keep `--cache-ram` above 0 in the model's command; the stack sets 6,144 MiB.

6. After the next session, count the events again as in step 1.

#### Results

The count stays at a few events per session, and a turn costs only the time of its new tokens.

### Tool calls fail or loop

#### About this task

Local models handle single tool calls well and fail more often in long, multi-step loops. Template
and parser problems add malformed calls. Check the causes in this order.

#### Steps

1. Confirm that the model runs with `--jinja` and a KV cache of at least `q8_0`.

2. If generation stops without a call and the call appears in the reasoning text: this is a known
   llama.cpp problem with Qwen3.5 and Qwen3.6 (llama.cpp issue 20837, closed on 14 November 2026 by
   commit `3c31179`). The stack's llama.cpp build, `b12407`, contains that commit (checked in the
   llama.cpp repository), but the commit changes only the Ministral-3 parser and the chat tests,
   so whether it ends the problem for Qwen models is not confirmed. Retry the request. Take newer
   llama.cpp builds through the image updates and test them with
   [Pass the evaluation gate](#pass-the-evaluation-gate).

3. If calls carry malformed arguments (JSON written as a string), or requests with several system
   messages or empty thinking blocks in the history fail: the official Qwen 3.5, 3.6 and 3.8 chat
   templates have these problems. The community template `froggeric/Qwen-Fixed-Chat-Templates`
   (v22.5) fixes them, but at least one user reports more repeated thinking with it. Test it as a
   pinned file passed with `--chat-template-file`, through the evaluation gate.

4. If the model repeats the same call or loses the plan: give it smaller, scoped tasks, let it
   write its plan to a file, and cap the number of turns per task. Keep the reasoning effort at
   `medium`. For `coder-moe`, a Qwen3.6 loop was reported fixed with `--swa-full`; test that flag
   through the evaluation gate.

5. If the failures concern answers with several tool calls at once: local models make parallel
   calls less reliably than single calls. The sources disagree on whether llama-server allows them
   without the request field `parallel_tool_calls`, and whether OpenCode and Claude Code send that
   field was not checked; the stack has no setting that turns parallel calls off. Compare the
   evaluation cases `tools-005` and `tools-006` (OpenAI route) and `tools-015` (Anthropic route), and
   if they fail, ask for one tool call per step in the project's `AGENTS.md`.

6. In OpenCode, check that the model is declared with `"tools": true` in its capabilities, as the
   stack ships it.

7. To see the requests and answers of a failing session in llama-swap's web interface
   (`https://models.lab.example.com/ui`, whose labels were not checked for this guide), let
   llama-swap keep request and response bodies for a while. The release sets `captureBuffer: 0`,
   so that no prompt stays in its memory; `5` keeps up to 5 MB. Raise it in an override copy, as in
   [Apply a fallback when coder does not fit](#apply-a-fallback-when-coder-does-not-fit), with this
   command in place of that task's step 2:

        sudo sed -e 's/^captureBuffer: 0$/captureBuffer: 5/' \
          /mnt/tank/ai/stacks/local-agent-stack/stack/inference/llama-swap/config.yaml |
          sudo tee /mnt/tank/ai/appdata/llama-swap/config.yaml > /dev/null

    If a fallback copy is already in place, change that copy instead:
    `sudo sed -i 's/^captureBuffer: 0$/captureBuffer: 5/' /mnt/tank/ai/appdata/llama-swap/config.yaml`.
    Complete the remaining steps of that task, or redeploy `ai-inference` if the override is
    already listed. The captured bodies hold prompts and answers: when you have what you need,
    set the value back to `0` in the copy, or return to the release's configuration as the
    Results of that task describe, and redeploy.

8. Repeat [Test tool calling](#test-tool-calling).

#### Results

Tool calls come back structured, on both API formats, and a real session shows none of the failure
signs.

### LiteLLM health checks swap the GPU model

#### About this task

`GET /health` on LiteLLM sends a real request to every model in its configuration. That loads
`coder-moe`, which swaps `coder` out of the GPU, and the next agent request swaps it back: two model
loads for nothing. A monitoring tool or a script that checks `/health` regularly keeps the GPU busy
swapping.

#### Steps

1. Find the caller: check uptime monitors, scripts and dashboards that point at
   `https://llm.lab.example.com/health` or `http://litellm:4000/health`.

2. Change the check to one of these, which make no model calls:

        https://llm.lab.example.com/health/liveliness
        https://llm.lab.example.com/health/readiness

    To check one model, use `/health?model=local-coder` with a key.

3. Load the default model again with any request to `local-coder`, for example:

        python3 tools/smoke.py --only chat

4. Verify that `coder` is loaded:

        sudo docker exec llama-swap sh -c 'curl -fsS -H "Authorization: Bearer $LLAMA_SWAP_API_KEY" http://127.0.0.1:8080/running'

    The list shows `coder`, `embed` and `rerank`.

#### Results

Nothing calls `/health` on LiteLLM without a model any more, and `coder` stays loaded.

### Open WebUI ignores changed environment variables

#### About this task

Open WebUI 0.13.3 runs with `ENABLE_PERSISTENT_CONFIG=true`, its default. On its first start it
copies most settings from the environment into its database; from then on, the database wins, and
the Admin Panel is where those settings change. Editing them in `web.env` or `compose.yaml` later
has no effect.

Table: Open WebUI settings by source

| Read at every start (the environment wins) | Seeded on the first start (the database wins afterwards) |
|---|---|
| `WEBUI_SECRET_KEY`, `DATABASE_URL`, `VECTOR_DB`, `PGVECTOR_INDEX_METHOD`, `ENABLE_PERSISTENT_CONFIG`, `CORS_ALLOW_ORIGIN`, `WEBUI_SESSION_COOKIE_SECURE`, `OFFLINE_MODE`, `ENABLE_VERSION_UPDATE_CHECK`, `SCARF_NO_ANALYTICS`, `DO_NOT_TRACK`, `ANONYMIZED_TELEMETRY`, `ENABLE_LOCAL_WEB_FETCH` | `WEBUI_URL`, `ENABLE_SIGNUP`, `DEFAULT_USER_ROLE`, `ENABLE_COMMUNITY_SHARING`, `ENABLE_API_KEYS`, `ENABLE_OLLAMA_API`, `ENABLE_OPENAI_API`, `OPENAI_API_BASE_URLS`, `OPENAI_API_KEYS`, `DEFAULT_MODELS`, `TASK_MODEL_EXTERNAL`, every `RAG_*` and `CHUNK_*` variable, `ENABLE_RAG_HYBRID_SEARCH`, `ENABLE_MARKDOWN_HEADER_TEXT_SPLITTER`, `CONTENT_EXTRACTION_ENGINE`, `DOCLING_SERVER_URL`, `DOCLING_API_KEY`, `ENABLE_WEB_SEARCH`, `WEB_SEARCH_ENGINE`, `SEARXNG_QUERY_URL`, `WEB_SEARCH_RESULT_COUNT` |

#### Steps

1. For a setting in the right column, sign in as the administrator and change it in the Admin
   Panel:

    - Model connection and its key: **Admin Panel** > **Settings** > **Connections**.
    - Embeddings, reranker, chunking, hybrid search and the docling engine and key:
      **Admin Panel** > **Settings** > **Documents**.
    - Web search: **Admin Panel** > **Settings** > **Web Search**.

2. When you rotate `LITELLM_WEBUI_KEY`, enter the new key in three places: the connection under
   **Connections**, and the embedding key and the reranker key under **Documents**. Also update
   `web.env`, which seeds a future first start.
   [Rotate the LiteLLM key of Open WebUI](#rotate-the-litellm-key-of-open-webui) gives the complete
   procedure.

3. When you rotate `DOCLING_API_KEY`, set the new value in `rag.env` and `web.env`, redeploy
   `ai-rag`, and enter it under **Documents** for the docling engine.

4. Verify the change: for a key, send a chat message with `local-coder` and upload a small
   document to a knowledge base.

#### Results

The setting is changed in Open WebUI's database, where it takes effect, and `web.env` holds the
same value for a future first start.

!!! note
    `ENABLE_PERSISTENT_CONFIG=false` makes the environment win at every start, but then every
    change made in the Admin Panel, MCP connections included, lasts only until the next restart.
    The stack keeps the default.

### SearXNG answers 403 to JSON requests

#### About this task

Open WebUI and the hub's `searxng` server request results as JSON. SearXNG answers HTTP 403 when
`json` is missing from `search.formats` in its settings. The release's
`stack/web/searxng/settings.yml` contains it, so a 403 means that the running settings differ from
the release.

#### Steps

1. Test the JSON API from another container:

        sudo docker exec open-webui curl -s -o /dev/null -w '%{http_code}\n' 'http://searxng:8080/search?q=test&format=json'

    The output is `200`. Continue if it is `403`.

2. Show the formats of the running settings:

        sudo docker exec searxng grep -A3 'formats:' /etc/searxng/settings.yml

    The output lists `- html` and `- json`.

3. If `json` is missing, check the TrueNAS clone for local changes:

        git -C /mnt/tank/ai/stacks/local-agent-stack status --porcelain

    Discard local changes as in [Update the clones](#update-the-clones), then redeploy `ai-web`.

4. Repeat step 1.

    The output is `200`.

#### Results

SearXNG runs the release's settings and answers JSON requests.

### The MCP hub answers 401 or 421

#### About this task

The hub checks two things on every request. The bearer token must equal `MCP_HUB_TOKEN`
(HTTP 401 otherwise), and the Host header must be `mcp-hub:8096` or loopback (HTTP 421 otherwise).
Caddy rewrites the Host header for `mcp.lab.example.com`, so clients that go through Caddy pass
the second check.

#### Steps

1. On the workstation, compare the token's length with the server's, without printing either:

        printf '%s' "$MCP_HUB_TOKEN" | wc -c
        ssh -t truenas_admin@192.0.2.10 "sudo sed -n 's/^MCP_HUB_TOKEN=//p' /mnt/tank/ai/secrets/web.env | tr -d '\n' | wc -c"

    Both commands print the same number. If not, copy the value from `web.env` into
    `~/.config/local-agent-stack/client.env` and open a new terminal.

2. Test the hub through Caddy:

        python3 tools/smoke.py --only mcp

    Each of `searxng`, `fetch` and `kb` shows its server name and protocol version.

3. On a 421: make sure the client uses `https://mcp.lab.example.com`, and, inside `ai-net`,
   `http://mcp-hub:8096`. Do not remove `--allowed-host=mcp-hub:8096` from `stack/web/compose.yaml`
   or `header_up Host {upstream_hostport}` from the `Caddyfile`.

4. Check the hub itself:

        sudo docker exec mcp-hub mcp-hub-healthcheck

    The output is `ok: fetch, kb, searxng`.

#### Results

The hub accepts the client's token, and its three servers answer through Caddy.

### Certificates are not issued

#### About this task

Caddy proves control of your domain by creating a TXT record through the DNS provider's API, then
waits until the record is visible. Issuance fails when the token cannot write the record, or when
the resolvers Caddy asks cannot see it. Local DNS that serves its own zone for your domain (a
split-horizon setup in a router, Pi-hole, dnsmasq or Unbound) hides the public zone.

#### Steps

1. Read the errors in the `caddy` log:

        sudo docker logs --since 1h caddy 2>&1 | grep -i -e error -e 'certificate obtained'

2. For `expected 1 zone, got 0` or `timed out waiting for record to fully propagate`, check the
   resolvers that Caddy uses for the challenge:

        sudo grep '^ACME_RESOLVERS=' /mnt/tank/ai/secrets/edge.env

    The value must name public resolvers, by default `1.1.1.1 1.0.0.1`. Never set it to your local
    DNS server. These resolvers affect only certificate issuance and renewal.

3. For an authentication or permission error with Cloudflare, create a new token: a custom API
   token with the permissions **Zone / Zone / Read** and **Zone / DNS / Edit**, and **Zone
   Resources** limited to the zone that holds your domain. Never use the Global API Key. Put the
   token into `edge.env`, copy the file to the server as in
   [Copy the environment files to TrueNAS](#copy-the-environment-files-to-truenas), and delete the
   old token.

4. While you test, set `ACME_CA=https://acme-staging-v02.api.letsencrypt.org/directory` in
   `edge.env`, which avoids the production rate limits.

5. Redeploy `ai-edge`:

        sudo midclt call -j app.redeploy ai-edge

6. Watch the log until it shows `certificate obtained`, then, if you set the staging CA, remove the
   `ACME_CA` line and redeploy again.

7. From the workstation, verify the certificate:

        echo | openssl s_client -connect chat.lab.example.com:443 -servername chat.lab.example.com 2>/dev/null | openssl x509 -noout -subject -issuer -enddate

    The subject is `CN = *.lab.example.com`, and the issuer is a Let's Encrypt production
    authority.

#### Results

Caddy holds a production certificate for every lab host name and renews it by itself.

### Change the Open WebUI database password

#### About this task

PostgreSQL uses `PG_PASSWORD` only when it creates the database on the first start. Changing the
variable later does not change the password: set the new value in both secrets files, then change
the password inside the database to the value of the server's file. The command builds the SQL
statement from the file and passes it to `psql` on standard input, so the password appears neither
on a command line nor in the shell history. The running containers keep the old value until their
app is redeployed.

#### Steps

1. Create a new password. Use letters and digits only, because the password goes into a URL:

        python3 -c 'import secrets, string; a = string.ascii_letters + string.digits; print("".join(secrets.choice(a) for _ in range(48)))'

2. Set `PG_PASSWORD=<new>` in both `rag.env` and `web.env` in `~/.config/local-agent-stack/secrets/`
   on the workstation, and copy both files to the server as in
   [Copy the environment files to TrueNAS](#copy-the-environment-files-to-truenas).

3. On TrueNAS, change the password of the `openwebui` role to the value of the server's `rag.env`:

        sudo sed -n "s/^PG_PASSWORD=\(.*\)$/ALTER ROLE openwebui PASSWORD '\1';/p" /mnt/tank/ai/secrets/rag.env |
          sudo docker exec -i pgvector psql -U openwebui -d openwebui

    The output is `ALTER ROLE`.

4. Redeploy `ai-rag`, wait until its containers are healthy, then redeploy `ai-web`:

        sudo midclt call -j app.redeploy ai-rag
        sudo midclt call -j app.redeploy ai-web

5. Verify that Open WebUI answers:

        sudo docker exec open-webui curl -s http://127.0.0.1:8080/health

    The output is `{"status":true}`.

#### Results

The database, both secrets files and the running containers use the new password.

### Set the LiteLLM database password again

#### About this task

PostgreSQL uses `LITELLM_DB_PASSWORD` only when `litellm-db` creates its database on the first
start. If the value in `inference.env` changed later, `litellm` cannot log in. Set the role's
password to the value of the server's file. As in
[Change the Open WebUI database password](#change-the-open-webui-database-password), the SQL
statement goes to `psql` on standard input.

#### Steps

1. On TrueNAS, set the password of the `litellm` role:

        sudo sed -n "s/^LITELLM_DB_PASSWORD=\(.*\)$/ALTER ROLE litellm PASSWORD '\1';/p" /mnt/tank/ai/secrets/inference.env |
          sudo docker exec -i litellm-db psql -U litellm -d litellm

    The output is `ALTER ROLE`.

2. Redeploy `ai-inference`:

        sudo midclt call -j app.redeploy ai-inference

3. Check that LiteLLM reaches its database:

        sudo docker exec litellm python3 -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:4000/health/readiness').read().decode())"

    The answer contains `"status":"healthy"` and `"db":"connected"`.

#### Results

The `litellm` role's password matches `inference.env`, and LiteLLM uses its database again.

### Start a knowledge sync now

#### About this task

`oikb` syncs every 15 minutes. To sync at once, call its sync route. The route needs
`OIKB_API_KEY` when that variable is set; the command reads it from the container's own
environment, so the key never appears on a command line.

#### Steps

1. Start the sync:

        sudo docker exec oikb python -c "import os, urllib.request as u; \
        u.urlopen(u.Request('http://127.0.0.1:8080/sync/rag-docs', method='POST', \
        headers={'Authorization': 'Bearer ' + os.environ['OIKB_API_KEY']}))"

    The command returns without output. An `HTTP Error 401` means that the key in the request does
    not match `OIKB_API_KEY`.

2. Check the result:

        sudo docker exec oikb python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/health').read().decode())"

    The source `rag-docs` shows a new last-sync time, its file counts and no error.

#### Results

The `rag-docs` share is synced to the knowledge base without waiting for the schedule.
