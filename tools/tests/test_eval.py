"""Unit tests of tools/eval.py: matching, checks, the coding sandbox, config-hash, and run, compare
and verify against a fake gateway (http.server on the loopback address, in a thread). No model."""

import contextlib
import hashlib
import http.server
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parent.parent
REPO = TOOLS.parent
KEY = "sk-local-example"
KB_KEY = "kb-reader-example"


def load(name):
    spec = importlib.util.spec_from_file_location(f"las_{name}", TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ev = load("eval")


def make_root():
    """A scratch copy of the files eval.py reads: the inference configs and evals/."""
    root = Path(tempfile.mkdtemp(prefix="eval-test-"))
    for relative in ev.CONFIG_FILES:
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, root / relative)
    shutil.copytree(REPO / "evals", root / "evals", ignore=shutil.ignore_patterns("results", "baselines"))
    return root


def run_main(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(err):
        code = ev.main([str(arg) for arg in argv], out=out)
    return code, out.getvalue() + err.getvalue()


# ---------------------------------------------------------------------------
# The fake gateway
# ---------------------------------------------------------------------------


def openai_answer(text, calls, tokens):
    message = {"role": "assistant", "content": text or None}
    if calls:
        message["tool_calls"] = [
            {
                "id": f"call_{index}",
                "type": "function",
                "function": {"name": call["name"], "arguments": json.dumps(call.get("arguments", {}))},
            }
            for index, call in enumerate(calls)
        ]
    return {
        "object": "chat.completion",
        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if calls else "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": tokens, "total_tokens": 100 + tokens},
    }


def anthropic_answer(text, calls, tokens):
    content = [{"type": "text", "text": text}] if text else []
    content += [
        {"type": "tool_use", "id": f"toolu_{index}", "name": call["name"], "input": call.get("arguments", {})}
        for index, call in enumerate(calls)
    ]
    return {
        "type": "message",
        "role": "assistant",
        "content": content,
        "stop_reason": "tool_use" if calls else "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": tokens},
    }


class QuietServer(http.server.ThreadingHTTPServer):
    """A delayed request whose client gave up ends in a broken pipe: expected, not printed."""

    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


class FakeGateway:
    """Answers every case with its reference answer, or a wrong one for the IDs in `wrong`."""

    def __init__(self, root):
        self.evals = ev.load_evals(root)
        documents = ev.bundled_documents(root)
        self.cases = {}
        self.questions = []
        for suite, case in self.evals.all_cases():
            _, path, body = ev.build_request(suite, case, "any", ev.Options(), documents)
            self.cases[(path, json.dumps(body["messages"], sort_keys=True))] = (suite, case)
            if suite.kind == "rag":
                self.questions.append((case["question"], suite, case))
        self.wrong = set()
        self.status = {}
        self.delay = {}
        self.requests = []
        self.in_flight = 0
        self.max_in_flight = 0
        self.lock = threading.Lock()
        self.server = QuietServer(("127.0.0.1", 0), self.handler())
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def handler(self):
        gateway = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                headers = {key.lower(): value for key, value in self.headers.items()}
                status, payload = gateway.handle(self.path, headers, body)
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        return Handler

    def find(self, path, messages):
        found = self.cases.get((path, json.dumps(messages, sort_keys=True)))
        if found:
            return found
        last = json.dumps(messages[-1])
        for question, suite, case in self.questions:
            if json.dumps(question)[1:-1] in last:
                return suite, case
        return None, None

    def handle(self, path, headers, body):
        with self.lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            self.requests.append((path, headers, body))
        try:
            time.sleep(0.002)
            if path == "/api/v1/retrieval/query/collection":
                return self.retrieval(headers, body)
            if headers.get("authorization") != f"Bearer {KEY}":
                return 401, {"error": {"message": "Authentication Error"}}
            messages = body["messages"]
            if messages == [{"role": "user", "content": ev.WARMUP_PROMPT}]:
                return 200, self.answer(path, "OK", [], 2)
            suite, case = self.find(path, messages)
            if case is None:
                return 400, {"error": {"message": "unknown request"}}
            if case["id"] in self.delay:
                time.sleep(self.delay[case["id"]])
            if case["id"] in self.status:
                return self.status[case["id"]], {"error": {"message": f"upstream failed, key {KEY}"}}
            text, calls = self.reference(suite, case) if case["id"] not in self.wrong else self.mistake(suite, case)
            return 200, self.answer(path, text, calls, 64)
        finally:
            with self.lock:
                self.in_flight -= 1

    def answer(self, path, text, calls, tokens):
        if path == "/v1/chat/completions":
            return openai_answer(text, calls, tokens)
        return anthropic_answer(text, calls, tokens)

    @staticmethod
    def reference(suite, case):
        reference = case["reference"]
        if suite.kind == "tools":
            return reference.get("text", ""), reference["calls"]
        if suite.kind == "coding":
            return f"Here it is:\n\n```python\n{reference}```\n", []
        return reference, []

    @staticmethod
    def mistake(suite, case):
        if suite.kind == "tools":
            if case["expect"]["calls"]:
                return "I cannot do that.", []
            return "", [{"name": case["tools"][0]["name"], "arguments": {}}]
        if suite.kind == "coding":
            return f"```python\ndef {case['entry_point']}(*args):\n    return None\n```", []
        return "nope", []

    def retrieval(self, headers, body):
        if headers.get("authorization") != f"Bearer {KB_KEY}":
            return 401, {"detail": "Not authenticated"}
        documents, metadatas = [], []
        for name, text in ev.bundled_documents(self.evals.root):
            documents.append(text)
            metadatas.append({"name": name, "source": name})
        return 200, {"distances": [[0.1] * len(documents)], "documents": [documents], "metadatas": [metadatas]}


