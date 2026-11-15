# Changelog

## Unreleased

## v1.0 (2026-11-15)

- Public under the Apache License 2.0.
- The Caddy and MCP hub images this project builds are pinned by digest (#5).
- `deploy.py`: `content_hashes = false` / `--no-hashes` for a TrueNAS that refuses the hash block; the guide keeps API keys out of every process argument list (#5).
- `deploy.py`: options before or after the command, change detection for config and env files, per-app overrides; `secrets.py gen client`; wrapper YAML files per app (#4).
- `tools/eval.py` and `evals/`: tool-calling, format, coding and document suites with a regression gate tied to a configuration checksum (#5).
- Project scaffold: research contract, guide renderer (vendor-style A4 PDF), guide style contract.
