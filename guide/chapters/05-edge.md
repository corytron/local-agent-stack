title: Deploying the edge app

# Deploying the edge app

This chapter installs the `ai-edge` app, the only app of the stack that publishes ports on the
TrueNAS server. Its `caddy` container terminates HTTPS for every host name of the stack with one
wildcard certificate, `*.lab.example.com`, obtained from Let's Encrypt through the ACME DNS-01
challenge, and forwards each name to its container on the `ai-net` network. Its `gpu-exporter`
container serves Prometheus metrics for the GPU on `ai-net` only.

The edge app comes before the RAG and web apps because Open WebUI has no published port: browsers
reach it only through Caddy. You add the host names to your local DNS, check them on the clients
and in the public zone, create a DNS API token, complete `edge.env`, check the Caddy image, install
the app, obtain a test certificate and then a production certificate, and verify every host name.
The worked example uses a UniFi Dream Machine Pro SE (UDM-Pro SE) as the local DNS server and
Cloudflare as the DNS provider; other local DNS servers need the same records, and the other
supported providers differ only in the credentials they need.

Table: Values used in this chapter

| Value | Meaning |
|---|---|
| `192.0.2.10` | LAN address of the TrueNAS server |
| `192.0.2.20` | LAN address of the workstation `c4dev` |
| `192.0.2.1` | LAN address of the UniFi gateway (UDM-Pro SE), the DNS server of the LAN; on another network (VLAN), use the gateway's address on that network |
| `<ui-https-port>` | The HTTPS port of the TrueNAS web interface, `444` in this guide's examples ([Run the port inventory](#run-the-port-inventory)) |
| `lab.example.com` | Your lab domain (`LAB_DOMAIN`); every host name of the stack is directly under it |
| `example.com` | The DNS zone at your DNS provider that holds the lab domain; it can also be the lab domain itself |
| `<cloudflare-token>` | The Cloudflare API token that you create in this chapter |

Run TrueNAS commands in **System** > **Shell** or in an SSH session as `truenas_admin`, as in
Chapter 3. Run workstation commands on `c4dev`.

## Overview of the edge app

The edge app consists of two containers and three configuration files from the repository: the
compose file, the `Caddyfile` and the environment file `edge.env`. Every value that differs between
installations comes from `edge.env`, so you do not edit the repository's files.

### Components and ports of the edge app

Table: Containers of the ai-edge app

| Container | Image | Ports | GPU |
|---|---|---|---|
| `caddy` | `ghcr.io/corytron/local-agent-stack-caddy:2.11.9`, built and published by this project, pinned by digest | 80/tcp, 443/tcp and 443/udp (HTTP/3), published on the server | None |
| `gpu-exporter` | `utkuozdemir/nvidia_gpu_exporter:1.18.0-nvml`, pinned by digest | 9835, on `ai-net` only | Read-only access through the `utility` capability |

