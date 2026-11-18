// MCP smoke check for the law-bench admin-assistant wiring.
//
// Connects to a law-bench MCP streamable-HTTP instance exactly the way
// server.mjs does (X-API-Key shared token), lists tools, and verifies the
// destructive denylist is absent. Run against any instance:
//
//   COPILOT_MCP_URL=http://127.0.0.1:8199/mcp \
//   COPILOT_MCP_TOKEN=<token> \
//   node scripts/mcp-smoke.mjs
//
// Exit 0 = denylist respected; exit 1 = a denylisted tool is advertised or
// the connection failed.
//
// Windows caveat: after a tool call the SDK leaves a streaming handle that can
// trip a libuv assert during process teardown, overwriting the exit code with
// 127 — on Windows judge by stdout ("OK:"/"FAIL:" lines). The exit code is
// reliable on Linux (the deploy/CI target).

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

const url = process.env.COPILOT_MCP_URL || "http://127.0.0.1:8199/mcp";
const token = process.env.COPILOT_MCP_TOKEN;
const denylist = (
  process.env.COPILOT_TOOL_DENYLIST ||
  "clause_delete,rubric_delete,criterion_delete,prompt_delete"
)
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

if (!token) {
  console.error("COPILOT_MCP_TOKEN is required");
  process.exit(1);
}

const client = new Client({ name: "mcp-smoke", version: "0.1.0" });
const transport = new StreamableHTTPClientTransport(url, {
  requestInit: { headers: { "X-API-Key": token } },
});

// Explicit transport close keeps the Windows exit code clean; without it the
// SDK's dangling async handle trips a libuv assert on process teardown.
async function shutdown(code) {
  await transport.close().catch(() => {});
  await client.close().catch(() => {});
  process.exit(code);
}

try {
  await client.connect(transport);
  const { tools } = await client.listTools();
  const names = new Set(tools.map((t) => t.name));
  console.log(`connected to ${url}: ${names.size} tools advertised`);

  const leaked = denylist.filter((name) => names.has(name));
  if (leaked.length) {
    console.error(`FAIL: denylisted tools are advertised: ${leaked.join(", ")}`);
    await shutdown(1);
  }
  console.log(`OK: none of the denylisted tools (${denylist.join(", ")}) are advertised`);

  // A denylisted tool call must fail as unknown rather than execute. The raw
  // SDK surfaces the failure as a result envelope with isError=true (the MCP
  // protocol's error form), not as a thrown exception.
  const probe = denylist[0];
  const result = await client.callTool({ name: probe, arguments: {} });
  const text = (result.content || [])
    .map((block) => (block.type === "text" ? block.text : ""))
    .join(" ");
  if (result.isError && /unknown tool/i.test(text)) {
    console.log(`OK: ${probe} call rejected as unknown tool (${text.slice(0, 60)})`);
  } else {
    console.error(
      `FAIL: denylisted tool ${probe} did not fail as unknown tool: ${JSON.stringify(result).slice(0, 200)}`,
    );
    await shutdown(1);
  }
  await shutdown(0);
} catch (err) {
  console.error(`FAIL: could not connect to ${url}: ${err.message}`);
  await shutdown(1);
}
