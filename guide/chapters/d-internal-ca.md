title: TLS with an internal certificate authority
kind: appendix

# TLS with an internal certificate authority

Chapter 6 obtains publicly trusted certificates for your own domain through the ACME DNS-01
challenge. This appendix describes the alternative: Caddy runs its own local certificate
authority (CA) and signs the certificates itself. The internal CA works fully offline and needs no
domain, no DNS provider and no API token. In exchange, you install one root certificate on every
client that connects to the stack: the workstation `c4dev`, the Mac and the Windows VM, and in any
browser or tool that keeps its own list of trusted authorities.

TrueNAS 25.10 no longer includes a built-in certificate authority, so the CA lives in Caddy. The
procedures use the `ai-edge` app of Chapter 6 with one change: a copy of the release's
`Caddyfile` in which the DNS-01 settings are replaced by `tls internal`.

## How the internal CA works

### Certificates and where Caddy keeps them

On its first start with `tls internal`, Caddy creates a root certificate named
`Caddy Local Authority - <year> ECC Root` and an intermediate certificate, and signs the site
certificates with the intermediate. The stack's `Caddyfile` serves one wildcard site,
`*.<LAB_DOMAIN>`, so Caddy signs one certificate that covers every host name of the stack.

Table: Internal CA certificates

| Certificate | Lifetime | Renewal |
|---|---|---|
| Root (`root.crt`, `root.key`) | 3600 days (about 10 years) | None; clients trust this certificate |
| Intermediate | 7 days | Automatic |
| Site certificate (`*.<LAB_DOMAIN>`) | 12 hours | Automatic |

Caddy keeps the CA in its data directory, `/data/caddy/pki/authorities/local/` inside the
container, which the `ai-edge` app stores at
`/mnt/tank/ai/appdata/caddy/data/caddy/pki/authorities/local/` on the server. Snapshots and
replication of `tank/ai/appdata` protect it (Appendix A). If the data directory is lost, Caddy
creates a new root on its next start, and every client must trust the new root.

!!! warning
    Anyone who holds `root.key` can issue certificates that your clients trust for any name. Copy
    only `root.crt` to clients. Never copy `root.key` off the server, and treat the snapshots and
    replicas of `tank/ai/appdata` as sensitive.

### Choose the lab domain

The host names are built from `LAB_DOMAIN` in `edge.env`, as with DNS-01. With an internal CA,
use one of the following:

- A subdomain of `home.arpa`, the name that RFC 8375 reserves for home networks, for example
  `lab.home.arpa`. Do not use `home.arpa` itself: it is on the Public Suffix List, and browsers
  reject a wildcard certificate placed directly below a public suffix.
- A subdomain of a domain you own, for example `lab.example.com`, without publishing it.

The rest of this appendix uses `lab.home.arpa`.

Table: Host names with the internal CA

| Host name | Used by |
|---|---|
| `chat.lab.home.arpa` | Browsers (Open WebUI) |
| `llm.lab.home.arpa` | OpenCode, Claude Code, scripts (LiteLLM) |
| `models.lab.home.arpa` | Administrators (llama-swap) |
| `mcp.lab.home.arpa` | OpenCode, Open WebUI (MCP hub) |
| `search.lab.home.arpa` | Administrators (SearXNG) |

## Configure the edge app for the internal CA

These tasks replace the DNS-01 steps of Chapter 6. The other steps of that chapter apply
unchanged.

### Add the lab host names to DNS

#### About this task

The clients must resolve every host name to the TrueNAS server. Add A records in your local DNS
server or router. If that is not possible, add the names to the hosts file of each client.

#### Steps

1. In your local DNS server or router, add an A record for each host name in the table above,
   pointing to `192.0.2.10`.

    Alternatively, add the following line to `/etc/hosts` on Linux and macOS, and to
    `C:\Windows\System32\drivers\etc\hosts` on Windows (edit as administrator):

        192.0.2.10 chat.lab.home.arpa llm.lab.home.arpa models.lab.home.arpa mcp.lab.home.arpa search.lab.home.arpa

2. Verify the name on each client:

    - Ubuntu: `getent hosts chat.lab.home.arpa`
    - macOS: `dscacheutil -q host -a name chat.lab.home.arpa`
    - Windows (PowerShell): `Resolve-DnsName chat.lab.home.arpa`

    Each command returns `192.0.2.10`.

### Set the edge environment for the internal CA

#### About this task

The compose file of `ai-edge` requires `LAB_DOMAIN`, `ACME_EMAIL` and `DNS_PROVIDER_TOKEN` to be
set. With the internal CA, Caddy uses only `LAB_DOMAIN`; the other two need a value but are not
used to obtain the lab certificates.

