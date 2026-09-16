import { Suspense } from "react";
import { PlayGate } from "@/components/PlayGate";

export default async function StoryPlayPage({
  params,
}: {
  params: Promise<{ storyId: string }>;
}) {
  const { storyId } = await params;
  return (
    <Suspense
      fallback={
        <header className="masthead">
          <div className="mast-title">
            <h1>演繹</h1>
            <p className="sub">載入中…</p>
          </div>
        </header>
      }
    >
      <PlayGate storyRef={storyId} />
    </Suspense>
  );
}
