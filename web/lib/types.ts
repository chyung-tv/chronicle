export type Activity =
  | "idle"
  | "thinking"
  | "writing"
  | "injecting"
  | "steering";

export type ActorDot = {
  id: string;
  name: string;
  alive: boolean;
};

export type Location = {
  id: string;
  name: string;
  description: string;
  intact: boolean;
  x: number;
  y: number;
  actors: ActorDot[];
  objects: { id: string; name: string; hidden: boolean }[];
};

export type Actor = {
  id: string;
  name: string;
  voice: string;
  want: string;
  secret: string;
  constitution: string;
  location_id: string;
  goal: string;
  mood: string;
  alive: boolean;
  injured: boolean;
  inventory: { id: string; name: string }[];
};

export type CanonEvent = {
  id: number;
  day: number;
  scene: number;
  kind: string;
  actor_id: string | null;
  target_id: string | null;
  summary: string;
};

export type DaySlot = {
  kind: string;
  actor_id?: string;
  source?: string;
  rung_id?: string;
  status?: string;
  encounter?: boolean;
};

export type DayPlan = {
  day: number;
  cursor: number;
  slots: DaySlot[];
};

export type Encounter = {
  initiator: string;
  counterpart: string;
  active: boolean;
} | null;

export type Intent = {
  id: number;
  text: string;
  status: string;
  campaign: {
    summary?: string;
    rungs?: { id: string; status: string }[];
  };
  created_day: number;
  created_scene: number;
};

export type Chapter = {
  id: number;
  day: number;
  pov: string;
  tags: string[];
  cited_event_ids: number[];
  text: string;
};

export type WorldSnapshot = {
  title: string;
  worldview: string;
  day: number;
  scene: number;
  time_label: string;
  scenes_per_day: number;
  day_plan: DayPlan | null;
  day_run_multiplier: number;
  encounter: Encounter;
  max_days: number;
  weather: string;
  clock: { note?: string };
  paused: boolean;
  llm_mode: string;
  llm_model: string;
  activity: Activity;
  activity_actor: string;
  activity_detail: string;
  activity_gen: number;
  activity_error: string;
  locations: Location[];
  edges: { a: string; b: string }[];
  actors: Actor[];
  events: CanonEvent[];
  diaries: Record<string, { day: number; scene: number; text: string; importance: number }[]>;
  chapters: Chapter[];
  intents: Intent[];
};
