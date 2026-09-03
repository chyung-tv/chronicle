import { PlayGate } from "@/components/PlayGate";

export default async function StoryPlayPage({
  params,
}: {
  params: Promise<{ storyId: string }>;
}) {
  const { storyId } = await params;
  return <PlayGate storyRef={storyId} />;
}
