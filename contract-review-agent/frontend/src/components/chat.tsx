"use client";

import { useState } from "react";
import type { ChatResult } from "../app/page";

type Message = {
  role: "user" | "assistant";
  content: string;
};

export function Chat({ onResult }: { onResult: (r: ChatResult | null) => void }) {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "👋 你好！我是合同评审助手。\n\n我可以帮你生成合同，并用 3 个 AI 评审员（法律、商业、完整性）并行审查，最后给出双重评估。\n\n试试输入：「生成一份农产品买卖合同」",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  const send = async () => {
    if (!input.trim() || loading) return;
    const userMsg = input.trim();
    setMessages((m) => [...m, { role: "user", content: userMsg }]);
    setInput("");
    setLoading(true);
    onResult(null);

    try {
      const backendUrl =
        process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
      const res = await fetch(`${backendUrl}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: userMsg,
          contract_type: "sale",
          scenario: "农产品买卖",
        }),
      });
      const data: ChatResult = await res.json();
      onResult(data);
      setMessages((m) => [
        ...m,
        { role: "assistant", content: formatResult(data) },
      ]);
    } catch (e: any) {
      setMessages((m) => [
        ...m,
        { role: "assistant", content: `❌ 出错：${e.message}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Header */}
      <div className="px-4 py-3 border-b bg-gradient-to-r from-brand-600 to-brand-500 text-white">
        <div className="flex items-center gap-2">
          <span className="text-lg">🤖</span>
          <div>
            <div className="font-semibold text-sm">合同评审助手</div>
            <div className="text-xs text-brand-50">
              {loading ? "正在评审中..." : "在线 · 3个AI模型待命"}
            </div>
          </div>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3 bg-slate-50">
        {messages.map((m, i) => (
          <div
            key={i}
            className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap leading-relaxed ${
                m.role === "user"
                  ? "bg-brand-600 text-white rounded-br-sm"
                  : "bg-white border border-slate-200 text-slate-700 rounded-bl-sm shadow-sm"
              }`}
            >
              {m.content}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-white border border-slate-200 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm">
              <div className="flex items-center gap-1">
                <span className="typing-dot"></span>
                <span className="typing-dot"></span>
                <span className="typing-dot"></span>
                <span className="text-xs text-slate-400 ml-2">
                  3个模型并行评审中...
                </span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t bg-white p-3">
        <div className="flex gap-2 items-end">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder="输入消息，例如：生成一份农产品买卖合同"
            disabled={loading}
            rows={1}
            className="flex-1 resize-none px-3 py-2 border border-slate-300 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent max-h-24"
          />
          <button
            onClick={send}
            disabled={loading || !input.trim()}
            className="px-4 py-2 bg-brand-600 text-white rounded-xl text-sm font-medium hover:bg-brand-700 disabled:bg-slate-300 disabled:cursor-not-allowed transition-colors flex-shrink-0"
          >
            {loading ? "..." : "发送"}
          </button>
        </div>
        <p className="text-xs text-slate-400 mt-1.5 px-1">
          ⏱ 评审流程约需 2-4 分钟（3模型并行 + 双重评估）
        </p>
      </div>
    </div>
  );
}

function formatResult(data: ChatResult): string {
  const ev = data.eval_result || {};
  const reviews = data.reviews || [];
  const suggestions = data.synthesized_suggestions || [];
  const deepeval = data.deepeval_scores || {};
  const errors = data.errors || [];

  let out = `✅ 评审完成（${data.total_duration}s）\n\n`;
  out += `📋 规则评估：${ev.n_passed || 0}/${ev.n_criteria || 0} 项通过\n`;

  if (reviews.length > 0) {
    out += `\n🔍 评审员反馈：\n`;
    reviews.forEach((r, i) => {
      out += `  ${i + 1}. ${r.name} · ${r.lens}\n     ${r.suggestions?.length || 0} 条建议`;
      if (r.error) out += ` ⚠️`;
      out += "\n";
    });
  }

  if (suggestions.length > 0) {
    out += `\n📝 综合建议（${suggestions.length}条）\n`;
  }

  if (Object.keys(deepeval).length > 0) {
    out += `\n📈 DeepEval 已运行\n`;
  }

  out += `\n📄 合同已生成（${data.draft.length} 字符）\n👉 详细结果见右侧面板`;
  return out;
}
