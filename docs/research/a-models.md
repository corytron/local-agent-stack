# Open-weight models for agentic coding and tool calling on 16 GB VRAM

Status: research, 2026-11-15. Author: research agent A.

Scope: which publicly available open-weight models best serve a local Claude-Code-like agent on
one RTX 4080 (16 GB), sized for the owner's server as confirmed on 2026-11-15:

- GPU: RTX 4080 16 GB (Ada, sm_89, PCIe 4.0 x16), one card.
- CPU: Intel Xeon w5-3435X (Sapphire Rapids, 16 cores / 32 threads, AVX-512 + AMX, 8 DDR5-4800
  channels on the socket).
- RAM: **two 32 GB DDR5 RDIMMs = 2 of 8 channels populated**, 62.3 GiB usable, about 40 GB
  realistically free for model weights once the ZFS ARC and other apps take their share.
- OS: TrueNAS SCALE 25.10.8 "Goldeye" (containers; see `e-truenas.md` for GPU passthrough and ARC).

All "GB" below are 10^9 bytes (what Hugging Face lists); "GiB" is 2^30 bytes (what `nvidia-smi`
and llama.cpp print). Every source was read on 2026-11-15 unless the source list says otherwise.

## Summary

- **Primary agent model for this box: Qwen3.8-27B** (dense, 27B, Apache 2.0, Aug 2026),
  quantized to about 3.5 bits per weight so it **fits entirely in VRAM**: IST-DASLab
  `Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf` (12.12 GB) or Unsloth `Qwen3.8-27B-UD-Q3_K_XL.gguf`
  (13.15 GB), q8_0 KV cache, 64K context (up to ~96K with the IQ3_S file), MTP speculative
  decoding on. Expected about 40-45 tok/s without MTP and 50-65 tok/s with it on a 4080
  (estimate, calibrated on 16 GB Blackwell/Ada measurements). It has the strongest
  agentic-coding scores of anything that fits (vendor: Terminal-Bench 2.1 73.0, SWE-bench Pro
  61.7) and its hybrid attention keeps the KV cache at 64 KiB/token (f16).
- **Fast second profile: Qwen3.6-35B-A3B** (MoE 35B/3B active, Apache 2.0), Unsloth
  `UD-Q4_K_XL` with `--n-cpu-moe 16` (about 8 GB of experts in RAM): **~80 tok/s measured** on an
  RTX 4080 SUPER with 2-channel DDR5-4800 at 64K context; expect 65-80 tok/s here. Weaker than
  Qwen3.8-27B on agentic benchmarks (NVIDIA-measured SWE-bench Verified 70.1, Terminal-Bench 2.1
  44.4) but much faster for interactive work.
- **With only 2 memory channels (~77 GB/s peak), fully GPU-resident models must be the primary
  choice.** MoE offload is only worth it when few GB of experts are read from RAM per token
  (Qwen3.6-35B-A3B class). gpt-oss-120b (needs ~54 GB of experts in RAM) and GLM-4.5-Air do not
  fit or crawl (est. 10-20 tok/s); Qwen3-Coder-Next and Qwen3.8-Flash-Next are borderline.
- **AMX does not help the MoE offload path in llama.cpp**: the AMX kernels only handle plain
  `MUL_MAT`, not the `MUL_MAT_ID` op that MoE experts use; token generation at batch 1 is
  memory-bandwidth-bound; prompt processing of CPU-resident experts is shipped to the GPU over
  PCIe anyway. AMX/AVX-512 do help CPU-only dense work: embeddings, reranking, a small helper model.
- **Small fast model (Haiku role):** reuse the main model with thinking off (no extra VRAM); if a
  separate model is wanted, Qwen3.5-4B (Q4_K_M 2.74 GB) on the CPU.
- **RAG:** embeddings `Qwen3-Embedding-0.6B` (Apache 2.0, 32K context, official Q8_0 GGUF
  0.64 GB; upgrade `Qwen3-Embedding-4B`), reranker `Qwen3-Reranker-0.6B` (ggml-org Q8_0 GGUF,
  `llama-server --rerank`; upgrade 4B). Both run acceptably on this CPU.
- **Vision:** Qwen3.8-27B and Qwen3.6-35B-A3B are natively vision-language; load their `mmproj`
  (0.6-0.9 GB) at reduced context, or on the CPU. For PDF-to-text ingestion: GLM-OCR (1.3B, MIT).
- **Engine:** llama.cpp (`llama-server`). vLLM/SGLang cannot fit a 27B or 35B model in 16 GB
  (smallest 4-bit safetensors builds are 21-30 GB) and have no expert-offload path as mature as
  llama.cpp's. Ollama's default tags (18-23 GB) spill to CPU and its Hugging Face import has
  corrupted Qwen templates (Nov 2026).
- **Gap to Claude is large and should be designed around.** On the Artificial Analysis
  Intelligence Index (read 2026-11-15) Claude Opus 5.5 scores 59, Sonnet 5.5 55, Haiku 5.5 36,
  Qwen3.8-Flash-Next 29 and Qwen3.8-27B 20. Single tool calls are reliable; long multi-turn tool
  loops, long contexts and thinking-heavy latency are where local models fail. Mitigate with
  small tasks, sub-agents with fresh contexts, early compaction, a short CLAUDE.md, few tools,
  q8_0 KV (never q4_0) and pinned templates.
- **Best upgrade for model choice:** two more matched 32 GB RDIMMs (4 channels, 128 GB, ~154 GB/s
  peak) roughly doubles offload speed and makes Qwen3.8-Flash-Next (AA index 29) and gpt-oss-120b
  usable at an estimated 25-35 tok/s.

## Recommendation

### What the guide should install for this server

