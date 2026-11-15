title: Planning the deployment

# Planning the deployment

This chapter describes the hardware the stack is sized for, how the GPU memory and the system
memory are budgeted, the host names and ports the stack uses, and the accounts and tokens you need
before you start. It ends with a checklist to complete before you continue with Chapter 3.

## Hardware requirements and the reference system

The stack is designed and sized for one reference system. The model choices, context lengths and
memory budgets in this guide depend on its GPU and on how its memory channels are populated.

### Reference system

Table: Reference system

| Component | Reference system | Notes |
|---|---|---|
| Operating system | TrueNAS SCALE 25.10.8 "Goldeye" | Docker-based apps; NVIDIA driver 580.173.02 included |
| Processor | Intel Xeon w5-3435X | Sapphire Rapids, 16 cores and 32 threads, AVX-512 and AMX, eight DDR5-4800 memory channels |
| Memory | Two 32 GB DDR5-4800 RDIMMs (64 GB, 62.3 GiB usable) | Two of eight channels populated |
| GPU | NVIDIA GeForce RTX 4080, 16 GB | Ada architecture, compute capability 8.9, 716.8 GB/s memory bandwidth, PCIe 4.0 x16, 320 W board power |
| Storage | Pool `tank` on SSD or NVMe | Holds the apps, the models and the stack's datasets |
| Workstation | `c4dev` (`192.0.2.20`), Ubuntu Linux | Runs the coding agent while you use it; other clients log in to it over SSH, and a Mac can also run its own copy of the agent |

### Minimum requirements

Table: Minimum requirements

| Requirement | Minimum | Reason |
|---|---|---|
| TrueNAS SCALE | 25.10.6 | The first 25.10 release with NVIDIA driver 580.173.02. Releases 25.10.0 to 25.10.5 ship driver 570.172.08 |
| GPU architecture | NVIDIA Turing or newer | TrueNAS 25.10 builds the driver from NVIDIA's open kernel modules, which support Turing and newer only |
| GPU memory | 16 GB | The model profiles in this guide are sized for 16 GB. Other sizes need other models |
| GPU assignment | Not isolated | TrueNAS offers **Install NVIDIA Drivers** only for a GPU that is not isolated. A GPU isolated for a virtual machine cannot be used by apps |
| System memory | 64 GB | The memory budget in this chapter assumes 62.3 GiB usable |
| Free space on the apps pool | About 36 GB for the models, plus the container images | See the model files table below |

!!! warning
    Do not move the system to TrueNAS 27 release candidates while you follow this guide. A change of
    the NVIDIA driver branch changes which container images can start. Stay on 25.10.8 and repeat
    the CUDA compatibility check before any later upgrade.

## Sizing the GPU and system memory

