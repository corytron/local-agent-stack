# Quillmate 3.2.0 release notes

Quillmate is a fictional note-taking server. This document is sample data for the retrieval suite
of the local-agent-stack evaluations; the product does not exist.

Quillmate 3.2.0 was released on 4 March 2026.

## Changes

- The default port changed from 7310 to 7420.
- The `--legacy-sync` flag was removed; use `--sync-mode=classic` instead.
- Quillmate now requires Python 3.11 or later.
- Exports to PDF are about 40% faster.

## Known issues

- On ARM boards, the first start can take up to 90 seconds while the search index is built.
