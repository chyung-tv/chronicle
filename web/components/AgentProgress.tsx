"use client";

export type AgentState = {
  kind: string;
  status: "idle" | "queued" | "running" | "done" | "error" | string;
  actor: string;
  detail: string;
  progress: number;
  gen: number;
  error: string;
};

const KIND_LABEL: Record<string, string> = {
  wizard: "巫師補完",
  tick: "演一步",
  day: "演完今日",
  inject: "神諭",
  steer: "導引",
};

export function AgentProgress({ state }: { state: AgentState }) {
  const pct = Math.max(0, Math.min(100, Math.round((state.progress || 0) * 100)));
  const label = KIND_LABEL[state.kind] || state.kind || "工作中";
  return (
    <div className="agent-progress">
      <p className="agent-kind">{label}</p>
      <p className="agent-detail">{state.detail || "請稍候…"}</p>
      <div
        className="agent-bar"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-label={state.detail || label}
      >
        <span style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
