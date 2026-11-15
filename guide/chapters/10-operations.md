title: Operating and updating the stack

# Operating and updating the stack

This chapter describes how to keep the stack current and healthy after the deployment. You move
the server to a new release of this repository with `tools/deploy.py`, schedule an optional drift
check on TrueNAS, take container image updates, change or add a model, monitor the GPU and the
services, read the logs of each app, and update TrueNAS itself.

Every service runs on the TrueNAS server. The workstation runs only the commands you start:
`tools/deploy.py`, `tools/smoke.py`, `tools/eval.py`, `git` and the coding agent. Nothing in this
chapter installs a timer, a daemon or a container on the workstation; the only scheduled job is an
optional cron job on TrueNAS.

Table: Values used in this chapter

| Value | Meaning |
|---|---|
| `192.0.2.10` | LAN address of the TrueNAS server |
| `lab.example.com` | Your lab domain (`LAB_DOMAIN`) |
| `~/local-agent-stack` | The clone of this repository on the workstation (Chapter 3) |
| `/mnt/tank/ai/stacks/local-agent-stack` | The clone of this repository on TrueNAS (Chapter 3) |
| `<old-tag>`, `<new-tag>` | The release the server runs now and the release you install, for example `v1.0` and `v1.1` |
| `<app>` | One of the TrueNAS apps `ai-inference`, `ai-rag`, `ai-web` and `ai-edge` |
| `<stack>` | The app's folder under `stack/` and the name of its environment file: `inference`, `rag`, `web` or `edge` (for example `stack/inference/` and `inference.env` for `ai-inference`) |

## Releases of the stack

The server always runs a release of this repository, never a branch. Each release is a git tag,
and the TrueNAS clone is checked out at that tag, so the server runs exactly the files the
release's guide describes.

### Release tags and assets

A release is a tag `vX.Y` on `main`, for example `v1.1`. A prerelease for testing is a tag
`vX.Y-beta.N`, for example `v1.1-beta.1`; GitHub marks it as a prerelease and never as the latest
release. `tools/deploy.py` accepts both forms. The release workflow builds every asset from the
tagged commit after it has run all of the repository's checks.

Table: Release assets

| Asset | Contents |
|---|---|
| `local-agent-stack-<version>-deployment-guide.pdf` | This guide, for that release |
| `stack-vX.Y.tar.gz` | The `stack/`, `clients/` and `deploy/` directories at the tag |
| `SHA256SUMS.txt` | The SHA-256 checksums of the PDF and the bundle |

Each PDF and bundle carries a signed build provenance attestation, and the release notes are the
`## Unreleased` section of `CHANGELOG.md` at the time of the release. Use the guide of the release
that you install: the commands and files in it match that release.

### What a release changes

A release can change any file under `stack/`, `clients/` and `deploy/`. How a change reaches the
running stack depends on the file.

Table: How release changes take effect

