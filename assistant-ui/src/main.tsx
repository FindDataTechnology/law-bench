/**
 * law-bench admin-assistant island (change add-admin-copilot-assistant).
 *
 * Self-mounting CopilotPopup: base.html includes the built bundle only for
 * sessions holding the admin scope, so this file never runs for anyone else.
 * All traffic goes to the same-origin /copilotkit route (session cookie),
 * which is the sole public path to the CopilotKit runtime and its MCP tools.
 */
import { CopilotKit } from "@copilotkit/react-core";
import { CopilotPopup } from "@copilotkit/react-ui";
import "@copilotkit/react-ui/styles.css";
import { createRoot } from "react-dom/client";

function AssistantIsland() {
  return (
    // useSingleEndpoint pins the {method, params, body} envelope: the runtime
    // is mounted single-route, and the default "auto" transport negotiation
    // kept re-probing /info without ever issuing the agent run. The
    // single-route transport resolves its endpoints with new URL(...), so the
    // runtime URL must be absolute — a bare "/copilotkit" throws Invalid URL.
    <CopilotKit
      runtimeUrl={new URL("/copilotkit", window.location.origin).href}
      useSingleEndpoint
    >
      <CopilotPopup
        instructions={
          "You are the law-bench workbench assistant for an administrator. " +
          "Use the available tools to answer questions about contracts, rubrics, " +
          "prompts, evaluations and clauses: search clauses, generate contracts, " +
          "evaluate drafts, inspect runs and law references. Deletion tools are " +
          "not available by design — if asked to delete something, explain that " +
          "deletion must be done from the regular workbench pages. Reply in the " +
          "language the user writes in (usually Chinese)."
        }
        labels={{
          title: "Law Bench 助手",
          placeholder: "例如：帮我生成一份农产品买卖合同（ pro_a 立场）…",
          initial: "您好，我是 law-bench 助手。可以帮您检索条款、生成合同、运行评估。删除类操作不支持，请到对应页面操作。",
        }}
        shortcut="Ctrl-."
        defaultOpen={false}
      />
    </CopilotKit>
  );
}

const mount = document.getElementById("lawbench-assistant-root");
if (mount) {
  createRoot(mount).render(<AssistantIsland />);
}
