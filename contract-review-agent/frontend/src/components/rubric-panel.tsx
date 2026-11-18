"use client";

import type { ChatResult } from "../app/page";

export function RubricPanel({ result }: { result: ChatResult | null }) {
  const eval_result = result?.eval_result || {};
  const passed = (eval_result.n_passed || 0) as number;
  const total = (eval_result.n_criteria || 10) as number;
  const summary = eval_result.summary as string;

  if (!result || !summary) return null;

  // Mock criteria data (from database query)
  // In production, this should come from an API call
  const mockCriteria = [
    { id: "party_identification", title: "合同主体识别", verdict: "pass", description: "是否清晰识别全部合同主体，载明完整法律名称与角色（甲方/乙方）？" },
    { id: "governing_law_present", title: "适用法律约定", verdict: "pass", description: "是否明确约定适用法律（如中华人民共和国法律）？" },
    { id: "clause_completeness", title: "核心条款完备", verdict: "pass", description: "是否具备该类合同的核心必备条款（如违约责任、争议解决、合同期限等）？" },
    { id: "delivery_terms", title: "交付条款", verdict: "pass", description: "是否明确约定交付方式、时间、地点及风险转移？" },
    { id: "payment_terms", title: "支付条款", verdict: "pass", description: "是否明确约定价款、支付方式、支付时间？" },
    { id: "quality_standard", title: "质量标准", verdict: "pass", description: "是否明确约定质量标准、验收依据？" },
    { id: "breach_liability", title: "违约责任", verdict: "pass", description: "是否约定违约情形及责任承担方式？" },
    { id: "ownership_transfer", title: "所有权转移", verdict: "fail", description: "是否约定标的物所有权转移的时点（交付或登记）？" },
    { id: "inspection_period", title: "检验期间", verdict: "fail", description: "是否约定检验期间与质量异议期限？" },
    { id: "retention_title", title: "所有权保留", verdict: "fail", description: "所有权保留条款是否合法且表述清晰（如分期付款）？" },
  ];

  const passList = mockCriteria.filter(c => c.verdict === "pass");
  const failList = mockCriteria.filter(c => c.verdict === "fail");

  const passRate = Math.round((passed / total) * 100);

  return (
    <div className="space-y-4">
      {/* Progress bar */}
      <div className="bg-white rounded-xl border border-slate-200 p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-slate-700 flex items-center gap-2">
            <span>📋</span>
            Rubric 规则评估
          </h3>
          <div className="flex items-center gap-2">
            <span className={`px-2 py-1 rounded-full text-xs font-medium ${
              passRate >= 80 ? "bg-green-100 text-green-700" :
              passRate >= 50 ? "bg-amber-100 text-amber-700" :
              "bg-red-100 text-red-700"
            }`}>
              {passed}/{total} ({passRate}%)
            </span>
          </div>
        </div>

        {/* Progress bar */}
        <div className="h-2 bg-slate-100 rounded-full overflow-hidden mb-2">
          <div
            className={`h-full transition-all ${
              passRate >= 80 ? "bg-green-500" :
              passRate >= 50 ? "bg-amber-400" :
              "bg-red-500"
            }`}
            style={{ width: `${passRate}%` }}
          />
        </div>

        <p className="text-xs text-slate-500">{summary}</p>
      </div>

      {/* Pass Criteria */}
      {passList.length > 0 && (
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <h3 className="text-sm font-semibold text-green-700 mb-3 flex items-center gap-2">
            <span className="w-5 h-5 rounded-full bg-green-100 flex items-center justify-center text-xs">✓</span>
            已达标项 ({passList.length})
          </h3>
          <div className="space-y-2">
            {passList.map((c) => (
              <div key={c.id} className="border border-green-200 rounded-lg p-2.5 hover:bg-green-50 transition-colors">
                <div className="flex items-start gap-2">
                  <span className="text-green-600 mt-0.5">✓</span>
                  <div className="flex-1">
                    <div className="text-sm font-medium text-slate-800">{c.title}</div>
                    <div className="text-xs text-slate-500 mt-0.5">{c.description}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Fail Criteria */}
      {failList.length > 0 && (
        <div className="bg-white rounded-xl border border-red-200 p-4">
          <h3 className="text-sm font-semibold text-red-700 mb-3 flex items-center gap-2">
            <span className="w-5 h-5 rounded-full bg-red-100 flex items-center justify-center text-xs">✕</span>
            需改进项 ({failList.length})
          </h3>
          <div className="space-y-2">
            {failList.map((c) => (
              <div key={c.id} className="border border-red-200 rounded-lg p-2.5 hover:bg-red-50 transition-colors">
                <div className="flex items-start gap-2">
                  <span className="text-red-600 mt-0.5">✕</span>
                  <div className="flex-1">
                    <div className="text-sm font-medium text-slate-800">{c.title}</div>
                    <div className="text-xs text-slate-500 mt-0.5">{c.description}</div>
                    <div className="text-xs text-red-500 mt-1 italic">建议补充相关条款</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
