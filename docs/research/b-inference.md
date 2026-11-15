# Inference servers and model routing on one RTX 4080 16 GB in containers

Status: research, 2026-11-15. Author: research agent B.

Scope: the model-serving layer (inference engines, model hot-swapping, the API gateway in front
of them) for the owner's TrueNAS SCALE server, and how Claude Code and other clients reach it.
Other agents own:

- model choice: agent A;
- TrueNAS GPU, app and dataset plumbing: agent E (`docs/research/e-truenas.md`, whose
  conventions this file follows);
- GUI and RAG: agent D.

The model files named below are sizing examples, to be replaced by agent A's picks:

- gpt-oss-20b
- Qwen3-Coder-30B-A3B
- Qwen3-4B
- Qwen3-Embedding-0.6B and Qwen3-Reranker-0.6B

**Target box, confirmed by the owner via the coordinator:**

- TrueNAS SCALE 25.10.8 "Goldeye", with NVIDIA driver 580.173.02. That driver supports CUDA 13.0
  at most, so images whose `NVIDIA_REQUIRE_CUDA` asks for 13.1 or later will not start.
- 62.3 GiB usable RAM: **2 × 32 GB DDR5-4800 RDIMMs**, so only **2 of 8 channels** are populated
  (76.8 GB/s theoretical). The ZFS ARC shares this RAM and will be capped at 12 GiB.
- Intel Xeon w5-3435X: Sapphire Rapids, 16 cores / 32 threads, AVX-512 and AMX.
- RTX 4080 (or 4080 SUPER): 16 GB, Ada, compute capability 8.9.
- The stack is split into separate TrueNAS custom apps (inference, web, RAG, ops) on the shared
  external Docker network `ai-net`. The inference app described here is self-contained.

## Summary

- **Engine: llama.cpp `llama-server` only, managed by llama-swap,** in one GPU container:
  `ghcr.io/mostlygeek/llama-swap:v273-cuda-b12407`. That is the official llama.cpp
  `server-cuda-b12407` image (CUDA 12.8.1; image config `NVIDIA_REQUIRE_CUDA=cuda>=12.8`, so it
  starts on driver 580) with llama-swap v273 added. All models are GGUF.
- **Why llama.cpp:**
  - It natively serves the Anthropic `/v1/messages` and `/v1/messages/count_tokens` endpoints
    (streaming, tools, `tool_choice`, thinking), plus OpenAI chat, Responses, embeddings and
    rerank.
  - It quantises the KV cache, keeps a prompt cache in host RAM, and exposes Prometheus metrics.
  - It neutralises the per-request hash in Claude Code's system prompt.
  - It is the only engine here that can move MoE experts to the CPU one layer at a time, as an
    *option*.
- **Default profile: everything on the GPU that matters.** The host has only 2 memory channels,
  so a model whose experts live in RAM is bandwidth-bound. Hence:
  - The primary model is fully GPU-resident at **64k context**. The worked example is gpt-oss-20b
    MXFP4 (12.1 GB file, about 13.6 GiB at 64k).
  - The **embedding and reranker models run on the CPU** (`--device none`), where the image's
    AMX/AVX-512 CPU backend handles their compute-bound batches. They use no VRAM.
  - Agent A may swap in any model of about 12–13 GB or less: a dense 14B Q4 at 64k, a 24B IQ4_XS
    at 16–24k, or a 30–35B-A3B IQ3_XXS at about 24k.
  - Claude Code needs at least 64k; Ollama's docs also say coding agents need at least 64,000
    tokens.
- **Two other profiles:**
  - *RAG on GPU* (about 2.8 GiB VRAM), with the primary shrunk to a 14B-class model at 32k.
  - *MoE CPU offload* (optional): a 30B-A3B Q4 model at 64k with the experts of about 20–30 of
    its 48 layers in RAM. Expected decode is about 30–50 t/s on 2 channels with
    `-t 8 -tb 16` (estimate).
- **Gateway: LiteLLM proxy, LTS line v1.108.8, with PostgreSQL 16.13,** inside the same app.
  - It serves both API styles (OpenAI and Anthropic `/v1/messages`) and offers the virtual
    models `local-opus`, `local-sonnet` and `local-haiku`.
  - It adds per-client virtual keys, GPU-time budgets, Postgres spend logs and `/metrics`.
  - It is reached through `ai-net` and Caddy (agent E); no port is published by default.
  - **Pin it by digest.** LiteLLM was compromised twice in 2026: in March through PyPI only, and
    on 21 Oct 2026 through PyPI and Docker (`v1.107.0`, `latest`, `main-latest`, `main-stable`).
- **No custom llama.cpp build is needed for this CPU.** The official CUDA images are built with
  `GGML_NATIVE=OFF`, `GGML_BACKEND_DL=ON` and `GGML_CPU_ALL_VARIANTS=ON`. That ships a
  `sapphirerapids` CPU backend (AVX-512 VBMI/VNNI/BF16 plus AMX tile and INT8) chosen at runtime.
  - AMX helps compute-bound CPU work: RAG models, and prompt processing with `--no-op-offload`.
  - It does not lift the 2-channel bandwidth ceiling on decode.
  - Use the CUDA 12 tags only. `server-cuda13` (13.5) and llama-swap's `unified-cuda13`
    (requires CUDA 13.3) will not start on this driver.
- **Expected speeds on a 4080-class card, measured by others:**

  | Model and setup | Prompt processing (t/s) | Generation (t/s) |
  |---|---|---|
  | gpt-oss-20b, 2k prompt (4080 SUPER) | 8,171 | 186.5 |
  | gpt-oss-20b, 32k prompt (4080 SUPER) | 6,740 | not measured |
  | gpt-oss-20b (4080, Ollama) | not measured | 140 |
  | 14B dense Q4_K_M | not measured | ≈62 |
  | 30B-A3B MoE, part on CPU (Ollama, dual-channel DDR5-6000) | not measured | ≈57 |
  | Dense 24–27B spilling to the CPU | not measured | 6–19 |

  The owner's 2 × DDR5-4800 gives about 20% less bandwidth than that dual-channel DDR5-6000.
- **Pointing Claude Code at the gateway** needs these settings:
  - `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN`.
  - `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL`. `ANTHROPIC_SMALL_FAST_MODEL` is deprecated.
  - `CLAUDE_CODE_MAX_CONTEXT_TOKENS=65536`. Without it, Claude Code assumes 1M tokens for an
    unknown model ID.
  - `CLAUDE_CODE_ATTRIBUTION_HEADER=0`.

  Anthropic does not support non-Claude models behind a gateway. WebSearch (a server tool),
  Remote Control and fast mode are unavailable.
- **The alternatives:**
  - **Ollama** is the simple fallback. It has had `/v1/messages` since v0.14 and carries its own
    CUDA runners. It lacks `tool_choice`, `count_tokens`, rerank, metrics and expert-level
    offload, and defaults to a 4k context on GPUs under 24 GiB.
  - **vLLM** (v0.33.0, CUDA 13.0) and **SGLang** each preallocate the GPU for one model and have
    no practical MoE offload, so they are poor fits for 16 GB.
  - **TabbyAPI** has no Anthropic or rerank endpoint and is AGPL-licensed.
  - **LM Studio** has no official container image.
  - **LocalAI** wraps the same engines.

## Recommendation

### Architecture (TrueNAS custom app `ai-inference`)

