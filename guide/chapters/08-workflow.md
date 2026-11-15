title: Running projects with agents

# Running projects with agents

This chapter describes how to run a software project with the coding agent from Chapter 7 the way
a Claude Code project is run. A short project memory file holds the standing rules. A contract
under `docs/` is written before any code. Background agents each own a disjoint set of files while
a coordinator integrates their work. Every change goes from a GitHub issue to a pull request that
must pass the required checks. A changelog and tagged releases record what shipped. The Local Agent
Stack repository is run this way, and its `CLAUDE.md` is the example this chapter refers to.

The method is the same as with a cloud model; the budget is not. Every agent shares one 16 GB GPU,
and every token of fixed prompt is processed again for each new agent context. The sections below
say where the method bends for that. The examples use OpenCode, the GitHub CLI (`gh`, version
2.103.2 checked) and this repository; replace `<owner>/<repo>` with your GitHub account and
repository.

## Project memory files

### Memory files each harness reads

A project memory file carries the rules that apply to every task in a repository: how to plan,
how changes reach GitHub, how agents divide work, which commands check the work. Make `AGENTS.md`
the canonical file, because every local harness reads it, and keep a `CLAUDE.md` beside it that
imports it for Claude Code.

Table: Project memory files by harness

| Harness | Reads | How it shares one file |
|---|---|---|
| OpenCode 2.3.0 | `AGENTS.md`: the global `~/.config/opencode/AGENTS.md`, then the project's files upward from the working directory and nested ones | Native. It reads `CLAUDE.md` only when listed under `instructions` in the project `opencode.jsonc` |
| Claude Code 2.1.277 or later | `CLAUDE.md` files. `AGENTS.md` only when no `CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md` exists in the working directory or any directory above it | A `CLAUDE.md` that contains the line `@AGENTS.md` |
| Qwen Code 0.27.4 | `QWEN.md` and `AGENTS.md`; the list is set by `context.fileName` | Set `context.fileName` to `["AGENTS.md", "QWEN.md"]` |
| Codex CLI 0.169.0 | `AGENTS.md` from the repository root to the working directory, truncated at 32 KiB | Native |

The repository ships two templates for new projects:

- `clients/templates/AGENTS.md`: the canonical rules. It reproduces the working style of this
  chapter: contracts in `docs/`, parallel agents capped at two or three on one GPU, and the
  GitHub flow.
- `clients/templates/CLAUDE.md`: the line `@AGENTS.md` followed by a short section of rules that
  apply only to Claude Code.

