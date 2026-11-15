# PROJECT_NAME

<!-- Template from local-agent-stack/clients/templates/AGENTS.md. Replace every CAPITALISED
placeholder, delete what does not apply, keep it under 150 lines. Every line here is sent with
every request to a 64K-context local model: keep only rules that are always true, and put
procedures in commands (.opencode/commands/) and details in docs/. -->

ONE_SENTENCE_WHAT_THIS_PROJECT_IS. Deliverable: WHAT_IT_PRODUCES.
The repository is PUBLIC_OR_PRIVATE.

## Always

- Plan first, then build. Before you change anything, state the approach and the exact files
  you will touch (`/plan`). Routine work is approved: do it and report. Ask the owner only for
  a real design choice or something that needs their hands.
- Contract before code. When more than one agent works on a change, write the shared contract
  (interface, file layout, names, ports, variables) into `docs/` and commit it first.
- Edge cases before automation. Before building anything that acts on its own (sync, import,
  deploy, delete), list the lifecycle cases (added, renamed, moved, replaced, removed, restored
  from backup) and write in the contract which are automatic, which are only offered, and
  which are forbidden without a click.
- Verified facts only. Versions, flags, image tags, API fields and UI labels come from primary
  sources (official docs, release notes, source code, `--help`). Never invent one. Write
  `UNVERIFIED` next to anything you could not check.
- Small commits with clear messages. Run `CHECK_COMMAND` before every commit.
- Never commit secrets or private data. Placeholders only: PLACEHOLDER_LIST (for example
  `192.0.2.10`, `lab.example.com`, `sk-local-...`). Real values live in `*.env` files that git
  ignores; `*.env.example` documents them.
- Never push to main. Push a feature branch by name and open a pull request.

## GitHub flow

1. Issue first: `gh issue create` with labels from `.github/labels.json`, or `/issue N` for an
   existing one.
2. Branch from an up-to-date main: `TYPE/short-slug-N` (feat, fix, docs, chore; issue number last).
3. Open the pull request early with `Closes #N` in its body (`/pr`).
4. A change people would notice adds a line under `## Unreleased` in `CHANGELOG.md`, with the
   issue number.
5. Merge when the required checks pass. Close the issue with one line naming the PR.
6. Decisions for the owner go into an issue labelled `question`.
7. Research notes, agent reports and reviews are also posted to GitHub Discussions, with
   private data replaced by placeholders.

## Working with agents

- The coordinator (the default agent) plans, writes the contract, briefs the other agents,
  integrates their work, runs the checks and commits. Only the coordinator runs git and gh.
- Split work into parts with disjoint files. One writer per file.
- Run at most 2 subagents at a time (3 only for short read-only research). One GPU serves every
  agent; more agents make each one slower.
- `researcher`: read-only, writes exactly one file under `docs/research/`.
  `builder`: creates or edits only the files its brief names, never runs git.
  `reviewer`: read-only review of the diff, findings by severity with file and line.
- A brief is self-contained: the goal, the docs to read, the exact files it may change,
  "others edit the rest of the checkout; do not run git", the conventions, and the commands
  that prove it is done.
- Every subagent ends with a report: files changed, checks run and their result, anything
  UNVERIFIED or needed from another file.

## Commands

| Command | What it does |
|---|---|
| `/plan <change>` | read-only plan: approach, files, contract, split, checks |
| `/issue <N>` | read the issue, branch, write the contract, start the parts |
| `/pr [N]` | checks, changelog line, push the branch by name, open or update the PR |
| `/check` | run `tools/check.sh` and summarise what fails |

Project commands:

- Checks: `CHECK_COMMAND` (the same checks CI runs)
- Tests: `TEST_COMMAND`
- Build: `BUILD_COMMAND`

New tools run independent work in parallel on all cores from the start. Anything that talks
to the GPU server under load (benchmarks, evals) runs one at a time.

## Layout

```
SRC_DIR/      WHAT_IS_THERE
docs/         contracts (*-design.md), research/, status.md
tools/        check.sh and helper scripts
build/        generated output (git ignores it)
```

## Environment

- Workstation: WORKSTATION_NAME (Ubuntu). The coding agent runs here. Services never run here;
  they run as containers on SERVER_NAME.
- Models are local, served at `https://llm.LAB_DOMAIN`. The context is 64K tokens: read only
  the files you need, keep replies short, and let compaction work.
- MCP tools: `searxng` (web search), `fetch` (read a URL), `kb` (the owner's documents), `ssh`
  (only the hosts in the ssh-mcp policy; destructive commands need the owner's approval).

## Where the detail lives

- `docs/status.md`: current state, with links to the open issues.
- `docs/*-design.md`: the contract for each feature.
- `docs/research/`: research notes, with sources.
- `CHANGELOG.md`: every release, and `## Unreleased` for the next one.
