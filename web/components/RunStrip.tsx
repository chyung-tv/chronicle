"use client";

import type { WorldSnapshot } from "@/lib/types";
import { RUNG } from "@/lib/labels";

export function RunStrip({ state }: { state: WorldSnapshot }) {
  const plan = state.day_plan;
  const nameOf = (id?: string) =>
    state.actors.find((a) => a.id === id)?.name || id || "";

  if (!plan?.slots?.length) {
    return (
      <ol className="run-strip" aria-label="今日跑序">
        <li>尚未開今日之序。按「演一步」即黎明排程。</li>
      </ol>
    );
  }
  const cur = plan.cursor || 0;
  const talking = state.encounter?.active;
  return (
    <ol className="run-strip" aria-label="今日跑序">
      {plan.slots.map((s, i) => {
        const cls = [
          i === cur ? "current" : "",
          s.status === "done" || i < cur ? "done" : "",
          s.kind === "event" ? "event" : "",
          s.encounter || (talking && i === cur) ? "encounter" : "",
        ]
          .filter(Boolean)
          .join(" ");
        let label: string;
        if (s.kind === "event") {
          label =
            s.source === "steer"
              ? `導引·${RUNG[s.rung_id || ""] || s.rung_id || "世變"}`
              : "世變";
        } else {
          label = nameOf(s.actor_id);
        }
        if ((s.encounter || (talking && i === cur)) && s.kind === "actor") {
          label += " · 對話中";
        }
        return (
          <li key={i} className={cls}>
            {label}
          </li>
        );
      })}
    </ol>
  );
}