```
 c4dev / Mac / Windows ──HTTPS──► Caddy (ops app, 443, tls internal) ─┐
 Open WebUI (web app), RAG pipeline (RAG app) ───── ai-net ───────────┤
                                                                      ▼
 ┌──────────────────────── app "ai-inference" (one compose project) ─────────────────────────┐
 │ litellm :4000  ── litellm-db (Postgres 16.13; keys, budgets, spend logs)                  │
 │   local-opus | local-sonnet | local-haiku  → anthropic/coder → llama-swap /v1/messages      │
 │   coder | small | coder-moe                → openai/<id>     → llama-swap /v1/chat/...     │
 │   embed → /v1/embeddings ; rerank → /rerank                                                │
 │ llama-swap :8080 (GPU container)                                                           │
 │   group "rag" (persistent): embed, rerank   ← CPU-only children (--device none)            │
 │   group "llm" (swap):       coder | coder-moe | small   ← one GPU model at a time          │
 │   children: llama-server on 127.0.0.1:10001+ (llama.cpp b12407, CUDA 12.8.1)              │
 └────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Why this arrangement

1. **VRAM is the scarce resource and RAM bandwidth is the second.** With 2 DDR5-4800 channels,
   every GB of weights read from RAM per token costs about 15–17 ms (at about 60 GB/s effective,
   assumed). A model fully in VRAM reads at the 4080's 716.8 GB/s. So the default keeps the
   generating model wholly on the GPU, and moves to the CPU only the small, compute-bound RAG
   models. On this Sapphire Rapids those get AVX-512/AMX kernels from the official image.
2. **Claude Code compatibility comes from the engine itself.**
   - llama-server implements `/v1/messages` with streaming, tools, `tool_choice`
     (auto→auto, any or tool→required), thinking budget, `output_config`, `defer_loading` and
     `/v1/messages/count_tokens`.
   - It rewrites the per-request `cch=` hash of Claude Code's attribution block so the prefix
     cache survives (source, PR #21793).
   - LiteLLM's `anthropic/` provider forwards to it, so there is a single format conversion,
     inside llama.cpp.
3. **llama-swap gives deterministic control:**
   - a persistent group keeps the RAG models up;
   - a swap group guarantees one GPU model at a time;
   - an API key, a UI with logs, GPU/system metrics, `ttl` and preload hooks.

   llama.cpp's built-in router mode is the single-process alternative (§3.6). It can only unload
   in least-recently-used order and cannot pin models.
4. **LiteLLM is the only mature self-hosted gateway found** that offers OpenAI and Anthropic
   formats, virtual keys, budgets, rate limits, Postgres spend logs and Prometheus in one open
   container. Its 2026 supply-chain history argues for:
   - pinning a version plus digest;
   - giving it no cloud credentials at all;
   - keeping llama-swap's own `/v1/messages` as a fallback endpoint.

   Bifrost (Apache-2.0, Go) is the alternative to evaluate (vendor claims, not verified).

### Profiles and VRAM budgets (RTX 4080 16 GB; GiB = 2^30 bytes)

The card reports about 16,376 MiB (assumed; check `nvidia-smi`). TrueNAS is headless. Each
llama-server process that touches the GPU carries a CUDA context of about 0.3 GiB (assumed).
Budget numbers are estimates; §5.3 shows how to measure them.

**Profile A, default ("agent 64k, RAG on CPU"):**

| Process | Settings | VRAM (est.) | Host RAM (est.) |
|---|---|---|---|
| `coder`: gpt-oss-20b MXFP4 (12.11 GB = 11.28 GiB) | `-c 65536 -np 1 -ngl 99` (f16 KV) | ≈13.6 (see below) | ≈7 (`--cache-ram 6144` plus buffers) |
| `embed`: Qwen3-Embedding-0.6B Q8_0 (0.64 GB) | `--device none --embedding --pooling last -c 4096 -ub 4096 -t 4 -tb 8` | 0 | ≈1.3 |
| `rerank`: Qwen3-Reranker-0.6B Q8_0 (0.64 GB) | `--device none --reranking -c 4096 -ub 4096 -t 4 -tb 8` | 0 | ≈1.3 |
| Headroom | | ≈2.0 | |

How the `coder` figure of about 13.6 GiB breaks down:

- 11.28 GiB weights.
- 1.5 GiB KV cache at f16. gpt-oss-20b has 24 layers; only its 12 full-attention layers grow
  with context (8 KV heads, head dimension 64), which is 24 KiB per token. The other 12 layers
  use a 128-token sliding window.
- About 0.5 GiB compute buffer and 0.3 GiB CUDA context.

The 2 GiB of headroom is enough to keep `rerank` on the GPU instead (about 1.3 GiB) if reranking
on the CPU proves too slow (§5.2).

Same profile, other primary models from agent A's shortlist:

| Primary candidate | File | VRAM at stated context | Fits profile A? |
|---|---|---|---|
| Dense 14B, Q4_K_M (e.g. Qwen3-14B 9.0 GB; needs a 64k-capable model or YaRN) | 8.4 GiB | 64k q8_0 KV 5.3 → ≈14.6 | yes |
| Dense 24B, IQ4_XS (Devstral-Small-2, 12.78 GB) | 11.9 GiB | 16k q8_0 1.3 → ≈14.1; 24k → ≈14.8 | yes, at ≤24k (too short for Claude Code) |
| 30B-A3B, UD-IQ3_XXS (Qwen3-Coder, 12.85 GB) | 12.0 GiB | 24k q8_0 1.2 → ≈14.1 | yes, at ≤24k; IQ3 costs quality |
| 35B-A3B hybrid, UD-IQ3_XXS (Qwen3.6, 13.21 GB) | 12.3 GiB | hybrid layers keep less KV (assumed) → ≈14.5 at 24–32k | probably; measure |

**Profile B, "RAG on GPU"** (for RAG-heavy chat in Open WebUI rather than Claude Code):

- Embed and rerank on the GPU: about 2.8 GiB together (about 1.4 each: 0.6 weights, 0.44 KV at
  4k, compute, context).
- Primary: dense 14B Q4_K_M at **32k** with q8_0 KV (2.66 GiB): about 12.0 GiB.
- Total about 15.6 GiB, which is tight. At 32k, Claude Code compacts constantly.

**Profile C, optional "MoE CPU offload"** (quality over speed; for example Qwen3-Coder-30B-A3B
UD-Q4_K_XL, 17.67 GB):

- `coder-moe` with `-c 65536 -ctk q8_0 -ctv q8_0 -ub 2048` (KV 3.2 GiB). With the RAG models on
  the CPU, about 14.8 GiB is left for it.
- Fixed costs: 1.1 GiB non-expert weights, 1.2 GiB compute buffer, 0.3 GiB CUDA context.
- That leaves about 9 GiB of experts on the GPU, about 28 of 48 layers, so **`--n-cpu-moe ≈ 20`**.
- Host RAM for the CPU experts: about 20 × 0.343 GB ≈ 6.9 GB ≈ 6.4 GiB, loaded with `-lm none`.
- With the RAG models on the GPU instead, `--n-cpu-moe ≈ 30` (about 9.6 GiB in RAM).
- **Expected decode: about 30–50 t/s** (assumed):
  - each token reads about 21 MB of active experts per CPU layer, so 20 layers is about 0.43 GB,
    which takes about 7 ms at about 60 GB/s effective;
  - the GPU part and per-layer synchronisation come on top;
  - Ollama measured 57 t/s on a 4080 with dual-channel DDR5-6000 (§5).
- **Prompt processing: about 1.5–2.5k t/s.** `--op-offload` (the default) uploads CPU experts
  over PCIe 4.0 x16 for each batch; use a large `-ub`.

**On a 64 GB host:** 120B-class MoEs (gpt-oss-120b MXFP4, 63.4 GB) do not fit in RAM and are out.

### System RAM budget (62.3 GiB usable; ARC cap 12 GiB per agent E)

| Consumer | Profile A | Profile C | Note |
|---|---|---|---|
| TrueNAS OS, middleware, Docker | ≈4 | ≈4 | assumed |
| ZFS ARC (`zfs_arc_max` = 12884901888) | 12 | 12 | agent E (System > Advanced Settings > Sysctl, type ZFS) |
| llama-swap: prompt cache (`--cache-ram 6144`) and host buffers | ≈8 | ≈8 | |
| llama-swap: CPU-resident RAG models | ≈2.6 | ≈2.6 | 0.6B Q8_0 each plus KV and compute |
| llama-swap: CPU-resident MoE experts | 0 | ≈6.4–9.6 | `-lm none` (pinned host buffer, assumed) |
| LiteLLM and Postgres | ≈2 | ≈2 | assumed |
| Web, RAG and ops apps | ≈8 | ≈8 | agent D/E estimate |
| Free (page cache for fast model reloads, spikes) | ≈26 | ≈17–20 | |

- Cap the llama-swap container at `deploy.resources.limits.memory: 32G`, so a runaway process is
  killed inside its cgroup (agent E's pattern).
- Set `primarycache=metadata` on `tank/ai/models` (agent E, shell only), so the ARC never holds
  GGUF data.
- Profile A loads the GPU model with the default mmap. Its pages then stay in the Linux page cache
  after a swap, so switching back is fast (assumed).
- Profile C loads with `-lm none`, so its RAM-resident experts are not file-backed pages that the
  kernel can evict.

### What the guide should install

1. **Datasets** (agent E): `tank/ai/models` (Generic preset, 1M record size, LZ4, atime off,
   `primarycache=metadata`) with GGUF files under `gguf/`, and
   `tank/ai/appdata/litellm-db` (Apps preset).
2. **The compose project `stack/inference/compose.yaml`**, installed as the TrueNAS custom app
   `ai-inference`. Its wrapper `include:`s that file with
   `env_file: /mnt/tank/stacks/secrets/inference.env`. Its files:
   - `stack/inference/llama-swap/config.yaml`
   - `stack/inference/litellm/config.yaml`
3. **One LiteLLM virtual key per client.** Clients: c4dev Claude Code, Mac, Windows, Open WebUI,
   RAG ingester. Each key gets a `models` allowlist, `rpm_limit`, `max_parallel_requests` and a
   notional GPU-time budget (§3.5).
4. **Client configuration:** Claude Code's `~/.claude/settings.json` env block on each client
   (§4.3).
5. **One benchmark pass on the box** (§5.3), to confirm context and `-ub`, the RAG models' speed
   on the CPU and, if profile C is used, the `--n-cpu-moe` and `-t` values.

## Options compared

| Option | What it is | Fit for this box (16 GB Ada, 64 GB at 2 channels, 16C SPR, driver 580 = CUDA ≤13.0) | Maturity (Nov 2026) | Licence | Verdict |
|---|---|---|---|---|---|
| **llama.cpp `llama-server`** (`ghcr.io/ggml-org/llama.cpp:server-cuda-b12407`) | C/C++ GGUF engine: OpenAI, Anthropic and Responses APIs, embeddings, rerank, router mode | Best: runs GPU-only, CPU-only (RAG on AMX) or hybrid (MoE experts); CUDA 12.8 image works; `server-cuda13` (13.5) does not | Very active; build b12418 published 2026-11-15; images nightly | MIT | **Recommended engine** |
| **llama-swap** (`ghcr.io/mostlygeek/llama-swap:v273-cuda-b12407`; or `unified-cuda-273`, CUDA 12.9) | Go proxy: starts and stops llama-server per requested model; group, matrix and capacity routing | Excellent: pins the RAG models, swaps GPU models, API key, UI, metrics | v273 on 2026-11-15; frequent releases | MIT | **Recommended model manager** |
| llama.cpp router mode (built in) | `llama-server --models-preset`, LRU unload with memory margin | Good; no pinning | New in 2026 | MIT | Alternative |
| **LiteLLM proxy** (`ghcr.io/berriai/litellm:v1.108.8`) | Python gateway: OpenAI and Anthropic formats, virtual keys, budgets, logs, Prometheus | Good (CPU only; non-CUDA base image) | Very active; 1.108.x is the LTS line; **2 supply-chain incidents in 2026** | MIT core (assumed) | **Recommended gateway, pinned by digest** |
| Ollama (`ollama/ollama:0.40.16`) | Go wrapper on a llama.cpp-derived engine; bundles CUDA 12 and 13.0 runners | OK for models that fit fully; whole-layer split only; default 4k context under 24 GiB | Very active | MIT | Fallback |
| vLLM (`vllm/vllm-openai:v0.33.0`, image requires CUDA ≥13.0) | PyTorch engine: paged attention, prefix cache, OpenAI, Responses and Anthropic APIs | Poor: one model per process, preallocated VRAM; GGUF experimental; AWQ/GPTQ/FP8 fine for ≤14B | Very active | Apache-2.0 | Not for this box |
| SGLang (`lmsysorg/sglang:v0.5.23`) | Engine with RadixAttention; Anthropic endpoint on by default | Poor on 16 GB (same reasons); check the image's CUDA requirement first | Active | Apache-2.0 | Not for this box |
| TabbyAPI + ExLlamaV3 (`ghcr.io/theroyallab/tabbyapi:latest`, CUDA 12.8) | FastAPI server for EXL3 quants | Fast for dense models in VRAM; no Anthropic or rerank endpoints; `cu13` tag not checked | Rolling ("not for production") | AGPL-3.0 | Not recommended |
| LM Studio headless (`llmster` / `lms`) | Proprietary app with a headless daemon; OpenAI and Anthropic endpoints | No official container | Mature | Proprietary | Not for TrueNAS apps |
| LocalAI (`localai/localai:v4.12.1-gpu-nvidia-cuda-12`) | All-in-one wrapper (80+ backends), OpenAI, Anthropic and ElevenLabs formats, rerank | Works, but redundant on top of llama.cpp | Active | MIT (assumed) | Not recommended |
| Bifrost (`maximhq/bifrost`) | Go gateway; Anthropic API at `/anthropic`, virtual keys and budgets | Plausible LiteLLM replacement; not tested | Active | Apache-2.0 | Candidate |

## Details

### 1. API and feature matrix per server (question 1)

Notes on the symbols used below:

- **Y** means verified in docs or source; **y** means assumed; **N** means not supported or not
  documented. Cells say which.
- "Anthropic `/v1/messages`" is native support in the server itself, without LiteLLM.
- The SGLang column covers only its own server.
- For Ollama, tool calls with streaming are documented as supported; parallel tool calls depend
  on the model (y).
- For Ollama, prompt prefix reuse in the runner is assumed (y); Anthropic `cache_control` is not
  supported.
- For vLLM, the docs show `--enable-prefix-caching` and APC.

**Endpoints and APIs**

| Feature | llama-server b12407 | Ollama 0.40.16 | vLLM 0.33 | SGLang 0.5.23 | TabbyAPI | LM Studio | LocalAI 4.12 |
|---|---|---|---|---|---|---|---|
| OpenAI chat completions + streaming | Y | Y | Y | Y | Y | Y | Y |
| Tool calls (streaming) | Y (`--jinja`, on by default) | Y | Y (`--enable-auto-tool-choice --tool-call-parser`) | Y | Y | Y | Y |
| Parallel tool calls | Y; default comes from the template's capability (source) | y | Y | y | y | y | y |
| `tool_choice` | Y (auto/any/tool → auto/required) | **N** | Y | y | y | y | y |
| JSON schema / grammar output | Y (`response_format` json_schema, GBNF, `-j`) | Y | Y (`structured_outputs`) | y | Y | Y | y |
| Embeddings | Y (`--embedding`) | Y | Y | y | Y (extras image) | y | Y |
| Rerank | Y (`/v1/rerank`, `--reranking`) | N | Y (`/rerank`) | y | N | N | Y |
| OpenAI Responses `/v1/responses` | Y (converted to chat) | Y | Y | y | N | y | y |
| **Anthropic `/v1/messages`** | **Y** | **Y** (since v0.14; no `tool_choice`, `count_tokens`, `cache_control`, PDF) | **Y** (no server tools; no `max_tokens: 0`) | **Y** | N | **Y** | **Y** |
| `/v1/messages/count_tokens` | Y | N | y | Y | N | y | y |

**Formats, memory and speed features**

| Feature | llama-server b12407 | Ollama 0.40.16 | vLLM 0.33 | SGLang 0.5.23 | TabbyAPI | LM Studio | LocalAI 4.12 |
|---|---|---|---|---|---|---|---|
| Weight formats | GGUF (all K/IQ/MXFP4 types) | GGUF, safetensors import | AWQ, GPTQ, FP8 (W8A8 on Ada), INT8, bnb; GGUF experimental (plugin) | AWQ, GPTQ, FP8 (y) | EXL3, FP16/BF16 | GGUF, MLX | Per backend |
| KV cache quantisation | Y: f16, bf16, f8_e4m3, q8_0, q4_0, q4_1, iq4_nl, q5_0, q5_1 | Y: f16, q8_0, q4_0 (global) | Y: fp8, fp8_e4m3, fp8_e5m2 | y | Y: FP16, Q8, Q6, Q4 | y | per backend |
| Flash attention | Y (`-fa on\|off\|auto`) | Y (automatic) | Y | Y | Y | y | per backend |
| Speculative decoding | Y: draft model, `draft-eagle3`, `draft-mtp`, n-gram (`--spec-type`) | N | Y: draft, EAGLE, MTP, n-gram, suffix | Y: EAGLE | Y: draft | y | y |
| Prompt and prefix reuse | Y: slot prefix reuse, `--cache-reuse`, `--cache-ram` (host RAM), slot save and restore, context checkpoints (SWA and hybrid), Claude Code `cch` normalisation | y; `cache_control` N | Y: APC | Y: RadixAttention | y | y | per backend |
| Several models on one GPU | Y: router mode or llama-swap groups | Y: `OLLAMA_MAX_LOADED_MODELS` (default 3 × GPUs), only if each fits fully; `keep_alive` | One per process; sleep mode | One per process | Main + draft + embeddings | JIT loading | Y |
| CPU-only models in the same server image | Y (`--device none`, CPU variant per runtime) | Y (falls back to CPU) | N (practical) | N | N | y | Y |
| MoE expert offload to CPU | **Y**: `--cpu-moe`, `--n-cpu-moe`, `-ot`, `--moe-cache-mib` | Whole layers only | `--cpu-offload-gb` (UNVERIFIED in 0.33) | N | y | y | via llama.cpp |
| Prometheus metrics | Y (`--metrics`) | N | Y (`/metrics`) | y | Y (`enable_metrics`) | N | y |
| Image CUDA requirement (from the image config) | `server-cuda`: cuda>=12.8 ✓; `server-cuda13`: cuda>=13.5 ✗ | carries its own runners ✓ | v0.33.0 and v0.32.0: cuda>=13.0 ✓ | not checked | `latest`: cuda>=12.8 ✓ | n/a | cuda-12 tag ✓ (assumed) |

llama.cpp source details (2026-11-15):

- `server_chat_convert_anthropic_to_oai` maps:
  - `tool_choice` `auto` to `auto`, and `any` or `tool` to `required`;
  - `stop_sequences` to `stop`, with `max_tokens` defaulting to 4096;
  - `thinking.budget_tokens` to `thinking_budget_tokens`, and passes `defer_loading` on tools.
- `parallel_tool_calls` defaults to the template's `supports_parallel_tool_calls`.
- No SSE `ping` events were found in the server source.

### 2. How the models coexist (question 2)

- **One GPU model at a time** (`llm` group, `swap: true`). The primary owns about 85% of the VRAM.
- **`local-haiku` points at the same `coder` instance.** Claude Code's background calls (titles,
  summaries, WebFetch digests) go to the `haiku` alias (`ANTHROPIC_DEFAULT_HAIKU_MODEL`). A
  separate small model would force a 12 GB swap between calls.
- **`small` is for explicit callers only.** The `small` model (Qwen3-4B Q4_K_M, about 4 GiB at
  32k) exists for FIM autocomplete or UI tasks. It swaps `coder` out, so Claude Code must never
  get it. It could run on the CPU instead (`--device none`, decode about 10–20 t/s on 2 channels,
  assumed).
- **RAG models are persistent and CPU-only.** They do not compete for VRAM. For large ingestion
  jobs, temporarily move `embed` to the GPU (`-ngl 99`) while the agent is idle.
- **Slots.** `-np 1` with the full 64k per conversation. Concurrent requests (subagents,
  background calls) queue; an idle slot's prompt goes to the host-RAM prompt cache
  (`--cache-idle-slots` is on by default; `--cache-ram` is its size) instead of being recomputed.
  Alternative to benchmark: `-np 2 -kvu` (two slots share one 64k KV pool).
- **Ollama equivalent** (if chosen instead):
  - `OLLAMA_MAX_LOADED_MODELS=2`, `OLLAMA_KEEP_ALIVE=-1`, `OLLAMA_NUM_PARALLEL=1`,
    `OLLAMA_CONTEXT_LENGTH=65536`, `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_FLASH_ATTENTION=1`.
  - No pinning. CPU-only embedding is not configurable per model (assumed).

KV cache size per token (from Hugging Face `config.json`, f16; q8_0 is 0.531× that):

| Model (example) | Layers / KV heads / head dim | KiB per token f16 | 32k f16 | 64k f16 | 64k q8_0 |
|---|---|---|---|---|---|
| gpt-oss-20b | 24 / 8 / 64; 12 full-attention and 12 sliding-window (128) layers | ≈24 effective | 0.75 GiB | 1.5 GiB | 0.8 GiB |
| Qwen3-Coder-30B-A3B (MoE) | 48 / 4 / 128 | 96 | 3.0 GiB | 6.0 GiB | 3.2 GiB |
| Qwen3-14B, Devstral-Small 24B | 40 / 8 / 128 | 160 | 5.0 GiB | 10.0 GiB | 5.3 GiB |
| Qwen3-32B | 64 / 8 / 128 | 256 | 8.0 GiB | 16.0 GiB | 8.5 GiB |
| Qwen3-4B-Instruct-2507 | 36 / 8 / 128 | 144 | 4.5 GiB | 9.0 GiB | 4.8 GiB |
| Qwen3-Embedding / Reranker 0.6B | 28 / 8 / 128 | 112 | n/a | n/a | n/a |

GGUF file sizes (Hugging Face repo listings):

- gpt-oss-20b: MXFP4 12.11 GB.
- Qwen3-Coder-30B-A3B-Instruct: UD-Q4_K_XL 17.67 GB; Q4_K_M 18.56 GB; UD-Q3_K_XL 13.81 GB;
  UD-IQ3_XXS 12.85 GB.
- Qwen3.6-35B-A3B: UD-IQ3_XXS 13.21 GB; UD-Q4_K_XL 22.36 GB.
- GLM-4.7-Flash: Q4_K_M 18.31 GB.
- Qwen3-14B: Q4_K_M 9.00 GB.
- Devstral-Small-2-24B: IQ4_XS 12.78 GB; Q4_K_M 14.33 GB.
- Qwen3-4B-Instruct-2507: Q4_K_M 2.50 GB.
- Qwen3-Embedding-0.6B: Q8_0 0.64 GB.
- Qwen3-Reranker-0.6B: Q8_0 0.64 GB.

### 3. Compose and configuration (question 3)

All flags below were checked against the llama.cpp server README and `common/arg.cpp`
(master, 2026-11-15), llama-swap `docs/config.example.yaml`, and the LiteLLM docs. Image
`NVIDIA_REQUIRE_CUDA`, user and entrypoint were read from the registries' image configs.
Items not verified are marked UNVERIFIED.

#### 3.1 Images, tags and CUDA compatibility with driver 580.173.02 (CUDA ≤13.0)

| Image | Tag (exists, 2026-11-15) | CUDA / `NVIDIA_REQUIRE_CUDA` | Starts on 25.10.8 | Notes |
|---|---|---|---|---|
| ghcr.io/mostlygeek/llama-swap | **`v273-cuda-b12407`** | 12.8.1 / `cuda>=12.8` | yes | Legacy flavour = llama.cpp `server-cuda-b12407` + llama-swap v273; root; entrypoint `/app/llama-swap -config /app/config.yaml -watch-config`; image env `NVIDIA_VISIBLE_DEVICES=all`, `LLAMA_ARG_HOST=0.0.0.0`, `LLAMA_ARG_PORT=8080` |
| ghcr.io/mostlygeek/llama-swap | `unified-cuda-273` | 12.9.1 / `cuda>=12.9` | yes | Adds ik_llama-server, whisper.cpp, sd.cpp, audio.cpp; entrypoint `run.sh`; config at `/etc/llama-swap/config/config.yaml`; `LLAMA_SWAP_*` env vars |
| ghcr.io/mostlygeek/llama-swap | `unified-cuda13-273` | `cuda>=13.3` | **no** | |
| ghcr.io/ggml-org/llama.cpp | `server-cuda-b12407`, `full-cuda-b12407` | 12.8.1 / `cuda>=12.8` | yes | `full` has `--bench` (llama-bench) |
| ghcr.io/ggml-org/llama.cpp | `server-cuda13-b12407` | `cuda>=13.5` | **no** | Also needs an R620 driver |
| ghcr.io/berriai/litellm | `v1.108.8` (LTS); `v1.108.9` exists | none (Wolfi base) | yes | Runs as root; `PATH` starts with `/app/.venv/bin`; default CMD `--port 4000` |
| postgres | `16.13` | none | yes | |
| ollama/ollama | `0.40.16` | own runners | yes | |
| vllm/vllm-openai | `v0.33.0`, `v0.32.0` | `cuda>=13.0` | yes | Not recommended for this box |
| ghcr.io/theroyallab/tabbyapi | `latest` | `cuda>=12.8` | yes | Not recommended |

**CPU backends in the official CUDA image.** `.devops/cuda.Dockerfile` builds with
`-DGGML_NATIVE=OFF -DGGML_CUDA=ON -DGGML_BACKEND_DL=ON -DGGML_CPU_ALL_VARIANTS=ON`.

- `ggml/src/CMakeLists.txt` then adds a `sapphirerapids` variant (SSE4.2, AVX, F16C, FMA, AVX2,
  BMI2, AVX512, AVX512_VBMI, AVX512_VNNI, AVX512_BF16, AMX_TILE, AMX_INT8), plus `icelake`,
  `cooperlake`, `zen4`, `haswell` and others. Not `AMX_BF16`.
- With `GGML_BACKEND_DL`, the best matching variant loads at runtime. The selection mechanism is
  assumed: check the start-up log for the loaded CPU backend and `AMX_INT8 = 1`.
- AMX kernels exist for Q4_0, Q4_1, Q8_0, Q4_K, Q5_K, Q6_K and IQ4_XS weights
  (`ggml-cpu/amx/common.h`). The Q8_0 RAG models are eligible.
- **A custom build is not worth it for CPU features.** Reasons to build anyway would be a single
  `CMAKE_CUDA_ARCHITECTURES=89` build (smaller image), or the ik_llama.cpp fork, which is already
  inside the `unified-cuda-273` image.

**`--no-host`.** In a CUDA build, CPU-resident weights go into the CUDA host (pinned) buffer by
default. `--no-host` "bypass[es] host buffer allowing extra buffers to be used", meaning the AMX
and repack buffer types.

- `--device none` processes have no CUDA host buffer, so the RAG models get AMX either way
  (assumed).
- For profile C, benchmark `--no-host 0,1` and `--no-op-offload 0,1`:
  - `--no-host` may speed up the CPU expert path (assumed);
  - `--no-op-offload` makes prompt processing of the CPU experts run on AMX instead of over PCIe.

#### 3.2 Secrets: `/mnt/tank/stacks/secrets/inference.env` (outside the repo, per agent E)

```dotenv
LLAMA_SWAP_API_KEY=sk-...        # e.g. "sk-" + 48 random alphanumerics
LITELLM_MASTER_KEY=sk-...        # openssl rand -hex 32, prefixed with sk-
LITELLM_SALT_KEY=sk-...          # never change after first start (encrypts stored credentials)
POSTGRES_PASSWORD=...
```

#### 3.3 `stack/inference/compose.yaml` (included by the custom app `ai-inference`)

```yaml
# TrueNAS 25.10 custom app wrapper (agent E):
#   include:
#     - path: /mnt/tank/stacks/local-agent-stack/stack/inference/compose.yaml
#       env_file: [/mnt/tank/stacks/secrets/inference.env]
#   services: {}
# Relative paths below resolve against this file's directory.

