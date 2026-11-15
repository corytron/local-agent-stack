title: Planning the deployment

# Planning the deployment

This chapter describes the hardware the stack is sized for, the software the workstation needs,
how the GPU memory and the system memory are budgeted, the host names and ports the stack uses,
the accounts and tokens you need before you start, and how the stack is exposed and protected. It
ends with a checklist to complete before you continue with Chapter 3.

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
| Workstation | `c4dev` (`192.0.2.20`), Ubuntu 26.04 LTS on x86_64 | Runs the coding agent while you use it; other clients log in to it over SSH, and a Mac can also run its own copy of the agent |

### Minimum requirements

Table: Minimum requirements

| Requirement | Minimum | Reason |
|---|---|---|
| TrueNAS SCALE | 25.10.6 | The first 25.10 release with NVIDIA driver 580.173.02. Releases 25.10.0 to 25.10.5 ship driver 570.172.08 |
| GPU architecture | NVIDIA Turing or newer | TrueNAS 25.10 builds the driver from NVIDIA's open kernel modules, which support Turing and newer only |
| GPU memory | 16 GB | The model profiles in this guide are sized for 16 GB. Other sizes need other models |
| GPU assignment | Not isolated | TrueNAS offers **Install NVIDIA Drivers** only for a GPU that is not isolated. A GPU isolated for a virtual machine cannot be used by apps |
| Display on the GPU | None | The VRAM budget assumes that the card drives no display. Chapter 3 checks it ([Verify the GPU on the host and in a container](#verify-the-gpu-on-the-host-and-in-a-container)) |
| System memory | 64 GB | The memory budget in this chapter assumes 62.3 GiB usable. Less memory is not supported: the ZFS ARC cap, the document parser's limits and the fast profile are sized for 64 GB. More memory is supported ([Memory upgrade to four channels](#memory-upgrade-to-four-channels)) |
| Host Secure Boot | Off | Forum reports say that the TrueNAS 25.10 host does not boot with Secure Boot on (reported, not verified). Turn it off in the firmware setup before you install or reinstall TrueNAS |
| Free space on the apps pool | About 37 GB (34.5 GiB) for the model files, plus the container images | See the model files table below |

!!! warning
    Do not move the system to TrueNAS 27 release candidates while you follow this guide. A change of
    the NVIDIA driver branch changes which container images can start. Stay on 25.10.8 and repeat
    the CUDA compatibility check before any later upgrade.

### Workstation requirements

The workstation runs the coding agent, the repository's tools and the commands of this guide that
do not run on the server. Nothing of the stack runs on it as a service, container or timer.

Table: Workstation software

| Software | Version | Needed for |
|---|---|---|
| Operating system | Ubuntu 24.04 LTS or later, or macOS; x86_64 or arm64 | `clients/install.sh` and OpenCode (Chapter 7). The reference workstation runs Ubuntu 26.04 LTS on x86_64. A Windows computer reaches the agent only over SSH to a Linux workstation |
| Git | A current release | Cloning and updating the repository |
| OpenSSH client: `ssh`, `scp`, `ssh-keygen` | A current release | Access to TrueNAS (Chapter 3) and the SSH tool (Chapter 7) |
| `curl`, `tar`, `openssl` | A current release | `clients/install.sh` stops without them; several checks in this guide use `curl` and `openssl` |
| Python | 3.11 or later, with the `venv` module (package `python3-venv` on Ubuntu) | `tools/secrets.py`, `smoke.py`, `eval.py`, and `deploy.py` in its own virtual environment |
| Node.js and npm | 20.6 or later | The SSH tool `ssh-mcp`; without it the installer skips the SSH tool and installs everything else. Qwen Code (Appendix B) needs Node.js 22 or later |
| Docker CLI with the Compose plugin | `docker compose` (v5.6.0 checked); no Docker daemon | The image comparison of `deploy.py plan` and `drift` (Chapter 10), and the `compose` check of `tools/check.sh` (Chapter 8) |
| GitHub CLI, `gh` | 2.103.2 checked | The project workflow (Chapter 8) and `deploy.py drift --issue` |
| Check tools of `tools/setup-checks.sh` | Pinned by the script | The repository checks (Chapter 8); the script supports Linux on x86_64 only |
| A web browser | A current release | Open WebUI and the TrueNAS web interface |
| Claude Code | 2.1.325 checked | Only for the optional Claude Code path (Chapter 7) |

OpenCode itself needs no Node.js: `clients/install.sh` installs its native build for Linux or
macOS on x86_64 or arm64.

!!! note
    Ubuntu 24.04 LTS ships Node.js 18.19 in its archive (`nodejs` 18.19.1, checked on
    packages.ubuntu.com on 15 November 2026), which is older than the SSH tool needs. On 24.04,
    install Node.js 20.6 or later from another source, such as the official binaries on
    nodejs.org. Ubuntu 26.04 LTS ships Node.js 22, so `sudo apt install nodejs npm` is enough
    there.

### Support matrix

Table: Support matrix

| Item | Supported | Status in this release |
|---|---|---|
| TrueNAS SCALE 25.10.6 to 25.10.8 | Yes; the guide is written for 25.10.8 | Not yet run on the server ([Validation status and known issues](#validation-status-and-known-issues)) |
| TrueNAS SCALE 25.10.0 to 25.10.5 | No | NVIDIA driver 570 |
| TrueNAS 27 | No | A new driver branch, no REST API and Docker 29; see the warning above |
| NVIDIA GeForce RTX 4080 16 GB | Yes; the reference GPU | Figures are estimates; the fast profile's figures were measured by others on an RTX 4080 SUPER |
| Other NVIDIA GPUs with 16 GB, Turing or newer | Expected to work with the same profiles (assumed) | Not tested; speeds differ |
| GPUs with less than 16 GB | No | The model profiles do not fit |
| System memory 64 GB in two channels | Yes; the reference system | Not yet run |
| System memory 128 GB or more | Yes ([Memory upgrade to four channels](#memory-upgrade-to-four-channels)) | Not tested |
| System memory below 64 GB | No | The memory budget does not fit |
| Workstation: Ubuntu 26.04 LTS, x86_64 | Yes; the reference workstation | Repository checks, tests and the MCP hub image build ran here; not yet run against the stack |
| Workstation: Ubuntu 24.04 LTS or later, x86_64 or arm64 | Yes | Not tested; needs Node.js from outside the archive on 24.04 |
| Workstation: macOS, Apple silicon or Intel | Yes, through the macOS path of `clients/install.sh` | The macOS path has not been run on a Mac |
| Workstation: Windows | Only over SSH to a Linux workstation, and a browser | `clients/install.sh` does not run on Windows |
| Local DNS: UniFi gateway (UDM-Pro SE), UniFi Network 9.4 or later | Yes; the worked example of Chapter 5 | Labels checked against UniFi Network 9.4; the same path assumed for 10.6 and 11.0 |
| Local DNS: another router or DNS server that can hold A records | Yes | The same five records; Chapter 5 gives the rules, not the menus |
| OpenCode 2.3.0 | Yes; the primary coding agent | Not yet run against the gateway |
| Claude Code 2.1.325 | Optional; Anthropic does not support it with non-Claude models | Not yet run against the gateway |

## Sizing the GPU and system memory

The GPU memory (VRAM) decides which models and context lengths the stack can run. The system
memory holds the ZFS cache, the services, the CPU models and, for the fast profile, part of the
model weights. All figures in this section are estimates from the research notes unless they are
marked as measured; Chapter 9 measures them on your system
([Record a benchmark baseline](#record-a-benchmark-baseline)).

### Model files and disk space

The stack serves six files from public Hugging Face repositories: the four models, and the vision
projectors (`mmproj-*`) with which the two chat models read images. Chapter 4 downloads them
([Download the model files](#download-the-model-files)).

Table: Model files

| File | Hugging Face repository | Size |
|---|---|---|
| `Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf` | `ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF` | 12.12 GB |
| `mmproj-Qwen3.8-27B-Q8_0.gguf` (projector of `coder`) | `ggml-org/Qwen3.8-27B-GGUF` | 0.63 GB |
| `Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf` | `unsloth/Qwen3.6-35B-A3B-GGUF` | 22.36 GB |
| `mmproj-Qwen3.6-35B-A3B-Q8_0.gguf` (projector of `coder-moe`) | `ggml-org/Qwen3.6-35B-A3B-GGUF` | 0.61 GB |
| `Qwen3-Embedding-0.6B-Q8_0.gguf` | `Qwen/Qwen3-Embedding-0.6B-GGUF` | 0.64 GB |
| `qwen3-reranker-0.6b-q8_0.gguf` | `ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF` | 0.64 GB |
| Total | | 37.00 GB (34.5 GiB) |

The container images need additional space in the apps pool. The document parser image alone
(`docling-serve-cpu`) is about 4.4 GB.

### VRAM budget

Only one GPU model is loaded at a time: `coder` and `coder-moe` are in the same llama-swap group,
and requesting one unloads the other. The embedding and reranking models run on the CPU and use
no VRAM.

Table: VRAM budget per model

| llama-swap id | Placement | Context and KV cache | VRAM (GiB) | System RAM |
|---|---|---|---|---|
| `coder` | All layers on the GPU; the vision projector on the CPU | 65,536 tokens, `q8_0` | About 14.3 (estimate of the model's allocations; the CUDA context comes on top) | Prompt cache, and the vision projector, about 1 to 1.5 GiB |
| `coder-moe` | GPU, with the experts of 16 layers in system RAM (`--n-cpu-moe 16`); the vision projector on the CPU | 65,536 tokens, `q8_0` | About 15.7 (measured by others on an RTX 4080 SUPER; the whole process, CUDA context included) | About 8 GB of experts, and the vision projector, about 1 to 1.5 GiB |
| `embed` | CPU only (`--device none`) | Not applicable | 0 | About 1.3 GiB |
| `rerank` | CPU only (`--device none`) | Not applicable | 0 | About 1.3 GiB |

Table: VRAM of the coder model at 64K context

| Item | GiB |
|---|---|
| Model weights, including the MTP head | 11.3 |
| Recurrent state of the Gated DeltaNet layers | 0.15 |
| Compute buffer | About 0.7 |
| KV cache, 65,536 tokens at `q8_0` | 2.1 |
| Total of the model's allocations | About 14.3 |
| CUDA context of the `llama-server` process | About 0.3 (assumed) |
| Card total that `nvidia-smi` reports | About 16.0 (16,376 MiB, assumed) |
| Usable for the model's allocations on a card that drives no display, after the CUDA context | About 15.5 (assumed) |

The two figures in the per-model table are not measured the same way. The `coder` estimate counts
only what the model allocates: weights, recurrent state, compute buffer and KV cache. Each
`llama-server` process that uses the GPU also holds a CUDA context, and `nvidia-smi` counts it in
the process's memory. The `coder-moe` figure is the total that a published run reported for the
whole process (assumed to be the `nvidia-smi` reading), so it compares with the card's total of
about 16.0 GiB, not with the 15.5 GiB left for a model's own allocations. The `--n-cpu-moe` value
sets how much of `coder-moe` stays on the GPU; in the same run, `--n-cpu-moe 14` overflowed VRAM.
Chapter 4 reads the real totals on your card
([Check GPU memory and processes](#check-gpu-memory-and-processes)).

A monitor attached to the card takes VRAM for the display and leaves less for the models. The
budget assumes a card that drives no display, which Chapter 3 checks.

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
    loads ([Check GPU memory and processes](#check-gpu-memory-and-processes)). The vision
    projector is not in these figures: the stack loads it into system RAM and runs it on the CPU
    (`--no-mmproj-offload`). On the GPU it would take 0.59 GiB (`Q8_0`) or 0.87 GiB (`BF16` or
    `F16`) of the VRAM that the 64K context needs.

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
| Vision projector of the loaded chat model | About 1 to 1.5 | About 1 to 1.5 | Weights (0.6 GiB) and compute buffer; only one of the two projectors is loaded at a time, never both |
| `embed` and `rerank` on the CPU | About 2.6 | About 2.6 | |
| `coder-moe` experts in system RAM | 0 | About 8 | `--n-cpu-moe 16` |
| LiteLLM and its PostgreSQL | About 2 | About 2 | |
| `ai-rag` and `ai-web` services | About 14 | About 14 | Includes the document parser at up to 8 GB |
| Total | About 44 | About 52 | |
| Free of 62.3 GiB | About 18 | About 10 | Page cache and load spikes |

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
resolve to the TrueNAS server through your local DNS, and Caddy serves them all on port 443. The
TrueNAS web interface keeps ports of its own.

### Placeholder values

This guide uses placeholder addresses and names. Replace them with your own values wherever they
appear.

Table: Placeholder values

| Placeholder | Meaning |
|---|---|
| `192.0.2.10` | LAN address of the TrueNAS server (`truenas.lab.example.com`) |
| `192.0.2.20` | LAN address of the workstation `c4dev` |
| `192.0.2.1` | LAN address of the gateway and local DNS server, a UniFi Dream Machine Pro SE in the worked example |
| `<ui-https-port>`, `<ui-http-port>` | The HTTPS and HTTP ports of the TrueNAS web interface; `444` and `81` in this guide's examples |
| `lab.example.com` | Your lab domain (`LAB_DOMAIN`), in a zone at your DNS provider (`example.com`) |
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

The names use split-horizon DNS: they resolve on the LAN only, and the public zone does not know
them. Chapter 5 sets them up ([Create the local DNS records](#create-the-local-dns-records)):

- **Local records.** Your local DNS server holds one A record per name, five in all, each pointing
  to `192.0.2.10`. In the worked example, the server is a UniFi Dream Machine Pro SE (UDM-Pro SE),
  where each record is a **Host (A)** DNS policy in the UniFi Network application
  (**Settings** > **Policy Table**). UniFi has no wildcard records, so each name needs its own.
- **A fixed address for TrueNAS.** The records point to one address, so the server keeps it: a
  fixed IP address in UniFi, or a DHCP reservation in another DNS server.
- **Clients ask the local DNS server.** Every network hands out the gateway as its DNS server, which
  is the UniFi default. Browsers keep a secure DNS setting that falls back to it
  ([Browsers and DNS over HTTPS](#browsers-and-dns-over-https)), and the TrueNAS server stays out of
  every UniFi Content Filter and Ad Blocking policy, which would redirect the DNS queries of the
  certificate checks ([Keep the server out of DNS redirection](#keep-the-server-out-of-dns-redirection)).
- **No public records.** The public zone at your DNS provider holds no record for the lab names.
  Caddy obtains the certificates through the DNS-01 challenge, which only needs an API token for
  the zone and writes a temporary TXT record under `_acme-challenge`. If the zone has a wildcard
  record, one marker record at the lab domain keeps it from answering for the lab names
  ([Check the public zone](#check-the-public-zone)).
- **IPv4 only.** The names get no AAAA records, so clients with IPv6 connect over IPv4.

### Server ports

The stack needs three ports on the server, all for Caddy: 80/tcp, 443/tcp and 443/udp. Nothing else
may hold them. The TrueNAS web interface and the other services of the server keep their own
ports. Before anything is installed, Chapter 3 runs `tools/port-inventory.sh`, which lists every
listening port, the ports that containers publish and the web interface's ports, and says whether
the three ports are free ([Check the ports for the edge proxy](#check-the-ports-for-the-edge-proxy)).
The web interface moves only if it holds port 80 or 443, as it does after a new TrueNAS
installation.

Table: Ports published on the TrueNAS server

| Port | Service | Notes |
|---|---|---|
| 443/tcp | `caddy` (`ai-edge`) | HTTPS for every host name |
| 443/udp | `caddy` (`ai-edge`) | HTTP/3 for every host name |
| 80/tcp | `caddy` (`ai-edge`) | Redirects to HTTPS |
| `<ui-https-port>`/tcp, `<ui-http-port>`/tcp | TrueNAS web interface | Its own ports, other than 80 and 443: `444` and `81` in this guide's examples ([Change the web interface ports](#change-the-web-interface-ports), only if it holds 80 or 443) |
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
the LAN; a firewall between the LAN and the internet must allow them.

Table: Outbound connections

| Destination | From | Port | Purpose |
|---|---|---|---|
| Container registries: `ghcr.io` and Docker Hub (`docker.io`) | TrueNAS | 443/tcp | Pulling the images at installation and update, and the base images of an image built on the server |
| Hugging Face and the servers it redirects downloads to | TrueNAS | 443/tcp | Downloading the model files |
| GitHub (`github.com`) | TrueNAS and the workstation | 443/tcp | Cloning and updating the repository; release assets |
| Your DNS provider's API and the ACME certificate authority | `caddy` | 443/tcp | Issuing and renewing certificates (DNS-01) |
| Public DNS resolvers `1.1.1.1` and `1.0.0.1`, or the ones you set in `ACME_RESOLVERS` | `caddy` | 53/udp and 53/tcp | Checking the challenge record during DNS-01. A firewall that blocks or redirects outbound DNS to these addresses breaks certificate issuance, and so does a UniFi Content Filter or Ad Blocking policy that covers the server |
| Public search engines | `searxng` | 443/tcp | Web search |
| Any public web server whose image a request names by its web address | `llama-swap` (`llama-server`) | 443/tcp, and 80/tcp for `http://` addresses | Only for an image sent as an `http(s)://` address instead of the image data, for example by a script: `llama-server` downloads it (at most 10 MB, within 10 seconds) and refuses addresses that are not public. Open WebUI, OpenCode and Claude Code send the image data itself |
| Any public web server whose page a tool is asked to read | `mcp-hub` (its `fetch` and `web_url_read` tools) and `open-webui` on TrueNAS; OpenCode's `webfetch` on the workstation | 443/tcp, and 80/tcp for `http://` addresses | Reading web pages and remote documents for the models |
| npm registry (`registry.npmjs.org`) | The workstation | 443/tcp | Installing OpenCode, `ssh-mcp` and, optionally, Qwen Code |
| PyPI and GitHub release downloads | The workstation | 443/tcp | The check tools of `tools/setup-checks.sh`, and the TrueNAS API client that `deploy.py` uses |
| npm registry, PyPI, the Go module proxy and GitHub | TrueNAS | 443/tcp | Only when you build the MCP hub image or the Caddy image on the server instead of pulling it |

## Accounts, keys and tokens

Collect the accounts and tokens in the first table before you start. The deployment creates the
secrets in the second table; you do not need to prepare them.

Table: Accounts and credentials you provide

| Item | Used for | Notes |
|---|---|---|
| A domain at a supported DNS provider | Host names and certificates (`LAB_DOMAIN`, `DNS_PROVIDER`) | The edge image includes the modules `cloudflare`, `route53`, `digitalocean`, `porkbun`, `namecheap`, `duckdns`, `desec` and `ovh` |
| An API token for that DNS zone | DNS-01 challenge (`DNS_PROVIDER_TOKEN`) | Scope it to the one zone. Some providers need more than one credential; Chapter 5 names the variables ([Credentials by DNS provider](#credentials-by-dns-provider)) |
| An email address | ACME account of the certificates (`ACME_EMAIL`) | |
| An administrator login to the UniFi Network application, or to your local DNS server | The local DNS records, the server's fixed address and the Content Filter check (Chapter 5) | |
| The TrueNAS administrator `truenas_admin`, with the workstation's SSH public key | Shell access and deployment over SSH | **Credentials** > **Users**: **Public SSH Key** and **SSH Access** |
| An SMB user | Copying documents to the `rag-docs` share | An SMB share cannot be reached as `root` or a built-in user |
| Two TrueNAS API keys, roles READONLY_ADMIN and FULL_ADMIN | `tools/deploy.py`: the read-only key for plan, drift and status; the full key only for apply | Created in Chapter 3 ([Create TrueNAS API keys for deploy.py](#create-truenas-api-keys-for-deploypy)) and stored in `~/.config/local-agent-stack/` on the workstation; Chapter 10 configures `deploy.py` with them |
| A GitHub account | The project workflow in Chapter 8: issues, pull requests and CI | Not needed to clone the public repository |

A Hugging Face account is not needed. The six model repositories are public and not gated
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

## Security overview

The stack serves the LAN only, and it keeps its credentials in two places: the dataset
`tank/ai/secrets` on the server (`/mnt/tank/ai/secrets`, owned by root, mode 0700) and
`~/.config/local-agent-stack/` on the workstation (your user, mode 0700). This topic summarizes
the exposure and the credentials; the linked sections give the details and the procedures.

### Network exposure

- Of the stack's containers, only `caddy` publishes ports on the server: 80/tcp, which only
  redirects, and 443 over TCP and UDP. Every host name behind it asks for its own credential,
  except `search.lab.example.com`: SearXNG has no login
  ([What the edge exposes](#what-the-edge-exposes)).
- Caddy closes every connection from an address outside `EDGE_ALLOWED_CIDRS`, by default the
  private address ranges ([LAN-only access guard](#lan-only-access-guard)). TrueNAS has no host
  firewall in its web interface, so do not forward any port from your router to the server.
- The TrueNAS web interface (`<ui-https-port>` and `<ui-http-port>`, 444 and 81 in this guide's
  examples), SSH (22) and SMB (445) are TrueNAS's own services. Caddy does not proxy them, and its
  guard does not apply to them.
- The containers reach each other by name on `ai-net`; their ports are not published.
- The connections that leave the LAN are listed in [Outbound connections](#outbound-connections).

### Credentials and who holds them

Table: Credentials of the stack

| Credential | Kept in | Grants |
|---|---|---|
| The `truenas_admin` password and the workstation's SSH key | The password with you; the key in `~/.ssh/` on the workstation | Full control of the server, with `sudo` ([Enable SSH access to TrueNAS](#enable-ssh-access-to-truenas)) |
| TrueNAS API keys of `deploy-read` and `deploy-apply` | `truenas-read.key` and `truenas-apply.key` on the workstation | Read-only administration (`deploy-read`) and full administration (`deploy-apply`); an API key bypasses two-factor authentication ([Create TrueNAS API keys for deploy.py](#create-truenas-api-keys-for-deploypy)) |
| `LITELLM_MASTER_KEY` | `inference.env` | Every function of the gateway, including the LiteLLM Admin UI at `https://llm.lab.example.com/ui`, which any client inside `EDGE_ALLOWED_CIDRS` can open ([Workstation keys and where they go](#workstation-keys-and-where-they-go)) |
| LiteLLM virtual keys | `client.env` of each workstation; `LITELLM_WEBUI_KEY` in `web.env` | The model names and limits of that key |
| `LLAMA_SWAP_API_KEY` | `inference.env`; also Open WebUI's reranker setting if you followed [Point the reranker at llama-swap](#point-the-reranker-at-llama-swap) | The llama-swap API and UI at `https://models.lab.example.com`, without per-key limits or usage logs |
| `MCP_HUB_TOKEN` | `web.env` and every `client.env` | Every tool of the MCP hub. All clients share the one token, so the hub cannot tell them apart |
| Open WebUI accounts, and the API keys of the `indexer` and `kb-reader` users | Open WebUI; `OIKB_TOKEN` in `rag.env`, `KB_READER_TOKEN` in `web.env` | Chats, documents and knowledge bases, as that user |
| `DNS_PROVIDER_TOKEN` | `edge.env` | The DNS records of your zone; scope the token to the one zone |
| The SSH tool's key `~/.ssh/agent_ed25519` | The workstation | Commands on the hosts in the SSH policy, as a restricted user ([How the SSH tool is protected](#how-the-ssh-tool-is-protected)) |
| The internal CA's root key, only with Appendix D | `tank/ai/appdata/caddy` | Certificates that every client trusts |

The workstation also keeps copies of the four server files under
`~/.config/local-agent-stack/secrets/`. Appendix A backs up both locations
([Data to back up](#data-to-back-up)), and the rotation procedures are in Chapters 4 and 6.

## Pre-deployment checklist

Complete every item before you continue with Chapter 3, except the items whose check names a later
chapter: complete those in that chapter.

Table: Pre-deployment checklist

| Item | How to check | Done |
|---|---|---|
| TrueNAS SCALE is 25.10.6 or later (25.10.8 recommended) | **Dashboard**, System Information card; or `midclt call system.version` in **System** > **Shell** | ☐ |
| A configuration backup is saved | **System** > **Advanced Settings** > **Manage Configuration** > **Download File**, with **Export Password Secret Seed** selected | ☐ |
| The NVIDIA GPU is not isolated | **System** > **Advanced Settings** > **Isolated GPU Device(s)** lists no device | ☐ |
| The RTX 4080 drives no display | No monitor is connected to the card; Chapter 3 checks it ([Verify the GPU on the host and in a container](#verify-the-gpu-on-the-host-and-in-a-container)) | ☐ |
| Secure Boot is off, if you install or reinstall TrueNAS | The server's firmware setup ([Minimum requirements](#minimum-requirements)) | ☐ |
| The server has at least 64 GB of memory, in two channels at 4800 MT/s | [Check the memory configuration](#check-the-memory-configuration) | ☐ |
| The apps pool is on SSD or NVMe | **Apps** > **Configuration** > **Choose Pool** | ☐ |
| The apps pool has at least 37 GB (34.5 GiB) free for the model files, plus room for the container images | **Storage** | ☐ |
| SSH from the workstation to `truenas_admin` works with a key | `ssh truenas_admin@192.0.2.10` from `c4dev`, or set it up in Chapter 3 ([Enable SSH access to TrueNAS](#enable-ssh-access-to-truenas)) | ☐ |
| Ports 80/tcp, 443/tcp and 443/udp on the server are free for Caddy | Chapter 3 runs the port inventory ([Run the port inventory](#run-the-port-inventory)); the TrueNAS web interface keeps its own ports and moves only if it holds 80 or 443 | ☐ |
| The Docker address pool does not overlap your LAN | **Apps** > **Installed** > **Configuration** > **Settings** | ☐ |
| You can add A records in your local DNS server | UniFi Network 9.4 or later: **Settings** > **Control Plane** > **Updates** shows the version, and the records go in **Settings** > **Policy Table**; or your DNS server (Chapter 5, [Add the host names to local DNS](#add-the-host-names-to-local-dns)) | ☐ |
| The TrueNAS server has a fixed LAN address | UniFi: **Client Devices** > the server > **Settings** > **Fixed IP Address** (Chapter 5, [Give the TrueNAS server a fixed IP address](#give-the-truenas-server-a-fixed-ip-address)) | ☐ |
| The clients' networks hand out the gateway as DNS server | UniFi: **Settings** > **Networks** > **DNS Server** at its default (Chapter 5, [Check the DNS server of each network](#check-the-dns-server-of-each-network)) | ☐ |
| No UniFi Content Filter or Ad Blocking policy covers the TrueNAS server | **Settings** > **CyberSecure** > **Content Filter**, the **Source** of each policy (Chapter 5, [Keep the server out of DNS redirection](#keep-the-server-out-of-dns-redirection)) | ☐ |
| The public zone holds no record for the lab names, and no wildcard answers for them | Chapter 5, [Check the public zone](#check-the-public-zone) | ☐ |
| Your domain is at a supported DNS provider, with an API token for the zone | Your DNS provider | ☐ |
| The server can reach the internet for images, models and certificates, including DNS to `1.1.1.1` and `1.0.0.1` on port 53 | [Outbound connections](#outbound-connections) | ☐ |
| The workstation has Git, the OpenSSH client, `curl`, `tar`, `openssl` and Python 3.11 or later with `venv` | `git --version`, `ssh -V`, `python3 --version` on the workstation ([Workstation requirements](#workstation-requirements)) | ☐ |
| The workstation has Node.js 20.6 or later and npm, for the SSH tool | `node --version`; or install it before Chapter 7 | ☐ |
| The workstation has the Docker CLI with the Compose plugin, for `deploy.py` | `docker compose version`; or install it before Chapter 10 | ☐ |
| `gh` is installed and a GitHub account is ready, if you use the workflow in Chapter 8 | `gh --version`; github.com | ☐ |
