title: Model profiles and alternatives
kind: appendix

# Model profiles and alternatives

This appendix describes the model profiles the stack supports on one RTX 4080 16 GB with two of the
CPU's eight memory channels populated, the models that do not suit that server and why, the memory
upgrade that changes the choice, and the coding agents that can stand in for OpenCode.

Figures marked "est." are estimates from the research notes' bandwidth model, calibrated on other
machines; "measured" figures come from published runs on similar hardware. Measure on your own
server before you rely on either (Chapter 9). The files in `stack/` are the authority for every
flag; this appendix explains the choices behind them.

## Model profiles compared

Table: Model profiles

| Profile | GPU model and context | Memory | Decode, tokens/s | Use for |
|---|---|---|---|---|
| Default | Qwen3.8-27B GSQ-RCO IQ3_S with MTP head, 64K, q8_0 KV cache; RAG models on the CPU | About 14.3 GiB VRAM (est.) | 40 to 45; 50 to 65 with MTP (est.) | Agent work and chat |
| Fast | Qwen3.6-35B-A3B UD-Q4_K_XL, experts of 16 layers in RAM, 64K | About 15.7 GiB VRAM (measured) and 8 GB RAM | 65 to 80 (80 measured) | Interactive edits and short tasks |
| RAG on GPU | A smaller primary configuration at 32K; embedding and reranker on the GPU | About 2.8 GiB VRAM for the RAG models (est.) | Depends on the primary | RAG-heavy chat in Open WebUI |

### Default profile with Qwen3.8-27B on the GPU

The default profile keeps the generating model entirely in VRAM. llama-swap serves it as `coder`
from `Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf` (`ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF`, 12.12 GB), with
`-ngl 99 -c 65536 -ctk q8_0 -ctv q8_0 --jinja` and the model's MTP head for speculative decoding.
LiteLLM exposes it under every client-facing chat name: `local-coder`, `local-fast` (the same model
with thinking off), and `local-opus`, `local-sonnet` and `local-haiku` for Claude Code.

Why this model:

- **It is the strongest model that fits.** Vendor figures at full precision: Terminal-Bench 2.1
  73.0 and SWE-bench Pro 61.7. On the third-party Artificial Analysis Intelligence Index it scores
  20, the highest of any model under about 40B total parameters listed there.
- **The quantization holds up.** IST-DASLab's study reports the GSQ-RCO IQ3_S file (3.5 bits per
  weight) matching full precision on AIME25, GPQA-Diamond and LiveCodeBench v6. These are
  single-turn tests; no multi-turn agentic comparison of the quantizations is published.
- **Its context is cheap.** Only 16 of its 64 layers keep a KV cache; the others hold a fixed
  state of about 0.15 GiB. 64K of context costs about 2.1 GiB at q8_0, instead of about 8 GiB for
  a classic dense 27B.

Table: Default profile VRAM budget (est., plus or minus 0.5 GiB)

| Part | GiB |
|---|---|
| Weights, `IQ3_S-mtp` file | 11.3 |
| Fixed recurrent state | 0.15 |
| Compute buffer | about 0.7 |
| KV cache, 64K at q8_0 | 2.1 |
| Total | about 14.3 |

About 15.5 GiB of the card is usable on a headless server (assumed), which leaves about 1 GiB of
headroom. `stack/` spends it on the MTP draft context and wins back about 0.6 GiB by keeping the
token embeddings, a lookup table, on the CPU (`-ot token_embd.weight=CPU`). It runs one 64K slot
(`-np 1`) with a 6 GiB host-RAM prompt cache (`--cache-ram 6144`). Prompt processing runs at about 900 to 1,500 tokens per second (est.), so a cold
30,000-token first turn takes 20 to 35 seconds; later turns reuse the prompt cache.

