title: Configuring the coding agent

# Configuring the coding agent

This chapter installs and configures the coding agent on the workstation `c4dev`: OpenCode 2.3.0
against the LiteLLM gateway, the four agents and four commands that reproduce the Claude Code
working style, the guard plugin, the shared MCP tools on the hub, and the SSH tool for remote
hosts. It then runs a first session, describes how the Mac and the Windows VM use the agent, and
configures Claude Code itself as a second, unsupported path to the same gateway.

Every service of the stack runs as a container on TrueNAS. A workstation runs only the programs
you start: the OpenCode or Claude Code command, a browser, and the stdio MCP children that the
command starts for one session and stops with it. The installer adds no service, timer or daemon,
and it turns off OpenCode's shared background service, so nothing of the stack keeps running on a
workstation after you exit the agent.

Table: Values used in this chapter

| Value | Meaning |
|---|---|
| `192.0.2.10` | LAN address of the TrueNAS server |
| `192.0.2.20` | LAN address of the workstation `c4dev` |
| `192.0.2.30` | A lab VM that the SSH tool may reach (the example host of the SSH policy) |
| `lab.example.com` | Your domain (`LAB_DOMAIN`); the gateway is `https://llm.lab.example.com` |
| `~/local-agent-stack` | The clone of this repository on the workstation, at the release tag (Chapter 3) |
| `<release-tag>` | The release of this guide, for example `v1.0` |
| `<mac-lan-ip>` | LAN address of the Mac, if the Mac runs its own SSH tool |
| `sk-local-...` | A LiteLLM virtual key; the real value comes from Chapter 4 |

## Workstation components

### What runs on a workstation

Table: Workstation components

| Component | Version | Runs | Purpose |
|---|---|---|---|
| OpenCode CLI (`opencode`) | 2.3.0 | Only while you use it; each command runs its own server and stops it on exit | The coding agent |
| `ssh-mcp` | 2.26.0 | As a stdio child of OpenCode, for one session, only in projects that enable it | The SSH tool for remote hosts |
| `ssh-mcp-stdio` | Release file | Started by OpenCode | Starts `ssh-mcp` with strict host keys and a tamper-evident audit log |
| `claude-local` | Release file | Only while you use it | Runs Claude Code against the gateway for one session |
| `client.env` | Your file | Read by the shell profile, `claude-local` and Claude Code's key helper | The domain, the LiteLLM key and the MCP hub token |

The search, fetch and knowledge-base tools are not installed on the workstation. They run on the
MCP hub in the `ai-web` app on TrueNAS, and OpenCode reaches them over HTTPS at
`https://mcp.lab.example.com`.

### Files the installer places

`clients/install.sh` links the configuration files to the clone instead of copying them, so the
clone must stay where it is. Files that you must edit are copied once and never overwritten.

Table: Files installed on the workstation

| Repository file | What it is | Installed as |
|---|---|---|
| `clients/opencode/opencode.jsonc` | Provider `local`, models, limits, policies, permissions, MCP servers | Link `~/.config/opencode/opencode.jsonc` |
| `clients/opencode/agents/*.md` | `coordinator` (default), `researcher`, `builder`, `reviewer` | Links in `~/.config/opencode/agents/` |
| `clients/opencode/commands/*.md` | `/plan`, `/issue`, `/pr`, `/check` | Links in `~/.config/opencode/commands/` |
| `clients/opencode/plugins/guard.ts` | Refuses pushes to main, secrets in files, wiping commands | Link `~/.config/opencode/plugins/guard.ts` |
| `clients/ssh-mcp/config.example.toml` | Deny-by-default SSH policy with one example host | Copied once to `~/.config/ssh-mcp/config.toml` (macOS: `~/Library/Application Support/ssh-mcp/config.toml`), mode 600 |
| `clients/ssh-mcp/ssh-mcp-stdio` | How OpenCode starts `ssh-mcp` | Link `~/.local/bin/ssh-mcp-stdio` |
| `clients/claude-code/claude-local` | Runs `claude --settings ...` for one session | Link `~/.local/bin/claude-local` |
| `clients/claude-code/settings.json` | Claude Code settings for the gateway | Read by `claude-local` from the clone |
| `clients/templates/AGENTS.md`, `clients/templates/CLAUDE.md` | Project memory for a new repository | Not installed; copied by hand (Chapter 8) |

Appendix E prints every one of these files in full.

### Supported workstations

Table: Supported workstations

| Workstation | Supported path | Notes |
|---|---|---|
| `c4dev` (Ubuntu) | `clients/install.sh` | The reference workstation. Everything in this chapter is written for it |
| Mac | `clients/install.sh` (macOS path), or `ssh` into `c4dev` | The macOS path of the installer has not been run on a Mac |
| Windows VM | `ssh` into `c4dev`; a browser for Open WebUI | `install.sh` supports Linux and macOS only |

## Install the workstation prerequisites

A workstation needs a few command-line tools besides the agent. None of them runs in the
background: the Docker command-line tools in particular are installed without Docker Engine.

### Software the workstation needs

Table: Software on the workstation

| Software | Needed for | Check |
|---|---|---|
| `git`, `curl`, `tar`, `openssl` | The clone, `install.sh` and the certificate checks | `git --version` |
| Python 3.11 or later | `tools/secrets.py` (Chapter 3 and this chapter), `smoke.py` and `eval.py` (Chapter 9), `deploy.py` (Chapter 10) | `python3 --version` |
| Node.js 20.6 or later, with npm | The SSH tool (`ssh-mcp`), and Claude Code if you install it with npm | `node --version` |
| Docker CLI with the Compose plugin, without Docker Engine | `deploy.py` (Chapter 10), which compares the images that the apps run with those of the release by running `docker compose config --images` on the workstation | `docker compose version` |
| GitHub CLI (`gh`) | The project workflow (Chapter 8) and the optional provenance checks of the images (Chapters 5 and 6) | `gh --version` |

On Ubuntu, install any of the first four that is missing with `sudo apt install git curl openssl`;
the `python3` of Ubuntu 24.04 and 26.04 is recent enough. On macOS, if `python3 --version` reports
a version below 3.11, install a current one with Homebrew (`brew install python`). Chapter 8
installs `gh`.

### Install Node.js and npm

#### About this task

The SSH tool needs Node.js 20.6 or later and npm; `install.sh` skips it otherwise. Ubuntu's own
`nodejs` package is Node.js 22.22.1 on Ubuntu 26.04, which is enough, and Node.js 18.19.1 on
Ubuntu 24.04, which is too old (packages.ubuntu.com, checked on 15 November 2026). On Ubuntu 24.04,
install Node.js 22 from NodeSource's repository instead, as NodeSource documents it.

#### Steps

1. Check what is installed:

        node --version
        npm --version

    If the first line is `v20.6.0` or later and the second prints a version, skip this task.

2. On Ubuntu 26.04, install the archive's packages:

        sudo apt install nodejs npm

3. On Ubuntu 24.04, download NodeSource's setup script for Node.js 22, read it, run it, and install
   the package. The script adds NodeSource's apt repository and its signing key; the `nodejs`
   package from that repository includes npm:

        curl -fsSL https://deb.nodesource.com/setup_22.x -o nodesource_setup.sh
        less nodesource_setup.sh
        sudo -E bash nodesource_setup.sh
        sudo apt install -y nodejs
        rm nodesource_setup.sh

4. On macOS, install Node.js with Homebrew:

        brew install node

5. Check the versions again:

        node --version
        npm --version

    The first line is `v20.6.0` or later, and the second prints the npm version.

#### Results

Node.js and npm are installed, and `install.sh` installs the SSH tool.

### Install the Docker CLI and the Compose plugin

#### About this task

`deploy.py` (Chapter 10) runs `docker compose config --images` on the workstation to read the images
of the release's compose files, and compares them with the images that the apps run on TrueNAS.
This needs the `docker` command and its Compose plugin, but no Docker Engine: no daemon is
installed and nothing runs in the background. Without them, `deploy.py plan` and `drift` report
the images as not compared and never notice an image that differs from the release.

On Ubuntu, the packages come from Docker's apt repository, set up as Docker's installation guide
describes for Ubuntu 22.04, 24.04 and 26.04. That guide also installs Docker Engine (`docker-ce`);
this task installs only the command-line tool and the plugin.

#### Steps

1. On Ubuntu, add Docker's apt repository:

        sudo apt update
        sudo apt install ca-certificates curl
        sudo install -m 0755 -d /etc/apt/keyrings
        sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
        sudo chmod a+r /etc/apt/keyrings/docker.asc
        sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
        Types: deb
        URIs: https://download.docker.com/linux/ubuntu
        Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
        Components: stable
        Architectures: $(dpkg --print-architecture)
        Signed-By: /etc/apt/keyrings/docker.asc
        EOF
        sudo apt update

2. On Ubuntu, install the command-line tool and the Compose plugin only:

        sudo apt install docker-ce-cli docker-compose-plugin

3. On macOS, install both with Homebrew, and tell the `docker` command where Homebrew puts its
   plugins. The second command creates `~/.docker/config.json` only if it does not exist; if it
   exists, add the `cliPluginsExtraDirs` entry to it by hand:

        brew install docker docker-compose
        mkdir -p ~/.docker
        test -e ~/.docker/config.json || printf '{\n  "cliPluginsExtraDirs": ["%s/lib/docker/cli-plugins"]\n}\n' "$(brew --prefix)" > ~/.docker/config.json

4. Check the plugin:

        docker compose version

    The output is `Docker Compose version v` followed by the version.