The template files are the authority for their own wording; the steps in
[Add memory files to a project](#add-memory-files-to-a-project) copy and adapt them.

### Prompt budget of the memory file

Every request carries the harness's own prompt, the memory file and the conversation so far. A
local server processes that prefix again on every prompt-cache miss and for every new agent
context. With a cloud model this costs little; on one 16 GB GPU it costs seconds that every other
agent waits for.

Table: Fixed prompt before the first task token

| Item | Tokens | Basis |
|---|---|---|
| OpenCode 2.3.0 system prompt and tool schemas | 5,340 | Measured: first headless request, no memory file |
| A memory file of about 100 lines and 7 KB | about 1,800 | Estimate at about 4 bytes per token |
| Memory files of a long-lived Claude Code project (33 KB) | about 8,000 | Same estimate |

At the estimated prefill rate of the default model, 900 to 1,500 tokens per second (Appendix B),
a new agent context with OpenCode's prompt and a 1,800-token memory file (about 7,100 tokens)
costs 5 to 8 seconds before it reads a single file. With an 8,000-token memory file (about 13,300
tokens) it costs 9 to 15 seconds, and each parallel agent pays it again.
Long rule files are also followed less reliably by local models as the context grows.

Keep the memory file within these limits:

- Under 150 lines, the limit that the template states, and preferably under 2,000 to 3,000 tokens
  (about 8,000 to 12,000 bytes).
- Only rules that are true for every task. Move detail into the contracts under `docs/` and into
  skills (`.opencode/skills/<id>/SKILL.md`; OpenCode also reads `.claude/skills/`), which load on
  demand.
- A rule that a tool can enforce belongs in the tool. The prose rule then only explains it (see
  the next table).
- Change the file between sessions, not during one. A changed prefix misses the server's prompt
  cache, and the hybrid-attention models of the default profile reprocess the whole prompt when
  earlier context changes.

### Rules stated in prose and enforced by tools

A local model forgets a prose rule sooner than a cloud model does. Back every rule that can be
checked mechanically with a tool, so that a slip is caught even when the model misses it.

Table: Where the standing rules are enforced

| Rule | Stated in | Enforced by |
|---|---|---|
| Never push to `main` | `AGENTS.md` | `tools/hooks/pre-push`; the OpenCode plugin `clients/opencode/plugins/guard.ts`; a branch ruleset on GitHub |
| No secrets or private data in files | `AGENTS.md` | `guard.ts`; the `secrets` check (gitleaks) in the pre-push hook and in CI |
| Checks pass before a merge | `AGENTS.md` | `tools/check.sh`; the four required CI jobs; for a change to the models or their configuration, the regression gate of `tools/eval.py`, run from the workstation |
| Only the coordinator changes the repository with `git` and `gh` | `AGENTS.md` | Permission rules in the agent definitions under `clients/opencode/agents/`: the builder may run neither, the researcher and the reviewer only read-only commands |
| One writer per file | Each brief | The coordinator's review of `git status` before every commit |
| Contract before code | `AGENTS.md` | The pull request: the contract is its first commit |

### Add memory files to a project

#### Prerequisites

- OpenCode is configured on c4dev as described in Chapter 7.
- `<stack-repo>` is the local clone of the Local Agent Stack repository on c4dev.
- `<project>` is the root of the repository you are setting up.

#### About this task

This task copies the two templates into a project, fits them to it, checks their size and confirms
that each harness loads them.

#### Steps

1. Change to the root of the project.

        cd <project>

2. Copy the templates.

        cp <stack-repo>/clients/templates/AGENTS.md AGENTS.md
        cp <stack-repo>/clients/templates/CLAUDE.md CLAUDE.md

    If the project already has a `CLAUDE.md`, move its rules into `AGENTS.md` first, then keep
    only the `@AGENTS.md` line and the Claude Code section in `CLAUDE.md`.

3. Edit `AGENTS.md`: replace every CAPITALISED placeholder of the template, such as
   `PROJECT_NAME`, `ONE_SENTENCE_WHAT_THIS_PROJECT_IS` and `PUBLIC_OR_PRIVATE`, with the project's
   own values, fill in its commands and its layout, and delete the sections that do not apply.
   Then confirm that no placeholder is left:

        grep -nE '\b[A-Z][A-Z0-9]+(_[A-Z0-9]+)+\b' AGENTS.md CLAUDE.md

    The command prints no line that is a template placeholder. Names that the project really uses
    in capitals, such as environment variables, can remain.

    !!! warning
        In a public repository, write only placeholders for addresses, domains, keys and names:
        `192.0.2.10`, `lab.example.com`, `sk-local-...`. The memory file is published with the
        code.

4. Measure both files.

        wc -l -c AGENTS.md CLAUDE.md

    `AGENTS.md` is under 150 lines, the limit that the template states, and preferably under
    about 12,000 bytes.

5. Optional: for a large area of the project, add a nested pair, for example `stack/AGENTS.md`
   and a `stack/CLAUDE.md` that contains `@AGENTS.md`. The closest `AGENTS.md` to the edited file
   applies.

6. If a `CLAUDE.md` exists in a directory above the project, for example in your home directory,
   Claude Code loads it into every session in the project. Exclude it in
   `.claude/settings.local.json`; patterns are glob patterns matched against absolute paths.

        {
          "claudeMdExcludes": ["/home/<user>/CLAUDE.md"]
        }

7. Confirm that OpenCode loads the file.

        opencode run "Without using any tool, quote the first heading of your project instructions."

    The answer quotes the first heading of `AGENTS.md`.

8. If you use Claude Code in the project, start `claude` in `<project>` and run `/context all`.

    `CLAUDE.md` is listed under **Memory files**.

#### Results

The project has a short `AGENTS.md` that every harness reads and a `CLAUDE.md` that imports it.

## Contracts before code

### Contents of a contract

A contract is the shared text that every agent working on a feature builds against: an interface,
a file layout, a wire format, a set of names. The coordinator writes it under `docs/`, you review
it, and it is committed before any agent starts. Agents start with empty contexts, so the contract
is the only place where two of them can agree.

Table: Contracts in this repository

| Contract | Path | What it fixes |
|---|---|---|
| Stack design | `docs/stack-design.md` | Decisions where the research notes differed, app and container names, hostnames, model names, datasets, secrets, the file layout |
| Guide style | `docs/guide-style.md` | The file shape, voice and elements of every chapter |
| Research contract | `docs/research-contract.md` | The template and rules of every research note |

A feature contract (`docs/<feature>-design.md`) has these sections:

- **Goal**: what the feature does and the issue number.
- **Files and owners**: every file the feature creates or changes, and which agent owns it. One
  writer per file.
- **Interfaces**: the names, options, file formats and ports the pieces share, quoted exactly.
- **Lifecycle cases**: for anything that acts on its own (a sync, a deploy, a cleanup), the
  cases on both sides (added, renamed, replaced, removed, restored from backup), each marked
  automatic, offered or forbidden.
- **Verification**: the commands that prove the feature works. This is the definition of done.
- **Open questions**: decisions that need you. Each one also goes into an issue labelled
  `question`.

### Write a feature contract

#### Prerequisites

An issue and a branch for the feature exist ([Start work on an issue](#start-work-on-an-issue)).

#### About this task

The coordinator drafts the contract from the issue; you correct it; it becomes the first commit of
the pull request, so every later commit can be reviewed against it.

#### Steps

1. Start OpenCode in the repository with `opencode`.

    The session starts with the **coordinator**, the default agent (`default_agent` in
    `opencode.jsonc`). If you switched to another primary agent, press Tab until the coordinator
    is selected again.

2. Ask for the contract. Replace `<N>` with the issue number and `<feature>` with a short name.

        Read issue #<N> (gh issue view <N>) and the docs it mentions. Write the contract
        docs/<feature>-design.md with these sections: Goal, Files and owners, Interfaces,
        Lifecycle cases, Verification, Open questions. Quote names and options exactly and
        cite the doc each one comes from. Create no other file.

3. Read the draft and correct it, either by editing the file or by telling the coordinator what to
   change.

4. Check the file with the repository's checks.

        tools/check.sh --only markdown links

    Both checks report `ok`.

5. Commit the contract and push the branch.

        git add docs/<feature>-design.md
        git commit -m "Contract: <feature> (#<N>)"
        git push -u origin <branch>

#### Results

The contract is the first commit on the feature branch. Agents can now be briefed against it.

## Coordinating parallel agents

### Agent roles

The agent definitions in `clients/opencode/agents/` divide the work into four roles. Chapter 7
installs them ([The four agents](#the-four-agents)); the files themselves are the authority for
their models and permission rules.

Table: Agent roles

| Agent | Does | Writes | git and gh |
|---|---|---|---|
| coordinator | Writes contracts and briefs, launches the other agents, integrates, runs the checks, commits | Contracts, integration files, `CHANGELOG.md` | Yes; `git push` and other writes not listed in [Using gh from agents](#using-gh-from-agents) ask you first |
| researcher | Answers one question from code, docs and the web, citing sources | The one file under `docs/` that its brief names, in this workflow under `docs/research/` | Read-only: `git log` and `git show`; every other shell command is denied |
| builder | Implements one brief | Only the files its brief names | No: `git` and `gh` commands are denied |
| reviewer | Compares a diff with its contract and reports findings | Nothing | Read-only: `git status`, `git diff`, `git log`, `git show`, `gh pr view`, `gh pr diff`; it also runs `tools/check.sh` |

How OpenCode runs them:

- Subagents always run in the background. The coordinator receives a report when a subagent
  goes idle, and again after each later round of work.
- Nesting depth is 1 by default (`experimental.subagent_depth`), so only the coordinator
  launches agents.
- The `subagent` permission action, with an agent ID as the resource, controls which agents an
  agent may launch. The three subagent files deny it for every agent; the coordinator's file allows
  only `researcher`, `builder`, `reviewer` and OpenCode's built-in `explore`.
- OpenCode documents no setting that limits how many subagents run at once. The cap below is a
  rule in `AGENTS.md` and in the coordinator's prompt; the server does not enforce it, it only
  queues the requests.

### Concurrency on one 16 GB GPU

Cap parallel work at two or three agents at a time. Every agent's requests go to the same GPU,
and three effects add up:

- **One GPU model at a time.** llama-swap's `llm` group swaps models: `coder` and `coder-moe`
  never share the GPU. `local-coder` and `local-fast` are both served by the `coder` process
  (`local-fast` arrives as its alias `coder-fast`, with thinking off), so mixing them costs
  nothing. A request for `local-coder-moe` unloads `coder`
  for every agent and client, and the next `local-coder` request loads it back. Give every agent
  in a round the same profile.
- **One slot: agents take turns.** The `coder` entry in `stack/inference/llama-swap/config.yaml`
  runs one 64K slot (`-np 1`). Concurrent requests queue, and the server keeps idle contexts in
  a host-RAM prompt cache (`--cache-ram 6144`, in MiB). Parallel agents therefore overlap their
  tool runs, file reads and tests, not their generation. Each extra agent makes every agent wait
  longer for its turn, and once the prompt cache cannot hold every context, switching back to an
  agent means processing its prompt again. Two slots would decode two requests at once, but they
  would split the same KV cache, about 32K each.
- **Every new context is prefilled from scratch.** A new agent sends the harness prompt, the
  memory file and its brief, then reads files. A 15,000-token start costs 10 to 17 seconds of
  GPU time at the estimated prefill rate, and the other agents wait during it.

Table: Concurrency guidelines

| Situation | Agents at once | Why |
|---|---|---|
| Builders editing code | 2 | Long turns; each waits for the other's turn on the one slot |
| Builders and one researcher | 3 | Research turns are short reads and searches |
| A benchmark or eval is running | 0 | Throughput measurements need the GPU alone |
| Fast profile (`local-coder-moe`) in use | All on `local-coder-moe`, or none | Any other request swaps the model |

### Self-contained briefs

A builder starts with an empty context: it knows the memory file and its brief, nothing else. A
brief that says "as discussed" fails. Write every brief so that it can be executed by an agent that
has never seen the conversation:

```
Brief: <one-line goal> (issue #<N>)

Read first:
- docs/<feature>-design.md (the contract; it wins over this brief)
- <other docs or files, with paths>

Files you may edit:
- <path>
- <path>

Others are editing the rest of the checkout at the same time. Do not touch any other
file. Do not run git or gh.

Conventions: <language version, formatting, test framework, placeholders only>

Done when:
- <observable result>
- These commands pass: <verification commands, exact>

Report: the files you changed, the commands you ran and their results, anything
you could not verify.
```

Keep the list of files exact. The coordinator checks it against `git status` before committing,
and overlapping lists are how two agents overwrite each other's work.

### Run a parallel round

#### Prerequisites

- The contract is committed on the feature branch.
- No benchmark or eval is running against the GPU server, and no client is using the fast profile
  ([Concurrency on one 16 GB GPU](#concurrency-on-one-16-gb-gpu)).

#### About this task

The coordinator splits the contract into briefs with disjoint file lists, launches the builders at
once, and integrates their results in one commit after the checks pass.

#### Steps

1. Ask the coordinator to plan the split before launching anything.

        Split docs/<feature>-design.md into builder briefs with disjoint file lists.
        At most two builders at once. Show me the split in one line per builder and
        the files you keep for yourself, then wait.

2. Check that no file appears in two lists, then tell the coordinator to launch.

        Launch both builders now with self-contained briefs in the brief format from
        AGENTS.md.

3. Wait for the reports. Each builder's report lists its files, the commands it ran and their
   results.

4. List the changed files.

        git status --porcelain

    Every path is in exactly one brief's list, or in the coordinator's own list. Anything else
    is a stray edit: revert it or reassign it before going on.

5. Run every check.

        tools/check.sh

    Each check reports `ok` or `skip`. Hand each `FAIL` back to the builder that owns the file.

6. Commit and push.

        git add <files from the briefs>
        git commit -m "<feature>: <what changed> (#<N>)"
        git push

#### Results

The feature branch carries one integrated commit that passed the same checks CI runs.

### Run a research agent

#### About this task

A research agent is read-only: it searches the code, the documentation and the web (through the
`searxng` and `fetch` tools of the MCP hub), and writes exactly one note under `docs/research/`.
The note follows `docs/research-contract.md`: it cites a source for every claim and separates
**Verified** from **Assumed**. Use one before a contract whenever the contract depends on a fact
you have not checked: a flag, an API field, a version.

#### Steps

1. Ask the coordinator to launch the researcher.

        Launch the researcher with this brief. Question: <one question>. Read
        docs/research-contract.md and follow it. Write only docs/research/<x>-<topic>.md.
        Cite a primary source with a URL for every flag, field and version. Separate
        Verified from Assumed. Edit nothing else.

2. When the report arrives, open the note and check that each claim you will rely on has a source.

3. Have the coordinator commit the note on the feature branch, and archive it
   ([Archive reports in Discussions](#archive-reports-in-discussions)).

#### Results

The note is committed and cited by the contract that depends on it.

## Working through GitHub

### Prepare a repository for the workflow

#### Prerequisites

`gh` is installed on c4dev and authenticated as the account that owns `<owner>/<repo>`.

#### About this task

This task enables what the workflow uses on GitHub: a token scope for project boards, a board,
Discussions and the labels.

#### Steps

1. Check the authentication and the token scopes.

        gh auth status

    The output names your account and lists the token scopes.

2. If `project` is not among the scopes, add it.

        gh auth refresh -s project

3. Enable Discussions.

        gh repo edit <owner>/<repo> --enable-discussions

4. Create a project board, then note its number.

        gh project create --owner <owner> --title "<project title>"
        gh project list --owner <owner>

5. Create the labels. The Local Agent Stack repository keeps its labels in `.github/labels.json`,
   one entry per label with its name, colour and description:

    {{ include .github/labels.json }}

    Four labels are used by tools, not only by people: `question` marks decisions that need you;
    `deploy` is the label of the issue that `deploy.py drift --issue` keeps open (Chapter 10);
    Renovate adds `dependencies` and `stack` to its image updates, and Dependabot adds
    `dependencies` and `ci` to its updates of actions and check tools. Copy the file into your
    repository as `.github/labels.json`, adapt the topic labels (`models`, `gpu`, `rag` and so on)
    to the project, and keep those four. Then create every label in the file, from the root of
    your repository:

        python3 -c 'import json; [print(l["name"], l["color"], l["description"], sep="\t") for l in json.load(open(".github/labels.json"))]' |
          while IFS=$'\t' read -r name color description; do
            gh label create "$name" --color "$color" --description "$description" --force
          done

    `--force` updates a label that already exists, so the command can run again after you change
    the file.

6. Check the labels.

        gh label list --limit 100

    The list contains every label of `.github/labels.json`.

7. List the Discussions categories.

        gh api graphql -f o=<owner> -f r=<repo> -f query='
          query($o: String!, $r: String!) {
            repository(owner: $o, name: $r) {
              discussionCategories(first: 20) { nodes { name } }
            }
          }'

    The output lists the categories, including **Announcements** and **Show and tell**.

#### Results

The repository has a board, labels and Discussions, and `gh` can write to all three.

### Start work on an issue

#### About this task

Every change starts as an issue, gets a branch named after it and a pull request opened early, so
that each commit lands somewhere reviewable under the right title.

In an OpenCode session, `/issue <N>` does steps 3 and 4 for an existing issue, on the coordinator:
it shows the issue and stops if it is closed, switches to an up-to-date `main`, creates the branch
`<type>/<slug>-<N>` with `git switch -c`, plans as `/plan` does, commits the contract with the
message `Contract for #<N>: <title>` when more than one agent will work on the change, opens the
pull request with `/pr`, and starts at most two subagents. `git switch -c` does not link the
branch to the issue on GitHub as `gh issue develop` does; the `Closes #<N>` line of the pull
request links them. `/pr` runs `tools/check.sh`, adds the `CHANGELOG.md` line if it is missing,
pushes the branch by name (OpenCode asks you to approve the push) and opens a ready pull request,
not a draft.

#### Steps

1. Create the issue.

        gh issue create --title "<title>" --label <label> --body "<what and why>"

    The output is the issue URL; its last part is the issue number `<N>`.

2. Add the issue to the board.

        gh project item-add <project-number> --owner <owner> \
          --url https://github.com/<owner>/<repo>/issues/<N>

3. Create the branch from `main`, linked to the issue, and check it out. Name it
   `<type>/<slug>-<N>`, where `<type>` is `feat`, `fix`, `docs` or `chore`, for example
   `fix/smoke-timeout-12`.

        gh issue develop <N> --base main --name <type>/<slug>-<N> --checkout

4. Commit the contract ([Write a feature contract](#write-a-feature-contract)), push, and open
   the pull request as a draft.

        git push -u origin <type>/<slug>-<N>
        gh pr create --draft --base main --title "<title>" --body "Closes #<N>"

#### Results

The issue is on the board, and a draft pull request whose body says `Closes #<N>` tracks the
branch. Merging it closes the issue.

### Finish a pull request

#### Steps

1. Mark the pull request ready for review.

        gh pr ready <PR>

2. Wait for the required checks.

        gh pr checks <PR> --watch --required

    `Lint`, `Compose stack`, `Secrets` and `Guide` all pass.

3. Merge, and delete the branch.

        gh pr merge <PR> --merge --delete-branch

4. Update the local `main`.

        git switch main
        git pull --ff-only

5. Confirm that the issue closed, and leave a one-line comment that names the pull request.

        gh issue view <N> --json state --jq .state
        gh issue comment <N> --body "Fixed by #<PR>."

    The first command prints `CLOSED`.

6. Read the code-scanning alerts ([Review code scanning alerts](#review-code-scanning-alerts)).

#### Results

The change is on `main`, the issue is closed with a pointer to the pull request, and the branch is
gone.

### Using gh from agents

The coordinator runs `git` and `gh` through OpenCode's shell tool. Read-only commands run
without a prompt, and writes ask you first. In `opencode.jsonc` the permission rules are ordered
and the last matching rule wins; each agent's own rules are appended after the global ones. The
installed configuration starts with `{ "action": "shell", "resource": "*", "effect": "ask" }`, so
every shell command asks, and then allows these without a prompt:

Table: Shell commands that run without a prompt

| Rules | Commands |
|---|---|
| Global, in `opencode.jsonc` (the subagent files narrow them) | `git status`, `git diff`, `git log`, `git show`, `git branch --show-current`, `gh issue view`, `gh issue list`, `gh pr view`, `gh pr checks`, `tools/check.sh` |
| The coordinator's own, in `coordinator.md` | `git add`, `git commit`, `git switch`, `git fetch`, `git pull --ff-only`, `gh issue create`, `gh pr create` |

Every other command, such as `git push`, `gh pr merge` or `gh issue comment`, asks first. `sudo`
is denied, and the `policies` of the configuration and the guard plugin refuse a push to `main` or
`master` whatever you answer ([What the guard refuses](#what-the-guard-refuses)). To allow another
read-only command, append a rule after the general one in the same form, for example
`{ "action": "shell", "resource": "gh run list *", "effect": "allow" }`, and keep writes on
`ask`. Then keep the agent's reach small:

- **The account.** OpenCode has no OS sandbox; its shell runs with your user's authority. Run it
  as a dedicated unprivileged user whose `gh` token reaches only the repositories it works on.
- **No agents in CI on a public repository.** GitHub-hosted runners cannot reach the model server
  on your LAN, and a self-hosted runner on a public repository can be compromised by code in a
  pull request from outside. Run agents on c4dev only; let CI run the deterministic checks.
- **Untrusted checkouts.** OpenCode loads `.opencode/plugins/*.ts` from a repository at start-up.
  Read the `.opencode/` directory of a pull request from someone else before you run OpenCode on
  its branch.

### Archive reports in Discussions

#### About this task

GitHub Discussions keeps every report the work produces: each research note, agent hand-back,
review and release. Issues hold decisions and work; Discussions hold the record.

Table: Discussions categories

| Report | Category |
|---|---|
| Research note, agent hand-back, review | Show and tell |
| Release | Announcements |

#### Steps

1. Save the report to a file under `build/`, which Git ignores.

2. Replace private data in it with the placeholders: addresses, domains, keys, names.

3. Post it. The `gh discussion` command is a preview in `gh` 2.103.2.

        gh discussion create --category "Show and tell" \
          --title "<topic>: <report kind> (#<N>)" --body-file build/<report>.md

4. Confirm the post.

        gh discussion list --category "Show and tell" --limit 5

#### Results

The report is archived and can be linked from the issue.

## Checks and continuous integration

### Parallel check runner

`tools/check.sh` runs every check that CI runs, all at the same time across the workstation's
cores, and prints one line per check in a fixed order: `ok <name>`, `FAIL <name>` followed by the
failing command's output, or `skip <name>` with the missing tool and how to install it. Run it
before every commit.

Table: Checks in tools/check.sh

| Check | Tool | Covers |
|---|---|---|
| `yaml` | yamllint | Compose files, configs, workflows |
| `shell` | shellcheck | Shell scripts |
| `python` | `ruff check` (including the `S` security rules), `ruff format --check`, then `unittest`, one process per `tools/tests/test_*.py` module | Tools and their tests |
| `markdown` | pymarkdown | Every Markdown file |
| `workflows` | actionlint and zizmor | `.github/` |
| `compose` | `docker compose config -q` per app, with `stack/<app>/<app>.env.example`; no Docker daemon needed | `stack/` |
| `secrets` | gitleaks | The working tree and the history of every local ref (only `HEAD` in GitHub Actions) |
| `links` | `tools/check_links.py`, offline | Every relative link and heading anchor in Markdown |
| `guide` | `tools/guide/build.py` (needs Chromium, `pdfinfo`, `python3-markdown` and `python3-yaml`) | The guide PDF |

Options:

- `--only <name>...` runs a subset, for example `tools/check.sh --only markdown links`.
- `--strict` makes a check whose tool is missing fail instead of skip. CI uses it, so nothing is
  skipped silently on a runner.
- `JOBS=<n>` caps how many checks run at once and how many processes each starts (the default is
  `nproc`); `JOBS=1` runs everything one at a time, for debugging.

Build project tools in the same way: independent work runs concurrently on every core and is
reported in a fixed order. Keep serial only what talks to the GPU server under load, to GitHub or
to a registry.

### Install the check tools and the pre-push hook

#### About this task

`tools/setup-checks.sh` installs the pinned check tools without `sudo`, in three parallel lanes,
into the repository's own tool directory (`~/.local/share/local-agent-stack/check-tools` unless
`LAS_TOOLS_DIR` says otherwise). Python tools are installed from hash-pinned requirements;
actionlint and gitleaks are verified against pinned SHA-256 sums. The pinned actionlint and
gitleaks downloads are Linux x86_64 builds, so the script works only on Linux on x86_64: run it on
`c4dev`, not on a Mac. It also links each tool into `~/.local/bin` when no command of that name
exists there yet; an existing command is never replaced.

The script also points Git at the repository's hooks (`git config core.hooksPath tools/hooks`).
The `pre-push` hook refuses any push to `main`, including its deletion, and runs
`tools/check.sh --only secrets yaml shell python` before anything leaves c4dev:

{{ include tools/hooks/pre-push }}

#### Steps

1. From the root of the repository, run the setup script.

        tools/setup-checks.sh

2. Confirm that Git uses the repository's hooks.

        git config --get core.hooksPath

    The output is `tools/hooks`.

3. Run every check once.

        tools/check.sh

    Each check reports `ok` or `skip`.

#### Results

The check tools are installed, and every push from this clone runs the hook first. A push to
`main` stops with `pre-push: refusing to push ... main changes only through a pull request`.

!!! warning
    `git push --no-verify` bypasses the hook. Use it only in an emergency, and say so in the pull
    request: the hook is the last check before a secret reaches a public repository.

### Required CI jobs

`.github/workflows/ci.yml` runs `tools/check.sh --strict` in four jobs. Their names are fixed,
because the branch ruleset requires them by name: a renamed job never reports, and every pull
request then waits for it forever.

Table: Required CI jobs

| Job | Typical checks |
|---|---|
| `Lint` | `yaml`, `shell`, `python`, `markdown`, `workflows` |
| `Compose stack` | `compose` |
| `Secrets` | `secrets`, over the full history |
| `Guide` | `guide` and the links of the built guide |

The workflow file is the authority for which job runs which check. Actions in it are pinned by
commit SHA, and CodeQL default setup scans the repository, because it is public.

### Evaluations before a merge

`tools/check.sh` and CI never run a model, because CI has no GPU; the `python` check tests
`tools/eval.py` only against a fake gateway on the loopback address. The evaluations run from the
workstation against your server, one request at a time: `tools/eval.py run` sends the pinned cases
of the `evals/` suites (tool calling on both API formats, instruction following, small coding tasks
and questions over sample documents) and writes a results file, and `tools/eval.py compare` is the
regression gate between a baseline and a new result.

Run them for every pull request that changes what the configuration hash of a results file
covers: `stack/inference/llama-swap/config.yaml`, `stack/inference/litellm/config.yaml`,
`stack/inference/compose.yaml`, `stack/inference/models.sha256`, `evals/sets.toml`, the suites
under `evals/suites/` or the documents under `evals/rag-docs/`. Do not run them while agents
work: an evaluation needs the GPU server to itself
([Concurrency on one 16 GB GPU](#concurrency-on-one-16-gb-gpu)). Chapter 9 describes the suites,
the run, the results files and the gate
([Evaluations and the regression gate](#evaluations-and-the-regression-gate)).

### Protect the main branch with a ruleset

#### Prerequisites

- The repository is public. GitHub Free offers rulesets and protected branches on public
  repositories only; on a private repository, the pre-push hook is the only guard.
- You are an administrator of `<owner>/<repo>`.

#### About this task

A branch ruleset makes the workflow binding on GitHub: `main` changes only through a pull request
whose four required checks passed on a branch that is up to date with `main`, and `main` cannot be
deleted or force-pushed.

#### Steps

1. Write the ruleset to a file under `build/`.

        mkdir -p build
        cat > build/ruleset-main.json <<'EOF'
        {
          "name": "main",
          "target": "branch",
          "enforcement": "active",
          "conditions": { "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] } },
          "rules": [
            { "type": "deletion" },
            { "type": "non_fast_forward" },
            { "type": "pull_request", "parameters": {
                "required_approving_review_count": 0,
                "dismiss_stale_reviews_on_push": false,
                "require_code_owner_review": false,
                "require_last_push_approval": false,
                "required_review_thread_resolution": false } },
            { "type": "required_status_checks", "parameters": {
                "strict_required_status_checks_policy": true,
                "required_status_checks": [
                  { "context": "Lint" }, { "context": "Compose stack" },
                  { "context": "Secrets" }, { "context": "Guide" } ] } }
          ]
        }
        EOF

    `required_approving_review_count` is `0` because a single maintainer cannot approve their
    own pull request. `strict_required_status_checks_policy` requires the branch to be up to
    date with `main`.

2. Create the ruleset.

        gh api -X POST repos/<owner>/<repo>/rulesets --input build/ruleset-main.json

3. Confirm the rules that now apply to `main`.

        gh api repos/<owner>/<repo>/rules/branches/main --jq '.[].type'

    The output lists `deletion`, `non_fast_forward`, `pull_request` and
    `required_status_checks`.

#### Results

GitHub refuses direct pushes to `main` and merges that have not passed `Lint`, `Compose stack`,
`Secrets` and `Guide`.

### Review code scanning alerts

#### About this task

Every push to `main` is scanned again. After each merge, read the open alerts: open an issue and a
pull request for each real finding, and dismiss a false positive with its reason.

#### Steps

1. Once per repository, enable CodeQL default setup and confirm it.

        gh api -X PATCH repos/<owner>/<repo>/code-scanning/default-setup -f state=configured
        gh api repos/<owner>/<repo>/code-scanning/default-setup --jq .state

    The second command prints `configured`.

2. After each merge, list the open code-scanning alerts.

        gh api "repos/<owner>/<repo>/code-scanning/alerts?state=open" \
          --jq '.[] | [.number, .rule.id, .most_recent_instance.location.path] | @tsv'

    No output means no open alerts.

3. List the open secret-scanning alerts.

        gh api "repos/<owner>/<repo>/secret-scanning/alerts?state=open" --jq length

    The output is `0`.

4. For a false positive, dismiss the alert with a reason (`false positive`, `won't fix` or
   `used in tests`) and a comment, and say so in the issue or pull request that decided it.

        gh api -X PATCH repos/<owner>/<repo>/code-scanning/alerts/<alert> \
          -f state=dismissed -f dismissed_reason="false positive" \
          -f dismissed_comment="<why>"

#### Results

`main` has no unexplained open alerts.

## Releases and the changelog

### Changelog entries

`CHANGELOG.md` is the list of every release. Its `## Unreleased` section collects what the next
release changes. Every pull request that changes the stack or the guide adds one line there,
written for the person who installs the stack, with the issue number:

```
## Unreleased

- The smoke test can check the fast profile and leaves the default model loaded (#42).
```

The release workflow, `.github/workflows/release.yml`, uses this section as follows:

- **The notes are the section.** The notes of the GitHub release are the text under
  `## Unreleased`, under the title `Local Agent Stack <version>` (for example
  `Local Agent Stack 1.1`), followed by one sentence about the attached files and their
  attestations.
- **An empty section fails the release.** When `## Unreleased` holds no list item (a line that
  starts with a hyphen or an asterisk and a space), the workflow stops with
  `CHANGELOG.md: the '## Unreleased' entry is empty; a release needs its changes listed there`,
  and no release is created.
- **A pull request closes the section afterwards.** The workflow does not change `CHANGELOG.md`.
  After a release, a pull request moves the lines from `## Unreleased` under a new heading for the
  release, `## v1.1` in the example below, and leaves `## Unreleased` empty for the next release
  ([Cut a release](#cut-a-release), step 7).

### Cut a release

#### Prerequisites

- Every pull request for the release is merged, and the checks on `main` passed.
- `## Unreleased` lists every change, as list items ([Changelog entries](#changelog-entries)).
- `version` in `guide/guide.yaml` is the release's number without the `v`, for example `"1.1"`.
  The workflow refuses a tag whose number differs, so that the guide's cover always names its
  release.

#### About this task

A release is a tag `vX.Y` on a commit of `main`; a prerelease is a tag `vX.Y-beta.N`. Pushing the
tag starts `.github/workflows/release.yml`. Its first job checks the tag's form and that the commit
is on `main`, checks `guide/guide.yaml`, runs `tools/check.sh --strict`, and builds the guide PDF,
`stack-vX.Y.tar.gz` (a `git archive` of `stack/`, `clients/` and `deploy/` at the tag),
`SHA256SUMS.txt` and the notes. Its second job checks the files against `SHA256SUMS.txt`, signs a
build provenance attestation for the PDF and the bundle, and creates the GitHub release with the
files attached; running the workflow again for the same tag updates that release. The example uses
`v1.1`.

#### Steps

1. Update `main` and read the section that becomes the release notes.

        git switch main
        git pull --ff-only
        sed -n '/^## Unreleased/,/^## [^U]/p' CHANGELOG.md
        grep -E '^version:' guide/guide.yaml

    The first command prints the list of changes under `## Unreleased`; the last prints
    `version: "1.1"`.

2. Tag `main` and push the tag.

        git tag -a v1.1 -m "v1.1"
        git push origin v1.1

3. Find the release run and watch it.

        gh run list --workflow release.yml --limit 1
        gh run watch <run-id> --exit-status

    The run ends successfully.

4. List the release assets.

        gh release view v1.1 --json assets --jq '.assets[].name'

    The list contains the guide PDF (`local-agent-stack-<version>-deployment-guide.pdf`),
    `stack-v1.1.tar.gz` and `SHA256SUMS.txt`.

5. Download the assets and verify the checksums and the provenance.

        mkdir -p build/release/v1.1
        gh release download v1.1 --dir build/release/v1.1
        cd build/release/v1.1 && sha256sum -c SHA256SUMS.txt
        gh attestation verify stack-v1.1.tar.gz --repo <owner>/<repo>

    Every line of `sha256sum` ends with `OK`, and `gh attestation verify` reports a successful
    verification. Return to the root of the repository with `cd -`.

6. Archive the release in Discussions.

        gh release view v1.1 --json body --jq .body > build/notes-v1.1.md
        gh discussion create --category Announcements --title "Release v1.1" --body-file build/notes-v1.1.md

7. Close the changelog section in a pull request: create a branch from `main`, move the lines
   under `## Unreleased` in `CHANGELOG.md` under a new heading `## v1.1` placed right below it,
   and leave `## Unreleased` empty.

        git switch -c docs/changelog-v1.1-<N>
        git add CHANGELOG.md
        git commit -m "Changelog: v1.1 (#<N>)"
        git push -u origin docs/changelog-v1.1-<N>
        gh pr create --base main --title "Changelog: v1.1" --body "Closes #<N>"

    `<N>` is the issue of the release. Merge the pull request as in
    [Finish a pull request](#finish-a-pull-request). The next release then starts from an empty
    `## Unreleased`, which pull requests fill again.

#### Results

The release `v1.1` carries the guide PDF, the stack bundle and their checksums, with signed
provenance; its notes are archived under **Announcements**, and `CHANGELOG.md` on `main` lists the
release under its own heading.

#### Next steps

Install the release on the server as described in Chapter 10
([Updating to a new release](#updating-to-a-new-release)).

## Example: a feature from issue to release

This example takes one feature through the whole workflow in this repository: a smoke test for the
fast profile. The issue number 42, the pull request number 43 and the `--profile` option are
illustrative; `tools/smoke.py` does not have that option.

### Example: open the issue and write the contract

#### Steps

1. Create the issue and add it to the board. Use a label that exists in `.github/labels.json`.

        gh issue create --title "Smoke test for the fast profile" --label enhancement \
          --body "tools/smoke.py should check local-coder-moe on request and leave local-coder loaded."
        gh project item-add <project-number> --owner <owner> \
          --url https://github.com/<owner>/local-agent-stack/issues/42

2. Create the branch.

        gh issue develop 42 --base main --name feat/fast-profile-smoke-42 --checkout

3. Start `opencode`, which opens with the **coordinator** agent, and ask for the contract.

        Read issue #42 and docs/stack-design.md sections 5 and 8. Write the contract
        docs/fast-profile-smoke-design.md: Goal, Files and owners, Interfaces (the new
        option, its output, its exit codes), Lifecycle cases (the GPU model before and
        after the check), Verification, Open questions. Create no other file.

4. Review the contract. In this example you decide that the test must request `local-coder`
   again at the end, so that the default model is loaded when the test exits, and tell the
   coordinator to add that to **Interfaces**.

5. Commit the contract, push and open the draft pull request.

        git add docs/fast-profile-smoke-design.md
        git commit -m "Contract: fast-profile smoke test (#42)"
        git push -u origin feat/fast-profile-smoke-42
        gh pr create --draft --base main --title "Smoke test for the fast profile" \
          --body "Closes #42"

    The output is the pull request URL, ending in `/pull/43`.

#### Results

Issue 42 is on the board, the branch `feat/fast-profile-smoke-42` carries the reviewed contract as
its first commit, and draft pull request 43 tracks it.

### Example: research and the parallel build

#### Steps

1. The contract leaves one fact open: how the test can tell which model llama-swap has loaded.
   Ask the coordinator for a research note.

        Launch the researcher. Question: how does llama-swap v273 report which model is
        loaded, and which endpoint or field shows it? Follow docs/research-contract.md.
        Write only docs/research/g-llama-swap-loaded-model.md. Cite the llama-swap README
        and docs/config.example.yaml with URLs. Edit nothing else.

2. Read the note, then have the coordinator cite it in the contract and commit both.

3. Ask for the split.

        Split docs/fast-profile-smoke-design.md into two builder briefs. Builder A owns
        tools/smoke.py and tools/tests/test_smoke.py. Builder B owns
        guide/chapters/09-validation.md.
        You own CHANGELOG.md. Show me the split, then wait.

4. Check that the lists do not overlap, then launch.

        Launch both builders now, with self-contained briefs in the brief format from
        AGENTS.md. Builder A verifies with tools/check.sh --only python; builder B with
        tools/check.sh --only markdown links guide.

    Two builders run at once. The researcher finished before they started, so no more than two
    agents share the GPU.

5. When both reports are in, list the changed files.

        git status --porcelain

    The output names `tools/smoke.py`, `tools/tests/test_smoke.py`,
    `guide/chapters/09-validation.md` and nothing else.

6. Ask the coordinator to add the changelog line, then run every check, commit and push.

        tools/check.sh
        git add CHANGELOG.md tools/smoke.py tools/tests/test_smoke.py guide/chapters/09-validation.md
        git commit -m "Smoke test: check the fast profile (#42)"
        git push

#### Results

Pull request 43 holds the contract, the research note and one integrated commit with the code, its
tests, the guide change and the changelog line, and `tools/check.sh` passed on it. The CI checks of
the pull request start with the push.

### Example: review, merge and release

#### Steps

1. Save the diff for the reviewer.

        git diff main...HEAD > build/review-42.diff

2. Ask for a review.

        Launch the reviewer. Read docs/fast-profile-smoke-design.md and
        build/review-42.diff. Report every place where the diff departs from the contract,
        with file and line. Edit nothing.

3. Have the coordinator hand each finding to the builder that owns the file, then repeat the checks
   and the commit.

4. Ask the coordinator to collect the research note's summary, the builders' reports and the
   review into `build/reports-42.md`, with private data replaced by placeholders. Archive it.

        gh discussion create --category "Show and tell" \
          --title "Fast-profile smoke test: agent reports (#42)" --body-file build/reports-42.md

5. Finish the pull request.

        gh pr ready 43
        gh pr checks 43 --watch --required
        gh pr merge 43 --merge --delete-branch
        git switch main
        git pull --ff-only
        gh issue comment 42 --body "Fixed by #43; ships in the next release."

6. Read the open code-scanning alerts on `main`
   ([Review code scanning alerts](#review-code-scanning-alerts)).

7. When the release is due, cut it ([Cut a release](#cut-a-release)). The changelog line from
   step 6 of the previous task appears in its notes, and step 7 of that release task moves it
   under the release's own heading.

#### Results

Issue 42 is closed with a comment that names pull request 43. `main` holds the contract, the
research note, the code, its tests and the guide change, each reviewable in the pull request. The
reports are archived in Discussions, and the next release lists the change.
