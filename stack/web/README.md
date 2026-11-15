# ai-web: Open WebUI, SearXNG and the MCP hub

The browser GUI, web search and the shared tool hub, installed on TrueNAS as the custom app
`ai-web` ([`compose.yaml`](compose.yaml); contract: [`docs/stack-design.md`](../../docs/stack-design.md)
§1-§3, §6; research: [`docs/research/d-gui-rag-search.md`](../../docs/research/d-gui-rag-search.md)).

| Service | Image (tag, pinned by digest) | On `ai-net` | Through Caddy | State |
|---|---|---|---|---|
| `open-webui` | `ghcr.io/open-webui/open-webui:v0.13.3-slim` | `open-webui:8080` | `chat.<LAB_DOMAIN>` | `appdata/open-webui` (uploads); database in `pgvector` |
| `searxng` | `docker.io/searxng/searxng:2026.11.15-2d500cb6b` | `searxng:8080` | `search.<LAB_DOMAIN>` | none (config read-only from git) |
| `mcp-hub` | built from [`mcp-hub/`](mcp-hub/Dockerfile) on `sparfenyuk/mcp-proxy:v0.15.0-debian-node` | `mcp-hub:8096` | `mcp.<LAB_DOMAIN>` | none |

No port is published, no service uses the GPU (`NVIDIA_VISIBLE_DEVICES=void` on all three; none
is CUDA-based), every container has `no-new-privileges`, and logs rotate at 10 MB, five files.

## Before installing

- `ai-rag` is running (`pgvector`, `docling`) and `ai-inference` is running (`litellm`).
- A LiteLLM virtual key for Open WebUI exists (`LITELLM_WEBUI_KEY`). It must allow
  `local-coder`, `local-fast`, `local-coder-moe`, `local-embed` and `local-rerank`: the one key
  serves chat, embeddings and reranking, and Open WebUI lists exactly the models it allows.
- `web.env` from [`web.env.example`](web.env.example) is in `/mnt/tank/ai/secrets/` (mode 0600):
  `LAB_DOMAIN` as in `edge.env`, `PG_PASSWORD` and `DOCLING_API_KEY` as in `rag.env`.
  Compose refuses to start the app while a required value is missing and names it.
- Open WebUI is reached only through Caddy (`https://chat.<LAB_DOMAIN>`), so its first start
  in a browser happens once `ai-edge` is up.

## First start of Open WebUI

These steps are the ones the guide walks the reader through. Steps 2-4 only confirm what the
environment already seeded; steps 5-9 create the two service accounts oikb and the kb MCP
server need.

1. Open `https://chat.lab.example.com` and sign up. The first account becomes the admin and
   sign-up closes behind it (`ENABLE_SIGNUP=false`; Open WebUI never gates the first account
   on that flag and turns sign-up off after it). Later users are created by the admin.
2. **Admin Panel** > **Settings** > **Connections**: one OpenAI API connection,
   `http://litellm:4000/v1`, and the Ollama API off. The model selector lists the `local-*`
   models; `local-coder` is the default.
3. **Admin Panel** > **Settings** > **Documents**: **Content Extraction Engine** Docling
   (`http://docling:5001`), **Embedding Model Engine** OpenAI with model `local-embed`,
   **Hybrid Search** on, **Reranking Engine** External with model `local-rerank` and URL
   `http://litellm:4000/v1/rerank`.
4. **Admin Panel** > **Settings** > **Web Search**: on, engine searxng, query URL
   `http://searxng:8080/search?q=<query>`.
5. **Admin Panel** > **Users** > **Groups**: create a group (for example `service-accounts`) and
   turn on **API Keys** in its permissions. The **Default permissions** keep API keys off for
   everyone else.
6. **Admin Panel** > **Users** > **Add User**: `indexer` and `kb-reader`, role user, both in
   that group.
7. **Workspace** > **Knowledge**: create the knowledge base for the `rag-docs` dataset. Under
   its access settings give `indexer` write access and `kb-reader` read access. Copy its ID
   from the page URL: that is `OIKB_KB_ID`. Open WebUI keys act as their user, so `kb-reader`
   sees only the knowledge bases it was given.
