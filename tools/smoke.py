#!/usr/bin/env python3
"""End-to-end checks of every endpoint of the deployed stack, from the workstation.

  smoke.py [--only CHECK...] [--timeout SECONDS] [--cafile FILE] [--env-file FILE]

Checks, reported in this order (docs/stack-design.md, sections 3 and 5):
  tls         chat., llm., models., mcp. and search.<LAB_DOMAIN>: the TLS handshake verifies the
              certificate and the name; prints the days left before it expires
  models      GET https://llm.<domain>/v1/models lists every client-facing model name of section 5
  chat        POST /v1/chat/completions, local-fast, a few tokens (OpenAI API)
  messages    POST /v1/messages, local-haiku, a few tokens (Anthropic API, as Claude Code uses it)
  embeddings  POST /v1/embeddings, local-embed: one vector
  rerank      POST /v1/rerank, local-rerank: the matching document scores highest
  search      GET https://search.<domain>/search?q=...&format=json: SearXNG answers JSON
  mcp         POST https://mcp.<domain>/servers/<name>/mcp, an MCP initialize request, for the
              hub's searxng, fetch and kb servers (bearer token)

Settings come from the environment, then from --env-file (default
~/.config/local-agent-stack/client.env, read when it exists) for what the environment lacks:
  LAB_DOMAIN       the lab domain, e.g. lab.example.com (required)
  LOCAL_LLM_KEY    a LiteLLM key (models, chat, messages, embeddings, rerank)
  MCP_HUB_TOKEN    the MCP hub's bearer token (mcp)
A check whose key is missing fails and says which variable to set. Keys are never printed.

The checks that make the GPU generate (chat, messages) run one after the other; every other check
runs at the same time as them and as each other. --cafile trusts a private CA (appendix D:
internal CA); otherwise the system's CAs are used.

Standard library only. Exit codes: 0 every check passed, 1 a check failed, 2 usage.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import dataclasses
import datetime
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HOSTS = ("chat", "llm", "models", "mcp", "search")
MODELS = (
    "local-coder",
    "local-fast",
    "local-coder-moe",
    "local-opus",
    "local-sonnet",
    "local-haiku",
    "local-embed",
    "local-rerank",
)
MCP_SERVERS = ("searxng", "fetch", "kb")
MCP_PROTOCOL = "2025-06-18"
CHECKS = ("tls", "models", "chat", "messages", "embeddings", "rerank", "search", "mcp")
GPU_CHECKS = ("chat", "messages")
DEFAULT_ENV_FILE = Path.home() / ".config" / "local-agent-stack" / "client.env"
USER_AGENT = "local-agent-stack-smoke/1"


class CheckFailed(Exception):
    """A check that did not pass: its message is the reason."""


@dataclasses.dataclass
class Result:
    name: str
    ok: bool
    lines: list


@dataclasses.dataclass
class Settings:
    domain: str
    llm_key: str | None
    mcp_token: str | None
    timeout: float
    context: ssl.SSLContext


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Response:
    status: int
    headers: dict
    body: bytes

    def json(self):
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise CheckFailed(f"the answer is not JSON: {self.body[:120]!r}") from error


def http(settings, method, url, payload=None, headers=None):
    """One HTTPS request; any status is returned, a network error raises CheckFailed."""
    if not url.startswith("https://"):
        raise CheckFailed(f"refusing a URL that is not https: {url}")
    data = None
    request_headers = {"User-Agent": USER_AGENT}
    request_headers.update(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=data, method=method, headers=request_headers)  # noqa: S310 - https only, checked above
    try:
        with urllib.request.urlopen(request, timeout=settings.timeout, context=settings.context) as answer:  # noqa: S310
            return Response(answer.status, {k.lower(): v for k, v in answer.headers.items()}, answer.read())
    except urllib.error.HTTPError as error:
        return Response(error.code, {k.lower(): v for k, v in error.headers.items()}, error.read())
    except (urllib.error.URLError, OSError, ssl.SSLError) as error:
        reason = getattr(error, "reason", error)
        raise CheckFailed(f"{method} {url}: {reason}") from error


def expect(response, what, statuses=(200,)):
    if response.status not in statuses:
        text = response.body[:200].decode("utf-8", "replace").replace("\n", " ")
        raise CheckFailed(f"{what}: HTTP {response.status}: {text}")


def url_of(settings, host, path):
    return f"https://{host}.{settings.domain}{path}"


def bearer(token, variable):
    if not token:
        raise CheckFailed(f"{variable} is not set (environment or client.env)")
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Checks: each returns lines to print, or raises CheckFailed
# ---------------------------------------------------------------------------


def certificate_days(settings, hostname, port=443, now=None):
    """Days until the certificate of hostname expires; the handshake verifies chain and name."""
    with socket.create_connection((hostname, port), timeout=settings.timeout) as raw:
        with settings.context.wrap_socket(raw, server_hostname=hostname) as tls:
            certificate = tls.getpeercert()
    expires = ssl.cert_time_to_seconds(certificate["notAfter"])
    now = time.time() if now is None else now
    return int((expires - now) // 86400)


def check_tls(settings):
    lines, failed = [], []
    for host in HOSTS:
        name = f"{host}.{settings.domain}"
        try:
            days = certificate_days(settings, name)
        except (OSError, ssl.SSLError, ValueError, KeyError) as error:
            failed.append(name)
            lines.append(f"{name}: {error}")
            continue
        lines.append(f"{name}: certificate valid, {days} days left")
        if days < 7:
            failed.append(name)
            lines[-1] += " (renewal overdue: Caddy renews 30 days ahead)"
    if failed:
        raise CheckFailed("; ".join(lines))
    return lines


def check_models(settings):
    response = http(
        settings, "GET", url_of(settings, "llm", "/v1/models"), headers=bearer(settings.llm_key, "LOCAL_LLM_KEY")
    )
    expect(response, "GET /v1/models")
    listed = {entry.get("id") for entry in response.json().get("data", []) if isinstance(entry, dict)}
    missing = [name for name in MODELS if name not in listed]
    if missing:
        raise CheckFailed("missing from /v1/models: " + ", ".join(missing))
    return [f"/v1/models lists all {len(MODELS)} names"]


def check_chat(settings):
    started = time.monotonic()
    response = http(
        settings,
        "POST",
        url_of(settings, "llm", "/v1/chat/completions"),
        {
            "model": "local-fast",
            "messages": [{"role": "user", "content": "Reply with the single word OK."}],
            "max_tokens": 16,
            "temperature": 0,
        },
        bearer(settings.llm_key, "LOCAL_LLM_KEY"),
    )
    expect(response, "POST /v1/chat/completions")
    choices = response.json().get("choices") or [{}]
    text = ((choices[0] or {}).get("message") or {}).get("content") or ""
    if not text.strip():
        raise CheckFailed("local-fast answered with no text")
    return [f"local-fast answered {text.strip()[:40]!r} in {time.monotonic() - started:.1f} s"]


def check_messages(settings):
    started = time.monotonic()
    headers = bearer(settings.llm_key, "LOCAL_LLM_KEY")
    headers["anthropic-version"] = "2023-06-01"
    response = http(
        settings,
        "POST",
        url_of(settings, "llm", "/v1/messages"),
        {
            "model": "local-haiku",
            "max_tokens": 16,
            "messages": [{"role": "user", "content": "Reply with the single word OK."}],
        },
        headers,
    )
    expect(response, "POST /v1/messages")
    body = response.json()
    blocks = body.get("content") if isinstance(body, dict) else None
    texts = [block.get("text", "") for block in blocks or [] if isinstance(block, dict) and block.get("type") == "text"]
    if body.get("type") != "message" or not "".join(texts).strip():
        raise CheckFailed(f"not an Anthropic message with text: {str(body)[:160]}")
    return [f"local-haiku answered {''.join(texts).strip()[:40]!r} in {time.monotonic() - started:.1f} s"]


def check_embeddings(settings):
    response = http(
        settings,
        "POST",
        url_of(settings, "llm", "/v1/embeddings"),
        {"model": "local-embed", "input": "local agent stack"},
        bearer(settings.llm_key, "LOCAL_LLM_KEY"),
    )
    expect(response, "POST /v1/embeddings")
    data = response.json().get("data") or [{}]
    vector = (data[0] or {}).get("embedding")
    if not isinstance(vector, list) or not vector or not all(isinstance(x, (int, float)) for x in vector):
        raise CheckFailed("local-embed returned no vector")
    return [f"local-embed returned a {len(vector)}-dimension vector"]


def check_rerank(settings):
    payload = {
        "model": "local-rerank",
        "query": "What is the capital of France?",
        "documents": ["Paris is the capital of France.", "A GPU has many small cores."],
    }
    headers = bearer(settings.llm_key, "LOCAL_LLM_KEY")
    response = http(settings, "POST", url_of(settings, "llm", "/v1/rerank"), payload, headers)
    path = "/v1/rerank"
    if response.status == 404:
        path = "/rerank"
        response = http(settings, "POST", url_of(settings, "llm", path), payload, headers)
    expect(response, f"POST {path}")
    results = response.json().get("results") or []
    scored = [entry for entry in results if isinstance(entry, dict) and "index" in entry]
    if len(scored) != 2:
        raise CheckFailed(f"local-rerank scored {len(scored)} of 2 documents")
    best = max(scored, key=lambda entry: entry.get("relevance_score", float("-inf")))
    if best["index"] != 0:
        raise CheckFailed("local-rerank ranked the unrelated document first")
    return [f"local-rerank ranked the matching document first ({path})"]


def check_search(settings):
    query = urllib.parse.urlencode({"q": "local agent stack", "format": "json"})
    response = http(
        settings, "GET", url_of(settings, "search", f"/search?{query}"), headers={"Accept": "application/json"}
    )
    expect(response, "GET /search?format=json")
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get("results"), list):
        raise CheckFailed("SearXNG answered without a results list (is json in search.formats?)")
    return [f"SearXNG answered JSON with {len(body['results'])} results"]


def parse_mcp_answer(response):
    """The JSON-RPC message of an MCP Streamable HTTP answer: plain JSON, or the first SSE data event."""
    kind = response.headers.get("content-type", "")
    if kind.startswith("text/event-stream"):
        data = []
        for line in response.body.decode("utf-8", "replace").splitlines():
            if line.startswith("data:"):
                data.append(line[5:].lstrip())
            elif not line.strip() and data:
                break
        if not data:
            raise CheckFailed("the event stream carried no data")
        try:
            return json.loads("\n".join(data))
        except ValueError as error:
            raise CheckFailed("the event stream's data is not JSON") from error
    return response.json()


def check_mcp(settings):
    lines, failed = [], []
    headers = bearer(settings.mcp_token, "MCP_HUB_TOKEN")
    headers["Accept"] = "application/json, text/event-stream"
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": MCP_PROTOCOL,
            "capabilities": {},
            "clientInfo": {"name": "local-agent-stack-smoke", "version": "1"},
        },
    }
    for server in MCP_SERVERS:
        url = url_of(settings, "mcp", f"/servers/{server}/mcp")
        try:
            response = http(settings, "POST", url, request, headers)
            expect(response, f"initialize {server}")
            message = parse_mcp_answer(response)
            result = message.get("result") if isinstance(message, dict) else None
            if not isinstance(result, dict) or "protocolVersion" not in result:
                raise CheckFailed(f"{server}: no initialize result: {str(message)[:160]}")
            info = result.get("serverInfo") or {}
            lines.append(
                f"{server}: {info.get('name', '?')} {info.get('version', '')}".rstrip()
                + f", {result['protocolVersion']}"
            )
            session = response.headers.get("mcp-session-id")
            if session:  # end the session politely; its answer does not matter
                with contextlib.suppress(CheckFailed):
                    http(settings, "DELETE", url, headers=dict(headers, **{"Mcp-Session-Id": session}))
        except CheckFailed as error:
            failed.append(server)
            lines.append(str(error))
    if failed:
        raise CheckFailed("; ".join(lines))
    return lines


CHECK_FUNCTIONS = {
    "tls": check_tls,
    "models": check_models,
    "chat": check_chat,
    "messages": check_messages,
    "embeddings": check_embeddings,
    "rerank": check_rerank,
    "search": check_search,
    "mcp": check_mcp,
}


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def run_one(name, settings, functions=CHECK_FUNCTIONS):
    try:
        return Result(name, True, functions[name](settings))
    except CheckFailed as error:
        return Result(name, False, [str(error)])


def run_checks(names, settings, functions=CHECK_FUNCTIONS):
    """Every check at once, except the GPU checks, which run one after the other in one lane."""
    gpu = [name for name in names if name in GPU_CHECKS]
    other = [name for name in names if name not in GPU_CHECKS]
    results = {}

    def gpu_lane():
        return {name: run_one(name, settings, functions) for name in gpu}

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(other) + 1) as pool:
        lane = pool.submit(gpu_lane) if gpu else None
        futures = {name: pool.submit(run_one, name, settings, functions) for name in other}
        for name, future in futures.items():
            results[name] = future.result()
        if lane is not None:
            results.update(lane.result())
    return [results[name] for name in names]


def read_env_file(path):
    values = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def make_settings(args, environ=None):
    environ = os.environ if environ is None else environ
    from_file = read_env_file(args.env_file) if args.env_file else {}

    def get(name):
        return environ.get(name) or from_file.get(name) or None

    domain = get("LAB_DOMAIN")
    if not domain:
        raise ValueError("LAB_DOMAIN is not set (for example: LAB_DOMAIN=lab.example.com)")
    context = ssl.create_default_context(cafile=args.cafile) if args.cafile else ssl.create_default_context()
    return Settings(domain.strip().strip("."), get("LOCAL_LLM_KEY"), get("MCP_HUB_TOKEN"), args.timeout, context)


def main(argv=None, out=None, functions=CHECK_FUNCTIONS, environ=None):
    out = out or sys.stdout
    parser = argparse.ArgumentParser(prog="smoke.py", description="End-to-end checks of the deployed stack.")
    parser.add_argument("--only", nargs="+", choices=CHECKS, metavar="CHECK", help=" ".join(CHECKS))
    parser.add_argument("--timeout", type=float, default=120.0, help="seconds per request (default 120)")
    parser.add_argument("--cafile", help="a CA certificate file to trust (internal CA)")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="KEY=value file read after the environment")
    args = parser.parse_args(argv)
    try:
        settings = make_settings(args, environ)
    except (ValueError, OSError, ssl.SSLError) as error:
        print(f"smoke.py: {error}", file=sys.stderr)
        return 2
    names = [name for name in CHECKS if not args.only or name in args.only]
    started = datetime.datetime.now(datetime.UTC)
    results = run_checks(names, settings, functions)
    failed = 0
    for result in results:
        out.write(f"{'ok' if result.ok else 'FAIL'} {result.name}\n")
        for line in result.lines:
            out.write(f"  {line}\n")
        failed += not result.ok
    elapsed = (datetime.datetime.now(datetime.UTC) - started).total_seconds()
    out.write(f"smoke: {len(results) - failed} passed, {failed} failed, {elapsed:.1f} s ({settings.domain})\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
