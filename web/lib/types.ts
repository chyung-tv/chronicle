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
  condition?: string;
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
  turns_per_day_min: number;
  turns_per_day_max: number;
  encounter: Encounter;
  weather: string;
  clock: string;
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
  story_id?: string;
  slug?: string;
  is_owner?: boolean;
  can_god?: boolean;
};

export type LocationSketch = {
  id: string;
  name: string;
  note: string;
  x: number;
  y: number;
};

export type ActorSketch = {
  id: string;
  name: string;
  note: string;
  location: string;
};

export type ObjectSketch = {
  id: string;
  name: string;
  note: string;
  location_id?: string | null;
  holder_id?: string | null;
};

export type RelationshipSketch = {
  a: string;
  b: string;
  note: string;
};

export type StorySketch = {
  title: string;
  worldview: string;
  opening_situation: string;
  opening_events: string;
  turns_per_day_max: number;
  locations: LocationSketch[];
  edges: [string, string][];
  actors: ActorSketch[];
  objects: ObjectSketch[];
  relationships: RelationshipSketch[];
};

export type LocationSetup = {
  id: string;
  name: string;
  description: string;
  x: number;
  y: number;
  intact?: boolean;
};

export type ActorSetup = {
  id: string;
  name: string;
  location: string;
  voice: string;
  want: string;
  secret: string;
  constitution: string;
  goal: string;
  mood: string;
};

export type ObjectSetup = {
  id: string;
  name: string;
  description: string;
  location_id?: string | null;
  holder_id?: string | null;
  hidden: boolean;
};

export type RelationshipSetup = {
  a: string;
  b: string;
  trust: number;
  resentment: number;
  notes: string;
};

export type StorySetup = {
  title: string;
  turns_per_day_min: number;
  turns_per_day_max: number;
  worldview: string;
  opening_situation: string;
  opening_events: string;
  locations: LocationSetup[];
  edges: [string, string][];
  actors: ActorSetup[];
  objects: ObjectSetup[];
  relationships: RelationshipSetup[];
};

export type StoryCard = {
  id: string;
  slug: string;
  title: string;
  owner_id: string;
  is_owner: boolean;
  status: "draft" | "live";
  day: number | null;
  actor_count: number;
  location_count: number;
  created_at: string;
  updated_at: string;
};

export type StoryDetail = StoryCard & {
  editable: boolean;
  can_god: boolean;
  setup: StorySetup;
  sketch: StorySketch;
  agent?: AgentState;
};

export type AgentState = {
  kind: string;
  status: string;
  actor: string;
  detail: string;
  progress: number;
  gen: number;
  error: string;
};

export type SessionUser = {
  id: string;
  name: string;
};
