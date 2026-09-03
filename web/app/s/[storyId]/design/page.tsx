import { DesignConsole } from "@/components/DesignConsole";

export default async function StoryDesignPage({
  params,
}: {
  params: Promise<{ storyId: string }>;
}) {
  const { storyId } = await params;
  return <DesignConsole storyRef={storyId} />;
}
