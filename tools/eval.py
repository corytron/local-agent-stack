#!/usr/bin/env python3
"""Evaluation suites of the stack, run from the workstation against the gateway, with results tied
to a configuration hash and a regression gate (docs/research/f-project-tooling.md, section 3).

  eval.py run --suite smoke|full [--model local-coder] [--out FILE] [--baseline FILE] [options]
  eval.py compare BASELINE RESULT [--gate evals/gate.toml]
  eval.py verify [--current] [RESULT ...]
  eval.py config-hash [--files]
  eval.py suites

Suites (evals/suites/<name>.jsonl: a header line, then one case per line, each with a stable ID):
  tools    tool calling: single, parallel, no call needed, nested arguments, multi-turn, on the
           OpenAI route (/v1/chat/completions) and the Anthropic route (/v1/messages); the calls
           are matched by name and by a JSON-Schema subset over their arguments
  format   instruction following with deterministic checks: exact JSON, exact text, regex, lines
  coding   small Python functions, checked by hidden unit tests in a sandboxed subprocess
  rag      questions over evals/rag-docs/, with the documents in context; with --rag-source
           openwebui the context is what Open WebUI's knowledge base retrieves instead
The sets of evals/sets.toml pin which cases a run covers: smoke (15 cases) and full (every case).

run sends one request at a time (one GPU: parallel requests only queue and distort latency); the
offline work, the coding tests and verify, runs on every core (--jobs, default JOBS or nproc).
Per case it records pass, fail or error, the latency, the tokens of the usage block and the output
tokens per second (for answers of 32 tokens or more); per suite and overall the pass rate with a
95% Wilson interval and the median speed. The results file holds no key, no domain, no prompt and
no answer: only IDs, outcomes, short reasons and numbers.

config-hash is the sha256 of a sha256sum-style manifest (one "<sha256>  <path>" line per file,
sorted by path) of the files a result depends on: stack/inference/llama-swap/config.yaml,
stack/inference/litellm/config.yaml, stack/inference/compose.yaml (the image builds),
stack/inference/models.sha256 (the model files), evals/sets.toml, evals/suites/*.jsonl and
evals/rag-docs/*.md.

compare fails (exit 1) when a suite's pass rate drops by more than the gate's points or the median
tokens per second drops by more than its percentage (evals/gate.toml). verify checks a results
file offline: its schema, its configuration hash, and that it covers exactly the cases its set
pins, at the suite versions in the repository; --current also requires the working tree's
configuration hash (without RESULT: any results file under evals/results/ with that hash).
suites checks the suite files and runs every case's reference answer through its checks.

Settings come from the environment, then from --env-file (default
~/.config/local-agent-stack/client.env) for what the environment lacks:
  LAB_DOMAIN     the lab domain; the gateway is https://llm.<LAB_DOMAIN> (or --base-url)
  LOCAL_LLM_KEY  a LiteLLM key allowed the models of the run
  EVAL_KB_ID     the Open WebUI knowledge base to query (only with --rag-source openwebui)
  EVAL_KB_KEY    an Open WebUI API key that can read it, such as the kb-reader key (same)

Standard library only (Python 3.11+). Exit codes: 0 success; 1 a failed gate, a failed
verification or an aborted run; 2 usage or unreadable input.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import dataclasses
import datetime
import functools
import hashlib
import http.client
import json
import math
import os
import platform
import re
import shutil
import signal
import ssl
import statistics
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "local-agent-stack/eval-result/1"
HARNESS_VERSION = "1.0"
CONFIG_FILES = (
    "stack/inference/llama-swap/config.yaml",
    "stack/inference/litellm/config.yaml",
    "stack/inference/compose.yaml",
    "stack/inference/models.sha256",
)
CONFIG_GLOBS = ("evals/sets.toml", "evals/suites/*.jsonl", "evals/rag-docs/*.md")
KINDS = ("tools", "format", "coding", "rag")
APIS = ("openai", "anthropic")
STATUSES = ("pass", "fail", "error")
ANTHROPIC_MODEL_FOR = {"local-coder": "local-sonnet", "local-fast": "local-haiku"}
DEFAULT_MAX_TOKENS = {"tools": 4096, "format": 4096, "coding": 8192, "rag": 4096}
SPEED_MIN_TOKENS = 32
DEFAULT_ENV_FILE = Path.home() / ".config" / "local-agent-stack" / "client.env"
USER_AGENT = "local-agent-stack-eval/1"
ANTHROPIC_VERSION = "2023-06-01"
LOOPBACK = ("127.0.0.1", "localhost", "::1")
WARMUP_PROMPT = "Reply with the single word OK."
SECRET_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")
HEX64 = re.compile(r"[0-9a-f]{64}")


class UsageError(Exception):
    """Bad arguments, settings or input files: exit 2."""


class Abort(Exception):
    """The run cannot go on (gateway unreachable, key refused): exit 1, no results written."""


class CaseError(Exception):
    """One case's request failed: the case is recorded as an error."""


def jobs_default():
    try:
        return max(1, int(os.environ.get("JOBS") or 0) or os.cpu_count() or 1)
    except ValueError:
        return os.cpu_count() or 1


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def utc_now():
    return datetime.datetime.now(datetime.UTC)


def short(value, limit=80):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = text.replace("\n", "\\n")
    return text if len(text) <= limit else text[: limit - 3] + "..."


# ---------------------------------------------------------------------------
# The suites and the sets (evals/)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Suite:
    name: str
    kind: str
    version: int
    description: str
    system: str | None
    path: Path
    sha256: str
    cases: list


@dataclasses.dataclass
class Evals:
    root: Path
    order: list
    suites: dict
    sets: dict

    def all_cases(self):
        return [(self.suites[name], case) for name in self.order for case in self.suites[name].cases]

    def case_ids(self, set_name):
        pinned = self.sets[set_name]["cases"]
        if pinned == "all":
            return [case["id"] for _, case in self.all_cases()]
        return list(pinned)

    def select(self, set_name, only=None):
        """The (suite, case) pairs of a set in run order, optionally narrowed to some IDs."""
        wanted = set(self.case_ids(set_name))
        if only:
            unknown = [case_id for case_id in only if case_id not in wanted]
            if unknown:
                raise UsageError(f"not in set {set_name}: {', '.join(unknown)}")
            wanted &= set(only)
        return [(suite, case) for suite, case in self.all_cases() if case["id"] in wanted]


def read_suite(path, name):
    raw = path.read_bytes()
    lines = [(number, line) for number, line in enumerate(raw.decode("utf-8").splitlines(), 1) if line.strip()]
    if not lines:
        raise UsageError(f"{path}: empty suite file")
    records = []
    for number, line in lines:
        try:
            records.append(json.loads(line))
        except ValueError as error:
            raise UsageError(f"{path}:{number}: not JSON: {error}") from error
    header, cases = records[0], records[1:]
    if not isinstance(header, dict) or header.get("suite") != name:
        raise UsageError(f'{path}: the first line must be the header {{"suite": "{name}", ...}}')
    if header.get("kind") not in KINDS:
        raise UsageError(f"{path}: header kind must be one of {', '.join(KINDS)}")
    if not isinstance(header.get("version"), int) or isinstance(header.get("version"), bool):
        raise UsageError(f"{path}: header version must be an integer")
    if not all(isinstance(case, dict) and isinstance(case.get("id"), str) for case in cases):
        raise UsageError(f"{path}: every case must be an object with a string id")
    return Suite(
        name=name,
        kind=header["kind"],
        version=header["version"],
        description=str(header.get("description", "")),
        system=header.get("system"),
        path=path,
        sha256=sha256_bytes(raw),
        cases=cases,
    )