class GatewayTest(unittest.TestCase):
    def setUp(self):
        self.root = make_root()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.gateway = FakeGateway(self.root)
        self.addCleanup(self.gateway.close)
        environ = {
            "LOCAL_LLM_KEY": KEY,
            "LAB_DOMAIN": "lab.example.com",
            "EVAL_KB_ID": "kb-example",
            "EVAL_KB_KEY": KB_KEY,
        }
        patcher = mock.patch.dict(os.environ, environ)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_eval(self, *extra, suite="smoke", out=None):
        argv = ["run", "--root", self.root, "--suite", suite, "--base-url", self.gateway.url]
        argv += ["--env-file", self.root / "no-such-client.env", "--jobs", "4"]
        if out is not None:
            argv += ["--out", out]
        return run_main(*argv, *extra)

    def results(self):
        return sorted((self.root / "evals" / "results").glob("*.json"))


# ---------------------------------------------------------------------------
# Matching and checks
# ---------------------------------------------------------------------------


class TestMatching(unittest.TestCase):
    def test_types(self):
        self.assertEqual(ev.match_schema(5, {"type": "integer"}), [])
        self.assertEqual(ev.match_schema(5.0, {"type": "integer"}), [])
        self.assertTrue(ev.match_schema(True, {"type": "integer"}))
        self.assertTrue(ev.match_schema("5", {"type": "integer"}))
        self.assertEqual(ev.match_schema(2.5, {"type": "number", "minimum": 2, "maximum": 3}), [])
        self.assertTrue(ev.match_schema(3.5, {"type": "number", "maximum": 3}))
        self.assertEqual(ev.match_schema(None, {"type": ["string", "null"]}), [])

    def test_json_same(self):
        self.assertTrue(ev.json_same({"a": [1, 2.0]}, {"a": [1.0, 2]}))
        self.assertFalse(ev.json_same(True, 1))
        self.assertFalse(ev.json_same({"a": 1}, {"a": 1, "b": 2}))
        self.assertFalse(ev.json_same([1, 2], [2, 1]))

    def test_objects(self):
        schema = {
            "type": "object",
            "properties": {
                "city": {"type": "string", "pattern": "(?i)^paris\\b"},
                "start": {"type": "object", "properties": {"date": {"const": "2026-12-03"}}, "required": ["date"]},
            },
            "required": ["city"],
            "additionalProperties": False,
        }
        self.assertEqual(ev.match_schema({"city": "Paris, France"}, schema), [])
        self.assertIn("$: city is missing", ev.match_schema({}, schema))
        self.assertIn("$: unexpected unit", ev.match_schema({"city": "Paris", "unit": "c"}, schema))
        problems = ev.match_schema({"city": "Paris", "start": {"date": "2026-12-04"}}, schema)
        self.assertTrue(problems[0].startswith("$.start.date: expected"), problems)
        self.assertTrue(ev.match_schema({"city": "Pariss"}, schema)[0].startswith("$.city:"))

    def test_arrays(self):
        schema = {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 2,
            "allOf": [{"contains": {"const": "bug"}}, {"contains": {"const": "backup"}}],
        }
        self.assertEqual(ev.match_schema(["backup", "bug"], schema), [])
        self.assertTrue(ev.match_schema(["bug"], schema))
        self.assertTrue(ev.match_schema(["bug", "docs"], schema))
        self.assertTrue(ev.match_schema(["bug", 3], schema))
        self.assertTrue(ev.match_schema([1, 1], {"uniqueItems": True}))

    def test_alternatives(self):
        schema = {
            "anyOf": [
                {"properties": {"cwd": {"const": "/srv/app"}}, "required": ["cwd"]},
                {"properties": {"command": {"pattern": "cd /srv/app"}}, "required": ["command"]},
            ]
        }
        self.assertEqual(ev.match_schema({"command": "git status", "cwd": "/srv/app"}, schema), [])
        self.assertEqual(ev.match_schema({"command": "cd /srv/app && git status"}, schema), [])
        self.assertTrue(ev.match_schema({"command": "git status"}, schema))
        self.assertTrue(ev.match_schema(1, {"oneOf": [{"type": "integer"}, {"type": "number"}]}))
        self.assertTrue(ev.match_schema(1, {"not": {"type": "integer"}}))

    def test_schema_problems(self):
        self.assertEqual(ev.schema_problems({"type": "string", "description": "x", "pattern": "^a"}), [])
        self.assertIn("$: unsupported keyword format_x", ev.schema_problems({"format_x": 1}))
        self.assertTrue(ev.schema_problems({"pattern": "("}))
        self.assertTrue(ev.schema_problems({"properties": {"a": {"type": "str"}}}))