The embedding and reranker models (`Qwen3-Embedding-0.6B` and `Qwen3-Reranker-0.6B`, both Q8_0)
run on the CPU with `--device none` in llama-swap's persistent `rag` group. They use no VRAM and
about 1.3 GiB of RAM each (est.). The CPU's AVX-512 and AMX kernels apply to this dense work.
Reranking 20 chunks of 400 tokens takes about 3 to 8 seconds (est.).

To confirm the budget, run the following command in **System > Shell** on TrueNAS while `coder` is
loaded:

```
nvidia-smi --query-gpu=memory.total,memory.used --format=csv
```

`memory.used` is roughly 14,000 to 15,500 MiB. A value at the card's total, or a load that fails
with an out-of-memory error in the container log, means the context or the MTP draft does not fit:
remove the two `--spec-*` flags first, then lower `-c`.

### Fast profile with Qwen3.6-35B-A3B expert offload

The fast profile trades agentic strength for speed. llama-swap serves it as `coder-moe` from
`Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf` (`unsloth/Qwen3.6-35B-A3B-GGUF`, 22.36 GB) with
`--n-cpu-moe 16`: the expert weights of 16 layers, about 8 GB, stay in system RAM. Clients reach it
as `local-coder-moe`.

- **Speed.** A published run on an RTX 4080 SUPER with two channels of DDR5-4800, a 64K context
  and prompts of 2K to 21K tokens measured 77.4 to 80.5 tokens/s of generation and 1,782 to 2,068
  tokens/s of prompt processing. With `--n-cpu-moe 14` the same run overflowed VRAM and prompt
  processing fell to 260 to 510 tokens/s.
- **Why offload works here.** The model activates 3B of its 35B parameters per token, so only
  about 0.25 GB of expert weights is read from RAM per token. The GPU, not the memory channels,
  sets the pace.
- **Quality.** NVIDIA's re-run in a consistent harness gives SWE-bench Verified 70.12 and
  Terminal-Bench 2.1 44.38; the default model's 73.0 on Terminal-Bench 2.1 is a vendor figure from
  a different harness, so compare with care. Community reports describe the fast model losing the
  plan on long multi-step runs more often than the default model.
- **Placement and tuning.** `stack/` loads it with `-lm none`, so the experts in RAM are
  anonymous memory that the kernel cannot evict and the ZFS ARC does not cache a second time. It
  starts from `-t 8 -tb 16`, because generation on two memory channels saturates at about 6 to 8
  threads. Sweep `-t` from 4 to 16 and `--n-cpu-moe` from 14 to 20 with the benchmark in
  Chapter 9, and keep the fastest setting that fits.

!!! caution
    llama-swap keeps one GPU model loaded at a time. While any client uses `local-coder-moe`, a
    request for `local-coder` from another client or agent swaps the models back, and the next
    fast-profile request swaps them again. Switch profiles for a whole working session, not per
    request.

To use the fast profile from OpenCode:

1. In `opencode.jsonc`, copy the `local-coder` entry of the `local` provider, rename the copy
   `local-coder-moe` and keep its `limit` values; both models run with a 64K context.

2. Run a task against it.

        opencode run --model local/local-coder-moe "Reply with the single word OK."

    The answer is `OK`. The first request takes longer while llama-swap loads the model.

3. In **System > Shell** on TrueNAS, check the GPU memory.

        nvidia-smi --query-gpu=memory.used --format=csv

    `memory.used` is about 16,000 MiB.

4. When the session ends, send any request to `local-coder` so that the default model is loaded
   for the other clients.

### RAG-on-GPU profile

If reranking on the CPU is too slow for RAG-heavy chat, first rerank fewer chunks. If that is not
enough, move one or both RAG models to the GPU. Each costs about 1.4 GiB of VRAM (0.6 GiB of
weights, the KV cache at 4K, compute buffers and a CUDA context), so the primary model has to give
up context.

Table: RAG-on-GPU configurations (est.)