networks:
  ai-net:
    external: true      # created once: sudo docker network create ai-net

services:
  llama-swap:
    image: ghcr.io/mostlygeek/llama-swap:v273-cuda-b12407   # CUDA 12.8.1; pin @sha256 too
    container_name: llama-swap
    restart: unless-stopped
    networks: [ai-net]
    # ENTRYPOINT already is: /app/llama-swap -config /app/config.yaml -watch-config  (listens :8080)
    # ports: ["9292:8080"]   # optional LAN access to UI/API; default: only via ai-net / Caddy
    environment:
      NVIDIA_VISIBLE_DEVICES: all
      NVIDIA_DRIVER_CAPABILITIES: compute,utility
      LLAMA_SWAP_API_KEY: ${LLAMA_SWAP_API_KEY}   # used by config.yaml as ${env.LLAMA_SWAP_API_KEY}
    volumes:
      - /mnt/tank/ai/models:/models:ro
      - ./llama-swap/config.yaml:/app/config.yaml:ro
    ulimits:
      memlock: { soft: -1, hard: -1 }   # harmless; needed only for -lm mlock
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
        limits:
          memory: 32G                   # profile C peak ≈ 20 GiB; OOM stays inside this container
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8080/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 120s

  litellm:
    image: ghcr.io/berriai/litellm:v1.108.8   # then pin: ghcr.io/berriai/litellm@sha256:<verified digest>
    container_name: litellm
    restart: unless-stopped
    networks: [ai-net]
    command: ["--config", "/app/config.yaml", "--port", "4000"]
    # ports: ["4000:4000"]    # optional; preferred path is Caddy (TLS) on ai-net
    environment:
      NVIDIA_VISIBLE_DEVICES: void
      LITELLM_MASTER_KEY: ${LITELLM_MASTER_KEY}
      LITELLM_SALT_KEY: ${LITELLM_SALT_KEY}
      DATABASE_URL: postgresql://litellm:${POSTGRES_PASSWORD}@litellm-db:5432/litellm
      STORE_MODEL_IN_DB: "False"            # models live in config.yaml (git)
      LITELLM_LOCAL_MODEL_COST_MAP: "True"  # no fetch of the cost map from GitHub
      LITELLM_TELEMETRY_DISABLED: "true"
      LLAMA_SWAP_API_KEY: ${LLAMA_SWAP_API_KEY}
    volumes:
      - ./litellm/config.yaml:/app/config.yaml:ro
    depends_on:
      litellm-db: { condition: service_healthy }
      llama-swap: { condition: service_healthy }
    healthcheck:
      # python is in /app/.venv/bin (image PATH); exact binary name UNVERIFIED
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:4000/health/liveliness', timeout=5)"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 90s

  litellm-db:
    image: postgres:16.13
    container_name: litellm-db
    restart: unless-stopped
    networks: [ai-net]       # or a private network if only litellm needs it
    environment:
      NVIDIA_VISIBLE_DEVICES: void
      POSTGRES_USER: litellm
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: litellm
    volumes:
      - /mnt/tank/ai/appdata/litellm-db:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U litellm"]
      interval: 10s
      timeout: 5s
      retries: 10
