# ai-inference

The model-serving app of the stack: llama.cpp behind llama-swap on the GPU, and the LiteLLM gateway
that every client uses. The design is `docs/stack-design.md` (sections 1, 2, 4, 5 and 6); the
reasons are in `docs/research/b-inference.md` and `docs/research/a-models.md`.

## Files

| File | What it is |
|---|---|
| `compose.yaml` | Services `llama-swap` (GPU), `litellm` and `litellm-db` on the external network `ai-net`, no published ports, images pinned by tag and digest |
| `llama-swap/config.yaml` | Model ids `coder`, `coder-fast` (alias: thinking off), `coder-moe`, `embed`, `rerank`; swap group `llm`, persistent CPU-only group `rag`; `coder` and `coder-moe` read images through a vision projector on the CPU |
| `litellm/config.yaml` | Client-facing names `local-coder`, `local-fast`, `local-coder-moe`, `local-opus`, `local-sonnet`, `local-haiku`, `local-embed`, `local-rerank`; the six chat names declare `supports_vision`; master key and database from the environment, spend logs on, no cloud providers |
| `models.tsv`, `models.sha256` | The model files to download (id, Hugging Face repository, pinned revision, file) and their SHA-256 checksums |
| `inference.env.example` | Every variable, with placeholders; the real file is `/mnt/tank/ai/secrets/inference.env` |

`tools/bench.sh` benchmarks the same llama.cpp build on the server (`tools/bench.sh --help`).

## How TrueNAS runs it

Create the custom app `ai-inference` with **Apps** > **Discover Apps** > **Custom App** >
**Install via YAML**, with exactly this YAML (`docs/stack-design.md` section 4):

```yaml
include:
  - path: /mnt/tank/ai/stacks/local-agent-stack/stack/inference/compose.yaml
    env_file: /mnt/tank/ai/secrets/inference.env
services: {}
```

The `env_file` supplies the variables that `compose.yaml` interpolates; relative paths in
`compose.yaml` resolve against `stack/inference/`. Before installing, the host needs the network
`ai-net`, the datasets `tank/ai/models` and `tank/ai/appdata/litellm-db`, and these files under
`/mnt/tank/ai/models/gguf/`:

| File | `models.tsv` id | Hugging Face repository | Size in bytes |
|---|---|---|---|
| `Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf` | `coder` | `ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF` | 12120016960 (12.12 GB) |
| `mmproj-Qwen3.8-27B-Q8_0.gguf` | `coder-mmproj` | `ggml-org/Qwen3.8-27B-GGUF` | 629247008 (0.63 GB) |
| `Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf` | `coder-moe` | `unsloth/Qwen3.6-35B-A3B-GGUF` | 22360456160 (22.36 GB) |
| `mmproj-Qwen3.6-35B-A3B-Q8_0.gguf` | `coder-moe-mmproj` | `ggml-org/Qwen3.6-35B-A3B-GGUF` | 614194304 (0.61 GB) |
| `Qwen3-Embedding-0.6B-Q8_0.gguf` | `embed` | `Qwen/Qwen3-Embedding-0.6B-GGUF` | 639150592 (0.64 GB) |
| `qwen3-reranker-0.6b-q8_0.gguf` | `rerank` | `ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF` | 639153184 (0.64 GB) |

The six files are 37002218208 bytes (37.00 GB, 34.5 GiB); the two `mmproj-*` files, the vision
projectors (see "Images" below), add 1.24 GB (1.16 GiB) to the four model files. `llama-server`
refuses to start a model whose `--mmproj` file is missing ("failed to load multimodal model"), so
on an existing install download them before the redeploy that brings in this configuration, with
the guide's `dl` function (it reads `models.tsv` by id):

```sh
dl coder-mmproj
dl coder-moe-mmproj
sudo docker wait dl-coder-mmproj dl-coder-moe-mmproj   # two lines of 0
sudo docker rm dl-coder-mmproj dl-coder-moe-mmproj
cd /mnt/tank/ai/models/gguf && sha256sum -c /mnt/tank/ai/stacks/local-agent-stack/stack/inference/models.sha256
```

The last command prints six lines ending in `: OK`.

After a change in this directory: `git pull` in the clone, then
`sudo midclt call -j app.redeploy ai-inference` (every container of the app restarts).

## Checks

On the workstation, before a commit:

```sh
cd stack/inference && docker compose --env-file inference.env.example -f compose.yaml config -q
```

On the TrueNAS host, after the app is running:

```sh
sudo docker exec llama-swap curl -fsS http://127.0.0.1:8080/health
sudo docker exec llama-swap sh -c 'curl -fsS -H "Authorization: Bearer $LLAMA_SWAP_API_KEY" http://127.0.0.1:8080/running'
sudo docker exec litellm python3 -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:4000/health/readiness').read().decode())"
```

