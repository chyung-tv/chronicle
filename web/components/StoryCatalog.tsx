"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, fetchMe } from "@/lib/api";
import type { SessionUser, StoryCard } from "@/lib/types";

function isPublicLive(s: StoryCard) {
  return s.visibility === "public" && s.status === "live";
}

function StoryActions({
  s,
  busy,
  onDuplicate,
}: {
  s: StoryCard;
  busy: boolean;
  onDuplicate: (id: string) => void;
}) {
  return (
    <div className="card-actions">
      {s.status === "live" ? (
        <Link
          className="btn"
          href={s.is_owner ? `/s/${s.id}?room=reading` : `/s/${s.id}`}
        >
          閱讀
        </Link>
      ) : s.is_owner ? (
        <Link className="btn" href={`/s/${s.id}/design`}>
          繼續設定
        </Link>
      ) : (
        <span className="pill">尚未開演</span>
      )}
      {s.is_owner && s.status === "live" ? (
        <Link className="btn ghost" href={`/s/${s.id}`}>
          寫作室
        </Link>
      ) : null}
      {s.is_owner && s.status === "live" ? (
        <Link className="btn ghost" href={`/s/${s.id}/design/review`}>
          世界設定
        </Link>
      ) : null}
      <button
        type="button"
        className="ghost"
        disabled={busy}
        onClick={() => onDuplicate(s.id)}
      >
        另開草稿
      </button>
    </div>
  );
}

function Card({
  s,
  busy,
  onDuplicate,
}: {
  s: StoryCard;
  busy: boolean;
  onDuplicate: (id: string) => void;
}) {
  return (
    <article className="story-card" key={s.id}>
      <h2>{s.title}</h2>
      <p className="entry">
        {s.status === "live" ? "演繹中" : "草稿"}
        {s.day ? ` · 第${s.day}日` : ""}
        {` · ${s.location_count}處 · ${s.actor_count}人`}
        {s.slug === "harbors-end" ? " · 公開示範" : ""}
      </p>
      <StoryActions s={s} busy={busy} onDuplicate={onDuplicate} />
    </article>
  );
}

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

  const published = stories.filter(isPublicLive);
  const drafts = stories.filter((s) => s.is_owner && !isPublicLive(s));

  return (
    <>
      <header className="masthead">
        <div className="mast-title">
          <h1>演繹</h1>
          <p className="sub">
            公開的故事給人讀；草稿只有你見得到。
            {user ? ` · ${user.name}` : ""}
          </p>
        </div>
        <div className="controls">
          <button type="button" disabled={busy} onClick={create}>
            開新故事
          </button>
        </div>
        {error ? <p className="banner">{error}</p> : null}
      </header>
      <main className="catalog-page">
        <section className="catalog-section" aria-labelledby="public-h">
          <h2 id="public-h">公開演繹</h2>
          {published.length ? (
            <div className="catalog">
              {published.map((s) => (
                <Card key={s.id} s={s} busy={busy} onDuplicate={duplicate} />
              ))}
            </div>
          ) : (
            <p className="entry catalog-empty">暫時沒有公開的演繹。</p>
          )}
        </section>
        <section className="catalog-section" aria-labelledby="mine-h">
          <h2 id="mine-h">我的草稿</h2>
          {drafts.length ? (
            <div className="catalog">
              {drafts.map((s) => (
                <Card key={s.id} s={s} busy={busy} onDuplicate={duplicate} />
              ))}
            </div>
          ) : (
            <p className="entry catalog-empty">未有草稿。開一則新故事即可。</p>
          )}
        </section>
      </main>
    </>
  );
}