5. On Ubuntu, check that no Docker Engine was installed:

        systemctl list-unit-files docker.service

    The output ends with `0 unit files listed.`, unless Docker Engine was installed on the
    workstation before.

6. In the clone, read the images of a compose file of the release:

        cd ~/local-agent-stack
        docker compose --env-file stack/edge/edge.env.example -f stack/edge/compose.yaml config --images

    The output is two lines, the images of the edge app with their digests:
    `ghcr.io/corytron/local-agent-stack-caddy:2.11.9@sha256:...` and
    `utkuozdemir/nvidia_gpu_exporter:1.18.0-nvml@sha256:...`.

#### Results

The workstation has the `docker` command with the Compose plugin and no Docker Engine, and
`deploy.py` can compare images in Chapter 10.

!!! note
    The macOS steps were not run on a Mac for this release. The Homebrew formula `docker` installs
    the command-line client, and the formula `docker-compose` names the plugin directory in its
    installation notes.

## Prepare the client environment file

### Values in client.env

OpenCode, `claude-local` and Claude Code's key helper read three values from
`~/.config/local-agent-stack/client.env`. The file holds a secret, so it is created with mode 600
in a directory with mode 700, and it never enters a repository.

Table: Variables in client.env

| Variable | Value | Where it comes from |
|---|---|---|
| `LAB_DOMAIN` | Your domain, for example `lab.example.com` | The same value as `LAB_DOMAIN` in `edge.env` and `web.env` (Chapters 5 and 6). OpenCode builds `https://llm.<LAB_DOMAIN>/v1` and `https://mcp.<LAB_DOMAIN>/servers/<name>/mcp` from it |
| `LOCAL_LLM_KEY` | A LiteLLM virtual key, `sk-local-...` | The key that Chapter 4 created for this workstation. Never use `LITELLM_MASTER_KEY` |
| `MCP_HUB_TOKEN` | The MCP hub's bearer token | The same value as `MCP_HUB_TOKEN` in `web.env` (Chapter 3); the hub has one token for every client |

The workstation's LiteLLM key must allow these model names:

- `local-coder`, `local-fast` and `local-coder-moe`, for OpenCode;
- `local-opus`, `local-sonnet` and `local-haiku`, if you also use Claude Code with `claude-local`.

Use one key per workstation, so that LiteLLM's usage logs and budgets separate `c4dev` from the
Mac.

### Create client.env

#### Prerequisites

- The `ai-inference`, `ai-rag`, `ai-web` and `ai-edge` apps are running, and the host names
  resolve to `192.0.2.10` (Chapters 4 to 6).
