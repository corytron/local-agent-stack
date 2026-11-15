# Stack design contract (v1.0)

Issue #3. Coordinator-owned. Every `stack/`, `clients/`, `tools/` and guide agent builds against
this text. Sources: `docs/research/a-…f-*.md` (cited there); decisions here resolve the places
where those notes differ. Owner decisions: #7, #8.

## 1. Decisions (where the research notes differed)

| Topic | Decision | Why |
|---|---|---|
| Primary model | **Qwen3.8-27B**, `ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF` : `Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf`, fully on GPU, 64K context, q8_0 KV | a-models §Recommendation; b-inference's gpt-oss-20b was a worked example only |
| Fast/offload profile | **Qwen3.6-35B-A3B** `unsloth/Qwen3.6-35B-A3B-GGUF` : `Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf`, `--n-cpu-moe 16`, 64K | a-models (measured on 2-channel DDR5) |
| Haiku role | the primary model with thinking off (no second model in VRAM) | a-models (b) |
| Embeddings / reranker | `Qwen3-Embedding-0.6B` Q8_0 and `Qwen3-Reranker-0.6B` Q8_0, **CPU-only** (`--device none`) under llama-swap's persistent group | a-models + b-inference: no VRAM cost, AMX/AVX-512 used. d-gui's GPU containers and bge reranker are not used |
| Engine | llama.cpp via **llama-swap** `ghcr.io/mostlygeek/llama-swap:v273-cuda-b12407` (CUDA 12.8) | b-inference; CUDA ≤ 13.0 driver ceiling (e-truenas) |
| Gateway | **LiteLLM** v1.108.8, pinned by digest, Postgres 16.13 | b-inference |
| GUI | **Open WebUI** v0.13.3 slim, pgvector backend | d-gui |
| RAG store | `pgvector/pgvector:0.8.7-pg17` (Open WebUI DB + vectors) | d-gui |
| Parsing | `docling-serve-cpu` v1.38.2 | d-gui |
| NAS sync | `oikb` 0.6.0 daemon | d-gui |
| Search | SearXNG `2026.11.15-2d500cb6b`, `formats: [html, json]`, limiter off (LAN only) | d-gui |
| Shared tools | MCP hub: `sparfenyuk/mcp-proxy` v0.15.0 serving searxng, fetch, kb at `/servers/<name>/mcp`, bearer token | d-gui |
| SSH tool | `ssh-mcp` 2.26.0 (tufantunc), **stdio on the workstation only**, never in the hub | d-gui |
| Primary harness | **OpenCode** 2.3.0 on c4dev (Mac attaches over SSH, or runs its own) | c-agents |
| Claude Code itself | supported second path: Claude Code → LiteLLM `/v1/messages` with `local-opus/sonnet/haiku` (unsupported by Anthropic; documented with its limits) | c-agents + b-inference; it is the literal "closest to Claude Code" UX |
| Qwen Code | mentioned as an alternative in an appendix only | scope |
| TLS | **own domain, DNS-01** (owner, #8). Caddy built with DNS provider modules, image published by this repo's CI to GHCR | owner decision; e-truenas's internal-CA design kept as the fallback appendix |
| Remote access | LAN only | owner, #8 |
| Deploy | TrueNAS custom apps ("Install via YAML") that `include:` compose files from a git clone on the NAS; `tools/deploy.py` (truenas_api_client `TS-25.10.8`) for plan/apply/drift | e-truenas + f-tooling |
| Guide renderer | existing `tools/guide/build.py` (headless Chromium); not Pandoc/WeasyPrint | already matches the reference layout, no new dependencies |
| CI | GitHub Actions, four jobs, CodeQL default setup (repo is public) | f-tooling, adjusted for public |

## 2. TrueNAS apps, networks and services

**Everything runs on TrueNAS** (owner, 2026-11-15). Workstations (c4dev, the Mac, the Windows VM)
run only clients that the owner starts and stops: the OpenCode or Claude Code CLI, a browser, and
the stdio MCP children (such as `ssh-mcp`) that the CLI spawns for a session. No service, daemon,
container or timer of this stack runs on a workstation. Build agents may run short local tests
(a `docker build`, `compose config`) and must remove what they create.

All apps join the external Docker network **`ai-net`** (created once: `docker network create ai-net`
from **System > Shell**; the guide gives the exact step). Container names are fixed so other apps
reach them by name on `ai-net`.

| TrueNAS app | Compose file | Services (container_name) | Internal port | GPU |
|---|---|---|---|---|
| `ai-inference` | `stack/inference/compose.yaml` | `llama-swap`, `litellm`, `litellm-db` | 8080, 4000, 5432 | llama-swap only |
| `ai-rag` | `stack/rag/compose.yaml` | `pgvector`, `docling`, `oikb` | 5432, 5001, — | none (`NVIDIA_VISIBLE_DEVICES: void` where the image is CUDA-based) |
| `ai-web` | `stack/web/compose.yaml` | `open-webui`, `searxng`, `mcp-hub` | 8080, 8080, 8096 | none |
| `ai-edge` | `stack/edge/compose.yaml` | `caddy`, `gpu-exporter` | 443/80 published; 9835 | exporter only |

Only `caddy` publishes ports (443, and 80 for redirects). The TrueNAS web UI moves to 8080/8443
first (guide chapter 3).

## 3. Hostnames (placeholders; the reader substitutes their domain)

| Name | Upstream | Who uses it |
|---|---|---|
| `chat.lab.example.com` | `open-webui:8080` | browsers |
| `llm.lab.example.com` | `litellm:4000` (OpenAI `/v1/...` and Anthropic `/v1/messages`) | OpenCode, Claude Code, scripts |
| `models.lab.example.com` | `llama-swap:8080` (UI, logs; API key required) | admin only |
| `mcp.lab.example.com` | `mcp-hub:8096` | OpenCode, Open WebUI |
| `search.lab.example.com` | `searxng:8080` | optional, admin |

DNS: the reader adds A records (local DNS / router) for these names → `192.0.2.10`. Certificates
via DNS-01 with an API token scoped to the zone. Caddy env: `ACME_EMAIL`, `DNS_PROVIDER_TOKEN`,
`LAB_DOMAIN` (e.g. `lab.example.com`); the owner uses **Cloudflare** (#8), so it is the default and the guide's worked example; the Caddyfile uses `{$LAB_DOMAIN}` so no file edits.
The edge image `ghcr.io/corytron/local-agent-stack-caddy:<caddy-version>` is built by
`.github/workflows/caddy-image.yml` with modules for: cloudflare, route53, digitalocean,
porkbun, namecheap, duckdns, desec, ovh (names verified against caddy-dns org). The Caddyfile
selects the provider with `{$DNS_PROVIDER}` per Caddy's env placeholder support; if a provider
needs more than one credential, the guide says which variables.

## 4. Datasets and paths on TrueNAS (pool `tank`)

| Dataset | Mount path | Properties | Contents |
|---|---|---|---|
| `tank/ai` | `/mnt/tank/ai` | parent | — |
| `tank/ai/models` | `/mnt/tank/ai/models` | recordsize 1M, lz4, atime off, `primarycache=metadata`, no snapshots | `gguf/*.gguf` |
| `tank/ai/appdata` | `/mnt/tank/ai/appdata/<service>` | Apps preset | per-service state |
| `tank/ai/appdata/{litellm-db,pgvector}` | child datasets | Apps preset, recordsize 32K | PostgreSQL data (`PGDATA` = `<mount>/pgdata`) |
| `tank/ai/appdata/{oikb,open-webui,caddy}` | child datasets | Apps preset | service state |
| `tank/ai/rag-docs` | `/mnt/tank/ai/rag-docs` | SMB preset, share `rag-docs` | documents to index (mounted read-only) |
| `tank/ai/stacks` | `/mnt/tank/ai/stacks/local-agent-stack` | default | git clone of this repo (release tag) |
| `tank/ai/secrets` | `/mnt/tank/ai/secrets` | mode 0700 root | `<app>.env` files, never in git |

Compose files use `${AI_ROOT:-/mnt/tank/ai}` so paths can be changed in one place. Each TrueNAS
app's YAML is exactly:

```yaml
include:
  - path: /mnt/tank/ai/stacks/local-agent-stack/stack/<app>/compose.yaml
    env_file: /mnt/tank/ai/secrets/<app>.env
services: {}
```

`stack/<app>/<app>.env.example` documents every variable with a placeholder value, and `stack/<app>/truenas-app.yaml` holds exactly these four lines for the hand install. `tools/deploy.py apply` writes the same YAML plus a top-level `x-local-agent-stack` block (`files` and `env` content hashes) and, when `desired.toml` lists `overrides` for the app, includes them after the compose file (`path:` as a list).

## 5. Models, aliases and VRAM budget

llama-swap model ids (in `stack/inference/llama-swap/config.yaml`):

| id | file under `/models/gguf/` | group | device | notes |
|---|---|---|---|---|
| `coder` | `Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf` | `llm` (swap) | GPU, `-ngl 99 -c 65536 -ctk q8_0 -ctv q8_0 --jinja`, MTP draft per a-models | ~14.3 GiB |
| `coder-moe` | `Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf` | `llm` (swap) | GPU + `--n-cpu-moe 16` | ~15.7 GiB + ~8 GB RAM |
| `embed` | `Qwen3-Embedding-0.6B-Q8_0.gguf` | `rag` (persistent) | `--device none --embedding --pooling last` | RAM only |
| `rerank` | `qwen3-reranker-0.6b-q8_0.gguf` | `rag` (persistent) | `--device none --reranking` | RAM only |

LiteLLM model names (the only names clients use):

| Client-facing name | Routes to | Use |
|---|---|---|
| `local-coder` | `coder` | OpenCode main, Open WebUI default |
| `local-fast` | `coder` with thinking off (`chat_template_kwargs.enable_thinking=false`) | titles, scouts, summaries |
| `local-coder-moe` | `coder-moe` | fast profile (swaps the GPU model) |
| `local-opus`, `local-sonnet` | `coder` via `/v1/messages` | Claude Code |
| `local-haiku` | `coder`, thinking off | Claude Code small/fast |
| `local-embed`, `local-rerank` | `embed`, `rerank` | Open WebUI RAG |

Every flag, model file and repo name in the stack files must be checked against the research
notes (and their sources); anything unverified is marked `# UNVERIFIED:` in the file and listed
in the agent's hand-back.

## 6. Secrets (names only; values never in git)

`inference.env`: `LITELLM_MASTER_KEY`, `LITELLM_SALT_KEY`, `LITELLM_DB_PASSWORD`, `LLAMA_SWAP_API_KEY`.
`rag.env`: `PG_PASSWORD` (URL-safe), `DOCLING_API_KEY`, `OIKB_TOKEN` (the `indexer` user's Open WebUI key), `OIKB_KB_ID` (not secret), optional `OIKB_API_KEY`.
`web.env`: `LAB_DOMAIN`, `WEBUI_SECRET_KEY`, `PG_PASSWORD` (same value as rag), `DOCLING_API_KEY` (same as rag), `LITELLM_WEBUI_KEY` (a LiteLLM virtual key allowed local-coder/fast/coder-moe/embed/rerank), `SEARXNG_SECRET`, `MCP_HUB_TOKEN` (`[A-Za-z0-9-._~+/]` only), `KB_READER_TOKEN` (the `kb-reader` user's key; empty until created), optional `SEARXNG_CONTACT_URL`.
Open WebUI reads most settings only on its first start (PersistentConfig), so `web.env` must be complete before the first install; later changes to those go through the Admin Panel (`stack/web/README.md`).
`edge.env`: `LAB_DOMAIN`, `ACME_EMAIL`, `DNS_PROVIDER` (default `cloudflare`), `DNS_PROVIDER_TOKEN`; optional `DNS_PROVIDER_KEY_ID`, `DNS_PROVIDER_CONSUMER_KEY`, `DNS_PROVIDER_ENDPOINT` (providers that need more than a token), `ACME_RESOLVERS` (default `1.1.1.1 1.0.0.1`, for split-horizon DNS), `ACME_CA` (staging/production), `EDGE_ALLOWED_CIDRS` (default private ranges), `EDGE_BIND_IP`, `AI_ROOT`.
Workstation: `~/.config/local-agent-stack/client.env` with `LAB_DOMAIN`, `LOCAL_LLM_KEY`, `MCP_HUB_TOKEN`.
`tools/secrets.py gen <app> [--share FILE] [--ask NAME]`; `gen client --share web.env --ask LOCAL_LLM_KEY` writes `client.env`. It prints a new `<app>.env` with random values for every generated
secret (stdlib `secrets`), leaving the reader-provided ones as placeholders.

## 7. Workstation (clients/)

- `clients/opencode/opencode.jsonc`: provider `local` (`https://llm.lab.example.com/v1`,
  `{env:LOCAL_LLM_KEY}`), models `local-coder` (main) and `local-fast` (small), real context
  limits, MCP servers: `searxng`/`fetch`/`kb` via the hub (`https://mcp.lab.example.com/servers/<n>/mcp`,
  bearer `{env:MCP_HUB_TOKEN}`), `ssh` (stdio `ssh-mcp`), updates and models.dev fetch disabled.
- `clients/opencode/agents/*.md`: `coordinator`, `researcher` (read-only, writes one docs file),
  `builder` (owns named files), `reviewer` (read-only); `clients/opencode/commands/*.md`: `/plan`,
  `/issue`, `/pr`, `/check`; `clients/opencode/plugins/guard.ts`: the PreToolUse-equivalent rules
  (no push to main, no secrets in files).
- `clients/claude-code/settings.json`: env block for Claude Code against `llm.lab.example.com`.
- `clients/ssh-mcp/policy.example.*`: deny-by-default policy, one host allowed as an example.
- `clients/templates/AGENTS.md` and `CLAUDE.md`: the project-memory template that reproduces the
  owner's working style (contracts, parallel agents capped at 2–3 on one GPU, GitHub flow).
- No `opencode serve` daemon: the Mac runs its own CLI against `llm.lab.example.com`, or SSHes in.
- `clients/install.sh`: installs/updates OpenCode at the pinned version and links the configs
  (idempotent; `--dry-run`).

## 8. Repository tooling

- `tools/check.sh` (Hue design: every check at once on all cores, fixed report order,
  `--only`, `--strict`, `JOBS`): `yaml` (yamllint), `shell` (shellcheck), `python` (ruff incl. `S`
  rules + `python -m unittest`), `markdown` (markdownlint-cli2 or pymarkdown — pick one installable
  without sudo), `workflows` (actionlint, zizmor), `compose` (`docker compose -f … config -q` per
  app with the `.env.example`), `secrets` (gitleaks), `links` (`tools/check_links.py`, offline,
  anchors included), `guide` (`tools/guide/build.py`).
- `tools/setup-checks.sh`: installs pinned tools into `~/.local/bin` without sudo, in parallel,
  and sets `core.hooksPath tools/hooks`; `tools/hooks/pre-push`: refuses pushes to `main`, runs
  `secrets` and fast checks.
- `.github/workflows/ci.yml`: four jobs, names fixed (they become required checks):
  `Lint`, `Compose stack`, `Secrets`, `Guide`. Actions pinned by SHA. `release.yml`: on tag
  `vX.Y`, build the guide PDF and `stack-vX.Y.tar.gz`, `SHA256SUMS.txt`, notes from `CHANGELOG.md`.
- `renovate.json` (images incl. `server-cuda-bNNNN` style tags; CUDA ≤ 13.0 rule as a comment),
  `.github/dependabot.yml` (actions, pip), `.github/labels.json`.
- `tools/deploy.py [--file|--config|--local] validate|render|plan|apply|drift|status` (options before or after the command; `desired.toml` with `env_dir` and per-app `overrides`; change detection by image, YAML, mounted config files and env file hashes) against `deploy/truenas.toml`
  (desired release tag + apps; `drift` runs on demand and after every `apply`, or from a TrueNAS cron job, never a workstation timer), keys from `~/.config/local-agent-stack/` (READONLY_ADMIN for
  plan/drift/status, FULL_ADMIN only for apply). `tools/bench.sh` (llama-bench sweep, run on the
  NAS shell) and `tools/smoke.py` (end-to-end checks of every endpoint from the workstation).

## 9. Guide outline (chapter files under `guide/chapters/`)

1. `01-introduction.md` — Introduction: overview, architecture, how it maps to Claude Code, terminology, revision history
2. `02-planning.md` — Planning the deployment: hardware and sizing, VRAM/RAM budget, network/DNS/ports, accounts and tokens, pre-deployment checklist
3. `03-truenas.md` — Preparing TrueNAS SCALE: release check, NVIDIA driver, ARC cap, Post Init script, datasets, SMB share, UI ports, `ai-net`, clone the repo, secrets
4. `04-inference.md` — Deploying the inference app: download models, configure and install `ai-inference`, keys, verification, first benchmark
5. `05-edge.md` — Deploying the edge app: DNS records, Cloudflare DNS-01 token, `ai-edge`, certificates, verification (before the web app: Open WebUI has no published port)
6. `06-rag-web.md` — Deploying the RAG and web apps: `ai-rag`, `ai-web`, Open WebUI first-run settings, service users and keys, SearXNG, MCP hub, knowledge sync
7. `07-workstation.md` — Configuring the coding agent: OpenCode on c4dev and the Mac, agents/commands/plugins, MCP tools, SSH tool, Claude Code against the local gateway
8. `08-workflow.md` — Running projects with agents: project memory, contracts, parallel agents, GitHub flow, CI and checks, releases
9. `09-validation.md` — Validating the deployment: smoke tests, benchmarks, evals and the regression gate
10. `10-operations.md` — Operating and updating: releases and `deploy.py`, image updates, model changes, monitoring
11. `11-troubleshooting.md` — Troubleshooting
12. `12-uninstall.md` — Uninstalling
- `a-backup.md` (appendix) Backup and restore
- `b-profiles.md` (appendix) Model profiles, alternatives and the memory upgrade
- `c-parity.md` (appendix) Feature parity with Claude Code
- `d-internal-ca.md` (appendix) TLS with an internal CA instead of DNS-01
- `e-config-files.md` (appendix) Configuration file reference (every file the reader installs, via include)
- `f-references.md` (appendix) References