#### Steps

1. On the workstation, edit `~/.config/local-agent-stack/secrets/edge.env` and set the following
   values:

        LAB_DOMAIN=lab.home.arpa
        ACME_EMAIL=admin@example.com
        DNS_PROVIDER_TOKEN=unused

2. Copy the file to the server and install it as in
   [Copy the environment files to TrueNAS](#copy-the-environment-files-to-truenas):

        scp ~/.config/local-agent-stack/secrets/edge.env truenas_admin@192.0.2.10:

    Then, on TrueNAS:

        sudo install -m 0600 -o root -g root ~/edge.env /mnt/tank/ai/secrets/
        rm ~/edge.env

3. Verify the values on the server:

        sudo grep -E '^(LAB_DOMAIN|ACME_EMAIL|DNS_PROVIDER_TOKEN)=' /mnt/tank/ai/secrets/edge.env

    The output shows the three values from step 1.

### Create the internal CA Caddyfile

#### About this task

The release's `Caddyfile` stays unchanged in the git clone. A copy under
`/mnt/tank/ai/appdata/caddy` replaces its `tls { ... }` block, which configures the DNS-01
challenge, with `tls internal`, and adds the global option `skip_install_trust`, which stops Caddy
from trying to install its root into the container's own trust store. A small compose override
file then mounts the copy in place of the release's file.

!!! note
    Repeat this task after every release update, so that the copy follows the release's
    `Caddyfile`.

#### Steps

1. Create the Caddy directory, if it does not exist yet:

        sudo install -d /mnt/tank/ai/appdata/caddy

2. Write the internal CA copy of the `Caddyfile`:

        sudo sed -e '/^\ttls {$/,/^\t}$/c tls internal' -e '/^\tpersist_config off$/a skip_install_trust' /mnt/tank/ai/stacks/local-agent-stack/stack/edge/Caddyfile | sudo tee /mnt/tank/ai/appdata/caddy/Caddyfile.internal-ca > /dev/null

3. Verify the changes:

        sudo grep -nE 'tls internal|skip_install_trust|import dns-' /mnt/tank/ai/appdata/caddy/Caddyfile.internal-ca

    The output has exactly two lines, `skip_install_trust` and `tls internal`, and no
    `import dns-` line. If the output differs, the release's `Caddyfile` has changed; compare it
    with the copy and edit the copy by hand.

4. Write the compose override file:

        sudo tee /mnt/tank/ai/appdata/caddy/internal-ca.override.yaml > /dev/null <<'EOF'
        services:
          caddy:
            volumes:
              - /mnt/tank/ai/appdata/caddy/Caddyfile.internal-ca:/etc/caddy/Caddyfile:ro
        EOF

    Compose merges volume entries by their target path, so this entry replaces the release's
    `./Caddyfile:/etc/caddy/Caddyfile:ro` mount.

#### Results

The copy and the override file are on the `tank/ai/appdata` dataset, which the backup tasks of
Appendix A protect.

### Install the ai-edge app with the internal CA

#### About this task

The app's YAML lists two files under `path`: the release's compose file and the override file.
Compose merges them before it includes the result. TrueNAS validates the YAML with
`docker compose config` when you save it.

#### Steps

1. Go to **Apps** > **Discover Apps**, click **More Options** (⋮) next to **Custom App**, and click
   **Install via YAML**.

    If `ai-edge` is already installed, go to **Apps** > **Installed**, select `ai-edge`, and click
    **Edit** instead.

2. Enter **Name** `ai-edge`.

3. Enter the following YAML in **Custom Config**:

        include:
          - path:
              - /mnt/tank/ai/stacks/local-agent-stack/stack/edge/compose.yaml
              - /mnt/tank/ai/appdata/caddy/internal-ca.override.yaml
            env_file: /mnt/tank/ai/secrets/edge.env
        services: {}

4. Click **Save**.

5. When the app is running, verify the configuration inside the container:

        sudo docker exec caddy grep -c 'tls internal' /etc/caddy/Caddyfile

    The output is `1`.

6. Verify that Caddy keeps its data on the dataset:

        sudo docker inspect caddy --format '{{range .Mounts}}{{println .Destination .Source}}{{end}}'

    The output includes `/data /mnt/tank/ai/appdata/caddy/data`.

7. From the workstation, display the certificate that Caddy serves:

        echo | openssl s_client -connect 192.0.2.10:443 -servername chat.lab.home.arpa 2>/dev/null | openssl x509 -noout -subject -issuer -ext subjectAltName

    The issuer is `CN=Caddy Local Authority - ECC Intermediate` and the subject alternative name
    is `DNS:*.lab.home.arpa`.

#### Results

Caddy serves every host name with a certificate from its internal CA. Clients do not trust it yet.

!!! note
    Caddy logs a warning that its input "is not formatted". The edited lines are not indented;
    the warning has no effect.

## Trust the internal root certificate on clients

Each client needs the root certificate, `root.crt`, in its trust store. Copy the file once from the
server, check its hash on every client, and install it.

### Export the root certificate from TrueNAS

#### Steps

1. Copy the root certificate out of the container into the home directory of `truenas_admin`:

        sudo docker cp caddy:/data/caddy/pki/authorities/local/root.crt ~/caddy-root.crt

2. Make the copy readable by `truenas_admin`:

        sudo chown truenas_admin:truenas_admin ~/caddy-root.crt

3. Display the certificate's name and expiry date:

        openssl x509 -in ~/caddy-root.crt -noout -subject -enddate

    The subject is `CN=Caddy Local Authority - <year> ECC Root`, and the end date is about ten
    years away.

4. Record the file's SHA-256 hash:

        sha256sum ~/caddy-root.crt

5. On the workstation, copy the file:

        scp truenas_admin@192.0.2.10:caddy-root.crt .

6. Copy `caddy-root.crt` from the workstation to the Mac and the Windows VM by any means.

#### Results

Each client has a copy of `caddy-root.crt`. Before you trust it on a client, compare its hash with
the value from step 4; the commands are in the tasks that follow.

### Trust the root certificate on Ubuntu

#### Steps

1. Check the hash:

        sha256sum caddy-root.crt

2. Install the certificate into the system store:

        sudo cp caddy-root.crt /usr/local/share/ca-certificates/caddy-local-root.crt
        sudo update-ca-certificates

    The command reports one certificate added.

3. Verify the connection without any certificate option:

        curl -sS -o /dev/null -w '%{http_code}\n' https://chat.lab.home.arpa/

    The command prints an HTTP status code, for example `200`, and no certificate error.

### Trust the root certificate on macOS

#### Steps

1. Check the hash:

        shasum -a 256 caddy-root.crt

2. Add the certificate to the System keychain as a trusted root:

        sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain caddy-root.crt

    macOS asks for your password, and can ask a second time to authorize the trust setting.

3. Verify that the certificate is in the keychain:

        security find-certificate -c "Caddy Local Authority" /Library/Keychains/System.keychain

    The output shows the attributes of the certificate.

4. Open `https://chat.lab.home.arpa` in Safari.

    The page opens without a certificate warning.

### Trust the root certificate on Windows

#### Steps

1. Open Command Prompt as administrator and change to the folder that holds `caddy-root.crt`.

2. Check the hash:

        certutil -hashfile caddy-root.crt SHA256

3. Add the certificate to the trusted root store of the computer:

        certutil -addstore -f "ROOT" caddy-root.crt

4. Verify in PowerShell:

        Get-ChildItem Cert:\LocalMachine\Root | Where-Object Subject -like '*Caddy Local Authority*'

    The output lists one certificate.

5. Open `https://chat.lab.home.arpa` in Microsoft Edge.

    The page opens without a certificate warning.

### Trust the root certificate in browsers and tools with their own store

Some programs ignore the operating system's trust store.

- **Firefox** uses its own store. Import `caddy-root.crt` under **Privacy & Security** >
  **Certificates** > **View Certificates** > **Authorities** > **Import**.
- **Node.js tools**, such as Claude Code, read extra trusted certificates from a PEM file named in
  `NODE_EXTRA_CA_CERTS`. Set it in the tool's environment, for example
  `NODE_EXTRA_CA_CERTS=$HOME/caddy-root.crt`. The file `root.crt` is already in PEM format.
- **Python tools that use `requests`** read their trusted certificates from the bundle named in
  `REQUESTS_CA_BUNDLE`. The variable replaces the default bundle, so on Ubuntu point it to the
  system bundle, which now includes the root:
  `REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt`.

Test each tool against `https://llm.lab.home.arpa` before you rely on it.

## Return to DNS-01 certificates

To switch from the internal CA to publicly trusted certificates later, set the DNS-01 values in
`edge.env` (Chapter 6), edit the `ai-edge` app and replace its YAML with the standard one from
Chapter 6, which includes only the release's compose file, and save. Caddy then obtains
certificates through DNS-01. Remove the root certificate from the clients when no service uses it
any longer.
