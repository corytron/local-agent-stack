title: Backup and restore
kind: appendix

# Backup and restore

This appendix describes how to protect the stack's data on TrueNAS SCALE 25.10 and how to bring it
back. ZFS snapshots on the server give fast, frequent restore points; replication copies them to a
second pool or a second TrueNAS system; nightly logical dumps of the two PostgreSQL databases add a
portable copy that restores into any newer PostgreSQL; and a configuration file restores the
TrueNAS settings themselves. The files that exist only on the workstation, such as the keys and
settings of `deploy.py` and the SSH tool, get an encrypted archive of their own.

Set up the tasks after you complete Chapter 3, and run the test restores at least once a month and
after every release update.

## Backup scope

Everything the stack writes lives in the datasets under `tank/ai` (Chapter 3). The model files are
large and can be downloaded again, so they are not backed up.

### Data to back up

Table: Backup scope

| Data | Location | Protection |
|---|---|---|
| Service state: both PostgreSQL databases, Open WebUI files, the sync history, Caddy's certificates and keys | `tank/ai/appdata` and its children | Daily snapshots kept 14 days, nightly PostgreSQL dumps, replication |
| Documents | `tank/ai/rag-docs` | Hourly snapshots kept 48 hours, replication |
| Repository clone | `tank/ai/stacks` | Daily snapshots kept 14 days, replication; the release tag on GitHub is a second copy |
| Secrets | `tank/ai/secrets` | Daily snapshots kept 14 days, replication; the copies in `~/.config/local-agent-stack/secrets/` on the workstation |
| TrueNAS settings: users, API keys, shares, tunables, init scripts, data protection tasks | TrueNAS configuration database | Configuration file downloaded before every update |
| Model files | `tank/ai/models` | Not backed up; download them again ([Download the model files](#download-the-model-files)) |
| Container images and app definitions | The hidden `ix-apps` dataset | Not backed up; images are pulled again and each app's YAML is four lines (Chapters 4 to 6) |
| Workstation files: `client.env`, the copies of the secrets files, the LiteLLM keys of the workstations, `desired.toml`, the settings and API keys of `deploy.py`, the SSH policy with its pinned host keys, the SSH tool's key, the evaluation results and baselines | `~/.config/local-agent-stack/`, `~/.config/ssh-mcp/`, `~/.ssh/` and the clone on the workstation | An encrypted archive after every change ([Workstation state](#workstation-state)) |

Restore the secrets from the same point in time as the databases. LiteLLM cannot read the
credentials in its database with a different `LITELLM_SALT_KEY`, and the PostgreSQL passwords are
fixed when each database is first created.

!!! warning
    Snapshots and replicas of `tank/ai/secrets` and `tank/ai/appdata` contain credentials: the
    gateway and database keys, Caddy's private keys and, with the internal CA of Appendix D, the
    root key that every client trusts. Replicate only to a system that you control and protect as
    well as this server, and use **SSH Transfer Security** with encryption for a remote target.

## Snapshot tasks

Periodic snapshot tasks take the restore points on the server itself. The tasks below cover every
dataset in the backup scope and leave out `tank/ai/models`. Do not create a recursive task on
`tank` or `tank/ai`: it would include the model files.

### Create the periodic snapshot tasks

#### About this task

A recursive snapshot task snapshots a dataset and all of its children at the same instant. Each
PostgreSQL data directory lies in one dataset, so its snapshot is consistent: PostgreSQL treats a
restored snapshot like a restart after a power loss and replays its write-ahead log. Keep the
default naming schema, `auto-%Y-%m-%d_%H-%M`; replication matches snapshots by this schema.

Table: Periodic snapshot tasks

| **Dataset** | **Recursive** | **Snapshot Lifetime** | **Schedule** |
|---|---|---|---|
| `tank/ai/appdata` | Selected | 14 Days | Daily |
| `tank/ai/rag-docs` | Cleared | 48 Hours | Hourly |
| `tank/ai/stacks` | Cleared | 14 Days | Daily |
| `tank/ai/secrets` | Cleared | 14 Days | Daily |

The **Daily** preset runs at 00:00 and the **Hourly** preset at the start of each hour, in the
system time zone.

#### Steps

1. Go to **Data Protection**.

2. On the **Periodic Snapshot Tasks** card, click **Add**.

3. Select the **Dataset** from the first row of the table, and set **Recursive** as shown.

4. Set **Snapshot Lifetime** to the number in the table and **Unit** to the unit in the table.

5. Keep **Naming Schema** `auto-%Y-%m-%d_%H-%M`, select the **Schedule** from the table, and keep
   **Enabled** selected.

6. Click **Save**.

7. Repeat steps 2 to 6 for the other rows of the table.

#### Results

The **Periodic Snapshot Tasks** card lists four tasks with their next run times.

### Verify the snapshots

#### Steps

1. After the next hourly run, list the newest snapshots under `tank/ai`:

        sudo zfs list -t snapshot -o name,creation -s creation -r tank/ai | tail -n 8

    The output shows `auto-...` snapshots of `tank/ai/rag-docs`. After 00:00, it also shows
    snapshots of `tank/ai/appdata` and each of its children, `tank/ai/stacks` and
    `tank/ai/secrets`, all with the same name.

2. Confirm that the model dataset has no snapshots:

        sudo zfs list -t snapshot -r tank/ai/models

    The output is `no datasets available`.

#### Results

Every dataset in the backup scope has restore points. In the web interface, select a dataset in
**Datasets** and click **View Snapshots** on its **Data Protection** card to see them.

## Replication to a second pool or system

A replication task copies the snapshots to another pool on this server or to another TrueNAS
system, and keeps sending only the changes. A second pool protects against the loss of `tank`; a
second system also protects against the loss of the server.

### Create a replication task

#### Prerequisites

- The periodic snapshot tasks exist and have run at least once.
- A destination: a second pool on this server (`backup` in this example), or a second TrueNAS
  system (`192.0.2.40` in this example) with an administrator account.

#### About this task

One task replicates the four datasets. TrueNAS places each source under the destination by its
path below the common parent `tank/ai`: with the destination `backup/ai`, the replicas are
`backup/ai/appdata` (with its children), `backup/ai/rag-docs`, `backup/ai/stacks` and
`backup/ai/secrets`. The task runs at 01:00, after the nightly database dumps and the 00:00
snapshots.

#### Steps

1. Go to **Data Protection**. On the **Replication Tasks** card, click **Add**.

    The **Replication Task Wizard** opens at **What and Where**.

2. Set **Source Location** to `On this System`.

3. In **Source**, select `tank/ai/appdata`, `tank/ai/rag-docs`, `tank/ai/stacks` and
   `tank/ai/secrets`.

    The wizard shows the number of existing snapshots for the selection.

4. Select **Recursive**.

5. Set **Destination Location**:

    - For a second pool on this server, select `On this System`.
    - For a second TrueNAS system, select `On a Different System`. In **SSH Connection**, select
      **Create New**. In the **New SSH Connection** form, enter a **Connection Name**, select
      **Setup Method** `Semi-automatic (TrueNAS only)`, enter the **TrueNAS URL**
      (`https://192.0.2.40`), the **Admin Username** and **Admin Password** of the destination,
      enter the **Username** that receives the replica (for example `truenas_admin`), select
      **Enable passwordless sudo for zfs commands**, select **Private Key** `Generate New`, and
      click **Save**. If the wizard offers **Use Sudo For ZFS Commands**, select it. Then set
      **SSH Transfer Security** to `Encryption (more secure, but slower)`.

6. Enter **Destination** `backup/ai`.

7. Enter a **Task Name**, for example `ai-to-backup`, and click **Next**.

    The wizard opens **When**.

8. Set **Replication Schedule** to `Run On a Schedule`. In **Schedule**, select **Custom**, set
   **Minutes** to `0` and **Hours** to `1`, and click **Done**.

9. Select **Make Destination Dataset Read-only?**.

10. Set **Destination Snapshot Lifetime** to `Same as Source`.

    For a longer history on the destination, select `Custom` and enter a number and unit instead.

11. Click **Save**.

#### Results

The **Replication Tasks** card lists the new task. It sends a full copy on its first run and only
changes afterwards.

### Verify the replica

#### Steps

1. On the **Replication Tasks** card, click the **Run job** icon (play button) of the task.

2. In the **Run Now** dialog, click **Continue**.

3. When the task has finished, list the replica. For a second system, run the command on that
   system:

        sudo zfs list -r -o name,used backup/ai

    The output shows `backup/ai/appdata` and its children, `backup/ai/rag-docs`,
    `backup/ai/stacks` and `backup/ai/secrets`.

4. Compare the newest snapshot names on the source and the destination:

        sudo zfs list -t snapshot -o name -s creation -r tank/ai/secrets | tail -n 1
        sudo zfs list -t snapshot -o name -s creation -r backup/ai/secrets | tail -n 1

    Run the second command on the destination system. Both show the same `auto-...` name.

#### Results

The replica is complete and current.

## PostgreSQL logical dumps

The stack has two PostgreSQL servers: `litellm-db` in the `ai-inference` app (database `litellm`,
user `litellm`) and `pgvector` in the `ai-rag` app (database `openwebui`, user `openwebui`, with
Open WebUI's vectors). A logical dump made with `pg_dump` restores into the same or a newer
PostgreSQL version, and lets you restore one database without rolling back a whole dataset.

The dumps go to `/mnt/tank/ai/appdata/pg-dumps`. Each run overwrites the previous dump; the daily
snapshots of `tank/ai/appdata` keep 14 days of dumps, and replication copies them off the server.
The official PostgreSQL images trust connections made inside the container over the local socket,
so `docker exec` needs no database password.

### Create the dump directory and the first dumps

#### Steps

1. Open **System** > **Shell** and refresh the `sudo` credentials, so that the commands in the
   pipes below do not prompt:

        sudo -v

2. Create the dump directory, readable only by root:

        sudo install -d -m 0700 /mnt/tank/ai/appdata/pg-dumps

3. Dump the LiteLLM database:

        sudo docker exec litellm-db pg_dump -U litellm -d litellm -Fc | sudo tee /mnt/tank/ai/appdata/pg-dumps/litellm-db.dump > /dev/null

4. Dump the Open WebUI database:

        sudo docker exec pgvector pg_dump -U openwebui -d openwebui -Fc | sudo tee /mnt/tank/ai/appdata/pg-dumps/pgvector.dump > /dev/null

5. Verify that each dump can be read:

        sudo cat /mnt/tank/ai/appdata/pg-dumps/litellm-db.dump | sudo docker exec -i litellm-db pg_restore --list | head -n 12
        sudo cat /mnt/tank/ai/appdata/pg-dumps/pgvector.dump | sudo docker exec -i pgvector pg_restore --list | head -n 12

    Each listing starts with the archive header, which names the database (`litellm` or
    `openwebui`), followed by the table of contents.

#### Results

Both databases have a current dump.

### Schedule the nightly dumps

#### About this task

A TrueNAS cron job runs its command with `sh -c` as the selected user. The commands below write
to a temporary file and rename it only when `pg_dump` succeeds, so a failed run never replaces a
good dump. The jobs run at 23:30, before the 00:00 snapshot of `tank/ai/appdata`.

Table: Cron jobs for the database dumps

| **Description** | **Command** |
|---|---|
| `pg_dump litellm-db` | The command in step 4 |
| `pg_dump pgvector` | The command in step 9 |

#### Steps

1. Go to **System** > **Advanced Settings**.

2. On the **Cron Jobs** card, click **Add**.

3. Enter **Description** `pg_dump litellm-db`.

4. Enter the following **Command** on one line:

        docker exec litellm-db pg_dump -U litellm -d litellm -Fc > /mnt/tank/ai/appdata/pg-dumps/litellm-db.dump.tmp && mv /mnt/tank/ai/appdata/pg-dumps/litellm-db.dump.tmp /mnt/tank/ai/appdata/pg-dumps/litellm-db.dump

5. Set **Run As User** to `root`.

6. In **Schedule**, select **Custom**, set **Minutes** to `30` and **Hours** to `23`, and click
   **Done**.

7. Keep **Hide Standard Output** selected, clear **Hide Standard Error** so that failures are
   reported, and keep **Enabled** selected.

8. Click **Save**.

9. Repeat steps 2 to 8 with **Description** `pg_dump pgvector` and the following **Command**:

        docker exec pgvector pg_dump -U openwebui -d openwebui -Fc > /mnt/tank/ai/appdata/pg-dumps/pgvector.dump.tmp && mv /mnt/tank/ai/appdata/pg-dumps/pgvector.dump.tmp /mnt/tank/ai/appdata/pg-dumps/pgvector.dump

10. The next morning, check the time stamps of the dumps:

        sudo ls -l /mnt/tank/ai/appdata/pg-dumps

    Both `.dump` files show a time of about 23:30 the previous evening, and no `.tmp` file remains.

#### Results

The databases are dumped every night, and the snapshots keep 14 days of dumps.

## TrueNAS configuration backup

The configuration database holds every TrueNAS setting that this guide makes in the web interface:
users and API keys, the SMB share, the tunable, the init script, the cron jobs and the data
protection tasks. It does not hold the data in the datasets.

### Back up the TrueNAS configuration

#### About this task

Download the configuration before every TrueNAS update and after you change settings. With the
password secret seed included, the file also restores the credentials that TrueNAS stores
encrypted.

!!! warning
    The configuration file with the secret seed contains password hashes and the key that decrypts
    the stored credentials. Store it encrypted, for example in a password manager, and never in
    the repository or the `rag-docs` share.

#### Steps

1. Go to **System** > **Advanced Settings**.

2. Click **Manage Configuration** > **Download File**.

    The **Save Configuration** dialog opens.

3. Select **Export Password Secret Seed**.

4. Click **Save**.

    The browser downloads the configuration file.

#### Results

The file is in the browser's download folder. Move it to encrypted storage. To restore it on a
reinstalled server, use **Manage Configuration** > **Upload File**.

## Workstation state

Some state of the stack exists only on the workstation. The snapshots and the replica of the
server do not contain it. The following table lists it, with what you lose without a backup and
how to recreate it. The OpenCode binary, the links that `clients/install.sh` places,
the check tools and the virtual environment of `deploy.py` are not in the list: their installation
tasks create them again.

Table: Workstation files to back up

| File or folder | Contents | Without a backup |
|---|---|---|
| `~/.config/local-agent-stack/secrets/` | Copies of `inference.env`, `rag.env`, `web.env` and `edge.env`; the LiteLLM keys of the workstations, such as `litellm-c4dev.key` | Copy the server files back from `/mnt/tank/ai/secrets` or its snapshots. Delete lost LiteLLM keys and create new ones ([Generate the workstation keys](#generate-the-workstation-keys)) |
| `~/.config/local-agent-stack/client.env` | The domain, this workstation's LiteLLM key and the MCP hub token | Create it again ([Create client.env](#create-clientenv)) |
| `~/.config/local-agent-stack/desired.toml` | Your desired state for `deploy.py`, with its `overrides` lines | Create it again ([Create your desired-state file](#create-your-desired-state-file)) |
| `~/.config/local-agent-stack/truenas.toml`, `truenas-ca.pem`, `truenas-read.key`, `truenas-apply.key` | The connection settings, the trusted certificate and the API keys of `deploy.py` | Create the settings again ([Create the connection settings](#create-the-connection-settings)); delete the lost keys in TrueNAS and create new ones ([Create the API keys and store them on the workstation](#create-the-api-keys-and-store-them-on-the-workstation)) |
| `~/.config/ssh-mcp/config.toml` (on a Mac, `~/Library/Application Support/ssh-mcp/config.toml`) | The SSH policy, with the pinned host key (`trustedHostKey`) of each remote host | Pin every host key again ([Pin the host key and edit the policy](#pin-the-host-key-and-edit-the-policy)) |
| `~/.ssh/agent_ed25519`, `~/.ssh/agent_ed25519.pub` | The SSH tool's key pair | Create a new key and replace the public key on every remote host ([Create the agent key](#create-the-agent-key), [Prepare the remote host](#prepare-the-remote-host)) |
| `~/.ssh/known_hosts` | The host keys that `ssh` accepted, including the server's | Confirm each host key again at the next login |
| `~/.local/share/ssh-mcp/` | The SSH tool's tamper-evident audit log | The record of past commands is lost |
| `evals/results/` and `evals/baselines/` in the clone `~/local-agent-stack` | Evaluation results and baselines; untracked in a clone that follows the release tags | Record new baselines ([Record an evaluation baseline](#record-an-evaluation-baseline)) |

Keep your own SSH key, `~/.ssh/id_ed25519`, with your other personal keys. Without it, add a new
public key to `truenas_admin` ([Add the workstation key to truenas_admin](#add-the-workstation-key-to-truenas_admin)).

!!! warning
    The archive holds every key of the stack: the gateway's master key, the database passwords, the
    DNS provider token, the TrueNAS API keys and the SSH tool's private key. Encrypt it with a
    strong passphrase, keep it in encrypted storage outside the workstation, and never place it in
    the repository or the `rag-docs` share.

### Back up the workstation files

#### About this task

The task writes the files of the table into one archive encrypted with a passphrase. Repeat it
after every change to them: a new key, a new host in the SSH policy, a new baseline. The commands
are for a Linux workstation such as `c4dev`. On a Mac, replace `.config/ssh-mcp` with
`"Library/Application Support/ssh-mcp"` in step 2, and leave out `--ignore-failed-read`, which
the Mac's `tar` does not accept, together with every folder that does not exist.

#### Steps

1. Change to your home directory:

        cd ~

2. Write the encrypted archive. `openssl` asks for the passphrase twice:

        tar -czf - --ignore-failed-read .config/local-agent-stack .config/ssh-mcp .ssh/agent_ed25519 .ssh/agent_ed25519.pub .ssh/known_hosts .local/share/ssh-mcp local-agent-stack/evals/results local-agent-stack/evals/baselines | openssl enc -aes-256-cbc -pbkdf2 -salt -out ~/workstation-backup-$(date +%F).tar.gz.enc

    `tar` warns about a folder that does not exist yet, such as `evals/baselines` before
    Chapter 9, and leaves it out.

3. List the archive's contents to check that it can be decrypted:

        openssl enc -d -aes-256-cbc -pbkdf2 -in ~/workstation-backup-$(date +%F).tar.gz.enc | tar -tzf - | head -n 20

    The list starts with `.config/local-agent-stack/` and its files.

4. Move the archive to encrypted storage outside the workstation, then delete the local copy:

        rm ~/workstation-backup-$(date +%F).tar.gz.enc

#### Results

An encrypted copy of the workstation's state is stored outside the workstation, and you know its
passphrase.

### Restore the workstation files

#### Prerequisites

- The workstation has a clone of the repository at the release that the server runs
  (`~/local-agent-stack`), and the software of Chapter 2
  ([Workstation requirements](#workstation-requirements)).
- The archive from [Back up the workstation files](#back-up-the-workstation-files), copied to the
  home directory as `<archive>`.

#### Steps

1. Restore the files with their permissions:

        cd ~
        openssl enc -d -aes-256-cbc -pbkdf2 -in <archive> | tar -xpzf -

2. Check the modes of the key files and of `client.env`:

        stat -c '%a %n' ~/.config/local-agent-stack/*.key ~/.config/local-agent-stack/client.env ~/.config/local-agent-stack/secrets/* ~/.ssh/agent_ed25519

    Each line starts with `600`.

3. Run the client installer again, so that it links the configuration and the commands and adds
   the profile block ([Run the installer](#run-the-installer)). It keeps the restored
   `client.env` and SSH policy:

        ~/local-agent-stack/clients/install.sh

4. Check the desired state of `deploy.py`:

        cd ~/local-agent-stack
        python3 tools/deploy.py --file ~/.config/local-agent-stack/desired.toml validate

    The output ends with `ok (4 apps, release <release-tag>, TrueNAS 25.10.8)`.

5. Delete the archive from the home directory:

        rm ~/<archive>

#### Results

The workstation has its keys, settings and evaluation baselines back. Check the connection to the
server with `deploy.py status` ([Check the connection with deploy.py status](#check-the-connection-with-deploypy-status))
and the client with a first request ([Check the client from the shell](#check-the-client-from-the-shell)).

## Restore procedures

Choose the smallest restore that fixes the problem: a file from a snapshot, one database from its
dump, one dataset from a snapshot, and only then the replica.

!!! caution
    A rollback or a database restore discards every change made after the restore point. Before
    you start, take a manual snapshot of the dataset you are about to change, for example
    `sudo zfs snapshot tank/ai/appdata/litellm-db@before-restore`, so that you can return to the
    current state.

### Restore files from a snapshot

#### About this task

Every dataset has a hidden `.zfs/snapshot` directory with one read-only folder per snapshot. The
directory does not appear in listings, but you can open it by its path.

#### Steps

1. List the snapshots of the dataset, for example `tank/ai/rag-docs`:

        sudo ls /mnt/tank/ai/rag-docs/.zfs/snapshot/

2. Copy the file back from the snapshot you need:

        sudo cp -a /mnt/tank/ai/rag-docs/.zfs/snapshot/<snapshot>/<file> /mnt/tank/ai/rag-docs/<file>

    Replace `<snapshot>` with a name from step 1, such as `auto-2026-11-14_09-00`, and `<file>`
    with the file's path inside the dataset.

3. Verify the restored file:

        sudo ls -l /mnt/tank/ai/rag-docs/<file>

#### Results

The file is back with its original ownership, permissions and time stamps. The same method
restores a single secrets file, for example
`/mnt/tank/ai/secrets/.zfs/snapshot/<snapshot>/web.env`, or an older database dump from
`/mnt/tank/ai/appdata/.zfs/snapshot/<snapshot>/pg-dumps/`.

### Restore a database from its dump

#### About this task

The restore replaces the contents of one database with the dump while the database server keeps
running. Stop the containers that use the database first, so that no client writes during the
restore.

Table: Database clients

| Database container | Clients to stop |
|---|---|
| `litellm-db` | `litellm` |
| `pgvector` | `open-webui`, `oikb` |

#### Steps

1. Stop the clients of the database, for example for `litellm-db`:

        sudo docker stop litellm

2. Refresh the `sudo` credentials:

        sudo -v

3. Restore the dump into the database:

        sudo cat /mnt/tank/ai/appdata/pg-dumps/litellm-db.dump | sudo docker exec -i litellm-db pg_restore -U litellm -d litellm --clean --if-exists

    For `pgvector`, use `pgvector.dump`, the container `pgvector`, and `-U openwebui -d openwebui`.

4. Start the clients again:

        sudo docker start litellm

5. Verify that the containers are healthy:

        sudo docker ps --filter name=litellm --format '{{.Names}} {{.Status}}'

    Each container shows `Up` and `(healthy)` once its health check has passed.

#### Results

The database holds the data of the dump. **Apps** > **Installed** shows the app as running again.

### Roll back a service dataset

#### About this task

A rollback returns a whole dataset to a snapshot, for example `tank/ai/appdata/open-webui` or
`tank/ai/appdata/pgvector` after a failed update. Every child of `tank/ai/appdata` has its own
snapshots with the same names, so you can roll back one service without touching the others. Stop
every app that uses the dataset first; for `pgvector`, stop both `ai-web` and `ai-rag`.

#### Steps

1. Go to **Apps** > **Installed**, select each app that uses the dataset, and click **Stop**.

2. Go to **Datasets**, select the dataset, and click **View Snapshots** on its **Data Protection**
   card.

3. Expand the snapshot to restore and click **Rollback**.

    The **Dataset Rollback From Snapshot** dialog opens.

4. Choose **Stop Rollback if Snapshots Exist**:

    - `Newer Intermediate, Child, and Clone` rolls back only to the newest snapshot.
    - `Newer Clone` also destroys the snapshots that are newer than the selected one.

5. Select **Confirm** and click **Rollback**.

6. Go to **Apps** > **Installed**, select each app you stopped, and click **Start**.

7. Verify that the containers are healthy:

        sudo docker ps --format '{{.Names}} {{.Status}}'

#### Results

The service runs with the data of the snapshot.

### Restore from the replica

#### About this task

Use the replica when the snapshots on `tank` are lost, or to rebuild the server. The **Restore**
action of a replication task creates a new task that copies the replica back to a dataset that you
name. Restore into a new location first, then copy or move the data into place.

#### Steps

1. Go to **Data Protection**. On the **Replication Tasks** card, click the **Restore** icon of the
   `ai-to-backup` task.

    The **Restore Replication Task** dialog opens.

2. Enter **Name** `restore-ai` and **Destination** `tank/restore/ai`, and click **Restore**.

3. On the **Replication Tasks** card, click the **Run job** icon of `restore-ai` and click
   **Continue**.

4. When the task has finished, verify the restored datasets:

        sudo zfs list -r -o name,used,readonly tank/restore/ai

    If `readonly` is `on` for a dataset you need to change, turn it off, for example
    `sudo zfs set readonly=off tank/restore/ai/rag-docs`.

5. Copy the data you need into place with the apps stopped, for example the documents:

        sudo cp -a /mnt/tank/restore/ai/rag-docs/. /mnt/tank/ai/rag-docs/

6. When you no longer need the restored copy, delete the `restore-ai` task and the
   `tank/restore` dataset.

#### Results

The data from the replica is back on `tank`.

To rebuild a server from scratch, work in this order: install TrueNAS 25.10 and upload the
configuration file (**System** > **Advanced Settings** > **Manage Configuration** > **Upload
File**), which brings back the users, API keys, share, tunable, init script and tasks; create the
pool `tank` with the datasets `tank/ai` and `tank/ai/models` (Chapter 3); restore the replica as in
steps 1 to 4; move each restored dataset into place, for example
`sudo zfs rename tank/restore/ai/appdata tank/ai/appdata`, and turn `readonly` off; create the
`ai-net` network ([Create the shared Docker network](#create-the-shared-docker-network)); then
download the models ([Download the model files](#download-the-model-files)) and install the apps
in the order of Chapters 4 to 6: `ai-inference`, `ai-edge`, then `ai-rag` and `ai-web`.

## Test restores

A backup that has never been restored is not proven. Run these tests monthly and after every
release update. None of them changes the running stack.

### Test-restore a database dump

#### About this task

The test restores the latest dump into a scratch database in the same container, compares the
number of tables with the live database, and deletes the scratch database.

#### Steps

1. Refresh the `sudo` credentials:

        sudo -v

2. Create a scratch database:

        sudo docker exec litellm-db createdb -U litellm restore_test

3. Restore the dump into it:

        sudo cat /mnt/tank/ai/appdata/pg-dumps/litellm-db.dump | sudo docker exec -i litellm-db pg_restore -U litellm -d restore_test --no-owner

4. Count the tables in the scratch database and in the live database:

        sudo docker exec litellm-db psql -U litellm -d restore_test -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
        sudo docker exec litellm-db psql -U litellm -d litellm -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"

    Both commands print the same number, greater than zero.

5. Delete the scratch database:

        sudo docker exec litellm-db dropdb -U litellm restore_test

6. Repeat steps 2 to 5 for `pgvector`, with `pgvector.dump` and `-U openwebui`, and compare with
   the database `openwebui`.

#### Results

Both dumps restore completely.

### Test-restore files from a snapshot and the replica

#### Steps

1. Compare the secrets files with yesterday's snapshot:

        sudo ls /mnt/tank/ai/secrets/.zfs/snapshot/
        sudo diff -r /mnt/tank/ai/secrets/.zfs/snapshot/<snapshot> /mnt/tank/ai/secrets

    The `diff` command prints nothing when the files have not changed since the snapshot.

2. Check that the newest snapshot on the replica matches the source, as in
   [Verify the replica](#verify-the-replica).

3. Check that the configuration file of the last update is in your encrypted storage.

#### Results

The snapshots, the replica and the configuration file are usable for a restore.
