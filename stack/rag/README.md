# ai-rag: pgvector, docling and oikb

The retrieval layer behind Open WebUI, installed on TrueNAS as the custom app `ai-rag`
([`compose.yaml`](compose.yaml); contract: [`docs/stack-design.md`](../../docs/stack-design.md) §2,
§4, §6; research: [`docs/research/d-gui-rag-search.md`](../../docs/research/d-gui-rag-search.md)).

| Service | Image (tag, pinned by digest) | On `ai-net` | State |
|---|---|---|---|
| `pgvector` | `pgvector/pgvector:0.8.7-pg17` | `pgvector:5432` | `appdata/pgvector` |
| `docling` | `ghcr.io/docling-project/docling-serve-cpu:v1.38.2` | `docling:5001` | none |
| `oikb` | `ghcr.io/open-webui/oikb:0.6.0` | `oikb:8080` (health, metrics) | `appdata/oikb` (history) |

No port is published, no service uses the GPU, and all three set `NVIDIA_VISIBLE_DEVICES=void`
(none of the images is CUDA-based; the setting guards against TrueNAS's default nvidia runtime).
Logs rotate at 10 MB, five files per container.

## Install order and first start

1. Datasets (pool `tank`, [`docs/stack-design.md`](../../docs/stack-design.md) §4):
   `tank/ai/appdata/pgvector` (record size 32K suits PostgreSQL), `tank/ai/appdata/oikb`, and
   `tank/ai/rag-docs` with the SMB share. Give the `apps` group (GID 568) **Read** on
   `rag-docs` and **Modify** on `appdata/oikb`: oikb runs as `568:568`.
2. `rag.env` from [`rag.env.example`](rag.env.example) into `/mnt/tank/ai/secrets/` (mode 0600).
   `PG_PASSWORD` and `DOCLING_API_KEY` are copied into `web.env` too. Leave `OIKB_TOKEN` and
   `OIKB_KB_ID` at their placeholders for now.
3. Install `ai-rag` (before `ai-web`: Open WebUI cannot start without `pgvector`).
4. After Open WebUI's first start ([First start of Open WebUI](../web/README.md#first-start-of-open-webui)): create the
   `indexer` user and its API key and the knowledge base, put `OIKB_TOKEN` and `OIKB_KB_ID`
   into `rag.env`, and redeploy `ai-rag` (`midclt call -j app.redeploy ai-rag`). The redeploy
   restarts `pgvector` too; Open WebUI reconnects by itself.

Until step 4, oikb runs, answers its health check, and logs one failed sync every 15 minutes.

## Verify

From **System > Shell** on TrueNAS (all names resolve on `ai-net`; `sudo` where needed):

```sh
docker ps --filter name=pgvector --filter name=docling --filter name=oikb \
  --format '{{.Names}} {{.Status}}'                    # all three "(healthy)"
docker exec pgvector psql -U openwebui -d openwebui -c "SELECT extversion FROM pg_extension WHERE extname = 'vector';"
docker exec open-webui curl -s -o /dev/null -w '%{http_code}\n' http://docling:5001/health   # 200
docker exec oikb python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/health').read().decode())"
```

The `vector` extension row appears once Open WebUI has started (it runs `CREATE EXTENSION`).
oikb's `/health` lists each source with its last sync, file counts and error.

## Settings worth knowing

- **PostgreSQL password.** `POSTGRES_PASSWORD` is used only when the data directory is empty. To
  change it later: `docker exec -it pgvector psql -U openwebui -d openwebui -c "ALTER ROLE openwebui PASSWORD '<new>'"`,
  then update `PG_PASSWORD` in both `rag.env` and `web.env` and redeploy both apps.
- **`PGDATA`** is `/var/lib/postgresql/data/pgdata`, a directory the entrypoint creates (mode
  0700, owner `postgres`) inside the mounted dataset, as TrueNAS's own app library does for its
  PostgreSQL containers (one level below the volume).
- **docling** waits up to 600 s for a synchronous conversion (`DOCLING_SERVE_MAX_SYNC_WAIT`;
  default 120) with two workers and an 8 GB memory limit (64 GB host). On a 32 GB host use 4g
  and one worker. Every request needs the `X-Api-Key` header; the API reference pages are off.
- **oikb** ([`oikb/oikb.yaml`](oikb/oikb.yaml)) syncs `/data/docs` (the dataset, read-only) every
  15 minutes, skips files over 100 MB and the usual junk (`.git`, `.zfs`, `.recycle`, `@eaDir`,
  Office lock files, `._*`, `.DS_Store`). Unchanged files cost nothing: only added or changed
  files are uploaded, parsed by docling and embedded. A sync on demand:
  `docker exec oikb python -c "import urllib.request as u; u.urlopen(u.Request('http://127.0.0.1:8080/sync/rag-docs', method='POST', headers={'Authorization': 'Bearer <OIKB_API_KEY>'}))"`.
  Files Open WebUI rejects (size, extension) fail on every run: exclude them in the filter.

## Unverified

Marked `# UNVERIFIED:` or listed here; check on the first TrueNAS install:

- oikb 0.6.0 running as `568:568` (an arbitrary UID without a passwd entry). The image's own
  user (1000) could not read `rag-docs` with the ACL above.
- PostgreSQL's `initdb` on a dataset with the **Apps** preset (NFSv4 ACL): the entrypoint
  `chmod`s `PGDATA` to 0700, which an ACL mode of `restricted` could refuse. If `pgvector`
  fails with a permissions error, create `tank/ai/appdata/pgvector` with the **Generic** preset.
- `security_opt: no-new-privileges` with the PostgreSQL entrypoint (it switches to the
  `postgres` user with `gosu`, which needs no setuid bit) and with docling and oikb.
- None of these three containers was started for this release (the owner's rule: nothing of
  the stack runs on c4dev); the images, tags, digests, environment variables, endpoints and
  user IDs were read from the images' metadata and the projects' source at the pinned tags.