| Configuration | VRAM, GiB | Fits in about 15.5 GiB |
|---|---|---|
| Default primary at 64K, both RAG models on the GPU | 14.3 + 2.8 = 17.1 | No |
| `IQ3_S-mtp` at 32K, both RAG models on the GPU | 13.2 + 2.8 = 16.0 | No |
| `IQ3_S-mtp` at 32K, reranker only on the GPU | 13.2 + 1.4 = 14.6 | Yes |
| `IQ3_XXS-mtp` (10.44 GB) at 32K, both RAG models on the GPU | 11.6 + 2.8 = 14.4 | Yes, with some loss of quality |

The change touches several files, so make it as a feature (Chapter 8) and deploy it (Chapter 10):

- In `stack/inference/llama-swap/config.yaml`, for each RAG model you move, replace
  `--device none` with `-ngl 99` and remove its `CUDA_VISIBLE_DEVICES=-1` entry, which hides the
  GPU from it. Set `coder` to `-c 32768`.
- Lower every declared context to 32,768 tokens: LiteLLM's `max_input_tokens`, OpenCode's
  `limit.context`, Claude Code's `CLAUDE_CODE_MAX_CONTEXT_TOKENS` and Qwen Code's
  `contextWindowSize`.

!!! note
    At 32K, coding agents compact their context constantly; Ollama's documentation advises at
    least 64,000 tokens for coding agents. Use this profile when RAG chat in Open WebUI matters
    more than agent work.

## Models to avoid on two memory channels

The w5-3435X has eight DDR5-4800 channels; the server populates two. Peak bandwidth is the number of
channels times 8 bytes per transfer times 4,800 MT/s:

```
2 channels x 8 bytes x 4,800 MT/s =  76.8 GB/s   (today)
4 channels x 8 bytes x 4,800 MT/s = 153.6 GB/s   (after the upgrade below)
```

llama.cpp's CPU expert kernels reach an estimated 40 to 50 GB/s of that on two channels, 55 to
65 % of peak. For a mixture-of-experts model whose experts partly live in RAM, the time per
generated token is roughly:

```
t_token = t_gpu + (expert bytes read from RAM per token) / (achieved RAM bandwidth)
                + about 0.1 ms per layer whose experts are in RAM
```

The RAM term alone caps generation speed, before any GPU time is added.

Table: RAM-bound generation on two channels

| Model and placement | Experts in RAM | Read from RAM per token | RAM time per token at 40 to 50 GB/s | Decode, tokens/s (est.) |
|---|---|---|---|---|
| Qwen3.8-27B, all in VRAM (default) | none | none | none | 40 to 45 |
| Qwen3.6-35B-A3B Q4, 16 layers in RAM (fast) | about 8 GB | about 0.25 GB | 5 to 6 ms | 65 to 80 |
| Qwen3-Coder-Next IQ4_XS | about 31 GB | about 0.6 GB | 12 to 15 ms | 30 to 38 |
| gpt-oss-120b MXFP4 | about 54 GB | about 1.7 GB | 34 to 43 ms | 12 to 20 |
| GLM-4.5-Air UD-IQ3_XXS | about 40 GB | about 2 GB | 40 to 50 ms | 10 to 14 |

For contrast, the default model reads its 11.2 GB of weights per token from GDDR6X at 716.8 GB/s,
about 16 ms, faster than any large mixture-of-experts model reads its experts from two channels.

Capacity limits the choice too. Of the 62.3 GiB usable, the ZFS ARC cap (12 GiB), TrueNAS, the
prompt cache and the other apps leave about 40 GB for model weights.

Do not run these on this server:

- **gpt-oss-120b, GLM-4.5-Air, Qwen3.5-122B-A10B, Mistral-Small-4-119B.** They do not fit next to
  TrueNAS, or they generate at about 10 to 20 tokens/s.
- **Qwen3-Coder-Next.** It needs about 31 GB of RAM and is no better than the default model.
- **Qwen3.8-Flash-Next.** It fits only with the ARC capped hard and part of the file paged from
  NVMe, which is fragile on ZFS. Keep it for after the memory upgrade.
