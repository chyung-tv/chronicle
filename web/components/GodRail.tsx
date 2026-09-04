"use client";

import { FormEvent } from "react";
import { RUNG, statusLabel } from "@/lib/labels";
import type { WorldSnapshot } from "@/lib/types";

export function GodRail({
  state,
  busy,
  onInject,
  onSteer,
  onInsertLocation,
  onInsertActor,
}: {
  state: WorldSnapshot;
  busy: boolean;
  onInject: (text: string) => void;
  onSteer: (text: string) => void;
  onInsertLocation: (text: string) => void;
  onInsertActor: (text: string) => void;
}) {
  const submit =
    (name: string, send: (text: string) => void) =>
    (ev: FormEvent<HTMLFormElement>) => {
      ev.preventDefault();
      const input = ev.currentTarget.elements.namedItem(name) as HTMLInputElement;
      const text = input.value.trim();
      if (!text) return;
      send(text);
      input.value = "";
    };

  return (
    <footer className="god" aria-label="神諭">
      <p className="god-kicker">神諭 · 不改昨日</p>
      <form onSubmit={submit("inject", onInject)}>
        <label>
          世界事件
          <input
            name="inject"
            placeholder="忽然變了天"
            autoComplete="off"
            disabled={busy}
          />
        </label>
        <button type="submit" disabled={busy}>
          注入
        </button>
      </form>
      <form onSubmit={submit("steer", onSteer)}>
        <label>
          導引意圖
          <input
            name="steer"
            placeholder="關瑪應當毀了張渡"
            autoComplete="off"
            disabled={busy}
          />
        </label>
        <button type="submit" disabled={busy}>
          導引
        </button>
      </form>
      <form onSubmit={submit("location", onInsertLocation)}>
        <label>
          插入地點
          <input
            name="location"
            placeholder="鎮上多一間蘋果店"
            autoComplete="off"
            disabled={busy}
          />
        </label>
        <button type="submit" disabled={busy}>
          寫入
        </button>
      </form>
      <form onSubmit={submit("actor", onInsertActor)}>
        <label>
          插入人物
          <input
            name="actor"
            placeholder="碼頭多一個掌櫃"
            autoComplete="off"
            disabled={busy}
          />
        </label>
        <button type="submit" disabled={busy}>
          寫入
        </button>
      </form>
      <div className="god-intents">
        {state.intents.length ? (
          state.intents.map((i) => {
            const rungs = (i.campaign.rungs || [])
              .map((r) => `${RUNG[r.id] || r.id}：${statusLabel(r.status)}`)
              .join(" · ");
            return (
              <div className="intent" key={i.id}>
                <div className={`status ${i.status}`}>
                  {statusLabel(i.status)}
                </div>
                <p>{i.text}</p>
                <p className="entry">{i.campaign.summary || ""}</p>
                <p className="entry">{rungs}</p>
              </div>
            );
          })
        ) : (
          <p className="entry">尚無導引。寫下一則你希望變得可能的未來。</p>
        )}
      </div>
      <p className="hint">
        正史已封。你可以改明日，不能改昨日。導引只造動機與壓力；人物仍自己選擇。對持中的回話算在發起者這一拍裡。插入地點與人物即時寫入正史。
      </p>
    </footer>
  );
}