class TestChecks(unittest.TestCase):
    def check(self, text, **check):
        return ev.check_text(text, check)

    def test_json_equals_is_strict(self):
        self.assertIsNone(
            self.check(' {"name": "Ada", "born": 1815}\n', check="json_equals", value={"born": 1815, "name": "Ada"})
        )
        fenced = '```json\n{"name": "Ada"}\n```'
        self.assertIn("not JSON", self.check(fenced, check="json_equals", value={"name": "Ada"}))
        self.assertIsNotNone(self.check('{"born": true}', check="json_equals", value={"born": 1}))

    def test_exact_regex_lines(self):
        self.assertIsNone(self.check("name,qty\r\napples,3\n", check="exact", value="name,qty\napples,3"))
        self.assertIsNotNone(self.check("Blue", check="regex", pattern="blue", mode="fullmatch"))
        self.assertIsNone(self.check("Blue", check="regex", pattern="blue", mode="fullmatch", flags="i"))
        self.assertIsNone(self.check("red\ngreen\nblue", check="lines", count=3, each="(red|green|blue)"))
        self.assertIn("expected 3 lines", self.check("1. red\n2. green", check="lines", count=3))
        self.assertIsNotNone(self.check("password: x", check="not_regex", pattern="password"))

    def test_json_schema_check(self):
        schema = {"type": "object", "properties": {"done": {"const": False}}, "required": ["done"]}
        self.assertIsNone(self.check('{"done": false}', check="json_schema", schema=schema))
        self.assertIsNotNone(self.check('{"done": 0}', check="json_schema", schema=schema))

    def test_check_problems(self):
        self.assertEqual(ev.check_problems({"check": "regex", "pattern": "a", "flags": "i"}, "w"), [])
        self.assertTrue(ev.check_problems({"check": "equals"}, "w"))
        self.assertTrue(ev.check_problems({"check": "regex", "pattern": "a", "flags": "x"}, "w"))
        self.assertTrue(ev.check_problems({"check": "regex", "pattern": "("}, "w"))


