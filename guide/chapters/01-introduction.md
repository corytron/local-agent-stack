title: Introduction

# Introduction

This guide describes how to plan, deploy, validate and operate the Local Agent Stack: a self-hosted
coding agent that works like Claude Code but runs on open-weight models served from your own
TrueNAS SCALE server with one NVIDIA GPU. The guide follows the deployment from an empty TrueNAS
system to a working agent on a Linux workstation, and ends each procedure with a step that verifies
the result.

The files that the guide tells you to install are in the project repository, under `stack/` and
`clients/`. The guide quotes them.

!!! note
    If a command or a file in this guide differs from the file in the repository, the file in the
    repository is correct. Use the repository version and report the difference as an issue.

## Stack overview

The Local Agent Stack replaces the hosted parts of Claude Code with services that run on your LAN.
Models, retrieval and tools run locally; only web search, certificate issuance and downloads leave
the LAN. There is no cloud fallback for inference.

The stack provides:

- **Local models.** Qwen3.8-27B, fully resident on an RTX 4080 16 GB, is the main agent model. A
  faster mixture-of-experts profile (Qwen3.6-35B-A3B) can replace it on demand. llama.cpp serves the
  models; llama-swap starts and stops them.
- **One API endpoint.** LiteLLM serves the OpenAI format (`/v1/...`) and the Anthropic format
  (`/v1/messages`) at `https://llm.lab.example.com`, with one key per client.
- **A terminal coding agent.** OpenCode 2.3.0 runs on the workstation `c4dev` with sub-agents,
  commands, a guard plugin and MCP tools, only while you use it: no service, container or timer of
  the stack runs on a workstation. Claude Code itself can use the same endpoint as a second,
  unsupported path.
- **A web GUI.** Open WebUI at `https://chat.lab.example.com` for chat, retrieval over your
  documents and web search.
- **Retrieval over your documents (RAG).** Files you copy to an SMB share are parsed, embedded and
  indexed. The web GUI and the coding agent query the same index.
- **Web search.** A self-hosted SearXNG instance.
- **Tools.** An MCP hub serves search, page fetch and knowledge-base tools to every client. A
  separate SSH tool on the workstation reaches remote hosts under a deny-by-default policy.
- **TLS.** Caddy terminates HTTPS for every host name with certificates obtained through the
  DNS-01 challenge for your own domain.

### Intended audience

This guide is for the administrator of a home lab or small lab who:

- administers TrueNAS SCALE through its web interface and shell;
- is familiar with the Linux shell, Docker Compose and git;
- owns a domain whose DNS provider offers an API;
- uses, or wants to use, a terminal coding agent.

### Limits of the stack

