# Web GUI, RAG pipeline, web search and MCP tool servers (including SSH)

Status: research, 2026-11-15. Author: research agent D.

## Summary

- **GUI: Open WebUI v0.13.3** (2026-11-08), slim image `ghcr.io/open-webui/open-webui:v0.13.3-slim`. It is
  the only candidate that has, in one container, multi-user auth (local, OIDC, LDAP, SCIM), native tool
  calling, native MCP (Streamable HTTP, OAuth 2.1, elicitation), built-in RAG with hybrid BM25+vector search
  and an external reranker, SearXNG web search with agentic `search_web`/`fetch_url` tools, artifacts and
  code execution through Open Terminal [1][3][5][11][13][14]. Licence: BSD-3 plus a branding clause since
  v0.6.6 (not OSI open source). The clause only bites above 50 users per rolling 30 days, so it does not
  affect a home install [2].
- **RAG store: PostgreSQL 17 with pgvector 0.8.7** (`pgvector/pgvector:0.8.7-pg17`) as both the Open WebUI
  database and the vector store. Open WebUI's pgvector backend does hybrid search natively in SQL (a GIN
  `to_tsvector` index plus vector search). Its Qdrant backend has no native hybrid, so BM25 is scored in
  Python over every chunk of the collection [5][15]. One database also means one thing to back up.
- **Embeddings and reranking: two small llama.cpp servers** (`ghcr.io/ggml-org/llama.cpp:server-cuda-b12407`)
  running Qwen3-Embedding-0.6B Q8_0 (639 MB, Apache-2.0) on `/v1/embeddings` and bge-reranker-v2-m3 Q8_0
  (636 MB, Apache-2.0) on `/v1/rerank`. Together they need about 1.5–2.5 GB of VRAM, or they can run on the
  CPU [44][45][46]. Hugging Face TEI was ruled out because its `/rerank` API (`texts` in, `score` out) does
  not match what Open WebUI's external reranker sends and parses (`documents` in, `results[].relevance_score`
  out) [15][43].
- **Document parsing: docling-serve on the CPU** (`ghcr.io/docling-project/docling-serve-cpu:v1.38.2`) for
  PDF, Office, HTML and images, with OCR and table structure. It is native to Open WebUI as
  `CONTENT_EXTRACTION_ENGINE=docling` [12][47]. Apache Tika 3.3/4.2 is the light fallback.
- **Keeping the index current from the NAS: `oikb`**, Open WebUI's official sync daemon
  (`ghcr.io/open-webui/oikb:0.6.0`, MIT). It does incremental SHA-256 diffs from a read-only bind of the
  dataset on an interval or cron, with globs and size caps, Prometheus metrics and a history log [8][9].
- **Web search: self-hosted SearXNG** (`docker.io/searxng/searxng:2026.11.15-2d500cb6b`). It must have
  `search.formats: [html, json]` or Open WebUI gets HTTP 403. Leave `limiter: false` on a private LAN
  instance; Valkey is only needed when the limiter is on [10][27][29]. The GUI uses it natively. The CLI
  agent uses it through `mcp-searxng` v2.10.1, which also provides `web_url_read` (HTML and PDF to text)
  [31]. A paid API is optional, with Brave ($5 per 1,000 requests, $5 free credit a month) or Tavily
  (1,000 free credits a month) as the fallback [54].
- **Shared tools: one MCP hub container**, `sparfenyuk/mcp-proxy` v0.15.0. It serves stdio MCP servers as
  Streamable HTTP at `/servers/<name>/mcp` behind a bearer token. It carries SearXNG, URL fetch, a
  knowledge-base MCP (`open-webui-knowledge-mcp-server`, which calls Open WebUI's own
  `/api/v1/retrieval/query/collection`, so the CLI agent queries the same hybrid-plus-rerank index as the
  GUI) and optional read-only filesystem and database tools. The GitHub MCP server runs separately in its
  native HTTP mode [34][41][15][33]. mcpo is no longer needed: Open WebUI speaks MCP Streamable HTTP
  natively [3][4].
- **SSH: `ssh-mcp` v2.26.0 (tufantunc, MIT)**, run as stdio on c4dev for the CLI agent only. It is the one
  maintained SSH MCP server found with a policy engine (roles × host tiers, deny-lists), human approval
  through MCP elicitation (fails closed when the client cannot ask), host-key pinning (`--hostKeyMode
  strict`), ProxyJump, SSH CA certificates, quotas and a redacted JSONL audit log [38]. Pair it with
  host-side controls: a dedicated key per agent, a non-root user, `restrict,from=…,command=…` in
  `authorized_keys`, a `Match User` block, an optional bastion, and logs on both sides [52].
- **Not recommended:** LibreChat (MIT, strong agents and MCP, but needs MongoDB, Meilisearch, pgvector,
  rag_api, a separate code sandbox and a scraper, and its rerankers are cloud-only) [17][19][20];
  AnythingLLM (MIT and simple, but MCP is agent-mode only, telemetry is on by default and RAG tuning is
  thinner) [22]; LobeHub (seven services, and its licence restricts derivative works) [23]; Jan and Msty
  (desktop-only) [24][25]; Onyx (excellent connectors and its own MCP server, but heavy, with SSO and RBAC
  in the enterprise edition) [26].

## Recommendation

### Architecture

```
Browsers (Mac, Windows VM, c4dev)
   │ HTTP(S) :3000 (TLS via reverse proxy: see e-truenas.md)
   ▼
open-webui (slim, CPU) ── OpenAI-compatible ──► model router (see b-inference.md)
   ├─► postgres + pgvector   app DB + vectors, native hybrid search
   ├─► llama-embed            Qwen3-Embedding-0.6B   /v1/embeddings   (GPU or CPU)
   ├─► llama-rerank           bge-reranker-v2-m3     /v1/rerank       (GPU or CPU)
   ├─► docling                PDF/Office/HTML/images → Markdown, OCR   (CPU)
   ├─► searxng :8080          format=json ─────► internet engines
   ├─► mcp-hub :8096          /servers/{searxng,fetch,kb,docs-ro}/mcp   (bearer token)
   └─► github-mcp :8082       GitHub MCP, native HTTP, PAT sent by each client
oikb daemon ── reads NAS dataset (ro bind) ──► Open WebUI knowledge API (incremental, every 15 min)

c4dev (CLI agent, see c-agents.md)
   ├─► mcp-hub over LAN (bearer token): searxng, fetch, kb (the same index the GUI uses)
   ├─► github-mcp over LAN (Authorization: Bearer <PAT>)
   └─► ssh-mcp (stdio, local process, key stays on c4dev) ──SSH──► remote hosts (restricted user)
```

### Why this set

1. **One GUI that already does nearly everything.** Open WebUI 0.13 has native function calling as the
   default mode, built-in tools (`query_knowledge_bases`, `search_web`, `fetch_url`, sub-agents, skills and
   tool search), MCP Streamable HTTP with OAuth 2.1 and elicitation dialogs, tool-approval modes, artifacts,
   and Open Terminal for code execution. Open Terminal can even drive OpenCode, Claude Code, Codex and others
   as "models" in the picker [1][3][11][14]. The slim image is about 197 MB to download and used about
   300 MiB of RAM at idle in the vendor's test, because embeddings, reranking and extraction move out to
   dedicated services [13].
2. **Hybrid search that scales.** With `VECTOR_DB=pgvector`, Open WebUI runs the BM25 part as Postgres
   full-text search. With Qdrant or Chroma it fetches every chunk of the collection and scores BM25 itself on
   each query [5][15]. pgvector also lets `DATABASE_URL` and the vectors share one Postgres instance.
3. **Local embedder and reranker on the API shapes Open WebUI expects.** Open WebUI's `openai` embedding
   engine calls any `/v1/embeddings`. Its `external` reranker posts `{model, query, documents, top_n}` and
   reads `results[].relevance_score` [5][15]. llama.cpp's `/v1/rerank` accepts this (Jina) shape and returns
   exactly that [44]. It is the same engine family as the LLM servers, so no extra runtime is needed.
4. **One index, two clients.** The CLI agent's knowledge MCP calls
   `POST /api/v1/retrieval/query/collection`, which uses the same hybrid-plus-rerank code path as chat
   (checked in source) [15][41]. There is no second vector store to keep in sync.
   `qdrant/mcp-server-qdrant` was rejected because it only supports FastEmbed embeddings and its own
   payload schema [42].
5. **Sync without a home-made script.** `oikb` is maintained by the Open WebUI team and uses the server's
   `sync/diff` and `sync/cleanup` endpoints (Open WebUI 0.9.6 or later). Unchanged files cost nothing:
   nothing is re-uploaded or re-embedded [8][9].
6. **A tool hub both clients reach.** `mcp-proxy` serves each stdio server at its own URL with one bearer
   token and Host and Origin checks, from a single container [34]. ContextForge is the upgrade path if an
   admin UI, RBAC or virtual servers are wanted [36]. MetaMCP is archived [37].