class TestToolGrading(unittest.TestCase):
    CASE = {
        "expect": {
            "calls": [
                {
                    "name": "get_weather",
                    "arguments": {"properties": {"city": {"pattern": "(?i)^tokyo"}}, "required": ["city"]},
                },
                {
                    "name": "get_weather",
                    "arguments": {"properties": {"city": {"pattern": "(?i)^oslo"}}, "required": ["city"]},
                },
            ]
        }
    }

    def grade(self, *calls, text="", case=None, finish="tool_calls"):
        answer = ev.Answer(text=text, calls=[ev.Call(*call) for call in calls], finish=finish)
        return ev.grade_tools(case or self.CASE, answer)

    def test_parallel_calls_in_any_order(self):
        grade = self.grade(("get_weather", {"city": "Oslo"}), ("get_weather", {"city": "Tokyo"}))
        self.assertTrue(grade.ok, grade.reason)

    def test_missing_extra_and_wrong_calls(self):
        self.assertIn("expected 2 call(s)", self.grade(("get_weather", {"city": "Oslo"})).reason)
        three = self.grade(*[("get_weather", {"city": city}) for city in ("Oslo", "Tokyo", "Rome")])
        self.assertFalse(three.ok)
        allowed = dict(self.CASE, expect=dict(self.CASE["expect"], allow_extra=True))
        self.assertTrue(self.grade(*[("get_weather", {"city": c}) for c in ("Oslo", "Tokyo", "Rome")], case=allowed).ok)
        wrong = self.grade(("get_weather", {"city": "Oslo"}), ("get_weather", {"city": "Kyoto"}))
        self.assertFalse(wrong.ok)
        self.assertIn("$.city", wrong.reason)

    def test_no_call_and_call_written_as_text(self):
        grade = self.grade(text='<tool_call>{"name": "get_weather"}</tool_call>', finish="stop")
        self.assertFalse(grade.ok)
        self.assertIn("written as text", grade.reason)
        none_expected = {"expect": {"calls": [], "text": [{"check": "regex", "pattern": "144"}]}}
        self.assertTrue(self.grade(text="144", case=none_expected, finish="stop").ok)
        self.assertFalse(self.grade(("get_weather", {}), case=none_expected).ok)
        self.assertIn("max_tokens", self.grade(case=none_expected, finish="length").reason)

    def test_parse_answers(self):
        answer = ev.parse_openai(
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {"function": {"name": "a", "arguments": '{"x": 1}'}},
                                {"function": {"name": "b", "arguments": "{x: 1"}},
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "timings": {"predicted_per_second": 51.5},
            }
        )
        self.assertEqual((answer.calls[0].name, answer.calls[0].arguments), ("a", {"x": 1}))
        self.assertIsNotNone(answer.calls[1].error)
        self.assertEqual((answer.prompt_tokens, answer.completion_tokens, answer.server_tps), (10, 5, 51.5))
        self.assertFalse(ev.grade_tools({"expect": {"calls": [{"name": "b"}]}}, answer).ok)
        message = ev.parse_anthropic(
            {
                "type": "message",
                "content": [
                    {"type": "thinking", "thinking": "hmm"},
                    {"type": "text", "text": "Calling."},
                    {"type": "tool_use", "id": "t", "name": "a", "input": {"x": 2}},
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 7, "output_tokens": 3},
            }
        )
        self.assertEqual(
            (message.text, message.calls[0].arguments, message.completion_tokens), ("Calling.", {"x": 2}, 3)
        )
        with self.assertRaises(ev.CaseError):
            ev.parse_openai({"choices": []})

    def test_extract_code(self):
        text = (
            "First:\n```\npip install x\n```\nThen:\n```python\nimport re\n\ndef slugify(t):\n    return t\n```\nDone."
        )
        self.assertIn("def slugify", ev.extract_code(text, "slugify"))
        self.assertEqual(ev.extract_code("```py\nx = 1\n```", "f"), "x = 1\n")
        self.assertEqual(ev.extract_code("def f():\n    pass", "f"), "def f():\n    pass")


# ---------------------------------------------------------------------------
# The coding sandbox
# ---------------------------------------------------------------------------