def load_evals(root):
    root = Path(root)
    sets_path = root / "evals" / "sets.toml"
    try:
        data = tomllib.loads(sets_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise UsageError(f"{sets_path} is missing") from error
    except tomllib.TOMLDecodeError as error:
        raise UsageError(f"{sets_path}: {error}") from error
    order = data.get("suites")
    if not isinstance(order, list) or not order or not all(isinstance(name, str) for name in order):
        raise UsageError(f"{sets_path}: suites must be a list of suite names")
    suites = {}
    seen = {}
    for name in order:
        path = root / "evals" / "suites" / f"{name}.jsonl"
        if not path.is_file():
            raise UsageError(f"{path} is missing (listed in evals/sets.toml)")
        suite = read_suite(path, name)
        for case in suite.cases:
            if case["id"] in seen:
                raise UsageError(f"duplicate case id {case['id']} in {seen[case['id']]} and {name}")
            seen[case["id"]] = name
        suites[name] = suite
    sets = {}
    for set_name, entry in (data.get("sets") or {}).items():
        cases = entry.get("cases") if isinstance(entry, dict) else None
        if cases != "all":
            if not isinstance(cases, list) or not cases or not all(isinstance(c, str) for c in cases):
                raise UsageError(f'{sets_path}: sets.{set_name}.cases must be "all" or a list of case ids')
            unknown = [case_id for case_id in cases if case_id not in seen]
            if unknown:
                raise UsageError(f"{sets_path}: sets.{set_name} pins unknown cases: {', '.join(unknown)}")
            if len(set(cases)) != len(cases):
                raise UsageError(f"{sets_path}: sets.{set_name} lists a case twice")
        sets[set_name] = {"description": str(entry.get("description", "")), "cases": cases}
    if not sets:
        raise UsageError(f"{sets_path}: no [sets.<name>] defined")
    return Evals(root=root, order=list(order), suites=suites, sets=sets)


def bundled_documents(root):
    """The RAG documents placed in context: (file name, text), sorted by name."""
    folder = Path(root) / "evals" / "rag-docs"
    return [(path.name, path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.md"))]


# ---------------------------------------------------------------------------
# The configuration hash
# ---------------------------------------------------------------------------


def config_inputs(root):
    root = Path(root)
    paths = set()
    for relative in CONFIG_FILES:
        if not (root / relative).is_file():
            raise UsageError(f"{relative} is missing: the configuration hash needs it")
        paths.add(relative)
    for pattern in CONFIG_GLOBS:
        for path in root.glob(pattern):
            if path.is_file():
                paths.add(path.relative_to(root).as_posix())
    return sorted(paths)


def changed_files(old, new):
    return sorted(path for path in old.keys() | new.keys() if old.get(path) != new.get(path))


def is_sha256(value):
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def config_hash(root):
    """(sha256 of the manifest, {path: sha256}) for the files a result depends on."""
    files = {relative: sha256_bytes((Path(root) / relative).read_bytes()) for relative in config_inputs(root)}
    manifest = "".join(f"{digest}  {relative}\n" for relative, digest in sorted(files.items()))
    return sha256_bytes(manifest.encode("utf-8")), files


# ---------------------------------------------------------------------------
# Matching: a JSON-Schema subset for tool arguments and JSON answers
# ---------------------------------------------------------------------------

SCHEMA_KEYWORDS = {
    "type",
    "const",
    "enum",
    "pattern",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "minItems",
    "maxItems",
    "contains",
    "uniqueItems",
    "anyOf",
    "allOf",
    "oneOf",
    "not",
}
SCHEMA_ANNOTATIONS = {"description", "title", "default", "examples", "$comment"}
JSON_TYPES = ("object", "array", "string", "integer", "number", "boolean", "null")


def json_type(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def is_type(value, name):
    actual = json_type(value)
    if name == "number":
        return actual in ("integer", "number")
    if name == "integer":
        return actual == "integer" or (actual == "number" and float(value).is_integer())
    return actual == name


def json_same(left, right):
    """JSON equality: true is not 1, 1 equals 1.0, objects compare by keys and values."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(json_same(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(json_same(a, b) for a, b in zip(left, right, strict=True))
    return type(left) is type(right) and left == right


def schema_problems(schema, path="$"):
    """What is wrong with a matcher written in a suite file (unknown keywords, bad patterns)."""
    if not isinstance(schema, dict):
        return [f"{path}: a schema must be an object"]
    problems = []
    for key in schema:
        if key not in SCHEMA_KEYWORDS and key not in SCHEMA_ANNOTATIONS:
            problems.append(f"{path}: unsupported keyword {key}")
    types = schema.get("type")
    for name in types if isinstance(types, list) else [types] if types is not None else []:
        if name not in JSON_TYPES:
            problems.append(f"{path}: unknown type {name}")
    if "pattern" in schema:
        try:
            re.compile(schema["pattern"])
        except (re.error, TypeError) as error:
            problems.append(f"{path}: bad pattern: {error}")
    for key in ("properties",):
        for name, sub in (schema.get(key) or {}).items():
            problems += schema_problems(sub, f"{path}.{name}")
    for key in ("items", "contains", "not"):
        if key in schema:
            problems += schema_problems(schema[key], f"{path}/{key}")
    if isinstance(schema.get("additionalProperties"), dict):
        problems += schema_problems(schema["additionalProperties"], f"{path}/additionalProperties")
    for key in ("anyOf", "allOf", "oneOf"):
        if key in schema:
            if not isinstance(schema[key], list) or not schema[key]:
                problems.append(f"{path}: {key} must be a non-empty list")
                continue
            for index, sub in enumerate(schema[key]):
                problems += schema_problems(sub, f"{path}/{key}[{index}]")
    return problems


def match_schema(value, schema, path="$"):
    """Problems of value against schema; an empty list means it matches."""
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(is_type(value, name) for name in types):
            return [f"{path}: expected {'/'.join(types)}, got {json_type(value)} {short(value, 40)}"]
    problems = []
    if "const" in schema and not json_same(value, schema["const"]):
        problems.append(f"{path}: expected {short(schema['const'], 40)}, got {short(value, 40)}")
    if "enum" in schema and not any(json_same(value, option) for option in schema["enum"]):
        problems.append(f"{path}: {short(value, 40)} is not one of {short(schema['enum'], 60)}")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            problems.append(f"{path}: {short(value, 40)} does not match {schema['pattern']}")
        if len(value) < schema.get("minLength", 0):
            problems.append(f"{path}: shorter than {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            problems.append(f"{path}: longer than {schema['maxLength']} characters")
    if json_type(value) in ("integer", "number"):
        if "minimum" in schema and value < schema["minimum"]:
            problems.append(f"{path}: {value} is below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            problems.append(f"{path}: {value} is above {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            problems.append(f"{path}: {value} is not above {schema['exclusiveMinimum']}")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            problems.append(f"{path}: {value} is not below {schema['exclusiveMaximum']}")
    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        for name, sub in properties.items():
            if name in value:
                problems += match_schema(value[name], sub, f"{path}.{name}")
        for name in schema.get("required") or []:
            if name not in value:
                problems.append(f"{path}: {name} is missing")
        extra = [name for name in value if name not in properties]
        additional = schema.get("additionalProperties", True)
        if additional is False and extra:
            problems.append(f"{path}: unexpected {', '.join(sorted(extra))}")
        elif isinstance(additional, dict):
            for name in extra:
                problems += match_schema(value[name], additional, f"{path}.{name}")
    if isinstance(value, list):
        if "items" in schema:
            for index, item in enumerate(value):
                problems += match_schema(item, schema["items"], f"{path}[{index}]")
        if len(value) < schema.get("minItems", 0):
            problems.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            problems.append(f"{path}: more than {schema['maxItems']} items")
        if "contains" in schema and not any(not match_schema(item, schema["contains"]) for item in value):
            problems.append(f"{path}: no item matches {short(schema['contains'], 60)}")
        if schema.get("uniqueItems"):
            for index, item in enumerate(value):
                if any(json_same(item, other) for other in value[:index]):
                    problems.append(f"{path}: duplicate item {short(item, 40)}")
                    break
    if "anyOf" in schema:
        results = [match_schema(value, sub, path) for sub in schema["anyOf"]]
        if all(results):
            problems.append(f"{path}: matches none of {len(results)} alternatives ({results[0][0]})")
    for sub in schema.get("allOf") or []:
        problems += match_schema(value, sub, path)
    if "oneOf" in schema:
        matched = sum(1 for sub in schema["oneOf"] if not match_schema(value, sub, path))
        if matched != 1:
            problems.append(f"{path}: matches {matched} of the oneOf alternatives, not exactly one")
    if "not" in schema and not match_schema(value, schema["not"], path):
        problems.append(f"{path}: matches a schema it must not match")
    return problems


# ---------------------------------------------------------------------------
# Text checks (format, rag, and the text of answers without tool calls)
# ---------------------------------------------------------------------------

CHECKS = ("exact", "contains", "regex", "not_regex", "json_equals", "json_schema", "lines")


def regex_flags(check):
    flags = 0
    for letter in check.get("flags", ""):
        flags |= {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL}[letter]
    return flags


def check_problems(check, where):
    if not isinstance(check, dict) or check.get("check") not in CHECKS:
        return [f"{where}: a check needs check: one of {', '.join(CHECKS)}"]
    kind = check["check"]
    problems = []
    flags = check.get("flags", "")
    if not isinstance(flags, str) or set(flags) - set("ims"):
        return [f"{where}: flags may hold only i, m and s"]
    if kind in ("exact", "contains") and not isinstance(check.get("value"), str):
        problems.append(f"{where}: {kind} needs a string value")
    if kind in ("regex", "not_regex") or (kind == "lines" and "each" in check):
        pattern = check.get("pattern" if kind != "lines" else "each")
        try:
            re.compile(pattern, regex_flags(check))
        except (re.error, TypeError) as error:
            problems.append(f"{where}: bad pattern: {error}")
    if kind == "regex" and check.get("mode", "search") not in ("search", "fullmatch"):
        problems.append(f"{where}: mode must be search or fullmatch")
    if kind == "json_equals" and "value" not in check:
        problems.append(f"{where}: json_equals needs a value")
    if kind == "json_schema":
        problems += schema_problems(check.get("schema"), f"{where}/schema")
    if kind == "lines" and not isinstance(check.get("count"), int):
        problems.append(f"{where}: lines needs an integer count")
    return problems


def normalize(text):
    return text.replace("\r\n", "\n").strip()


def parse_json_text(text):
    try:
        return json.loads(text), None
    except ValueError:
        return None, f"not JSON: {short(text, 60)}"


def check_text(text, check):
    """The problem of text against one check, or None."""
    kind = check["check"]
    text = normalize(text)
    flags = regex_flags(check)
    if kind == "exact":
        left, right = (text.lower(), check["value"].lower()) if check.get("ignore_case") else (text, check["value"])
        return None if left == right else f"expected {short(check['value'], 50)}, got {short(text, 50)}"
    if kind == "contains":
        left, right = (text.lower(), check["value"].lower()) if check.get("ignore_case") else (text, check["value"])
        return None if right in left else f"does not contain {short(check['value'], 50)}"
    if kind == "regex":
        search = re.fullmatch if check.get("mode") == "fullmatch" else re.search
        return None if search(check["pattern"], text, flags) else f"does not match {short(check['pattern'], 60)}"
    if kind == "not_regex":
        return None if not re.search(check["pattern"], text, flags) else f"matches {short(check['pattern'], 60)}"
    if kind in ("json_equals", "json_schema"):
        value, problem = parse_json_text(text)
        if problem:
            return problem
        if kind == "json_equals":
            return None if json_same(value, check["value"]) else f"expected {short(check['value'], 60)}"
        problems = match_schema(value, check["schema"])
        return problems[0] if problems else None
    if kind == "lines":
        lines = [line.strip() for line in text.split("\n")]
        if len(lines) != check["count"]:
            return f"expected {check['count']} lines, got {len(lines)}"
        if "each" in check:
            for line in lines:
                if not re.fullmatch(check["each"], line, flags):
                    return f"line {short(line, 40)} does not match {check['each']}"
        return None
    raise UsageError(f"unknown check {kind}")


def first_problem(text, checks):
    for check in checks:
        problem = check_text(text, check)
        if problem:
            return problem
    return None


# ---------------------------------------------------------------------------
# Case validation (eval.py suites, and before every run)
# ---------------------------------------------------------------------------


def case_problems(suite, case, rag_names):
    case_id = case.get("id")
    where = f"{suite.name}/{case_id}"
    problems = []
    if not re.fullmatch(rf"{re.escape(suite.name)}-[0-9]{{3}}", str(case_id)):
        problems.append(f"{where}: the id must be {suite.name}-NNN")
    if case.get("api", "openai") not in APIS:
        problems.append(f"{where}: api must be openai or anthropic")
    if "max_tokens" in case and (not isinstance(case["max_tokens"], int) or case["max_tokens"] < 1):
        problems.append(f"{where}: max_tokens must be a positive integer")
    if not isinstance(case.get("extra_body", {}), dict):
        problems.append(f"{where}: extra_body must be an object")
    kind = suite.kind
    if kind in ("tools", "format") and not (isinstance(case.get("messages"), list) and case["messages"]):
        problems.append(f"{where}: messages must be a non-empty list")
    if kind == "tools":
        tools = case.get("tools")
        names = set()
        if not isinstance(tools, list) or not tools:
            problems.append(f"{where}: tools must be a non-empty list")
            tools = []
        for tool in tools:
            if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
                problems.append(f"{where}: every tool needs a name")
                continue
            names.add(tool["name"])
            if not isinstance(tool.get("parameters"), dict):
                problems.append(f"{where}: tool {tool['name']} needs parameters (a JSON Schema)")
        expect = case.get("expect")
        if not isinstance(expect, dict) or not isinstance(expect.get("calls"), list):
            problems.append(f"{where}: expect.calls must be a list")
        else:
            for index, call in enumerate(expect["calls"]):
                if not isinstance(call, dict) or call.get("name") not in names:
                    problems.append(f"{where}: expect.calls[{index}] must name one of the case's tools")
                    continue
                problems += schema_problems(call.get("arguments", {}), f"{where}/calls[{index}]")
            for index, check in enumerate(expect.get("text", [])):
                problems += check_problems(check, f"{where}/text[{index}]")
        reference = case.get("reference")
        if not isinstance(reference, dict) or not isinstance(reference.get("calls"), list):
            problems.append(f"{where}: reference.calls must be a list")
    if kind in ("format", "rag"):
        checks = case.get("checks")
        if not isinstance(checks, list) or not checks:
            problems.append(f"{where}: checks must be a non-empty list")
        else:
            for index, check in enumerate(checks):
                problems += check_problems(check, f"{where}/checks[{index}]")
    if kind in ("format", "rag", "coding") and not isinstance(case.get("reference"), str):
        problems.append(f"{where}: reference must be a string")
    if kind == "coding":
        for key in ("prompt", "tests", "entry_point"):
            if not isinstance(case.get(key), str) or not case[key].strip():
                problems.append(f"{where}: {key} must be a non-empty string")
        if not str(case.get("entry_point", "")).isidentifier():
            problems.append(f"{where}: entry_point must be a Python name")
        try:
            compile(str(case.get("tests", "")), f"{case_id}-tests", "exec")
        except SyntaxError as error:
            problems.append(f"{where}: tests do not compile: {error}")
        if "timeout" in case and not isinstance(case["timeout"], (int, float)):
            problems.append(f"{where}: timeout must be a number of seconds")
    if kind == "rag":
        if not isinstance(case.get("question"), str) or not case["question"].strip():
            problems.append(f"{where}: question must be a non-empty string")
        sources = case.get("sources")
        if not isinstance(sources, list):
            problems.append(f"{where}: sources must be a list of file names")
        else:
            for name in sources:
                if name not in rag_names:
                    problems.append(f"{where}: source {name} is not in evals/rag-docs/")
    return problems


def suite_problems(evals):
    rag_names = {name for name, _ in bundled_documents(evals.root)}
    problems = []
    for suite, case in evals.all_cases():
        problems += case_problems(suite, case, rag_names)
    return problems


# ---------------------------------------------------------------------------
# Requests and answers
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Options:
    model: str = "local-coder"
    anthropic_model: str = "local-sonnet"
    temperature: float | None = None
    seed: int | None = None
    max_tokens: int | None = None
    rag_source: str = "bundled"
    test_timeout: float = 10.0
    jobs: int = 1
    kb_k: int = 5


@dataclasses.dataclass
class Call:
    name: str
    arguments: object
    error: str | None = None


@dataclasses.dataclass
class Answer:
    text: str = ""
    calls: list = dataclasses.field(default_factory=list)
    finish: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    server_tps: float | None = None


@dataclasses.dataclass
class Grade:
    ok: bool
    reason: str


def rag_prompt(documents, question):
    parts = ["<documents>"]
    for name, text in documents:
        parts.append(f'<document name="{name}">\n{text.strip()}\n</document>')
    parts += ["</documents>", "", f"Question: {question}"]
    return "\n".join(parts)


def build_request(suite, case, model, options, documents=()):
    """(api, path, body) of one case."""
    api = case.get("api", "openai")
    kind = suite.kind
    system = case.get("system", suite.system)
    if kind == "coding":
        messages = [{"role": "user", "content": case["prompt"]}]
    elif kind == "rag":
        messages = [{"role": "user", "content": rag_prompt(documents, case["question"])}]
    else:
        messages = copy.deepcopy(case["messages"])
    max_tokens = options.max_tokens or case.get("max_tokens") or DEFAULT_MAX_TOKENS[kind]
    tools = case.get("tools") if kind == "tools" else None
    if api == "openai":
        path = "/v1/chat/completions"
        body = {"model": model, "messages": ([{"role": "system", "content": system}] if system else []) + messages}
        body["max_tokens"] = max_tokens
        if tools:
            body["tools"] = [{"type": "function", "function": copy.deepcopy(tool)} for tool in tools]
        if options.seed is not None:
            body["seed"] = options.seed
    else:
        path = "/v1/messages"
        body = {"model": model, "max_tokens": max_tokens, "messages": messages}
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [
                {"name": tool["name"], "description": tool.get("description", ""), "input_schema": tool["parameters"]}
                for tool in tools
            ]
    if options.temperature is not None:
        body["temperature"] = options.temperature
    body.update(copy.deepcopy(case.get("extra_body") or {}))
    return api, path, body


def as_int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def as_float(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def parse_openai(data):
    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise CaseError("the answer has no choices")
    choice = choices[0]
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    content = message.get("content")
    if isinstance(content, list):
        text = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    else:
        text = content if isinstance(content, str) else ""
    calls = []
    for call in message.get("tool_calls") or []:
        function = (call or {}).get("function") or {}
        name = function.get("name") if isinstance(function.get("name"), str) else ""
        raw = function.get("arguments")
        if isinstance(raw, dict):
            calls.append(Call(name, raw))
            continue
        try:
            arguments = json.loads(raw) if raw not in (None, "") else {}
        except (TypeError, ValueError):
            calls.append(Call(name, None, "its arguments are not valid JSON"))
            continue
        if isinstance(arguments, dict):
            calls.append(Call(name, arguments))
        else:
            calls.append(Call(name, None, "its arguments are not a JSON object"))
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    timings = data.get("timings") if isinstance(data.get("timings"), dict) else {}
    return Answer(
        text=text,
        calls=calls,
        finish=choice.get("finish_reason"),
        prompt_tokens=as_int(usage.get("prompt_tokens")),
        completion_tokens=as_int(usage.get("completion_tokens")),
        server_tps=as_float(timings.get("predicted_per_second")),
    )


def parse_anthropic(data):
    if not isinstance(data, dict) or data.get("type") == "error":
        raise CaseError(f"error answer: {short((data or {}).get('error', data), 120)}")
    blocks = [block for block in data.get("content") or [] if isinstance(block, dict)]
    if data.get("type") != "message":
        raise CaseError("the answer is not an Anthropic message")
    text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
    calls = []
    for block in blocks:
        if block.get("type") != "tool_use":
            continue
        arguments = block.get("input")
        if isinstance(arguments, dict):
            calls.append(Call(str(block.get("name", "")), arguments))
        else:
            calls.append(Call(str(block.get("name", "")), None, "its input is not a JSON object"))
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return Answer(
        text=text,
        calls=calls,
        finish=data.get("stop_reason"),
        prompt_tokens=as_int(usage.get("input_tokens")),
        completion_tokens=as_int(usage.get("output_tokens")),
    )


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------


def no_text_reason(answer):
    if answer.finish in ("length", "max_tokens"):
        return f"max_tokens reached before an answer (finish: {answer.finish})"
    return f"no text in the answer (finish: {answer.finish})"


def call_problems(expected, call):
    if call.name != expected["name"]:
        return [f"called {call.name or '(no name)'}"]
    if call.error:
        return [f"{call.name}: {call.error}"]
    return match_schema(call.arguments, expected.get("arguments") or {})


def grade_tools(case, answer):
    expect = case["expect"]
    expected = expect["calls"]
    calls = answer.calls
    names = ", ".join(call.name or "(no name)" for call in calls) or "none"
    if not expected:
        if calls:
            return Grade(False, f"expected no tool call, got {names}")
        if not answer.text.strip():
            return Grade(False, no_text_reason(answer))
        problem = first_problem(answer.text, expect.get("text", []))
        return Grade(not problem, problem or "answered without a tool call")
    if not calls:
        hint = ""
        if "<tool_call>" in answer.text or "<function=" in answer.text:
            hint = "; the text holds a tool call: it was written as text, not parsed"
        return Grade(False, f"no tool call (finish: {answer.finish}){hint}")
    for call in calls:
        if call.error:
            return Grade(False, f"{call.name}: {call.error}")
    if len(calls) < len(expected) or (len(calls) > len(expected) and not expect.get("allow_extra")):
        wanted = ", ".join(call["name"] for call in expected)
        return Grade(False, f"expected {len(expected)} call(s) ({wanted}), got {len(calls)} ({names})")
    table = [[call_problems(want, call) for call in calls] for want in expected]

    def search(index, used):
        if index == len(expected):
            return True
        return any(
            column not in used and not table[index][column] and search(index + 1, used | {column})
            for column in range(len(calls))
        )

    if search(0, frozenset()):
        return Grade(True, f"{len(expected)} call(s) matched")
    for index, want in enumerate(expected):
        if any(not problems for problems in table[index]):
            continue
        same = [problems for problems, call in zip(table[index], calls, strict=True) if call.name == want["name"]]
        if same:
            best = min(same, key=len)
            return Grade(False, f"{want['name']}: {best[0]}")
        return Grade(False, f"no call of {want['name']} (got {names})")
    return Grade(False, "the calls match the expected ones only in overlapping ways")


def grade_text(checks, answer):
    if not answer.text.strip():
        return Grade(False, no_text_reason(answer))
    problem = first_problem(answer.text, checks)
    return Grade(not problem, problem or "every check passed")


FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+.-]*)[^\n]*\n(.*?)```", re.DOTALL)


def extract_code(text, entry_point):
    """The code of an answer: the last fenced block defining entry_point, else the last Python block."""
    blocks = [(language.lower(), body) for language, body in FENCE.findall(text)]
    defining = re.compile(rf"^\s*(async\s+)?def\s+{re.escape(entry_point)}\s*\(", re.MULTILINE)
    with_def = [body for _, body in blocks if defining.search(body)]
    if with_def:
        return with_def[-1]
    python = [body for language, body in blocks if language in ("python", "py", "python3")]
    if python:
        return python[-1]
    if blocks:
        return blocks[-1][1]
    return text


# ---------------------------------------------------------------------------
# The coding sandbox: a subprocess in a temporary directory, with a time limit, resource limits,
# an audit hook that refuses network, process creation and writes outside the directory, and a
# network namespace too where unprivileged user namespaces are allowed
# ---------------------------------------------------------------------------

RUNNER = r"""
import linecache
import os
import sys
import traceback

BLOCKED_PREFIXES = (
    "socket.", "subprocess.", "ctypes.", "os.exec", "os.spawn", "os.posix_spawn", "os.fork",
    "os.forkpty", "os.system", "os.kill", "os.killpg", "os.startfile", "pty.", "webbrowser.",
    "urllib.", "http.client.", "ftplib.", "smtplib.", "telnetlib.", "imaplib.", "poplib.", "nntplib.",
)
WRITES = {
    "os.remove": (0,), "os.rmdir": (0,), "os.mkdir": (0,), "os.chmod": (0,), "os.chown": (0,),
    "os.truncate": (0,), "os.utime": (0,), "os.rename": (0, 1), "os.link": (1,), "os.symlink": (1,),
    "os.setxattr": (0,), "os.removexattr": (0,), "shutil.rmtree": (0,), "shutil.move": (0, 1),
    "shutil.copyfile": (1,), "shutil.copymode": (1,), "shutil.copystat": (1,), "shutil.copytree": (1,),
}
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def limit(cpu_seconds, memory_mb):
    try:
        import resource
    except ImportError:
        return
    for name, value in (("RLIMIT_CPU", cpu_seconds), ("RLIMIT_AS", memory_mb << 20),
                        ("RLIMIT_FSIZE", 16 << 20), ("RLIMIT_CORE", 0)):
        kind = getattr(resource, name, None)
        if kind is not None:
            try:
                resource.setrlimit(kind, (value, value))
            except (ValueError, OSError):
                pass


def main():
    nonce = sys.stdin.readline().strip()
    limit(int(sys.argv[1]), int(sys.argv[2]))
    root = os.path.realpath(os.getcwd())
    with open("solution.py", encoding="utf-8") as handle:
        solution = handle.read()
    with open("tests.py", encoding="utf-8") as handle:
        tests = handle.read()
    os.remove("tests.py")
    for name, text in (("solution.py", solution), ("hidden_tests.py", tests)):
        linecache.cache[name] = (len(text), None, text.splitlines(True), name)
    realpath, fsdecode, sep = os.path.realpath, os.fsdecode, os.sep

    def inside(path):
        if isinstance(path, int):
            return True
        try:
            full = realpath(fsdecode(path))
        except (TypeError, ValueError):
            return False
        return full == root or full.startswith(root + sep)

    def hook(event, args):
        if event.startswith(BLOCKED_PREFIXES):
            raise PermissionError("sandbox: " + event + " is not allowed")
        if event == "open":
            path, mode, flags = args
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and flags & WRITE_FLAGS)
            if writing and path is not None and not inside(path):
                raise PermissionError("sandbox: writing outside the test directory is not allowed")
        elif event in WRITES:
            for index in WRITES[event]:
                if index < len(args) and isinstance(args[index], (str, bytes, os.PathLike)):
                    if not inside(args[index]):
                        raise PermissionError("sandbox: " + event + " outside the test directory")

    sys.addaudithook(hook)
    namespace = {"__name__": "solution", "__builtins__": __builtins__}
    try:
        exec(compile(solution, "solution.py", "exec"), namespace)
        exec(compile(tests, "hidden_tests.py", "exec"), namespace)
    except BaseException:
        traceback.print_exc(limit=-4)
        sys.stderr.flush()
        os._exit(1)
    sys.stdout.write("\nEVAL-OK " + nonce + "\n")
    sys.stdout.flush()
    os._exit(0)


main()
"""


@functools.lru_cache(maxsize=1)
def sandbox_prefix():
    """unshare's prefix for a private network namespace, when this host allows it; else ()."""
    command = ("unshare", "--user", "--map-root-user", "--net", "--")
    if shutil.which("unshare") is None:
        return ()
    try:
        probe = subprocess.run(
            [*command, sys.executable, "-I", "-c", "pass"], capture_output=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    return command if probe.returncode == 0 else ()


def sandbox_kind():
    return "netns+audit-hook" if sandbox_prefix() else "audit-hook"


def tail(path, limit=4096):
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - limit))
            return handle.read().decode("utf-8", "replace")
    except OSError:
        return ""


def failure_reason(stderr, returncode):
    # Skip blank lines and the ^^^/~~~ marker lines of Python 3.11+ tracebacks.
    lines = [line for line in stderr.splitlines() if line.strip(" \t^~")]
    if not lines:
        return f"exit code {returncode}"
    reason = lines[-1].strip()
    if reason in ("AssertionError", "AssertionError: ") and len(lines) >= 2:
        reason = f"AssertionError at: {lines[-2].strip()}"
    return short(reason, 200)


def run_tests(code, tests, timeout=10.0, memory_mb=1024):
    """Run hidden tests against code in a sandboxed subprocess: a Grade."""
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="eval-coding-") as folder:
        work = Path(folder)
        (work / "runner.py").write_text(RUNNER, encoding="utf-8")
        (work / "solution.py").write_text(code, encoding="utf-8")
        (work / "tests.py").write_text(tests, encoding="utf-8")
        nonce = os.urandom(16).hex()  # not the secrets module: tools/secrets.py shadows it
        environment = {"PATH": os.defpath, "LANG": "C.UTF-8", "HOME": folder, "TMPDIR": folder}
        command = [*sandbox_prefix(), sys.executable, "-I", "-B", "runner.py", str(int(timeout) + 1), str(memory_mb)]
        with open(work / "out.txt", "wb") as out, open(work / "err.txt", "wb") as err:
            try:
                process = subprocess.Popen(
                    command,
                    cwd=folder,
                    stdin=subprocess.PIPE,
                    stdout=out,
                    stderr=err,
                    env=environment,
                    start_new_session=True,
                )
            except OSError as error:
                return Grade(False, f"could not start the test process: {error}")
            try:
                process.stdin.write((nonce + "\n").encode())
                process.stdin.close()
            except OSError:
                pass  # the process already ended; its exit code tells why
            try:
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    process.kill()
                process.wait()
                return Grade(False, f"the tests timed out after {timeout:g} s")
        stdout, stderr = tail(work / "out.txt"), tail(work / "err.txt")
    elapsed = time.monotonic() - started
    if returncode == 0 and stdout.rstrip().endswith(f"EVAL-OK {nonce}"):
        return Grade(True, f"tests passed in {elapsed:.1f} s")
    return Grade(False, f"tests failed: {failure_reason(stderr, returncode)}")


def grade_coding_reference(case, timeout):
    """The reference must pass the hidden tests and a do-nothing stub must fail them."""
    fenced = f"```python\n{case['reference']}```"
    grade = run_tests(extract_code(fenced, case["entry_point"]), case["tests"], timeout)
    if not grade.ok:
        return Grade(False, f"the reference fails its tests: {grade.reason}")
    stub = f"def {case['entry_point']}(*args, **kwargs):\n    return None\n"
    if run_tests(stub, case["tests"], timeout).ok:
        return Grade(False, "a stub that returns None passes the tests: they check nothing")
    return Grade(True, "reference passes, stub fails")


def reference_answer(suite, case):
    reference = case["reference"]
    if suite.kind == "tools":
        calls = [Call(call["name"], call.get("arguments", {})) for call in reference["calls"]]
        return Answer(text=reference.get("text", ""), calls=calls, finish="tool_calls" if calls else "stop")
    if suite.kind == "coding":
        return Answer(text=f"```python\n{reference}```", finish="stop")
    return Answer(text=reference, finish="stop")


def grade_answer(suite, case, answer):
    """Grade a non-coding answer (coding answers are graded by run_tests)."""
    if suite.kind == "tools":
        return grade_tools(case, answer)
    return grade_text(case["checks"], answer)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Settings:
    base_url: str
    key: str
    timeout: float
    context: ssl.SSLContext
    domain: str | None = None
    webui_url: str | None = None
    kb_id: str | None = None
    kb_key: str | None = None
    kb_k: int = 5

    def redact(self, text):
        text = str(text)
        for secret in (self.key, self.kb_key):
            if secret:
                text = text.replace(secret, "<key>")
        if self.domain:
            text = text.replace(self.domain, "<LAB_DOMAIN>")
        return SECRET_PATTERN.sub("sk-<redacted>", text)


def checked_url(url, what):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return url.rstrip("/")
    if parts.scheme == "http" and parts.hostname in LOOPBACK:
        return url.rstrip("/")
    raise UsageError(f"{what}: refusing {url}: https only (http only for a test server on the loopback address)")


def post_json(settings, url, payload, headers):
    """POST JSON; returns (status, parsed body or None, a short text of the body)."""
    data = json.dumps(payload).encode("utf-8")
    request_headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json", **headers}
    request = urllib.request.Request(url, data=data, method="POST", headers=request_headers)  # noqa: S310 - checked_url
    try:
        with urllib.request.urlopen(request, timeout=settings.timeout, context=settings.context) as answer:  # noqa: S310
            status, raw = answer.status, answer.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    except TimeoutError as error:
        raise CaseError(f"no answer within {settings.timeout:g} s") from error
    except urllib.error.URLError as error:
        if isinstance(error.reason, TimeoutError):
            raise CaseError(f"no answer within {settings.timeout:g} s") from error
        raise Abort(f"cannot reach {urllib.parse.urlsplit(url).hostname}: {error.reason}") from error
    except http.client.HTTPException as error:
        raise CaseError(f"broken answer: {error!r}") from error
    except OSError as error:
        raise Abort(f"cannot reach {urllib.parse.urlsplit(url).hostname}: {error}") from error
    snippet = raw[:240].decode("utf-8", "replace").replace("\n", " ")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        parsed = None
    return status, parsed, snippet


def call_model(settings, api, path, body):
    headers = {"Authorization": f"Bearer {settings.key}"}
    if api == "anthropic":
        headers["anthropic-version"] = ANTHROPIC_VERSION
    status, data, snippet = post_json(settings, settings.base_url + path, body, headers)
    if status in (401, 403):
        raise Abort(f"HTTP {status} from {path} for {body.get('model')}: check LOCAL_LLM_KEY and the models it allows")
    if status != 200:
        raise CaseError(f"HTTP {status}: {snippet}")
    if not isinstance(data, dict):
        raise CaseError(f"the answer is not a JSON object: {snippet[:80]}")
    return data


def retrieve(settings, case):
    """Passages from Open WebUI's knowledge base for a RAG question: (documents, retrieval hit)."""
    body = {"collection_names": [settings.kb_id], "query": case["question"], "k": settings.kb_k}
    headers = {"Authorization": f"Bearer {settings.kb_key}"}
    url = settings.webui_url + "/api/v1/retrieval/query/collection"
    status, data, snippet = post_json(settings, url, body, headers)
    if status in (401, 403):
        raise Abort(f"HTTP {status} from Open WebUI: check EVAL_KB_KEY and its access to EVAL_KB_ID")
    if status != 200 or not isinstance(data, dict):
        raise CaseError(f"Open WebUI retrieval: HTTP {status}: {snippet[:120]}")
    documents = parse_retrieval(data)
    expected = case.get("sources") or []
    hit = None
    if expected:
        hit = any(source in name for source in expected for name, _ in documents)
    return documents, hit


def parse_retrieval(data):
    """(source name, passage) pairs from a retrieval answer: lists of lists, Chroma style."""
    documents = data.get("documents") or []
    metadatas = data.get("metadatas") or []
    texts = documents[0] if documents and isinstance(documents[0], list) else documents
    metas = metadatas[0] if metadatas and isinstance(metadatas[0], list) else metadatas
    passages = []
    for index, text in enumerate(texts):
        meta = metas[index] if index < len(metas) and isinstance(metas[index], dict) else {}
        name = next(
            (str(meta[key]) for key in ("name", "source", "file_name", "filename", "title") if meta.get(key)),
            f"passage-{index + 1}",
        )
        passages.append((Path(name).name, str(text)))
    return passages


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


def wilson(passed, total, z=1.959964):
    if not total:
        return None
    share = passed / total
    denominator = 1 + z * z / total
    centre = (share + z * z / (2 * total)) / denominator
    half = z * math.sqrt(share * (1 - share) / total + z * z / (4 * total * total)) / denominator
    return [round(100 * max(0.0, centre - half), 1), round(100 * min(1.0, centre + half), 1)]


def median_or_none(values, digits=2):
    values = [value for value in values if value is not None]
    return round(statistics.median(values), digits) if values else None


def summarize(records):
    total = len(records)
    passed = sum(1 for record in records if record["status"] == "pass")
    errors = sum(1 for record in records if record["status"] == "error")
    return {
        "cases": total,
        "passed": passed,
        "failed": total - passed - errors,
        "errors": errors,
        "pass_rate": round(100 * passed / total, 2) if total else None,
        "pass_rate_ci95": wilson(passed, total),
        "median_tokens_per_s": median_or_none([record.get("tokens_per_s") for record in records]),
        "median_latency_s": median_or_none([record.get("latency_s") for record in records], 3),
        "prompt_tokens": sum(record.get("prompt_tokens") or 0 for record in records),
        "completion_tokens": sum(record.get("completion_tokens") or 0 for record in records),
    }


def build_result(evals, set_name, partial, options, records, started, finished, config):
    by_suite = {}
    for record in records:
        by_suite.setdefault(record["suite"], []).append(record)
    suites = {}
    for name in evals.order:
        if name in by_suite:
            suite = evals.suites[name]
            suites[name] = {"version": suite.version, "sha256": suite.sha256, **summarize(by_suite[name])}
            if suite.kind == "rag":
                suites[name]["source"] = options.rag_source
                hits = [record["retrieval_hit"] for record in by_suite[name] if record.get("retrieval_hit") is not None]
                if hits:
                    suites[name]["retrieval_hit_rate"] = round(100 * sum(hits) / len(hits), 2)
    return {
        "schema": SCHEMA,
        "harness": {"tool": "tools/eval.py", "version": HARNESS_VERSION, "python": platform.python_version()},
        "created": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_s": round((finished - started).total_seconds(), 1),
        "set": set_name,
        "partial": partial,
        "model": options.model,
        "anthropic_model": options.anthropic_model,
        "sampling": {"temperature": options.temperature, "seed": options.seed, "max_tokens": options.max_tokens},
        "rag_source": options.rag_source,
        "sandbox": sandbox_kind(),
        "speed_min_tokens": SPEED_MIN_TOKENS,
        "config": {"sha256": config[0], "files": config[1]},
        "suites": suites,
        "overall": summarize(records),
        "cases": records,
    }


def load_result(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise UsageError(f"{path}: no such file") from error
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise UsageError(f"{path}: not a JSON results file: {error}") from error
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise UsageError(f"{path}: not a {SCHEMA} results file")
    if not isinstance(data.get("cases"), list):
        raise UsageError(f"{path}: no cases list")
    return data


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def warm_up(settings, api, model, out):
    """One tiny request per route, so a model swap does not land on the first measured case."""
    body = {"model": model, "max_tokens": 16, "messages": [{"role": "user", "content": WARMUP_PROMPT}]}
    path = "/v1/chat/completions" if api == "openai" else "/v1/messages"
    started = time.monotonic()
    try:
        call_model(settings, api, path, body)
    except CaseError as error:
        raise Abort(f"warm-up of {model} ({api}) failed: {settings.redact(error)}") from error
    out.write(f"warm-up: {model} ({api}) answered in {time.monotonic() - started:.1f} s\n")


def new_record(suite, case):
    return {
        "id": case["id"],
        "suite": suite.name,
        "api": case.get("api", "openai"),
        "status": "error",
        "reason": "",
        "latency_s": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "tokens_per_s": None,
        "finish": None,
    }


def run_case(settings, suite, case, options, documents, pool, save_dir=None):
    """Send one case and grade it; coding cases return a future for their tests."""
    record = new_record(suite, case)
    api = record["api"]
    model = options.model if api == "openai" else options.anthropic_model
    context = documents
    if suite.kind == "rag" and options.rag_source == "openwebui":
        try:
            context, hit = retrieve(settings, case)
        except CaseError as error:
            record["reason"] = settings.redact(f"retrieval: {error}")
            return record, None
        record["retrieval_hit"] = hit
    api, path, body = build_request(suite, case, model, options, context)
    started = time.monotonic()
    try:
        data = call_model(settings, api, path, body)
        latency = time.monotonic() - started
        answer = parse_openai(data) if api == "openai" else parse_anthropic(data)
    except CaseError as error:
        record["latency_s"] = round(time.monotonic() - started, 3)
        record["reason"] = settings.redact(error)
        return record, None
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)
        (save_dir / f"{case['id']}.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    record["latency_s"] = round(latency, 3)
    record["prompt_tokens"] = answer.prompt_tokens
    record["completion_tokens"] = answer.completion_tokens
    if answer.completion_tokens and answer.completion_tokens >= SPEED_MIN_TOKENS and latency > 0:
        record["tokens_per_s"] = round(answer.completion_tokens / latency, 2)
    if answer.server_tps is not None:
        record["server_tokens_per_s"] = round(answer.server_tps, 2)
    record["finish"] = answer.finish if isinstance(answer.finish, str) else None
    if suite.kind == "coding":
        if not answer.text.strip():
            record["status"], record["reason"] = "fail", no_text_reason(answer)
            return record, None
        code = extract_code(answer.text, case["entry_point"])
        timeout = float(case.get("timeout", options.test_timeout))
        record["status"], record["reason"] = "testing", "hidden tests queued"
        return record, pool.submit(run_tests, code, case["tests"], timeout)
    grade = grade_answer(suite, case, answer)
    record["status"] = "pass" if grade.ok else "fail"
    record["reason"] = settings.redact(grade.reason)
    return record, None


def progress_line(index, total, record):
    tokens = record.get("completion_tokens")
    speed = record.get("tokens_per_s")
    latency = record.get("latency_s")
    return (
        f"[{index:>{len(str(total))}}/{total}] {record['id']:<12} {record['status']:<7}"
        f" {f'{latency:.1f} s' if latency is not None else '-':>8}"
        f" {f'{tokens} tok' if tokens is not None else '-':>9}"
        f" {f'{speed:.1f} tok/s' if speed is not None else '':>12}"
        f"  {record['reason']}\n"
    )


def run_cases(settings, cases, options, documents, out, save_dir=None):
    records = []
    pending = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, options.jobs)) as pool:
        for index, (suite, case) in enumerate(cases, 1):
            record, future = run_case(settings, suite, case, options, documents, pool, save_dir)
            records.append(record)
            if future is not None:
                pending.append((record, future))
            out.write(progress_line(index, len(cases), record))
            out.flush()
        for record, future in pending:
            try:
                grade = future.result()
            except OSError as error:
                grade = Grade(False, f"could not run the tests: {error}")
            record["status"] = "pass" if grade.ok else "fail"
            record["reason"] = settings.redact(grade.reason)
            out.write(f"tests {record['id']:<12} {record['status']:<7} {record['reason']}\n")
    return records


