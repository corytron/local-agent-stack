title: Deploying the inference app

# Deploying the inference app

This chapter installs `ai-inference`, the app that serves the models. Its `llama-swap` container
runs llama.cpp's `llama-server` for every model, on the GPU for the agent models and on the CPU for
the embedding and reranking models. Its `litellm` container is the gateway that every client uses,
with one key per client and a usage log, and `litellm-db` is the PostgreSQL database behind it. You
download the model files, review the configuration, install the app, verify that the models load,
create the keys of the workstations, measure the performance, and learn how the fast profile is
used.

Run the TrueNAS commands in **System** > **Shell**, or in an SSH session from the workstation as
`truenas_admin`, as in Chapter 3. The app publishes no port. Until the edge app is installed in
Chapter 5, every check in this chapter runs on the TrueNAS server, inside the containers, over the
`ai-net` network.

Table: Values used in this chapter

| Value | Meaning |
|---|---|
| `192.0.2.10` | LAN address of the TrueNAS server |
| `lab.example.com` | Your domain (`LAB_DOMAIN`) |
| `<release-tag>` | The release of this guide that the clone is checked out at, for example `v1.0` |
| `sk-local-...` | A LiteLLM key; the real values are printed during the tasks |

## Download the model files

The stack serves six GGUF files, 37.00 GB (34.5 GiB) in total, from public Hugging Face
repositories: the four model files and the vision projectors of the two chat models, which let
`coder` and `coder-moe` read images. No Hugging Face account is needed. The files go to
`/mnt/tank/ai/models/gguf`, on the `tank/ai/models` dataset that Chapter 3 created with a 1M record
size and `primarycache=metadata`.

The release lists the files in `stack/inference/models.tsv`: for each file an id, the Hugging Face
repository, a fixed revision (commit) of that repository, checked on 15 November 2026, and the file
name, separated by tabs. The id of a model file is its llama-swap id; the id of a projector is the
model's id followed by `-mmproj`. Because each download names its revision, the file sizes below
and the SHA-256 checksums in `stack/inference/models.sha256` stay valid even if a repository
changes later. The download commands in this topic read the file from the clone on TrueNAS:

{{ include stack/inference/models.tsv }}

Table: Model files to download

| File | Size in bytes | Id in models.tsv |
|---|---|---|
| `Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf` | 12120016960 (12.12 GB) | `coder` |
| `mmproj-Qwen3.8-27B-Q8_0.gguf` | 629247008 (0.63 GB) | `coder-mmproj` |
| `Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf` | 22360456160 (22.36 GB) | `coder-moe` |
| `mmproj-Qwen3.6-35B-A3B-Q8_0.gguf` | 614194304 (0.61 GB) | `coder-moe-mmproj` |
| `Qwen3-Embedding-0.6B-Q8_0.gguf` | 639150592 (0.64 GB) | `embed` |
| `qwen3-reranker-0.6b-q8_0.gguf` | 639153184 (0.64 GB) | `rerank` |

The two `mmproj-*` files are the multimodal projectors, the part of a vision-language model that
turns an image into tokens. Each chat model needs its own: llama.cpp refuses a projector whose
output size differs from the model's, and the two models differ (5,120 for `coder`, 2,048 for
`coder-moe`). They are the Q8_0 conversions published by ggml-org, together 1.24 GB (1.16 GiB).