class TestSandbox(unittest.TestCase):
    TESTS = "assert double(2) == 4\nassert double(5) == 10\n"

    def run_code(self, code, timeout=5.0):
        return ev.run_tests(code, self.TESTS, timeout=timeout)

    def test_pass_and_fail(self):
        self.assertTrue(self.run_code("def double(x):\n    return 2 * x\n").ok)
        grade = self.run_code("def double(x):\n    return x + 2\n")
        self.assertFalse(grade.ok)
        self.assertIn("AssertionError at: assert double(5) == 10", grade.reason)
        self.assertIn("NameError", self.run_code("def triple(x):\n    return 3 * x\n").reason)
        self.assertIn("SyntaxError", self.run_code("def double(x)\n    return 2 * x\n").reason)

    def test_timeout(self):
        started = time.monotonic()
        grade = self.run_code("def double(x):\n    while True:\n        pass\n", timeout=1.0)
        self.assertFalse(grade.ok)
        self.assertIn("timed out", grade.reason)
        self.assertLess(time.monotonic() - started, 5)

    def test_network_and_processes_are_blocked(self):
        network = "import socket\ndef double(x):\n    socket.socket().connect(('192.0.2.10', 80))\n    return 2 * x\n"
        self.assertIn("sandbox: socket", self.run_code(network).reason)
        spawn = "import subprocess\ndef double(x):\n    subprocess.run(['true'])\n    return 2 * x\n"
        self.assertIn("sandbox: subprocess", self.run_code(spawn).reason)
        system = "import os\ndef double(x):\n    os.system('true')\n    return 2 * x\n"
        self.assertIn("sandbox: os.system", self.run_code(system).reason)

    def test_writes_stay_in_the_test_directory(self):
        outside = Path(tempfile.mkdtemp(prefix="eval-outside-"))
        self.addCleanup(shutil.rmtree, outside, True)
        target = outside / "written.txt"
        code = f"def double(x):\n    open({str(target)!r}, 'w').write('x')\n    return 2 * x\n"
        self.assertIn("writing outside", self.run_code(code).reason)
        self.assertFalse(target.exists())
        removal = f"import os\ndef double(x):\n    os.remove({str(outside)!r})\n    return 2 * x\n"
        self.assertIn("outside the test directory", self.run_code(removal).reason)
        inside = "def double(x):\n    open('scratch.txt', 'w').write('x')\n    return 2 * x\n"
        self.assertTrue(self.run_code(inside).ok)

    def test_early_exit_does_not_pass(self):
        self.assertFalse(self.run_code("import sys\nsys.exit(0)\n").ok)
        self.assertFalse(self.run_code("import os\nos._exit(0)\n").ok)
        self.assertFalse(self.run_code("def double(x):\n    print('EVAL-OK 00')\n    return 0\n").ok)


# ---------------------------------------------------------------------------
# The suites, the sets and the configuration hash
# ---------------------------------------------------------------------------


