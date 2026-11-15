# Local Agent Stack

A self-hosted, local-model equivalent of Claude Code for one home lab: open-weight models served
from containers on a TrueNAS SCALE server with one NVIDIA RTX 4080 (16 GB), a terminal coding
agent on the workstations, a web GUI, retrieval over the owner's documents (RAG), web search,
and tools that reach remote hosts over SSH. The deliverable is a vendor-style **deployment guide**
(`guide/` → `build/guide/*.pdf`) plus the files it installs (`stack/`). **Public on GitHub under
the Apache License 2.0 since 2026-11-15** (`LICENSE`, `NOTICE`).

## How I want you to work

- **Plan first, then build.** For any new feature or fix, explore, then state the approach and
  the files you'll touch. **Standing approval: I approve everything, every time** — plans,
  installs, merges, deletes. Don't stop to ask me to confirm; do it and report. Ask only when a
  real design choice needs my answer or something needs my hands (the TrueNAS web UI, a
  reboot, a physical check of the GPU).
- **Contracts before code.** Anything several agents build together gets its contract under
  `docs/` first (an interface, a file layout, a port map, the guide's style). Research and
  design notes cite primary sources and separate verified from assumed
  (`docs/research-contract.md` is the template).
- **Verified facts only.** Image names, tags, flags, environment variables, API fields and UI
  labels come from primary sources (official docs, release notes, model cards, `--help`).
  Never invent one. When uncertain, say what you verified and what you're assuming.
- **The guide and the stack agree.** The guide quotes files in `stack/`; when they disagree,
  `stack/` wins and the guide is the bug. Every procedure in the guide ends with a verification
  step the reader can run.
- **Everything runs through GitHub.** Issue first (`gh issue create`, labels from
  `.github/labels.json`, added to the project board), branch from `main` with the issue number
  in its name, PR early with "Closes #N", merge when the required checks pass, close the issue
  with a one-line comment naming the PR. Never push to `main`. Decisions for me go into an issue
  labelled `question`.
- **A changelog for every release.** `CHANGELOG.md` `## Unreleased` gets a line per PR that
  changes the stack or the guide. Releases are tags `vX.Y` with the guide PDF attached.
- Commit in small, working steps with clear messages.
- **The repository is public.** Never commit secrets or private data: API keys, SSH keys, DNS
  provider tokens, LAN addresses, the owner's domain, names. Placeholders only: `192.0.2.10`
  TrueNAS, `192.0.2.20` workstation, domain `lab.example.com`, pool `tank`, keys `sk-local-...`.
  The workstation's name `c4dev` is fine. `.env` files are gitignored; `stack/*.env.example`
  documents them. Never copy passages of login-walled or restrictively licensed docs.
- **Code scanning after every merge:** read the open code-scanning and secret-scanning alerts
  (`gh api "repos/corytron/local-agent-stack/code-scanning/alerts?state=open"`); an issue and a
  PR per real finding, dismiss false positives with a reason.
- **GitHub Discussions is the archive of every report:** each research note, agent hand-back,
  review and release is posted there as it arrives, with private data replaced by placeholders.

## Working with agents

**Parallel by default.** Split every piece of work into parts that touch disjoint files and run
them as background agents at once. Serial only when the work cannot be split. Before starting,
say in one line how it is split and which agent owns which files.

- **Coordinator first.** Write the shared contract into `docs/`, then spawn every agent in one go.
- **One writer per file.** Each brief names the exact files the agent may create or edit and says
  others are editing the rest of the checkout. No agent runs `git`; the coordinator integrates,
  runs `tools/check.sh` and the build, and commits.
- **Briefs are self-contained:** doc paths to read, conventions, hardware facts, what done looks
  like and the verification commands.
- **Research agents are read-only** and write one file under `docs/research/`.
- Typical split: research notes / `stack/` compose and configs / tools and CI / guide chapters
  (one agent per group of chapters). Integration into `guide/guide.yaml`, `tools/check.sh`,
  CI workflows and this file stays with the coordinator.

## Hardware and environment

- **Server:** TrueNAS SCALE (Docker-based apps), NVIDIA RTX 4080 16 GB (Ada, sm_89). One GPU,
  shared by every model; VRAM is the budget that decides everything.
- **Workstation:** this Ubuntu VM (c4dev, 32 cores), where the coding agent and this repo live.
  The owner drives sessions from a Mac (Claude Desktop over SSH) and has a Windows VM.
- **Local only for the core path:** models, RAG and tools run on the LAN. Web search goes out
  through self-hosted SearXNG. No cloud fallback for inference.

## Repository layout

```
stack/          docker compose files and configs installed on TrueNAS (one dir per app)
guide/          guide.yaml, chapters/*.md, figures/, template/ (CSS)
docs/           contracts, research/, design notes, status.md
tools/          check.sh, guide/build.py, evals and benchmarks, deploy helpers
build/          generated output (gitignored)
```

## Commands

- Checks: `tools/check.sh` before every commit (the same checks CI runs; runs them in parallel,
  reports in a fixed order; `JOBS=N` caps processes).
- Guide: `python3 tools/guide/build.py` → `build/guide/local-agent-stack-<ver>-deployment-guide.pdf`
  (Markdown chapters rendered in parallel, printed twice by headless Chromium so the contents
  carries page numbers). Authoring rules: `docs/guide-style.md`.
- **Use all cores:** every tool runs independent work concurrently across `nproc`; new tools are
  designed parallel from the start. Left serial on purpose: anything that talks to the GPU server
  under load (benchmarks, evals run one model at a time).

## Current state

`docs/status.md` is the summary and points at the issues.