- **A KV cache below q8_0.** llama.cpp's documentation warns that `-ctk q4_0` can substantially
  degrade tool calling.
- **Ollama's default tags** `qwen3.8:27b` (18 GB) and `qwen3.6:35b` (23 GB). They spill to the
  CPU on a 16 GB card.
- **vLLM or SGLang for the agent model.** The smallest 4-bit builds of these models are 21 to
  30 GB.

!!! note
    The CPU's AMX units do not speed up expert offload in llama.cpp: its AMX kernels handle plain
    matrix multiplication, not the expert operation, and generating one token is bound by memory
    bandwidth. AMX and AVX-512 help the CPU-only RAG models.

## Memory upgrade to four channels

### Effect of four memory channels

Adding two RDIMMs matched to the installed pair doubles both capacity and peak bandwidth. That is
the upgrade that most widens the choice of models.

Table: Memory configurations

| Configuration | Capacity and peak bandwidth | What changes |
|---|---|---|
| 2 x 32 GB (today) | 64 GB, 76.8 GB/s | The profiles above |
| 4 x 32 GB (add two) | 128 GB, 153.6 GB/s | Qwen3.8-Flash-Next UD-IQ4_XS (93.7 GB) fits with its n-gram table in RAM: 25 to 35 tokens/s (est.). gpt-oss-120b: 25 to 32 (est.). The fast profile gains about 5 to 10 %, because it is GPU-bound |
| 8 x 32 GB | 256 GB, 307.2 GB/s | Flash-Next at Q4 or Q5 and gpt-oss-120b at 35 to 45 (est.); gains flatten, as GPU time dominates and 16 cores may not saturate eight channels |
| 8 x 16 GB (replace the pair) | 128 GB, 307.2 GB/s | The capacity of 4 x 32 GB with the bandwidth of eight channels |

After the upgrade, the research recommends two models: Qwen3.8-27B in VRAM for fast turns, and
Qwen3.8-Flash-Next with its experts in RAM for hard tasks. Flash-Next scores 29 on the Artificial
Analysis Intelligence Index, against 20 for the default model. Before adopting it, note:

- Its licence is the Qwen Community License 1.0: internal use is allowed; a "Model as a Service"
  or "AI Work Assistant" business needs a separate licence.
- Its n-gram embedding table belongs in RAM, or memory-mapped from NVMe, never on the GPU. Forcing
  it onto the GPU dropped generation from 108.5 to 1.95 tokens/s in a published run.
- Load offload models with `--load-mode none` so the experts sit in anonymous memory, and keep the
  ARC capped so it does not compete.
- A new model is a change to `stack/` (a llama-swap entry, a LiteLLM name, the client
  declarations). Plan it as a feature (Chapter 8).

### Install two more memory modules

#### Prerequisites

- Two DDR5-4800 RDIMMs of 32 GB, matched to the installed pair: the same size, speed and rank,
  and the same part number where possible. Mixing sizes or populating channels unevenly is
  assumed to unbalance interleaving.
- The motherboard manual's population order for four DIMMs, one per channel.
- A maintenance window: the server and every app on it stop.

#### About this task

This task records the memory layout and a baseline, installs the modules, and confirms that the
server sees four modules at full speed.

#### Steps

1. In **System > Shell** on TrueNAS, record the installed modules.

        sudo dmidecode -t memory | grep -E "^\s+(Size|Locator|Speed|Configured Memory Speed|Part Number):"

    Two slots show `Size: 32 GB`. Note their locators, part numbers and configured speed, and
    check in the manual that the two locators belong to different channels; two modules on one
    channel would halve today's bandwidth.

2. Stop the `ai-inference` app on the **Apps** screen, then record a baseline for the fast profile.

        sudo docker run --rm --gpus all -v /mnt/tank/ai/models:/models:ro \
          ghcr.io/ggml-org/llama.cpp:full-cuda-b12407 --bench \
          -m /models/gguf/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf \
          -ngl 99 -fa on -ctk q8_0 -ctv q8_0 -ncmoe 14,16,18,20 -t 8,16 \
          -p 2048 -n 128 -r 3 -o md

    The output is a table of prompt (`pp2048`) and generation (`tg128`) rates for each setting.
    Save it.

