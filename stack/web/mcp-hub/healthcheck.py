#!/usr/bin/env python3
"""Container health check for mcp-hub (stack/web/compose.yaml).

Calls mcp-proxy's /status endpoint on the loopback address with the bearer token and reports
healthy only when every named server (searxng, fetch, kb) started. mcp-proxy skips a server
whose process fails to start and marks it "failed" in /status, so a plain HTTP check would
miss it. Standard library only; exit 0 = healthy, 1 = unhealthy.
"""

import json
import os
import sys
import urllib.request

STATUS_URL = "http://127.0.0.1:8096/status"


def main() -> int:
    token = os.environ.get("MCP_PROXY_AUTH_TOKEN", "")
    request = urllib.request.Request(STATUS_URL, headers={"Authorization": f"Bearer {token}"})
    try:
        # Fixed http:// URL on the loopback interface; no user input reaches it.
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
            status = json.load(response)
    except Exception as error:  # any failure (refused, 401, timeout, bad JSON) means unhealthy
        print(f"unhealthy: {error}")
        return 1
    instances = status.get("server_instances", {})
    failed = {name: state for name, state in instances.items() if state != "configured"}
    if not instances or failed:
        print(f"unhealthy: {failed or 'no servers configured'}")
        return 1
    print("ok: " + ", ".join(sorted(instances)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