| Changed file | Effect | How it takes effect |
|---|---|---|
| `stack/<stack>/compose.yaml`, an `image:` line included | New containers or container settings | `deploy.py apply` updates the app, which recreates its containers; the file is part of the app's content hash |
| A configuration file that the compose file mounts: `stack/inference/llama-swap/config.yaml`, `stack/inference/litellm/config.yaml`, `stack/rag/oikb/oikb.yaml`, the files under `stack/web/searxng/`, `stack/edge/Caddyfile` | New service configuration | `deploy.py apply` updates the app; these files are part of the app's content hash |
| `stack/edge/Dockerfile` | A new Caddy image | With the published image, the release also pins the new image in `stack/edge/compose.yaml`, and `apply` updates the app. With the image built on the server, build it again and redeploy `ai-edge` by hand ([Apply the release](#apply-the-release)) |
| The MCP hub files under `stack/web/mcp-hub/` | A new hub image | With the published image, the release also pins the new image in `stack/web/compose.yaml`, and `apply` updates the app. With the image built on the server, build it again and redeploy `ai-web` by hand ([Apply the release](#apply-the-release)); `deploy.py` does not hash build files |
| `stack/<stack>/<stack>.env.example` | New or changed variables | Add the variables to your copy `~/.config/local-agent-stack/secrets/<stack>.env` and to `/mnt/tank/ai/secrets/<stack>.env`; `deploy.py apply` then updates the app, because its environment file changed |
| Seed values of Open WebUI in `stack/web/compose.yaml` | Nothing on an existing installation | Open WebUI keeps these settings in its database after its first start; make the change in the Admin Panel when the release notes say so. `apply` still recreates the `ai-web` containers, because the file changed |
| `clients/` | Workstation configuration | The links that `clients/install.sh` created point into the workstation clone, so they follow its checkout; run `clients/install.sh` again for a new OpenCode or ssh-mcp version |
| `deploy/truenas.toml` | The desired state of the project's own server | Compare it with your desired-state file (see [Create your desired-state file](#create-your-desired-state-file)) |

### Check a release before you install it

#### Prerequisites

The GitHub CLI `gh` is installed and logged in on the workstation (Chapter 8). Without it, download
the assets from the release page on GitHub into `~/releases/<new-tag>` and run steps 3, 5 and 6.

#### About this task

Read what the release changes, check that the assets are the ones the release workflow built, and
list the files that differ from the release the server runs. The list tells you which apps the
update touches, whether the MCP hub image needs a new build, and which environment files need new
variables.

#### Steps

1. Display the release notes:

        gh release view <new-tag> --repo corytron/local-agent-stack

    Read every line. Note each change that asks you to do something, such as a setting in the Open
    WebUI Admin Panel.

2. Download the assets into a new directory:

        mkdir -p ~/releases/<new-tag>
        gh release download <new-tag> --repo corytron/local-agent-stack --dir ~/releases/<new-tag>

3. Verify the checksums:

        cd ~/releases/<new-tag> && sha256sum -c SHA256SUMS.txt

    Every line ends with `OK`.

4. Verify the provenance of the guide and the bundle:

        gh attestation verify ~/releases/<new-tag>/local-agent-stack-*-deployment-guide.pdf --repo corytron/local-agent-stack
        gh attestation verify ~/releases/<new-tag>/stack-<new-tag>.tar.gz --repo corytron/local-agent-stack

    Each command reports that the verification succeeded.

5. Fetch the new tag into the workstation clone and list the changed files:

        git -C ~/local-agent-stack fetch --tags
        git -C ~/local-agent-stack diff --stat <old-tag> <new-tag> -- stack clients deploy

    Each changed directory under `stack/` names an app that the update touches: `stack/inference`
    is `ai-inference`, `stack/rag` is `ai-rag`, `stack/web` is `ai-web` and `stack/edge` is
    `ai-edge`. A changed file under `stack/web/mcp-hub/` means a new MCP hub image, and a changed
    `stack/edge/Dockerfile` a new Caddy image: the release pins each published image in its compose
    file, and an image that you built on the server must be built again.

6. Show the changes to the variables of the apps:

        git -C ~/local-agent-stack diff <old-tag> <new-tag> -- 'stack/*/*.env.example'

    Lines that start with `+` and name a variable are new or changed variables.

#### Results

You know what the release changes, which apps it touches and which variables you must add. Keep the
list for [Updating to a new release](#updating-to-a-new-release).

## Setting up deploy.py

`tools/deploy.py` compares the TrueNAS server with a desired state and makes the server match it.
It runs on the workstation and talks to the TrueNAS API (JSON-RPC over a WebSocket at
`wss://192.0.2.10:8443/api/current`). Set it up once, before the first release update.

### How deploy.py works

The desired state names the release the server runs, the TrueNAS version the tool was checked
against, and the four custom apps. Each app's YAML in TrueNAS is this include wrapper, followed by
two content hashes:

```
include:
  - path: /mnt/tank/ai/stacks/local-agent-stack/stack/<stack>/compose.yaml
    env_file: /mnt/tank/ai/secrets/<stack>.env
services: {}
x-local-agent-stack:
  files: sha256:<64 hex digits>
  env: sha256:<64 hex digits>
```

The first four lines are the file `stack/<stack>/truenas-app.yaml`, which Chapters 4 to 6 paste
into TrueNAS by hand. The Compose Specification lets a file carry top-level keys that start with
`x-` (extension fields), and Compose ignores them, so the `x-local-agent-stack` block changes
nothing in the app; it records what `apply` deployed:

- **`files`** is a SHA-256 checksum over the app's `compose.yaml` and the files under
  `stack/<stack>/` that it mounts: `llama-swap/config.yaml` and `litellm/config.yaml` for
  `ai-inference`, `oikb/oikb.yaml` for `ai-rag`, every file under `searxng/` for `ai-web`, and the
  `Caddyfile` for `ai-edge`. `deploy.py` reads them from the release tag with `git archive`, so
  every machine with the tag computes the same value. The MCP hub's build files are not part of
  it, because a redeploy does not rebuild an image.
- **`env`** is the SHA-256 checksum of the app's environment file: on the workstation, your copy
  `<env_dir>/<stack>.env` (`~/.config/local-agent-stack/secrets/<stack>.env`); with `--local` on
  TrueNAS, the server's file in `/mnt/tank/ai/secrets`. Only the checksum leaves the file; the
  values are never printed or sent.

Compose recreates a container when its definition changes, not when a file it mounts changes. The
hashes make such a change visible: when one differs from the value the app's YAML records, `plan`
reports `update`, and `apply` writes the new YAML, which recreates the app's containers.

!!! note
    The `x-local-agent-stack` block was accepted by `docker compose config` of Compose 5.6.0 on a
    workstation, for both wrapper shapes. The Compose version that TrueNAS 25.10 bundles was not
    tried. TrueNAS checks every custom app's YAML with `docker compose config` before it stores it,
    so if that version refuses the block, the first `apply` that records the hashes fails for every
    app, and each app keeps its previous YAML and its running containers. The setting
    `content_hashes = false` in the desired-state file then makes `deploy.py` write the YAML
    without the block, at the cost of no longer detecting changed files and environment files.
    [Update the apps without content hashes](#update-the-apps-without-content-hashes) describes the
    symptom, the switch and the way back.

An app that runs with compose override files, such as the internal CA of Appendix D or the `coder`
fallback of Chapter 4, lists them in its `overrides` line in the desired-state file. Its `path`
then becomes a list, the release's compose file first, and `apply` keeps the overrides:

```
include:
  - path:
      - /mnt/tank/ai/stacks/local-agent-stack/stack/<stack>/compose.yaml
      - <override file>
    env_file: /mnt/tank/ai/secrets/<stack>.env
services: {}
x-local-agent-stack:
  files: sha256:<64 hex digits>
  env: sha256:<64 hex digits>
```

Table: deploy.py commands

| Command | What it does | Key |
|---|---|---|
| `validate` | Checks the desired-state file and that the stack files it names exist; offline | None |
| `render [--app <app>]` | Prints each app's YAML as `apply` would write it for a new app, with the hashes this machine can compute; offline | None |
| `plan [--app <app>]...` | Shows, per app, what `apply` would do | Read-only |
| `apply [--app <app>]... [--dry-run] [--timeout <seconds>]` | Creates, updates or redeploys the apps, one at a time in the order of the desired-state file, and waits up to 600 seconds (default) for each to run | Full admin |
| `drift [--app <app>]... [--issue]` | Runs `plan` and exits with code 3 when the server differs; `--issue` keeps one GitHub issue labelled `deploy` up to date (needs `gh`) | Read-only |
| `status` | Prints one line per app: state, YAML, files, environment file, images | Read-only |

`--app` can be repeated. The options `--file`, `--config`, `--local` and `--no-hashes` can stand
before or after the command: `deploy.py --local drift` and `deploy.py drift --local` are the same.
If an option is written on both sides, the value after the command wins.

The desired-state file's setting `content_hashes` (default `true`) decides whether `deploy.py`
writes and compares the content hashes. With `content_hashes = false`, `render` and `apply` write
the include wrapper without the `x-local-agent-stack` block, `plan` and `drift` compare only the
YAML and the images and print a note that changed files and environment files are not detected, and
`status` shows `files -` and `env -`. The option `--no-hashes` does the same for one command. Use
the setting and the option only as
[Update the apps without content hashes](#update-the-apps-without-content-hashes) describes.

For each app, `plan` decides one action:

Table: deploy.py plan actions

| Action | When | What apply does |
|---|---|---|
| `create` | The app does not exist | Creates the custom app with the wrapper and its hashes |
| `update` | The stored YAML differs from the wrapper, or one of its content hashes: the release's files of the app or its environment file changed, or no hash is recorded yet. With `content_hashes = false`, also a YAML that still carries the `x-local-agent-stack` block | Replaces the YAML; TrueNAS recreates every container of a running app. A stopped app only gets the new YAML |
| `redeploy` | The YAML and its hashes match, but the app runs images other than the release's, or it is `CRASHED` | Redeploys the app |
| `conflict` | An app of that name exists and is a catalog app | Nothing; reported only |
| `none` | The app is in step | Nothing. A `STOPPED` app is reported and not started, because someone stopped it on purpose |

`deploy.py` never deletes an app. Apps on the server that the desired state does not name are
listed as `unmanaged` and left alone. It computes the `files` hash and the release's images from
`git archive <release>` and `docker compose config --images` on the machine where it runs; for that
it needs `git`, the Docker CLI with the Compose plugin (no Docker daemon) and the release tag in the
local clone ([Install the TrueNAS API client on the workstation](#install-the-truenas-api-client-on-the-workstation)
installs them). Without the tag, the files and images are reported as `not compared`; without
Docker, the images, and `plan` then never sees an image update. The `env` hash is `not compared` when the environment file cannot be read. A hash that
is not compared keeps the value that the server has recorded, so a run from a machine without git or
without the environment files never undoes what another run recorded.

Table: deploy.py exit codes

| Code | Meaning |
|---|---|
| `0` | Done; for `drift`, no drift |
| `1` | A call or an apply step failed |
| `2` | A usage or configuration error, including a server that reports another TrueNAS version than the desired state |
| `3` | Drift found (`drift` only) |

!!! note
    `deploy.py` detects changed images, a changed app YAML, changed files under `stack/<stack>/`
    that the app mounts, and changed environment files (your copy in `env_dir`, or the server's
    file with `--local`). It does not detect override files, files that only an override mounts,
    or the MCP hub's build files. With `content_hashes = false`, it detects only changed images
    and a changed app YAML. Redeploy the app by hand after a change that it does not detect, as in
    [Redeploy one app](#redeploy-one-app).

!!! note
    `deploy.py` compares the images that an app runs with the images of the release's compose
    file, not with an override. With the Caddy image built on the server
    ([Build the Caddy image on TrueNAS](#build-the-caddy-image-on-truenas)), `plan` and `drift`
    therefore always report `ai-edge` with `redeploy (RUNNING) runs images other than <tag>'s`, and
    an `apply` of every app redeploys `ai-edge` (which keeps the local image) and ends with exit code
    `1`, because its final plan still shows the redeploy. While you use the local image, apply and
    check the other apps by name: `apply --app ai-inference --app ai-rag --app ai-web`, and the
    same `--app` options for `drift`. For `ai-edge`, read the `YAML`, `files` and `env` fields of
    `status`.

The tool uses the two API keys from Chapter 3. `plan`, `drift` and `status` log in as `deploy-read`
(Readonly Admin) and never change anything. Only `apply` loads the key of `deploy-apply` (Full
Admin), because TrueNAS 25.10 has no smaller predefined role that can write apps.

### Install the TrueNAS API client on the workstation

#### Prerequisites

- An Ubuntu workstation (`c4dev`) with Python 3.11 or later (`python3 --version`) and `git`
  (`git --version`), which the clone of Chapter 3 already needed. Chapter 2 lists the rest of the
  workstation's software ([Workstation requirements](#workstation-requirements)).
- The key files `~/.config/local-agent-stack/truenas-read.key` and `truenas-apply.key`, from
  [Create the API keys and store them on the workstation](#create-the-api-keys-and-store-them-on-the-workstation).

#### About this task

`deploy.py` uses the official TrueNAS API client at the tag that matches the server,
`TS-25.10.8`. Install it into its own virtual environment, so that it does not touch the system
Python.

`deploy.py` also runs `docker compose config --images` on the workstation to read the release's
images, so the workstation needs the Docker command-line client with the Compose plugin. It needs
no Docker daemon: install only the packages `docker-ce-cli` and `docker-compose-plugin` from
Docker's apt repository, not `docker-ce`, which is the daemon. If `docker compose version` already
works on the workstation, skip steps 1 to 4.

#### Steps

1. Create the directory for Docker's signing key and download the key:

        sudo install -m 0755 -d /etc/apt/keyrings
        sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
        sudo chmod a+r /etc/apt/keyrings/docker.asc

2. Add Docker's apt repository:

        sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
        Types: deb
        URIs: https://download.docker.com/linux/ubuntu
        Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
        Components: stable
        Architectures: $(dpkg --print-architecture)
        Signed-By: /etc/apt/keyrings/docker.asc
        EOF

3. Install the client and the Compose plugin, without the daemon:

        sudo apt update
        sudo apt install docker-ce-cli docker-compose-plugin

4. Verify the Compose plugin:

        docker compose version

    The output starts with `Docker Compose version`. The command works without a Docker daemon.

5. Create the virtual environment:

        python3 -m venv ~/.local/share/local-agent-stack/deploy-venv

    If the command reports that `ensurepip` is not available, install the `python3-venv` package
    with `sudo apt install python3-venv` and repeat the command.

6. Install the client:

        ~/.local/share/local-agent-stack/deploy-venv/bin/pip install 'git+https://github.com/truenas/api_client.git@TS-25.10.8'

7. Verify the installation:

        ~/.local/share/local-agent-stack/deploy-venv/bin/python -c 'import truenas_api_client; print("ok")'

    The output is `ok`.

#### Results

The workstation has the TrueNAS API client, `git` and the Docker client with the Compose plugin.
Run `deploy.py` with this environment's Python, for example
`~/.local/share/local-agent-stack/deploy-venv/bin/python tools/deploy.py status`, from the
workstation clone.

### Create the connection settings

#### About this task

The connection settings file names the API address, the two users and their key files, and the
certificate that the workstation trusts for the TrueNAS web interface. `deploy.py` connects only
over `wss://` and verifies the certificate; TrueNAS revokes an API key that is ever sent over plain
HTTP or `ws://`. The web interface uses its own self-signed certificate by default, so you save that
certificate as `truenas-ca.pem` and compare its fingerprint with the one your browser shows.

#### Steps

1. Save the certificate that the TrueNAS web interface presents:

        echo | openssl s_client -connect 192.0.2.10:8443 2>/dev/null | openssl x509 > ~/.config/local-agent-stack/truenas-ca.pem

2. Display its names and fingerprint:

        openssl x509 -in ~/.config/local-agent-stack/truenas-ca.pem -noout -subject -ext subjectAltName -fingerprint -sha256

3. Open `https://192.0.2.10:8443` in a browser, open the certificate viewer from the address bar,
   and compare the SHA-256 fingerprint with the output of step 2.

    The two fingerprints are identical. If they differ, do not continue: something between the
    workstation and the server presents another certificate.

4. Write the settings file:

        (umask 077; cat > ~/.config/local-agent-stack/truenas.toml <<'EOF'
        uri = "wss://192.0.2.10:8443/api/current"
        read_user = "deploy-read"
        read_key_file = "truenas-read.key"
        apply_user = "deploy-apply"
        apply_key_file = "truenas-apply.key"
        ca_file = "truenas-ca.pem"
        EOF
        )

    The key and certificate file names are relative to the folder of the settings file.

5. Verify the files and their modes:

        ls -l ~/.config/local-agent-stack/

    `truenas.toml`, `truenas-read.key` and `truenas-apply.key` show `-rw-------`. `deploy.py`
    refuses a key file that other users can read or that belongs to another user.

#### Results

The workstation holds the connection settings, the two key files and the server's certificate,
readable only by you. [Check the connection with deploy.py status](#check-the-connection-with-deploypy-status)
tests them.

!!! note
    Whether the default certificate of the TrueNAS web interface names the server's IP address
    was not verified. If `deploy.py` fails with a certificate error that mentions a host name or
    IP address mismatch, see the `deploy.py` rows in the troubleshooting chapter.

### Create your desired-state file

#### About this task

`deploy/truenas.toml` in the repository is the desired state of the project's own server; it
changes through pull requests. Keep your own copy outside the clone, so that checking out a new tag
never conflicts with your edits, and pass it to every command with `--file`. The repository's file
at this release:

{{ include deploy/truenas.toml }}

#### Steps

1. Copy the file from the workstation clone:

        cp ~/local-agent-stack/deploy/truenas.toml ~/.config/local-agent-stack/desired.toml

2. Open `~/.config/local-agent-stack/desired.toml` in a text editor and set `release` to the tag
   that the TrueNAS clone is checked out at (Chapter 3), for example:

        release = "v1.0"

3. Check `truenas_version` against the server's version: `midclt call system.version` in
   **System** > **Shell** prints for example `TrueNAS-25.10.8`, and the file holds `25.10.8`. Keep
   `stacks_dir` and `secrets_dir` unless you placed the clone or the secrets elsewhere.

4. Keep `env_dir`. It names the folder of your copies of the environment files, which Chapter 3
   created; `deploy.py` computes each app's `env` hash from `<env_dir>/<stack>.env`. Without the
   line, the environment files are not compared. Keep `content_hashes = true` as well; set it to
   `false` only as [Update the apps without content hashes](#update-the-apps-without-content-hashes)
   describes.

5. If an app runs with a compose override file, add an `overrides` line to its table, below its
   `stack` line. The guide creates three override files:

    - The `coder` fallback of
      [Apply a fallback when coder does not fit](#apply-a-fallback-when-coder-does-not-fit):

            [apps.ai-inference]
            stack = "inference"
            overrides = ["/mnt/tank/ai/appdata/llama-swap/fallback.override.yaml"]

    - The Caddy image built on the server, of
      [Build the Caddy image on TrueNAS](#build-the-caddy-image-on-truenas):

            [apps.ai-edge]
            stack = "edge"
            overrides = ["/mnt/tank/ai/appdata/caddy/local-image.override.yaml"]

    - The internal CA of Appendix D, of
      [Install the ai-edge app with the internal CA](#install-the-ai-edge-app-with-the-internal-ca):

            [apps.ai-edge]
            stack = "edge"
            overrides = ["/mnt/tank/ai/appdata/caddy/internal-ca.override.yaml"]

    With both edge overrides, one line names both files, in the order of the paths in the app's
    YAML: `overrides = ["/mnt/tank/ai/appdata/caddy/local-image.override.yaml",
    "/mnt/tank/ai/appdata/caddy/internal-ca.override.yaml"]`. Each entry is an absolute path on the
    server, listed once. `apply` then writes the same YAML as the task that created the override,
    followed by the content hashes, and keeps it; `plan` shows `override: <file>` under the app.
    Without the line, `plan` reports `update` for the app, and `apply` would replace its YAML with
    the four lines of `truenas-app.yaml` and drop the override.

6. Validate the file:

        cd ~/local-agent-stack
        python3 tools/deploy.py --file ~/.config/local-agent-stack/desired.toml validate

    The output ends with `ok (4 apps, release v1.0, TrueNAS 25.10.8)`.

#### Results

Your desired-state file names the release and TrueNAS version that the server runs, the four apps
and their override files, and passes `validate`.

### Check the connection with deploy.py status

#### Steps

1. Change to the workstation clone:

        cd ~/local-agent-stack

2. Show the state of the server with the read-only key:

        ~/.local/share/local-agent-stack/deploy-venv/bin/python tools/deploy.py --file ~/.config/local-agent-stack/desired.toml status

    After the installation by hand of Chapters 4 to 6, the output has the following shape:

        TrueNAS 25.10.8; desired release v1.0
        ai-inference: state RUNNING, YAML matches, files not recorded, env not recorded, images match
        ai-rag: state RUNNING, YAML matches, files not recorded, env not recorded, images match
        ai-web: state RUNNING, YAML matches, files not recorded, env not recorded, images match
        ai-edge: state RUNNING, YAML matches, files not recorded, env not recorded, images match

    `not recorded` means that the app's YAML carries no content hashes yet; the next task records
    them. Once they are recorded, each line reads `files match, env match`. An app that is not
    installed yet shows `state -, YAML missing, files -, env -, images -`, and a field that cannot
    be computed on this machine shows `not compared`. With `content_hashes = false`, every app
    shows `files -, env -`. Apps of other projects appear as `<name>: unmanaged`.

3. Show the plan:

        ~/.local/share/local-agent-stack/deploy-venv/bin/python tools/deploy.py --file ~/.config/local-agent-stack/desired.toml plan

    Each installed app shows `update (RUNNING)` with the reasons that no hashes are recorded, as the
    next task describes, and no other reason. An app with `YAML differs` runs another YAML than the
    wrapper, for example an override that your desired-state file does not list yet.

#### Results

The read-only key works, and the server matches the desired state apart from the content hashes.
Nothing on the server has changed.

### Record the content hashes

#### Prerequisites

- [Check the connection with deploy.py status](#check-the-connection-with-deploypy-status) shows
  `YAML matches` for every app.
- No agent or Open WebUI user is working: the task recreates the containers of every app once.

#### About this task

Apps installed by hand from `stack/<stack>/truenas-app.yaml` carry no content hashes. The first
`apply` records them, which recreates every container of each app once
([What a redeploy restarts](#what-a-redeploy-restarts) lists the effect). The `env` hash is
computed from your copies of the environment files, so check first that they are identical to the
files the apps run with on the server. With the Caddy image built on the server, `ai-edge` also
shows `redeploy` in steps 3 to 6, and `apply` ends with exit code `1` and `drift` with
`drift: yes`; the note in [How deploy.py works](#how-deploypy-works) explains why. The other apps
show the results below.

#### Steps

1. On the workstation, display the checksums of your copies:

        sha256sum ~/.config/local-agent-stack/secrets/*.env

2. On TrueNAS, display the checksums of the server's files:

        sudo sha256sum /mnt/tank/ai/secrets/*.env

    Each file has the same checksum on both machines. If one differs, one copy was changed without
    the other. The apps run with the server's file: bring the workstation copy to the values that
    are current, and install it on the server as in
    [Copy the environment files to TrueNAS](#copy-the-environment-files-to-truenas). Then repeat
    steps 1 and 2.

3. On the workstation, show the plan:

        cd ~/local-agent-stack
        ~/.local/share/local-agent-stack/deploy-venv/bin/python tools/deploy.py --file ~/.config/local-agent-stack/desired.toml plan

    Each app shows a line of this shape, followed by a diff that adds the `x-local-agent-stack`
    block:

        ai-inference: update (RUNNING) no hash of the files of stack/inference/ recorded (installed by hand?); no hash of its env file recorded

4. Run the apply as a dry run:

        ~/.local/share/local-agent-stack/deploy-venv/bin/python tools/deploy.py --file ~/.config/local-agent-stack/desired.toml apply --dry-run

    After the plan, each app shows `<app>: update (dry run)`. Nothing is changed.

5. Apply:

        ~/.local/share/local-agent-stack/deploy-venv/bin/python tools/deploy.py --file ~/.config/local-agent-stack/desired.toml apply

    For each app, in the order `ai-inference`, `ai-rag`, `ai-web`, `ai-edge`, the tool prints
    `<app>: update` and, once the app runs again, `<app>: RUNNING`. It ends with `after apply:` and
    a new plan, in which every app shows `none (RUNNING) in step`. The exit code is `0`.

    If every app instead prints `<app>: FAILED: app.update:` followed by a validation error that
    contains `Invalid compose configuration`, TrueNAS refused the `x-local-agent-stack` block.
    Nothing changed on the server; do not repeat the apply, and continue with
    [Update the apps without content hashes](#update-the-apps-without-content-hashes).

6. Check for drift:

        ~/.local/share/local-agent-stack/deploy-venv/bin/python tools/deploy.py --file ~/.config/local-agent-stack/desired.toml drift

    The output ends with `drift: none`.

#### Results

Every app's YAML records the hashes of its files and its environment file, and `status` shows
`files match, env match` for each app. From now on, `plan` reports `update` for an app whose
release files or environment file change.

### Update the apps without content hashes

#### About this task

Use this task only if TrueNAS refused the content hashes in
[Record the content hashes](#record-the-content-hashes). The Compose version that TrueNAS 25.10
bundles was not tested with the `x-local-agent-stack` block. TrueNAS validates a custom app's YAML
with `docker compose config` before it stores the YAML or touches a container (checked in the
TrueNAS middleware source at tag `TS-25.10.8`), so a refused apply leaves every app with the
four-line wrapper of `stack/<stack>/truenas-app.yaml` and its containers running. Until you switch
the hashes off, `plan` reports every app as `update` with the reason
`no hash of the files of stack/<stack>/ recorded`, `apply` fails for each of them in the same way,
and `drift` always reports drift.

The setting `content_hashes = false` in your desired-state file makes `deploy.py` work without the
block:

- `render` and `apply` write exactly the include wrapper: the four lines of
  `stack/<stack>/truenas-app.yaml`, or the list of paths of an app with `overrides`.
- `plan` and `drift` compare the app's YAML and its running images with the release, report the app
  states as before, and print one note under their first line:
  `note: content hashes are off (content_hashes = false or --no-hashes): changes to the release's files and to the env files are not detected; redeploy the apps they touch by hand`.
- `status` shows `files -` and `env -` for every app, and `deploy.py` no longer reads your copies of
  the environment files.

What you lose: `deploy.py` no longer notices a changed file that an app mounts, such as
`llama-swap/config.yaml`, `litellm/config.yaml`, `oikb/oikb.yaml`, the files under `searxng/` or
the `Caddyfile`, nor a changed environment file. A release that changes an `image:` line is still
detected, as `redeploy`, because the running images then differ from the release's. You redeploy
the other changed apps by hand. If an app's YAML still carries the block from an earlier `apply`,
`plan` reports it as `update` with the reason
`its YAML carries an x-local-agent-stack block, which apply removes while content hashes are off`,
and `apply` writes the YAML without the block, which recreates the app's containers once.

#### Steps

1. Confirm that nothing changed on the server:

        cd ~/local-agent-stack
        ~/.local/share/local-agent-stack/deploy-venv/bin/python tools/deploy.py --file ~/.config/local-agent-stack/desired.toml status

    Every app shows `state RUNNING, YAML matches, files not recorded, env not recorded, images match`.
    If an app shows another state, read `/var/log/app_lifecycle.log` on TrueNAS.

2. Report the problem to the project as an issue. Include the TrueNAS version and the `FAILED`
   lines of the apply, with your domain and addresses replaced by the guide's placeholders.

3. Open `~/.config/local-agent-stack/desired.toml` in a text editor, change the `content_hashes`
   line to the following, and save the file:

        content_hashes = false

4. Validate the file:

        python3 tools/deploy.py --file ~/.config/local-agent-stack/desired.toml validate

    The output ends with `ok (4 apps, release v1.0, TrueNAS 25.10.8, content hashes off)`.

5. If you copied your desired-state file to TrueNAS for the drift cron job
   ([Check that deploy.py runs on TrueNAS](#check-that-deploypy-runs-on-truenas)), copy it again:

        scp ~/.config/local-agent-stack/desired.toml truenas_admin@192.0.2.10:/mnt/tank/ai/stacks/desired.toml

6. Check for drift:

        ~/.local/share/local-agent-stack/deploy-venv/bin/python tools/deploy.py --file ~/.config/local-agent-stack/desired.toml drift

    The second line of the output is the note that content hashes are off. Every app shows
    `none (RUNNING) in step`, and the output ends with `drift: none`. With the Caddy image built on
    the server, add `--app ai-inference --app ai-rag --app ai-web` after `drift`, as the note in
    [How deploy.py works](#how-deploypy-works) explains.

7. Display the status:

        ~/.local/share/local-agent-stack/deploy-venv/bin/python tools/deploy.py --file ~/.config/local-agent-stack/desired.toml status

    Every app shows `state RUNNING, YAML matches, files -, env -, images match`.

#### Results

`deploy.py` manages the apps with the include wrapper alone: `plan`, `apply`, `drift`, `status` and
the drift cron job work, and compare the YAML, the images and the app states. Changes of the
release's files and of the environment files reach the server only through a redeploy by hand.

#### Next steps

While `content_hashes = false` is set, operate the stack as follows:

- For each release update, follow [Updating to a new release](#updating-to-a-new-release). In
  [Apply the release](#apply-the-release), `plan` shows `redeploy` only for the apps whose images
  changed, and `apply` redeploys them. Then redeploy by hand, as in step 5 of that task, every other
  app whose folder under `stack/` changed (step 5 of
  [Check a release before you install it](#check-a-release-before-you-install-it)) and every other
  app whose environment file you changed. A redeploy reads the compose file, the mounted files and
  the environment file again.
- After you change an environment file outside a release update, for example when you rotate a
  secret, redeploy its app as in [Redeploy one app](#redeploy-one-app), unless the task that you
  follow ends with that redeploy. An app reads the new values only at its next redeploy.
- When a release of this project or of TrueNAS resolves the issue of step 2, turn the hashes back
  on with [Turn the content hashes back on](#turn-the-content-hashes-back-on).

### Turn the content hashes back on

#### Prerequisites

- `deploy.py drift` reports `drift: none` with `content_hashes = false`.
- No agent or Open WebUI user is working: the task recreates the containers of every app once.

#### About this task

The first `apply` with the hashes on records them in every app's YAML, which recreates every
container of each app once. If TrueNAS still refuses the block, every app reports `FAILED` and keeps
its YAML and its running containers, as in the first attempt, and you switch the hashes off again.

#### Steps

1. Open `~/.config/local-agent-stack/desired.toml` in a text editor, change the `content_hashes`
   line to the following, and save the file:

        content_hashes = true

2. Validate the file:

        cd ~/local-agent-stack
        python3 tools/deploy.py --file ~/.config/local-agent-stack/desired.toml validate

    The output ends with `ok (4 apps, release v1.0, TrueNAS 25.10.8)`, without
    `content hashes off`.

3. Record the hashes: follow [Record the content hashes](#record-the-content-hashes) from step 1.

    If every app prints `<app>: FAILED: app.update:` with `Invalid compose configuration`,
    TrueNAS still refuses the block: set `content_hashes = false` again and repeat steps 4 to 7 of
    [Update the apps without content hashes](#update-the-apps-without-content-hashes).

4. If you copied your desired-state file to TrueNAS for the drift cron job, copy it again:

        scp ~/.config/local-agent-stack/desired.toml truenas_admin@192.0.2.10:/mnt/tank/ai/stacks/desired.toml

5. Display the status:

        ~/.local/share/local-agent-stack/deploy-venv/bin/python tools/deploy.py --file ~/.config/local-agent-stack/desired.toml status

    Every app shows `files match, env match`.

#### Results

Every app's YAML records the hashes of its files and its environment file again, and `plan` reports
`update` for an app whose release files or environment file change.

## Updating to a new release

A release update moves both clones to the new tag, adds new variables to the environment files,
lets `deploy.py apply` update the apps whose files, environment files or images changed, and
verifies the result. Plan for a few minutes of interruption per app;
[What a redeploy restarts](#what-a-redeploy-restarts) lists the effect of each app.

Before the first update, record the content hashes as in
[Record the content hashes](#record-the-content-hashes): `status` shows `files match, env match`
for every app. Without them, `apply` cannot tell which apps the release changes, and updates every
app. If TrueNAS refused the hashes and your desired-state file sets `content_hashes = false`, follow
the changes that the next steps of
[Update the apps without content hashes](#update-the-apps-without-content-hashes) list.

### Prepare for a release update

#### Prerequisites

You ran [Check a release before you install it](#check-a-release-before-you-install-it) for the
new tag.

#### Steps

1. Stop the coding agents and tell the users of Open WebUI that the stack will restart.

2. Download the TrueNAS configuration file, as in
   [Back up the TrueNAS configuration](#back-up-the-truenas-configuration).

3. In **System** > **Shell** on TrueNAS, dump both databases to the dump directory of Appendix A
   (if it does not exist yet, create it as in
   [Create the dump directory and the first dumps](#create-the-dump-directory-and-the-first-dumps)):

        sudo -v
        sudo docker exec litellm-db pg_dump -U litellm -d litellm -Fc | sudo tee /mnt/tank/ai/appdata/pg-dumps/litellm-db.dump > /dev/null
        sudo docker exec pgvector pg_dump -U openwebui -d openwebui -Fc | sudo tee /mnt/tank/ai/appdata/pg-dumps/pgvector.dump > /dev/null

4. Take a manual snapshot of the service data and the secrets:

        sudo zfs snapshot -r tank/ai/appdata@before-<new-tag>
        sudo zfs snapshot tank/ai/secrets@before-<new-tag>

5. Verify the snapshots:

        sudo zfs list -t snapshot -o name | grep before-<new-tag>

    The list shows `tank/ai/appdata` and each of its children, and `tank/ai/secrets`.

#### Results

You can return to the current state with
[Roll back a release update](#roll-back-a-release-update).

### Update the clones

#### Steps

1. On TrueNAS, as `truenas_admin` (without `sudo`), check that the clone has no local changes:

        git -C /mnt/tank/ai/stacks/local-agent-stack status --porcelain

    The output is empty. If it lists files, someone edited the clone; the checkout in step 3 can
    fail or carry the edits along. Save any edit you need elsewhere, then discard them with
    `git -C /mnt/tank/ai/stacks/local-agent-stack checkout -- .`.

2. Fetch the new tag:

        git -C /mnt/tank/ai/stacks/local-agent-stack fetch --tags

3. Check out the new tag:

        git -C /mnt/tank/ai/stacks/local-agent-stack checkout <new-tag>

    Git reports a detached HEAD at the tag. This is expected.

4. Verify the checkout:

        git -C /mnt/tank/ai/stacks/local-agent-stack describe --tags --exact-match

    The output is `<new-tag>`.

5. On the workstation, check out the same tag:

        git -C ~/local-agent-stack status --porcelain
        git -C ~/local-agent-stack checkout <new-tag>

    The first command prints nothing, or only `?? evals/results/` and `?? evals/baselines/`: your
    evaluation results of Chapter 9, which the checkout keeps. After the checkout, the OpenCode
    configuration that `clients/install.sh` linked into the clone is the new release's.

6. Set `release` in `~/.config/local-agent-stack/desired.toml` to `<new-tag>`, and compare the file
   with the release's desired state:

        diff ~/local-agent-stack/deploy/truenas.toml ~/.config/local-agent-stack/desired.toml

    Apart from `release` and the lines you changed on purpose (`overrides` lines and a changed
    `env_dir`), the files are the same. Take over any other difference, for example a new app or a
    new setting.

7. If you created the drift cron job of
   [Scheduled drift checks on TrueNAS](#scheduled-drift-checks-on-truenas), copy the file to the
   server as well:

        scp ~/.config/local-agent-stack/desired.toml truenas_admin@192.0.2.10:/mnt/tank/ai/stacks/desired.toml

8. If an app runs with an override, refresh its copy so that it follows the new release: repeat
   [Create the internal CA Caddyfile](#create-the-internal-ca-caddyfile) for the internal CA of
   Appendix D, and steps 2 and 3 of
   [Apply a fallback when coder does not fit](#apply-a-fallback-when-coder-does-not-fit) for the
   `coder` fallback. `deploy.py` does not detect a changed copy; note the app for a redeploy by
   hand in [Apply the release](#apply-the-release). The local Caddy image of
   [Build the Caddy image on TrueNAS](#build-the-caddy-image-on-truenas) needs a new build only when
   the release changed `stack/edge/Dockerfile`; step 1 of [Apply the release](#apply-the-release)
   covers it.

#### Results

Both clones are at `<new-tag>`, your desired-state file names it, and the override copies follow
the new release. The apps still run the old release until
[Apply the release](#apply-the-release).

### Add new variables to the secrets files

#### About this task

Each compose file stops an app with an error that names the variable when a required variable is
missing. Add every new variable from step 6 of
[Check a release before you install it](#check-a-release-before-you-install-it) before you apply
the release. Never run `tools/secrets.py gen` for an existing file: it creates new values for every
secret, and `LITELLM_SALT_KEY` and `WEBUI_SECRET_KEY` must never change.

The environment files are named after the app's folder, `<stack>.env`: `inference.env` for
`ai-inference`, `rag.env`, `web.env` and `edge.env`. Change your workstation copy and install it on
the server before you run `apply`: `apply` records the checksum of your copy, and the containers read
the server's file.

#### Steps

1. For a new variable that the release notes describe as generated, create one value. The stack's
   generated values are 48 letters and digits; keys that LiteLLM or llama-swap check start with
   `sk-`:

        python3 -c 'import secrets, string; a = string.ascii_letters + string.digits; print("".join(secrets.choice(a) for _ in range(48)))'

    For a variable that you provide, use the value the release notes or the example file describe.

2. Add the line `<VARIABLE>=<value>` to `~/.config/local-agent-stack/secrets/<stack>.env` on the
   workstation with a text editor.

3. Copy the file to the server:

        scp ~/.config/local-agent-stack/secrets/<stack>.env truenas_admin@192.0.2.10:

4. On TrueNAS, install it and delete the copy:

        sudo install -m 0600 -o root -g root ~/<stack>.env /mnt/tank/ai/secrets/
        rm ~/<stack>.env

5. Verify the variable on the server:

        sudo grep -c '^<VARIABLE>=' /mnt/tank/ai/secrets/<stack>.env

    The output is `1`.

6. Verify that the server's file and your copy are identical: compare the output of
   `sudo sha256sum /mnt/tank/ai/secrets/<stack>.env` on TrueNAS with that of
   `sha256sum ~/.config/local-agent-stack/secrets/<stack>.env` on the workstation.

    The two checksums are the same.

#### Results

The environment files hold every variable of the new release. `deploy.py plan` shows
`its env file differs from the one hashed at the last apply` for each app whose file changed, and
the next task applies it.

### Apply the release

#### About this task

`apply` updates every app whose release files or environment file changed, and redeploys every app
whose running images differ from the release's. It works one app at a time, in the order of the
desired-state file (`ai-inference`, `ai-rag`, `ai-web`, `ai-edge`), and waits until each app runs
before it moves to the next. A new published image reaches the server this way too: the release
pins it in the compose file, which changes the app's `files` hash. Some changes remain manual,
because `deploy.py` does not detect them: a new build of an image that you build on the server, and
an override copy that you refreshed in [Update the clones](#update-the-clones). With the local Caddy image, name the other apps with
`--app` in steps 2 to 4 (see the note in [How deploy.py works](#how-deploypy-works)). With
`content_hashes = false`, `apply` redeploys only the apps whose images changed, and step 5 covers
every other app that the release or your environment files changed.

#### Steps

1. If you build an image on the server instead of pulling the published one, and the release
   changed its files, build it again first: the MCP hub image as in
   [Build or pull the MCP hub image](#build-or-pull-the-mcp-hub-image) when files under
   `stack/web/mcp-hub/` changed, and the Caddy image as in steps 1 to 3 of
   [Build the Caddy image on TrueNAS](#build-the-caddy-image-on-truenas) when
   `stack/edge/Dockerfile` changed. With the published images, skip this step.

2. On the workstation, change to the clone and show the plan:

        cd ~/local-agent-stack
        ~/.local/share/local-agent-stack/deploy-venv/bin/python tools/deploy.py --file ~/.config/local-agent-stack/desired.toml plan

    Apps whose release files changed show
    `update (RUNNING) the files of stack/<stack>/ in <new-tag> differ from the last apply`, and apps
    whose environment file you changed show `its env file differs from the one hashed at the last
    apply`; each is followed by a diff of the hashes. A change of an `image:` line shows as a
    change of the files, because `compose.yaml` is one of them. The other apps show
    `none (RUNNING) in step`.

3. Run the apply as a dry run:

        ~/.local/share/local-agent-stack/deploy-venv/bin/python tools/deploy.py --file ~/.config/local-agent-stack/desired.toml apply --dry-run

    After the plan, each app to change shows `<app>: <action> (dry run)`. Nothing is changed.

4. Apply the release:

        ~/.local/share/local-agent-stack/deploy-venv/bin/python tools/deploy.py --file ~/.config/local-agent-stack/desired.toml apply

    For each app it changes, the tool prints the action and then `RUNNING`. It ends with
    `after apply:` and a new plan, in which every app shows `none`. The exit code is `0`.

5. Redeploy by hand each app that `apply` did not change and that needs it: `ai-web` after a new
   hub image built in step 1, `ai-edge` after a new local Caddy image, and an app whose override
   copy you refreshed. With `content_hashes = false`, also every app whose folder under `stack/`
   changed (step 5 of
   [Check a release before you install it](#check-a-release-before-you-install-it)) or whose
   environment file you changed. Do one app at a time, in the order `ai-inference`, `ai-rag`,
   `ai-web`, `ai-edge`:

        sudo midclt call -j app.redeploy <app>

    From the workstation, the same command runs over SSH with a terminal for the `sudo` prompt:
    `ssh -t truenas_admin@192.0.2.10 'sudo midclt call -j app.redeploy <app>'`.

6. After each redeploy, wait until the app's containers are healthy before you redeploy the next
   app:

        sudo docker ps --format '{{.Names}} {{.Status}}'

    Every container shows `Up` and `(healthy)`, except `gpu-exporter`, which has no health check
    and shows `Up`.

#### Results

The server runs the new release, and every app's YAML records the hashes of the release's files and
of its environment file.

### Update the workstation clients

#### Steps

1. If the release changed `clients/install.sh`, preview and run it again from the workstation
   clone:

        cd ~/local-agent-stack
        clients/install.sh --dry-run
        clients/install.sh

    The script changes only what differs and keeps any file of yours it replaces as
    `<name>.bak.<time>`.

2. Open a new terminal and check the OpenCode version:

        opencode --version

    The output is the version that the release notes name.

3. Compare your SSH tool policy with the release's example, and carry any new setting over by
   hand; the installer never replaces your copy:

        diff ~/.config/ssh-mcp/config.toml ~/local-agent-stack/clients/ssh-mcp/config.example.toml

    On macOS, the policy is `~/Library/Application Support/ssh-mcp/config.toml`.

4. Repeat steps 1 to 3 on every other machine that runs the clients, such as the Mac.
   [Update OpenCode and the SSH tool](#update-opencode-and-the-ssh-tool) describes the same task
   for one workstation.

#### Results

Every workstation runs the OpenCode version and client files of the new release, and its SSH tool
policy carries the release's new settings.

### Verify the release update

#### Steps

1. Check the state of the server:

        cd ~/local-agent-stack
        ~/.local/share/local-agent-stack/deploy-venv/bin/python tools/deploy.py --file ~/.config/local-agent-stack/desired.toml drift

    The output ends with `drift: none`, and the exit code (`echo $?`) is `0`. With the Caddy
    image built on the server, add `--app ai-inference --app ai-rag --app ai-web` after `drift`.

2. Run the end-to-end checks:

        python3 tools/smoke.py

    The last line starts with `smoke: 8 passed, 0 failed`.

3. Do any Admin Panel change that the release notes ask for.

#### Results

The server and the workstation run the new release. Keep the `before-<new-tag>` snapshots until
you are sure that you will not roll back, then delete them:

```
sudo zfs destroy -r tank/ai/appdata@before-<new-tag>
sudo zfs destroy tank/ai/secrets@before-<new-tag>
```

### Roll back a release update

#### About this task

A rollback returns the clones and the apps to the previous release. LiteLLM and Open WebUI can
change their database schemas when a newer version starts, and an older version may not run on the
changed schema. If the update replaced the LiteLLM, PostgreSQL, Open WebUI or pgvector image, also
roll back the database datasets to the snapshot of
[Prepare for a release update](#prepare-for-a-release-update).

!!! caution
    Rolling back a database dataset discards every change made since the snapshot: new keys, usage
    logs, chats and documents indexed after the update.

#### Steps

1. Check out `<old-tag>` in the TrueNAS clone and in the workstation clone, as in
   [Update the clones](#update-the-clones), and set `release` in your desired-state file back to
   `<old-tag>`.

2. If you added variables to a secrets file, you can leave them in place; the old release ignores
   them.

3. If the database datasets must go back, stop the apps that use them in **Apps** > **Installed**:
   `ai-inference` for `tank/ai/appdata/litellm-db`, and `ai-web` and `ai-rag` for
   `tank/ai/appdata/pgvector`. Then roll back each dataset to the snapshot `before-<new-tag>`, as in
   [Roll back a service dataset](#roll-back-a-service-dataset), which ends with starting the apps
   again.

4. Check that every app of the stack runs. `deploy.py apply` does not start a stopped app.

5. Run `deploy.py plan` and `deploy.py apply` as in [Apply the release](#apply-the-release).
   `apply` updates every app whose files differ between the two tags, which includes the images
   that the old tag pins. If you build an image on the server and the update built a new one, build
   it again from the old tag's files first (step 1 of that task), and redeploy its app by hand if
   `apply` did not update it.

6. Run the verification of [Verify the release update](#verify-the-release-update).

#### Results

The clones and the apps run `<old-tag>` again, and the databases hold the state of the snapshot if
you rolled them back. Delete the `before-<new-tag>` snapshots once you no longer need them, as in
[Verify the release update](#verify-the-release-update).

## Scheduled drift checks on TrueNAS

`deploy.py drift` is an on-demand command: run it by hand, or let an agent run it, and after every
apply. If you want a scheduled check, run it as a TrueNAS cron job on the server. Nothing of the
stack is scheduled on a workstation.

On TrueNAS, `deploy.py --local` talks to the local middleware socket as `root`, so it needs no API
key and no certificate. It reads the environment files in `/mnt/tank/ai/secrets` for the `env`
hashes and ignores `env_dir`; with `content_hashes = false` it reads none of them. If your workstation copies differ from the server's files, the check
reports the app as drifted, with the note
`if apply ran from another machine, its copy of the env file differs from the one read here`: keep
both copies identical, as [Add new variables to the secrets files](#add-new-variables-to-the-secrets-files)
does. With the Caddy image built on the server, the check always reports `ai-edge`, because it
compares the running image with the release's compose file and not with the override; in that case
add `--app ai-inference --app ai-rag --app ai-web` after `drift` in the cron command below.

### Check that deploy.py runs on TrueNAS

#### About this task

`--local` needs the Python of the TrueNAS base system to import `truenas_api_client`, the library
that `midclt` uses, and Python 3.11 or later. This was not verified on TrueNAS 25.10.8; the steps
check it.

#### Steps

1. In **System** > **Shell**, check the Python version:

        python3 --version

    The version is 3.11 or later.

2. Check the API client:

        sudo python3 -c 'import truenas_api_client; print("ok")'

    The output is `ok`. If the import fails, scheduled drift checks on TrueNAS are not possible;
    run `deploy.py drift` from the workstation instead.

3. If you have not copied your desired-state file to the server yet, copy it from the workstation:

        scp ~/.config/local-agent-stack/desired.toml truenas_admin@192.0.2.10:/mnt/tank/ai/stacks/desired.toml

4. Run the status command once by hand:

        sudo python3 /mnt/tank/ai/stacks/local-agent-stack/tools/deploy.py --local --file /mnt/tank/ai/stacks/desired.toml status

    The output has the same shape as on the workstation. If the files and images show
    `not compared`, git did not read the clone; the cron job in the next task passes git a setting
    for that.

#### Results

`deploy.py --local` reads the apps through the local middleware, without a key. If step 2 failed,
keep the drift checks on the workstation and skip the next task.

### Create the drift cron job

#### About this task

The job runs `deploy.py --local drift` once a day and prints the report only when the check finds
drift or fails. A TrueNAS cron job runs its command with `sh -c` as the selected user.

Git refuses to work in a repository that belongs to another user unless the directory is listed in
its `safe.directory` setting. The clone belongs to `truenas_admin` and the job runs as `root`, so
the command passes that setting to git in its environment. Without it, `deploy.py` reports the
files and images as not compared and checks only the YAML, the environment files and the app
states.

#### Steps

1. Go to **System** > **Advanced Settings**.

2. On the **Cron Jobs** card, click **Add**.

3. Enter **Description** `deploy.py drift`.

4. Enter the following **Command** on one line:

        out=$(env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0=/mnt/tank/ai/stacks/local-agent-stack python3 /mnt/tank/ai/stacks/local-agent-stack/tools/deploy.py --local --file /mnt/tank/ai/stacks/desired.toml drift 2>&1) || echo "$out" >&2

5. Set **Run As User** to `root`.

6. In **Schedule**, select **Custom**, set **Minutes** to `0` and **Hours** to `6`, and click
   **Done**.

7. Keep **Hide Standard Output** selected, clear **Hide Standard Error**, and keep **Enabled**
   selected.

8. Click **Save**.

9. To test the command without waiting for 06:00, open a root shell with `sudo -i` in **System** >
   **Shell**, paste the command, and leave the root shell with `exit`.

    The command prints nothing when the server matches the desired state.

#### Results

The job checks the server every morning at 06:00. When the server differs from the desired state,
or the check fails, the report goes to standard error, which TrueNAS reports because **Hide Standard
Error** is cleared.

!!! note
    That TrueNAS mails the output of a cron job was assumed, not verified. Check that the server's
    email settings deliver mail to you, then test the job while one app is stopped. The `--issue`
    option of `drift`, which keeps a GitHub issue, needs `gh` and does not work on TrueNAS.

## Updating container images

The compose files pin every image by tag and digest, the stack's own Caddy and MCP hub images
included. Image updates reach the server only through a release of this repository: they arrive in
`main` as pull requests, and a release carries them to the server with
[Updating to a new release](#updating-to-a-new-release). An update notice in the TrueNAS **Apps**
screen does not change what an app runs, because the digest stays the same.

The exception is an image that you build on the server instead of pulling the published one: the
Caddy image of [Build the Caddy image on TrueNAS](#build-the-caddy-image-on-truenas), or the MCP hub
image when you build it as in [Build or pull the MCP hub image](#build-or-pull-the-mcp-hub-image).
Such an image changes only when you build it again, which
[Apply the release](#apply-the-release) does when a release changes its files.

### How image updates arrive

Renovate, configured by `renovate.json` in the repository, opens a pull request for each new image
version in a compose file or a Dockerfile under `stack/`. The Renovate app must be installed on the
repository (or on your fork) for this to happen.

Table: Renovate rules of the stack

| Rule | Effect |
|---|---|
| `config:best-practices` | Every image is written as `tag@sha256:digest`; Renovate updates tag and digest together |
| `minimumReleaseAge: 7 days` | A version is proposed only when it is a week old, so that a compromised release has time to be withdrawn |
| Labels | Each pull request carries `dependencies` and `stack` |
| Dependency Dashboard | One issue lists every pending update |
| llama.cpp and llama-swap tags | Compared by build number within the `cuda` variant; never switched to another variant |
| CUDA newer than 13.0 | Tags that name such a version are never proposed |
| PostgreSQL and pgvector major versions | Proposed only after you approve them on the Dependency Dashboard; they need a dump and a restore |

GitHub Actions and the Python check tools are updated by Dependabot, not Renovate.

To pin an image by hand, for example a new image in a compose file, read the digest of its tag
and write both into the `image:` line as `<image>:<tag>@sha256:<digest>`:

```
docker buildx imagetools inspect <image>:<tag>
```

The `Digest:` line of the output is the digest of the tag. For an image with several platforms it
is the index digest, which covers all of them.

{{ include renovate.json }}

### The CUDA 13.0 rule

The NVIDIA driver of TrueNAS 25.10.6 to 25.10.8, 580.173.02, supports CUDA 13.0 and older. An
image built on a newer CUDA version does not start: the NVIDIA container runtime compares the
image's `NVIDIA_REQUIRE_CUDA` value with the driver and refuses the container. The rule applies to
`llama-swap`, the only image of the stack built on a CUDA base. Its tags (`v273-cuda-b12407`) do
not name the CUDA version, so check every update by hand. Never use llama.cpp `server-cuda13`
images or llama-swap `unified-cuda13` images; they require CUDA 13.5 and 13.3.

### Review an image update pull request

#### About this task

Check each image update before you merge it. The example checks a llama-swap update; the same
inspection works for any image.

#### Steps

1. Read the image's release notes, linked in the pull request, for breaking changes and new
   settings.

2. In **System** > **Shell** on TrueNAS, pull the proposed image by the reference in the pull
   request:

        sudo docker pull <image>:<tag>@sha256:<digest>

3. Display its CUDA requirement:

        sudo docker image inspect --format '{{range .Config.Env}}{{println .}}{{end}}' <image>:<tag>@sha256:<digest> | grep NVIDIA_REQUIRE_CUDA

    The value starts with `cuda>=`. The version after it must be 13.0 or lower; the current image
    shows `NVIDIA_REQUIRE_CUDA=cuda>=12.8`. Images that print nothing are not built on CUDA.

4. For a LiteLLM update, check that the pull request keeps the digest pin. Never use LiteLLM's
   floating tags (`latest`, `main-latest`, `main-stable`): LiteLLM was compromised twice in 2026, in
   March through its Python packages, and in October through its Python packages and the Docker
   images `v1.107.0`, `latest`, `main-latest` and `main-stable`.

5. For a PostgreSQL or pgvector major version, do not merge the pull request alone: the data
   directory of a new major version is not compatible. Plan a dump with `pg_dump` and a restore
   into the new version (Appendix A shows the commands).

6. For a llama-swap update, optionally measure the proposed image before you merge it. `--oneoff`
   runs the benchmark in a throwaway container of the image given with `--image`, with the model
   files mounted from the server; it first unloads the GPU model of the running `llama-swap`, so
   run it while no client works. From the TrueNAS clone:

        cd /mnt/tank/ai/stacks/local-agent-stack
        sudo bash tools/bench.sh --oneoff --image <image>:<tag>@sha256:<digest> \
          -m Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf -c 0,16384,32768 -u 512 -r 5

    Compare the table with your baseline as in
    [Compare a new run with the baseline](#compare-a-new-run-with-the-baseline). The quality of the
    answers is checked only after a release deploys the image, by the evaluation gate
    ([Run the regression check](#run-the-regression-check)).

7. Let the checks of the pull request pass, merge it, and remove the image you pulled if you do not
   keep it:

        sudo docker image rm <image>:<tag>@sha256:<digest>

#### Results

The update is in `main` and reaches the server with the next release.

!!! note
    The stack's own images are built by the repository's workflows when their files change on
    `main`: `ghcr.io/corytron/local-agent-stack-caddy` from `stack/edge/Dockerfile` by **Caddy
    image**, tagged with the Caddy version, and `ghcr.io/corytron/local-agent-stack-mcp-hub` from
    `stack/web/mcp-hub/` by **MCP hub image**, tagged with the mcp-proxy version. A Renovate update
    of a base image in one of these Dockerfiles therefore produces a new image. Pin it through a
    pull request, with the `image:` line that the workflow run's summary prints
    (`<image>:<version>@sha256:<digest>`), in `stack/edge/compose.yaml` or `stack/web/compose.yaml`.
    GitHub creates a new container package as private: make it public once, in the package's
    **Package settings** > **Danger Zone** > **Change visibility** > **Public**, so that TrueNAS can
    pull it without credentials.

### What a redeploy restarts

`app.redeploy` stops every container of the app and creates it again (`docker compose down`, then
`up --force-recreate`). Every container of the app restarts, even if only one changed. That is why
the stack is split into four apps, and why you redeploy one app at a time. The `update` of
`deploy.py apply` has the same effect: TrueNAS stores the new YAML and recreates every container of
a running app (`up --force-recreate --remove-orphans`).

Table: Effect of a redeploy

| App | Containers | Effect while it restarts |
|---|---|---|
| `ai-inference` | `llama-swap`, `litellm`, `litellm-db` | Running requests fail. The models are unloaded; `llama-swap` loads `embed`, `rerank` and `coder` again at start, and `coder` takes a minute or more. Agents and Open WebUI get errors until `litellm` is healthy |
| `ai-rag` | `pgvector`, `docling`, `oikb` | Open WebUI loses its database for the restart and reconnects by itself. Document uploads and the sync pause; `docling` can take up to three minutes to become ready |
| `ai-web` | `open-webui`, `searxng`, `mcp-hub` | The web GUI, web search and the MCP tools are unavailable. Signed-in sessions stay valid, because `WEBUI_SECRET_KEY` does not change |
| `ai-edge` | `caddy`, `gpu-exporter` | Every host name is unreachable for the restart. Certificates stay in `/mnt/tank/ai/appdata/caddy/data` and are not requested again |

### Redeploy one app

#### About this task

`deploy.py apply` updates an app whenever its release files, its environment file or its images
change. Redeploy an app by hand for the changes that `deploy.py` does not detect: a changed override
file or override copy, an image that you rebuilt on the server, a branch deployed for testing and,
with `content_hashes = false`, changed release files and environment files.

#### Steps

1. In **System** > **Shell** on TrueNAS, redeploy the app:

        sudo midclt call -j app.redeploy <app>

    The command waits for the job and prints its result.

2. Wait until every container of the app is healthy:

        sudo docker ps --format '{{.Names}} {{.Status}}'

    The app's containers show `Up` and `(healthy)`; `gpu-exporter` shows `Up`.

3. If a container stays unhealthy or restarts, read its log as in
   [Read the logs of a container](#read-the-logs-of-a-container).

#### Results

The app's containers run again with the current compose file, mounted files, environment file and
images.

## Changing or adding a model

A model change touches several files of the inference app and every client that names models, so
make it as a feature through a pull request (Chapter 8): measure the model, add it to llama-swap and
LiteLLM, let it pass the evaluation gate, and deploy it with a release. Clients address only the
LiteLLM names, so a model can be replaced behind an existing name without any client change.

### Before you change a model

The 16 GB card holds one generating model. A model fits when its weights, its KV cache at the
planned context, a compute buffer of about 0.7 GiB and any draft model stay below the memory that
remains after the CUDA context, about 15.5 GiB on a headless card (assumed). The current `coder`
model needs about 14.3 GiB at 64K by that count (an estimate). Two kinds of figures appear in this
guide: estimates count only the model's own allocations, as above; measurements, such as the
**GPU MiB used / total** column of `tools/bench.sh --mode server` and the memory that `nvidia-smi`
reports, count everything on the card, the CUDA context included. Compare a measurement with the
card's total, not with 15.5 GiB. Appendix B lists the models that suit this server, the ones to
avoid on two memory channels, and their sizes.

Keep these rules for any new model:

- Run it with `--jinja`, so that llama.cpp parses its tool calls.
- Keep the KV cache at `q8_0` or larger (`-ctk q8_0 -ctv q8_0`); smaller types harm tool calling.
- Treat the chat template as part of the model: if you replace it with `--chat-template-file`, pin
  the template file in the repository and test it like a new model.
- Declare the real context everywhere: llama-swap `-c`, LiteLLM `max_input_tokens`, OpenCode
  `limit.context`, and Claude Code `CLAUDE_CODE_MAX_CONTEXT_TOKENS`.

### Download a model file

#### About this task

Model files live in `/mnt/tank/ai/models/gguf/` on TrueNAS. The `llama-swap` container mounts the
dataset read-only, so the download runs in a throwaway container from the same image, which has
`curl`, with the directory mounted writable. The repositories of the stack's models are public and
need no Hugging Face account.

#### Steps

1. In **System** > **Shell**, check the free space of the models dataset:

        sudo zfs list -o name,used,avail tank/ai/models

    `avail` must exceed the file size listed on the model's Hugging Face page.

2. Read the image reference of the running `llama-swap` container:

        IMG=$(sudo docker inspect --format '{{.Config.Image}}' llama-swap)
        echo "$IMG"

    The output is the pinned image, `ghcr.io/mostlygeek/llama-swap:...@sha256:...`.

3. Download the file to a temporary name. Replace `<repo>` with the Hugging Face repository (for
   example `unsloth/Qwen3.6-35B-A3B-GGUF`), `<revision>` with the commit of the repository that you
   tested (or `main` for the newest), and `<file>` with the file name. `-C -` continues a partial
   file if you run the command again:

        sudo docker run --rm -e NVIDIA_VISIBLE_DEVICES=void --entrypoint curl -v /mnt/tank/ai/models/gguf:/gguf "$IMG" -fL --retry 5 -C - -o /gguf/<file>.part https://huggingface.co/<repo>/resolve/<revision>/<file>

    `curl` shows its progress and ends without an error message.

4. Give the file its final name:

        sudo mv /mnt/tank/ai/models/gguf/<file>.part /mnt/tank/ai/models/gguf/<file>

5. Compare the file's SHA-256 checksum with the value that Hugging Face publishes for that file and
   revision:

        sha256sum /mnt/tank/ai/models/gguf/<file>

    The two values are identical. If they differ, delete the file and download it again.

#### Results

The model file is in `/mnt/tank/ai/models/gguf/` under its final name, with the checksum that
Hugging Face publishes.

### Measure the model with bench.sh

#### Prerequisites

- No agent or Open WebUI user is using the stack. The benchmark needs the GPU to itself; a request
  that arrives during the run makes `llama-swap` load a model next to the benchmark.
- The model file is in `/mnt/tank/ai/models/gguf/`.

#### About this task

`tools/bench.sh` runs on TrueNAS inside the running `llama-swap` container, so it measures the
production build. It first asks `llama-swap` to unload `coder` and `coder-moe`; `llama-swap` loads
them again on the next request. The `server` mode starts one `llama-server` per context and batch
size, records whether it starts, how much GPU memory it holds, and the prompt and generation speed
of one request that fills 75% of the context. The `bench` mode runs `llama-bench` for prompt and
generation speed at several context depths.

Chapter 4 lists the main options ([How bench.sh works](#how-benchsh-works)). The following options
change where and how the benchmark runs; `tools/bench.sh --help` lists them all.

Table: Further options of bench.sh

| Option | Meaning |
|---|---|
| `-p`, `--prompt N` | `bench`: prompt tokens per prompt-processing test; default 2048 |
| `--container NAME` | The running container to use; default `llama-swap` |
| `--oneoff` | Run in a throwaway container of `--image` instead of the running container; also works while `ai-inference` is stopped |
| `--image REF` | The image for `--oneoff`; default the llama-swap image that the release pins |
| `--models-dir DIR` | The host directory mounted at `/models` for `--oneoff`; default `/mnt/tank/ai/models` |
| `--port N` | `server`: the loopback port of the test server inside the container; default 18080 |
| `--timeout SEC` | `server`: seconds to wait for a test server to start; default 600 |
| `DOCKER` (environment) | The Docker command; default `docker` |
| `AI_ROOT` (environment) | The root of the stack's datasets, which sets the default of `--models-dir` (`<AI_ROOT>/models`); default `/mnt/tank/ai` |

#### Steps

1. Change to the TrueNAS clone:

        cd /mnt/tank/ai/stacks/local-agent-stack

2. Measure whether the model fits and how fast it serves, with the flags you plan to use after `--`:

        sudo tools/bench.sh --mode server -m <file> -c 32768,65536 -u 512,1024 -- -ngl 99 -fa on -ctk q8_0 -ctv q8_0

    The script prints a Markdown table with the columns `context (-c)`, `-ub`, `starts`,
    `GPU MiB used / total`, `prompt t/s`, `generation t/s` and `draft accepted`. A row with
    `starts` `no` did not fit; the script prints the last lines of its log.

3. Measure prompt and generation speed at several depths:

        sudo tools/bench.sh -m <file> -c 0,16384,32768 -u 512,1024

4. Run steps 2 and 3 with the current model file and its flags from
   `stack/inference/llama-swap/config.yaml`, so that you compare like with like.

5. Save the tables in the pull request of the change.

#### Results

You know the largest context that fits with headroom, the best batch size, and the speeds of the new
model against the current one.

!!! note
    `tools/bench.sh` had not been run on the server when this guide was written; only its dry run
    (`--dry-run`), which prints the Docker commands, was tested. Add `--dry-run` to check a command
    before you run it.

### Add the model to llama-swap and LiteLLM

#### About this task

A model needs an entry in `stack/inference/llama-swap/config.yaml`, which starts it, and an entry in
`stack/inference/litellm/config.yaml`, which gives clients a name for it. Make both changes in a
branch.

#### Steps

1. In `stack/inference/llama-swap/config.yaml`, add an entry under `models:`. Use the `coder-moe`
   entry as the pattern: a new id, `${server}` followed by the model file under `${gguf}` and the
   flags you measured, and `ttl: 0`:

    {{ include stack/inference/llama-swap/config.yaml lines=125-140 }}

2. Add the id to a routing group. A GPU model joins the `llm` group, which keeps one GPU model
   loaded at a time; a CPU-only model with `--device none` and `CUDA_VISIBLE_DEVICES=-1` joins the
   persistent `rag` group:

    {{ include stack/inference/llama-swap/config.yaml lines=178-194 }}

3. In `stack/inference/litellm/config.yaml`, add a client-facing name under `model_list`. An
   OpenAI-format name routes to `openai/<id>` at `http://llama-swap:8080/v1`; an Anthropic-format
   name for Claude Code routes to `anthropic/<id>` at `http://llama-swap:8080`. Set
   `max_input_tokens` to the context and, for a GPU model, `cost_per_second` to `0.0001`, which turns
   key budgets into GPU-time quotas:

    {{ include stack/inference/litellm/config.yaml lines=81-88 }}

    To replace the model behind an existing name, change only the `model:` line of that name.

4. If the model replaces the default `coder`, also update the `preload` list at the end of the
   llama-swap file, which loads the models when the container starts.

5. Run the repository checks:

        tools/check.sh

    Every check reports `ok`.

#### Results

The branch starts the model in llama-swap and gives it a client-facing name in LiteLLM. Nothing
reaches the server until you deploy the branch in
[Pass the evaluation gate](#pass-the-evaluation-gate).

### Make the model available to clients

#### Steps

1. Allow the new name in each LiteLLM key that should use it. Each key carries a list of allowed
   names, and LiteLLM lists only those to the key's client. For a workstation key, delete the key by
   its alias as shown at the end of [Verify a LiteLLM key](#verify-a-litellm-key), create it again
   with the new name added to `models` as in
   [Generate the workstation keys](#generate-the-workstation-keys), and put the new key into the
   workstation's `client.env` as `LOCAL_LLM_KEY`.

2. For Open WebUI, which lists exactly the names its key allows, replace its key as in
   [Rotate the LiteLLM key of Open WebUI](#rotate-the-litellm-key-of-open-webui), with the new name
   added to the key's `models` list.

3. For OpenCode, add the name to the `local` provider in `clients/opencode/opencode.jsonc` with its
   real `limit.context` and `limit.output`, in the same branch.

4. Verify a key's names as in [Verify a LiteLLM key](#verify-a-litellm-key): the list includes the
   new name.

#### Results

Every client that should use the model has a key that allows its name, and OpenCode declares it
with its real limits.

### Pass the evaluation gate

#### Prerequisites

- An evaluation baseline of the model that the change replaces, recorded at the release the server
  runs ([Record an evaluation baseline](#record-an-evaluation-baseline)), for example
  `evals/baselines/local-coder-full.json`.
- The change is committed to a branch, which is checked out in the workstation clone and pushed to
  GitHub (Chapter 8).

#### About this task

A model change is merged only when it does not make the stack worse at what it is used for. The
gate combines the benchmark, the end-to-end checks, the regression gate of `tools/eval.py compare`
([Compare a change with the baseline](#compare-a-change-with-the-baseline)) and a tool-calling
session, run against the branch deployed on the server. It is the regression check of Chapter 9
([Run the regression check](#run-the-regression-check)) applied to a model change.

#### Steps

1. Deploy the branch for testing: check out the branch in the TrueNAS clone, then redeploy
   `ai-inference`. Replace `<owner>` with the GitHub account that holds the branch (your fork, or
   `corytron`):

        git -C /mnt/tank/ai/stacks/local-agent-stack fetch https://github.com/<owner>/local-agent-stack.git <branch>
        git -C /mnt/tank/ai/stacks/local-agent-stack checkout --detach FETCH_HEAD
        sudo midclt call -j app.redeploy ai-inference

2. On the workstation, check that the clone holds the same branch:

        git -C ~/local-agent-stack branch --show-current

    The output is `<branch>`. The evaluation takes its configuration checksum from the files of this
    clone, so they must be the files that the server now runs.

3. From the workstation, run the end-to-end checks:

        python3 tools/smoke.py

    The last line starts with `smoke: 8 passed, 0 failed`.

4. Run the full evaluation set against the changed configuration and compare it with the baseline:

        cd ~/local-agent-stack
        python3 tools/eval.py run --suite full --baseline evals/baselines/local-coder-full.json

    The output ends with the comparison; the `config:` line names the changed files, and the last
    line reads `gate: pass`. For a model under a new name, add `--model <name>` (and
    `--anthropic-model <name>` for its Anthropic-format name, if it has one) and compare with the
    baseline of the model it replaces; `compare` notes the different model. For a failed case, see
    [Act on failed evaluation cases](#act-on-failed-evaluation-cases).

5. Run a real agent task with tool calls for about 30 minutes, then search the `llama-swap` log for
   full prompt re-processing:

        sudo docker logs --since 30m llama-swap 2>&1 | grep -c 'Forcing full prompt re-processing'

    A count that grows with every turn means that the model or the harness rewrites the history.
    Also watch the session for tool calls written into the reasoning text instead of being executed,
    and for the same tool call repeated with the same arguments.

6. Return the TrueNAS clone to the release tag and redeploy:

        git -C /mnt/tank/ai/stacks/local-agent-stack checkout <old-tag>
        sudo midclt call -j app.redeploy ai-inference

7. Commit the new results file from `evals/results/` to the branch, and write the benchmark tables,
   the smoke summary, the `compare` output and the session's outcome into the pull request.

#### Results

Merge the change when the speeds are acceptable, the smoke checks pass, `compare` prints
`gate: pass` or the pull request and the change's `CHANGELOG.md` line accept the regression with
the issue number, and the session shows none of the failure signs. The change reaches the server
with the next release; after you install it, record a new baseline
([Record an evaluation baseline](#record-an-evaluation-baseline)).

!!! note
    While the TrueNAS clone is on a branch, `deploy.py plan` compares the server with the release in
    your desired-state file and may show `redeploy` for `ai-inference`. Do not run `deploy.py apply`
    until the clone is back on the release tag.

### Change the embedding or reranker model

#### About this task

The embedding model decides the vectors in the document index, so a new `local-embed` model needs a
new index. A reranker change needs no reindex. Keep each reranker input (the query plus one
document) within the reranker's `-ub`, which is 4,096 tokens in the stack; longer inputs fail.

#### Steps

1. Before you change `local-embed`, check the new model's vector size: keep it at 1,536 dimensions
   or fewer, the default maximum of the pgvector index (`PGVECTOR_INITIALIZE_MAX_VECTOR_LENGTH`).
   `Qwen3-Embedding-0.6B` produces 1,024.
2. After the release with the new embedding model is deployed, reindex in Open WebUI:
   **Admin Panel** > **Settings** > **Documents**, **Reindex Embedding Data**. Files attached
   directly to chats keep their old vectors.
3. Check the query prefix in **Documents**. Open WebUI sends the model card's instruction prefix
   with every query (`RAG_EMBEDDING_QUERY_PREFIX`, seeded on the first start, then changed in
   **Documents**); a new model can need another prefix or none.
4. Verify retrieval as in [Test retrieval over your documents](#test-retrieval-over-your-documents).

#### Results

The document index holds vectors of the new embedding model, and retrieval finds the planted test
document.

!!! note
    The Open WebUI field labels in this chapter were read from the source of v0.13.3; the captions
    of the Admin Panel tabs (such as **Documents**) were not checked in a running instance.

### Remove a model

#### Steps

1. In a branch, delete the model's entry and its group membership from the llama-swap file, its
   names from the LiteLLM file and the OpenCode entry, and release the change.
2. Remove the name from the virtual keys that allow it, as in
   [Make the model available to clients](#make-the-model-available-to-clients).
3. After the release that removes it is deployed, delete the file on TrueNAS:

        sudo rm /mnt/tank/ai/models/gguf/<file>

4. Verify that no key lists the name any more, as in [Verify a LiteLLM key](#verify-a-litellm-key).

#### Results

No configuration, key or client names the model, and its file is gone from the models dataset.

## Monitoring the stack

TrueNAS 25.10 has no GPU graphs. Monitor the GPU with `nvidia-smi` and the `gpu-exporter`
metrics, the model server through `llama-swap`, the gateway through LiteLLM, and the rest through the
container health checks.

### Check container health

#### Steps

1. In **System** > **Shell**, list the containers and their health:

        sudo docker ps --format '{{.Names}} {{.Status}}'

    The eleven containers of the stack show `Up`; every container except `gpu-exporter` also shows
    `(healthy)`. A container that shows `(unhealthy)` or `Restarting` needs attention.

2. Show the memory use of the containers against their limits:

        sudo docker stats --no-stream

    `llama-swap` has a limit of 32 GiB, `litellm` 6 GiB, `litellm-db` 2 GiB and `docling` 8 GiB. A
    process that exceeds its container's limit is killed, and the container restarts.

3. From the workstation, check the server with `deploy.py status` and run `python3 tools/smoke.py`.

#### Results

You know which containers are unhealthy or close to their memory limit, and whether the stack
answers end to end.

### Monitor the GPU with nvidia-smi

#### Steps

1. Display the GPU state and its processes:

        nvidia-smi

    While `coder` is loaded, one `llama-server` process holds most of the memory. The CPU-only
    models `embed` and `rerank` are not meant to appear in the process list.

2. Watch utilization, memory, power and temperature every five seconds:

        nvidia-smi --query-gpu=utilization.gpu,memory.used,power.draw,temperature.gpu --format=csv -l 5

    Press **Ctrl+C** to stop.

3. Alternatively, watch a compact rolling view:

        nvidia-smi dmon

4. Check persistence mode and the power limit after a restart:

        nvidia-smi -q | grep -i 'persistence mode'
        nvidia-smi --query-gpu=power.limit,power.default_limit --format=csv

    Persistence mode reads `Enabled`, and `power.limit` is the limit you set in Chapter 3.

#### Results

You know the GPU's load, memory, power and temperature, and that the settings of Chapter 3 are in
effect.

### Read the gpu-exporter metrics

The `gpu-exporter` container serves Prometheus metrics for the GPU on port 9835 of `ai-net` only.
It has no shell and no HTTP client, so read it from another container on `ai-net`:

```
sudo docker exec open-webui curl -s http://gpu-exporter:9835/metrics | grep -m3 nvidia_smi_
```

The output shows metric lines that start with `nvidia_smi_`. A Prometheus server that scrapes this
address must join `ai-net`; the stack does not include one.

### Monitor the model server

#### Steps

1. List the loaded models. The shell inside the container reads the key from the container's
   environment, and its built-in `printf` passes it to `curl` on standard input, so the key never
   appears in a command line or the process list:

        sudo docker exec llama-swap sh -c 'printf "Authorization: Bearer %s\n" "$LLAMA_SWAP_API_KEY" |
          curl -fsS -H @- http://127.0.0.1:8080/running'

    The output lists `coder`, `embed` and `rerank` with the state `ready`, or `coder-moe` instead of
    `coder` while a client uses the fast profile.

2. Check that `llama-swap` uses the processor's AVX-512 and AMX kernels for the CPU models: search
   its log for the CPU backend line.

        sudo docker logs llama-swap 2>&1 | grep -i -m3 -e sapphirerapids -e AMX_INT8

    The output names the `sapphirerapids` backend and shows `AMX_INT8 = 1`. After a long run, the
    start-up lines can have rotated out of the log; they appear again after the next redeploy.

3. Read the Prometheus metrics of the `coder` process:

        sudo docker exec llama-swap sh -c 'printf "Authorization: Bearer %s\n" "$LLAMA_SWAP_API_KEY" |
          curl -fsS -H @- http://127.0.0.1:8080/upstream/coder/metrics' | grep -m10 '^llamacpp:'

    The lines include the requests in progress and the token counters of `llama-server`.

#### Results

You know which models are loaded, that the CPU models use the AMX kernels, and the load of the
`coder` process.

!!! note
    `llama-swap` also has a web UI at `https://models.lab.example.com`, which requires its API key.
    How a browser presents the key to it, and the metrics path `/upstream/<id>/metrics`, were not
    verified; use the commands above when the UI does not open.

### Monitor the gateway

LiteLLM writes one spend log row per request, with the key, the model, the token counts and the
duration, but not the prompt or the answer. Read them in the Admin UI at
`https://llm.lab.example.com/ui`. Each GPU model costs a notional 0.0001 per second of request time,
so a key's spend is its GPU time: a budget of 50 allows 500,000 GPU-seconds.

Check the readiness of the gateway and its database:

```
sudo docker exec litellm python3 -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:4000/health/readiness').read().decode())"
```

The answer contains `"status":"healthy"` and `"db":"connected"`.

Read the gateway's Prometheus metrics with the master key. The key is passed to `curl` on standard
input, so it never appears in a command line or the process list:

```
K=$(sudo sed -n 's/^LITELLM_MASTER_KEY=//p' /mnt/tank/ai/secrets/inference.env)
printf 'Authorization: Bearer %s\n' "$K" |
  sudo docker exec -i llama-swap curl -sS -H @- http://litellm:4000/metrics | grep -m10 -i '^litellm'
unset K
```

!!! caution
    Never call `GET /health` on LiteLLM without a model: it sends a real request to every model,
    which loads `coder-moe` and swaps `coder` out of the GPU. Use `/health/liveliness` and
    `/health/readiness`, or `/health?model=local-coder` for one model.

!!! note
    The Admin UI signs in with the master key. Its menu labels are not described in this guide.

### Monitor Open WebUI and the knowledge sync

- **Users.** **Admin Panel** > **Users** lists the accounts and their roles.
- **Documents.** **Workspace** > **Knowledge** shows the files of each knowledge base.
- **Sync.** `oikb` reports each source with its last sync, the file counts and the last error:

        sudo docker exec oikb python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/health').read().decode())"

    `oikb` syncs every 15 minutes and uploads only added or changed files.

### Monitor the certificates

Caddy renews the wildcard certificate 30 days before it expires. The `tls` check of
`tools/smoke.py` prints the days left for each host name and fails below seven days:

```
python3 tools/smoke.py --only tls
```

On TrueNAS, `sudo docker logs caddy 2>&1 | grep -i 'certificate obtained'` shows each issuance and
renewal.

## Logs per app

Every container has a fixed name, so its log is available with `docker logs <container>` whatever
TrueNAS calls the compose project. The same logs are in the web interface under **Apps** >
**Installed** > *app* > **Workloads** > **View Logs**.

### Where the logs are

Table: Logs per app

| App | Container | What its log shows |
|---|---|---|
| `ai-inference` | `llama-swap` | Model loads and unloads, and the output of each `llama-server`: the CPU backend line, out-of-memory errors, "Forcing full prompt re-processing" |
| `ai-inference` | `litellm` | Requests, key and budget errors, errors from the upstream model |
| `ai-inference` | `litellm-db` | PostgreSQL start-up and authentication errors |
| `ai-rag` | `pgvector` | PostgreSQL start-up, permission and authentication errors |
| `ai-rag` | `docling` | Document conversions and time-outs |
| `ai-rag` | `oikb` | Each sync run, in JSON |
| `ai-web` | `open-webui` | Sign-ins, model and tool connections, document processing |
| `ai-web` | `searxng` | Engine errors and engines suspended after a CAPTCHA |
| `ai-web` | `mcp-hub` | Start of the `searxng`, `fetch` and `kb` servers, and servers that failed |
| `ai-edge` | `caddy` | Certificate issuance and renewal, TLS and proxy errors |
| `ai-edge` | `gpu-exporter` | Start-up and NVML errors |

Errors that stop an app before any container starts, such as a missing variable or a YAML error,
are in the TrueNAS app lifecycle log, `/var/log/app_lifecycle.log`.

The inference, RAG and web apps keep at most five log files of 10 MB per container. The edge app's
compose file sets no log options, so the Docker daemon's defaults apply to its two containers.

### Read the logs of a container

#### Steps

1. Show the last 200 lines of a container's log:

        sudo docker logs --tail 200 <container>

2. Show the last 30 minutes, or follow the log as it grows (press **Ctrl+C** to stop):

        sudo docker logs --since 30m <container>
        sudo docker logs -f <container>

3. Search a log; `docker logs` writes the container's standard error too, so redirect it:

        sudo docker logs llama-swap 2>&1 | grep -i 'out of memory'

4. Show the app lifecycle log of TrueNAS:

        sudo tail -n 100 /var/log/app_lifecycle.log

#### Results

You have the log lines of the failing container or app, which the tables of the troubleshooting
chapter match to their causes ([Troubleshooting deployment issues](#troubleshooting-deployment-issues)).

## TrueNAS updates

TrueNAS updates replace the operating system image. The stack keeps all of its state on the pool and
all of its TrueNAS settings in the configuration database, so it is designed to survive updates; the
checks below confirm it after each one.

### What survives a TrueNAS update

Table: State across a TrueNAS update

| Item | Survives | Where it lives |
|---|---|---|
| Datasets, models, service data, secrets, the clone | Yes | The pool |
| Container images, app definitions, the `ai-net` network | Yes (the network is expected to; check it) | The hidden `ix-apps` dataset on the pool |
| **Install NVIDIA Drivers**, the ARC tunable, the Post Init command, cron jobs, shares, users, API keys, data protection tasks | Yes (expected for the tunable and the Post Init command; check them) | The configuration database, which updates migrate |
| Packages installed with `apt`, edits under `/etc` or `/usr`, a replaced `nvidia.raw`, hand-written systemd units or iptables rules | No | The read-only operating system image |

The NVIDIA driver and the Docker version come with the release. A new driver branch can change the
newest CUDA version that containers may use; a Docker major version can change how compose files
behave.

### Update TrueNAS within 25.10

#### About this task

`deploy.py` refuses to work with a server that reports another version than `truenas_version` in
the desired-state file, so that every change of the server's version, a maintenance release of
25.10 included, is reviewed against the API before the tool uses it again.

#### Steps

1. Read the release notes of the new TrueNAS version. Note the NVIDIA driver version and the Docker
   version it ships.

2. Download the configuration file, as in
   [Back up the TrueNAS configuration](#back-up-the-truenas-configuration).

3. Take a manual snapshot of the stack's data:

        sudo zfs snapshot -r tank/ai/appdata@before-truenas-update
        sudo zfs snapshot tank/ai/secrets@before-truenas-update

4. Go to **System** > **Update** and install the update. The server restarts.

5. Run [Check the stack after a TrueNAS update](#check-the-stack-after-a-truenas-update).

6. Set `truenas_version` in `~/.config/local-agent-stack/desired.toml` (and in
   `/mnt/tank/ai/stacks/desired.toml`, if you use the drift cron job) to the new version, after you
   checked the release notes for API changes, and run `deploy.py status`.

#### Results

The server runs the new version, and `deploy.py` accepts it.

!!! note
    TrueNAS keeps the previous system as a boot environment, listed under **System** > **Boot**.
    The steps to activate an older boot environment were not verified for this guide.

### Check the stack after a TrueNAS update

#### Steps

1. Check the driver and its CUDA version:

        nvidia-smi

    The header shows the driver of the new release and `CUDA Version: 13.0` or later. If the CUDA
    version is lower than 12.8, the `llama-swap` image cannot start; stay on or return to the
    previous release.

2. Check that the Apps service has the driver enabled:

        midclt call docker.config

    The output contains `"nvidia": true`.

3. Check the ARC cap:

        cat /sys/module/zfs/parameters/zfs_arc_max

    The output is the value you set in Chapter 3, for example `12884901888`.

4. Check persistence mode:

        nvidia-smi -q | grep -i 'persistence mode'

    The line reads `Enabled`.

5. Check the shared network:

        sudo docker network ls --filter name=ai-net

    The output has one row, `ai-net`. If it is missing, the apps fail to start: create it again with
    `sudo docker network create ai-net` and start the apps in **Apps** > **Installed**.

6. Check the containers:

        sudo docker ps --format '{{.Names}} {{.Status}}'

    Every container of the stack is `Up` and, except `gpu-exporter`, `(healthy)`.

7. From the workstation, run `python3 tools/smoke.py`. The last line starts with
   `smoke: 8 passed, 0 failed`.

#### Results

The driver, the Apps service, the ARC cap, persistence mode, the shared network and every
container came through the update, and the stack answers end to end.

### Moving to TrueNAS 27

TrueNAS 27 (announced earlier as 26) was in testing when this guide was written; 27.0 was planned
for early December 2026. Stay on 25.10 and plan the move after 27.0.1, the first maintenance
release of 27.0.

Before you move:

- **Update within 25.10 first.** The supported path is from the latest 25.10 release to 27.0.
- **Check the CUDA version of the driver.** 27-RC.1 ships the same driver, 580.173.02 (CUDA 13.0),
  but the 26 betas shipped 590.44.01. Read the release notes of the 27 build you install, and check
  that the CUDA requirement of every GPU image (see [The CUDA 13.0 rule](#the-cuda-130-rule)) is at
  or below the driver's CUDA version.
- **Docker 29.** 27 ships Docker 29.0.4 instead of 28.3.1. Test the compose files on it before you
  rely on the server.
- **The REST API is removed.** Only the JSON-RPC API (`midclt` and `wss://.../api/current`) remains.
  `deploy.py` already uses JSON-RPC, but any script of your own that calls `/api/v2.0` stops working.
- **deploy.py needs a review.** `deploy.py` refuses the new version until `truenas_version` changes,
  and it was written against the 25.10 API and the `TS-25.10.8` client. The 27 client adds SCRAM
  login, so that the key is never sent, and key files for `midclt`. Update the client tag, check the
  API calls that `deploy.py` makes (`auth.login_ex`, `system.info`, `app.query`, `app.config`,
  `app.create`, `app.update`, `app.redeploy`) against the 27 API, and change `truenas_version`
  through a reviewed change.

After the move, run [Check the stack after a TrueNAS update](#check-the-stack-after-a-truenas-update).