The GPU memory (VRAM) decides which models and context lengths the stack can run. The system
memory holds the ZFS cache, the services, the CPU models and, for the fast profile, part of the
model weights. All figures in this section are estimates from the research notes unless they are
marked as measured; Chapter 9 measures them on your system
([Record a benchmark baseline](#record-a-benchmark-baseline)).

### Model files and disk space

All four model files come from public Hugging Face repositories.

Table: Model files

| File | Hugging Face repository | Size |
|---|---|---|
| `Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf` | `ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF` | 12.12 GB |
| `Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf` | `unsloth/Qwen3.6-35B-A3B-GGUF` | 22.36 GB |
| `Qwen3-Embedding-0.6B-Q8_0.gguf` | `Qwen/Qwen3-Embedding-0.6B-GGUF` | 0.64 GB |
| `qwen3-reranker-0.6b-q8_0.gguf` | `ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF` | 0.64 GB |
| Total | | 35.76 GB |

The container images need additional space in the apps pool. The document parser image alone
(`docling-serve-cpu`) is about 4.4 GB.

### VRAM budget

Only one GPU model is loaded at a time: `coder` and `coder-moe` are in the same llama-swap group,
and requesting one unloads the other. The embedding and reranking models run on the CPU and use
no VRAM.

Table: VRAM budget per model

| llama-swap id | Placement | Context and KV cache | VRAM (GiB) | System RAM |
|---|---|---|---|---|
| `coder` | All layers on the GPU | 65,536 tokens, `q8_0` | About 14.3 (estimate) | Prompt cache only |
| `coder-moe` | GPU, with the experts of 16 layers in system RAM (`--n-cpu-moe 16`) | 65,536 tokens, `q8_0` | About 15.7 (measured on an RTX 4080 SUPER) | About 8 GB of experts |
| `embed` | CPU only (`--device none`) | Not applicable | 0 | About 1.3 GiB |
| `rerank` | CPU only (`--device none`) | Not applicable | 0 | About 1.3 GiB |

Table: VRAM of the coder model at 64K context

| Item | GiB |
|---|---|
| Model weights, including the MTP head | 11.3 |
| Recurrent state of the Gated DeltaNet layers | 0.15 |
| Compute buffer | About 0.7 |
| KV cache, 65,536 tokens at `q8_0` | 2.1 |
| Total | About 14.3 |
| Usable on a headless RTX 4080 after the CUDA context | About 15.5 (assumed) |

The KV cache of Qwen3.8-27B is small for a 27B model: only 16 of its 64 layers keep a KV cache.
That is what makes 64K context fit next to the weights. Longer contexts cost VRAM as follows.

Table: VRAM of the coder model by context length

| Context | VRAM (GiB, estimate) | Fits in 16 GB |
|---|---|---|
| 32,768 tokens | 13.2 | Yes |
| 65,536 tokens | 14.3 | Yes (default) |
| 98,304 tokens | 15.3 | Tight |
| 131,072 tokens | Does not fit | No |

!!! note
    The estimates carry about ±0.5 GiB of uncertainty, and they include the weights of the MTP
    head but not any working memory that speculative decoding adds; Unsloth's documentation puts
    MTP's extra need at 1 to 2 GB. Chapter 4 checks the real usage with `nvidia-smi` after the model
    loads ([Check GPU memory and processes](#check-gpu-memory-and-processes)). Loading the model's vision projector would add 0.59 GiB (`Q8_0`) or 0.87 GiB (`F16`), so
    the default profile does not load it.

!!! note
    Keep the KV cache at `q8_0`. llama.cpp's documentation warns that `q4_0` can substantially
    degrade tool calling.

### System RAM budget

The ZFS ARC, the services and the models share the system memory. Chapter 3 caps the ARC at
12 GiB (`zfs_arc_max` = `12884901888`, [Cap the ZFS ARC](#cap-the-zfs-arc)), which leaves room for
the model processes.

Table: System RAM budget (GiB, estimates)

| Consumer | With `coder` loaded | With `coder-moe` loaded | Note |
|---|---|---|---|
| TrueNAS operating system, middleware and Docker | About 4 | About 4 | |
| ZFS ARC | 12 | 12 | Capped in Chapter 3 |
| llama-swap: prompt cache and host buffers | About 8 | About 8 | Keeps idle conversations ready for reuse |
| `embed` and `rerank` on the CPU | About 2.6 | About 2.6 | |
| `coder-moe` experts in system RAM | 0 | About 8 | `--n-cpu-moe 16` |
| LiteLLM and its PostgreSQL | About 2 | About 2 | |
| `ai-rag` and `ai-web` services | About 14 | About 14 | Includes the document parser at up to 8 GB |
| Total | About 43 | About 51 | |
| Free of 62.3 GiB | About 20 | About 12 | Page cache and load spikes |

### Memory channels and bandwidth

The Xeon w5-3435X has eight DDR5-4800 memory channels and reaches full speed with one module per
channel. The reference system populates two channels. That limits the system memory bandwidth to
76.8 GB/s in theory, and to an estimated 40 to 50 GB/s for llama.cpp's CPU expert kernels, against
716.8 GB/s for the GPU memory.

Generating a token reads every active weight once, so a model whose weights sit in system memory
generates tokens far more slowly than one held in VRAM. For that reason the stack keeps its main
model entirely on the GPU, and uses expert offload only for `coder-moe`, which reads about 0.25 GB
of experts from system memory per token.

Table: Memory bandwidth by populated channels

| Modules (matched, one per channel) | Peak bandwidth | Achieved by llama.cpp (estimate) | Capacity with 32 GB RDIMMs |
|---|---|---|---|
| 2 (reference system) | 76.8 GB/s | 40–50 GB/s | 64 GB |
| 4 | 153.6 GB/s | 80–100 GB/s | 128 GB |
| 8 | 307.2 GB/s | 130–180 GB/s | 256 GB |

Larger mixture-of-experts models, such as gpt-oss-120b, GLM-4.5-Air, Qwen3.5-122B-A10B and
Mistral-Small-4-119B, either do not fit beside TrueNAS in 64 GB or generate only about 10 to 20
tokens per second on two channels. Do not plan on them with this memory configuration. Appendix B
describes what two more modules change.

!!! note
    The AMX and AVX-512 units of the processor speed up the CPU models (embedding and reranking).
    They do not raise the speed of offloaded experts, which is limited by the memory channels.

### Expected model performance

Table: Expected model performance on the reference system

| Profile | Generation (tokens/s) | Prompt processing (tokens/s) | Basis |
|---|---|---|---|
| `coder` | 40–45; 50–65 with MTP | About 900–1,500 | Estimate from the bandwidth model |
| `coder-moe` | 65–80 | About 1,800–2,000 | Measured at 80 and 1,782–2,068 on an RTX 4080 SUPER with two-channel DDR5-4800 |

With `coder`, a first request of 30,000 tokens takes about 20 to 35 seconds to process. Later turns
reuse the prompt cache and process only the new tokens.

### Check the memory configuration

#### Prerequisites

- Administrator access to the TrueNAS web interface.

#### About this task

The sizing in this chapter assumes that the two memory modules sit in two different channels and
run at 4800 MT/s. Two modules in the same channel halve the bandwidth figures above. This task
reads the module placement and speed from the system firmware.

#### Steps

1. In the TrueNAS web interface, go to **System** > **Shell**.
2. List the memory slots:

        sudo dmidecode -t memory | grep -E '^\s+(Size|Locator|Bank Locator|Configured Memory Speed):'

    The command prints four lines for each slot. A populated slot shows `Size: 32 GB` and
    `Configured Memory Speed: 4800 MT/s`. An empty slot shows `Size: No Module Installed`.

3. Note the `Locator` and `Bank Locator` values of the two populated slots, and find them in the
   channel map of the motherboard manual.

#### Results

Two 32 GB modules run at 4800 MT/s in two different channels. If the modules share a channel or run
at a lower speed, expect lower speeds for `coder-moe` than the table above; `coder` is not
affected because it runs entirely on the GPU.

!!! caution
    Before you move or add memory modules, shut down TrueNAS from the web interface and disconnect
    the power. Install matched RDIMMs, one per channel, in the slot order given in the motherboard
    manual.

## Network, DNS names and ports

The stack is reached only on the LAN. Every service has a host name under your domain; the names
resolve to the TrueNAS server through your local DNS, and Caddy serves them all on port 443.

### Placeholder values

This guide uses placeholder addresses and names. Replace them with your own values wherever they
appear.

Table: Placeholder values

| Placeholder | Meaning |
|---|---|
| `192.0.2.10` | LAN address of the TrueNAS server (`truenas.lab.example.com`) |
| `192.0.2.20` | LAN address of the workstation `c4dev` |
| `lab.example.com` | Your domain, a zone at your DNS provider (`LAB_DOMAIN`) |
| `tank` | The ZFS pool that holds the apps, the models and the stack's datasets |
| `sk-local-...` | An API key; the real values are generated during deployment |

### Host names and DNS records

Table: Host names

| Host name | Upstream (container:port) | Used by |
|---|---|---|
| `chat.lab.example.com` | `open-webui:8080` | Browsers |
| `llm.lab.example.com` | `litellm:4000` (OpenAI `/v1/...` and Anthropic `/v1/messages`) | OpenCode, Claude Code, scripts |
| `models.lab.example.com` | `llama-swap:8080` (model list, logs; API key required) | Administrators |
| `mcp.lab.example.com` | `mcp-hub:8096` | OpenCode, Open WebUI |
| `search.lab.example.com` | `searxng:8080` | Administrators (optional) |

Chapter 5 adds an A record for each name in your local DNS server or router, pointing to
`192.0.2.10` ([Add the host names to local DNS](#add-the-host-names-to-local-dns)). The names do not need public DNS records: Caddy obtains the certificates through the
DNS-01 challenge, which only needs an API token for the zone at your DNS provider.

### Server ports

Table: Ports published on the TrueNAS server

| Port | Service | Notes |
|---|---|---|
| 443/tcp | `caddy` (`ai-edge`) | HTTPS for every host name |
| 80/tcp | `caddy` (`ai-edge`) | Redirects to HTTPS |
| 8443/tcp, 8080/tcp | TrueNAS web interface | Moved from 443 and 80 in Chapter 3 ([Change the web interface ports](#change-the-web-interface-ports)) |
| 22/tcp | SSH | Administration and deployment from the workstation |
| 445/tcp | SMB | The `rag-docs` document share |

Table: Container ports on ai-net (not published)

| Container | App | Port |
|---|---|---|
| `llama-swap` | `ai-inference` | 8080 |
| `litellm` | `ai-inference` | 4000 |
| `litellm-db` | `ai-inference` | 5432 |
| `pgvector` | `ai-rag` | 5432 |
| `docling` | `ai-rag` | 5001 |
| `oikb` | `ai-rag` | None |
| `open-webui` | `ai-web` | 8080 |
| `searxng` | `ai-web` | 8080 |
| `mcp-hub` | `ai-web` | 8096 |
| `gpu-exporter` | `ai-edge` | 9835 |

Several containers use the same internal port. They do not conflict, because each container has
its own address on `ai-net` and only `caddy` publishes ports on the server.

Nothing of the stack listens on a workstation. OpenCode, the SSH tool and `claude-local` run only
while you use them, and `clients/install.sh` keeps OpenCode's background service disabled
([Why the OpenCode service stays disabled](#why-the-opencode-service-stays-disabled)). A Mac
either logs in to `c4dev` over SSH and runs OpenCode there, or runs its own OpenCode against the
gateway ([Use OpenCode from the Mac](#use-opencode-from-the-mac)); the Windows VM logs in to
`c4dev` over SSH ([Use the Windows VM](#use-the-windows-vm)).

!!! warning
    TrueNAS 25.10 has no host firewall in its web interface, and with Apps enabled Docker forwards
    traffic to every published port. Publish only the ports in the table above, and do not forward
    any port from your router to the server. The stack is designed for access from the LAN only.

!!! note
    Docker on TrueNAS assigns container networks from the address pool `172.17.0.0/12` in /24
    blocks by default. If your LAN uses addresses in that range, change the pool before you install
    the apps: **Apps** > **Installed** > **Configuration** > **Settings** > **Address Pools**.

### Outbound connections

Inference, retrieval and the tools run without internet access. The following connections leave
the LAN.

Table: Outbound connections

| Destination | From | Purpose |
|---|---|---|
| Container registries (`ghcr.io`, Docker Hub) | TrueNAS | Pulling the images at installation and update |
| Hugging Face | TrueNAS | Downloading the model files |
| GitHub | TrueNAS and the workstation | Cloning and updating the repository |
| Your DNS provider's API and the ACME certificate authority | `caddy` | Issuing and renewing certificates (DNS-01) |
| Public search engines | `searxng` | Web search |
| Package registries | The workstation | Installing OpenCode and `ssh-mcp` |

## Accounts, keys and tokens

Collect the accounts and tokens in the first table before you start. The deployment creates the
secrets in the second table; you do not need to prepare them.

Table: Accounts and credentials you provide

| Item | Used for | Notes |
|---|---|---|
| A domain at a supported DNS provider | Host names and certificates (`LAB_DOMAIN`, `DNS_PROVIDER`) | The edge image includes the modules `cloudflare`, `route53`, `digitalocean`, `porkbun`, `namecheap`, `duckdns`, `desec` and `ovh` |
| An API token for that DNS zone | DNS-01 challenge (`DNS_PROVIDER_TOKEN`) | Scope it to the one zone. Some providers need more than one credential; Chapter 5 names the variables ([Credentials by DNS provider](#credentials-by-dns-provider)) |
| An email address | ACME account of the certificates (`ACME_EMAIL`) | |
| The TrueNAS administrator `truenas_admin`, with the workstation's SSH public key | Shell access and deployment over SSH | **Credentials** > **Users**: **Public SSH Key** and **SSH Access** |
| An SMB user | Copying documents to the `rag-docs` share | An SMB share cannot be reached as `root` or a built-in user |
| Two TrueNAS API keys, roles READONLY_ADMIN and FULL_ADMIN | `tools/deploy.py`: the read-only key for plan, drift and status; the full key only for apply | Created in Chapter 3 ([Create TrueNAS API keys for deploy.py](#create-truenas-api-keys-for-deploypy)) and stored in `~/.config/local-agent-stack/` on the workstation; Chapter 10 configures `deploy.py` with them |
| A GitHub account | The project workflow in Chapter 8: issues, pull requests and CI | Not needed to clone the public repository |

A Hugging Face account is not needed. The four model repositories are public and not gated
(checked on 15 November 2026), so the files download without signing in.

Table: Secrets created during deployment

| File | Variables | Created by |
|---|---|---|
| `inference.env` | `LITELLM_MASTER_KEY`, `LITELLM_SALT_KEY`, `LITELLM_DB_PASSWORD`, `LLAMA_SWAP_API_KEY` | `tools/secrets.py gen inference` generates all four (Chapter 3) |
| `rag.env` | `PG_PASSWORD`, `DOCLING_API_KEY`, `OIKB_API_KEY` (optional), `OIKB_TOKEN`, `OIKB_KB_ID` | `tools/secrets.py gen rag` generates the first three. `OIKB_TOKEN`, the API key of Open WebUI's `indexer` user, and `OIKB_KB_ID`, the ID of the knowledge base it fills (not secret), exist only after Open WebUI's first start (Chapter 6) |
| `web.env` | `LAB_DOMAIN`, `WEBUI_SECRET_KEY`, `SEARXNG_SECRET`, `MCP_HUB_TOKEN`, `PG_PASSWORD`, `DOCLING_API_KEY`, `LITELLM_WEBUI_KEY`, `KB_READER_TOKEN`, `SEARXNG_CONTACT_URL` (optional) | `tools/secrets.py gen web --share rag.env` generates `WEBUI_SECRET_KEY`, `SEARXNG_SECRET` and `MCP_HUB_TOKEN` and copies `PG_PASSWORD` and `DOCLING_API_KEY` from `rag.env`. Before Open WebUI's first start you set `LAB_DOMAIN`, `SEARXNG_CONTACT_URL` and `LITELLM_WEBUI_KEY`, a LiteLLM virtual key created once `ai-inference` runs; after it, `KB_READER_TOKEN`, the API key of the `kb-reader` user (Chapter 6) |
| `edge.env` | `LAB_DOMAIN`, `ACME_EMAIL`, `DNS_PROVIDER`, `DNS_PROVIDER_TOKEN`; optional `DNS_PROVIDER_KEY_ID`, `DNS_PROVIDER_CONSUMER_KEY`, `DNS_PROVIDER_ENDPOINT`, `ACME_RESOLVERS`, `ACME_CA`, `EDGE_ALLOWED_CIDRS`, `EDGE_BIND_IP` | `tools/secrets.py gen edge` writes the example file with its placeholders; you replace them with the values from the first table (Chapter 5) |
| `~/.config/local-agent-stack/client.env` on the workstation | `LAB_DOMAIN`, `LOCAL_LLM_KEY`, `MCP_HUB_TOKEN` | `tools/secrets.py gen client --share web.env --ask LOCAL_LLM_KEY` copies `LAB_DOMAIN` and `MCP_HUB_TOKEN` from `web.env` and prompts for the workstation's LiteLLM key from Chapter 4 (Chapter 7) |

Every server file can also set `AI_ROOT`, the root of the stack's datasets (default
`/mnt/tank/ai`); change it only if every app uses the same other path.

Some values must be identical in two or three files. `tools/secrets.py` copies them with
`--share`, and the chapters that complete the files check them.

Table: Values shared between files

| Variable | Files |
|---|---|
| `PG_PASSWORD`, `DOCLING_API_KEY` | `rag.env` and `web.env` |
| `LAB_DOMAIN` | `edge.env`, `web.env` and `client.env` |
| `MCP_HUB_TOKEN` | `web.env` and `client.env` |

`tools/secrets.py gen <app>`, where `<app>` is `inference`, `rag`, `web`, `edge` or `client`, fills
in the app's example file: a new random value (48 letters and digits) for every secret it
generates, the shared values copied from the file named with `--share`, a prompt without echo for
each variable named with `--ask`, and the example's placeholder for every value that you provide or
that a running service creates later. With `-o <file>` it writes a new file with mode 0600 and
refuses to replace an existing one. Chapter 3 generates the four server files on the workstation
and installs them in the dataset `tank/ai/secrets` (`/mnt/tank/ai/secrets`, mode 0700, owned by
root).

!!! caution
    Never change `LITELLM_SALT_KEY` after the first start of LiteLLM; it encrypts the credentials
    that LiteLLM stores. Keep `WEBUI_SECRET_KEY` stable as well; Open WebUI encrypts the OAuth
    tokens of MCP connections with it. Back up the secrets dataset together with the application data.

!!! warning
    The repository is public. Keep the secrets files only in `/mnt/tank/ai/secrets` and in
    `~/.config/local-agent-stack/` on the workstation. Never copy them into the git clone, and never
    paste a key into an issue or a chat.

## Pre-deployment checklist

Complete every item before you continue with Chapter 3.

Table: Pre-deployment checklist

| Item | How to check | Done |
|---|---|---|
| TrueNAS SCALE is 25.10.6 or later (25.10.8 recommended) | **Dashboard**, System Information card; or `midclt call system.version` in **System** > **Shell** | ☐ |
| A configuration backup is saved | **System** > **Advanced Settings** > **Manage Configuration** > **Download File**, with **Export Password Secret Seed** selected | ☐ |
| The NVIDIA GPU is not isolated | **System** > **Advanced Settings** > **Isolated GPU Device(s)** lists no device | ☐ |
| The apps pool is on SSD or NVMe | **Apps** > **Configuration** > **Choose Pool** | ☐ |
| The apps pool has at least 36 GB free for models, plus room for images | **Storage** | ☐ |
| The memory modules are in two channels at 4800 MT/s | [Check the memory configuration](#check-the-memory-configuration) | ☐ |
| SSH from the workstation to `truenas_admin` works with a key | `ssh truenas_admin@192.0.2.10` from `c4dev` | ☐ |
| Ports 80 and 443 on the server are free for Caddy after the UI moves | Planned in Chapter 3 ([Move the TrueNAS web UI to ports 8080 and 8443](#move-the-truenas-web-ui-to-ports-8080-and-8443)) | ☐ |
| The Docker address pool does not overlap your LAN | **Apps** > **Installed** > **Configuration** > **Settings** | ☐ |
| You can add A records in your local DNS server or router | Your router or DNS server | ☐ |
| Your domain is at a supported DNS provider, with an API token for the zone | Your DNS provider | ☐ |
| The server can reach the internet for images, models and certificates | Outbound connections table | ☐ |
| A GitHub account is ready, if you use the workflow in Chapter 8 | github.com | ☐ |
