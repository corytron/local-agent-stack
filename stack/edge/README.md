# ai-edge: Caddy and the GPU exporter

The TrueNAS app `ai-edge` is the only app that publishes ports (80, 443/tcp, 443/udp). Caddy
gets one wildcard certificate, `*.lab.example.com`, through the ACME DNS-01 challenge and proxies
each lab host name to its container on the `ai-net` network (`docs/stack-design.md` §2, §3).
`gpu-exporter` serves Prometheus metrics for the GPU on `ai-net` only.

| File | What it is |
|---|---|
| `compose.yaml` | services `caddy` and `gpu-exporter`, included by the TrueNAS app YAML |
| `Caddyfile` | the whole proxy config; every deployment value comes from the environment |
| `Dockerfile` | Caddy 2.11.9 plus the DNS provider modules, built by `.github/workflows/caddy-image.yml` |
| `edge.env.example` | every variable, with placeholders; the real file is `/mnt/tank/ai/secrets/edge.env` |

| Host name | Upstream on `ai-net` |
|---|---|
| `chat.lab.example.com` | `open-webui:8080` |
| `llm.lab.example.com` | `litellm:4000` |
| `models.lab.example.com` | `llama-swap:8080` |
| `mcp.lab.example.com` | `mcp-hub:8096` (Host header rewritten to `mcp-hub:8096`) |
| `search.lab.example.com` | `searxng:8080` |

Any other name under the wildcard, and any client outside `EDGE_ALLOWED_CIDRS` (default: the
private address ranges), gets its connection closed.

## Before you install

1. The TrueNAS web UI is off ports 80 and 443 (guide chapter 3), and `ai-net` exists.
2. Local DNS (router or DNS server) has A records for the five names, all pointing at the NAS
   (`192.0.2.10`).
3. Datasets `tank/ai/appdata/caddy/data` and `tank/ai/appdata/caddy/config` exist and are
   writable by UID/GID 568 (the Apps preset grants this). Caddy keeps its ACME account and the
   certificate in `data`; losing it only means a new certificate.
4. A Cloudflare API token for the zone that holds your lab domain (below).
5. The image `ghcr.io/corytron/local-agent-stack-caddy` is public (below).

### Cloudflare API token (the default provider)

`caddy-dns/cloudflare` documents a single scoped **API token** with `Zone.Zone:Read` and
`Zone.DNS:Edit` for the domain Caddy manages. In the Cloudflare dashboard that is a custom token
with the permissions **Zone / Zone / Read** and **Zone / DNS / Edit**, and **Zone Resources**
limited to the one zone that holds `LAB_DOMAIN`. Do not use the Global API Key. Put the token in
`DNS_PROVIDER_TOKEN`; Caddy refuses to start when the value does not have the shape of a
Cloudflare token (checked by the module), so a leftover placeholder fails loudly.

The module finds the zone with a lookup by name (`GET /zones?name=<zone>`), which a token limited
to that zone can answer. The `libdns/cloudflare` README words the single-token case as "All
zones"; the zone-limited token is the narrower choice and matches the `caddy-dns` README.

### Split-horizon DNS and `resolvers`