8. Sign in as each service user, **Settings** > **Account** > **API keys** >
   **Create new secret key**: the `indexer` key is `OIKB_TOKEN` (`rag.env`), the `kb-reader`
   key is `KB_READER_TOKEN` (`web.env`).
9. Save both env files and redeploy both apps (`midclt call -j app.redeploy ai-rag`, then
   `ai-web`). Within 15 minutes oikb uploads the dataset into the knowledge base.

Open WebUI's own tools already search the web (SearXNG), fetch pages and query knowledge bases,
so the GUI needs no connection to the MCP hub. To add one anyway, use
**Admin Panel** > **Settings** > **Integrations**: a connection of type MCP (Streamable HTTP) to
`http://mcp-hub:8096/servers/<name>/mcp` with Bearer auth and `MCP_HUB_TOKEN` (d-gui D1, D4).

## Settings that persist

`ENABLE_PERSISTENT_CONFIG` is `true` (Open WebUI's default). Open WebUI 0.13.3 stores most
settings in its database: on the first start it seeds each one from the environment, and from
then on the database wins and the Admin Panel is where they change. Editing those variables in
`compose.yaml` or `web.env` later has **no effect**. Checked in the source at `v0.13.3`
(`backend/open_webui/config.py` `DEFAULT_CONFIG`, `models/config.py` `seed_defaults`).

| Read at every start (environment wins) | Seeded on the first start (database wins afterwards) |
|---|---|
| `WEBUI_SECRET_KEY`, `DATABASE_URL`, `VECTOR_DB`, `PGVECTOR_INDEX_METHOD`, `ENABLE_PERSISTENT_CONFIG`, `CORS_ALLOW_ORIGIN`, `WEBUI_SESSION_COOKIE_SECURE`, `OFFLINE_MODE`, `ENABLE_VERSION_UPDATE_CHECK`, `SCARF_NO_ANALYTICS`, `DO_NOT_TRACK`, `ANONYMIZED_TELEMETRY`, `ENABLE_LOCAL_WEB_FETCH` | `WEBUI_URL`, `ENABLE_SIGNUP`, `DEFAULT_USER_ROLE`, `ENABLE_COMMUNITY_SHARING`, `ENABLE_API_KEYS`, `ENABLE_OLLAMA_API`, `ENABLE_OPENAI_API`, `OPENAI_API_BASE_URLS`, `OPENAI_API_KEYS`, `DEFAULT_MODELS`, `TASK_MODEL_EXTERNAL`, every `RAG_*` and `CHUNK_*` variable in the file, `ENABLE_RAG_HYBRID_SEARCH`, `ENABLE_MARKDOWN_HEADER_TEXT_SPLITTER`, `CONTENT_EXTRACTION_ENGINE`, `DOCLING_SERVER_URL`, `DOCLING_API_KEY`, `ENABLE_WEB_SEARCH`, `WEB_SEARCH_ENGINE`, `SEARXNG_QUERY_URL`, `WEB_SEARCH_RESULT_COUNT`, `ENABLE_MEMORIES`, `ENABLE_MEMORY_SYSTEM_CONTEXT`, `ENABLE_MEMORY_BACKGROUND_REVIEW` |

Consequences for the guide:

- **Rotating `LITELLM_WEBUI_KEY` or `DOCLING_API_KEY`** means entering the new key in the Admin
  Panel (Connections; Documents twice for the key: embeddings and reranker; Documents for
  docling), not only in `web.env`.
- **Placeholder values on the first start stay** until changed in the Admin Panel. Fill
  `web.env` completely before the first install.
- The alternative, `ENABLE_PERSISTENT_CONFIG=false`, makes the environment win on every start,
  but then Admin Panel changes (MCP connections included) last only until the next restart.
- **Changing the embedding model** needs **Reindex Embedding Data** (Admin Panel > Settings >
  Documents); files attached directly to chats keep their old vectors (d-gui D2).
- **`ENABLE_MEMORY_BACKGROUND_REVIEW` has no Admin Panel switch** in 0.13.3 (the Admin Panel
  shows only **Memories** and **Memory System Context**), so its first-start value, `false`,
  stays.

Other choices in the file: `OFFLINE_MODE=true` stops the update check, Hugging Face downloads
(the slim image needs none) and pip installs of plugin requirements; Scarf, `DO_NOT_TRACK` and
anonymized telemetry are off (the image sets the same values; the file states them).
`CORS_ALLOW_ORIGIN` and the secure session cookie assume the browser address
`https://chat.<LAB_DOMAIN>` and nothing else.

## Memory

Open WebUI's Memory feature is on (`docs/v1.2-design.md` §3). The three variables in
`compose.yaml` are Open WebUI 0.13.3's defaults, stated so the choice is visible; they are
PersistentConfig seeds (`backend/open_webui/config.py` `DEFAULT_CONFIG`: `memories.enable`,
`memories.system_context.enable`, `memories.background_review.enable`). Checked in the source at
`v0.13.3` (`utils/middleware.py`, `utils/tools.py`, `utils/memory.py`, `routers/memories.py` and
the Svelte components named below).

| Level | Where | Default | What it does |
|---|---|---|---|
| Server | **Admin Panel** > **Settings** > **General** > **Memories** (`ENABLE_MEMORIES`) | on | Memory exists at all; with it off, the memory API refuses every call and the user switch is hidden |
| Server | **Admin Panel** > **Settings** > **General** > **Memory System Context** (`ENABLE_MEMORY_SYSTEM_CONTEXT`) | on | The user's matching memories go to the model at each turn |
| Server | `ENABLE_MEMORY_BACKGROUND_REVIEW` (no Admin Panel switch) | off | Every 10th user turn, one more completion on the chat's model decides what to save; off here because that model is `local-coder` (GPU time with thinking) |
| Group | **Admin Panel** > **Users** > **Groups** > a group's permissions > **Memories** (`USER_PERMISSIONS_FEATURES_MEMORIES`) | on | Whether that group's users may use memory (admins always may) |
| Model | **Admin Panel** > **Settings** > **Models**, the model, **Capabilities** > **Memory** | on (a model without saved settings) | Whether that model gets the memory tools (`utils/tools.py`, `get_model_capability('memory')`) |
| User | **Settings** > **Personalization** > **Memory** (marked experimental) | follows **Memories** until the user changes it | The user's own switch; **Add Memory** and **Manage** list, add, edit and delete that user's memories |

So Memory is both: the server and group levels are persisted configuration (the database wins
after the first start; the variables only seed it), and each user has a switch of their own in
their settings. Nothing needs a click for memory to work: every level defaults to on except the
background review.

Memories belong to one user and are kept in the database (PostgreSQL in `pgvector`). They are
written in two ways: by the user (**Add Memory**), and by the model, which gets eight memory
tools (search, list paths, read a path, list, update, add, replace content, delete) while the
model's Function Calling is Native, Open WebUI 0.13.3's default; the matching memories reach the
model as a recalled tool result at the start of each turn. A model set to Legacy gets no memory
tools, and the matching memories are appended to the user's message instead. So "remember that I
prefer tabs" in a chat lets `local-coder` save a memory, if it calls the tool. Caveat: the eight
tool definitions are part of every chat's request while memory is on, which costs context and
makes tool choice harder for a local model; a user who does not want that turns their own switch
off.

## Images and files in chats

**Images.** Open WebUI 0.13.3 offers image upload for a model when that model's capability
**Vision** is on, and a model with no saved settings counts as vision-capable
(`src/lib/components/chat/MessageInput.svelte`: `capabilities[...] ?? true`;
`src/lib/constants.ts` `DEFAULT_CAPABILITIES.vision = true`). The `local-*` models arrive from the
LiteLLM connection without saved settings, so images work without a click. To check or change
it:

- One model: **Admin Panel** > **Settings** > **Models**, click the model (for example
  `local-coder`), section **Capabilities**, checkbox **Vision** ("Model accepts image inputs"),
  then save. Keep it on for `local-coder`, `local-fast` and `local-coder-moe`.
- Every model at once: the same page, **Model Defaults** at the top, **Model Capabilities**
  (stored as `models.default_metadata`, seeded from `DEFAULT_MODEL_METADATA`, which this stack
  does not set). A model's own setting wins.

In a chat, the reader adds an image by dragging it onto the chat, pasting it into the message box,
or with the message box's **More** button > **Upload Files** (labels from
`src/lib/components/chat/MessageInput/InputMenu.svelte`), then sends a question about it. With
Vision off, attaching an image fails at once with "Selected model(s) do not support image
inputs". With it on, the browser uploads the image as a file of the chat, and before calling the
model Open WebUI replaces its address with a base64 data URL (`utils/middleware.py`
`convert_url_images_to_base64`), so llama-server receives the picture itself and never has to fetch
a URL. The model reads it with its CPU projector, about 11 s per image (estimate;
`stack/inference/README.md`, "Images"). To cut that time for large photos, **Admin Panel** >
**Settings** > **Documents** > **Image Compression Width** and **Image Compression Height**
(`FILE_IMAGE_COMPRESSION_WIDTH`/`HEIGHT`, not set here) shrink images in the browser before upload.

