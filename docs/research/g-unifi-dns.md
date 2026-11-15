# Lab host names in local DNS on a UniFi UDM-Pro SE

Status: research, 2026-11-15. Author: research agent G.

Scope: v1.2 design §2 (#32). This note covers making `chat`, `llm`, `models`, `mcp` and `search` under the
lab domain resolve to the TrueNAS server on a UDM-Pro SE, and what breaks split-horizon DNS.
Placeholders: TrueNAS `192.0.2.10`, c4dev `192.0.2.20`, the UDM's LAN address `192.0.2.1`, lab domain
`lab.example.com` in the zone `example.com`. Every source was read on 2026-11-15. Ubiquiti's help center blocks
automated page fetches, so its articles were read through the help center's public Zendesk API. The JSON
holds the same article body, and each source gives the article's `updated_at` stamp.

## Summary

- **Current software (Verified).** On the release channel, the UDM-Pro SE's newest firmware is **UniFi OS 6.0.17**,
  published 2026-11-10 [S11]. The current UniFi Network application for UniFi OS 6 is **11.0.x**: **11.0.99** is on
  the release channel of Ubiquiti's update API, and **11.0.102** was announced on 2026-11-13 [S12][S10a]. Network 11 needs
  UniFi OS 6.0 or newer [S10a]. A console still on UniFi OS 5.x stays on Network **10.6.x** (10.6.111, 2026-11-13) [S10b].
- **UI path (Verified for 9.4, Assumed for 10.6 and 11.0).** **Settings > Policy Table > Create New Policy > DNS**, then
  **Type: Host (A)**, **Domain Name**, **IP Address**, an optional **TTL**, and **Add** [S1]. A HostiFi guide on Network
  9.5.21 (updated 2026-10-09) uses the same path [S18], and the 10.5 release notes still name the "Policy Table" [S10d].
  In Network 9.3 the path was **Settings > Policy Engine > DNS > Create DNS Record** [S1]. No Ubiquiti article names the
  path for 10.6 or 11.0.
- **Record types (Verified):** Host (A), Host (AAAA), Alias (CNAME), Mail (MX), Text (TXT), Service (SRV) and Forward
  Domain [S1]. CNAME needs UniFi OS 4.3+ and Network 9.3+ [S1]. The API limits a record name to 127 characters and an
  A/AAAA TTL to 0–86400 s. It has **no per-network field**, so a record applies to the whole site [S13].
- **No wildcards (Assumed, strong).** Ubiquiti documents no wildcard support [S1]. The UniFi API rejected
  `*.…` with `"Invalid hostname"` [S16], and two projects that track the API say wildcards are not supported. One of
  them confirmed this on 2026-11-07 [S15][S17]. **Use five Host (A) records**, one per name. A Forward Domain covers a
  domain and all its subdomains, but it can only hand the queries to another DNS server [S2].
- **Recommendation:** add five Host (A) records → `192.0.2.10` with the default TTL, and give TrueNAS a fixed IP. Keep
  every network's **DNS Server** on its default, which is the gateway. One A record plus four Alias (CNAME) records is
  an acceptable variant. Do not add AAAA records, and do not publish any lab record in the public Cloudflare zone.
- **Content Filtering and Ad Blocking** redirect DNS traffic to the gateway, even from clients set to a custom DNS
  server [S2][S3]. Local records therefore still answer. The one risk is the **TrueNAS server**: if it falls inside a
  filter policy's source, the UDM silently answers Caddy's `ACME_RESOLVERS` queries to 1.1.1.1 (see Details §5). Keep
  the server out of those policies, and test it with one command.
- **Encrypted DNS** (formerly DNS Shield) encrypts only the hop from the UDM to its upstream, so local records keep
  answering (Assumed, third-party guide [S19]). **DNS rebinding:** Ubiquiti documents no rebinding setting [S1–S9].
  dnsmasq's rebinding filter applies only to answers from upstream servers [S22], so it cannot affect local records.
- **Browsers using DNS-over-HTTPS (Verified in browser source):**
  - Chrome and Edge in their default automatic mode keep using the UDM. Choosing a named provider switches them to
    "secure" mode, which has no fallback, so the lab names fail [S31][S32][S33].
  - Firefox's default mode falls back to the system resolver after an NXDOMAIN [S26][S24]. Without fallback, Firefox
    needs an exception for `lab.example.com` [S28][S29].
  - With iCloud Private Relay, the device reaches names that are not public directly on the local network [S35].
- **IPv6:** A records only is correct. With no AAAA record, Happy Eyeballs connects over IPv4 after waiting at most the
  50 ms Resolution Delay [S46]. Make sure IPv6 clients get the gateway as their DNS server (Assumed label).
- **Caddy (Verified in source):** the repo's `resolvers {$ACME_RESOLVERS:1.1.1.1 1.0.0.1}` is consistent with UniFi.
  With custom resolvers, certmagic v0.25.6 (Caddy 2.11.9) runs the zone lookup through them and polls them for the TXT
  record every 2 s, for up to 2 min, instead of querying the authoritative servers [S44]. Also check that the public
  zone has no wildcard that would answer for the lab names [S45].

## Recommendation

Install nothing new. In the UniFi Network application, add one **Host (A)** record per host name, each pointing to the
TrueNAS server, and leave clients on the gateway's DNS. The reasons:

1. **Simplest supported option.** Per-name A records are documented [S1] and have existed since Network 8.2 [S48].
   They have no target constraints. They also match the table that `guide/chapters/05-edge.md` already prints.
   Five edits when the server's IP changes is an acceptable cost, and the procedure makes that IP fixed anyway.
2. **No wildcards.** A wildcard (`*.lab.example.com`) would save edits when names are added later, but UniFi rejects
   it [S15][S16][S17].
3. **Alternatives cost more.**
   - A Forward Domain needs another DNS server (CoreDNS or dnsmasq on TrueNAS), which means port 53 on the host.
     v1.2 §1 limits the host to 80/443 for Caddy.
   - The client page's **Local DNS Record** gives a device only one name [S1].
   - Public records that point to the private IP leak the internal address and the service inventory. They undo the
     certificate-log benefit of the wildcard certificate. They also break contract §2, and they don't work everywhere:
     Firefox's DoH rejects RFC 1918 answers [S24].
4. **Keep the public zone empty of lab records**, as contract §2 requires. Caddy writes only the temporary
   `_acme-challenge` TXT record.
5. **Optional, the owner's choice:**
   - Make Firefox's automatic DoH rollout stand down on the home network with the canary domain (Details §3.4).
   - If the public zone has a wildcard, add one harmless marker record at `lab.example.com` (Details §4.3).

## Options compared

| Option | What it is | Fit for this network | Maturity | Licence | Verdict |
|---|---|---|---|---|---|
| Five Host (A) records in UniFi | One record per name → `192.0.2.10`, in **Policy Table > DNS** | Exact, documented, site-wide | Since Network 8.2 [S48]; documented for 9.3/9.4 [S1] | Proprietary (UniFi Network) | **Recommended** |
| One Host (A) + Alias (CNAME) records | `edge.lab.example.com` A → IP; five CNAMEs to it | One edit on IP change; needs UniFi OS 4.3+/Network 9.3+ [S1]. A dnsmasq CNAME target must be a locally known name [S22], which it is here | Documented [S1]; UI labels from a third party [S18] | Proprietary | Acceptable variant |
| Wildcard `*.lab.example.com` in UniFi | One record for all names | Rejected as invalid hostname [S16]; "not supported" [S15][S17] | n/a | n/a | **Not possible** |
| Forward Domain `lab.example.com` → DNS server elsewhere | UniFi forwards the domain and all subdomains [S2] to e.g. CoreDNS with a wildcard | Adds a service and port 53 on TrueNAS (against v1.2 §1); hides the public zone from clients | Documented [S1][S2] | CoreDNS Apache-2.0 / dnsmasq GPL | Not recommended |
| Client Devices > Local DNS Record on TrueNAS | One host name tied to a fixed IP | Gives one name only, not five [S1] | Documented [S1] | Proprietary | Not sufficient (fine for the server's own name) |
| Pi-hole / AdGuard Home as the network's DNS server | Separate resolver handed out by DHCP [S1] | Wildcards possible, but more moving parts and the content-filtering caveats of [S2] | Mature | EUPL / GPL | Not recommended |
| Public A records → `192.0.2.10` | Names in the public Cloudflare zone | Leaks internal IP and names; Firefox DoH rejects RFC 1918 answers [S24]; resolvers with rebind protection drop them [S22] | n/a | n/a | **Rejected** |
| Hosts file on each client | `/etc/hosts`, Windows `hosts` | Already the guide's fallback for clients not using the UDM | Universal | n/a | Fallback only |

## Details

### 1. UniFi Network version and where DNS records live

- **Versions (Verified).**
  - The update API lists **UDMPROSE v6.0.17+7bcad58** on the `release` channel, created 2026-11-10 [S11].
  - The UniFi OS 6 Network package (`unifi-native`, platform `uos-deb13-arm64`) is **v11.0.99** on the release channel.
    The UniFi OS 5 package (`uos-deb11-arm64`) is **v10.6.109** [S12].
  - The community release feed shows **11.0.102** and **10.6.111**, both on 2026-11-13 [S10a][S10b].
  - 11.0.83 (2026-10-12) moved the database to PostgreSQL, cleared statistics history and migrated every site to the
    Zone-Based Firewall. 11.0.x requires UniFi OS 6.0+ [S10c].
  - The owner sees the installed versions and the release channel under **Settings > Control Plane > Updates** [S8].
- **Path (Verified for 9.3/9.4 [S1]).**
  - Network 9.4 and later: **Settings > Policy Table > Create New Policy > DNS**.
  - Network 9.3: **Settings > Policy Engine > DNS > Create DNS Record**.
  - The help article was updated on 2026-11-11 but still names only 9.3 and 9.4 [S1].
  - For 10.6 and 11.0 the same path is **Assumed**: HostiFi's 9.5.21 walk-through uses it [S18], and the 10.5.54/10.5.67
    release notes refer to the "Policy Table" [S10d]. No source names a newer path.
- **Fields (Verified [S1]).**
  - **Type**: Host (A), Host (AAAA), Alias (CNAME), Mail (MX), Text (TXT), Service (SRV), Forward Domain.
  - **Domain Name**, **IP Address**, optional **TTL**, button **Add**.
  - For CNAME, HostiFi shows **Alias Domain Name** and **Target Domain Name** (Assumed for 10.x/11.x) [S18].
- **Limits (Verified in the API schema [S13][S14]).**
  - `domain` is 1–127 characters. `ttlSeconds` is 0–86400 for A/AAAA and 0–604800 for CNAME.
  - Records have no network or VLAN field, so they apply to the whole site.
  - A list call returns at most 200 per page. The maximum number of records is **UNVERIFIED**.
  - The Integration API's DNS-policy endpoints reject labels that start with `_` [S15]. That doesn't matter here.
- **Scripted alternative (Verified schema, Assumed auth header).**
  - `POST https://192.0.2.1/proxy/network/integration/v1/sites/{siteId}/dns/policies` with
    `{"type":"A_RECORD","enabled":true,"domain":"chat.lab.example.com","ipv4Address":"192.0.2.10","ttlSeconds":0}` [S13].
  - The header that carries the API key (`X-API-KEY`) is **UNVERIFIED**: the spec declares no security scheme.
  - The guide stays with the UI.
- **Interaction with "Domain Name" and client host names.**
  - Each network's DHCP server can hand out an optional **Domain Name** [S7], default `localdomain` per a 2024 guide (Assumed) [S48].
  - The five records are full names and do not depend on it.
  - Do not set a network's Domain Name to the lab domain. If the gateway also registers DHCP client names under that
    domain (Assumed [S48]), a device named `chat` or `search` would collide with a service name.
  - The client page's **Local DNS Record** is a shortcut for one Host (A) record per device. Those names "only resolve
    for clients using the Gateway as their DNS server" [S1].
- **Resolver behind it (Assumed).** UniFi's resolver is dnsmasq [S15]. The dnsmasq facts this note relies on:
  - Local records answer before forwarding.
  - Names that are not local are forwarded upstream.
  - Negative answers from upstream are cached for the SOA's negative TTL [S22].

### 2. Choosing between records

- **Five Host (A) records**, recommended: one per name, all → `192.0.2.10`.
- **One A record plus CNAMEs**: `edge.lab.example.com` A → `192.0.2.10`, then `chat` … `search` CNAME →
  `edge.lab.example.com`.
  - In dnsmasq a CNAME target "must be a DNS record which is known to dnsmasq and NOT a DNS record which comes from an
    upstream server" [S22]. A local A record satisfies that.
  - One forum user reports more stable results with CNAMEs (anecdotal, Aug 2026 [S20]).
- **Forward Domain.** Enter only the base domain: "Any DNS query matching this domain (including subdomains) will be
  forwarded" [S2]. Using it for `lab.example.com` would also forward `_acme-challenge.lab.example.com`. The repo's
  `ACME_RESOLVERS` already protects Caddy from that.
- **Fixed IP for TrueNAS (Verified):** **Client Devices** > *device* > **Settings** > **Fixed IP Address** [S1]. The
  A records are only as stable as this address.

### 3. Things that break split horizon, and what to do

#### 3.1 Content Filtering, Ad Blocking, Encrypted DNS

- **Content Filtering** lives at **Settings > CyberSecure > Content Filter** (Verified [S2]).
  - Each policy has a **Source** of Networks and/or client Devices, an optional **Ad Blocking** switch, Safe Search, and
    a **Filtering Policy** (Off / Basic / Enhanced, the last one powered by Cloudflare) [S2].
  - It "works by redirecting DNS traffic to the UniFi Gateway for inspection" [S2].
  - With Ad Blocking on, "Clients using custom DNS servers are redirected to use the UniFi Gateway DNS server" [S3].
  - Effect on clients: the gateway still holds the five records, so local records keep answering (Assumed: no source
    says so outright, and Ubiquiti's caveat [S1][S2] concerns custom internal DNS servers, not gateway records). The
    redirect even helps, because it pulls clients with a hard-coded DNS server onto the UDM.
  - Effect on the **TrueNAS server**: see §5.
- **Encrypted DNS** (Settings > CyberSecure, "called DNS Shield before Network 9") changes only the UDM→upstream hop.
  "local DNS records you've defined on the gateway keep working" (Assumed; third-party guide, 2026-11-02 [S19]).
  - Forum users report intermittent resolution with it on (anecdotal, Aug 2026 [S20]).
  - If lab names resolve only some of the time, test with Encrypted DNS off.
- **DNS Assistance (UNVERIFIED risk).** Network 10.3.55 added a per-WiFi "DNS Assistance setting … to improve DNS
  resiliency and latency" [S10e]. The API exposes it as `AUTO` or `MANUAL` with up to two "Failover DNS servers" [S13].
  - No documentation says how it answers. If it is set to manual public failover servers, WiFi clients could get
    NXDOMAIN for lab names during a failover.
  - Leave it on its default, and enter no public failover servers.

#### 3.2 DNS rebinding protection

- **No UniFi setting is documented (Verified).** A help-center search for "rebind" returns no DNS article [S1–S9].
  dnsmasq's `--stop-dns-rebind` rejects "addresses from upstream nameservers which are in the private ranges" [S22].
  Answers from local records are never subject to it.
- A February 2026 report says a gateway on Network 10 blocked `plex.direct` (public names with private IPs). It was
  not resolved in the thread (forum, Assumed [S21]).
- Conclusion: rebinding protection matters only for the rejected option of public records with private IPs. On top of
  that, Firefox's DoH ignores RFC 1918 answers (`network.trr.allow-rfc1918` = false [S24]).

#### 3.3 Clients and browsers that bypass the UDM

| Client | Default behaviour | Lab names | Action |
|---|---|---|---|
| Chrome / Edge, secure DNS on, "current service provider" (automatic) | "automatic" mode: DoH only if the system resolver is a known DoH provider, "may fallback to sending insecure queries on error" [S31][S33] | Work: the UDM is not a DoH provider, so queries go to it in plain DNS | None |
| Chrome / Edge with a provider picked from the list or a custom URL | Settings code switches to `SecureDnsMode.SECURE` [S32]: "will only send DNS-over-HTTPS queries and will fail to resolve on error" [S31] | **Fail** (NXDOMAIN from the public zone) | Set back to the current provider, or turn secure DNS off. Managed: `DnsOverHttpsMode` = `automatic` or `off` [S31]. `DnsOverHttpsExcludedDomains` exists for ChromeOS 131+ only [S47] |
| Firefox "Default" (TRR-first, provider `mozilla.cloudflare-dns.com`) | A failed DoH lookup, including NXDOMAIN, falls back to the system resolver [S26]. `strict_native_fallback` defaults to false [S24] | Work, after one DoH round trip | None, or the canary (§3.4) |
| Firefox "Custom" with "Always warn me if secure DNS isn't available" (TRR-only) | No fallback [S30][S26] | **Fail** | **Manage exceptions** → `lab.example.com`. An entry excludes the domain and every subdomain [S28]. Managed: policy `DNSOverHTTPS.ExcludedDomains` [S29] |
| Safari with iCloud Private Relay | "If a proxy or ODoH server detects that a specific server name is not a public internet name, it instructs the device to try to access the server directly over the local network" [S35] (Dec 2021 source) | Work | None. Never answer NXDOMAIN for `mask.icloud.com` unless you want Private Relay off on the network [S36] |
| Windows 11 system DoH | Upgrades only for servers in its DoH list (`Get-DnsClientDohServerAddress`) [S39] | Work while the adapter's DNS is the UDM | Keep adapter DNS automatic |
| Android Private DNS | "Automatic" upgrades to DoT only if the network's DNS server supports it. A host name enters strict mode with no fallback [S37] | Automatic works; a host name fails | Keep Automatic |
| CLI tools (Claude Code, OpenCode, curl, Python) | Use the OS resolver (Assumed) | Work | None |

Firefox labels: Firefox's main branch shows **Default protection**, **Custom** with **Always warn me if secure DNS
isn't available**, and **Off** [S30]. Release builds may still show the older Default/Increased/Max Protection
levels, so the guide should name the setting area and **Manage exceptions**, not the level names. Firefox also skips DoH
for the network's DNS suffix (`network.trr.split_horizon_mitigations` = true [S24][S26]). That is one more reason not to
make the lab domain the DHCP Domain Name (§1).

#### 3.4 Optional: Firefox canary domain

- Firefox's rollout heuristic resolves `use-application-dns.net` through the system resolver. It disables DoH when the
  answer is NXDOMAIN, has no addresses, or has only local addresses (`0.0.0.0`, loopback, private) [S27].
- On UniFi, HostiFi makes a name return NXDOMAIN with an **Alias (CNAME)** record whose **Target Domain Name** is
  `NXDOMAIN` (Network 9.5.21 [S18]; Assumed for 10.x/11.x). The same record for `use-application-dns.net` would turn off
  the automatic rollout for the whole home network.
- The canary does not override a user's explicit Custom choice [S27]. Firefox's TRR-first fallback already makes lab
  names work, so this is optional (Open question 2).

#### 3.5 IPv6

- **Do not add AAAA records.** The lab names should stay IPv4-only:
  - Caddy's default `EDGE_ALLOWED_CIDRS` (`private_ranges`) covers `fd00::/8` and `::1`, not global IPv6 addresses
    (`stack/edge/Caddyfile` comment). A global AAAA record would get clients dropped by `@outside`.
  - With only an A answer, RFC 8305 clients wait at most the 50 ms Resolution Delay for the AAAA answer, then connect
    over IPv4 [S46].
  - From the UDM, an AAAA query for a name that has only an A record should return "no error, no data". dnsmasq
    returns NODATA for an AAAA query to a CNAME that points to an A record only [S23]. For a plain local A record this
    is **Assumed**, and the procedure checks it.
- **Hand out the gateway as the IPv6 DNS server.** UniFi's Router Advertisements can carry DNS server information [S6].
  If a network's IPv6 settings advertise another resolver (an ISP's, for example), dual-stack clients may ask it and get
  NXDOMAIN. The exact UI label of the IPv6 DNS setting is **UNVERIFIED**. The check is on the client:
  `scutil --dns`, `resolvectl status`, or `Get-DnsClientServerAddress -AddressFamily IPv6` must list only the UDM.

#### 3.6 VLANs and clients on another DNS server

- Records are site-wide [S13]. Every VLAN whose **DNS Server** is the gateway (the default [S7]) resolves the names.
- A network whose DNS Server toggle was turned off and pointed elsewhere [S1] does not resolve them.
- Clients with a hard-coded DNS server, VPN clients with their own DNS (for example Tailscale MagicDNS), and VMs behind
  a hypervisor NAT also miss them. For each, check which DNS server the client actually uses (procedure step 6), or use
  the guide's hosts-file fallback.
- Resolving is not the same as reaching. The Zone-Based Firewall may still block traffic between VLANs to
  `192.0.2.10:443`, and Caddy's `EDGE_ALLOWED_CIDRS` must cover the client subnet. The default private ranges do.
- TrueNAS's own resolver matters only if a container calls a lab name. The stack uses container names on `ai-net`,
  so it doesn't need to.

### 4. Verification commands

#### 4.1 Against the UDM, from each client

| Platform | Command | Expected |
|---|---|---|
| Ubuntu (c4dev) | `dig @192.0.2.1 chat.lab.example.com A +short` | `192.0.2.10` |
| Ubuntu | `dig @192.0.2.1 chat.lab.example.com AAAA +noall +comments \| grep status` | `status: NOERROR` and `ANSWER: 0` (NODATA), not `NXDOMAIN` |
| Ubuntu | `resolvectl query chat.lab.example.com`; `resolvectl status` | `192.0.2.10`; DNS servers list only the UDM |
| macOS | `dig @192.0.2.1 chat.lab.example.com +short` | `192.0.2.10` |
| macOS | `dscacheutil -q host -a name chat.lab.example.com`; `scutil --dns \| grep nameserver` | `ip_address: 192.0.2.10`; only UDM addresses |
| Windows | `Resolve-DnsName chat.lab.example.com -Server 192.0.2.1 -Type A -DnsOnly` | `IPAddress 192.0.2.10` |
| Windows | `nslookup chat.lab.example.com 192.0.2.1` | `Address: 192.0.2.10` |
| Windows | `Get-DnsClientServerAddress`; `Resolve-DnsName chat.lab.example.com -DnsOnly -NoHostsFile` | Only the UDM; `192.0.2.10` through the system resolver |

`-Server`, `-Type`, `-DnsOnly` and `-NoHostsFile` are documented parameters of `Resolve-DnsName` [S38]. On macOS and
Ubuntu, `dig` bypasses the hosts file and the system cache. `dscacheutil` and `resolvectl` go through them.

#### 4.2 The public Cloudflare zone holds no lab records

| Check | Command | Expected |
|---|---|---|
| Name absent publicly | `dig chat.lab.example.com A @1.1.1.1 +noall +comments \| grep status` | `status: NXDOMAIN` |
| Same over DoH (what browsers see) | `curl -s -H 'accept: application/dns-json' 'https://cloudflare-dns.com/dns-query?name=chat.lab.example.com&type=A'` | `"Status":3` (RCODE 3 = NXDOMAIN) [S41] |
| No public wildcard catches lab names | `dig +short nonexistent-check.lab.example.com A @1.1.1.1` | empty |
| No leftover challenge record (outside issuance) | `dig +short _acme-challenge.lab.example.com TXT @1.1.1.1` | empty |
| Authoritative view | `dig +short NS example.com @1.1.1.1`, then `dig chat.lab.example.com @<one of those servers> +norecurse +noall +comments` | `NXDOMAIN` |
| Windows | `Resolve-DnsName chat.lab.example.com -Server 1.1.1.1 -DnsOnly` | error: name does not exist (exact text Assumed) |

In the Cloudflare dashboard, the zone's DNS records page must show no `chat`/`llm`/`models`/`mcp`/`search` records.
A TXT record under `_acme-challenge.lab` may appear briefly during issuance.

#### 4.3 Why the wildcard check matters (Verified, RFC 4592)

- A public `*.example.com` record answers `chat.lab.example.com` whenever `lab.example.com` does not exist as a node.
  RFC 4592's example synthesizes `foo.bar.example` from `*.example` "because bar.example. does not exist" [S45].
  DoH browsers and Private Relay would then get the wildcard's public target instead of NXDOMAIN, so none of the
  fallbacks in §3.3 would happen.
- Remedies:
  - Remove the wildcard, or
  - create any record at `lab.example.com` itself, for example a TXT record. The name then exists, and names below it
    get NXDOMAIN (closest encloser `lab.example.com`, no source of synthesis [S45]).
- If `LAB_DOMAIN` is the zone apex itself, a public wildcard there always shadows the lab names and must go.

### 5. Caddy's DNS-01 challenge with UniFi split horizon

- **What the Caddyfile does (Verified).**
  - The `tls` block of `*.{$LAB_DOMAIN}` sets `resolvers {$ACME_RESOLVERS:1.1.1.1 1.0.0.1}` (`stack/edge/Caddyfile`).
  - Caddy: `resolvers` "customizes the DNS resolvers used when performing the DNS challenge; these take precedence over
    system resolvers or any default ones". `propagation_timeout` defaults to 2 minutes [S43].
  - Caddy 2.11.9 pins certmagic **v0.25.6** [S44]. There:
    - the zone lookup runs `FindZoneByFQDN` through the configured resolvers;
    - with custom resolvers set, `checkAuthoritativeServers := len(m.Resolvers) == 0` is false, so the propagation
      check polls 1.1.1.1/1.0.0.1 every 2 s instead of the authoritative servers;
    - the default timeout is 2 minutes [S44].
  - The edge README describes the setting as covering "zone lookup and propagation check", which matches.
- **Consistent with UniFi (Assumed: rests on UniFi records being exact names, §1).**
  - Per-name Host (A) records do not cover `_acme-challenge.lab.example.com`, so even through the UDM those lookups
    would be forwarded to the public zone.
  - The `resolvers` line is therefore not strictly needed with this recommendation. It is still right to keep:
    - it protects the Forward Domain variant, which shadows every subdomain [S2];
    - it covers any future "local zone";
    - it keeps issuance independent of the UDM's cache.
- **One UniFi breaker, the TrueNAS server inside a Content Filter or Ad Blocking source** (Assumed; built from
  Verified parts):
  - UniFi redirects DNS traffic from in-scope clients to the gateway [S2][S3]. Caddy's packets to 1.1.1.1:53 leave
    through Docker's NAT with the TrueNAS address and would be answered by the UDM.
  - The zone lookup runs before the TXT record exists, and the first polls may run before Cloudflare serves it. Both get
    negative answers, which dnsmasq caches for the SOA's negative TTL [S22].
  - That TTL is **1800 s** by default for Cloudflare zones on non-Enterprise plans [S42], well beyond the 2-minute
    timeout. Issuance or renewal would then fail with `timed out waiting for record to fully propagate`.
  - **Mitigation:** keep the TrueNAS server out of every Content Filter policy's **Source** (select Devices rather than
    its whole network, or a network without it).
  - **Test from the server:** `sudo docker exec caddy nslookup chat.lab.example.com 1.1.1.1` must report NXDOMAIN. If
    it returns `192.0.2.10`, the UDM is answering queries sent to 1.1.1.1. That the official `caddy` image ships busybox
    `nslookup` is Assumed (Alpine-based).
- **Encrypted DNS** on the UDM does not touch Caddy's path unless the redirect above applies.
- **Cloudflare's resolvers** keep their own negative cache, but the repo default already relies on them, and they serve
  Cloudflare zones directly. No change is proposed.

## Procedure for the guide

UI labels are tagged **[V]** (verified in a cited source) or **[A]** (assumed). The worked example uses the
placeholders above.

1. **Check the versions.** In UniFi Network, open **Settings > Control Plane > Updates** [V, S8]. Note the UniFi OS and
   Network versions. The procedure needs Network **9.4 or later** (Policy Table). On 9.3, use **Settings > Policy Engine
   > DNS > Create DNS Record** instead [V, S1]. On 10.6 and 11.0 the path is the same as 9.4 [A, S18][S10d].
2. **Give TrueNAS a fixed address.** **Client Devices** > select the TrueNAS server > **Settings** > turn on **Fixed IP
   Address** > enter `192.0.2.10` > **Apply Changes** [V, S1].
3. **Check what DNS the networks hand out.** **Settings > Networks** > each network that has clients of the stack >
   **DNS Server**. Its toggle must stay on (the default, the gateway) [V, S1][S7]. If IPv6 is on, that network's IPv6
   DNS setting must also point to the gateway [A, label UNVERIFIED].
4. **Create the records.** **Settings > Policy Table > Create New Policy > DNS** [V, S1]:
   - **Type**: **Host (A)** [V]
   - **Domain Name**: `chat.lab.example.com` [V]
   - **IP Address**: `192.0.2.10` [V]
   - **TTL**: leave empty or automatic [V: optional field; A: the "Auto" wording]
   - Click **Add** [V].

   Repeat for `llm`, `models`, `mcp` and `search`. Do not enter `*.lab.example.com`: wildcards are rejected [A, S15][S16].
   Do not create AAAA records (Details §3.5).

   *Variant:* one Host (A) record `edge.lab.example.com` → `192.0.2.10`, then five records with **Type**
   **Alias (CNAME)** [V, S1], **Alias Domain Name** `chat.lab.example.com` and **Target Domain Name**
   `edge.lab.example.com` [A, labels from S18].
5. **Keep the server out of DNS redirection.** Open **Settings > CyberSecure > Content Filter** [V, S2]. For every
   policy, including those with **Ad Blocking** on [V, S2], check its **Source** [V, S2]. If a policy covers the
   TrueNAS server, choose Devices that exclude it, or a network that doesn't contain it [A]. Leave WiFi
   **DNS Assistance** at its default, without public failover servers [A, S10e][S13].
6. **Verify from every client** with the commands of Details §4.1. A client that resolves through `dig @192.0.2.1` but
   not through its system resolver uses another DNS server. Check `resolvectl status`, `scutil --dns` or
   `Get-DnsClientServerAddress`, flush its cache, or use the hosts-file fallback.
7. **Verify the public zone** with Details §4.2. If the wildcard check returns an address, apply §4.3.
8. **Verify Caddy's path** after `ai-edge` is installed: `sudo docker exec caddy nslookup chat.lab.example.com 1.1.1.1`
   must report NXDOMAIN (Details §5).
9. **Browsers.**
   - Chrome: **Settings > Privacy and security > Security > Use secure DNS** must be off or on the current service
     provider [V, S33].
   - Edge: **Use secure DNS to specify how to lookup the network address for websites** must be on **Use current
     service provider** [A, S34].
   - Firefox: in the DNS over HTTPS settings, keep the default. If a no-fallback mode is in use, add `lab.example.com`
     under **Manage exceptions** [V label, S30; V behaviour, S28].
   - Safari with iCloud Private Relay: no change [V, S35].
   - Then open `https://chat.lab.example.com` in each browser.

## Fit with Claude Code features

DNS is plumbing, not a Claude Code feature. What it affects:

- **Claude Code, OpenCode and scripts** (`llm`, `mcp`) resolve through the OS resolver (Assumed). Browser DoH doesn't
  touch them, so the five A records are enough. Nothing is lost compared with Claude Code against a cloud endpoint.
- **Web GUI** (`chat`): browsers are the only clients exposed to the DoH cases of Details §3.3. With default browser
  settings, nothing is lost.
- **Remote work over SSH:** the names resolve only on the home LAN, the same as the stack's LAN-only design.

## Verified vs assumed

**Verified** (primary sources: Ubiquiti help center and release feed, Ubiquiti update API and OpenAPI, browser source
code, vendor docs, RFCs):

- UDM-Pro SE release firmware UniFi OS 6.0.17 (2026-11-10). Network 11.0.99 on the release channel, 11.0.102 and
  10.6.111 announced 2026-11-13. Network 11 needs UniFi OS 6.0+ [S10a–c][S11][S12].
- DNS record path and field labels for Network 9.3/9.4. The record types. CNAME needs UniFi OS 4.3+/Network 9.3+. Local
  records resolve only for clients that use the gateway [S1].
- API limits: 127-character names, TTL ranges, no per-network scope [S13][S14].
- Forward Domain matches the domain and its subdomains [S2]. Content Filtering redirects DNS to the gateway. Ad Blocking
  redirects clients with custom DNS servers [S2][S3].
- dnsmasq: CNAME target rules, rebind filtering applies only to upstream answers, negative caching [S22][S23].
- Chrome/Edge secure DNS modes, and that picking a provider means secure mode [S31][S32][S33]. Firefox TRR fallback,
  pref defaults, exception matching, policy schema and the canary logic [S24]–[S30].
- Private Relay's local-name handling (2021 source) [S35]. Android DoT modes [S37].
- `Resolve-DnsName` parameters [S38]. `Get-DnsClientDohServerAddress` [S39]. Cloudflare's DoH JSON endpoint [S41].
  Cloudflare's SOA negative TTL default of 1800 s [S42].
- Caddy `resolvers`/`propagation_timeout` [S43]. certmagic v0.25.6 logic and Caddy 2.11.9's pin [S44].
- RFC 4592 wildcard matching [S45]. RFC 8305 Resolution Delay [S46].

**Assumed** (third-party guides, forum reports, inference):

- The Policy Table path is unchanged in Network 10.6 and 11.0 [S18][S10d].
- Wildcards are unsupported [S15][S16][S17]. UniFi's resolver is dnsmasq [S15].
- CNAME field labels and the `NXDOMAIN`-target trick [S18].
- Encrypted DNS leaves local records working [S19]. Encrypted DNS instability reports [S20].
- A network Domain Name default of `localdomain`, and client registration under it [S48].
- Local records keep answering when Content Filtering or Ad Blocking is on (inference from [S1][S2][S3]).
- The UDM answers NODATA for AAAA on an A-only local name.
- The Caddy-breaking redirect scenario of Details §5 (inference from verified parts).
- busybox `nslookup` in the `caddy` image.
- The Edge setting label [S34]. The exact PowerShell error text.
- CLI tools use the OS resolver.
- **UNVERIFIED:** the maximum number of DNS records; the IPv6 DNS setting label; DNS Assistance's behaviour; the API
  key header name.

## Open questions for the owner

1. **Is the TrueNAS server inside any Content Filter or Ad Blocking policy?** If it is, should the guide tell readers to
   narrow that policy's Source (recommended), or keep the policy and accept the Caddy risk of Details §5?
2. **Firefox canary:** should the guide offer the optional `use-application-dns.net` → NXDOMAIN record, which turns off
   Firefox's automatic DoH for the whole home network (§3.4)? It isn't required for the lab names to work.
3. **Public zone wildcard:** if the owner's zone has `*.example.com`, which remedy is acceptable: remove the wildcard,
   or add one marker TXT record at `lab.example.com`? The marker is a small exception to contract §2's "no lab records".
   It carries no address.

## Sources

All read 2026-11-15.

- [S1] Ubiquiti Help Center, "UniFi DNS Records and Local Hostnames" (updated 2026-11-11), https://help.ui.com/hc/en-us/articles/15179064940439 (read via https://help.ui.com/api/v2/help_center/en-us/articles/15179064940439.json)
- [S2] Ubiquiti Help Center, "Content and Domain Filtering in UniFi" (updated 2026-11-15), https://help.ui.com/hc/en-us/articles/12568927589143
- [S3] Ubiquiti Help Center, "UniFi Gateway - Ad Blocking" (updated 2026-11-10), https://help.ui.com/hc/en-us/articles/9794438523799
- [S4] Ubiquiti Help Center, "UniFi - DNS Troubleshooting Guide" (updated 2026-11-11), https://help.ui.com/hc/en-us/articles/17484948645015
- [S5] Ubiquiti Help Center, "Traffic & Policy Management in UniFi" (updated 2026-11-10), https://help.ui.com/hc/en-us/articles/5546542486551
- [S6] Ubiquiti Help Center, "Configuring IPv6 in UniFi" (updated 2026-11-12), https://help.ui.com/hc/en-us/articles/36378535649687
- [S7] Ubiquiti Help Center, "UniFi DHCP Server" (updated 2026-11-08), https://help.ui.com/hc/en-us/articles/360012097513
- [S8] Ubiquiti Help Center, "UniFi Updates" (updated 2026-11-15), https://help.ui.com/hc/en-us/articles/7605005245975
- [S9] Ubiquiti Help Center, "Application Filtering in UniFi" (updated 2026-10-21), https://help.ui.com/hc/en-us/articles/28314415752727; help-center search API for "rebind", "wildcard", "DNS Assistance": https://help.ui.com/api/v2/help_center/articles/search.json
- [S10a] UniFi Network Application 11.0.102 release notes (2026-11-13), https://community.ui.com/releases/UniFi-Network-Application-11-0-102/15b502c5-5ac6-4c96-8692-1f3616e46121 (via the release RSS feed https://community.ui.com/rss/releases/UniFi-Network-Application/e6712595-81bb-4829-8e42-9e2630fabcfe)
- [S10b] UniFi Network Application 10.6.111 (2026-11-13), https://community.ui.com/releases/UniFi-Network-Application-10-6-111/9559b5b4-7939-4f22-8c58-934c7ed624ef
- [S10c] UniFi Network Application 11.0.83 (2026-10-12), https://community.ui.com/releases/UniFi-Network-Application-11-0-83/d6940379-cd5a-4e61-8596-7e22d647a4ea
- [S10d] UniFi Network Application 10.5.67 (2026-07-23), https://community.ui.com/releases/UniFi-Network-Application-10-5-67/375288b9-a4b4-46f1-a19d-5c787d342c2b
- [S10e] UniFi Network Application 10.3.55 (2026-04-16), https://community.ui.com/releases/UniFi-Network-Application-10-3-55/3ed8145b-94a2-44b2-a42e-2d970f135b7b
- [S11] Ubiquiti firmware update API, UDMPROSE release channel, https://fw-update.ui.com/api/firmware-latest?filter=eq~~product~~unifi-dream&filter=eq~~channel~~release&filter=eq~~platform~~UDMPROSE
- [S12] Ubiquiti firmware update API, UniFi Network native package, https://fw-update.ui.com/api/firmware-latest?filter=eq~~product~~unifi-native&filter=eq~~channel~~release
- [S13] UniFi Network API OpenAPI 11.0.97 (DNS Policies, WiFi broadcast schemas), https://developer.ui.com/network/v11.0.97/openapi.json
- [S14] UniFi Network API OpenAPI 10.1.84, https://developer.ui.com/network/v10.1.84/openapi.json; page https://developer.ui.com/network/v10.1.84/creatednspolicy
- [S15] home-operations/external-dns-unifi-webhook README (last commit 2026-11-07), https://github.com/home-operations/external-dns-unifi-webhook
- [S16] external-dns-unifi-webhook issue #58 "UniFi will not handle wildcard cname's" (2024-09-16), https://github.com/home-operations/external-dns-unifi-webhook/issues/58
- [S17] DNSControl, UniFi Network provider, https://docs.dnscontrol.org/provider/unifi
- [S18] HostiFi, "UniFi - How to block iCloud Private Relay in UniFi" (updated 2026-10-09, Network 9.5.21), https://www.hostifi.com/support/unifi-how-to-block-icloud-private-relay-in-unifi
- [S19] svenvg, "How to Set Up Encrypted DNS on UniFi — and Make Every Device Use It" (2026-11-02), https://svenvg.com/posts/how-to-set-up-encrypted-dns-on-unifi-and-make-every-device-use-it/
- [S20] Lawrence Systems Forums, "Unifi Local DNS issues" (2025-10 to 2026-08), https://forums.lawrencesystems.com/t/unifi-local-dns-issues/26079
- [S21] Plex Forum, "Unifi Gateway & Plex Remote Access, DNS Rebinding Protection Whitelist?" (2026-02-27), https://forums.plex.tv/t/unifi-gateway-plex-remote-access-dns-rebinding-protection-whitelist/936735
- [S22] dnsmasq man page (`--cname`, `--host-record`, `--address`, `--stop-dns-rebind`, `--no-negcache`, `--neg-ttl`, `--local-ttl`), https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html
- [S23] dnsmasq CHANGELOG (to 2.93), https://thekelleys.org.uk/dnsmasq/CHANGELOG
- [S24] Firefox `StaticPrefList.yaml` (main @ b578c91cb483, 2026-11-14): `network.trr.mode`, `default_provider_uri`, `strict_native_fallback`, `allow-rfc1918`, `split_horizon_mitigations`, https://raw.githubusercontent.com/mozilla-firefox/firefox/main/modules/libpref/init/StaticPrefList.yaml
- [S25] Firefox `all.js` (`network.trr.builtin-excluded-domains` = `localhost,local`), https://raw.githubusercontent.com/mozilla-firefox/firefox/main/modules/libpref/init/all.js
- [S26] Firefox networking docs, "DNS over HTTPS (Trusted Recursive Resolver)", https://firefox-source-docs.mozilla.org/networking/dns/dns-over-https-trr.html (source https://raw.githubusercontent.com/mozilla-firefox/firefox/main/netwerk/docs/dns/dns-over-https-trr.md)
- [S27] Firefox `DoHHeuristics.sys.mjs` (global canary `use-application-dns.net`), https://raw.githubusercontent.com/mozilla-firefox/firefox/main/toolkit/components/doh/DoHHeuristics.sys.mjs
- [S28] Firefox `TRRService.cpp` (`IsExcludedFromTRR_unlocked`), https://raw.githubusercontent.com/mozilla-firefox/firefox/main/netwerk/dns/TRRService.cpp
- [S29] Firefox enterprise `policies-schema.json` (`DNSOverHTTPS`), https://raw.githubusercontent.com/mozilla-firefox/firefox/main/browser/components/enterprisepolicies/schemas/policies-schema.json
- [S30] Firefox `preferences.ftl` (DoH section labels), https://raw.githubusercontent.com/mozilla-firefox/firefox/main/browser/locales/en-US/browser/preferences/preferences.ftl
- [S31] Chromium policy `DnsOverHttpsMode.yaml`, https://raw.githubusercontent.com/chromium/chromium/main/components/policy/resources/templates/policy_definitions/Miscellaneous/DnsOverHttpsMode.yaml
- [S32] Chromium settings `secure_dns.ts`, https://raw.githubusercontent.com/chromium/chromium/main/chrome/browser/resources/settings/privacy_page/security/secure_dns.ts
- [S33] Google Chrome Help, secure DNS on desktop, https://support.google.com/chrome/answer/10468685?hl=en&co=GENIE.Platform%3DDesktop
- [S34] ElevenForum, "Enable or Disable Secure DNS over HTTPS (DoH) in Microsoft Edge", https://www.elevenforum.com/t/enable-or-disable-secure-dns-over-https-doh-in-microsoft-edge.12470/
- [S35] Apple, "iCloud Private Relay Overview" (December 2021), https://www.apple.com/icloud/docs/iCloud_Private_Relay_Overview_Dec2021.pdf
- [S36] Apple Developer, "Prepare your network or web server for iCloud Private Relay", https://developer.apple.com/support/prepare-your-network-for-icloud-private-relay/
- [S37] Android Developers Blog, "DNS over TLS support in Android P Developer Preview" (2018), https://android-developers.googleblog.com/2018/04/dns-over-tls-support-in-android-p.html
- [S38] Microsoft Learn, `Resolve-DnsName`, https://learn.microsoft.com/en-us/powershell/module/dnsclient/resolve-dnsname
- [S39] Microsoft Learn, `Get-DnsClientDohServerAddress`, https://learn.microsoft.com/en-us/powershell/module/dnsclient/get-dnsclientdohserveraddress
- [S40] Cloudflare 1.1.1.1 docs, Troubleshooting (updated 2026-05-06), https://developers.cloudflare.com/1.1.1.1/troubleshooting/
- [S41] Cloudflare 1.1.1.1 docs, DoH JSON API (updated 2026-05-05), https://developers.cloudflare.com/1.1.1.1/encryption/dns-over-https/make-api-requests/dns-json/
- [S42] Cloudflare DNS docs, DNS record types, SOA defaults (updated 2026-10-15), https://developers.cloudflare.com/dns/manage-dns-records/reference/dns-record-types/
- [S43] Caddy docs, `tls` directive, https://caddyserver.com/docs/caddyfile/directives/tls
- [S44] certmagic v0.25.6 `solvers.go` and `dnsutil.go`, https://github.com/caddyserver/certmagic/blob/v0.25.6/solvers.go, https://github.com/caddyserver/certmagic/blob/v0.25.6/dnsutil.go; Caddy v2.11.9 `go.mod`, https://github.com/caddyserver/caddy/blob/v2.11.9/go.mod
- [S45] RFC 4592, "The Role of Wildcards in the Domain Name System", §2.2.1 and §3.3.2, https://www.rfc-editor.org/rfc/rfc4592.txt
- [S46] RFC 8305, "Happy Eyeballs Version 2", §3, https://www.rfc-editor.org/rfc/rfc8305.txt
- [S47] Chromium policy `DnsOverHttpsExcludedDomains.yaml` (ChromeOS 131+), https://raw.githubusercontent.com/chromium/chromium/main/components/policy/resources/templates/policy_definitions/Network/DnsOverHttpsExcludedDomains.yaml
- [S48] LazyAdmin, "UniFi Local and Server DNS Settings" (updated 2024-09-12), https://lazyadmin.nl/home-network/unifi-local-and-server-dns-settings/
