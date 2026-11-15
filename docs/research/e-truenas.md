# TrueNAS SCALE platform layer: apps, NVIDIA GPU, storage, network, TLS, backup

Status: research, 2026-11-15. Author: research agent E.

Owner-confirmed facts used throughout: TrueNAS **25.10.8 "Goldeye"**, **62.3 GiB usable RAM** (64 GB ECC),
Intel Xeon w5-3435X (16C/32T, Sapphire Rapids), one RTX 4080 (16 GB). Every UI click path below is for
25.10 and was checked against the 25.10 documentation and, where the docs were vague or disagreed, against
the web UI source code at tag `TS-25.10.8` of `github.com/truenas/webui` [S41]. Other releases get short notes only.
Placeholders: TrueNAS `192.0.2.10`, c4dev `192.0.2.20`, pool `tank`.

## Summary

- **Stay on 25.10.8.** It is TrueNAS's current "General" recommendation (released 2026-11-05) [S1]. The
  **minimum for this project is 25.10.6**, the first 25.10 build that ships **NVIDIA 580.173.02** [S3]. On
  25.10.0–25.10.5 the driver is 570.172.08. TrueNAS 27.0 (the renamed "26") is due in early December 2026; 27-RC.1
  ships the same 580.173.02 driver with Docker 29.0.4 [S4][S5]. Wait for 27.0.x before upgrading.
- **NVIDIA on 25.10.8:** the driver is **580.173.02**, built from NVIDIA's open kernel modules (Turing or newer
  only). It ships inside the OS image as a systemd-sysext together with `nvidia-container-toolkit`, so turning
  it on needs no internet [S3][S8]. To turn it on: **Apps > Installed > Configuration ▾ > Settings > Install NVIDIA
  Drivers > Save** [S6][S41]. Once a usable NVIDIA GPU is present, TrueNAS sets Docker's **default runtime
  to `nvidia`** [S9].
- **CUDA ceiling = 13.0.** Driver branch 580 is the CUDA 13.0 driver [S10]. A container image built on a CUDA
  base newer than 13.0 will **refuse to start**, because NVIDIA's runtime enforces the image's
  `NVIDIA_REQUIRE_CUDA` value [S11]. Concretely: llama.cpp `cuda`/`cuda12` images (CUDA 12.8.1) and vLLM v0.33.0
  (CUDA 13.0.3) are fine. llama.cpp `cuda13` images (CUDA 13.5.0) and vLLM `main` (CUDA 13.2.1) are not [S12][S13].
- **Deploy the stack as TrueNAS custom apps ("Install via YAML").** Each app's YAML is a few lines: an
  `include:` that points at a compose file in a **git working copy on a dataset**, plus `services: {}` (required
  since 25.10) [S14][S15][S16]. To update: `git pull`, then `midclt call -j app.redeploy <app>`. Both tools are on
  the base OS and documented [S17][S18][S19]. The stacks stay visible in the TrueNAS Apps UI, start at boot, and
  get image-update checks. Komodo (in the catalog) is the optional upgrade if the owner wants push-to-deploy.
- **GPU in YAML:** use `deploy.resources.reservations.devices` with `driver: nvidia` and `capabilities: [gpu]`
  (`count: all`, or `device_ids: [GPU-UUID]`), plus `NVIDIA_VISIBLE_DEVICES` and `NVIDIA_DRIVER_CAPABILITIES`.
  This is the same pattern TrueNAS's own app library renders [S7][S16]. `runtime: nvidia` is redundant on
  TrueNAS. Give services that must not see the GPU `NVIDIA_VISIBLE_DEVICES: void`.
- **ZFS ARC cap: supported on 25.10, from the UI.** Go to **System > Advanced Settings > Sysctl > Add**, then set
  **Type = ZFS**, **Variable = `zfs_arc_max`**, **Value = bytes** [S20][S21][S41]. TrueNAS stores the setting in
  its configuration database, applies it immediately, and writes `/etc/modprobe.d/zfs.conf` plus the initramfs,
  so it persists across reboots. For this host, use **12 GiB (`12884901888`)**, which leaves about 38 GiB for
  CPU-offloaded weights. Surviving a version update is expected (the configuration database is migrated) but
  not proven, so check the value after every update.
- **Storage:** create four datasets:
  - `ai/models`: `recordsize=1M`, `lz4`, atime off, optionally `primarycache=metadata`, no snapshots.
  - `ai/appdata`: the **Apps** preset, one child per service.
  - `ai/rag-docs`: the **SMB** preset with an SMB share for dropping files in, mounted **read-only** into
    containers; give the `apps` group (GID 568) Read access through the ACL.
  - `stacks`: the git checkout.

  Keep every byte of state on host-path datasets (no ixVolumes), so that snapshots and replication capture
  everything.
- **Network/TLS:**
  - Move the TrueNAS UI off 80/443 in **System > General Settings > GUI > Settings**.
  - Run **Caddy** (not in the catalog, so as a custom app) on 443 with `tls internal`, a fully offline local
    CA. DNS-01 with the owner's own domain is the alternative. TrueNAS 25.10 **removed its built-in CA** [S22].
  - There is no host firewall UI, and Docker's forwarding policy is ACCEPT [S23][S24]. Publish only the proxy port
    (plus SSH and the UI).
- **Operations:**
  - Logs: Apps UI ▸ Workloads ▸ View Logs, and `/var/log/app_lifecycle.log`.
  - GPU: `nvidia-smi` on the host, plus the `nvidia_gpu_exporter` container. TrueNAS has no GPU reporting graphs.
  - Persistence mode and the power limit: a **Post Init** script.
  - Anything changed in the OS outside the UI or API is lost on update; everything on the pool or in the
    configuration database survives.

## Recommendation

1. **Release:** keep 25.10.8. Do not adopt 27-RC.1. Plan the move to 27.0.x after its first maintenance release.
   Before that move, check that every image still fits the shipped driver's CUDA version, and that no script
   uses the REST API, which is removed in 27 [S5].
2. **GPU:** enable **Install NVIDIA Drivers** (path above). Verify with `nvidia-smi` on the host and inside a test
   container. Add one **Post Init** script that turns on persistence mode and sets a power limit (owner picks
   the watts; 260–280 W is a common efficiency point for a 320 W card [S25]).
3. **Inference images** (input to agents A/B): require **CUDA ≤ 13.0** images (any 12.x, or 13.0.x), or images
   like Ollama that carry their own CUDA 12/13 runners and no `NVIDIA_REQUIRE_CUDA` [S26]. Pin by tag *and* digest.
   Re-check this rule whenever TrueNAS changes the driver branch (it moved 570 → 580 in 25.10.6, and the 26 betas
   briefly shipped 590 [S5]).
