"use client";

import { useParams } from "next/navigation";
import { DesignConsole } from "@/components/DesignConsole";

export default function StoryDesignPage() {
  const { id } = useParams<{ id: string }>();
  return <DesignConsole storyRef={id} />;
}
