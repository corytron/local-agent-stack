# Spec-driven repo workflow, CI for a container stack, evals and benchmarks, guide build pipeline

Status: research, 2026-11-15. Author: research agent F.

## Summary

- **GitHub Free on a private personal repo is much thinner than on the public Hue repo.** Verified
  2026-11-15: no protected branches, no rulesets, so no required status checks; no environments; no
  code scanning (CodeQL); no secret scanning and no push protection; no deployment protection rules.
  Dependabot alerts and version updates do work. Actions get $12 of compute a month (≈2,000 standard
  Linux minutes, or ≈6,000 minutes on the new 1-vCPU `ubuntu-slim` runner at $0.002/min). GitHub Pro
  ($4/month, price from secondary sources) adds protected branches, rulesets and environments, but
  still no code or secret scanning on personal private repos.
- **CI design:** one `tools/check.sh` (the Hue design, unchanged in spirit) runs every check at the same
  time on the 32-core VM. CI runs four jobs that call the same script: three on `ubuntu-slim` (lint,
  compose, secrets) and one on `ubuntu-24.04` (guide build). The checks are compose (`docker compose
  config` plus a policy checker), yamllint, actionlint plus zizmor, shellcheck, hadolint (only if a
  Dockerfile exists), ruff, markdownlint-cli2, lychee in offline mode, gitleaks over the tree and the
  history, the changelog, the deploy desired state and the eval gate. Without branch protection,
  local git hooks and a "commit on main without a PR" audit job enforce the "PR only" rule.
- **Image updates:** pin every image as `tag@sha256:digest`. Use **Renovate** (AGPL-3.0, run as a
  scheduled GitHub Action) for images, because its `regex:` versioning handles tags like
  `server-cuda-b12418` and its custom managers can also bump image references that the guide quotes.
  Keep **Dependabot** for `github-actions` and `pip`, as in the Hue repo. Dependabot's `docker-compose`
  ecosystem is GA and matches `compose.yaml` (verified in source), but it is weaker on non-semver CUDA
  tags (UNVERIFIED for that tag shape).
- **Image scanning:** Trivy 0.76.2 or Grype 0.121.3, weekly and on image-bump PRs, **advisory only**
  (CUDA base images carry many unfixable CVEs). SARIF upload needs code scanning, which this plan does
  not have, so results go into one `security` issue. Pin the scanners by SHA: the trivy-action and
  setup-trivy tags were hijacked on 2026-03-19 (CVE-2026-33634).
- **GitOps deploy for the owner's TrueNAS SCALE 25.10.8 "Goldeye": an approval-gated push from c4dev
  through the 25.10 JSON-RPC websocket API.** `tools/deploy.py` uses the Python
  `truenas_api_client`, pinned to tag `TS-25.10.8`. It renders each app with `docker compose
  config`, then calls `app.create` or `app.update` with `custom_compose_config_string` (both are
  jobs, verified in the v25.10 API docs). For drift it compares `app.config` and `app.query` against
  the repo, since the NAS has an API, unlike the Control4 controller. A c4dev systemd timer runs the
  drift check and keeps one `deploy` issue current.
- **25.10 specifics:** login is `auth.login_with_api_key` or `auth.login_ex` with `API_KEY_PLAIN`.
  25.10 has no SCRAM, so the key travels inside TLS: always use `wss://`, because a key sent over
  `ws://` is revoked. The 25.10 `midclt -K` takes the raw key on the command line, so use the Python
  client with a key file instead. Writing apps needs the **FULL_ADMIN** role: the only predefined
  roles in 25.10 are FULL_ADMIN, READONLY_ADMIN, SHARING_ADMIN and REPLICATION_ADMIN. So the drift
  timer uses a separate **READONLY_ADMIN** key, and the full-admin key is used only by `apply`.
  Komodo, doco-cd and a self-hosted runner were compared and are not recommended as the first step.
- **Evals:** one harness covers the agentic benchmarks. **Harbor 0.26.0** (Apache-2.0) is the official
  Terminal-Bench 2.0 harness, and its registry also has `aider-polyglot@1.0` (225 tasks),
  `swebench-verified@1.0` (500), `terminal-bench-sample@2.0` (10) and `bfcl_parity@1.0` (123), all
  verified 2026-11-15. It takes `--base-url`, `-n` concurrency and `-i` task globs, and runs the task
  containers on c4dev against the model served on TrueNAS. **llama-bench** and **llama-benchy**
  measure throughput, **bfcl-eval 2026.3.23** with fixed `--run-ids` measures tool calling, and
  **ragas 0.4.4** measures RAG quality. A committed results file with a config hash gates every
  model or setting change.
- **Guide PDF: Pandoc 3.14 → HTML5 → WeasyPrint 70.0**, with CSS Paged Media for every vendor-guide
  element. Verified in the WeasyPrint 70.0 docs: margin boxes, named pages, `target-counter()`,
  `leader()`, `string-set`, running elements, bookmarks and PDF/UA. Pandoc 3.14's `alerts` extension
  turns `> [!NOTE]`, `> [!CAUTION]` and `> [!WARNING]` into styled callouts, the same syntax GitHub
  renders. The c4dev VM already has the Pango and HarfBuzz libraries, so both tools install without
  sudo (a pinned pandoc tarball and a hash-pinned venv). Chapters convert in parallel. The book itself
  is one WeasyPrint pass. Typst 0.15.1 is the runner-up. Paged.js is not recommended: its CLI's last
  stable release is from 2023.
- **CLAUDE.md / AGENTS.md:** make `AGENTS.md` the canonical file, since the local harnesses (opencode,
  goose, Aider, Codex, ...) read it. Keep `CLAUDE.md` as `@AGENTS.md` plus Claude-only rules, with the
  same pair in `stack/`, `guide/` and `evals/`. Keep each file under 200 lines, which matters more on
  16 GB-VRAM context budgets. **Watch out:** the home directory above `projects/` holds a
  `CLAUDE.md` with another project's older instructions. It loads into every session in this repo
  unless it is excluded (`claudeMdExcludes`) or moved.

## Recommendation

1. **Repository rules without branch protection (GitHub Free).** Keep the Hue workflow as written
   rules: issue → branch `<type>/<slug>-<N>` → PR "Closes #N" → merge. Enforce it with:
   - `tools/hooks/pre-push`, installed by `tools/setup-checks.sh` through `git config core.hooksPath
     tools/hooks`. It refuses a push to `main`, runs `tools/check.sh --only secrets` on the outgoing
     commits (`gitleaks git --log-opts=<remote>/main..HEAD`) and runs the fast checks.
   - A Claude Code `PreToolUse` hook (and the same rule in AGENTS.md for the local harnesses) that
     blocks `git push` to `main`.
   - A CI job, `audit-main`, on `push` to `main`. It asks `gh api
     repos/{o}/{r}/commits/{sha}/pulls` whether the commit came from a PR and opens or updates one
     issue if not. This detects a bypass after the fact. It cannot prevent one.
   - If the owner buys GitHub Pro, the same four job names become required checks in a ruleset, and
     the pre-push hook stays as the fast local gate.
2. **CI:** `.github/workflows/ci.yml` with four jobs (names stable, so they can become required
   checks later): `Lint (YAML, shell, Python, Markdown, workflows)`, `Compose stack`, `Secrets`
   (`ubuntu-slim`), and `Guide (HTML and PDF)` (`ubuntu-24.04`). Each one is `tools/check.sh --strict
   --only ...`. Weekly workflows: `scan.yml` (Trivy over the pinned images; one `security` issue),
   `links-online.yml` (lychee with network, non-blocking), `renovate.yml`. `release.yml` runs on tag
   `vX.Y`: it builds the guide PDF and a `stack-vX.Y.tar.gz` of the rendered compose files, writes
   `SHA256SUMS.txt`, and takes the notes from `CHANGELOG.md`. No CodeQL and no Scorecard: neither can
   report on a private Free repo (Scorecard could run, but it has no code scanning to upload to). Use
   ruff's `S` (bandit) rules for the Python tools, zizmor for workflows and gitleaks for secrets in
   their place.
3. **GitOps (TrueNAS SCALE 25.10.8):** desired state `deploy/truenas.toml` (stdlib `tomllib`, no
   PyYAML), naming the release tag and the apps. `tools/deploy.py validate|render|plan|apply|drift|status`
   runs on c4dev with `truenas_api_client` installed from git tag `TS-25.10.8`, connecting to
   `wss://192.0.2.10/api/current`. It uses two API keys, each in `~/.config/local-agent-stack/`
   (mode 0600, never in the repo): a **READONLY_ADMIN** key for `plan`, `drift` and `status`, and a
   **FULL_ADMIN** key used only by `apply`. `apply` is run by a person or a coordinator agent under
   the owner's standing approval. It is never automatic, matching the Hue model. `drift --issue` runs
   from a systemd user timer on c4dev and after every `apply`. When the NAS moves to TrueNAS 27, move
   the client tag and switch to SCRAM login (Details §2.1).
4. **Evals:** `evals/` holds the suites (pinned task IDs), the baselines and the results.
   `tools/eval.py run --suite smoke|full`, `compare` and `verify` (offline, in CI). A PR that changes
   `stack/inference/**` or a model line in `deploy/truenas.toml` must carry a results file whose
   `config_sha256` matches the PR's rendered config and whose comparison against the baseline passed.
