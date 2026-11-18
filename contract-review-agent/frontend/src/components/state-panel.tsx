"use client";

import type { ChatResult } from "../app/page";

const NODE_LABELS: Record<string, string> = {
  generate_v1: "生成草案",
  review_panel: "多模型评审",
  synthesize: "综合建议",
  generate_quiz: "生成填槽",
  generate_v2: "生成终稿",
  evaluate: "双重评估",
  export: "导出文档",
};

const NODE_ICONS: Record<string, string> = {
  generate_v1: "📝",
  review_panel: "🔍",
  synthesize: "🔀",
  generate_quiz: "❓",
  generate_v2: "📄",
  evaluate: "📊",
  export: "📤",
};

export function StatePanel({ result }: { result: ChatResult | null }) {
  const timings = result?.node_timings || {};
  const reviews = result?.reviews || [];
  const suggestions = result?.synthesized_suggestions || [];
  const errors = (result?.errors || []).filter(
    (e) => !e.message?.includes("isn't mapped")
  );

  return (
    <div className="space-y-4">
      {/* Node timings */}
      <div className="bg-white rounded-xl border border-slate-200 p-4">
        <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
          <span>⏱</span> 执行流程
          <span className="ml-auto text-xs font-normal text-slate-400">
            总耗时 {result?.total_duration || 0}s
          </span>
        </h3>
        <div className="space-y-1.5">
          {Object.entries(NODE_LABELS).map(([node, label]) => {
            const t = timings[node];
            if (t === undefined) return null;
            return (
              <div
                key={node}
                className="flex items-center gap-3 px-3 py-2 rounded-lg bg-green-50 border border-green-100"
              >
                <span className="text-base">{NODE_ICONS[node]}</span>
                <span className="text-sm text-slate-700 flex-1">{label}</span>
                <span className="text-xs font-mono text-slate-500">{t}s</span>
                <span className="text-green-600 text-xs">✓</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Reviews */}
      {reviews.length > 0 && (
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
            <span>🔍</span> 评审员反馈
            <span className="ml-auto text-xs font-normal text-slate-400">
              {reviews.length} 个模型
            </span>
          </h3>
          <div className="space-y-2">
            {reviews.map((r, i) => {
              const suggCount = r.suggestions?.length || 0;
              return (
                <div
                  key={i}
                  className="border border-slate-200 rounded-lg p-3 hover:border-brand-300 transition-colors"
                >
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="font-medium text-sm text-slate-800">
                      {r.name}
                    </span>
                    <span className="text-[10px] px-1.5 py-0.5 bg-brand-50 text-brand-700 rounded font-medium">
                      {r.lens}
                    </span>
                    {r.error && (
                      <span className="text-[10px] px-1.5 py-0.5 bg-amber-50 text-amber-700 rounded">
                        ⚠️
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 text-xs text-slate-500">
                    <span>{r.model}</span>
                    <span>·</span>
                    <span>{suggCount} 条建议</span>
                    <span>·</span>
                    <span>{r.timing}s</span>
                    {r.tokens > 0 && (
                      <>
                        <span>·</span>
                        <span>{r.tokens} tokens</span>
                      </>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Suggestions */}
      {suggestions.length > 0 && (
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
            <span>📝</span> 综合建议
            <span className="ml-auto text-xs font-normal text-slate-400">
              {suggestions.length} 条
            </span>
          </h3>
          <div className="space-y-2">
            {suggestions.slice(0, 10).map((s, i) => {
              const color =
                s.severity === "critical"
                  ? "border-l-red-500 bg-red-50"
                  : s.severity === "warning"
                  ? "border-l-amber-500 bg-amber-50"
                  : "border-l-slate-400 bg-slate-50";
              const badge =
                s.severity === "critical"
                  ? "bg-red-100 text-red-700"
                  : s.severity === "warning"
                  ? "bg-amber-100 text-amber-700"
                  : "bg-slate-200 text-slate-600";
              return (
                <div
                  key={i}
                  className={`border-l-2 ${color} rounded-r-lg p-2.5`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${badge}`}
                    >
                      {s.severity}
                    </span>
                    <span className="text-xs font-medium text-slate-700">
                      {s.section}
                    </span>
                  </div>
                  <p className="text-xs text-slate-600 leading-relaxed">
                    {s.recommendation}
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Errors (non-model-mapping) */}
      {errors.length > 0 && (
        <div className="bg-white rounded-xl border border-amber-200 p-4">
          <h3 className="text-sm font-semibold text-amber-700 mb-2 flex items-center gap-2">
            <span>⚠️</span> 警告
            <span className="ml-auto text-xs font-normal text-slate-400">
              {errors.length} 条
            </span>
          </h3>
          <div className="space-y-1">
            {errors.slice(0, 5).map((e, i) => (
              <div key={i} className="text-xs text-slate-500">
                <span className="font-mono text-amber-600">[{e.node}]</span>{" "}
                {e.message?.slice(0, 80)}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
