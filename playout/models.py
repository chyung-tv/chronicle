"""Pydantic models for actions, patches, and agent outputs. Canon lives in SQLite."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MoveAction(BaseModel):
    type: Literal["move"] = "move"
    to: str


class InteractAction(BaseModel):
    type: Literal["interact"] = "interact"
    text: str


class SpeakAction(BaseModel):
    type: Literal["speak_to"] = "speak_to"
    target: str
    speech: str


class TakeAction(BaseModel):
    type: Literal["take"] = "take"
    object_id: str


class DropAction(BaseModel):
    type: Literal["drop"] = "drop"
    object_id: str


class ExamineAction(BaseModel):
    type: Literal["examine"] = "examine"
    target: str  # object id or location id


class WaitAction(BaseModel):
    type: Literal["wait"] = "wait"


class WriteNoteAction(BaseModel):
    type: Literal["write_note"] = "write_note"
    text: str


class AttackAction(BaseModel):
    type: Literal["attack"] = "attack"
    target: str


class KillAction(BaseModel):
    type: Literal["kill"] = "kill"
    target: str


Action = Annotated[
    MoveAction
    | InteractAction
    | SpeakAction
    | TakeAction
    | DropAction
    | ExamineAction
    | WaitAction
    | WriteNoteAction
    | AttackAction
    | KillAction,
    Field(discriminator="type"),
]


class ActorInner(BaseModel):
    """Thought/mood after tools have already mutated the world."""

    thought: str = ""
    goal_update: str | None = None
    mood: str | None = None


class ActorDecision(BaseModel):
    thought: str = ""
    goal_update: str | None = None
    mood: str | None = None
    action: Action


class Patch(BaseModel):
    op: Literal[
        "destroy_location",
        "describe_location",
        "injure_actor",
        "kill_actor",
        "move_actor",
        "add_object",
        "destroy_object",
        "reveal_object",
        "rumor",
        "broadcast",
        "set_weather",
    ]
    location_id: str | None = None
    actor_id: str | None = None
    actor_ids: list[str] | None = None
    object_id: str | None = None
    name: str | None = None
    detail: str = ""
    hidden: bool = False


class PerceptionOut(BaseModel):
    actor_id: str
    text: str


class SpeechOut(BaseModel):
    speaker_id: str
    hearer_id: str | None = None
    text: str


class ObjectMutation(BaseModel):
    op: Literal["take", "drop", "reveal", "write_note"]
    object_id: str | None = None
    actor_id: str | None = None
    text: str = ""


class RelationBump(BaseModel):
    from_id: str
    to_id: str
    trust: int = 0
    resentment: int = 0
    note: str = ""


class RefereeVerdict(BaseModel):
    """Structured judgment of one or two interact attempts. Applied deterministically."""

    summary: str
    kind: str = "interact"
    patches: list[Patch] = Field(default_factory=list)
    perceptions: list[PerceptionOut] = Field(default_factory=list)
    speeches: list[SpeechOut] = Field(default_factory=list)
    objects: list[ObjectMutation] = Field(default_factory=list)
    relations: list[RelationBump] = Field(default_factory=list)


class StorytellerPlan(BaseModel):
    summary: str
    patches: list[Patch] = Field(default_factory=list)


class SteerRung(BaseModel):
    id: str
    kind: Literal["motive", "means", "opportunity", "escalation"]
    status: Literal["pending", "injected"] = "pending"
    injection: StorytellerPlan


class SteerCampaign(BaseModel):
    summary: str
    success_predicates: list[str] = Field(default_factory=list)
    failure_predicates: list[str] = Field(default_factory=list)
    rungs: list[SteerRung] = Field(default_factory=list)


class WriterChapter(BaseModel):
    pov: str
    tags: list[str] = Field(default_factory=list)
    cited_event_ids: list[int] = Field(default_factory=list)
    text: str


class ConnectedExit(BaseModel):
    """A neighbor on the location graph. Ruined exits are listed but not walkable."""

    id: str
    name: str
    intact: bool = True


class NodePerson(BaseModel):
    id: str
    name: str
    injured: bool = False
    alive: bool = True


class NodeObject(BaseModel):
    id: str
    name: str
    description: str = ""


class LocationNode(BaseModel):
    """A place an actor can stand. description is the environmental palette."""

    id: str
    name: str
    description: str
    intact: bool = True
    x: float = 0
    y: float = 0
    connected: list[ConnectedExit] = Field(default_factory=list)
    present: list[NodePerson] = Field(default_factory=list)
    visible_objects: list[NodeObject] = Field(default_factory=list)


class WorldAtmosphere(BaseModel):
    """Non-spatial world: weather, clock, worldview. Visible everywhere."""

    title: str = ""
    worldview: str = ""
    day: int = 1
    beat: str = ""
    weather: str = ""
    clock: str = ""


class MoveIntent(BaseModel):
    actor_id: str
    to: str
    kind: Literal["voluntary", "forced", "evacuate"] = "voluntary"


class MoveResolution(BaseModel):
    ok: bool
    actor_id: str
    from_id: str
    to_id: str | None = None
    dest_name: str = ""
    kind: Literal["voluntary", "forced", "evacuate"] = "voluntary"
    reason: str | None = None
    summary: str = ""
    self_perception: str = ""
    leave_perception: str = ""
    arrive_perception: str = ""
    event_id: int | None = None


class ClockSetup(BaseModel):
    model_config = ConfigDict(extra="allow")
    storm_in_days: int | None = None
    note: str = ""


class LocationSetup(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    description: str
    x: float = 0
    y: float = 0
    intact: bool = True


class ActorSetup(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    location: str
    voice: str
    want: str
    secret: str = ""
    constitution: str
    goal: str = ""
    mood: str = "靜"


class ObjectSetup(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    description: str
    location_id: str | None = None
    holder_id: str | None = None
    hidden: bool = False


class RelationshipSetup(BaseModel):
    a: str
    b: str
    trust: int = 0
    resentment: int = 0
    notes: str = ""


class OpeningEventSetup(BaseModel):
    kind: str = "world"
    summary: str
    perceive: list[str] = Field(default_factory=list)
    actor_id: str | None = None
    target_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class StorySetup(BaseModel):
    """Birth configuration of a story. Editable only while the story is draft."""

    title: str
    days: int = 3
    scenes_per_day: int = 6
    day_run_multiplier: int = 2
    time_labels: list[str] = Field(
        default_factory=lambda: ["黎明", "上午", "正午", "午後", "黃昏", "夜"]
    )
    weather: str = ""
    clock: ClockSetup = Field(default_factory=ClockSetup)
    worldview: str = ""
    locations: list[LocationSetup]
    edges: list[tuple[str, str]] = Field(default_factory=list)
    actors: list[ActorSetup]
    objects: list[ObjectSetup] = Field(default_factory=list)
    relationships: list[RelationshipSetup] = Field(default_factory=list)
    opening_events: list[OpeningEventSetup] = Field(default_factory=list)

    @model_validator(mode="after")
    def _refs_exist(self) -> "StorySetup":
        loc_ids = [loc.id for loc in self.locations]
        if len(set(loc_ids)) != len(loc_ids):
            raise ValueError("location ids must be unique")
        if not loc_ids:
            raise ValueError("at least one location")
        actor_ids = [act.id for act in self.actors]
        if len(set(actor_ids)) != len(actor_ids):
            raise ValueError("actor ids must be unique")
        if not actor_ids:
            raise ValueError("at least one actor")
        loc_set = set(loc_ids)
        actor_set = set(actor_ids)
        obj_ids = [obj.id for obj in self.objects]
        if len(set(obj_ids)) != len(obj_ids):
            raise ValueError("object ids must be unique")
        for act in self.actors:
            if act.location not in loc_set:
                raise ValueError(f"actor {act.id} location {act.location} missing")
            if not act.goal:
                act.goal = act.want
        for a, b in self.edges:
            if a not in loc_set or b not in loc_set:
                raise ValueError(f"edge {a}-{b} refers to unknown location")
        for obj in self.objects:
            if obj.location_id and obj.location_id not in loc_set:
                raise ValueError(f"object {obj.id} location missing")
            if obj.holder_id and obj.holder_id not in actor_set:
                raise ValueError(f"object {obj.id} holder missing")
        for rel in self.relationships:
            if rel.a not in actor_set or rel.b not in actor_set:
                raise ValueError(f"relationship {rel.a}->{rel.b} unknown actor")
        for ev in self.opening_events:
            for pid in ev.perceive:
                if pid not in actor_set:
                    raise ValueError(f"opening event perceives unknown actor {pid}")
        return self


def empty_setup(title: str = "未名") -> StorySetup:
    return StorySetup(
        title=title,
        worldview="",
        weather="天色未定。",
        clock=ClockSetup(note=""),
        locations=[
            LocationSetup(
                id="place",
                name="一處",
                description="尚無描述。",
                x=270,
                y=180,
            )
        ],
        edges=[],
        actors=[
            ActorSetup(
                id="someone",
                name="某人",
                location="place",
                voice="尚未定腔。",
                want="尚未定願。",
                secret="",
                constitution="尚未定性。",
                goal="尚未定願。",
                mood="靜",
            )
        ],
    )


def action_from_dict(data: dict[str, Any]) -> Action:
    t = data.get("type")
    mapping = {
        "move": MoveAction,
        "interact": InteractAction,
        "speak_to": SpeakAction,
        "take": TakeAction,
        "drop": DropAction,
        "examine": ExamineAction,
        "wait": WaitAction,
        "write_note": WriteNoteAction,
        "attack": AttackAction,
        "kill": KillAction,
    }
    cls = mapping.get(t)
    if not cls:
        return WaitAction()
    return cls.model_validate(data)
