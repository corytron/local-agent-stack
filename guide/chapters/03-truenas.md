title: Preparing TrueNAS SCALE

# Preparing TrueNAS SCALE

This chapter prepares the TrueNAS SCALE server for the stack. You confirm the release, turn on
the NVIDIA driver that ships with TrueNAS, set the GPU and memory parameters, create the datasets
and the document share, create the shared Docker network, place a copy of the repository on the
pool, check that ports 80 and 443 are free for the edge proxy, place the secrets on the pool, and
create the API keys that `tools/deploy.py` uses. The TrueNAS web interface keeps ports of its own;
it moves only if it holds port 80 or 443.

Perform the tasks in the order shown. Run TrueNAS commands in **System** > **Shell** in the web
interface, or in an SSH session from the workstation as `truenas_admin`. Commands that start with
`sudo` prompt for the `truenas_admin` password. Every setting in this chapter is made through the
web interface or stored on the pool, so it survives TrueNAS updates; changes made to the operating
system by other means (packages, edits under `/etc` or `/usr`) are lost at the next update.

Table: Values used in this chapter

| Value | Meaning |
|---|---|
| `192.0.2.10` | LAN address of the TrueNAS server |
| `192.0.2.20` | LAN address of the workstation `c4dev` |
| `tank` | The pool that holds the apps and the stack's datasets |
| `<release-tag>` | The release of this guide, for example `v1.0` |
| `<smb-user>` | The SMB user that copies documents to the `rag-docs` share |
| `<ui-https-port>` | The HTTPS port of the TrueNAS web interface; `444` in this guide's examples |
| `<ui-http-port>` | The HTTP port of the TrueNAS web interface; `81` in this guide's examples |

## Verify the TrueNAS release

The stack requires TrueNAS SCALE 25.10.6 or later in the 25.10 "Goldeye" series. Release 25.10.6
is the first 25.10 build that ships NVIDIA driver 580.173.02; builds 25.10.0 to 25.10.5 ship driver
570.172.08. This guide is written for 25.10.8.

### Check the installed TrueNAS version

#### About this task

The NVIDIA driver version decides which container images can start: driver branch 580 supports
CUDA 13.0 and older, and the stack's GPU image is built on CUDA 12.8. Confirm the release before
you change anything else.

#### Steps

1. Log in to the TrueNAS web interface and open **Dashboard**.

    The **System Information** card shows the installed version.

2. Open **System** > **Shell** and run the following command:

        midclt call system.version

    The output is the version string, for example `TrueNAS-25.10.8`.