- **Model quality.** The local models are much smaller than Claude. They handle single tool calls
  well but fail more often on long, multi-step tasks. Plan the work around that; see
  [Where local models fall short](#where-local-models-fall-short).
- **One GPU model at a time.** The 16 GB card holds one agent model. Switching between the default
  and the fast profile reloads the model, and concurrent agents share the GPU. Plan for two to three
  agents working at the same time.
- **LAN only.** The design publishes no service to the internet and offers no remote access.
- **No cloud fallback.** If the server is down, the agent is down.

### Stack architecture

The stack runs as four TrueNAS custom apps. Each app is a compose file in the repository, installed
through **Install via YAML**. All apps join one external Docker network, `ai-net`, and reach each
other by container name. Only `caddy` publishes ports on the server.

<figure markdown><img src="../figures/architecture.svg" alt="Stack architecture: LAN clients, the TrueNAS server with four apps on ai-net, and outbound connections"><figcaption>Figure: Stack architecture</figcaption></figure>

Table: TrueNAS apps of the stack

| App | Services (container names) | Role | GPU |
|---|---|---|---|
| `ai-inference` | `llama-swap`, `litellm`, `litellm-db` | Serves the models and the API endpoint, with keys and usage logs | `llama-swap` only |
| `ai-rag` | `pgvector`, `docling`, `oikb` | Stores documents and vectors, parses documents, syncs the document share | None |
| `ai-web` | `open-webui`, `searxng`, `mcp-hub` | Web GUI, web search, shared MCP tools | None |
| `ai-edge` | `caddy`, `gpu-exporter` | HTTPS for every host name, GPU metrics | `gpu-exporter` only |

A request from the coding agent follows this path: the workstation resolves
`llm.lab.example.com` to the server, `caddy` terminates TLS and forwards the request over `ai-net`
to `litellm`, which checks the client key and forwards it to `llama-swap`. `llama-swap` starts the
requested model if it is not loaded, and passes the request to that model's `llama-server` process.

The embedding and reranking models run on the CPU, so they never compete with the agent model for
VRAM. They stay loaded while the GPU model changes.

### Software components and versions

Table: Software components

| Component | Version | Role |
|---|---|---|
| TrueNAS SCALE | 25.10.8 "Goldeye" (minimum 25.10.6) | Server operating system and app platform |
| NVIDIA driver | 580.173.02, shipped with TrueNAS (CUDA 13.0 maximum) | GPU driver and container toolkit |
| llama-swap with llama.cpp | `ghcr.io/mostlygeek/llama-swap:v273-cuda-b12407` (llama.cpp b12407, CUDA 12.8) | Model server and model switching |
| LiteLLM | v1.108.8, pinned by digest | API gateway |
| PostgreSQL | 16.13 | LiteLLM keys and usage logs |
| Open WebUI | v0.13.3, slim image | Web GUI and RAG |
| pgvector | `pgvector/pgvector:0.8.7-pg17` | Open WebUI database and vector store |
| docling-serve | `docling-serve-cpu` v1.38.2 | Document parsing |
| oikb | 0.6.0 | Sync of the document share into Open WebUI |
| SearXNG | 2026.11.15-2d500cb6b | Web search |
| mcp-proxy | v0.15.0 | MCP hub |
| Caddy | Built with DNS provider modules by the project's CI; tag in `stack/edge/compose.yaml` | Reverse proxy and certificates |
| OpenCode | 2.3.0 | Coding agent on the workstation |
| ssh-mcp | 2.26.0 | SSH tool on the workstation |

!!! note
    The compose files of a release pin every image by tag and digest, so a pull fetches exactly the
    image that the release was written for. Two images are built by this project from its own
    Dockerfiles: the Caddy image with the DNS provider modules
    (`ghcr.io/corytron/local-agent-stack-caddy`) and the MCP hub image
    (`ghcr.io/corytron/local-agent-stack-mcp-hub`). The project's GitHub workflows **Caddy image**
    and **MCP hub image** publish them from `main`, and a compose file can name one of them by
    digest only after a workflow run has published it; until then it names the image by tag alone.
    Chapters 5 and 6 show how to compare a pulled image with the workflow run that built it, and how
    to build either image on the server when the pull fails
    ([How the image is built and published](#how-the-image-is-built-and-published),
    [Build or pull the MCP hub image](#build-or-pull-the-mcp-hub-image)).

!!! note
    Container images built for CUDA newer than 13.0 do not start with the driver that TrueNAS 25.10
    ships; the stack uses CUDA 12.8 images for that reason.

### Models and client-facing names

Clients never address a model file directly. They use the LiteLLM names in the last column, so a
model can be replaced on the server without changing any client.

Table: Models served by the stack

| Model | llama-swap id | Runs on | LiteLLM names |
|---|---|---|---|
| Qwen3.8-27B, dense, 3.5 bits per weight | `coder` | GPU, 64K context | `local-coder`; `local-fast` (thinking off); `local-opus`, `local-sonnet`, `local-haiku` (Claude Code) |
| Qwen3.6-35B-A3B, mixture of experts | `coder-moe` | GPU, experts of 16 layers in system RAM | `local-coder-moe` |
| Qwen3-Embedding-0.6B | `embed` | CPU | `local-embed` |
| Qwen3-Reranker-0.6B | `rerank` | CPU | `local-rerank` |

### Component licences

Every component of the stack is open source except Open WebUI, whose licence adds a branding
clause, and Claude Code, which is proprietary and optional. The licences were read from each
project's repository and model card on 15 November 2026; Appendix F links every text
([Component licence texts](#component-licence-texts)).

Table: Component licences

| Component | Licence | Notes |
|---|---|---|
| TrueNAS SCALE | GPL-3.0 for its build system and web interface; LGPL-3.0 for its middleware | The server's operating system |
| NVIDIA open kernel modules | MIT; dual MIT and GPL-2.0 when linked into a kernel module | Shipped inside TrueNAS 25.10 |
| llama.cpp | MIT | Model server (`llama-server`) |
| llama-swap | MIT | Model switching |
| LiteLLM | MIT, except the `litellm/enterprise/` directory | The enterprise directory has its own licence |
| PostgreSQL and pgvector | PostgreSQL License | Permissive, BSD-style |
| Open WebUI | Open WebUI License: BSD-3-Clause plus a branding clause, since v0.6.6 | Not an OSI open-source licence; see below |
| docling-serve | MIT | Document parsing |
| oikb | MIT | Knowledge-base sync |
| SearXNG | AGPL-3.0 | Network copyleft; see below |
| mcp-proxy | MIT | The MCP hub |
| mcp-searxng | MIT | The hub's `searxng` server |
| mcp-server-fetch | MIT | The hub's `fetch` server, from the MCP reference servers, whose repository is moving to Apache-2.0 |
| open-webui-knowledge-mcp-server | MIT | The hub's `kb` server |
| Caddy | Apache-2.0 | The edge image also compiles in eight DNS provider modules; see below |
| nvidia_gpu_exporter | MIT | GPU metrics |
| OpenCode | MIT | The coding agent |
| ssh-mcp | MIT | The SSH tool |
| Qwen Code | Apache-2.0 | Optional harness (Appendix B) |
| Claude Code | Proprietary | Use is subject to Anthropic's Commercial Terms of Service; optional second path |
| Qwen3.8-27B, Qwen3.6-35B-A3B, Qwen3-Embedding-0.6B, Qwen3-Reranker-0.6B, and the four GGUF files of this guide | Apache-2.0 | Qwen3.8-Flash-Next, an option after a memory upgrade (Appendix B), uses the Qwen Community License 1.0 instead |
| This project: `stack/`, `clients/`, `tools/`, `evals/`, the guide | Apache-2.0 | The repository's `LICENSE` and `NOTICE` |

Running the stack on your own LAN for yourself and your household needs no permission beyond these
licences. Their conditions matter when you give a larger group access, change a component, or
redistribute an image or a fork of the repository:

- **Open WebUI branding.** The licence forbids altering, removing, obscuring or replacing the
  "Open WebUI" name, logo and other branding, except in a deployment with at most 50 end users
  (people with direct access) in any rolling 30-day period, with the copyright holder's written
  permission, or under an enterprise licence. A home installation is within the 50-user exception.
  The stack does not change the branding; keep it as shipped if more than 50 people may use the
  GUI within 30 days.
- **SearXNG.** If you change SearXNG's code and let other people use the instance over a network,
  the AGPL-3.0 requires you to offer them the changed source. The stack runs the published image
  unchanged and configures it with its own settings files.
- **DNS provider modules.** The modules in the Caddy image are separate projects. On 15 November
  2026, `cloudflare` was Apache-2.0, and `route53`, `porkbun`, `desec` and `ovh` were MIT; GitHub
  detected no licence file for `digitalocean`, `namecheap` and `duckdns`. Check those three
  repositories before you redistribute the image.
- **Claude Code.** Anthropic does not support routing Claude Code to non-Claude models through a
  gateway (Chapter 7).
- **Qwen3.8-Flash-Next.** Its licence allows internal use; a "Model as a Service" or "AI Work
  Assistant" business needs a separate licence.

!!! note
    A component can change its licence in a later release, as Open WebUI did in v0.6.6. Read the
    licence again before an update that moves a component to a new major version or to another
    project.

### Files that accompany this guide

Table: Repository layout

| Directory | Contents |
|---|---|
| `stack/` | One directory per app (`inference`, `rag`, `web`, `edge`): the compose file, its configuration files, `truenas-app.yaml` (the four-line YAML that installs the app in TrueNAS) and an example environment file, such as `inference.env.example`, that documents every variable |
| `clients/` | OpenCode configuration, agents, commands and the guard plugin; Claude Code settings; the ssh-mcp policy example; memory-file templates; `client.env.example`; `install.sh` |
| `tools/` | `secrets.py` (generates the secrets files), `deploy.py` (plan, apply and drift checks against TrueNAS), `smoke.py` and `bench.sh` (validation), `eval.py` (evaluation suites and the regression gate), `check.sh` (repository checks) |
| `evals/` | The evaluation suites, their sample documents, the run sets and the thresholds of the regression gate |
| `deploy/` | `truenas.toml`, the desired state that `deploy.py` compares with the server |
| `guide/` | The source of this guide |
| `docs/` | The design contract and the research notes, with their sources |
| `.github/` | The CI, release and image workflows, the Dependabot settings, the issue templates and `labels.json` |
| Repository root | `CHANGELOG.md`, `renovate.json` (image updates), `LICENSE` and `NOTICE` |

### Deployment sequence

Table: Deployment sequence

| Step | Task | Chapter |
|---|---|---|
| 1 | Check the hardware and the workstation software, choose names and collect accounts and tokens | 2, Planning the deployment |
| 2 | Enable the GPU, cap the ZFS ARC, create datasets and the document share, move the TrueNAS UI ports, create `ai-net`, clone the repository, create the secrets and the API keys of `deploy.py` | 3, Preparing TrueNAS SCALE |
| 3 | Download the models, install `ai-inference` and create the LiteLLM keys of the workstations | 4, Deploying the inference app |
| 4 | Add DNS records, install `ai-edge` and obtain certificates | 5, Deploying the edge app |
| 5 | Install `ai-rag` and `ai-web`, then complete the Open WebUI first-run settings | 6, Deploying the RAG and web apps |
| 6 | Install and configure OpenCode and the MCP tools on the workstation | 7, Configuring the coding agent |
| 7 | Set up project memory, agents and the GitHub workflow | 8, Running projects with agents |
| 8 | Run the smoke tests, benchmarks and evaluations | 9, Validating the deployment |

The edge app comes before the RAG and web apps because Open WebUI publishes no port: browsers reach
it only through Caddy, and its first-run settings are made in a browser. Chapters 10 to 12 cover
operation, troubleshooting and removal.

## How the stack maps to Claude Code

Each part of Claude Code has a local counterpart. The harness features carry over almost
unchanged; the models are where the stack differs most.

Table: Claude Code and its local counterparts

| Claude Code | This stack |
|---|---|
| Claude models (Opus, Sonnet, Haiku) | Qwen3.8-27B through LiteLLM (`local-coder`, `local-fast`) |
| Anthropic API | LiteLLM at `https://llm.lab.example.com`, OpenAI and Anthropic formats |
| Claude Code CLI | OpenCode 2.3.0; Claude Code itself as an optional second path |
| `CLAUDE.md` memory files | `AGENTS.md`, from the templates in `clients/templates/` |
| Sub-agents | OpenCode agents `coordinator`, `researcher`, `builder` and `reviewer` |
| Slash commands | `/plan`, `/issue`, `/pr` and `/check` |
| Hooks | The OpenCode plugin `guard.ts` |
| WebSearch and WebFetch | SearXNG and fetch tools on the MCP hub; OpenCode's `webfetch` |
| MCP servers | The MCP hub at `https://mcp.lab.example.com`, and `ssh-mcp` on the workstation |
| No equivalent | Retrieval over your documents, in Open WebUI and through the `kb` tool |

Appendix C compares the features one by one, rates the parity of each, and describes where local
models fall short and how the stack mitigates it.

## Validation status and known issues

This release was built and checked on the workstation `c4dev` and in the project's CI. None of it
has run on the TrueNAS server or on the RTX 4080 yet, so the first installation is also the first
run on the reference hardware. Follow the verification step of every task, and report anything
that differs from this guide as an issue ([Where to get help](#where-to-get-help)). The chapters
mark each statement that was not checked on hardware with "not verified", "not tested",
"assumed" or "est.", and say what to check and what to do if it fails.

### What was tested for this release

Table: Tests made for this release

| What | Where and how | Result |
|---|---|---|
| Every check of `tools/check.sh`: YAML, shell, Python (with the unit tests of `deploy.py`, `secrets.py`, `smoke.py`, `eval.py` and the link checker), Markdown, workflows, `docker compose config` of each app with its example environment file, secrets, links and the guide build | `c4dev` and the four required CI jobs | Pass |
| The MCP hub image | `c4dev`, 15 November 2026: `docker build`, then a run with the flags of the compose file next to a SearXNG container on a test network, both removed afterwards | The health check reported `fetch`, `kb` and `searxng`; each server listed its tools; a web search returned live results; `fetch` read a public page and refused a private address; a missing or wrong token got HTTP 401 and an unknown Host header HTTP 421. The `kb` server was not called against a real Open WebUI |
| The YAML of each app with the `x-local-agent-stack` block that `deploy.py` writes | `docker compose config`, Compose v5.6.0 on `c4dev` | Accepted. The Compose version that TrueNAS bundles was not tried |
| `tools/bench.sh` | `c4dev`: `--dry-run`, ShellCheck, unit tests of its request and of its timing parser | Pass; never run on a GPU |
| `tools/eval.py` and `tools/smoke.py` | `c4dev`: unit tests, `eval.py` against a fake gateway on the loopback address | Pass; never run against the stack |
| Image names, tags, digests, environment variables, endpoints and user IDs | Read from each image's metadata and from the projects' sources at the pinned versions | Recorded in `stack/` |
| First-request prompt sizes of the coding agents | Headless first requests, measured for the research behind this release | The figures in Chapter 8 and Appendix B |

### What has not run on the server

Every VRAM, memory and speed figure in this guide is an estimate or a measurement that others
published for similar hardware. The table groups the not-verified notes of the chapters; each
linked section says what to check and how to recover.

Table: Not verified in this release

| Area | Not verified | Where the guide handles it |
|---|---|---|
| GPU memory and speed | That `coder` fits in 16 GB with its MTP draft context; every VRAM, RAM and speed figure; `bench.sh` on a GPU | [VRAM budget](#vram-budget), [Test that the coder model fits](#test-that-the-coder-model-fits), [Apply a fallback when coder does not fit](#apply-a-fallback-when-coder-does-not-fit), [How bench.sh works](#how-benchsh-works) |
| Inference app | That llama.cpp b12407 loads the MTP head as configured; that the CPU-only models create no CUDA context; that llama-swap notices a changed configuration file | [The coder model entry](#the-coder-model-entry), [The embedding and reranking model entries](#the-embedding-and-reranking-model-entries), [Redeploy ai-inference after a change](#redeploy-ai-inference-after-a-change) |
| Containers on TrueNAS | The first start of PostgreSQL (`litellm-db` in Chapter 4, `pgvector` in Chapter 6) on a dataset with the **Apps** preset; `oikb` as UID 568; `no-new-privileges` with the PostgreSQL entrypoints and Open WebUI's start script; `gpu-exporter` with every capability dropped. None of the six `ai-rag` and `ai-web` containers was started on TrueNAS | [Recreate the pgvector dataset with the Generic preset](#recreate-the-pgvector-dataset-with-the-generic-preset), [Verify pgvector, docling and oikb](#verify-pgvector-docling-and-oikb), [Install ai-web from a YAML wrapper](#install-ai-web-from-a-yaml-wrapper), [Read the GPU metrics](#read-the-gpu-metrics) |
| Images this project builds | Building the Caddy image or the MCP hub image on TrueNAS, the fallback when a pull fails | [Build the Caddy image on TrueNAS](#build-the-caddy-image-on-truenas), [Build or pull the MCP hub image](#build-or-pull-the-mcp-hub-image) |
| Open WebUI | The menu and field labels of Open WebUI 0.13.3; the embedding and reranking chain Open WebUI, LiteLLM, llama-swap; the retrieval request of the evaluations | [Configure Open WebUI](#configure-open-webui), [Check the Open WebUI connections and document settings](#check-the-open-webui-connections-and-document-settings), [Evaluate retrieval through Open WebUI](#evaluate-retrieval-through-open-webui) |
| Validation and operation tools | `eval.py` against the stack, including whether LiteLLM forwards `seed` and `parallel_tool_calls`; the `x-local-agent-stack` block with TrueNAS's Compose; the certificate check of the TrueNAS web interface; `deploy.py --local` on TrueNAS and the mail of its cron job; the metrics of the model server in a browser | [Evaluation suites](#evaluation-suites), [How deploy.py works](#how-deploypy-works), [Create the connection settings](#create-the-connection-settings), [Check that deploy.py runs on TrueNAS](#check-that-deploypy-runs-on-truenas), [Create the drift cron job](#create-the-drift-cron-job), [Monitor the model server](#monitor-the-model-server) |
| Workstations | The macOS path of `clients/install.sh`; the Windows VM path; whether OpenCode reads the system trust store or `NODE_EXTRA_CA_CERTS`; the hub tools in Claude Code; that command-line MCP clients send no `Origin` header | [Install OpenCode on the Mac](#install-opencode-on-the-mac), [What the Windows VM supports](#what-the-windows-vm-supports), [Certificates from the internal CA](#certificates-from-the-internal-ca), [Add the hub tools to Claude Code](#add-the-hub-tools-to-claude-code), [Settings that other apps must match](#settings-that-other-apps-must-match) |
| Screens of other products | Some TrueNAS 25.10.8 labels used to remove the stack; the Cloudflare dashboard labels; the activation of an older boot environment | [Delete the apps](#delete-the-apps), [Destroy the datasets](#destroy-the-datasets), [Revoke the DNS provider token and records](#revoke-the-dns-provider-token-and-records), [Update TrueNAS within 25.10](#update-truenas-within-2510) |
| Host firmware | Reported, not verified: the TrueNAS 25.10 host does not boot with Secure Boot on | [Minimum requirements](#minimum-requirements) |

### Known issues

Table: Known issues in this release

| Issue | Effect | What to do |
|---|---|---|
| `deploy.py` compares the running images with the release's compose file only, not with the compose file merged with an app's overrides (issue 17 on GitHub) | With an override that changes an image, such as the locally built Caddy image of [Build the Caddy image on TrueNAS](#build-the-caddy-image-on-truenas), `plan` and `drift` always report the images of `ai-edge` as different | Expect the report while that override is in place, and check the running image as that task describes. The other comparisons (YAML, content hashes, environment files) are not affected |

The issue is tracked at
[github.com/corytron/local-agent-stack/issues/17](https://github.com/corytron/local-agent-stack/issues/17).

## Using this guide

### Document conventions

Table: Document conventions

| Convention | Meaning |
|---|---|
| **Bold** | A label in a user interface: a menu, button, field, card or tab |
| **Apps** > **Installed** | A click path: select each label in turn |
| `Monospace` | A command, file, path, variable, value or output, typed or read exactly as shown |
| `<placeholder>` | A value that you replace, angle brackets included, for example `<release-tag>`. Each task explains its placeholders |
| `192.0.2.10`, `lab.example.com`, `tank`, `sk-local-...` | Placeholder addresses, domain, pool and keys; replace them with your own ([Placeholder values](#placeholder-values)) |
| Code block | One command per line, ready to paste. A line that ends with `\` continues on the next line. The paragraph under a step says what the command prints |
| NOTE, CAUTION, WARNING | Additional information; a risk of data loss or hardware damage; a risk of credential exposure or loss of service. The legend at the front of this guide shows how each is printed |
| "est.", "assumed", "not verified" | A figure or a behaviour that was not measured or tested on the reference system for this release ([Validation status and known issues](#validation-status-and-known-issues)) |

Each task is a block of **Prerequisites** (when there are any), **About this task**, **Steps** and
**Results**, sometimes followed by **Next steps**. **Results** says what is true when the task is
complete; when the check comes in a later task, it says which one.

### Where to get help

- Chapter 11 collects diagnostics and lists known problems with their solutions
  ([Collecting diagnostics](#collecting-diagnostics)).
- Appendix F lists the primary sources behind this guide and where each component's maintainers
  answer questions ([Getting help](#getting-help)).
- For a problem with this guide or the files it installs, open an issue in the project's repository,
  [github.com/corytron/local-agent-stack](https://github.com/corytron/local-agent-stack), with every
  address, domain, key and name replaced by the placeholders of this guide.

## Terminology

Table: Terminology

| Term | Definition |
|---|---|
| `ai-net` | The external Docker network that every app of the stack joins. Containers reach each other on it by name. |
| AMX | Advanced Matrix Extensions: matrix instructions of Intel Sapphire Rapids processors. llama.cpp uses them for dense CPU work such as embeddings and reranking, not for decoding with offloaded experts. |
| ARC | Adaptive Replacement Cache: the ZFS read cache in system RAM. The stack caps it so that the models keep their share of memory. |
| Compaction | The agent's summary of older conversation turns, written when the context window fills up. |
| Context window | The number of tokens a model processes in one request: prompt, history, tool results and output. The `coder` model runs with 65,536 tokens. |
| Custom app | A TrueNAS app installed from YAML through **Install via YAML**. Each app of the stack is a short YAML file that includes a compose file from the repository. |
| Dataset | A ZFS file system inside a pool, with its own properties, permissions and snapshots. |
| Decode | Generation of output tokens, one at a time. Its speed is limited by memory bandwidth. |
| DNS-01 | An ACME challenge that proves control of a domain through a DNS TXT record. It lets Caddy obtain trusted certificates for host names that are only reachable on the LAN. |
| Embedding | A vector that represents the meaning of a text passage. Similar passages have nearby vectors, which makes semantic search possible. |
| Expert offload | Keeping the expert weights of some layers of a mixture-of-experts model in system RAM (`--n-cpu-moe`), so that a model larger than the VRAM can run. |
| GGUF | The single-file model format of llama.cpp: quantized weights plus the metadata and chat template. |
| Harness | The program around a model that runs the agent loop: tools, permissions, memory files and sub-agents. OpenCode and Claude Code are harnesses. |
| KV cache | The attention keys and values that a model keeps for every token in its context. Its size grows with the context length; the stack stores it at `q8_0`. |
| llama.cpp | An open-source inference engine for GGUF models. Its `llama-server` program serves OpenAI- and Anthropic-format APIs. |
| llama-swap | A proxy that starts and stops `llama-server` processes on demand, keeps one GPU model loaded at a time and keeps the CPU models running. |
| LiteLLM | An API gateway that serves both API formats under one address, with virtual keys, rate limits and usage logs. |
| MCP | Model Context Protocol: an open protocol that connects agents to tool servers, over stdio or Streamable HTTP. |
| MCP hub | The `mcp-hub` container (`mcp-proxy`), which serves several stdio MCP servers over HTTP at `/servers/<name>/mcp` behind one bearer token. |
| MoE | Mixture of experts: a model architecture that activates only a few expert sub-networks per token. Qwen3.6-35B-A3B has 35 billion parameters, of which about 3 billion are active per token. |
| MTP | Multi-token prediction: a model head that drafts several tokens ahead, which llama.cpp uses for speculative decoding to raise decode speed. |
| OpenCode | An open-source (MIT) terminal coding agent, used as the main harness of the stack. |
| Open WebUI | A self-hosted web interface for chat, retrieval over documents, web search and MCP tools. |
| pgvector | A PostgreSQL extension that stores vectors and searches them. Open WebUI uses it for the document index. |
| Prefill | Processing of the input tokens before the first output token. A long first prompt takes seconds to tens of seconds. |
| Quantization | Storing model weights or the KV cache with fewer bits per value. The `coder` model uses about 3.5 bits per weight. |
| RAG | Retrieval-augmented generation: searching your documents and passing the best passages to the model with the question. |
| Reranker | A model that scores each retrieved passage against the query, so that only the most relevant passages reach the context. |
| SearXNG | A self-hosted metasearch engine that queries public search engines and returns the results as HTML or JSON. |
| VRAM | Memory on the GPU. The RTX 4080 has 16 GB, which decides which models and context lengths fit. |

## Revision history

Table: Revision history

| Revision | Date | Description |
|---|---|---|
| A00 | November 2026 | Initial release, for Local Agent Stack v1.0: planning, the four TrueNAS apps, the workstation clients, the project workflow with agents, validation, evaluation, operation, troubleshooting and removal, with six appendices. Written before the first run on the reference server ([Validation status and known issues](#validation-status-and-known-issues)). |
