# Evaluations

Developer notes for `tools/eval.py` and the files in this directory. How the reader runs the
evaluations, reads the results and uses the gate is in the deployment guide, chapter 9
([Validating the deployment](../guide/chapters/09-validation.md)); this file is for whoever changes
the suites or the tool. The design is section 3 of
[docs/research/f-project-tooling.md](../docs/research/f-project-tooling.md), cut down to what runs
with the Python standard library from the workstation against the gateway.

## Layout

| Path | Contents |
|---|---|
| `sets.toml` | The suite order, the optional cases, and the run sets: `smoke` (15 pinned case IDs), `full` (every case but the optional ones) and `vision` (the optional image case) |
| `suites/<name>.jsonl` | One suite: a header line, then one case per line |
| `rag-docs/*.md` | The fictional documents of the `rag` suite (the reader may copy them to the `rag-docs` share) |
| `images/*.png` | Images the cases send (`maple-74.png`, 640x160, the text "MAPLE 74") |
| `images/make_images.py` | Draws those images with the standard library only (`--check` compares the committed files) |
| `gate.toml` | The thresholds of `tools/eval.py compare` |
| `results/` | Results files, `<UTC>-<model>-<set>.json`, committed |
| `baselines/` | Optional: copies of accepted results, one per model profile (`local-coder-full.json`) |

Partial runs (`--case`) are written to `build/evals/` (gitignored) and never pass `verify`.

## Commands

```
python3 tools/eval.py run --suite smoke|full|vision [--model local-coder] [--out FILE] [--baseline FILE]
python3 tools/eval.py compare BASELINE RESULT [--gate evals/gate.toml]
python3 tools/eval.py verify [--current] [RESULT ...]
python3 tools/eval.py config-hash [--files]
python3 tools/eval.py suites
```

`python3 tools/eval.py <command> --help` lists every option. The unit tests are
`tools/tests/test_eval.py` (a fake gateway on the loopback address; no model), run by
`tools/check.sh`'s `python` check.

## Suite files

The first line of `suites/<name>.jsonl` is the header: `suite` (the file's name), `kind` (`tools`,
`format`, `coding` or `rag`), `version` (an integer), `description`, and optionally `system`, the
system prompt of every case that has none of its own. Every other line is a case. Fields of every
case: `id` (`<suite>-NNN`), `title`, `api` (`openai`, the default, sends `/v1/chat/completions`;
`anthropic` sends `/v1/messages`), and optionally `max_tokens`, `system` and `extra_body` (fields
merged into the request body, such as `"parallel_tool_calls": true`).

