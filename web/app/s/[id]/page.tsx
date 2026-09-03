"use client";

import { useParams } from "next/navigation";
import { PlayGate } from "@/components/PlayGate";

export default function StoryPlayPage() {
  const { id } = useParams<{ id: string }>();
  return <PlayGate storyRef={id} />;
}