7. **SSH is the riskiest tool, so it stays out of the shared hub.** It runs on c4dev under the CLI agent,
   with approval prompts going straight to that client through elicitation. A proxy in between might not
   relay elicitation; mcp-proxy's README does not say that it does [34][38].

### docker-compose (stack `gui-rag-search`)

Placeholders: `${APPDATA}` is an app dataset on the pool, `${DOCS}` the documents dataset (mounted
read-only), `${MODELS}` a dataset holding the GGUF files, and `${ROUTER_URL}` the OpenAI-compatible router
from b-inference.md. Secrets live in `.env`, which is not committed. GPU stanzas follow the standard Compose
syntax; TrueNAS specifics are in e-truenas.md.

```yaml
name: gui-rag-search

x-gpu: &gpu
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]

networks:
  backend: {}

services:
  postgres:
    image: pgvector/pgvector:0.8.7-pg17
    restart: unless-stopped
    environment:
      POSTGRES_USER: openwebui
      POSTGRES_PASSWORD: ${PG_PASSWORD}
      POSTGRES_DB: openwebui
    volumes:
      - ${APPDATA}/postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U openwebui -d openwebui"]
      interval: 10s
      timeout: 5s
      retries: 10
    networks: [backend]

  llama-embed:
    <<: *gpu
    image: ghcr.io/ggml-org/llama.cpp:server-cuda-b12407
    restart: unless-stopped
    volumes:
      - ${MODELS}/rag:/models:ro
    command: >
      -m /models/Qwen3-Embedding-0.6B-Q8_0.gguf
      --embedding --pooling last
      -a qwen3-embedding-0.6b
      -ngl all -c 16384 -np 4 -b 4096 -ub 4096
      --host 0.0.0.0 --port 8080
      --api-key ${LLAMA_RAG_KEY}
    networks: [backend]

  llama-rerank:
    <<: *gpu
    image: ghcr.io/ggml-org/llama.cpp:server-cuda-b12407
    restart: unless-stopped
    volumes:
      - ${MODELS}/rag:/models:ro
    command: >
      -m /models/bge-reranker-v2-m3-Q8_0.gguf
      --reranking
      -a bge-reranker-v2-m3
      -ngl all -c 8192 -np 4 -b 2048 -ub 2048
      --host 0.0.0.0 --port 8080
      --api-key ${LLAMA_RAG_KEY}
    networks: [backend]

  docling:
    image: ghcr.io/docling-project/docling-serve-cpu:v1.38.2
    restart: unless-stopped
    environment:
      DOCLING_SERVE_API_KEY: ${DOCLING_API_KEY}
      DOCLING_SERVE_MAX_SYNC_WAIT: "600"
      DOCLING_SERVE_ENG_LOC_NUM_WORKERS: "2"
    deploy:
      resources:
        limits:
          memory: 8g          # 4g on the 32 GB tier; see Sizing
    networks: [backend]

  searxng:
    image: docker.io/searxng/searxng:2026.11.15-2d500cb6b
    restart: unless-stopped
    environment:
      SEARXNG_SECRET: ${SEARXNG_SECRET}
      SEARXNG_BASE_URL: http://searxng:8080/
    volumes:
      - ${APPDATA}/searxng/config:/etc/searxng
      - ${APPDATA}/searxng/cache:/var/cache/searxng
    # ports: ["8888:8080"]   # only if you also want to use SearXNG directly from a browser
    networks: [backend]

  open-webui:
    image: ghcr.io/open-webui/open-webui:v0.13.3-slim
    restart: unless-stopped
    depends_on:
      postgres: { condition: service_healthy }
    ports:
      - "3000:8080"
    environment:
      WEBUI_SECRET_KEY: ${WEBUI_SECRET_KEY}           # must be stable (MCP OAuth tokens are encrypted with it)
      WEBUI_URL: http://192.0.2.10:3000                # or the https URL from the reverse proxy
      ENABLE_SIGNUP: "false"                           # leave true until the admin account exists
      ENABLE_PERSISTENT_CONFIG: "false"                # make this file the source of truth (owner decision)
      DATABASE_URL: postgresql://openwebui:${PG_PASSWORD}@postgres:5432/openwebui
      VECTOR_DB: pgvector
      PGVECTOR_INDEX_METHOD: hnsw
      # models
      ENABLE_OLLAMA_API: "false"
      OPENAI_API_BASE_URLS: ${ROUTER_URL}
      OPENAI_API_KEYS: ${ROUTER_KEY}
      # embeddings and reranking
      RAG_EMBEDDING_ENGINE: openai
      RAG_OPENAI_API_BASE_URL: http://llama-embed:8080/v1
      RAG_OPENAI_API_KEY: ${LLAMA_RAG_KEY}
      RAG_EMBEDDING_MODEL: qwen3-embedding-0.6b
      RAG_EMBEDDING_QUERY_PREFIX: "Instruct: Given a search query, retrieve relevant passages that answer the query\nQuery:"
      ENABLE_RAG_HYBRID_SEARCH: "true"
      RAG_HYBRID_BM25_WEIGHT: "0.5"
      RAG_RERANKING_ENGINE: external
      RAG_EXTERNAL_RERANKER_URL: http://llama-rerank:8080/v1/rerank
      RAG_EXTERNAL_RERANKER_API_KEY: ${LLAMA_RAG_KEY}
      RAG_RERANKING_MODEL: bge-reranker-v2-m3
      RAG_TOP_K: "40"
      RAG_TOP_K_RERANKER: "8"
      # chunking and extraction
      ENABLE_MARKDOWN_HEADER_TEXT_SPLITTER: "true"
      CHUNK_SIZE: "1500"
      CHUNK_OVERLAP: "150"
      CHUNK_MIN_SIZE_TARGET: "600"
      CONTENT_EXTRACTION_ENGINE: docling
      DOCLING_SERVER_URL: http://docling:5001
      DOCLING_API_KEY: ${DOCLING_API_KEY}
      # web search
      ENABLE_WEB_SEARCH: "true"
      WEB_SEARCH_ENGINE: searxng
      SEARXNG_QUERY_URL: http://searxng:8080/search
      WEB_SEARCH_RESULT_COUNT: "5"
      # API keys for oikb and the knowledge MCP
      ENABLE_API_KEYS: "true"
    volumes:
      - ${APPDATA}/open-webui:/app/backend/data
    networks: [backend]

  oikb:
    image: ghcr.io/open-webui/oikb:0.6.0
    restart: unless-stopped
    command: daemon
    depends_on: [open-webui]
    environment:
      OPEN_WEBUI_URL: http://open-webui:8080
      OPEN_WEBUI_API_KEY: ${OIKB_OWUI_API_KEY}         # key of a dedicated "indexer" user
      OIKB_API_KEY: ${OIKB_API_KEY}                   # protects /sync and /history
      LOG_FORMAT: json
    volumes:
      - ${APPDATA}/oikb/.oikb.yaml:/app/.oikb.yaml:ro
      - ${DOCS}:/data/docs:ro
    networks: [backend]

  mcp-hub:
    build: ./mcp-hub                                  # Dockerfile below (pins the MCP servers)
    restart: unless-stopped
    command: >
      --pass-environment --host=0.0.0.0 --port=8096
      --allowed-host mcp-hub:8096 --allowed-host 192.0.2.10:8096
      --named-server-config /config/servers.json
    environment:
      MCP_PROXY_AUTH_TOKEN: ${MCP_HUB_TOKEN}
    ports:
      - "8096:8096"
    volumes:
      - ${APPDATA}/mcp-hub/servers.json:/config/servers.json:ro
      - ${DOCS}:/data/docs:ro
    networks: [backend]

  github-mcp:
    image: ghcr.io/github/github-mcp-server:v2.1.0
    restart: unless-stopped
    command: ["http", "--port", "8082", "--read-only"]  # drop --read-only when write tools are wanted
    environment:
      GITHUB_TOOLSETS: "repos,issues,pull_requests,actions"
    ports:
      - "8082:8082"
    networks: [backend]
```

`mcp-hub/Dockerfile` (UNVERIFIED as a build; image tag and packages verified to exist):

```Dockerfile
FROM ghcr.io/sparfenyuk/mcp-proxy:v0.15.0-debian-node
RUN npm install -g mcp-searxng@2.10.1 open-webui-knowledge-mcp-server@0.2.0 \
      @modelcontextprotocol/server-filesystem@2.3.0 \
 && uv tool install mcp-server-fetch==2026.11.11
```

