#!/usr/bin/env python3
"""Print a new .env file for one app, with fresh random values for every secret the stack generates.

  secrets.py gen <app> [--example FILE] [--share FILE] [--ask NAME]... [-o FILE]
  secrets.py names [<app>]

<app> is inference, rag, web, edge (the TrueNAS apps, docs/stack-design.md, section 6) or client
(the workstation's ~/.config/local-agent-stack/client.env: LAB_DOMAIN, LOCAL_LLM_KEY,
MCP_HUB_TOKEN).

gen reads the app's example file, stack/<app>/<app>.env.example (clients/client.env.example for
client), and prints it with every generated secret replaced by a new random value; every other
line, comments and reader-provided placeholders included, is printed as the example has it. A
generated secret the example does not list is added at the end. Without an example file, gen
prints the section 6 variables alone.

Generated values come from the standard library's `secrets` module: 48 letters and digits, no
symbols, because the database passwords go into URLs (DATABASE_URL), the keys into HTTP headers,
and MCP_HUB_TOKEN may hold only [A-Za-z0-9-._~+/]; keys LiteLLM and llama-swap check get the
prefix sk- (b-inference research note). Values created later in a UI (LiteLLM virtual keys, Open
WebUI API keys, the knowledge base ID) stay placeholders, with a comment saying where they come
from. They are new on every run: run gen once per installation, and never again for a value that
must not change (LITELLM_SALT_KEY encrypts what LiteLLM stores; WEBUI_SECRET_KEY encrypts Open
WebUI's tokens).

Values two files share are copied, never generated twice: --share FILE reads an existing .env
and takes the shared values from it (web's PG_PASSWORD and DOCLING_API_KEY from rag.env; client's
MCP_HUB_TOKEN and LAB_DOMAIN from web.env, whose LAB_DOMAIN is the same as edge.env's). Without
--share they stay placeholders, and gen says so on standard error.

--ask NAME prompts on the terminal for a value you provide or copy (not echoed, never on the
command line or in the shell history), for example the workstation's LiteLLM key:
  install -d -m 0700 ~/.config/local-agent-stack
  python3 tools/secrets.py gen client --share ~/.config/local-agent-stack/secrets/web.env \\
      --ask LOCAL_LLM_KEY -o ~/.config/local-agent-stack/client.env
The value may hold letters, digits and . _ ~ + / = : @ % , - only, because the .env files are read
by Compose and client.env by a shell.

-o FILE writes the result to a new file created with mode 0600 (it refuses to replace one); the
default is standard output, for example on the NAS:
  (umask 077; python3 tools/secrets.py gen inference > /mnt/tank/ai/secrets/inference.env)

Standard library only. Exit codes: 0 done, 1 cannot write the output, 2 usage (unknown app,
unreadable --share or --example file, an --ask name the app does not take, an empty or unsafe
value).
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import string
import sys
from pathlib import Path

# This file has the name of the standard library's secrets module, and `python3 tools/secrets.py`
# puts tools/ first on sys.path: take this folder out before importing the real module.
_HERE = Path(__file__).resolve().parent
sys.path[:] = [entry for entry in sys.path if Path(entry or ".").resolve() != _HERE]
import secrets  # noqa: E402 - only after the line above

ROOT = Path(__file__).resolve().parent.parent
ALPHABET = string.ascii_letters + string.digits
LENGTH = 48

# docs/stack-design.md, section 6: per app, each variable's kind:
#   "key"      generated, sk- + 48 letters and digits (LiteLLM and llama-swap keys)
#   "secret"   generated, 48 letters and digits
#   "shared"   copied from another app's file (--share), never generated twice
#   "provided" the reader supplies it (a token from a UI, a domain, an address)
VARIABLES = {
    "inference": {
        "LITELLM_MASTER_KEY": "key",
        "LITELLM_SALT_KEY": "key",
        "LITELLM_DB_PASSWORD": "secret",
        "LLAMA_SWAP_API_KEY": "key",
    },
    "rag": {
        "PG_PASSWORD": "secret",
        "DOCLING_API_KEY": "secret",
        "OIKB_API_KEY": "secret",
        "OIKB_TOKEN": "provided",
        "OIKB_KB_ID": "provided",
    },
    "web": {
        "LAB_DOMAIN": "provided",
        "WEBUI_SECRET_KEY": "secret",
        "PG_PASSWORD": "shared",
        "DOCLING_API_KEY": "shared",
        "LITELLM_WEBUI_KEY": "provided",
        "SEARXNG_SECRET": "secret",
        "MCP_HUB_TOKEN": "secret",
        "KB_READER_TOKEN": "provided",
        "SEARXNG_CONTACT_URL": "provided",
    },
    "edge": {
        "LAB_DOMAIN": "provided",
        "ACME_EMAIL": "provided",
        "DNS_PROVIDER": "provided",
        "DNS_PROVIDER_TOKEN": "provided",
    },
    "client": {
        "LAB_DOMAIN": "shared",
        "LOCAL_LLM_KEY": "provided",
        "MCP_HUB_TOKEN": "shared",
    },
}

# Where a shared value comes from (the file to pass with --share).
SHARED_FROM = {
    ("web", "PG_PASSWORD"): "rag.env",
    ("web", "DOCLING_API_KEY"): "rag.env",
    ("client", "LAB_DOMAIN"): "web.env",
    ("client", "MCP_HUB_TOKEN"): "web.env",
}

# Where a reader-provided value comes from, for the comment written above it when the example
# file has no line for it. Values created later in a UI stay placeholders until then.
PROVIDED = {
    "OIKB_TOKEN": "the API key of Open WebUI's indexer user (Settings > Account > API keys), "
    "created after ai-web's first start",
    "OIKB_KB_ID": "the ID of the knowledge base oikb fills (Open WebUI > Workspace > Knowledge, from its URL)",
    "LITELLM_WEBUI_KEY": "a LiteLLM virtual key for Open WebUI, created with /key/generate once ai-inference runs",
    "KB_READER_TOKEN": "the API key of Open WebUI's kb-reader user, created after ai-web's first start",
    "SEARXNG_CONTACT_URL": "optional: a mailto: address or web page SearXNG sends to Wikipedia and OpenStreetMap",
    "LAB_DOMAIN": "your lab domain, e.g. lab.example.com",
    "ACME_EMAIL": "the ACME account address, e.g. admin@example.com",
    "DNS_PROVIDER": "the DNS provider of the DNS-01 challenge, e.g. cloudflare",
    "DNS_PROVIDER_TOKEN": "an API token of the DNS provider, scoped to the zone",
    "LOCAL_LLM_KEY": "the LiteLLM virtual key created for this workstation in the guide's chapter 4 "
    "(never LITELLM_MASTER_KEY); gen client --ask LOCAL_LLM_KEY prompts for it",
}

ASSIGNMENT_RE = re.compile(r"^(\s*)(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
# A value given with --ask: nothing a shell (client.env) or Compose's .env parser would change.
SAFE_VALUE_RE = re.compile(r"^[A-Za-z0-9._~+/=:@%,-]+$")


class UsageError(Exception):
    """Printed to stderr, exit 2."""


def random_value(kind, choice=secrets.choice):
    value = "".join(choice(ALPHABET) for _ in range(LENGTH))
    return "sk-" + value if kind == "key" else value


def example_path(app):
    if app == "client":
        return ROOT / "clients" / "client.env.example"
    return ROOT / "stack" / app / f"{app}.env.example"


def read_env(path):
    """KEY=value pairs of a .env file (no interpolation; surrounding quotes removed)."""
    values = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise UsageError(f"cannot read {path}: {error}") from error
    for line in text.splitlines():
        match = ASSIGNMENT_RE.match(line)
        if match:
            value = match.group(3).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            values[match.group(2)] = value
    return values


def generate(app, example_text=None, shared=None, choice=secrets.choice, asked=None):
    """The new .env text for the app. `shared` holds values copied from another app's file, `asked`
    values typed at an --ask prompt; both replace the example's placeholders."""
    if app not in VARIABLES:
        raise UsageError(f"unknown app {app!r}: one of {', '.join(VARIABLES)}")
    variables = VARIABLES[app]
    shared = shared or {}
    asked = asked or {}
    generated = any(kind in ("key", "secret") for kind in variables.values())
    out = [
        f"# {app}.env, written by tools/secrets.py gen {app}"
        + (": every generated value below is new." if generated else ".")
    ]
    seen = set()

    def value_for(name, current):
        kind = variables.get(name)
        if name in asked:
            return asked[name]
        if kind in ("key", "secret"):
            return random_value(kind, choice)
        if kind == "shared" and name in shared:
            return shared[name]
        return current

    if example_text is not None:
        for line in example_text.splitlines():
            match = ASSIGNMENT_RE.match(line)
            if match and match.group(2) in variables:
                name = match.group(2)
                seen.add(name)
                out.append(f"{match.group(1)}{name}={value_for(name, match.group(3))}")
            else:
                out.append(line)
    missing = [name for name in variables if name not in seen]
    if missing and example_text is not None:
        out.append("")
        out.append("# Not in the example file (docs/stack-design.md, section 6):")
    for name in missing:
        kind = variables[name]
        if name in asked:
            out.append(f"{name}={asked[name]}")
        elif kind == "shared" and name not in shared:
            source = SHARED_FROM.get((app, name), "the other app's file")
            out.append(f"# The same value as {name} in {source} (or run gen with --share {source}).")
            out.append(f"{name}=replace-with-{name.lower().replace('_', '-')}-from-{source.replace('.', '-')}")
        elif kind == "provided":
            out.append(f"# Set later: {PROVIDED.get(name, 'provided by you')}.")
            out.append(f"{name}=replace-with-{name.lower().replace('_', '-')}")
        else:
            out.append(f"{name}={value_for(name, '')}")
    return "\n".join(out) + "\n"


