# ai-inference

The model-serving app of the stack: llama.cpp behind llama-swap on the GPU, and the LiteLLM gateway
that every client uses. The design is `docs/stack-design.md` (sections 1, 2, 4, 5 and 6); the
reasons are in `docs/research/b-inference.md` and `docs/research/a-models.md`.

## Files

| File | What it is |
|---|---|
| `compose.yaml` | Services `llama-swap` (GPU), `litellm` and `litellm-db` on the external network `ai-net`, no published ports, images pinned by tag and digest |
| `llama-swap/config.yaml` | Model ids `coder`, `coder-fast` (alias: thinking off), `coder-moe`, `embed`, `rerank`; swap group `llm`, persistent CPU-only group `rag` |
| `litellm/config.yaml` | Client-facing names `local-coder`, `local-fast`, `local-coder-moe`, `local-opus`, `local-sonnet`, `local-haiku`, `local-embed`, `local-rerank`; master key and database from the environment, spend logs on, no cloud providers |
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

| File | Hugging Face repository | Size |
|---|---|---|
| `Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf` | `ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF` | 12.12 GB |
| `Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf` | `unsloth/Qwen3.6-35B-A3B-GGUF` | 22.36 GB |
| `Qwen3-Embedding-0.6B-Q8_0.gguf` | `Qwen/Qwen3-Embedding-0.6B-GGUF` | 0.64 GB |
| `qwen3-reranker-0.6b-q8_0.gguf` | `ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF` | 0.64 GB |

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

Use `/health/liveliness` and `/health/readiness` for probes. `GET /health` on LiteLLM sends a
real request to every model, which loads `coder-moe` and swaps `coder` out of the GPU; to check one
model, use `/health?model=local-coder`.

## Memory

| Model | VRAM | Host RAM |
|---|---|---|
| `coder` (64K, q8_0 KV, MTP) | about 14-15 GiB (estimate) | prompt cache up to 6 GiB |
| `coder-moe` (64K, 16 expert layers in RAM) | about 15.7 GiB (measured elsewhere) | about 8 GB of experts plus prompt cache up to 6 GiB |
| `embed`, `rerank` (CPU only) | none | about 1.3 GiB each |

Only one of `coder` and `coder-moe` is loaded at a time. The `llama-swap` container is capped at
32 GiB of RAM, `litellm` at 6 GiB and `litellm-db` at 2 GiB.