The first prints `OK`. The second lists `coder`, `embed` and `rerank` with state `ready` once
they have loaded (`coder` takes a minute or more after a reboot). The third reports
`"status":"healthy"` and `"db":"connected"`.

To check that `coder` loaded its vision projector:

```sh
sudo docker exec llama-swap sh -c 'curl -fsS -H "Authorization: Bearer $LLAMA_SWAP_API_KEY" http://127.0.0.1:8080/upstream/coder/props' | grep -o '"vision":[a-z]*'
sudo docker logs llama-swap 2>&1 | grep -E 'loaded multimodal model|compute buffer size' | tail -n 4
```

The first prints `"vision":true` (llama-server's `/props` field `modalities.vision`); it loads
`coder` if it is not loaded. The second shows the line `loaded multimodal model,
'/models/gguf/mmproj-Qwen3.8-27B-Q8_0.gguf'` and the projector's compute buffer, in MiB, for the
RAM figure below. The log also warns at load that "Qwen-VL models require at minimum 1024 image
tokens to function correctly on grounding tasks" (`tools/mtmd/mtmd-model.cpp`, printed because
the projector file sets no minimum image size); grounding (bounding boxes) is not used here, and
`--image-min-tokens 1024` would upscale every small image at a CPU cost, so the warning is
expected. End to end, from the workstation: `python3 tools/eval.py run --suite vision`
sends `evals/images/maple-74.png` through LiteLLM and passes when the model reads back "MAPLE 74".

Use `/health/liveliness` and `/health/readiness` for probes. `GET /health` on LiteLLM sends a
real request to every model, which loads `coder-moe` and swaps `coder` out of the GPU; to check one
model, use `/health?model=local-coder`.

## Memory

| Model | VRAM | Host RAM |
|---|---|---|
| `coder` (64K, q8_0 KV, MTP) | about 14-15 GiB (estimate) | vision projector about 1-1.5 GiB (estimate), prompt cache up to 6 GiB |
| `coder-moe` (64K, 16 expert layers in RAM) | about 15.7 GiB (measured elsewhere) | about 8 GB of experts, vision projector about 1-1.5 GiB (estimate), prompt cache up to 6 GiB |
| `embed`, `rerank` (CPU only) | none | about 1.3 GiB each |

Only one of `coder` and `coder-moe` is loaded at a time, so the projectors add about 1-1.5 GiB to
the stack's RAM, never both: about 0.6 GiB of Q8_0 weights, read into memory rather than mapped
(`tools/mtmd/mtmd-model.cpp`), plus a compute buffer that is reserved at load for an image of
46x46 = 2,116 tokens (`set_warmup_n_tokens`; the size is in the log as "compute buffer size") and
grows when a larger image (up to 4096 tokens) is encoded. Against the RAM budget of
`docs/research/b-inference.md` ("System RAM budget", 62.3 GiB usable) the free RAM drops from
about 26 to about 25 GiB with `coder` and from about 17-20 to about 16-19 GiB with `coder-moe`. The `llama-swap` container is capped at 32 GiB of RAM,
`litellm` at 6 GiB and `litellm-db` at 2 GiB; with the projector, the container's peak with
`coder-moe` is about 18-22 GiB (estimate: experts, prompt cache and host buffers, projector,
`embed` and `rerank`), still under the cap.

## Images

`coder` (so also `local-coder`, `local-fast`, `local-opus`, `local-sonnet`, `local-haiku`) and
`coder-moe` (`local-coder-moe`) accept images: OpenAI `image_url` parts on `/v1/chat/completions`
and Anthropic `image` blocks on `/v1/messages`, also inside tool results. Each model loads its own
multimodal projector with `--mmproj /models/gguf/<file> --no-mmproj-offload`, which keeps the
projector in system RAM and runs it on the CPU (both flags, and the default of offloading to the
GPU, are in `tools/server/README.md` and `common/arg.cpp` at b12407). It costs no VRAM, so the
64K context stays.