def summary_table(result):
    lines = [f"{'suite':<10}{'cases':>6}{'pass':>6}{'rate':>9}{'95% CI':>15}{'tok/s':>9}{'latency':>10}"]

    def row(name, summary):
        ci = summary.get("pass_rate_ci95")
        rate = summary.get("pass_rate")
        speed = summary.get("median_tokens_per_s")
        latency = summary.get("median_latency_s")
        return (
            f"{name:<10}{summary['cases']:>6}{summary['passed']:>6}"
            f"{f'{rate:.1f}%' if rate is not None else '-':>9}"
            f"{f'{ci[0]:.0f}-{ci[1]:.0f}%' if ci else '-':>15}"
            f"{f'{speed:.1f}' if speed is not None else '-':>9}"
            f"{f'{latency:.1f} s' if latency is not None else '-':>10}"
        )

    for name, summary in result["suites"].items():
        lines.append(row(name, summary))
    lines.append(row("overall", result["overall"]))
    return "\n".join(lines) + "\n"


def default_out(root, result):
    stamp = result["created"].replace("-", "").replace(":", "")
    name = f"{stamp}-{result['model']}-{result['set']}{'-partial' if result['partial'] else ''}.json"
    folder = Path(root) / ("build/evals" if result["partial"] else "evals/results")
    return folder / name