`servers.json` (kept out of git, mode 600; the keys follow mcp-proxy's documented format [34]):

```json
{
  "mcpServers": {
    "searxng": {
      "command": "mcp-searxng",
      "env": { "SEARXNG_URL": "http://searxng:8080", "SEARXNG_MAX_RESULTS": "10",
               "SEARXNG_MAX_RESULT_CHARS": "500", "URL_READ_MAX_CHARS": "20000" }
    },
    "fetch": { "command": "mcp-server-fetch", "args": [] },
    "kb": {
      "command": "open-webui-knowledge-mcp-server",
      "env": { "OPEN_WEBUI_API_URL": "http://open-webui:8080/api/v1",
               "OPEN_WEBUI_API_TOKEN": "<api key of the read-only 'kb-reader' user>" }
    },
    "docs-ro": {
      "command": "mcp-server-filesystem",
      "args": ["--read-only", "/data/docs"]
    }
  }
}
```

Each server is then reachable at `http://192.0.2.10:8096/servers/<name>/mcp` with
`Authorization: Bearer ${MCP_HUB_TOKEN}`. The route layout was checked in mcp-proxy's source [34].

## Options compared

### Web GUIs

| Option | What it is | Fit for this hardware | Maturity (2026-11) | Licence | Verdict |
|---|---|---|---|---|---|
| **Open WebUI 0.13.3** | Multi-user web UI and agent harness. Auth: local, OIDC/OAuth, LDAP, SCIM 2.0, trusted header, RBAC groups. Native tool calling, native MCP (Streamable HTTP only), RAG with 13 vector DBs and 8 extraction engines, hybrid search, reranker, SearXNG, artifacts, Open Terminal, sub-agents, skills, automations [1][3][5][16] | Very good. The slim image needs no GPU and idles at about 300 MiB; ML work runs in separate services [13] | Very active, releases weekly, about 159k stars | BSD-3 + branding clause (since v0.6.6, 2025-04-19). Not OSI. Exempt at 50 or fewer users per 30 days [2] | **Recommended** |
| LibreChat 0.8.8 (v0.8.9-rc1) | Multi-provider chat with agents, subagents, MCP (stdio from YAML, HTTP/SSE from the UI, per-user OAuth), artifacts, code interpreter (ClickHouse/code-interpreter sandbox, Apache-2.0), file search via rag_api and pgvector [17][18][20][21] | Heavier: api, MongoDB, Meilisearch, pgvector, rag_api, admin panel. Web search needs a scraper (Firecrawl) and its rerankers are Jina or Cohere (cloud) or none [19] | Active, monthly stable releases | MIT | Strong second choice. More moving parts and a weaker local RAG |
| AnythingLLM 1.19.0 | All-in-one workspaces, RAG (LanceDB by default; Qdrant, pgvector, Chroma, Milvus), agents, MCP (stdio, SSE, streamable) for agents, built-in llama.cpp engine [22] | Light, a single container | Active | MIT. Telemetry (PostHog) on by default, `DISABLE_TELEMETRY=true` to opt out [22] | Simple, but MCP only in agent mode and less RAG control |
| LobeHub 2.3.3 | Polished chat with plugins and MCP marketplace, knowledge base on pgvector [23] | Heavy: lobehub, gateway, ParadeDB, Redis, RustFS (S3), SearXNG, Elasticsearch [23] | Active | LobeHub Community License (Apache-2.0 plus a commercial licence for derivative works) [23] | Not recommended |
| Jan 0.8.8 | Desktop app with llama.cpp, remote OpenAI-compatible providers, MCP, local API on :1337 [24] | Desktop only, not a server GUI | Active | Apache-2.0 [24] | Optional client on the Mac or Windows |
| Msty Studio | Desktop app with Knowledge Stacks, MCP "Toolbox", personas [25] | Desktop only | Commercial | Proprietary freemium (MCP and Knowledge Stacks "Limited" on the free tier) [25] | Not recommended |
| Onyx CE | RAG-first workspace with 50+ connectors, deep research, its own MCP server for Claude-Code-style clients [26] | Heavy: index, workers, model servers, Redis, MinIO. "Lite" mode cannot index [26] | Active | MIT core. SSO, RBAC and SCIM in the enterprise edition [26] | Consider only if connectors matter more than the chat UI |
| llama.cpp built-in WebUI / Llama app | Browser chat inside `llama-server` with MCP support. llama.cpp 1.0.0 shipped 2026-11-13 [16] | Zero extra services | New | MIT | Fine single-user fallback, but no multi-user or RAG |
| Vane (formerly Perplexica) 1.12.2 | Answer engine on top of SearXNG [49] | Light | Last release 2026-04 | MIT | Niche. Open WebUI's agentic search covers it |

### Vector store (Open WebUI backends)

| Option | Fit | Hybrid search in Open WebUI | Notes | Verdict |
|---|---|---|---|---|
| **pgvector 0.8.7 (Postgres 17)** | One service for app DB and vectors | **Native SQL** (`to_tsvector('simple')` GIN plus vector) [15] | `PGVECTOR_INDEX_METHOD=hnsw`, dimensions up to 2000 (`halfvec` above that) [5] | **Recommended** |
| Qdrant 1.20.1 | Very good, small footprint | BM25 computed in Python over all chunks [15] | Open WebUI recommends it for multi-replica setups; multitenancy mode is on by default [5] | Good second choice |
| Chroma (embedded default) | Fine for one user | Python BM25 | SQLite files, not safe with several replicas [5] | Not for this build |
| Milvus 2.5+ | Heavy (etcd, MinIO) | Native hybrid [5] | Overkill at home | No |

### Embedding and reranker servers

| Option | Embeddings API | Rerank API compatible with Open WebUI `external` | CUDA for Ada | Verdict |
|---|---|---|---|---|
| **llama.cpp `llama-server`** | `/v1/embeddings` (OpenAI) | **Yes**: `/v1/rerank` Jina shape returns `results[].relevance_score` [44] | `server-cuda-*` images | **Recommended** (GGUF, same engine family as the LLMs) |
| HF TEI 1.9.4 | `/v1/embeddings` | **No**: `/rerank` takes `texts`, returns `score` [43] | `89-1.9.4` (Ada) [43] | Embeddings only |
| Infinity 3.0.2-beta | OpenAI-style | Cohere-style rerank (assumed) | yes | Beta line, not needed |
| Ollama | `/api/embed`, `/v1/embeddings` | No rerank endpoint [57] | yes | Embeddings only |
| Open WebUI in-process (SentenceTransformers) | built in | local CrossEncoder | needs the `:cuda` image, not slim | Avoid: it makes the GUI container heavy |

### Document parsers

| Option | What it handles | Footprint | Verdict |
|---|---|---|---|
| **docling-serve 1.38.2 (`-cpu`)** | PDF (layout, tables, OCR), DOCX, PPTX, XLSX, HTML, images, Markdown. Optional picture description by a VLM [12][47] | Large image (about 4.4 GB). CPU-bound; a `-cu128`/`-cu130` GPU build exists [47] | **Recommended**, on the CPU so it does not compete for VRAM |
| Apache Tika 3.3.3.0-full / 4.2.0-full | Broad formats, fast. Tika 4 returns Markdown (`TIKA_SERVER_VERSION=4`) [5][55] | JVM, about 1 GB RAM | Fallback for speed |
| MinerU, Datalab Marker, PaddleOCR-VL, Mistral OCR, Document Intelligence | Supported engines [5] | MinerU and PaddleOCR are GPU-heavy; Mistral and Azure are cloud | No (cloud or VRAM) |

### Web search and page fetching

| Option | Role | Verdict |
|---|---|---|
| **SearXNG (date-tagged image)** | Self-hosted metasearch, JSON API | **Recommended** |
| **Open WebUI `search_web` and `fetch_url`** | GUI's agentic search and full-page fetch. Private IPs blocked unless `ENABLE_LOCAL_WEB_FETCH=true` [5][11] | Use |
| **mcp-searxng 2.10.1** | MCP tools `searxng_web_search` and `web_url_read` (HTML/PDF to text, cache, optional FlareSolverr) [31] | CLI agent's WebSearch/WebFetch |
| **mcp-server-fetch 2026.11.11** | Official fetch MCP. Obeys robots.txt for model requests, refuses private and loopback IPs by default, `--allowed-hosts` [32] | Second fetch path for the CLI agent |
| Playwright remote browser (`WEB_LOADER_ENGINE=playwright`, `PLAYWRIGHT_WS_URL`) | JS-rendered pages for the GUI [5] | Add only if many sites need JS |
| crawl4ai 0.9.5 (self-hosted, Apache-2.0) | REST plus MCP (SSE/WS at `/mcp/sse`), token required [49] | Optional JS crawler; bridge SSE through mcp-proxy |
| Firecrawl 2.11 (AGPL-3.0, self-hostable) | Scraper; needed by LibreChat's web search [19] | Only with LibreChat |
| Jina Reader (`r.jina.ai`) | **Cloud** | Not on the core path |
| Brave Search API / Tavily | Paid fallback: Brave $5 per 1,000 requests with $5 monthly credit; Tavily 1,000 free credits a month, then $0.008 a credit [54] | Optional |

### MCP gateway or hub

| Option | What it is | Licence, release | Verdict |
|---|---|---|---|
| **sparfenyuk/mcp-proxy 0.15.0** | stdio to Streamable HTTP/SSE; many named servers at `/servers/<name>/mcp`; bearer token; Host and Origin checks [34] | MIT, 2026-11-07 | **Recommended** |
| mcpo (Open WebUI) 0.0.20 | MCP to OpenAPI bridge [4] | MIT, last release 2026-02 | Not needed: Open WebUI has native MCP |
| IBM ContextForge 1.1.1 | Registry and proxy, admin UI, JWT auth, virtual servers, federation, translate stdio to SSE or HTTP [36] | Apache-2.0, `ghcr.io/ibm/mcp-context-forge:v1.1.1` | Upgrade path if RBAC or UI is wanted |
| Docker MCP Gateway 0.44.3 | Runs each catalog server in its own container; `docker mcp gateway run --transport streaming` [35] | MIT | Needs the Docker socket; not on TrueNAS |
| supergateway 4.2.2, TBXark/mcp-proxy 1.1.0, 1mcp 0.39.9, MCPJungle 0.4.7, agentgateway 1.7.0 | Other bridges and aggregators | MIT / Apache / MPL | Alternatives |
| MetaMCP | Aggregator | **Archived** (last release 2025-12) [37] | No |

### SSH MCP servers

| Option | Security controls | Licence, release | Verdict |
|---|---|---|---|
| **tufantunc/ssh-mcp 2.26.0** (`npm ssh-mcp`) | Command classification; role × tier policy; `denylist`; approval through MCP elicitation (`ask-destructive`, `ask-all`, `deny`; refuses with `APPROVAL_UNAVAILABLE` if the client cannot elicit); host-key `tofu` / `strict` / pinned `trustedHostKey`; no secrets on the CLI; SSH agent, keychain or key file; ProxyJump (`via`); CA certificates; quotas; JSONL audit with redaction and an optional hash chain; HTTP mode needs a bearer token [38] | MIT, 2026-11-12, OpenSSF badges | **Recommended** |
| classfang/ssh-mcp-server 1.10.0 (`@fangjunjie/ssh-mcp-server`) | Regex whitelist and blacklist (whitelist rejects `; & \| $() > <`), `--allowed-remote-paths`, `--allowed-local-paths`, HTTP token. **No host-key verification found in the source** [39] | ISC, 2026-10-09 | Acceptable only on a trusted LAN with a whitelist |
| bvisible/mcp-ssh-manager 4.2.0 | Many tools (transfer, management) | MIT, 2026-11-13 | Not assessed in depth |
| samerfarida/mcp-ssh-orchestrator, n0madic/ssh-mcp, oaslananka/ssh-mcp-pro | Policy and allow-lists, but tiny user base (2–30 stars) | various | No |

### Other MCP servers (verified names)

| Need | Server | Package / image | Notes |
|---|---|---|---|
| Filesystem | Official `server-filesystem` 2.3.0 | `npx @modelcontextprotocol/server-filesystem`, image `mcp/filesystem` | `--read-only`, `--read-only-dir`; allowed dirs on the command line [32] |
| Git | Official `mcp-server-git` 2026.11.11 | `uvx mcp-server-git --repository <path>`, image `mcp/git` | Confine with `--repository`; never runs repo hooks or config programs [32] |
| GitHub | `github/github-mcp-server` 2.1.0 | `ghcr.io/github/github-mcp-server:v2.1.0` | `stdio` or `http` (port 8082); `--toolsets`, `--read-only`, `--lockdown-mode`; in HTTP mode the PAT comes from the client's `Authorization` header [33] |
| Databases | `bytebase/dbhub` (1.6.x) | `npx @bytebase/dbhub`, image `bytebase/dbhub:1.6.0` | Postgres, MySQL, MariaDB, MSSQL, Oracle, SQLite; `--transport http --auth-token`; TOML `readonly = true`, `max_rows` [50]. Official example in Claude Code's docs |
| Docker | `mcp-server-docker` 0.3.0 (ckreiling) | `uvx mcp-server-docker` | GPL-3.0. Pair with `tecnativa/docker-socket-proxy:v0.5.0` (`POST=0`, `CONTAINERS=1`) for read-only use [51] |
| Document conversion | `docling-mcp` 3.5.0 | `uvx --from docling-mcp docling-mcp-server --transport streamable-http` | Lets the CLI agent turn PDFs and Office files into Markdown [48] |
| Knowledge base (shared index) | `RonasIT/open-webui-mcp-server` 0.2.0 | `npx open-webui-knowledge-mcp-server` | Tools `list_knowledge_bases`, `search_knowledge_base`, `get_knowledge_base_info`; stdio or HTTP (`MCP_TRANSPORT=http`) [41]. Small project (12 stars) but only about 150 lines; easy to fork |

## Details

### D1. Open WebUI setup facts

- **Images** [13][56]: `:main` (about 1.62 GB, bundled ML), `:slim`/`:main-slim` (about 197 MB, no local ML;
  `VECTOR_DB` defaults to pgvector; the `token_transformers` splitter is unavailable), `:cuda` (CUDA 12.8),
  `:cuda126`, `:ollama`. Version-pinned tags exist: `v0.13.3`, `v0.13.3-slim`, `v0.13.3-cuda`,
  `v0.13.3-ollama`. The container listens on 8080; data lives in `/app/backend/data`.
- **First run:** start with `ENABLE_SIGNUP=true` and create the admin at `http://192.0.2.10:3000` (the first
  account becomes admin). Then set `ENABLE_SIGNUP=false`. `DEFAULT_USER_ROLE` defaults to `pending`, so any
  later sign-up waits for approval [5].
- **Persistent config:** `ENABLE_PERSISTENT_CONFIG` defaults to `True`, so settings saved in the admin UI
  override environment variables from then on. Set it to `false` if the compose file in this repository is
  to stay authoritative, at the cost of UI edits being lost on restart [5].
- **`WEBUI_SECRET_KEY`** must be fixed. Otherwise OAuth-connected MCP tools fail after every restart with
  "Error decrypting tokens" [3].
- **MCP connections** are configured in the UI under Settings > Integrations > External Tool Servers >
  Add Connection > Type **MCP (Streamable HTTP)**. Only admins can add them; Access Control scopes them to
  users or groups. Auth modes: None, Bearer, Session, OAuth, OAuth 2.1 (dynamic client registration) and
  OAuth 2.1 Static. Choose None or Bearer for the hub: Bearer with an empty key sends a bare
  `Authorization: Bearer` header that servers reject. Tools appear to the model as `<server id>_<tool>`.
  Use the Function Name Filter List to expose only some tools. `MCP_INITIALIZE_TIMEOUT` defaults to 10 s;
  raise it for slow `npx` cold starts [3]. `TOOL_SERVER_CONNECTIONS` (JSON in an environment variable) is
  documented for OpenAPI/mcpo connections. Seeding MCP-type connections through it is **UNVERIFIED**, so
  add them in the UI and record them in the guide [5].
- **Elicitation** (an MCP server asking the user) shows a dialog that waits up to 120 s, and only while
  that chat is the open tab [3].
- **Code execution:** `CODE_EXECUTION_ENGINE` and `CODE_INTERPRETER_ENGINE` (`pyodide` or `jupyter`) are
  marked legacy. Use **Open Terminal** (`ghcr.io/open-webui/open-terminal`, MIT, v0.17.17): run it in
  Docker with `OPEN_TERMINAL_API_KEY`, resource limits and an admin-configured connection [5][14]. Its
  coding-agents feature lists Claude Code, Codex, Cursor, Grok, OpenCode, Cline, Gemini CLI and Pi in the
  model picker. That is the bridge to c-agents.md's harness inside the GUI [14].
- **Pipelines** (`open-webui/pipelines`) is **archived** (2026-10-29). Use in-app Functions (pipes,
  filters, actions) instead [58].
- **API keys:** `ENABLE_API_KEYS=true`. Non-admin users also need the "API Keys" permission.
  `ENABLE_API_KEYS_ENDPOINT_RESTRICTIONS` with `API_KEYS_ALLOWED_ENDPOINTS` can limit what keys may call.
  Whether entries are prefixes is **UNVERIFIED**, so test it before relying on it [5].

### D2. RAG pipeline

**Ingestion path.** Each file is extracted by docling (`CONTENT_EXTRACTION_ENGINE=docling`), split on
Markdown headers, sized with the character or token splitter, small chunks merged forward up to
`CHUNK_MIN_SIZE_TARGET`, embedded through `/v1/embeddings` in batches (1,000 chunks by default since
0.12.5) and written to pgvector [1][6]. Defaults are `CHUNK_SIZE=1024`, `CHUNK_OVERLAP=100` and
`CHUNK_MIN_SIZE_TARGET=0`. The doc's own example of a good setting is a target of 1000 for a chunk size of
2000 [5][6]. Starting point for mixed manuals and notes: 1500/150/600.

**Retrieval path.** Hybrid search sets `ENABLE_RAG_HYBRID_SEARCH=true` and `RAG_HYBRID_BM25_WEIGHT`
(default 0.5). It takes `RAG_TOP_K` candidates (default 10, use 40), reranks them through
`RAG_EXTERNAL_RERANKER_URL` (the full URL including `/v1/rerank`) and keeps `RAG_TOP_K_RERANKER` (default
10, use 8). `RAG_RELEVANCE_THRESHOLD` defaults to 0 [5]. Files under `RAG_FULL_TEXT_CHAR_THRESHOLD`
(50,000 characters by default) attached in chat are injected whole. Knowledge bases always use retrieval
[5]. In native tool-calling mode the model calls `query_knowledge_bases` itself. `ENABLE_KB_EXEC` adds a
`kb_exec` tool with `ls`, `cat`, `grep`, `find` and similar over a knowledge base [5].

**Embedding model.** Qwen3-Embedding-0.6B: 0.6B parameters, 32k context, up to 1024 dimensions (MRL from
32 to 1024), instruction-aware. Queries take the form `Instruct: <task>\nQuery:<query>`; documents take no
prefix [45]. Open WebUI supports this through `RAG_EMBEDDING_QUERY_PREFIX` and
`RAG_EMBEDDING_CONTENT_PREFIX` (also under Settings > Documents > Advanced) [5]. The GGUF card's own
server command is `llama-server -m model.gguf --embedding --pooling last -ub 8192` [45]. 1024 dimensions
fits pgvector's default `PGVECTOR_INITIALIZE_MAX_VECTOR_LENGTH=1536` [5]. **Changing the embedding model
means pressing Reindex** (Settings > Documents). Files attached directly to chats are not reindexed [6].

**Reranker.** bge-reranker-v2-m3 GGUF Q8_0 (636 MB), served with `--reranking`. A bidirectional reranker
must fit the whole query plus document in `--ubatch-size`, so keep `-ub` at least the largest chunk in
tokens plus the query [44][46]. Qwen3-Reranker-0.6B Q8_0 (`ggml-org`, 639 MB, Apache-2.0) is the
alternative to evaluate [46].

**Sizes and VRAM.** About 0.64 GB of weights each, plus compute buffers that grow with `-ub` and `-c`.
Plan on 1.5–2.5 GB of VRAM for both (assumed; measure with `nvidia-smi`). To give all 16 GB to the coding
model, drop the `<<: *gpu` anchors and pass `-ngl 0`. Query-time latency stays acceptable on the CPU; bulk
ingestion gets slower (assumed). b-inference.md owns the VRAM budget.

**NAS folder sync (oikb).** Bind the dataset read-only into the oikb container. Create knowledge bases in
Workspace > Knowledge and copy their IDs from the URL. Give a dedicated "indexer" user write access to them
and create its API key. `.oikb.yaml`:

```yaml
defaults:
  interval: 15m
  concurrency: 4
  filter:
    max-size: 100mb
    exclude: ["**/.git/**", "**/node_modules/**", "**/.zfs/**", "**/@eaDir/**", "**/~$*", "**/*.tmp", "**/.DS_Store"]
sources:
  - name: documents
    source: /data/docs/documents
    kb-id: ${KB_DOCUMENTS_ID}
  - name: manuals
    source: /data/docs/manuals
    kb-id: ${KB_MANUALS_ID}
    interval: "0 3 * * *"
  - name: project-docs
    source: github:OWNER/REPO          # private repos need GITHUB_TOKEN in the environment
    kb-id: ${KB_PROJECT_DOCS_ID}
    filter: { include: ["docs/**", "*.md", "adr/**"] }
```

Behaviour [8][9]: SHA-256 manifest to `POST /api/v1/knowledge/{id}/sync/diff`, then upload of the added
and modified files, then `sync/cleanup`. Locking is per knowledge base. `GET /health` and `/metrics` are
public; `/sync/{name}` and `/history` need `OIKB_API_KEY`. `oikb watch <dir> --kb-id …` uses filesystem
events with a 1 s debounce, but the daemon's interval is the robust choice on a NAS. Server-side limits
`RAG_FILE_MAX_SIZE` and `RAG_ALLOWED_FILE_EXTENSIONS` reject files on every sync until they are filtered
out [8]. Where oikb keeps its history SQLite inside the container is **UNVERIFIED**; mount a volume once
the path is known.

**Code repositories.** Index documentation, ADRs and READMEs, not whole source trees. The CLI agent greps
code better than embeddings retrieve it (assumed, common practice). oikb's GitHub connector reads through
the Trees API without cloning [8].

**What the CLI agent sees.** The `kb` MCP server lists knowledge bases and runs `search_knowledge_base(id,
query, k=5)`, which calls `POST /api/v1/retrieval/query/collection`. With hybrid search enabled, that
handler runs `query_collection_with_hybrid_search` (BM25, vector and reranker) [15][41]. Give the CLI
agent the key of a separate **read-only "kb-reader" user** with read access only to the knowledge bases it
should see. Open WebUI keys act as that user and do not bypass access control [8].

### D3. SearXNG

`${APPDATA}/searxng/config/settings.yml` (merged over the defaults; engine entries merge by `name` [30]):

```yaml
use_default_settings: true
general:
  instance_name: "searxng-local"
server:
  # secret_key comes from SEARXNG_SECRET; base_url from SEARXNG_BASE_URL
  limiter: false            # private LAN instance; the limiter would also block API clients
  public_instance: false
  image_proxy: false
  method: "GET"
search:
  safe_search: 0
  autocomplete: ""
  formats:
    - html
    - json                  # required: without it Open WebUI and mcp-searxng get 403
outgoing:
  request_timeout: 5.0
engines:                    # defaults kept; enable coding sources that ship disabled
  - name: npm
    disabled: false
  - name: crates.io
    disabled: false
  - name: pkg.go.dev
    disabled: false
  - name: gitlab
    disabled: false
  - name: codeberg
    disabled: false
  - name: huggingface
    disabled: false
  - name: hackernews
    disabled: false
```

Facts [27][28][29]: the official compose (`container/docker-compose.yml`) runs `searxng-core` from
`docker.io/searxng/searxng:${SEARXNG_VERSION:-latest}` on port 8080, with `searxng-valkey`
(`valkey/valkey:9-alpine`) next to it. The image is mirrored at `ghcr.io/searxng/searxng`; Docker Hub
rate-limits anonymous pulls. Volumes are `/etc/searxng` (config) and `/var/cache/searxng` (favicon cache).
Environment overrides include `SEARXNG_SECRET`, `SEARXNG_BASE_URL`, `SEARXNG_LIMITER`,
`SEARXNG_PUBLIC_INSTANCE`, `SEARXNG_VALKEY_URL`, `SEARXNG_PORT` and `SEARXNG_BIND_ADDRESS`.
`FORCE_OWNERSHIP` (default true) chowns mounted volumes. Valkey is needed only when the limiter is
enabled. If you expose SearXNG publicly, set `limiter: true` with `valkey.url: valkey://searxng-valkey:6379/0`
and put the Docker subnet and LAN in `limiter.toml` `[botdetection.ip_lists] pass_ip`.

Default engine state on master [29]: general results come from DuckDuckGo, Brave, Wikipedia and Wikidata.
**Google, Bing and Qwant ship disabled**; Startpage and Mojeek are inactive. IT sources on by default
include GitHub, Stack Overflow, Ask Ubuntu, Super User, PyPI, Docker Hub, MDN, Arch Wiki and arXiv. Engines
get suspended after CAPTCHAs (for example `SearxEngineCaptcha: 3600` s), which is the main reliability risk
of the setup.

Test: `docker exec open-webui curl -s 'http://searxng:8080/search?q=test&format=json' | head -c 300`.

### D4. MCP client configuration for the CLI agent (Claude-Code-style `.mcp.json`)

The `mcpServers` JSON format with `type: "http"` is accepted by Claude Code (`streamable-http` is accepted
as an alias) and by most harnesses in c-agents.md [53]. Keep tokens in environment variables.

```json
{
  "mcpServers": {
    "search":  { "type": "http", "url": "http://192.0.2.10:8096/servers/searxng/mcp",
                 "headers": { "Authorization": "Bearer ${MCP_HUB_TOKEN}" } },
    "fetch":   { "type": "http", "url": "http://192.0.2.10:8096/servers/fetch/mcp",
                 "headers": { "Authorization": "Bearer ${MCP_HUB_TOKEN}" } },
    "kb":      { "type": "http", "url": "http://192.0.2.10:8096/servers/kb/mcp",
                 "headers": { "Authorization": "Bearer ${MCP_HUB_TOKEN}" } },
    "github":  { "type": "http", "url": "http://192.0.2.10:8082",
                 "headers": { "Authorization": "Bearer ${GITHUB_PAT}", "X-MCP-Toolsets": "repos,issues,pull_requests",
                              "X-MCP-Readonly": "true" } },
    "ssh":     { "type": "stdio", "command": "ssh-mcp", "args": ["--hostKeyMode=strict"] }
  }
}
```

The same hub URLs go into Open WebUI as MCP (Streamable HTTP) connections with Auth set to Bearer, using
the docker-network address `http://mcp-hub:8096/servers/<name>/mcp`. For the GUI, add `github` and,
optionally, `docs-ro`. The GUI already has native SearXNG, fetch and knowledge tools, so it needs no
`search`, `fetch` or `kb` connection.

For a SearXNG MCP that runs without the hub, `mcp-searxng` has its own hardened HTTP mode:
`MCP_HTTP_PORT`, `MCP_HTTP_HOST`, `MCP_HTTP_HARDEN=true` with `MCP_HTTP_AUTH_TOKEN` and
`MCP_HTTP_ALLOWED_ORIGINS`, and `MCP_HTTP_ALLOWED_HOSTS`, which match the Host header exactly, port
included. It also has an image, `isokoliuk/mcp-searxng:2.10.1`. `SEARXNG_LITE_TOOLS=true` shrinks tool
schemas for small-context local models [31].

### D5. SSH to remote environments, safely

**Client side (c4dev), `ssh-mcp` 2.26.0** [38]:

- Install with `npm install -g ssh-mcp@2.26.0`. There is no published image; the repository's Dockerfile
  runs as UID 65532 on `node:22-slim`.
- Config lives at `~/.config/ssh-mcp/config.toml` (mode 600, directory 700).
- Run it as stdio from the CLI agent: `claude mcp add --transport stdio ssh-mcp -- ssh-mcp` is the upstream
  example. Use the equivalent in the chosen harness.
- Start with `--hostKeyMode=strict` and pin every host with `trustedHostKey = "SHA256:…"`. The default
  `tofu` mode trusts the first key seen and forgets it on restart.
- The audit log goes to `$XDG_DATA_HOME/ssh-mcp/audit.log` (`~/.local/share/ssh-mcp/audit.log`). Add
  `--auditTamperEvident` for a hash chain.

```toml
[defaults]
defaultProfile = "lab"
approvalMode = "ask-destructive"     # use "ask-all" for anything that matters
commandTimeoutMs = 60000
commandQuotaPerDay = 300
approvalGrantTtlMs = 0

[[profiles]]
name = "bastion"
host = "bastion.lan.example"
user = "agent-jump"
auth = "agent"
trustedHostKey = "SHA256:<bastion-host-key>"

[[profiles]]
name = "lab"
host = "192.0.2.30"
user = "agent"
auth = "agent"                        # an ssh-agent holding only the agent key
via = "bastion"
group = "dev"
role = "operator"
tty = false
trustedHostKey = "SHA256:<lab-host-key>"

[policy]
denylist = ["\\.ssh/authorized_keys", "^\\s*shutdown", "^\\s*reboot", "mkfs", "\\bdd\\s+if="]
```

Approval needs a client that supports MCP elicitation. Without it, destructive and privileged commands are
refused with `APPROVAL_UNAVAILABLE`, which is fail-closed [38]. Check whether the harness in c-agents.md
supports elicitation. If it does not, use a `readOnly = true` profile plus host-side forced commands.

**Host side (each remote host):**

1. **Key per agent.** Generate it with `ssh-keygen -t ed25519 -f ~/.ssh/agent_ed25519 -C agent@c4dev` on
   c4dev. Use it only in a dedicated `ssh-agent` (`SSH_AUTH_SOCK` for the agent process). Never reuse the
   owner's key.
2. **Restricted user.** Create `agent`: no password, not in `sudo`/`wheel`, and a `sudoers.d` entry only
   for specific commands if needed (never `NOPASSWD: ALL`) [38].
3. **`authorized_keys` options** [52]: `restrict` turns off port, agent and X11 forwarding, PTY and
   `~/.ssh/rc`. `from=` pins the client address. `command=` forces a wrapper that receives the requested
   command in `SSH_ORIGINAL_COMMAND`. `expiry-time=` makes the key lapse.

   ```
   restrict,from="192.0.2.20",expiry-time="20270515",command="/usr/local/bin/agent-gate" ssh-ed25519 AAAA… agent@c4dev
   ```

   `agent-gate` logs `SSH_ORIGINAL_COMMAND` with `logger -t agent-gate`, rejects shell metacharacters
   (`; & | $( ) \` > <` and newlines, as classfang's whitelist does [39]), checks an allow-list of command
   prefixes, then `exec`s the command. With a forced command, SFTP only works if the gate allows the
   `internal-sftp`/`sftp-server` request. With `restrict`, interactive sessions get no PTY, so set
   `tty = false` in ssh-mcp.
4. **`sshd_config`** [52]:

   ```
   Match User agent
       AuthenticationMethods publickey
       DisableForwarding yes
       PermitTTY no
       ForceCommand /usr/local/bin/agent-gate
   # File-transfer-only variant:
   # Match User agent-xfer
   #     ChrootDirectory /srv/agent-xfer      # every path component root-owned, not group/world-writable
   #     ForceCommand internal-sftp
   ```

   Add `AllowUsers` or `AllowGroups` covering the agent user. `ForceCommand` overrides `command=` and does
   not by itself block forwarding, hence `DisableForwarding` [52].
5. **Short-lived certificates (optional).** With `TrustedUserCAKeys /etc/ssh/agent_ca.pub` on hosts, sign
   the agent key for a few hours, for example `ssh-keygen -s agent_ca -I agent-c4dev -n agent -V +8h
   agent_ed25519.pub`. ssh-mcp picks up `<key>-cert.pub` with `cert = true` [38][52].
6. **Jump host.** Only c4dev reaches the bastion; targets accept SSH only from the bastion. The bastion
   line for the agent key is `restrict,port-forwarding,permitopen="192.0.2.30:22" ssh-ed25519 …`:
   forwarding is re-enabled but limited to the listed targets [52]. That ProxyJump's `-W` stream counts as
   a `permitopen`-governed forward is **assumed** (standard OpenSSH behaviour). ssh-mcp's `via` makes a
   TCP tunnel without agent forwarding [38].
7. **Audit.** Keep `sshd` logs (`journalctl -u ssh`), the `agent-gate` syslog tag, sudo I/O logging
   (`Defaults:agent log_output`, replay with `sudoreplay`, assumed) and the ssh-mcp JSONL audit on c4dev.
   Optionally ship them off-host. ssh-mcp also sends `AI_AGENT=ssh-mcp` to hosts unless
   `announceAgent = false` [38].
8. **Never** point the agent at TrueNAS's own root, middleware or the Docker socket.

### D6. Docker and database tools

- **Docker:** a Docker-socket MCP is root-equivalent on the host. Prefer ssh-mcp to a dev VM. If container
  visibility is needed, run `tecnativa/docker-socket-proxy:v0.5.0` with `CONTAINERS=1`, `POST=0` (GET and
  HEAD only), and point `mcp-server-docker` (`DOCKER_HOST=tcp://socket-proxy:2375`) at it. Write tools
  then fail by design [51].
- **Databases:** DBHub with a TOML file declaring `[[tools]] name="execute_sql" readonly=true
  max_rows=1000` per source, served as `--transport http --auth-token …`, with `/healthz` left unauthenticated
  [50]. Use a database role that is read-only at the SQL level too.

### D7. Sizing per system-RAM tier (assumed, not measured, except where cited)

| Service | 32 GB tier | 64 GB tier | 128 GB tier |
|---|---|---|---|
| open-webui (slim) | 1 GB (300 MiB idle measured by vendor [13]) | 2 GB | 2 GB |
| postgres + pgvector | 1 GB | 2 GB | 4 GB (more `shared_buffers`) |
| docling (CPU) | 4 GB limit, 1 worker | 8 GB, 2 workers | 12 GB, 4 workers, optional picture description |
| llama-embed and llama-rerank | GPU about 2 GB VRAM, about 1 GB RAM | same | CPU-only possible, frees VRAM |
| searxng (+ valkey) | 0.3 GB | 0.3 GB | 0.3 GB |
| mcp-hub (4 servers) | 0.5–1 GB | 1 GB | 1 GB |
| oikb, github-mcp | 0.3 GB | 0.3 GB | 0.3 GB |
| **Total for this stack** | **about 8–9 GB** | **about 15 GB** | **about 20 GB** |

On 32 GB, the LLM's CPU offload (b-inference.md) gets what is left. Run docling ingestion at night through
oikb's cron intervals.

### D8. Known problems and fixes

- **SearXNG 403 in Open WebUI logs:** `json` is missing from `search.formats` [10].
- **Empty search results:** upstream engines suspended after CAPTCHAs. Check `/stats` or the logs, enable
  more engines, or add the Brave API as a fallback [29][54].
- **"Failed to connect to MCP server":** Bearer chosen with an empty key; an empty Function Name Filter
  (put `,` in it); an OAuth 2.1 tool set as a default tool; or a slow cold start (raise
  `MCP_INITIALIZE_TIMEOUT`) [3].
- **UI stuck loading after adding a tool server:** an MCP server was added as type OpenAPI. Disable it in
  Settings > Integrations and re-add it as MCP [3].
- **Reranker errors:** `RAG_EXTERNAL_RERANKER_URL` must include `/v1/rerank` [5]. Inputs longer than
  `-ub` fail in llama.cpp, so raise `-ub` [44].
- **Retrieval quality collapses after a model change:** press Reindex. Chat-attached files keep their old
  vectors [6].
- **oikb keeps re-uploading files:** files uploaded before Open WebUI 0.9.6 have no stored hash and are
  replaced once [8]. Files rejected by size or extension fail every run; exclude them in `filter` [8].
- **Docling timeouts on large PDFs:** raise `DOCLING_SERVE_MAX_SYNC_WAIT` (default 120 s) and the job
  timeouts [47].
- **mcp-proxy on 0.0.0.0** refuses requests whose Host is not in `--allowed-host`; list every
  `host:port` clients use [34].
- **Settings in compose "ignored":** `ENABLE_PERSISTENT_CONFIG=true` means the database wins [5].

## Fit with Claude Code features

| Claude Code feature | Local equivalent | How close | What is lost |
|---|---|---|---|
| **WebSearch** (Anthropic backend; up to 8 backend searches per call; `allowed_domains`/`blocked_domains`; 200 searches per session) [53] | CLI: `mcp-searxng` `searxng_web_search`. GUI: Open WebUI `search_web` [11][31] | Good for common queries | Result quality depends on upstream engines and CAPTCHA suspensions. No internal query refinement (the model must re-query). Domain scoping only through `site:` operators in the query (assumed). Claude Code's own docs say the search backend is not configurable and point to an MCP search server as the substitute [53] |
| **WebFetch** (HTML to Markdown, then a secondary model extracts per prompt; 100k characters per call; 15-min cache; refuses localhost; per-domain permission rules) [53] | CLI: `web_url_read` (24 h cache, `URL_READ_MAX_CHARS`, PDF support) or `mcp-server-fetch` (private IPs refused, robots.txt, `--allowed-hosts`, `max_length` paging) [31][32]. GUI: `fetch_url` with `ENABLE_LOCAL_WEB_FETCH=false` [5][11] | Good | No secondary-model summarisation: raw Markdown lands in a small local context, so use the length caps. Per-domain permission prompts become a server-side allow-list or the harness's per-tool approval |
| **Reading PDFs** (Read tool; pages rendered with `pdftoppm`, read visually, 20 pages per call) [53] | Text: docling (GUI ingestion and `docling-mcp` for the CLI), `web_url_read` for remote PDFs [31][47][48] | Text and tables good; layout good with docling | No native visual reading of figures unless a VLM is configured (a-models.md), for example docling picture description. Scanned PDFs depend on OCR quality |
| **MCP** (stdio, http/streamable-http, sse deprecated, ws; local, project `.mcp.json` and user scopes; OAuth; `mcp__server__tool` permissions) [53] | Hub over Streamable HTTP with a bearer token; Open WebUI native MCP (HTTP only, admin-added, OAuth 2.1, elicitation, MCP Apps) [3][34] | Close | Open WebUI cannot run stdio servers; the hub does that. Per-tool permission granularity depends on the CLI harness (c-agents.md). mcp-proxy's bearer token carries no per-user identity [34] |
| **Remote hosts over SSH** (Claude Code uses `ssh` through Bash with permission prompts) | `ssh-mcp` with policy, elicitation approval, host pinning and audit [38] | Stronger controls than plain Bash ssh | Approval needs elicitation support in the harness. Interactive TTY sessions are limited under `restrict` |
| **GitHub integration** (`gh` CLI, GitHub MCP) | Same `gh` on c4dev plus `github-mcp-server` HTTP with read-only and lockdown modes [33] | Equal | None |
| **RAG over own documents** (not in Claude Code) | Open WebUI knowledge bases plus the `kb` MCP for the CLI [15][41] | New capability | — |

## Verified vs assumed

**Verified** (primary source read 2026-11-15):

- Open WebUI latest is v0.13.3 (2026-11-08). The 0.13.x features listed (terminal workspace, MCP Apps,
  tool approval modes, full-text threshold) [1].
- The licence terms: BSD-3 through v0.6.5; branding clause from v0.6.6 (2025-04-19); exempt at 50 or fewer
  users per 30 days; not OSI [2].
- Native MCP: Streamable HTTP only, admin-only, the auth modes, elicitation dialog (120 s), stateless
  2026-07-28 protocol revision supported, mcpo for stdio/SSE [3][4].
- Every Open WebUI environment variable used above, with its defaults (`VECTOR_DB` options,
  `RAG_EMBEDDING_ENGINE` options, the `RAG_*` and `CHUNK_*` defaults, `SEARXNG_QUERY_URL`,
  `WEB_LOADER_ENGINE` options, `ENABLE_PERSISTENT_CONFIG=True`, `ENABLE_API_KEYS=False`,
  `ENABLE_LOCAL_WEB_FETCH=False`, `DEFAULT_USER_ROLE=pending`) [5].
- In Open WebUI's source: pgvector has native hybrid search (GIN `to_tsvector`) and Qdrant does not;
  `/retrieval/query/collection` uses hybrid search when enabled; the external reranker sends
  `{model, query, documents, top_n}` and reads `results[].relevance_score` [15].
- Image tags exist on GHCR or Docker Hub: `open-webui:v0.13.3-slim`, `oikb:0.6.0`,
  `mcp-proxy:v0.15.0-debian-node`, `github-mcp-server:v2.1.0`, `llama.cpp:server-cuda-b12407`,
  `docling-serve-cpu:v1.38.2`, `docling-serve-cu128:v1.38.2`, `text-embeddings-inference:89-1.9.4`,
  `searxng:2026.11.15-2d500cb6b` (amd64/arm64/arm), `valkey:9.0.7-alpine`, `pgvector:0.8.7-pg17`,
  `qdrant:v1.20.1`, `apache/tika:3.3.3.0-full` and `4.2.0-full`, `dbhub:1.6.0`,
  `docker-socket-proxy:v0.5.0`, `mcp-context-forge:v1.1.1`, `mcp-searxng:2.10.1` [55][56].
- oikb features, config keys, endpoints, image and the Open WebUI 0.9.6+ requirement [8][9].
- SearXNG compose layout, settings keys, the `use_default_settings` merge rules and default engine states
  [27]–[30].
- mcp-searxng tools and environment variables [31]. The official fetch, filesystem and git servers'
  behaviour and flags [32]. GitHub MCP server toolsets, read-only, lockdown and HTTP mode [33].
- mcp-proxy flags, auth token and routes [34]. ContextForge features [35][36]. MetaMCP archived [37].
- ssh-mcp features, flags, config keys and audit path. classfang has no host-key verification
  (source grep) [38][39].
- llama.cpp `--embedding`, `--pooling`, `--reranking`, `/v1/rerank` formats, `-ub` requirement, default
  port 9931 in current docs [44]. TEI endpoints and Ada tag [43].
- Qwen3-Embedding-0.6B specs and GGUF server command; model licences; GGUF sizes [45][46].
- docling-serve image variants and environment variables [47]. OpenSSH `authorized_keys` options and
  `sshd_config` keywords [52]. Claude Code WebSearch, WebFetch, PDF and MCP behaviour [53]. Brave and Tavily
  prices [54].
- LibreChat stack images, rag_api, MCP and web-search requirements and code-interpreter backend [17]–[21].
  AnythingLLM features and telemetry [22]. LobeHub licence and services [23]. Jan licence [24]. Onyx
  editions [26]. Pipelines archived [58].

**Assumed** (inference, memory or secondary sources):

- VRAM and RAM figures in D7 (except Open WebUI slim idle RAM).
- That mcp-proxy may not relay elicitation, which is why SSH is kept out of the hub.
- That `search_web` domain scoping works through `site:` in SearXNG queries.
- That ProxyJump `-W` is governed by `permitopen`.
- sudo I/O logging details.
- That embedding and reranking on the CPU is acceptable for queries.
- Code-repo RAG being less useful than grep.
- Infinity's rerank API shape.
- That Open WebUI's MCP client works with mcp-proxy's endpoints (widely reported, not tested here).
- That the `github-mcp-server` image's entrypoint accepts `http` as its command, and its default bind
  address.
- The `mcp-hub` Dockerfile build: binary names on PATH and the image's user.
- LibreChat LDAP support and AnythingLLM reranking details. Msty's licence being proprietary.
- The Vane row in the GUI table rests on the GitHub repository only.

**UNVERIFIED** (could not confirm):

- Seeding MCP-type connections through `TOOL_SERVER_CONNECTIONS`.
- Whether `API_KEYS_ALLOWED_ENDPOINTS` entries match by prefix.
- oikb's history database path inside the container.
- The mcp-hub Dockerfile as a whole.

## Open questions for the owner

1. **Who uses the GUI?** Only you, or family too? This decides whether to enable OIDC SSO and how to split
   knowledge-base access.
2. **Which NAS datasets get indexed,** and is anything sensitive that some GUI users must not retrieve?
3. **Should the GUI get "hands"?** Open Terminal, a writable GitHub MCP and SSH could be limited to the
   CLI agent, as recommended, or also given to the GUI for your admin account.
4. **Compose as source of truth** (`ENABLE_PERSISTENT_CONFIG=false`, settings changed only through the
   repository) versus editing settings in the admin UI.
5. **Embedder and reranker on the GPU** (about 2 GB VRAM, faster ingestion) **or the CPU** (all 16 GB for
   the coding model)?
6. **Paid search fallback:** enable Brave ($5 per 1,000 requests, $5 free a month) for when SearXNG
   engines are rate-limited, or stay strictly self-hosted?
7. **SSH targets:** which hosts, which operations (read-only diagnostics or changes), and are you willing
   to run a small bastion and an SSH CA for short-lived certificates?

## Sources

All read 2026-11-15.

1. Open WebUI releases: https://github.com/open-webui/open-webui/releases
2. Open WebUI licence: https://docs.openwebui.com/license/ and https://github.com/open-webui/open-webui/blob/main/LICENSE
3. Open WebUI MCP: https://docs.openwebui.com/features/extensibility/mcp
4. Open WebUI mcpo: https://docs.openwebui.com/features/extensibility/plugin/tools/openapi-servers/mcp, https://github.com/open-webui/mcpo
5. Open WebUI environment reference: https://docs.openwebui.com/reference/env-configuration
6. Open WebUI RAG: https://docs.openwebui.com/features/chat-conversations/rag
7. Open WebUI Knowledge (sync and API): https://docs.openwebui.com/features/workspace/knowledge
8. Knowledge Base Sync (oikb): https://docs.openwebui.com/ecosystem/knowledge-base-sync, https://github.com/open-webui/oikb
9. oikb daemon: https://docs.openwebui.com/ecosystem/knowledge-base-sync/daemon
10. Open WebUI with SearXNG: https://docs.openwebui.com/features/chat-conversations/web-search/providers/searxng
11. Agentic search and fetch: https://docs.openwebui.com/features/chat-conversations/web-search/agentic-search
12. Open WebUI with Docling: https://docs.openwebui.com/features/chat-conversations/rag/document-extraction/docling
13. Open WebUI quick start (image tags, slim, RAM): https://docs.openwebui.com/getting-started/quick-start
14. Open Terminal: https://docs.openwebui.com/features/open-terminal, https://docs.openwebui.com/features/open-terminal/advanced/security, https://docs.openwebui.com/features/open-terminal/coding-agents, https://github.com/open-webui/open-terminal
15. Open WebUI source: https://github.com/open-webui/open-webui/blob/main/backend/open_webui/routers/retrieval.py, …/retrieval/vector/dbs/pgvector.py, …/retrieval/vector/dbs/qdrant.py, …/retrieval/models/external.py
16. Open WebUI and llama.cpp (updated 2026-11-14): https://docs.openwebui.com/alternatives/llama-cpp
17. LibreChat RAG API: https://www.librechat.ai/docs/features/rag_api, https://www.librechat.ai/docs/configuration/rag_api
18. LibreChat MCP: https://www.librechat.ai/docs/features/mcp
19. LibreChat web search: https://www.librechat.ai/docs/features/web_search
20. LibreChat code interpreter: https://www.librechat.ai/docs/features/code_interpreter, https://github.com/ClickHouse/code-interpreter
21. LibreChat v0.8.8 changelog and releases: https://www.librechat.ai/changelog/v0.8.8, https://github.com/LibreChat-AI/LibreChat/releases, deploy-compose.yml in that repository
22. AnythingLLM: https://github.com/Mintplex-Labs/anything-llm, https://docs.anythingllm.com/mcp-compatibility/overview
23. LobeHub licence and compose: https://github.com/lobehub/lobehub/blob/main/LICENSE, https://github.com/lobehub/lobehub/tree/main/docker-compose/deploy
24. Jan: https://github.com/janhq/jan
25. Msty pricing: https://msty.ai/pricing/
26. Onyx: https://github.com/onyx-dot-app/onyx
27. SearXNG container installation: https://docs.searxng.org/admin/installation-docker.html
28. SearXNG compose and env: https://github.com/searxng/searxng/tree/master/container
29. SearXNG defaults: https://github.com/searxng/searxng/blob/master/searx/settings.yml, https://github.com/searxng/searxng/blob/master/searx/limiter.toml
30. SearXNG settings (use_default_settings): https://docs.searxng.org/admin/settings/settings.html
31. mcp-searxng: https://github.com/ihor-sokoliuk/mcp-searxng (README, CONFIGURATION.md)
32. MCP reference servers: https://github.com/modelcontextprotocol/servers (src/fetch, src/filesystem, src/git), PyPI mcp-server-fetch and mcp-server-git 2026.11.11, npm @modelcontextprotocol/server-filesystem 2.3.0
33. GitHub MCP server: https://github.com/github/github-mcp-server (README, docs/server-configuration.md, docs/streamable-http.md, cmd/github-mcp-server/main.go)
34. mcp-proxy: https://github.com/sparfenyuk/mcp-proxy (README, src/mcp_proxy/mcp_server.py)
35. Docker MCP Gateway: https://github.com/docker/mcp-gateway
36. IBM ContextForge: https://github.com/IBM/mcp-context-forge
37. MetaMCP (archived): https://github.com/metatool-ai/metamcp
38. ssh-mcp (tufantunc): https://github.com/tufantunc/ssh-mcp (README, SECURITY.md, src/ssh/host-key.ts, src/audit/store.ts, Dockerfile), npm ssh-mcp 2.26.0
39. classfang ssh-mcp-server: https://github.com/classfang/ssh-mcp-server (README_EN.md, src/)
40. Other SSH MCP repositories (status only): https://github.com/bvisible/mcp-ssh-manager, https://github.com/n0madic/ssh-mcp, https://github.com/samerfarida/mcp-ssh-orchestrator
41. Open WebUI knowledge MCP: https://github.com/RonasIT/open-webui-mcp-server (README, src/tool-handlers.ts), npm open-webui-knowledge-mcp-server 0.2.0
42. Qdrant MCP: https://github.com/qdrant/mcp-server-qdrant
43. Text Embeddings Inference: https://github.com/huggingface/text-embeddings-inference (README, docs/openapi.json)
44. llama.cpp server: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md, https://github.com/ggml-org/llama.cpp/releases
45. Qwen3-Embedding-0.6B: https://huggingface.co/Qwen/Qwen3-Embedding-0.6B, https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF
46. Rerankers: https://huggingface.co/BAAI/bge-reranker-v2-m3, https://huggingface.co/gpustack/bge-reranker-v2-m3-GGUF, https://huggingface.co/ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF
47. docling-serve: https://github.com/docling-project/docling-serve (README, docs/configuration.md)
48. docling-mcp: https://github.com/docling-project/docling-mcp
49. crawl4ai: https://github.com/unclecode/crawl4ai, https://docs.crawl4ai.com/core/self-hosting/; Vane: https://github.com/ItzCrazyKns/Vane
50. DBHub: https://github.com/bytebase/dbhub, https://dbhub.ai/config/command-line, https://dbhub.ai/config/toml
51. mcp-server-docker: https://github.com/ckreiling/mcp-server-docker; docker-socket-proxy: https://github.com/Tecnativa/docker-socket-proxy
52. OpenSSH: https://man.openbsd.org/sshd.8 (AUTHORIZED_KEYS FILE FORMAT), https://man.openbsd.org/sshd_config.5
53. Claude Code docs: https://code.claude.com/docs/en/mcp, https://code.claude.com/docs/en/tools-reference
54. Paid search: https://brave.com/search/api/, https://www.tavily.com/pricing
55. Docker Hub tag listings (hub.docker.com/v2/repositories/…/tags) for searxng/searxng, valkey/valkey, pgvector/pgvector, qdrant/qdrant, apache/tika, bytebase/dbhub, mintplexlabs/anythingllm, lobehub/lobehub, isokoliuk/mcp-searxng, tecnativa/docker-socket-proxy, unclecode/crawl4ai
56. GHCR manifests (ghcr.io/v2/…/manifests/<tag>) for open-webui/open-webui, open-webui/oikb, open-webui/mcpo, open-webui/open-terminal, sparfenyuk/mcp-proxy, github/github-mcp-server, ggml-org/llama.cpp, huggingface/text-embeddings-inference, docling-project/docling-serve-*, ibm/mcp-context-forge
57. Ollama API: https://github.com/ollama/ollama/blob/main/docs/api.md
58. Open WebUI Pipelines (archived): https://github.com/open-webui/pipelines