5. **Guide:** `tools/guide.py build [--proofs]` runs Pandoc 3.14 per chapter in parallel and
   WeasyPrint 70.0 once for the book. It writes `build/guide/guide.pdf` and `book.html`. Image tags in
   the text are injected from the compose files, never typed by hand, so the guide and the stack
   cannot drift apart. Template under `guide/template/` (HTML skeleton, CSS, Lua filters, OFL fonts).
6. **Agent files:** `AGENTS.md` (canonical, under 200 lines) plus a `CLAUDE.md` that imports it and adds
   the Claude-only rules. Nested `AGENTS.md`/`CLAUDE.md` pairs in `stack/`, `guide/` and `evals/`.
   `.claude/rules/*.md` scoped by `paths:` for detail only Claude needs. The outline is in
   Details §5.

## Options compared

### A. Dependency bots for images

| Option | What it is | Fit for this repo | Maturity | Licence | Verdict |
|---|---|---|---|---|---|
| Renovate, self-hosted via `renovatebot/github-action` v46.3.13 (Renovate 44.239.1) | Scheduled workflow opens PRs. `docker-compose` manager matches `(^|/)(?:docker-)?compose[^/]*\.ya?ml$`. `pinDigests` / `docker:pinDigests`, `regex:` versioning, `customManagers`, `minimumReleaseAge` | Handles `tag@digest`, non-semver CUDA tags, image references in the guide's Markdown. Needs a GitHub App or fine-grained PAT so its PRs trigger CI | Very mature, release several times a week | AGPL-3.0 (running it is fine) | **Use for images** |
| Mend Renovate Community Cloud (GitHub App) | Same engine, hosted by Mend. Free for private repos | Zero CI minutes, but a third party reads the private repo | Mature | Service terms | Option if the owner accepts third-party access |
| Dependabot `docker-compose` | Native. GA since 2025-02-25. Fetcher regex `(docker-)?compose(-[\w]+)?(?>\.[\w-]+)?\.ya?ml`. Parser keeps `@sha256:` digests | Free, no token. Weak on `server-cuda-bNNNN`-style tags (UNVERIFIED). Security updates "not supported" for compose | GA | MIT (dependabot-core) | **Keep for actions and pip**, not images |

### B. GitOps deploy to TrueNAS

| Option | What it is | Fit | Maturity | Licence | Verdict |
|---|---|---|---|---|---|
| **`tools/deploy.py` on c4dev → TrueNAS websocket API** (`app.create` / `app.update` with `custom_compose_config_string`, `app.config`, `app.query`) | Push, approval-gated, drift by reading the API | Native TrueNAS apps (UI, upgrades, logs stay TrueNAS's). No inbound port. Matches the Hue GitOps contract. On 25.10.8: API key login over `wss://`, READONLY_ADMIN key for drift, FULL_ADMIN key for apply | API documented for 25.10 (owner's release), 27.0, 28.0; client tag `TS-25.10.8` | Own code; `truenas_api_client` LGPL-3.0 | **Recommended** |
| TrueNAS cron job + local `midclt` (pull) | Cron on TrueNAS pulls a read-only checkout, calls `app.update` over the local socket | No key on c4dev, but runs as root automatically, not approval-gated | Built from stock parts | n/a | Later option |
| Komodo v2.3.4 (Core + Periphery) | Stacks from git, ResourceSync from TOML with a pending-diff view and manual confirm, webhooks | Strong UI. Adds Core plus MongoDB/FerretDB and a docker-socket agent. Stacks are not TrueNAS apps | Active, v2.0 on 2026-03-24 | GPL-3.0 | Not first choice: a second control plane |
| doco-cd v0.134.0 | One container, polls or webhooks a repo, deploys compose, SOPS, metrics | Simple, pull-based, self-healing. Automatic (gate by tracking a tag). Docker socket = root on NAS | Active (1.8k stars) | Apache-2.0 | Option if the owner wants automatic pull |
| Arcane v3.0.0 | Docker UI with git sync of stacks | Like Komodo, lighter. Git-sync details UNVERIFIED | v3 released 2026-11-14 | BSD-3-Clause | Watch |
| Dockge 1.5.0 | Compose UI, no git sync | No GitOps | Last release 2025-03-30 | MIT | No |
| Self-hosted GitHub Actions runner on c4dev/TrueNAS | CD job on merge runs `deploy.py apply` | GitHub warns: runners "can be persistently compromised by untrusted code in a workflow", even on private repos. A runner on the NAS with the docker socket is root on the NAS | Mature | MIT (runner) | **No**, unless ephemeral JIT on c4dev and `push`-to-`main` only |

### C. Eval and benchmark harnesses (one 16 GB GPU)