def write_new_file(path, text):
    """Create path with mode 0600; never replace an existing file."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as error:
        raise OSError(f"{path} exists; secrets.py never replaces a secrets file") from error
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)


def ask_values(app, names, ask):
    """{name: value} for each --ask name, read with ask (getpass: not echoed)."""
    values = {}
    for name in names:
        kind = VARIABLES[app].get(name)
        if kind is None:
            raise UsageError(f"--ask {name}: {app}.env has no such variable ({', '.join(VARIABLES[app])})")
        if kind not in ("provided", "shared"):
            raise UsageError(f"--ask {name}: gen generates this value; --ask takes one you provide or copy")
        try:
            value = ask(f"{name}: ").strip()
        except EOFError:  # no terminal and nothing on standard input
            value = ""
        if not value:
            raise UsageError(f"--ask {name}: no value entered")
        if not SAFE_VALUE_RE.match(value):
            raise UsageError(
                f"--ask {name}: the value may hold only letters, digits and . _ ~ + / = : @ % , - "
                "(a shell reads client.env, Compose the other files)"
            )
        values[name] = value
    return values


def main(argv=None, out=None, ask=getpass.getpass):
    out = out or sys.stdout
    parser = argparse.ArgumentParser(prog="secrets.py", description="Print a new .env file with fresh random secrets.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    gen = commands.add_parser("gen", help="print a new <app>.env")
    gen.add_argument("app", help=", ".join(VARIABLES))
    gen.add_argument("--example", help="the example file to fill in (default: the app's .env.example)")
    gen.add_argument("--share", help="an existing .env to copy shared values from")
    gen.add_argument(
        "--ask",
        action="append",
        default=[],
        metavar="NAME",
        help="prompt for this variable's value without echoing it (repeatable)",
    )
    gen.add_argument("-o", "--output", help="write to this new file (mode 0600) instead of standard output")
    names = commands.add_parser("names", help="list the section 6 variables and their kinds")
    names.add_argument("app", nargs="?")
    args = parser.parse_args(argv)
    try:
        if args.command == "names":
            apps = [args.app] if args.app else list(VARIABLES)
            for app in apps:
                if app not in VARIABLES:
                    raise UsageError(f"unknown app {app!r}: one of {', '.join(VARIABLES)}")
                for name, kind in VARIABLES[app].items():
                    out.write(f"{app} {name} {kind}\n")
            return 0
        if args.app not in VARIABLES:
            raise UsageError(f"unknown app {args.app!r}: one of {', '.join(VARIABLES)}")
        example = Path(args.example) if args.example else example_path(args.app)
        example_text = None
        if args.example or example.is_file():
            try:
                example_text = example.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as error:
                raise UsageError(f"cannot read {example}: {error}") from error
        shared = {}
        if args.share:
            values = read_env(args.share)
            shared = {
                name: values[name]
                for name, kind in VARIABLES[args.app].items()
                if kind == "shared" and values.get(name)
            }
        asked = ask_values(args.app, args.ask, ask)
        text = generate(args.app, example_text, shared, asked=asked)
        for name, kind in VARIABLES[args.app].items():
            if kind == "shared" and name not in shared and name not in asked:
                source = SHARED_FROM.get((args.app, name), "the other app's file")
                print(
                    f"secrets.py: {name} is a placeholder: run gen {args.app} with --share <{source}>", file=sys.stderr
                )
    except UsageError as error:
        print(f"secrets.py: {error}", file=sys.stderr)
        return 2
    if args.output:
        try:
            write_new_file(args.output, text)
        except OSError as error:
            print(f"secrets.py: {error}", file=sys.stderr)
            return 1
        print(f"secrets.py: wrote {args.output} (mode 0600)", file=sys.stderr)
        return 0
    out.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
