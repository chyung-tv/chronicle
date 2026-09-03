import { SetupReview } from "@/components/SetupReview";

export default async function StorySetupReviewPage({
  params,
}: {
  params: Promise<{ storyId: string }>;
}) {
  const { storyId } = await params;
  return <SetupReview storyRef={storyId} />;
}