4. **Deployment method:** TrueNAS custom apps whose YAML `include:`s compose files from this repo, cloned to
   `/mnt/tank/stacks/local-agent-stack`. Split by lifecycle, so that a change to the web UI does not reload the
   model:
   - `ai-inference`: the LLM server(s).
   - `ai-web`: Caddy, Open WebUI, SearXNG.
   - `ai-rag`: vector DB, embedder, document parser.
   - `ai-ops`: GPU exporter (optional).

   All apps join one external Docker network, `ai-net`, created once. Updating is two commands, run either in
   **System > Shell** or over SSH from c4dev.
5. **Storage:** put apps (ix-apps) and models on the fastest pool (SSD/NVMe), and the dataset layout below on that
   pool. Cap ARC at 12 GiB. Take snapshots of appdata, RAG docs and stacks, but not models; replicate appdata and
   RAG docs to a second pool or machine.
6. **TLS:** Caddy with an internal CA for `*.home.arpa` names (RFC 8375 [S27]). Install the Caddy root on the
   Mac, c4dev and the Windows VM. Move the TrueNAS UI to 8080/8443.
7. **Remote access:** none by default (local-only rule). The Tailscale catalog app is the optional path.

## Options compared

### How to deploy and update the stack on TrueNAS

| Option | What it is | Fit for this host | Maturity | Licence | Verdict |
|---|---|---|---|---|---|
| **Custom app "Install via YAML" + `include:` of compose files in a git checkout** | TrueNAS middleware runs `docker compose` on a wrapper YAML that includes repo files [S16][S18] | Full GPU support (same nvidia runtime); visible in Apps UI with logs/shell; boot start; image-update checks; no extra container with `docker.sock` | `include` is officially a valid top-level key [S14]. The `services: {}` quirk since 25.10 is documented only by the community [S15][S16] | TrueNAS (GPLv3) | **Recommended** |
| Catalog apps (Ollama, Open WebUI, SearXNG, vLLM, Qdrant, LiteLLM, …) | iX-maintained forms in the `community` train [S28] | Has a GPU selector; easy | Maintained, updated often | Per-app | Good for a quick trial. Settings live in a UI form, not in git, so it is **not GitOps** |
| Komodo (catalog app 2.3.4, with MongoDB 8.3.17) | Core + Periphery agent, Stacks deployed from a git repo, webhook or poll, `auto_update` on new image digests [S29][S30] | Works through `docker.sock`; its stacks are invisible in the TrueNAS Apps UI [S31] | Active (v2.3.4, 2026-10-22) | GPL-3.0 (UNVERIFIED) | **Optional upgrade** for push-to-deploy |
| Portainer CE (catalog 2.45.3) | Git-backed stacks, polling or webhook [S32] | "Enable relative path volumes" is Business-only, so compose files need absolute paths | Mature | zlib (CE) (UNVERIFIED) | Heavier than needed |
| Arcane (catalog v2.17.3; upstream v3.0.1 released 2026-11-15) | Docker UI with Git sync | Young, changing fast | New | BSD-3 (UNVERIFIED) | Watch |
| Dockge (catalog 1.5.0) | Compose UI over a stacks folder | No git integration; **no upstream release since 2025-03-30** | Stale | MIT | Not recommended |
| Ubuntu VM with GPU passthrough | Full VM | **Impossible with one GPU**: isolating a GPU for a VM needs at least two GPUs, and an isolated GPU cannot be used by apps [S33] | — | — | Rejected |
| LXC "Containers" with Docker inside | Incus/LXC system container | Experimental on 25.10 [S34]. 27 adds GPU assignment to LXC from the UI [S5] | Experimental | — | Revisit on 27 |

### TLS / reverse proxy on the LAN

| Option | What it is | Fit | Maturity | Licence | Verdict |
|---|---|---|---|---|---|
| **Caddy `caddy:2.11.9` (custom app), `tls internal`** | Local CA run by Caddy; the root is at `/data/caddy/pki/authorities/local/root.crt` [S35][S36] | Fully offline; one root to trust on 3 clients | Mature | Apache-2.0 | **Recommended** |
| Caddy + DNS-01 | Public CA certificate for an owned domain | Needs a custom build with a `caddy-dns` plugin, plus internet for issuance and renewal [S35] | Mature | Apache-2.0 | Option if the owner has a domain |
| Traefik (catalog v3.7.18) | Proxy with built-in ACME DNS providers | Label-based config | Mature | MIT | Fine alternative |
| Nginx Proxy Manager (catalog 2.17.0) | Proxy with a UI, DNS challenge built in | Config lives in the UI, not git | Mature | MIT | Not GitOps |
| TrueNAS built-in CA | — | **Removed in 25.10** [S22] | — | — | Gone |

## Details

### 1. Releases, version check, upgrade path

| Release | Status (2026-11-15) [S1] | Apps backend | NVIDIA driver [S3][S8] | Docker | Kernel / OpenZFS |
|---|---|---|---|---|---|
| 24.04 Dragonfish (last 24.04.2.5) | archive | Kubernetes | — | — | — |
| 24.10 Electric Eel (last 24.10.2.4, 2025-08-07) | not recommended | Docker + compose | 550.127.05 | — | — |
| 25.04 Fangtooth (last 25.04.2.6, 2025-10-30) | not recommended | Docker | 550.142 | — | — |
| **25.10 Goldeye (25.10.8, 2026-11-05)** | **General** | Docker | **580.173.02** (25.10.6+), 570.172.08 (≤25.10.5) | **28.3.1** | 6.12.113 / 2.3.9 |
| 27 (= renamed 26), 27-RC.1 2026-10-06; 27.0 "early December 2026" | Early Adopter | Docker; LXC fully supported | 580.173.02 (26-BETA.1/2 had 590.44.01) | 29.0.4 | 6.18.52 / 2.4.4 |

- **Check the version.** In the UI: **Dashboard** (System Information card), or **System > Update**. In
  **System > Shell**: `midclt call system.version` (the `system.version` method is documented [S37]; since 25.04 it
  returns e.g. `TrueNAS-25.10.8` without the word SCALE).
- **Upgrading from 24.04 or older** (kept short; the owner is already on 25.10.8): automatic Kubernetes→Docker
  migration of apps ended on 2025-06-01 [S38]. Systems still on 24.04 must copy app data out of `ix-applications`
  and reinstall the apps on 24.10+. The path is 24.04.2.5 → 24.10.2.x → 25.04.2.6 → 25.10.8, or a fresh 25.10.8
  ISO install plus a configuration restore [S3][S39].
