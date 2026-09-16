"use client";

import type { WorldSnapshot } from "@/lib/types";

export function Cast({
  state,
  selected,
  onSelect,
  publicView = false,
}: {
  state: WorldSnapshot;
  selected: string | null;
  onSelect: (id: string) => void;
  publicView?: boolean;
}) {
  const current =
    state.actors.find((x) => x.id === selected) || state.actors[0];
  const locName = (id: string) =>
    state.locations.find((l) => l.id === id)?.name || id;

  return (
    <>
      <div className="cast-nav">
        {state.actors.map((a) => (
          <button
            key={a.id}
            type="button"
            className={a.id === current?.id ? "on" : ""}
            onClick={() => onSelect(a.id)}
          >
            {a.name}
          </button>
        ))}
      </div>
      {current ? (
        <div className="cast-sheet">
          <h3>
            {current.name} {current.alive ? "" : "（已歿）"}{" "}
            {current.injured ? "· 帶傷" : ""}
          </h3>
          <p className="entry">
            <b>所在</b> {locName(current.location_id)} · <b>心境</b>{" "}
            {current.mood || "—"}
          </p>
          <p className="entry">
            <b>目前目標</b> {current.goal || "—"}
          </p>
          {current.want ? (
            <p className="entry">
              <b>一直想要</b> {current.want}
            </p>
          ) : null}
          {!publicView && current.secret ? (
            <p className="entry">
              <b>秘密</b> {current.secret}
            </p>
          ) : null}
          <p className="entry">
            <b>隨身</b>{" "}
            {current.inventory.map((o) => o.name).join("、") || "空手"}
          </p>
          <h2>日記</h2>
          {(state.diaries[current.id] || []).length ? (
            (state.diaries[current.id] || []).map((d, i) => (
              <p key={i} className="entry">
                第{d.day}日：{d.text}
              </p>
            ))
          ) : (
            <p className="entry">還沒有日記。</p>
          )}
        </div>
      ) : null}
    </>
  );
}