| Option | What it is | Fit | Maturity | Licence | Verdict |
|---|---|---|---|---|---|
| llama-bench (llama.cpp v1.0.0 / b12418) | C++ pp/tg throughput, `-d` depth, `-r` reps, JSON/JSONL output | Exact engine speed. Needs exclusive GPU | Core tool | MIT | **Use** |
| llama-benchy 0.4.0 | llama-bench-style pp/tg at depths through any OpenAI-compatible endpoint | End-to-end through the server and router | Young | MIT | **Use** |
| llama-server `/metrics` (`--metrics`) | Prometheus counters: `llamacpp:prompt_tokens_seconds`, `predicted_tokens_seconds`, `requests_deferred`, ... | Free telemetry during every eval | Core | MIT | **Use** |
| bfcl-eval 2026.3.23 | Berkeley Function Calling Leaderboard v4. `--run-ids`, `--num-threads`, `--skip-server-setup`, `REMOTE_OPENAI_BASE_URL` | Official tool-calling scores on a fixed subset | Research standard | Apache-2.0 | **Use** (subset) |
| Harbor 0.26.0 | Terminal-Bench 2.0 harness plus adapters (aider-polyglot, swebench-verified, bfcl, ...). Many agents (opencode, qwen-code, goose, aider, mini-swe-agent, openhands, ...), `--base-url` | One CLI for agentic suites, Docker on c4dev | Very active, release 2026-11-13 | Apache-2.0 | **Use** |
| Aider polyglot (native `benchmark.py`) | 225 Exercism tasks, `--threads`, `--num-tests`, `--keywords` | Superseded here by Harbor's adapter. Aider's last release is 0.86.2 (2026-02-12) | Slowing | Apache-2.0 | Via Harbor |
| SWE-bench 5.0.2 + mini-swe-agent 2.4.6 | `mini-extra swebench --subset lite --slice 0:N --workers W` plus the harness | Real repo fixes. Needs about 120 GB disk, 16 GB RAM, 8 cores (SWE-bench README) | Standard | MIT / MIT | Small subset, monthly |
| ragas 0.4.4 | RAG metrics (faithfulness, context_precision, context_recall, factual_correctness, ...) with an LLM judge via `llm_factory(..., client=OpenAI(base_url=...))` | Works with a local judge | Active | Apache-2.0 | **Use** |
| inspect-ai 0.3.290, promptfoo 0.125.1, DeepEval 4.2.4, lm-eval 0.4.13 | General eval frameworks | Good for custom regression tests (owner's own tool prompts) | Active | MIT / MIT / Apache-2.0 / MIT | Optional |

### D. Guide PDF engines

| Option | What it is | Fit (A4 vendor guide, VM has Chromium snap and Docker) | Maturity | Licence | Verdict |
|---|---|---|---|---|---|
| **Pandoc 3.14 + WeasyPrint 70.0** | Markdown → HTML5 → CSS Paged Media PDF, pure Python | Every required feature in CSS (verified list). No browser. Pango/HarfBuzz already on c4dev | Both very mature | GPL-2.0+ / BSD-3-Clause | **Recommended** |
| Pandoc 3.14 + Typst 0.15.1 | Markdown → Typst → PDF, single Rust binary | Excellent typography, fast, PDF/UA-1 (`--pdf-standard ua-1`), outline has dot leaders by default. Template in Typst, raw HTML in chapters lost | Mature since 0.14 (2025-10) | GPL-2.0+ / Apache-2.0 | Runner-up |
| Vivliostyle CLI 11.5.0 | Chromium-based CSS typesetter, Markdown (VFM) native, TOC and cover pages, Docker image `ghcr.io/vivliostyle/cli:11.5.0` | Full CSS (grid, flex, JS). Heavier. Snap Chromium awkward, use its image | Active (release 2026-11-14) | AGPL-3.0 (tool) | Fallback |
| pagedjs-cli (Paged.js) | Chromium + JS polyfill | Stable CLI 0.4.3 dates from 2023-07-20, beta 0.5.0-beta.2 from 2025-09, pulls Puppeteer | Core active, CLI stalled | MIT | No |
| Pandoc + LaTeX | TeX engines | Multi-GB TeX Live, hard to style to a vendor look, slow | Very mature | various | No |
| XSL-FO: Apache FOP 2.12. Commercial: Antenna House, Prince 17 ($495 desktop) | DocBook/FO or HTML (Prince) | FOP verbose. Prince best CSS support but paid | Mature | Apache-2.0 / commercial | No |

## Details

### 0. What the c4dev VM has (observed 2026-11-15)

32 cores and **15 GiB RAM** (`free -g`). This caps the parallel Docker-based eval tasks (SWE-bench
recommends 16 GB). Docker 29.9.1, Docker Compose v5.6.0 (the latest release is v5.7.1 of
2026-11-11), Chromium 157 (snap), Python 3.14.4, no Node.js, no pandoc, no WeasyPrint. `libpango-1.0`,
`libpangoft2-1.0`, `libharfbuzz` and `libharfbuzz-subset` are present. `shellcheck`, `actionlint` and
`gitleaks` are already in `~/.local/bin`. A test install of WeasyPrint into a scratch venv was refused
by the permission classifier, so every PDF timing below is an estimate.

### 1. CI for the compose-based stack

#### 1.1 What GitHub Free allows on a private personal repo (verified 2026-11-15)

Confirmed for this repo (private, free personal account): **no branch protection rules, no rulesets,
and therefore no required status checks** can be enforced. GitHub's own availability notes read
"Rulesets are available in public repositories with GitHub Free and GitHub Free for organizations,
and in public and private repositories with GitHub Pro, GitHub Team, and GitHub Enterprise Cloud"
[2], and "Protected branches are available in public repositories with GitHub Free … also available
in public and private repositories with GitHub Pro, GitHub Team, GitHub Enterprise Cloud, and GitHub
Enterprise Server" [3]. CI still runs and still shows red or green on every PR. Nothing stops a
merge or a direct push to `main` except the local hooks and the audit job (Recommendation 1). The
cheapest way to make the four CI jobs real required checks is GitHub Pro on the personal account.

| Feature | Free, private | Pro, private | Source |
|---|---|---|---|
| Protected branches | no | yes | [3] |
| Rulesets (required status checks, block force push) | no | yes | [2] |
| Environments, environment secrets, deployment branches | no | yes | [8] |
| Deployment protection rules (wait timer, reviewers) | no | no (public only) | [8] |
| Code scanning / CodeQL | no | no. Needs an org on Team or Enterprise with Code Security | [4] |
| Secret scanning, push protection | no. Push protection for users covers public repos only | no | [5][6] |
| Dependabot alerts, security updates, version updates, dependency graph | yes | yes | [7] |
| Actions compute | $12/month included | $18/month | [1][9] |
| Artifact storage / cache | 500 MB / 10 GB per repo | 1 GB / 10 GB | [9] |
| Concurrent hosted jobs | 20 | (more) | [12] |
| Discussions, Projects, Releases, Issues | yes (no plan limit stated) | yes | [—] assumed |

Runner rates [10]: `ubuntu-slim` (1 vCPU, 5 GB RAM, runs in an unprivileged container, **no
Docker-in-Docker**) $0.002/min. `ubuntu-latest` / `ubuntu-24.04` / `ubuntu-26.04` (2 vCPU, 8 GB RAM,
14 GB SSD on private repos) $0.006/min. arm64 $0.005/min. Self-hosted runners are free. The
$0.002/min platform fee announced for March 2026 was postponed [9][61]. Runner images of
2026-11-11 [14]: `ubuntu-slim` has Docker Compose **5.7.1** and Node 24, `ubuntu-24.04` (=
`ubuntu-latest`) has Compose 2.38.2 and yamllint 1.38.0, `ubuntu-26.04` has Compose 5.1.3. All have
shellcheck 0.9–0.11, so pin your own.

Budget sketch (assumed durations): three slim jobs × ~1.5 min × $0.002 + one standard job ×
~3 min × $0.006 ≈ $0.03 per push. 200 pushes a month ≈ $6. Use `concurrency: cancel-in-progress`
as in Hue. Keep image scans and evals off GitHub, or weekly only.

#### 1.2 Tools and pinned versions (all verified as the latest release on 2026-11-15)

| Check | Tool, version, licence | Command | Notes |
|---|---|---|---|
| compose | Docker Compose v5.7.1 (Apache-2.0) | `docker compose -f stack/<app>/compose.yaml --env-file deploy/ci.env config --quiet` then `config --format json` into `tools/check_compose.py` | `config` works **without a daemon** (tested with a dead `DOCKER_HOST`), so it runs on `ubuntu-slim`. `--no-env-resolution` keeps `env_file:` references unread (tested) |
| compose policy | own `tools/check_compose.py` (stdlib only, reads the JSON) | every image `name:tag@sha256:<64 hex>`, no `:latest`. No `build:` (TrueNAS custom apps). Bind sources absolute under the apps dataset (from `deploy/truenas.toml`). No `${…}` interpolation of a variable whose name matches `(?i)(key|token|secret|password)`: secrets only via `env_file:`/`secrets:`. Published host ports unique across all apps and outside a reserved list (TrueNAS UI). `restart:` set. `healthcheck:` on long-running services. App names `^[a-z]([a-z0-9-]{0,38}[a-z0-9])?$` (TrueNAS `app_name` rule: lowercase alphanumeric plus hyphen, 1–40 chars [29]) | Trivy has no compose misconfiguration scanner (its IaC coverage is Ansible, ARM, CloudFormation, Dockerfile, Helm, Kubernetes, Terraform [24]). dclint 3.1.0 (MIT) is optional |
| yaml | yamllint 1.38.0 (GPL-3.0-or-later) | `yamllint -s stack deploy .github evals` | Needs `truthy: {check-keys: false}` for workflow `on:` (assumed) |
| workflows | actionlint 1.7.12 (MIT), zizmor 1.32.0 (MIT) | `actionlint`. `zizmor --min-severity medium .github/workflows` | as Hue |
| shell | shellcheck 0.11.0 (GPL-3.0), via shellcheck-py 0.11.0.1 | `shellcheck -S style tools/*.sh stack/**/*.sh` | as Hue |
| dockerfile | hadolint 2.15.1 (GPL-3.0) | `hadolint <each Dockerfile>` | only if the stack builds images |
| python-lint / python-test | ruff 0.17.5 (MIT), unittest | `ruff check tools` (rules E F W I B **S**), `ruff format --check`, `tools/parallel.py unittest` | S = bandit rules, standing in for CodeQL |
| markdown | markdownlint-cli2 0.24.1 (MIT) | `markdownlint-cli2 "**/*.md"` | No Node on c4dev: the pinned image `davidanson/markdownlint-cli2:v0.24.1` there, `npx markdownlint-cli2@0.24.1` on `ubuntu-slim` (Node 24) |
| links | lychee 0.24.2 (Apache-2.0/MIT) | `lychee --offline --include-fragments --root-dir "$PWD" '**/*.md' build/guide/book.html` | `--offline`, `--include-fragments[=none|anchor-only|text-only|full]`, `--root-dir`, `--cache` verified in README [25]. Online run weekly, non-blocking |
| secrets | gitleaks 8.30.1 (MIT) | tree and history at once, as Hue (`--all` on the VM, `HEAD` in CI) | stands in for secret scanning and push protection. Pre-push hook too |
| images | Trivy 0.76.2 (Apache-2.0) or Grype 0.121.3 (Apache-2.0) | `trivy image --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed <ref@digest>` per image, in parallel on c4dev | Advisory. CUDA images are several GB: run on c4dev or weekly in CI, never as a required check |
| changelog / deploy / evals / guide | own Python tools | `changelog.py check`, `deploy.py validate`, `eval.py verify`, `guide.py build --check` | |

Supply chain: pin every action by full commit SHA with the version in a comment (Hue convention). Do
not use `aquasecurity/trivy-action` by tag: on 2026-03-19 an attacker overwrote 76 of 77
trivy-action tags and all setup-trivy tags and published a malicious Trivy 0.69.4. The exposure
lasted about 12 h, and v0.35.0, protected by GitHub immutable releases, was the only safe tag [23].
Install the Trivy binary at a pinned version and sha256 (as Hue does for gitleaks), or use the
pinned image `aquasec/trivy:0.76.2` by digest. Dependabot `cooldown: default-days: 7` for actions,
Renovate `minimumReleaseAge: "7 days"` for images (option verified [20]).

#### 1.3 Image pinning and updates

- Author `image: ghcr.io/org/name:1.2.3@sha256:…`. `docker compose config --resolve-image-digests`
  pins tags to digests, and `--lock-image-digests` writes an override file with digests (both flags
  verified on Compose v5.6.0). Use one of them in `tools/pin-images.sh` for a new image. Renovate
  keeps the pair current after that.
- Renovate `renovate.json` sketch (option names verified [19][20][21]. The regex is an example):

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:best-practices"],
  "minimumReleaseAge": "7 days",
  "labels": ["dependencies"],
  "packageRules": [
    { "matchDatasources": ["docker"], "matchPackageNames": ["ghcr.io/ggml-org/llama.cpp"],
      "versioning": "regex:^server-cuda-b(?<patch>\\d+)$" },
    { "matchManagers": ["github-actions"], "enabled": false }
  ]
}
```

  `config:best-practices` includes `docker:pinDigests` [19]. Leave `github-actions` to Dependabot
  (Hue parity). Add a `customManagers` regex entry for image references in `guide/chapters/*.md`
  only if the guide quotes tags directly. The recommendation is to inject them (§4.4).
- Renovate needs a token whose PRs trigger workflows (PRs opened with `GITHUB_TOKEN` start no CI:
  assumed, standard Actions behaviour). Use a GitHub App installation token or a fine-grained PAT
  limited to this repo (contents, pull requests, issues: write).

#### 1.4 `tools/check.sh` (same contract as the Hue repo)

`tools/check.sh [--strict] [--only <name>...]`, `JOBS=N` (default `nproc`), one `ok`/`FAIL`/`skip`
line per check in a fixed order. Every check runs at once, with output buffered and printed in order.
Checks: `compose yaml workflows shell dockerfile python-lint python-test markdown links secrets
changelog deploy evals guide`.

Parallel strategy on 32 cores:

- **Across checks:** all start at once. Two dependencies: `links` waits for `guide` (it reads
  `build/guide/book.html`), and `secrets` waits for `python-lint` (ruff writes `.ruff_cache`, as in
  Hue).
- **Within checks:** a generic `tools/parallel.py run --per-file` runs one process per file or per
  shard and prints in file order (the Hue `parallel.py` pattern): `compose` one `docker compose
  config` per app, `shell`/`dockerfile`/`yaml` sharded by file, `python-test` one process per module.
  lychee and gitleaks parallelise internally (`--max-concurrency` for lychee). `guide` uses its own
  pool (§4.5).
- **Serial on purpose:** anything that talks to TrueNAS, GitHub or a registry (`deploy.py plan`,
  online lychee, Trivy pulls under a concurrency cap).
- `tools/setup-checks.sh` installs into `~/.local/bin` without sudo: pip packages with
  `--require-hashes` (ruff, zizmor, yamllint, shellcheck-py), and release binaries with a pinned
  sha256 (actionlint, gitleaks, lychee, hadolint, trivy). The installs run in lanes, as in Hue.

#### 1.5 Workflow design

```
ci.yml       (pull_request, push main, weekly, dispatch; permissions: contents: read;
              concurrency ci-${{ github.ref }} cancel-in-progress)
  lint     ubuntu-slim   tools/check.sh --strict --only yaml workflows shell dockerfile python-lint
                         python-test markdown changelog deploy evals
  compose  ubuntu-slim   tools/check.sh --strict --only compose          (no daemon needed)
  secrets  ubuntu-slim   fetch-depth: 0; tools/check.sh --strict --only secrets
  guide    ubuntu-24.04  tools/check.sh --strict --only guide links; upload guide.pdf (retention 7 d)
audit-main.yml (push main)  commit without a PR -> one issue
scan.yml     (weekly, and pull_request with paths: stack/**)  Trivy per image -> one `security` issue
renovate.yml (weekly) | links-online.yml (weekly, non-blocking)
release.yml  (tag vX.Y, dispatch with version)  build guide + stack bundle + SHA256SUMS, notes from CHANGELOG
```

Jobs do not depend on each other. Every job has `timeout-minutes` (slim 10, guide 15). Job names are
stable so a later ruleset (Pro) can require them. Artifact attestations on private repos: whether a
personal Free account can use them is UNVERIFIED. Keyless cosign signing would write the private
repo's workflow identity into the public Sigstore transparency log (assumed from how keyless signing
works), so publish `SHA256SUMS.txt` only.

### 2. GitOps deploy to TrueNAS

#### 2.1 API facts (verified)

**Target confirmed by the owner (2026-11-15): TrueNAS SCALE 25.10.8 "Goldeye".** What that means for
the tool:

- **API documentation:** the hosted docs carry one 25.10 set (`https://api.truenas.com/v25.10/`;
  `v25.10.8` returns 404). Its method schemas below are the contract. Before the first `apply`,
  confirm them against the NAS's built-in docs at `https://192.0.2.10/api/docs/` [37].
- **Client:** `truenas/api_client` has a tag `TS-25.10.8` (verified). Install it with `pip install
  git+https://github.com/truenas/api_client.git@TS-25.10.8` into a venv on c4dev. At that tag the
  login call is `c.call("auth.login_with_api_key", key)`, and `Client(uri=..., verify_ssl=True)`
  exists (25.10 added `verify_ssl` [35]).
- **Login:** `auth.login_ex` in 25.10 accepts `PASSWORD_PLAIN`, `API_KEY_PLAIN` (`username`,
  `api_key`), `TOKEN_PLAIN` and `OTP_TOKEN`. There is **no SCRAM** in 25.10 [63], so the key is
  protected only by TLS. Always use `wss://192.0.2.10/api/current`: keys sent over plain HTTP are
  revoked automatically [37].
- **Do not use `midclt -K` from c4dev on 25.10.** At `TS-25.10.8`, `-K/--api-key` takes the raw key as
  a command-line argument [35], so it shows in `ps` and shell history. Key-file paths for `-K` and
  stdin payloads only arrived in the 26 client. `tools/deploy.py` reads the key file and calls the
  Python client instead.
- **Roles:** 25.10 RBAC bundles roles into privileges linked to local groups. The only predefined
  group roles a privilege can take are FULL_ADMIN, READONLY_ADMIN, SHARING_ADMIN and
  REPLICATION_ADMIN, and "using custom privilege sets is deprecated and will be removed in TrueNAS
  28" [64]. **Only FULL_ADMIN covers writing apps** (APPS_WRITE). READONLY_ADMIN can read every
  subsystem. Hence two keys: a READONLY_ADMIN key for `plan`, `drift` and `status`, which never
  change anything, and a FULL_ADMIN key used only by `apply`. Each key belongs to its own local user.
  Keys are user-linked and password-equivalent [37]. Whether a key on 25.10 carries exactly its
  user's roles is not stated on the RBAC page (assumed yes).
- **Custom apps on 25.10:** the YAML must contain a `services:` key [39][40]. `app_name` is lowercase
  alphanumeric plus hyphens, 1–40 characters [29].

General API facts (all versions):

- TrueNAS 25.04 introduced the versioned **JSON-RPC 2.0 over WebSocket** API (`wss://<host>/api/current`).
  The REST API was deprecated in 25.04, and the TrueNAS 26 deprecations page says it no longer works
  in 26 and later [36]. Version naming: the release planned as "26" was renamed **TrueNAS 27** at
  RC.1 (2026-10-06), with the final planned for early December 2026 (secondary sources [38]). Hosted
  API docs exist for v25.10, v27.0 and v28.0 [29][30]. `auth.login_with_api_key` is deprecated, to be
  removed in 27, in favour of `auth.login_ex` with `API_KEY_PLAIN` or `SCRAM` [36].
- API keys are user-linked, "password-equivalent", bypass 2FA, and are **revoked automatically if
  sent over plain HTTP** [37]. The client (`truenas/api_client`, LGPL-3.0) provides `midclt`:
  `midclt --uri wss://<host>/api/current -K <key> call -j app.update …`. The TS-26+ clients add
  SCRAM-SHA-512 (the key is never sent), `-K <file>`, stdin payloads (`-`), `--insecure` (dev
  only), and TLS channel binding by default. Older servers need `--plain` [35]. None of that applies
  to 25.10.8 (above). It becomes the upgrade path when the NAS moves to TrueNAS 27.
- `app.create` (job): `app_name` (1–40 chars, lowercase alphanumeric and hyphens), `custom_app: true`,
  `custom_compose_config` (object) or `custom_compose_config_string` (YAML string), `values`,
  `catalog_app`, `train`, `version` [29].
- `app.update` (job): `app_name`, `{values, custom_compose_config, custom_compose_config_string}`,
  with the same fields in v27.0 [30].
- `app.config <app_name>` returns "the current configuration object" (APPS_READ role) [31].
  `app.query` with `extra.retrieve_config: true` gives `state` (CRASHED, DEPLOYING, RUNNING, STOPPED,
  STOPPING), `custom_app`, `images`, `upgrade_available`, `active_workloads`, `config` [32].
  `app.pull_images <app> {redeploy: true}` (job, APPS_WRITE) [33]. Also present: `app.redeploy`,
  `app.rollback`, `app.container_ids`, `app.outdated_docker_images`.
- Since 25.10 a custom-app YAML must contain a `services:` key (forum and TechnoTim, 2026-01 [39][40]).
  The community "include" pattern (`include: [/mnt/<pool>/<app>/compose.yaml]` plus `services: {}`)
  keeps the real file on a dataset. It hides the compose from `app.config`, so drift could then only
  be read from the dataset. Not recommended for GitOps.

#### 2.2 Recommended flow (`tools/deploy.py`, standard library plus `truenas_api_client`)

```
deploy/truenas.toml          desired state (tomllib):
  schema = 1
  release = "v1.0"           # tag whose stack/ is installed
  apps_dataset = "/mnt/<pool>/apps"   # placeholder; real value lives on c4dev only if private
  [apps.llm]   compose = "stack/llm/compose.yaml"
  [apps.webui] compose = "stack/webui/compose.yaml"
~/.config/local-agent-stack/truenas.toml   (c4dev, 0600): uri = "wss://192.0.2.10/api/current",
                                           read_user, read_key_file   (READONLY_ADMIN)
                                           apply_user, apply_key_file (FULL_ADMIN)
                                           ca_file, truenas_version = "25.10.8"
```

`deploy.py` refuses to start when `system.info` reports a version other than `truenas_version`
(UNVERIFIED field name: read `system.info` once and record the key), so an upgrade of the NAS is a
reviewed change to the tool, not a silent one.

- `validate` (CI, offline): schema, app names, that the compose files exist, that `release` matches a
  tag pattern.
- `render`: `docker compose -f <compose> --env-file deploy/truenas.env config --no-env-resolution
  --format yaml` writes `build/render/<app>.yaml` and its sha256. Drop the top-level `name:`, since
  TrueNAS names the project itself (UNVERIFIED). Secrets are only `env_file:` paths on the dataset
  (0600), never values.
- `plan` (online): for each app, `app.query` plus `app.config`. Parse both the stored config and the
  rendered YAML into canonical JSON (sorted keys) and print a unified diff. Comparing the parsed YAML
  on c4dev avoids false drift from differing Compose versions between c4dev and TrueNAS. The
  container `com.docker.compose.config-hash` label (verified in compose source [27]) depends on the
  Compose version, so use it only as a secondary signal.
- `apply [--app X] [--pull]`: `app.create` for a new app, `app.update` for an existing one, waiting
  for the job. Optionally `app.pull_images {redeploy: true}`. Then poll `app.query` until `RUNNING`
  or a timeout. Never deletes an app: a removed app is reported and offered, never automatic (the
  owner's "edge cases before automation" rule). Writes `build/deploy/<tag>/record.json`, comments on
  the deploy issue, and posts the report to Discussions.
- `drift [--issue]`: `plan`, exit 3 on drift, and keeps exactly one open issue labelled `deploy`
  through `gh`. This is the Hue `drift.yml` logic, run by a **systemd user timer on c4dev**, because
  GitHub-hosted runners cannot reach the LAN. GitHub Environments and Deployments are not used:
  environments need Pro on private repos [8], and the API itself is the observed state.
- API key scope on 25.10.8: the method pages name fine-grained roles (`APPS_READ` for `app.config`,
  `APPS_WRITE` for `app.pull_images`) [31][33], but a 25.10 privilege can only take the four
  predefined group roles, and only FULL_ADMIN writes apps [64]. So: two local users, `deploy-read`
  in a group whose privilege is READONLY_ADMIN and `deploy-apply` in a group with FULL_ADMIN, one
  API key each. The drift timer only ever loads the read key. Use `wss://` with the NAS certificate
  trusted explicitly (`ca_file`; the client's `verify_ssl=True`). SCRAM and channel binding arrive
  with TrueNAS 26/27 [35]. A third-party report says putting FULL_ADMIN inside a *custom* privilege
  broke authentication and suggests using the built-in administrators group for the apply user
  instead [65] (unofficial; test once).

#### 2.3 Why not a self-hosted runner

GitHub [13]: self-hosted runners "can be persistently compromised by untrusted code in a workflow".
On private repos anyone who can open a PR can compromise them. Even with destroy-after-job, "there is
no way to guarantee that a self-hosted runner only runs one job". JIT runners help but need a clean
environment. A runner holding a TrueNAS key (or, worse, sitting on TrueNAS with the docker socket)
turns any compromised action pin or bot PR into root on the NAS. On Free private repos there are no
environments to gate a deploy job [8].

### 3. Evaluation and benchmarking harness

#### 3.1 Layout and gate

```
evals/
  suites/smoke.toml      # pinned IDs: bfcl run-ids JSON, harbor include globs, ragas set, llama-bench grid
  suites/full.toml
  bfcl/run_ids_smoke.json
  rag/golden.jsonl       # 30–50 question/answer/ground-truth contexts over the owner's own documents
  baselines/<profile>.json
  results/<UTC>-<profile>-<suite>.json   # committed
tools/eval.py run|compare|verify
```

Each results file records: `config_sha256` (the rendered inference compose plus server flags plus
model file sha256), harness versions, GPU name and driver (`nvidia-smi`), the server's `--parallel`
slots and context, temperature and seed, and per metric the value, n, and a 95% interval (Wilson for
pass rates, bootstrap for scores). `compare` fails when:

- tg or pp tok/s median < 0.95 × baseline at any depth (llama-bench `-r 5`), or
- BFCL subset accuracy drops more than 2 points **and** the two-proportion test says the drop is
  significant, or
- agentic pass rate drops by more than one task on smoke (small n catches only gross regressions;
  decide on `full`), or
- any ragas metric drops by more than 0.05.

Thresholds are proposals. `verify` (CI, offline) checks that a PR touching inference settings carries
a passing results file for its own `config_sha256`, or a `CHANGELOG.md` line with an issue number that
accepts the regression.

#### 3.2 Throughput

- `llama-bench -m <gguf> -p 512 -n 128 -d 0,8192,32768 -r 5 -fa on -ctk q8_0 -ctv q8_0 -o jsonl`
  (flags verified in the README [44]: `-d/--n-depth`, `-r`, `-fa on|off|auto`, `-ctk/-ctv`,
  `-ncmoe`, `-ot`, `-fitt`, `-o csv|json|jsonl|md|sql`). Run it inside the same llama.cpp image as
  the server, with the server **stopped**, on TrueNAS.
- `llama-benchy` (PyPI 0.4.0, MIT) from c4dev against the live endpoint, for end-to-end pp/tg/TTFT at
  depths. It works around prompt-cache hits that distort `vllm bench` numbers on llama-server [45].
- Scrape `/metrics` (`--metrics`) before and after each functional suite for average throughput and
  `requests_deferred`. `/slots` shows per-slot state [44].
- Estimated duration (assumed): one model and the grid above take 3–8 minutes including load.

#### 3.3 Tool calling (BFCL)

- `pip install bfcl-eval==2026.3.23`. `bfcl generate --model <M> --run-ids --skip-server-setup
  --num-threads <slots>`, then `bfcl evaluate --model <M> --partial-eval` [46].
- Endpoint: `REMOTE_OPENAI_BASE_URL=http://192.0.2.10:<port>/v1` for the OSS handlers. The OpenAI
  chat-completions FC handler reads `OPENAI_BASE_URL` (verified in source). A model the leaderboard
  does not list needs a model-config entry, per BFCL's contributing guide (file path UNVERIFIED).
  Two ways to measure: prompting mode (the BFCL handler formats the prompt, which measures the model)
  or FC mode through llama-server's `--jinja` tool-call parsing (which measures the stack the agents
  actually use). **Measure FC through the server**, because that is what breaks in practice.
- Subset (proposal): 50 each of `simple_python`, `multiple`, `parallel`, `parallel_multiple`,
  `irrelevance`, `live_simple`, `live_multiple`, plus 40 `multi_turn_base` (category names verified
  [46]). Skip `web_search` (needs SerpAPI unless rewired) and `memory` at first.
- Estimated time (assumed): about 20–40 minutes at 2–4 concurrent requests for a 30B-class MoE.

#### 3.4 Agentic coding (Harbor)

- `pip install harbor==0.26.0` (or `uv tool install`). Datasets in the registry (verified
  2026-11-15): `terminal-bench@2.0` (89 tasks), `terminal-bench-sample@2.0` (10),
  `aider-polyglot@1.0` (225), `swebench-verified@1.0` (500), `swebench_multilingual@1.0` (300),
  `bfcl@1.0` (3641), `bfcl_parity@1.0` (123) [47].
- `harbor run -d terminal-bench-sample@2.0 -a <agent> -m <provider/model> --base-url
  http://192.0.2.10:<port>/v1 -n 2 -k 1 --timeout-multiplier 2`. `-i/--include-task-name`
  (globs), `-x`, `-l/--n-tasks`, `-n/--n-concurrent`, `-k/--n-attempts`, `--base-url` were verified
  in `src/harbor/cli/jobs.py` [47]. The agent is whatever agent C recommends (Harbor ships opencode,
  qwen_code, goose, aider, mini_swe_agent, openhands, swe_agent, codex, claude_code, ...).
- Suites (proposal): **smoke** = `terminal-bench-sample@2.0` (10) plus 20 pinned aider-polyglot tasks.
  **full** (overnight) = `terminal-bench@2.0` (89) plus 60 aider-polyglot plus 20 pinned
  swebench-verified tasks.
- Resources: task containers run on c4dev (Docker), and the model runs on TrueNAS. SWE-bench wants
  ≥120 GB free disk, 16 GB RAM and 8 cores, with `max_workers` < `min(0.75 × cpus, 24)` [49]. With
  c4dev's 15 GiB RAM, keep `-n` ≤ 3 for SWE tasks.
- Estimated time (assumed, 30B-class model at 40–80 tok/s): T-Bench sample 30–90 minutes, 20 polyglot
  tasks 15–40 minutes, 20 SWE-bench tasks 1.5–3 hours plus a first image pull of tens of GB.
- Alternative for SWE-bench Lite (300, not in Harbor's registry): `mini-extra swebench --subset lite
  --split test --slice 0:20 --workers 3 --model <litellm model>`, then the SWE-bench harness with
  `--max_workers 3` [49].

#### 3.5 RAG quality (ragas)

- `pip install ragas==0.4.4`. `llm_factory("<model>", client=OpenAI(base_url=..., api_key=...))` for
  the judge [50]. Metrics present in 0.4 (`ragas/metrics/collections`): `faithfulness`,
  `context_precision`, `context_recall`, `context_relevance`, `answer_relevancy`, `factual_correctness`,
  `answer_correctness`, `response_groundedness`, `noise_sensitivity`, `tool_call_accuracy`, ...
- The golden set is 30–50 questions over the owner's own documents, with reference answers and source
  passages. Capture the RAG pipeline's retrieved contexts (agent D's pipeline) for each question.
  ragas relies on structured output, so enable JSON schema or grammar output on the server (assumed).
- The judge bias of using the same model is a known limit. Use a different local model as judge
  where VRAM allows, as a separate serial phase. Estimated time (assumed): 10–20 minutes for 50
  questions.

#### 3.6 Running evals in parallel safely on one GPU

1. **Throughput lane is exclusive:** take an `flock` on `~/.cache/local-agent-stack/gpu.lock`, check
   that `/slots` is idle and `llamacpp:requests_processing` is 0, run, release. Never measure speed
   while another suite is using the server.
2. **Functional lanes share one server:** harness concurrency ≤ the server's `-np` slots. With
   `--kv-unified` (the default when slots are auto) the KV pool is shared. Otherwise each slot gets
   `ctx / np`, and agentic tasks need ≥32k context, so on 16 GB use 2–4 slots (flags verified [44]).
   Record the slot count in the result and compare like with like. Batched decoding can change
   outputs even at temperature 0 (assumed).
3. **Never load two models at once** on the 16 GB card. Judge-model phases run after generation phases.
4. **CPU-side work goes wide:** test containers, BFCL and ragas scoring and report building run on
   c4dev's 32 cores (capped by RAM).
5. Every run writes to its own job directory (`harbor -o`, `--job-name`). Results are merged by
   `eval.py`, never by concurrent writers.

### 4. The guide build pipeline

#### 4.1 Tools (exact versions)

- **Pandoc 3.14** (changelog date 2026-11-10, GitHub release 2026-11-12) from the static
  `pandoc-3.14-linux-amd64.tar.gz`, sha256 pinned in `tools/setup-guide.sh`. Docker Hub `pandoc/core`
  stops at 3.11, so do not use the image [54][58].
- **WeasyPrint 70.0** (2026-09-08, BSD-3-Clause), in a venv with `--require-hashes`. It needs Python
  ≥3.10 and Pango ≥1.44. On Ubuntu the apt packages are `libpango-1.0-0 libharfbuzz0b
  libpangoft2-1.0-0 libharfbuzz-subset0` [53], and all are present on c4dev. CI `ubuntu-24.04`:
  install the same packages with apt.
- Optional checks: `qpdf --check` (Apache-2.0), `pdffonts` (poppler-utils) for "all fonts embedded",
  veraPDF (GPL-3.0/MPL) if PDF/UA is required.
- Fonts: vendor OFL fonts under `guide/template/fonts/` (for example Noto Sans and Noto Sans Mono, or
  IBM Plex), referenced with `@font-face`, so output does not depend on host fonts.

#### 4.2 Mapping each vendor-guide element (WeasyPrint 70.0 support verified [53])

| Element | Implementation |
|---|---|
| A4, margins | `@page { size: A4; margin: 20mm 18mm 24mm 18mm }` |
| Cover with colour band | `@page cover { margin: 0 }` and a full-bleed `<section class="cover">` with a coloured `div` band, title, version, date (`page: cover`) |
| Notes/cautions page | static `front/notices.html` (legal, the meaning of the callout icons) with `page: front`, roman page numbers (`counter(page, lower-roman)`) |
| TOC with dot leaders and page numbers | generated `<nav class="toc">` of `<a href="#id">`. `a::after { content: leader('.') target-counter(attr(href), page) }` |
| Chapter openers | `section.chapter > header.opener { page: opener; break-before: right }` with a big chapter number from `counter(chapter)` |
| Running footer with page number and chapter title | `h1 { string-set: chapter-title content() }`. `@page { @bottom-left { content: string(chapter-title) } @bottom-right { content: counter(page) } }` (named strings and margin boxes supported) |
| Numbered tables | `section.chapter { counter-increment: chapter; counter-reset: table }`. `caption::before { counter-increment: table; content: "Table " counter(chapter) "-" counter(table) ". " }`. Pandoc emits `<caption>` from a table caption (`: Caption` syntax) |
| NOTE / CAUTION / WARNING | Pandoc `alerts` extension (`> [!NOTE]`, `> [!CAUTION]`, `> [!WARNING]`, verified in MANUAL 3.14 [54]) produces a `div` with the alert class (exact HTML shape assumed). Style with `border-left`, an icon, `break-inside: avoid`. The same source renders as alerts on GitHub |
| Gray code blocks | `pre { background: #eeeeee; padding: 3mm; font: 8.5pt/1.35 "Noto Sans Mono"; white-space: pre-wrap }` plus Pandoc highlighting |
| PDF bookmarks | `h1 { bookmark-level: 1 } h2 { bookmark-level: 2 }` (supported) |
| Accessibility | PDF/UA generation is supported, but WeasyPrint does not guarantee validity [53]. Check with veraPDF if it matters |

Pandoc chapter command (per file): `pandoc -f gfm+alerts -t html5 --section-divs
--id-prefix=chNN- --lua-filter=guide/template/filters/guide.lua guide/chapters/NN-slug.md -o
build/guide/NN.html`. Whether `gfm` accepts `+alerts` explicitly or enables it by default is
UNVERIFIED (the MANUAL lists the extension). Use `commonmark_x+alerts` if needed. The Lua filter
adds `id`s, wraps tables with captions and maps image paths.

#### 4.3 Typst runner-up (if the owner prefers it)

`pandoc -t typst` per chapter, a `guide/template/guide.typ` with `set page(paper: "a4")`,
`outline()` (default fill is `repeat(body: [.], gap: 0.15em)`, which gives dot leaders, verified
[55]), headers and footers via `context` plus a heading query, `figure(kind: table)` numbering,
alert divs mapped to Typst boxes by a Lua filter, then `typst compile --pdf-standard ua-1`
(Typst 0.14+ [55]). Image `ghcr.io/typst/typst:0.15.1`. Upside: one binary, very fast, best
typography. Downside: raw HTML in chapters is dropped, and the template is written in Typst instead
of CSS.

#### 4.4 Versions in the text come from the stack

`tools/guide_vars.py` runs `docker compose config --format json` for every app and writes
`build/guide/vars.yaml` (`image.<service>`, `port.<service>`, ...). That file is passed with
`--metadata-file`, and chapters use `$image.llama$`-style variables through the Lua filter. A check
fails if a chapter contains a literal `@sha256:` or an image tag that is not in the stack. So
Renovate bumps reach the guide automatically.

#### 4.5 Parallel build design (`tools/guide.py build [--proofs] [--chapter NN]`)

1. **Parallel, one process per chapter (JOBS):** Pandoc to an HTML fragment, then the diagram renders
   (D2/Graphviz to SVG, if used), image optimisation and markdownlint per chapter.
2. **Serial, about 1–2 s (assumed):** assemble `book.html` from the cover, the notices, the TOC built
   from the fragments' `h1`/`h2`, and the chapters. Run lychee `--offline --include-fragments` on it.
3. **Serial:** one WeasyPrint pass (`weasyprint book.html guide.pdf`). Estimated 10–40 s for 100–200
   pages (assumed; could not be measured, see §0). The book is one pass because page numbers and
   the TOC need the whole flow.
4. **Parallel, with `--proofs`:** one WeasyPrint process per chapter (`build/guide/proof-NN.pdf`), at
   the same time as step 3, for quick review of a chapter and to find which chapter breaks layout.
5. **Parallel:** `qpdf --check`, `pdffonts`, `pdftotext` for a text diff against the last release
   (review aid), and a page-count report.

Escalation if a single pass ever exceeds about 60 s: two passes per chapter (pass 1 in parallel gets
page counts and anchor pages via WeasyPrint's Python API, pass 2 in parallel renders with `@page {
counter-reset: page N }` offsets), then the front matter with known numbers, then merge with qpdf.
This costs cross-chapter links and is not worth it at guide scale.

`--chapter NN` renders one chapter alone for fast iteration. The CI `guide` job runs build plus
`--check` and uploads `guide.pdf` (7-day retention, so the 500 MB artifact quota holds).

### 5. CLAUDE.md / AGENTS.md template outline for this project

Facts that shape it (verified [51][52]): Claude Code reads `AGENTS.md` only when there is **no**
`CLAUDE.md`/`CLAUDE.local.md` in the working directory **or any directory above it**. A `CLAUDE.md`
with `@AGENTS.md` imports it. Subdirectory `CLAUDE.md` files load on demand. `.claude/rules/*.md` can
be scoped with `paths:`. Keep each file under 200 lines. `claudeMdExcludes` skips ancestor files.
AGENTS.md is stewarded by the Agentic AI Foundation (Linux Foundation), and "the closest AGENTS.md to
the edited file wins". Because an ancestor `CLAUDE.md` exists in the home directory, a bare
`AGENTS.md` here would **not** be read by Claude Code. Use the import.

Files:

```
AGENTS.md                 canonical, ≤200 lines, every harness
CLAUDE.md                 "@AGENTS.md" + "## Claude Code" (agent spawning, hooks, artifact/Discussions rules)
stack/AGENTS.md + stack/CLAUDE.md (@AGENTS.md)     compose conventions
guide/AGENTS.md + guide/CLAUDE.md                  writing and template conventions
evals/AGENTS.md + evals/CLAUDE.md                  eval rules
.claude/rules/workflows.md (paths: .github/**)     Actions conventions (SHA pins, permissions, zizmor)
.claude/settings.json      PreToolUse hooks: block git push to main, block printing key files,
                           enforce the agent model rule
.claude/settings.local.json  claudeMdExcludes for the home-directory CLAUDE.md (owner's decision)
```

`AGENTS.md` outline (mirrors the Hue CLAUDE.md, cut to fit infra work):

1. **Purpose** (3 lines): what the stack approximates, that the deliverable is the PDF guide plus
   `stack/`, that the repo is private, and that private data never goes in.
2. **How I want you to work.** Plan, then build. The approval policy (the owner's standing-approval
   wording, or "ask before X"). **Edge cases before automation:** before any deploy, sync, prune or
   model-download automation, enumerate the lifecycle cases on both sides (TrueNAS app added, renamed,
   rolled back, dataset restored from snapshot, GPU swapped, model file replaced) and write
   automatic / offered / forbidden into the feature's contract under `docs/`. A changelog line for
   every change that alters the stack or the guide. A new document: decide whether it belongs in the
   README index. Small commits.
3. **Everything through GitHub:** issue first (labels from `.github/labels.json`, board), branch with
   the issue number, PR "Closes #N", close issues with the PR and release named. Tags `vX.Y` for
   releases (guide PDF plus stack bundle), decisions in `question` issues, reports archived in
   Discussions with placeholders. **No branch protection on Free:** never push to `main`. The
   pre-push hook and the `audit-main` job enforce it.
4. **Working with agents:** parallel by default. The coordinator writes the contract into `docs/`
   first. One writer per file. Briefs are self-contained. Research agents are read-only and write one
   `docs/research/` file. No agent runs `git`. The coordinator integrates, runs `tools/check.sh`,
   commits. The model and effort rule (owner) and its hook. Typical split: `stack/<app>` /
   `tools/*.py` plus tests / `guide/chapters/NN` / `docs/` contract.
5. **Environment:** c4dev (192.0.2.20, 32 cores, 15 GiB, Docker, no Node). TrueNAS (192.0.2.10,
   SCALE 25.10.8, GPU RTX 4080 16 GB). What an agent may do on TrueNAS: read via API (`deploy.py
   plan|drift`). Write only via `deploy.py apply`. Never `docker` over SSH on the NAS, never delete
   datasets.
6. **Targets:** TrueNAS SCALE 25.10.8 "Goldeye" today (API v25.10, client `TS-25.10.8`). TrueNAS 27
   only after a reviewed upgrade PR. Compose spec features allowed (no `build:`,
   absolute dataset paths, GPU reservation syntax), image policy (amd64 CUDA, `tag@sha256`, registry
   allow-list), local-only rule (SearXNG; any cloud fallback is opt-in), Python 3.12+ stdlib for
   tools.
7. **Layout:** `stack/<app>/{compose.yaml,config/}`, `deploy/{truenas.toml,truenas.env,ci.env}`,
   `guide/{chapters,template}`, `evals/`, `tools/`, `docs/` (contracts, `status.md`, `research/`),
   `build/` (ignored).
8. **Commands:** `tools/setup-checks.sh`, `tools/check.sh [--only …]` (and the list of checks),
   `tools/guide.py build [--proofs|--chapter NN]`, `tools/deploy.py validate|render|plan|apply|drift|status`,
   `tools/eval.py run|compare|verify`, `JOBS=N`. The rule: every new tool is parallel from the start,
   and only what talks to TrueNAS, GitHub or registries stays serial.
9. **Deploy (GitOps)** in 6 lines: desired `deploy/truenas.toml` at tag → `deploy.py plan` → `apply`
   (approval) → drift timer → one `deploy` issue.
10. **Evals gate** in 4 lines: inference changes need a passing results file for their config hash.
11. **Guide conventions** (pointer to `guide/AGENTS.md`): one chapter per file `NN-slug.md`, alerts
    syntax, captions, no literal image tags, placeholders only.
12. **Security and privacy:** placeholders (192.0.2.10, 192.0.2.20, example.com), where keys live
    (`~/.config/local-agent-stack/`, 0600), never print or commit them, gitleaks rules.
13. **Licensing:** the repo's own licence (owner's decision; private for now), third-party docs not
    copied into the repo, model licences recorded per model in `stack/<app>/MODELS.md`.

## Fit with Claude Code features

| Claude Code feature | How this tooling matches it | What is lost or different |
|---|---|---|
| CLAUDE.md project memory | `AGENTS.md`, read by opencode, goose, Aider, Codex and Claude Code (via import), with nested files per area | `.claude/rules` `paths:` scoping is Claude-only. Other harnesses get nesting by directory only. Local models have smaller contexts, so the files must stay short |
| Hooks (PreToolUse etc.) | git `pre-push` hook and `tools/check.sh` give harness-independent gates. Claude hooks where Claude runs | Local harnesses' hook systems differ (agent C). The git hook is the common floor |
| Sub-agents and parallel work | The contract-first, one-writer-per-file workflow is harness-neutral. Harbor can run several agent instances against one server | One 16 GB GPU serves parallel agents only through server slots, so parallel local agents are slower than parallel cloud agents |
| Plan mode / permission modes | "Plan first" and approval in AGENTS.md. `deploy.py apply` is the only write path to TrueNAS | Enforcement depends on each harness's permission model. The TrueNAS API key scope is the hard limit |
| GitHub integration | `gh` CLI for issues, PRs, Discussions, the drift issue | No branch protection or code and secret scanning on a private Free repo. Compensated locally |
| Measuring "as close as possible to Claude Code" | Harbor runs Terminal-Bench, Aider polyglot and SWE-bench subsets with local agents and models, on a fixed, repeatable scale | A Claude Code reference score needs the cloud. That conflicts with the local-only rule unless the owner allows a one-off run (open question) |

## Verified vs assumed

**Verified** (read in primary sources or tested on c4dev, 2026-11-15):

- GitHub Free and Pro private-repo feature limits: protected branches, rulesets, environments, code
  scanning, secret scanning, push protection, Dependabot, Actions $12/$18, storage, runner rates and
  specs, `ubuntu-slim` container limits, 20 concurrent jobs, self-hosted runners free in the billing
  docs [1]–[14].
- Runner image tool versions (Compose 5.7.1 on slim, 2.38.2 on 24.04, 5.1.3 on 26.04) [14].
- Dependabot `docker-compose` GA date, its file regex and digest parsing (dependabot-core source)
  [15]–[17]. Renovate compose file pattern, `docker:pinDigests`, `config:best-practices`,
  `minimumReleaseAge`, `customManagers`, `regex:` versioning [18]–[21].
- Every tool version and licence in the tables (GitHub releases API, PyPI, npm, Docker Hub, GHCR).
- `docker compose config` flags (`--hash`, `--images`, `--format json`, `--no-env-resolution`,
  `--resolve-image-digests`, `--lock-image-digests`, `--quiet`), and that it runs without a daemon
  (tested). The `com.docker.compose.config-hash` label (source) [27][28].
- Trivy's IaC coverage list without compose [24]. lychee flags [25].
- TrueNAS `app.create`, `app.update` (25.10 and 27.0), `app.config`, `app.query`, `app.pull_images`,
  the method pages that exist, `privilege.create` fields, REST removal and API key rules, and the
  api_client features and usage [29]–[37].
- For the owner's 25.10.8: the api_client tag `TS-25.10.8` exists, and at that tag midclt `-K` takes
  the raw key and the Python client logs in with `auth.login_with_api_key` [35]. `auth.login_ex`
  mechanisms in 25.10 (no SCRAM) [63]. The four predefined group roles, only FULL_ADMIN writes apps,
  custom privilege sets deprecated until removal in 28 [64]. There is no hosted `v25.10.8` doc set,
  only `v25.10`.
- GitHub Free private repos: the quoted rulesets and protected-branch availability sentences [2][3].
- llama-bench flags and llama-server `--metrics` metric names, `-np`, `--kv-unified` [44]. llama.cpp
  v1.0.0 release (2026-11-13).
- BFCL categories, `--run-ids`, `--skip-server-setup`, `REMOTE_OPENAI_BASE_URL`, and the
  `OPENAI_BASE_URL` handler [46]. Harbor datasets, task counts, CLI flags, `--base-url`, agent list
  [47]. Aider benchmark options [48]. SWE-bench resource advice and mini-swe-agent flags [49]. The
  ragas metric list and `llm_factory` [50].
- AGENTS.md stewardship and precedence [51]. Claude Code's AGENTS.md and CLAUDE.md loading rules, the
  200-line advice, `claudeMdExcludes` [52].
- WeasyPrint 70.0 feature support and install requirements [53]. The pandoc 3.14 `alerts`
  extension, PDF engines and release assets [54]. Typst outline fill default, 0.14 PDF/UA, 0.15.1
  date [55]. Vivliostyle CLI options [56]. pagedjs-cli release dates [57]. `pandoc/core` image at 3.11
  [58]. Prince desktop price, FOP 2.12 [59].
- Komodo ResourceSync, polling and webhook behaviour and stack-from-git fields [41]. The doco-cd
  feature list [42].
- The trivy-action tag compromise of 2026-03-19 (vendor post-mortem and security press) [23].

**Assumed** (inference, secondary sources or memory; check before relying on them):

- GitHub Pro costs $4/month (secondary sources [60]). Discussions and Projects have no plan limit on
  private repos. Billing rounds jobs to whole minutes. CI cost per push.
- PRs opened with `GITHUB_TOKEN` do not trigger workflows (standard behaviour, not re-read).
- Mend Community Cloud is free for private repos (Renovate docs and Marketplace via search [22]).
- How Dependabot handles `server-cuda-bNNNN` tags (UNVERIFIED).
- TrueNAS 27 final in early December 2026 (secondary). The 25.10 `services:` key requirement (forum and
  blog). That TrueNAS overrides the compose `name:`. That `app.config` returns the stored compose for
  custom apps in a form comparable to the rendered YAML. That a 25.10 API key carries exactly its
  user's roles. The `system.info` version field name. A third-party report that FULL_ADMIN inside a
  custom privilege breaks login [65].
- Artifact attestations on private personal repos (UNVERIFIED). That keyless cosign leaks the repo
  identity into the public log.
- Every eval duration and every PDF render time. Batching non-determinism at temperature 0. That
  ragas needs JSON or grammar output from the server.
- The exact HTML shape Pandoc gives alerts. Whether `gfm` takes `+alerts`. yamllint `truthy`
  settings for workflows. Arcane's git-sync details. The BFCL model-config file path.

## Open questions for the owner

1. **GitHub Pro ($4/month)** for protected branches, rulesets with required checks, and environments
   on this private repo? Without it, "PRs only" is a convention backed by a pre-push hook and an
   after-the-fact audit. Code and secret scanning stay unavailable either way on a personal account.
2. **Renovate:** run it as a scheduled Action with a fine-grained PAT or GitHub App token (data stays
   on GitHub), or install Mend's hosted app (Mend reads the private repo)?
3. **Deploy model:** approval-gated push from c4dev (recommended), or automatic pull on the NAS
   (doco-cd or a TrueNAS cron job tracking a `deploy` tag)?
4. **TrueNAS API keys on 25.10.8:** applying apps needs a FULL_ADMIN key, since no smaller predefined
   role writes apps. Accept a FULL_ADMIN key in a 0600 file on c4dev, used only by `deploy.py
   apply`, beside a READONLY_ADMIN key for the drift timer? Or keep the full-admin key off disk and
   paste it per apply session? (25.10 has no SCRAM; the key is protected by TLS only.)
5. **Guide engine:** HTML/CSS with WeasyPrint (recommended; the template is CSS, and an HTML version
   comes free), or Typst (best typography, the template is Typst)? Which OFL font family for the
   vendor look?
6. **Reference scores:** allow one cloud-model run (for example Claude Code in Harbor) as a yardstick
   for "how close", or keep evals strictly local?
7. **The home-directory `CLAUDE.md`** (an older copy of another project's instructions) loads into
   every session in this repo. Move it, or exclude it with `claudeMdExcludes` in this repo's
   `.claude/settings.local.json`?

## Sources

All read 2026-11-15 unless noted.

1. GitHub's plans — https://docs.github.com/en/get-started/learning-about-github/githubs-plans
2. About rulesets (availability box) — https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets
3. About protected branches — https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
4. About code scanning — https://docs.github.com/en/code-security/code-scanning/introduction-to-code-scanning/about-code-scanning
5. About secret scanning — https://docs.github.com/en/code-security/secret-scanning/introduction/about-secret-scanning
6. Push protection — https://docs.github.com/en/code-security/concepts/secret-security/push-protection
7. GitHub security features — https://docs.github.com/en/code-security/getting-started/github-security-features
8. Managing environments for deployment — https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments (and REST deployments/environments pages)
9. GitHub Actions billing — https://docs.github.com/en/billing/concepts/product-billing/github-actions
10. Actions runner pricing — https://docs.github.com/en/billing/reference/actions-runner-pricing
11. GitHub-hosted runners reference — https://docs.github.com/en/actions/reference/runners/github-hosted-runners
12. Actions limits — https://docs.github.com/en/actions/reference/limits
13. Secure use reference (self-hosted runner hardening) — https://docs.github.com/en/actions/reference/security/secure-use
14. Runner images READMEs (ubuntu-slim, Ubuntu 24.04, Ubuntu 26.04; images 20261111) — https://github.com/actions/runner-images
15. Dependabot Docker Compose GA (2025-02-25) — https://github.blog/changelog/2025-02-25-dependabot-version-updates-now-support-docker-compose-in-general-availability/
16. Dependabot supported ecosystems — https://docs.github.com/en/code-security/reference/supply-chain-security/supported-ecosystems-and-repositories
17. dependabot-core `docker/lib/dependabot/docker_compose/file_fetcher.rb`, `file_parser.rb` — https://github.com/dependabot/dependabot-core
18. Renovate docker-compose manager — https://docs.renovatebot.com/modules/manager/docker-compose/
19. Renovate Docker docs (digest pinning) — https://docs.renovatebot.com/docker/
20. Renovate configuration options — https://docs.renovatebot.com/configuration-options/
21. Renovate regex versioning — https://docs.renovatebot.com/modules/versioning/regex/
22. Mend Renovate cloud-hosted overview (via search) — https://docs.renovatebot.com/mend-hosted/overview/
23. Trivy supply chain attack (Aqua) — https://www.aquasec.com/blog/trivy-supply-chain-attack/ ; Snyk analysis — https://snyk.io/articles/trivy-github-actions-supply-chain-compromise
24. Trivy IaC coverage docs tree — https://github.com/aquasecurity/trivy/tree/main/docs/guide/coverage/iac
25. lychee README (CLI options) — https://github.com/lycheeverse/lychee
26. Release pages used for versions: https://github.com/{rhysd/actionlint, koalaman/shellcheck, hadolint/hadolint, adrienverge/yamllint, DavidAnson/markdownlint-cli2, lycheeverse/lychee, gitleaks/gitleaks, aquasecurity/trivy, anchore/grype, renovatebot/renovate, docker/compose, zizmorcore/zizmor, zavoloklom/docker-compose-linter}/releases, plus PyPI and npm JSON
27. Compose labels — https://github.com/docker/compose/blob/main/pkg/api/labels.go
28. `docker compose config --help`, Compose v5.6.0 on c4dev (tested)
29. TrueNAS API v25.10 `app.create` — https://api.truenas.com/v25.10/api_methods_app.create.html
30. TrueNAS API `app.update` v25.10 and v27.0 — https://api.truenas.com/v25.10/api_methods_app.update.html , https://api.truenas.com/v27.0/api_methods_app.update.html
31. `app.config` — https://api.truenas.com/v25.10/api_methods_app.config.html
32. `app.query` — https://api.truenas.com/v25.10/api_methods_app.query.html
33. `app.pull_images` — https://api.truenas.com/v25.10/api_methods_app.pull_images.html
34. `privilege.create` — https://api.truenas.com/v25.10/api_methods_privilege.create.html
35. TrueNAS API client README — https://github.com/truenas/api_client
36. TrueNAS 26 deprecations — https://www.truenas.com/docs/scale/26/gettingstarted/deprecations/
37. TrueNAS API docs landing — https://www.truenas.com/docs/scale/api/
38. TrueNAS 27 rename and RC.1 (secondary, via search) — https://www.truenas.com/blog/truenas-27-is-here/ , https://phoronix.com/news/TrueNAS-27-RC.1-Release
39. TechnoTim, "How I Run Docker on TrueNAS Like a Pro" (2025-07-14, updated 2026-01-07) — https://technotim.com/posts/truenas-docker-pro/
40. TrueNAS forum, 25.10 RC1 custom app YAML (via search) — https://forums.truenas.com/t/25-10-rc1-custom-app-yaml-input-bug/55300
41. Komodo docs — https://komo.do/docs/automate/sync-resources , https://komo.do/docs/deploy/compose , https://komo.do/docs/releases/v2.0.0
42. doco-cd README — https://github.com/kimdre/doco-cd
43. Arcane — https://github.com/getarcaneapp/arcane ; Dockge — https://github.com/louislam/dockge
44. llama.cpp `tools/llama-bench/README.md`, `tools/server/README.md`, release v1.0.0 — https://github.com/ggml-org/llama.cpp
45. llama-benchy — https://pypi.org/project/llama-benchy/ , https://github.com/eugr/llama-benchy
46. BFCL README, TEST_CATEGORIES.md, `openai_completion.py`, `base_oss_handler.py` — https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard
47. Harbor README, `registry.json`, `src/harbor/cli/jobs.py`, `docs-mintlify/agents/base-url-management.mdx` — https://github.com/laude-institute/harbor
48. Aider benchmark README — https://github.com/Aider-AI/aider/blob/main/benchmark/README.md
49. SWE-bench README — https://github.com/SWE-bench/SWE-bench ; mini-swe-agent `docs/usage/swebench.md` — https://github.com/SWE-agent/mini-swe-agent
50. ragas `docs/howtos/customizations/customize_models.md`, `src/ragas/metrics/collections` — https://github.com/explodinggradients/ragas
51. AGENTS.md — https://agents.md/
52. Claude Code memory docs — https://code.claude.com/docs/en/memory
53. WeasyPrint 70.0 API reference and first steps — https://doc.courtbouillon.org/weasyprint/stable/api_reference.html , https://doc.courtbouillon.org/weasyprint/stable/first_steps.html
54. Pandoc 3.14 MANUAL and changelog — https://raw.githubusercontent.com/jgm/pandoc/3.14/MANUAL.txt , https://github.com/jgm/pandoc/releases/tag/3.14
55. Typst outline docs (0.15.1) — https://typst.app/docs/reference/model/outline/ ; Typst 0.14.0 changelog — https://typst.app/docs/changelog/0.14.0/ ; 0.15.1 — https://typst.app/docs/changelog/0.15.1/
56. Vivliostyle CLI README — https://github.com/vivliostyle/vivliostyle-cli
57. npm registry `pagedjs`, `pagedjs-cli` — https://registry.npmjs.org/pagedjs-cli
58. Docker Hub `pandoc/core` tags — https://hub.docker.com/r/pandoc/core/tags
59. Prince purchase page — https://www.princexml.com/purchase/ ; Apache FOP binaries — https://archive.apache.org/dist/xmlgraphics/fop/binaries/
60. GitHub Pro price (secondary, via search) — https://creditforstartups.com/resources/github-pro-pricing ; GitHub pricing page — https://github.com/pricing
61. Self-hosted runner fee postponed (Dec 2025, secondary) — https://www.theregister.com/2025/12/17/github_charge_dev_own_hardware/ ; https://resources.github.com/actions/2026-pricing-changes-for-github-actions/
62. Owner's reference project (read-only, style): its CLAUDE.md, `.github/`, `tools/check.sh`, `tools/parallel.py`, `docs/cicd-gitops-design.md`
63. TrueNAS API v25.10 `auth.login_ex` — https://api.truenas.com/v25.10/api_methods_auth.login_ex.html
64. TrueNAS API v25.10 Role-Based Access Control — https://api.truenas.com/v25.10/rbac.html
65. Third-party report, FULL_ADMIN in a custom privilege (unofficial, via search) — https://bearbinary.github.io/omni-infra-provider-truenas/upstream-bugs/truenas-role-recursion/
(api_client tag `TS-25.10.8`: https://github.com/truenas/api_client/tree/TS-25.10.8, read 2026-11-15)