**Other files.** A file dropped into a chat stays with that chat: it is extracted (docling) and
indexed in its own vector collection `file-<id>`, used for that chat only. It is never added to a
knowledge base: `routers/files.py` links an upload to a knowledge base only when the upload names
one (`knowledge_id`), which only **Workspace** > **Knowledge** does. Documents meant for every chat
go into the knowledge base through the `rag-docs` share (oikb) or **Workspace** > **Knowledge**.

## Reranker: LiteLLM's /v1/rerank fits Open WebUI

Open WebUI's `external` reranker (`backend/open_webui/retrieval/models/external.py` at
`v0.13.3`) posts `{"model", "query", "documents": [strings], "top_n"}` with
`Authorization: Bearer <key>` to `RAG_EXTERNAL_RERANKER_URL` and reads `results`, sorted by
`index`, taking each `relevance_score`. LiteLLM 1.108.8 serves `/rerank`, `/v1/rerank` and
`/v2/rerank` with the Cohere request shape (`litellm/proxy/rerank_endpoints/endpoints.py`) and
always answers a `RerankResponse` whose `results` hold `index` and `relevance_score`; for a
`hosted_vllm/` model it forwards to `<api_base>/rerank` and rebuilds that response from the
backend's `results` (`litellm/llms/hosted_vllm/rerank/transformation.py`). The shapes match, so
the reranker goes through LiteLLM with `LITELLM_WEBUI_KEY` and model `local-rerank`, with
LiteLLM's keys and logs.