def write_result(path, result):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


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
        return (environ.get(name) or from_file.get(name) or "").strip() or None

    domain = get("LAB_DOMAIN")
    domain = domain.strip(".") if domain else None
    if args.base_url:
        base_url = checked_url(args.base_url, "--base-url")
    elif domain:
        base_url = f"https://llm.{domain}"
    else:
        raise UsageError("LAB_DOMAIN is not set (for example: LAB_DOMAIN=lab.example.com), and no --base-url")
    key = get("LOCAL_LLM_KEY")
    if not key:
        raise UsageError("LOCAL_LLM_KEY is not set (environment or client.env)")
    context = ssl.create_default_context(cafile=args.cafile) if args.cafile else ssl.create_default_context()
    settings = Settings(base_url=base_url, key=key, timeout=args.timeout, context=context, domain=domain)
    if args.rag_source == "openwebui":
        if args.webui_url:
            settings.webui_url = checked_url(args.webui_url, "--webui-url")
        elif domain:
            settings.webui_url = f"https://chat.{domain}"
        else:
            raise UsageError("--rag-source openwebui needs LAB_DOMAIN or --webui-url")
        settings.kb_id, settings.kb_key = get("EVAL_KB_ID"), get("EVAL_KB_KEY")
        if not settings.kb_id or not settings.kb_key:
            raise UsageError("--rag-source openwebui needs EVAL_KB_ID and EVAL_KB_KEY (environment or client.env)")
    return settings


