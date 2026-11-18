"use client";

import type { ChatResult } from "../app/page";

export function MetricsPanel({ result }: { result: ChatResult | null }) {
  const modelCalls = result?.model_calls || [];
  const totalTokens = modelCalls.reduce(
    (sum: number, call: any) => sum + (call.tokens || 0),
    0
  );
  const ev = result?.eval_result || {};
  const deepeval = result?.deepeval_scores || {};
  const passRate =
    ev.n_criteria > 0
      ? Math.round(((ev.n_passed || 0) / ev.n_criteria) * 100)
      : 0;

  return (
    <div className="space-y-4">
      {/* Metrics cards */}
      <div className="grid grid-cols-2 gap-3">
        <MetricCard
          icon="⏱"
          label="总耗时"
          value={`${result?.total_duration || 0}s`}
        />
        <MetricCard
          icon="🤖"
          label="模型调用"
          value={`${modelCalls.length} 次`}
        />
        <MetricCard
          icon="🎯"
          label="Token 用量"
          value={totalTokens.toLocaleString()}
        />
        <MetricCard
          icon="📋"
          label="规则评估"
          value={`${ev.n_passed || 0}/${ev.n_criteria || 0}`}
          subtitle={`${passRate}% 通过`}
          highlight={ev.all_pass ? "green" : passRate >= 50 ? "amber" : "red"}
        />
      </div>

      {/* DeepEval scores */}
      {Object.keys(deepeval).length > 0 && (
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
            <span>📈</span> DeepEval 指标
          </h3>
          <div className="space-y-2">
            {Object.entries(deepeval).map(([k, v]: [string, any]) => {
              if (!v || typeof v !== "object") return null;
              const score = v.score ?? 0;
              const success = v.success;
              return (
                <div key={k} className="flex items-center gap-3">
                  <span className="text-xs text-slate-600 w-28 capitalize">
                    {k}
                  </span>
                  <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${
                        success ? "bg-green-500" : "bg-amber-400"
                      }`}
                      style={{ width: `${Math.round(score * 100)}%` }}
                    />
                  </div>
                  <span className="text-xs font-mono text-slate-500 w-10 text-right">
                    {score.toFixed(2)}
                  </span>
                  <span className="text-xs w-4">
                    {success ? "✓" : "✗"}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Contract preview */}
      {result?.draft && (
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
            <span>📄</span> 合同预览
            <span className="ml-auto text-xs font-normal text-slate-400">
              {result.draft.length} 字符
            </span>
          </h3>
          <pre className="text-xs font-mono text-slate-600 bg-slate-50 p-3 rounded-lg max-h-96 overflow-y-auto whitespace-pre-wrap leading-relaxed border border-slate-100">
            {result.draft}
          </pre>
        </div>
      )}
    </div>
  );
}

function MetricCard({
  icon,
  label,
  value,
  subtitle,
  highlight,
}: {
  icon: string;
  label: string;
  value: string;
  subtitle?: string;
  highlight?: "green" | "amber" | "red";
}) {
  const borderColor =
    highlight === "green"
      ? "border-green-200"
      : highlight === "amber"
      ? "border-amber-200"
      : highlight === "red"
      ? "border-red-200"
      : "border-slate-200";
  const subColor =
    highlight === "green"
      ? "text-green-600"
      : highlight === "amber"
      ? "text-amber-600"
      : highlight === "red"
      ? "text-red-600"
      : "text-slate-400";
  return (
    <div
      className={`bg-white rounded-xl border ${borderColor} p-3.5`}
    >
      <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-1">
        <span>{icon}</span>
        <span>{label}</span>
      </div>
      <div className="text-lg font-semibold text-slate-800">{value}</div>
      {subtitle && (
        <div className={`text-xs ${subColor} mt-0.5`}>{subtitle}</div>
      )}
    </div>
  );
}
