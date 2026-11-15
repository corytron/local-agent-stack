# Changelog

## Unreleased

- `tools/port-inventory.sh`: a read-only check, run on TrueNAS, that ports 80/tcp, 443/tcp and 443/udp are free for Caddy; the guide keeps the TrueNAS web interface on its own ports (444 in the examples) (#31).

## v1.1 (2026-11-15)

- MCP hub: the knowledge-base server's zod is lifted to 4.6.7, fixing a memory-exhaustion advisory (high) in zod 3.x (#25).
- The MCP hub image is pinned to its rebuilt digest; the guide is revision A01 (#25).

## v1.0 (2026-11-15)

- Public under the Apache License 2.0.
- The Caddy and MCP hub images this project builds are pinned by digest (#5).
- `deploy.py`: `content_hashes = false` / `--no-hashes` for a TrueNAS that refuses the hash block; the guide keeps API keys out of every process argument list (#5).
- `deploy.py`: options before or after the command, change detection for config and env files, per-app overrides; `secrets.py gen client`; wrapper YAML files per app (#4).
- `tools/eval.py` and `evals/`: tool-calling, format, coding and document suites with a regression gate tied to a configuration checksum (#5).
- Project scaffold: research contract, guide renderer (vendor-style A4 PDF), guide style contract.
