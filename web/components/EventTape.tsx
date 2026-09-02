"use client";

import { kindLabel } from "@/lib/labels";
import type { WorldSnapshot } from "@/lib/types";

export function EventTape({
  state,
  pending,
}: {
  state: WorldSnapshot;
  pending: boolean;
}) {
  const events = [...(state.events || [])].reverse();
  return (
    <ol className="tape">
      {pending ? (
        <li className="pending">
          <div className="meta">進行中</div>
          <div>{state.activity_detail || "思考中…"}</div>
        </li>
      ) : null}
      {events.map((e, i) => {
        const prev = events[i + 1];
        const held = !!(
          prev &&
          prev.day === e.day &&
          prev.scene === e.scene &&
          (e.kind === "speak" ||
            prev.kind === "speak" ||
            e.kind === "attack" ||
            prev.kind === "attack")
        );
        return (
          <li
            key={e.id}
            className={`kind-${e.kind}${held ? " held" : ""}`}
          >
            <div className="meta">
              第{e.day}日 {kindLabel(e.kind)} #{e.id}
            </div>
            <div>{e.summary}</div>
          </li>
        );
      })}
    </ol>
  );
}

export function Chapters({ state }: { state: WorldSnapshot }) {
  const nameOf = (id: string) =>
    state.actors.find((a) => a.id === id)?.name || id;
  if (!state.chapters.length) {
    return <p className="entry">章回於一日終了時寫成。</p>;
  }
  return (
    <>
      {state.chapters.map((c) => (
        <div key={c.id}>
          <h3>
            第{c.day}日 · {nameOf(c.pov)} · {c.tags.join("、")}
          </h3>
          <div className="chapter">{c.text}</div>
        </div>
      ))}
    </>
  );
}