```

Notes:

- **GPU visibility.** TrueNAS 25.10 makes `nvidia` Docker's default runtime, so `runtime: nvidia`
  is not needed. Any CUDA-based image sees the GPU unless `NVIDIA_VISIBLE_DEVICES=void` (agent E).
  LiteLLM and Postgres are not CUDA-based; `void` is set anyway.
- **Inherited environment.** llama-swap's children inherit `LLAMA_ARG_HOST=0.0.0.0` and
  `LLAMA_ARG_PORT=8080` from the image. Every `cmd` therefore passes
  `--host 127.0.0.1 --port ${PORT}`; the command line beats the environment.
- **Default port.** llama-server's own default port is now **9931** (`common.h`), so always pass
  `--port`.
- **Name resolution.** Other apps reach `litellm:4000` (and admins `llama-swap:8080`) by name on
  `ai-net`. A private network between `litellm` and `litellm-db` is optional hardening.

#### 3.4 `stack/inference/llama-swap/config.yaml`

```yaml
# llama-swap v273 (keys per docs/config.example.yaml)
healthCheckTimeout: 600
logLevel: info
startPort: 10001
sendLoadingState: false        # don't inject "loading" text into reasoning fields
globalTTL: 0                   # never auto-unload

apiKeys:
  - "${env.LLAMA_SWAP_API_KEY}"  # Bearer or x-api-key (PR #436, assumed)

macros:
  "srv": >-
    /app/llama-server --host 127.0.0.1 --port ${PORT}
    --jinja --metrics --no-webui
  "gguf": "/models/gguf"

models:
  # ---- Profile A default: GPU-resident primary at 64k (example: gpt-oss-20b) ----
  coder:
    name: "Primary (GPU-resident, 64k)"
    cmd: |
      ${srv}
      -m ${gguf}/gpt-oss-20b-MXFP4.gguf
      -fa on -ngl 99
      -c 65536 -np 1
      -b 2048 -ub 1024
      -t 4
      --cache-ram 6144 --cache-reuse 256
    ttl: 0

  # ---- Profile C (optional): MoE with experts partly in RAM; slower on 2 DDR5 channels ----
  coder-moe:
    name: "MoE coder (experts in RAM, 64k)"
    cmd: |
      ${srv}
      -m ${gguf}/Qwen3-Coder-30B-A3B-Instruct-UD-Q4_K_XL.gguf
      -fa on -ngl 99 --n-cpu-moe 20
      -c 65536 -np 1
      -ctk q8_0 -ctv q8_0
      -b 2048 -ub 2048
      -t 8 -tb 16
      -lm none
      --cache-ram 6144 --cache-reuse 256
    ttl: 0

  # ---- Small model for explicit callers only (swaps out the primary) ----
  small:
    name: "Small 4B"
    cmd: |
      ${srv}
      -m ${gguf}/Qwen3-4B-Instruct-2507-Q4_K_M.gguf
      -fa on -ngl 99
      -c 32768 -np 2 -ctk q8_0 -ctv q8_0
      -t 4
    ttl: 600

  # ---- RAG models: CPU-only (AVX-512/AMX), zero VRAM ----
  embed:
    name: "Embeddings (CPU)"
    env:
      - "CUDA_VISIBLE_DEVICES=-1"     # assumed: avoid creating a CUDA context at all
    cmd: |
      ${srv}
      -m ${gguf}/Qwen3-Embedding-0.6B-Q8_0.gguf
      --device none
      --embedding --pooling last
      -c 4096 -b 4096 -ub 4096 -np 1
      -t 4 -tb 8
    ttl: 0
  rerank:
    name: "Reranker (CPU)"
    env:
      - "CUDA_VISIBLE_DEVICES=-1"
    cmd: |
      ${srv}
      -m ${gguf}/qwen3-reranker-0.6b-q8_0.gguf
      --device none
      --reranking
      -c 4096 -b 4096 -ub 4096 -np 1
      -t 4 -tb 8
    ttl: 0