!!! note
    On an installation of an earlier release, which has only the four model files, download the
    two projectors before the release's configuration is redeployed:
    [Add the vision projectors to an existing installation](#add-the-vision-projectors-to-an-existing-installation).
    `llama-server` does not start a model whose projector file is missing.

### Check the free space for the models

#### Prerequisites

- The dataset `tank/ai/models` exists with its properties set
  ([Create the parent and models datasets](#create-the-parent-and-models-datasets)).

#### Steps

1. Create the directory for the model files:

        sudo install -d /mnt/tank/ai/models/gguf

2. Display the free space of the models dataset:

        df -h /mnt/tank/ai/models

    The **Avail** column shows at least `35G`. The six files need 34.5 GiB.

#### Results

The directory `/mnt/tank/ai/models/gguf` exists, and the dataset has room for the six files. If
**Avail** is lower, free space in the pool before you start the downloads.

### Start the model downloads

#### Prerequisites

- The release is cloned in `/mnt/tank/ai/stacks/local-agent-stack`
  ([Clone the release tag](#clone-the-release-tag)).

#### About this task

Each file is downloaded by `curl` in a throwaway container of the llama-swap image, the same image
that the `ai-inference` app runs. Nothing is installed on TrueNAS, the first download pulls the
image that the app needs anyway, and the downloads continue in the background if you close the
shell. The six containers, `dl-coder`, `dl-coder-mmproj`, `dl-coder-moe`, `dl-coder-moe-mmproj`,
`dl-embed` and `dl-rerank`, run at the same time; each one downloads one file and stops. `-C -`
makes `curl` continue a partial file instead of starting again.

The commands take the image from `stack/inference/compose.yaml` and the repository, revision and
file name of each model from `stack/inference/models.tsv`, both in the clone, so they download
exactly what the release names.

#### Steps

1. Refresh the `sudo` credentials, so that the commands with pipes below do not prompt:

        sudo -v

2. Store the image and the path of the model list in shell variables:

        IMG=$(sed -n 's/^ *image: *\(ghcr\.io\/mostlygeek\/llama-swap:.*\)$/\1/p' \
          /mnt/tank/ai/stacks/local-agent-stack/stack/inference/compose.yaml)
        MODELS=/mnt/tank/ai/stacks/local-agent-stack/stack/inference/models.tsv
        echo "$IMG"

    The output is the image of the `llama-swap` container, pinned by tag and digest:
    `ghcr.io/mostlygeek/llama-swap:v273-cuda-b12407@sha256:` followed by 64 hexadecimal digits.

3. Define the shell function `dl`, which starts the download of one model:

        dl() {
          awk -F '\t' -v id="$1" '$1 == id { print $2, $3, $4 }' "$MODELS" |
            while read -r REPO REV FILE; do
              sudo docker run -d --name "dl-$1" -e NVIDIA_VISIBLE_DEVICES=void \
                -v /mnt/tank/ai/models/gguf:/gguf --entrypoint curl "$IMG" \
                -fsSL --retry 5 -C - -o "/gguf/$FILE" \
                "https://huggingface.co/$REPO/resolve/$REV/$FILE" < /dev/null
            done
        }

    `dl <id>` reads the line of `<id>` in `models.tsv` and starts the container `dl-<id>`, which
    downloads that file from that revision. The variables and the function last until the shell
    closes. In a new shell, run steps 1 to 3 again.

4. Start the six downloads:

        dl coder
        dl coder-mmproj
        dl coder-moe
        dl coder-moe-mmproj
        dl embed
        dl rerank

    Docker pulls the image at the first command, then each command prints the ID of a new
    container. A command that prints nothing names an id that is not in `models.tsv`.

5. Follow the progress. Run the command again from time to time; the file sizes grow:

        ls -l /mnt/tank/ai/models/gguf

6. Wait until every download has stopped:

        sudo docker wait dl-coder dl-coder-mmproj dl-coder-moe dl-coder-moe-mmproj dl-embed dl-rerank

    The command returns when the last container stops, and prints one exit code per container.
    Six lines of `0` mean that every download completed.

7. If a line is not `0`, display the error of that container, for example `dl-coder-moe`:

        sudo docker logs dl-coder-moe

    Remove the container and start its download again. `curl` continues from where the file
    stopped:

        sudo docker rm dl-coder-moe
        dl coder-moe

8. Remove the download containers:

        sudo docker rm dl-coder dl-coder-mmproj dl-coder-moe dl-coder-moe-mmproj dl-embed dl-rerank

#### Results

The four model files and the two projectors are in `/mnt/tank/ai/models/gguf`, and the llama-swap
image is in the local image store.

### Verify the model files

#### Steps

1. List the files with their sizes in bytes:

        ls -l /mnt/tank/ai/models/gguf

    The six files have exactly the sizes in the table above.

2. Change to the model directory:

        cd /mnt/tank/ai/models/gguf

3. Compare the SHA-256 checksum of each file with the value in `stack/inference/models.sha256`,
   the checksum that Hugging Face publishes for that file at its revision. The file in the clone
   holds these lines:

    {{ include stack/inference/models.sha256 }}

    Check the six files against it. Reading 37.0 GB takes a few minutes:

        sha256sum -c /mnt/tank/ai/stacks/local-agent-stack/stack/inference/models.sha256

    The output has six lines, each a file name followed by `: OK`.

4. If a line reads `FAILED`, delete that file, for example
   `sudo rm /mnt/tank/ai/models/gguf/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf`, and download it again with
   the function of [Start the model downloads](#start-the-model-downloads): `dl coder-moe`, then
   `sudo docker wait dl-coder-moe` and `sudo docker rm dl-coder-moe`. Repeat this task.

5. Return to your home directory:

        cd

#### Results

The model files are complete and match the published checksums. The `llama-swap` container mounts
`/mnt/tank/ai/models` read-only at `/models`, so it finds them at `/models/gguf/`.

!!! note
    The model files are not backed up (Appendix A). After a loss of the `tank/ai/models` dataset,
    repeat this topic to restore them.

### Add the vision projectors to an existing installation

#### Prerequisites

- `ai-inference` was installed from an earlier release, and `/mnt/tank/ai/models/gguf` holds its
  four model files.
- The clone on TrueNAS is at the new release tag, and the release is not yet applied: Chapter 10,
  after [Update the clones](#update-the-clones) and before [Apply the release](#apply-the-release).

#### About this task

From this release on, `coder` and `coder-moe` start with a vision projector (`--mmproj`), and
`llama-server` refuses to start a model whose projector file is missing: the model never becomes
ready, and the `llama-swap` log shows `failed to load multimodal model` followed by the file's path.
Download the two projectors before the redeploy that brings in the new configuration. The model
files of the earlier release stay as they are.

#### Steps

1. Run steps 1 to 3 of [Start the model downloads](#start-the-model-downloads), which define the
   `dl` function with the clone's `models.tsv`.

2. Check the free space:

        df -h /mnt/tank/ai/models

    The **Avail** column shows at least `2G`; the two projectors need 1.16 GiB.

3. Start the two downloads:

        dl coder-mmproj
        dl coder-moe-mmproj

    Each command prints the ID of a new container. A command that prints nothing means that the
    clone is not yet at the new tag.

4. Wait until both downloads have stopped:

        sudo docker wait dl-coder-mmproj dl-coder-moe-mmproj

    The output is two lines of `0`. For a line that is not `0`, follow step 7 of
    [Start the model downloads](#start-the-model-downloads) with that container's name.

5. Remove the download containers:

        sudo docker rm dl-coder-mmproj dl-coder-moe-mmproj

6. Check every model file against the release's checksums:

        cd /mnt/tank/ai/models/gguf && sha256sum -c /mnt/tank/ai/stacks/local-agent-stack/stack/inference/models.sha256
        cd

    The output has six lines, each a file name followed by `: OK`.

#### Results

The six files of the release are in `/mnt/tank/ai/models/gguf`. Continue with the release update;
after the redeploy of `ai-inference`, check the projector with
[Check the vision projector](#check-the-vision-projector).

If `coder` was redeployed before the download and does not load, finish this task, then redeploy
the app as in [Redeploy ai-inference after a change](#redeploy-ai-inference-after-a-change).

## Review the inference configuration

The `ai-inference` app is defined by three files in the clone on TrueNAS:
`stack/inference/compose.yaml` (the containers), `stack/inference/llama-swap/config.yaml` (the
models) and `stack/inference/litellm/config.yaml` (the names that clients use). You do not edit
them; the clone stays at the release tag. This topic explains what they set, so that you can read
the checks and the benchmark results later in this chapter. Appendix E prints every file in full.

### Services of the ai-inference app

Table: Containers of ai-inference

| Container | Image | Role | Limits and health check |
|---|---|---|---|
| `llama-swap` | `ghcr.io/mostlygeek/llama-swap:v273-cuda-b12407` (llama.cpp b12407, CUDA 12.8.1) | Starts a `llama-server` process per model and switches between them; the only container with the GPU | 32 GiB of memory. Health check: llama-swap's `/health`, which needs no key and does not wait for the models |
| `litellm` | `ghcr.io/berriai/litellm:v1.108.8` | The gateway: OpenAI `/v1/...` and Anthropic `/v1/messages`, client keys, usage logs, Prometheus metrics | 6 GiB of memory. Health check: `/health/liveliness`, which makes no model call. Starts after the other two are healthy; allows 120 seconds for its database migrations on the first start |
| `litellm-db` | `postgres:16.13` | LiteLLM's keys, budgets and usage logs, in `tank/ai/appdata/litellm-db` | 2 GiB of memory. Health check: `pg_isready` |

Other properties of the compose file:

- **No published ports.** Other apps reach `llama-swap:8080` and `litellm:4000` by name on
  `ai-net`; browsers and workstations reach them through Caddy (Chapter 5).
- **Pinned images.** Every image is pinned by tag and digest. LiteLLM's PyPI and Docker images were
  compromised twice in 2026 (in March through PyPI, and on 21 October through PyPI and Docker:
  `v1.107.0` and the floating tags), which is why its digest is fixed.
- **GPU access.** Only `llama-swap` gets the GPU: `NVIDIA_VISIBLE_DEVICES: all` and a device
  reservation with `count: all`, which avoids naming the GPU's UUID (a card swap would break it).
  `litellm` and `litellm-db` set `NVIDIA_VISIBLE_DEVICES: void`, because TrueNAS makes `nvidia` the
  default Docker runtime.
- **LiteLLM runs local only.** Models come only from the configuration file
  (`STORE_MODEL_IN_DB: "False"`), the model cost map bundled in the image is used instead of a
  download (`LITELLM_LOCAL_MODEL_COST_MAP`), usage telemetry is off (`LITELLM_TELEMETRY_DISABLED`),
  and production mode (`LITELLM_MODE: PRODUCTION`) stops it from reading a stray `.env` file. It
  runs one worker, because the GPU serves one request at a time.
- **Shutdown and logs.** `llama-swap` gets 30 seconds to stop its `llama-server` processes. Every
  container's log rotates at 10 MB, five files.

The app reads its variables from `/mnt/tank/ai/secrets/inference.env`, which Chapter 3 generated
from this example file in
[Generate the environment files on the workstation](#generate-the-environment-files-on-the-workstation):

{{ include stack/inference/inference.env.example }}

!!! caution
    Never change `LITELLM_SALT_KEY` after the first start of LiteLLM; it encrypts what LiteLLM stores
    in its database. `LITELLM_DB_PASSWORD` is fixed when the database is first created; a new value
    in `inference.env` alone locks LiteLLM out of its database.

### llama-swap global settings

{{ include stack/inference/llama-swap/config.yaml lines=43-80 }}

Table: llama-swap global settings

| Setting | Effect |
|---|---|
| `healthCheckTimeout: 600` | A model may take up to 600 seconds to become ready. Reading a 12 GB file from disk with a cold cache takes longer than the default 120 seconds |
| `logToStdout: "proxy,upstream"` | The container log carries llama-swap's own lines and the output of every `llama-server`, including the CPU backend line and the "Forcing full prompt re-processing" warnings |
| `startPort: 10001` | Each `llama-server` listens on `127.0.0.1`, port 10001 and up, inside the container |
| `sendLoadingState: false` | No "loading" text is injected into the reasoning field while a model loads; Claude Code and OpenCode would take it for model output |
| `globalTTL: 0` | No model is unloaded on a timer; the groups decide (below) |
| `captureBuffer: 0` | No request or response bodies are kept in llama-swap's memory (default 5 MB), for privacy. To see the requests of a failing tool call, raise it for a while: [Capture requests while you debug tool calls](#capture-requests-while-you-debug-tool-calls) |
| `helpagent: disable: true` | The UI's help chat is off; it would load a model of its own choice and swap the GPU model |
| `apiKeys` | Every inference and `/api` route needs `LLAMA_SWAP_API_KEY`, as a Bearer token, a Basic password or an `x-api-key` header. `/health` stays open for the health check |
| `macros` | `server` starts `llama-server` on loopback with Prometheus metrics (`/upstream/<id>/metrics`) and without its own web UI; `gguf` is the model directory |

### The coder model entry

`coder` is the primary agent model, Qwen3.8-27B, entirely on the GPU with a 64K context. Its vision
projector runs on the CPU, so the model reads images without giving up VRAM.

{{ include stack/inference/llama-swap/config.yaml lines=122-156 }}

Table: Flags of the coder model

| Flag | Effect |
|---|---|
| `-ngl 99 -fa on` | All 64 layers on the GPU, flash attention on |
| `-c 65536 -np 1` | One slot with the full 64K context. Concurrent requests queue; an idle slot's prompt moves to the prompt cache in host RAM instead of being computed again |
| `-ctk q8_0 -ctv q8_0` | KV cache at 8 bits. Do not lower it to `q4_0`: llama.cpp warns that it can substantially degrade tool calling |
| `-b 2048 -ub 512` | llama.cpp's default batch sizes, written out; the benchmark in this chapter tries larger `-ub` values against the VRAM |
| `-t 16` | CPU threads of the process. Generation runs on the GPU and needs few of them, but the vision projector encodes each image on the CPU with exactly this many threads, so it gets the 16 physical cores; the hyper-threads stay free for the other apps. The cost: idle threads wait actively for a while before they sleep, so 16 threads take more CPU time than 4 while the model writes an answer. [Choose the CPU threads of coder](#choose-the-cpu-threads-of-coder) measures it |
| `-ot token_embd.weight=CPU` | Keeps the token embeddings, a lookup table of about 0.6 GiB, in system RAM to make room in VRAM |
| `--cache-ram 6144` | Up to 6 GiB of host RAM for the prompt cache |
| `--jinja --reasoning-format deepseek --reasoning-effort medium` | The model's chat template, thinking returned in a separate reasoning field, medium effort |
| `--temp 1.0 --top-p 0.95 --top-k 20 --min-p 0.0` | The model card's sampling for thinking mode; a request may override them |
| `--spec-type draft-mtp --spec-draft-n-max 3` | Speculative decoding with the multi-token prediction (MTP) head inside the `-mtp` file, three draft tokens |
| `--mmproj ${gguf}/mmproj-Qwen3.8-27B-Q8_0.gguf` | Loads the model's vision projector, so the model accepts images |
| `--no-mmproj-offload` | Keeps the projector in system RAM and runs it on the CPU. On the GPU it would take 0.6 to 0.9 GiB of VRAM that the 64K context needs |

The entry sets no `--cache-reuse`: that option works by shifting the KV cache, which the model's
Gated DeltaNet layers cannot do. Loading a projector also turns off context shift and
`--cache-reuse`, neither of which the stack uses. The `filters` block makes `coder-fast` an alias
of `coder`: a request for `coder-fast` is served by the same process, with thinking off and the
model card's non-thinking sampling written into the request. This is the fast and small-model role,
with no second model in VRAM, and it reads images too, because it is the same process.
`presence_penalty` takes effect only on the OpenAI route.

!!! note
    Two properties of this entry are not verified on hardware. First, the VRAM saved by
    `-ot token_embd.weight=CPU` is not measured; the option has no effect if llama.cpp already keeps
    that tensor on the CPU. Second, it is an estimate that the weights, the 64K KV cache and the MTP
    draft context fit in 16 GB together, and it is not verified that llama.cpp b12407 loads the MTP
    head from this file. Check both with
    [Test that the coder model fits](#test-that-the-coder-model-fits) before you rely on the stack.

!!! note
    The vision projector was not run on the reference server for this release. Its system memory
    (about 1 to 1.5 GiB) and its speed (about 11 seconds per image) are estimates, images together
    with MTP speculative decoding and the 64K context are not tested, and it is not verified that
    the Q8_0 projector reads text in images as well with this quantization of the model as with
    the original. [Check the vision projector](#check-the-vision-projector) is the first test on
    your system.

### The coder-moe model entry

`coder-moe` is the fast profile, Qwen3.6-35B-A3B, with the experts of 16 layers in system RAM.

{{ include stack/inference/llama-swap/config.yaml lines=176-191 }}

- `--n-cpu-moe 16` keeps the experts of the first 16 layers, about 8 GB, in system RAM. With 14,
  the measured run overflowed the VRAM.
- `-lm none` loads the model without memory mapping, so the experts in RAM are memory that the
  kernel cannot evict and that the ZFS ARC does not cache a second time.
- `-t 8 -tb 16`: generation on two memory channels saturates at about 6 to 8 threads; batches use
  16.
- `-ub 2048` is the measured setting; a large batch spreads the cost of sending the experts over
  PCIe for each batch.
- The entry sets no sampling defaults and no MTP: the model card gives no defaults for this model,
  and speculative decoding was a net loss for it in published tests.
- `--mmproj ... --no-mmproj-offload` loads this model's own vision projector into system RAM, about
  0.6 GiB next to the experts; the projector of `coder` does not fit this model. It encodes images
  with the 8 threads of `-t 8`, so an image takes about twice as long as on `coder` (estimate); the
  thread count stays at 8 for the speed of the experts.
- Loading `coder-moe` unloads `coder`, and the other way round.

### The embedding and reranking model entries

{{ include stack/inference/llama-swap/config.yaml lines=201-227 }}

- `--device none` runs both models on the CPU. The image selects its `sapphirerapids` CPU backend,
  with AVX-512 and AMX, at run time.
- `CUDA_VISIBLE_DEVICES=-1` hides the GPU from these two processes, so that they do not each create
  a CUDA context of about 0.3 GiB of VRAM.
- `-c 4096 -b 4096 -ub 4096`: each input, for the reranker the query together with one document,
  must fit one batch. Document chunks are far smaller.
- `--embedding --pooling last` is the setting of the embedding model's card; `--reranking` serves
  `/v1/rerank`.
- Each model uses about 1.3 GiB of system RAM (estimate) and no VRAM, and both stay loaded.

!!! note
    It is not verified that `--device none` alone would create a CUDA context, nor that
    `CUDA_VISIBLE_DEVICES=-1` prevents it. Check it in
    [Check GPU memory and processes](#check-gpu-memory-and-processes).

### Swap groups and preloading

{{ include stack/inference/llama-swap/config.yaml lines=229-251 }}

The `llm` group holds the two GPU models and swaps them: requesting one unloads the other. The
`rag` group is persistent: the embedding and reranking models stay loaded whatever happens in the
`llm` group. When the container starts, llama-swap loads `embed`, `rerank` and `coder`, so the
stack is ready after a restart without a slow first request.

### LiteLLM model names

Clients use only the LiteLLM names. Each name points to a llama-swap id, over one of three routes.

Table: LiteLLM model names

| Name | llama-swap id | Route | Used by |
|---|---|---|---|
| `local-coder` | `coder` | OpenAI | OpenCode (main model), Open WebUI (default) |
| `local-fast` | `coder-fast` (thinking off) | OpenAI | Titles, scouts, summaries |
| `local-coder-moe` | `coder-moe` | OpenAI | The fast profile; swaps the GPU model |
| `local-opus`, `local-sonnet` | `coder` | Anthropic | Claude Code |
| `local-haiku` | `coder-fast` (thinking off) | Anthropic | Claude Code's small and background model |
| `local-embed` | `embed` | OpenAI embeddings | Open WebUI retrieval |
| `local-rerank` | `rerank` | Rerank | Open WebUI retrieval |

{{ include stack/inference/litellm/config.yaml lines=50-132 }}

- **Anthropic route** (`anthropic/<id>`). LiteLLM appends `/v1/messages` to `api_base`, so Claude
  Code's requests reach llama-server's own Anthropic endpoint with no format conversion in LiteLLM.
  Do not route Claude Code through the `openai/` names.
- **OpenAI route** (`openai/<id>`). Chat completions and embeddings at `http://llama-swap:8080/v1`.
- **Rerank route** (`hosted_vllm/rerank`). LiteLLM posts the Cohere-style request to
  `http://llama-swap:8080/rerank` and returns `results` with `index` and `relevance_score`.
- `max_input_tokens: 65536` is what `/v1/models` and `/model/info` report. Claude Code's own window
  is set on the client (`CLAUDE_CODE_MAX_CONTEXT_TOKENS=65536`, Chapter 7,
  [Claude Code settings for the gateway](#claude-code-settings-for-the-gateway)).
- `cost_per_second: 0.0001` is a notional price per second of request time on the GPU models. At
  that price, a key budget of 50 allows 500,000 seconds, so budgets act as GPU-time quotas. The CPU
  models carry no price. Usage logs record tokens and duration for every request either way.
- `supports_vision: true` on the six chat names declares that they accept images; `/model/info`
  and `/model_group/info` report it. LiteLLM does not act on it for these routes: it passes images
  through unchanged either way, as described in [Images on the chat models](#images-on-the-chat-models).

### Images on the chat models

Every chat name accepts images: the names backed by `coder` (`local-coder`, `local-fast`,
`local-opus`, `local-sonnet`, `local-haiku`) and `local-coder-moe`. The embedding and reranking
models do not.

- **What clients send.** On `/v1/chat/completions`, `image_url` parts in a user message, usually
  with a `data:` URL that carries the image in base64. On `/v1/messages`, `image` blocks, also
  inside tool results. LiteLLM forwards both unchanged; on the OpenAI route it moves images that a
  `tool` message carries into a user message right after the tool results. `llama-server` decodes
  PNG, JPEG, GIF, BMP and WebP. Given a web address instead of image data, it downloads the image
  itself (at most 10 MB, within 10 seconds) and refuses addresses that are not public.
- **Where it runs.** The projector encodes each image on the CPU, then the model on the GPU reads
  the resulting tokens with the rest of the prompt. Expect about 11 seconds per image on `coder`
  (measured on another machine; an estimate here), more for a large image, against about 0.3
  seconds on a GPU.
- **What it costs in context.** One image token covers 32 x 32 pixels, and an image takes at most
  4,096 tokens by default. A 1920 x 1080 screenshot is about 2,000 tokens of the 64K window.
- **No size limit in the gateway.** LiteLLM sets no request size limit, and llama-swap accepts
  requests of up to 250 MB.
- **PDF files are not images.** `llama-server` rejects a `file` part on `/v1/chat/completions` with
  the error `unsupported content[].type`, and silently drops a PDF `document` block on
  `/v1/messages`, so the model never sees the PDF. PDFs reach the models as text, through the
  knowledge bases of Chapter 6.
- **Without a projector**, for example in a copy of the configuration without the `--mmproj` line,
  `llama-server` answers any image with
  `image input is not supported - hint: if this is unexpected, you may need to provide the mmproj`.

### LiteLLM gateway settings

{{ include stack/inference/litellm/config.yaml lines=134-165 }}

Table: LiteLLM gateway settings

| Setting | Effect |
|---|---|
| `drop_params: true` | Request parameters that a route does not support are dropped instead of failing the request |
| `request_timeout: 900`, `timeout: 900` | A long agent turn, a 30,000-token prompt plus a long answer, can take minutes on this GPU |
| `callbacks: ["prometheus"]` | Prometheus metrics at `litellm:4000/metrics` (a key is required) |
| `sse_keepalive_ping_interval_seconds: 30` | During a silent stream (a model swap, a long prompt) LiteLLM sends a keep-alive comment every 30 seconds, so Claude Code (300-second idle limit) and Caddy keep the stream open. Once a ping has gone out the status is 200, so a later failure arrives as an error event in the stream, not as an HTTP error status |
| `num_retries: 0` | No retries: there is one upstream, and a retry would repeat minutes of GPU work |
| `master_key`, `database_url` | From the environment (`inference.env`) |
| `store_model_in_db: false` | Models come only from this file |
| `disable_spend_logs: false` | One usage row per request (key, model, tokens, duration), shown in the Admin UI at `/ui` |
| `store_prompts_in_spend_logs: false` | The rows hold metadata only, not prompts or responses |

## Install the ai-inference app

The app is a TrueNAS custom app whose YAML includes `stack/inference/compose.yaml` from the clone
and reads its variables from `/mnt/tank/ai/secrets/inference.env`.

### Check the inference prerequisites

#### Prerequisites

- The `ai-net` network exists ([Create the shared Docker network](#create-the-shared-docker-network)).
- The datasets `tank/ai/models` and `tank/ai/appdata/litellm-db` exist
  ([Create the appdata datasets](#create-the-appdata-datasets)).
- The clone is at the release tag ([Clone the release tag](#clone-the-release-tag)).
- `inference.env` is in `/mnt/tank/ai/secrets`
  ([Copy the environment files to TrueNAS](#copy-the-environment-files-to-truenas)).
- The model files are verified ([Verify the model files](#verify-the-model-files)).

#### Steps

1. Confirm the release of the clone:

        git -C /mnt/tank/ai/stacks/local-agent-stack describe --tags --exact-match

    The output is the release tag, for example `v1.0`.

2. Confirm that `inference.env` sets the four variables:

        sudo grep -c -E \
          '^(LITELLM_MASTER_KEY|LITELLM_SALT_KEY|LITELLM_DB_PASSWORD|LLAMA_SWAP_API_KEY)=' \
          /mnt/tank/ai/secrets/inference.env

    The output is `4`.

3. Confirm that no placeholder of the example file is left:

        sudo grep -c 'change-me' /mnt/tank/ai/secrets/inference.env

    The output is `0`.

4. Render the compose file with the real variables, as TrueNAS does when you save the app:

        sudo docker compose --env-file /mnt/tank/ai/secrets/inference.env \
          -f /mnt/tank/ai/stacks/local-agent-stack/stack/inference/compose.yaml config -q

    The command prints nothing. A missing variable is named in the error message.

5. Confirm that the LiteLLM database directory is empty before the first install:

        sudo ls -A /mnt/tank/ai/appdata/litellm-db

    The command prints nothing. PostgreSQL creates its data directory, `pgdata`, on the first start,
    with the password from `inference.env`.

#### Results

The clone, the environment file and the database directory are ready, and Compose accepts the app's
files with your values. Every check passed, so TrueNAS can validate the YAML in the next task.

### Install ai-inference with Install via YAML

#### About this task

TrueNAS validates the YAML with `docker compose config` when you save it, so the included file
must already exist. It then runs the app as the compose project `ix-ai-inference`. The
`services: {}` line is required by TrueNAS 25.10 for a YAML that only includes other files. The
`env_file` supplies the variables that the compose file uses, and the relative paths in the compose
file, such as `./llama-swap/config.yaml`, resolve against `stack/inference/` in the clone. The
app's **Edit** screen later shows only these lines, not the included files.

#### Steps

1. Go to **Apps** > **Discover Apps**, click **More Options** (⋮) next to **Custom App**, and click
   **Install via YAML**.

2. Enter **Name** `ai-inference`.

    App names use lower-case letters, digits and hyphens, start with a letter, and have at most 40
    characters.

3. Enter the following YAML in **Custom Config**. It is the file
   `stack/inference/truenas-app.yaml` of the release:

    {{ include stack/inference/truenas-app.yaml }}

    On the workstation, in the clone, `python3 tools/deploy.py render --app ai-inference` prints the
    same four lines after a `# ai-inference` line. When the clone has the release tag, it adds an
    `x-local-agent-stack` block with the content hashes that `deploy.py apply` records
    ([Setting up deploy.py](#setting-up-deploypy)). Paste only the four lines.

4. Click **Save**.

    TrueNAS pulls the three images, which takes several minutes on the first install, and starts
    the containers. **Apps** > **Installed** shows `ai-inference` as **Deploying** while a container
    is starting, and as **Running** when all three report healthy.

5. In **System** > **Shell**, follow the containers:

        sudo docker ps --filter name=llama-swap --filter name=litellm \
          --format 'table {{.Names}}\t{{.Status}}'

    Repeat the command until the three rows `llama-swap`, `litellm` and `litellm-db` show
    `(healthy)` in their status. On the first start, LiteLLM runs its database migrations and can
    take up to two minutes.

    !!! note
        PostgreSQL's first start on a dataset with the **Apps** preset (NFSv4 ACL) was not tested.
        If `litellm-db` keeps restarting and `sudo docker logs --tail 30 litellm-db` shows a
        permissions error for `/var/lib/postgresql/data/pgdata` (for example from `chmod`), the
        dataset's ACL refuses the mode that PostgreSQL sets on its data directory. `litellm` then
        never starts, because it waits for a healthy database, and the app stays **Deploying**.
        Recreate the empty dataset with
        [Recreate the litellm-db dataset with the Generic preset](#recreate-the-litellm-db-dataset-with-the-generic-preset),
        then continue with this step.

6. Confirm the state that TrueNAS reports:

        sudo midclt call app.get_instance ai-inference |
          python3 -c "import json, sys; print(json.load(sys.stdin)['state'])"

    The output is `RUNNING`.

#### Results

`ai-inference` is running. **Apps** > **Installed** > `ai-inference` > **Workloads** lists the three
containers; **View Logs** next to a container shows its log.

If the app does not start, read the compose errors that TrueNAS logs, and the log of the container
that failed:

```
sudo tail -n 50 /var/log/app_lifecycle.log
sudo docker logs --tail 100 litellm
```

### Recreate the litellm-db dataset with the Generic preset

#### Prerequisites

- `litellm-db` keeps restarting, and its log shows a permissions error for
  `/var/lib/postgresql/data/pgdata`.
- LiteLLM has never started, so the dataset holds no keys and no usage logs.

#### About this task

PostgreSQL's first start on a dataset with the **Apps** preset (NFSv4 ACL) was not tested. The
image's entrypoint changes the mode of `PGDATA` to 0700, which the dataset's ACL mode can refuse.
If that happens, recreate `tank/ai/appdata/litellm-db` with the **Generic** preset. A dataset's
preset cannot be changed after it is created, so this task destroys the empty dataset and creates
it again with the same record size, 32K. The `litellm-db` service mounts the dataset at
`/var/lib/postgresql/data` and keeps `PGDATA` one level below it:

{{ include stack/inference/compose.yaml lines=141-171 }}

Chapter 6 gives the `pgvector` database of the `ai-rag` app the same treatment if it shows the same
error ([Recreate the pgvector dataset with the Generic preset](#recreate-the-pgvector-dataset-with-the-generic-preset)).

!!! caution
    `zfs destroy` deletes the dataset and every file in it. Run step 4 only while the database has
    never started. After LiteLLM has stored keys, restore from a backup instead (Appendix A).

#### Steps

1. Confirm the error:

        sudo docker logs --tail 30 litellm-db

    The log shows a permissions error that names `/var/lib/postgresql/data/pgdata`.

2. Confirm that no database was created:

        sudo test -e /mnt/tank/ai/appdata/litellm-db/pgdata/PG_VERSION && echo initialized || echo empty

    The output is `empty`. If it is `initialized`, PostgreSQL created its database, and the error
    has another cause; do not continue with this task, and see Chapter 11.

3. Stop the container:

        sudo docker stop litellm-db

4. Destroy the dataset:

        sudo zfs destroy tank/ai/appdata/litellm-db

5. In the TrueNAS web interface, go to **Datasets**, select `tank/ai/appdata` and click
   **Add Dataset**.

6. Enter **Name** `litellm-db` and select **Dataset Preset** `Generic`.

7. Click **Advanced Options**, set **Record Size** to `32K` and click **Save**.

8. Verify the record size and that the new dataset is empty:

        sudo zfs get -o property,value recordsize tank/ai/appdata/litellm-db
        sudo ls -A /mnt/tank/ai/appdata/litellm-db

    The value is `32K`, and the second command prints nothing.

9. Redeploy the app, which recreates all three containers:

        sudo midclt call -j app.redeploy ai-inference

10. Repeat steps 5 and 6 of
    [Install ai-inference with Install via YAML](#install-ai-inference-with-install-via-yaml).

#### Results

PostgreSQL initializes its data directory on the **Generic** dataset, `litellm-db` reports
healthy, and `litellm` starts. Appendix A backs up the new dataset like the old one.

### Redeploy ai-inference after a change

#### About this task

A redeploy re-reads the included files and recreates every container of the app. After a release
update, `deploy.py apply` does this by itself when the release changed the app's files
([Apply the release](#apply-the-release)). Redeploy by hand after you change a file that only your
server has, such as the copy and the override file in
[Apply a fallback when coder does not fit](#apply-a-fallback-when-coder-does-not-fit), and whenever
you move the clone to another tag without `deploy.py`. The GPU model loads again, so clients wait
for a minute or more.

#### Steps

1. Redeploy the app:

        sudo midclt call -j app.redeploy ai-inference

    The command waits for the redeploy job and prints its result.

2. Confirm that the running `coder` process uses the new configuration, by printing its command
   line:

        sudo docker exec llama-swap sh -c 'printf "Authorization: Bearer %s\n" "$LLAMA_SWAP_API_KEY" |
          curl -fsS -H @- http://127.0.0.1:8080/running' |
          python3 -c "import json, sys; \
            [print(m['model'], '|', ' '.join(m['cmd'].split())) \
             for m in json.load(sys.stdin)['running']]"

    Each line shows a loaded model and the flags it runs with.

#### Results

Every container of `ai-inference` runs with the current files, and the `coder` line shows the flags
you expect. Clients that sent requests during the redeploy retry once the model has loaded.

!!! note
    llama-swap runs with `-watch-config` and reloads its configuration when the file changes. The
    configuration file is mounted as a single file, and it is not verified that llama-swap notices a
    file that `git` replaced, because a single-file mount keeps the old file. When a `git checkout`
    in the clone changes the file, let `deploy.py apply` recreate the app, which it does for a
    changed file, or redeploy it by hand, and check the result with step 2.

## Verify the models load

These checks run on TrueNAS. The `llama-swap` container has `curl` and is on `ai-net`, so it can
reach both llama-swap and `litellm:4000`. Keys never appear on a command line. For llama-swap's
key, the shell inside the container reads it from the container's own environment, and its
built-in `printf` hands the header to `curl` on standard input (`-H @-`). The LiteLLM key is passed
to `curl` on standard input from the TrueNAS shell.

### Check the health endpoints

#### Steps

1. Check llama-swap:

        sudo docker exec llama-swap curl -fsS http://127.0.0.1:8080/health

    The output is `OK`.

2. List the loaded models and their state:

        sudo docker exec llama-swap sh -c 'printf "Authorization: Bearer %s\n" "$LLAMA_SWAP_API_KEY" |
          curl -fsS -H @- http://127.0.0.1:8080/running' |
          python3 -c "import json, sys; \
            [print(m['model'], m['state']) for m in json.load(sys.stdin)['running']]"

    The output lists `coder`, `embed` and `rerank`, each with the state `ready`. Loading `coder`
    takes a minute or more after a start; repeat the command until it shows `ready`.

3. Check LiteLLM and its database:

        sudo docker exec litellm python3 -c "import urllib.request as u; \
          print(u.urlopen('http://127.0.0.1:4000/health/readiness').read().decode())"

    The output contains `"status":"healthy"` and `"db":"connected"`.

#### Results

llama-swap answers and has loaded `coder`, `embed` and `rerank`, and LiteLLM is ready with its
database connected.

!!! warning
    Never call LiteLLM's `GET /health` without a model, and never point a monitor at it. It sends a
    real request to every model, which loads `coder-moe` and swaps `coder` out of the GPU. Use
    `/health/liveliness` and `/health/readiness` for probes, and `/health?model=local-coder` to
    check one model.

### Check GPU memory and processes

#### Steps

1. Display the GPU memory:

        nvidia-smi --query-gpu=memory.used,memory.total --format=csv

    `memory.total` is about 16,376 MiB, and `memory.used` is roughly 14,000 to 15,500 MiB while
    `coder` is loaded. A value at the card's total means that the model barely fits or does not fit;
    continue with [Test that the coder model fits](#test-that-the-coder-model-fits). The vision
    projector is in system RAM and adds nothing to this figure.

2. List the processes that use the GPU:

        nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv

    The list has one `llama-server` process, the `coder` model.

#### Results

Only the `coder` process holds GPU memory, and you know how much of the card it uses. The
benchmark later in this chapter measures the headroom in detail
([Test that the coder model fits](#test-that-the-coder-model-fits)).

!!! note
    The VRAM figures are estimates with an uncertainty of about 0.5 GiB, and the total of about
    16,376 MiB is assumed; read your card's values here. If step 2 lists two more `llama-server`
    processes of about 300 MiB each, the CPU-only models have created CUDA contexts despite
    `CUDA_VISIBLE_DEVICES=-1`. Note their memory, because it reduces the headroom of `coder`, and
    report it to the project as an issue.

### Check the llama-swap logs

#### Steps

1. Open **Apps** > **Installed** > `ai-inference` > **Workloads**, and click **View Logs** next to
   `llama-swap`.

    The log shows llama-swap's own lines and the output of each `llama-server` process.

2. Alternatively, display the last lines in the shell:

        sudo docker logs --tail 100 llama-swap

3. Confirm that the CPU models use the Sapphire Rapids backend:

        sudo docker logs llama-swap 2>&1 | grep -i -E 'sapphirerapids|AMX_INT8'

    The output names the `sapphirerapids` backend and shows `AMX_INT8 = 1`.

4. Confirm that no model ran out of memory:

        sudo docker logs llama-swap 2>&1 | grep -i 'out of memory'

    The command prints nothing.

#### Results

The models loaded without errors. Keep the log in mind for later: a "Forcing full prompt
re-processing" line means that a client changed earlier messages of a conversation, which makes
the model process the whole prompt again. Chapter 9 counts these lines in
[Watch a real agent session for tool-call problems](#watch-a-real-agent-session-for-tool-call-problems).

### Send test requests through ai-net

#### About this task

The first request goes straight to llama-swap and shows the speed of the `coder` model and whether
speculative decoding with the MTP head is active. The other requests go to LiteLLM over `ai-net`
with the master key, through the same names that clients will use.

#### Steps

1. Refresh the `sudo` credentials, so that the commands with pipes below do not prompt:

        sudo -v

2. Ask `coder-fast` for a short program directly at llama-swap, and print the timing figures of the
   answer:

        echo '{"model": "coder-fast", "max_tokens": 256, "messages": [{"role": "user",
          "content": "Write a Python function that checks whether a number is prime."}]}' |
          sudo docker exec -i llama-swap sh -c 'body=$(cat)
            printf "Authorization: Bearer %s\n" "$LLAMA_SWAP_API_KEY" |
            curl -sS -d "$body" -H @- -H "Content-Type: application/json" \
              http://127.0.0.1:8080/v1/chat/completions' |
          python3 -c "import json, sys; t = json.load(sys.stdin)['timings']; \
            print({k: t.get(k) for k in ('prompt_n', 'predicted_n', 'predicted_per_second', \
            'draft_n', 'draft_n_accepted')})"

    `predicted_per_second` is the generation speed, about 50 to 65 tokens per second (estimate).
    `draft_n` and `draft_n_accepted` are greater than 0 when speculative decoding with the MTP head
    is active. If they are missing or 0, the MTP head was not loaded; see
    [Read the benchmark results](#read-the-benchmark-results).

3. Read the LiteLLM master key into a shell variable. The value is not printed:

        MK=$(sudo sed -n 's/^LITELLM_MASTER_KEY=//p' /mnt/tank/ai/secrets/inference.env)

4. List the model names that LiteLLM serves:

        printf 'Authorization: Bearer %s\n' "$MK" |
          sudo docker exec -i llama-swap curl -sS -H @- http://litellm:4000/v1/models |
          python3 -c "import json, sys; \
            print(' '.join(sorted(m['id'] for m in json.load(sys.stdin)['data'])))"

    The output is the eight names: `local-coder local-coder-moe local-embed local-fast local-haiku
    local-opus local-rerank local-sonnet`.

5. Send a chat request in the OpenAI format to `local-fast`:

        printf 'Authorization: Bearer %s\n' "$MK" |
          sudo docker exec -i llama-swap curl -sS -H @- -H 'Content-Type: application/json' \
            -d '{"model": "local-fast", "max_tokens": 16,
                 "messages": [{"role": "user", "content": "Reply with the single word OK."}]}' \
            http://litellm:4000/v1/chat/completions |
          python3 -c "import json, sys; d = json.load(sys.stdin); \
            print(d['choices'][0]['message']['content'] if 'choices' in d else d)"

    The output is `OK`.

6. Send a request in the Anthropic format, as Claude Code does, to `local-haiku`:

        printf 'Authorization: Bearer %s\n' "$MK" |
          sudo docker exec -i llama-swap curl -sS -H @- -H 'Content-Type: application/json' \
            -H 'anthropic-version: 2023-06-01' \
            -d '{"model": "local-haiku", "max_tokens": 16,
                 "messages": [{"role": "user", "content": "Reply with the single word OK."}]}' \
            http://litellm:4000/v1/messages |
          python3 -c "import json, sys; d = json.load(sys.stdin); \
            print(''.join(b.get('text', '') for b in d.get('content', []) \
            if b.get('type') == 'text') or d)"

    The output is `OK`.

7. Request an embedding from `local-embed` and print the length of the vector:

        printf 'Authorization: Bearer %s\n' "$MK" |
          sudo docker exec -i llama-swap curl -sS -H @- -H 'Content-Type: application/json' \
            -d '{"model": "local-embed", "input": "local agent stack"}' \
            http://litellm:4000/v1/embeddings |
          python3 -c "import json, sys; \
            print(len(json.load(sys.stdin)['data'][0]['embedding']))"

    The output is `1024`.

8. Rerank two documents with `local-rerank`:

        printf 'Authorization: Bearer %s\n' "$MK" |
          sudo docker exec -i llama-swap curl -sS -H @- -H 'Content-Type: application/json' \
            -d '{"model": "local-rerank", "query": "What is the capital of France?",
                 "documents": ["Paris is the capital of France.",
                               "A GPU has many small cores."]}' \
            http://litellm:4000/v1/rerank |
          python3 -c "import json, sys; \
            print([(r['index'], round(r['relevance_score'], 3)) \
            for r in json.load(sys.stdin)['results']])"

    The output lists both documents; document `0` has the higher score.

9. Check one model's health the safe way:

        printf 'Authorization: Bearer %s\n' "$MK" |
          sudo docker exec -i llama-swap curl -sS -H @- \
            'http://litellm:4000/health?model=local-coder' |
          python3 -c "import json, sys; d = json.load(sys.stdin); \
            print('healthy:', d.get('healthy_count'), 'unhealthy:', d.get('unhealthy_count'))"

    The output is `healthy: 1 unhealthy: 0`.

#### Results

Every model answers through llama-swap and through LiteLLM, in both API formats. Keep the shell
open with `MK` set for the next task and the next topic.

### Check the vision projector

#### Prerequisites

- A TrueNAS shell in which `MK` holds the LiteLLM master key, as after
  [Send test requests through ai-net](#send-test-requests-through-ai-net). In a new shell, run
  steps 1 and 3 of that task first.

#### About this task

This task confirms that `coder` loaded its vision projector on the CPU, and sends the test image
of the release, `evals/images/maple-74.png` in the clone, through LiteLLM in both API formats. The
image is 640 x 160 pixels and shows the text `MAPLE 74` in black capital letters on white. The
requests use `local-fast` and `local-haiku`, the `coder` process with thinking off, so the answer
is the text alone. Chapter 9 sends the same image as the optional evaluation case `format-011`
([Evaluations and the regression gate](#evaluations-and-the-regression-gate)).

#### Steps

1. Ask `llama-server` which inputs `coder` accepts:

        sudo docker exec llama-swap sh -c 'printf "Authorization: Bearer %s\n" "$LLAMA_SWAP_API_KEY" |
          curl -fsS -H @- http://127.0.0.1:8080/upstream/coder/props' |
          grep -o '"vision":[a-z]*'

    The output is `"vision":true`. The request loads `coder` if it is not loaded. `"vision":false`
    means that the model runs without a projector: check the `--mmproj` line of the running
    process as in step 2 of
    [Redeploy ai-inference after a change](#redeploy-ai-inference-after-a-change).

2. Display the projector's lines in the log:

        sudo docker logs llama-swap 2>&1 |
          grep -E 'loaded multimodal model|mtmd_context.*compute buffer size|image tokens' | tail -n 3

    The output has three lines from the last load of `coder`:

    - a warning that Qwen-VL models require at minimum 1024 image tokens to function correctly
      on grounding tasks. It is expected: grounding (boxes around objects in an image) is not
      used here, and the option it suggests, `--image-min-tokens 1024`, would enlarge every small
      image at a cost in CPU time;
    - the projector's `CPU compute buffer size`, in MiB, which adds to the 0.6 GiB of its weights
      in system RAM;
    - `loaded multimodal model, '/models/gguf/mmproj-Qwen3.8-27B-Q8_0.gguf'`.

    If the log shows `failed to load multimodal model` instead, the projector file is missing or
    damaged: check it with [Verify the model files](#verify-the-model-files).

3. Store the test image in a shell variable, encoded in base64:

        IMG64=$(base64 -w 0 /mnt/tank/ai/stacks/local-agent-stack/evals/images/maple-74.png)
        echo "${#IMG64}"

    The output is the length of the encoded image, about 1,700 characters.

4. Send the image in the OpenAI format to `local-fast`, and time the request:

        time printf 'Authorization: Bearer %s\n' "$MK" |
          sudo docker exec -i llama-swap curl -sS -H @- -H 'Content-Type: application/json' \
            -d '{"model": "local-fast", "max_tokens": 32, "messages": [{"role": "user", "content": [
                 {"type": "image_url", "image_url": {"url": "data:image/png;base64,'"$IMG64"'"}},
                 {"type": "text", "text": "Reply with the text in the image and nothing else."}]}]}' \
            http://litellm:4000/v1/chat/completions |
          python3 -c "import json, sys; d = json.load(sys.stdin); \
            print(d['choices'][0]['message']['content'] if 'choices' in d else d)"

    The output is `MAPLE 74`, followed by the time the command took. It is longer than for the text
    request of step 5 of [Send test requests through ai-net](#send-test-requests-through-ai-net),
    because the CPU encodes the image first. This image is small; a large photo or screenshot
    takes several times as long.

5. Send the image in the Anthropic format, as Claude Code does, to `local-haiku`:

        printf 'Authorization: Bearer %s\n' "$MK" |
          sudo docker exec -i llama-swap curl -sS -H @- -H 'Content-Type: application/json' \
            -H 'anthropic-version: 2023-06-01' \
            -d '{"model": "local-haiku", "max_tokens": 32, "messages": [{"role": "user", "content": [
                 {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "'"$IMG64"'"}},
                 {"type": "text", "text": "Reply with the text in the image and nothing else."}]}]}' \
            http://litellm:4000/v1/messages |
          python3 -c "import json, sys; d = json.load(sys.stdin); \
            print(''.join(b.get('text', '') for b in d.get('content', []) \
            if b.get('type') == 'text') or d)"

    The output is `MAPLE 74`.

6. Confirm in the log that the model read the image tokens:

        sudo docker logs --since 10m llama-swap 2>&1 | grep 'image decoded'

    Each of the two images shows an `image decoded (batch 1/1) in <n> ms` line, written when the
    model on the GPU has read the tokens that the projector produced.

7. Clear the image variable:

        unset IMG64

#### Results

`coder` runs with its vision projector on the CPU and reads an image sent in either API format.
The projector uses no GPU memory. `coder-moe` loads its own projector the same
way; [Switch to the fast profile](#switch-to-the-fast-profile) checks it while that model is
loaded.

If the answer in step 4 or 5 is close to `MAPLE 74` but not exact, for example with one letter
wrong, the projector loaded but reads poorly with this model. Report it to the project as an
issue, with the answer and the time of step 4. If the request fails with `image input is not
supported`, the model was started without `--mmproj`.

## Create the LiteLLM keys for the workstations

The master key is for administration only. Each client gets its own LiteLLM virtual key, limited
to the model names it needs, so that the usage logs show which client sent each request and a key
can be revoked without affecting the others. This topic creates the keys of the two workstations.
Open WebUI gets its own key, with the five names it uses, in Chapter 6:
[Create the virtual key that Open WebUI uses](#create-the-virtual-key-that-open-webui-uses). Do not
create it in this chapter.

### Workstation keys and where they go

Table: Workstation keys

| Key alias | Allowed model names | Used by | Where the value goes |
|---|---|---|---|
| `c4dev` | All eight names | OpenCode and Claude Code (`claude-local`) on `c4dev`; `tools/smoke.py` | `LOCAL_LLM_KEY` in `~/.config/local-agent-stack/client.env` on `c4dev` |
| `mac` | All eight names | OpenCode and Claude Code on the Mac | `LOCAL_LLM_KEY` in `~/.config/local-agent-stack/client.env` on the Mac |

Chapter 7 writes each key into its workstation's `client.env`, in
[Prepare the client environment file](#prepare-the-client-environment-file).

- **What each name is for.** OpenCode needs `local-coder`, `local-fast` and `local-coder-moe`.
  Claude Code, through `claude-local`, needs `local-opus`, `local-sonnet` and `local-haiku`.
  `tools/smoke.py` (Chapter 9) checks that `/v1/models` lists every name and tests `local-embed`
  and `local-rerank` with the same key, so the workstation keys allow all eight. LiteLLM lists only
  the names that a key may use.
- **Claude Code has no key of its own.** `claude-local` reads `LOCAL_LLM_KEY` from the same
  `client.env` as OpenCode. The usage logs still tell the two apart: only Claude Code uses
  `local-opus`, `local-sonnet` and `local-haiku`.
- **Other clients**, such as a Windows VM, get a key of their own in the same way, with a new
  `key_alias`. Key aliases must be unique.

The keys in this topic have no budget and no rate limit. LiteLLM accepts the following optional
fields in the same request, if you want them.

Table: Optional key limits

| Field | Example | Effect |
|---|---|---|
| `max_budget` | `50` | Requests fail once the key's spend exceeds the value. At `cost_per_second: 0.0001`, 50 is 500,000 seconds of request time on the GPU models |
| `budget_duration` | `"30d"` | The spend resets at this interval |
| `rpm_limit` | `120` | Maximum requests per minute |
| `max_parallel_requests` | `2` | Maximum concurrent requests |

!!! caution
    The OpenCode coordinator runs two or three agents at the same time (Chapter 8), and their
    requests queue on the server. A `max_parallel_requests` below that number makes LiteLLM reject
    the extra requests instead of letting them queue. A budget that runs out stops the client until
    the spend resets.

### Generate the workstation keys

#### About this task

LiteLLM stores only a hash of each key. The response to the request that creates a key is the only
place where the key appears, so copy each key as soon as it is printed. The commands run on
TrueNAS, in the shell from the previous topic.

#### Steps

1. If you opened a new shell, refresh `sudo` and read the master key again:

        sudo -v
        MK=$(sudo sed -n 's/^LITELLM_MASTER_KEY=//p' /mnt/tank/ai/secrets/inference.env)

2. Create the key for `c4dev`:

        printf 'Authorization: Bearer %s\n' "$MK" |
          sudo docker exec -i llama-swap curl -sS -H @- -H 'Content-Type: application/json' \
            -d '{"key_alias": "c4dev",
                 "models": ["local-coder", "local-fast", "local-coder-moe", "local-opus",
                            "local-sonnet", "local-haiku", "local-embed", "local-rerank"],
                 "metadata": {"client": "c4dev: OpenCode and Claude Code"}}' \
            http://litellm:4000/key/generate |
          python3 -c "import json, sys; d = json.load(sys.stdin); \
            print(d.get('key_alias'), d.get('key') or d)"

    The output is the alias followed by the new key, `c4dev sk-...`. Copy the key now; the next
    task stores it.

3. Create the key for the Mac:

        printf 'Authorization: Bearer %s\n' "$MK" |
          sudo docker exec -i llama-swap curl -sS -H @- -H 'Content-Type: application/json' \
            -d '{"key_alias": "mac",
                 "models": ["local-coder", "local-fast", "local-coder-moe", "local-opus",
                            "local-sonnet", "local-haiku", "local-embed", "local-rerank"],
                 "metadata": {"client": "Mac: OpenCode and Claude Code"}}' \
            http://litellm:4000/key/generate |
          python3 -c "import json, sys; d = json.load(sys.stdin); \
            print(d.get('key_alias'), d.get('key') or d)"

    The output is `mac sk-...`. Copy the key.

    If a command prints an error that a key with the alias already exists, the key was created
    before. Delete it as described at the end of [Verify a LiteLLM key](#verify-a-litellm-key) and
    create it again.

4. Clear the master key from the shell:

        unset MK

#### Results

LiteLLM has a key for each workstation. The Admin UI at `https://llm.lab.example.com/ui`, available
after Chapter 5, also lists the keys with their usage; it signs in with the master key.

!!! warning
    A client key gives access to the models of this server. Store each key only in the files named
    in this topic, never in the git clone, and never paste a key into an issue or a chat.

### Keep the workstation keys until Chapter 7

#### About this task

Chapter 7 writes each key into `client.env` on its workstation, in
[Create client.env](#create-clientenv). Until then, keep both keys in the private directory
`~/.config/local-agent-stack/secrets` on `c4dev`, which Chapter 3 created with mode 0700 for the
server's environment files.

#### Steps

1. On `c4dev`, store the `c4dev` key. Run the command, paste the key at the prompt, and press
   Enter. The key is not echoed and does not enter the shell history:

        (umask 077; printf 'LiteLLM key: '; read -rs key; echo; \
          printf '%s\n' "$key" > ~/.config/local-agent-stack/secrets/litellm-c4dev.key)

2. Store the `mac` key in the same way:

        (umask 077; printf 'LiteLLM key: '; read -rs key; echo; \
          printf '%s\n' "$key" > ~/.config/local-agent-stack/secrets/litellm-mac.key)

3. Verify the files:

        ls -l ~/.config/local-agent-stack/secrets/litellm-*.key
        grep -c '^sk-' ~/.config/local-agent-stack/secrets/litellm-c4dev.key \
          ~/.config/local-agent-stack/secrets/litellm-mac.key

    Both files have the mode `-rw-------`, and the second command prints `1` for each file.

#### Results

Both keys are stored on `c4dev`. When Chapter 7 asks for a workstation's key, display it with
`cat ~/.config/local-agent-stack/secrets/litellm-c4dev.key` (or `litellm-mac.key`) and paste it.

### Verify a LiteLLM key

#### Steps

1. On TrueNAS, read a key into a shell variable. Run the command, paste the key, for example the
   `c4dev` key, and press Enter:

        printf 'Key: '; read -rs KEY; echo

2. List the names that the key may use:

        printf 'Authorization: Bearer %s\n' "$KEY" |
          sudo docker exec -i llama-swap curl -sS -H @- http://litellm:4000/v1/models |
          python3 -c "import json, sys; \
            print(' '.join(sorted(m['id'] for m in json.load(sys.stdin)['data'])))"

    For a workstation key, the output is all eight names. For the key of Open WebUI (Chapter 6), it
    is `local-coder local-coder-moe local-embed local-fast local-rerank`.

3. Display the key's own record:

        printf 'Authorization: Bearer %s\n' "$KEY" |
          sudo docker exec -i llama-swap curl -sS -H @- http://litellm:4000/key/info |
          python3 -c "import json, sys; i = json.load(sys.stdin)['info']; \
            print(i.get('key_alias'), i.get('status'), i.get('spend'))"

    The output is the key's alias, `active`, and its spend so far.

4. Clear the variable:

        unset KEY

#### Results

The key is active and allows exactly the model names of its client.

If a key is lost or exposed, delete it by its alias with the master key, then create a new one and
replace it where it goes. For example, for the `mac` key:

```
sudo -v
MK=$(sudo sed -n 's/^LITELLM_MASTER_KEY=//p' /mnt/tank/ai/secrets/inference.env)
printf 'Authorization: Bearer %s\n' "$MK" |
  sudo docker exec -i llama-swap curl -sS -H @- -H 'Content-Type: application/json' \
    -d '{"key_aliases": ["mac"]}' http://litellm:4000/key/delete
unset MK
```

The response lists the deleted key under `deleted_keys`.

## Rotate the inference secrets

Chapter 3 generates the four values of `inference.env` once. Replace one when it may have been
exposed, for example after it was pasted into a chat or an issue, or when a person who knew it no
longer should. The file of record is the workstation's copy,
`~/.config/local-agent-stack/secrets/inference.env`; the server's copy is installed from it. The
keys of the workstations and of Open WebUI are LiteLLM virtual keys, not values of this file:
replace them as described at the end of [Verify a LiteLLM key](#verify-a-litellm-key) and in
[Rotate the LiteLLM key of Open WebUI](#rotate-the-litellm-key-of-open-webui).

### What changes with each inference secret

Table: Rotating the inference secrets

| Secret | Also held by | Procedure |
|---|---|---|
| `LITELLM_MASTER_KEY` | No other app. You sign in to the LiteLLM Admin UI with it, and a Prometheus scrape job that you added for `litellm:4000/metrics` holds a copy | [Rotate the LiteLLM master key](#rotate-the-litellm-master-key) |
| `LLAMA_SWAP_API_KEY` | `litellm`, from the same file; Open WebUI's reranker key if you applied [Point the reranker at llama-swap](#point-the-reranker-at-llama-swap); a browser that saved it as the password of `https://models.lab.example.com/ui` | [Rotate the llama-swap key](#rotate-the-llama-swap-key) |
| `LITELLM_DB_PASSWORD` | The `litellm` role in the `litellm-db` database, which keeps the value of the first start | [Change the LiteLLM database password](#change-the-litellm-database-password) |
| `LITELLM_SALT_KEY` | The data that LiteLLM encrypted in its database | Never change it |

Each procedure starts with a new value in the form that `tools/secrets.py` generates. Print one on
the workstation; the two keys start with `sk-`, the database password does not:

```
python3 -c "import secrets, string; print('sk-' + ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(48)))"
python3 -c "import secrets, string; print(''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(48)))"
```

Each procedure redeploys `ai-inference`, which reloads the GPU model. Run it while no client needs
the stack.

### Rotate the LiteLLM master key

#### About this task

The master key administers LiteLLM: it creates and deletes the virtual keys and signs in to the
Admin UI. Only `litellm` reads it, from `inference.env`, so a new value needs the file and a
redeploy. The virtual keys of the clients are stored in LiteLLM's database; they are expected to
keep working with a new master key, and step 8 checks it.

#### Steps

1. On TrueNAS, keep the current key in a shell variable for the check in step 7. The value is not
   printed:

        sudo -v
        OLD=$(sudo sed -n 's/^LITELLM_MASTER_KEY=//p' /mnt/tank/ai/secrets/inference.env)

2. On the workstation, print a new key with the first command above and copy it.

3. Open `~/.config/local-agent-stack/secrets/inference.env` in a text editor, for example
   `nano ~/.config/local-agent-stack/secrets/inference.env`, set `LITELLM_MASTER_KEY` to the new
   key, and save the file.

4. Copy the file to the server with
   [Copy a changed environment file to TrueNAS](#copy-a-changed-environment-file-to-truenas), using
   `inference` for `<app>`.

5. On TrueNAS, in the shell of step 1, redeploy the app:

        sudo midclt call -j app.redeploy ai-inference

    Wait until the three containers report healthy, as in step 5 of
    [Install ai-inference with Install via YAML](#install-ai-inference-with-install-via-yaml).

6. Check the new key:

        MK=$(sudo sed -n 's/^LITELLM_MASTER_KEY=//p' /mnt/tank/ai/secrets/inference.env)
        printf 'Authorization: Bearer %s\n' "$MK" |
          sudo docker exec -i llama-swap curl -sS -o /dev/null -w '%{http_code}\n' -H @- \
            http://litellm:4000/v1/models

    The output is `200`.

7. Check that the old key is refused:

        printf 'Authorization: Bearer %s\n' "$OLD" |
          sudo docker exec -i llama-swap curl -sS -o /dev/null -w '%{http_code}\n' -H @- \
            http://litellm:4000/v1/models

    The output is `401`.

8. Check that a workstation key still works, with steps 1 to 3 of
   [Verify a LiteLLM key](#verify-a-litellm-key).

    The key lists its model names and its record shows `active`. If it fails, create the
    workstation keys again ([Generate the workstation keys](#generate-the-workstation-keys)) and
    replace them in `client.env` on each workstation (Chapter 7), and create a new key for Open
    WebUI ([Rotate the LiteLLM key of Open WebUI](#rotate-the-litellm-key-of-open-webui)).

9. Clear the variables:

        unset OLD MK

#### Results

LiteLLM accepts only the new master key, and the clients keep their virtual keys. Sign in to the
Admin UI with the new key, and update any scrape job that you configured with the old one.

### Rotate the llama-swap key

#### About this task

`llama-swap` requires `LLAMA_SWAP_API_KEY` on every model request, and `litellm` sends it on every
upstream call. Both containers read it from `inference.env`, so a redeploy of `ai-inference` changes
it on both sides at once. A copy outside the app, such as Open WebUI's reranker key after
[Point the reranker at llama-swap](#point-the-reranker-at-llama-swap), changes by hand.

#### Steps

1. On TrueNAS, keep the current key in a shell variable for the check in step 7:

        sudo -v
        OLD=$(sudo sed -n 's/^LLAMA_SWAP_API_KEY=//p' /mnt/tank/ai/secrets/inference.env)

2. On the workstation, print a new key with the first command above, set it as
   `LLAMA_SWAP_API_KEY` in `~/.config/local-agent-stack/secrets/inference.env` in a text editor, and
   save the file.

3. Copy the file to the server with
   [Copy a changed environment file to TrueNAS](#copy-a-changed-environment-file-to-truenas), using
   `inference` for `<app>`.

4. On TrueNAS, in the shell of step 1, redeploy the app and wait until the three containers report
   healthy:

        sudo midclt call -j app.redeploy ai-inference

5. Check that llama-swap accepts the new key, which the command reads from the container's
   environment:

        sudo docker exec llama-swap sh -c 'printf "Authorization: Bearer %s\n" "$LLAMA_SWAP_API_KEY" |
          curl -sS -o /dev/null -w "%{http_code}\n" -H @- http://127.0.0.1:8080/running'

    The output is `200`.

6. Check that LiteLLM reaches llama-swap with the new key, with steps 3 and 5 of
   [Send test requests through ai-net](#send-test-requests-through-ai-net).

    The output of step 5 is `OK`.

7. Check that the old key is refused, and clear the variable:

        printf 'Authorization: Bearer %s\n' "$OLD" |
          sudo docker exec -i llama-swap curl -sS -o /dev/null -w '%{http_code}\n' -H @- \
            http://127.0.0.1:8080/running
        unset OLD

    The output is `401`.

8. If Open WebUI reranks through llama-swap, display the new key, enter it as the API key of the
   **Reranking Engine** in **Admin Panel** > **Settings** > **Documents**, and click **Save**:

        sudo sed -n 's/^LLAMA_SWAP_API_KEY=//p' /mnt/tank/ai/secrets/inference.env

    Then repeat step 1 of [Point the reranker at llama-swap](#point-the-reranker-at-llama-swap).

#### Results

llama-swap accepts only the new key, and LiteLLM uses it. A browser that stored the old key for
`https://models.lab.example.com/ui` asks for the new one at its next visit.

### Change the LiteLLM database password

#### About this task

`LITELLM_DB_PASSWORD` becomes the password of the `litellm` role when `litellm-db` first creates its
data directory; a new value in `inference.env` alone does not change it and locks LiteLLM out of
its database. This task changes the role's password first, to the new value in the server's file,
and then recreates the containers so that LiteLLM connects with it. `psql` reads the statement on
standard input, so the password does not appear on a command line.

#### Steps

1. On the workstation, print a new password with the second command above (letters and digits
   only, because the password goes into a URL), set it as `LITELLM_DB_PASSWORD` in
   `~/.config/local-agent-stack/secrets/inference.env` in a text editor, and save the file.

2. Copy the file to the server with
   [Copy a changed environment file to TrueNAS](#copy-a-changed-environment-file-to-truenas), using
   `inference` for `<app>`.

3. On TrueNAS, change the password of the role to the value in the new file:

        sudo -v
        printf "ALTER ROLE litellm PASSWORD '%s';\n" \
          "$(sudo sed -n 's/^LITELLM_DB_PASSWORD=//p' /mnt/tank/ai/secrets/inference.env)" |
          sudo docker exec -i litellm-db psql -U litellm -d litellm

    The output is `ALTER ROLE`. LiteLLM's open connections keep working; new ones fail until the
    next step.

4. Redeploy the app at once:

        sudo midclt call -j app.redeploy ai-inference

5. Check LiteLLM and its database, with step 3 of
   [Check the health endpoints](#check-the-health-endpoints).

    The output contains `"status":"healthy"` and `"db":"connected"`.

#### Results

The database and LiteLLM use the new password. The `POSTGRES_PASSWORD` that `litellm-db` receives
from `inference.env` is used only when its data directory is empty, so the `ALTER ROLE` statement is
the change that counts.

## Measure performance with bench.sh

`tools/bench.sh` measures the llama.cpp build of the stack on the server: whether a model
configuration fits in VRAM, how much GPU memory it holds, and its prompt and generation speed. Run
it now, before any client depends on the stack, to confirm that the `coder` configuration fits.
Chapter 9 uses the same tool to record a baseline and to tune the fast profile
([Record a benchmark baseline](#record-a-benchmark-baseline)).

`bench.sh` measures speed and memory, not the quality of the answers. To measure whether a change
to a model or its flags keeps the models good at tool calling, coding and retrieval, the repository
has `tools/eval.py`, which runs evaluation suites from the workstation through the gateway and
compares the results with a stored baseline; Chapter 9 describes it in
[Evaluations and the regression gate](#evaluations-and-the-regression-gate).

### How bench.sh works

Table: Modes of bench.sh

| Mode | What it runs | What it reports |
|---|---|---|
| `bench` (default) | llama-bench (`/app/llama bench` in the image), for every `-ub` value and every KV depth given with `-c` | Prompt processing (`pp`) and generation (`tg`) speed in tokens per second, as the mean and standard deviation of the repetitions |
| `server` (`--mode server`) | One `llama-server` per pair of context size and `-ub` value, with one chat request whose prompt fills 75% of the context | Whether the server starts (fits in VRAM), the GPU memory in use, prompt and generation speed, and the share of accepted draft tokens. Covers what llama-bench cannot run, such as `--spec-type draft-mtp` |

- **Where it runs.** By default inside the running `llama-swap` container, with the production
  image and build. `--oneoff` uses a throwaway container of the same image, which also works while
  `ai-inference` is stopped.
- **It takes the GPU.** Before a GPU run it asks llama-swap to unload `coder` and `coder-moe`
  (`--unload`), so the measurement has the card to itself. llama-swap loads a model again on the
  next request for it.
- **Output.** A Markdown table on standard output; progress and errors on standard error.
- **Defaults.** Without extra flags after `--`, it uses the `coder` model's GPU flags:
  `-ngl 99 -fa on -ctk q8_0 -ctv q8_0`. Extra flags after `--` go to llama-bench or llama-server
  unchanged; llama-bench accepts comma-separated lists in most flags.

Table: Main options of bench.sh

| Option | Meaning |
|---|---|
| `-m`, `--model FILE` | A file under `/models/gguf` in the container, or an absolute path inside the container (required) |
| `--mode MODE` | `bench` or `server` |
| `-c`, `--contexts LIST` | `bench`: KV depths, default `0,16384,32768`. `server`: context sizes, default `32768,65536` |
| `-u`, `--ubatch LIST` | `-ub` values, default `512,1024,2048` |
| `-p`, `--prompt N` | `bench`: prompt tokens per prompt-processing test, default 2048 |
| `-g`, `--gen N` | `bench`: generated tokens per generation test, default 128, `0` to skip the test. `server`: `max_tokens` of the request |
| `-r`, `--reps N` | `bench`: repetitions per test, default 3 |
| `-f`, `--fill PCT` | `server`: share of the context that the prompt fills, default 75 |
| `--container NAME` | The llama-swap container to run in, default `llama-swap` |
| `--oneoff` | Run in a throwaway container instead of inside the running one |
| `--image REF` | `--oneoff`: the image, default the pinned llama-swap image |
| `--models-dir DIR` | `--oneoff`: the server directory mounted at `/models`, default `${AI_ROOT:-/mnt/tank/ai}/models` |
| `--unload LIST` | llama-swap models to unload first, `all` or `none`; default `coder,coder-moe` |
| `--port N` | `server`: loopback port of the test server inside the container, default 18080 |
| `--timeout SEC` | `server`: seconds to wait for a test server to start, default 600 |
| `--dry-run` | Print the Docker commands instead of running them |
| `-h`, `--help` | Print the usage |

Two environment variables change the defaults: `DOCKER`, the Docker command that the script runs
(default `docker`), and `AI_ROOT`, the root of the stack's datasets (default `/mnt/tank/ai`), which
sets the default of `--models-dir`.

!!! note
    `bench.sh` has not yet been run on a server with a GPU. It was checked with `--dry-run`,
    ShellCheck and unit tests of its request and of its parser of the timing figures. Run it with
    `--dry-run` first, and report any problem to the project as an issue.

!!! caution
    A benchmark unloads the GPU model and occupies the GPU for its whole run. Run it while no client
    uses the stack, and run one benchmark at a time.

### Test that the coder model fits

#### About this task

This task starts `llama-server` with the production flags of `coder`, MTP included, at 48K and 64K
context and two `-ub` values, and reports whether each combination starts and how much GPU memory
it uses. Each row loads the 12 GB model once and processes a prompt of about 75% of the context, so
allow several minutes per row. The test leaves out the vision projector, which stays in system RAM
and takes no VRAM.

#### Steps

1. Change to the clone and refresh the `sudo` credentials:

        cd /mnt/tank/ai/stacks/local-agent-stack
        sudo -v

2. Print the commands of the run without running them:

        sudo bash tools/bench.sh --dry-run --mode server \
          -m Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf -c 49152,65536 -u 512,1024 \
          -- -ngl 99 -fa on -ctk q8_0 -ctv q8_0 -ot token_embd.weight=CPU --spec-type draft-mtp

    The output lists the unload requests and one `llama-server` command per row.

3. Run the fit test with the production flags:

        sudo bash tools/bench.sh --mode server \
          -m Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf -c 49152,65536 -u 512,1024 \
          -- -ngl 99 -fa on -ctk q8_0 -ctv q8_0 -ot token_embd.weight=CPU --spec-type draft-mtp

    The script prints a table with one row per context and `-ub` value.

4. If the row for context `65536` and `-ub` `512` shows `no` in the **starts** column, run the test
   again without the two speculative decoding flags:

        sudo bash tools/bench.sh --mode server \
          -m Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf -c 49152,65536 -u 512 \
          -- -ngl 99 -fa on -ctk q8_0 -ctv q8_0 -ot token_embd.weight=CPU

5. To measure what `-ot token_embd.weight=CPU` saves, run one row without it and compare the
   **GPU MiB used** column with the row of step 3:

        sudo bash tools/bench.sh --mode server \
          -m Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf -c 65536 -u 512 \
          -- -ngl 99 -fa on -ctk q8_0 -ctv q8_0 --spec-type draft-mtp

6. Load the production model again, so that it is ready for clients:

        echo '{"model": "coder-fast", "max_tokens": 16,
          "messages": [{"role": "user", "content": "Reply with the single word OK."}]}' |
          sudo docker exec -i llama-swap sh -c 'body=$(cat)
            printf "Authorization: Bearer %s\n" "$LLAMA_SWAP_API_KEY" |
            curl -sS -o /dev/null -w "%{http_code}\n" -d "$body" -H @- \
              -H "Content-Type: application/json" http://127.0.0.1:8080/v1/chat/completions'

    The output is `200` once the model has loaded.

#### Results

You know whether the production configuration of `coder` fits, with how much GPU memory to spare.
Read the table as described in [Read the benchmark results](#read-the-benchmark-results).

### Measure prompt and generation speed

#### Steps

1. In the clone, run llama-bench for `coder` at three KV depths and two `-ub` values:

        sudo bash tools/bench.sh -m Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf \
          -c 0,16384,32768 -u 512,1024

    The script prints a short description of the run and llama-bench's table. The run takes a few
    minutes (estimate: 3 to 8 minutes for a grid of this size, including the model load).

2. Load the production model again, as in step 6 of the previous task.

#### Results

The table has a `pp2048` and a `tg128` row for each depth and `-ub` value, for example
`pp2048 @ d16384`. llama-bench cannot use the MTP head, so the `tg` rows are the speed without
speculative decoding.

### Read the benchmark results

Table: Columns of the server-mode table

| Column | Meaning |
|---|---|
| **context (-c)**, **-ub** | The combination tested |
| **starts** | `yes` if `llama-server` started, `no` if it did not (usually out of VRAM; the script prints the last log lines) |
| **GPU MiB used / total** | GPU memory in use on the whole card while that server ran |
| **prompt tokens**, **prompt t/s** | Size of the test prompt and the speed at which it was processed |
| **generated tokens**, **generation t/s** | Tokens generated and generation speed |
| **draft accepted** | Share of the MTP draft tokens that the model accepted; `-` means that no speculative decoding took place |

Table: Expected results on the reference system

| Measurement | Expected | Basis |
|---|---|---|
| `coder` generation without MTP (llama-bench `tg`) | 40 to 45 tokens/s | Estimate from the memory bandwidth |
| `coder` generation with MTP (server mode) | 50 to 65 tokens/s | Estimate |
| `coder` prompt processing | About 900 to 1,500 tokens/s | Estimate |
| `coder` GPU memory at 64K | About 14.3 GiB of model, KV cache and buffers | Estimate, plus or minus 0.5 GiB |
| `coder-moe` generation | 65 to 80 tokens/s | 80 measured on an RTX 4080 SUPER with two DDR5-4800 channels |
| `coder-moe` prompt processing | About 1,800 to 2,000 tokens/s | Measured on the same system |
| Image on the CPU projector | About 11 seconds per image | Measured on another machine; an estimate here |

Table: What to do with the fit test results

| Result | Meaning | Action |
|---|---|---|
| `yes` at `65536` and `-ub` `512` with MTP, and **draft accepted** shows a percentage | The production configuration fits and speculative decoding works | None |
| `yes` at `65536` with MTP, but **draft accepted** shows `-` | The model fits, but the MTP head did not load in this build | Check the `llama-server` lines of the run for an error about the MTP head; report it as an issue. The stack works at the speed without MTP |
| `no` at `65536` with MTP, `yes` without it | The MTP draft context does not fit | Fallback A in [Apply a fallback when coder does not fit](#apply-a-fallback-when-coder-does-not-fit) |
| `no` at `65536` even without MTP, `yes` at `49152` | The 64K context does not fit | Fallback B in the same task |
| `yes` at `-ub` `1024` with a higher **prompt t/s** | A larger batch fits and processes prompts faster | Optional: propose the change to `stack/inference/llama-swap/config.yaml` through the project workflow (Chapter 8) |

### Apply a fallback when coder does not fit

#### About this task

The release's `llama-swap/config.yaml` stays unchanged in the clone. A copy under
`/mnt/tank/ai/appdata/llama-swap` removes the speculative decoding flags of `coder` (fallback A),
or also lowers its context to 49,152 tokens (fallback B). A compose override file mounts the copy
in place of the release's file, and the app's YAML lists both files.

Fallback A costs speed: generation drops from the estimated 50 to 65 tokens per second to 40 to 45.
Fallback B also shrinks the window that every client relies on.

!!! note
    The copy does not follow the release. After every release update, write it again with steps 2
    and 3 and redeploy the app as in
    [Redeploy ai-inference after a change](#redeploy-ai-inference-after-a-change). `deploy.py` does
    not detect changes to the copy or to the override file: redeploy by hand after you change
    either. To make a fallback permanent, change `stack/inference/llama-swap/config.yaml` in the
    repository through the workflow of Chapter 8
    ([Start work on an issue](#start-work-on-an-issue)).

!!! warning
    Fallback B lowers the server's context below the 65,536 tokens that the clients are configured
    for: `max_input_tokens` in `stack/inference/litellm/config.yaml`, the OpenCode limits in
    `clients/opencode/opencode.jsonc` and `CLAUDE_CODE_MAX_CONTEXT_TOKENS` in
    `clients/claude-code/settings.json`. Requests longer than 49,152 tokens then fail. Use fallback B
    only to keep the stack running, and change all of these files together in the repository.

#### Steps

1. Create the directory for the copy:

        sudo install -d /mnt/tank/ai/appdata/llama-swap

2. Write the copy. For fallback A, remove the speculative decoding line:

        sudo sed -e '/^      --spec-type draft-mtp --spec-draft-n-max 3$/d' \
          /mnt/tank/ai/stacks/local-agent-stack/stack/inference/llama-swap/config.yaml |
          sudo tee /mnt/tank/ai/appdata/llama-swap/config.yaml > /dev/null

    For fallback B, also lower the context of `coder` only:

        sudo sed -e '/^      --spec-type draft-mtp --spec-draft-n-max 3$/d' \
          -e '/^  coder:$/,/^    ttl: 0$/s/-c 65536 -np 1/-c 49152 -np 1/' \
          /mnt/tank/ai/stacks/local-agent-stack/stack/inference/llama-swap/config.yaml |
          sudo tee /mnt/tank/ai/appdata/llama-swap/config.yaml > /dev/null

3. Verify the copy:

        sudo grep -n -E '^ +--spec-type|^ +-c [0-9]+ -np' \
          /mnt/tank/ai/appdata/llama-swap/config.yaml

    The output has no `--spec-type` line and two context lines: for fallback A, both read
    `-c 65536 -np 1`; for fallback B, the first (`coder`) reads `-c 49152 -np 1` and the second
    (`coder-moe`) `-c 65536 -np 1`. If the output differs, the release's file has changed; compare
    the copy with it and edit the copy by hand.

4. Write the compose override file:

        sudo tee /mnt/tank/ai/appdata/llama-swap/fallback.override.yaml > /dev/null <<'EOF'
        services:
          llama-swap:
            volumes:
              - /mnt/tank/ai/appdata/llama-swap/config.yaml:/app/config.yaml:ro
        EOF

    Compose merges volume entries by their target path, so this entry replaces the release's
    `./llama-swap/config.yaml:/app/config.yaml:ro` mount.

5. Go to **Apps** > **Installed**, select `ai-inference`, and click **Edit**.

6. Replace the YAML in **Custom Config** with the following:

        include:
          - path:
              - /mnt/tank/ai/stacks/local-agent-stack/stack/inference/compose.yaml
              - /mnt/tank/ai/appdata/llama-swap/fallback.override.yaml
            env_file: /mnt/tank/ai/secrets/inference.env
        services: {}

7. Click **Save**.

    TrueNAS validates the YAML and recreates the containers.

8. When the app is running again, confirm the flags of the running `coder` process as in step 2 of
   [Redeploy ai-inference after a change](#redeploy-ai-inference-after-a-change).

    The `coder` line has no `--spec-type`, and for fallback B it shows `-c 49152`.

9. Check the GPU memory again as in [Check GPU memory and processes](#check-gpu-memory-and-processes).

10. List the override in your desired-state file, the copy of `deploy/truenas.toml` that Chapter 10
    creates in [Create your desired-state file](#create-your-desired-state-file). Add this line to
    the `[apps.ai-inference]` table, below its `stack` line; if you create the file later, add the
    line then:

        overrides = ["/mnt/tank/ai/appdata/llama-swap/fallback.override.yaml"]

    `deploy.py apply` then writes the same two-path YAML as step 6, followed by its content hashes,
    and keeps it on every later apply. `deploy.py plan` shows
    `override: /mnt/tank/ai/appdata/llama-swap/fallback.override.yaml` under the app. Without the
    line, `apply` would replace the YAML with the four lines of `truenas-app.yaml` and drop the
    fallback.

#### Results

`coder` loads with the fallback configuration.

To return to the release's configuration, remove the `overrides` line from the
`[apps.ai-inference]` table of your desired-state file and apply it from the workstation clone:

```
cd ~/local-agent-stack
~/.local/share/local-agent-stack/deploy-venv/bin/python tools/deploy.py \
  --file ~/.config/local-agent-stack/desired.toml apply --app ai-inference
```

Without a desired-state file, edit the app instead, replace **Custom Config** with the four lines of
`stack/inference/truenas-app.yaml` from
[Install ai-inference with Install via YAML](#install-ai-inference-with-install-via-yaml), and
click **Save**. In both cases, the copy and the override file under
`/mnt/tank/ai/appdata/llama-swap` are no longer used; delete them with
`sudo rm /mnt/tank/ai/appdata/llama-swap/config.yaml /mnt/tank/ai/appdata/llama-swap/fallback.override.yaml`.

### Choose the CPU threads of coder

#### Prerequisites

- [Check the vision projector](#check-the-vision-projector) passed.
- No client is using the stack: steps 2 and 3 unload the GPU model.

#### About this task

`coder` runs with `-t 16`. Generation runs on the GPU and needs few CPU threads, but the vision
projector encodes images on the CPU with exactly the process's thread count, and `llama-server`
has no separate thread setting for it. With 4 threads, the earlier setting, an image takes about
four times as long (estimate). The cost of 16 threads is CPU time while the model writes an
answer: the image's llama.cpp is built with OpenMP, whose idle threads wait actively (spin) for a
while before they sleep, so 16 threads take more CPU time from the embedding and reranking models
and from the document parser than 4 do. Whether 16 threads also change the generation speed is
not measured. This task measures both, and you decide which setting to keep.

Table: Thread settings of coder

| Setting | Images | CPU time while the model generates |
|---|---|---|
| `-t 16` (the release) | Fastest | Highest: idle threads spin before they sleep |
| `-t 4` | About four times slower (estimate) | Low |
| `-t 16` and `OMP_WAIT_POLICY=PASSIVE` in the entry's `env` | Not measured; idle threads sleep at once, which can add a delay each time they wake | Low (assumed) |

#### Steps

1. Change to the clone and refresh the `sudo` credentials:

        cd /mnt/tank/ai/stacks/local-agent-stack
        sudo -v

2. Measure generation with 4 threads, with the other production flags of `coder`:

        sudo bash tools/bench.sh --mode server \
          -m Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf -c 65536 -u 512 \
          -- -ngl 99 -fa on -ctk q8_0 -ctv q8_0 -ot token_embd.weight=CPU --spec-type draft-mtp -t 4

    The table has one row. Note its **generation t/s**.

3. Repeat the measurement with 16 threads:

        sudo bash tools/bench.sh --mode server \
          -m Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf -c 65536 -u 512 \
          -- -ngl 99 -fa on -ctk q8_0 -ctv q8_0 -ot token_embd.weight=CPU --spec-type draft-mtp -t 16

    Compare its **generation t/s** with the row of step 2.

4. Load the production model again, as in step 6 of
   [Test that the coder model fits](#test-that-the-coder-model-fits).

5. Measure the CPU use of the production `coder` process while it writes a long answer. In the
   TrueNAS shell, start a request in the background:

        sudo -v
        echo '{"model": "coder-fast", "max_tokens": 1024, "messages": [{"role": "user",
          "content": "Write a Python module that parses a CSV file of orders and prints totals per customer."}]}' |
          sudo docker exec -i llama-swap sh -c 'body=$(cat)
            printf "Authorization: Bearer %s\n" "$LLAMA_SWAP_API_KEY" |
            curl -sS -o /dev/null -d "$body" -H @- -H "Content-Type: application/json" \
              http://127.0.0.1:8080/v1/chat/completions' &

6. While the answer is generated, display the busiest processes twice, five seconds apart:

        top -b -n 2 -d 5 -o %CPU | grep llama-server | tail -n 3

    The three lines come from the second display: `coder`, `embed` and `rerank`. The line with the
    highest **%CPU** is `coder`; 100% is one fully busy core, so 16 spinning threads show up to
    about 1,600%.

7. Wait for the background request to finish:

        wait

#### Results

You know whether 16 threads cost generation speed and how much CPU `coder` takes while it writes.

Table: What to do with the thread measurement

| Result | Action |
|---|---|
| **generation t/s** about the same in steps 2 and 3, and the CPU use of step 6 does not slow Open WebUI's document uploads or searches | Keep `-t 16` |
| **generation t/s** lower with 16 threads | Use `-t 4` and accept slower images |
| Same speed, but the CPU use of step 6 slows the other apps | Try `-t 16` with `OMP_WAIT_POLICY=PASSIVE`, and repeat steps 5 and 6 and [Check the vision projector](#check-the-vision-projector) |

To change the setting on your server, write a copy of the configuration and its override file as
in [Apply a fallback when coder does not fit](#apply-a-fallback-when-coder-does-not-fit), with
these `sed` expressions instead of those of its step 2 (or in addition to them, if you already run
a fallback). For `-t 4`:

```
sudo sed -e '/^  coder:$/,/^    ttl: 0$/s/^      -t 16$/      -t 4/' \
  /mnt/tank/ai/stacks/local-agent-stack/stack/inference/llama-swap/config.yaml |
  sudo tee /mnt/tank/ai/appdata/llama-swap/config.yaml > /dev/null
```

For `OMP_WAIT_POLICY=PASSIVE`, which adds an `env` list to the `coder` entry:

```
sudo sed -e '/^  coder:$/,/^    ttl: 0$/s/^    cmd: |$/    env:\n      - "OMP_WAIT_POLICY=PASSIVE"\n    cmd: |/' \
  /mnt/tank/ai/stacks/local-agent-stack/stack/inference/llama-swap/config.yaml |
  sudo tee /mnt/tank/ai/appdata/llama-swap/config.yaml > /dev/null
```

Check the copy:

```
sudo grep -n -E '^ +-t [0-9]+$|"OMP_WAIT_POLICY' /mnt/tank/ai/appdata/llama-swap/config.yaml
```

The output is the `-t` line of `coder` with the thread count you chose, and for the second variant
also the line `- "OMP_WAIT_POLICY=PASSIVE"` above it. Then continue with steps 4 to 10 of the
fallback task, and repeat [Check the vision projector](#check-the-vision-projector). As with a
fallback, the copy does not follow the release: write it again with the same expressions after
every release update. To make the change part of the stack, propose it to
`stack/inference/llama-swap/config.yaml` through the workflow of Chapter 8, with your
measurements.

## Tool calls on the local models

The agents depend on the model calling tools in the exact format that llama-server parses. This
topic lists what is known about tool calls in the llama.cpp build of the stack and shows how to see
the requests of a failing call. Chapter 9 tests tool calls
([Test tool calls on the OpenAI route](#test-tool-calls-on-the-openai-route)), and Chapter 11 gives
the order in which to look for causes ([Tool calls fail or loop](#tool-calls-fail-or-loop)).

### Known tool-call problems of this build

- **A call inside the thinking block (llama.cpp issue 20837).** Qwen3.5 and Qwen3.6 models
  sometimes write a tool call into their reasoning, and the answer ends without a call. The issue
  was closed on 14 November 2026 by commit `3c31179`. The stack's build, `b12407`, contains that
  commit: in the llama.cpp repository, `b12407` is 16 commits after it. The commit's final change,
  however, touches only the Ministral-3 parser and the chat tests, so the problem may still occur
  with the Qwen models of this stack. Watch for a turn that stops while the agent was about to use a
  tool: the answer has `finish_reason` `stop`, no `tool_calls`, and a `<tool_call>` text in
  `content` or `reasoning_content`. Retry the turn, as Chapter 11 describes. `local-fast` runs with
  thinking off and writes no reasoning to put a call into.
- **Parallel tool calls.** One answer can carry several tool calls. llama-server `b12407` returns
  several calls only when the request's `parallel_tool_calls` field is `true` or, if the request
  does not set the field, when the model's chat template declares support for them (read in the
  llama.cpp source of `b12407`). Whether OpenCode and Claude Code set the field was not verified.
  Local models produce several calls in one answer less reliably than Claude does. If a session's
  failures cluster on answers with several calls, capture them with the next task and report an
  issue: switching parallel calls off is a change to the release's configuration, made through
  Chapter 8 and tested with the evaluation gate of Chapter 9.

To see whether the chat template of `coder` declares parallel tool calls, ask its `llama-server`
for its properties:

```
sudo docker exec llama-swap sh -c 'printf "Authorization: Bearer %s\n" "$LLAMA_SWAP_API_KEY" |
  curl -fsS -H @- http://127.0.0.1:8080/upstream/coder/props' |
  python3 -c "import json, sys; \
    print(json.load(sys.stdin)['chat_template_caps'].get('supports_parallel_tool_calls'))"
```

The output is `True` or `False`.

### Capture requests while you debug tool calls

#### About this task

With `captureBuffer: 0`, llama-swap keeps no request or response bodies. While you debug a failing
tool call, a capture buffer lets llama-swap's web interface at
`https://models.lab.example.com/ui` show the recent requests and responses, with the tools the
client sent and the calls that the model returned. The release's file stays unchanged: as for the
fallbacks of `coder`, a copy under `/mnt/tank/ai/appdata/llama-swap` with `captureBuffer: 5` (5 MB)
replaces it through a compose override file.

!!! warning
    Captured requests hold whole prompts: the files that the agent read, command output, and any
    secret that passed through a session. Anyone with the llama-swap key can read them in the web
    interface. Capture only while you debug, and turn the capture off again with steps 8 and 9.

!!! caution
    Do not run `deploy.py apply` while the capture is on. The override is not listed in your
    desired-state file, so `apply` writes the release's YAML back and turns the capture off.

#### Steps

1. Check whether a fallback of `coder` is in place:

        sudo ls /mnt/tank/ai/appdata/llama-swap 2>/dev/null

    If the output lists `config.yaml` and `fallback.override.yaml`, a fallback from
    [Apply a fallback when coder does not fit](#apply-a-fallback-when-coder-does-not-fit) is in
    place. Otherwise the output is empty.

2. Without a fallback, create the directory and write a copy of the release's file with the capture
   buffer on:

        sudo install -d /mnt/tank/ai/appdata/llama-swap
        sudo sed -e 's/^captureBuffer: 0$/captureBuffer: 5/' \
          /mnt/tank/ai/stacks/local-agent-stack/stack/inference/llama-swap/config.yaml |
          sudo tee /mnt/tank/ai/appdata/llama-swap/config.yaml > /dev/null

    With a fallback, change its copy instead:

        sudo sed -i 's/^captureBuffer: 0$/captureBuffer: 5/' /mnt/tank/ai/appdata/llama-swap/config.yaml

3. Verify the copy:

        sudo grep -n '^captureBuffer' /mnt/tank/ai/appdata/llama-swap/config.yaml

    The output is one line that ends in `captureBuffer: 5`.

4. Without a fallback, write the override file and change the app's YAML with steps 4 to 7 of
   [Apply a fallback when coder does not fit](#apply-a-fallback-when-coder-does-not-fit). Do not
   add the override to your desired-state file. With a fallback, redeploy the app instead:

        sudo midclt call -j app.redeploy ai-inference

5. Confirm that `llama-swap` reads the copy:

        sudo docker inspect llama-swap --format '{{range .Mounts}}{{println .Destination .Source}}{{end}}' | grep /app/config.yaml

    The output is `/app/config.yaml /mnt/tank/ai/appdata/llama-swap/config.yaml`.

6. Repeat the failing request from the client, for example the same prompt in a new OpenCode
   session.

7. On a workstation, open `https://models.lab.example.com/ui` in a browser. It asks for a user name
   and a password and accepts the llama-swap key as the password; display the key on TrueNAS with
   `sudo sed -n 's/^LLAMA_SWAP_API_KEY=//p' /mnt/tank/ai/secrets/inference.env`. Open the recent
   requests of `coder` and read the captured request and response. The labels of llama-swap's
   interface are not described in this guide.

8. Turn the capture off. With a fallback, change its copy back and redeploy:

        sudo sed -i 's/^captureBuffer: 5$/captureBuffer: 0/' /mnt/tank/ai/appdata/llama-swap/config.yaml
        sudo midclt call -j app.redeploy ai-inference

    Without a fallback, edit the app, replace **Custom Config** with the four lines of
    `stack/inference/truenas-app.yaml` from
    [Install ai-inference with Install via YAML](#install-ai-inference-with-install-via-yaml), click
    **Save**, and delete the copy and the override file:

        sudo rm /mnt/tank/ai/appdata/llama-swap/config.yaml /mnt/tank/ai/appdata/llama-swap/fallback.override.yaml

9. Confirm the configuration that `llama-swap` reads:

        sudo docker inspect llama-swap --format '{{range .Mounts}}{{println .Destination .Source}}{{end}}' | grep /app/config.yaml

    Without a fallback, the source is
    `/mnt/tank/ai/stacks/local-agent-stack/stack/inference/llama-swap/config.yaml`. With a
    fallback, it is the copy, and
    `sudo grep -n '^captureBuffer' /mnt/tank/ai/appdata/llama-swap/config.yaml` ends in
    `captureBuffer: 0`.

#### Results

You have read the requests and responses of the failing call, and llama-swap keeps no request
bodies again. Attach the relevant part, with every secret and private address removed, to the issue
that you report.

## Reach the models while LiteLLM is down

Every client of the stack goes through LiteLLM. If `litellm` or `litellm-db` fails, OpenCode,
Claude Code and Open WebUI get errors, while `llama-swap` keeps serving at
`https://models.lab.example.com`. This topic describes that direct route as a stopgap while you
repair LiteLLM with Chapter 11 ([LiteLLM gateway issues](#litellm-gateway-issues)).

### What llama-swap serves without LiteLLM

llama-swap answers the same two API formats as LiteLLM: `/v1/chat/completions` in the OpenAI format
and `/v1/messages` with `/v1/messages/count_tokens` in the Anthropic format, plus `/v1/embeddings`
and `/v1/rerank`. It knows only its own model ids, `coder`, `coder-fast`, `coder-moe`, `embed` and
`rerank`, not the `local-*` names, and it accepts only `LLAMA_SWAP_API_KEY`.

What the direct route loses:

- **No client keys.** Every request uses the server's one llama-swap key: no model allowlists, no
  budgets and no usage logs. The key also opens llama-swap's `/api` routes and its web interface,
  which load and unload models.
- **No OpenCode.** OpenCode's global policies allow only the provider `local`, whose models are the
  LiteLLM names, so OpenCode cannot be pointed at llama-swap without changing the release's
  configuration. Open WebUI also reaches its models only through LiteLLM.
- **Claude Code only from `c4dev`.** The next task reads the key from the workstation's copy of
  `inference.env`, which only `c4dev` holds. Do not copy the key to another machine or into a
  project; if it leaves `c4dev`, rotate it afterwards
  ([Rotate the llama-swap key](#rotate-the-llama-swap-key)).

### Check llama-swap directly from the workstation

#### Steps

1. On `c4dev`, read the llama-swap key from your copy of `inference.env`. The value is not printed:

        LSK=$(sed -n 's/^LLAMA_SWAP_API_KEY=//p' ~/.config/local-agent-stack/secrets/inference.env)

2. Send a request in the OpenAI format to `coder-fast`. Replace `lab.example.com` with your domain:

        printf 'Authorization: Bearer %s\n' "$LSK" |
          curl -sS -H @- -H 'Content-Type: application/json' \
            -d '{"model": "coder-fast", "max_tokens": 16,
                 "messages": [{"role": "user", "content": "Reply with the single word OK."}]}' \
            https://models.lab.example.com/v1/chat/completions |
          python3 -c "import json, sys; d = json.load(sys.stdin); \
            print(d['choices'][0]['message']['content'] if 'choices' in d else d)"

    The output is `OK`.

3. Send a request in the Anthropic format:

        printf 'Authorization: Bearer %s\n' "$LSK" |
          curl -sS -H @- -H 'Content-Type: application/json' -H 'anthropic-version: 2023-06-01' \
            -d '{"model": "coder-fast", "max_tokens": 16,
                 "messages": [{"role": "user", "content": "Reply with the single word OK."}]}' \
            https://models.lab.example.com/v1/messages |
          python3 -c "import json, sys; d = json.load(sys.stdin); \
            print(''.join(b.get('text', '') for b in d.get('content', []) \
            if b.get('type') == 'text') or d)"

    The output is `OK`.

4. Clear the variable:

        unset LSK

#### Results

llama-swap serves both API formats without LiteLLM. If it does not, the problem is not in LiteLLM:
check `ai-inference` with [Verify the models load](#verify-the-models-load).

### Run Claude Code against llama-swap while LiteLLM is down

#### Prerequisites

- `claude-local` works on `c4dev` when LiteLLM is up
  ([Start Claude Code with claude-local](#start-claude-code-with-claude-local), Chapter 7).
- `~/.config/local-agent-stack/secrets/inference.env` is on `c4dev` (Chapter 3).

#### About this task

`claude-local` points Claude Code at LiteLLM. A second settings file points it at llama-swap
instead, with the llama-swap ids as the model names. Its key helper reads the llama-swap key from
the workstation's copy of `inference.env` when Claude Code needs it, so the key is not written into
the settings and the commands that Claude Code runs do not inherit it. The file holds no secret;
keep it for the next outage.

!!! note
    Claude Code against llama-swap's `/v1/messages` directly was not tested. The research of this
    release names this route as the fallback; the settings follow those of `claude-local`
    (Chapter 7, [Claude Code settings for the gateway](#claude-code-settings-for-the-gateway)).

#### Steps

1. On `c4dev`, write the settings file:

        cat > ~/.config/local-agent-stack/claude-fallback.json <<'EOF'
        {
          "env": {
            "ANTHROPIC_BASE_URL": "https://models.lab.example.com",
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "coder",
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "coder",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": "coder-fast",
            "ANTHROPIC_MODEL": "coder",
            "CLAUDE_CODE_SUBAGENT_MODEL": "coder",
            "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "65536",
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "16384",
            "CLAUDE_CODE_ATTRIBUTION_HEADER": "0",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_TELEMETRY": "1"
          },
          "apiKeyHelper": "sed -n 's/^LLAMA_SWAP_API_KEY=//p' \"$HOME/.config/local-agent-stack/secrets/inference.env\"",
          "skipWebFetchPreflight": true
        }
        EOF

2. Put your domain into the file, from the `LAB_DOMAIN` that the profile block of Chapter 7 exports:

        sed -i "s/lab\.example\.com/$LAB_DOMAIN/" ~/.config/local-agent-stack/claude-fallback.json

3. Check the file:

        python3 -m json.tool ~/.config/local-agent-stack/claude-fallback.json > /dev/null && echo valid
        grep -c "https://models.$LAB_DOMAIN" ~/.config/local-agent-stack/claude-fallback.json

    The output is `valid` and `1`.

4. Run a headless request in a repository:

        CLAUDE_CODE_MAX_CONTEXT_TOKENS=65536 claude --settings ~/.config/local-agent-stack/claude-fallback.json -p "Reply with the word OK."

    The answer is `OK`.

5. Start an interactive session with the same command without `-p "..."`, and work as usual. When
   LiteLLM works again, return to `claude-local`.

#### Results

Claude Code works against llama-swap while LiteLLM is down. The requests of this session do not
appear in LiteLLM's usage logs.

## Use the fast profile

The fast profile serves `coder-moe`, Qwen3.6-35B-A3B, under the name `local-coder-moe`. It
generates faster than `coder` and is weaker on long, multi-step agent work. Use it for interactive
edits and short tasks, for a whole working session at a time.

### What the fast profile costs

Table: Default and fast profiles compared

| Property | Default (`local-coder`) | Fast (`local-coder-moe`) |
|---|---|---|
| Model and placement | Qwen3.8-27B, entirely on the GPU | Qwen3.6-35B-A3B, experts of 16 layers in system RAM |
| VRAM in use on the card | About 14.3 GiB of model, KV cache and buffers (estimate), plus the CUDA context | About 15.7 GiB in total, CUDA context included (measured on an RTX 4080 SUPER) |
| System RAM | Vision projector about 1 to 1.5 GiB (estimate), prompt cache up to 6 GiB | About 8 GB of experts, vision projector about 1 to 1.5 GiB (estimate), prompt cache up to 6 GiB |
| Images | Projector on the CPU with 16 threads, about 11 s per image (estimate) | Own projector on the CPU with 8 threads, about twice as long (estimate) |
| Generation | 40 to 45 tokens/s, 50 to 65 with MTP (estimates) | 65 to 80 tokens/s (80 measured elsewhere) |
| Prompt processing | About 900 to 1,500 tokens/s (estimate) | About 1,800 to 2,000 tokens/s (measured elsewhere) |
| Agentic strength | Terminal-Bench 2.1: 73.0 (vendor figure) | Terminal-Bench 2.1: 44.38, SWE-bench Verified: 70.12 (NVIDIA's re-run); community reports of losing the plan on long runs |

The two VRAM figures measure different things. The 15.7 GiB of `coder-moe` is read as the memory in
use on the whole card, as `nvidia-smi` reports it, with the CUDA context of the process included
(the measurement's source gives the total only); it compares with the card's total of about
16,376 MiB (16.0 GiB). The 15.5 GiB that Chapter 2 gives as usable is what remains for a model's own
allocations after that context (an assumption for a headless card). Read that way, `coder-moe` fits
with about 0.3 GiB to spare; with `--n-cpu-moe 14` instead of 16, the measured run overflowed. Read
your own figure in step 4 of [Switch to the fast profile](#switch-to-the-fast-profile); if
`memory.used` reaches the card's total, the model does not fit.

The profiles share one GPU, and only one of the two models is loaded at a time:

- **The first request for `local-coder-moe` swaps `coder` out of the GPU**, which takes tens of
  seconds, and the next request for any name based on `coder` swaps it back. The names based on
  `coder` are `local-coder`, `local-fast`, `local-opus`, `local-sonnet` and `local-haiku`.
- **Background requests swap too.** OpenCode names its sessions with `local-fast`, Claude Code sends
  its background requests to `local-haiku`, and Open WebUI's default model is `local-coder`. Any of
  them, from any client, swaps `coder` back in while you work with the fast profile.
- **System RAM is tighter.** With `coder-moe` loaded, about 8 GiB more system memory is in use
  for its experts, and the estimated free memory is at its lowest
  ([System RAM budget](#system-ram-budget), Chapter 2). The vision projector of the loaded model
  takes about 1 to 1.5 GiB in either profile (estimate); the two projectors are never loaded
  together. The embedding and reranking models stay loaded either way.

!!! note
    The 32 GiB memory limit of the `llama-swap` container is sized from an estimate: with
    `coder-moe`, the container peaks at about 18 to 22 GiB (8 GB of experts, up to 6 GiB of prompt
    cache and the host buffers, the vision projector, and the CPU models). Check the real peak with
    `docker stats` while the fast profile is under load, as in the task below. If the usage
    approaches the limit, the kernel stops the model process inside the container.

### Switch to the fast profile

#### About this task

A client selects the fast profile by requesting `local-coder-moe`; nothing changes on the server.
This task switches from the TrueNAS shell, to see the swap and its cost. From Chapter 7 on, select
`local/local-coder-moe` in OpenCode for a whole session, for example
`opencode run --model local/local-coder-moe "<task>"`.

#### Steps

1. Refresh `sudo` and read the master key:

        sudo -v
        MK=$(sudo sed -n 's/^LITELLM_MASTER_KEY=//p' /mnt/tank/ai/secrets/inference.env)

2. Send a request to `local-coder-moe`:

        printf 'Authorization: Bearer %s\n' "$MK" |
          sudo docker exec -i llama-swap curl -sS -H @- -H 'Content-Type: application/json' \
            -d '{"model": "local-coder-moe", "max_tokens": 1024,
                 "messages": [{"role": "user", "content": "Reply with the single word OK."}]}' \
            http://litellm:4000/v1/chat/completions |
          python3 -c "import json, sys; d = json.load(sys.stdin); \
            print(d['choices'][0]['message']['content'] if 'choices' in d else d)"

    The answer takes longer than usual while llama-swap loads the model, then the output is `OK`.

3. List the loaded models:

        sudo docker exec llama-swap sh -c 'printf "Authorization: Bearer %s\n" "$LLAMA_SWAP_API_KEY" |
          curl -fsS -H @- http://127.0.0.1:8080/running' |
          python3 -c "import json, sys; \
            [print(m['model'], m['state']) for m in json.load(sys.stdin)['running']]"

    The output lists `coder-moe`, `embed` and `rerank` as `ready`; `coder` is no longer listed.

4. Check the GPU memory:

        nvidia-smi --query-gpu=memory.used --format=csv

    `memory.used` is about 16,000 MiB.

5. Check the memory of the `llama-swap` container:

        sudo docker stats --no-stream llama-swap

    **MEM USAGE / LIMIT** shows the container's usage against its 32 GiB limit.

6. Check that `coder-moe` loaded its own vision projector:

        sudo docker exec llama-swap sh -c 'printf "Authorization: Bearer %s\n" "$LLAMA_SWAP_API_KEY" |
          curl -fsS -H @- http://127.0.0.1:8080/upstream/coder-moe/props' |
          grep -o '"vision":[a-z]*'
        sudo docker logs llama-swap 2>&1 | grep 'loaded multimodal model' | tail -n 1

    The output is `"vision":true`, then a line that ends in
    `loaded multimodal model, '/models/gguf/mmproj-Qwen3.6-35B-A3B-Q8_0.gguf'`.

#### Results

The fast profile is loaded, with its vision projector. The `-t` and `--n-cpu-moe` values of
`coder-moe` are starting points; Chapter 9 measures them on your system in
[Tune and record the fast profile](#tune-and-record-the-fast-profile).

### Return to the default profile

#### Steps

1. Send a request to a name based on `coder`:

        printf 'Authorization: Bearer %s\n' "$MK" |
          sudo docker exec -i llama-swap curl -sS -H @- -H 'Content-Type: application/json' \
            -d '{"model": "local-fast", "max_tokens": 16,
                 "messages": [{"role": "user", "content": "Reply with the single word OK."}]}' \
            http://litellm:4000/v1/chat/completions |
          python3 -c "import json, sys; d = json.load(sys.stdin); \
            print(d['choices'][0]['message']['content'] if 'choices' in d else d)"

    The output is `OK` after `coder` has loaded.

2. Confirm that `coder` is loaded again, with the command of step 3 of the previous task.

    The output lists `coder`, `embed` and `rerank` as `ready`.

3. Clear the master key from the shell:

        unset MK

#### Results

The default model is loaded for every client. At the end of a fast-profile session, always send one
request to a name based on `coder`, so that the next client does not wait for the swap.

#### Next steps

Continue with Chapter 5, [Overview of the edge app](#overview-of-the-edge-app), to install the
edge app, which gives the gateway its address `https://llm.lab.example.com`.
