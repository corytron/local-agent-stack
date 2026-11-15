title: Deploying the RAG and web apps

# Deploying the RAG and web apps

This chapter installs the two apps that sit between the models and the people who use them. The
`ai-rag` app holds Open WebUI's database and vector index (`pgvector`), converts documents to text
(`docling`) and keeps a knowledge base in step with the `rag-docs` share (`oikb`). The `ai-web` app
runs the web interface (`open-webui`), the self-hosted metasearch engine (`searxng`) and the MCP
hub (`mcp-hub`), which serves search, page fetch and knowledge-base tools to the coding agent.
Neither app publishes a port or uses the GPU. Browsers and the workstation reach them through the
edge app from Chapter 5.

Open WebUI copies most of its settings from its environment into its database the first time it
starts, and from then on ignores the environment for those settings. Complete `web.env` before you
install `ai-web`, and make later changes to those settings in the Open WebUI **Admin Panel**.
Perform the tasks in the order shown. Run TrueNAS commands in **System** > **Shell**, or in an SSH
session from the workstation as `truenas_admin`; commands that start with `sudo` prompt for the
`truenas_admin` password.

Table: Values used in this chapter

| Value | Meaning |
|---|---|
| `192.0.2.10` | LAN address of the TrueNAS server |
| `lab.example.com` | Your domain (`LAB_DOMAIN`). Open WebUI is at `https://chat.lab.example.com` |
| `<litellm-webui-key>` | The LiteLLM virtual key of Open WebUI (`LITELLM_WEBUI_KEY`) |
| `<kb-id>` | The ID of the `rag-docs` knowledge base in Open WebUI (`OIKB_KB_ID`) |
| `<indexer-key>`, `<kb-reader-key>` | The Open WebUI API keys of the two service users (`OIKB_TOKEN`, `KB_READER_TOKEN`) |
| `<smb-user>` | The SMB user of the `rag-docs` share (Chapter 3) |

Table: Order of the tasks in this chapter

| Step | Task | Requires |
|---|---|---|
| 1 | Create the LiteLLM key of Open WebUI and complete `web.env` | `ai-inference` running (Chapter 4); `edge.env` complete (Chapter 5) |
| 2 | Install `ai-rag` | The datasets, the share and `rag.env` from Chapter 3 |
| 3 | Build or pull the MCP hub image, then install `ai-web` | `ai-rag` and `ai-inference` running |
| 4 | Create the administrator account and check the settings | `ai-edge` running with a certificate (Chapter 5) |
| 5 | Create the service users, the knowledge base and their keys; redeploy both apps | Steps 2 to 4 |
| 6 | Add documents; verify web search and the MCP hub | Step 5 |

Table: Services of the RAG and web apps

| Container | App | Image (pinned by tag and digest) | Address on ai-net |
|---|---|---|---|
| `pgvector` | `ai-rag` | `pgvector/pgvector:0.8.7-pg17` | `pgvector:5432` |
| `docling` | `ai-rag` | `ghcr.io/docling-project/docling-serve-cpu:v1.38.2` | `docling:5001` |
| `oikb` | `ai-rag` | `ghcr.io/open-webui/oikb:0.6.0` | `oikb:8080` (health, sync and metrics routes) |
| `open-webui` | `ai-web` | `ghcr.io/open-webui/open-webui:v0.13.3-slim` | `open-webui:8080` |
| `searxng` | `ai-web` | `docker.io/searxng/searxng:2026.11.15-2d500cb6b` | `searxng:8080` |
| `mcp-hub` | `ai-web` | `ghcr.io/corytron/local-agent-stack-mcp-hub:0.15.0`, built from `stack/web/mcp-hub` | `mcp-hub:8096` |

Every container sets `NVIDIA_VISIBLE_DEVICES=void`, because TrueNAS makes `nvidia` the default
Docker runtime and none of these images needs the GPU. Every container runs with
`no-new-privileges`, and Docker rotates each container's log at 10 MB, keeping five files.

!!! note
    None of these six containers was started on a TrueNAS server while this release was prepared.
    Their images, tags, environment variables, endpoints and user IDs were read from the images and
    from the projects' source code at the pinned versions, and the MCP hub and SearXNG were tested
    together on another Docker host. The notes in this chapter say what to check at each point
    where the first installation on TrueNAS can differ.

## Open WebUI first-start settings

Open WebUI reads its settings from `web.env` through the compose file of the `ai-web` app. This
topic explains which settings Open WebUI keeps from its first start, creates the LiteLLM key that
`web.env` needs, and completes the file before the first installation.

### Settings that Open WebUI keeps from its first start

Open WebUI 0.13.3 runs with `ENABLE_PERSISTENT_CONFIG=true`, its default. On the first start it
seeds most settings from its environment into its database. From then on the database wins: the
**Admin Panel** is where these settings change, and editing the variables in `web.env` or in the
compose file has no effect on them. This behaviour was checked in the Open WebUI source at
`v0.13.3`. A small group of variables is read from the environment at every start.

Table: Open WebUI variables by when they are read

| When read | Variables | Where to change them later |
|---|---|---|
| At every start (the environment wins) | `WEBUI_SECRET_KEY`, `DATABASE_URL`, `VECTOR_DB`, `PGVECTOR_INDEX_METHOD`, `ENABLE_PERSISTENT_CONFIG`, `CORS_ALLOW_ORIGIN`, `WEBUI_SESSION_COOKIE_SECURE`, `OFFLINE_MODE`, `ENABLE_VERSION_UPDATE_CHECK`, `SCARF_NO_ANALYTICS`, `DO_NOT_TRACK`, `ANONYMIZED_TELEMETRY`, `ENABLE_LOCAL_WEB_FETCH` | `web.env` for the values it holds, then a redeploy of `ai-web`; the others change only with a release |
| First start: access | `WEBUI_URL`, `ENABLE_SIGNUP`, `DEFAULT_USER_ROLE`, `ENABLE_COMMUNITY_SHARING`, `ENABLE_API_KEYS` | **Admin Panel** |
| First start: models | `ENABLE_OLLAMA_API`, `ENABLE_OPENAI_API`, `OPENAI_API_BASE_URLS`, `OPENAI_API_KEYS`, `DEFAULT_MODELS`, `TASK_MODEL_EXTERNAL` | **Admin Panel** > **Settings** > **Connections** and the other model settings of the **Admin Panel** |
| First start: retrieval | Every `RAG_*` and `CHUNK_*` variable, `ENABLE_RAG_HYBRID_SEARCH`, `ENABLE_MARKDOWN_HEADER_TEXT_SPLITTER` | **Admin Panel** > **Settings** > **Documents** |
| First start: extraction | `CONTENT_EXTRACTION_ENGINE`, `DOCLING_SERVER_URL`, `DOCLING_API_KEY` | **Admin Panel** > **Settings** > **Documents** |
| First start: web search | `ENABLE_WEB_SEARCH`, `WEB_SEARCH_ENGINE`, `SEARXNG_QUERY_URL`, `WEB_SEARCH_RESULT_COUNT` | **Admin Panel** > **Settings** > **Web Search** |

The environment of the `open-webui` service in `stack/web/compose.yaml` holds both groups. The
first block is read at every start; the second block seeds the database once:

{{ include stack/web/compose.yaml lines=41-122 }}

Some of these values come from `web.env`. The following table shows what each variable of the file
feeds and what it must hold before the first start of `ai-web`.

Table: Variables in web.env

