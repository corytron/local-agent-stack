# Research contract (phase 1)

Every research agent builds against this text. The coordinator owns this file.

## Goal of the project

Approximate, as closely as possible, every feature of Claude Code (agentic coding in a terminal,
sub-agents, hooks, slash commands, skills, MCP tools, CLAUDE.md-style project memory, plan mode,
permission modes, web search and fetch, reading documents, working on remote hosts over SSH,
GitHub integration) using **open-weight models running locally** on the owner's TrueNAS SCALE
server, as containers, on one NVIDIA GPU. Add what Claude Code does not have natively but the
owner wants: a web GUI, retrieval-augmented generation (RAG) over the owner's own documents.

The deliverable of the project is a **deployment guide** (PDF, vendor style) the owner follows
by hand, plus the files it installs (compose files, configs, scripts) kept in this repository.

## Hardware and environment facts

- GPU: NVIDIA GeForce RTX 4080 (ASUS ProArt edition), **16 GB GDDR6X**, Ada Lovelace, compute
  capability 8.9. One GPU only. Assume it may be a 4080 or 4080 SUPER: same 16 GB.
- Host (owner, 2026-11-15, #7): TrueNAS SCALE **25.10.8 "Goldeye"**, **62.3 GiB usable RAM**
  (64 GB ECC, shared with ZFS ARC), CPU **Intel Xeon w5-3435X** (Sapphire Rapids, 16 cores /
  32 threads, AVX-512 and AMX). Memory is **two 32 GB DIMMs: 2 of 8 channels populated**
  (~77 GB/s theoretical), so CPU offload is bandwidth-bound. Size for this box; keep other
  RAM tiers as a short table.
- Clients: an Ubuntu VM ("c4dev", 32 cores) where the owner runs coding work, a Mac (Claude
  Desktop app over SSH today), a Windows VM. All on one home LAN.
- Local only where possible: the owner's rule is **no reliance on cloud services** for the core
  path. Web search is allowed to reach the internet but should go through a self-hosted
  metasearch (for example SearXNG) rather than a paid API, with a paid API only as an option.
- Today's date: 2026-11-15. Prefer sources from 2026. Say when a fact's newest source is older.

## Rules for every research agent

1. **Read-only** on the repository except the one file your brief names under `docs/research/`.
   Other agents are writing other files in this checkout at the same time. Do not run `git`.
2. Use web search and page fetches extensively. Cite every non-obvious claim with a URL and the
   date you read it. Separate **Verified** (read in a primary source: official docs, release
   notes, model cards, source code) from **Assumed** (inferred, forum reports, your memory).
3. Never invent version numbers, flags, image names, environment variables or API fields. If you
   cannot verify one, mark it `UNVERIFIED` in the text.
4. Container images: give the exact image name, a current tag, the registry, and whether it
   publishes CUDA builds for amd64.
5. Do not put private data in the file: no LAN addresses (use `192.0.2.10` for the TrueNAS
   server, `192.0.2.20` for c4dev), no names, no keys.

## Output format (every `docs/research/*.md`)

```
# <Topic>

Status: research, <date>. Author: research agent <letter>.

## Summary
Five to ten bullets: the answer and the recommendation.

## Recommendation
What the guide should install and configure, with the reasoning.

## Options compared
A table: option, what it is, fit for this hardware, maturity, licence, verdict.

## Details
The facts the guide writer needs: install steps, configs, ports, volumes, env vars,
sizing numbers, known problems and their fixes.

## Fit with Claude Code features
For each feature in this topic: how closely the recommended option matches it, and what is lost.

## Verified vs assumed
Two lists.

## Open questions for the owner
Only real decisions that need the owner.

## Sources
Numbered URLs with the date read.
```

## Research topics and file owners

| Agent | File | Topic |
|---|---|---|
| A | `docs/research/a-models.md` | Open-weight models for agentic coding and tool calling on 16 GB VRAM |
| B | `docs/research/b-inference.md` | Inference servers and model routing on one NVIDIA GPU in containers |
| C | `docs/research/c-agents.md` | Claude-Code-like agent harnesses (CLI and IDE) that run on local models |
| D | `docs/research/d-gui-rag-search.md` | Web GUI, RAG pipeline, web search, MCP tool servers incl. SSH |
| E | `docs/research/e-truenas.md` | TrueNAS SCALE apps, NVIDIA GPU passthrough to containers, storage, network, TLS, backup |
| F | `docs/research/f-project-tooling.md` | Spec-driven repo workflow, CI for a container stack, evals and benchmarks, guide build pipeline |