Fallback if the LiteLLM route misbehaves: point **Admin Panel** > **Settings** > **Documents** at
llama-swap directly, URL `http://llama-swap:8080/v1/rerank`, model `rerank`, key
`LLAMA_SWAP_API_KEY` (llama.cpp's `/v1/rerank` takes and returns the same Jina/Cohere shape,
d-gui [44]). It costs a second copy of the llama-swap key in Open WebUI.

## SearXNG

[`searxng/settings.yml`](searxng/settings.yml) lists only the differences from SearXNG's
defaults: JSON output on (Open WebUI and mcp-searxng get HTTP 403 without it), limiter off (LAN
only; no Valkey), no image proxy. Google and Bing are not scraped: the main engines ship
disabled and are listed anyway, and the side engines that ship enabled in this version
(`google cse`, `google cse images`, `google news`, `google videos`, `google scholar`,
`bing images`, `bing news`, `bing videos`) are turned off. General results come from DuckDuckGo,
Brave, Wikipedia and Wikidata; npm, crates.io, pkg.go.dev, GitLab, Codeberg, Hugging Face and
Hacker News are turned on for the IT category. The two Tor engines are made inactive so they do
not log an error at every start. [`searxng/limiter.toml`](searxng/limiter.toml) is empty on
purpose (SearXNG warns when the file is missing).

`SEARXNG_SECRET` replaces the built-in secret (SearXNG refuses to start with it).
`SEARXNG_CONTACT_URL` is required by the Wikipedia, Wikidata and OpenStreetMap engines, which
send it in their User-Agent; empty leaves those three engines unloaded. The configuration is
mounted read-only from the git checkout with `FORCE_OWNERSHIP=false`, so the entrypoint does not
`chown` the checkout (it prints an ownership warning instead), and the favicon cache is a tmpfs.

## MCP hub