3. Shut the server down from the TrueNAS web UI and disconnect power.

    !!! caution
        Handle the modules with ESD protection and install them only in the slots the manual
        names for four DIMMs. A wrongly seated module can damage the board.

4. Install the two modules in the slots the manual gives for one DIMM per channel, then power the
   server on.

5. Confirm the new layout.

        sudo dmidecode -t memory | grep -E "^\s+(Size|Locator|Speed|Configured Memory Speed|Part Number):"

    Four slots show `Size: 32 GB` and `Configured Memory Speed: 4800 MT/s`. A lower configured
    speed means the population does not match the manual.

6. Confirm the capacity.

        free -g

    The `total` in the `Mem:` row is about twice the value before the upgrade.

7. Repeat the benchmark of step 2, then start the `ai-inference` app.

    The fast profile gains about 5 to 10 % (est.). The large gains appear only with models whose
    experts live mostly in RAM.

#### Results

The server has 128 GB in four channels, with about twice the bandwidth for any model that reads
weights from system RAM.

#### Next steps

- Revisit the ZFS ARC cap set in Chapter 3; the cap was sized for 64 GB.
- Plan any new model as a feature (Chapter 8) and benchmark it (Chapter 9).

## Alternative coding agents

OpenCode is the primary harness because it has the smallest prompt among the full-featured agents
and covers nearly every Claude Code feature. The others in the table each fit a narrower case.

Table: Coding agents for the local stack

| Harness | Version checked | First request, tokens | API it needs | Use it when |
|---|---|---|---|---|
| OpenCode | 2.3.0 | 5,340 | Chat Completions | Default for all work |
| Qwen Code | 0.27.4 | 9,695 | Chat Completions | Claude-format hook scripts must run unchanged, or an OS sandbox is wanted |
| Claude Code via LiteLLM | 2.1.325 | 11,375 (1,200 with `--bare`) | Anthropic Messages | An existing `.claude/` setup must run unchanged |
| Codex CLI | 0.169.0 | 9,427 | Responses only | Only after testing its requests against the gateway |
| Pi | 1.5.2 | 1,322 | Chat Completions | A very weak model, or quick single tasks |

The token counts are measured first requests in headless mode, with no memory file and no MCP
servers. Interactive sessions can declare more tools.

### Qwen Code as the secondary harness

Qwen Code is the closest open clone of Claude Code. Its hooks use Claude Code's JSON protocol and
accept Claude tool names, its subagent files match Claude Code's format, and it has a
bubblewrap or Landlock sandbox for shell commands. It costs almost twice OpenCode's prompt and sends
usage statistics until you turn them off.

#### Prerequisites

- Node.js 22 or later on c4dev.
- `LOCAL_LLM_KEY` from `~/.config/local-agent-stack/client.env` (Chapter 7).

#### Steps

1. Install Qwen Code. Prefer npm to the vendor's one-line installer, which downloads from an
   Alibaba OSS bucket.

        npm install -g @qwen-code/qwen-code@0.27.4

2. Write `~/.qwen/settings.json`. Use the context values declared in
   `clients/opencode/opencode.jsonc`.

        {
          "modelProviders": {
            "openai": [
              { "id": "local-coder", "name": "Local coder", "envKey": "LOCAL_LLM_KEY",
                "baseUrl": "https://llm.lab.example.com/v1",
                "generationConfig": { "contextWindowSize": 65536 } },
              { "id": "local-fast", "name": "Local fast", "envKey": "LOCAL_LLM_KEY",
                "baseUrl": "https://llm.lab.example.com/v1",
                "generationConfig": { "contextWindowSize": 65536 } }
            ]
          },
          "security": { "auth": { "selectedType": "openai" } },
          "model": { "name": "local-coder", "catalogRefresh": false },
          "fastModel": "local-fast",
          "privacy": { "usageStatisticsEnabled": false },
          "context": { "fileName": ["AGENTS.md", "QWEN.md"] },
          "tools": { "approvalMode": "default", "webSearch": { "enabled": false } }
        }

    `approvalMode` is `default` (ask) because the out-of-the-box mode, `auto`, lets an LLM
    classifier approve actions, and with a local model that classifier is the weakest link.

