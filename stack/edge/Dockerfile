# syntax=docker/dockerfile:1
#
# Caddy with the DNS provider modules the edge app needs for the ACME DNS-01 challenge
# (docs/stack-design.md §3). Published by .github/workflows/caddy-image.yml as
# ghcr.io/corytron/local-agent-stack-caddy:<caddy-version>.
#
# One version, two places: the Caddy version is the tag of both FROM lines (keep them equal;
# the workflow refuses to build when they differ and tags the image with it). xcaddy in the
# builder image builds the version in its own CADDY_VERSION, which is that tag.
#
# Module versions: the latest release of each caddy-dns module on 2026-11-15 (proxy.golang.org
# @latest). digitalocean has no tagged release, so it is pinned to a commit (Go pseudo-version).
# Go verifies every module against sum.golang.org while building.

FROM caddy:2.11.9-builder@sha256:345264d8c6b50f44f4a4d507d4e6b6bcae40eef2f210d70f76e717fd8cc31baf AS builder

RUN xcaddy build \
	--output /usr/bin/caddy \
	--with github.com/caddy-dns/cloudflare@v0.2.4 \
	--with github.com/caddy-dns/route53@v1.6.3 \
	--with github.com/caddy-dns/digitalocean@v0.0.0-20250606074528-04bde2867106 \
	--with github.com/caddy-dns/porkbun@v0.3.1 \
	--with github.com/caddy-dns/namecheap@v1.0.0 \
	--with github.com/caddy-dns/duckdns@v0.5.0 \
	--with github.com/caddy-dns/desec@v1.1.0 \
	--with github.com/caddy-dns/ovh@v1.1.0

FROM caddy:2.11.9@sha256:4e2425f6009577e7c651010f16679c28f7d12df3e7b1914f941a7a3370746b3c

COPY --from=builder /usr/bin/caddy /usr/bin/caddy

# The service runs as an unprivileged user (compose sets user 568:568, the TrueNAS "apps"
# account, with every capability dropped) and binds 80/443 through
# net.ipv4.ip_unprivileged_port_start=0. xcaddy sets cap_net_bind_service=+ep on its output
# (XCADDY_SETCAP=1 in the builder) and an effective file capability that the bounding set
# lacks makes exec fail, so remove it. The checks prove the binary runs and has the modules.
RUN set -eux; \
	setcap -r /usr/bin/caddy || true; \
	caddy version; \
	caddy list-modules --skip-standard --versions

LABEL org.opencontainers.image.source="https://github.com/corytron/local-agent-stack" \
	org.opencontainers.image.description="Caddy with caddy-dns modules (cloudflare, route53, digitalocean, porkbun, namecheap, duckdns, desec, ovh) for the local-agent-stack edge app" \
	org.opencontainers.image.licenses="Apache-2.0"