3. If the version is older than 25.10.6, save a configuration backup (see
   [Back up the TrueNAS configuration](#back-up-the-truenas-configuration)), then update the
   server in **System** > **Update** before you continue.

#### Results

The server runs TrueNAS 25.10.6 or later, preferably 25.10.8.

!!! note
    TrueNAS 27 (formerly announced as 26) was a release candidate when this guide was written.
    It removes the REST API and changes Docker to version 29. Stay on 25.10 for this deployment
    and move to 27 only after its first maintenance release, after you check that every image
    still fits the CUDA version of the driver that 27 ships.

## Enable SSH access to TrueNAS

The workstation copies files to the server and runs commands on it over SSH. If
`ssh truenas_admin@192.0.2.10` from the workstation already works with a key (pre-deployment
checklist in Chapter 2), skip this topic.

### Add the workstation key to truenas_admin

#### Prerequisites

The workstation has an SSH key pair. If `~/.ssh/id_ed25519.pub` does not exist, create one with
`ssh-keygen -t ed25519`.

#### Steps

1. On the workstation, display the public key and copy the whole line:

        cat ~/.ssh/id_ed25519.pub

2. In the TrueNAS web interface, go to **Credentials** > **Users** and select `truenas_admin`.

3. Click **Edit**.

4. Under **Allow Access**, select **SSH Access**.

5. In **Public SSH Key**, paste the key line. Leave **Allow SSH Login with Password (not
   recommended)** cleared.

6. Click **Save**.

#### Results

`truenas_admin` holds the workstation's public key and is allowed to log in over SSH. The login is
verified in step 4 of the next task, once the SSH service runs.

### Start the SSH service

#### Steps

1. Go to **System** > **Services**.

2. On the **SSH** row, turn on **Start Automatically**.

3. If the **Status** of SSH is not running, click the **Start Service** button (play icon) on the
   row.

4. On the workstation, run the following command:

        ssh truenas_admin@192.0.2.10 hostname

    On the first connection, SSH asks you to confirm the server's host key. The command then
    prints the TrueNAS host name without asking for a password.

#### Results

The workstation logs in to TrueNAS as `truenas_admin` with its key. The account can run
administrative commands with `sudo`; the installer grants it all sudo commands with its password.

## Enable the NVIDIA driver

TrueNAS 25.10 ships the NVIDIA driver (580.173.02, built from NVIDIA's open kernel modules) and the
NVIDIA container toolkit inside the operating system image, so turning the driver on downloads
nothing. When a usable NVIDIA GPU is present, TrueNAS also makes `nvidia` the default Docker
runtime.

!!! caution
    Do not replace the driver file `/usr/share/truenas/sysext-extensions/nvidia.raw` with a
    different driver build, as some community scripts do. Systems changed this way have needed a
    fresh installation of the boot device. A container image built on a CUDA version newer than
    13.0 does not start on this driver; choose images built on CUDA 13.0 or older instead.

### Turn on the NVIDIA driver

#### Prerequisites

- The GPU is not isolated: **System** > **Advanced Settings** > **Isolated GPU Device(s)** lists
  no device.
- The debug kernel is off (**System** > **Advanced Settings** > **Kernel**). The debug kernel
  disables the NVIDIA driver.

#### About this task

The **Install NVIDIA Drivers** setting activates the driver extension that is already in the
operating system image, loads the kernel modules and restarts Docker. TrueNAS repeats this at
every boot.

#### Steps

1. Go to **Apps**. If TrueNAS asks you to choose a pool, click **Configuration** > **Choose Pool**,
   select `tank`, and click **Choose**.

2. Go to **Apps** > **Installed** and click **Configuration** > **Settings**.

3. Select **Install NVIDIA Drivers**.

    The option is shown only when TrueNAS detects an NVIDIA GPU that is not isolated and the
    debug kernel is off.

4. Click **Save**.

    TrueNAS loads the driver and restarts Docker. Installed apps restart with it.

#### Results

The driver is active and Docker uses the NVIDIA runtime by default. Continue with the
verification task.

### Verify the GPU on the host and in a container

#### Steps

1. Run the following command:

        nvidia-smi

    The header shows `Driver Version: 580.173.02` and `CUDA Version: 13.0`, and the table lists
    the NVIDIA GeForce RTX 4080. The `Processes` part of the output reads `No running processes found`,
    because no app uses the GPU yet.

2. Check that the card drives no display. Make sure that no monitor cable is connected to the
   RTX 4080, then read its memory use while no app runs:

        nvidia-smi --query-gpu=memory.used,memory.total --format=csv

    `memory.used` is at most a few MiB, and `memory.total` is about 16,000 MiB. A larger
    `memory.used` with no app running means that something else, such as a display, holds VRAM:
    the VRAM budget of Chapter 2 assumes a card that drives no display. Move the monitor to
    another graphics output of the server, if it has one, or expect less room for the models.

3. Confirm that the Apps service has the driver enabled:

        midclt call docker.config

    The output contains `"nvidia": true`.

4. Confirm the Docker runtime:

        sudo docker info | grep -i runtime

    The output lists `nvidia` among the runtimes and shows `Default Runtime: nvidia`.

5. Run `nvidia-smi` inside a test container. The image is built on CUDA 13.0, the newest version
   this driver supports:

        sudo docker run --rm --gpus all nvidia/cuda:13.0.2-base-ubuntu24.04 nvidia-smi

    The container prints the same table as the host. Keep the image for now; the document share
    test in [Verify the share and the read-only container mount](#verify-the-share-and-the-read-only-container-mount)
    uses it and then removes it.

#### Results

The GPU is visible on the host and inside containers, and its memory is free for the models.

If `nvidia-smi` reports that no devices were found, clear **Install NVIDIA Drivers**, click
**Save**, select it again and click **Save**. Then check the kernel and middleware logs:

```
sudo dmesg | grep -i nvrm
sudo journalctl -u middlewared --since "15 minutes ago"
```

## Set persistence mode and the power limit

GPU persistence mode and the power limit both reset at every boot. A **Post Init** command in
TrueNAS sets them again after each start. The RTX 4080 is rated at 320 W total graphics power
(partner cards can differ). This guide keeps the stock limit by default; the optional task shows
how to cap it.

### Add the GPU Post Init command

#### About this task

TrueNAS runs a **Command** type init script with `sh -c` and waits for it for at most its
**Timeout** in seconds. The command below waits up to 60 seconds for the driver to answer, then turns on
persistence mode, which keeps the driver initialized between jobs. TrueNAS stores the command in
its configuration database, so it survives updates.

Table: Post Init command settings

| Field | Value |
|---|---|
| **Description** | `GPU persistence mode` |
| **Type** | `Command` |
| **Command** | The command in step 3 |
| **When** | `Post Init` |
| **Enabled** | Selected |
| **Timeout** | `120` |

#### Steps

1. Go to **System** > **Advanced Settings**.

    The first visit shows a warning that these settings are for advanced users. Read it and
    continue.

2. On the **Init/Shutdown Scripts** card, click **Add**.

3. Enter the values from the table above. Type the command on one line:

        i=0; until nvidia-smi >/dev/null 2>&1 || [ $i -ge 30 ]; do i=$((i+1)); sleep 2; done; nvidia-smi -pm 1

4. Click **Save**.

5. Apply the setting now, without a restart:

        sudo nvidia-smi -pm 1

6. Verify the setting:

        nvidia-smi -q | grep -i 'persistence mode'

    The **Persistence Mode** line of the output reads `Enabled`.

#### Results

Persistence mode is on now and is set again at every boot. The restart in
[Restart and verify the GPU and memory settings](#restart-and-verify-the-gpu-and-memory-settings)
confirms the boot path.

### Cap the GPU power limit

#### About this task

This task is optional. A lower power limit reduces power draw and heat at some cost in token
throughput. The example uses 280 W; pick a value inside the range that the card reports.

#### Steps

1. Display the default, minimum and maximum limits of the card:

        nvidia-smi --query-gpu=power.default_limit,power.min_limit,power.max_limit --format=csv

    Choose a limit between the minimum and the maximum.

2. In **System** > **Advanced Settings** > **Init/Shutdown Scripts**, open the
   `GPU persistence mode` entry.

3. Append the limit to the end of **Command**, then click **Save**:

        ; nvidia-smi -pl 280

    The complete command now ends with `nvidia-smi -pm 1; nvidia-smi -pl 280`.

4. Apply the limit now:

        sudo nvidia-smi -pl 280

5. Verify the limit:

        nvidia-smi --query-gpu=power.limit,power.default_limit --format=csv

    The first value is `280.00 W`; the second is the card's default.

#### Results

The GPU runs at the chosen power limit now and after every boot. To return to the stock limit,
remove `; nvidia-smi -pl 280` from the command and restart the server.

## Cap the ZFS ARC

ZFS keeps a read cache, the ARC, in system memory and lets it grow into most of the free RAM. The
fast model profile keeps part of the model in system memory, and llama.cpp needs memory for its
own buffers, so the stack caps the ARC. On a 64 GB server the cap is 12 GiB, which leaves about
38 GiB for the model process.

Table: ARC cap by installed memory

| Installed memory | `zfs_arc_max` value | Size |
|---|---|---|
| 64 GB (reference system) | `12884901888` | 12 GiB |
| 64 GB, more expert offload | `8589934592` | 8 GiB |
| 128 GB | `25769803776` | 24 GiB |

A server with less than 64 GB is below the minimum of this guide and is not supported: the model
profiles, the services and the ZFS ARC do not fit together
([Minimum requirements](#minimum-requirements)).

### Add the zfs_arc_max tunable

#### About this task

TrueNAS 25.10 supports the ARC cap as a tunable of type ZFS. TrueNAS stores it in its
configuration database, applies it at once, and writes it to `/etc/modprobe.d/zfs.conf` and the
initramfs so that it persists across restarts.

#### Steps

1. Go to **System** > **Advanced Settings**.

2. On the **Sysctl** card, click **Add**.

    The **Add Sysctl** form opens.

3. Enter the following values:

    - **Type**: `ZFS`
    - **Variable**: `zfs_arc_max`
    - **Value**: `12884901888`
    - **Description**: `Cap ARC at 12 GiB for model offload`
    - **Enabled**: selected

4. Click **Save**.

5. Verify the active value:

        cat /sys/module/zfs/parameters/zfs_arc_max

    The output is `12884901888`.

#### Results

The cap is active. A lower cap does not shrink an ARC that is already larger, so restart the
server once (next task).

!!! note
    Use only this tunable to cap the ARC. Do not also set `zfs_arc_min` to the same value, and do
    not use the older methods (an `echo` into `/sys` in an init script, or extra kernel options).
    Starting or stopping virtual machines makes TrueNAS adjust the ARC; do not run virtual
    machines on this server.

### Restart and verify the GPU and memory settings

#### Steps

1. In the top toolbar, click the power icon, click **Restart**, and confirm.

2. After the server is back, log in and open **System** > **Shell**.

3. Verify the ARC cap:

        cat /sys/module/zfs/parameters/zfs_arc_max

    The output is `12884901888`.

4. Verify persistence mode:

        nvidia-smi -q | grep -i 'persistence mode'

    The **Persistence Mode** line of the output reads `Enabled`.

5. If you capped the power limit, verify it:

        nvidia-smi --query-gpu=power.limit --format=csv

#### Results

The ARC cap, persistence mode and the optional power limit survive a restart.

!!! note
    The tunable and the Post Init command are expected to survive TrueNAS updates, because they
    are stored in the configuration database that updates migrate. Repeat steps 3 to 5 after every
    update.

## Create the datasets

The stack keeps all of its data in datasets under `tank/ai`, mounted at `/mnt/tank/ai`. Every
service writes to a host path on these datasets, never to an app volume inside TrueNAS's hidden
`ix-apps` dataset, so snapshots and replication capture all of the state. Each stateful service
has its own child dataset under `tank/ai/appdata`, named after its container.

Table: Datasets of the stack

| Dataset | Preset | Settings | Contents |
|---|---|---|---|
| `tank/ai` | Generic | Defaults | Parent of the datasets below |
| `tank/ai/models` | Generic | **Record Size** 1M, **Compression Level** LZ4, **Enable Atime** Off; `primarycache=metadata` from the shell | Model files under `gguf/`; not snapshotted |
| `tank/ai/appdata` | Apps | Defaults | Parent of the per-service datasets |
| `tank/ai/appdata/litellm-db` | Apps | **Record Size** 32K | PostgreSQL data of LiteLLM |
| `tank/ai/appdata/pgvector` | Apps | **Record Size** 32K | PostgreSQL data of Open WebUI and its vectors |
| `tank/ai/appdata/oikb` | Apps | Defaults | Sync history of the knowledge-base sync |
| `tank/ai/appdata/open-webui` | Apps | Defaults | Open WebUI uploads and caches |
| `tank/ai/appdata/caddy` | Apps | Defaults | Caddy certificates, ACME account and configuration |
| `tank/ai/rag-docs` | SMB | **Create SMB Share**, **SMB Name** `rag-docs` | Documents to index, mounted read-only |
| `tank/ai/stacks` | Generic | Owner `truenas_admin` (set from the shell) | Git clone of this repository |
| `tank/ai/secrets` | Generic | Mode 0700, owner root (set from the shell) | The environment files `inference.env`, `rag.env`, `web.env` and `edge.env` |

The Apps preset sets the ACL type to NFSv4, turns access time off, and grants the TrueNAS `apps`
user (UID 568) Modify with inheritance. A 32K record size suits PostgreSQL data files.

!!! note
    The name, the preset and the case sensitivity of a dataset cannot be changed after it is
    created. Check them before you click **Save**.

### Create the parent and models datasets

#### Steps

1. Go to **Datasets**, select `tank`, and click **Add Dataset**.

2. Enter **Name** `ai`, select **Dataset Preset** `Generic`, and click **Save**.

3. Select `tank/ai` and click **Add Dataset**.

4. Enter **Name** `models` and select **Dataset Preset** `Generic`.

5. Click **Advanced Options**. Under **Other Options**, set **Compression Level** to `LZ4`,
   **Enable Atime** to `Off` and **Record Size** to `1M`.

6. Click **Save**.

7. Set the cache property, which the dataset form does not offer:

        sudo zfs set primarycache=metadata tank/ai/models

    With `primarycache=metadata`, ZFS caches only the metadata of the model files. The model
    server holds the weights in its own memory, so the ARC does not keep a second copy. The
    property is stored on the pool.

8. Verify the properties:

        sudo zfs get -o property,value recordsize,compression,atime,primarycache tank/ai/models

    The values are `1M`, `lz4`, `off` and `metadata`.

#### Results

`tank/ai` and `tank/ai/models` exist, and the model dataset stores large files with 1M records,
LZ4 compression and no access times, and keeps only their metadata in the ARC.

### Create the appdata datasets

#### Steps

1. Select `tank/ai` and click **Add Dataset**.

2. Enter **Name** `appdata`, select **Dataset Preset** `Apps`, and click **Save**.

3. Select `tank/ai/appdata`, click **Add Dataset**, enter **Name** `litellm-db`, and select
   **Dataset Preset** `Apps`.

4. Click **Advanced Options**, set **Record Size** to `32K`, and click **Save**.

5. Repeat steps 3 and 4 for `pgvector`.

6. Create `oikb`, `open-webui` and `caddy` under `tank/ai/appdata` with **Dataset Preset** `Apps`
   and the default settings.

7. Verify the datasets:

        sudo zfs list -r -o name,recordsize,mountpoint tank/ai/appdata

    The list shows `tank/ai/appdata` and its five children; `litellm-db` and `pgvector` have
    record size `32K`.

#### Results

Each stateful service has its own dataset under `tank/ai/appdata`, with the **Apps** preset, so
that the `apps` user (UID 568) can write to it. The two PostgreSQL datasets use 32K records.

### Create the rag-docs, stacks and secrets datasets

#### Steps

1. Select `tank/ai` and click **Add Dataset**.

2. Enter **Name** `rag-docs` and select **Dataset Preset** `SMB`.

3. Make sure that **Create SMB Share** is selected and that **SMB Name** is `rag-docs`, then click
   **Save**.

4. Select `tank/ai`, click **Add Dataset**, enter **Name** `stacks`, select **Dataset Preset**
   `Generic`, and click **Save**.

5. Select `tank/ai`, click **Add Dataset**, enter **Name** `secrets`, select **Dataset Preset**
   `Generic`, and click **Save**.

6. Give `truenas_admin` ownership of the repository dataset, so that it can clone and update the
   repository without `sudo`:

        sudo chown truenas_admin:truenas_admin /mnt/tank/ai/stacks

7. Restrict the secrets dataset to root:

        sudo chmod 0700 /mnt/tank/ai/secrets

8. Verify ownership and modes:

        sudo stat -c '%n %a %U:%G' /mnt/tank/ai/stacks /mnt/tank/ai/secrets

    `/mnt/tank/ai/stacks` is owned by `truenas_admin:truenas_admin`, and `/mnt/tank/ai/secrets`
    shows `700 root:root`.

9. Verify the complete layout:

        sudo zfs list -r -o name,mountpoint tank/ai

#### Results

The list shows the eleven datasets of the table, each mounted under `/mnt/tank/ai`. **Shares** >
**Windows (SMB) Shares** lists the `rag-docs` share.

## Share the documents folder over SMB

The `rag-docs` share is the drop folder for the documents that the stack indexes. People copy
files to it over SMB; the containers mount the dataset read-only and read it as the `apps` group
(GID 568).

### Create an SMB user for the documents share

#### About this task

An SMB share cannot be reached as `root` or as a built-in account. Create a dedicated local user
with SMB access, or give **SMB Access** to an existing personal account.

#### Steps

1. Go to **Credentials** > **Users** and click **Add**.

2. Enter **Full Name** and **Username** (`<smb-user>`).

3. Enter **Password** and **Confirm Password**.

4. Under **Allow Access**, keep **SMB Access** selected, and leave **TrueNAS Access**,
   **Shell Access** and **SSH Access** cleared.

5. Click **Save**.

#### Results

The user is listed in **Credentials** > **Users**, and its **Access** card shows
**Has SMB Access**.

### Start the SMB service

#### Steps

1. Go to **System** > **Services**.

2. On the **SMB** row, turn on **Start Automatically**.

3. If the **Status** of SMB is not running, click the **Start Service** button (play icon) on the
   row.

#### Results

The SMB service is running and starts at every boot.

### Give the apps group read access to rag-docs

#### About this task

The SMB preset gives the dataset a restrictive NFSv4 ACL for SMB users. Add one entry that lets
the `apps` group read the documents, with inheritance so that new files carry it too. Do not change
the existing `builtin_users` entry.

#### Steps

1. Go to **Datasets** and select `tank/ai/rag-docs`.

2. On the **Permissions** card, click **Edit**.

    The **ACL Editor** opens.

3. Click **Add Item**.

4. In the new **Access Control Entry**, set **Who** to `Group` and **Group** to `apps`.

5. Keep **Permissions Type** `Basic` and set **Permissions** to `Read`. Keep the **Flags** at
   `Inherit`.

6. Select **Apply permissions recursively** and confirm the warning.

7. Click **Save Access Control List**.

#### Results

The **Permissions** card of `rag-docs` lists a `Group - apps` entry with Read access.

### Verify the share and the read-only container mount

#### Steps

1. From a client, connect to the share and copy a test file into it, for example
   `share-test.txt`:

    - macOS: **Finder** > **Go** > **Connect to Server**, enter `smb://192.0.2.10/rag-docs`, and log
      in as `<smb-user>`.
    - Windows: in File Explorer, open `\\192.0.2.10\rag-docs` and log in as `<smb-user>`.
    - Linux (requires the `cifs-utils` package):

            sudo mkdir -p /mnt/rag-docs
            sudo mount -t cifs //192.0.2.10/rag-docs /mnt/rag-docs -o username=<smb-user>

2. On TrueNAS, list the share as a container running as UID and GID 568 sees it, with the dataset
   mounted read-only:

        sudo docker run --rm --user 568:568 -e NVIDIA_VISIBLE_DEVICES=void -v /mnt/tank/ai/rag-docs:/docs:ro nvidia/cuda:13.0.2-base-ubuntu24.04 ls -l /docs

    The output lists `share-test.txt`.

3. Confirm that the mount is read-only:

        sudo docker run --rm --user 568:568 -e NVIDIA_VISIBLE_DEVICES=void -v /mnt/tank/ai/rag-docs:/docs:ro nvidia/cuda:13.0.2-base-ubuntu24.04 touch /docs/write-test

    The command fails with `Read-only file system`.

4. Remove the test image:

        sudo docker image rm nvidia/cuda:13.0.2-base-ubuntu24.04

5. Delete `share-test.txt` from the share.

#### Results

Users write to `rag-docs` over SMB, and containers read it without being able to change it.

## Create the ai-net network

All four apps join one external Docker network, `ai-net`, and reach each other by container name.
Each compose file declares the network as external, so it must exist before the first app is
installed.

### Create the shared Docker network

#### Prerequisites

The Docker address pool does not overlap your LAN (**Apps** > **Installed** > **Configuration** >
**Settings** > **Address Pools**). The default pool is `172.17.0.0/12`, divided into /24 networks.

#### Steps

1. Create the network:

        sudo docker network create ai-net

    Docker prints the ID of the new network.

2. Verify the network:

        sudo docker network ls --filter name=ai-net

    The output has one row: `ai-net` with driver `bridge` and scope `local`.

3. Display the subnet that Docker assigned:

        sudo docker network inspect ai-net --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}'

    The subnet lies inside the address pool and does not overlap your LAN.

#### Results

The network exists. It is stored in the Docker data directory on the apps pool and is expected to
survive TrueNAS updates; if an update removes it, the apps fail to start and step 1 creates it
again.

## Clone the repository on TrueNAS

The TrueNAS apps include the compose files from a git clone of this repository on the pool, at
`/mnt/tank/ai/stacks/local-agent-stack`. The clone is checked out at a release tag, so the server
runs exactly the files that this guide describes.

### Check that git is available

#### Steps

1. Run the following command:

        git --version

    The output is one line that starts with `git version`. Git is part of the TrueNAS base
    system, because the middleware depends on it.

#### Results

If the command is not found, clone the repository on the workstation instead and copy it over
SSH. Run the following commands on the workstation:

```
git clone --branch <release-tag> https://github.com/corytron/local-agent-stack.git /tmp/local-agent-stack
tar -C /tmp -czf - local-agent-stack | ssh truenas_admin@192.0.2.10 'tar -C /mnt/tank/ai/stacks -xzf -'
rm -rf /tmp/local-agent-stack
```

### Clone the release tag

#### Steps

1. Clone the repository at the release tag, as `truenas_admin` (without `sudo`):

        git clone --branch <release-tag> https://github.com/corytron/local-agent-stack.git /mnt/tank/ai/stacks/local-agent-stack

    Git reports that the clone is in a detached HEAD state. This is expected for a tag.

2. Verify the checked-out release:

        git -C /mnt/tank/ai/stacks/local-agent-stack describe --tags --exact-match

    The output is the release tag, for example `v1.0`.

3. Verify that the app directories are present:

        ls /mnt/tank/ai/stacks/local-agent-stack/stack

    The output lists `edge`, `inference`, `rag` and `web`.

#### Results

The repository is on the pool at the release tag.

!!! note
    Do not edit files in the clone. Local changes make the server differ from the release and
    block the move to the next tag. Chapter 10 describes updates
    ([Updating to a new release](#updating-to-a-new-release)).

## Check the ports for the edge proxy

The `caddy` container of the edge app publishes ports 80 and 443 over TCP, and 443 over UDP for
HTTP/3, on the server; the stack publishes no other port on the server. The TrueNAS web interface
keeps ports of its own, which this guide writes as `<ui-https-port>` and `<ui-http-port>` (`444`
and `81` in the examples). A new TrueNAS installation serves the web interface on ports 80 and 443;
only in that case does the web interface move.

`tools/port-inventory.sh`, in the clone, lists what listens on the server's ports, the ports that
Docker containers publish and the ports of the TrueNAS web interface, and says for each of the
three ports that Caddy needs whether it is free. It only reads: it runs `ss`, `docker ps` and
`midclt call system.general.config`, writes no file and changes nothing.

### Run the port inventory

#### About this task

Run the script on the server, in **System** > **Shell** or over SSH from the workstation, as
`truenas_admin`. It runs its three commands through `sudo`, because only root can see which
process or container holds a port. With `--no-sudo` it skips `sudo`, but then it cannot name most
of them. With `--json` it prints the same report as one JSON object. Its exit status is `0` when
every port that Caddy needs is free or already used by the edge app, and `1` otherwise.

#### Steps

1. In **System** > **Shell**, run the following command:

        sh /mnt/tank/ai/stacks/local-agent-stack/tools/port-inventory.sh

    If `sudo` has not cached your password, the script prints
    `port-inventory.sh: sudo asks for your password once`, and `sudo` asks for the `truenas_admin`
    password.

    To run the same check from the workstation, use SSH with `-t`, which gives `sudo` a terminal
    for its password prompt:

        ssh -t truenas_admin@192.0.2.10 sh /mnt/tank/ai/stacks/local-agent-stack/tools/port-inventory.sh

    The report has the sections `Listening sockets`, `Ports published by Docker containers`,
    `TrueNAS web interface` and `Ports the stack needs on this server`, then `Notes` when there is
    something to note, and a result line.

2. In the section `TrueNAS web interface`, note the two ports. In this guide's examples, it reads:

        TrueNAS web interface (midclt call system.general.config; System > General Settings > GUI)
          HTTP port (ui_port)         81
          HTTPS port (ui_httpsport)   444
          Redirect HTTP to HTTPS      yes
          Addresses                   0.0.0.0, ::

    `HTTPS port (ui_httpsport)` is `<ui-https-port>` and `HTTP port (ui_port)` is `<ui-http-port>`
    in the rest of this guide. They are the values of **Web Interface HTTPS Port** and
    **Web Interface HTTP Port** behind the **GUI** card of **System** > **General Settings**.

3. Check the section `Ports the stack needs on this server` and the result line. Before the edge
   app is installed, they read:

        Ports the stack needs on this server (Caddy, app ai-edge)
          80/tcp    free
          443/tcp   free
          443/udp   free

        Result: every port the stack needs is free or already used by the stack (exit 0).

    After the edge app is installed in Chapter 5, the three lines read
    `ours: container caddy (app ai-edge)`, and the result line is the same.

4. If a line reads anything else, act on it as the table shows, then repeat step 1.

    Table: Verdicts of the port inventory

    | Verdict | Action |
    |---|---|
    | `used by the TrueNAS web interface` | Give the web interface other ports ([Change the web interface ports](#change-the-web-interface-ports)). The `Notes` section says the same |
    | `used by container <name> (app <app>)` | A TrueNAS app publishes the port. In **Apps** > **Installed**, select the app and click **Edit** to change its port, or click **Stop** |
    | `used by container <name> (not a TrueNAS app)` | A container started outside the TrueNAS apps publishes the port. Stop it, or change its port where it was started |
    | `used by <process>` | A service of the server listens on the port; the section `Listening sockets` shows it. Stop that service or give it another port |
    | `unknown (ss could not be run)` | The script could not read the sockets. Read the `Notes` section, and run the script again with your password |

#### Results

Ports 80/tcp, 443/tcp and 443/udp are free for Caddy, and the result line ends with `(exit 0)`.
The web interface is at `https://192.0.2.10:<ui-https-port>` (`https://192.0.2.10:444` in this
guide's examples), and `tools/deploy.py` connects to `wss://192.0.2.10:<ui-https-port>/api/current`
(`wss://192.0.2.10:444/api/current`).

### Change the web interface ports

#### About this task

Do this only when the port inventory reports `used by the TrueNAS web interface`, which is the case
on a new TrueNAS installation. Choose two ports that the inventory lists neither under
`Listening sockets` nor under `Ports published by Docker containers`; this guide uses `81` for
HTTP and `444` for HTTPS. The web interface restarts on the new ports, and the TrueNAS API moves
with it.

#### Steps

1. Go to **System** > **General Settings**.

2. On the **GUI** card, click **Settings**.

3. Set **Web Interface HTTP Port** to `81` and **Web Interface HTTPS Port** to `444`, or to other
   ports that the inventory does not list.

4. Click **Save**.

    The **Restart Web Service** dialog opens.

5. Select **Confirm** and click **Continue**.

    The web interface restarts on the new ports. Open `https://192.0.2.10:444` and log in again.

6. Run the port inventory again ([Run the port inventory](#run-the-port-inventory), step 1).

    `80/tcp` and `443/tcp` read `free`, and `HTTPS port (ui_httpsport)` is `444`.

#### Results

The web interface is at `https://192.0.2.10:444`, and ports 80 and 443 are free for Caddy. Update
your bookmarks. Use `444` as `<ui-https-port>` and `81` as `<ui-http-port>` in the rest of this
guide.

## Create the secrets files

Each app reads its secrets from one environment file in `/mnt/tank/ai/secrets`, named after its
directory under `stack/`: `inference.env`, `rag.env`, `web.env` and `edge.env`. The tool
`tools/secrets.py gen <name>` fills in the example file of that directory, for example
`stack/inference/inference.env.example`, with a new random value (48 letters and digits) for every
secret it generates, copies the values that two files share from an existing file named with
`--share`, and leaves the example's placeholder for each value that you provide or that a running
service creates later. With `-o <file>`, it writes a new file with mode 0600 and refuses to replace
an existing one. The fifth file, the workstation's `client.env`, is created in Chapter 7
([Create client.env](#create-clientenv)).

Table: Secrets files

| File | Variables | Values |
|---|---|---|
| `inference.env` | `LITELLM_MASTER_KEY`, `LITELLM_SALT_KEY`, `LITELLM_DB_PASSWORD`, `LLAMA_SWAP_API_KEY` | Generated |
| `rag.env` | `PG_PASSWORD`, `DOCLING_API_KEY`, `OIKB_API_KEY`, `OIKB_TOKEN`, `OIKB_KB_ID` | The first three generated. `OIKB_TOKEN`, the `indexer` user's Open WebUI API key, and `OIKB_KB_ID`, the ID of the knowledge base, are set after Open WebUI's first start in Chapter 6 ([Store the service keys and redeploy ai-rag and ai-web](#store-the-service-keys-and-redeploy-ai-rag-and-ai-web)) |
| `web.env` | `LAB_DOMAIN`, `WEBUI_SECRET_KEY`, `SEARXNG_SECRET`, `MCP_HUB_TOKEN`, `PG_PASSWORD`, `DOCLING_API_KEY`, `LITELLM_WEBUI_KEY`, `KB_READER_TOKEN`, `SEARXNG_CONTACT_URL` | `WEBUI_SECRET_KEY`, `SEARXNG_SECRET` and `MCP_HUB_TOKEN` generated; `PG_PASSWORD` and `DOCLING_API_KEY` copied from `rag.env`. You set `LAB_DOMAIN`, `LITELLM_WEBUI_KEY` (a LiteLLM key that exists only after `ai-inference` is installed) and the optional `SEARXNG_CONTACT_URL` before Open WebUI's first start ([Complete web.env before the first start](#complete-webenv-before-the-first-start)), and `KB_READER_TOKEN`, the `kb-reader` user's API key, after it |
| `edge.env` | `LAB_DOMAIN`, `ACME_EMAIL`, `DNS_PROVIDER`, `DNS_PROVIDER_TOKEN`; optional `DNS_PROVIDER_KEY_ID`, `DNS_PROVIDER_CONSUMER_KEY`, `DNS_PROVIDER_ENDPOINT`, `ACME_RESOLVERS`, `ACME_CA`, `EDGE_ALLOWED_CIDRS`, `EDGE_BIND_IP`, `AI_ROOT` | You provide them in Chapter 5 ([Complete edge.env](#complete-edgeenv)); the example's defaults suit the optional ones |

!!! warning
    The secrets files hold the keys that control the gateway, the databases and the certificates.
    Keep them only in `/mnt/tank/ai/secrets` on the server and in `~/.config/local-agent-stack/` on
    the workstation. Never copy them into the git clone or the `rag-docs` share, and never paste a
    value into an issue or a chat.

### Generate the environment files on the workstation

#### Prerequisites

The workstation has Python 3.11 or later ([Workstation requirements](#workstation-requirements))
and a clone of the repository at the same release tag. If it has no clone yet, create one:

```
git clone --branch <release-tag> https://github.com/corytron/local-agent-stack.git ~/local-agent-stack
```

#### Steps

1. Create a private directory for the server's environment files:

        install -d -m 0700 ~/.config/local-agent-stack/secrets

2. Change to the clone:

        cd ~/local-agent-stack

3. Generate one file per app. Generate `rag.env` before `web.env`, which copies its
   `PG_PASSWORD` and `DOCLING_API_KEY`:

        python3 tools/secrets.py gen inference -o ~/.config/local-agent-stack/secrets/inference.env
        python3 tools/secrets.py gen rag -o ~/.config/local-agent-stack/secrets/rag.env
        python3 tools/secrets.py gen web --share ~/.config/local-agent-stack/secrets/rag.env -o ~/.config/local-agent-stack/secrets/web.env
        python3 tools/secrets.py gen edge -o ~/.config/local-agent-stack/secrets/edge.env

    Run each command only once per installation. A second run creates new values, and
    `LITELLM_SALT_KEY` and `WEBUI_SECRET_KEY` must never change after the first start.

4. Verify the files and their modes:

        ls -l ~/.config/local-agent-stack/secrets/

    The output lists four files, each with `-rw-------`.

5. Check that `rag.env` and `web.env` carry the same database password and docling key:

        for v in PG_PASSWORD DOCLING_API_KEY; do grep -h "^$v=" ~/.config/local-agent-stack/secrets/rag.env ~/.config/local-agent-stack/secrets/web.env | sort -u | wc -l; done

    The output is `1` twice.

6. Check that every secret was generated. Each generated value replaced a `change-me` placeholder
   of the example file:

        grep -c 'change-me' ~/.config/local-agent-stack/secrets/inference.env ~/.config/local-agent-stack/secrets/rag.env ~/.config/local-agent-stack/secrets/web.env

    The counts are `0` for `inference.env` and `rag.env`, and `1` for `web.env`: its
    `LITELLM_WEBUI_KEY` placeholder, which Chapter 6 replaces.

7. Leave the placeholders that you provide for now. Chapter 5 completes `edge.env`
   ([Complete edge.env](#complete-edgeenv)), and Chapter 6 completes `web.env` before Open WebUI
   first starts and `rag.env` after it.

#### Results

`~/.config/local-agent-stack/secrets/` holds `inference.env`, `rag.env`, `web.env` and
`edge.env`, readable only by you, with every generated secret filled in and the shared values
identical in `rag.env` and `web.env`. These files are the workstation's copies of the server's
secrets: keep them, and back them up with the rest of the workstation state
([Back up the workstation files](#back-up-the-workstation-files)).

### Copy the environment files to TrueNAS

#### Steps

1. Copy the files to the home directory of `truenas_admin`:

        scp ~/.config/local-agent-stack/secrets/*.env truenas_admin@192.0.2.10:

2. On TrueNAS, install them into the secrets dataset, owned by root with mode 0600:

        sudo install -m 0600 -o root -g root ~/inference.env ~/rag.env ~/web.env ~/edge.env /mnt/tank/ai/secrets/

3. Delete the copies in the home directory:

        rm ~/inference.env ~/rag.env ~/web.env ~/edge.env

4. Verify the files:

        sudo ls -l /mnt/tank/ai/secrets

    The output lists the four files, each with `-rw-------` and owner `root root`.

#### Results

The apps can read their environment files, and no other user can. To change a value later, edit
the file in `~/.config/local-agent-stack/secrets/` on the workstation and repeat this task. To read
a value on the server, run for example
`sudo grep '^LITELLM_MASTER_KEY=' /mnt/tank/ai/secrets/inference.env`.

## Create TrueNAS API keys for deploy.py

`tools/deploy.py` runs on the workstation and talks to the TrueNAS API (JSON-RPC over WebSocket at
`wss://192.0.2.10:<ui-https-port>/api/current`, `wss://192.0.2.10:444/api/current` in this guide's
examples) to compare and install the apps. TrueNAS 25.10 has no role
smaller than full administrator that can write apps, so the tool uses two keys, each tied to its
own user:

Table: Deploy users and keys

| User | Role in TrueNAS | Key used by |
|---|---|---|
| `deploy-read` | Readonly Admin (group `truenas_readonly_administrators`) | `deploy.py plan`, `drift` and `status`; never changes anything |
| `deploy-apply` | Full Admin (group `builtin_administrators`) | `deploy.py apply` only |

The **TrueNAS Access** role in the user form adds the user to the built-in group of that role. The
built-in groups avoid custom privileges, which TrueNAS 25.10 deprecates.

!!! warning
    An API key is equivalent to its user's password and bypasses two-factor authentication. The
    `deploy-apply` key gives full control of the server. TrueNAS 25.10 has no challenge-response
    login, so the key is protected only by TLS: always connect with `wss://` on the web interface's
    HTTPS port, `<ui-https-port>`. TrueNAS revokes a key automatically if it is ever sent over
    plain HTTP. Keep the key files only on the workstation, with mode 0600, and never commit, paste
    or attach them.

### Create the deploy users

#### Steps

1. Go to **Credentials** > **Users** and click **Add**.

2. Enter **Full Name** `Deploy (read-only)` and **Username** `deploy-read`.

3. Under **Allow Access**, clear **SMB Access**.

4. Select **TrueNAS Access** and select the role `Readonly Admin`. Leave **Shell Access** and
   **SSH Access** cleared.

5. Under **Authentication**, select **Disable Password**.

    The user logs in only with its API key.

6. Click **Save**.

7. Repeat steps 1 to 6 with **Full Name** `Deploy (apply)`, **Username** `deploy-apply` and the
   role `Full Admin`.

#### Results

Both users are listed in **Credentials** > **Users**. The **Access** card of `deploy-read` shows
**TrueNAS Access: Readonly Admin** and **No Password**; the card of `deploy-apply` shows
**TrueNAS Access: Full Admin**.

### Create the API keys and store them on the workstation

#### About this task

TrueNAS shows each key only once, at creation. Store it on the workstation before you close the
dialog. If a key is lost, delete it and create a new one.

#### Steps

1. On the workstation, create the configuration directory:

        install -d -m 0700 ~/.config/local-agent-stack

2. In TrueNAS, go to **Credentials** > **Users** and select `deploy-read`.

3. On the **Access** card, click **Add API Key**.

    The **Add API Key** form opens with **Username** `deploy-read`.

4. Enter **Name** `deploy-read-c4dev`. Keep **Non-expiring** selected, or clear it and set
   **Expires On**.

5. Click **Save**.

    The **API Key** dialog shows the key and states that this is the only time the key is shown.

6. Click **Copy to Clipboard**.

7. On the workstation, run the following command, paste the key at the prompt, and press Enter.
   The key is not echoed and does not enter the shell history:

        (umask 077; printf 'API key: '; read -rs key; echo; printf '%s\n' "$key" > ~/.config/local-agent-stack/truenas-read.key)

8. In TrueNAS, click **Close**.

9. Repeat steps 2 to 8 for `deploy-apply`, with **Name** `deploy-apply-c4dev` and the file
   `~/.config/local-agent-stack/truenas-apply.key`.

10. On the workstation, verify the key files:

        stat -c '%a %s %n' ~/.config/local-agent-stack/truenas-*.key

    Both files have mode `600` and a size greater than zero.

11. In TrueNAS, check the keys: the **Access** card of each deploy user shows **API Keys: 1 key**,
    and **View API Keys** lists the key with its name and user.

#### Results

The workstation holds a read-only key and an apply key for `tools/deploy.py`. Chapter 10
configures the tool with the address `wss://192.0.2.10:<ui-https-port>/api/current` and these two
files ([Setting up deploy.py](#setting-up-deploypy)), and checks the read-only key with
`deploy.py status` before anything is applied. To revoke a key, open **View API Keys** for its
user and delete it.
