"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { PlayOutApp } from "@/components/PlayOutApp";
import { fetchMe, fetchStory } from "@/lib/api";
import type { StoryDetail } from "@/lib/types";

export function PlayGate({ storyRef }: { storyRef: string }) {
  const router = useRouter();
  const [story, setStory] = useState<StoryDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await fetchMe();
        const rec = await fetchStory(storyRef);
        if (cancelled) return;
        if (rec.status === "draft") {
          if (rec.is_owner) {
            router.replace(`/s/${rec.id}/design`);
            return;
          }
          setStory(rec);
          return;
        }
        setStory(rec);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router, storyRef]);

  if (error) {
    return (
      <header className="masthead">
        <div className="mast-title">
          <p className="chrome-links">
            <Link href="/">故事</Link>
          </p>
          <h1>演繹</h1>
          <p className="sub">{error}</p>
        </div>
      </header>
    );
  }

  if (!story) {
    return (
      <header className="masthead">
        <div className="mast-title">
          <h1>演繹</h1>
          <p className="sub">載入世界…</p>
        </div>
      </header>
    );
  }

  if (story.status === "draft") {
    return (
      <header className="masthead">
        <div className="mast-title">
          <p className="chrome-links">
            <Link href="/">故事</Link>
          </p>
          <h1>{story.title}</h1>
          <p className="sub">尚未開演。</p>
        </div>
      </header>
    );
  }

  return <PlayOutApp storyId={story.id} />;
}