Your local DNS answers for the lab names with the NAS's LAN address, while the public zone at
Cloudflare does not need to contain them at all. That is split-horizon DNS. Caddy's DNS challenge
first finds the zone that holds `_acme-challenge.lab.example.com`, then waits until the TXT record
it created is visible. If the local resolver serves its own zone for `lab.example.com` (an
Unbound `local-zone`, a dnsmasq `address=/lab.example.com/...`, a Pi-hole or router "local
domain"), those lookups get the local answer, and issuance fails with
`expected 1 zone, got 0` or `timed out waiting for record to fully propagate`. The
`caddy-dns/cloudflare` README gives both errors and the fix, a custom `resolvers` line, and Caddy's
own documentation of the option says it is "often necessary to configure when using split-horizon
DNS".

The Caddyfile therefore sets `resolvers {$ACME_RESOLVERS}` with the default `1.1.1.1 1.0.0.1`
(Cloudflare's public resolvers, the same operator as the authoritative servers). It affects only
certificate issuance and renewal, which need the internet anyway; browsing the lab names still
uses your local DNS. Set `ACME_RESOLVERS` to other public resolvers if you prefer.

### Making the image public (once)

GitHub creates a new container package as **private**, and a package does not inherit the
repository's visibility. After the first run of the **Caddy image** workflow: open the package
`local-agent-stack-caddy` on GitHub > **Package settings** > **Danger Zone** > **Change
visibility** > **Public**. Public GHCR packages can be pulled without logging in, so TrueNAS needs
no registry credentials. Then pin the digest from the run's summary in `compose.yaml`.

Check an image's provenance before pinning it:

```sh
gh attestation verify oci://ghcr.io/corytron/local-agent-stack-caddy:2.11.9 --repo corytron/local-agent-stack
```

## Choosing another DNS provider

The image also contains `route53`, `digitalocean`, `porkbun`, `namecheap`, `duckdns`, `desec`
and `ovh`. Set `DNS_PROVIDER` to one of them and fill the credentials listed in
`edge.env.example`; no file edits are needed.

How it works: Caddy replaces `{$NAME}` placeholders in the Caddyfile before it parses the file
(`replaceEnvVars` in `caddyconfig/caddyfile/parse.go`, v2.11.9), so a placeholder may stand for any
part of a token. The providers take different settings (`cloudflare` one token; `desec` a block
with `token`; `ovh` four values), so a single `dns {$DNS_PROVIDER} <token>` line cannot serve all
of them. Instead the Caddyfile defines one snippet per provider, `(dns-cloudflare)` ...
`(dns-ovh)`, and the `tls` block runs `import dns-{$DNS_PROVIDER:cloudflare}`. An unknown name
stops Caddy with `File to import not found: dns-<name>`.

Credentials are written as `{env.NAME}`, which the DNS module replaces at run time, so they never
appear in the adapted JSON config; `persist_config off` keeps Caddy from writing that config to
`/config` at all.

## Install

TrueNAS: **Apps > Discover Apps > ⋮ > Install via YAML**, name `ai-edge`:

```yaml
include:
  - path: /mnt/tank/ai/stacks/local-agent-stack/stack/edge/compose.yaml
    env_file: /mnt/tank/ai/secrets/edge.env
services: {}
```

For the first attempt, set `ACME_CA=https://acme-staging-v02.api.letsencrypt.org/directory` in
`edge.env` (untrusted certificate, generous rate limits), check that issuance works, then remove
the line and redeploy (`sudo midclt call -j app.redeploy ai-edge`). Caddy stores certificates per
CA, so it then obtains a production certificate.

## Verify

From c4dev:

```sh
# validate the compose file against the example variables
docker compose --env-file stack/edge/edge.env.example -f stack/edge/compose.yaml config -q

# validate the Caddyfile in the image with example values (Cloudflare path)
docker run --rm -v "$PWD/stack/edge/Caddyfile:/etc/caddy/Caddyfile:ro" \
  -e LAB_DOMAIN=lab.example.com -e ACME_EMAIL=admin@example.com -e DNS_PROVIDER=cloudflare \
  -e DNS_PROVIDER_TOKEN="cfut_$(printf 'x%.0s' $(seq 40))" \
  ghcr.io/corytron/local-agent-stack-caddy:2.11.9 caddy validate --config /etc/caddy/Caddyfile
# expected: Valid configuration

# after installing: certificate and routing
curl -sI https://chat.lab.example.com | head -1              # HTTP/2 200 (or a redirect to /auth)
curl -sI http://chat.lab.example.com | grep -i '^location'   # https://chat.lab.example.com/
echo | openssl s_client -connect chat.lab.example.com:443 -servername chat.lab.example.com 2>/dev/null \
  | openssl x509 -noout -subject -issuer -enddate            # subject CN = *.lab.example.com
```

On the NAS (**System > Shell**): `sudo docker logs caddy 2>&1 | grep -i 'certificate obtained'`
shows the issuance, and `sudo docker exec open-webui curl -s http://gpu-exporter:9835/metrics |
grep -m3 nvidia_smi_` shows GPU metrics (any container on `ai-net` with curl will do).

## Hardening in this app

- `caddy` runs as UID/GID 568 with every capability dropped, `no-new-privileges` and a read-only
  root filesystem; it binds 80/443 through `net.ipv4.ip_unprivileged_port_start=0`. Only `/data`,
  `/config` and a tmpfs `/tmp` are writable. The image's binary carries no file capabilities.
- Response headers: HSTS (one year, this host only), `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy: strict-origin-when-cross-origin`; `Server` and
  `X-Powered-By` removed. No Content-Security-Policy, because the web UIs behind it use inline
  scripts and a wrong policy breaks them silently.
- The admin API listens on `localhost:2019` inside the container only (used by the healthcheck).
- `gpu-exporter` (distroless, UID 65534) gets the GPU with the `utility` capability only, reads
  NVML, and is not published. It has no shell or HTTP client, so it has no healthcheck.

## What the other apps must match

- `mcp-hub` (`stack/web`): `--allowed-host mcp-hub:8096` must stay in its list; Caddy sends that
  Host header. Command-line MCP clients normally send no `Origin` header (assumed, not tested), so
  no allowed origin should be needed.
- `open-webui`: `WEBUI_URL=https://chat.lab.example.com` (built from `LAB_DOMAIN`).
- `searxng`: `SEARXNG_BASE_URL=https://search.lab.example.com/` if it is used from a browser.
- The container names in the host table above.
