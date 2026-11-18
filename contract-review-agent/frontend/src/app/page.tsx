"use client";

import { useState } from "react";
import { Chat } from "../components/chat";
import { StatePanel } from "../components/state-panel";
import { MetricsPanel } from "../components/metrics-panel";
import { RubricPanel } from "../components/rubric-panel";

export type ChatResult = {
  thread_id: string;
  contract_type: string;
  draft: string;
  slots: string[];
  reviews: any[];
  synthesized_suggestions: any[];
  quiz_items: any[];
  eval_result: any;
  deepeval_scores: any;
  node_timings: Record<string, number>;
  model_calls: any[];
  errors: any[];
  total_duration: number;
};

export default function Home() {
  const [result, setResult] = useState<ChatResult | null>(null);

  return (
    <div className="h-screen flex flex-col bg-slate-50">
      {/* Top header */}
      <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-brand-600 to-brand-500 flex items-center justify-center text-white text-lg">
            ⚖️
          </div>
          <div>
            <h1 className="text-base font-semibold text-slate-900">
              Contract Review Agent
            </h1>
            <p className="text-xs text-slate-500">
              多模型合同评审 · 3 个 AI 并行分析 · 双重评估
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-green-50 text-green-700 border border-green-200">
            <span className="w-1.5 h-1.5 rounded-full bg-green-500"></span>
            在线
          </span>
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 flex overflow-hidden">
        {/* Left: Chat */}
        <div className="w-[400px] border-r border-slate-200 flex-shrink-0">
          <Chat onResult={setResult} />
        </div>

        {/* Right: Results */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {result === null ? (
            <EmptyState />
          ) : (
            <>
              <RubricPanel result={result} />
              <StatePanel result={result} />
              <MetricsPanel result={result} />
            </>
          )}
        </div>
      </main>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="h-full flex items-center justify-center">
      <div className="text-center max-w-md">
        <div className="text-6xl mb-4">📋</div>
        <h2 className="text-lg font-semibold text-slate-700 mb-2">
          等待评审开始
        </h2>
        <p className="text-sm text-slate-400 leading-relaxed">
          在左侧聊天框输入消息（例如「生成一份农产品买卖合同」），
          系统会用 3 个 AI 评审员并行分析合同，并给出双重评估结果。
        </p>
        <div className="mt-6 grid grid-cols-3 gap-3 text-xs">
          <div className="bg-white rounded-lg p-3 border border-slate-200">
            <div className="text-2xl mb-1">⚖️</div>
            <div className="font-medium text-slate-600">法律审查</div>
          </div>
          <div className="bg-white rounded-lg p-3 border border-slate-200">
            <div className="text-2xl mb-1">💼</div>
            <div className="font-medium text-slate-600">商业公平</div>
          </div>
          <div className="bg-white rounded-lg p-3 border border-slate-200">
            <div className="text-2xl mb-1">✅</div>
            <div className="font-medium text-slate-600">完整性检查</div>
          </div>
        </div>
      </div>
    </div>
  );
}