routing:
  router:
    use: group
    settings:
      groups:
        rag:
          persistent: true     # other groups can never unload these
          swap: false
          exclusive: false
          members: [embed, rerank]
        llm:
          swap: true           # one GPU model at a time
          exclusive: false
          members: [coder, coder-moe, small]

hooks:
  on_startup:
    preload: [embed, rerank, coder]
```

How to adjust it:

- **Profile B (RAG on GPU).** In `embed` and `rerank`, replace `--device none` with `-ngl 99`,
  drop the `env` entries, and change `coder` to a 14B-class model at `-c 32768 -ctk q8_0 -ctv
  q8_0`.
- **gpt-oss-20b.**
  - Its KV cache stays f16 here; it is small, and quantising a sliding-window and attention-sink
    model's cache is UNVERIFIED for quality.
  - Prefix reuse for sliding-window models relies on context checkpoints (`--ctx-checkpoints`,
    default 32; `-cms`). Check `cache_n` across turns (§5.3).
  - Agent A to set the model's recommended sampling parameters and reasoning effort
    (`--chat-template-kwargs`).
- **`coder-moe` tuning.**
  - `--n-cpu-moe 20` is the start value with the RAG models on the CPU; use 30 if they are on the
    GPU.
  - If the load runs out of memory, add 2; if `nvidia-smi` shows more than 1 GiB free, subtract 2.
  - Alternatively leave it unset: `--fit` is on by default and "adjust[s] unset arguments to fit
    in device memory", keeping `--fit-target` (default 1024 MiB) free. Pin what the log reports.
- **Threads with 2 memory channels.**
  - Decode on CPU-resident weights is bandwidth-bound and saturates early. Arm's roofline guide
    says threads beyond memory saturation do not help and often slow decode; one community report
    saw saturation at about 6 threads.
  - Hence `-t 8` for `coder-moe`, to be swept as 4, 6, 8, 12 and 16.
  - `-tb 16` (the physical cores) only matters for CPU-side prompt processing: the RAG models,
    and `--no-op-offload`.
  - The GPU-only `coder` needs few CPU threads (`-t 4`).
  - Leave the 16 SMT siblings to the other apps.
  - NUMA: if `lscpu` shows more than one node (sub-NUMA clustering), add `--numa distribute`.
    Assumed: one node on W790.
- **Speculative decoding.**
  - gpt-oss-20b has an EAGLE-3 draft published by ggml-org (`eagle3-gpt-oss-20b-Q8_0.gguf`,
    0.92 GB). Usable with `--spec-type draft-eagle3 -md <file>`; the combination is UNVERIFIED.
    Benchmark it, and check it fits in the 2 GiB headroom.
  - For dense models, `--spec-type ngram-mod` costs no VRAM.

#### 3.5 `stack/inference/litellm/config.yaml`

```yaml
model_list:
  # --- Anthropic Messages path (Claude Code). The anthropic provider appends /v1/messages to
  #     api_base, so requests reach llama-swap's /v1/messages unchanged (no translation here).
  - model_name: local-opus
    litellm_params: { model: anthropic/coder, api_base: http://llama-swap:8080, api_key: os.environ/LLAMA_SWAP_API_KEY }
    model_info: { max_input_tokens: 65536, cost_per_second: 0.0001 }   # notional GPU-second price
  - model_name: local-sonnet
    litellm_params: { model: anthropic/coder, api_base: http://llama-swap:8080, api_key: os.environ/LLAMA_SWAP_API_KEY }
    model_info: { max_input_tokens: 65536, cost_per_second: 0.0001 }
  - model_name: local-haiku       # same instance on purpose: no swap for background calls
    litellm_params: { model: anthropic/coder, api_base: http://llama-swap:8080, api_key: os.environ/LLAMA_SWAP_API_KEY }
    model_info: { max_input_tokens: 65536, cost_per_second: 0.0001 }

  # --- OpenAI path (Open WebUI, other harnesses, RAG pipeline)
  - model_name: coder
    litellm_params: { model: openai/coder, api_base: http://llama-swap:8080/v1, api_key: os.environ/LLAMA_SWAP_API_KEY }
    model_info: { max_input_tokens: 65536, cost_per_second: 0.0001 }
  - model_name: coder-moe
    litellm_params: { model: openai/coder-moe, api_base: http://llama-swap:8080/v1, api_key: os.environ/LLAMA_SWAP_API_KEY }
    model_info: { max_input_tokens: 65536, cost_per_second: 0.0001 }
  - model_name: small
    litellm_params: { model: openai/small, api_base: http://llama-swap:8080/v1, api_key: os.environ/LLAMA_SWAP_API_KEY }
  - model_name: embed
    litellm_params: { model: openai/embed, api_base: http://llama-swap:8080/v1, api_key: os.environ/LLAMA_SWAP_API_KEY }
  - model_name: rerank            # Cohere/Jina-style; llama-swap serves /rerank and /v1/rerank
    litellm_params: { model: hosted_vllm/rerank, api_base: http://llama-swap:8080, api_key: os.environ/LLAMA_SWAP_API_KEY }

litellm_settings:
  callbacks: ["prometheus"]   # /metrics on :4000
  drop_params: true
  request_timeout: 900

router_settings:
  num_retries: 0
  timeout: 900

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  store_model_in_db: false
  store_prompts_in_spend_logs: false   # metadata only by default
```

Create keys after the first start (fields from LiteLLM's virtual-key and budget docs), from any
container on `ai-net` or through Caddy:

```bash
curl -s http://litellm:4000/key/generate \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H "Content-Type: application/json" \
  -d '{"models":["local-opus","local-sonnet","local-haiku"],
       "max_budget": 50, "budget_duration": "30d",
       "rpm_limit": 120, "max_parallel_requests": 2,
       "metadata": {"client": "c4dev-claude-code"}}'
```

At `cost_per_second: 0.0001`, `max_budget: 50` means 500,000 GPU-seconds per 30 days. Dollar
budgets are meaningless locally; this turns them into a GPU-time quota. Use `rpm_limit` and
`max_parallel_requests` to protect interactive use from batch jobs.

#### 3.6 Alternative: llama.cpp router mode instead of llama-swap

The preset file below defines the models (keys are long flag names without dashes; short forms
are allowed):

```ini
; /models/presets.ini
version = 1
[*]
jinja = true
flash-attn = on
metrics = true
[coder]
model = /models/gguf/gpt-oss-20b-MXFP4.gguf
load-on-startup = true
c = 65536
[embed]
model = /models/gguf/Qwen3-Embedding-0.6B-Q8_0.gguf
load-on-startup = true
device = none
embedding = true
pooling = last
c = 4096
```

Start it with:

```bash
llama-server --models-preset /models/presets.ini --models-max 3 --models-memory-margin 1024 \
  --host 0.0.0.0 --port 8080
```

Requests are routed by their `model` field. Limitations against llama-swap:

- no pinning: idle models are unloaded least-recently-used first;
- `/metrics` needs `?model=`;
- no per-model environment variables. The `device = none` key is assumed to map to the flag.

#### 3.7 Alternative: Ollama only (simplest; loses `tool_choice`, `count_tokens`, rerank, expert offload)

```yaml
  ollama:
    image: ollama/ollama:0.40.16
    restart: unless-stopped
    networks: [ai-net]
    environment:
      NVIDIA_VISIBLE_DEVICES: all
      NVIDIA_DRIVER_CAPABILITIES: compute,utility
      OLLAMA_HOST: "0.0.0.0:11434"
      OLLAMA_CONTEXT_LENGTH: "65536"   # default is 4k on <24 GiB VRAM
      OLLAMA_FLASH_ATTENTION: "1"
      OLLAMA_KV_CACHE_TYPE: q8_0
      OLLAMA_MAX_LOADED_MODELS: "2"
      OLLAMA_NUM_PARALLEL: "1"
      OLLAMA_KEEP_ALIVE: "-1"
      OLLAMA_NO_CLOUD: "1"
    volumes: ["/mnt/tank/ai/appdata/ollama:/root/.ollama"]
    deploy: { resources: { reservations: { devices: [ { driver: nvidia, count: all, capabilities: [gpu] } ] } } }
    healthcheck: { test: ["CMD", "ollama", "list"], interval: 30s, timeout: 10s, retries: 3 }
```

### 4. Gateway design and Claude Code (question 4)

#### 4.1 One endpoint, both API styles

- **One base URL, both APIs.** LiteLLM serves `/v1/chat/completions`, `/v1/responses`,
  `/v1/embeddings`, `/rerank` (OpenAI and Cohere style) and `/v1/messages` (Anthropic style).
  - Clients on the LAN reach it through Caddy, e.g. `https://<caddy-host>/` routed to
    `litellm:4000` (agent E), or via the optional port 4000.
  - Apps on `ai-net` use `http://litellm:4000`.
- **Virtual names.** `local-opus`, `local-sonnet` and `local-haiku` serve Anthropic-format
  clients; `coder`, `coder-moe`, `small`, `embed` and `rerank` serve OpenAI-format ones. Swap the
  GGUF behind `coder` and no client changes.
- **Keys.** The master key is for admins only. Each client gets a virtual key with a model
  allowlist, budget, `rpm_limit` and `max_parallel_requests`. llama-swap has its own key, known
  only to LiteLLM and admins.
- **Logging:**
  - LiteLLM spend logs (per key, model, tokens, duration) in Postgres, plus the Admin UI at `/ui`.
    Prompts are stored only if `store_prompts_in_spend_logs` is enabled.
  - Prometheus targets: `litellm:4000/metrics`, `llama-swap:8080/metrics` (system and GPU), and
    per model `llama-swap:8080/upstream/<id>/metrics`. That path is assumed from the
    `/upstream/:model_id` route.
- **Local only.** `LITELLM_LOCAL_MODEL_COST_MAP=True`, `LITELLM_TELEMETRY_DISABLED=true`, and no
  provider keys anywhere.
- **Fallback.** Point `ANTHROPIC_BASE_URL` at llama-swap directly (model `coder`,
  `LLAMA_SWAP_API_KEY`). llama-swap serves `/v1/messages` and `/v1/messages/count_tokens`
  itself. This loses per-key budgets and spend logs.
- **Discovery.** Claude Code's optional `/v1/models` discovery only lists IDs that contain
  "claude" or "anthropic", so set the models with environment variables instead.

#### 4.2 Claude Code variables (verified at code.claude.com, 2026-11-15)

| Variable | Use here |
|---|---|
| `ANTHROPIC_BASE_URL` | The gateway URL. Non-Anthropic hosts disable Remote Control (v2.1.196+). With Caddy's internal CA the client must trust the root (`NODE_EXTRA_CA_CERTS`, assumed; agents C and E). |
| `ANTHROPIC_AUTH_TOKEN` | LiteLLM virtual key, sent as `Authorization: Bearer`. |
| `ANTHROPIC_API_KEY` | Set to an empty string, so a stale Anthropic key is not used. |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` / `_SONNET_MODEL` / `_HAIKU_MODEL` | `local-opus` / `local-sonnet` / `local-haiku`. Haiku is also used for background functionality. |
| `ANTHROPIC_MODEL` (or `ANTHROPIC_DEFAULT_MODEL`, v2.1.236+) | `local-sonnet` |
| `ANTHROPIC_SMALL_FAST_MODEL` | **Deprecated**; use `ANTHROPIC_DEFAULT_HAIKU_MODEL`. |
| `CLAUDE_CODE_SUBAGENT_MODEL` | `local-sonnet` (no swaps for subagents). |
| `CLAUDE_CODE_MAX_CONTEXT_TOKENS` | `65536`. Without it an unknown ID is assumed to have a **1M** window. Applies on its own for IDs that do not start with `claude-` and have no `[1m]`. |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | Accepts 100k–1M only, so do not use it for 64k models. LiteLLM's tutorial suggests it, but that is wrong for small windows. |
| `CLAUDE_CODE_MAX_OUTPUT_TOKENS` | `16384`. The default for unknown IDs is 32000, half of a 64k window. |
| `CLAUDE_CODE_ATTRIBUTION_HEADER` | `0`. Gives an identical system-prompt prefix across conversations and subagents; SGLang's doc calls it "required"; llama.cpp also neutralises the hash. |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` | `1` |
| `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS` | Leave unset first. Set to `1` if the gateway rejects requests with "Extra inputs are not permitted". It also disables MCP tool search, which costs context. |
| `skipWebFetchPreflight` (settings key) | `true`. The WebFetch domain check otherwise calls `api.anthropic.com` regardless of provider. |
| `CLAUDE_STREAM_IDLE_TIMEOUT_MS` / `API_TIMEOUT_MS` | Defaults are 300 s with no bytes and 600 s for headers; enough here. llama-server sends no SSE pings. |

#### 4.3 Example client configuration (c4dev, user scope)

`~/.claude/settings.json`:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://<caddy-host-for-litellm>",
    "ANTHROPIC_API_KEY": "",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "local-opus",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "local-sonnet",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "local-haiku",
    "ANTHROPIC_MODEL": "local-sonnet",
    "CLAUDE_CODE_SUBAGENT_MODEL": "local-sonnet",
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "65536",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "16384",
    "CLAUDE_CODE_ATTRIBUTION_HEADER": "0",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "DISABLE_TELEMETRY": "1"
  },
  "skipWebFetchPreflight": true
}
```

Put `ANTHROPIC_AUTH_TOKEN` in the shell environment or an `apiKeyHelper`, not in a file kept in
Git. Without Caddy, use `http://192.0.2.10:4000` after publishing port 4000.

#### 4.4 Known limitations of Claude Code on non-Anthropic models

1. **Unsupported by Anthropic.** "Anthropic … doesn't support routing Claude Code to non-Claude
   models through any gateway". New releases may add fields a gateway rejects, so pin the Claude
   Code version (agent C) and retest after upgrades.
2. **Context.** 64k against 200k–1M. The system prompt plus tool definitions take a large share
   (assumed 15–25k tokens; check with `/context`), and MCP tools add more. Expect frequent
   compaction.
3. **WebSearch.** It is an Anthropic server tool (vLLM returns HTTP 400; unavailable on
   non-Anthropic providers). Replace it with an MCP search server on SearXNG (agent D). WebFetch
   works, but its summaries go to the `haiku` model.
4. **Tool-use quality.** Tool-use quality depends on the model and its template: malformed
   arguments and loops are more common than with Claude (assumed). Ollama ignores `tool_choice`.
5. **Thinking and effort.** These map approximately (llama.cpp reasoning budget; Ollama accepts
   `budget_tokens` without enforcing it). There is no adaptive reasoning.
6. **Prompt caching.** `cache_control` has no effect; the engine's prefix cache does the work.
7. **Images and PDFs.** Images need a vision model plus `mmproj`. PDF `document` blocks are
   unsupported on Ollama and UNVERIFIED on llama.cpp.
8. **Claude-only features.** Remote Control, fast mode and Advisor are unavailable; `/cost`
   figures are meaningless (use LiteLLM spend logs).
9. **Reported issues.** One public issue reports Claude Code 2.1.114 hanging against Ollama 0.21
   (#51239); not reproduced here.

### 5. Performance on Ada 16 GB (question 5)

#### 5.1 Measured numbers (others' hardware; dates in Sources)

| Model | Quant | GPU / setup | Prefill t/s | Decode t/s | Source |
|---|---|---|---|---|---|
| Llama-2-7B | Q4_0 (3.6 GiB) | RTX 4080, llama.cpp, FA on | 9,206 (pp512) | 143.5 | [24] |
| gpt-oss-20b | MXFP4 (12.1 GB) | RTX 4080 SUPER, llama.cpp b6316, `-ub 2048` | 8,171 (pp2048), 7,989 (pp8192), 7,518 (pp16384), 6,740 (pp32768) | 186.5 | [25] |
| gpt-oss-20b | MXFP4 | RTX 4080, Ollama 0.17.7, 19k ctx | n/a | 139.9 | [27] |
| Qwen3-14B | Q4_K_M (9.0 GB) | RTX 4080, Ollama, 100% GPU | n/a | 61.9 | [27] |
| Ministral-3 14B | Q4_K_M | RTX 4080, Ollama, 100% GPU | n/a | 70.1 | [27] |
| Qwen3-Coder-30B-A3B | Q4_K_M | RTX 4080 + dual-channel DDR5-6000, Ollama, 25% CPU / 75% GPU | n/a | 57.2 | [27] |
| Qwen3-30B-A3B | Q3_K_M (13.7 GiB) | RTX 5070 12 GB, llama-bench `--n-cpu-moe 12` | 1,254 (pp512) | 54.0 | [26] |
| Qwen3-30B-A3B | Q4_K_M | T4 16 GB, 4 vCPU VM, `--cpu-moe --moe-cache-mib 10000` vs plain `--cpu-moe` | 382 vs 150 | 43.2 vs 9.6 | [28] |
| Devstral-Small-2 24B (dense) | Q4_K_M | RTX 4080, Ollama, 18% CPU | n/a | 18.7 | [27] |
| Qwen3.5 27B (dense) | Q4_K_M | RTX 4080, Ollama, 43% CPU | n/a | 6.5 | [27] |

#### 5.2 Expectations for this box (estimates; assumed)

- **Profile A (gpt-oss-20b, fully on the GPU):**
  - decode about 140–185 t/s at short context, lower at 32–64k depth;
  - prefill about 8k t/s at 2k, falling to about 6.7k t/s at 32k;
  - a cold 25k-token Claude Code first request takes about 3–4 s; later turns only process new
    tokens.
  - These do not depend on the RAM configuration.
- **Dense 14B Q4 fully on the GPU:** decode about 60 t/s, prefill about 4k t/s.
- **Dense 24B IQ4_XS fully on the GPU:** decode about 40 t/s, prefill about 2.5k t/s (the 4080's
  716.8 GB/s divided by the weight bytes, at about 76% efficiency).
- **Profile C, 30B-A3B Q4 with experts in RAM on 2 DDR5-4800 channels:**
  - decode about 30–50 t/s at `--n-cpu-moe 20`, slower at 30;
  - prefill about 1.5–2.5k t/s with op-offload and `-ub 2048`.
- **Populating more channels.** Adding 2 more DIMMs (4 channels) roughly doubles the CPU-side
  bandwidth, which would make profile C competitive. Owner's decision.
- **RAG on the CPU (profile A).** Qwen3-0.6B Q8_0 embedding and rerank on 16 SPR cores with AMX
  INT8 (UNVERIFIED speed): roughly 1–3k prompt tokens/s per process. That means:
  - a query embedding takes milliseconds;
  - reranking 20 chunks × 400 tokens takes about 3–8 s;
  - bulk ingestion runs at about 1–3k tokens/s.

  If reranking feels slow, move `rerank` to the GPU (about 1.3 GiB; it fits the 2 GiB headroom)
  or rerank fewer chunks.
- **Effect of context.** gpt-oss prefill falls about 18% from 2k to 32k. Decode slows as the KV
  grows; measure it with `-d`. q8_0 KV halves KV memory at a small quality cost (Ollama FAQ:
  "usually no noticeable impact"; models with many query heads per KV head are more sensitive).

#### 5.3 Benchmark method

1. **Unload the models.**
   `curl -X POST -H "Authorization: Bearer $LLAMA_SWAP_API_KEY" http://llama-swap:8080/api/models/unload`
   (from a container on `ai-net`), or stop the app.
2. **GPU models**, using llama-bench in the matching full image (`tools.sh --bench`). Lists are
   comma-separated:

   ```bash
   docker run --rm --gpus all -v /mnt/tank/ai/models:/models:ro \
     ghcr.io/ggml-org/llama.cpp:full-cuda-b12407 --bench \
     -m /models/gguf/gpt-oss-20b-MXFP4.gguf -ngl 99 -fa on \
     -ub 512,1024,2048 -p 2048,16384 -n 128 -d 0,32768 -r 3 -o md
   ```

3. **Profile C sweep.** Cut the matrix down; the full cross product is large.

   ```bash
   docker run --rm --gpus all -v /mnt/tank/ai/models:/models:ro \
     ghcr.io/ggml-org/llama.cpp:full-cuda-b12407 --bench \
     -m /models/gguf/Qwen3-Coder-30B-A3B-Instruct-UD-Q4_K_XL.gguf \
     -ngl 99 -fa on -ctk q8_0 -ctv q8_0 -ncmoe 18,20,24,30 \
     -t 4,6,8,12,16 -ub 2048 -lm none --no-host 0,1 -nopo 0,1 \
     -p 2048 -n 128 -d 0,16384 -r 3 -o md
   ```

4. **CPU RAG speed:**

   ```bash
   docker run --rm -e NVIDIA_VISIBLE_DEVICES=void -v /mnt/tank/ai/models:/models:ro \
     ghcr.io/ggml-org/llama.cpp:full-cuda-b12407 --bench \
     -m /models/gguf/Qwen3-Embedding-0.6B-Q8_0.gguf -dev none -embd 1 \
     -t 8,16 -p 512,2048 -n 0 -r 3
   ```

   Running the CUDA image without a GPU should fall back to the CPU backend (assumed).
5. **Check the CPU backend.** The server log at start-up should name the CPU variant
   (`sapphirerapids`) and report `AMX_INT8 = 1`.
6. **Check end-to-end prompt caching.** Responses carry `timings.cache_n` (tokens reused) and
   `prompt_n` (tokens processed). Over two Claude Code turns, `cache_n` should cover nearly the
   whole previous prompt. llama-swap's UI shows the same.
7. **Concurrency** (optional): `vllm bench serve --backend openai-chat --endpoint
   /v1/chat/completions --model coder --max-concurrency 1`, run against the gateway. The flag for
   a remote base URL is UNVERIFIED; see `--help`.

### 6. Known problems and fixes

- **An image does not start with an `NVIDIA_REQUIRE_CUDA` error.** It needs CUDA newer than 13.0
  (for example `server-cuda13`, `unified-cuda13`). Use the CUDA 12 tag.
- **Claude Code re-processes the whole prompt every turn.**
  - Set `CLAUDE_CODE_ATTRIBUTION_HEADER=0`.
  - For sliding-window or hybrid models, keep `--ctx-checkpoints` and `--cache-ram` above 0.
  - Make sure no proxy reorders or flattens the `system` array.
- **Out of memory at load.**
  - Profile A: lower `-c` or `-ub`.
  - Profile C: raise `--n-cpu-moe` by 2.
  - Check `nvidia-smi` on the host.
- **Decode drops to a few t/s after hours (profile C).** The experts were evicted. Use `-lm none`,
  keep the ARC cap, and keep the container memory limit above the experts plus `--cache-ram`.
- **Streaming stalls behind Caddy or nginx.** Disable response buffering for SSE (llama-swap
  README). Claude Code aborts after 300 s with no bytes.
- **"Extra inputs are not permitted" or unknown `anthropic-beta`.** Set
  `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`.
- **LiteLLM and `output_config`.** LiteLLM issue #22963 reports Claude Code's `output_config`
  being forwarded to OpenAI and rejected. The `anthropic/` provider used here sends it to
  llama.cpp, which handles it (source). Do not route Claude Code through `openai/` models.

## Fit with Claude Code features

| Claude Code feature (inference-related) | Match with the recommended stack | What is lost |
|---|---|---|
| Model aliases `opus` / `sonnet` / `haiku`, `/model`, `opusplan` | Close: env vars map aliases to `local-*` | Model diversity: on 16 GB all three are one model; `opusplan` gains nothing |
| Background "Haiku" tasks | Served by the primary (no swap); fast with a GPU-resident model | Nothing important |
| Subagents | Same model; requests queue on `-np 1` (or share with `-np 2 -kvu`) | True parallelism; per-subagent model choice costs a swap |
| Tool use, parallel tool calls, `tool_choice` | Supported by llama-server `/v1/messages` | Argument quality and reliability compared with Claude |
| Streaming | SSE supported | Keep-alive pings |
| Prompt caching | Engine prefix cache plus host-RAM prompt cache; good with `ATTRIBUTION_HEADER=0` | `cache_control` semantics and TTL |
| Extended thinking and effort | Mapped to the model's reasoning mode and budget | Adaptive reasoning; exact effort levels |
| Context window and compaction | Works with `CLAUDE_CODE_MAX_CONTEXT_TOKENS=65536` | 200k–1M windows; more compaction |
| Token counting | Native in llama-server and llama-swap. LiteLLM pass-through UNVERIFIED; otherwise Claude Code falls back to a character estimate | Exact counts in the fallback |
| WebSearch | Not available; MCP search on SearXNG (agent D) | The built-in server tool |
| WebFetch | Works (`skipWebFetchPreflight: true`) | The domain blocklist check |
| Vision | Only with a vision GGUF plus `mmproj` | Images with text-only models |
| PDF and document blocks | UNVERIFIED (llama.cpp); unsupported (Ollama) | Native PDF reading |
| Usage and cost | LiteLLM spend logs per key, Prometheus | Claude Code `/cost` |
| Remote Control, fast mode, Advisor | Not available with a custom base URL | These features |

## Verified vs assumed

**Verified** (read in a primary source on 2026-11-15):

- llama.cpp server flags and defaults:
  - `--jinja`, `-fa`, `-ctk`/`-ctv` types, `-c`, `-ngl`, `-ot`, `--cpu-moe`, `--n-cpu-moe`,
    `--moe-cache-mib`, `-np`, `--cache-reuse`, `--cache-ram` (8192), `-kvu`,
    `--ctx-checkpoints`, `--metrics`, `--embedding`, `--reranking`, `--pooling`;
  - `-dev/--device` (`none`), `-lm`, `--no-host`, `--op-offload`, `--repack`, `--fit`,
    `--fit-target`, `-t`, `-tb`, `--numa`, `--models-*`, `--sleep-idle-seconds`,
    `--spec-type`, `--spec-draft-*`, `--no-webui`, `--slots`, `--api-key`;
  - the default port 9931.
- llama.cpp endpoints: Anthropic, OpenAI, Responses, embeddings, rerank, `/metrics` and its
  metric names, `/health`.
- llama.cpp Anthropic conversion code: `tool_choice` mapping, thinking budget, `output_config`,
  `defer_loading`, `cch` normalisation (PR #21793), `parallel_tool_calls` default from the
  template.
- llama.cpp images:
  - tags `server-cuda-b12407`, `server-cuda13-b12407` and `full-cuda-b12407`; release b12418;
  - image configs: `NVIDIA_REQUIRE_CUDA` (`cuda>=12.8` for `server-cuda`, `cuda>=13.5` for
    `server-cuda13`), environment, entrypoints, `tools.sh --bench`.
- The Docker build uses `GGML_NATIVE=OFF`, `GGML_BACKEND_DL=ON` and `GGML_CPU_ALL_VARIANTS=ON`;
  the `sapphirerapids` variant has AVX512 VBMI, VNNI and BF16 plus AMX TILE and INT8; the list of
  AMX kernel quant types.
- llama-bench options, including `-ncmoe`, `-d`, `-lm`, `--no-host`, `-nopo`, `-dev`, `-embd`,
  `-t` lists.
- llama-swap v273:
  - endpoints: `/v1/messages`, `count_tokens`, `/v1/rerank`, `/metrics`, `/upstream/:id`,
    `/api/models/unload`;
  - configuration keys: `apiKeys`, `macros` with `${env.X}` and `${PORT}`, per-model `env`,
    `ttl`, group routing with `swap`/`exclusive`/`persistent`, `hooks.on_startup.preload`,
    `sendLoadingState`;
  - image configs for `v273-cuda-b12407` (cuda>=12.8, root, entrypoint, environment),
    `unified-cuda-273` (cuda>=12.9) and `unified-cuda13-273` (cuda>=13.3).
- Ollama: the Anthropic compatibility lists (no `tool_choice`, `count_tokens`, `cache_control`,
  PDF), the environment variables used, the default 4k context under 24 GiB, the advice to set at
  least 64,000 tokens for coding agents, the tag `0.40.16`.
- Claude Code: every variable in §4.2 and the behaviours cited (1M default for unknown IDs, the
  100k–1M range of `AUTO_COMPACT_WINDOW`, the attribution block, gateway formats, the discovery
  filter, 300 s watchdogs, the WebFetch preflight, Remote Control disabled, no support for
  non-Claude models).
- LiteLLM:
  - the `/v1/messages` endpoint; `anthropic/` with `api_base` appending `/v1/messages`;
    `openai/` and `hosted_vllm/` (including rerank);
  - `cost_per_second`; virtual keys and budgets need Postgres;
  - the configuration keys and environment variables used; `/health/liveliness`;
  - v1.108.8 labelled LTS; the image config (no CUDA, root, venv `PATH`);
  - the October 2026 compromise (Datadog).
- vLLM: the Claude Code doc points; GGUF experimental; FP8 W8A8 on Ada; `--kv-cache-dtype fp8`;
  sleep mode; `/metrics`; `vllm bench serve`; the `v0.33.0` and `v0.32.0` image configs
  (cuda>=13.0).
- SGLang: Anthropic endpoint on by default; `CLAUDE_CODE_ATTRIBUTION_HEADER=0` advice.
- TabbyAPI: routes and configuration; image `latest` requires cuda>=12.8.
- LM Studio: `/v1/messages`; headless llmster; no Docker image mentioned.
- LocalAI: formats and images.
- Xeon w5-3435X (Intel ARK): 16 performance cores, 32 threads, DDR5-4800, 8 channels, PCIe 5.0 with
  112 lanes, AMX, AVX-512.
- TrueNAS 25.10.6 ships driver 580.173.02; 25.10.8 runs kernel 6.12.113.
- NVIDIA: CUDA 12.8 needs driver 570.26 or later; R580 is CUDA 13.0; CUDA 13.5 needs the R620
  branch.
- Model configurations (including gpt-oss-20b's 12 full and 12 sliding-window layers and 131,072
  maximum positions) and GGUF sizes from Hugging Face.
- Benchmark rows [24]–[28] as published by their authors.

**Assumed** (verify on the box):

- All VRAM and RAM budget figures:
  - CUDA context of about 0.3 GiB, compute buffers, non-expert and per-layer expert sizes;
  - `--n-cpu-moe 20/30`;
  - the about 60 GB/s effective bandwidth of 2 × DDR5-4800 channels.
- Tokens/s estimates for this box (§5.2), including CPU RAG speeds with AMX.
- That `GGML_BACKEND_DL` picks `sapphirerapids` and the log lines that show it; that
  `--device none` processes use AMX; the `--no-host` and `-lm none` effects.
- That `CUDA_VISIBLE_DEVICES=-1` prevents a CUDA context in CPU-only children.
- That running the CUDA image with `NVIDIA_VISIBLE_DEVICES=void` falls back to the CPU.
- Thread saturation at about 6–8 threads on 2 channels: Arm roofline guide plus one community
  report, not measured here.
- Whether `--fit` places MoE experts by itself; ZFS mmap double caching; page-cache retention for
  fast swaps; the 32G container limit being enough.
- That LiteLLM's `anthropic/` provider forwards every Claude Code field llama-server needs, and
  whether it passes `count_tokens` through. `hosted_vllm` rerank compatibility with llama.cpp.
- llama-swap accepting `x-api-key` (PR #436 text); `/health` not key-protected; the
  `/upstream/<id>/metrics` path.
- The `python` binary in the LiteLLM image (healthcheck); TrueNAS behaviour per agent E.
- The size of the Claude Code system prompt; tool-use reliability of local models.
- EAGLE-3 draft use with gpt-oss-20b in llama-server; quantised KV quality for gpt-oss.
- Bifrost features; licences of LocalAI, ExLlamaV3 and LiteLLM enterprise parts; the March 2026
  LiteLLM incident (search summaries only); `vllm bench` remote-URL flag; vLLM `--cpu-offload-gb`
  in 0.33.

## Open questions for the owner

1. **Default primary.** Should the default be GPU-resident (profile A: fast, 64k, model about
   12–13 GB or less, e.g. gpt-oss-20b or a dense 14B)? Or the MoE CPU-offload profile C (a
   stronger 30B-A3B Q4 at about 30–50 t/s on 2 channels)? Agent A's quality findings decide.
2. **More memory channels.** Is adding 2 more matching 32 GB RDIMMs (4 channels, 128 GB) an
   option? It roughly doubles CPU-side bandwidth and makes profile C, or larger MoEs, attractive.
3. **RAG models on the CPU.** Is CPU-side embedding and reranking acceptable (zero VRAM; reranking
   20 chunks takes seconds)? Or should `rerank` (or both) stay on the GPU and the primary's
   context shrink?
4. **Gateway.** LiteLLM (featureful, two supply-chain compromises in 2026, pinned by digest),
   Bifrost, or llama-swap's own key check without budgets and spend logs?
5. **Budget units.** GPU-seconds (`cost_per_second`), or only rate and concurrency limits?
6. **Prompt logging.** Should prompts and responses be stored in gateway logs
   (`store_prompts_in_spend_logs`)? This is a privacy decision.
7. **LAN ports.** Should llama-swap's UI and LiteLLM be reachable on LAN ports (9292, 4000), or
   only through Caddy and `ai-net`?
8. **Small model.** Is a separate small model needed at all, given that it swaps the primary out
   on 16 GB?

## Sources

All read on 2026-11-15 unless stated otherwise.

1. llama.cpp server README (master): https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
2. llama.cpp `common/arg.cpp` and `common/common.h`: https://github.com/ggml-org/llama.cpp/blob/master/common/arg.cpp, https://github.com/ggml-org/llama.cpp/blob/master/common/common.h
3. llama.cpp Docker docs: https://github.com/ggml-org/llama.cpp/blob/master/docs/docker.md
4. llama.cpp CUDA Dockerfile and Docker workflow: https://github.com/ggml-org/llama.cpp/blob/master/.devops/cuda.Dockerfile, https://github.com/ggml-org/llama.cpp/blob/master/.github/workflows/docker.yml
5. ggml CPU variants and AMX types: https://github.com/ggml-org/llama.cpp/blob/master/ggml/src/CMakeLists.txt, https://github.com/ggml-org/llama.cpp/blob/master/ggml/src/ggml-cpu/amx/common.h
6. llama.cpp packages and releases (b12418, 2026-11-15): https://github.com/ggml-org/llama.cpp/pkgs/container/llama.cpp, https://github.com/ggml-org/llama.cpp/releases
7. llama.cpp server source (Anthropic conversion, parallel tool-call default): https://github.com/ggml-org/llama.cpp/blob/master/tools/server/server-chat.cpp, https://github.com/ggml-org/llama.cpp/blob/master/tools/server/server-common.cpp
8. llama.cpp function calling doc: https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md
9. llama-bench README: https://github.com/ggml-org/llama.cpp/blob/master/tools/llama-bench/README.md
10. "New in llama.cpp: Anthropic Messages API" (2026-01-19), via search: https://huggingface.co/blog/ggml-org/anthropic-messages-api-in-llamacpp. PR #17570: https://github.com/ggml-org/llama.cpp/pull/17570
11. llama-swap README, config reference, Containerfile, unified image README, `llama-swap.go`; release v273 (2026-11-15):
    - https://github.com/mostlygeek/llama-swap
    - https://github.com/mostlygeek/llama-swap/blob/main/docs/config.example.yaml
    - https://github.com/mostlygeek/llama-swap/blob/main/docker/llama-swap.Containerfile
    - https://github.com/mostlygeek/llama-swap/blob/main/docker/unified/README.md
12. llama-swap PR #436 (API key headers), via search only: https://github.com/mostlygeek/llama-swap/pull/436
13. Ollama docs; release 0.40.16 (2026-11-09):
    - https://docs.ollama.com/api/anthropic-compatibility
    - https://docs.ollama.com/api/openai-compatibility
    - https://docs.ollama.com/faq
    - https://docs.ollama.com/docker
    - https://docs.ollama.com/context-length
    - https://docs.ollama.com/integrations/claude-code
14. Claude Code docs:
    - https://code.claude.com/docs/en/env-vars
    - https://code.claude.com/docs/en/model-config
    - https://code.claude.com/docs/en/llm-gateway
    - https://code.claude.com/docs/en/llm-gateway-protocol
    - https://code.claude.com/docs/en/network-config
    - https://code.claude.com/docs/en/feature-availability
    - https://code.claude.com/docs/en/data-usage
    - https://code.claude.com/docs/en/tools-reference
15. LiteLLM docs:
    - https://docs.litellm.ai/docs/tutorials/claude_non_anthropic_models
    - https://docs.litellm.ai/docs/anthropic_unified
    - https://docs.litellm.ai/docs/providers/anthropic
    - https://docs.litellm.ai/docs/providers/openai_compatible
    - https://docs.litellm.ai/docs/providers/vllm
    - https://docs.litellm.ai/docs/rerank
    - https://docs.litellm.ai/docs/proxy/docker_quick_start
    - https://docs.litellm.ai/docs/proxy/virtual_keys
    - https://docs.litellm.ai/docs/proxy/users
    - https://docs.litellm.ai/docs/proxy/custom_pricing
    - https://docs.litellm.ai/docs/proxy/prometheus
    - https://docs.litellm.ai/docs/proxy/config_settings
    - https://docs.litellm.ai/docs/proxy/health
16. LiteLLM releases (v1.108.8 "LTS", 2026-11-13) and quickstart compose: https://github.com/BerriAI/litellm/releases, https://github.com/BerriAI/litellm/blob/main/litellm/deploy/docker/docker-compose.quickstart.yml
17. Datadog Security Labs, LiteLLM PyPI and Docker compromise (October 2026): https://securitylabs.datadoghq.com/articles/litellm-compromised-pypi-docker/. March 2026 advisory, via search only: https://docs.litellm.ai/blog/security-update-march-2026
18. LiteLLM issue #22963 (`output_config`), via search: https://github.com/BerriAI/litellm/issues/22963
19. vLLM docs (`main`); images v0.33.0 and v0.32.0:
    - https://github.com/vllm-project/vllm/blob/main/docs/serving/integrations/claude_code.md
    - https://github.com/vllm-project/vllm/blob/main/docs/serving/online_serving/openai_compatible_server.md
    - https://github.com/vllm-project/vllm/blob/main/docs/features/quantization/gguf.md
    - https://github.com/vllm-project/vllm/blob/main/docs/features/quantization/README.md
    - https://github.com/vllm-project/vllm/blob/main/docs/features/quantization/llm_compressor/fp8.md
    - https://github.com/vllm-project/vllm/blob/main/docs/features/quantization/quantized_kvcache.md
    - https://github.com/vllm-project/vllm/blob/main/docs/features/sleep_mode.md
    - https://github.com/vllm-project/vllm/blob/main/docs/usage/metrics.md
    - https://github.com/vllm-project/vllm/blob/main/docs/benchmarking/cli.md
    - https://github.com/vllm-project/vllm/blob/main/docs/getting_started/installation/gpu.cuda.inc.md
20. SGLang Anthropic API: https://docs.sglang.io/docs/basic_usage/anthropic_api.md. Release v0.5.23 (2026-11-02): https://github.com/sgl-project/sglang/releases
21. TabbyAPI: https://github.com/theroyallab/tabbyAPI. ExLlamaV3 v1.6.7 (2026-11-13): https://github.com/turboderp-org/exllamav3/releases
22. LM Studio: https://lmstudio.ai/docs/developer/anthropic-compat, https://lmstudio.ai/docs/developer/core/headless_llmster
23. LocalAI (v4.12.1, 2026-10-23): https://github.com/mudler/LocalAI. Bifrost (transports v2.5.1, 2026-11-10): https://github.com/maximhq/bifrost
24. llama.cpp CUDA scoreboard, discussion #15013 (started 2025-08-01; older than 2026): https://github.com/ggml-org/llama.cpp/discussions/15013
25. gpt-oss guide, discussion #15396 (started 2025-08-18; build 6316): https://github.com/ggml-org/llama.cpp/discussions/15396
26. llama-bench `--n-cpu-moe` PR #15952 (merged 2025-09-16): https://github.com/ggml-org/llama.cpp/pull/15952
27. Ollama on 16 GB VRAM benchmark (RTX 4080, i7-14700, 64 GB DDR5-6000; Ollama 0.17.7 update 2026-03-09): https://www.glukhov.org/post/2026/01/choosing-best-llm-for-ollama-on-16gb-vram-gpu/
28. "llama.cpp's MoE cache nearly doubled 30B decode speed on a free T4" (tests 2026-10-17, build b11712): https://dev.to/sampop3/llamacpps-moe-cache-nearly-doubled-30b-decode-speed-on-a-free-t4-15np
29. Aliteq `--n-cpu-moe` guide (updated 2026-11-14; secondary): https://aliteq.com/run-big-moe-model-small-gpu-n-cpu-moe-guide
30. NVIDIA CUDA Toolkit release notes (driver table): https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html
31. TrueNAS 25.10 version notes: https://www.truenas.com/docs/scale/25.10/gettingstarted/versionnotes/. TrueNAS conventions: this repo's `docs/research/e-truenas.md` (agent E, 2026-11-15).
32. Intel Xeon w5-3435X specifications: https://www.intel.com/content/www/us/en/products/sku/233421/intel-xeon-w53435x-processor-45m-cache-3-10-ghz/specifications.html
33. Arm Learning Path, "LLM decode roofline: threads and size" (thread saturation): https://learn.arm.com/learning-paths/cross-platform/llm-decode-roofline/threads-and-size/. Community thread-scaling notes, via search only: https://insiderllm.com/guides/dual-channel-ram-local-llm-cpu-inference/
34. Hugging Face model configs and GGUF listings:
    - https://huggingface.co/openai/gpt-oss-20b
    - https://huggingface.co/ggml-org/gpt-oss-20b-GGUF
    - https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct
    - https://huggingface.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF
    - https://huggingface.co/Qwen/Qwen3-14B
    - https://huggingface.co/mistralai/Devstral-Small-2507
    - https://huggingface.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF
    - https://huggingface.co/Qwen/Qwen3-32B
    - https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507
    - https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF
    - https://huggingface.co/ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF
    - https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF
    - https://huggingface.co/unsloth/GLM-4.7-Flash-GGUF
    - https://huggingface.co/ggml-org/gpt-oss-120b-GGUF
35. Registry tag and image-config checks (2026-11-15):
    - ghcr.io: ggml-org/llama.cpp, mostlygeek/llama-swap, berriai/litellm, theroyallab/tabbyapi
    - Docker Hub: ollama/ollama, vllm/vllm-openai, lmsysorg/sglang, localai/localai, postgres
36. Claude Code issue #51239 (hang with Ollama), via search only: https://github.com/anthropics/claude-code/issues/51239
