// law-bench admin-assistant CopilotKit runtime.
//
// Sits entirely inside the k3s cluster: the FastAPI /copilotkit proxy (the only
// public path, admin-scope gated) forwards here. The node-http endpoint speaks
// CopilotKit's single-route JSON protocol (POST {method, params, body}; the
// chat method is "agent/run" streaming AG-UI events over SSE), routed to a
// registered BuiltInAgent:
//   - model via @ai-sdk/openai pointed at the GLM/DeepSeek OpenAI-compatible
//     endpoint (OPENAI_BASE_URL + OPENAI_API_KEY from the copilot-runtime
//     secret);
//   - tools from the dedicated law-bench-mcp-assistant instance over
//     streamable HTTP with the shared token (X-API-Key).
//
// Defense in depth: the server-side MCP instance runs with MCP_TOOL_DENYLIST
// (destructive tools never advertised), and this client filters the same names
// again in tools() in case it is ever pointed at an instance without the
// denylist.

import { createServer } from "node:http";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { createOpenAI } from "@ai-sdk/openai";
import { BuiltInAgent, CopilotRuntime } from "@copilotkit/runtime/v2";
import { createCopilotNodeListener } from "@copilotkit/runtime/v2/node";

const PORT = Number(process.env.PORT || 3111);
const ENDPOINT = process.env.COPILOT_ENDPOINT || "/copilotkit";
// LLM defaults: the shared token-vault gateway (OpenRouter-compatible API —
// sk-or keys, "vendor/model" ids, plain OpenAI chat-completions protocol).
const LLM_BASE_URL = process.env.OPENAI_BASE_URL || "https://api.openai.com/v1";
const MODEL = process.env.COPILOT_MODEL || "deepseek/deepseek-v4.1-flash";
const MCP_URL =
  process.env.COPILOT_MCP_URL ||
  "http://law-bench-mcp-assistant.law-bench.svc.cluster.local/mcp";
const MCP_TOKEN = process.env.COPILOT_MCP_TOKEN || "";
// Same list as the MCP instance's MCP_TOOL_DENYLIST; names here are dropped
// from what the agent hands the model even if the server did not filter.
const TOOL_DENYLIST = new Set(
  (
    process.env.COPILOT_TOOL_DENYLIST ||
    "clause_delete,rubric_delete,criterion_delete,prompt_delete"
  )
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean),
);

const ASSISTANT_PROMPT =
  "You are the law-bench workbench assistant for an administrator. " +
  "Use the available tools to answer questions about contracts, rubrics, " +
  "prompts, evaluations and clauses: search clauses, generate contracts, " +
  "evaluate drafts, inspect runs and law references. Deletion tools are " +
  "not available by design — if asked to delete something, explain that " +
  "deletion must be done from the regular workbench pages. Reply in the " +
  "language the user writes in (usually Chinese).";

if (!process.env.OPENAI_API_KEY) {
  console.error("OPENAI_API_KEY is required; refusing to start");
  process.exit(1);
}
if (!MCP_TOKEN) {
  console.error("COPILOT_MCP_TOKEN is required; refusing to start");
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Lazy MCP client (user-managed): connects on first tools() call and
// reconnects once on a stale session. CopilotKit's BuiltInAgent accepts it
// via mcpClients and deliberately does not close user-managed clients.

let mcpClient = null;

async function getMcpClient() {
  if (mcpClient) return mcpClient;
  const client = new Client({ name: "lawbench-copilot-runtime", version: "0.1.0" });
  const transport = new StreamableHTTPClientTransport(MCP_URL, {
    requestInit: { headers: { "X-API-Key": MCP_TOKEN } },
  });
  await client.connect(transport);
  mcpClient = client;
  return client;
}

const lawbenchMcp = {
  async tools() {
    let client;
    try {
      client = await getMcpClient();
    } catch (err) {
      console.error(`MCP connect to ${MCP_URL} failed:`, err.message);
      throw err;
    }
    let listed;
    try {
      listed = await client.listTools();
    } catch (err) {
      // Stale session (restart of the MCP pod, idle timeout) — drop the
      // cached client and reconnect once before surfacing the error.
      mcpClient = null;
      client = await getMcpClient();
      listed = await client.listTools();
    }
    const tools = {};
    for (const t of listed.tools) {
      if (TOOL_DENYLIST.has(t.name)) continue;
      const inputSchema = t.inputSchema || {};
      tools[t.name] = {
        description: t.description,
        schema: {
          parameters: {
            properties: inputSchema.properties || {},
            required: inputSchema.required || [],
          },
        },
        execute: async (params) => {
          const result = await client.callTool({ name: t.name, arguments: params || {} });
          // Flatten MCP content blocks to text so the model sees strings.
          if (Array.isArray(result?.content)) {
            return result.content
              .map((block) =>
                block.type === "text" ? block.text : JSON.stringify(block),
              )
              .join("\n");
          }
          return result;
        },
      };
    }
    return tools;
  },
};

// ---------------------------------------------------------------------------

const provider = createOpenAI({
  apiKey: process.env.OPENAI_API_KEY,
  baseURL: LLM_BASE_URL,
});

const agent = new BuiltInAgent({
  // .chat() pins the chat-completions endpoint: the provider default targets
  // OpenAI's /responses API, which the Ark-compatible endpoint does not serve
  // (404).
  model: provider.chat(MODEL),
  mcpClients: [lawbenchMcp],
  prompt: ASSISTANT_PROMPT,
  maxSteps: 10,
});

// Register under both ids: "copilotkit" is the classic default the v1 React
// provider sends, "default" is a common fallback.
const runtime = new CopilotRuntime({
  agents: { copilotkit: agent, default: agent },
});

// Node listener: basePath strips /copilotkit; single-route mode serves the
// JSON envelope ({method, params, body} posted at the base) that the island's
// v1 React provider speaks (multi-route mode would 404 it with
// single_route_envelope_against_multi_route_runtime).
const copilotHandler = createCopilotNodeListener({
  runtime,
  basePath: ENDPOINT,
  mode: "single-route",
});

createServer((req, res) => {
  if (req.url === "/health") {
    res.writeHead(200, { "content-type": "text/plain" });
    res.end("ok");
    return;
  }
  Promise.resolve(copilotHandler(req, res)).catch((err) => {
    console.error("copilot handler error:", err);
    if (!res.headersSent) {
      res.writeHead(502, { "content-type": "text/plain" });
    }
    res.end("copilot runtime error");
  });
}).listen(PORT, () => {
  console.log(`copilot runtime listening on :${PORT}${ENDPOINT} (model ${MODEL}, mcp ${MCP_URL})`);
});
