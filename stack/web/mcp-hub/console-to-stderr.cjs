// Preloaded with `node --require` for the kb server (servers.json). A stdio MCP server must
// write only JSON-RPC to stdout, but open-webui-knowledge-mcp-server 0.2.0 prints two banner
// lines with console.info at start-up, which mcp-proxy logs as "Failed to parse JSONRPC
// message". Sending console.log/info/debug to stderr keeps the banners in the container log
// and stdout clean. The MCP SDK writes its messages with process.stdout.write, unaffected.
"use strict";

console.log = console.error;
console.info = console.error;
console.debug = console.error;