def command_run(args, out):
    evals = load_evals(args.root)
    if args.suite not in evals.sets:
        raise UsageError(f"no set {args.suite} in evals/sets.toml (sets: {', '.join(evals.sets)})")
    problems = suite_problems(evals)
    if problems:
        raise UsageError("the suite files have problems (tools/eval.py suites):\n  " + "\n  ".join(problems))
    cases = evals.select(args.suite, args.case)
    settings = make_settings(args)
    options = Options(
        model=args.model,
        anthropic_model=args.anthropic_model or ANTHROPIC_MODEL_FOR.get(args.model, args.model),
        temperature=args.temperature,
        seed=args.seed,
        max_tokens=args.max_tokens,
        rag_source=args.rag_source,
        test_timeout=args.test_timeout,
        jobs=args.jobs,
        kb_k=args.kb_k,
    )
    settings.kb_k = args.kb_k
    config = config_hash(args.root)
    apis = [api for api in APIS if any(case.get("api", "openai") == api for _, case in cases)]
    out.write(
        f"eval: set {args.suite}, {len(cases)} cases, model {options.model}"
        f"{f' (Anthropic route: {options.anthropic_model})' if 'anthropic' in apis else ''},"
        f" config {config[0][:12]}, coding sandbox {sandbox_kind()}\n"
    )
    started = utc_now()
    try:
        if not args.no_warmup:
            for api in apis:
                warm_up(settings, api, options.model if api == "openai" else options.anthropic_model, out)
        documents = bundled_documents(args.root)
        records = run_cases(settings, cases, options, documents, out, args.save_responses)
    except Abort as error:
        out.write(f"eval: run aborted, no results written: {settings.redact(error)}\n")
        return 1
    result = build_result(evals, args.suite, bool(args.case), options, records, started, utc_now(), config)
    path = Path(args.out) if args.out else default_out(args.root, result)
    write_result(path, result)
    out.write(summary_table(result))
    out.write(f"results: {path}\n")
    if args.baseline:
        out.write("\n")
        return compare_files(args.baseline, path, args.gate, out)
    return 0


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------


