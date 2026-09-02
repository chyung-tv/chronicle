"""Pydantic models for actions, patches, and agent outputs. Canon lives in SQLite."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class MoveAction(BaseModel):
    type: Literal["move"] = "move"
    to: str


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


def action_from_dict(data: dict[str, Any]) -> Action:
    t = data.get("type")
    mapping = {
        "move": MoveAction,
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
