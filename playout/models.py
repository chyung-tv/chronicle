"""Pydantic models for actions, patches, and agent outputs. Canon lives in SQLite."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


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
    intent: str = ""


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


class ExamineIntent(BaseModel):
    actor_id: str
    aim: str
    intent: str = ""


class ObjectAppend(BaseModel):
    object_id: str
    text: str


class FoundObject(BaseModel):
    object_id: str
    name: str
    description: str = ""


class ExamineDiscovery(BaseModel):
    """God-side result of looking. Applied by the examine resolver only."""

    perception: str = ""
    summary: str = ""
    object_appends: list[ObjectAppend] = Field(default_factory=list)
    location_details: list[str] = Field(default_factory=list)
    add_objects: list[FoundObject] = Field(default_factory=list)
    reveal_ids: list[str] = Field(default_factory=list)


class ExamineResolution(BaseModel):
    ok: bool
    actor_id: str
    aim: str
    here_id: str = ""
    kind: Literal["object", "place", "look_toward", "failed"] = "failed"
    reason: str | None = None
    summary: str = ""
    self_perception: str = ""
    witness_perception: str = ""
    event_id: int | None = None


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