- **Projector files.** The ggml-org Q8_0 conversions, pinned by revision with their SHA-256 and
  size from the Hugging Face API (`models.tsv`, `models.sha256`; a-models §7 names the coder
  one). Q8_0 is the smallest file (0.63 GB against 0.93 GB for BF16 or F16). On this CPU,
  llama.cpp's tinyBLAS kernels run Q8_0 matrix products with AVX-512 VNNI int8 dot products and
  BF16 with AVX-512 BF16 dot products, while F16 (Unsloth's `mmproj-F16.gguf`) goes through F32
  arithmetic (`ggml/src/ggml-cpu/llamafile/sgemm.cpp`); which of Q8_0 and BF16 is faster here is
  not measured. The projector's own buffers stay on the plain CPU backend (no AMX repack).
  The file headers, read at the pinned revisions, report `clip.projector_type` `qwen3vl_merger`,
  patch size 16, spatial merge 2 and projection sizes 5120 and 2048, equal to the
  `embedding_length` of `coder`'s and `coder-moe`'s model files; llama.cpp refuses a projector
  whose size differs from the model's (`tools/mtmd/mtmd.cpp`), so each model needs its own file.
  `ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF` ships `mmproj-Qwen3.8-27B-BF16.gguf`, which its model card
  says was converted from the base checkpoint and verified with its GSQ-RCO quantizations; its
  `clip.*` metadata is identical to ggml-org's BF16 conversion, of which the Q8_0 file is the
  quantized form. That the Q8_0 projector reads as well with the GSQ-RCO model is UNVERIFIED until
  `format-011` passes; the BF16 file (0.93 GB) is the fallback.
- **Speed.** About 11 s per image on the CPU (a-models §7, measured on another machine; an
  estimate here, not measured on this server), against about 0.3 s on a GPU. The time grows with
  the image: one image token covers 32x32 pixels (patch 16, merge 2), at most 4096 tokens per image
  by default (`--image-max-tokens N` caps it, at some loss of detail), so a 1920x1080 screenshot is
  about 2,000 tokens of the 64K context. The projector uses the process's `-t` threads
  (`tools/server/server-context.cpp`): `coder` runs `-t 16` for that reason (it was 4; decode runs
  on the GPU and needs few threads). The image's llama.cpp is built with OpenMP, whose idle
  threads busy-wait 300,000 spins before sleeping (GCC libgomp, `GOMP_SPINCOUNT`), so the 16
  threads also use more CPU time while the model generates text. UNVERIFIED: that 16 threads cost
  no decode speed and how much CPU they take from the RAG models and docling; check with
  `tools/bench.sh --mode server` and `top` during a long answer, and go back to `-t 4` (images
  about four times slower, estimate) or add `OMP_WAIT_POLICY=PASSIVE` to `coder`'s `env` if it
  matters. `coder-moe` keeps `-t 8` for its experts' decode speed, so an image takes about twice
  as long there (estimate).
- **Clients.** OpenCode declares image input on `local-coder`, `local-fast` and
  `local-coder-moe` (`clients/opencode/opencode.jsonc`): images attached with `@` in the TUI (or
  Attach file, paste or drag in the desktop and web clients) and images its read tool opens are
  scaled to fit 2000x2000 pixels and 5 MiB, then sent. Claude Code needs no setting
  (`clients/claude-code/settings.json` is unchanged): its docs ("Work with images") take an image
  dragged into its window, pasted with `Ctrl+V` or named by path, and it sends the image to
  `/v1/messages` as an image block (assumed: Claude Code's source is not public; nothing in its
  documented settings gates images by model). Open WebUI offers image upload
  for every model whose capability **Vision** is on, the default (`stack/web/README.md`,
  "Images and files in chats").
- **Other effects.** Loading a projector turns off context shift and `--cache-reuse` (neither is
  used here); the projector's attention follows `-fa on`; MTP speculative decoding is set up the
  same way with a projector (b12407). A swap back to `coder` reads 0.63 GB more from the dataset.
  PNG, JPEG, GIF and BMP are decoded by stb_image, WebP through ffmpeg (in the image). PDFs are not
  images: llama-server rejects a `file` part on `/v1/chat/completions`
  (`unsupported content[].type`) and drops an Anthropic `document` block on `/v1/messages` without
  an error (`tools/server/server-chat.cpp` converts only text, thinking, image, tool_use and
  tool_result blocks), so a PDF that Claude Code sends never reaches the model.
- **Without a projector** (before this change, or with the `--mmproj` line removed) llama-server
  answers any image with `image input is not supported - hint: if this is unexpected, you may
  need to provide the mmproj`.
- **LiteLLM** forwards image parts and blocks unchanged on both routes (checked in the source at
  v1.108.8; details in `litellm/config.yaml`). `model_info.supports_vision: true` on the six chat
  names is reported by `/model/info` and `/model_group/info`; LiteLLM does not gate images on it
  for these providers. No request size limit applies in LiteLLM (unset) or llama-swap (250 MB).

UNVERIFIED on this server: the projector's RAM and speed, images together with MTP drafting, and
whether Qwen3.8-27B reads the eval image back exactly (`format-011` stays optional until it has).