[`mcp-hub/Dockerfile`](mcp-hub/Dockerfile) adds three stdio MCP servers to
`ghcr.io/sparfenyuk/mcp-proxy:v0.15.0-debian-node` (pinned by digest; Python 3.13, Node.js 24)
and runs them as uid 10001. mcp-proxy serves each one at `/servers/<name>/mcp` (Streamable
HTTP), checks the bearer token (`MCP_PROXY_AUTH_TOKEN` = `MCP_HUB_TOKEN`) on every request,
including `/status`, and answers HTTP 421 to a Host header other than `mcp-hub:8096` or
loopback. [`mcp-hub/servers.json`](mcp-hub/servers.json) holds no secrets:

| Path | Server | Tools |
|---|---|---|
| `/servers/searxng/mcp` | `mcp-searxng` 2.10.1, `SEARXNG_URL=http://searxng:8080`, at most 10 results of 500 characters, 20,000 characters per page read | `searxng_web_search`, `searxng_search_suggestions`, `searxng_instance_info`, `web_url_read` |
| `/servers/fetch/mcp` | `mcp-server-fetch` 2026.11.11, `--no-readability-js`; refuses private, loopback and link-local addresses and honours robots.txt (its defaults) | `fetch` |
| `/servers/kb/mcp` | `open-webui-knowledge-mcp-server` 0.2.0 against `http://open-webui:8080/api/v1` with `KB_READER_TOKEN` | `search_knowledge_base`, `list_knowledge_bases`, `get_knowledge_base_info`, `get_knowledge_base_file_content` |

Details:

- **Pinning.** The Node.js servers are installed with `npm ci` from
  [`package-lock.json`](mcp-hub/package-lock.json) (127 packages, none with an install script, so
  `--ignore-scripts`); the fetch server goes into its own virtual environment from
  [`requirements-fetch.txt`](mcp-hub/requirements-fetch.txt) with `--require-hashes`. Both were
  resolved with nothing published after 2026-11-12. To update, change the versions in
  `package.json` or `requirements-fetch.in` and regenerate, in the base image. `package.json`
  overrides the kb server's nested zod 3.x to 4.6.7 (issue #25, Dependabot alert #1); keep the
  override until `open-webui-knowledge-mcp-server` itself depends on zod 4.6.6 or later:

  ```sh
  cd stack/web/mcp-hub
  IMG=ghcr.io/sparfenyuk/mcp-proxy:v0.15.0-debian-node@sha256:29265b23ef7517a095083714d582fcf47803287a3c3d66513e2a661d4b9ce3e9
  docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD":/w -w /w --entrypoint npm "$IMG" \
    install --package-lock-only --ignore-scripts --no-audit --no-fund --before=<date>
  docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD":/w -w /w --entrypoint uv "$IMG" \
    pip compile requirements-fetch.in --universal --python-version 3.13 --generate-hashes \
    --exclude-newer <date> --output-file requirements-fetch.txt
  ```

- **kb server output.** `open-webui-knowledge-mcp-server` 0.2.0 prints two start-up lines on
  stdout, which mcp-proxy logs as "Failed to parse JSONRPC message". It is started with
  `node --require console-to-stderr.cjs`, which moves `console.log/info/debug` to stderr.
- **fetch and Node.js.** By default the fetch server runs Readability.js under Node.js and lets
  readabilipy try `npm install` into its package directory at run time (it failed with EACCES as
  the unprivileged user, then fell back). `--no-readability-js` uses the pure-Python extractor
  only and never starts npm.
- **Health check.** `mcp-hub-healthcheck` ([`healthcheck.py`](mcp-hub/healthcheck.py)) calls
  `/status` with the token and is healthy only when `searxng`, `fetch` and `kb` all started
  (mcp-proxy skips a server that fails to start and marks it `failed`).
- **Image.** The compose file names `ghcr.io/corytron/local-agent-stack-mcp-hub:0.15.0` and
  `build: ./mcp-hub`: Compose pulls the image if it exists and otherwise builds it from the
  checkout on the NAS.

### What was tested (c4dev, 2026-11-15)

`docker build` of [`mcp-hub/`](mcp-hub/Dockerfile) succeeded (about 430 MB). The container ran
with the flags from `compose.yaml` on a test network next to a SearXNG container started from
[`searxng/`](searxng/settings.yml) (both since removed, with their images):