| Role | Model (licence) | File(s) | Runs on | Memory | Expected speed on this box |
|---|---|---|---|---|---|
| (a) Primary agent | Qwen3.8-27B (Apache 2.0) | `ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF` : `Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf` (12.12 GB); alt. `unsloth/Qwen3.8-27B-GGUF` : `Qwen3.8-27B-UD-Q3_K_XL.gguf` (13.15 GB) | GPU only | ~14.3 GiB VRAM at 64K q8_0 KV (est.) | 40-45 tok/s, 50-65 with MTP; prefill ~1,000-1,500 tok/s (est.) |
| (a') Fast profile | Qwen3.6-35B-A3B (Apache 2.0) | `unsloth/Qwen3.6-35B-A3B-GGUF` : `Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf` (22.36 GB) | GPU + 16 layers of experts in RAM | ~15.7 GiB VRAM + ~8 GB RAM at 64K | 65-80 tok/s (80 measured on a 4080 SUPER + 2-ch DDR5-4800); prefill ~1,800-2,000 tok/s measured |
| (b) Small/fast | same model as (a), thinking off | (none extra) | GPU | 0 | same as (a), no reasoning tokens |
| (b') Optional separate small model | Qwen3.5-4B (Apache 2.0) | `unsloth/Qwen3.5-4B-GGUF` : `Qwen3.5-4B-Q4_K_M.gguf` (2.74 GB) | CPU | ~3.5 GB RAM | ~12-18 tok/s on 2 channels (est.) |
| (c) Embeddings | Qwen3-Embedding-0.6B (Apache 2.0) | `Qwen/Qwen3-Embedding-0.6B-GGUF` : `Qwen3-Embedding-0.6B-Q8_0.gguf` (0.64 GB) | CPU (AVX-512/AMX) or GPU | ~1 GB | ingestion speed: measure; query latency is small |
| (d) Reranker | Qwen3-Reranker-0.6B (Apache 2.0) | `ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF` : `qwen3-reranker-0.6b-q8_0.gguf` (0.64 GB) | CPU or GPU | ~1 GB | top-20-50 rerank per query: seconds on CPU (est.) |
| (e) Vision | the primary model's projector | `mmproj-F16.gguf` (0.93 GB, Unsloth) or `ggml-org/Qwen3.8-27B-GGUF` : `mmproj-Qwen3.8-27B-Q8_0.gguf` (0.63 GB) | GPU (cut context to ~32-48K) or CPU (`--no-mmproj-offload`) | +0.6-0.9 GiB VRAM | ~0.3 s/image on GPU, ~11 s on CPU (measured on a 5060 Ti box) |
| (e') PDF/OCR ingestion | GLM-OCR (MIT) | `ggml-org/GLM-OCR-GGUF` | GPU between agent sessions, or CPU | ~1.5 GB | batch job |

Reasoning:

1. **Dense in VRAM beats MoE offload on 2 memory channels.** Decode speed of an offloaded MoE is
   bounded by (expert bytes read from RAM per token) / (RAM bandwidth). This box has ~77 GB/s
   peak and ~40-50 GB/s achieved by llama.cpp's CPU expert kernels; a 27B dense model at 3.5 bpw
   in GDDR6X (716.8 GB/s) reads all its weights faster than a big MoE reads its experts from RAM.
2. **Qwen3.8-27B is the strongest model that fits.** Vendor numbers at BF16: Terminal-Bench 2.1
   73.0 vs 63.4 for Qwen3.6-27B; SWE-bench Pro 61.7; IFBench 79.5. Third-party: Artificial
   Analysis Intelligence Index 20 (xhigh), the highest of any model under ~40B total parameters
   listed there (Qwen3.8-Flash-Next 125B-A6B scores 29; Nemotron 3.5 Lightning 6; gpt-oss-120B 4;
   Gemma 4 31B 4). IST-DASLab's quantization study shows its GSQ-RCO IQ3_S (3.5 bpw) matches BF16
   on AIME25, GPQA-Diamond and LiveCodeBench v6 (single-turn).
3. **Its architecture suits 16 GB.** Only 16 of 64 layers keep a KV cache (the rest are Gated
   DeltaNet with a fixed ~0.15 GiB state), so 64K context costs 2.1 GiB at q8_0 instead of ~8 GiB
   for a classic 27B.
4. **Qwen3.6-35B-A3B is the speed profile** for chat, quick edits and sub-agent work, and the one
   MoE that profits from offload on this box (few experts per token, small CPU share).
5. **Everything RAG and helper-model related can live on the CPU**, which is otherwise idle when
   the agent model is GPU-resident; that is where the w5-3435X's AVX-512/AMX actually pay off.
6. **Keep the stack on llama.cpp** and pin the build plus the chat template (Section 9 lists the
   template and parser bugs seen in 2026).

### What not to do on this box

- Do not run gpt-oss-120b, GLM-4.5-Air, Qwen3.5-122B-A10B or Mistral-Small-4-119B with 64 GB on
  2 channels: they either do not fit after ARC/apps or decode at ~10-20 tok/s.
- Do not use `-ctk q4_0` (llama.cpp's own docs warn it "can substantially degrade the model's tool
  calling performance"); use q8_0.
- Do not pull Ollama's default `qwen3.8:27b` (18 GB) or `qwen3.6:35b` (23 GB) tags; they spill to
  the CPU on 16 GB. If Ollama is used at all, build the model from a GGUF with a checked template.
- Do not plan on vLLM for the agent model on this GPU (Section 4.9).

## Options compared

| Option | What it is | Fit for this hardware | Maturity | Licence | Verdict |
|---|---|---|---|---|---|
| **Qwen3.8-27B** | Dense 27B VLM, hybrid DeltaNet/attention, 262K ctx, MTP head, Aug 2026 | Fits fully at 3-3.5 bpw with 64-96K ctx | Very high adoption (6.5M downloads of the Unsloth GGUF); some template issues | Apache 2.0 | **Primary** |
| **Qwen3.6-35B-A3B** | MoE 35B/3B active VLM, hybrid attention, 262K ctx, Apr 2026 | 3-bit fully in VRAM, or Q4 with 16 expert layers in RAM | Mature; many 16 GB reports | Apache 2.0 | **Fast profile** |
| Qwen3.6-27B | Previous dense 27B | Same fit as 3.8 | Mature | Apache 2.0 | Superseded by 3.8 |
| gpt-oss-20b | MoE 21B/3.6B, MXFP4, 131K ctx, Aug 2025 | 12.1 GB file; full 128K ctx fits; 187 tok/s on 4080 SUPER | Very mature; harmony tool format well supported | Apache 2.0 | Fallback only: weak on agentic coding (SWE-V 52.4, TB2.1 15.2, NVIDIA-measured) |
| Gemma 4 26B-A4B | MoE 25.2B/3.8B, 256K ctx, Mar 2026 | QAT q4_0 14.44 GB; IQ4_XS fits ~65K | Tool-call template/parser bugs through mid-2026 | Apache 2.0 | Alternative; weaker on agentic coding (SWE-V 57.4, TB2.1 37.2, NVIDIA-measured) |
| Gemma 4 31B / 12B | Dense | 31B: 17.65 GB QAT, does not fit; 12B: 6.98 GB | As above | Apache 2.0 | Not chosen |
| Devstral Small 2 (24B) | Dense coding model, Dec 2025 | Q4_K_M 14.33 GB, very short ctx | Mature | Apache 2.0 | Superseded (independent SWE-V bash-only 56.4) |
| Nemotron 3.5 Lightning 30B-A3B | Mamba-2/MoE hybrid, Aug 2026 | Q4_0 18.9 GB, needs light offload | New | OpenMDW-1.1 | Weaker than Qwen3.6-35B-A3B in NVIDIA's own table |
| Nemotron 3.5 Bolt 74B-A9B "24GB" | 2-bit QAT LatentMoE VLM, Oct 2026 | 22.02 GB GGUF; ~8 GB in RAM | Very new; NVIDIA recipes target 32 GB+ GPUs | OpenMDW-1.1 | Worth a benchmark (TB2.1 51.0 per NVIDIA); not primary |
| GLM-4.7-Flash | MoE 30B-A3B, Jan 2026 | Q4_K_M 18.31 GB, needs offload | Mature | MIT | Not chosen (SWE-V 59.2 vendor) |
| Granite 4.2 30B | Dense 30B, Aug 2026 | Would need 3-bit | New | Apache 2.0 | Not chosen (SWE-V 57, TB2.1 29.2, IBM) |
| North Mini Code 1.0 | Cohere MoE 30B-A3B coder, Jun 2026 | Similar to 35B-A3B | Needs vLLM main + Cohere parser library | Apache 2.0 | Not chosen (immature tooling) |
| Qwen3-Coder-Next | MoE 80B/3B, Feb 2026 | IQ4_XS 42.7 GB: ~31 GB in RAM | Mature | Apache 2.0 | Borderline on 64 GB/2-ch; superseded by Qwen3.8 |
| Qwen3.8-Flash-Next | MoE 125B/6B + 51B n-gram embeddings, Aug 2026 | Smallest useful files 66-84 GB | New | Qwen Community License 1.0 (internal use allowed) | Best quality locally (AA 29); **after a RAM upgrade** |
| gpt-oss-120b | MoE 117B/5.1B, MXFP4 63.4 GB | ~54 GB of experts in RAM | Mature | Apache 2.0 | Does not fit 64 GB with TrueNAS; after upgrade only |
| GLM-4.5-Air | MoE 106B/12B, Jul 2025 | IQ3_XXS 51.45 GB, 12B active | Mature | MIT | Too slow on 2 channels; dated |
| Qwen3-Embedding-0.6B / 4B | Text embedders, 32K ctx | 0.64 / ~4.3 GB Q8_0 | Very mature (llama.cpp, TEI, vLLM) | Apache 2.0 | **Embeddings** |
| EmbeddingGemma 2 | 0.74B multimodal embedder, 8K ctx, Sep 2026 | 0.31 GB Q8_0 | New | Apache 2.0 | Alternative (images/audio) |
| Nemotron-3-Embed-1B | 1.1B embedder, Jul 2026 | small | vLLM-validated; community GGUF | OpenMDW-1.1 | Alternative (higher retrieval scores, less tooling) |
| jina-embeddings-v5 / jina-reranker-v3.5 | Strong small models | small | Mature | CC-BY-NC-4.0 | Avoid (non-commercial licence) |
| Qwen3-Reranker-0.6B / 4B | Cross-encoder rerankers | 0.64 GB Q8_0 / ~4.3 GB | llama.cpp `--rerank` | Apache 2.0 | **Reranker** |
| bge-reranker-v2-m3 | Older reranker | small | Very mature in TEI | Apache 2.0 | Fallback (weaker: MTEB-R 57.0 vs 65.8) |
| GLM-OCR | 1.3B document OCR VLM, Jan 2026 | small | GGUF from ggml-org | MIT | **PDF ingestion** |

## Details

### 1. Hardware arithmetic the guide can reuse

**VRAM budget.** RTX 4080 = 16 GB GDDR6X, 716.8 GB/s (vendor spec; the 4080 SUPER is 736 GB/s).
On a headless server about 15.5 GiB is usable after the CUDA context (assumed; a retail RTX 5080
reports 16,303 MiB total). llama.cpp's `--fit` is on by default and keeps a 1,024 MiB margin
(`--fit-target`), so it may pick a smaller context than the tables below unless `-c` is given.

**KV cache per token** (from the model cards' layer layouts; f16 = 2 bytes/value, q8_0 = 1.0625):

| Model | Layers with KV | KV heads x dim | f16 per token | q8_0 per token | 64K q8_0 | 128K q8_0 |
|---|---|---|---|---|---|---|
| Qwen3.8-27B / Qwen3.6-27B | 16 of 64 | 4 x 256 | 64 KiB | 34 KiB | 2.1 GiB | 4.25 GiB |
| Qwen3.6-35B-A3B | 10 of 40 | 2 x 256 | 20 KiB | 10.6 KiB | 0.66 GiB | 1.33 GiB |
| gpt-oss-20b | 12 of 24 (others: 128-token window) | 8 x 64 | 24 KiB | 12.8 KiB | 0.8 GiB | 1.6 GiB |
| classic dense 27B (for contrast) | 64 of 64 | 4-8 x 128 | 128-256 KiB | 68-136 KiB | 4.3-8.5 GiB | 8.5-17 GiB |

The Gated DeltaNet layers of the Qwen3.5/3.6/3.8 family keep a fixed recurrent state per sequence
instead: about 0.15 GiB for the 27B and 0.06 GiB for the 35B-A3B (computed from the card's head
counts, f32). The independent calculation in Unsloth discussion #131 matches the 27B figures.

**Decode-speed model** (used for every estimate marked "est."):

    t_token = t_gpu + (expert bytes read from RAM per token) / (achieved RAM bandwidth)
              + ~0.1 ms per layer whose experts live in RAM

Calibration points: (1) Qwen3.6-35B-A3B UD-Q4_K_XL fully on an RTX 3090 = 135.7 tok/s; (2) the
same file on an RTX 4080 SUPER with 16 expert layers in 2-channel DDR5-4800 = ~80 tok/s;
(3) gpt-oss-120b with 22-28 expert layers in desktop 2-channel DDR5 = 22-31 tok/s; (4)
Qwen3.8-Flash-Next UD-IQ3_XXS on an RTX 5080 + 64 GB DDR5 = 24.7 tok/s. These fit an achieved
CPU-side bandwidth of roughly 40-50 GB/s for 2-channel DDR5, i.e. 55-65% of peak. GPU-side MoE
kernels at batch 1 reach only ~25-30% of GPU peak bandwidth (calibration 1), so a small MoE is
launch-overhead-bound, not bandwidth-bound, on the GPU.

**System RAM bandwidth of this CPU** (Intel W-3400 quick reference guide: w5-3435X has 8 DDR5-4800
channels, 1 DIMM per channel for full speed):

| DIMMs populated (matched, 1 per channel) | Peak | Achieved by llama.cpp expert kernels (est.) | Capacity with 32 GB RDIMMs |
|---|---|---|---|
| **2 (today)** | 76.8 GB/s | 40-50 GB/s | 64 GB |
| 4 | 153.6 GB/s | 80-100 GB/s | 128 GB |
| 8 | 307.2 GB/s | 130-180 GB/s (16 cores likely limit it; not measured) | 256 GB |

Whether the two DIMMs really sit in two different channels and run at 4800 MT/s is unverified
(see open questions). Two DIMMs on the same channel would halve the figures above.

**PCIe.** The 4080 is a PCIe 4.0 x16 card (~25 GB/s usable). For prompts of 32+ tokens llama.cpp
copies RAM-resident expert weights to the GPU and runs the batch there (DocShotgun's guide;
`--op-offload` is on by default), so prefill with offload is bounded by roughly
(GB of experts in RAM) / 25 GB/s per micro-batch. With 8 GB in RAM and `-ub 2048` that is ~0.3 s
per 2,048 tokens, which is why the measured prefill stays near 2,000 tok/s.

### 2. Primary model: Qwen3.8-27B

**Facts (model card, verified):** 27B dense (27.78B including the vision encoder per the HF
safetensors index), 64 layers laid out as 16 x (3 x Gated DeltaNet + 1 x Gated Attention), 24 Q /
4 KV heads of dim 256 in the attention layers, MTP head trained with multiple steps, context
262,144 native and up to 1,000,000 with YaRN. Native image and video input. Thinking on by default,
`reasoning_effort` levels `xhigh` (default), `medium`, `low`; `preserve_thinking` on by default.
Licence Apache 2.0. Published on Hugging Face 2026-08-05.

**Vendor benchmarks (BF16, model card; SWE-bench Pro, NL2Repo and DeepSWE run in the Claude Code
harness at 256K context):**

| Benchmark | Qwen3.8-27B | Qwen3.6-27B | Claude Opus 4.6 Max (as listed) |
|---|---|---|---|
| Terminal-Bench 2.1 (Terminus) | 73.0 | 63.4 | 78.2 |
| SWE-bench Pro | 61.7 | 53.5 | 53.4 (official score) |
| NL2Repo-Bench | 42.3 | 36.2 | 47.6 |
| DeepSWE 1.1 | 42.2 | 13.3 | - |
| IFBench | 79.5 | 69.1 | 62.5 |
| LiveCodeBench v6 | 90.3 | 83.9 | 88.8 |

Treat these as upper bounds: they are vendor-run, at full precision, with 256K context. The
third-party Artificial Analysis index (Section 10) is far less flattering.

**Quantization choice (sizes from the HF file listings; quality from IST-DASLab's model card):**

| File | Size | bpw | IST-DASLab quality (single-turn) |
|---|---|---|---|
| GSQ-RCO IQ3_XXS (`ISTA-DASLab/...`) | 10.09 GB (+0.35 GB with MTP head) | 3.0 | 100.6% zero-shot recovery; LCB v6 84.57 vs 85.71 BF16 |
| **GSQ-RCO IQ3_S** | 11.77 GB (12.12 GB `-mtp`) | 3.5 | "task-lossless": AIME25 100, GPQA-D 89.39 vs 89.90, LCB v6 85.71 = BF16 |
| Unsloth UD-IQ3_S | 12.04 GB | 3.52 | GPQA-D 89.90, LCB v6 84.00 (same table) |
| **Unsloth UD-Q3_K_XL** | 13.15 GB | ~3.9 | mean KLD ~0.026 (third-party guide, unverified) |
| Unsloth UD-IQ4_XS | 14.35 GB | ~4.25 | only ~32K ctx fits (see below) |
| Unsloth UD-Q4_K_M | 16.56 GB | ~4.9 | does not fit without `--n-cpu-ffn` (slow) |

Caveats: the IST-DASLab table is single-turn; nobody has published a multi-turn agentic comparison
of these quants. One user's 240-run coding test on a 4090 found Q4_K_XL more consistent than
IQ4_XS on hard tasks, so going above 4 bits matters on bigger GPUs, but on 16 GB the choice is
between ~3.5 bpw in VRAM and much slower partial offload.

**VRAM by context** (weights + 0.15 GiB DeltaNet state + ~0.7 GiB compute buffer + q8_0 KV;
estimates, +-0.5 GiB; verify with `nvidia-smi`):

| File | Weights GiB | 32K | 64K | 96K | 128K |
|---|---|---|---|---|---|
| GSQ-RCO IQ3_XXS | 9.4 | 11.3 | 12.4 | 13.4 | 14.5 |
| GSQ-RCO IQ3_S | 11.0 | 12.9 | 13.9 | 15.0 | 16.1 (no) |
| GSQ-RCO IQ3_S-mtp | 11.3 | 13.2 | 14.3 | 15.3 (tight) | no |
| UD-Q3_K_XL | 12.25 | 14.2 | 15.2 (tight) | no | no |
| UD-IQ4_XS | 13.4 | 15.3 (tight) | ~15.0 only with `-ot token_embd.weight=CPU` | no | no |
| + vision projector | +0.59 (Q8_0) or +0.87 (F16) | | | | |

Moving `token_embd.weight` to the CPU (`-ot "token_embd.weight=CPU"`) frees ~0.6 GiB at almost no
speed cost (lookup only); suggested in Unsloth discussion #70, not measured here.

**Speed (est. for a 4080; measured references):**

- Bandwidth ceiling: 716.8 GB/s / ~11.2 GB read per token (IQ3_S) = ~64 tok/s; llama.cpp dense
  decode typically reaches ~70% of that: **~40-45 tok/s without MTP**.
- With MTP speculative decoding: **~50-65 tok/s** (est.). References: RTX 5060 Ti 16 GB
  (448 GB/s), GSQ-RCO IQ3_S + MTP, 30-41 tok/s over a 256K tool task (llama.cpp discussion
  #28894); RTX 5070 Ti (896 GB/s), UD-IQ3_XXS + MTP 2 + n-gram, 68-74 tok/s (Unsloth discussion #94).
- Prefill: 437-466 tok/s first pass on the 5060 Ti at deep context; the 4080 has about twice the
  compute, so ~900-1,500 tok/s (est.). A 30K-token first turn therefore takes ~20-35 s; later
  turns hit the prompt cache.

**Recommended `llama-server` arguments** (flags verified in the current server README; the MTP
pairing is UNVERIFIED in detail, see note):

    llama-server \
      -m /models/Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf \
      --alias qwen3.8-27b \
      -ngl all -fa on -c 65536 -np 1 \
      -ctk q8_0 -ctv q8_0 \
      -ot "token_embd.weight=CPU" \
      --jinja --reasoning-format deepseek --reasoning-effort medium \
      --spec-type draft-mtp --spec-draft-n-max 3 \
      --temp 1.0 --top-p 0.95 --top-k 20 --min-p 0.0 \
      --no-mmproj --host 0.0.0.0 --port 8080

- `--spec-type draft-mtp` is documented as "use Multi Token Prediction (MTP) heads from the main
  model". With the IST-DASLab `-mtp` file the head is inside the GGUF. With Unsloth or ggml-org
  files the head ships separately (`MTP/mtp-Qwen3.8-27B-Q4_0.gguf`, 1.37 GB, or
  `mtp-Qwen3.8-27B-Q4_0.gguf`, 1.68 GB) and community commands pass it with `-md`; whether `-md`
  is required for the 27B is UNVERIFIED. MTP needs 1-2 GB extra VRAM (Unsloth docs).
- Sampling (model card): thinking `temperature=1.0, top_p=0.95, top_k=20, min_p=0,
  presence_penalty=0`; non-thinking `temperature=0.7, top_p=0.8, top_k=20, presence_penalty=1.5`.
- Reasoning effort: practitioners report `medium` is the sweet spot for agents (a 4090 test:
  `high` ~7x slower and worse; thinking off falls from 99% to 78% at ~106K context). The card warns
  that lower effort can increase total task time through retries.
- Per-request switches go in `chat_template_kwargs` (`enable_thinking`, `reasoning_effort`,
  `preserve_thinking`); `--chat-template-kwargs` sets server defaults.
- Port 8080 is an example; the README lists 9931 as the server default. Agent B owns ports.

**Tool-call format.** The official `chat_template.jinja` emits Qwen3-Coder style XML:
`<tool_call><function=NAME><parameter=ARG>value</parameter></function></tool_call>`. llama.cpp
parses it into OpenAI `tool_calls`; vLLM uses `--tool-call-parser qwen3_coder --reasoning-parser
qwen3` (official vLLM recipe; vLLM's tool-calling doc also lists `qwen3_xml` for this format).

### 3. Fast profile: Qwen3.6-35B-A3B

Facts (model card): 35B total / 3B active, 40 layers as 10 x (3 x DeltaNet + 1 x attention),
256 experts (8 routed + 1 shared, expert dim 512), 262,144 context (1,010,000 extended), vision.
Apache 2.0, published 2026-04-15.

Benchmarks: Qwen-reported SWE-bench Verified 73.4, SWE-bench Pro 49.5, Terminal-Bench 2.0 51.5,
MCP-Atlas 62.8; NVIDIA's re-run (consistent harness) SWE-bench Verified 70.12, Terminal-Bench 2.1
44.38, IFBench 63.71. Community reports describe it "getting lost" on long multi-step runs more
than the 27B dense (secondary source).

Two ways to run it on 16 GB:

| Variant | File | Placement | VRAM | RAM | Speed |
|---|---|---|---|---|---|
| Quality | UD-Q4_K_XL 22.36 GB | `-ngl 99 -ncmoe 16`, 64K q8_0 KV | ~15.7 GiB (measured) | ~8 GB | 80 tok/s measured on 4080 SUPER + DDR5-4800 2-ch; est. 65-80 here |
| Speed | UD-IQ3_XXS 13.21 GB or UD-IQ3_S 13.68 GB | all on GPU, up to 128K q8_0 | ~14.4-14.8 GiB (est.) | ~0 | est. 110-140 tok/s (3090 at Q4 = 135.7) |

Measured command (Unsloth discussion #31, llama.cpp b11900, 2026-10-27):

    llama-server -m Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf --jinja -fa on -ctk q8_0 -ctv q8_0 \
      -np 1 -c 65536 -ngl 99 -ncmoe 16 -t 12 -b 2048 -ub 2048

Results: prefill 1,782-2,068 tok/s, decode 77.4-80.5 tok/s from 2K to 21K prompt tokens;
`-ncmoe 14` overflowed VRAM and prefill fell to 260-510 tok/s. On this box use `-t 16` (physical
cores) as a starting point and sweep `-ncmoe` 14-20.

Notes: speculative decoding (n-gram, draft model) was net-negative for this A3B model on a 3090
(April 2026); test MTP before enabling it. `--swa-full` fixed tool-call loops for one user.

### 4. Other candidates (why they were not chosen)

4.1 **gpt-oss-20b** (Apache 2.0; 21B/3.6B active; 131,072 ctx; MXFP4 GGUF 12.11 GB). The safest
tool caller and fastest option (llama-bench on a 4080 SUPER: pp2048 ~8,171, tg128 ~187 tok/s;
full 128K context fits at f16 KV, ~14.8 GiB). In an August 2026 eight-task test on an RTX 5080 it
was the only model to pass all tasks including a two-turn tool test, but that test did not include
Qwen3.6/3.8. NVIDIA's harness: SWE-bench Verified 52.44, Terminal-Bench 2.1 15.17. Uses the
harmony format (`--tool-call-parser openai` in vLLM; native handler in llama.cpp). Keep as an
emergency fallback, not the default.

4.2 **Gemma 4** (Apache 2.0, Google, Mar-May 2026): E2B, E4B, 12B, 26B-A4B (25.2B/3.8B active, 30
layers, 128 experts 8+1 shared, 256K), 31B. Official QAT q4_0 GGUFs exist (26B 14.44 GB, 31B
17.65 GB, 12B 6.98 GB). NVIDIA-measured 26B-A4B: SWE-bench Verified 57.40, Terminal-Bench 2.1 37.22.
Community BFCL v4 on a 16 GB card (UD-IQ4_XS, 65K ctx): non-live 89.1%, live 63.8%, multi-turn
45.1%. Tool calling was unstable across llama.cpp, vLLM and Ollama through mid-2026 (native
`<|tool_call>` syntax, dropped `role="tool"` messages in the template, reasoning re-injection
causing loops in 33% of seeds on one derivative). Not chosen.

4.3 **Devstral Small 2 24B** (Apache 2.0, Dec 2025): Mistral reports SWE-bench Verified 68.0, but
the independent mini-SWE-agent run on swebench.com is 56.4. Q4_K_M is 14.33 GB, leaving almost no
KV room. Superseded.

4.4 **Nemotron 3.5 Lightning 30B-A3B** (OpenMDW-1.1, Aug 2026): NVIDIA's own table places it below
Qwen3.6-35B-A3B on every coding row (SWE-V 51.56 vs 70.12). Not chosen.

4.5 **Nemotron 3.5 Bolt 74B-A9B-24GB** (OpenMDW-1.1, Oct 2026): a 2-bit quantization-aware-trained
LatentMoE VLM, 22.02 GB GGUF, 256K ctx. NVIDIA's table: Terminal-Bench 2.1 50.98 vs 44.38 for
Qwen3.6-35B-A3B, MCP-Atlas 52.2. NVIDIA's llama.cpp recipes target 32 GB+ GPUs and use `--spec-type
draft-dflash`; on this box ~6-8 GB of experts would sit in RAM (est. 30-45 tok/s, no measurement
found). Worth a benchmark run once; not a primary pick on unverified hybrid behaviour.

4.6 **GLM-4.7-Flash** (MIT, 30B-A3B, Jan 2026): vendor SWE-V 59.2; Q4_K_M 18.31 GB. Not chosen.
**Granite 4.2 30B** (Apache 2.0, dense, Aug 2026): IBM reports SWE-V 57, Terminal-Bench 2.1 29.24,
BFCL v4 61.39. Not chosen. **North Mini Code 1.0** (Cohere, Apache 2.0, 30B-A3B): needs vLLM main
plus Cohere's parser library; not chosen.

4.7 **Qwen3-Coder-Next** (Apache 2.0, 80B/3B active, 512 experts top-10, 262K, Feb 2026). Secondary
sources quote SWE-bench Verified 70.6 (card shows it only as an image). UD-Q4_K_XL 49.6 GB, IQ4_XS
42.7 GB, UD-Q3_K_XL 36.3 GB. On this box: IQ4_XS leaves ~31 GB of experts in RAM, est. 30-38 tok/s.
Usable but no better than Qwen3.8-27B in VRAM.

4.8 **Qwen3.8-Flash-Next** (Qwen Community License 1.0; 125B with 6B active, plus 51B n-gram
embeddings and a 4B MTP head; 48 layers, 512 experts top-10). The best local model by the AA index
(29). Licence allows internal use; a "Model as a Service" or "AI Work Assistant" business needs a
separate licence. Files: Unsloth UD-IQ4_XS 93.7 GB, UD-Q4_K_XL 111 GB, UD-IQ3_XXS 83.6 GB;
IST-DASLab GSQ-RCO IQ3_XXS 75.8 GB, IQ2_XS 68.0 GB, Q2_0 66.4 GB (standard GGUF, run unmodified in
llama.cpp). The n-gram table (27.2 GiB of the IQ4_XS file) is a lookup table that should stay in
RAM or on NVMe via mmap, never on the GPU (forcing it there dropped decode from 108.5 to 1.95
tok/s). Measured on single 16 GB GPUs: RTX 5080 + 64 GB DDR5, UD-IQ3_XXS, 32K: 24.7 tok/s
(27.5-29 with n-gram speculation); RTX 5070 Ti + 128 GB, UD-Q4_K_XL, all experts in RAM, 131K
q8_0: 14.9 tok/s decode, 628 tok/s prefill. On this box today it only fits with the ZFS ARC capped
and part of the file paged from NVMe; see Section 8.

4.9 **Why not vLLM/SGLang for the agent model.** Smallest 4-bit safetensors builds: official
`Qwen3.5-27B-GPTQ-Int4` 30.2 GB, `cyankiwi/Qwen3.8-27B-AWQ-INT4` 21.0 GB, official
`Qwen3.5-35B-A3B-GPTQ-Int4` 24.4 GB. None fit 16 GB with a KV cache. NVFP4 builds need Blackwell.
vLLM remains a fit for embeddings/rerankers and for gpt-oss-20b only.

### 5. Small fast model (the Haiku role)

Claude Code uses a small model for titles, summaries, quick classification. On one 16 GB GPU a
second GPU-resident model costs context or forces swapping (seconds to reload), so:

1. **Default: the same server and model with thinking disabled per request**
   (`chat_template_kwargs: {"enable_thinking": false}`), non-thinking sampling. Zero extra memory.
   How the harness maps its small-model setting to this is agent C's topic.
2. **Optional separate model on the CPU** for parallelism: Qwen3.5-4B (Apache 2.0; vendor BFCL-V4
   50.3, TAU2 79.9; Q4_K_M 2.74 GB, vision via a 0.67 GB mmproj) or Qwen3.5-2B (Q4_K_M 1.28 GB) for
   titles only. Decode is bandwidth-bound: ~2.7 GB per token at ~40-50 GB/s gives ~12-18 tok/s for
   the 4B and ~25-35 tok/s for the 2B (est.). Prefill benefits from AVX-512/AMX (dense `MUL_MAT`).
   Qwen3.5-9B (vendor BFCL-V4 66.1, TAU2 79.1; Q4_K_M 5.68 GB) is better but ~7-9 tok/s on CPU.
3. Other small models checked: Gemma 4 E4B (QAT q4_0 5.15 GB), Granite 4.2 3B/8B (Apache 2.0),
   LFM3-1.7B (LFM licence), Nemotron 3.5 Bolt E4B (OpenMDW). None beats Qwen3.5 at this job with a
   cleaner licence.

### 6. Embeddings and reranker

| Model | Params | Ctx | Dim | Quality (vendor) | Licence | Serving |
|---|---|---|---|---|---|---|
| **Qwen3-Embedding-0.6B** | 0.6B | 32K | 1024 (MRL 32-1024) | MMTEB 64.33; MTEB-Code retrieval 75.41 | Apache 2.0 | llama.cpp `--embedding --pooling last` (official GGUF card); TEI (card example uses `text-embeddings-inference:1.7.2`); vLLM `task="embed"` |
| Qwen3-Embedding-4B | 4B | 32K | 2560 | MMTEB 69.45 | Apache 2.0 | same; Q8_0 ~4.3 GB |
| Qwen3-Embedding-8B | 7.6B | 32K | 4096 | MMTEB 70.58 | Apache 2.0 | too big to share the GPU |
| EmbeddingGemma 2 | 0.74B (270M text) | 8K | 768 (MRL 128-768) | MTEB multilingual v2 61.36, code 78.68; text+image+video+audio | Apache 2.0 | `ggml-org/embeddinggemma-2-GGUF` (Q8_0 0.31 GB) |
| Nemotron-3-Embed-1B | 1.14B | 32K | 2048 | MMTEB retrieval 71.04, RTEB 72.38 (NVIDIA) | OpenMDW-1.1 | vLLM 0.25.0 validated; community GGUF only |
| bge-m3 | 0.6B | 8K | 1024 | MMTEB 59.56 | MIT | everywhere |
| **Qwen3-Reranker-0.6B** | 0.6B | 32K | - | MTEB-R 65.80, MTEB-Code 73.42 | Apache 2.0 | `ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF`, `llama-server --rerank` |
| Qwen3-Reranker-4B | 4B | 32K | - | MTEB-R 69.76, MTEB-Code 81.20 | Apache 2.0 | community GGUFs |
| bge-reranker-v2-m3 | 0.57B | 8K | - | MTEB-R 57.03, MTEB-Code 41.38 (Qwen's table) | Apache 2.0 | TEI |
| jina v5 embeddings / reranker v3.5 | 0.2-1.6B | - | - | strong | **CC-BY-NC-4.0** | avoid |

Recommendation: Qwen3-Embedding-0.6B plus Qwen3-Reranker-0.6B, both Q8_0, both on the CPU via
llama.cpp (dense `MUL_MAT`, which is where the AMX kernels apply: Q4_0/Q4_1/Q8_0/Q4_K/Q5_K/Q6_K/
IQ4_XS/F16 weights). Upgrade either to 4B if retrieval quality disappoints. Choose the embedding
model once: changing it means re-embedding the whole corpus. Qwen embedders are instruction-aware
(queries take a task instruction prefix; documents do not), which the RAG pipeline (agent D) must
implement.

### 7. Vision and documents

- Screenshots and single images: the primary model's projector. Qwen3.8-27B is natively a VLM
  (vendor OmniDocBench 1.5 91.1, OSWorld-Verified 84.3). Loading `mmproj` costs 0.6-0.9 GiB, so
  drop to ~32-48K context in a "vision" preset, or keep it on the CPU with `--no-mmproj-offload`
  (~11 s per image vs ~0.3 s on GPU, measured on a 5060 Ti box).
- Bulk PDF ingestion for RAG: GLM-OCR (zai-org, 1.3B, MIT, `ggml-org/GLM-OCR-GGUF`), run as a batch
  job when the agent is idle. Alternatives: DeepSeek-OCR-2 (3.4B, Apache 2.0), Nemotron-Parse-2.0
  (0.9B, OpenMDW). Agent D decides the ingestion tool.

### 8. MoE CPU offload: AMX, this box, and RAM tiers

**What AMX and AVX-512 do in llama.cpp (verified in source, master, 2026-11-15):**

- The AMX path (`ggml/src/ggml-cpu/amx/`) only claims `GGML_OP_MUL_MAT` for Q4_0, Q4_1, Q8_0, Q4_K,
  Q5_K, Q6_K, IQ4_XS and F16 weights. MoE experts run through `GGML_OP_MUL_MAT_ID`, which the AMX
  path does not handle (the generic CPU repack path does). MXFP4 (gpt-oss) has no AMX kernel.
- Even for dense matmuls, the AMX code notes that the single-row case (m=1, i.e. decoding one
  token) uses an AVX-512-VNNI fast path, not AMX tiles. AMX helps prompt-sized batches.
- With a GPU present, batches of 32+ tokens that touch RAM-resident experts are copied to the GPU
  and computed there, so prefill does not use AMX either.
- The official CUDA Dockerfile builds `-DGGML_BACKEND_DL=ON -DGGML_CPU_ALL_VARIANTS=ON`, which
  includes a `sapphirerapids` CPU variant with AVX-512 VNNI/BF16 and AMX; it is chosen at runtime.

Conclusion: on this box AMX/AVX-512 speed up CPU-only dense work (embeddings, reranking, a small
helper model's prefill) but not hybrid MoE decoding, which is limited by the two memory channels.
KTransformers (`kt-kernel` with the `sglang-kt` fork) has dedicated AMX INT4/INT8 MoE kernels for
Sapphire Rapids, mainly a prefill win; decode would still be bandwidth-bound, and it needs
converted weights and a forked SGLang. Not recommended for this guide.

**Offload candidates on this box (16 GB VRAM, 2-channel DDR5-4800, ~40 GB RAM free):**

| Candidate | File | Experts in RAM | RAM bytes read per token | Decode (est.) | Verdict at 2 channels |
|---|---|---|---|---|---|
| Qwen3.6-35B-A3B UD-Q4_K_XL, `-ncmoe 16` | 22.4 GB | ~8 GB | ~0.25 GB | **65-80 tok/s** (80 measured on similar desktop) | **Usable** |
| Qwen3.6-35B-A3B UD-Q6_K, `-ncmoe ~28` | 29.3 GB | ~19 GB | ~0.58 GB | 38-48 tok/s | Usable, small quality gain |
| Nemotron 3.5 Bolt 74B-A9B-24GB | 22.0 GB | ~7 GB | ~0.5 GB (rough) | 30-45 tok/s (no measurement) | Usable if llama.cpp handles it; benchmark first |
| Qwen3-Coder-Next IQ4_XS, `-ncmoe ~38` | 42.7 GB | ~31 GB | ~0.6 GB | 30-38 tok/s | Borderline (RAM), not worth it |
| Qwen3.8-Flash-Next GSQ-RCO IQ2_XS / IQ3_XXS | 68-76 GB | ~40-45 GB + n-gram table paged from NVMe | ~0.6-0.75 GB | 20-28 tok/s (24.7 measured on a 64 GB desktop) | Only with ARC capped; fragile on ZFS |
| gpt-oss-120b MXFP4, `-ncmoe ~32` | 63.4 GB | ~54 GB | ~1.7 GB | 12-20 tok/s | **Not usable** (does not fit next to TrueNAS) |
| GLM-4.5-Air UD-IQ3_XXS | 51.5 GB | ~40 GB | ~2 GB (12B active) | 10-14 tok/s | **Not usable** (too slow, dated) |
| Qwen3.5-122B-A10B, Mistral-Small-4-119B | 52-76 GB | >40 GB | 2+ GB | <12 tok/s | **Not usable** |
| *Reference: Qwen3.8-27B fully in VRAM* | 12.1 GB | 0 | 0 | **40-45 (50-65 with MTP)** | **Primary** |

**Upgrade option: populate more channels (matched RDIMMs, 1 per channel, per the board manual):**

| Configuration | RAM / peak BW | What changes |
|---|---|---|
| Today: 2 x 32 GB | 64 GB / 76.8 GB/s | Table above |
| **Add 2 matched 32 GB RDIMMs (4 x 32)** | 128 GB / 153.6 GB/s | Qwen3.8-Flash-Next UD-IQ4_XS (93.7 GB) fits with the n-gram table in RAM: est. 25-35 tok/s; gpt-oss-120b: est. 25-32 tok/s; Qwen3.6-35B-A3B Q4 offload: ~5-10% faster (it is GPU-bound) |
| 8 x 32 GB (all channels) | 256 GB / 307.2 GB/s | Flash-Next Q4/Q5 and gpt-oss-120b at est. 35-45 tok/s; gains flatten because GPU time and per-layer sync dominate and 16 cores may not saturate 8 channels |
| 8 x 16 GB (replace the 32s) | 128 GB / 307.2 GB/s | Same capacity as 4 x 32 with the bandwidth of 8 channels |

Mixed DIMM sizes or unequal population per channel should be avoided (unbalanced interleaving;
assumed from general Xeon guidance, not verified for W790). After an upgrade to 128 GB with 4+
channels, the primary pick changes to a two-model setup: Qwen3.8-27B in VRAM for fast turns and
Qwen3.8-Flash-Next with experts in RAM for hard tasks, or Flash-Next alone if its speed is
acceptable in practice.

**Generic RAM-tier table (16 GB VRAM; usable = after OS, ARC and other apps):**

| System RAM | Free for experts | Best agent model | Best larger MoE via offload | Decode (2-ch DDR5 / 4-ch / 8-ch) |
|---|---|---|---|---|
| 32 GB | ~15-20 GB | Qwen3.8-27B IQ3_S in VRAM | Qwen3.6-35B-A3B UD-Q4_K_XL `-ncmoe 16` | 65-80 tok/s (GPU-bound at all channel counts) |
| **64 GB (this box)** | ~40 GB | Qwen3.8-27B IQ3_S in VRAM | Qwen3.6-35B-A3B Q4-Q6; Flash-Next IQ2/IQ3 only with ARC capped | Flash-Next 20-28 / 28-35 / 35-40 |
| 128 GB | ~100 GB | Qwen3.8-27B in VRAM, or Flash-Next | Qwen3.8-Flash-Next UD-IQ4_XS or UD-Q4_K_XL; gpt-oss-120b | Flash-Next 15-25 (measured 14.9-24.7) / 25-35 / 35-45; gpt-oss-120b 15-22 / 25-32 / 35-45 |

All non-measured figures are estimates from the Section 1 model; the owner should run
`llama-bench` (Section 12) before committing.

**TrueNAS notes for offload** (details belong to agent E): model files on ZFS read through the
ARC; llama.cpp's default mmap load can double-cache. Use `--load-mode none` (or `mlock`) for
offload profiles so the experts sit in anonymous memory, and cap `zfs_arc_max` so the ARC does
not compete. Flash-Next measured prefill: 746.7 tok/s with `--load-mode none` vs 400.4 with mmap
(RTX PRO 6000 box).

### 9. Tool calling by engine: what works and known problems

**llama.cpp (`llama-server`)** - recommended.
- `--jinja` is the default; tool calls are parsed into OpenAI `tool_calls` with native handlers
  (Qwen XML, harmony for gpt-oss, Hermes, Mistral and more) or a generic fallback. Parallel tool
  calls are off unless the request sets `"parallel_tool_calls": true`.
- The tool-call output is grammar-constrained once a call starts (described by the maintainers in
  issue #20837).
- Bug to know: Qwen3.5/3.6 sometimes wrote a tool call inside the thinking block and generation
  stopped with no call returned (issue #20837, opened 2026-03-21, closed 2026-11-14 by commit
  3c31179; whether that commit fixes the Qwen case is not confirmed). Use a build newer than
  2026-11-14 and test.
- Hybrid (DeltaNet) and sliding-window models cannot roll their state back to an arbitrary
  position: if the harness rewrites earlier messages, llama.cpp logs "Forcing full prompt
  re-processing" and re-prefills everything. `--ctx-checkpoints N` (default 32) and `--swa-full`
  reduce this. Harnesses should only append to history and compact rarely.
- Templates: the official Qwen 3.5/3.6/3.8 templates had issues with JSON-string tool arguments,
  multiple system/developer messages, and blank `<think>` blocks in history; the community
  `froggeric/Qwen-Fixed-Chat-Templates` (v22.5, 2026-09-03) fixes them, but at least one user
  reports more repeated thinking with it. Treat the template as a pinned, tested artifact
  (`--chat-template-file`).
- Do not quantize the KV cache below q8_0 (llama.cpp function-calling docs).

**Ollama.** Library pages list tools/thinking/vision for `qwen3.6` and `qwen3.8`, but the default
tags are 18-23 GB. Pulling `hf.co/unsloth/...` GGUFs produced a corrupted auto-generated template
and stop parameters (including `stop <think>`) for Qwen3.6 in November 2026. KV quantization is a
global env var (`OLLAMA_KV_CACHE_TYPE`, default f16) and flash attention is
`OLLAMA_FLASH_ATTENTION`; its docs show no per-model expert-offload control comparable to
`--n-cpu-moe`. Suitable for quick tests, not for the agent model.

**vLLM** (for reference): parsers `qwen3_coder` (+ `--reasoning-parser qwen3`) for Qwen3.5+,
`openai` for gpt-oss, `glm47` (+ `glm45`) for GLM-4.7, `mistral` for Devstral, `cohere_command4`
for North Mini Code; a `gemma4` parser exists but had streaming bugs. Not used for the agent model
on 16 GB (Section 4.9).

### 10. Gap analysis versus Claude

**Third-party numbers (read 2026-11-15):**

| Measure | Claude | Best local option that fits this box | Note |
|---|---|---|---|
| Artificial Analysis Intelligence Index (v5.0.1) | Opus 5.5 (Max) 59, Sonnet 5.5 (Max) 55, Haiku 5.5 (Max) 36 | Qwen3.8-27B (xhigh) 20; Qwen3.8-Flash-Next 29 (needs RAM upgrade) | Index includes Terminal-Bench 4.0 and agentic office tasks. Qwen3.8-27B at medium effort: 17; non-reasoning: 10 |
| BFCL v4 multi-turn (leaderboard last updated 2026-04-12, no 2026 Qwen entries) | Opus 4.5 68.4%, Sonnet 4.5 61.4%, Haiku 4.5 53.6% | Qwen3-32B 47.9%, Qwen3-30B-A3B-2507 30.0%; Gemma 4 26B community run 45.1% | Single-turn (non-live AST) is ~86-90% for all of them |
| SWE-bench Verified, mini-SWE-agent bash-only (newest entries Feb 2026) | Opus 4.5 (high) 76.8, Sonnet 4.5 (high) 71.4, Haiku 4.5 (high) 66.6 | Devstral Small 2512 56.4 (Mistral's own claim: 68.0) | Shows how much vendor scaffolds inflate small-model scores |
| Vendor vs third-party, same model | - | Qwen3.6-35B-A3B SWE-V 73.4 (Qwen) vs 70.12 (NVIDIA) | Vendor numbers are BF16, 256K ctx; this box runs 3.5-4.9 bpw at 64K |

Interpretation: a 16 GB-class model is roughly at last year's Haiku level on agentic work in
single, short tool calls, and well below current Haiku 5.5 on long multi-step work. The vendor
claims that Qwen3.8-27B beats Opus 4.6 on SWE-bench Pro should not be taken at face value.

**Where local models fail, and the mitigation for each:**

| Failure mode | Evidence | Mitigation the guide should build in |
|---|---|---|
| Long multi-step tool loops: repetition, losing the plan, repeating a failing call | BFCL multi-turn gap above; Gemma 4 loop reports; Qwen3.6 loop fixed with `--swa-full` | Small, scoped tasks; plan mode writes a step list to a file; harness detects repeated identical tool calls and injects a stop/replan message; cap turns per task |
| Context length | 64-96K practical on 16 GB vs 200K+ for Claude; thinking-off accuracy dropped 99% to 78% at ~106K (one 4090 test) | Keep thinking on at `medium`; compact at ~60-70% of the window; push searching and reading into sub-agents with fresh contexts that return summaries |
| Re-prefill cost | 30K-token prompt = ~20-35 s on this GPU; hybrid models re-prefill on any history edit | Stable system prompt and tool list (prompt cache), append-only history, `--ctx-checkpoints` |
| Instruction following with a large CLAUDE.md | Vendor IFBench 79.5 is good, but rules decay over long contexts (practitioner reports) | Keep CLAUDE.md short (aim for <2-3K tokens); move hard rules into hooks and permission settings, which are deterministic |
| Tool schema overload | Each MCP tool description costs context and choice accuracy | Expose few tools per profile; short descriptions; enum-constrained arguments |
| Malformed tool calls | Template/parser bugs across engines; sub-4-bit claims of malformed calls (unverified) | Grammar-constrained calls in llama.cpp, schema validation and one automatic retry in the harness, pinned build plus template, a tool-call regression test (agent F) |
| Latency from thinking tokens | Qwen3.8-27B used 128M output tokens for the AA index at xhigh vs a 77.7M median | `reasoning_effort: medium` for the main loop, thinking off for the small-model role |
| Quantization loss in long agentic runs | Only single-turn quant studies exist | Prefer IQ3_S/Q3_K_XL over smaller files; re-test when changing quants |

### 11. Verified repositories and files (all returned HTTP 200 from the Hugging Face API, 2026-11-15)

| Purpose | Repository | Files to use (size) |
|---|---|---|
| Primary (official weights) | `Qwen/Qwen3.8-27B` | reference only |
| Primary GGUF (best per bit) | `ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF` | `Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf` (12.12 GB), `Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf` (10.44 GB) |
| Primary GGUF (alternative) | `unsloth/Qwen3.8-27B-GGUF` | `Qwen3.8-27B-UD-Q3_K_XL.gguf` (13.15 GB), `Qwen3.8-27B-UD-IQ3_S.gguf` (12.04 GB), `mmproj-F16.gguf` (0.93 GB), `MTP/mtp-Qwen3.8-27B-Q4_0.gguf` (1.37 GB) |
| Primary GGUF (ggml-org) | `ggml-org/Qwen3.8-27B-GGUF` | `mmproj-Qwen3.8-27B-Q8_0.gguf` (0.63 GB), `mtp-Qwen3.8-27B-Q4_0.gguf` (1.68 GB); its Q4_K_M (19.4 GB) is too big |
| Primary GGUF (bartowski) | `bartowski/Qwen3.8-27B-GGUF` | `Qwen3.8-27B-Q3_K_M.gguf` (13.40 GB), `Qwen3.8-27B-IQ3_XS.gguf` (12.80 GB) |
| Fast profile | `unsloth/Qwen3.6-35B-A3B-GGUF` | `Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf` (22.36 GB), `Qwen3.6-35B-A3B-UD-IQ3_XXS.gguf` (13.21 GB), `Qwen3.6-35B-A3B-UD-IQ3_S.gguf` (13.68 GB), `mmproj-F16.gguf` (0.90 GB) |
| Fast profile (others) | `ggml-org/Qwen3.6-35B-A3B-GGUF`, `bartowski/Qwen_Qwen3.6-35B-A3B-GGUF`, `unsloth/Qwen3.6-35B-A3B-MTP-GGUF` | |
| Fallback | `ggml-org/gpt-oss-20b-GGUF` | `gpt-oss-20b-MXFP4.gguf` (12.11 GB) |
| Alternatives | `google/gemma-4-26B-A4B-it-qat-q4_0-gguf` (14.44 GB + 1.19 GB mmproj), `unsloth/gemma-4-26B-A4B-it-GGUF`, `unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF`, `ggml-org/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-GGUF`, `nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB-GGUF` (22.02 GB) | |
| Small model | `unsloth/Qwen3.5-4B-GGUF` | `Qwen3.5-4B-Q4_K_M.gguf` (2.74 GB); also `unsloth/Qwen3.5-2B-GGUF`, `unsloth/Qwen3.5-9B-GGUF` |
| Embeddings | `Qwen/Qwen3-Embedding-0.6B-GGUF` | `Qwen3-Embedding-0.6B-Q8_0.gguf` (0.64 GB); safetensors `Qwen/Qwen3-Embedding-0.6B`; upgrade `Qwen/Qwen3-Embedding-4B-GGUF` |
| Embeddings (alt.) | `ggml-org/embeddinggemma-2-GGUF`, `google/embeddinggemma-2`, `nvidia/Nemotron-3-Embed-1B-BF16`, `BAAI/bge-m3` | |
| Reranker | `ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF` | `qwen3-reranker-0.6b-q8_0.gguf` (0.64 GB); safetensors `Qwen/Qwen3-Reranker-0.6B`, upgrade `Qwen/Qwen3-Reranker-4B`; fallback `BAAI/bge-reranker-v2-m3` |
| OCR | `ggml-org/GLM-OCR-GGUF`, `zai-org/GLM-OCR` | |
| After RAM upgrade | `unsloth/Qwen3.8-Flash-Next-GGUF` (`UD-IQ4_XS/`, `UD-Q4_K_XL/`, `MTP/`), `ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF` (`IQ3_S/`, `IQ3_XXS/`, `IQ2_XS/`), `ggml-org/gpt-oss-120b-GGUF` (`gpt-oss-120b-MXFP4.gguf`, 63.39 GB), `unsloth/Qwen3-Coder-Next-GGUF` | |

`bartowski/Qwen_Qwen3.8-27B-GGUF` (with the `Qwen_` prefix bartowski uses elsewhere) does not
exist; use `bartowski/Qwen3.8-27B-GGUF`.

### 12. Benchmark checklist for the owner's box (before finalising the guide)

1. `dmidecode -t memory` (on the host): confirm the two RDIMMs are in different channels and their
   configured speed (4800 vs 4400 MT/s).
2. `nvidia-smi --query-gpu=memory.total,memory.used --format=csv` with nothing loaded: usable VRAM.
3. `llama-bench -m <Qwen3.8-27B IQ3_S> -ngl 99 -fa 1 -ctk q8_0 -ctv q8_0 -p 512,8192 -n 128 -d 0,32768`
   (prefill/decode at empty and 32K depth).
4. `llama-bench -m <Qwen3.6-35B-A3B UD-Q4_K_XL> -ngl 99 -ncmoe 14,16,18,20 -t 8,16 -fa 1 -ctk q8_0 -ctv q8_0`.
5. Start `llama-server` with the Section 2 arguments, run an agent task with tool calls for 30
   minutes, and watch for: tool calls in `reasoning_content`, "Forcing full prompt re-processing",
   repeated identical calls.

## Fit with Claude Code features

| Claude Code feature | How the recommended models match | What is lost |
|---|---|---|
| Main agent loop (Opus/Sonnet) | Qwen3.8-27B with thinking, tool calls in OpenAI format via llama-server | Roughly a third of Opus 5.5 on the AA index; weaker on long multi-step tasks; 40-65 tok/s plus long first-turn prefill |
| Small fast model (Haiku) | Same model, thinking off; or Qwen3.5-4B on CPU | Fine for titles/summaries; slower than Haiku in parallel use |
| Sub-agents | Same server, separate requests; `-np 2` lets two run concurrently but splits the KV budget (e.g. 2 x 32K) | Fewer and smaller parallel sub-agents; a 16 GB card gives one strong model at a time |
| Extended thinking | `reasoning_effort` low/medium/xhigh, `preserve_thinking` | Thinking is slower and less efficient; use medium |
| Plan mode | Prompt-level; the model follows it | More drift on long plans; keep plans in files |
| Long context / auto-compact | 64K (27B IQ3_S at q8_0) up to ~96K; 128K+ only with the 35B-A3B or smaller quants | No 200K-1M working window; compaction happens much sooner |
| CLAUDE.md memory | Works as a system prompt | Long files cost context and are followed less reliably |
| Tools and MCP | Native tool calling (Qwen XML parsed by llama.cpp) | Many tools degrade choice accuracy; use few |
| Parallel tool calls | Supported by llama.cpp when requested | Less reliable than Claude; consider disabling |
| Reading images, screenshots, PDF pages | Native vision via mmproj; GLM-OCR for bulk PDFs | Costs VRAM/context; CPU projector is slow |
| Web search/fetch summarisation | Main or small model summarises pages | Long pages must be chunked; quality below Claude |
| RAG over own documents (not in Claude Code) | Qwen3-Embedding + Qwen3-Reranker on CPU | New capability |
| Hooks, slash commands, skills, permissions | Model-independent (harness features, agent C) | Nothing from the model side; hooks are the best defence against weak instruction following |

## Verified vs assumed

**Verified** (primary source read on 2026-11-15):

- Model facts, licences, parameter counts, context lengths, layer layouts and vendor benchmark
  tables for Qwen3.8-27B, Qwen3.6-35B-A3B, Qwen3.6-27B, Qwen3.8-Flash-Next, Qwen3-Coder-Next,
  Qwen3.5-9B/4B, Gemma 4, gpt-oss-20b, Devstral Small 2, Nemotron 3.5 Lightning and Bolt, GLM-4.7-
  Flash, Granite 4.2 30B, North Mini Code 1.0, Qwen3-Embedding, Qwen3-Reranker, EmbeddingGemma 2,
  Nemotron-3-Embed-1B (model cards and HF API metadata).
- Licence texts: Qwen Community License 1.0 (internal use allowed; MaaS/AI-work-assistant
  businesses need a licence); OpenMDW-1.1 (permissive); jina v5 models CC-BY-NC-4.0 (HF metadata).
- Every GGUF file size in this document (HF tree API) and the existence of every repository in
  Section 11.
- llama.cpp flags: `-ncmoe/--n-cpu-moe`, `-cmoe`, `-ot`, `--n-cpu-ffn`, `--moe-cache-mib`,
  `-ctk/-ctv` types, `-fa`, `--fit` (default on, 1,024 MiB margin), `--jinja` (default on),
  `--reasoning-format`, `--reasoning-effort`, `--reasoning-budget`, `--reasoning-preserve`,
  `--chat-template-kwargs`, `--chat-template-file`, `--spec-type draft-mtp` and the other spec
  types, `-md`, `--spec-draft-n-max`, `--rerank`, `--embedding`, `--pooling`, `--repack`,
  `--op-offload`, `--load-mode`, `--ctx-checkpoints`, `--swa-full`, `--no-mmproj`,
  `--mmproj-offload` (server README, master).
- AMX kernels cover only `MUL_MAT` with Q4_0/Q4_1/Q8_0/Q4_K/Q5_K/Q6_K/IQ4_XS/F16; no `MUL_MAT_ID`
  (llama.cpp source). The CUDA Dockerfile builds all CPU variants including `sapphirerapids`.
- llama.cpp docs warning about `-ctk q4_0` and tool calling; native tool-format handlers list.
- Issue #20837 details and closing commit; Unsloth/HF discussion numbers quoted (each is a single
  user's measurement).
- w5-3435X: 16C/32T, 8 channels DDR5-4800, 1 DPC for max speed, 112 PCIe 5.0 lanes, AVX-512 + AMX
  (TMUL) + BF16 (Intel W-3400 quick reference guide).
- vLLM parser names (vLLM tool-calling doc and the official Qwen3.8 recipe); Ollama env vars
  (Ollama FAQ).
- Artificial Analysis index values (leaderboard and Qwen3.8 27B model page), BFCL v4 CSV, SWE-bench
  leaderboard JSON, Aider polyglot YAML (the last three are stale: April 2026, Feb 2026, Oct 2025).

**Assumed** (inferred, estimated or from secondary sources):

- All "est." tokens/s figures, including every number for this server; they come from the
  bandwidth model in Section 1, calibrated on other machines.
- Achieved RAM bandwidth of 40-50 GB/s for 2 channels and the 4- and 8-channel scaling; per-core
  bandwidth limits of 16 Sapphire Rapids cores are not measured.
- RTX 4080 bandwidth (716.8 GB/s), PCIe 4.0 x16, usable VRAM ~15.5 GiB (vendor specs from memory).
- VRAM-by-context totals (compute buffer ~0.7 GiB assumed).
- That `--spec-type draft-mtp` picks up the MTP head from the IST-DASLab `-mtp` file without `-md`.
- That the TrueNAS host leaves ~40 GB for model weights (coordinator's figure).
- Qwen3-Coder-Next SWE-bench Verified 70.6 (secondary sources; card shows an image).
- KLD ~0.026 for UD-Q3_K_XL (third-party guide); the claim that sub-4-bit quants cause malformed
  tool calls (secondary guide, contradicted by several practitioner reports).
- That DIMMs of mixed size should not be combined on W790 (general guidance).
- Community statements that Qwen3.6-35B-A3B gets lost on long tasks and Qwen3.8-27B makes fewer
  failed tool calls (anecdotal).

## Open questions for the owner

1. **Default profile:** Qwen3.8-27B (stronger, ~45-65 tok/s) as the default with Qwen3.6-35B-A3B
   (~65-80 tok/s) as the fast profile, or the reverse? Recommendation: 27B default.
2. **RAM upgrade:** add two matched 32 GB DDR5-4800 RDIMMs (4 channels, 128 GB) to enable
   Qwen3.8-Flash-Next and gpt-oss-120b at an estimated 25-35 tok/s? Eight DIMMs add bandwidth but
   with diminishing returns.
3. **ZFS ARC cap:** how much RAM may the model stack take from the ARC (decide with agent E)?
4. **Is the RTX 4080 headless** (no display or desktop attached)? That decides whether 64K
   context fits beside the 27B.
5. **Vision default:** keep the projector on the GPU (shorter context) or on the CPU (slow
   images)?
6. **Licence:** is the Qwen Community License 1.0 acceptable for Qwen3.8-Flash-Next, should it be
   used after an upgrade? (Personal/internal use is permitted by its text.)

## Sources

All read on 2026-11-15.

1. https://huggingface.co/Qwen/Qwen3.8-27B (model card, `chat_template.jinja`, file list)
2. https://recipes.vllm.ai/Qwen/Qwen3.8-27B
3. https://huggingface.co/unsloth/Qwen3.8-27B-GGUF (file list) and discussions /70, /94, /112, /121, /130, /131, /140
4. https://huggingface.co/ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF
5. https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF and https://huggingface.co/bartowski/Qwen3.8-27B-GGUF
6. https://unsloth.ai/docs/models/qwen3.8-27b
7. https://github.com/ggml-org/llama.cpp/discussions/28894 (Qwen3.8-27B on RTX 5060 Ti, 2026-09-14)
8. https://huggingface.co/Qwen/Qwen3.6-35B-A3B and https://huggingface.co/Qwen/Qwen3.6-27B
9. https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF (file list) and discussions /2, /5, /14, /31, /32
10. https://huggingface.co/Qwen/Qwen3.8-Flash-Next (card and LICENSE)
11. https://huggingface.co/unsloth/Qwen3.8-Flash-Next-GGUF (file list) and discussion /3
12. https://huggingface.co/ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF
13. https://dev.to/alanwest/how-to-run-qwen38-flash-next-locally-39-toks-on-24gb-of-vram-plus-96gb-ram-12ca
14. https://huggingface.co/Qwen/Qwen3-Coder-Next and https://huggingface.co/unsloth/Qwen3-Coder-Next-GGUF
15. https://huggingface.co/Qwen/Qwen3.5-9B, https://huggingface.co/Qwen/Qwen3.5-4B, https://huggingface.co/unsloth/Qwen3.5-4B-GGUF
16. https://huggingface.co/Qwen/Qwen3.5-27B-GPTQ-Int4, https://huggingface.co/Qwen/Qwen3.5-35B-A3B-GPTQ-Int4, https://huggingface.co/cyankiwi/Qwen3.8-27B-AWQ-INT4 (file sizes)
17. https://huggingface.co/google/gemma-4-26B-A4B-it (card; covers the whole Gemma 4 family)
18. https://huggingface.co/google/gemma-4-26B-A4B-it-qat-q4_0-gguf, https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF and discussions /42, /43
19. https://discuss.huggingface.co/t/gemma-4-bug-fixes-and-research-request/176979 (seen via search summary only)
20. https://huggingface.co/openai/gpt-oss-20b (card, config.json) and https://huggingface.co/ggml-org/gpt-oss-20b-GGUF
21. https://github.com/ggml-org/llama.cpp/discussions/15396 (gpt-oss guide, 2025-08-18; older source)
22. https://github.com/ggml-org/llama.cpp/discussions/15013 (CUDA scoreboard, Aug 2025; older source)
23. https://huggingface.co/mistralai/Devstral-Small-2-24B-Instruct-2512
24. https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16
25. https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB and https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB-GGUF
26. https://openmdw.ai/license/1-1/
27. https://huggingface.co/zai-org/GLM-4.7-Flash and https://huggingface.co/unsloth/GLM-4.7-Flash-GGUF
28. https://huggingface.co/ibm-granite/granite-4.2-30b
29. https://huggingface.co/CohereLabs/North-Mini-Code-1.0
30. https://huggingface.co/unsloth/GLM-4.5-Air-GGUF, https://huggingface.co/unsloth/Qwen3.5-122B-A10B-GGUF, https://huggingface.co/unsloth/Mistral-Small-4-119B-2603-GGUF (file sizes)
31. https://huggingface.co/ggml-org/gpt-oss-120b-GGUF (file size)
32. https://huggingface.co/Qwen/Qwen3-Embedding-4B (comparison table incl. 0.6B/8B) and https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF
33. https://huggingface.co/Qwen/Qwen3-Reranker-4B and https://huggingface.co/ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF
34. https://huggingface.co/google/embeddinggemma-2 and https://huggingface.co/ggml-org/embeddinggemma-2-GGUF
35. https://huggingface.co/nvidia/Nemotron-3-Embed-1B-BF16
36. https://huggingface.co/jinaai/jina-embeddings-v5-text-small, https://huggingface.co/jinaai/jina-reranker-v3.5 (licence metadata)
37. https://huggingface.co/zai-org/GLM-OCR and https://huggingface.co/ggml-org/GLM-OCR-GGUF
38. https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
39. https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
40. https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md
41. https://github.com/ggml-org/llama.cpp/tree/master/ggml/src/ggml-cpu/amx (`amx.cpp`, `common.h`, `mmq.cpp`) and https://github.com/ggml-org/llama.cpp/blob/master/ggml/src/CMakeLists.txt
42. https://github.com/ggml-org/llama.cpp/blob/master/.devops/cuda.Dockerfile
43. https://github.com/ggml-org/llama.cpp/issues/20837
44. https://huggingface.co/froggeric/Qwen-Fixed-Chat-Templates
45. https://github.com/vllm-project/vllm/blob/main/docs/features/tool_calling.md
46. https://github.com/ollama/ollama/blob/main/docs/faq.mdx, https://ollama.com/library/qwen3.8, https://ollama.com/library/qwen3.6
47. https://artificialanalysis.ai/leaderboards/models and https://artificialanalysis.ai/models/qwen3-8-27b
48. https://gorilla.cs.berkeley.edu/leaderboard.html and https://gorilla.cs.berkeley.edu/data_overall.csv (last updated 2026-04-12)
49. https://github.com/SWE-bench/swe-bench.github.io/blob/master/data/leaderboards.json (newest entries 2026-02-26)
50. https://github.com/Aider-AI/aider/blob/main/aider/website/_data/polyglot_leaderboard.yml (newest entries 2025-10-03; stale)
51. https://gist.github.com/DocShotgun/a02a4c0c0a57e43ff4f038b46ca66ae0 (MoE CPU+GPU offload guide, last active 2026-11-07)
52. https://github.com/kvcache-ai/ktransformers (README) and https://github.com/kvcache-ai/ktransformers/blob/main/kt-kernel/README.md
53. https://cdrdv2-public.intel.com/751438/Intel%20Xeon_W-3400_and_Xeon_W-2400_QuickRefGuide.pdf
54. https://www.intel.com/content/www/us/en/products/sku/233421/ (ARK listing for w5-3435X, via search summary)
55. https://techfuelhq.com/articles/best-local-llm-coding-2026/ (RTX 5080 test, updated 2026-11-04)
56. https://www.xda-developers.com/i-stopped-thinking-my-8gb-gpu-was-too-small-after-learning-to-offload-moe-llm-layers-to-ram/ (2026-10-22)
57. https://llmkube.com/blog/hybrid-moe-offloading-qwen-36-deltanet (2026-04-18)
58. https://hashnode.com/blog/best-open-weight-llms (landscape, 2026-10-28) and https://kilo.ai/new-open-weight-models (catalogue dates)
59. https://huggingface.co/api/models?author=... (Hugging Face API listings used to enumerate 2026 releases by Qwen, Google, Mistral, OpenAI, Z.ai, NVIDIA, IBM, Microsoft, DeepSeek, ByteDance-Seed, Moonshot, Cohere, LiquidAI, AllenAI, Meta, Jina, BAAI, Alibaba-NLP)