- **25.10 → 27:** update to the latest 25.10 first; 25.10.8 → 27.0 is the charted path [S5]. Breaking changes in
  27 that matter here:
  - REST API removed: use `midclt`/JSON-RPC only.
  - VMs created on the 25.04 "Instances" screen are dropped.
  - 2FA intervals are restricted.

### 2. NVIDIA GPU

**How the driver ships (verified in source).** The build downloads
`NVIDIA-Linux-x86_64-580.173.02-no-compat32.run`, installs it with `--kernel-module-type=open` into a sysext
image together with `nvidia-container-toolkit`, and ships it as
`/usr/share/truenas/sysext-extensions/nvidia.raw` [S8].

**What the checkbox does.** Ticking it makes middleware:
1. symlink that file into `/run/extensions/`;
2. run `systemd-sysext refresh` and `ldconfig`;
3. `modprobe nvidia nvidia_drm nvidia_modeset`;
4. restart Docker.

The same configuration runs again at every boot [S9]. Nothing is downloaded, and nothing is written to the
read-only root filesystem.

**Enable it (25.10.8):**
1. **Apps** → if you are asked, **Configuration ▾ > Choose Pool** and pick the SSD/NVMe pool → **Choose**.
2. **Apps > Installed > Configuration ▾ > Settings**.
3. Tick **Install NVIDIA Drivers** → **Save**. The checkbox appears only when `docker.nvidia_present` sees a
   non-isolated NVIDIA GPU, and the debug kernel disables it [S6][S41].

   The same dialog holds **Preferred Trains**, **Address Pools** (default base `172.17.0.0/12`, size 24 [S40]),
   **Install NVIDIA Drivers**, **Registry Mirrors** and **Check for docker image updates**. The API equivalent
   is `midclt call -j docker.update '{"nvidia": true}'` [S42].

**Docker daemon effect (verified in 25.10.8 source).** With a non-isolated NVIDIA GPU present, `daemon.json` gets
`"runtimes": {"nvidia": {"path": "/usr/bin/nvidia-container-runtime"}}` and `"default-runtime": "nvidia"` [S9].
Consequences:
- `runtime: nvidia` in compose is harmless but unnecessary.
- **Any** container whose image sets `NVIDIA_VISIBLE_DEVICES=all` (every CUDA base image does [S11]) sees the
  GPU even without a reservation. TrueNAS's own library therefore sets `NVIDIA_VISIBLE_DEVICES=void` on
  non-GPU apps [S7]; do the same for any non-GPU service built on a CUDA image.

**CUDA compatibility with driver 580.173.02.**

| Image built on | Starts on 25.10.6–25.10.8 / 27-RC.1? | Why |
|---|---|---|
| CUDA 12.x (e.g. llama.cpp `cuda`/`cuda12`, CUDA 12.8.1 [S12]) | Yes | The driver is newer than the toolkit |
| CUDA 13.0.x (e.g. vLLM v0.33.0, CUDA 13.0.3 [S13]) | Yes | R580 = CUDA 13.0 [S10] |
| CUDA 13.1+ (llama.cpp `cuda13` = 13.5.0 [S12]; vLLM `main` = 13.2.1 [S13]) | **No** | `NVIDIA_REQUIRE_CUDA=cuda>=13.x` fails, "the container does not start" [S11]. `NVIDIA_DISABLE_REQUIRE=true` bypasses the check, but the program then depends on CUDA 13 minor-version compatibility (≥580) [S10]. UNVERIFIED for llama.cpp/vLLM; avoid it |
| Ollama (CUDA 12.8 and 13.0 runners inside a non-CUDA base [S26]) | Yes | No `NVIDIA_REQUIRE_CUDA` |

**GPU in catalog apps (25.10).** On the install or edit form: **Resources Configuration > GPU Configuration > Select
NVIDIA GPU(s) > Use this GPU** [S6][S43]. The form renders `deploy.resources.reservations.devices: [{driver: nvidia,
device_ids: [<UUID>], capabilities: [gpu]}]` plus `NVIDIA_VISIBLE_DEVICES=<UUID>` and
`NVIDIA_DRIVER_CAPABILITIES=all`, and adds groups 44 (video) and 107 (render) [S7].

**GPU in custom YAML** (pattern from the official Apps docs [S16], adapted):

```yaml
services:
  llm:
    image: <chosen by agent B, CUDA <= 13.0>
    restart: unless-stopped
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all            # one GPU; avoids hard-coding the UUID (a card swap breaks device_ids)
              capabilities: [gpu]
        limits:
          memory: 44G               # bounds the LLM process; see ARC budget
    environment:
      NVIDIA_VISIBLE_DEVICES: all
      NVIDIA_DRIVER_CAPABILITIES: compute,utility
  some-cpu-service:
    environment:
      NVIDIA_VISIBLE_DEVICES: void
```

Multiple containers can share the one GPU; Docker does not make reservations exclusive (Assumed). VRAM
sharing is the stack's problem.

**Verify the driver and the container path** (in **System > Shell**, or SSH + `sudo`):

```sh
nvidia-smi                                   # driver 580.173.02, "CUDA Version: 13.0", RTX 4080
nvidia-smi -L                                # GPU UUID
midclt call docker.config                    # expect "nvidia": true
sudo docker info | grep -i runtime           # expect nvidia listed and "Default Runtime: nvidia"
sudo docker run --rm --gpus all nvidia/cuda:13.0.2-base-ubuntu24.04 nvidia-smi   # throwaway test, amd64 tag exists [S44]
```

Inside a running app: **Apps > Installed >** *app* **> Workloads > Shell** → `nvidia-smi`.

**Known issues and fixes:**
- **Checkbox missing.** Either no NVIDIA GPU was detected, the GPU is isolated (**System > Advanced Settings >
  Isolated GPU Device(s) > Configure**), or the debug kernel is on (**System > Advanced Settings > Kernel**)
  [S6][S21][S33].
- **`nvidia-smi` says no devices.** Untick **Install NVIDIA Drivers** → Save → tick again → Save. Then check
  `dmesg | grep -i nvrm` and `journalctl -u middlewared` [S45][S46].
- **Never replace `nvidia.raw` by hand.** Community scripts that swap it left a system that needed a fresh boot-device
  install [S47].
- **Card swap.** Apps created through the catalog keep the old GPU UUID until they are edited and saved
  (fixed in 25.10.8) [S3]. `count: all` in custom YAML avoids this.