3. Load the key into the shell.

        set -a; . ~/.config/local-agent-stack/client.env; set +a

4. Run a headless test.

        qwen -p "Reply with the single word OK."

    The answer is `OK`.

5. Optional: confine shell commands to the workspace. Confirm that `/usr/bin/bwrap` exists, then
   add this key inside `"tools"`:

        "executionSandbox": { "backend": "bwrap", "filesystem": "workspace-write", "network": "open" }

    `"network": "closed"` would also block `gh` and `npm` inside tool commands.

6. In an interactive `qwen` session, run `/context detail` on the first turn to read the actual
   prompt cost.

#### Results

Qwen Code runs against the gateway with telemetry off. Project hooks go in `.qwen/settings.json`
and run only after you approve them; subagents go in `.qwen/agents/<name>.md`. To add the MCP hub's
servers, follow the Qwen Code MCP documentation (Appendix E).

### Claude Code through the LiteLLM gateway

Chapter 7 configures Claude Code against `llm.lab.example.com` with the names `local-opus`,
`local-sonnet` and `local-haiku`. Use it when an existing `.claude/` setup (hooks, commands,
skills, subagents) must run unchanged, or when you want Claude Code's own interface. Keep it a
fallback:

- Anthropic does not support routing Claude Code to non-Claude models through a gateway. New
  releases can add request fields the gateway rejects: pin the version and test again after every
  upgrade.
- It assumes a 1M-token window for unknown model names unless `CLAUDE_CODE_MAX_CONTEXT_TOKENS` is
  set, and its prompt is the largest of the harnesses measured.
- WebSearch is an Anthropic server tool; use the SearXNG MCP server instead. Remote Control is
  disabled behind a non-Anthropic base URL, and `/cost` is meaningless (read LiteLLM's spend logs).
- All three model names are the same model on this server, so `opusplan` gains nothing.

### Codex CLI against the gateway

Codex CLI has a strong sandbox and Claude-compatible hooks, but it speaks only the Responses API
(`wire_api = "responses"` is the only value). LiteLLM serves `/v1/responses`, but Codex also sends
OpenAI-only tool types, a `namespace` tool group and a hosted `web_search` tool, that the gateway
must translate or drop for a local model. That translation is untested. Codex also truncates
`AGENTS.md` at 32 KiB (`project_doc_max_bytes`). If you test it, turn off its telemetry and update
checks with `[analytics] enabled = false`, `check_for_update_on_startup = false` and
`feedback.enabled = false`.

### Pi for very weak models

Pi is a minimal agent: four tools (`read`, `bash`, `edit`, `write`), MCP built in, and a first
request of 1,322 tokens. It has no subagents, no plan mode and no permission system, so run it only
in a disposable checkout or a container. Use it for quick single tasks, or when a model is too weak
for a larger prompt; run it headless with `pi -p`.

### Harnesses evaluated and not adopted

Goose (1.59.1, with a tool shim for models that emit tool calls as text) and Crush (source-available
under FSL-1.1-MIT) are workable alternatives. Kilo Code CLI is an OpenCode fork, relevant only for
its VS Code and JetBrains extensions. Do not adopt Roo Code (repository archived), Continue
(acquired by Cursor, no release since June 2026), OpenHands CLI (no longer maintained), Plandex
(cloud wound down, last release July 2025) or Aider (frozen at 0.86.2, without an agent loop, MCP
or subagents).
