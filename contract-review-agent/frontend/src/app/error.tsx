"use client";

import { useEffect } from "react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Page error:", error);
  }, [error]);

  return (
    <div style={{ padding: 40, fontFamily: "system-ui, sans-serif" }}>
      <h2 style={{ color: "#dc2626", marginBottom: 16 }}>
        页面渲染出错
      </h2>
      <pre
        style={{
          background: "#f3f4f6",
          padding: 16,
          borderRadius: 8,
          overflow: "auto",
          fontSize: 13,
          whiteSpace: "pre-wrap",
        }}
      >
        {error?.message || "Unknown error"}
        {error?.stack ? "\n\n" + error.stack : ""}
      </pre>
      <button
        onClick={reset}
        style={{
          marginTop: 16,
          padding: "8px 16px",
          background: "#2563eb",
          color: "white",
          border: "none",
          borderRadius: 6,
          cursor: "pointer",
        }}
      >
        重试
      </button>
    </div>
  );
}
