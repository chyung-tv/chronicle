"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Cast } from "@/components/Cast";
import { Chapters, EventTape } from "@/components/EventTape";
import { TownMap } from "@/components/TownMap";
import { useWorldStream } from "@/hooks/useWorldStream";
import type { WorldSnapshot } from "@/lib/types";

type View = "read" | "inspect";

function readerClock(state: { day: number; clock?: string }) {
  const note = (state.clock || "").trim();
  return note ? `第${state.day}日 · ${note}` : `第${state.day}日`;
}

export function ReadingRoom({
  storyId,
  isOwner,
}: {
  storyId: string;
  isOwner: boolean;
}) {
  const { state, error, busy } = useWorldStream(storyId);
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const view: View = search.get("view") === "inspect" ? "inspect" : "read";

  const switchView = (next: View) => {
    const q = new URLSearchParams(search.toString());
    if (next === "inspect") q.set("view", "inspect");
    else q.delete("view");
    if (isOwner) q.set("room", "reading");
    const qs = q.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };

  if (!state) {
    return (
      <header className="masthead">
        <div className="mast-title">
          <h1>閱覽室</h1>
          <p className="sub">{error || "載入中…"}</p>
        </div>
      </header>
    );
  }

  return (
    <>
      <header className="masthead">
        <div className="mast-title">
          <p className="chrome-links">
            <Link href="/">目錄</Link>
            {isOwner ? <Link href={`/s/${storyId}`}>寫作室</Link> : null}
          </p>
          <h1>{state.title || "閱覽室"}</h1>
          <p className="sub">{readerClock(state)}</p>
        </div>
        <div className="controls">
          <div className="mode-switch" role="tablist" aria-label="閱覽方式">
            <button
              type="button"
              role="tab"
              aria-selected={view === "read"}
              className={view === "read" ? "on" : ""}
              onClick={() => switchView("read")}
            >
              閱讀
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={view === "inspect"}
              className={view === "inspect" ? "on" : ""}
              onClick={() => switchView("inspect")}
            >
              探看
            </button>
          </div>
          {busy ? (
            <span className="pill busy">
              {state.activity_detail || "仍在演繹"}
            </span>
          ) : null}
        </div>
        {error ? <p className="banner">{error}</p> : null}
      </header>

      {view === "read" ? <NovelSurface state={state} busy={busy} /> : null}
      {view === "inspect" ? <InspectSurface state={state} /> : null}
    </>
  );
}

function NovelSurface({
  state,
  busy,
}: {
  state: WorldSnapshot;
  busy: boolean;
}) {
  return (
    <main className="workspace reading-novel">
      <section className="panel chronicle" aria-labelledby="chapters-h">
        <h2 id="chapters-h">章節</h2>
        <Chapters state={state} />
      </section>
      <section className="panel tape-col" aria-labelledby="tape-h">
        <h2 id="tape-h">紀錄</h2>
        <EventTape state={state} pending={busy} />
      </section>
    </main>
  );
}

function InspectSurface({ state }: { state: WorldSnapshot }) {
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (!state.actors.length) return;
    if (selected && state.actors.some((a) => a.id === selected)) return;
    setSelected(state.actors[0].id);
  }, [state, selected]);

  return (
    <main className="workspace reading-inspect">
      <section className="panel stage" aria-labelledby="map-h">
        <h2 id="map-h">地圖</h2>
        <TownMap state={state} onSelect={setSelected} />
        <p className="weather">{state.weather}</p>
      </section>
      <aside className="panel cast" aria-labelledby="cast-h">
        <h2 id="cast-h">人物</h2>
        <Cast
          state={state}
          selected={selected}
          onSelect={setSelected}
          publicView
        />
      </aside>
    </main>
  );
}