- **Turing or newer only** on 25.10. Ada (cc 8.9) is fine [S2].
- **Host Secure Boot:** TrueNAS 25.10 adds Secure Boot for *VMs*. Forum reports say the host OS itself does not
  boot with Secure Boot on, so leave it disabled in the BIOS. Host Secure Boot is "being worked on" [S48]; its state
  in 27 is UNVERIFIED.
- **Debug kernel disables NVIDIA** [S21].

**Persistence mode and power limit.** Both reset at every boot. NVIDIA calls persistence mode "legacy" in favour of
`nvidia-persistenced` [S49]. Whether TrueNAS runs `nvidia-persistenced` is UNVERIFIED; check `nvidia-smi -q | grep -i
persistence`. Driver setup runs when middleware starts, before Post Init [S9].

Add a script to the repo at `tools/truenas-gpu-init.sh`:

```sh
#!/bin/sh
# wait for the driver (normally already loaded), then set persistence + power limit
i=0; until nvidia-smi >/dev/null 2>&1 || [ $i -ge 30 ]; do i=$((i+1)); sleep 2; done
nvidia-smi -pm 1
nvidia-smi -pl 280      # watts; owner decision. Check range with: nvidia-smi -q -d POWER
```

Register it under **System > Advanced Settings** (first visit shows an advanced-users warning; continue) **>
Init/Shutdown Scripts > Add**:
- **Description** `GPU persistence + power limit`
- **Type** `Script`
- **Script** `/mnt/tank/stacks/local-agent-stack/tools/truenas-gpu-init.sh`
- **When** `Post Init`
- **Enabled**
- **Timeout** `120`
- → **Save**

Field names and options were checked in the 25.10.8 source [S41]. The docs warn that custom scripting is an
advanced feature [S21]. The RTX 4080 and 4080 SUPER are both rated at 320 W TGP; partner cards may differ [S25].

### 3. Deploying the multi-container stack

**Catalog.** Versions below were read from `truenas/apps` main on 2026-11-15, last commit 2026-11-13. The
`community` train has:

| App | Version | Image | min TrueNAS |
|---|---|---|---|
| ollama | 0.40.16 | `ollama/ollama` | 24.10.2.2 |
| open-webui | v0.13.3 | `ghcr.io/open-webui/open-webui` | — |
| searxng | 2026.11.13-219b63b20 | — (+ valkey 9.1.3) | — |
| vllm | v0.33.0 | `vllm/vllm-openai` | — |
| qdrant | v1.20.1 | — (also a `-gpu-nvidia` tag) | — |
| litellm | v1.109.1 | — | — |
| localai | v4.12.1 | — | — |
| traefik | v3.7.18 | — | — |
| nginx-proxy-manager | 2.17.0 | — | — |
| tailscale | v1.104.7 | — | — |
| komodo | 2.3.4 | — | — |
| portainer | 2.45.3 | — | — |
| dockge | 1.5.0 | — | — |
| arcane | v2.17.3 | — | — |
| playwright | v1.65.0-noble | — | — |

Notes:
- **No Caddy and no llama.cpp** in any train [S28].
- Catalog apps offer **Port Bind Mode** (Publish / Expose / None), **Host IPs**, and **Networks** (join an
  existing Docker network) [S50]. Ollama's default host port is 30068.

**Recommended: a custom app per lifecycle group, with the compose files kept in git.**

