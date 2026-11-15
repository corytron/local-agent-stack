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

The stack serves four GGUF model files, 35.76 GB (33.3 GiB) in total, from public Hugging Face
repositories. No Hugging Face account is needed. The files go to `/mnt/tank/ai/models/gguf`, on the
`tank/ai/models` dataset that Chapter 3 created with a 1M record size and `primarycache=metadata`.

Each download URL names a fixed revision (commit) of its repository, checked on 15 November 2026,
so the file sizes and SHA-256 checksums below stay valid even if a repository changes later.

Table: Model files to download

| File | Hugging Face repository | Size in bytes | llama-swap id |
|---|---|---|---|
| `Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf` | `ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF` | 12120016960 (12.12 GB) | `coder` |
| `Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf` | `unsloth/Qwen3.6-35B-A3B-GGUF` | 22360456160 (22.36 GB) | `coder-moe` |
| `Qwen3-Embedding-0.6B-Q8_0.gguf` | `Qwen/Qwen3-Embedding-0.6B-GGUF` | 639150592 (0.64 GB) | `embed` |
| `qwen3-reranker-0.6b-q8_0.gguf` | `ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF` | 639153184 (0.64 GB) | `rerank` |

### Check the free space for the models

#### Prerequisites

- The dataset `tank/ai/models` exists with its properties set
  ([Create the parent and models datasets](#create-the-parent-and-models-datasets)).

#### Steps

1. Create the directory for the model files:

        sudo install -d /mnt/tank/ai/models/gguf

2. Display the free space of the models dataset:

        df -h /mnt/tank/ai/models

    The **Avail** column shows at least `34G`. The four files need 33.3 GiB.

### Start the model downloads

#### About this task

Each file is downloaded by `curl` in a throwaway container of the llama-swap image, the same image
that the `ai-inference` app runs. Nothing is installed on TrueNAS, the first download pulls the
image that the app needs anyway, and the downloads continue in the background if you close the
shell. The four containers, `dl-coder`, `dl-coder-moe`, `dl-embed` and `dl-rerank`, run at the same
time; each one downloads one file and stops. `-C -` makes `curl` continue a partial file instead of
starting again.

#### Steps

1. Store the image name in a shell variable for the commands that follow:

        IMG=ghcr.io/mostlygeek/llama-swap:v273-cuda-b12407
        IMG=$IMG@sha256:8fd9f1cfe9e96cddf53fbdc5cb2683b19633ab49b1a41a406e6239376ead65e6

    The variable lasts until the shell closes. In a new shell, run this step again.

2. Start the download of the `coder` model:

        REPO=ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF
        REV=d562806dbafae37109975e970aae91b43e73b440
        FILE=Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf
        sudo docker run -d --name dl-coder -e NVIDIA_VISIBLE_DEVICES=void \
          -v /mnt/tank/ai/models/gguf:/gguf --entrypoint curl "$IMG" \
          -fsSL --retry 5 -C - -o "/gguf/$FILE" \
          "https://huggingface.co/$REPO/resolve/$REV/$FILE"

    Docker pulls the image the first time, then prints the ID of the new container.

3. Start the download of the `coder-moe` model:

        REPO=unsloth/Qwen3.6-35B-A3B-GGUF
        REV=a483e9e6cbd595906af30beda3187c2663a1118c
        FILE=Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf
        sudo docker run -d --name dl-coder-moe -e NVIDIA_VISIBLE_DEVICES=void \
          -v /mnt/tank/ai/models/gguf:/gguf --entrypoint curl "$IMG" \
          -fsSL --retry 5 -C - -o "/gguf/$FILE" \
          "https://huggingface.co/$REPO/resolve/$REV/$FILE"

4. Start the download of the embedding model:

        REPO=Qwen/Qwen3-Embedding-0.6B-GGUF
        REV=370f27d7550e0def9b39c1f16d3fbaa13aa67728
        FILE=Qwen3-Embedding-0.6B-Q8_0.gguf
        sudo docker run -d --name dl-embed -e NVIDIA_VISIBLE_DEVICES=void \
          -v /mnt/tank/ai/models/gguf:/gguf --entrypoint curl "$IMG" \
          -fsSL --retry 5 -C - -o "/gguf/$FILE" \
          "https://huggingface.co/$REPO/resolve/$REV/$FILE"

5. Start the download of the reranking model:

        REPO=ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF
        REV=a02f48bb4f057028298c21fa033da2b30d7742d5
        FILE=qwen3-reranker-0.6b-q8_0.gguf
        sudo docker run -d --name dl-rerank -e NVIDIA_VISIBLE_DEVICES=void \
          -v /mnt/tank/ai/models/gguf:/gguf --entrypoint curl "$IMG" \
          -fsSL --retry 5 -C - -o "/gguf/$FILE" \
          "https://huggingface.co/$REPO/resolve/$REV/$FILE"

6. Follow the progress. Run the command again from time to time; the file sizes grow:

        ls -l /mnt/tank/ai/models/gguf

7. Wait until every download has stopped:

        sudo docker wait dl-coder dl-coder-moe dl-embed dl-rerank

    The command returns when the last container stops, and prints one exit code per container.
    Four lines of `0` mean that every download completed.

8. If a line is not `0`, display the error of that container, for example `dl-coder-moe`:

        sudo docker logs dl-coder-moe

    Remove the container with `sudo docker rm dl-coder-moe` and run its command from steps 2 to 5
    again. `curl` continues from where the file stopped.

9. Remove the download containers:

        sudo docker rm dl-coder dl-coder-moe dl-embed dl-rerank

#### Results

The four model files are in `/mnt/tank/ai/models/gguf`, and the llama-swap image is in the local
image store.

### Verify the model files

#### Steps

1. List the files with their sizes in bytes:

        ls -l /mnt/tank/ai/models/gguf

    The four files have exactly the sizes in the table above.

2. Change to the model directory:

        cd /mnt/tank/ai/models/gguf

3. Compare the SHA-256 checksum of each file with the value that Hugging Face publishes for that
   revision. Paste the whole block; reading 35.8 GB takes a few minutes. Each entry is split over
   two lines; the shell joins the lines that end with a backslash:

        sha256sum -c <<EOF
        58fd826723939933dc86f45b7fe04545cbc2de1c70f6fe2cdd3858c87a98c12f  \
        Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf
        707a55a8a4397ecde44de0c499d3e68c1ad1d240d1da65826b4949d1043f4450  \
        Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf
        06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439  \
        Qwen3-Embedding-0.6B-Q8_0.gguf
        22c9979ce4fbcdc5acdc310c6641c32797eff1aa980b8f7a2db8a8ea23429a48  \
        qwen3-reranker-0.6b-q8_0.gguf
        EOF

    The output has four lines, each a file name followed by `OK`.

4. If a line reads `FAILED`, delete that file, for example
   `sudo rm /mnt/tank/ai/models/gguf/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf`, download it again as in
   [Start the model downloads](#start-the-model-downloads), and repeat this task.

5. Return to your home directory:

        cd

#### Results

The model files are complete and match the published checksums. The `llama-swap` container mounts
`/mnt/tank/ai/models` read-only at `/models`, so it finds them at `/models/gguf/`.

!!! note
    The model files are not backed up (Appendix A). After a loss of the `tank/ai/models` dataset,
    repeat this topic to restore them.

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
from this example file:

{{ include stack/inference/inference.env.example }}

!!! caution
    Never change `LITELLM_SALT_KEY` after the first start of LiteLLM; it encrypts what LiteLLM stores
    in its database. `LITELLM_DB_PASSWORD` is fixed when the database is first created; a new value
    in `inference.env` alone locks LiteLLM out of its database.

### llama-swap global settings

{{ include stack/inference/llama-swap/config.yaml lines=13-50 }}

Table: llama-swap global settings

| Setting | Effect |
|---|---|
| `healthCheckTimeout: 600` | A model may take up to 600 seconds to become ready. Reading a 12 GB file from disk with a cold cache takes longer than the default 120 seconds |
| `logToStdout: "proxy,upstream"` | The container log carries llama-swap's own lines and the output of every `llama-server`, including the CPU backend line and the "Forcing full prompt re-processing" warnings |
| `startPort: 10001` | Each `llama-server` listens on `127.0.0.1`, port 10001 and up, inside the container |
| `sendLoadingState: false` | No "loading" text is injected into the reasoning field while a model loads; Claude Code and OpenCode would take it for model output |
| `globalTTL: 0` | No model is unloaded on a timer; the groups decide (below) |
| `captureBuffer: 0` | No request or response bodies are kept in llama-swap's memory (default 5 MB), for privacy |
| `helpagent: disable: true` | The UI's help chat is off; it would load a model of its own choice and swap the GPU model |
| `apiKeys` | Every inference and `/api` route needs `LLAMA_SWAP_API_KEY`, as a Bearer token, a Basic password or an `x-api-key` header. `/health` stays open for the health check |
| `macros` | `server` starts `llama-server` on loopback with Prometheus metrics (`/upstream/<id>/metrics`) and without its own web UI; `gguf` is the model directory |

### The coder model entry

`coder` is the primary agent model, Qwen3.8-27B, entirely on the GPU with a 64K context.

{{ include stack/inference/llama-swap/config.yaml lines=75-109 }}

Table: Flags of the coder model

| Flag | Effect |
|---|---|
| `-ngl 99 -fa on` | All 64 layers on the GPU, flash attention on |
| `-c 65536 -np 1` | One slot with the full 64K context. Concurrent requests queue; an idle slot's prompt moves to the prompt cache in host RAM instead of being computed again |
| `-ctk q8_0 -ctv q8_0` | KV cache at 8 bits. Do not lower it to `q4_0`: llama.cpp warns that it can substantially degrade tool calling |
| `-b 2048 -ub 512` | llama.cpp's default batch sizes, written out; the benchmark in this chapter tries larger `-ub` values against the VRAM |
| `-t 4` | Generation runs on the GPU and needs few CPU threads |
| `-ot token_embd.weight=CPU` | Keeps the token embeddings, a lookup table of about 0.6 GiB, in system RAM to make room in VRAM |
| `--cache-ram 6144` | Up to 6 GiB of host RAM for the prompt cache |
| `--jinja --reasoning-format deepseek --reasoning-effort medium` | The model's chat template, thinking returned in a separate reasoning field, medium effort |
| `--temp 1.0 --top-p 0.95 --top-k 20 --min-p 0.0` | The model card's sampling for thinking mode; a request may override them |
| `--spec-type draft-mtp --spec-draft-n-max 3` | Speculative decoding with the multi-token prediction (MTP) head inside the `-mtp` file, three draft tokens |
| `--no-mmproj` | No vision projector; it would cost 0.6 to 0.9 GiB of VRAM |

The entry sets no `--cache-reuse`: that option works by shifting the KV cache, which the model's
Gated DeltaNet layers cannot do. The `filters` block makes `coder-fast` an alias of `coder`: a
request for `coder-fast` is served by the same process, with thinking off and the model card's
non-thinking sampling written into the request. This is the fast and small-model role, with no
second model in VRAM. `presence_penalty` takes effect only on the OpenAI route.

!!! note
    Two properties of this entry are not verified on hardware. First, the VRAM saved by
    `-ot token_embd.weight=CPU` is not measured; the option has no effect if llama.cpp already keeps
    that tensor on the CPU. Second, it is an estimate that the weights, the 64K KV cache and the MTP
    draft context fit in 16 GB together, and it is not verified that llama.cpp b12407 loads the MTP
    head from this file. Check both with
    [Test that the coder model fits](#test-that-the-coder-model-fits) before you rely on the stack.

### The coder-moe model entry

`coder-moe` is the fast profile, Qwen3.6-35B-A3B, with the experts of 16 layers in system RAM.

{{ include stack/inference/llama-swap/config.yaml lines=125-140 }}

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
- Loading `coder-moe` unloads `coder`, and the other way round.

### The embedding and reranking model entries

{{ include stack/inference/llama-swap/config.yaml lines=150-176 }}

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

{{ include stack/inference/llama-swap/config.yaml lines=178-200 }}

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

{{ include stack/inference/litellm/config.yaml lines=29-105 }}

- **Anthropic route** (`anthropic/<id>`). LiteLLM appends `/v1/messages` to `api_base`, so Claude
  Code's requests reach llama-server's own Anthropic endpoint with no format conversion in LiteLLM.
  Do not route Claude Code through the `openai/` names.
- **OpenAI route** (`openai/<id>`). Chat completions and embeddings at `http://llama-swap:8080/v1`.
- **Rerank route** (`hosted_vllm/rerank`). LiteLLM posts the Cohere-style request to
  `http://llama-swap:8080/rerank` and returns `results` with `index` and `relevance_score`.
- `max_input_tokens: 65536` is what `/v1/models` and `/model/info` report. Claude Code's own window
  is set on the client (`CLAUDE_CODE_MAX_CONTEXT_TOKENS=65536`, Chapter 7).
- `cost_per_second: 0.0001` is a notional price per second of request time on the GPU models. At
  that price, a key budget of 50 allows 500,000 seconds, so budgets act as GPU-time quotas. The CPU
  models carry no price. Usage logs record tokens and duration for every request either way.

### LiteLLM gateway settings

{{ include stack/inference/litellm/config.yaml lines=107-138 }}

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

3. Enter the following YAML in **Custom Config**:

    {{ include stack/inference/README.md lines=24-27 }}

    On the workstation, `python3 tools/deploy.py render --app ai-inference` in the clone prints the
    same lines.

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

### Redeploy ai-inference after a change

#### About this task

A redeploy re-reads the included files and recreates every container of the app. Redeploy after
the clone moves to a new release tag (Chapter 10) and after you change a file that the app includes
or mounts, such as the override in
[Apply a fallback when coder does not fit](#apply-a-fallback-when-coder-does-not-fit). The GPU model
loads again, so clients wait for a minute or more.

#### Steps

1. Redeploy the app:

        sudo midclt call -j app.redeploy ai-inference

    The command waits for the redeploy job and prints its result.

2. Confirm that the running `coder` process uses the new configuration, by printing its command
   line:

        sudo docker exec llama-swap sh -c 'curl -fsS \
          -H "Authorization: Bearer $LLAMA_SWAP_API_KEY" http://127.0.0.1:8080/running' |
          python3 -c "import json, sys; \
            [print(m['model'], '|', ' '.join(m['cmd'].split())) \
             for m in json.load(sys.stdin)['running']]"

    Each line shows a loaded model and the flags it runs with.

!!! note
    llama-swap runs with `-watch-config` and reloads its configuration when the file changes. The
    configuration file is mounted as a single file, and it is not verified that llama-swap notices a
    file that `git` replaced, because a single-file mount keeps the old file. Always redeploy after
    a `git checkout` or `git pull` in the clone, and check the result with step 2.

## Verify the models load

These checks run on TrueNAS. The `llama-swap` container has `curl` and is on `ai-net`, so it can
reach both llama-swap and `litellm:4000`. Keys never appear on a command line: llama-swap's key is
expanded inside the container from its own environment, and the LiteLLM key is passed to `curl` on
standard input.

### Check the health endpoints

#### Steps

1. Check llama-swap:

        sudo docker exec llama-swap curl -fsS http://127.0.0.1:8080/health

    The output is `OK`.

2. List the loaded models and their state:

        sudo docker exec llama-swap sh -c 'curl -fsS \
          -H "Authorization: Bearer $LLAMA_SWAP_API_KEY" http://127.0.0.1:8080/running' |
          python3 -c "import json, sys; \
            [print(m['model'], m['state']) for m in json.load(sys.stdin)['running']]"

    The output lists `coder`, `embed` and `rerank`, each with the state `ready`. Loading `coder`
    takes a minute or more after a start; repeat the command until it shows `ready`.

3. Check LiteLLM and its database:

        sudo docker exec litellm python3 -c "import urllib.request as u; \
          print(u.urlopen('http://127.0.0.1:4000/health/readiness').read().decode())"

    The output contains `"status":"healthy"` and `"db":"connected"`.

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
    continue with [Test that the coder model fits](#test-that-the-coder-model-fits).

2. List the processes that use the GPU:

        nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv

    The list has one `llama-server` process, the `coder` model.

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
the model process the whole prompt again (Chapter 9 checks for it).

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
          sudo docker exec -i llama-swap sh -c 'curl -sS -d @- \
            -H "Authorization: Bearer $LLAMA_SWAP_API_KEY" \
            -H "Content-Type: application/json" http://127.0.0.1:8080/v1/chat/completions' |
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
open with `MK` set for the next topic.

## Create the LiteLLM keys for the workstations

The master key is for administration only. Each client gets its own LiteLLM virtual key, limited
to the model names it needs, so that the usage logs show which client sent each request and a key
can be revoked without affecting the others. This topic creates the keys of the two workstations.
Open WebUI gets its own key in Chapter 6, in
[Create the virtual key that Open WebUI uses](#create-the-virtual-key-that-open-webui-uses).

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

        (umask 077; read -rsp 'LiteLLM key: ' key; echo; \
          printf '%s\n' "$key" > ~/.config/local-agent-stack/secrets/litellm-c4dev.key)

2. Store the `mac` key in the same way:

        (umask 077; read -rsp 'LiteLLM key: ' key; echo; \
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

## Measure performance with bench.sh

`tools/bench.sh` measures the llama.cpp build of the stack on the server: whether a model
configuration fits in VRAM, how much GPU memory it holds, and its prompt and generation speed. Run
it now, before any client depends on the stack, to confirm that the `coder` configuration fits.
Chapter 9 uses the same tool to record a baseline and to tune the fast profile.

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
| `-m`, `--model FILE` | A file under `/models/gguf` in the container (required) |
| `--mode MODE` | `bench` or `server` |
| `-c`, `--contexts LIST` | `bench`: KV depths, default `0,16384,32768`. `server`: context sizes, default `32768,65536` |
| `-u`, `--ubatch LIST` | `-ub` values, default `512,1024,2048` |
| `-r`, `--reps N` | `bench`: repetitions per test, default 3 |
| `-g`, `--gen N` | Generated tokens per test, default 128 |
| `-f`, `--fill PCT` | `server`: share of the context that the prompt fills, default 75 |
| `--unload LIST` | llama-swap models to unload first, `all` or `none`; default `coder,coder-moe` |
| `--dry-run` | Print the Docker commands instead of running them |

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
allow several minutes per row.

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
          sudo docker exec -i llama-swap sh -c 'curl -sS -o /dev/null -w "%{http_code}\n" \
            -d @- -H "Authorization: Bearer $LLAMA_SWAP_API_KEY" \
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

!!! caution
    While the override is in place, `tools/deploy.py drift` reports `ai-inference` as different
    from the desired state, and `tools/deploy.py apply` replaces the app's YAML with the plain
    include, which removes the override. Repeat this task after every release update, so that the
    copy follows the release's file. To make a fallback permanent, change
    `stack/inference/llama-swap/config.yaml` in the repository through the workflow of Chapter 8.

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

#### Results

`coder` loads with the fallback configuration. To return to the release's configuration, edit the
app again, restore the single-path YAML of
[Install ai-inference with Install via YAML](#install-ai-inference-with-install-via-yaml), and save.

## Use the fast profile

The fast profile serves `coder-moe`, Qwen3.6-35B-A3B, under the name `local-coder-moe`. It
generates faster than `coder` and is weaker on long, multi-step agent work. Use it for interactive
edits and short tasks, for a whole working session at a time.

### What the fast profile costs

Table: Default and fast profiles compared

| Property | Default (`local-coder`) | Fast (`local-coder-moe`) |
|---|---|---|
| Model and placement | Qwen3.8-27B, entirely on the GPU | Qwen3.6-35B-A3B, experts of 16 layers in system RAM |
| VRAM | About 14.3 GiB (estimate) | About 15.7 GiB (measured on an RTX 4080 SUPER) |
| System RAM | Prompt cache up to 6 GiB | About 8 GB of experts plus the prompt cache up to 6 GiB |
| Generation | 40 to 45 tokens/s, 50 to 65 with MTP (estimates) | 65 to 80 tokens/s (80 measured elsewhere) |
| Prompt processing | About 900 to 1,500 tokens/s (estimate) | About 1,800 to 2,000 tokens/s (measured elsewhere) |
| Agentic strength | Terminal-Bench 2.1: 73.0 (vendor figure) | Terminal-Bench 2.1: 44.38, SWE-bench Verified: 70.12 (NVIDIA's re-run); community reports of losing the plan on long runs |

The profiles share one GPU, and only one of the two models is loaded at a time:

- **The first request for `local-coder-moe` swaps `coder` out of the GPU**, which takes tens of
  seconds, and the next request for any name based on `coder` swaps it back. The names based on
  `coder` are `local-coder`, `local-fast`, `local-opus`, `local-sonnet` and `local-haiku`.
- **Background requests swap too.** OpenCode names its sessions with `local-fast`, Claude Code sends
  its background requests to `local-haiku`, and Open WebUI's default model is `local-coder`. Any of
  them, from any client, swaps `coder` back in while you work with the fast profile.
- **System RAM is tighter.** With `coder-moe` loaded, the estimated free system memory drops from
  about 20 GiB to about 12 GiB (Chapter 2). The embedding and reranking models stay loaded either
  way.

!!! note
    The 32 GiB memory limit of the `llama-swap` container is sized from an estimate: `coder-moe`
    peaks at about 18 GiB (8 GB of experts, up to 6 GiB of prompt cache, and the CPU models). Check
    the real peak with `docker stats` while the fast profile is under load, as in the task below. If
    the usage approaches the limit, the kernel stops the model process inside the container.

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

        sudo docker exec llama-swap sh -c 'curl -fsS \
          -H "Authorization: Bearer $LLAMA_SWAP_API_KEY" http://127.0.0.1:8080/running' |
          python3 -c "import json, sys; \
            [print(m['model'], m['state']) for m in json.load(sys.stdin)['running']]"

    The output lists `coder-moe`, `embed` and `rerank` as `ready`; `coder` is no longer listed.

4. Check the GPU memory:

        nvidia-smi --query-gpu=memory.used --format=csv

    `memory.used` is about 16,000 MiB.

5. Check the memory of the `llama-swap` container:

        sudo docker stats --no-stream llama-swap

    **MEM USAGE / LIMIT** shows the container's usage against its 32 GiB limit.

#### Results

The fast profile is loaded. The `-t` and `--n-cpu-moe` values of `coder-moe` are starting points;
Chapter 9 measures them on your system.

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

Continue with Chapter 5 to install the edge app, which gives the gateway its address
`https://llm.lab.example.com`.
