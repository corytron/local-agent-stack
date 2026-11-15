"""Unit tests of tools/smoke.py with a fake HTTP layer (no network)."""

import argparse
import importlib.util
import io
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(f"las_{name}", TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


smoke = load("smoke")


def settings(llm_key="sk-local-example", mcp_token="token-example"):
    args = argparse.Namespace(cafile=None, timeout=5.0, env_file=None)
    environ = {"LAB_DOMAIN": "lab.example.com"}
    if llm_key:
        environ["LOCAL_LLM_KEY"] = llm_key
    if mcp_token:
        environ["MCP_HUB_TOKEN"] = mcp_token
    return smoke.make_settings(args, environ)


def answer(body, status=200, content_type="application/json"):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    return smoke.Response(status, {"content-type": content_type}, data)


class FakeServer:
    """Routes (method, URL path) to answers and records every request."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def __call__(self, _settings, method, url, payload=None, headers=None):
        path = url.split(".lab.example.com", 1)[1].split("?", 1)[0]
        host = url.split("//", 1)[1].split(".", 1)[0]
        self.requests.append((method, host, path, payload, dict(headers or {})))
        route = self.routes.get((method, host, path))
        if route is None:
            return answer({"error": "not found"}, 404)
        return route(payload) if callable(route) else route


class TestChecks(unittest.TestCase):
    def run_check(self, name, routes, **kwargs):
        server = FakeServer(routes)
        with mock.patch.object(smoke, "http", server):
            result = smoke.run_one(name, settings(**kwargs))
        return result, server

    def test_models_lists_every_name(self):
        data = {"data": [{"id": name} for name in smoke.MODELS]}
        result, server = self.run_check("models", {("GET", "llm", "/v1/models"): answer(data)})
        self.assertTrue(result.ok, result.lines)
        self.assertEqual(server.requests[0][4]["Authorization"], "Bearer sk-local-example")

    def test_models_missing_names(self):
        data = {"data": [{"id": "local-coder"}]}
        result, _ = self.run_check("models", {("GET", "llm", "/v1/models"): answer(data)})
        self.assertFalse(result.ok)
        self.assertIn("local-rerank", result.lines[0])

    def test_missing_key_says_which_variable(self):
        result, server = self.run_check("models", {}, llm_key=None)
        self.assertFalse(result.ok)
        self.assertIn("LOCAL_LLM_KEY is not set", result.lines[0])
        self.assertEqual(server.requests, [])

    def test_chat(self):
        body = {"choices": [{"message": {"content": "OK"}}]}
        result, server = self.run_check("chat", {("POST", "llm", "/v1/chat/completions"): answer(body)})
        self.assertTrue(result.ok, result.lines)
        self.assertEqual(server.requests[0][3]["model"], "local-fast")

    def test_chat_http_error(self):
        result, _ = self.run_check("chat", {("POST", "llm", "/v1/chat/completions"): answer({"error": "x"}, 401)})
        self.assertFalse(result.ok)
        self.assertIn("HTTP 401", result.lines[0])

    def test_messages_is_the_anthropic_api(self):
        body = {"type": "message", "content": [{"type": "text", "text": "OK"}]}
        result, server = self.run_check("messages", {("POST", "llm", "/v1/messages"): answer(body)})
        self.assertTrue(result.ok, result.lines)
        headers = server.requests[0][4]
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertEqual(server.requests[0][3]["model"], "local-haiku")

    def test_messages_without_text(self):
        body = {"type": "message", "content": []}
        result, _ = self.run_check("messages", {("POST", "llm", "/v1/messages"): answer(body)})
        self.assertFalse(result.ok)

    def test_embeddings(self):
        body = {"data": [{"embedding": [0.1] * 1024}]}
        result, _ = self.run_check("embeddings", {("POST", "llm", "/v1/embeddings"): answer(body)})
        self.assertTrue(result.ok)
        self.assertIn("1024-dimension", result.lines[0])

    def test_rerank_ranks_the_match_first(self):
        body = {"results": [{"index": 1, "relevance_score": 0.01}, {"index": 0, "relevance_score": 0.98}]}
        result, _ = self.run_check("rerank", {("POST", "llm", "/v1/rerank"): answer(body)})
        self.assertTrue(result.ok, result.lines)

    def test_rerank_falls_back_to_the_cohere_path(self):
        body = {"results": [{"index": 0, "relevance_score": 0.9}, {"index": 1, "relevance_score": 0.1}]}
        result, server = self.run_check("rerank", {("POST", "llm", "/rerank"): answer(body)})
        self.assertTrue(result.ok, result.lines)
        self.assertEqual([request[2] for request in server.requests], ["/v1/rerank", "/rerank"])

    def test_rerank_wrong_order_fails(self):
        body = {"results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1}]}
        result, _ = self.run_check("rerank", {("POST", "llm", "/v1/rerank"): answer(body)})
        self.assertFalse(result.ok)

    def test_search_json(self):
        result, _ = self.run_check("search", {("GET", "search", "/search"): answer({"results": [{}, {}]})})
        self.assertTrue(result.ok)
        self.assertIn("2 results", result.lines[0])

    def test_search_html_is_a_failure(self):
        page = answer(b"<html></html>", content_type="text/html")
        result, _ = self.run_check("search", {("GET", "search", "/search"): page})
        self.assertFalse(result.ok)

    def test_mcp_initialize_over_sse_and_json(self):
        initialized = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"protocolVersion": "2025-06-18", "serverInfo": {"name": "s"}},
        }
        sse = ("event: message\ndata: " + json.dumps(initialized) + "\n\n").encode()
        routes = {
            ("POST", "mcp", "/servers/searxng/mcp"): smoke.Response(
                200, {"content-type": "text/event-stream", "mcp-session-id": "abc"}, sse
            ),
            ("POST", "mcp", "/servers/fetch/mcp"): answer(initialized),
            ("POST", "mcp", "/servers/kb/mcp"): answer(initialized),
        }
        result, server = self.run_check("mcp", routes)
        self.assertTrue(result.ok, result.lines)
        first = server.requests[0]
        self.assertEqual(first[3]["method"], "initialize")
        self.assertEqual(first[4]["Authorization"], "Bearer token-example")
        self.assertIn("text/event-stream", first[4]["Accept"])
        deletes = [request for request in server.requests if request[0] == "DELETE"]
        self.assertEqual(deletes[0][4]["Mcp-Session-Id"], "abc")

    def test_mcp_unauthorized(self):
        routes = {("POST", "mcp", f"/servers/{name}/mcp"): answer({}, 401) for name in smoke.MCP_SERVERS}
        result, _ = self.run_check("mcp", routes)
        self.assertFalse(result.ok)
        self.assertIn("HTTP 401", result.lines[0])

    def test_http_refuses_plain_http(self):
        with self.assertRaises(smoke.CheckFailed):
            smoke.http(settings(), "GET", "http://llm.lab.example.com/v1/models")


class TestRunner(unittest.TestCase):
    def test_gpu_checks_run_one_after_the_other_and_order_is_fixed(self):
        active = []
        overlap = []
        lock = threading.Lock()

        def gpu_check(_settings):
            with lock:
                active.append(1)
                if len(active) > 1:
                    overlap.append(True)
            with lock:
                active.pop()
            return ["fine"]

        functions = {name: (lambda _s: ["fine"]) for name in smoke.CHECKS}
        functions["chat"] = gpu_check
        functions["messages"] = gpu_check
        out = io.StringIO()
        code = smoke.main(
            ["--env-file", "/nonexistent"], out=out, functions=functions, environ={"LAB_DOMAIN": "lab.example.com"}
        )
        self.assertEqual(code, 0)
        self.assertEqual(overlap, [])
        names = [line.split()[1] for line in out.getvalue().splitlines() if line.startswith(("ok ", "FAIL "))]
        self.assertEqual(names, list(smoke.CHECKS))

    def test_only_and_failure_exit(self):
        def failing(_settings):
            raise smoke.CheckFailed("nope")

        out = io.StringIO()
        code = smoke.main(
            ["--only", "search", "--env-file", "/nonexistent"],
            out=out,
            functions={"search": failing},
            environ={"LAB_DOMAIN": "lab.example.com"},
        )
        self.assertEqual(code, 1)
        self.assertIn("FAIL search\n  nope", out.getvalue())

    def test_domain_is_required(self):
        self.assertEqual(smoke.main(["--env-file", "/nonexistent"], out=io.StringIO(), environ={}), 2)

    def test_env_file_fills_what_the_environment_lacks(self):
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as handle:
            handle.write(
                "# client\nLOCAL_LLM_KEY='sk-local-example'\nexport MCP_HUB_TOKEN=t\nLAB_DOMAIN=file.example.com\n"
            )
        self.addCleanup(Path(handle.name).unlink)
        args = argparse.Namespace(cafile=None, timeout=5.0, env_file=handle.name)
        result = smoke.make_settings(args, {"LAB_DOMAIN": "lab.example.com"})
        self.assertEqual(result.domain, "lab.example.com")
        self.assertEqual(result.llm_key, "sk-local-example")
        self.assertEqual(result.mcp_token, "t")


if __name__ == "__main__":
    unittest.main()