def load_gate(path):
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise UsageError(f"{path}: no such gate file") from error
    except tomllib.TOMLDecodeError as error:
        raise UsageError(f"{path}: {error}") from error
    gate = data.get("gate") or {}
    try:
        return {
            "points": float(gate.get("pass_rate_drop_points", 5.0)),
            "speed": float(gate.get("tokens_per_second_drop_percent", 15.0)),
            "min_speed_cases": int(gate.get("min_cases_for_speed", 5)),
            "suites": {
                name: float(entry.get("pass_rate_drop_points", gate.get("pass_rate_drop_points", 5.0)))
                for name, entry in (gate.get("suites") or {}).items()
            },
        }
    except (TypeError, ValueError, AttributeError) as error:
        raise UsageError(f"{path}: bad gate value: {error}") from error


def compare_results(baseline, result, gate):
    """(lines, failed rule count) of the gate between two results."""
    lines, failures = [], 0
    for key, label in (("model", "model"), ("anthropic_model", "Anthropic-route model"), ("sampling", "sampling")):
        if baseline.get(key) != result.get(key):
            lines.append(f"note: {label} differs: {short(baseline.get(key))} -> {short(result.get(key))}")
    base_config = (baseline.get("config") or {}).get("sha256")
    new_config = (result.get("config") or {}).get("sha256")
    if base_config == new_config:
        lines.append(f"config: same ({str(new_config)[:12]})")
    else:
        old_files = (baseline.get("config") or {}).get("files") or {}
        new_files = (result.get("config") or {}).get("files") or {}
        changed = changed_files(old_files, new_files)
        lines.append(f"config: {str(base_config)[:12]} -> {str(new_config)[:12]}; changed: {', '.join(changed) or '?'}")
    base_cases = {case.get("id"): case for case in baseline["cases"] if isinstance(case, dict)}
    new_cases = {case.get("id"): case for case in result["cases"] if isinstance(case, dict)}
    common = [case_id for case_id in new_cases if case_id in base_cases]
    if not common:
        return lines + ["no case in common: nothing to compare"], 1
    lines.append(f"{'suite':<10}{'baseline':>16}{'result':>16}{'change':>11}{'limit':>9}  verdict")
    suites = []
    for case_id in common:
        suite = new_cases[case_id].get("suite")
        if suite not in suites:
            suites.append(suite)
    for suite in suites:
        ids = [case_id for case_id in common if new_cases[case_id].get("suite") == suite]
        base_suite = (baseline.get("suites") or {}).get(suite) or {}
        new_suite = (result.get("suites") or {}).get(suite) or {}
        if base_suite.get("version") != new_suite.get("version"):
            lines.append(f"note: {suite} suite version {base_suite.get('version')} -> {new_suite.get('version')}")
        if base_suite.get("source") != new_suite.get("source"):
            lines.append(f"{suite:<10} skipped: context source {base_suite.get('source')} vs {new_suite.get('source')}")
            continue
        old_pass = sum(1 for case_id in ids if base_cases[case_id].get("status") == "pass")
        new_pass = sum(1 for case_id in ids if new_cases[case_id].get("status") == "pass")
        old_rate, new_rate = 100 * old_pass / len(ids), 100 * new_pass / len(ids)
        limit = gate["suites"].get(suite, gate["points"])
        drop = old_rate - new_rate
        verdict = "FAIL" if drop > limit + 1e-9 else "ok"
        failures += verdict == "FAIL"
        lines.append(
            f"{suite:<10}{f'{old_pass}/{len(ids)} {old_rate:5.1f}%':>16}{f'{new_pass}/{len(ids)} {new_rate:5.1f}%':>16}"
            f"{f'{new_rate - old_rate:+.1f} pt':>11}{f'{limit:g} pt':>9}  {verdict}"
        )
    pairs = [
        (base_cases[case_id].get("tokens_per_s"), new_cases[case_id].get("tokens_per_s"))
        for case_id in common
        if isinstance(base_cases[case_id].get("tokens_per_s"), (int, float))
        and isinstance(new_cases[case_id].get("tokens_per_s"), (int, float))
    ]
    if len(pairs) < gate["min_speed_cases"]:
        lines.append(f"tok/s     skipped: {len(pairs)} cases with a speed in both runs, need {gate['min_speed_cases']}")
    else:
        old_speed = statistics.median(pair[0] for pair in pairs)
        new_speed = statistics.median(pair[1] for pair in pairs)
        change = 100 * (new_speed - old_speed) / old_speed if old_speed else 0.0
        verdict = "FAIL" if -change > gate["speed"] + 1e-9 else "ok"
        failures += verdict == "FAIL"
        limit = f"{gate['speed']:g}%"
        lines.append(
            f"{'tok/s':<10}{f'{old_speed:.1f}':>16}{f'{new_speed:.1f}':>16}{f'{change:+.1f}%':>11}{limit:>9}  {verdict}"
        )
    passed_before = {case_id for case_id in common if base_cases[case_id].get("status") == "pass"}
    passed_now = {case_id for case_id in common if new_cases[case_id].get("status") == "pass"}
    worse = [case_id for case_id in common if case_id in passed_before and case_id not in passed_now]
    better = [case_id for case_id in common if case_id in passed_now and case_id not in passed_before]
    if worse:
        lines.append("newly failing: " + ", ".join(worse))
        for case_id in worse:
            lines.append(f"  {case_id}: {new_cases[case_id].get('status')}: {new_cases[case_id].get('reason', '')}")
    if better:
        lines.append("newly passing: " + ", ".join(better))
    only_base = [case_id for case_id in base_cases if case_id not in new_cases]
    only_new = [case_id for case_id in new_cases if case_id not in base_cases]
    if only_base or only_new:
        lines.append(f"not compared: {len(only_base)} cases only in the baseline, {len(only_new)} only in the result")
    return lines, failures