| Kind | Fields | Passes when |
|---|---|---|
| `tools` | `tools` (`name`, `description`, `parameters` as JSON Schema; converted to each API's form), `messages` (in the case's API's own format, so multi-turn cases carry tool results), `expect.calls` (`name` and an `arguments` matcher per call; `[]` means no call), `expect.allow_extra`, `expect.text` (checks for a no-call answer), `reference` (`calls`, `text`) | Every expected call matches a different actual call, in any order; no extra calls unless allowed; no call and a text answer when none is expected |
| `format` | `messages`, `checks`, `reference` (text) | Every check passes on the answer text (stripped, CRLF made LF) |
| `coding` | `prompt`, `entry_point`, `tests` (Python statements run after the solution, in its namespace), `reference` (code), optional `timeout` | The hidden tests run without an exception in the sandbox |
| `rag` | `question`, `sources` (expected file names; `[]` when the documents do not hold the answer), `checks`, `reference` (text) | Every check passes; the suite's checks also require the cited file name |

In `tools` and `format` cases a message's `content` may be a list of parts in the case's API format,
plus one part of the harness's own: `{"type": "image_file", "path": "images/<name>.png"}` names a
PNG in `evals/images/`. `build_request` replaces it with the API's image part: on the OpenAI route
`{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}`, on the Anthropic route
`{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}}`.
`eval.py suites` refuses a path outside `evals/images/`, a missing file, a file that is not a PNG
and unknown keys.

Argument matchers and the `json_schema` check use a JSON Schema subset: `type` (an integer-valued
float counts as an integer, a boolean never as a number), `const`, `enum`, `pattern` (a Python
`re.search`), `minLength`, `maxLength`, `minimum`, `maximum`, `exclusiveMinimum`,
`exclusiveMaximum`, `properties`, `required`, `additionalProperties` (boolean or schema), `items`,
`minItems`, `maxItems`, `contains`, `uniqueItems`, `anyOf`, `allOf`, `oneOf`, `not`; `description`,
`title`, `default`, `examples` and `$comment` are ignored. Any other keyword is an error.

Checks: `exact` (`value`, optional `ignore_case`), `contains`, `regex` (`pattern`, `flags` of
`i`, `m`, `s`, `mode` `search` or `fullmatch`), `not_regex`, `json_equals` (the whole answer must
parse as JSON, so a code fence fails), `json_schema` (`schema`), `lines` (`count`, optional `each`
pattern that every stripped line must fully match).

### Changing a suite

- IDs are stable: never renumber or reuse one. A case whose meaning changes gets a new ID, or its
  suite a new `version`; results of an older version then fail `verify`, and `compare` notes the
  version change.
- Keep `sets.toml`'s smoke list a fixed subset that touches every suite and both APIs.
- `optional` in `sets.toml` lists cases that `cases = "all"` leaves out; they run only in a set
  that pins them. `format-011` (image input, OpenAI route) is optional until it has passed on the
  server with the vision projector loaded (`docs/v1.2-design.md` §3): run it with
  `--suite vision`. To make it part of `full`, remove it from `optional` and record new results.
- Images are drawn by `images/make_images.py` (add the file name and text to its `IMAGES`, run
  it, commit the PNG); `tools/tests/test_eval.py` checks that every committed PNG has exactly the
  pixels the script draws.
- `python3 tools/eval.py suites` must pass: every reference answer passes its own checks, every
  coding reference passes its hidden tests, and a stub that returns `None` fails them (so the
  tests check something). The unit tests run it too.
- Any change to `sets.toml`, `suites/`, `rag-docs/` or `images/*.png` changes the configuration
  hash, so existing results no longer match `verify --current`. Record new results in the same
  pull request.
- The RAG documents must stay fictional, with placeholders only (`192.0.2.x`, `example.com`).

## Results files

`schema` (`local-agent-stack/eval-result/1`), `harness` (tool version and Python version),
`created` (UTC), `duration_s`, `set`, `partial`, `model`, `anthropic_model`, `sampling`
(`temperature`, `seed`, `max_tokens`; `null` means the server's defaults), `rag_source`,
`sandbox`, `speed_min_tokens`, `config` (`sha256` and the sha256 of every input file), `suites`
(per suite: `version`, the suite file's `sha256`, cases, passed, failed, errors, `pass_rate` in
percent, `pass_rate_ci95` (Wilson), `median_tokens_per_s`, `median_latency_s`, token totals; the
`rag` suite also `source` and, from Open WebUI, `retrieval_hit_rate`), `overall` (the same
figures), and `cases` (per case: `id`, `suite`, `api`, `status` `pass`, `fail` or `error`, a short
`reason`, `latency_s`, `prompt_tokens`, `completion_tokens`, `tokens_per_s`, `finish`, and where
present `server_tokens_per_s` and `retrieval_hit`). No prompt, no answer, no key, no domain:
reasons are redacted for the key, the domain and anything shaped like an `sk-` key.

`tokens_per_s` is the completion tokens over the request's wall time (prefill included), recorded
for answers of at least 32 tokens; shorter answers measure overhead, not decoding.
`server_tokens_per_s` is llama-server's `timings.predicted_per_second` when the gateway passes it on.

## The configuration hash

The sha256 of a `sha256sum`-style manifest (`<sha256>  <path>` per line, sorted by path) of
`stack/inference/llama-swap/config.yaml`, `stack/inference/litellm/config.yaml`,
`stack/inference/compose.yaml` (the image builds), `stack/inference/models.sha256` (the model
files), `evals/sets.toml`, `evals/suites/*.jsonl`, `evals/rag-docs/*.md` and `evals/images/*.png`. The compose file
and the model checksums are there besides the two configs because a new llama.cpp build or model
file changes results as much as a flag does. `gate.toml` is left out on purpose: a threshold
changes the verdict, not the results. The same value by hand:

```
sha256sum stack/inference/llama-swap/config.yaml stack/inference/litellm/config.yaml \
  stack/inference/compose.yaml stack/inference/models.sha256 evals/sets.toml \
  evals/suites/*.jsonl evals/rag-docs/*.md evals/images/*.png | LC_ALL=C sort -k2 | sha256sum
```

## Design notes

- **One request at a time.** One GPU and one llama-server slot (`-np 1`): parallel requests queue
  and distort latency. A warm-up request per API route runs first, so a model swap is not timed.
  `--jobs` (default `JOBS` or `nproc`) applies only to offline work: coding tests, `verify`,
  `suites`. The coding tests of a run start while later requests are still on the GPU.
- **Models.** `--model` names the OpenAI-route model; Anthropic-route cases use `local-sonnet` for
  `local-coder`, `local-haiku` for `local-fast`, else the same name (LiteLLM converts it), or
  `--anthropic-model`.
- **Thinking.** `local-coder` thinks before it answers, so `max_tokens` defaults are generous:
  4096, and 8192 for coding. A case that runs out fails with `max_tokens reached before an answer`.
  Sampling is the server's (the production settings) unless `--temperature` or `--seed` is given.
- **Parallel tool calls.** The OpenAI-route parallel cases send `"parallel_tool_calls": true` in
  `extra_body`: the research notes disagree on llama-server's default (a-models: off unless set;
  b-inference: the chat template's capability). The Anthropic route has no such field.
- **Coding sandbox.** Each test run is `python3 -I -B` in a fresh temporary directory with a
  minimal environment, a time limit (process group killed), `RLIMIT_CPU`, `RLIMIT_AS` 1 GiB and
  `RLIMIT_FSIZE` 16 MiB, and an audit hook that refuses sockets, subprocesses, `ctypes` and writes
  outside the directory. Where unprivileged user namespaces work, `unshare --user --net` adds a
  network namespace (not on c4dev: Ubuntu restricts them, so results say `audit-hook`). A pass
  needs exit 0 and a per-run nonce on stdout, so `sys.exit(0)` or `os._exit(0)` cannot fake one.
  This guards against accidents, not a hostile program: the code runs as the workstation user.
- **Open WebUI retrieval** (`--rag-source openwebui`) is separate from the default and recorded as
  the `rag` suite's `source`; `compare` skips the suite when the sources differ. It posts
  `{"collection_names": [EVAL_KB_ID], "query": ..., "k": 5}` to
  `https://chat.<LAB_DOMAIN>/api/v1/retrieval/query/collection` with `EVAL_KB_KEY` (the endpoint
  is the one docs/research/d-gui-rag-search.md names for the `kb` tool) and reads `documents` and
  `metadatas` as lists of lists, taking the file name from `name`, `source`, `file_name`,
  `filename` or `title`. UNVERIFIED against Open WebUI 0.13.3: the request field names and the
  answer's shape; no live Open WebUI was available.

### Verified and assumed

- Verified here: the model names and routes (`stack/inference/litellm/config.yaml`), the headers
  `tools/smoke.py` uses on both routes, the sandbox behaviour (unit tests: network, subprocess,
  outside writes, early exit, timeout), and the hash reproduction above.
- Verified in the source (not run): LiteLLM 1.108.8 passes an `image_url` part with a data URL
  through to llama-server unchanged on the `openai/` route, and llama-server b12407 decodes PNG
  through stb_image once `coder` has its projector (`stack/inference/README.md`, "Images").
- Assumed: that LiteLLM forwards `seed` and `parallel_tool_calls` on the `openai/` route and
  passes llama-server's `timings` through (only recorded when present); the Open WebUI retrieval
  details above; that Qwen3.8-27B reads the 5x7 pixel font of `maple-74.png` back exactly
  (`format-011` stays optional until it has). No run against the real stack has been made yet.