1. *SSH access.*
   1. **Credentials > Users** → edit `truenas_admin` (the installer's admin user [S51]).
   2. Paste the c4dev key into **Public SSH Key** and tick **SSH Access** [S41].
   3. **System > Services > SSH** → start it and turn on **Start Automatically**.
2. *Datasets* (see §4). `stacks` uses the **Generic** preset, owner `truenas_admin`.
3. *Clone* (git ships in the base OS; middleware depends on it [S17]):

   ```sh
   cd /mnt/tank/stacks && git clone https://github.com/<owner>/local-agent-stack.git
   ```

   A local-only alternative: push from c4dev to a bare repo on the dataset.
4. *Secrets:* keep them outside the repo in `/mnt/tank/stacks/secrets/<app>.env`
   (`chmod 600`, root-owned).
5. *Shared network, once:* `sudo docker network create ai-net`. It lives in the Docker data root on the pool
   (`/mnt/.ix-apps/docker` [S9][S52]); every app's compose declares `networks: {ai-net: {external: true}}`.
   Catalog apps can also join it (they require the network to exist already [S50]). It survives OS updates
   because it is on the pool (Assumed).
6. *Install each app:*
   1. **Apps > Discover Apps** → **⋮ (More Options)** next to **Custom App** → **Install via YAML**.
   2. **Name** `ai-inference` (lower-case, `^[a-z]([-a-z0-9]*[a-z0-9])?$`, at most 40 characters [S53]).
   3. **Custom Config**:

      ```yaml
      include:
        - path: /mnt/tank/stacks/local-agent-stack/stack/inference/compose.yaml
          env_file:
            - /mnt/tank/stacks/secrets/inference.env
      services: {}
      ```

   4. **Save**.

   On save, middleware validates the YAML with `docker compose config`, so the included file must already exist.
   It then runs it as compose project `ix-ai-inference` [S18][S14][S15].
7. *Update after a merge* (from c4dev):

   ```sh
   ssh truenas_admin@192.0.2.10 'cd /mnt/tank/stacks/local-agent-stack && git pull --ff-only \
     && sudo midclt call -j app.redeploy ai-web'
   ```

   - `app.redeploy` re-renders the app and runs `docker compose down`, then `up -d --force-recreate
     --remove-orphans`, so **every container of that app restarts**; hence the split by lifecycle [S18][S19].
   - For newer images under the same tag: `sudo midclt call -j app.pull_images ai-web` (pulls with
     `--policy always`, then redeploys) [S54].
   - **Check for docker image updates** flags outdated images per app; it is computed from running containers, so
     it covers included services too (inferred from source [S54]). The update notices for custom apps came back in
     25.10 [S3]. The **Update** item sits under **⋮** on the app's Application Info card [S55].
   - `midclt` flags (`-j/--job`) were verified in the current client source [S19]. Remote API use from c4dev
     needs `--plain` against 25.10, which has no SCRAM [S19]; SSH is simpler.
8. *What the UI can't do here:* edit the included files. The **Edit** screen only shows the wrapper.

### 4. Storage

| Dataset (pool on SSD/NVMe) | Preset | Properties | Snapshots | Mount into containers |
|---|---|---|---|---|
| `tank/ai/models` | Generic | Record Size **1M**, Compression **LZ4** (or OFF), Enable Atime **Off**; optional `primarycache=metadata` (shell) | none (re-downloadable) | rw for the downloader, ro for servers |
| `tank/ai/appdata/<service>` | **Apps** (NFSv4, group 568 modify, atime off) | default 128K, LZ4 | daily, keep 14 | rw |
| `tank/ai/appdata/postgres` (if pgvector) | Apps | Record Size **32K** (64K or 128K also fine), LZ4 [S56] | daily | rw |
| `tank/ai/rag-docs` | **SMB** (+ **Create SMB Share**) | LZ4 | hourly, keep 48 | **ro** |
| `tank/stacks` | Generic | default | daily | — (host-side git) |

- **Create a dataset:** **Datasets** → select the parent → **Add Dataset** → **Name**, **Dataset Preset** →
  **Advanced Options** (Other Options: **Compression Level**, **Enable Atime**, **Record Size**, **ACL Type**) →
  **Save**. Preset, case sensitivity and name cannot be changed later [S57][S41]. The Compression API accepts `OFF`
  and `LZ4` [S58]. `1M` record size suits sequential large files; up to 16M is possible with `large_blocks` [S56].
- **`primarycache=metadata` on `ai/models`** (Assumed benefit, test it): on Linux, mmapped files on ZFS can be
  cached twice (ARC + page cache) [S59]. Capping ARC limits the damage; setting
  `sudo zfs set primarycache=metadata tank/ai/models` stops ARC from holding model data at all. The property is
  not in the TrueNAS dataset API [S60], so it must be set from the shell. It is stored on the pool and should
  survive OS updates (Assumed). The alternative is to have the LLM server load without mmap (agent B decides).
- **Permissions:** the Apps preset grants **group 568 (apps)** modify. Run services as `user: "568:568"` where the
  image allows it; root in a container is root on the host (no user namespaces).
- **RAG docs share:**
  1. Create an SMB user: **Credentials > Users > Add**, tick **SMB Access** (a share cannot be reached as root
     or built-in users) [S61][S41].
  2. Create `rag-docs` with the **SMB** preset and tick **Create SMB Share**. Or later: **Shares > Windows (SMB)
     Shares > Add > Path**, **Purpose = Default Share** → **Save** → start the service when asked.
     **System > Services > SMB > Start Automatically** [S61].
  3. Let containers read it: **Datasets** → `rag-docs` → **Permissions > Edit** → **Add Item** → **Who: Group**,
     **Group: apps**, **Permissions: Basic / Read** → **Apply permissions recursively** → **Save Access Control
     List** [S62].
  4. Compose: `- /mnt/tank/ai/rag-docs:/docs:ro`.
- **Snapshots:** **Data Protection > Periodic Snapshot Tasks > Add** → **Dataset**, **Exclude**, **Recursive**,
  **Snapshot Lifetime**, **Naming Schema**, **Schedule** → **Save** [S63][S41].
- **Replication:** **Data Protection > Replication Tasks > Add** (wizard) to a second pool or another TrueNAS
  [S64].
- **ix-apps:** the `ix-apps` dataset (mounted at `/mnt/.ix-apps`, always unencrypted [S52]) is hidden in the UI.
  Backing it up or restoring it is not a supported UI feature [S65]. With everything in host paths and git, it
  only holds re-pullable images plus the wrapper YAMLs.
- **Configuration backup:** **System > Advanced Settings > Manage Configuration > Download File**, with **Export
  Password Secret Seed** ticked [S66]. Do this before every update.

**ZFS ARC cap (the supported way on 25.10).**

*UI:*
1. **System > Advanced Settings > Sysctl > Add**. The form title is "Add Sysctl".
2. **Type: `ZFS`**, **Variable: `zfs_arc_max`**, **Value: `12884901888`**, **Description:** `cap ARC at 12 GiB
   for model offload`, **Enabled** → **Save**.

The **Type** dropdown (SYSCTL / UDEV / ZFS) is in the 25.10.8 form [S41] even though the 25.10 docs page leaves
it out [S20]. The 27 docs show the same flow with a 16 GiB example [S67].

*API equivalent:*

```sh
sudo midclt call -j tunable.create '{"type":"ZFS","var":"zfs_arc_max","value":"12884901888","comment":"ARC cap"}'
```

`tunable.create` type `ZFS` "is a ZFS kernel module parameter name" [S20]. TrueNAS's own 25.10.8 test suite
sets `zfs_arc_max` exactly this way. The test shows the value live in `/sys/module/zfs/parameters/zfs_arc_max`,
`options zfs …` in `/etc/modprobe.d/zfs.conf`, an initramfs rebuild, and the root filesystem still read-only [S21].

*Persistence:*
- Across reboots: yes (modprobe.d + initramfs, regenerated from the configuration database) — Verified.
- Across version updates: expected, because tunables live in the configuration database that updates migrate —
  Assumed. After each update, run `cat /sys/module/zfs/parameters/zfs_arc_max`.
- A lower cap does not shrink ARC instantly [S68]. Reboot once after setting it.
- Do not set `zfs_arc_min` equal to max [S68].
- Starting or stopping VMs makes middleware adjust ARC [S68][S69]; avoid VMs on this host.
- Do **not** use the older community hacks: an `echo` in a Post Init script, or `kernel_extra_options`.

*Memory budget* (estimates, Assumed):

| Usable RAM | `zfs_arc_max` | OS + middleware + SMB | Non-LLM containers | Headroom | Left for the LLM process (weights offloaded to CPU + KV) |
|---|---|---|---|---|---|
| 32 GB (~31 GiB) | 4 GiB `4294967296` | ~4 GiB | ~4 GiB | 2 GiB | ~17 GiB |
| **64 GB (62.3 GiB, this host)** | **12 GiB `12884901888`** | ~4 GiB | ~5 GiB | 3 GiB | **~38 GiB** |
| 64 GB, offload pushed to ~42 GiB | 8 GiB `8589934592` | ~4 GiB | ~5 GiB | 3 GiB | ~42 GiB |
| 128 GB (~125 GiB) | 24 GiB `25769803776` | ~4 GiB | ~6 GiB | 4 GiB | ~87 GiB |

Also set `deploy.resources.limits.memory` on the LLM service (the library renders limits the same way [S7]).
That way a runaway process is OOM-killed inside its own container instead of the host killing something else.

### 5. Networking and access

**Ports.**

| Service | Port |
|---|---|
| TrueNAS UI | 80/443 by default → move to **8080/8443** |
| SSH | 22 |
| SMB | 445 |
| Caddy | 80, 443 (`192.0.2.10`) |
| Everything else | not published; reached through `ai-net` |

Optionally publish the LLM API port for c4dev, but preferably route it through Caddy with TLS and an API key.

**Move the UI.** **System > General Settings > GUI > Settings** → **Web Interface HTTP Port** `8080`, **Web
Interface HTTPS Port** `8443` → **Save** (fields and defaults verified [S70][S41]). The UI then lives at
`https://192.0.2.10:8443`.

Alternative: add a second address under **System > Network > Interfaces** → edit → **Static IP Addresses** → **Add**
(the label is from the 25.10.8 source [S41]; editing interfaces carries a test-and-confirm step, Assumed). Then
bind **Web Interface IPv4 Address** to one IP and Caddy (`ports: ["192.0.2.11:443:443"]`) to the other.

**Bridge or host network.** Use bridge networks with published ports. Host networking disables port mapping
[S43] and is only needed for mDNS-style discovery, which this stack doesn't need. The default Docker address
pool is `172.17.0.0/12` /24. If it clashes with the LAN, change it under **Apps > Installed > Configuration >
Settings > Address Pools** [S40][S41].

**Firewall.**
- TrueNAS has no host firewall UI; a supported nftables configuration is a feature request [S23].
- With Apps on, IP forwarding is enabled and the `FORWARD` policy is ACCEPT through a TrueNAS systemd override
  for Docker (`NAS-141332`, reported on 25.10.4) [S24].
- Mitigation: publish only what is needed and bind to specific host IPs. Do not port-forward from the router.
  Do not hand-edit iptables, because it is wiped on update.

**TLS with Caddy `tls internal`.** Image `caddy:2.11.9`, Docker Hub library, multi-arch.

```caddyfile
chat.home.arpa {
	tls internal
	reverse_proxy open-webui:8080
}
api.home.arpa {
	tls internal
	reverse_proxy llm:8080
}
```

- Persist `/data` and `/config` on `tank/ai/appdata/caddy` [S36].
- Copy `/data/caddy/pki/authorities/local/root.crt` out, then trust it [S36]:
  - Ubuntu: `/usr/local/share/ca-certificates/` + `sudo update-ca-certificates`.
  - macOS: `security add-trusted-cert` into the System keychain.
  - Windows: `certutil -addstore ROOT`.
- Browsers with their own trust store need a manual import [S36].
- Node and Python agent tools often ignore the OS store: set `NODE_EXTRA_CA_CERTS` /
  `REQUESTS_CA_BUNDLE` / `SSL_CERT_FILE` (Assumed; for agent C).
- Leaf certificates are short-lived and renew automatically (`internal` lifetime default 12h [S35]).
- Names: `*.home.arpa` [S27], via the router's DNS or the hosts file on each client.

DNS-01 alternative: Traefik (catalog) or a Caddy build with a `caddy-dns` plugin, plus the owner's domain.
Internet is needed only for issuance and renewal [S35].

**Remote access.** The Tailscale catalog app (v1.104.7) is the optional route. Nothing should be exposed to the
internet.

### 6. Operations

- **Updating images:** see §3 step 7. Pin images by tag and digest in the repo, as the catalog does [S28], and
  bump them through PRs. `app.pull_images` is for floating tags.
- **Logs:**
  - **Apps > Installed >** *app* **> Workloads > View Logs**, with **Shell** next to it [S55].
  - Host side: `/var/log/app_lifecycle.log` (compose errors [S18]) and `sudo docker logs ix-<app>-<service>-1`.
- **Resource limits:** `deploy.resources.limits.{cpus,memory}` in compose. With 32 threads, give the LLM server most
  CPU threads and cap the rest.
- **GPU monitoring:**
  - `nvidia-smi dmon`, or `nvidia-smi --query-gpu=utilization.gpu,memory.used,power.draw,temperature.gpu --format=csv -l 5`.
  - 25.10 has no GPU dashboard widget or reporting graphs [S71].
  - Prometheus: `utkuozdemir/nvidia_gpu_exporter:1.18.0-nvml` (Docker Hub/GHCR, amd64, port 9835 [S72]) in
    `ai-ops`, with the catalog `prometheus` + `grafana` apps.
  - NVIDIA `dcgm-exporter` (4.9.0, `nvcr.io/nvidia/k8s/dcgm-exporter`) targets data-centre GPUs; GeForce support
    is UNVERIFIED.
  - `nvtop` is not in the base OS (checked against the 25.10.8 package manifest [S17]).
- **Auto-start after reboot:** middleware starts Docker at system-ready [S52]. Containers with
  `restart: unless-stopped` (the catalog default [S7]) come back on their own; set it on every custom service.
  Known 25.10 race: apps that mount SMB/NFS *shares* can show "crashed" after boot [S3]. We bind host paths
  instead, so this does not apply.
- **What survives a TrueNAS update:**
  - Survives: the pool (datasets, `ix-apps` with images, app definitions, Docker networks) and the configuration
    database (apps settings including the NVIDIA flag, tunables, init scripts, shares, snapshot tasks, users and
    keys).
  - Lost: anything in the read-only root filesystem changed outside the UI/API (apt packages, `/etc` or `/usr`
    edits, a hand-replaced `nvidia.raw`, hand-written systemd units or iptables rules) [S73][S47].
  - Rollback: boot environments under **System > Boot** (menu entry verified [S41]; activation steps Assumed).
- **Risks per update:**
  - A driver-branch change breaks the CUDA ceiling (keep the §2 table current).
  - Docker major bumps (28 → 29 in 27).
  - Compose behaviour changes (the `services: {}` requirement appeared in 25.10).
  - REST API removal in 27.
  - Mitigation: before each update, take a snapshot, download the config, read the release notes. After it, run
    `nvidia-smi`, check the ARC value, and run a smoke test.

## Fit with Claude Code features

| Feature | How the platform supports it | What is lost |
|---|---|---|
| Local-only core path | The driver, container toolkit and stack run with no internet; the driver ships in the OS image [S8] | Pulling images, `git pull` and DNS-01 need internet (not part of the core path) |
| Remote work over SSH | TrueNAS SSH with keys; the agent on c4dev drives deploys over SSH | No supported way to install extra tools on the host; use containers |
| Sandboxing / permission modes | Containers isolate services; no `docker.sock` needed with the recommended method | Root in a container is host root; there is no host firewall UI |
| GitHub integration / GitOps | Compose in the repo; `git pull` + `app.redeploy` | No webhook auto-deploy without Komodo |
| Web search | SearXNG is a catalog app, or goes in the stack | — |
| Reading documents / RAG | SMB drop-folder mounted read-only; snapshotted hourly | — |
| Long-running or background work | Apps restart on boot and failure | A whole-app restart on every redeploy (mitigated by the split) |

## Verified vs assumed

**Verified** (primary source read on 2026-11-15):
- Release list and dates; 25.10.8 is the General pick; 27-RC.1 on 2026-10-06; 27.0 in early December [S1][S4][S5].
- 25.10.x component versions: NVIDIA 570.172.08 → 580.173.02 from 25.10.6; Docker 28.3.1; kernel 6.12.113;
  OpenZFS 2.3.9 [S3]. 27-RC.1: 580.173.02, Docker 29.0.4 [S5]. 24.10/25.04 drivers 550.127.05 and 550.142 [S8].
- The driver is built with `--kernel-module-type=open` into a sysext with `nvidia-container-toolkit` [S8]; the
  checkbox symlinks it, refreshes the sysext and modprobes; `daemon.json` sets `default-runtime: nvidia` [S9].
- Every 25.10 UI label and click path quoted above, checked in the 25.10 docs and/or the `TS-25.10.8` web UI
  source [S6][S21][S41][S57][S61][S62][S63][S66][S70].
- ZFS tunable type and `zfs_arc_max` through `tunable.create` (API docs, 25.10.8 tests) [S20][S21].
- The GPU compose rendering in the TrueNAS library, `NVIDIA_VISIBLE_DEVICES=void` for non-GPU apps, groups 44/107
  [S7]; GPU YAML in the official Apps docs [S16].
- `app.redeploy` = force-recreate; `app.pull_images` = pull `--policy always` + redeploy; project prefix `ix-`;
  compose validated with `docker compose config` [S18][S54]. `midclt -j`, `--plain` before 26 [S19].
- git ships in the base OS [S17]; `include:` accepted as a top-level key [S14].
- NVIDIA env-var semantics and the `NVIDIA_REQUIRE_CUDA` refusal [S11]; CUDA ↔ driver branch table [S10]; the
  CUDA versions of the llama.cpp, vLLM and Ollama images [S12][S13][S26].
- Catalog contents, versions and images [S28]. Caddy root path and client trust commands [S36]. 25.10 removed its
  built-in CA [S22]. OpenZFS recordsize guidance [S56]. RTX 4080 TGP 320 W [S25].

**Assumed** (inference, forum reports or memory):
- The `services: {}` requirement for `include` apps on 25.10 (community: forum + TechnoTim) [S15][S16b].
- The ARC tunable survives *version* updates (the config DB migrates; not tested).
- `primarycache=metadata` helps model loading, and `zfs set` properties survive updates.
- `docker network create ai-net` persists across updates.
- Post Init runs after NVIDIA setup.
- Host Secure Boot is unsupported on 25.10 (forum) [S48].
- Docker GPU reservations are not exclusive.
- The memory budget numbers.
- Node/Python CA environment variables.
- Image updates are detected for included services.
- Komodo, Portainer and Arcane licences.

UNVERIFIED: GeForce support in DCGM; `nvidia-persistenced` running on TrueNAS; whether `NVIDIA_DISABLE_REQUIRE`
plus minor-version compatibility works for llama.cpp `cuda13`.

## Open questions for the owner

1. Which pool goes on SSD/NVMe for `ix-apps` and models, and how much space is free for models (tens to hundreds
   of GB)?
2. TLS: a local CA (offline; trust one root on 3 clients), or DNS-01 with a domain you own?
3. TrueNAS UI: move to 8080/8443, or keep 443 and add a second IP for the proxy?
4. GPU power limit: full 320 W, or a capped 260–280 W for 24/7 efficiency and heat?
5. How many DIMMs fill the w5-3435X's 8 memory channels? This sets the speed of CPU-offloaded MoE layers
   (Assumed relevance; for agents A/B).
6. Is manual `git pull` + `redeploy` enough, or do you want push-to-deploy (Komodo)?
7. Remote access: none (default), or Tailscale?
8. When to move to 27.0: suggested after 27.0.1, with the CUDA check repeated first.

## Sources

All read 2026-11-15.

1. https://www.truenas.com/help-me-choose (software status, release dates)
2. https://update.freenas.org/scale/TrueNAS-SCALE-Goldeye/TrueNAS-SCALE-25.10.0.release-notes.txt
3. https://www.truenas.com/docs/scale/25.10/gettingstarted/versionnotes/ (component table, 25.10.x changelogs, upgrade chart, known issues)
4. https://www.truenas.com/blog/truenas-27-is-here/ (2026-10-05, rename 26→27)
5. https://www.truenas.com/docs/scale/27/gettingstarted/versionnotes/ (27-RC.1 components, breaking changes, LXC GPU)
6. https://www.truenas.com/docs/scale/25.10/scaleuireference/apps/ (Apps screens, Settings, Install via YAML)
7. https://github.com/truenas/apps/tree/main/library/2.3.19 (`resources.py`, `environment.py`, `container.py`, `restart.py`)
8. https://github.com/truenas/scale-build (`scale_build/extensions.py` and `conf/build.manifest` at tags `TS-25.10.8`, `release/25.10.0`, `release/25.04.2.6`, `release/24.10.2.4`)
9. https://github.com/truenas/middleware/blob/release/25.10.8/src/middlewared/middlewared/etc_files/docker/daemon.json.py and `plugins/docker/update.py`, `plugins/docker/state_management.py`
10. https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html (driver tables, minor-version compatibility)
11. https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/docker-specialized.html
12. https://github.com/ggml-org/llama.cpp (`.devops/cuda.Dockerfile`, `.github/workflows/docker.yml`)
13. https://github.com/vllm-project/vllm (`docker/Dockerfile` at `v0.33.0` and `main`)
14. https://apps.truenas.com/managing-apps/installing-custom-apps/
15. https://forums.truenas.com/t/25-10-0-ge-custom-app-vs-ee-custom-app-deployment/57684 (2025-10-30)
16. https://apps.truenas.com/managing-apps/installing-custom-apps/ (GPU YAML example). 16b. https://docs.technotim.com/posts/truenas-docker-pro/ (updated 2026-01-07)
17. https://github.com/truenas/scale-build/blob/TS-25.10.8/conf/build.manifest (git, htop; no jq or nvtop)
18. https://github.com/truenas/middleware/tree/release/25.10.8/src/middlewared/middlewared/plugins/apps (`compose_utils.py`, `crud.py`, `custom_app_utils.py`, `utils.py`)
19. https://github.com/truenas/api_client/blob/master/truenas_api_client/__init__.py (midclt options)
20. https://api.truenas.com/v25.10/api_methods_tunable.create.html and https://www.truenas.com/docs/scale/25.10/scaletutorials/systemsettings/advanced/
21. https://www.truenas.com/docs/scale/25.10/scaleuireference/systemsettings/advancedsettingsscreen/ and https://github.com/truenas/middleware/blob/release/25.10.8/tests/api2/test_tunables.py
22. Same as 2 (CA removed in 25.10)
23. https://forums.truenas.com/t/allow-configuration-of-host-firewall-nftables-iptables/24261
24. https://forums.truenas.com/t/why-is-truenass-default-forward-policy-set-to-accept/66348 (2026-06-09)
25. https://www.nvidia.com/en-us/geforce/graphics-cards/40-series/rtx-4080/
26. https://github.com/ollama/ollama/blob/main/Dockerfile (CUDA 12.8 and 13.0 runners)
27. https://www.rfc-editor.org/rfc/rfc8375.html
28. https://github.com/truenas/apps/tree/main/ix-dev (community, stable; `app.yaml`, `ix_values.yaml`; last commit 2026-11-13)
29. https://komo.do/docs/deploy/compose
30. https://komo.do/docs/resources
31. https://forums.truenas.com/t/moved-to-roadmap-display-non-ix-managed-stacks-and-containers-on-apps-screen/11617
32. https://docs.portainer.io/user/docker/stacks/add
33. https://www.truenas.com/docs/scale/25.10/scaletutorials/systemsettings/advanced/managegpuscale/
34. https://www.truenas.com/docs/scale/25.10/scaletutorials/containers/
35. https://caddyserver.com/docs/caddyfile/directives/tls and https://caddyserver.com/docs/automatic-https
36. https://caddyserver.com/docs/running
37. https://api.truenas.com/v26.0/_sources/api_methods_system.version.rst.txt; https://forums.truenas.com/t/get-api-v2-0-system-version-no-longer-includes-scale-in-version-string-breaking-detection-logic/40366
38. https://www.truenas.com/blog/app-migration-deadline (2025-05-28)
39. https://forums.truenas.com/t/best-upgrade-path-from-truenas-scale-24-04-2-5-without-losing-official-apps-configs/68173 (2026-10)
40. https://github.com/truenas/middleware/blob/release/25.10.8/src/middlewared/middlewared/plugins/docker/update.py (default address pools)
41. https://github.com/truenas/webui/tree/TS-25.10.8 (navigation service, apps-settings, custom-app-button, sysctl tunable-form, init-shutdown form, GUI form, dataset form, user form, interface form, snapshot task form)
42. https://api.truenas.com/v25.10/api_methods_docker.update.html
43. https://www.truenas.com/docs/scale/25.10/scaleuireference/apps/installcustomappscreens/
44. https://hub.docker.com/r/nvidia/cuda (tag `13.0.2-base-ubuntu24.04`, amd64)
45. https://ixsystems.atlassian.net/browse/NAS-132070
46. https://forums.truenas.com/t/nvidia-smi-showing-no-devices-while-showing-inside-apps/67084 (2026-07-25)
47. https://forums.truenas.com/t/nvidia-gpu-drivers-not-loading-or-gpu-not-loading-correctly/67367 (2026-08-08)
48. https://forums.truenas.com/t/feedback-captured-add-support-for-secure-boot-to-scale/9727 and the 25.10 RC thread https://forums.truenas.com/t/truenas-25-10-rc-1-is-now-available/54880
49. https://docs.nvidia.com/deploy/driver-persistence/
50. https://github.com/truenas/apps/blob/main/ix-dev/community/ollama/questions.yaml
51. https://github.com/truenas/truenas-installer/blob/master/truenas_installer/installer_menu.py
52. https://github.com/truenas/middleware/blob/release/25.10.8/src/middlewared/middlewared/plugins/docker/state_utils.py
53. https://api.truenas.com/v25.10/api_methods_app.create.html
54. https://github.com/truenas/middleware/blob/release/25.10.8/src/middlewared/middlewared/plugins/apps/pull_images.py; https://api.truenas.com/v25.10/api_methods_app.pull_images.html
55. https://www.truenas.com/docs/scale/27/apps/appsscreens/ (Installed screen cards, same layout in 25.10 per [S6])
56. https://openzfs.github.io/openzfs-docs/Performance%20and%20Tuning/Workload%20Tuning.html
57. https://www.truenas.com/docs/scale/25.10/scaletutorials/datasets/datasetsscale/ and https://www.truenas.com/docs/scale/25.10/scaleuireference/datasets/
58. https://api.truenas.com/v25.10/api_methods_pool.dataset.create.html (compression enum)
59. https://lists.freebsd.org/pipermail/freebsd-hackers/2016-July/049695.html (mechanism; old, not Linux-specific)
60. Same as 58 (`primarycache` absent)
61. https://www.truenas.com/docs/scale/25.10/scaletutorials/shares/smb/
62. https://www.truenas.com/docs/scale/25.10/scaletutorials/datasets/permissionsscale/
63. https://www.truenas.com/docs/scale/25.10/scaletutorials/dataprotection/periodicsnapshottasksscale/
64. https://www.truenas.com/docs/scale/25.10/gettingstarted/configure/setupbackupscale/
65. https://forums.truenas.com/t/some-questions-about-the-ix-apps-dataset/58194
66. https://www.truenas.com/docs/scale/25.10/scaletutorials/systemsettings/advanced/managesysconfig/
67. https://www.truenas.com/docs/scale/27/systemsettings/advanced/advancedsettings/
68. https://forums.truenas.com/t/zfs-cache-preventing-app-from-getting-allocated-memory-it-needs/57796 (2025-10/11); https://forums.truenas.com/t/zfs-arc-using-more-than-zfs-arc-max/56032
69. https://github.com/truenas/middleware/blob/release/25.10.8/src/middlewared/middlewared/plugins/sysctl/sysctl_info.py
70. https://www.truenas.com/docs/scale/25.10/scaleuireference/systemsettings/generalsettingsscreens/
71. https://www.truenas.com/docs/scale/25.10/scaleuireference/reportingscreensscale/
72. https://github.com/utkuozdemir/nvidia_gpu_exporter (v1.18.0, 2026-11-07)
73. https://forums.truenas.com/t/trying-to-undestand-the-specifics-of-the-read-only-rootfs/53578