def compare_files(baseline_path, result_path, gate_path, out):
    baseline = load_result(baseline_path)
    result = load_result(result_path)
    gate = load_gate(gate_path)
    out.write(
        f"compare: baseline {baseline.get('model')} {baseline.get('set')} {baseline.get('created')}"
        f" -> result {result.get('model')} {result.get('set')} {result.get('created')}\n"
    )
    lines, failures = compare_results(baseline, result, gate)
    for line in lines:
        out.write(line + "\n")
    out.write(f"gate: {'FAIL' if failures else 'pass'}{f' ({failures} rule(s) failed)' if failures else ''}\n")
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


def verify_problems(data, evals, current=None):
    """Problems of a results file, checked offline against the repository's evals/."""
    if not isinstance(data, dict):
        return ["not a JSON object"]
    if data.get("schema") != SCHEMA:
        return [f"schema is {data.get('schema')!r}, not {SCHEMA}"]
    problems = []
    for key, kind in (
        ("created", str),
        ("set", str),
        ("model", str),
        ("anthropic_model", str),
        ("partial", bool),
        ("config", dict),
        ("suites", dict),
        ("overall", dict),
        ("cases", list),
        ("harness", dict),
        ("sampling", dict),
    ):
        if not isinstance(data.get(key), kind):
            problems.append(f"{key} is missing or not a {kind.__name__}")
    if problems:
        return problems
    try:
        datetime.datetime.strptime(data["created"], "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        problems.append(f"created is not a UTC timestamp: {data['created']}")
    config = data["config"]
    if not isinstance(config.get("sha256"), str) or not HEX64.fullmatch(config["sha256"]):
        problems.append("config.sha256 is missing or not a sha256")
    files = config.get("files")
    if not isinstance(files, dict) or not files or not all(map(is_sha256, files.values())):
        problems.append("config.files is missing or holds a value that is not a sha256")
    elif isinstance(config.get("sha256"), str):
        manifest = "".join(f"{digest}  {relative}\n" for relative, digest in sorted(files.items()))
        if sha256_bytes(manifest.encode("utf-8")) != config["sha256"]:
            problems.append("config.sha256 does not match config.files")
        missing = [relative for relative in CONFIG_FILES if relative not in files]
        if missing:
            problems.append(f"config.files lacks {', '.join(missing)}")
    if data["partial"]:
        problems.append("a partial run (--case): not a complete result")
    if data["set"] not in evals.sets:
        problems.append(f"set {data['set']} is not in evals/sets.toml")
    seen, records = set(), []
    for index, case in enumerate(data["cases"]):
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            problems.append(f"cases[{index}] has no id")
            continue
        if case["id"] in seen:
            problems.append(f"{case['id']} appears twice")
        seen.add(case["id"])
        if case.get("status") not in STATUSES:
            problems.append(f"{case['id']}: status {case.get('status')!r} is not pass, fail or error")
        if case.get("suite") not in evals.suites:
            problems.append(f"{case['id']}: unknown suite {case.get('suite')!r}")
        for key in ("latency_s", "tokens_per_s", "prompt_tokens", "completion_tokens"):
            value = case.get(key)
            if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0):
                problems.append(f"{case['id']}: {key} is not a non-negative number")
        records.append(case)
    if data["set"] in evals.sets:
        pinned = evals.case_ids(data["set"])
        missing = [case_id for case_id in pinned if case_id not in seen]
        unexpected = sorted(seen - set(pinned))
        if missing:
            problems.append(f"missing pinned cases of set {data['set']}: {', '.join(missing)}")
        if unexpected:
            problems.append(f"cases not pinned by set {data['set']}: {', '.join(unexpected)}")
    for name, summary in data["suites"].items():
        suite = evals.suites.get(name)
        if suite is None:
            problems.append(f"suite {name} is not in evals/sets.toml")
            continue
        if not isinstance(summary, dict):
            problems.append(f"suites.{name} is not an object")
            continue
        if summary.get("version") != suite.version:
            problems.append(f"suite {name}: version {summary.get('version')} in the result, {suite.version} in evals/")
        own = [record for record in records if record.get("suite") == name and record.get("status") in STATUSES]
        counted = summarize(own)
        if (summary.get("cases"), summary.get("passed")) != (counted["cases"], counted["passed"]):
            said, found = f"{summary.get('passed')}/{summary.get('cases')}", f"{counted['passed']}/{counted['cases']}"
            problems.append(f"suites.{name} says {said} passed, the cases say {found}")
    text = json.dumps(data)
    if SECRET_PATTERN.search(text) or "Bearer " in text:
        problems.append("the file holds something that looks like a key")
    if current is not None and config.get("sha256") != current[0]:
        changed = ", ".join(changed_files(files if isinstance(files, dict) else {}, current[1]))
        made = str(config.get("sha256"))[:12]
        problems.append(f"made with configuration {made}, the working tree is {current[0][:12]} (changed: {changed})")
    return problems