class TestSuites(unittest.TestCase):
    def test_bundled_suites_are_consistent(self):
        code, output = run_main("suites", "--root", REPO, "--jobs", "8")
        self.assertEqual(code, 0, output)
        evals = ev.load_evals(REPO)
        self.assertEqual(evals.order, ["tools", "format", "coding", "rag"])
        sizes = {name: len(suite.cases) for name, suite in evals.suites.items()}
        self.assertEqual(sizes, {"tools": 20, "format": 10, "coding": 8, "rag": 6})
        smoke = evals.case_ids("smoke")
        self.assertEqual(len(smoke), 15)
        self.assertEqual({case_id.split("-")[0] for case_id in smoke}, set(evals.order))
        self.assertEqual(len(evals.case_ids("full")), 44)
        tools = evals.suites["tools"].cases
        self.assertGreaterEqual(sum(case.get("api") == "anthropic" for case in tools), 5)
        self.assertGreaterEqual(sum(len(case["expect"]["calls"]) > 1 for case in tools), 3)
        self.assertGreaterEqual(sum(not case["expect"]["calls"] for case in tools), 3)

    def test_suite_problems_are_reported(self):
        root = make_root()
        self.addCleanup(shutil.rmtree, root, True)
        path = root / "evals" / "suites" / "format.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        case = json.loads(lines[1])
        case["reference"] = '{"name": "Ada"}'
        lines[1] = json.dumps(case)
        bad = json.loads(lines[2])
        bad["checks"] = [{"check": "regex", "pattern": "("}]
        lines[2] = json.dumps(bad)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        code, output = run_main("suites", "--root", root)
        self.assertEqual(code, 1)
        self.assertIn("format/format-001: the reference fails", output)
        self.assertIn("format/format-002/checks[0]: bad pattern", output)

    def test_sets_must_pin_known_cases(self):
        root = make_root()
        self.addCleanup(shutil.rmtree, root, True)
        sets = root / "evals" / "sets.toml"
        sets.write_text(sets.read_text(encoding="utf-8").replace('"rag-006",', '"rag-099",'), encoding="utf-8")
        with self.assertRaises(ev.UsageError) as caught:
            ev.load_evals(root)
        self.assertIn("rag-099", str(caught.exception))

    def test_config_hash(self):
        root = make_root()
        self.addCleanup(shutil.rmtree, root, True)
        digest, files = ev.config_hash(root)
        self.assertRegex(digest, "^[0-9a-f]{64}$")
        self.assertEqual(ev.config_hash(root), (digest, files))
        for relative in ev.CONFIG_FILES + ("evals/sets.toml", "evals/suites/tools.jsonl"):
            self.assertIn(relative, files)
        self.assertTrue(any(path.startswith("evals/rag-docs/") for path in files))
        self.assertNotIn("evals/gate.toml", files)
        manifest = "".join(f"{hashlib.sha256((root / p).read_bytes()).hexdigest()}  {p}\n" for p in sorted(files))
        self.assertEqual(hashlib.sha256(manifest.encode()).hexdigest(), digest)
        code, output = run_main("config-hash", "--root", root)
        self.assertEqual((code, output), (0, digest + "\n"))
        (root / "evals" / "gate.toml").write_text("[gate]\n", encoding="utf-8")
        self.assertEqual(ev.config_hash(root)[0], digest)
        config = root / "stack/inference/llama-swap/config.yaml"
        config.write_text(config.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
        new_digest, new_files = ev.config_hash(root)
        self.assertNotEqual(new_digest, digest)
        self.assertEqual(ev.changed_files(files, new_files), ["stack/inference/llama-swap/config.yaml"])
        config.unlink()
        code, output = run_main("config-hash", "--root", root)
        self.assertEqual(code, 2)
        self.assertIn("llama-swap/config.yaml is missing", output)


# ---------------------------------------------------------------------------
# run, compare and verify against the fake gateway
# ---------------------------------------------------------------------------


class TestRun(GatewayTest):
    def test_smoke_run_passes_and_records_no_secrets(self):
        code, output = self.run_eval()
        self.assertEqual(code, 0, output)
        [path] = self.results()
        self.assertRegex(path.name, r"^\d{8}T\d{6}Z-local-coder-smoke\.json$")
        text = path.read_text(encoding="utf-8")
        result = json.loads(text)
        self.assertEqual(result["schema"], ev.SCHEMA)
        self.assertEqual(
            (result["set"], result["model"], result["anthropic_model"]), ("smoke", "local-coder", "local-sonnet")
        )
        self.assertEqual(result["config"]["sha256"], ev.config_hash(self.root)[0])
        self.assertEqual((result["overall"]["cases"], result["overall"]["passed"]), (15, 15))
        self.assertEqual(list(result["suites"]), ["tools", "format", "coding", "rag"])
        self.assertEqual(result["suites"]["tools"]["pass_rate"], 100.0)
        self.assertEqual(result["suites"]["rag"]["source"], "bundled")
        for case in result["cases"]:
            self.assertEqual(case["status"], "pass", case)
            self.assertEqual((case["prompt_tokens"], case["completion_tokens"]), (100, 64))
            self.assertGreater(case["tokens_per_s"], 0)
        self.assertNotIn(KEY, text)
        self.assertNotIn("lab.example.com", text)
        self.assertNotIn("Paris", text)  # no prompt bodies
        self.assertEqual(self.gateway.max_in_flight, 1)
        warmups = [body["model"] for path, _, body in self.gateway.requests[:2]]
        self.assertEqual(warmups, ["local-coder", "local-sonnet"])
        for path, headers, body in self.gateway.requests:
            self.assertEqual(headers["authorization"], f"Bearer {KEY}")
            if path == "/v1/messages":
                self.assertEqual(headers["anthropic-version"], ev.ANTHROPIC_VERSION)
                self.assertEqual(body["model"], "local-sonnet")
            else:
                self.assertEqual(body["model"], "local-coder")
        parallel = [body for path, _, body in self.gateway.requests if body.get("parallel_tool_calls")]
        self.assertEqual(len(parallel), 1)  # tools-005 in smoke
        self.assertIn("overall", output)
        self.assertIn("results: ", output)

    def test_full_run_verify_and_compare_with_itself(self):
        out = self.root / "evals" / "results" / "full.json"
        code, output = self.run_eval("--model", "local-fast", suite="full", out=out)
        self.assertEqual(code, 0, output)
        result = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(result["anthropic_model"], "local-haiku")
        self.assertEqual((result["overall"]["cases"], result["overall"]["passed"]), (44, 44))
        self.assertEqual(result["suites"]["coding"]["passed"], 8)
        self.assertEqual(run_main("verify", "--root", self.root, out)[0], 0)
        code, output = run_main("verify", "--root", self.root, "--current")
        self.assertEqual(code, 0, output)
        self.assertIn("ok ", output)
        code, output = run_main("compare", "--root", self.root, out, out)
        self.assertEqual(code, 0, output)
        self.assertIn("gate: pass", output)

    def test_regression_fails_the_gate(self):
        baseline = self.root / "baseline.json"
        self.assertEqual(self.run_eval(suite="full", out=baseline)[0], 0)
        self.gateway.wrong = {"tools-005", "format-003", "coding-004"}
        changed = self.root / "changed.json"
        code, output = self.run_eval("--baseline", baseline, suite="full", out=changed)
        self.assertEqual(code, 1, output)
        rows = {
            line.split()[0]: line for line in output.splitlines() if line.split() and line.split()[-1] in ("ok", "FAIL")
        }
        self.assertTrue(rows["tools"].endswith("ok"), rows)  # 1 of 20 = 5 points: not more than 5
        self.assertTrue(rows["format"].endswith("FAIL"), rows)
        self.assertTrue(rows["coding"].endswith("FAIL"), rows)
        self.assertIn("newly failing: tools-005, format-003, coding-004", output)
        result = json.loads(changed.read_text(encoding="utf-8"))
        statuses = {case["id"]: case for case in result["cases"]}
        self.assertEqual(statuses["coding-004"]["status"], "fail")
        self.assertIn("tests failed", statuses["coding-004"]["reason"])
        gate = self.root / "lenient.toml"
        gate.write_text(
            # The fake gateway's speeds are wall-clock timings that vary on a busy runner, so this
            # gate checks the pass-rate rules only (test_speed_drop_fails_the_gate covers speed).
            "[gate]\npass_rate_drop_points = 5\ntokens_per_second_drop_percent = 100\n"
            "[gate.suites.format]\npass_rate_drop_points = 10\n"
            "[gate.suites.coding]\npass_rate_drop_points = 12.5\n",
            encoding="utf-8",
        )
        code, output = run_main("compare", "--root", self.root, "--gate", gate, baseline, changed)
        self.assertEqual(code, 0, output)

    def test_speed_drop_fails_the_gate(self):
        baseline = self.root / "baseline.json"
        self.assertEqual(self.run_eval(out=baseline)[0], 0)
        data = json.loads(baseline.read_text(encoding="utf-8"))
        for factor, expected in ((0.8, 1), (0.9, 0)):
            slower = copy_with(data, factor)
            path = self.root / f"slower-{factor}.json"
            path.write_text(json.dumps(slower), encoding="utf-8")
            code, output = run_main("compare", "--root", self.root, baseline, path)
            self.assertEqual(code, expected, output)
            speed_row = next(line for line in output.splitlines() if line.startswith("tok/s"))
            self.assertTrue(speed_row.endswith("FAIL" if expected else "ok"), speed_row)

    def test_partial_run(self):
        code, output = self.run_eval("--case", "tools-001", "--case", "rag-001")
        self.assertEqual(code, 0, output)
        [path] = (self.root / "build" / "evals").glob("*-partial.json")
        result = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(result["partial"])
        self.assertEqual([case["id"] for case in result["cases"]], ["tools-001", "rag-001"])
        code, output = run_main("verify", "--root", self.root, path)
        self.assertEqual(code, 1)
        self.assertIn("partial run", output)
        self.assertEqual(self.run_eval("--case", "tools-002")[0], 2)  # not in the smoke set

    def test_failed_requests_are_errors_and_redacted(self):
        self.gateway.status = {"format-001": 500}
        self.gateway.delay = {"tools-007": 1.5}
        out = self.root / "errors.json"
        code, output = self.run_eval("--timeout", "0.5", out=out)
        self.assertEqual(code, 0, output)
        cases = {case["id"]: case for case in json.loads(out.read_text(encoding="utf-8"))["cases"]}
        self.assertEqual(cases["format-001"]["status"], "error")
        self.assertIn("HTTP 500", cases["format-001"]["reason"])
        self.assertNotIn(KEY, out.read_text(encoding="utf-8"))
        self.assertEqual(cases["tools-007"]["status"], "error")
        self.assertIn("no answer within", cases["tools-007"]["reason"])
        self.assertEqual(cases["tools-009"]["status"], "pass")

    def test_rag_through_open_webui(self):
        out = self.root / "kb.json"
        code, output = self.run_eval(
            "--case",
            "rag-001",
            "--case",
            "rag-006",
            "--rag-source",
            "openwebui",
            "--webui-url",
            self.gateway.url,
            out=out,
        )
        self.assertEqual(code, 0, output)
        result = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(result["rag_source"], "openwebui")
        self.assertEqual(result["suites"]["rag"]["source"], "openwebui")
        self.assertEqual(result["suites"]["rag"]["retrieval_hit_rate"], 100.0)
        cases = {case["id"]: case for case in result["cases"]}
        self.assertIs(cases["rag-001"]["retrieval_hit"], True)
        self.assertIsNone(cases["rag-006"]["retrieval_hit"])
        retrievals = [(h, b) for p, h, b in self.gateway.requests if p == "/api/v1/retrieval/query/collection"]
        self.assertEqual(len(retrievals), 2)
        self.assertEqual(retrievals[0][0]["authorization"], f"Bearer {KB_KEY}")
        self.assertEqual(retrievals[0][1]["collection_names"], ["kb-example"])
        self.assertNotIn(KB_KEY, out.read_text(encoding="utf-8"))

    def test_aborts_and_usage_errors(self):
        os.environ["LOCAL_LLM_KEY"] = "sk-local-wrong"
        code, output = self.run_eval()
        self.assertEqual(code, 1)
        self.assertIn("run aborted", output)
        self.assertEqual(self.results(), [])
        os.environ["LOCAL_LLM_KEY"] = KEY
        closed = http.server.HTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
        port = closed.server_address[1]
        closed.server_close()
        argv = ["run", "--root", self.root, "--suite", "smoke", "--env-file", self.root / "none"]
        code, output = run_main(*argv, "--base-url", f"http://127.0.0.1:{port}")
        self.assertEqual(code, 1)
        self.assertIn("cannot reach", output)
        code, output = run_main(*argv, "--base-url", "http://192.0.2.10:4000")
        self.assertEqual(code, 2)
        self.assertIn("https only", output)
        del os.environ["LOCAL_LLM_KEY"]
        code, output = run_main(*argv, "--base-url", self.gateway.url)
        self.assertEqual(code, 2)
        self.assertIn("LOCAL_LLM_KEY", output)
        self.assertEqual(run_main(*argv[:4], "nightly", "--base-url", self.gateway.url)[0], 2)


def copy_with(result, factor):
    slower = json.loads(json.dumps(result))
    for case in slower["cases"]:
        if case.get("tokens_per_s"):
            case["tokens_per_s"] = case["tokens_per_s"] * factor
    return slower


class TestVerify(GatewayTest):
    def setUp(self):
        super().setUp()
        self.path = self.root / "evals" / "results" / "smoke.json"
        code, output = self.run_eval(out=self.path)
        self.assertEqual(code, 0, output)
        self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def verify(self, data, *extra):
        path = self.root / "tampered.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return run_main("verify", "--root", self.root, *extra, path)

    def test_valid(self):
        code, output = run_main("verify", "--root", self.root, "--current", self.path)
        self.assertEqual(code, 0, output)

    def test_tampered_results(self):
        def changed(edit):
            data = json.loads(json.dumps(self.data))
            edit(data)
            return data

        cases = [
            (lambda d: d["config"].pop("sha256"), "config.sha256 is missing"),
            (lambda d: d["config"]["files"].update({"evals/sets.toml": "0" * 64}), "does not match config.files"),
            (lambda d: d["cases"].pop(0), "missing pinned cases of set smoke: tools-001"),
            (lambda d: d["cases"].append(dict(d["cases"][0], id="tools-002")), "not pinned by set smoke: tools-002"),
            (lambda d: d["cases"][0].update(status="maybe"), "is not pass, fail or error"),
            (lambda d: d["suites"]["tools"].update(version=0), "suite tools: version 0"),
            (lambda d: d["suites"]["format"].update(passed=1), "suites.format says 1/3 passed"),
            (lambda d: d["cases"][0].update(reason="sk-" + "x1" * 12), "looks like a key"),
            (lambda d: d.update(set="nightly"), "set nightly is not in evals/sets.toml"),
            (lambda d: d.update(schema="other/1"), "not local-agent-stack/eval-result/1"),
        ]
        for edit, message in cases:
            code, output = self.verify(changed(edit))
            self.assertEqual(code, 1, output)
            self.assertIn(message, output)

    def test_current_configuration(self):
        config = self.root / "stack" / "inference" / "litellm" / "config.yaml"
        config.write_text(config.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
        code, output = run_main("verify", "--root", self.root, "--current", self.path)
        self.assertEqual(code, 1)
        self.assertIn("changed: stack/inference/litellm/config.yaml", output)
        code, output = run_main("verify", "--root", self.root, "--current")
        self.assertEqual(code, 1)
        self.assertIn("no results file in evals/results/", output)
        self.assertEqual(run_main("verify", "--root", self.root)[0], 2)


if __name__ == "__main__":
    unittest.main()
