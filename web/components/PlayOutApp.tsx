"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Cast } from "@/components/Cast";
import { Chapters, EventTape } from "@/components/EventTape";
import { GodRail } from "@/components/GodRail";
import { RunStrip } from "@/components/RunStrip";
import { TownMap } from "@/components/TownMap";
import { useWorldStream } from "@/hooks/useWorldStream";
import {
  postDay,
  postInject,
  postReset,
  postSteer,
  postTick,
} from "@/lib/api";

function beatClock(state: {
  day: number;
  day_plan: { cursor?: number; slots?: unknown[] } | null;
  clock?: string;
}) {
  const plan = state.day_plan;
  const slots = plan?.slots || [];
  const k = Math.min((plan?.cursor || 0) + 1, slots.length || 1);
  const n = slots.length;
  const beat = n ? `第 ${k}/${n} 次` : "未排今日";
  const note = (state.clock || "").trim();
  return note ? `第${state.day}日 · ${beat} · ${note}` : `第${state.day}日 · ${beat}`;
}

export function PlayOutApp({ storyId }: { storyId: string }) {
  const { state, error, busy, runCommand } = useWorldStream(storyId);
  const router = useRouter();
  const [tab, setTab] = useState<"tape" | "chapters">("tape");
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (!state?.actors.length) return;
    if (selected && state.actors.some((a) => a.id === selected)) return;
    setSelected(state.actors[0].id);
  }, [state, selected]);

  if (!state) {
    return (
      <header className="masthead">
        <div className="mast-title">
          <h1>演繹</h1>
          <p className="sub">{error || "載入世界…"}</p>
        </div>
      </header>
    );
  }

  const activityText =
    state.activity !== "idle"
      ? state.activity_detail || "思考中…"
      : state.llm_mode === "live"
        ? state.llm_model || "openrouter"
        : "模擬語言模型";

  const owner = !!state.is_owner;
  const god = !!state.can_god;

  return (
    <>
      <header className="masthead">
        <div className="mast-title">
          <p className="chrome-links">
            <Link href="/">故事</Link>
            {owner ? (
              <Link href={`/s/${storyId}/design`}>世界設定</Link>
            ) : null}
          </p>
          <h1>{state.title || "演繹"}</h1>
          <p className="sub">{beatClock(state)}</p>
        </div>
        <div className="controls">
          <button
            type="button"
            disabled={busy}
            onClick={() => runCommand(() => postTick(storyId))}
          >
            演一步
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => runCommand(() => postDay(storyId))}
          >
            演完今日
          </button>
          {owner ? (
            <button
              type="button"
              className="ghost"
              disabled={busy}
              onClick={() => {
                if (
                  !confirm(
                    "這會銷毀已發生的事件帶，故事回到未開演，方可再改世界設定。此控制日後將移除。"
                  )
                ) {
                  return;
                }
                runCommand(
                  async () => {
                    await postReset(storyId);
                    router.push(`/s/${storyId}/design`);
                  },
                  { blocking: true }
                );
              }}
            >
              重置世界
            </button>
          ) : null}
          <span className={`pill${busy ? " busy" : ""}`}>{activityText}</span>
        </div>
        {error ? <p className="banner">{error}</p> : null}
        <RunStrip state={state} />
      </header>

      <main className="workspace">
        <section className="panel stage" aria-labelledby="stage-h">
          <h2 id="stage-h">鎮</h2>
          <TownMap state={state} onSelect={setSelected} />
          <p className="weather">{state.weather}</p>
        </section>

        <section className="panel chronicle" aria-labelledby="chron-h">
          <div className="tabs">
            <button
              type="button"
              className={tab === "tape" ? "on" : ""}
              onClick={() => setTab("tape")}
            >
              事件帶
            </button>
            <button
              type="button"
              className={tab === "chapters" ? "on" : ""}
              onClick={() => setTab("chapters")}
            >
              章回
            </button>
          </div>
          {tab === "tape" ? (
            <EventTape state={state} pending={busy} />
          ) : (
            <Chapters state={state} />
          )}
        </section>

        <aside className="panel cast" aria-labelledby="cast-h">
          <h2 id="cast-h">人物</h2>
          <Cast state={state} selected={selected} onSelect={setSelected} />
        </aside>
      </main>

      {god ? (
        <GodRail
          state={state}
          busy={busy}
          onInject={(text) => runCommand(() => postInject(storyId, text))}
          onSteer={(text) => runCommand(() => postSteer(storyId, text))}
        />
      ) : null}
    </>
  );
}