def command_verify(args, out):
    evals = load_evals(args.root)
    current = config_hash(args.root) if args.current else None
    paths = [Path(path) for path in args.results]
    if not paths:
        if not args.current:
            raise UsageError("name a results file, or use --current to find one for the working tree")
        candidates = sorted((Path(args.root) / "evals" / "results").glob("*.json"))
        for candidate in candidates:
            with_hash = None
            try:
                with_hash = json.loads(candidate.read_text(encoding="utf-8")).get("config", {}).get("sha256")
            except (OSError, ValueError, AttributeError):
                with_hash = None
            if with_hash == current[0]:
                paths.append(candidate)
        if not paths:
            out.write(f"FAIL no results file in evals/results/ for configuration {current[0][:12]}\n")
            return 1

    def check(path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return path, None, ["no such file"]
        except (OSError, UnicodeDecodeError, ValueError) as error:
            return path, None, [f"not JSON: {error}"]
        return path, data, verify_problems(data, evals, current)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.jobs, len(paths)))) as pool:
        checked = list(pool.map(check, paths))
    failed = 0
    for path, data, problems in checked:
        if problems:
            failed += 1
            out.write(f"FAIL {path}\n")
            for problem in problems:
                out.write(f"  {problem}\n")
        else:
            overall = data["overall"]
            out.write(
                f"ok {path} (set {data['set']}, {data['model']}, {overall.get('passed')}/{overall.get('cases')} passed,"
                f" config {data['config']['sha256'][:12]})\n"
            )
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# config-hash and suites
# ---------------------------------------------------------------------------


def command_config_hash(args, out):
    digest, files = config_hash(args.root)
    if args.files:
        for relative, file_digest in sorted(files.items()):
            out.write(f"{file_digest}  {relative}\n")
    out.write(f"{digest}\n")
    return 0


def command_suites(args, out):
    evals = load_evals(args.root)
    problems = suite_problems(evals)
    by_suite = {name: [] for name in evals.order}
    for problem in problems:
        by_suite.setdefault(problem.split("/", 1)[0], []).append(problem)
    broken = {"/".join(problem.split(":", 1)[0].split("/")[:2]) for problem in problems}
    work = [(suite, case) for suite, case in evals.all_cases() if f"{suite.name}/{case['id']}" not in broken]

    def check(item):
        suite, case = item
        if suite.kind == "coding":
            return suite, case, grade_coding_reference(case, float(case.get("timeout", args.test_timeout)))
        grade = grade_answer(suite, case, reference_answer(suite, case))
        return suite, case, Grade(grade.ok, grade.reason if grade.ok else f"the reference fails: {grade.reason}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        for suite, case, grade in pool.map(check, work):
            if not grade.ok:
                by_suite[suite.name].append(f"{suite.name}/{case['id']}: {grade.reason}")
    failed = 0
    for name in evals.order:
        suite = evals.suites[name]
        if by_suite[name]:
            failed += 1
            out.write(f"FAIL {name} (v{suite.version}, {len(suite.cases)} cases)\n")
            for problem in by_suite[name]:
                out.write(f"  {problem}\n")
        else:
            out.write(f"ok {name} (v{suite.version}, {suite.kind}, {len(suite.cases)} cases): every reference passes\n")
    for set_name in evals.sets:
        out.write(f"set {set_name}: {len(evals.case_ids(set_name))} cases\n")
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def positive_int(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return value


def parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this clone)")
    top = argparse.ArgumentParser(prog="eval.py", description="Evaluation suites and regression gate of the stack.")
    commands = top.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", parents=[common], help="run a set of cases against the gateway")
    run.add_argument("--suite", required=True, help="the set of evals/sets.toml to run: smoke or full")
    run.add_argument("--model", default="local-coder", help="model name for OpenAI-route cases (default local-coder)")
    run.add_argument(
        "--anthropic-model",
        help="model name for Anthropic-route cases (default: local-sonnet for local-coder, "
        "local-haiku for local-fast, else the --model name)",
    )
    run.add_argument("--out", help="results file (default evals/results/<UTC>-<model>-<set>.json)")
    run.add_argument("--baseline", help="after the run, compare with this results file and exit with the gate")
    run.add_argument("--gate", type=Path, help="gate thresholds (default evals/gate.toml)")
    run.add_argument("--case", action="append", metavar="ID", help="run only this case (repeatable): a partial run")
    run.add_argument("--temperature", type=float, help="sampling temperature (default: the server's)")
    run.add_argument("--seed", type=int, help="sampling seed, OpenAI route only (default: none)")
    run.add_argument("--max-tokens", type=positive_int, help="max_tokens for every case (default: per suite)")
    run.add_argument("--timeout", type=float, default=600.0, help="seconds per request (default 600)")
    run.add_argument("--test-timeout", type=float, default=10.0, help="seconds per coding test run (default 10)")
    run.add_argument(
        "--rag-source",
        choices=("bundled", "openwebui"),
        default="bundled",
        help="rag context: the bundled documents (default) or Open WebUI retrieval",
    )
    run.add_argument("--kb-k", type=positive_int, default=5, help="passages to retrieve with openwebui (default 5)")
    run.add_argument("--base-url", help="gateway URL (default https://llm.<LAB_DOMAIN>)")
    run.add_argument("--webui-url", help="Open WebUI URL (default https://chat.<LAB_DOMAIN>)")
    run.add_argument("--cafile", help="a CA certificate file to trust (internal CA)")
    run.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="KEY=value file read after the environment")
    run.add_argument("--no-warmup", action="store_true", help="skip the warm-up request of each route")
    run.add_argument("--save-responses", type=Path, metavar="DIR", help="save every raw answer here (debugging)")
    run.add_argument("--jobs", type=positive_int, default=jobs_default(), help="parallel coding test runs")

    compare = commands.add_parser("compare", parents=[common], help="the regression gate between two results")
    compare.add_argument("baseline")
    compare.add_argument("result")
    compare.add_argument("--gate", type=Path, help="gate thresholds (default evals/gate.toml)")

    verify = commands.add_parser("verify", parents=[common], help="check results files offline")
    verify.add_argument("results", nargs="*")
    verify.add_argument("--current", action="store_true", help="also require the working tree's config hash")
    verify.add_argument("--jobs", type=positive_int, default=jobs_default())

    hashing = commands.add_parser("config-hash", parents=[common], help="print the configuration hash")
    hashing.add_argument("--files", action="store_true", help="also print every input file's sha256")

    suites = commands.add_parser("suites", parents=[common], help="check the suite files and their references")
    suites.add_argument("--jobs", type=positive_int, default=jobs_default())
    suites.add_argument("--test-timeout", type=float, default=10.0)
    return top


def main(argv=None, out=None):
    out = out or sys.stdout
    args = parser().parse_args(argv)
    args.root = Path(args.root).resolve()
    if getattr(args, "gate", "unset") is None:
        args.gate = args.root / "evals" / "gate.toml"
    try:
        if args.command == "run":
            return command_run(args, out)
        if args.command == "compare":
            return compare_files(args.baseline, args.result, args.gate, out)
        if args.command == "verify":
            return command_verify(args, out)
        if args.command == "config-hash":
            return command_config_hash(args, out)
        return command_suites(args, out)
    except UsageError as error:
        print(f"eval.py: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