- the health check printed `ok: fetch, kb, searxng`;
- an MCP `initialize`, `notifications/initialized` and `tools/list` succeeded on each of
  `/servers/searxng/mcp`, `/servers/fetch/mcp` and `/servers/kb/mcp` (protocol 2025-06-18),
  listing the tools in the table above;
- `searxng_web_search` returned live results through SearXNG; `fetch` of `https://example.com`
  returned Markdown, and `fetch` of `http://searxng:8080/healthz` was refused as a private
  address;
- no token and a wrong token gave HTTP 401, a Host header of `evil.example.com` HTTP 421;
- SearXNG: `/healthz` answered `OK`, `/search?format=json` returned results from DuckDuckGo and
  Brave (general) and from the developer engines (category `it`), and no Google or Bing engine
  answered.

The kb server was not called against a real Open WebUI.

## Verify

From **System > Shell** on TrueNAS (`sudo` where needed):

```sh
docker ps --filter name=open-webui --filter name=searxng --filter name=mcp-hub \
  --format '{{.Names}} {{.Status}}'                               # all three "(healthy)"
docker exec open-webui curl -s http://127.0.0.1:8080/health       # {"status":true}
docker exec open-webui curl -s 'http://searxng:8080/search?q=test&format=json' | head -c 300
docker exec mcp-hub mcp-hub-healthcheck                           # ok: fetch, kb, searxng
T=$(sudo sed -n 's/^MCP_HUB_TOKEN=//p' /mnt/tank/ai/secrets/web.env)
docker exec open-webui curl -s http://mcp-hub:8096/servers/fetch/mcp \
  -H "Authorization: Bearer $T" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"check","version":"0"}}}'
```

The last command prints a JSON result naming `mcp-fetch` 2026.11.11. To check the reranker
route Open WebUI uses (with the Open WebUI key from `web.env`):

```sh
K=$(sudo sed -n 's/^LITELLM_WEBUI_KEY=//p' /mnt/tank/ai/secrets/web.env)
docker exec open-webui curl -s http://litellm:4000/v1/rerank -H "Authorization: Bearer $K" \
  -H 'Content-Type: application/json' \
  -d '{"model":"local-rerank","query":"what is pgvector","documents":["pgvector adds vector search to PostgreSQL","bananas are yellow"],"top_n":2}'
```

It answers `results` with `index` and `relevance_score`, the first document scoring higher.

## Unverified

- Open WebUI, and the reranker and embedding chain Open WebUI → LiteLLM → llama-swap, were not
  run (the owner's rule: nothing of the stack runs on c4dev). The request and response shapes
  were checked in the source of both projects at the pinned versions.
- Building the image on TrueNAS 25.10 (the fallback when the published
  `ghcr.io/corytron/local-agent-stack-mcp-hub` image cannot be pulled) was not tried there;
  `.github/workflows/mcp-hub-image.yml` publishes the image from main.
- `no-new-privileges` with Open WebUI's start script (runs as root; no setuid binaries used).
- The English captions of the Admin Panel tabs in "First start of Open WebUI": the field labels
  in step 3, **Admin Panel**, **Add User**, **Default permissions**, **API Keys**, **API keys**
  and **Create new secret key** were read from the `v0.13.3` frontend and its en-US
  translations; the tab captions (**Connections**, **Documents**, **Web Search**,
  **Integrations**) and the knowledge base's access dialog were not.
- `RAG_EMBEDDING_BATCH_SIZE=16`, `RAG_TOP_K=20` and `RAG_TOP_K_RERANKER=8` are starting points
  for CPU embeddings and reranking, not measured.
- The Memory and Images sections were read from the `v0.13.3` source and its en-US translations
  (labels **Memories**, **Memory System Context**, **Personalization**, **Memory**, **Add Memory**,
  **Manage**, **Capabilities**, **Vision**, **Model Defaults**, **Model Capabilities**, **Image
  Compression Width**/**Height**, **More**, **Upload Files**), not in a running Open WebUI; that
  clicking a model's row on **Admin Panel** > **Settings** > **Models** opens its editor, and
  where the **More** button sits in the message box, are read from the components, not tried.
