title: Uninstalling the stack

# Uninstalling the stack

This chapter removes the stack from the TrueNAS server and the workstations. You decide which data
to keep, revoke the keys while the services still run, delete the four apps and the shared network,
keep or destroy the datasets, revoke the remaining keys and tokens, undo the TrueNAS settings that
Chapter 3 made, and clean up each workstation.

Perform the tasks in the order shown. Run TrueNAS commands in **System** > **Shell** or in an SSH
session as `truenas_admin`; commands that start with `sudo` prompt for the `truenas_admin` password.

!!! caution
    Destroying the datasets deletes your documents in the `rag-docs` share, every chat and
    knowledge base of Open WebUI, the gateway's keys and usage logs, and the certificates. The
    snapshots of a dataset are destroyed with it. Decide what to keep before you start, and take the
    final backup in [Take a final backup](#take-a-final-backup).

## Before you uninstall

### Decide what to keep

Table: Data of the stack

| Dataset | Contents | Keep it when |
|---|---|---|
| `tank/ai/rag-docs` | The documents in the `rag-docs` share | The documents are yours and exist nowhere else |
| `tank/ai/appdata/pgvector` | Open WebUI's users, chats, knowledge bases and vectors | You may reinstall the stack and want the chats and indexes back |
| `tank/ai/appdata/litellm-db` | LiteLLM's virtual keys, budgets and usage logs | You may reinstall and keep the keys |
| `tank/ai/appdata/open-webui`, `oikb`, `caddy` | Uploaded files, the sync history, certificates and the ACME account | Together with `pgvector` and `litellm-db` |
| The folders `llama-swap`, `benchmarks` and `pg-dumps` in `tank/ai/appdata` | The override file and configuration copy of the `coder` fallback (the internal CA's files are in `caddy`), the benchmark baselines of Chapter 9, and the database dumps | You want the measurements or the dumps |
| `tank/ai/secrets` | The four environment files `inference.env`, `rag.env`, `web.env` and `edge.env` | With the application data: the databases only open with their original passwords and keys |
| `tank/ai/models` | The model files, about 36 GB | You will reinstall soon and want to skip the downloads |
| `tank/ai/stacks` | The clone of this repository, and `desired.toml` if you set up the drift cron job | Never needed; the release is on GitHub |

To reinstall later on kept datasets, follow the deployment chapters again with the same secrets
files. Never generate new secrets for kept data: `LITELLM_SALT_KEY`, `WEBUI_SECRET_KEY` and the
database passwords must match the data.

### Take a final backup

#### Steps

1. Download the TrueNAS configuration file, as in
   [Back up the TrueNAS configuration](#back-up-the-truenas-configuration).

2. Dump both databases, as in the first task of Appendix A:

        sudo -v
        sudo install -d -m 0700 /mnt/tank/ai/appdata/pg-dumps
        sudo docker exec litellm-db pg_dump -U litellm -d litellm -Fc | sudo tee /mnt/tank/ai/appdata/pg-dumps/litellm-db.dump > /dev/null
        sudo docker exec pgvector pg_dump -U openwebui -d openwebui -Fc | sudo tee /mnt/tank/ai/appdata/pg-dumps/pgvector.dump > /dev/null

3. If you will destroy the datasets, copy what you want to keep off the server first, for example
   the documents and the dumps to the workstation:

        ssh -t truenas_admin@192.0.2.10 'sudo tar -C /mnt/tank/ai -czf /tmp/las-final.tar.gz rag-docs appdata/pg-dumps secrets && sudo chown truenas_admin /tmp/las-final.tar.gz'
        scp truenas_admin@192.0.2.10:/tmp/las-final.tar.gz ~/
        ssh truenas_admin@192.0.2.10 'rm /tmp/las-final.tar.gz'

    The archive holds the secrets files. Store it encrypted.

4. Verify the archive on the workstation:

        tar -tzf ~/las-final.tar.gz | head

    The listing starts with `rag-docs/`, `appdata/pg-dumps/` or `secrets/` entries.

!!! warning
    The archive and the configuration file contain keys and password hashes. Keep them in encrypted
    storage, never in a repository or a shared folder.

### Stop the scheduled jobs

#### About this task

Remove the jobs that would act on the stack while you remove it: the drift check, which would
report every removed app, and the nightly database dumps, which would fail. From here on, do not run
`tools/deploy.py apply`: it creates every app that your desired-state file names and the server
lacks.

#### Steps

1. Go to **System** > **Advanced Settings**.

2. On the **Cron Jobs** card, delete the jobs `deploy.py drift`, `pg_dump litellm-db` and
   `pg_dump pgvector`, if they exist.

3. If you will destroy the datasets, go to **Data Protection** and delete the periodic snapshot
   tasks of `tank/ai/appdata`, `tank/ai/rag-docs`, `tank/ai/stacks` and `tank/ai/secrets`, and the
   replication task `ai-to-backup`. If you keep the datasets, keep the tasks.

#### Results

No job of the stack runs any more. The workstation has none to remove: the stack schedules nothing
there.

## Removing the apps

### Revoke the gateway and Open WebUI keys

#### About this task

The keys live in the databases. If you destroy `tank/ai/appdata/litellm-db` and
`tank/ai/appdata/pgvector`, they disappear with them and you can skip this task. If you keep the
datasets, delete the keys now, while the services run, so that a later reinstall does not bring
back keys that clients still hold.

#### Steps

1. On TrueNAS, delete the workstation keys by their aliases (`c4dev`, `mac` and any other alias
   you created). The command runs inside the `litellm` container and takes the master key from the
   container's own environment, so the key never appears on the command line:

        sudo docker exec litellm python3 -c "import json, os, urllib.request as u; body = json.dumps({'key_aliases': ['c4dev', 'mac']}).encode(); req = u.Request('http://127.0.0.1:4000/key/delete', data=body, headers={'Authorization': 'Bearer ' + os.environ['LITELLM_MASTER_KEY'], 'Content-Type': 'application/json'}); print(u.urlopen(req).read().decode())"

    The response lists the deleted keys under `deleted_keys`.

2. Delete the key of Open WebUI, whose value is in `web.env`:

        K=$(sudo sed -n 's/^LITELLM_WEBUI_KEY=//p' /mnt/tank/ai/secrets/web.env)
        sudo docker exec litellm python3 -c "import json, os, sys, urllib.request as u; body = json.dumps({'keys': [sys.argv[1]]}).encode(); req = u.Request('http://127.0.0.1:4000/key/delete', data=body, headers={'Authorization': 'Bearer ' + os.environ['LITELLM_MASTER_KEY'], 'Content-Type': 'application/json'}); print(u.urlopen(req).read().decode())" "$K"
        unset K

3. In Open WebUI, sign in as the administrator and delete the service users `indexer` and
   `kb-reader` in **Admin Panel** > **Users**. Their API keys, `OIKB_TOKEN` and `KB_READER_TOKEN`,
   stop working with them.

!!! note
    The `/key/delete` endpoint was not checked against LiteLLM 1.108.8 for this guide. If a deleted
    key still lists the models (test it as in [Verify a LiteLLM key](#verify-a-litellm-key)), revoke
    it in the Admin UI at `https://llm.lab.example.com/ui`, which signs in with the master key.

### Delete the apps

#### About this task

Delete the apps in the reverse order of installation: `ai-edge` first, so that nothing is reachable
from the LAN any more, then `ai-web`, `ai-rag` and `ai-inference`. `tools/deploy.py` never deletes
an app, so the apps are deleted in the web interface. Deleting a custom app stops and removes its
containers. The stack keeps no data in app volumes inside TrueNAS's `ix-apps` dataset,
so deleting an app does not delete data on the `tank/ai` datasets.

#### Steps

1. Go to **Apps** > **Installed** and select `ai-edge`.

2. Delete the app and confirm.

3. Wait until `ai-edge` has disappeared from the list.

4. Repeat steps 1 to 3 for `ai-web`, `ai-rag` and `ai-inference`, in that order.

5. Verify that no container of the stack remains:

        sudo docker ps -a --format '{{.Names}}' | grep -E '^(llama-swap|litellm|litellm-db|pgvector|docling|oikb|open-webui|searxng|mcp-hub|caddy|gpu-exporter)$'

    The command prints nothing.

#### Results

The four apps are gone from **Apps** > **Installed**, and no container of the stack runs.

!!! note
    The location of the delete action on the app's page in TrueNAS 25.10.8, and the options of its
    confirmation dialog, were not verified for this guide. If the dialog offers to remove the app's
    images, you can select it; the next task removes the images otherwise.

### Remove the stack's images

#### About this task

TrueNAS keeps the pulled images in the `ix-apps` dataset after the apps are deleted. Remove the
stack's images to free the space. Docker refuses to remove an image that a container still uses,
so an image that another app shares stays.

#### Steps

1. List the images of the stack:

        sudo docker image ls --format '{{.ID}} {{.Repository}}:{{.Tag}}' | grep -E 'llama-swap|berriai/litellm|postgres|pgvector|docling-serve|oikb|open-webui|searxng|local-agent-stack|nvidia_gpu_exporter'

    Check the list: `postgres` can also belong to another app.

2. Remove each image of the stack by its ID:

        sudo docker image rm <image-id>

3. If you ran the GPU test of Chapter 3 or a benchmark with `--oneoff`, check for their images too:

        sudo docker image ls | grep -E 'nvidia/cuda'

#### Results

The stack's images are removed.

### Remove the ai-net network

#### Steps

1. Check that no container is attached to the network:

        sudo docker network inspect ai-net --format '{{range .Containers}}{{println .Name}}{{end}}'

    The command prints nothing. If it lists a container of another app, that app joined `ai-net`;
    move it to another network first, or keep `ai-net`.

2. Remove the network:

        sudo docker network rm ai-net

3. Verify:

        sudo docker network ls --filter name=ai-net

    The output shows only the header line.

## Removing the data

### Keep the datasets

If you keep the datasets, do nothing more with them. They stay on the pool with their snapshots,
and the SMB share `rag-docs` keeps working. Keep `tank/ai/secrets` restricted to root (mode 0700).
Continue with [Revoking keys and tokens](#revoking-keys-and-tokens).

### Destroy the datasets

#### Prerequisites

- The final backup is complete and copied off the server, if you need it.
- The apps are deleted and the periodic snapshot and replication tasks of the datasets are removed.

#### About this task

Delete the `rag-docs` share first, so that TrueNAS has no share that points at a dataset that no
longer exists, then delete the parent dataset `tank/ai` with all of its children. To keep one
dataset, such as `tank/ai/rag-docs`, delete the other children one by one instead of the parent.

!!! caution
    Deleting a dataset destroys its data and all of its snapshots. It cannot be undone. A replica
    on another pool or system (Appendix A) is not affected; delete it there separately if you want
    it gone too.

#### Steps

1. Go to **Shares** > **Windows (SMB) Shares**, delete the `rag-docs` share and confirm.

2. If no other share uses SMB, go to **System** > **Services**, turn off **Start Automatically** on
   the **SMB** row, and stop the service.

3. Go to **Datasets** and select `tank/ai`.

4. Delete the dataset. TrueNAS lists the child datasets and asks you to type the dataset's name to
   confirm; type it and confirm.

5. Verify in **System** > **Shell**:

        sudo zfs list -r tank/ai

    The output reports that the dataset does not exist.

#### Results

The stack's data is gone from the pool.

!!! note
    The labels of the delete actions for shares and datasets in TrueNAS 25.10.8 were not verified
    for this guide.

## Revoking keys and tokens

### Revoke the TrueNAS API keys and deploy users

#### Steps

1. Go to **Credentials** > **Users** and select `deploy-apply`.

2. On the **Access** card, open **View API Keys** and delete the key `deploy-apply-c4dev`.

3. Repeat steps 1 and 2 for `deploy-read` and its key `deploy-read-c4dev`.

4. Delete the users `deploy-apply` and `deploy-read` in **Credentials** > **Users**.

5. If you created an SMB user only for the `rag-docs` share, delete it as well.

6. On the workstation, delete the key files and the connection settings:

        rm -f ~/.config/local-agent-stack/truenas-read.key ~/.config/local-agent-stack/truenas-apply.key ~/.config/local-agent-stack/truenas.toml ~/.config/local-agent-stack/truenas-ca.pem

7. Verify on the workstation:

        ls ~/.config/local-agent-stack/

    The listing shows no `truenas-*` file.

#### Results

No API key of the stack exists any more on the server or the workstation.

### Revoke the DNS provider token and records

#### Steps

1. In the Cloudflare dashboard, open the list of API tokens of your profile and delete the token
   you created for Caddy. For another provider, revoke the credentials listed in
   `DNS_PROVIDER_TOKEN` (and `DNS_PROVIDER_KEY_ID`, `DNS_PROVIDER_CONSUMER_KEY` where used) in that
   provider's console.

2. In the DNS zone of your domain at the provider, check for leftover TXT records named
   `_acme-challenge` and delete them. Caddy normally removes them after each challenge.

3. In your local DNS server or router, delete the A records of `chat`, `llm`, `models`, `mcp` and
   `search` under your domain.

4. Verify on the workstation:

        getent hosts chat.lab.example.com

    The command prints nothing.

!!! note
    The Cloudflare dashboard labels were not verified for this guide. Certificates that Caddy
    obtained stay valid until they expire; with the private keys gone from the `caddy` dataset,
    nobody can use them.

### Remove SSH keys

#### Steps

1. If the workstation no longer needs shell access to TrueNAS, go to **Credentials** > **Users**,
   edit `truenas_admin`, remove the workstation's line from **Public SSH Key**, and click **Save**.

2. If no other task needs SSH, go to **System** > **Services**, turn off **Start Automatically** on
   the **SSH** row and stop the service. Keep it running if you administer TrueNAS over SSH.

3. On each host that the SSH tool reached, remove the agent key's line from the `authorized_keys`
   file of the `agent` user (the line that starts with `restrict,from="192.0.2.20"` and ends with
   `agent@c4dev`), and delete the `agent` user if you created it only for the tool.

4. On the workstation, delete the agent's key pair:

        rm -f ~/.ssh/agent_ed25519 ~/.ssh/agent_ed25519.pub

## Restoring TrueNAS settings

These tasks undo the settings of Chapter 3. Keep any setting that another app or workload still
needs, such as the NVIDIA driver for another GPU app.

### Remove the GPU Post Init command

#### Steps

1. Go to **System** > **Advanced Settings**.

2. On the **Init/Shutdown Scripts** card, delete the entry `GPU persistence mode`.

    Persistence mode and any power limit stay in effect until the next restart, then return to the
    defaults.

### Remove the ARC tunable

#### Steps

1. Go to **System** > **Advanced Settings**.

2. On the **Sysctl** card, delete the entry `zfs_arc_max`.

    The cap is lifted at the next restart.

### Turn off the NVIDIA driver

#### About this task

Turn off the driver only if no other app on the server uses the GPU. Saving the setting restarts
Docker, and every installed app restarts with it.

#### Steps

1. Go to **Apps** > **Installed** and click **Configuration** > **Settings**.

2. Clear **Install NVIDIA Drivers** and click **Save**.

3. Verify:

        midclt call docker.config

    The output contains `"nvidia": false`.

### Return the web interface to ports 80 and 443

#### About this task

This task is optional. Ports 80 and 443 are free again now that `caddy` is gone.

#### Steps

1. Go to **System** > **General Settings**, and on the **GUI** card click **Settings**.

2. Set **Web Interface HTTP Port** to `80` and **Web Interface HTTPS Port** to `443`, and click
   **Save**.

3. In the **Restart Web Service** dialog, select **Confirm** and click **Continue**.

4. Open `https://192.0.2.10` and update your bookmarks.

### Restart and verify the server

#### Steps

1. In the top toolbar, click the power icon, click **Restart**, and confirm.

2. After the restart, check the ARC cap:

        cat /sys/module/zfs/parameters/zfs_arc_max

    The output is no longer `12884901888` (or the value you set).

3. Check that the Post Init command, the tunable and the cron jobs are gone: the **Init/Shutdown
   Scripts**, **Sysctl** and **Cron Jobs** cards of **System** > **Advanced Settings** list no entry
   of the stack.

## Cleaning up the workstation

`clients/install.sh` has no uninstall option. The tasks below remove what it created, the
`deploy.py` environment and the stack's files on the workstation. Repeat them on every workstation
that ran the clients, such as the Mac.

### Remove OpenCode and the links

#### Steps

1. Remove the links that `clients/install.sh` created in the OpenCode configuration directory:

        find ~/.config/opencode -type l -lname "$HOME/local-agent-stack/clients/*" -print -delete

    The command prints each link it removes: `opencode.jsonc`, the four agents, the four commands
    and `plugins/guard.ts`. If your clone is elsewhere, use its path in the pattern.

2. Restore any file of yours that the script kept, if you want it back. The script kept them as
   `<name>.bak.<time>`:

        find ~/.config/opencode -name '*.bak.*'

3. Remove the launchers:

        rm -f ~/.local/bin/ssh-mcp-stdio ~/.local/bin/claude-local

4. Remove the OpenCode binary that the script installed, with the copies it kept:

        rm -f ~/.opencode/bin/opencode ~/.opencode/bin/opencode.bak.*

    If you use OpenCode for other work, keep the binary and remove only the links.

5. Remove ssh-mcp, the `deploy.py` environment and the check tools:

        rm -rf ~/.local/share/local-agent-stack

6. Remove the SSH tool's policy file and its audit log:

        rm -rf ~/.config/ssh-mcp ~/.local/share/ssh-mcp

    On macOS, the policy file is in `~/Library/Application Support/ssh-mcp/`.

### Remove the shell profile block

#### About this task

`clients/install.sh` added a marked block to `~/.bashrc`, `~/.zshrc` or `~/.profile`, depending on
your shell. It loads `client.env` into every shell and puts the OpenCode and launcher directories
on `PATH`. The block reads:

{{ include clients/install.sh lines=344-354 }}

#### Steps

1. Open the profile file in a text editor and delete every line from
   `# >>> local-agent-stack (clients/install.sh) >>>` to `# <<< local-agent-stack <<<`,
   both included.

2. Verify that the block is gone:

        grep -n 'local-agent-stack' ~/.bashrc ~/.zshrc ~/.profile 2>/dev/null

    The command prints nothing.

3. Open a new terminal.

### Remove the stack's files from the workstation

#### Steps

1. Delete the client settings, the copies of the server's secrets files and your desired-state
   file:

        rm -rf ~/.config/local-agent-stack

    This removes `client.env` with your gateway key and hub token (and the `EVAL_KB_ID` and
    `EVAL_KB_KEY` lines, if you left them there), `desired.toml`, and
    `~/.config/local-agent-stack/secrets/` with the copies of the four environment files and the
    stored workstation keys `litellm-c4dev.key` and `litellm-mac.key`.

2. Delete the release downloads and the diagnostics, if you created them:

        rm -rf ~/releases ~/diag-*.txt

3. Delete the clone of the repository, after you saved any work in it. Your evaluation results
   and baselines of Chapter 9 are in its `evals/results/` and `evals/baselines/` directories; copy
   them elsewhere first if you want to keep them:

        rm -rf ~/local-agent-stack

4. If you kept raw model answers with `--save-responses`, delete that directory too, for example:

        rm -rf /tmp/eval-responses

### Remove the internal root certificate

#### About this task

Only for the internal CA of Appendix D: remove the Caddy root certificate from every client that
trusts it. Its private key was destroyed with the `caddy` dataset; if you kept that dataset, the
root still works for anyone who holds a copy of `root.key`.

#### Steps

1. On Ubuntu:

        sudo rm /usr/local/share/ca-certificates/caddy-local-root.crt
        sudo update-ca-certificates --fresh

2. On macOS:

        sudo security delete-certificate -c "Caddy Local Authority" /Library/Keychains/System.keychain

3. On Windows, in Command Prompt as administrator; the certificate's subject starts with
   `Caddy Local Authority`:

        certutil -delstore ROOT "Caddy Local Authority - <year> ECC Root"

4. In Firefox, delete the certificate under **Privacy & Security** > **Certificates** > **View
   Certificates** > **Authorities**, and remove any `NODE_EXTRA_CA_CERTS` or `REQUESTS_CA_BUNDLE`
   setting that names the file outside `client.env`.

5. Delete the copies of the certificate file:

        rm -f ~/caddy-root.crt

### Verify the workstation cleanup

#### Steps

1. In a new terminal, check that the commands are gone:

        command -v opencode claude-local ssh-mcp-stdio

    The command prints nothing.

2. Check that no link into the old clone remains:

        find ~/.config/opencode -xtype l

    The command prints nothing.

3. Check that no variable of the stack is set:

        env | grep -E '^(LAB_DOMAIN|LOCAL_LLM_KEY|MCP_HUB_TOKEN|EVAL_KB_ID|EVAL_KB_KEY)='

    The command prints nothing.

#### Results

The workstation holds nothing of the stack: no binary, link, setting, key or scheduled job.