The first part of the compose file defines `caddy`. The `gpu-exporter` part is shown in
[The GPU exporter](#the-gpu-exporter).

{{ include stack/edge/compose.yaml lines=1-66 }}

Points to note in this file:

- `caddy` runs as UID and GID 568, the TrueNAS `apps` account, with every Linux capability
  dropped, `no-new-privileges` and a read-only root filesystem. It binds ports 80 and 443 through
  the setting `net.ipv4.ip_unprivileged_port_start: "0"`. Only `/data`, `/config` and a temporary
  `/tmp` are writable.
- `/data` holds the ACME account key and the certificates, on the dataset
  `tank/ai/appdata/caddy` (`/mnt/tank/ai/appdata/caddy/data`). `/config` is
  `/mnt/tank/ai/appdata/caddy/config`. Both directories must be writable by UID 568.
- The `Caddyfile` is mounted read-only from the git clone on the server, so a release update
  changes it.
- The health check reads Caddy's admin API, which listens on `127.0.0.1:2019` inside the container
  only. The container is limited to 256 MB of memory.
- `LAB_DOMAIN`, `ACME_EMAIL` and `DNS_PROVIDER_TOKEN` have no default: if one of them is missing
  from `edge.env`, compose stops with the message shown in the file, for example
  `set LAB_DOMAIN in edge.env, e.g. lab.example.com`.

### Host names and routing

Caddy serves one site, `*.lab.example.com`, and picks the upstream container by the host name of
the request. The upstreams are container names on `ai-net`; each one exists only after its app is
installed.

Table: Host names served by the edge app

| Host name | Upstream on ai-net | Installed in |
|---|---|---|
| `chat.lab.example.com` | `open-webui:8080` | Chapter 6 (`ai-web`) |
| `llm.lab.example.com` | `litellm:4000` (OpenAI `/v1/...` and Anthropic `/v1/messages`) | Chapter 4 (`ai-inference`) |
| `models.lab.example.com` | `llama-swap:8080` (model list and logs; API key required) | Chapter 4 (`ai-inference`) |
| `mcp.lab.example.com` | `mcp-hub:8096`, with the `Host` header rewritten to `mcp-hub:8096` | Chapter 6 (`ai-web`) |
| `search.lab.example.com` | `searxng:8080` | Chapter 6 (`ai-web`) |

The site block of the `Caddyfile`:

{{ include stack/edge/Caddyfile lines=80-135 }}

The site block works as follows:

- **One certificate.** The `tls` block obtains one wildcard certificate for every name. A
  wildcard covers exactly one label: `chat.lab.example.com` is covered, while `lab.example.com`
  itself and `a.chat.lab.example.com` are not.
- **LAN only.** A client whose address is outside `EDGE_ALLOWED_CIDRS` has its connection closed
  (`abort`) before any routing. The default, `private_ranges`, is `10.0.0.0/8`, `172.16.0.0/12`,
  `192.168.0.0/16`, `127.0.0.1/8`, `fd00::/8` and `::1`.
- **Known names only.** Any other name under the wildcard, for example `test.lab.example.com`,
  has its connection closed.
- **Streaming.** For `llm.lab.example.com`, streamed responses (`text/event-stream`) are passed on
  as they arrive, and the proxy sets no response timeout, so long generations are not cut off.
- **MCP hub.** The hub, `mcp-proxy`, accepts only the `Host` values in its `--allowed-host` list,
  which names its `ai-net` address `mcp-hub:8096`. Caddy therefore sends `mcp-hub:8096` instead of
  `mcp.lab.example.com`.
- **Port 80.** Caddy answers plain HTTP only with a redirect to HTTPS.

### Settings that other apps must match

The edge app and the apps behind it share a few names. The files of the release already agree;
the table lists what must stay that way.

Table: Settings shared with other apps

| App | Setting | Value |
|---|---|---|
| `ai-web` (`mcp-hub`) | `--allowed-host` in `stack/web/compose.yaml` | Must include `mcp-hub:8096`, the `Host` header that Caddy sends |
| `ai-web` (`open-webui`) | `WEBUI_URL`, built from `LAB_DOMAIN` in `web.env` | `https://chat.lab.example.com`; `LAB_DOMAIN` in `web.env` must equal `LAB_DOMAIN` in `edge.env` |
| `ai-web` (`searxng`) | `SEARXNG_BASE_URL`, built from `LAB_DOMAIN` in `web.env` | `https://search.lab.example.com/` |
| All apps | Container names | `open-webui`, `litellm`, `llama-swap`, `mcp-hub`, `searxng`, as in the host name table |

!!! note
    Open WebUI reads its URL only on its first start. Chapter 6 sets `LAB_DOMAIN` in `web.env`
    before that start; use the same value as in `edge.env`.

!!! note
    Not tested: command-line MCP clients are expected to send no `Origin` header, so the MCP hub
    should need no list of allowed origins. If a client that sends an `Origin` header is refused by
    the hub while requests without one succeed, the hub's origin check is the cause.

### Certificates through the DNS-01 challenge

With the DNS-01 challenge, Caddy proves control of the domain by creating a TXT record,
`_acme-challenge.lab.example.com`, in the public zone through the DNS provider's API. Let's
Encrypt reads the record and issues the certificate. Nothing on the server has to be reachable from
the internet, and the lab names need no public DNS records. Because the certificate is a wildcard,
the individual host names are not written to the public Certificate Transparency logs; only
`*.lab.example.com` appears there.

The global options of the `Caddyfile`:

{{ include stack/edge/Caddyfile lines=1-20 }}

The `Caddyfile` uses two kinds of placeholder. `{$NAME}` and `{$NAME:default}` are replaced when
Caddy reads the file, before it parses it, so they can stand for a whole name, an address or several
words; this is how `LAB_DOMAIN`, `ACME_CA` and the other settings reach the file. `{env.NAME}` is
replaced at run time by the DNS module itself, so the DNS credentials never appear in the
configuration that Caddy builds from the file (its admin API and its logs). `persist_config off`
stops Caddy from writing that configuration to `/config/caddy/autosave.json`.

Split-horizon DNS and the `resolvers` setting:

- Your local DNS answers for the lab names with the server's LAN address, while the public zone at
  the DNS provider holds no record for them. This is split-horizon DNS.
- During the challenge, Caddy first finds the zone that holds `_acme-challenge.lab.example.com`,
  then waits until the TXT record it created is visible. If your local resolver serves its own zone
  for `lab.example.com` (an Unbound `local-zone`, a dnsmasq `address=/lab.example.com/...` line, a
  Pi-hole or router "local domain"), these lookups get the local answer, and issuance fails with
  `expected 1 zone, got 0` or `timed out waiting for record to fully propagate`.
- The `Caddyfile` therefore sends these lookups to public resolvers: `ACME_RESOLVERS`, by default
  `1.1.1.1 1.0.0.1` (Cloudflare's public resolvers). The setting affects only certificate issuance
  and renewal, which need the internet anyway; browsers and tools still resolve the lab names
  through your local DNS. The five exact-name records of a UniFi gateway do not cover
  `_acme-challenge.lab.example.com`, so these lookups would reach the public zone even through the
  gateway; the public resolvers keep issuance independent of the local DNS in every case.
- A gateway that intercepts DNS traffic defeats the setting: a UniFi Content Filter or Ad Blocking
  policy whose source includes the TrueNAS server makes the gateway answer the queries that Caddy
  sends to `1.1.1.1`. Keep the server out of such policies
  ([Keep the server out of DNS redirection](#keep-the-server-out-of-dns-redirection)).

Caddy renews the certificate automatically before it expires. Renewal uses the same DNS-01
challenge, so the server needs internet access and a valid DNS token for as long as the stack runs.
Caddy keeps the ACME account and the certificates in `/mnt/tank/ai/appdata/caddy/data`; if that
directory is lost, Caddy obtains a new certificate on its next start.

!!! note
    If you prefer certificates that need no domain, no DNS provider and no internet access, use
    Caddy's internal certificate authority instead: see
    [Configure the edge app for the internal CA](#configure-the-edge-app-for-the-internal-ca) in
    Appendix D. The internal CA requires a root certificate on every client.

## Create the local DNS records

The host names of the stack use split-horizon DNS. On the LAN, your local DNS server answers each
name with the address of the TrueNAS server. The public zone at your DNS provider holds no record
for the names: Caddy writes only the temporary TXT record of the DNS-01 challenge,
`_acme-challenge.lab.example.com`, and removes it again. Outside the LAN, the names do not
resolve.

Table: Local DNS records

| Name | Type | Address |
|---|---|---|
| `chat.lab.example.com` | A | `192.0.2.10` |
| `llm.lab.example.com` | A | `192.0.2.10` |
| `models.lab.example.com` | A | `192.0.2.10` |
| `mcp.lab.example.com` | A | `192.0.2.10` |
| `search.lab.example.com` | A | `192.0.2.10` |

The names get A records only. Do not add AAAA (IPv6) records: Caddy's default
`EDGE_ALLOWED_CIDRS` admits the private IPv6 range `fd00::/8` but no global IPv6 address, so a
client that reached the server over a global IPv6 address would have its connection closed. A
client that gets no IPv6 address for a name connects over IPv4, after a wait of at most 50 ms.

The worked example of this topic is a UniFi Dream Machine Pro SE (UDM-Pro SE), the gateway and DNS
server of the LAN, managed in the UniFi Network application. On the UDM, each record is a DNS
policy of type **Host (A)**. UniFi does not accept a wildcard name such as `*.lab.example.com`, so
each host name gets its own record. A record applies to every network (VLAN) of the site, and it
answers only the clients that use the gateway as their DNS server. For another router or DNS
server, see [Other DNS servers and the hosts file](#other-dns-servers-and-the-hosts-file).

!!! note
    The UniFi labels in this topic were checked against Ubiquiti's documentation for UniFi
    Network 9.4. On 15 November 2026 the current release firmware of the UDM-Pro SE was UniFi
    OS 6.0.17, with UniFi Network 11.0. That Network 10.6 and 11.0 use the same path to the DNS
    records is assumed, not verified: a third-party walk-through of Network 9.5.21 and Ubiquiti's
    release notes of Network 10.5 use it, and no source names another path. That UniFi rejects
    wildcard names is also assumed: Ubiquiti documents no wildcard records, and the UniFi API
    refuses a `*.` name as an invalid host name.

### Choose the host names

#### About this task

All host names are built from one value, `LAB_DOMAIN`. Choose it once; it appears in `edge.env`,
in `web.env` and in the configuration of every client, and changing it later means a new
certificate and new client settings.

#### Steps

1. Choose the lab domain. It must be a name in a DNS zone that you control at a supported DNS
   provider (Cloudflare in this guide), for example `lab.example.com` in the zone `example.com`.

    A subdomain such as `lab.example.com` keeps the lab names apart from any public names of the
    domain. The zone itself, for example `example.com`, also works.

2. Write down the five host names for your lab domain:

        chat.lab.example.com
        llm.lab.example.com
        models.lab.example.com
        mcp.lab.example.com
        search.lab.example.com

#### Results

You have the lab domain for `LAB_DOMAIN` and the five host names. `search.lab.example.com` is
optional for browsers, but adding it costs nothing.

### Check the UniFi Network version

#### About this task

Where the DNS records are created depends on the version of the UniFi Network application.

#### Steps

1. Log in to the UniFi Network application of the UDM-Pro SE.

2. Go to **Settings** > **Control Plane** > **Updates**.

    The page shows the installed versions of UniFi OS and of the Network application, and the
    release channel.

3. Note the version of the Network application.

#### Results

You know which path the next tasks use:

Table: Path to the DNS records by UniFi Network version

| UniFi Network | Path |
|---|---|
| 9.4 or later | **Settings** > **Policy Table** > **Create New Policy** > **DNS** (assumed for 10.6 and 11.0) |
| 9.3 | **Settings** > **Policy Engine** > **DNS** > **Create DNS Record** |
| Older than 9.3 | Not covered by this guide; update the Network application first |

### Give the TrueNAS server a fixed IP address

#### About this task

The five records point to one address, so the server must keep it. In UniFi, a fixed IP address
is set on the client device.

#### Steps

1. In the UniFi Network application, go to **Client Devices** and select the TrueNAS server.

2. Open **Settings**.

3. Turn on **Fixed IP Address** and enter the address that the server uses now, `192.0.2.10`.

4. Click **Apply Changes**.

5. On TrueNAS, in **System** > **Shell**, display the server's IPv4 addresses:

        ip -4 -brief address

    The line of the LAN interface shows `192.0.2.10` followed by its prefix length, for example
    `192.0.2.10/24`.

#### Results

The gateway gives the TrueNAS server the address `192.0.2.10` every time.

### Check the DNS server of each network

#### About this task

The records answer only the clients that use the gateway as their DNS server. Every UniFi network
hands out the gateway by default. This task checks that no network was changed.

#### Steps

1. Go to **Settings** > **Networks**.

2. Select each network that has clients of the stack (the network of the workstation, the Mac and
   the Windows VM, and any VLAN they use), and check **DNS Server**.

    It keeps its default, which hands out the gateway. If DNS servers are entered there, the
    clients of that network ask them instead and do not get the records: return the setting to
    its default and save the network.

3. If IPv6 is on for a network, check that its IPv6 settings hand out no other DNS server, such as
   one of your internet provider's. The label of this setting was not verified; the client checks in
   [Check name resolution from each client](#check-name-resolution-from-each-client) list the DNS
   servers that each client really uses.

4. On WiFi networks of UniFi Network 10.3 or later, leave **DNS Assistance** at its default, and
   enter no public failover DNS servers there.

    Ubiquiti does not document how this setting answers. A public failover server does not know
    the lab names.

#### Results

Every network that has clients of the stack hands out the gateway as its DNS server.

!!! note
    A record answers on every network, but resolving a name does not mean reaching the server. A
    client on another network (VLAN) than the server also needs the gateway's firewall to let it
    reach `192.0.2.10` on port 443, TCP and UDP (in UniFi Network, the Zone-Based Firewall
    decides traffic between networks), and its addresses must be inside Caddy's
    `EDGE_ALLOWED_CIDRS`, which by default admits every private range
    ([LAN-only access guard](#lan-only-access-guard)).

### Add the host names to local DNS

#### Prerequisites

- UniFi Network 9.4 or later ([Check the UniFi Network version](#check-the-unifi-network-version)).
  On 9.3, start the record with the path of that task's table instead.
- The TrueNAS server has a fixed address
  ([Give the TrueNAS server a fixed IP address](#give-the-truenas-server-a-fixed-ip-address)).

#### About this task

Create one DNS policy of type **Host (A)** per host name, each pointing to the TrueNAS server.
Leave the TTL empty, so that UniFi uses its default.

#### Steps

1. In the UniFi Network application, go to **Settings** > **Policy Table**.

2. Click **Create New Policy** and select **DNS**.

3. Enter the following values:

    - **Type**: **Host (A)**
    - **Domain Name**: `chat.lab.example.com`
    - **IP Address**: `192.0.2.10`
    - **TTL**: empty

4. Click **Add**.

5. Repeat steps 2 to 4 for `llm.lab.example.com`, `models.lab.example.com`,
   `mcp.lab.example.com` and `search.lab.example.com`.

    Do not enter `*.lab.example.com`, and do not create **Host (AAAA)** records.

6. On the workstation, ask the gateway for the five names:

        for n in chat llm models mcp search; do dig +short @192.0.2.1 $n.lab.example.com A; done

    The output is `192.0.2.10` five times. If `dig` is not installed, install the
    `bind9-dnsutils` package.

#### Results

The gateway answers for the five names with `192.0.2.10`. No record is needed at the public DNS
provider.

!!! note
    A variant needs only one change when the server's address changes: one **Host (A)** record
    `edge.lab.example.com` pointing to `192.0.2.10`, and five records of type **Alias (CNAME)**,
    each with a host name as **Alias Domain Name** and `edge.lab.example.com` as
    **Target Domain Name**. Alias records need UniFi OS 4.3 and UniFi Network 9.3 or later. The two
    field labels come from a third-party guide and were not verified.

!!! note
    Keep the **Domain Name** of your networks, a DHCP setting, different from the lab domain. If
    the gateway registers the names of DHCP clients under that domain, a device named `chat` or
    `search` would collide with a host name of the stack.

### Keep the server out of DNS redirection

#### About this task

UniFi Content Filtering works by redirecting the DNS traffic of the clients in a policy's
**Source** to the gateway, and a policy with **Ad Blocking** on also redirects the clients that use
other DNS servers. For the workstation and the other clients this is harmless: the gateway holds
the records. For the TrueNAS server it is not. Caddy's queries to the public resolvers of
`ACME_RESOLVERS` leave the server with its address, so the gateway would answer them. Before the
challenge record exists, the answers are negative, and the gateway keeps negative answers for the
zone's negative-caching time (1800 seconds by default for a Cloudflare zone), far longer than the
two minutes that Caddy waits for the record. Issuance and every renewal would then fail with
`timed out waiting for record to fully propagate`.

!!! warning
    A Content Filter or Ad Blocking policy that covers the TrueNAS server stops certificate
    renewal without any visible sign until the certificate expires. Check every policy.

#### Steps

1. In the UniFi Network application, go to **Settings** > **CyberSecure** > **Content Filter**.

2. For every policy, including those with **Ad Blocking** on, check its **Source**.

3. If a policy's **Source** includes the TrueNAS server, either as a device or through its
   network, change the **Source** to devices that do not include the server, or to networks that
   do not contain it, and save the policy.

#### Results

No Content Filter or Ad Blocking policy covers the TrueNAS server. Once the edge app runs,
[Verify the edge containers](#verify-the-edge-containers) tests this from the `caddy` container.

!!! note
    The redirect and its effect on Caddy follow from Ubiquiti's documentation of Content Filtering
    and Ad Blocking and from Caddy's source code; they have not been observed on a UDM. That the
    records keep answering clients inside such a policy is assumed for the same reason. **Encrypted
    DNS** (**Settings** > **CyberSecure**) encrypts only the gateway's own queries to its upstream
    servers, and a third-party guide reports that local records keep working with it. If the lab
    names resolve only some of the time, test with Encrypted DNS off.

### Other DNS servers and the hosts file

With another router or DNS server (Pi-hole, AdGuard Home, dnsmasq, Unbound and others), the same
rules apply:

- Add the five A records of the table in
  [Create the local DNS records](#create-the-local-dns-records), each pointing to `192.0.2.10`.
  Look for a setting named "local DNS records", "static DNS", "DNS host entries" or similar. Give
  the TrueNAS server a fixed address, for example with a DHCP reservation.
- Some products answer for a whole domain with one entry instead, for example a dnsmasq line
  `address=/lab.example.com/192.0.2.10`, an Unbound `local-zone` or a router "local domain". That
  works for the clients. It also hides the public zone from the local resolver, which is the
  reason the edge app uses public resolvers for the DNS challenge (`ACME_RESOLVERS`).
- If the DNS server or a firewall redirects DNS queries to public resolvers, keep the TrueNAS
  server out of the redirect, as on UniFi.
- In the checks of [Check name resolution from each client](#check-name-resolution-from-each-client),
  use the address of your DNS server instead of `192.0.2.1`.

A client that does not use the local DNS server, for example a VPN client with DNS servers of its
own, can use its hosts file instead: `/etc/hosts` on Ubuntu and macOS,
`C:\Windows\System32\drivers\etc\hosts` on Windows (edit it as administrator). Add this line:

```
192.0.2.10 chat.lab.example.com llm.lab.example.com models.lab.example.com mcp.lab.example.com search.lab.example.com
```

## Check the lab names in DNS

These checks confirm the records from every client, confirm that the public zone does not answer
for the lab names, and set the browsers so that they ask the local DNS server.

### Check name resolution from each client

#### About this task

Each step first asks the gateway directly, which shows that the records exist, then the client's
system resolver, which shows that the client uses the gateway. `dig` and `Resolve-DnsName` with
`-DnsOnly -NoHostsFile` ignore the hosts file; `getent` and `dscacheutil` read it first.

#### Steps

1. On Ubuntu (`c4dev`), run the following commands:

        dig +short @192.0.2.1 chat.lab.example.com A
        dig @192.0.2.1 chat.lab.example.com AAAA +noall +comments | grep -E 'status:|ANSWER:'
        getent hosts chat.lab.example.com
        resolvectl status

    The first and third commands print `192.0.2.10`. The second shows `status: NOERROR` and
    `ANSWER: 0`: the name exists but has no IPv6 address. `resolvectl status` lists only the
    gateway as DNS server of the LAN interface.

2. On macOS, run the following commands in **Terminal**:

        dig +short @192.0.2.1 chat.lab.example.com A
        dscacheutil -q host -a name chat.lab.example.com
        scutil --dns | grep nameserver

    The first prints `192.0.2.10`, the second `ip_address: 192.0.2.10`, and the third lists only
    addresses of the gateway.

3. On Windows, run the following commands in PowerShell:

        Resolve-DnsName chat.lab.example.com -Server 192.0.2.1 -Type A -DnsOnly
        Resolve-DnsName chat.lab.example.com -Type A -DnsOnly -NoHostsFile
        Get-DnsClientServerAddress

    The first two show `IPAddress` `192.0.2.10`. For the active network adapter, the third lists
    only addresses of the gateway: in the IPv4 row and, if the network has IPv6, in the IPv6 row.

4. Check all five names through the system resolver, with the command for the client's system:

        for n in chat llm models mcp search; do getent hosts $n.lab.example.com; done
        for n in chat llm models mcp search; do dscacheutil -q host -a name $n.lab.example.com; done
        'chat','llm','models','mcp','search' | ForEach-Object { Resolve-DnsName "$_.lab.example.com" -Type A -DnsOnly -NoHostsFile }

    The first line is for Ubuntu, the second for macOS and the third for Windows PowerShell. Each
    name shows `192.0.2.10`.

#### Results

Every client resolves every host name to `192.0.2.10` through the gateway. If the gateway answers
but the system resolver does not, the client uses another DNS server: check the list of DNS servers
from the step for its system, and flush its cache: `resolvectl flush-caches` on Ubuntu,
`sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder` on macOS, `ipconfig /flushdns` on
Windows. If the client must keep another DNS server, use the hosts file
([Other DNS servers and the hosts file](#other-dns-servers-and-the-hosts-file)). If the gateway
itself does not answer, check the records
([Add the host names to local DNS](#add-the-host-names-to-local-dns)).

!!! note
    The answer to the IPv6 (AAAA) query in step 1 is assumed, not yet checked on a UDM: UniFi's
    resolver is expected to answer `NOERROR` without data for a name that has only an A record. If
    the status is `NXDOMAIN` instead, the IPv4 address still works; record the result in a project
    issue.

### Check the public zone

#### About this task

The public zone must not answer for the lab names, so that a browser or a resolver outside the LAN
gets "name does not exist" (`NXDOMAIN`). A wildcard record of the public zone, for example
`*.example.com`, would answer for `chat.lab.example.com` as long as no record exists at
`lab.example.com` itself, and browsers that use public DNS would then reach the wildcard's target
instead of the server. The commands ask Cloudflare's public resolver over HTTPS, the way a browser
with secure DNS does; a UniFi gateway cannot redirect these queries.

#### Steps

1. On the workstation, look up a lab name in the public DNS:

        curl -s -H 'accept: application/dns-json' 'https://cloudflare-dns.com/dns-query?name=chat.lab.example.com&type=A'

    The output contains `"Status":3` (3 is `NXDOMAIN`) and no `"Answer"`.

2. Look up a name that no record should match:

        curl -s -H 'accept: application/dns-json' 'https://cloudflare-dns.com/dns-query?name=nonexistent-check.lab.example.com&type=A'

    The output contains `"Status":3`.

3. Check that no challenge record is left over:

        curl -s -H 'accept: application/dns-json' 'https://cloudflare-dns.com/dns-query?name=_acme-challenge.lab.example.com&type=TXT'

    The output contains `"Status":3`. While Caddy obtains or renews a certificate, a TXT record
    can appear here for a few minutes.

4. In the Cloudflare dashboard, open the zone `example.com` and its **DNS** > **Records** page.

    No record exists for `chat`, `llm`, `models`, `mcp` or `search` under the lab domain.

5. If step 1 or step 2 returned an address, a wildcard of the public zone answers for the lab
   names. Remove the wildcard, or, if the zone needs it, add one marker record at the lab domain:
   on the zone's **DNS** > **Records** page, click **Add record**, select **Type** `TXT`, enter the
   name `lab` and any text as its content, for example `no public records below this name`, and
   click **Save**. Then repeat steps 1 and 2.

    The marker carries no address. Once `lab.example.com` exists as a name, the wildcard no longer
    answers for names below it. If the lab domain is the zone itself (`example.com`), a marker does
    not help: remove the wildcard.

#### Results

Public DNS answers `NXDOMAIN` for every lab name, and only your local DNS knows them.

!!! note
    `dig chat.lab.example.com A @1.1.1.1` asks the same resolver over plain DNS. On a workstation
    inside a UniFi Content Filter or Ad Blocking policy, the gateway answers that query with
    `192.0.2.10` instead; that is harmless for the workstation, but it hides the public answer.
    Use the HTTPS lookups above.

### Browsers and DNS over HTTPS

Command-line clients (OpenCode, Claude Code, `curl`, Python) use the resolver of the operating
system, so they get the local records. Browsers can send their DNS queries over HTTPS (DoH) to a
public service instead; the public zone has no lab records, so such a query returns
`NXDOMAIN`. Whether a browser then falls back to the system resolver depends on its setting.

Table: Browsers and secure DNS

| Browser | Setting | Lab names |
|---|---|---|
| Chrome | **Use secure DNS** on with your current service provider (the default), or off | Work: the gateway offers no secure DNS, so Chrome sends its queries to it |
| Chrome | **Use secure DNS** with a provider chosen from the list, or a custom provider | Fail: Chrome uses only that provider and does not fall back |
| Microsoft Edge | **Use current service provider** (the default), or off | Work, as in Chrome |
| Microsoft Edge | A chosen provider | Fail, as in Chrome |
| Firefox | The default protection level, which uses Cloudflare's DoH service | Work: a lookup that fails, `NXDOMAIN` included, falls back to the system resolver |
| Firefox | A level without fallback (in recent versions, **Custom** with "Always warn me if secure DNS isn't available") | Fail, unless the lab domain is in **Manage exceptions** |
| Safari with iCloud Private Relay | On | Work: Private Relay sends a name that is not public directly to the local network |
| Android | **Private DNS** set to automatic | Work; a named Private DNS provider has no fallback and fails |

Firefox's setting labels differ between releases; the task names the setting area and
**Manage exceptions**, which exist in every current release. Windows 11 uses DoH only for DNS
servers in its own list, and the gateway is not one of them.

### Check the secure DNS setting of each browser

#### About this task

Check the setting in each browser on each client that opens `chat.lab.example.com`. Browsers that
an organization manages take the setting from a policy instead: in Chrome and Edge, the policy
`DnsOverHttpsMode` set to `automatic` or `off`; in Firefox, the policy `DNSOverHTTPS` with the lab
domain in `ExcludedDomains`.

#### Steps

1. In Chrome, open **Settings** > **Privacy and security** > **Security**, and find
   **Use secure DNS** under **Advanced**.

    Leave it off, or on with your current service provider. If a provider is selected from the
    drop-down list, select your current service provider instead.

2. In Microsoft Edge, open **Settings** and search for `secure DNS`.

    **Use secure DNS to specify how to lookup the network address for websites** is off, or set
    to **Use current service provider**. If a provider is chosen, select
    **Use current service provider**.

3. In Firefox, open **Settings** > **Privacy & Security** and scroll to the DNS over HTTPS
   settings.

    Keep the default. If a setting without fallback is in use, click **Manage exceptions**, add
    `lab.example.com`, and save. An exception covers the domain and every name below it.

4. In Safari, change nothing. iCloud Private Relay sends the lab names to the local network.

#### Results

Every browser sends the lab names to the gateway, or falls back to it.
[Open a host name in each browser](#open-a-host-name-in-each-browser) confirms this once the
edge app serves the production certificate.

!!! note
    The Edge labels come from a third-party guide and were not verified. Chrome's and Firefox's
    behaviour was checked in their source code and documentation.

### Turn off Firefox's automatic DNS over HTTPS

#### About this task

This task is optional. Firefox's automatic rollout turns on DNS over HTTPS by itself unless the
network tells it not to: Firefox looks up `use-application-dns.net` through the system resolver and
stays with the system resolver when that name returns no public address. One record on the gateway
makes the name return no address for the whole network. The lab names work without it, because
Firefox's default falls back to the system resolver; the record saves that extra round trip and
keeps Firefox's lookups on the gateway. It does not change a setting that a user chose.

#### Steps

1. In the UniFi Network application, go to **Settings** > **Policy Table**, click
   **Create New Policy** and select **DNS**.

2. Enter the following values:

    - **Type**: **Alias (CNAME)**
    - **Alias Domain Name**: `use-application-dns.net`
    - **Target Domain Name**: `NXDOMAIN`

3. Click **Add**.

4. On the workstation, check the answer of the gateway:

        dig +short @192.0.2.1 use-application-dns.net A

    The output contains no IPv4 address: it is empty or shows only the alias target `NXDOMAIN.`.

#### Results

Firefox's automatic DNS over HTTPS stays off on the networks that use the gateway. To undo it,
delete the policy.

!!! note
    The labels of the alias record and the use of `NXDOMAIN` as its target come from a third-party
    guide for UniFi Network 9.5.21, which uses the same record to turn off iCloud Private Relay;
    they are assumed for later versions. Do not create such a record for `mask.icloud.com` or
    `mask-h2.icloud.com` unless you want to turn off iCloud Private Relay on the network.

## Create the Cloudflare API token

Caddy needs an API token that can create and delete the TXT record of the challenge in the zone
that holds your lab domain. Use a scoped **API token**, never the Global API Key, and limit it to
the one zone.

!!! warning
    The token can change every DNS record of the zone: with it, anyone can redirect your domain or
    obtain certificates for it. Keep it only in `edge.env` (on the workstation in
    `~/.config/local-agent-stack/secrets/`, on the server in `/mnt/tank/ai/secrets/`). Never paste
    it into a chat, an issue, a commit or a shell command line. If it is exposed, delete it in
    **My Profile** > **API Tokens** and create a new one.

### Check that the zone is on Cloudflare

#### Steps

1. On the workstation, look up the name servers of the zone through a public resolver:

        dig +short NS example.com @1.1.1.1

    Both names in the output end in `.ns.cloudflare.com.`.

#### Results

Cloudflare is authoritative for the zone, so a Cloudflare token can complete the challenge. If
other name servers are listed, the zone is at another provider: see
[Other DNS providers](#other-dns-providers).

### Create a zone-scoped API token

#### About this task

The Cloudflare module of Caddy documents a single API token with two permissions: **Zone** >
**Zone** > **Read**, to find the zone by name, and **Zone** > **DNS** > **Edit**, to write the TXT
record. Cloudflare shows the token value only once, at creation.

Table: Cloudflare API token settings

| Setting | Value |
|---|---|
| **Token name** | A name that says what uses it, for example `caddy-dns01-lab` |
| **Permissions** | **Zone** > **Zone** > **Read**, and **Zone** > **DNS** > **Edit** |
| **Zone Resources** | **Include** > **Specific zone** > `example.com` (the zone that holds `LAB_DOMAIN`) |
| **Client IP Address Filtering** | Empty, unless your internet address is static |
| **Token expiration** (TTL) | None, or a date you record; Caddy cannot renew certificates with an expired token |

#### Steps

1. Log in to the Cloudflare dashboard at `https://dash.cloudflare.com`.

2. Open **My Profile** > **API Tokens** (`https://dash.cloudflare.com/profile/api-tokens`).

3. Click **Create Token**.

4. Start from scratch with a custom token instead of a template.

5. Enter the values from the table above: the name, the two permissions, and the zone.

6. Click **Continue to summary**.

    The summary lists the zone `example.com` with the permissions Zone Read and DNS Edit, and
    nothing else. If it lists more, click **Back** and correct the form.

7. Click **Create Token**.

    Cloudflare shows the token and states that it is shown only once.

8. Copy the token. Keep the page open until you have checked the token in the next task and
   stored it in `edge.env`.

#### Results

The token exists, limited to one zone with two permissions.

!!! note
    Cloudflare has changed the layout of the token form over time; its documentation of November
    2026 describes the scope as a policy with resource rules. Whatever the layout, the token must
    have exactly the two permissions above on the one zone. The documentation of the underlying
    `libdns/cloudflare` library describes the single token with "All zones"; the zone-limited token
    is narrower and sufficient, because Caddy finds the zone with a lookup by name
    (`GET /zones?name=example.com`), which a token limited to that zone can answer.

### Verify the API token

#### About this task

These commands read the token from a prompt, so it is not echoed and does not enter the shell
history, and pass it to `curl` on standard input, so it does not appear in the process list. Run
them on the workstation.

#### Steps

1. Read the token into a shell variable. Paste the token at the prompt and press Enter:

        printf 'Cloudflare token: '; read -rs CF_TOKEN; echo

2. Check that the token is valid:

        printf 'Authorization: Bearer %s\n' "$CF_TOKEN" | curl -sS -H @- https://api.cloudflare.com/client/v4/user/tokens/verify

    The output contains `"success":true`, `"status":"active"` and the message
    `This API Token is valid and active`.

3. Check that the token can find the zone:

        printf 'Authorization: Bearer %s\n' "$CF_TOKEN" | curl -sS -H @- 'https://api.cloudflare.com/client/v4/zones?name=example.com'

    The output contains `"success":true` and `"name":"example.com"`. If the result list is empty
    (`"result":[]`), the token does not include the zone or lacks **Zone** > **Zone** > **Read**.

4. Remove the variable:

        unset CF_TOKEN

#### Results

The token is valid and can read the zone. Store it in `edge.env` in
[Set the edge values for the first certificate](#set-the-edge-values-for-the-first-certificate).

## Other DNS providers

The Caddy image contains DNS modules for eight providers. `DNS_PROVIDER` in `edge.env` selects one;
no file needs to be edited. The `Caddyfile` defines one snippet per provider, and its `tls` block
imports `dns-{$DNS_PROVIDER}`, so a name that is not in the list stops Caddy at start-up with
`File to import not found: dns-<name>`.

### Credentials by DNS provider

Table: Credentials by DNS provider

| `DNS_PROVIDER` | `DNS_PROVIDER_TOKEN` | `DNS_PROVIDER_KEY_ID` | Other variables |
|---|---|---|---|
| `cloudflare` (default) | API token | Empty | None |
| `digitalocean` | Personal access token | Empty | None |
| `duckdns` | Account token | Empty | None |
| `desec` | Token | Empty | None |
| `route53` | Secret access key | Access key ID | None |
| `porkbun` | Secret API key | API key | None |
| `namecheap` | API key | API user name | None |
| `ovh` | Application secret | Application key | `DNS_PROVIDER_CONSUMER_KEY` (consumer key); `DNS_PROVIDER_ENDPOINT` (`ovh-eu` by default; also `ovh-ca`, `ovh-us` and others) |

The provider snippets of the `Caddyfile`, which show how each variable is used:

{{ include stack/edge/Caddyfile lines=22-65 }}

To use another provider:

- Create the credential in the provider's console with permission to create and delete TXT
  records in the zone that holds `LAB_DOMAIN`, limited to that zone where the provider allows it.
  The module of each provider is documented at `https://github.com/caddy-dns/<provider>`.
- Set `DNS_PROVIDER` and the variables of the table in `edge.env`. Leave the variables that the
  provider does not use empty; `DNS_PROVIDER_ENDPOINT` is ignored by every provider except `ovh`.
- Skip the Cloudflare checks of this chapter. The default `ACME_RESOLVERS`, `1.1.1.1 1.0.0.1`,
  works for any provider, because the public zone is visible through any public resolver; set
  other public resolvers if you prefer.

## Complete edge.env

Chapter 3 created `edge.env` from `stack/edge/edge.env.example` with placeholders for every value.
You now replace them. The file of record is the copy on the workstation,
`~/.config/local-agent-stack/secrets/edge.env`; the server's copy is installed from it.

### Edge environment variables

Table: Variables of edge.env

| Variable | Required | Default | Value |
|---|---|---|---|
| `LAB_DOMAIN` | Yes | None | Your lab domain, for example `lab.example.com`; the same value as in `web.env` |
| `ACME_EMAIL` | Yes | None | Contact address of the ACME account at Let's Encrypt |
| `DNS_PROVIDER` | No | `cloudflare` | One of the eight providers |
| `DNS_PROVIDER_TOKEN` | Yes | None | The Cloudflare API token; for other providers, see the credentials table |
| `DNS_PROVIDER_KEY_ID` | Some providers | Empty | Empty for Cloudflare |
| `DNS_PROVIDER_CONSUMER_KEY` | `ovh` only | Empty | Empty for Cloudflare |
| `DNS_PROVIDER_ENDPOINT` | `ovh` only | `ovh-eu` | Ignored by the other providers |
| `ACME_RESOLVERS` | No | `1.1.1.1 1.0.0.1` | Public resolvers for the challenge, separated by spaces |
| `ACME_CA` | No | Let's Encrypt production | The staging address for the first test, then production |
| `EDGE_ALLOWED_CIDRS` | No | `private_ranges` | Client address ranges allowed to connect, separated by spaces |
| `EDGE_BIND_IP` | No | `0.0.0.0` (all addresses) | One server address for ports 80 and 443, for example `192.0.2.10` |
| `AI_ROOT` | No | `/mnt/tank/ai` | Root of the stack's datasets; change it only if every app uses the same other path |

Notes on the optional variables:

- `ACME_CA`: `https://acme-staging-v02.api.letsencrypt.org/directory` is Let's Encrypt's staging
  service. Its certificates are not trusted by browsers or tools, and its rate limits are much
  higher than production's. Use it until issuance works, so that failed attempts do not count
  against the production limits. Production is
  `https://acme-v02.api.letsencrypt.org/directory`.
- `ACME_RESOLVERS`: keep the default unless your network blocks DNS queries to the internet; then
  set resolvers that answer with the public zone.
- `EDGE_ALLOWED_CIDRS`: `private_ranges` stands for `10.0.0.0/8 172.16.0.0/12 192.168.0.0/16
  127.0.0.1/8 fd00::/8 ::1`. If your LAN uses other addresses, list them explicitly, for example
  `192.0.2.0/24`. The placeholder network of this guide, `192.0.2.0/24`, is not a private range, so
  a LAN that really used it would need this setting.
- `EDGE_BIND_IP`: set it when the server has several addresses and Caddy should listen on only one
  of them.

The example file, with a comment for every variable:

{{ include stack/edge/edge.env.example }}

### Set the edge values for the first certificate

#### Prerequisites

- `~/.config/local-agent-stack/secrets/edge.env` exists on the workstation
  ([Generate the environment files on the workstation](#generate-the-environment-files-on-the-workstation)).
- The Cloudflare API token from [Create a zone-scoped API token](#create-a-zone-scoped-api-token).

#### About this task

The first installation uses the Let's Encrypt staging service. After a staging certificate has been
issued, [Switch to the production CA](#switch-to-the-production-ca) changes one line.

#### Steps

1. On the workstation, open the file in a text editor:

        nano ~/.config/local-agent-stack/secrets/edge.env

2. Set the following lines, with your own domain, address and token:

        LAB_DOMAIN=lab.example.com
        ACME_EMAIL=admin@example.com
        DNS_PROVIDER=cloudflare
        DNS_PROVIDER_TOKEN=<cloudflare-token>
        ACME_CA=https://acme-staging-v02.api.letsencrypt.org/directory

    Do not put quotes around the values. Caddy refuses to start if `DNS_PROVIDER_TOKEN` does not
    have the shape of a Cloudflare token, so a leftover placeholder fails at once.

3. Leave `DNS_PROVIDER_KEY_ID` and `DNS_PROVIDER_CONSUMER_KEY` empty, and keep
   `DNS_PROVIDER_ENDPOINT`, `ACME_RESOLVERS` and `AI_ROOT` at their example values.

4. If your LAN is not inside the private ranges, set `EDGE_ALLOWED_CIDRS` to its ranges. If Caddy
   should listen on one address only, set `EDGE_BIND_IP`, for example to `192.0.2.10`.

5. Save the file and close the editor.

6. Check the values, without printing the token:

        grep -E '^(LAB_DOMAIN|ACME_EMAIL|DNS_PROVIDER|ACME_CA|ACME_RESOLVERS|EDGE_ALLOWED_CIDRS|EDGE_BIND_IP)=' ~/.config/local-agent-stack/secrets/edge.env
        grep -c 'replace-with' ~/.config/local-agent-stack/secrets/edge.env

    The first command shows your values; `ACME_CA` is the staging address. The second prints `0`.

7. Copy the file to the server:

        scp ~/.config/local-agent-stack/secrets/edge.env truenas_admin@192.0.2.10:

8. On TrueNAS, install it into the secrets dataset and delete the copy:

        sudo install -m 0600 -o root -g root ~/edge.env /mnt/tank/ai/secrets/
        rm ~/edge.env

9. Verify the file on the server:

        sudo ls -l /mnt/tank/ai/secrets/edge.env
        sudo grep -c 'replace-with' /mnt/tank/ai/secrets/edge.env

    The file has `-rw-------` and owner `root root`; the second command prints `0`.

10. Check that compose accepts the file together with the release's compose file:

        sudo docker compose --env-file /mnt/tank/ai/secrets/edge.env -f /mnt/tank/ai/stacks/local-agent-stack/stack/edge/compose.yaml config -q

    The command prints nothing and returns to the prompt. A message such as
    `set ACME_EMAIL in edge.env` names a missing value.

#### Results

`edge.env` is complete on the workstation and on the server, set for the staging service. To
change a value later, edit the workstation copy, repeat steps 7 to 9, and redeploy the app with
`sudo midclt call -j app.redeploy ai-edge`.

## The Caddy image

The official Caddy image contains no DNS provider modules, so this project builds its own image
with the eight modules and publishes it on the GitHub Container Registry as
`ghcr.io/corytron/local-agent-stack-caddy`. A public package can be pulled without logging in, so
TrueNAS needs no registry credentials. The compose file of a release names the image by tag and
digest, so the server always runs the image that the release was tested with.

### How the image is built and published

The GitHub Actions workflow **Caddy image** (`.github/workflows/caddy-image.yml`) builds the image
from `stack/edge/Dockerfile`:

{{ include stack/edge/Dockerfile }}

Table: Publication of the Caddy image

| Item | Value |
|---|---|
| Trigger | A push to `main` that changes `stack/edge/Dockerfile` or the workflow, or a manual run; only `main` publishes |
| Platform | `linux/amd64` |
| Tags | `<caddy-version>`, for example `2.11.9`, and `<caddy-version>-<commit>`, where `<commit>` is the first 12 characters of the commit |
| Provenance | A signed build provenance attestation, pushed to the registry next to the image |
| Run summary | The line to pin in the compose file: `image: ghcr.io/corytron/local-agent-stack-caddy:2.11.9@sha256:<digest>` |

The Caddy version appears in both `FROM` lines of the Dockerfile, and the workflow refuses to build
when they differ. Each DNS module is pinned to its latest release on 15 November 2026
(`digitalocean` to a commit, because it has no tagged release), and Go verifies every module against its checksum
database during the build. The build removes the file capability that `xcaddy` sets on the binary:
with every capability dropped in the container, a binary that carries one cannot start.

The workflow runs in this repository on GitHub, on `main` only; no other project publishes the
image. A release copies the digest from the run summary into the `image:` line of
`stack/edge/compose.yaml`, so that the line reads
`ghcr.io/corytron/local-agent-stack-caddy:2.11.9@sha256:<digest>`. Docker then pulls that exact
image, even if a later run of the workflow publishes a different image under the same tag. The
workflow **MCP hub image** (`.github/workflows/mcp-hub-image.yml`) publishes the MCP hub image of
the `ai-web` app in the same way
([Build or pull the MCP hub image](#build-or-pull-the-mcp-hub-image)).

!!! note
    If the `image:` line of `caddy` in `stack/edge/compose.yaml` of your clone names the tag
    without `@sha256:`, the image of that release has not been pinned yet. A later run of the
    workflow can then publish a different image under the same tag, and a pull replaces the image
    on the server. Compare the digest of the image that you pull in the next task with the summary
    of the workflow run on the repository's **Actions** page, and report the missing pin as an
    issue.

### Check the Caddy image on TrueNAS

#### About this task

This task pulls the image that the release's compose file names, shows its digest, and validates
the release's `Caddyfile` in the image with your `edge.env`. Validation loads every module,
including the Cloudflare module's check of the token's shape, without starting the server. The
commands take the image name from the compose file in the clone, so they check exactly the image
that the app will run.

#### Steps

1. Store the image of the `caddy` service in a shell variable:

        IMG=$(sed -n 's/^ *image: *\(ghcr\.io\/[^ ]*local-agent-stack-caddy:.*\)$/\1/p' \
          /mnt/tank/ai/stacks/local-agent-stack/stack/edge/compose.yaml)
        echo "$IMG"

    The output is `ghcr.io/corytron/local-agent-stack-caddy:2.11.9@sha256:` followed by 64
    hexadecimal digits. If it ends in `:2.11.9` without `@sha256:`, the image is not pinned yet; see
    the note in [How the image is built and published](#how-the-image-is-built-and-published).

2. Pull the image:

        sudo docker pull "$IMG"

    The pull completes without asking for credentials. If it fails with an error such as `denied`,
    `unauthorized` or `manifest unknown`, the package is not public or not published: see
    [Make the Caddy image public](#make-the-caddy-image-public), or build the image on the server
    ([Build the Caddy image on TrueNAS](#build-the-caddy-image-on-truenas)).

3. Display the digest of the image:

        sudo docker image inspect --format '{{index .RepoDigests 0}}' "$IMG"

    The output is `ghcr.io/corytron/local-agent-stack-caddy@sha256:<digest>`, with the same digest
    as the output of step 1. The summary of the workflow run that built the image, on the
    repository's **Actions** page, names the same digest.

4. Validate the `Caddyfile` with your values:

        sudo docker run --rm --env-file /mnt/tank/ai/secrets/edge.env -v /mnt/tank/ai/stacks/local-agent-stack/stack/edge/Caddyfile:/etc/caddy/Caddyfile:ro "$IMG" caddy validate --config /etc/caddy/Caddyfile

    The last line of the output is `Valid configuration`.

5. Optional: on the workstation, with the GitHub CLI (`gh`) installed and logged in, verify the
   provenance of the image. Replace `<digest>` with the digest of step 3:

        gh attestation verify oci://ghcr.io/corytron/local-agent-stack-caddy@sha256:<digest> --repo corytron/local-agent-stack

    The command reports a successful verification. The attestation was signed by the workflow
    `.github/workflows/caddy-image.yml` of the repository.

#### Results

The image that the release names is on the server, its digest matches the release, and the
`Caddyfile` is valid with your values.

!!! note
    With a digest in the compose file, a pull always fetches the pinned image, and
    `sudo midclt call -j app.pull_images ai-edge`, which pulls the images of the app again and
    redeploys it, changes nothing. Without a digest, a later workflow run can publish a new image
    under the same tag, which that command or a new installation would pull; repeat this task
    before you run it.

### Make the Caddy image public

#### About this task

This task applies only to the maintainer of a GitHub repository that publishes the images: this
project's repository, or your fork if you publish your own images. GitHub creates a new container
package as private, and a package does not inherit the visibility of its repository. Do this once,
after the first run of the **Caddy image** workflow, and once for the MCP hub image after the first
run of its workflow.

A fork that publishes its own images must first rename them. The image names are written in six
places, each with the account `corytron`:

Table: Image names to change in a fork

| File | Line to change |
|---|---|
| `.github/workflows/caddy-image.yml` | `IMAGE: ghcr.io/corytron/local-agent-stack-caddy` |
| `.github/workflows/mcp-hub-image.yml` | `IMAGE: ghcr.io/corytron/local-agent-stack-mcp-hub` |
| `stack/edge/compose.yaml` | The `image:` line of `caddy` |
| `stack/web/compose.yaml` | The `image:` line of `mcp-hub` |
| `stack/edge/Dockerfile`, `stack/web/mcp-hub/Dockerfile` | The `org.opencontainers.image.source` label, the repository the image is built from |

Without the change, the fork's workflows cannot push to `corytron`'s packages, and its servers
keep pulling the images of this project. In the `gh attestation verify` commands of this guide, use
your own repository with `--repo` as well.

#### Steps

1. In a fork only: replace `corytron` with your GitHub account in the six places of the table, in
   a pull request, and merge it. The merge to `main` runs both workflows; otherwise start each one
   from the repository's **Actions** page with **Run workflow**.

2. On GitHub, open the repository page and click the package `local-agent-stack-caddy` under
   **Packages**.

3. Click **Package settings**.

4. Under **Danger Zone**, click **Change visibility**, select **Public**, and confirm.

5. Pin the digest from the summary of the workflow run in `stack/edge/compose.yaml`, through a
   pull request. The `image:` line then reads
   `ghcr.io/<account>/local-agent-stack-caddy:2.11.9@sha256:<digest>`.

6. Repeat steps 2 to 5 for the package `local-agent-stack-mcp-hub`, which the workflow **MCP hub
   image** (`.github/workflows/mcp-hub-image.yml`) publishes in the same way for the `ai-web` app
   (Chapter 6). Its digest is pinned in `stack/web/compose.yaml`.

7. Check that the images can be pulled without credentials, on TrueNAS, which is not logged in to
   the registry:

        sudo docker pull ghcr.io/<account>/local-agent-stack-caddy:2.11.9
        sudo docker pull ghcr.io/<account>/local-agent-stack-mcp-hub:0.15.0

    Both pulls complete without `denied` or `unauthorized`.

#### Results

The packages are public, and the compose files pin their digests; anyone can pull them without
logging in, and TrueNAS needs no registry credentials.

### Build the Caddy image on TrueNAS

#### About this task

This task is an alternative to the published image, for example while the package is not public.
The server builds the image from the release's `Dockerfile` and a compose override file selects the
local image. The build downloads the Caddy builder image and the Go modules from the internet and
takes several minutes.

!!! note
    Building the image on TrueNAS has not been tested. Check that the build log ends with the
    `caddy list-modules` output of step 2, and that step 3 lists all eight modules, before you use
    the image.

#### Steps

1. Build the image:

        sudo docker build --pull -t local-agent-stack-caddy:2.11.9-local /mnt/tank/ai/stacks/local-agent-stack/stack/edge

2. Check the end of the build output.

    The last build step prints the Caddy version and the non-standard modules, one
    `dns.providers.` module per provider with its version.

3. List the DNS modules in the new image:

        sudo docker run --rm local-agent-stack-caddy:2.11.9-local caddy list-modules --skip-standard

    The output lists `dns.providers.cloudflare`, `dns.providers.desec`,
    `dns.providers.digitalocean`, `dns.providers.duckdns`, `dns.providers.namecheap`,
    `dns.providers.ovh`, `dns.providers.porkbun` and `dns.providers.route53`.

4. Write the compose override file that selects the local image:

        sudo tee /mnt/tank/ai/appdata/caddy/local-image.override.yaml > /dev/null <<'EOF'
        services:
          caddy:
            image: local-agent-stack-caddy:2.11.9-local
            pull_policy: never
        EOF

5. When you install the app in [Create the ai-edge custom app](#create-the-ai-edge-custom-app),
   use the following YAML instead of the standard one. Compose merges the two files, and the
   override replaces only the image:

        include:
          - path:
              - /mnt/tank/ai/stacks/local-agent-stack/stack/edge/compose.yaml
              - /mnt/tank/ai/appdata/caddy/local-image.override.yaml
            env_file: /mnt/tank/ai/secrets/edge.env
        services: {}

    If you also use the internal CA of Appendix D, list its override file as a third path.

6. List the override in your desired-state file, the copy of `deploy/truenas.toml` that Chapter 10
   creates in [Create your desired-state file](#create-your-desired-state-file). Add this line to
   the `[apps.ai-edge]` table, below its `stack` line; if you create the file later, add the line
   then:

        overrides = ["/mnt/tank/ai/appdata/caddy/local-image.override.yaml"]

    With the internal CA of Appendix D as well, the list names both files, in the order of the
    paths in step 5. `deploy.py apply` then writes the same YAML as step 5, followed by its content
    hashes, and keeps the override; without the line, `apply` would replace the YAML with the four
    lines of `stack/edge/truenas-app.yaml` and return to the published image.

#### Results

The edge app runs the image built on the server. Repeat steps 1 to 3 after every release update
that changes `stack/edge/Dockerfile`, then redeploy the app with
`sudo midclt call -j app.redeploy ai-edge`: a redeploy does not rebuild the image, and `deploy.py`
does not detect a rebuilt image or a changed override file.

!!! note
    `deploy.py` compares the images that an app runs with the images of the release's compose file,
    not with an override. While the local image runs, `deploy.py plan` and `drift` report `ai-edge`
    with `runs images other than <release-tag>'s`, and `deploy.py apply` redeploys the app, which
    keeps the local image. To avoid that redeploy, name the other apps with `--app` when you apply.

To return to the published image, remove the local-image file from the `overrides` line of your
desired-state file (the whole line if it names no other file) and run `deploy.py apply --app ai-edge`
as in Chapter 10, or, without a desired-state file, edit the app and use the YAML of
[Create the ai-edge custom app](#create-the-ai-edge-custom-app).

## Install the ai-edge app

The app is a TrueNAS custom app whose YAML includes the release's compose file and names the
environment file. It joins `ai-net` and publishes ports 80 and 443.

### Prepare the Caddy data directories

#### Prerequisites

- The dataset `tank/ai/appdata/caddy` exists with the Apps preset
  ([Create the appdata datasets](#create-the-appdata-datasets)).

#### About this task

Caddy runs as UID and GID 568 and writes its ACME account, certificates and state to two
directories on the dataset. If Docker created them at the first start, they would be created by
root, and Caddy might not be able to write to them.

#### Steps

1. Create the directories:

        sudo mkdir -p /mnt/tank/ai/appdata/caddy/data /mnt/tank/ai/appdata/caddy/config

2. Give them to the `apps` user and group:

        sudo chown 568:568 /mnt/tank/ai/appdata/caddy/data /mnt/tank/ai/appdata/caddy/config

3. Verify the owner:

        sudo stat -c '%n %u:%g' /mnt/tank/ai/appdata/caddy/data /mnt/tank/ai/appdata/caddy/config

    Both lines end in `568:568`.

#### Results

Caddy can write to `/data` and `/config`. Appendix A backs up the dataset with the other
application data; losing it only means that Caddy obtains a new certificate.

### Create the ai-edge custom app

#### Prerequisites

- The port inventory reports ports 80/tcp, 443/tcp and 443/udp as `free`
  ([Run the port inventory](#run-the-port-inventory)). The TrueNAS web interface keeps its own
  ports, `<ui-https-port>` and `<ui-http-port>`.
- The network `ai-net` exists ([Create the ai-net network](#create-the-ai-net-network)).
- The repository is cloned at the release tag in `/mnt/tank/ai/stacks/local-agent-stack`.
- The host names resolve to `192.0.2.10` ([Create the local DNS records](#create-the-local-dns-records)),
  and no UniFi Content Filter or Ad Blocking policy covers the TrueNAS server
  ([Keep the server out of DNS redirection](#keep-the-server-out-of-dns-redirection)).
- `edge.env` is complete and set for staging, and the Caddy image validated it
  ([Check the Caddy image on TrueNAS](#check-the-caddy-image-on-truenas)).
- The Caddy data directories exist ([Prepare the Caddy data directories](#prepare-the-caddy-data-directories)).
- The `ai-inference` app of Chapter 4 is installed. It is not required for the edge app, but the
  verification in this chapter uses it.

#### About this task

TrueNAS validates the YAML with `docker compose config` when you save it, so the included file and
the environment file must exist. It runs the app as the compose project `ix-ai-edge`. The **Edit**
screen of a custom app shows only this YAML; the included files are changed through the git clone.

#### Steps

1. Go to **Apps** > **Discover Apps**, click **More Options** (⋮) next to **Custom App**, and click
   **Install via YAML**.

2. Enter **Name** `ai-edge`.

3. Enter the following YAML in **Custom Config**. It is the file `stack/edge/truenas-app.yaml` of
   the release:

    {{ include stack/edge/truenas-app.yaml }}

    The line `services: {}` is required for a YAML that consists of an `include` only. On the
    workstation, in the clone, `python3 tools/deploy.py render --app ai-edge` prints the same four
    lines after a `# ai-edge` line. When the clone has the release tag, it adds an
    `x-local-agent-stack` block with the content hashes that `deploy.py apply` records
    ([Setting up deploy.py](#setting-up-deploypy)). Paste only the four lines.

    If you built the image on the server, use the YAML from
    [Build the Caddy image on TrueNAS](#build-the-caddy-image-on-truenas) instead.

4. Click **Save**.

    TrueNAS pulls the images and starts the containers. If **Save** reports an error, read the
    message: a missing value names the variable (for example `set LAB_DOMAIN in edge.env`), and a
    missing file names its path.

5. Go to **Apps** > **Installed** and select `ai-edge`.

    The state of the app is **Running**, and the **Workloads** card lists the containers `caddy`
    and `gpu-exporter`.

#### Results

The edge app is installed. Caddy starts to obtain the staging certificate at once; continue with
the verification.

### Verify the edge containers

#### Steps

1. List the containers of the app and their status:

        sudo docker ps --filter label=com.docker.compose.project=ix-ai-edge --format '{{.Names}}  {{.Status}}'

    About a minute after the start, `caddy` shows `Up ... (healthy)` and `gpu-exporter` shows
    `Up ...` (it has no health check). A status of `Restarting` means that the container fails;
    read its log with `sudo docker logs <container>`.

2. Check the published ports:

        sudo docker port caddy

    The output lists `80/tcp`, `443/tcp` and `443/udp`, each mapped to `0.0.0.0` (or to
    `EDGE_BIND_IP` if you set it).

3. Check the mounts of Caddy:

        sudo docker inspect caddy --format '{{range .Mounts}}{{println .Destination .Source}}{{end}}'

    The output includes `/data /mnt/tank/ai/appdata/caddy/data`,
    `/config /mnt/tank/ai/appdata/caddy/config` and
    `/etc/caddy/Caddyfile /mnt/tank/ai/stacks/local-agent-stack/stack/edge/Caddyfile`.

4. Check that both containers are on `ai-net`:

        sudo docker network inspect ai-net --format '{{range .Containers}}{{println .Name}}{{end}}'

    The output includes `caddy` and `gpu-exporter`, next to the containers of `ai-inference`.

5. Run the port inventory again:

        sh /mnt/tank/ai/stacks/local-agent-stack/tools/port-inventory.sh

    The section `Ports the stack needs on this server` now reads:

        Ports the stack needs on this server (Caddy, app ai-edge)
          80/tcp    ours: container caddy (app ai-edge)
          443/tcp   ours: container caddy (app ai-edge)
          443/udp   ours: container caddy (app ai-edge)

    The result line ends with `(exit 0)`. A line that reads `used by` names something else that
    also holds the port.

6. Check that the gateway does not answer the queries that Caddy sends to the public resolvers:

        sudo docker exec caddy nslookup chat.lab.example.com 1.1.1.1

    The output reports that the name does not exist, with `NXDOMAIN`, for example
    `** server can't find chat.lab.example.com: NXDOMAIN`. If it shows the address `192.0.2.10`
    instead, the gateway answers DNS queries that the server sends to `1.1.1.1`: a Content Filter
    or Ad Blocking policy covers the server
    ([Keep the server out of DNS redirection](#keep-the-server-out-of-dns-redirection)), and
    certificate renewal would fail.

    The `caddy` image is based on Alpine Linux, whose BusyBox provides `nslookup`, as it provides
    the `wget` of [Read the GPU metrics](#read-the-gpu-metrics); this check has not yet been run
    on the server.

#### Results

Both containers run, Caddy publishes ports 80 and 443 and keeps its data on the dataset, and its
DNS queries reach the public resolvers.

## Obtain the certificates

Caddy obtains the certificate by itself when it starts. You first let it obtain a certificate from
the Let's Encrypt staging service, which proves that the token, the DNS challenge and the
resolvers work, and then switch to production.

!!! note
    Test the staging certificate with `openssl` and `curl -k` from the workstation, not in a
    browser. Browsers do not trust staging certificates.

### Obtain a staging certificate

#### Steps

1. Follow the Caddy log. In the web interface, go to **Apps** > **Installed**, select `ai-edge`,
   and on the **Workloads** card click **View Logs** for `caddy`. Or run the following command and
   press Ctrl+C to stop:

        sudo docker logs -f caddy

    Caddy logs in JSON. During issuance it creates the TXT record, waits until the public
    resolvers see it, and then obtains the certificate. This can take a few minutes.

2. Search the log for the issued certificate:

        sudo docker logs caddy 2>&1 | grep -i 'certificate obtained'

    The output has a line that contains `certificate obtained` and `*.lab.example.com`. If there is
    none after five minutes, look for the errors in
    [Certificate issuance errors](#certificate-issuance-errors).

3. On the workstation, display the certificate that Caddy serves:

        echo | openssl s_client -connect llm.lab.example.com:443 -servername llm.lab.example.com 2>/dev/null | openssl x509 -noout -subject -issuer -enddate -ext subjectAltName

    The subject is `CN=*.lab.example.com`, the subject alternative name is
    `DNS:*.lab.example.com`, and the issuer names start with `(STAGING)`, for example
    `O=(STAGING) Let's Encrypt`. On macOS, whose `openssl` is LibreSSL, leave out
    `-ext subjectAltName` if it reports an unknown option.

4. Check the routing while ignoring the untrusted certificate:

        curl -sS -k -o /dev/null -w '%{http_code}\n' https://llm.lab.example.com/health/liveliness

    The output is `200`.

#### Results

The DNS challenge works with your token and resolvers, and Caddy routes requests. Caddy keeps the
staging certificate in
`/mnt/tank/ai/appdata/caddy/data/caddy/certificates/`, in a directory named after the CA's address.

### Switch to the production CA

#### Steps

1. On the workstation, edit `~/.config/local-agent-stack/secrets/edge.env` and set the production
   address:

        ACME_CA=https://acme-v02.api.letsencrypt.org/directory

2. Copy the file to the server:

        scp ~/.config/local-agent-stack/secrets/edge.env truenas_admin@192.0.2.10:

3. On TrueNAS, install it and delete the copy:

        sudo install -m 0600 -o root -g root ~/edge.env /mnt/tank/ai/secrets/
        rm ~/edge.env

4. Check the value on the server:

        sudo grep '^ACME_CA=' /mnt/tank/ai/secrets/edge.env

    The output is `ACME_CA=https://acme-v02.api.letsencrypt.org/directory`.

5. Redeploy the app, so that the containers start with the new value:

        sudo midclt call -j app.redeploy ai-edge

    The command returns when the app has been recreated. Every container of the app restarts.

6. Search the log for the new certificate:

        sudo docker logs caddy 2>&1 | grep -i 'certificate obtained'

    A line for `*.lab.example.com` appears. Caddy stores certificates per CA, so it obtains a new
    certificate from production instead of reusing the staging one.

7. On the workstation, display the certificate again:

        echo | openssl s_client -connect llm.lab.example.com:443 -servername llm.lab.example.com 2>/dev/null | openssl x509 -noout -subject -issuer -enddate -ext subjectAltName

    The subject is `CN=*.lab.example.com`, and the issuer is `O=Let's Encrypt` with no
    `(STAGING)` in its names.

8. Check that the workstation trusts the certificate:

        curl -sS -o /dev/null -w '%{http_code}\n' https://llm.lab.example.com/health/liveliness

    The output is `200`, without `-k` and without a certificate error.

9. List the stored certificates:

        sudo ls /mnt/tank/ai/appdata/caddy/data/caddy/certificates/

    The output lists two directories, one for the staging service
    (`acme-staging-v02.api.letsencrypt.org-directory`) and one for production
    (`acme-v02.api.letsencrypt.org-directory`).

#### Results

Caddy serves a publicly trusted wildcard certificate for every host name and renews it
automatically. Clients need no extra root certificate.

!!! caution
    Do not delete the Caddy data directory to force a new certificate. Let's Encrypt limits how
    many certificates it issues for the same names in a week, and a new certificate is issued on
    every start without stored data.

### Certificate issuance errors

Table: Certificate issuance errors

| Message in the Caddy log or at start-up | Cause | Action |
|---|---|---|
| `expected 1 zone, got 0` | The challenge lookup got an answer from a local zone for the lab domain | Keep public resolvers in `ACME_RESOLVERS`; check that the server can send DNS queries to them |
| `timed out waiting for record to fully propagate` | The resolvers in `ACME_RESOLVERS` do not see the public zone, DNS to the internet is blocked, or the gateway answers the server's queries to them (a UniFi Content Filter or Ad Blocking policy covers the server) | As above; check the zone's name servers with `dig +short NS example.com @1.1.1.1`, and run step 6 of [Verify the edge containers](#verify-the-edge-containers) |
| `File to import not found: dns-<name>` | `DNS_PROVIDER` names a provider that is not in the image | Set one of the eight provider names |
| Caddy refuses the token at start-up | `DNS_PROVIDER_TOKEN` is a placeholder or not a Cloudflare token | Store the token from [Create a zone-scoped API token](#create-a-zone-scoped-api-token) |
| An authentication or permission error from the Cloudflare API | The token is revoked, expired, or lacks a permission or the zone | Repeat [Verify the API token](#verify-the-api-token); create a new token if needed |
| `set <VARIABLE> in edge.env` when you save or redeploy | A required variable is missing | Complete `edge.env` and copy it to the server again |

After you correct `edge.env` on the workstation, copy it to the server and run
`sudo midclt call -j app.redeploy ai-edge`.

## Verify each host name

At this stage `ai-inference` (Chapter 4) is running, so `llm.lab.example.com` and
`models.lab.example.com` reach their containers. `chat`, `mcp` and `search` point to containers
that Chapter 6 installs; until then Caddy answers them with `502 Bad Gateway`. A 502 for these
three names is the expected result now: it shows that the name resolves, the certificate is valid,
and Caddy routes the request.

### Check every host name from the workstation

#### Steps

1. Check the two names whose apps are installed:

        curl -sS -o /dev/null -w '%{http_code}\n' https://llm.lab.example.com/health/liveliness
        curl -sS https://models.lab.example.com/health

    The first prints `200`; LiteLLM answers this path without a key. The second prints `OK`;
    llama-swap answers `/health` without its API key.

2. Check the three names whose apps are not installed yet, with a `HEAD` request per name:

        curl -sI https://chat.lab.example.com/ | head -1
        curl -sI https://mcp.lab.example.com/ | head -1
        curl -sI https://search.lab.example.com/ | head -1

    Each command prints `HTTP/2 502`.

3. Check that port 80 redirects to HTTPS:

        curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' http://llm.lab.example.com/

    The output is a redirect status (`3xx`) followed by `https://llm.lab.example.com/`.

4. Check that a name that the `Caddyfile` does not list is closed. The command connects to the
   server without a DNS record for the name:

        curl -sS --http1.1 --resolve test.lab.example.com:443:192.0.2.10 https://test.lab.example.com/

    curl reports an error instead of an HTTP status, for example `Empty reply from server`.

#### Results

Table: Expected results by host name

| Host name | Now | After Chapter 6 |
|---|---|---|
| `llm.lab.example.com` | `200` on `/health/liveliness` | Unchanged |
| `models.lab.example.com` | `OK` on `/health` | Unchanged |
| `chat.lab.example.com` | `HTTP/2 502` | `HTTP/2 200`, or a redirect to the login page |
| `mcp.lab.example.com` | `HTTP/2 502` | An answer from the MCP hub instead of `502` |
| `search.lab.example.com` | `HTTP/2 502` | An answer from SearXNG instead of `502` |

A failure other than these points to its cause: a name that does not resolve is a DNS record
([Check name resolution from each client](#check-name-resolution-from-each-client)); a certificate
error is the CA setting or an unfinished issuance ([Obtain the certificates](#obtain-the-certificates));
a 502 on `llm` or `models` means that `ai-inference` is not running or not on `ai-net`; a closed
connection for a listed name means that the client's address is outside `EDGE_ALLOWED_CIDRS`.
Chapter 6 checks the remaining names again after it installs the apps.

### Check the response headers

#### Steps

1. Display the status line and headers of a request:

        curl -sS -D - -o /dev/null https://models.lab.example.com/health

    The output starts with `HTTP/2 200` and includes the following headers (HTTP/2 prints header
    names in lower case):

        strict-transport-security: max-age=31536000
        x-content-type-options: nosniff
        x-frame-options: SAMEORIGIN
        referrer-policy: strict-origin-when-cross-origin

    There is no `server` header and no `x-powered-by` header.

#### Results

Caddy adds the security headers of the edge app to every response.
[Container hardening and response headers](#container-hardening-and-response-headers) describes
them.

### Open a host name in each browser

#### About this task

This task checks that each browser resolves the lab names through the local DNS, with the setting
of [Check the secure DNS setting of each browser](#check-the-secure-dns-setting-of-each-browser).
It needs the production certificate; browsers do not trust the staging one.

#### Steps

1. On each client, open `https://models.lab.example.com/health` in each browser that you use with
   the stack.

    The page shows `OK`, without a certificate warning.

#### Results

Every browser reaches the stack by name. A browser that reports that the server cannot be found
uses a public secure DNS service without fallback: correct its setting as in
[Check the secure DNS setting of each browser](#check-the-secure-dns-setting-of-each-browser).

## The GPU exporter

TrueNAS 25.10 has no reporting graphs for the GPU. The `gpu-exporter` container reads the GPU
through the NVIDIA driver library (NVML) and serves the values as Prometheus metrics at
`http://gpu-exporter:9835/metrics`. The port is not published: only containers on `ai-net` can read
it. The stack contains no Prometheus server; to graph the metrics, add one that joins `ai-net` and
scrapes this address, for example the Prometheus and Grafana apps of the TrueNAS catalog.

{{ include stack/edge/compose.yaml lines=68-100 }}

The image is the `-nvml` flavour of the exporter, which reads `libnvidia-ml.so.1` directly instead
of running `nvidia-smi`. The NVIDIA container runtime adds that library and the GPU device nodes
when the container starts, for the `utility` capability only, which is why the container's root
filesystem is not read-only. The image is distroless: it has no shell and no HTTP client, so the
container has no health check, and it runs as UID 65534 with every capability dropped and a memory
limit of 128 MB.

### Metrics of the GPU exporter

All metric names start with `nvidia_smi_`. Every value carries the GPU's `uuid` as a label.

Table: Main GPU metrics

| Metric | Meaning | Unit |
|---|---|---|
| `nvidia_smi_gpu_info` | Constant `1`, with the GPU name, driver version, CUDA version and other details as labels | None |
| `nvidia_smi_utilization_gpu_ratio` | GPU utilization | Ratio, 0 to 1 |
| `nvidia_smi_memory_used_bytes` | Used GPU memory (VRAM) | Bytes |
| `nvidia_smi_power_draw_watts` | Power draw | Watts |
| `nvidia_smi_temperature_gpu` | GPU temperature | Degrees Celsius |
| `nvidia_smi_nvml_return_code` | Status of the last collection | `0` on success, `-1` on failure or when no GPU is visible |

The exporter also serves further GPU families (clocks, throttle reasons, energy, PCIe) and the
standard process metrics of a Prometheus exporter.

### Read the GPU metrics

#### About this task

The exporter's port is reachable only from `ai-net`, so the command runs `wget` inside the `caddy`
container, which is on the same network. Any container on `ai-net` with an HTTP client works, for
example `llama-swap`, which has `curl`.

#### Steps

1. Read the main metrics:

        sudo docker exec caddy wget -q -O - http://gpu-exporter:9835/metrics | grep -E '^nvidia_smi_(gpu_info|utilization_gpu_ratio|memory_used_bytes|power_draw_watts|temperature_gpu|nvml_return_code)'

    The output has one line per metric. `nvidia_smi_gpu_info` carries the labels
    `name="NVIDIA GeForce RTX 4080"` and `driver_version="580.173.02"`, and
    `nvidia_smi_nvml_return_code` is `0`.

2. Compare the values with the host:

        nvidia-smi --query-gpu=utilization.gpu,memory.used,power.draw,temperature.gpu --format=csv

    The values match within the moment between the two commands. `memory.used` is in MiB, while
    the exporter reports bytes.

3. Optional: watch the GPU on the host while a model works, refreshing every five seconds; press
   Ctrl+C to stop:

        nvidia-smi --query-gpu=utilization.gpu,memory.used,power.draw,temperature.gpu --format=csv -l 5

#### Results

The exporter reports the GPU, and its values match `nvidia-smi`.

!!! note
    Not tested on a host with a GPU: the exporter runs with every Linux capability dropped, which is
    expected to be enough for NVML, because it needs only the device nodes that the NVIDIA runtime
    adds. Check the result of step 1. If `wget` gets no answer, if `nvidia_smi_nvml_return_code` is
    not `0`, if `sudo docker ps` shows `gpu-exporter` as `Restarting`, or if
    `sudo docker logs gpu-exporter` shows an NVML error, the exporter cannot read the GPU in this
    configuration. Caddy and the other apps are not affected, and `nvidia-smi` on the host shows the
    same values. Record the log output in a project issue so that the compose file can be
    corrected.

## Security of the edge

The edge app is the stack's only entry point from the network. This topic summarizes what it
exposes, the protections it applies, and what lies outside it.

### What the edge exposes

Table: Network exposure of the server

| Port | Listener | Reachable from | Protection |
|---|---|---|---|
| 80/tcp | `caddy` | Every network that reaches `EDGE_BIND_IP` | Answers only with a redirect to HTTPS |
| 443/tcp, 443/udp | `caddy` | Every network that reaches `EDGE_BIND_IP` | TLS; connections from outside `EDGE_ALLOWED_CIDRS` and for unlisted names are closed; each service has its own login |
| 2019/tcp | Caddy admin API | Inside the `caddy` container only | Not published |
| 9835/tcp | `gpu-exporter` | Containers on `ai-net` | Not published; no authentication |
| `<ui-https-port>`/tcp, `<ui-http-port>`/tcp (444 and 81 in this guide's examples) | TrueNAS web interface | The LAN | TrueNAS login; not behind Caddy |

Table: Authentication behind each host name

| Host name | What a client needs |
|---|---|
| `chat.lab.example.com` | An Open WebUI account |
| `llm.lab.example.com` | A LiteLLM key; `/health/liveliness` is open |
| `models.lab.example.com` | The llama-swap API key; `/health` is open |
| `mcp.lab.example.com` | The MCP hub bearer token (`MCP_HUB_TOKEN`) |
| `search.lab.example.com` | Nothing: SearXNG has no login, so every client inside `EDGE_ALLOWED_CIDRS` can search |

The TrueNAS web interface is served by TrueNAS itself on its own ports, `<ui-https-port>` and
`<ui-http-port>`, with its own certificate, at `https://192.0.2.10:<ui-https-port>`
(`https://192.0.2.10:444` in this guide's examples). Caddy does not proxy it, and the LAN-only
guard does not apply to it. A host name such as `truenas.lab.example.com` on port 443 reaches Caddy, which closes
the connection because the name is not in the `Caddyfile`.

### LAN-only access guard

The `Caddyfile` closes every connection from a client address outside `EDGE_ALLOWED_CIDRS` before
it routes the request. This is a second line of defence. The first is the network itself:

- Do not forward any port from your router to the server. The stack is designed for access from
  the LAN only.
- TrueNAS 25.10 has no host firewall in its web interface, and with Apps enabled Docker forwards
  traffic to every published port. Do not edit firewall rules by hand; TrueNAS updates remove them.
- The default `private_ranges` admits every private address. If other private networks reach the
  server (a guest network or a VPN, for example), set `EDGE_ALLOWED_CIDRS` to the ranges that
  should have access, such as the one network of your LAN (`192.0.2.0/24` in this guide's
  placeholders). No container of the stack calls the lab host names;
  they reach each other by container name on `ai-net`, so a narrower list does not affect them.
- `EDGE_BIND_IP` limits the server address on which Caddy listens, when the server has more than
  one.
- SearXNG at `search.lab.example.com` has no login and runs without its rate limiter, which suits
  a LAN only. [Known limitations of the RAG and web apps](#known-limitations-of-the-rag-and-web-apps)
  lists what it would need if it were ever reachable from beyond the LAN.

### Container hardening and response headers

Hardening of the containers:

- `caddy` runs as UID and GID 568 with every capability dropped, `no-new-privileges` and a
  read-only root filesystem; only `/data`, `/config` and a temporary `/tmp` are writable. Its
  binary carries no file capabilities, and it binds ports 80 and 443 through
  `net.ipv4.ip_unprivileged_port_start=0`.
- The admin API listens on `localhost:2019` inside the container only; the health check uses it.
- DNS credentials are written as `{env.NAME}` in the `Caddyfile`, so they never appear in Caddy's
  built configuration, and `persist_config off` keeps that configuration off the disk.
- `gpu-exporter` runs as UID 65534 in a distroless image with every capability dropped, gets the
  GPU with the `utility` capability only, and is not published.

The response headers that Caddy adds to every host name:

{{ include stack/edge/Caddyfile lines=67-78 }}

- `Strict-Transport-Security` (HSTS) for one year, for each host name only (no subdomains). After
  a browser has received it from a trusted certificate, it refuses plain HTTP and certificate
  errors for that name.
- `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN` and
  `Referrer-Policy: strict-origin-when-cross-origin`.
- The `Server` and `X-Powered-By` headers are removed.
- There is no `Content-Security-Policy`: Open WebUI and the llama-swap interface load inline
  scripts and styles, and a wrong policy breaks them without a visible error.

!!! caution
    Because of HSTS, a browser that has opened a host name with the production certificate refuses
    an untrusted certificate for that name for a year. If you later move to the internal CA of
    Appendix D, trust its root certificate on every client before you switch.

The edge app is complete. Continue with Chapter 6, which installs the RAG and web apps behind `chat`, `mcp` and `search`.
Chapter 7 configures the coding agent against `https://llm.lab.example.com/v1` and
`https://mcp.lab.example.com`.