| Variable | Read by | Value before the first start |
|---|---|---|
| `LAB_DOMAIN` | `open-webui`: the allowed browser origin at every start, and `WEBUI_URL` once; `searxng`: its base URL at every start | Your domain, identical to `LAB_DOMAIN` in `edge.env` |
| `WEBUI_SECRET_KEY` | `open-webui`, at every start | Generated in Chapter 3. Never change it |
| `PG_PASSWORD` | `open-webui` (`DATABASE_URL`), at every start | The same value as in `rag.env` |
| `DOCLING_API_KEY` | `open-webui`, seeded once | The same value as in `rag.env` |
| `LITELLM_WEBUI_KEY` | `open-webui`, seeded once into three settings: the model connection, the embedding key and the reranker key | The virtual key from [Create the virtual key that Open WebUI uses](#create-the-virtual-key-that-open-webui-uses) |
| `SEARXNG_SECRET` | `searxng`, at every start | Generated in Chapter 3 |
| `MCP_HUB_TOKEN` | `mcp-hub`, at every start; the workstations hold a copy (Chapter 7) | Generated in Chapter 3. Allowed characters: `A-Z a-z 0-9 - . _ ~ + /` |
| `KB_READER_TOKEN` | `mcp-hub`, at every start | Empty. It is set later in this chapter |
| `SEARXNG_CONTACT_URL` | `searxng`, at every start | A `mailto:` address or a web page of yours, or empty |

!!! warning
    A placeholder that is still in `web.env` at the first start of `ai-web` stays in Open WebUI's
    database. `LITELLM_WEBUI_KEY=sk-local-change-me-litellm-webui-key` would leave chat, embeddings
    and reranking failing until the right key is entered in three places of the **Admin Panel**;
    `LAB_DOMAIN=lab.example.com` would store a wrong `WEBUI_URL`. Complete the file with the next
    two tasks before you install `ai-web`.

The alternative, `ENABLE_PERSISTENT_CONFIG=false`, makes the environment win at every start, but
every change made in the **Admin Panel**, MCP connections included, then lasts only until the next
restart. The stack keeps the default.

### Create the virtual key that Open WebUI uses

#### Prerequisites

- The `ai-inference` app is installed and healthy (Chapter 4). This command reports
  `"status":"healthy"` and `"db":"connected"`:

        sudo docker exec litellm python3 -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:4000/health/readiness').read().decode())"

#### About this task

Open WebUI uses one LiteLLM virtual key for chat, embeddings and reranking, and its model selector
lists exactly the models that the key allows. The key must allow `local-coder`, `local-fast`,
`local-coder-moe`, `local-embed` and `local-rerank`. This is the only task that creates it;
Chapter 4 creates only the keys of the workstations.

The command below runs inside the `litellm` container and calls LiteLLM's `/key/generate` endpoint
with the master key from the container's own environment, so the master key never appears on the
command line. Run it once: every run creates another valid key.

#### Steps

1. In the TrueNAS web interface, open **System** > **Shell**.

2. Create the key:

        sudo docker exec litellm python3 -c "import json, os, urllib.request as u; \
        body = json.dumps({'models': ['local-coder', 'local-fast', 'local-coder-moe', 'local-embed', 'local-rerank'], \
        'metadata': {'client': 'open-webui'}}).encode(); \
        req = u.Request('http://127.0.0.1:4000/key/generate', data=body, \
        headers={'Authorization': 'Bearer ' + os.environ['LITELLM_MASTER_KEY'], 'Content-Type': 'application/json'}); \
        print(json.load(u.urlopen(req))['key'])"

    The command prints the new key, which starts with `sk-`. Copy it; it is `<litellm-webui-key>`.

3. Check which models the key allows. Replace `<litellm-webui-key>` with the key:

        sudo docker exec litellm python3 -c "import json, urllib.request as u; \
        req = u.Request('http://127.0.0.1:4000/v1/models', headers={'Authorization': 'Bearer <litellm-webui-key>'}); \
        print(sorted(m['id'] for m in json.load(u.urlopen(req))['data']))"

    The output is
    `['local-coder', 'local-coder-moe', 'local-embed', 'local-fast', 'local-rerank']`.

#### Results

The key exists in LiteLLM and allows the five models that Open WebUI uses. The next task stores it
in `web.env`.

### Complete web.env before the first start

#### Prerequisites

- `~/.config/local-agent-stack/secrets/web.env` exists on the workstation, generated in Chapter 3
  with `--share` from `rag.env`
  ([Generate the environment files on the workstation](#generate-the-environment-files-on-the-workstation)).
- `edge.env` is complete (Chapter 5).
- You have `<litellm-webui-key>` from the previous task.

#### About this task

`tools/secrets.py` generated `WEBUI_SECRET_KEY`, `SEARXNG_SECRET` and `MCP_HUB_TOKEN`, and copied
`PG_PASSWORD` and `DOCLING_API_KEY` from `rag.env`. It left the values that you provide at the
placeholders of the example file, which is printed below. This task replaces them, checks the file
and copies it to the server.

{{ include stack/web/web.env.example }}

#### Steps

1. On the workstation, open the file in a text editor, for example:

        nano ~/.config/local-agent-stack/secrets/web.env

2. Set `LAB_DOMAIN` to your domain, the same value as in `edge.env`.

3. Set `LITELLM_WEBUI_KEY` to `<litellm-webui-key>`.

4. Set `SEARXNG_CONTACT_URL` to a `mailto:` address or a web page of yours. SearXNG sends it to the
   Wikipedia, Wikidata and OpenStreetMap engines, whose API policies require a contact. To keep
   those three engines off instead, leave the value empty (`SEARXNG_CONTACT_URL=`).

5. Leave `KB_READER_TOKEN` empty, and do not change the generated or copied values. Save the file
   and close the editor.

6. Check that no placeholder of the example file is left:

        grep -v '^#' ~/.config/local-agent-stack/secrets/web.env | grep -n -E 'change-me|example\.com'

    The command prints nothing. A line that it prints still holds a placeholder.

7. Check that `web.env` and `edge.env` name the same domain:

        grep -h '^LAB_DOMAIN=' ~/.config/local-agent-stack/secrets/edge.env ~/.config/local-agent-stack/secrets/web.env | sort -u | wc -l

    The output is `1`.

8. Check that `web.env` and `rag.env` share the database password and the docling key:

        for v in PG_PASSWORD DOCLING_API_KEY; do grep -h "^$v=" ~/.config/local-agent-stack/secrets/rag.env ~/.config/local-agent-stack/secrets/web.env | sort -u | wc -l; done

    The output is `1` twice.

9. Copy the file to the server with
   [Copy a changed environment file to TrueNAS](#copy-a-changed-environment-file-to-truenas),
   using `web` for `<app>`.

10. On TrueNAS, let Compose check the file against the app's compose file. This starts nothing:

        sudo docker compose --env-file /mnt/tank/ai/secrets/web.env -f /mnt/tank/ai/stacks/local-agent-stack/stack/web/compose.yaml config -q

    The command prints nothing. If a required value is missing, Compose names the variable.

#### Results

`/mnt/tank/ai/secrets/web.env` holds the final values that Open WebUI seeds on its first start.

### Copy a changed environment file to TrueNAS

#### About this task

The environment files are edited on the workstation in `~/.config/local-agent-stack/secrets/` and
copied to `/mnt/tank/ai/secrets/` on the server, where only root can read them. This chapter
repeats this task after every change; replace `<app>` with `rag` or `web`. An app reads the new
values at its next start or redeploy. The settings that Open WebUI seeded from `web.env` do not
change this way.

#### Steps

1. On the workstation, copy the file to the home directory of `truenas_admin`:

        scp ~/.config/local-agent-stack/secrets/<app>.env truenas_admin@192.0.2.10:

2. On TrueNAS, install it into the secrets dataset, owned by root with mode 0600:

        sudo install -m 0600 -o root -g root ~/<app>.env /mnt/tank/ai/secrets/

3. Delete the copy in the home directory:

        rm ~/<app>.env

4. Verify the file:

        sudo ls -l /mnt/tank/ai/secrets/<app>.env

    The output shows `-rw-------` and the owner `root root`.

#### Results

The server holds the new file. Chapter 3 describes the same procedure for all four files in
[Copy the environment files to TrueNAS](#copy-the-environment-files-to-truenas).

## Install the ai-rag app

The `ai-rag` app runs PostgreSQL with pgvector, the document parser and the knowledge-base sync.
Install it before `ai-web`: Open WebUI cannot start without `pgvector`. The document parser is
sized for the 64 GB reference system: `docling` may use up to 8 GB of memory and converts with two
workers. It requires the `X-Api-Key` header with `DOCLING_API_KEY` on every request, and its API
reference pages are turned off.

### Install ai-rag from a YAML wrapper

#### Prerequisites

- The datasets from Chapter 3 exist: `tank/ai/appdata/pgvector` (**Apps** preset, record size 32K),
  `tank/ai/appdata/oikb` (**Apps** preset, which gives the `apps` user, UID 568, Modify) and
  `tank/ai/rag-docs` with the SMB share and the `apps` group entry with Read access
  ([Give the apps group read access to rag-docs](#give-the-apps-group-read-access-to-rag-docs)).
  `oikb` runs as UID and GID 568.
- The `ai-net` network exists and the repository is cloned at the release tag (Chapter 3).
- `/mnt/tank/ai/secrets/rag.env` exists. `OIKB_TOKEN` and `OIKB_KB_ID` stay at their placeholders
  for now; they are set later in this chapter.

!!! caution
    `PG_PASSWORD` becomes the database password at the first start of `pgvector`, when its data
    directory is empty. Changing `PG_PASSWORD` later does not change the database password; it
    needs the procedure in [Rotate the other RAG and web secrets](#rotate-the-other-rag-and-web-secrets).
    Make sure that `rag.env` and `web.env` hold the same final value before you continue.

#### About this task

A TrueNAS custom app installed with **Install via YAML** holds only a wrapper: an `include:` of the
app's compose file from the clone, with the app's environment file, and the line `services: {}`,
which TrueNAS 25.10 requires. When you save, TrueNAS validates the YAML with `docker compose config`,
so the included files must already exist. It runs the app as the Compose project `ix-ai-rag`; the
containers keep the fixed names `pgvector`, `docling` and `oikb`, so other apps on `ai-net` reach
them by name. The first installation downloads the images; the document parser image alone is
about 4.4 GB.

The template of `rag.env`, for reference:

{{ include stack/rag/rag.env.example }}

#### Steps

1. On TrueNAS, let Compose check the environment file against the compose file. This starts
   nothing:

        sudo docker compose --env-file /mnt/tank/ai/secrets/rag.env -f /mnt/tank/ai/stacks/local-agent-stack/stack/rag/compose.yaml config -q

    The command prints nothing. If a required value is missing, Compose names the variable.

2. In the TrueNAS web interface, go to **Apps** > **Discover Apps**.

3. Click **⋮** (More Options) next to **Custom App**, then click **Install via YAML**.

4. In **Name**, enter `ai-rag`.

5. In **Custom Config**, enter exactly the following YAML. It is the file
   `stack/rag/truenas-app.yaml` of the release:

    {{ include stack/rag/truenas-app.yaml }}

    On the workstation, in the clone, `python3 tools/deploy.py render --app ai-rag` prints the same
    four lines after a `# ai-rag` line. When the clone has the release tag, it adds an
    `x-local-agent-stack` block with the content hashes that `deploy.py apply` records
    ([Setting up deploy.py](#setting-up-deploypy)). Paste only the four lines.

6. Click **Save**.

    TrueNAS validates the YAML, pulls the three images and starts the containers. If the
    installation fails, TrueNAS shows the error of the installation job; the Compose output is in
    `/var/log/app_lifecycle.log` (`sudo tail -n 50 /var/log/app_lifecycle.log`).

7. Wait until the three containers report healthy:

        sudo docker ps --filter name=pgvector --filter name=docling --filter name=oikb --format '{{.Names}} {{.Status}}'

    Each line ends with `(healthy)`. `docling` loads its models first; its health check allows
    180 seconds for the start.

#### Results

The `ai-rag` app is listed in **Apps** > **Installed**, and its three containers are healthy. The
logs of each container are under **Apps** > **Installed** > `ai-rag` > **Workloads** > **View
Logs**, or `sudo docker logs <container>` in the shell.

If `pgvector` keeps restarting instead, see
[Recreate the pgvector dataset with the Generic preset](#recreate-the-pgvector-dataset-with-the-generic-preset).

### Verify pgvector, docling and oikb

#### About this task

These checks confirm that PostgreSQL created its data directory, that the document parser is ready,
and that `oikb` can read the share and write its state. Until Open WebUI exists and the knowledge
base is configured, `oikb` runs, answers its health check, and logs one failed sync every 15
minutes. This is expected.

The `oikb` service runs the sync daemon as UID and GID 568, with the share mounted read-only at
`/data/docs` and its sync history (`history.db`) in the dataset `tank/ai/appdata/oikb`:

{{ include stack/rag/compose.yaml lines=100-144 }}

#### Steps

1. Check that PostgreSQL accepts connections:

        sudo docker exec pgvector pg_isready -U openwebui -d openwebui

    The output ends with `accepting connections`.

2. Check the data directory, which the image's entrypoint creates one level below the mounted
   dataset:

        sudo ls -ld /mnt/tank/ai/appdata/pgvector/pgdata

    The mode is `drwx------`.

3. Check that the document parser is ready:

        sudo docker exec docling python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:5001/ready', timeout=5).status)"

    The output is `200`.

4. Check that `oikb` can read the share and write its state directory:

        sudo docker exec oikb python -c "import os; print(os.listdir('/data/docs')); print(os.access('/state', os.W_OK))"

    The first line lists the files at the top of the share (`[]` while it is empty); the second
    line is `True`.

5. Display the health report of `oikb`:

        sudo docker exec oikb python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/health').read().decode())"

    The report lists each source with its last sync, its file counts and its error. The source
    `rag-docs` shows an error until the knowledge base is configured.

6. Display the recent log of `oikb`:

        sudo docker logs --tail 20 oikb

    The log is in JSON lines. A failed sync of `rag-docs` every 15 minutes is expected at this
    point.

#### Results

`pgvector` and `docling` are ready for Open WebUI, and `oikb` waits for its key and knowledge base.

!!! note
    Running `oikb` 0.6.0 as UID 568, a user ID without an entry in the image, was not tested. The
    image's own user (UID 1000) cannot read `rag-docs` with the ACL from Chapter 3. If step 4 raises
    a `PermissionError` or prints `False`, check the `apps` group entry on `rag-docs` and that
    `tank/ai/appdata/oikb` was created with the **Apps** preset.

!!! note
    The `no-new-privileges` setting was not tested with the PostgreSQL entrypoint, which switches to
    the `postgres` user with `gosu` and needs no setuid bit, nor with `docling` and `oikb`. If one of
    the three containers keeps restarting and its log names a privilege or setuid error, record the
    log lines before you change anything; Chapter 11 covers troubleshooting.

### Recreate the pgvector dataset with the Generic preset

#### Prerequisites

- `pgvector` keeps restarting, and its log shows a permissions error for
  `/var/lib/postgresql/data/pgdata`.
- The database has never started, so the dataset holds no data.

#### About this task

PostgreSQL's first start on a dataset with the **Apps** preset (NFSv4 ACL) was not tested. The
image's entrypoint changes the mode of `PGDATA` to 0700, which the dataset's ACL mode can refuse.
If that happens, recreate `tank/ai/appdata/pgvector` with the **Generic** preset. A dataset's preset
cannot be changed after it is created, so this task destroys the empty dataset and creates it
again. The `pgvector` service mounts the dataset at `/var/lib/postgresql/data` and keeps `PGDATA`
one level below it:

{{ include stack/rag/compose.yaml lines=33-62 }}

!!! caution
    `zfs destroy` deletes the dataset and every file in it. Run step 3 only while the database has
    never started. After Open WebUI has stored data, restore from a backup instead (Appendix A).

#### Steps

1. Confirm the error:

        sudo docker logs --tail 30 pgvector

    The log shows a permissions error that names `/var/lib/postgresql/data/pgdata`.

2. Stop the container:

        sudo docker stop pgvector

3. Destroy the dataset:

        sudo zfs destroy tank/ai/appdata/pgvector

4. In the TrueNAS web interface, go to **Datasets**, select `tank/ai/appdata` and click
   **Add Dataset**.

5. Enter **Name** `pgvector` and select **Dataset Preset** `Generic`.

6. Click **Advanced Options**, set **Record Size** to `32K` and click **Save**.

7. Verify the record size:

        sudo zfs get -o property,value recordsize tank/ai/appdata/pgvector

    The value is `32K`.

8. Redeploy the app, which recreates all three containers:

        sudo midclt call -j app.redeploy ai-rag

9. Repeat [Verify pgvector, docling and oikb](#verify-pgvector-docling-and-oikb).

#### Results

PostgreSQL initializes its data directory on the **Generic** dataset and accepts connections.

## Install the ai-web app

The `ai-web` app runs Open WebUI, SearXNG and the MCP hub. Its MCP hub image is built from the
repository, so the image must be on the server before Compose can start the app.

### Build or pull the MCP hub image

#### About this task

The `mcp-hub` service names the image `ghcr.io/corytron/local-agent-stack-mcp-hub:0.15.0` and the
build context `./mcp-hub`. Compose pulls the image if it is published, and otherwise builds it from
`stack/web/mcp-hub` in the clone on the server.

The GitHub Actions workflow **MCP hub image** (`.github/workflows/mcp-hub-image.yml`) builds the
image from `stack/web/mcp-hub` on a push to `main` that changes that folder or the workflow, or on
a manual run, and publishes it on the GitHub Container Registry with a signed build provenance
attestation, in the same way as the Caddy image
([How the image is built and published](#how-the-image-is-built-and-published)). When this guide
was written, the image had not yet been published, and the compose file names it by tag only,
without a digest. Until a release pins the digest, a later run of the workflow can publish a
different image under the same tag. If the pull in step 1 fails, build the image on the server.

The build starts from `ghcr.io/sparfenyuk/mcp-proxy:v0.15.0-debian-node`, pinned by digest, and adds
two Node.js MCP servers, installed with `npm ci` from the lock file (127 packages, none with an
install script), and the Python fetch server, installed into its own virtual environment with every
package checked by hash. The image is about 430 MB and runs as UID 10001. The time the build takes
was not measured; it depends on the download of the base image and the packages. If Compose builds
the image during the installation, the installation job shows no progress until the build ends.
Building it first in the shell shows each step and any error, and the installation of `ai-web` then
uses the image at once.

{{ include stack/web/compose.yaml lines=166-205 }}

#### Steps

1. Try to pull the published image:

        sudo docker pull ghcr.io/corytron/local-agent-stack-mcp-hub:0.15.0

    If the pull succeeds, continue with step 3. An error such as `not found`, `manifest unknown`
    or `denied` means that the image is not published; continue with step 2.

2. Build the image from the clone, under the name that the compose file uses:

        sudo docker build -t ghcr.io/corytron/local-agent-stack-mcp-hub:0.15.0 /mnt/tank/ai/stacks/local-agent-stack/stack/web/mcp-hub

    Docker prints each step of the Dockerfile and ends by naming the tagged image. An error in a
    `RUN` step stops the build and prints the failing command's output.

3. Verify the image:

        sudo docker image ls ghcr.io/corytron/local-agent-stack-mcp-hub

    The list shows the tag `0.15.0` with a size of about 430 MB.

4. Optional, if step 1 pulled the image: on the workstation, with the GitHub CLI (`gh`) installed
   and logged in, verify the provenance of the image:

        gh attestation verify oci://ghcr.io/corytron/local-agent-stack-mcp-hub:0.15.0 --repo corytron/local-agent-stack

    The command reports a successful verification. The attestation was signed by the workflow
    `.github/workflows/mcp-hub-image.yml` of the repository.

#### Results

The MCP hub image is on the server, and Compose uses it when `ai-web` is installed.

!!! note
    Building the image on TrueNAS 25.10 was not tried; it was built and tested on another Docker
    host. If step 2 fails on the server and the workstation has Docker, build the image there and
    copy it. On the workstation:

        docker build -t ghcr.io/corytron/local-agent-stack-mcp-hub:0.15.0 ~/local-agent-stack/stack/web/mcp-hub
        docker save -o /tmp/mcp-hub.tar ghcr.io/corytron/local-agent-stack-mcp-hub:0.15.0
        scp /tmp/mcp-hub.tar truenas_admin@192.0.2.10:/mnt/tank/ai/stacks/
        rm /tmp/mcp-hub.tar
        docker image rm ghcr.io/corytron/local-agent-stack-mcp-hub:0.15.0

    Then, on TrueNAS:

        sudo docker load -i /mnt/tank/ai/stacks/mcp-hub.tar
        rm /mnt/tank/ai/stacks/mcp-hub.tar

!!! note
    A redeploy of `ai-web` does not rebuild an image that is already on the server. When a later
    release changes files under `stack/web/mcp-hub`, repeat step 2 before you redeploy `ai-web`.

### Install ai-web from a YAML wrapper

#### Prerequisites

- `ai-rag` is installed and its containers are healthy.
- `ai-inference` is installed and `litellm` is healthy (Chapter 4).
- `/mnt/tank/ai/secrets/web.env` is complete
  ([Complete web.env before the first start](#complete-webenv-before-the-first-start)).
- The MCP hub image is on the server ([Build or pull the MCP hub image](#build-or-pull-the-mcp-hub-image)).

#### About this task

On its first start, Open WebUI connects to `pgvector`, creates its tables and the `vector`
extension, and seeds its settings from the environment. Its health check allows 120 seconds for the
first start. The installation itself does not need `ai-edge`; signing in does.

#### Steps

1. On TrueNAS, let Compose check the environment file once more:

        sudo docker compose --env-file /mnt/tank/ai/secrets/web.env -f /mnt/tank/ai/stacks/local-agent-stack/stack/web/compose.yaml config -q

    The command prints nothing.

2. Go to **Apps** > **Discover Apps**, click **⋮** (More Options) next to **Custom App**, then
   click **Install via YAML**.

3. In **Name**, enter `ai-web`.

4. In **Custom Config**, enter exactly the following YAML. It is the file
   `stack/web/truenas-app.yaml` of the release:

    {{ include stack/web/truenas-app.yaml }}

    On the workstation, in the clone, `python3 tools/deploy.py render --app ai-web` prints the same
    four lines after a `# ai-web` line. When the clone has the release tag, it adds an
    `x-local-agent-stack` block with the content hashes that `deploy.py apply` records
    ([Setting up deploy.py](#setting-up-deploypy)). Paste only the four lines.

5. Click **Save**.

6. Wait until the three containers report healthy:

        sudo docker ps --filter name=open-webui --filter name=searxng --filter name=mcp-hub --format '{{.Names}} {{.Status}}'

    Each line ends with `(healthy)`.

#### Results

The `ai-web` app is listed in **Apps** > **Installed**, and its three containers are healthy.

!!! note
    The `no-new-privileges` setting was not tested with Open WebUI's start script, which runs as
    root and uses no setuid program. If `open-webui` keeps restarting and its log names a privilege
    error, record the log lines before you change anything; Chapter 11 covers troubleshooting.

### Verify Open WebUI, SearXNG and the MCP hub containers

#### Steps

1. Check Open WebUI's health endpoint:

        sudo docker exec open-webui curl -s http://127.0.0.1:8080/health

    The output is `{"status":true}`.

2. Check that Open WebUI created the `vector` extension in PostgreSQL:

        sudo docker exec pgvector psql -U openwebui -d openwebui -c "SELECT extversion FROM pg_extension WHERE extname = 'vector';"

    The output has one row with the version of the extension (`0.8.7` for this image).

3. Check that Open WebUI reaches the document parser:

        sudo docker exec open-webui curl -s -o /dev/null -w '%{http_code}\n' http://docling:5001/health

    The output is `200`.

4. Check the MCP hub's own health check, which passes only when all three tool servers started:

        sudo docker exec mcp-hub mcp-hub-healthcheck

    The output is `ok: fetch, kb, searxng`.

5. Display the start of SearXNG's log:

        sudo docker logs searxng 2>&1 | head -n 20

    A warning about the ownership of `/etc/searxng` is expected: the configuration is mounted
    read-only from the clone, and the container is told not to change its owner
    (`FORCE_OWNERSHIP=false`).

#### Results

Open WebUI runs on its database, reaches the document parser, and the MCP hub serves its three tool
servers. In the MCP hub's log, two start-up lines of the knowledge-base server appear on standard
error; they are expected (the server is started with a preload file that moves its console output
off the protocol channel).

## Configure Open WebUI

This topic creates the administrator account, confirms the settings that Open WebUI seeded from
`web.env`, and creates the two service users whose keys `oikb` and the MCP hub need.

!!! note
    Open WebUI 0.13.3 was not run while this guide was written. The labels **Admin Panel**,
    **Add User**, **Default permissions**, **API Keys**, **API keys** and **Create new secret key**,
    and the field labels **Content Extraction Engine**, **Embedding Model Engine**,
    **Hybrid Search** and **Reranking Engine**, were read from the 0.13.3 source and its English
    texts. The tab captions **Connections**, **Documents**, **Web Search** and **Integrations**,
    the other menu names in this topic and the access dialog of a knowledge base were not checked.
    If a caption differs, open the tab or menu that holds the same settings.

### Sign in to Open WebUI for the first time

#### Prerequisites

- The `ai-edge` app runs, the DNS record for `chat.lab.example.com` points to `192.0.2.10`, and
  Caddy holds a certificate for it (Chapter 5). On the workstation, this command prints
  `HTTP/2 200` or a redirect to `/auth`:

        curl -sI https://chat.lab.example.com | head -1

!!! warning
    The first account created in Open WebUI becomes the administrator. Create it immediately after
    you install `ai-web`: until then, anyone on the LAN who opens the address first can claim it.

#### About this task

`web.env` seeds `ENABLE_SIGNUP=false`. Open WebUI never applies that flag to the first account,
and turns sign-up off after it; later users are created by the administrator in the
**Admin Panel**. `DEFAULT_USER_ROLE` is `pending`, so if sign-up is ever turned on again, a new
account waits for approval. Open WebUI accepts browsers only at `https://chat.lab.example.com` (its allowed origin
and secure session cookie), so always use that address, never the server's IP address.

#### Steps

1. In a browser on the LAN, open `https://chat.lab.example.com`.

    Because no account exists yet, Open WebUI offers to create one.

2. Enter a name, an email address and a password, and create the account.

    You sign in with the email address and the password from now on.

3. Store the password in a password manager.

4. Open the menu under your account name and confirm that it offers **Admin Panel**.

#### Results

You are signed in as the administrator, and sign-up is closed for everyone else.

### Check the Open WebUI connections and document settings

#### About this task

This task confirms that Open WebUI seeded the settings from `web.env`, and checks the embedding
and reranking routes that it uses through LiteLLM. No change is expected. If a value differs,
correct it on the same page and click **Save**.

#### Steps

1. Open the **Admin Panel** from the menu under your account name.

2. Click **Settings** > **Connections**. Confirm that the OpenAI API is on with exactly one
   connection, `http://litellm:4000/v1`, and that the Ollama API is off.

3. Start a new chat and open the model selector. It lists `local-coder`, `local-fast`,
   `local-coder-moe`, `local-embed` and `local-rerank`, and `local-coder` is the default.

    `local-embed` and `local-rerank` serve retrieval only; do not chat with them. Selecting
    `local-coder-moe` loads the fast profile on the GPU, which takes tens of seconds, and the next
    request for any other chat model loads `coder` again. Titles, tags and follow-up suggestions use
    `local-fast` (`TASK_MODEL_EXTERNAL`), the primary model with thinking off, which needs no model
    swap.

4. In the **Admin Panel**, click **Settings** > **Documents** and confirm these values:

    - **Content Extraction Engine**: Docling, with the URL `http://docling:5001`
    - **Embedding Model Engine**: OpenAI, with the URL `http://litellm:4000/v1` and the model
      `local-embed`
    - **Hybrid Search**: on
    - **Reranking Engine**: External, with the model `local-rerank` and the URL
      `http://litellm:4000/v1/rerank`

    The other values on the page, such as the chunk size and the number of results, are the ones
    quoted in [Settings that Open WebUI keeps from its first start](#settings-that-open-webui-keeps-from-its-first-start).

5. Click **Settings** > **Web Search** and confirm that web search is on, with the engine
   `searxng` and the query URL `http://searxng:8080/search?q=<query>`.

6. On TrueNAS, read the Open WebUI key from `web.env` into a shell variable and check the embedding
   route:

        K=$(sudo sed -n 's/^LITELLM_WEBUI_KEY=//p' /mnt/tank/ai/secrets/web.env)
        sudo docker exec open-webui curl -s http://litellm:4000/v1/embeddings -H "Authorization: Bearer $K" \
          -H 'Content-Type: application/json' -d '{"model":"local-embed","input":"pgvector adds vector search to PostgreSQL"}' \
          | python3 -c "import json, sys; print(len(json.load(sys.stdin)['data'][0]['embedding']))"

    The output is `1024`, the vector size of the embedding model.

7. Check the reranking route in the same shell:

        sudo docker exec open-webui curl -s http://litellm:4000/v1/rerank -H "Authorization: Bearer $K" \
          -H 'Content-Type: application/json' \
          -d '{"model":"local-rerank","query":"what is pgvector","documents":["pgvector adds vector search to PostgreSQL","bananas are yellow"],"top_n":2}'

    The answer holds `results`, each with an `index` and a `relevance_score`; the document with
    `index` 0 scores higher than the document with `index` 1.

#### Results

Open WebUI uses LiteLLM for chat, embeddings and reranking, docling for document extraction and
SearXNG for web search.

If steps 6 and 7 succeed but the model selector in step 3 is empty, the key that Open WebUI stored
differs from the key in `web.env` (for example, a placeholder was seeded). Enter the key from
`web.env` in **Settings** > **Connections** for the `http://litellm:4000/v1` connection and in
**Settings** > **Documents** twice, as the embedding key and as the reranker key. To display it:
`sudo sed -n 's/^LITELLM_WEBUI_KEY=//p' /mnt/tank/ai/secrets/web.env`.

If step 7 fails while step 6 succeeds, use
[Point the reranker at llama-swap](#point-the-reranker-at-llama-swap).

!!! note
    The embedding and reranking chain Open WebUI → LiteLLM → llama-swap was not run end to end.
    Open WebUI's external reranker sends `model`, `query`, `documents` and `top_n` and reads
    `results` with `index` and `relevance_score`; LiteLLM 1.108.8 answers its `/v1/rerank` route in
    that shape. Both sides were checked in the source of the pinned versions. Steps 6 and 7 are the
    first test of the chain on your system.

!!! note
    The retrieval values `RAG_EMBEDDING_BATCH_SIZE=16`, `RAG_TOP_K=20` and `RAG_TOP_K_RERANKER=8`
    are starting points for embedding and reranking on the CPU, not measured values. If document
    searches are slow or miss passages, adjust them on the **Documents** page.

### Point the reranker at llama-swap

#### About this task

Use this task only if the reranking check through LiteLLM fails. llama.cpp's `/v1/rerank`, which
llama-swap serves, takes and returns the same request and answer shape, so Open WebUI can call it
directly. This costs a second copy of the llama-swap key in Open WebUI, and reranking requests then
bypass LiteLLM's keys and logs.

#### Steps

1. On TrueNAS, read the llama-swap key and check llama-swap's reranking route:

        L=$(sudo sed -n 's/^LLAMA_SWAP_API_KEY=//p' /mnt/tank/ai/secrets/inference.env)
        sudo docker exec open-webui curl -s http://llama-swap:8080/v1/rerank -H "Authorization: Bearer $L" \
          -H 'Content-Type: application/json' \
          -d '{"model":"rerank","query":"what is pgvector","documents":["pgvector adds vector search to PostgreSQL","bananas are yellow"],"top_n":2}'

    The answer holds `results` with `index` and `relevance_score`.

2. Display the key to enter in Open WebUI:

        sudo sed -n 's/^LLAMA_SWAP_API_KEY=//p' /mnt/tank/ai/secrets/inference.env

3. In Open WebUI, open **Admin Panel** > **Settings** > **Documents**. Under **Reranking Engine**
   External, set the URL to `http://llama-swap:8080/v1/rerank`, the model to `rerank` and the API
   key to the llama-swap key.

4. Click **Save**.

#### Results

Open WebUI reranks through llama-swap. The embedding model and the chat models still go through
LiteLLM.

## Create the service users and their API keys

`oikb` and the MCP hub's knowledge-base server call Open WebUI with API keys. Each key acts as its
user and does not bypass Open WebUI's access control, so each tool gets its own user with only the
access it needs.

Table: Service users

| User | Access to the rag-docs knowledge base | Its API key goes to |
|---|---|---|
| `indexer` | Write | `OIKB_TOKEN` in `rag.env`, for `oikb` |
| `kb-reader` | Read | `KB_READER_TOKEN` in `web.env`, for the `kb` server of the MCP hub |

`kb-reader` sees only the knowledge bases that it is given, so the coding agent searches only
those. `web.env` seeds `ENABLE_API_KEYS=true`; users other than the administrator also need the
**API Keys** permission, which this topic grants through a group.

### Create the service-accounts group

#### Steps

1. In Open WebUI, open **Admin Panel** > **Users** > **Groups**.

2. Create a group named `service-accounts`.

3. In the permissions of the group, turn on **API Keys**, and save the group.

4. Open **Default permissions** on the same page and confirm that **API Keys** is off.

#### Results

Members of `service-accounts` can create API keys; every other user cannot.

### Add the indexer and kb-reader users

#### Steps

1. On the workstation, generate a password for each user and store both in a password manager:

        python3 -c "import secrets; print(secrets.token_urlsafe(24))"

    You need each password to sign in as that user when you create or rotate its key.

2. In Open WebUI, open **Admin Panel** > **Users** and click **Add User**.

3. Select the role `user`, enter the name `indexer`, the email address `indexer@lab.example.com`
   and the first password, and save.

4. Repeat steps 2 and 3 with the name `kb-reader`, the email address `kb-reader@lab.example.com`
   and the second password.

5. Open **Admin Panel** > **Users** > **Groups**, open `service-accounts` and add `indexer` and
   `kb-reader` as members.

#### Results

The user list shows `indexer` and `kb-reader` with the role `user`, both members of
`service-accounts`.

### Create the rag-docs knowledge base

#### About this task

`oikb` fills one knowledge base from the whole `rag-docs` share. You create the knowledge base as
the administrator, give `indexer` write access and `kb-reader` read access, and note its ID for
`OIKB_KB_ID`.

#### Steps

1. In Open WebUI, signed in as the administrator, open **Workspace** > **Knowledge**.

2. Create a knowledge base named `rag-docs`, with a description such as
   `Documents from the rag-docs share`.

3. In the access settings of the knowledge base, give `indexer` write access and `kb-reader` read
   access, and save.

4. Open the knowledge base. The address of its page ends with its ID. Copy the ID, the last part of
   the address after the final `/`; it is `<kb-id>`.

#### Results

The `rag-docs` knowledge base exists and is empty. `oikb` fills it once it has its key and the ID.

!!! note
    The access dialog of a knowledge base was not checked against a running Open WebUI 0.13.3. The
    result is checked later: the sync of `oikb` fails if `indexer` cannot write, and the MCP hub's
    `list_knowledge_bases` tool lists nothing if `kb-reader` cannot read
    ([Verify the MCP hub from the TrueNAS shell](#verify-the-mcp-hub-from-the-truenas-shell)).

### Create the API keys of the service users

#### Prerequisites

- On the workstation, `rag.env` and `web.env` in `~/.config/local-agent-stack/secrets/` are open in
  a text editor, so that each key goes straight into its file.

#### Steps

1. Open a private browser window, go to `https://chat.lab.example.com` and sign in as
   `indexer@lab.example.com`.

    The private window keeps your administrator session in the main window.

2. Open **Settings** > **Account**, and under **API keys** click **Create new secret key**.

3. Copy the key and set it as `OIKB_TOKEN` in `rag.env`: `OIKB_TOKEN=<indexer-key>`.

4. Sign out of the private window.

5. Sign in as `kb-reader@lab.example.com` in the private window and repeat step 2.

6. Copy the key and set it as `KB_READER_TOKEN` in `web.env`: `KB_READER_TOKEN=<kb-reader-key>`.

7. Sign out and close the private window.

#### Results

Each service user has an API key, and the keys are in the environment files on the workstation.
The next task sets the knowledge base ID and puts the files on the server.

### Store the service keys and redeploy ai-rag and ai-web

#### Steps

1. In `rag.env`, set `OIKB_KB_ID=<kb-id>`, and save both files.

2. Check that `rag.env` has no placeholder and an ID:

        grep -v '^#' ~/.config/local-agent-stack/secrets/rag.env | grep -n -E 'placeholder|change-me|^OIKB_KB_ID=$'

    The command prints nothing.

3. Check that `web.env` holds the `kb-reader` key:

        grep -c '^KB_READER_TOKEN=.' ~/.config/local-agent-stack/secrets/web.env

    The output is `1`.

4. Copy both files to the server with
   [Copy a changed environment file to TrueNAS](#copy-a-changed-environment-file-to-truenas): once
   with `rag` and once with `web` for `<app>`.

5. On TrueNAS, redeploy `ai-rag`:

        sudo midclt call -j app.redeploy ai-rag

    The redeploy recreates every container of the app, `pgvector` included. Open WebUI reconnects to
    the database by itself.

6. Wait until `pgvector`, `docling` and `oikb` report healthy:

        sudo docker ps --filter name=pgvector --filter name=docling --filter name=oikb --format '{{.Names}} {{.Status}}'

7. Redeploy `ai-web`, which gives the MCP hub the `kb-reader` key:

        sudo midclt call -j app.redeploy ai-web

8. Wait until `open-webui`, `searxng` and `mcp-hub` report healthy:

        sudo docker ps --filter name=open-webui --filter name=searxng --filter name=mcp-hub --format '{{.Names}} {{.Status}}'

#### Results

`oikb` and the MCP hub hold their Open WebUI keys. Within 15 minutes `oikb` uploads the contents
of the share into the `rag-docs` knowledge base; [Follow the oikb sync](#follow-the-oikb-sync)
starts a sync at once and shows its progress. Open WebUI keeps your session across the redeploy,
because `WEBUI_SECRET_KEY` did not change.

## Index the rag-docs share

The `rag-docs` share is the drop folder for the documents that the stack indexes. `oikb` sends
Open WebUI a SHA-256 manifest of the share at every interval, uploads only the files that were
added or changed, and removes the files that were deleted. Unchanged files cost nothing. Each
uploaded file is converted by `docling` and embedded on the CPU.

### Copy documents to the rag-docs share

#### About this task

The whole share goes into the one `rag-docs` knowledge base; subfolders are included. `docling`
converts PDF, Word, PowerPoint, Excel, HTML, image and Markdown files, with OCR and table structure.
`oikb` skips files over 100 MB and the usual clutter: `.git`, `node_modules`, `.zfs`, `.recycle` and
`@eaDir` folders, Office lock files (`~$*`), `._*` files, `*.tmp` files and `.DS_Store`. The
configuration that `oikb` reads:

{{ include stack/rag/oikb/oikb.yaml }}

#### Steps

1. From a client, connect to the share as `<smb-user>`:

    - macOS: **Finder** > **Go** > **Connect to Server**, enter `smb://192.0.2.10/rag-docs`.
    - Windows: in File Explorer, open `\\192.0.2.10\rag-docs`.
    - Linux (requires the `cifs-utils` package):

            sudo mkdir -p /mnt/rag-docs
            sudo mount -t cifs //192.0.2.10/rag-docs /mnt/rag-docs -o username=<smb-user>

2. Copy the documents into the share. Start with a few files to check the pipeline before you copy
   a large collection.

#### Results

The documents are on the share. `oikb` picks them up at its next interval.

### Follow the oikb sync

#### About this task

`oikb` syncs every 15 minutes and uploads two files at a time. A synchronous conversion in
`docling` may take up to 600 seconds, so a large PDF can hold its upload slot for minutes. This task
starts a sync at once and shows where to see its progress. The `oikb` routes `/sync` and `/history`
require `OIKB_API_KEY`, which the commands read from the container's environment.

#### Steps

1. On TrueNAS, start a sync of `rag-docs` now:

        sudo docker exec oikb python -c "import os, urllib.request as u; \
        u.urlopen(u.Request('http://127.0.0.1:8080/sync/rag-docs', method='POST', \
        headers={'Authorization': 'Bearer ' + os.environ['OIKB_API_KEY']}))"

    The command returns without output. An `HTTP Error 401` means that the key in the request does
    not match `OIKB_API_KEY`.

2. Display the health report:

        sudo docker exec oikb python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/health').read().decode())"

    The source `rag-docs` shows the time of its last sync and its file counts, and no error.

3. Display the sync history:

        sudo docker exec oikb python -c "import os, urllib.request as u; \
        print(u.urlopen(u.Request('http://127.0.0.1:8080/history', \
        headers={'Authorization': 'Bearer ' + os.environ['OIKB_API_KEY']})).read().decode())"

4. Follow the log while a sync runs, and press Ctrl+C to stop:

        sudo docker logs -f --since 10m oikb

5. In Open WebUI, open **Workspace** > **Knowledge** > `rag-docs`. The knowledge base lists the
   files that have been uploaded and processed.

#### Results

The knowledge base holds the documents of the share and follows its changes every 15 minutes.

A file that Open WebUI rejects, for example because of its size or file type, fails again at every
sync. Remove such files from the share: the file filter is part of `stack/rag/oikb/oikb.yaml`,
which changes only with a release.

### Search the knowledge base from a chat

#### Steps

1. In Open WebUI, start a new chat with `local-coder`.

2. Ask a question that one of the indexed documents answers, and name the subject precisely.

    Open WebUI 0.13 uses native function calling by default: the model calls the built-in
    knowledge tool by itself, which searches the knowledge bases that you can read.

3. If the answer does not draw on the documents, type `#` in the message box, select the
   `rag-docs` knowledge base, and ask again.

#### Results

The answer uses passages from the indexed documents and names its sources.

!!! note
    The `#` selection of a knowledge base in the message box was not checked against a running Open
    WebUI 0.13.3. If it is not offered, attach the knowledge base from the message box's menu.

## Verify web search and the MCP hub

Open WebUI searches the web through SearXNG, and the coding agent reaches the same search engine,
a page fetcher and the knowledge base through the MCP hub. This topic checks each path from the
TrueNAS shell, over `ai-net`, and from a chat.

### Query SearXNG from the TrueNAS shell

#### About this task

SearXNG's configuration lists only the differences from its defaults. The JSON output format is on,
because Open WebUI and the MCP hub's search server get HTTP 403 without it. The limiter is off,
because the instance serves only the LAN and the limiter would throttle the API clients. Google and
Bing are not queried: their main engines ship disabled and are listed anyway, and their side
engines that ship enabled in this version are turned off. General results come from DuckDuckGo,
Brave, Wikipedia and Wikidata; npm, crates.io, pkg.go.dev, GitLab, Codeberg, Hugging Face and
Hacker News are added to the IT category. The two Tor engines are inactive, so they log no error
at start. `SEARXNG_SECRET` replaces the built-in secret, with which SearXNG refuses to start. The
file `stack/web/searxng/limiter.toml` is empty on purpose, because SearXNG warns when it is
missing. SearXNG keeps no state: its configuration is mounted read-only from the clone, and its
favicon cache is in memory.

{{ include stack/web/searxng/settings.yml }}

#### Steps

1. Check SearXNG's health endpoint:

        sudo docker exec searxng wget -q -O - http://127.0.0.1:8080/healthz

    The output is `OK`.

2. Run a search through the JSON API, as Open WebUI does:

        sudo docker exec open-webui curl -s 'http://searxng:8080/search?q=test&format=json' | head -c 300

    The output is the beginning of a JSON document with the query and its results.

3. Count the results:

        sudo docker exec open-webui curl -s 'http://searxng:8080/search?q=test&format=json' | python3 -c "import json, sys; print(len(json.load(sys.stdin)['results']))"

    The output is a number greater than zero.

4. Run a search in the IT category, which uses the developer engines:

        sudo docker exec open-webui curl -s 'http://searxng:8080/search?q=pgvector&categories=it&format=json' | python3 -c "import json, sys; print(len(json.load(sys.stdin)['results']))"

    The output is a number greater than zero.

5. Optional: in a browser on the LAN, open `https://search.lab.example.com` and run a search.

#### Results

SearXNG answers JSON searches on `ai-net`, and its web interface is available to administrators
through the edge app.

!!! note
    Public search engines suspend a metasearch instance that triggers their CAPTCHAs, for example
    for an hour. Suspended engines are the main reason for empty or thin results. Check
    `sudo docker logs --tail 50 searxng` or the statistics page at
    `https://search.lab.example.com/stats`, and wait for the suspension to end.

### Search the web from an Open WebUI chat

#### Steps

1. In Open WebUI, start a new chat with `local-coder`.

2. Ask a question that needs current information from the web, for example
   `Search the web for the latest SearXNG release and summarize it.`

    The model calls the built-in web search tool, which queries SearXNG, and can fetch the pages
    it finds.

3. If the answer shows no web sources, turn on web search for the chat in the message box's menu,
   and ask again.

#### Results

The answer cites web pages that SearXNG found. Open WebUI's page fetcher cannot reach addresses on
the LAN or on `ai-net` (`ENABLE_LOCAL_WEB_FETCH=false`).

### Verify the MCP hub from the TrueNAS shell

#### About this task

The MCP hub runs `mcp-proxy` 0.15.0, which serves three stdio MCP servers over Streamable HTTP at
`/servers/<name>/mcp`. It checks the bearer token (`MCP_HUB_TOKEN`) on every request, `/status`
included, and answers HTTP 421 to any `Host` header other than `mcp-hub:8096` or the loopback
address; Caddy sends `mcp-hub:8096` for `mcp.lab.example.com`.

Table: Tool servers of the MCP hub

| Path | Server | Tools |
|---|---|---|
| `/servers/searxng/mcp` | `mcp-searxng` 2.10.1 against `http://searxng:8080`; at most 10 results of 500 characters, 20,000 characters per page read | `searxng_web_search`, `searxng_search_suggestions`, `searxng_instance_info`, `web_url_read` |
| `/servers/fetch/mcp` | `mcp-server-fetch` 2026.11.11 with the Python page extractor only; refuses private, loopback and link-local addresses and honours robots.txt | `fetch` |
| `/servers/kb/mcp` | `open-webui-knowledge-mcp-server` 0.2.0 against `http://open-webui:8080/api/v1`, with the `kb-reader` key | `search_knowledge_base`, `list_knowledge_bases`, `get_knowledge_base_info`, `get_knowledge_base_file_content` |

The server configuration holds no secrets; the `kb` server reads its key from the container's
environment:

{{ include stack/web/mcp-hub/servers.json }}

The commands below run `curl` inside the `open-webui` container, which sits on `ai-net`. An MCP
session starts with `initialize`; if the answer carries an `mcp-session-id` header, the later
requests of the session send it back. Each answer is either plain JSON or an event stream whose
`data:` line holds the JSON message.

#### Steps

1. Check the hub's own health check:

        sudo docker exec mcp-hub mcp-hub-healthcheck

    The output is `ok: fetch, kb, searxng`.

2. Read the hub token from `web.env` into a shell variable:

        T=$(sudo sed -n 's/^MCP_HUB_TOKEN=//p' /mnt/tank/ai/secrets/web.env)

3. Check that the hub refuses a request without the token, and a foreign `Host` header:

        sudo docker exec open-webui curl -s -o /dev/null -w '%{http_code}\n' -X POST http://mcp-hub:8096/servers/fetch/mcp
        sudo docker exec open-webui curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $T" -H 'Host: evil.example.com' http://mcp-hub:8096/status

    The outputs are `401` and `421`.

4. Choose the server to test, starting with `kb`:

        N=kb

5. Start a session:

        sudo docker exec open-webui curl -s -i http://mcp-hub:8096/servers/$N/mcp \
          -H "Authorization: Bearer $T" -H 'Content-Type: application/json' \
          -H 'Accept: application/json, text/event-stream' \
          -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"check","version":"0"}}}'

    The status line shows `200`, and the JSON result holds `protocolVersion` and a
    `serverInfo` with the server's name and version. For `fetch`, the name is `mcp-fetch` and the
    version `2026.11.11`.

6. Copy the value of the `mcp-session-id` header from the answer into a shell variable:

        S=<session-id>

    If the answer has no `mcp-session-id` header, leave out `-H "Mcp-Session-Id: $S"` in the next
    commands.

7. Complete the start of the session:

        sudo docker exec open-webui curl -s -o /dev/null -w '%{http_code}\n' http://mcp-hub:8096/servers/$N/mcp \
          -H "Authorization: Bearer $T" -H "Mcp-Session-Id: $S" -H 'MCP-Protocol-Version: 2025-06-18' \
          -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
          -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

    The output is a status in the 200 range; a notification has no result.

8. List the server's tools:

        sudo docker exec open-webui curl -s http://mcp-hub:8096/servers/$N/mcp \
          -H "Authorization: Bearer $T" -H "Mcp-Session-Id: $S" -H 'MCP-Protocol-Version: 2025-06-18' \
          -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
          -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

    The result lists the tools of the server, as in the table above, each with its description and
    input schema.

9. For `kb`, call `list_knowledge_bases`, which runs as the `kb-reader` user:

        sudo docker exec open-webui curl -s http://mcp-hub:8096/servers/kb/mcp \
          -H "Authorization: Bearer $T" -H "Mcp-Session-Id: $S" -H 'MCP-Protocol-Version: 2025-06-18' \
          -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
          -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"list_knowledge_bases","arguments":{}}}'

    The result names the `rag-docs` knowledge base and its ID. An authentication error means that
    `KB_READER_TOKEN` is empty or wrong, or that `ai-web` was not redeployed after it was set.

10. Repeat steps 4 to 8 with `N=searxng` and with `N=fetch`.

#### Results

The MCP hub accepts only requests with the token, and each of its three servers starts a session
and lists its tools. The `kb` server sees the `rag-docs` knowledge base through the `kb-reader`
user. Chapter 7 connects the coding agent to the hub at `https://mcp.lab.example.com`.

!!! note
    These checks passed on another Docker host for all three servers with protocol version
    2025-06-18: the tool lists, a live search through SearXNG, a fetch of `https://example.com`, the
    refusal of a private address by `fetch`, HTTP 401 without or with a wrong token and HTTP 421 for
    a foreign `Host` header. The `kb` server was not called against a real Open WebUI; step 9 is its
    first test against your knowledge base.

### Connect Open WebUI to the MCP hub (optional)

#### About this task

Open WebUI's own tools already search the web through SearXNG, fetch pages and query knowledge
bases, so the web interface needs no connection to the MCP hub. Add one only if you want the hub's
tools in chats as well. Only administrators can add MCP connections; the connection is stored in
Open WebUI's database, and its token is encrypted with `WEBUI_SECRET_KEY`.

#### Steps

1. On TrueNAS, display the hub token:

        sudo sed -n 's/^MCP_HUB_TOKEN=//p' /mnt/tank/ai/secrets/web.env

2. In Open WebUI, open **Admin Panel** > **Settings** > **Integrations** and add a connection.

3. Select the type **MCP (Streamable HTTP)**.

4. Enter the URL `http://mcp-hub:8096/servers/<name>/mcp`, where `<name>` is `searxng`, `fetch`
   or `kb`.

5. Select the authentication **Bearer** and enter the hub token as the key.

6. Save the connection, and repeat steps 2 to 5 for each server you want.

#### Results

The hub's tools are available in chats; the model sees them as `<server id>_<tool>`.

!!! caution
    Do not add the hub as a connection of type OpenAPI: the interface can then hang while loading.
    Disable such a connection and add it again as MCP (Streamable HTTP). **Bearer** with an empty
    key also fails, because it sends a bare `Authorization: Bearer` header. If a connection
    reports that it failed to connect while its function name filter list is empty, enter a single
    comma (`,`) in that list.

## Change keys and settings after the first start

The settings that Open WebUI seeded from `web.env` live in its database, so a key change there is
made in the **Admin Panel**, not only in the environment file. Keep the environment files current
as well: Compose refuses to start an app with a missing required value, and a new installation
seeds Open WebUI from `web.env` again.

To generate a new random secret on the workstation in the same form as `tools/secrets.py` (48
letters and digits), run:

```
python3 -c "import secrets, string; print(''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(48)))"
```

### Rotate the LiteLLM key of Open WebUI

#### About this task

`LITELLM_WEBUI_KEY` was seeded into three settings: the model connection, the embedding key and the
reranker key. A new key goes into all three, and then into `web.env`.

#### Steps

1. Create a new key with steps 1 to 3 of
   [Create the virtual key that Open WebUI uses](#create-the-virtual-key-that-open-webui-uses).

2. In Open WebUI, open **Admin Panel** > **Settings** > **Connections**, edit the
   `http://litellm:4000/v1` connection, enter the new key and save.

3. Open **Settings** > **Documents**, enter the new key for the embedding engine and for the
   reranking engine, and click **Save**.

4. Set the new key as `LITELLM_WEBUI_KEY` in `web.env` on the workstation, and copy the file with
   [Copy a changed environment file to TrueNAS](#copy-a-changed-environment-file-to-truenas).

5. Repeat steps 3, 6 and 7 of
   [Check the Open WebUI connections and document settings](#check-the-open-webui-connections-and-document-settings).

6. Delete the old key in LiteLLM. Replace `<old-litellm-webui-key>` with the old key:

        sudo docker exec litellm python3 -c "import json, os, urllib.request as u; \
        body = json.dumps({'keys': ['<old-litellm-webui-key>']}).encode(); \
        req = u.Request('http://127.0.0.1:4000/key/delete', data=body, \
        headers={'Authorization': 'Bearer ' + os.environ['LITELLM_MASTER_KEY'], 'Content-Type': 'application/json'}); \
        print(u.urlopen(req).read().decode())"

7. Check that the old key is refused: run step 3 of
   [Create the virtual key that Open WebUI uses](#create-the-virtual-key-that-open-webui-uses) with
   the old key.

    The command fails with an HTTP error instead of listing the models.

#### Results

Open WebUI uses the new key everywhere, and the old key no longer works.

!!! note
    LiteLLM's `/key/delete` endpoint was not checked against version 1.108.8 for this guide. Step 7
    shows whether the old key was revoked; if it still lists the models, revoke the key in LiteLLM's
    Admin UI at `https://llm.lab.example.com/ui`, where you sign in with the master key.

### Rotate the API keys of the service users

#### Steps

1. Open a private browser window and sign in to Open WebUI as the service user:
   `indexer@lab.example.com` or `kb-reader@lab.example.com`.

2. Open **Settings** > **Account**, and under **API keys** click **Create new secret key**.

3. Set the new key in its file on the workstation: `OIKB_TOKEN` in `rag.env` for `indexer`, or
   `KB_READER_TOKEN` in `web.env` for `kb-reader`.

4. Copy the file with
   [Copy a changed environment file to TrueNAS](#copy-a-changed-environment-file-to-truenas).

5. Redeploy the app that uses the key:

        sudo midclt call -j app.redeploy ai-rag

    For `kb-reader`, redeploy `ai-web` instead.

6. Verify the key: for `indexer`, run steps 1 and 2 of [Follow the oikb sync](#follow-the-oikb-sync);
   for `kb-reader`, run steps 4 to 9 of
   [Verify the MCP hub from the TrueNAS shell](#verify-the-mcp-hub-from-the-truenas-shell).

#### Results

The service uses its new key.

!!! note
    Whether creating a new secret key replaces the previous key of the same user was not checked
    for Open WebUI 0.13.3. After a rotation, open **Settings** > **Account** as that user and confirm
    that only the new key is listed; if the old key is still listed, delete it there.

### Rotate the other RAG and web secrets

Table: Rotating the RAG and web secrets

| Secret | Files | Procedure |
|---|---|---|
| `DOCLING_API_KEY` | `rag.env` and `web.env` (the same value) | Set the new value in both files and copy them; redeploy `ai-rag`; enter the new key for docling in **Admin Panel** > **Settings** > **Documents** and click **Save** |
| `PG_PASSWORD` | `rag.env` and `web.env` (the same value) | Change the database password first (steps below), then set it in both files, copy them, and redeploy `ai-rag`, then `ai-web` |
| `MCP_HUB_TOKEN` | `web.env`, and `client.env` on every workstation (Chapter 7) | Set the new value, copy `web.env`, redeploy `ai-web`; update each workstation and every Open WebUI MCP connection to the hub |
| `SEARXNG_SECRET`, `OIKB_API_KEY` | `web.env`, `rag.env` | Set the new value, copy the file, and redeploy the app |
| `WEBUI_SECRET_KEY` | `web.env` | Never change it: every session ends, and the tokens that Open WebUI stored can no longer be decrypted |

#### Steps

To change the database password:

1. Change the password of the `openwebui` role. Replace `<new-pg-password>` with a new value of
   letters and digits only, because the password goes into a URL:

        sudo docker exec -it pgvector psql -U openwebui -d openwebui -c "ALTER ROLE openwebui PASSWORD '<new-pg-password>'"

    The output is `ALTER ROLE`.

2. Set `PG_PASSWORD=<new-pg-password>` in `rag.env` and in `web.env` on the workstation, and copy
   both files with [Copy a changed environment file to TrueNAS](#copy-a-changed-environment-file-to-truenas).

3. Redeploy both apps:

        sudo midclt call -j app.redeploy ai-rag
        sudo midclt call -j app.redeploy ai-web

4. Check Open WebUI's health endpoint:

        sudo docker exec open-webui curl -s http://127.0.0.1:8080/health

    The output is `{"status":true}`.

#### Results

The database and both apps use the new password. The `POSTGRES_PASSWORD` that `pgvector` receives
from `rag.env` is used only when its data directory is empty, so the `ALTER ROLE` statement is the
change that counts.

### Change a setting that Open WebUI seeded

#### About this task

A setting in the first-start groups of the table in
[Settings that Open WebUI keeps from its first start](#settings-that-open-webui-keeps-from-its-first-start)
changes only in the **Admin Panel**. Editing its variable in `web.env` or in the compose file has
no effect.

#### Steps

1. In Open WebUI, open the **Admin Panel** page that holds the setting: **Settings** >
   **Connections** for models, **Settings** > **Documents** for extraction, embeddings, reranking
   and chunking, **Settings** > **Web Search** for search.

2. Change the value and click **Save**.

3. If you changed the embedding model, click **Reindex Embedding Data** on the **Documents** page.

    Vectors from different embedding models cannot be compared, so the knowledge bases must be
    embedded again. Files that were attached directly to chats keep their old vectors.

#### Results

Open WebUI uses the new setting at once, and keeps it across restarts and redeploys.

### Known limitations of the RAG and web apps

- **Web search depends on public engines.** Result quality follows DuckDuckGo, Brave and the other
  enabled engines; Google and Bing are not queried. Engines that see CAPTCHAs suspend the instance
  for a while.
- **One token for the MCP hub.** The hub's bearer token carries no user identity: every client that
  holds it gets the same tools, and the `kb` tools always act as `kb-reader`.
- **No fetches into the LAN.** Open WebUI's page fetcher and the hub's `fetch` server refuse
  private addresses, and `fetch` honours robots.txt.
- **Document conversion runs on the CPU.** `docling` has two workers and 8 GB of memory; a large
  scanned PDF can take minutes, up to the 600-second limit of a synchronous conversion. Embedding
  and reranking also run on the CPU.
- **Some files are never indexed.** Files over 100 MB and the excluded patterns are skipped; files
  that Open WebUI rejects fail at every sync until they are removed from the share.
- **One address for Open WebUI.** It accepts browsers only at `https://chat.lab.example.com`.
- **No downloads by Open WebUI.** `OFFLINE_MODE=true` stops the update check, Hugging Face
  downloads and the installation of Python packages that plugins request. A plugin whose Python
  requirements are not already in the image does not work.
- **Seeded settings.** After the first start, the settings in the first-start groups change only in
  the **Admin Panel**.
- **The MCP hub image is built locally** until a release publishes it, and a redeploy does not
  rebuild it.