- The workstation's LiteLLM virtual key from Chapter 4 is stored on `c4dev`
  ([Keep the workstation keys until Chapter 7](#keep-the-workstation-keys-until-chapter-7)).
- The workstation holds the environment files generated in
  [Generate the environment files on the workstation](#generate-the-environment-files-on-the-workstation),
  including `~/.config/local-agent-stack/secrets/web.env` with your domain in `LAB_DOMAIN`
  ([Complete web.env before the first start](#complete-webenv-before-the-first-start)).
- `~/local-agent-stack` is a clone of this repository at `<release-tag>` (Chapter 3).

#### About this task

This task writes `client.env` before the installer runs. When the file exists, `install.sh` leaves
it unchanged; otherwise the installer creates it with placeholders that you replace later.

`tools/secrets.py gen client` fills in the release's example file, `clients/client.env.example`,
printed below. `--share` copies `LAB_DOMAIN` and `MCP_HUB_TOKEN` from the workstation's copy of
`web.env`, and `--ask LOCAL_LLM_KEY` prompts for the LiteLLM key without echoing it, so the key
never appears on a command line or in the shell history. `-o` writes a new file with mode 600; the
tool never replaces an existing file.

{{ include clients/client.env.example }}

#### Steps

1. Make sure that the configuration directory exists with mode 700:

        install -d -m 0700 ~/.config/local-agent-stack

2. Change to the clone:

        cd ~/local-agent-stack

3. Display the workstation's LiteLLM key, stored in Chapter 4, and copy it:

        cat ~/.config/local-agent-stack/secrets/litellm-c4dev.key

4. Write `client.env`. At the prompt `LOCAL_LLM_KEY:`, paste the key and press Enter. The key is not
   echoed:

        python3 tools/secrets.py gen client --share ~/.config/local-agent-stack/secrets/web.env --ask LOCAL_LLM_KEY -o ~/.config/local-agent-stack/client.env

    The command ends with `secrets.py: wrote`, the path of the file and `(mode 0600)`.

    - If it reports that the file exists, `client.env` was written before. Check it with steps 5 to
      7; to start again, rename the old file, for example to `client.env.old`, run the command
      again, and delete the old file.
    - If it prints `MCP_HUB_TOKEN is a placeholder: run gen client with --share <web.env>`, the
      file named with `--share` has no hub token. Delete `client.env` and run the command again
      with the right file.
    - A value typed at a prompt may hold only letters, digits and the characters
      `. _ ~ + / = : @ % , -`; the tool refuses any other value, because a shell reads the file.

    If this workstation has no copy of `web.env`, let the tool prompt for all three values instead
    of `--share`: `--ask LAB_DOMAIN --ask MCP_HUB_TOKEN --ask LOCAL_LLM_KEY`. Read the hub token on
    TrueNAS with `sudo sed -n 's/^MCP_HUB_TOKEN=//p' /mnt/tank/ai/secrets/web.env`.

5. Verify the mode of the file:

        ls -l ~/.config/local-agent-stack/client.env

    The line starts with `-rw-------`.

6. Verify that the file sets the three variables and that no placeholder is left, without
   printing the values:

        grep -E -c '^(LAB_DOMAIN|LOCAL_LLM_KEY|MCP_HUB_TOKEN)=' ~/.config/local-agent-stack/client.env
        grep -c 'replace-with' ~/.config/local-agent-stack/client.env
        grep -c '^LOCAL_LLM_KEY=sk-' ~/.config/local-agent-stack/client.env

    The commands print `3`, `0` and `1`.

7. Check that `client.env` and `web.env` hold the same domain and the same hub token:

        for v in LAB_DOMAIN MCP_HUB_TOKEN; do grep -h "^$v=" ~/.config/local-agent-stack/secrets/web.env ~/.config/local-agent-stack/client.env | sort -u | wc -l; done

    The output is `1` twice.

#### Results

`client.env` holds your three values. The file is read by a shell, so the values must not contain
spaces or quotes; the generated tokens and LiteLLM keys contain none.

!!! warning
    `client.env` holds a key that can spend GPU time on your gateway, and the hub token that
    reaches your knowledge base. Keep it only in `~/.config/local-agent-stack/`, never copy it into
    a repository, and never paste a value into an issue or a chat. To replace a key later, edit the
    file in a text editor and open a new terminal.

### How the shell profile loads client.env

The installer appends a marked block to the profile file of your login shell: `~/.bashrc` for
bash, `~/.zshrc` for zsh, `~/.profile` for any other shell. The block is the following text:

{{ include clients/install.sh lines=346-356 }}

- `set -a` exports every variable that `client.env` assigns, so OpenCode reads them with
  `{env:LAB_DOMAIN}`, `{env:LOCAL_LLM_KEY}` and `{env:MCP_HUB_TOKEN}`.
- `~/.opencode/bin` (OpenCode) and `~/.local/bin` (`ssh-mcp-stdio`, `claude-local`) are put on
  `PATH` once.
- `OPENCODE_DISABLE_MODELS_FETCH=1` stops OpenCode from downloading the models.dev catalog, and
  `OPENCODE_DISABLE_FREE_MODELS=1` hides hosted free models.

The block takes effect in every new terminal. In the current terminal, load the profile file with
`. ~/.bashrc` (or the file the installer names).

!!! note
    The exported values reach every process started from that shell, including the commands that
    the agent runs through its shell tool and the MCP children it starts. OpenCode's policies stop
    the agent from reading `~/.config/local-agent-stack/`, and every shell command asks for your
    approval except read-only `git` and `gh` commands and `tools/check.sh`. Decline any command
    that would print the environment, and read `tools/check.sh` in a repository you did not write
    before you run OpenCode in it.

## Install OpenCode with install.sh

### What install.sh changes

`clients/install.sh` sets up the coding-agent side of the stack in seven steps. It is safe to run
again: it changes only what differs from the release, and it never replaces a file of yours without
first moving it to `<name>.bak.<YYYYMMDD-HHMMSS>`.

Table: What install.sh does

| Step | Change | Backups and conditions |
|---|---|---|
| 1. OpenCode | Downloads `@opencode/cli-<target>` 2.3.0 from `registry.npmjs.org`, checks it against the sha512 pinned in the script, and installs `~/.opencode/bin/opencode` (the package and location the official installer uses) | Skipped when 2.3.0 is already installed. A different version is kept as `opencode.bak.<time>` |
| 2. Background service | Runs `opencode service set disabled true` | Setting it again is harmless |
| 3. Configuration | Links `opencode.jsonc`, the agents, the commands and the plugin into `~/.config/opencode/` (or `$XDG_CONFIG_HOME/opencode/`) | An existing file at a link path is moved to `<name>.bak.<time>`. An existing `opencode.json` is moved aside, because OpenCode would merge it with `opencode.jsonc` |
| 4. `client.env` | Creates `~/.config/local-agent-stack/client.env` with placeholders, mode 600, directory mode 700. The path is always under `~/.config`, also when `XDG_CONFIG_HOME` is set | Only when the file does not exist |
| 5. SSH tool | Installs `ssh-mcp` 2.26.0 into `~/.local/share/local-agent-stack/ssh-mcp` with npm (registry integrity check, no install scripts), and copies the policy example to `~/.config/ssh-mcp/config.toml` with mode 600 in a 700 directory | Only when Node.js 20.6 or later and npm are present ([Install Node.js and npm](#install-nodejs-and-npm)). The policy is copied only when no `config.toml` exists |
| 6. Launchers | Links `ssh-mcp-stdio` and `claude-local` into `~/.local/bin` | As step 3 |
| 7. Shell profile | Appends the marked block (previous topic) to the profile file, or replaces an older version of the block | The profile file is copied to `<file>.bak.<time>` first |

The installer needs `curl`, `tar`, `openssl` and `uname`. It chooses the OpenCode build for the
machine: `linux-x64` (`linux-x64-baseline` on a processor without AVX2), the `-musl` variants on a
musl system, `linux-arm64`, `darwin-arm64` (also under Rosetta), `darwin-x64` and
`darwin-x64-baseline`. For any other machine it stops and names the official installer instead.

Table: install.sh options

| Option | Effect |
|---|---|
| `--dry-run` | Prints every change without making it |
| `--no-shell-rc` | Leaves the profile file alone and prints the block for you to add |
| `--no-opencode` | Skips steps 1 and 2 |
| `--no-ssh-mcp` | Skips step 5 |
| `-h`, `--help` | Prints the usage |

### Preview the installation

#### Prerequisites

- `~/local-agent-stack` is a clone of this repository at `<release-tag>` (Chapter 3).
- `client.env` exists ([Create client.env](#create-clientenv)).

#### Steps

1. Check that the clone is at the release tag:

        git -C ~/local-agent-stack describe --tags --exact-match

    The output is the release tag, for example `v1.0`.

2. Check the Node.js version that the SSH tool needs:

        node --version

    The SSH tool needs `v20.6.0` or later and npm. If `node` is missing or older, install it with
    [Install Node.js and npm](#install-nodejs-and-npm) and check the version again; on Ubuntu 24.04,
    the archive's `nodejs` package is too old. Without a suitable Node.js, the installer skips
    `ssh-mcp` and installs everything else.

3. Run the installer in dry-run mode:

        ~/local-agent-stack/clients/install.sh --dry-run

    The first line is `Dry run: nothing is changed.` Each section then lists its planned actions
    on lines that start with `[dry-run]`, or `ok` for a part that is already in place. The
    `Client secrets` section shows `ok` for `client.env` (`exists, left as it is`).

4. Read the `keeping your ... as ....bak....` lines, if there are any. They name your existing
   files that the real run will move aside.

#### Results

You know every change the installer will make. Nothing has changed yet.

### Run the installer

#### Steps

1. Run the installer:

        ~/local-agent-stack/clients/install.sh

    The output has one section per step. Expect, among others:

    - `checksum ok` and `installed /home/<user>/.opencode/bin/opencode (...)`;
    - `disabled: each opencode command runs its own server and stops it on exit`;
    - one `linked` line per configuration file;
    - `installed ssh-mcp 2.26.0 in ...` and `created .../ssh-mcp/config.toml`, or a `skipped:`
      line that names the missing or older Node.js; in that case, complete
      [Install Node.js and npm](#install-nodejs-and-npm) and run the installer again;
    - `appended block; open a new terminal or run: . /home/<user>/.bashrc`.

    The output ends with a `Next:` list. Its third line names only two models; the configuration
    defines three, and the verification below expects all three.

2. Open a new terminal, so that the profile block is loaded.

3. Verify the OpenCode version:

        opencode --version

    The output names version 2.3.0.

4. Verify that the shared background service is disabled:

        opencode service get disabled

    The output is `true`.

5. Verify the configuration links:

        ls -l ~/.config/opencode/opencode.jsonc ~/.config/opencode/agents ~/.config/opencode/commands ~/.config/opencode/plugins

    `opencode.jsonc` points to `~/local-agent-stack/clients/opencode/opencode.jsonc`. The
    directories hold links to `coordinator.md`, `researcher.md`, `builder.md`, `reviewer.md`,
    `check.md`, `issue.md`, `plan.md`, `pr.md` and `guard.ts` in the clone.

6. Verify the environment of the new terminal, without printing the secrets:

        echo "$LAB_DOMAIN $OPENCODE_DISABLE_MODELS_FETCH ${LOCAL_LLM_KEY:+key-set} ${MCP_HUB_TOKEN:+token-set}"

    The output is your domain, `1`, `key-set` and `token-set`.

7. Verify the SSH tool files, if Node.js was present:

        ls -l ~/.config/ssh-mcp/config.toml ~/.local/bin/ssh-mcp-stdio ~/.local/bin/claude-local

    `config.toml` has mode `-rw-------`; the two launchers are links into the clone.

8. Run the installer once more:

        ~/local-agent-stack/clients/install.sh

    Every section reports `ok`. A second run changes nothing that is already right.

#### Results

OpenCode 2.3.0 is installed in `~/.opencode/bin`, its configuration links to the release files,
the shared service is disabled, and new terminals load `client.env`. To undo a change, move the
`<name>.bak.<time>` file back over the link or file that replaced it.

!!! note
    The links point into `~/local-agent-stack`. Do not move or delete the clone, and do not edit
    the linked files there: a change takes effect in the next OpenCode session and makes the
    workstation differ from the release. Make changes through the project workflow of Chapter 8.

### Why the OpenCode service stays disabled

OpenCode can run a shared background server that several clients attach to. The stack does not use
it: nothing of the stack may run full time on a workstation. `opencode service set disabled true`
makes a private server the default for every `opencode` command, so each command starts its own
server and stops it when it exits, and the setting also stops a shared service that is already
running.

- Do not run `opencode service start`, `opencode serve` or `opencode pair` on a workstation.
- Never run `opencode pair --remote`. It exposes the server through an internet tunnel, which
  breaks the stack's LAN-only design.
- After you exit OpenCode, no OpenCode process remains. Check it with `pgrep -l opencode`, which
  prints nothing.

The Mac and the Windows VM therefore do not attach to a server on `c4dev`. They run their own CLI,
or you log in to `c4dev` over SSH and start `opencode` there
([Use OpenCode from the Mac](#use-opencode-from-the-mac)).

### Update OpenCode and the SSH tool

#### About this task

The installer pins OpenCode 2.3.0 and `ssh-mcp` 2.26.0. OpenCode's own updater is turned off
(`"update": "disable"`), so `opencode upgrade` is not used. A new release of this guide brings any
new versions; you move the clone to the new tag and run the installer again. Chapter 10 includes
this task in the update of a whole release.

#### Steps

1. Move the clone to the new release:

        git -C ~/local-agent-stack fetch --tags
        git -C ~/local-agent-stack checkout <release-tag>

2. Preview and run the installer:

        ~/local-agent-stack/clients/install.sh --dry-run
        ~/local-agent-stack/clients/install.sh

3. Open a new terminal and repeat steps 3 to 7 of [Run the installer](#run-the-installer).

#### Results

The workstation runs the versions and configuration of the new release. Your `client.env` and your
`config.toml` are left as they are; compare `config.toml` with the new
`clients/ssh-mcp/config.example.toml` and carry over any new settings by hand.

!!! note
    Moving to an OpenCode or `ssh-mcp` version that no release pins is a change to the repository:
    `OPENCODE_VERSION` and every per-platform sha512 in `install.sh` (field `dist.integrity` at
    `https://registry.npmjs.org/@opencode/cli-<target>/<version>`), or `SSH_MCP_VERSION`, change,
    and the configuration keys are checked against the new release notes. Make such a change
    through the workflow of Chapter 8.

## Review the OpenCode configuration

### The global configuration file

`~/.config/opencode/opencode.jsonc` is the global configuration of every OpenCode session on the
workstation. A project can add its own `opencode.jsonc`, but it cannot loosen the global
`policies`. The file is linked from the release:

{{ include clients/opencode/opencode.jsonc }}

### Provider and models

The configuration defines one provider, `local`, with OpenCode's OpenAI-compatible provider
package, the base URL `https://llm.{env:LAB_DOMAIN}/v1` and the key `{env:LOCAL_LLM_KEY}`. Two
policies lock OpenCode to it: `provider.use` is denied for every provider and allowed only for
`local`.

Table: Models in the OpenCode configuration

| Model | Served by | Context | Output limit | Use |
|---|---|---|---|---|
| `local/local-coder` | Qwen3.8-27B (`coder`) | 65,536 | 16,384 | Default model of every session and of all four agents |
| `local/local-fast` | The same model with thinking off | 65,536 | 8,192 | Session titles (the `title` agent) |
| `local/local-coder-moe` | Qwen3.6-35B-A3B (`coder-moe`) | 65,536 | 16,384 | Faster profile; requesting it unloads `coder` from the GPU |

- The declared context of 65,536 tokens matches the server's window. OpenCode starts compaction
  from it (`"compaction": { "auto": true, "keep": { "tokens": 8000 }, "buffer": "20%" }`): it
  compacts before the window fills and keeps the most recent 8,000 tokens.
- `local-coder` and `local-fast` are both served by the one `coder` process, so mixing them costs
  nothing. `local-coder-moe` swaps the GPU model for every client. Use it for a whole session that
  starts no subagents: the four agent definitions name `local/local-coder`, and each subagent
  request would load `coder` back.
- `"websearch": false` and the `websearch.use` policy remove OpenCode's built-in web search, which
  supports paid providers only. Web search goes through the SearXNG tool on the hub.
- `"update": "disable"` turns off update checks, and `"share": "disabled"` turns off session
  sharing. The profile variables turn off the models.dev download and the hosted free models.
  OpenCode documents no telemetry.
- `"experimental": { "todo": true }` turns on OpenCode's todo list, which is behind an
  experimental flag.

!!! note
    The configuration relies on OpenCode reading the model's reasoning stream field
    (`reasoning_content`) without extra settings. If the model's reasoning appears as answer text,
    or tool calls fail, the OpenCode setting for that field is `compatibility.reasoningField` on
    the model. Test such a change with the first-session tasks before you rely on it.

### MCP servers in the configuration

Table: MCP servers

| Server | Type and address | Tools | State |
|---|---|---|---|
| `searxng` | Remote, `https://mcp.{env:LAB_DOMAIN}/servers/searxng/mcp` | `searxng_web_search`, `searxng_search_suggestions`, `searxng_instance_info`, `web_url_read` | On |
| `fetch` | Remote, `https://mcp.{env:LAB_DOMAIN}/servers/fetch/mcp` | `fetch` | On |
| `kb` | Remote, `https://mcp.{env:LAB_DOMAIN}/servers/kb/mcp` | `search_knowledge_base`, `list_knowledge_bases`, `get_knowledge_base_info`, `get_knowledge_base_file_content` | On |
| `ssh` | Local (stdio), `{env:HOME}/.local/bin/ssh-mcp-stdio` | The `ssh-mcp` tools, for example `list-connections` | Off until you enable it in a project |

- The three remote servers send `Authorization: Bearer {env:MCP_HUB_TOKEN}` and use no OAuth
  (`"oauth": false`). The hub has one token for every client and no per-user identity.
- `searxng` returns at most 10 results of 500 characters each and at most 20,000 characters per
  page read. Result quality depends on the upstream engines, which SearXNG suspends after
  CAPTCHAs; the model must refine its queries itself.
- `fetch` refuses private, loopback and link-local addresses and honours `robots.txt`. OpenCode's
  built-in `webfetch` tool is also available.
- `kb` acts as the `kb-reader` user of Open WebUI (Chapter 6), so it sees only the knowledge bases
  that user was given, and it can only read them.
- `"codemode": false` on every server lists each MCP tool as a plain tool. Weak models call plain
  tools more reliably than they write the JavaScript that Code Mode needs. The cost is that every
  tool's schema is sent with every request, so keep the number of enabled servers small.

### Permissions and policies

OpenCode applies two kinds of rules.

- **Policies** are hard limits. They only deny, never prompt, and a project's configuration cannot
  loosen the global ones.
- **Permissions** are ordered allow, ask and deny rules. The last matching rule wins, the rules of
  an agent are appended after the global ones, and with no matching rule the default is `ask`. A
  rule such as `git status *` also matches the bare `git status`.

Table: Policies in the global configuration

| Policy | Denies |
|---|---|
| `provider.use` | Every provider except `local` |
| `websearch.use` | The built-in web search |
| `tool.use` on `shell:git push ...` | The simplest forms of a push to `main` or `master`, and `git push --all` and `--mirror` |
| `tool.use` on `shell:rm ...`, `--no-preserve-root`, `mkfs*` | `rm -rf /`, `rm -fr /`, `rm -rf ~`, any `--no-preserve-root`, any `mkfs` |
| `tool.use` on `edit:` | Writing `*.env`, `*.pem` and anything under `.ssh/` |
| `tool.use` on `read:` | Reading `.ssh/id_*` keys and anything under `.config/local-agent-stack/` |

Table: Permissions in the global configuration

| Action | Effect |
|---|---|
| `shell` | Ask before every command, except: allow `git status`, `git diff`, `git log`, `git show`, `git branch --show-current`, `gh issue view`, `gh issue list`, `gh pr view`, `gh pr checks` and `tools/check.sh`; deny `sudo` |
| `external_directory` | Ask before touching a path outside the project |
| `execute` | Deny: turns off Code Mode, so MCP tools are plain tools and the `execute` tool's schema is dropped |
| `opencode_*` | Deny: OpenCode's own tools (worktrees, session move and rename, model list, MCP resources), for a short tool list |
| `read` | Deny `*.env`; allow `*.env.example` |

The guard plugin enforces the finer rules (next topics), and the policies repeat its simplest forms
so that they still hold if a project's configuration disables the plugin.

!!! warning
    OpenCode has no operating-system sandbox: its shell tool runs with your user's rights. The
    policies, the guard and the `ask` rules are the fence. For a repository you do not trust, run
    OpenCode as a separate unprivileged user whose files and `gh` token reach only that work.

## Agents and commands

### The four agents

The agent files in `~/.config/opencode/agents/` define the roles of the working style in Chapter 8.
The frontmatter sets the mode, the model, the maximum number of steps and the permission rules; the
Markdown body replaces OpenCode's base system prompt for that agent, so each body restates the few
harness rules that matter, such as reading a file before editing it and copying old text exactly.

Table: Agents

| Agent | Mode, model, steps | Allowed beyond the global rules | Denied |
|---|---|---|---|
| `coordinator` | Primary and default (`default_agent`), `local/local-coder`, no `steps` setting | Starting the `researcher`, `builder`, `reviewer` and `explore` agents; `git add`, `git commit`, `git switch`, `git fetch`, `git pull --ff-only`, `gh issue create` and `gh pr create` without a prompt | Starting any other agent |
| `researcher` | Subagent, `local/local-coder`, 40 steps | Writing under `docs/`; `git log` and `git show` | Every other edit and shell command; starting agents |
| `builder` | Subagent, `local/local-coder`, 60 steps | Editing the files its brief names (the global rules apply) | `git` and `gh` commands; starting agents |
| `reviewer` | Subagent, `local/local-coder`, 30 steps | `git status`, `git diff`, `git log`, `git show`, `gh pr view`, `gh pr diff`, `tools/check.sh` | Every edit and every other shell command; starting agents |

The `coordinator` is the only agent that talks to you, owns the plan and runs `git`. It runs at most
two subagents at a time, or three for short read-only research, because one GPU serves every agent
(see [Concurrency on one 16 GB GPU](#concurrency-on-one-16-gb-gpu)). OpenCode also brings its own
agents: `plan`, which the `/plan` command uses, `explore` for quick searches, and `title`, which the
configuration moves to `local/local-fast`. Press Tab in a session to cycle through the primary
agents. Subagents always run in the background and report to the coordinator when they go idle.

### The coordinator definition

The coordinator's file shows how an agent is defined: permission rules in the frontmatter, the
working rules in the body.

{{ include clients/opencode/agents/coordinator.md }}

The files of the other three agents follow the same pattern. Appendix E prints them in full.

### The slash commands

The command files in `~/.config/opencode/commands/` add four commands. Type them at the start of a
message in an OpenCode session.

Table: Slash commands

| Command | Agent | What it does |
|---|---|---|
| `/plan <change or issue number>` | `plan` (read-only) | Reads `AGENTS.md`, `docs/status.md` and the code involved, then writes a plan under seven fixed headings: Goal, Approach, Files, Contract, Split (at most three parts with disjoint files), Checks, Open questions. Marks unconfirmed facts `UNVERIFIED` and stops |
| `/issue <number>` | `coordinator` | Runs `gh issue view <number>`, stops if the issue is closed or missing, creates the branch `<type>/<short-slug>-<number>` (type `feat`, `fix`, `docs` or `chore`; the issue number last) from an up-to-date `main`, plans, commits the contract when more than one agent works on it, opens the pull request with `/pr`, and starts at most two subagents |
| `/pr [issue number]` | `coordinator` | Shows the branch, the working tree and the commits not on `main`; stops on `main` or `master`; asks before committing uncommitted files; runs `tools/check.sh`; adds a `CHANGELOG.md` line under `## Unreleased` if one is missing; pushes the branch by name; creates the pull request with `Closes #<issue>`, or reports the existing one |
| `/check [check names]` | The current agent | Runs `tools/check.sh` with the names you give, shows the last 120 lines, and summarises each failing check with its file, line and likely fix. Changes nothing unless you ask |

A line that starts with `!` in a command file is a shell command that runs before the prompt is
sent, with your arguments put in place of `$1` or `$ARGUMENTS`. `/issue` and `/check` put your
arguments into such a line.

!!! warning
    Type only an issue number after `/issue` and only check names after `/check`. Anything else you
    type there becomes part of a shell command line.

The plan command:

{{ include clients/opencode/commands/plan.md }}

The issue command:

{{ include clients/opencode/commands/issue.md }}

The check command:

{{ include clients/opencode/commands/check.md }}

## The guard plugin

### What the guard refuses

`guard.ts` is the counterpart of Claude Code's `PreToolUse` hook. It is loaded into every OpenCode
session on the workstation and refuses three kinds of action. The model receives the reason,
prefixed with `guard:`, and what to do instead.

Table: Actions the guard refuses

| Kind | Refused |
|---|---|
| Pushes | A push to `main` or `master` in any refspec form (`main`, `src:main`, `+main`, `refs/heads/main`); a push of every branch (`--all`, `--branches`, `--mirror`); a push that names no branch, so the current branch cannot silently be `main` (a push of `--tags` alone is allowed); `HEAD` as the refspec |
| Secret files | Writing, editing or patching a path that looks like a secret store: `.env` and `.env.*` files (but not `.env.example`, `.sample`, `.template` or `.dist`); `.pem`, `.key`, `.p12`, `.pfx`, `.jks`, `.keystore`, `.kdbx` and `.ovpn` files; SSH private keys; anything under `.ssh/`, `.gnupg/`, `.config/local-agent-stack/` or a directory named `secrets/`; `.netrc`, `.git-credentials`, `.pgpass`, `.npmrc`, `.pypirc`; AWS, Docker, Kubernetes and `gh` credential files |
| Secret text | New file content that contains a private key block, or an AWS, GitHub, GitLab, Slack, Hugging Face or Cloudflare token, or an `sk-` key of 20 or more characters that mixes letters and digits. Placeholders such as `sk-local-...` pass |
| Wiping commands | `rm -r` of `/`, `~`, `.`, `..`, `*`, a top-level system directory, a home directory or a directory directly under `/mnt` or `/Volumes`; the same targets with `chmod -R`, `chown -R`, `chgrp -R` and `find -delete`; `--no-preserve-root`; `mkfs*` and `wipefs`; `dd` or `shred` onto a device; a redirect onto a disk device; fork bombs |

The guard looks through `VAR=value` prefixes and wrappers such as `sudo`, `env`, `nice`, `timeout`
and `xargs`, so `sudo rm -rf /` is refused like `rm -rf /`.

!!! note
    The `secrets/` rule refuses any file in a directory of that name, including documentation in a
    project's own `secrets/` folder. Name such a folder differently, or write the file yourself.

### How the guard works

OpenCode loads `.ts` files directly from `~/.config/opencode/plugins/`. The plugin imports types
only, so nothing has to be installed next to it. It uses two hooks:

- The permission hook sees every permission check that the rules resolved to allow or ask: shell
  commands as one string per subcommand, edit targets as paths. Setting the effect to deny refuses
  the action. An explicit deny from a policy or a permission rule is final and does not reach the
  hook.
- The tool hook sees the input of each `write`, `edit` and `patch` call before it runs, and blocks
  the call when the path or the new text matches a secret rule.

The rule summary at the top of the file and the patterns for secret paths and secret text:

{{ include clients/opencode/plugins/guard.ts lines=1-26 }}

{{ include clients/opencode/plugins/guard.ts lines=161-203 }}

!!! caution
    OpenCode also loads every `.opencode/plugins/*.ts` file of a repository that it opens, and runs
    it at start-up. A project's configuration could also disable the guard; the global policies
    still apply. Read the `.opencode/` directory and the `opencode.jsonc` of a repository you did
    not write before you run OpenCode in it.

### Verify the guard

#### About this task

This task confirms that the plugin loads and refuses actions, in a scratch repository with no
remote, so that nothing can leave the workstation even if a rule failed.

#### Steps

1. Create a scratch repository:

        mkdir -p ~/scratch/guard-test && cd ~/scratch/guard-test && git init

2. Start OpenCode:

        opencode

3. Enter the following prompt:

        Run exactly this shell command: git push origin main

    OpenCode refuses the command without asking you. The message reads
    `guard: Never push to main. Push a feature branch and open a pull request: git push -u origin <branch>, then gh pr create.`

4. Enter the following prompt:

        Create a file named .env containing the line TEST=1

    The write is refused without a prompt, by the `edit:*.env` policy or by the guard.

5. If OpenCode instead asks you to approve either action, reject it, exit OpenCode, and check that
   `~/.config/opencode/plugins/guard.ts` is a link to the clone (step 5 of
   [Run the installer](#run-the-installer)).

6. Exit OpenCode and remove the scratch repository:

        cd ~ && rm -rf ~/scratch/guard-test

#### Results

Pushes to `main` and secret files are refused before any prompt reaches you.

## Set up the SSH tool

### How the SSH tool is protected

The SSH tool lets the agent run commands on remote hosts. It is the one tool that is not on the
hub: `ssh-mcp` runs on the workstation as a stdio child of OpenCode, so the agent's key stays on the
workstation and approval prompts reach you directly. Several layers limit what it can do.

Table: Protection layers of the SSH tool

| Layer | Where | Effect |
|---|---|---|
| Dedicated key | Workstation | A key made only for the agent, never your own key. `ssh-mcp-stdio` does not pass your `SSH_AUTH_SOCK` on, so your own ssh-agent is out of reach |
| Restricted user | Remote host | A non-root account without `sudo` rights |
| `authorized_keys` options | Remote host | `restrict` turns off port, agent and X11 forwarding, the PTY and `~/.ssh/rc`; `from=` accepts the key only from the workstation's address; `expiry-time=` can make the key lapse |
| Deny-by-default policy | Workstation | `ssh-mcp` reaches only the hosts listed in its policy file and refuses every call until that file exists. A host without a known tier is treated as production, the strictest tier |
| Host-key pinning | Workstation | `ssh-mcp-stdio` starts `ssh-mcp` with `--hostKeyMode=strict`: an unpinned or changed host key is refused |
| Approval prompts | Workstation | Destructive and privileged commands are refused, or, where the policy allows asking, need your approval in an OpenCode form (MCP elicitation) |
| Limits | Workstation | 60-second command timeout, 300 commands per day, 1 MiB of output per command |
| Audit log | Workstation | `--auditTamperEvident` writes a hash-chained JSONL log under `~/.local/share/ssh-mcp/` |

`ssh-mcp` also tells each host that an agent is connecting (`AI_AGENT=ssh-mcp`), unless a profile
sets `announceAgent = false`.

!!! warning
    Never add the TrueNAS server itself to the SSH policy: not its root account, its middleware or
    its Docker socket. An agent with those rights controls every app and every dataset of the
    stack.

The launcher that OpenCode starts:

{{ include clients/ssh-mcp/ssh-mcp-stdio }}

Set `SSH_MCP_BIN` to run another `ssh-mcp` binary, and `SSH_MCP_AUTH_SOCK` to give the tool an
ssh-agent socket that holds only the agent key.

!!! note
    The approval form relies on OpenCode 2.3.0 supporting MCP elicitation. The research notes of
    this release confirm `ssh-mcp`'s behaviour but not OpenCode's form. If no form appears,
    `ssh-mcp` refuses destructive and privileged commands with `APPROVAL_UNAVAILABLE`, which fails
    closed. Commands of the read-only and safe classes are not affected.

### The SSH policy file

The installer copies the policy example once to `~/.config/ssh-mcp/config.toml` (macOS:
`~/Library/Application Support/ssh-mcp/config.toml`), with mode 600 in a 700 directory. `ssh-mcp`
refuses to start with looser modes, and an unknown key in the file is a start-up error, so a typo
cannot fall back to a default.

{{ include clients/ssh-mcp/config.example.toml }}

Table: Settings in the SSH policy

| Setting | Value in the example | Meaning |
|---|---|---|
| `approvalMode` (defaults) | `"deny"` | Destructive and privileged commands are refused unless a profile allows asking |
| `approvalGrantTtlMs` | `0` | Every approval is asked again; there is no automatic approval window |
| `commandTimeoutMs`, `commandQuotaPerDay`, `commandMaxOutputBytes` | 60000, 300, 1048576 | Limits per command and per day; the quota is a circuit breaker for a runaway agent |
| `name`, `host`, `port`, `user` | `lab-vm`, `192.0.2.30`, `22`, `agent` | The profile the agent names, and the account it logs in as |
| `auth`, `keyRef` | `"key"`, `~/.ssh/agent_ed25519` | The agent's own key file |
| `group` | `"dev"` | The policy tier: `dev`, `staging` or `prod` |
| `role` | `"operator"` | Read-only, safe and destructive commands on a `dev` host |
| `approvalPolicy` | `"ask-destructive"` | Destructive commands on this host are asked, not refused |
| `tty` | `false` | No PTY; the `restrict` option refuses one anyway |
| `trustedHostKey` | A placeholder | The pinned SHA-256 fingerprint of the host's ED25519 key |
| `workdir` | `/home/agent` | The working directory of commands |
| `denylist` | Six patterns | Refused on top of `ssh-mcp`'s built-in never-allowed list: shutdown and reboot, ZFS and pool destruction, Docker prune, `midclt`, and writes to `authorized_keys` |

!!! note
    A call that names a profile that is not listed fails with `Profile ... not found`. Without a
    `defaultProfile` setting, a call that names no profile goes to the first profile; this was
    observed with `ssh-mcp` 2.26.0. Keep the profile you want as the default first in the file.

### Create the agent key

#### About this task

OpenCode starts `ssh-mcp` without a terminal, so the tool cannot ask for a passphrase. The key is
therefore created without one, and its power is limited on each host instead (next task). Create
one key per workstation, so that the `from=` option on the host can name that workstation's address.

#### Steps

1. Create the key on `c4dev`:

        ssh-keygen -t ed25519 -f ~/.ssh/agent_ed25519 -C agent@c4dev -N ''

2. Verify the files:

        ls -l ~/.ssh/agent_ed25519 ~/.ssh/agent_ed25519.pub

    The private key has mode `-rw-------`.

3. Display the public key and copy the whole line for the next task:

        cat ~/.ssh/agent_ed25519.pub

#### Results

The agent has its own key pair. Your own keys and ssh-agent are not used by the SSH tool.

!!! caution
    OpenCode's policies forbid the agent to read `~/.ssh/id_*` keys but not other file names. The
    `external_directory` rule makes OpenCode ask before the agent reads `~/.ssh/agent_ed25519`;
    reject any such request.

### Prepare the remote host

#### Prerequisites

- An administrator account on the remote host (`192.0.2.30` in this example), a Linux system
  that runs the OpenSSH server.
- The public key line from [Create the agent key](#create-the-agent-key).

#### About this task

On each host that the agent may reach, create a dedicated account without `sudo` rights and allow
the agent key only from the workstation's address. The commands are written for Ubuntu and
Debian; use the equivalents of your distribution elsewhere.

#### Steps

1. On the remote host, create the account:

        sudo useradd --create-home --shell /bin/bash agent

    The account has no usable password, so it can log in only with a key. Do not add it to the
    `sudo` or `wheel` group. If the agent needs one privileged command, add a `sudoers.d` entry for
    that command only, never `NOPASSWD: ALL`.

2. Create the key directory:

        sudo install -d -m 0700 -o agent -g agent /home/agent/.ssh

3. Write the authorized key with its restrictions. Replace the key text with the line you copied:

        echo 'restrict,from="192.0.2.20" ssh-ed25519 AAAA...replace... agent@c4dev' | sudo tee /home/agent/.ssh/authorized_keys > /dev/null
        sudo chown agent:agent /home/agent/.ssh/authorized_keys
        sudo chmod 0600 /home/agent/.ssh/authorized_keys

    To make the key lapse on a date, add `expiry-time="YYYYMMDD"` after the `from=` option,
    separated by a comma.

4. Optional: harden the account in the SSH server. Add the following block at the end of
   `/etc/ssh/sshd_config`:

        Match User agent
            AuthenticationMethods publickey
            DisableForwarding yes
            PermitTTY no

    If the server uses `AllowUsers` or `AllowGroups`, add the `agent` account to it as well. Then
    check the configuration and reload the SSH server:

        sudo sshd -t
        sudo systemctl reload ssh

    `sshd -t` prints nothing when the configuration is valid. Keep your current session open until
    a new login works.

5. On `c4dev`, test the key with the normal SSH client:

        ssh -i ~/.ssh/agent_ed25519 -o IdentitiesOnly=yes agent@192.0.2.30 hostname

    The command prints the host name of the remote host. On the first connection, SSH asks you to
    confirm the host key; this check is separate from the pinning in the next task.

#### Results

The remote host accepts the agent key, from `c4dev` only, for an account without administrator
rights.

!!! note
    A forced command (`command=` in `authorized_keys`, or `ForceCommand`) can restrict the account
    further to an allow-list of command prefixes. This release ships no such wrapper; with a forced
    command, file transfer works only if the wrapper allows it.

### Pin the host key and edit the policy

#### Steps

1. On `c4dev`, read the host's ED25519 key fingerprint:

        ssh-keyscan -t ed25519 192.0.2.30 | ssh-keygen -lf -

    The output is one line such as `256 SHA256:... 192.0.2.30 (ED25519)`.

2. Compare the fingerprint with the one the host reports about itself. On the remote host's
   console, run:

        ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub

    The `SHA256:` values must be identical. If they differ, stop: something on the network answers
    for the host.

3. Open the policy file in a text editor, for example:

        nano ~/.config/ssh-mcp/config.toml

    In the `lab-vm` profile, set `host` to the host's address, `user` to `agent`, `keyRef` to
    `~/.ssh/agent_ed25519`, and `trustedHostKey` to the full `SHA256:...` value from step 1. Adjust
    `name`, `group` and `workdir` if you want. Save the file.

4. Verify the modes that `ssh-mcp` requires:

        ls -ld ~/.config/ssh-mcp
        ls -l ~/.config/ssh-mcp/config.toml

    The directory shows `drwx------` and the file `-rw-------`.

#### Results

The policy lists one host, with its key pinned. The tool still does nothing until a project enables
it.

### Enable the SSH tool in a project

#### About this task

The global configuration defines the `ssh` server but leaves it disabled, so the SSH tool is
available only in projects that need it, and its tool schemas cost context only there. A project
entry replaces the whole global entry, so the project file repeats every field.

#### Steps

1. In the root of the project, create or extend `opencode.jsonc` with the following entry:

        { "mcp": { "servers": { "ssh": {
          "type": "local", "command": ["{env:HOME}/.local/bin/ssh-mcp-stdio"], "codemode": false
        } } } }

    If the project already has an `opencode.jsonc`, add the `ssh` entry under its
    `mcp.servers` instead. The entry holds no secret, so it can be committed.

2. From the root of the project, list the MCP servers:

        opencode mcp list

    `ssh` is listed as connected, next to `searxng`, `fetch` and `kb`.

#### Results

OpenCode starts `ssh-mcp` for each session in this project and stops it when the session ends. The
first-session task [Test the SSH tool in a session](#test-the-ssh-tool-in-a-session) runs the first
commands.

### Add another host to the policy

#### Steps

1. Prepare the new host as in [Prepare the remote host](#prepare-the-remote-host).

2. Read and compare its host-key fingerprint as in steps 1 and 2 of
   [Pin the host key and edit the policy](#pin-the-host-key-and-edit-the-policy).

3. Append a profile to `~/.config/ssh-mcp/config.toml`, after the existing ones. Use a new `name`,
   and choose the tier and role for the host:

        [[profiles]]
        name = "<profile-name>"
        host = "<host-address>"
        port = 22
        user = "agent"
        auth = "key"
        keyRef = "~/.ssh/agent_ed25519"
        group = "dev"
        role = "operator"
        approvalPolicy = "ask-destructive"
        tty = false
        trustedHostKey = "SHA256:<fingerprint>"
        workdir = "/home/agent"

    For a host the agent should only inspect, set `readOnly = true` in its profile. For a
    production host, set `group = "prod"`; every unknown or missing tier is treated as production.

4. Start a new OpenCode session in a project with the SSH tool enabled, and ask the agent to run
   `list-connections`.

    The list includes the new profile.

#### Results

The agent can reach the new host under the tier and role you chose. Remove a host by deleting its
profile and the agent key line in that host's `authorized_keys`.

## First session

### Check the client from the shell

#### Prerequisites

- The installation is verified ([Run the installer](#run-the-installer)).
- With the internal CA of Appendix D, the workstation trusts the root certificate
  ([Trust the certificates](#trust-the-certificates)).

#### Steps

1. Check that the gateway accepts the workstation key and lists its models. The key goes to
   `curl` on standard input, so it does not appear in the process list:

        printf 'Authorization: Bearer %s\n' "$LOCAL_LLM_KEY" |
          curl -s -H @- https://llm.$LAB_DOMAIN/v1/models | head -c 300

    The output is JSON that lists the model names the key allows, such as `local-coder`.

2. Change to a repository. Any git repository works; the clone is used here:

        cd ~/local-agent-stack

3. List the models OpenCode offers:

        opencode models

    The output lists `local/local-coder`, `local/local-coder-moe` and `local/local-fast`, and no
    other model.

4. List the MCP servers:

        opencode mcp list

    `searxng`, `fetch` and `kb` are connected, and `ssh` is disabled.

5. Run a headless request:

        opencode run "Reply with the word OK."

    The answer is `OK`, from `local-coder`. If the `coder` model is not loaded, for example after
    a restart of the server, the first answer can take a minute or more while the model loads.

#### Results

The workstation reaches the gateway and the hub, and OpenCode offers only the local models.

### Start an interactive session

#### Steps

1. In the repository, start OpenCode:

        opencode

    The session opens with the `coordinator` agent and the model `local/local-coder`. Press Tab to
    see the other primary agents, and Tab again to return to `coordinator`.

2. Enter a prompt that reads the repository without changing it:

        List the top-level directories of this repository and say in one line what each holds.

    The agent uses its read and search tools and answers with the directory list. A new session
    first processes OpenCode's own prompt (about 5,300 tokens) and the tool schemas, so the first
    answer takes several seconds longer than later ones.

#### Results

An interactive session works with the coordinator agent and the local model.

### Test web search, fetch and the knowledge base

#### Prerequisites

The knowledge base exists, `kb-reader` has read access to it, and at least one document has been
indexed (Chapter 6).

#### Steps

1. In the session, test web search:

        Use the searxng_web_search tool to search for "llama.cpp GitHub repository" and list the first three result URLs.

    The session shows a call to `searxng_web_search`, and the answer lists URLs from the results.

2. Test the fetch tool:

        Use the fetch tool to read https://example.com and quote its first heading.

    The session shows a call to `fetch`, and the answer quotes `Example Domain`.

3. Test the knowledge base:

        Use the list_knowledge_bases tool and name each knowledge base you can see.

    The answer names the knowledge base you created for the `rag-docs` share in Chapter 6.

4. Ask a question that one of your indexed documents answers:

        Use the search_knowledge_base tool to find <a phrase from one of your documents>, and name the file it comes from.

    The session shows a call to `search_knowledge_base`, and the answer names the document.

#### Results

The agent searches the web through SearXNG, reads pages and queries the same index as Open WebUI.

### Test the SSH tool in a session

#### Prerequisites

The SSH tool is enabled in this project ([Enable the SSH tool in a project](#enable-the-ssh-tool-in-a-project)).

#### Steps

1. In a new session in the project, enter:

        Run the SSH tool's list-connections and show the result.

    The answer lists the `lab-vm` profile with its host and user.

2. Run a read-only command:

        On lab-vm, run the command uptime and show the output.

    The answer shows the output of `uptime` from the remote host.

3. Test the approval of a destructive command. First create a test file:

        On lab-vm, run: touch /home/agent/approval-test.txt

    Then ask for its removal:

        On lab-vm, run: rm /home/agent/approval-test.txt

    OpenCode shows a form that asks you to approve the command. Approve it once; the command runs.
    If no form appears, the command is refused with `APPROVAL_UNAVAILABLE`, and the file stays.

4. Ask for a command that the policy's denylist forbids:

        On lab-vm, run: midclt call system.info

    The command is refused without a prompt.

5. Exit OpenCode and check the audit log:

        ls -l ~/.local/share/ssh-mcp/
        tail -n 1 ~/.local/share/ssh-mcp/audit.log

    The last line is a JSON record of the last call.

#### Results

The agent reaches the allowed host with its own key, asks you before destructive commands, refuses
denied ones, and logs every call.

## Use OpenCode from the Mac

### Two ways to work from the Mac

Table: Ways to use the agent from the Mac

| Method | How | Choose it when |
|---|---|---|
| Log in to `c4dev` | `ssh` to `c4dev` and run `opencode` there | You work on repositories that live on `c4dev`. Nothing is installed on the Mac |
| Own CLI on the Mac | `clients/install.sh` on the Mac, against the same gateway | You work on files that live on the Mac |

In both cases nothing of OpenCode keeps running after you exit it. The Mac does not attach to a
server on `c4dev`, because that server is disabled
([Why the OpenCode service stays disabled](#why-the-opencode-service-stays-disabled)).

### Run OpenCode on c4dev from the Mac

#### Steps

1. In Terminal on the Mac, log in to `c4dev`:

        ssh <user>@192.0.2.20

2. Check that the login shell loaded the profile block:

        opencode --version && echo "${LAB_DOMAIN:-unset}"

    The output names version 2.3.0 and your domain. If it prints `unset`, load the profile with
    `. ~/.bashrc`.

3. Change to the repository and start OpenCode:

        cd <project>
        opencode

#### Results

The session runs on `c4dev` with its configuration, tools and SSH key. If the SSH connection
drops, the OpenCode process ends with it; log in again and run `opencode --continue` in the same
directory to resume the last session.

### Install OpenCode on the Mac

#### Prerequisites

- `git`, `curl`, `tar`, `openssl` and `python3` on the Mac.
- SSH access from the Mac to `c4dev`, which holds the Mac's LiteLLM key and the shared values of
  `client.env`.
- A LiteLLM virtual key for the Mac from Chapter 4, allowing the same models as the `c4dev` key.
- For the SSH tool: Node.js 20.6 or later and npm ([Install Node.js and npm](#install-nodejs-and-npm)).

#### About this task

The installer has a macOS path: it chooses the `darwin-arm64` or `darwin-x64` build of OpenCode
(Apple silicon also under Rosetta), puts the SSH policy in
`~/Library/Application Support/ssh-mcp/`, and adds the profile block to `~/.zshrc` when zsh is your
shell.

!!! note
    The macOS path of `clients/install.sh` is UNVERIFIED: the script is written for macOS but has
    not been run on a Mac for this release. Run the dry run first and read every line. The location
    of the `ssh-mcp` audit log on macOS is not verified either.

#### Steps

1. Clone the repository at the release tag:

        git clone --branch <release-tag> https://github.com/corytron/local-agent-stack.git ~/local-agent-stack

2. Create `client.env` as in [Create client.env](#create-clientenv), with these differences:

    - In step 3, display the Mac's own key, which is stored on `c4dev`:

            ssh <user>@192.0.2.20 cat .config/local-agent-stack/secrets/litellm-mac.key

    - The Mac has no copy of `web.env`. In step 4, take `LAB_DOMAIN` and `MCP_HUB_TOKEN` from the
      `client.env` of `c4dev` over SSH instead, and paste the Mac's key at the prompt:

            python3 tools/secrets.py gen client --share <(ssh <user>@192.0.2.20 cat .config/local-agent-stack/client.env) --ask LOCAL_LLM_KEY -o ~/.config/local-agent-stack/client.env

        The shell passes the output of `ssh` to the tool as a file; nothing is written to disk
        except the new `client.env`. Without SSH access to `c4dev`, let the tool prompt for all
        three values: `--ask LAB_DOMAIN --ask MCP_HUB_TOKEN --ask LOCAL_LLM_KEY` instead of
        `--share`.

    - Skip step 7, which compares the file with `web.env`. Step 5 of this task checks the values
      against the server.

3. Preview and run the installer:

        ~/local-agent-stack/clients/install.sh --dry-run
        ~/local-agent-stack/clients/install.sh

4. Open a new Terminal window and repeat the checks of [Run the installer](#run-the-installer)
   from step 3, with the macOS policy path
   `~/Library/Application Support/ssh-mcp/config.toml` in step 7.

5. Run the checks of [Check the client from the shell](#check-the-client-from-the-shell).

6. For the SSH tool, create a separate agent key on the Mac (`-C agent@mac` in
   [Create the agent key](#create-the-agent-key)), and on each remote host add a second
   `authorized_keys` line for it with `from="<mac-lan-ip>"`. Edit the policy at
   `~/Library/Application Support/ssh-mcp/config.toml`.

#### Results

The Mac runs its own OpenCode against `https://llm.lab.example.com`, with the same configuration as
`c4dev` and its own key.

## Use the Windows VM

### What the Windows VM supports

`clients/install.sh` supports Linux and macOS only; on any other system it stops with
`unsupported OS`. The Windows VM therefore uses the agent in one of these ways:

- Log in to `c4dev` over SSH and run `opencode` there (next task).
- Use Open WebUI at `https://chat.lab.example.com` in a browser for chat, retrieval and web search.

Running the installer inside the Windows Subsystem for Linux is not covered: the files of this
release neither detect nor document it, and it has not been tested.

### Run OpenCode on c4dev from Windows

#### Steps

1. On the Windows VM, open a terminal with an SSH client, for example PowerShell with the OpenSSH
   client, and log in to `c4dev`:

        ssh <user>@192.0.2.20

2. Check that the profile block is loaded:

        opencode --version && echo "${LAB_DOMAIN:-unset}"

    The output names version 2.3.0 and your domain. If it prints `unset`, run `. ~/.bashrc`.

3. Change to the repository and start OpenCode:

        cd <project>
        opencode

#### Results

The session runs on `c4dev` exactly as from the Mac. If the connection drops, log in again and
resume with `opencode --continue`.

## Use Claude Code against the local gateway

### How claude-local works

Claude Code can use the gateway through LiteLLM's Anthropic route, `/v1/messages`, with the model
names `local-opus`, `local-sonnet` and `local-haiku`. This keeps an existing `.claude/` setup
unchanged. Anthropic does not support routing Claude Code to non-Claude models through a gateway,
so treat this as a compatibility path; OpenCode remains the primary agent.

`claude-local` runs Claude Code against the gateway for one session and leaves your normal `claude`
command and `~/.claude/settings.json` on Anthropic. It does the following:

1. Reads `~/.config/local-agent-stack/client.env` and stops if `LAB_DOMAIN` or `LOCAL_LLM_KEY` is
   missing, or if `LAB_DOMAIN` contains anything other than letters, digits, dots and hyphens.
2. Stops if Claude Code (`claude`) is not installed.
3. Finds `settings.json` next to its own real path in the clone, and replaces `lab.example.com` in
   it with your `LAB_DOMAIN`.
4. Exports `CLAUDE_CODE_MAX_CONTEXT_TOKENS=65536`, because Claude Code's documentation asks for it
   in the environment that starts Claude Code.
5. Runs `claude --settings '<the settings>'` with every argument you gave.

The key reaches Claude Code only through the settings' `apiKeyHelper`, which reads the same
`client.env`.

!!! note
    `claude-local` reads `client.env` without exporting it, so that the commands Claude Code runs
    do not inherit the key. In a terminal where the installer's profile block has already exported
    `client.env`, they inherit it anyway. Use `--no-shell-rc` when you install, and load the values
    only where you need them, if that matters to you. Without the profile block, OpenCode and the
    hub tools of Claude Code need `MCP_HUB_TOKEN` and the other values exported by hand
    ([Add the hub tools to Claude Code](#add-the-hub-tools-to-claude-code)).

### Claude Code settings for the gateway

{{ include clients/claude-code/settings.json }}

Table: Claude Code settings for the gateway

| Setting | Value | Purpose |
|---|---|---|
| `ANTHROPIC_BASE_URL` | `https://llm.<LAB_DOMAIN>` | The gateway; LiteLLM serves `/v1/messages` |
| `ANTHROPIC_API_KEY` | Empty | A stale Anthropic key is not used |
| `apiKeyHelper` | Reads `LOCAL_LLM_KEY` from the environment or `client.env` | The LiteLLM key, never written into a settings file |
| `ANTHROPIC_DEFAULT_OPUS_MODEL`, `_SONNET_MODEL`, `_HAIKU_MODEL` | `local-opus`, `local-sonnet`, `local-haiku` | The `opus`, `sonnet` and `haiku` aliases; all three reach the same model, `local-haiku` with thinking off |
| `ANTHROPIC_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL` | `local-sonnet` | The main model and the subagent model |
| `CLAUDE_CODE_MAX_CONTEXT_TOKENS` | `65536` | The real window. Without it, Claude Code assumes 1,000,000 tokens for a model name it does not know and compacts far too late |
| `CLAUDE_CODE_MAX_OUTPUT_TOKENS` | `16384` | The default for unknown model names is 32,000 tokens, half of the window |
| `CLAUDE_CODE_ATTRIBUTION_HEADER` | `0` | The system prompt starts identically in every request, so the server's prompt cache is reused |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`, `DISABLE_TELEMETRY` | `1` | No telemetry, error reports or other traffic to Anthropic |
| `skipWebFetchPreflight` | `true` | WebFetch works without its domain check, which otherwise calls `api.anthropic.com` |

### Limits of Claude Code on local models

Table: Limits of Claude Code with the local gateway

| Item | Behavior |
|---|---|
| Support | Anthropic does not support Claude Code on non-Claude models. Pin the Claude Code version you tested (this release was researched with 2.1.325) and test again after every upgrade |
| New request fields | New releases can send request fields that the gateway rejects. If requests fail with `Extra inputs are not permitted`, set `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`, which also turns off MCP tool search |
| WebSearch | Not available: it is a server tool run by Anthropic. Use the hub's SearXNG tool instead ([Add the hub tools to Claude Code](#add-the-hub-tools-to-claude-code)) |
| Remote Control, fast mode, Advisor | Not available with a non-Anthropic base URL |
| Context | 65,536 tokens against 200,000 or more on Claude. Claude Code's first request alone carries 11,375 tokens (5,340 for OpenCode), so expect frequent compaction |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | Do not set it. It accepts only 100,000 to 1,000,000 tokens, so it cannot describe a 65,536-token window, although LiteLLM's Claude Code tutorial suggests it. `CLAUDE_CODE_MAX_CONTEXT_TOKENS` sets the window instead |
| Prompt caching | `cache_control` markers have no effect. llama-server reuses the unchanged start of the prompt by itself, from its slot and its prompt cache in host RAM; `CLAUDE_CODE_ATTRIBUTION_HEADER=0` keeps that start unchanged. Appendix C compares it with OpenCode ([Agent loop and context window](#agent-loop-and-context-window)) |
| Images and screenshots | Not available: the stack's models run without a vision projector (`--no-mmproj`), so they cannot read images ([Images and PDF reading](#images-and-pdf-reading)) |
| PDF documents | Not verified: whether llama.cpp accepts the PDF `document` blocks that Claude Code sends is unknown. Convert a PDF to text first, or put it in the knowledge base (Chapter 6) |
| Tool use | Weaker than on Claude: malformed arguments and loops are more common |
| `/cost` | Meaningless; LiteLLM's usage logs record tokens and durations per key |
| Subagents | Run two at a time, or three when one is a short read-only researcher; one GPU serves every agent ([Concurrency on one 16 GB GPU](#concurrency-on-one-16-gb-gpu)) |
| Guard rules | `guard.ts` and OpenCode's policies do not apply to Claude Code. Put the same rules into the project's `.claude/settings.json` hooks and permissions; the repository's `pre-push` hook still refuses pushes to `main` |

### Start Claude Code with claude-local

#### Prerequisites

- Claude Code is installed on the workstation. If it is not, install it with npm
  ([Install Node.js and npm](#install-nodejs-and-npm)) and pin the version you test:
  `npm install -g @anthropic-ai/claude-code@<version>`. If npm reports `EACCES` for its global
  directory, do not use `sudo`; set a prefix in your home directory first with
  `npm config set prefix ~/.local`, so that the command goes to `~/.local/bin`, which the profile
  block puts on `PATH`.
- The workstation's LiteLLM key allows `local-opus`, `local-sonnet` and `local-haiku`.
- `claude-local` is linked into `~/.local/bin` ([Run the installer](#run-the-installer)).

#### Steps

1. Check the installed Claude Code version:

        claude --version

    The output is the version you tested.

2. Check the launcher:

        command -v claude-local

    The output is `/home/<user>/.local/bin/claude-local`.

3. Run a headless request in a repository:

        claude-local -p "Reply with the word OK."

    The answer is `OK`.

4. Start an interactive session with `claude-local`, and run `/context`.

    The context usage is reported against a window of 65,536 tokens, not 1,000,000.

5. Exit the session and start `claude` without the launcher.

    Your normal Claude Code session uses Anthropic as before.

#### Results

Claude Code runs against the local gateway when you start it with `claude-local`, and against
Anthropic when you start it with `claude`.

### Add the hub tools to Claude Code

#### Prerequisites

- `MCP_HUB_TOKEN` is exported in the shell that starts `claude-local`. The installer's profile
  block exports it from `client.env`; `claude-local` itself reads `client.env` without exporting
  it. If you installed with `--no-shell-rc` and did not add the block, export the token alone in
  that shell, without printing it:

        export MCP_HUB_TOKEN="$(sed -n 's/^MCP_HUB_TOKEN=//p' ~/.config/local-agent-stack/client.env)"

    Check it with `echo "${MCP_HUB_TOKEN:+token-set}"`, which prints `token-set`.

#### About this task

Without WebSearch, Claude Code needs the hub's SearXNG tool for web search. The hub's servers are
plain MCP servers over HTTP with a bearer token, which Claude Code accepts in a project's
`.mcp.json` file. The file names the token as `${MCP_HUB_TOKEN}`, which Claude Code fills in from
its environment, so the token stays out of the file. Without the variable in the environment, the
hub servers do not connect.

!!! note
    This configuration is not part of the release files and was not tested against the hub through
    `claude-local`. Verify it with the last step before you rely on it.

#### Steps

1. In the root of the project, create `.mcp.json`. Replace `lab.example.com` with your domain:

        {
          "mcpServers": {
            "searxng": { "type": "http", "url": "https://mcp.lab.example.com/servers/searxng/mcp",
                         "headers": { "Authorization": "Bearer ${MCP_HUB_TOKEN}" } },
            "fetch":   { "type": "http", "url": "https://mcp.lab.example.com/servers/fetch/mcp",
                         "headers": { "Authorization": "Bearer ${MCP_HUB_TOKEN}" } },
            "kb":      { "type": "http", "url": "https://mcp.lab.example.com/servers/kb/mcp",
                         "headers": { "Authorization": "Bearer ${MCP_HUB_TOKEN}" } }
          }
        }

2. Keep the file out of a public repository, because it names your domain:

        echo '.mcp.json' >> .gitignore

3. Start `claude-local` in the project and run `/mcp`.

    The list shows `searxng`, `fetch` and `kb` as connected. If they fail to connect, check that
    `MCP_HUB_TOKEN` is exported (Prerequisites).

4. Ask Claude Code to search the web with the `searxng` server.

    The session shows a call to `searxng_web_search` and lists results.

#### Results

Claude Code searches the web, reads pages and queries the knowledge base through the hub.

## Trust the certificates

### Certificates from DNS-01

With the default configuration of Chapter 5, Caddy obtains a wildcard certificate for
`*.lab.example.com` from Let's Encrypt's production service through the DNS-01 challenge. The
certificate is publicly trusted, so the workstations need no extra certificate, and OpenCode,
Claude Code and `curl` connect without any option. This task only confirms it.

#### Steps

1. On the workstation, display the certificate that the gateway serves:

        echo | openssl s_client -connect llm.lab.example.com:443 -servername llm.lab.example.com 2>/dev/null | openssl x509 -noout -subject -issuer -enddate

    The subject is `CN=*.lab.example.com`, and the issuer is `O=Let's Encrypt` with no
    `(STAGING)` in its names.

2. Confirm that the workstation trusts the connection without options:

        curl -sS -o /dev/null -w '%{http_code}\n' https://llm.lab.example.com/health/liveliness

    The output is `200`, without a certificate error.

3. Repeat both steps on the Mac, if it runs its own OpenCode.

#### Results

The workstations trust the gateway's certificate. If the issuer names start with `(STAGING)`, the
edge app still uses Let's Encrypt's staging service, whose certificates no client trusts; complete
[Switch to the production CA](#switch-to-the-production-ca) before you continue.

### Certificates from the internal CA

With the internal certificate authority of Appendix D, Caddy signs the certificates itself, and
every workstation must trust its root certificate before OpenCode or Claude Code can connect.

#### Steps

1. Export the root certificate from TrueNAS as in
   [Export the root certificate from TrueNAS](#export-the-root-certificate-from-truenas).

2. Install it into the system store of each workstation:

    - `c4dev`: [Trust the root certificate on Ubuntu](#trust-the-root-certificate-on-ubuntu).
    - The Mac: [Trust the root certificate on macOS](#trust-the-root-certificate-on-macos).
    - The Windows VM needs it only for the browser:
      [Trust the root certificate on Windows](#trust-the-root-certificate-on-windows).

3. For Claude Code, which is a Node.js tool, add the certificate file to `client.env`, which the
   profile block exports:

        printf 'NODE_EXTRA_CA_CERTS=%s\n' "$HOME/caddy-root.crt" >> ~/.config/local-agent-stack/client.env

    Keep `caddy-root.crt` at that path. Open a new terminal afterwards. If you installed with
    `--no-shell-rc`, export the variable in your own profile instead.

4. Test OpenCode against the gateway:

        opencode models

    The three local models are listed without a certificate error.

5. Test Claude Code, if you use it:

        claude-local -p "Reply with the word OK."

    The answer is `OK`, without a certificate error.

#### Results

The workstations trust the internal CA, and the agents connect to the gateway and the hub. The SSH
tool does not use TLS and needs no certificate.

!!! note
    Whether OpenCode 2.3.0 reads the system trust store or `NODE_EXTRA_CA_CERTS` is not verified for
    this release. If step 4 reports a certificate error with both in place, use DNS-01 certificates
    (Chapter 5) instead of the internal CA.
