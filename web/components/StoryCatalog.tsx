"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, fetchMe } from "@/lib/api";
import type { SessionUser, StoryCard } from "@/lib/types";

export function StoryCatalog() {
  const router = useRouter();
  const [user, setUser] = useState<SessionUser | null>(null);
  const [stories, setStories] = useState<StoryCard[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    const me = await fetchMe();
    setUser(me);
    const list = await api<StoryCard[]>("/api/stories");
    setStories(list);
  };

  useEffect(() => {
    load().catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const rec = await api<StoryCard>("/api/stories", {
        method: "POST",
        body: JSON.stringify({}),
      });
      router.push(`/s/${rec.id}/design`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  const duplicate = async (id: string) => {
    setBusy(true);
    setError(null);
    try {
      const rec = await api<StoryCard>(`/api/stories/${id}/duplicate`, {
        method: "POST",
      });
      router.push(`/s/${rec.id}/design`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <>
      <header className="masthead">
        <div className="mast-title">
          <h1>演繹</h1>
          <p className="sub">
            選擇一則故事，或新設世界。開演之後，正史便封。
            {user ? ` · ${user.name}` : ""}
          </p>
        </div>
        <div className="controls">
          <button type="button" disabled={busy} onClick={create}>
            新故事
          </button>
        </div>
        {error ? <p className="banner">{error}</p> : null}
      </header>
      <main className="catalog">
        {stories.map((s) => (
          <article className="story-card" key={s.id}>
            <h2>{s.title}</h2>
            <p className="entry">
              {s.status === "live" ? "演繹中" : "未開演"}
              {s.day ? ` · 第${s.day}日` : ""}
              {` · ${s.location_count}處 · ${s.actor_count}人`}
              {s.is_owner ? " · 你的" : ""}
            </p>
            <div className="card-actions">
              {s.status === "live" ? (
                <Link className="btn" href={`/s/${s.id}`}>
                  進入
                </Link>
              ) : s.is_owner ? (
                <Link className="btn" href={`/s/${s.id}/design`}>
                  繼續設定
                </Link>
              ) : (
                <span className="pill">尚未開演</span>
              )}
              {s.is_owner && s.status === "live" ? (
                <Link className="btn ghost" href={`/s/${s.id}/design`}>
                  世界設定
                </Link>
              ) : null}
              <button
                type="button"
                className="ghost"
                disabled={busy}
                onClick={() => duplicate(s.id)}
              >
                複製
              </button>
            </div>
          </article>
        ))}
      </main>
    </>
  );
}
