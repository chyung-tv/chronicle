"""Actor agent: reads ActorView, mutates World only through referee tools."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from playout.agents.model import llm_mode, openrouter_model, actor_model_name
from playout.agents.views import view_as_prompt
from playout.canon import World
from playout.llm import LLM
from playout.memory import retrieve
from playout.models import (
    Action,
    ActorDecision,
    ActorInner,
    AttackAction,
    DropAction,
    ExamineAction,
    KillAction,
    MoveAction,
    SpeakAction,
    TakeAction,
    WaitAction,
    WriteNoteAction,
)
from playout.referee import apply_action
from playout.zh import with_prose

MUTATE_BUDGET = 4
MAX_ENCOUNTER_ROUNDS = 3

ACTOR_SYSTEM = with_prose("""你是活在故事裡的人物，須守住人格，不是助手。
你只知道自己感知過、寫進日記的事。別人的秘密，除非你已得知，否則你不知道。
目標由你自己從所見所聞長出。誰也不能替你派一個目標。

用工具在世上行動。讀類工具（survey、recall）不計次數。
改世界的工具每回合最多四次。若你對在場之人說話或動手，工具會先讓對方反應，再把你能感知到的結果回給你；你可以再開口、離開，或做別的。
對方不理、走開、或已來回三次，這場對持即止。

最後輸出 JSON 形的心思：thought、goal_update、mood。不要敘述世界。
speech、thought、goal_update 一律繁體中文。
""")


@dataclass
class ActorDeps:
    world: World
    llm: LLM
    actor_id: str
    extra: str = ""
    in_encounter: bool = False
    allow_encounter: bool = True
    mutate_budget: int = MUTATE_BUDGET
    mutates_used: int = 0
    encounter_rounds: int = 0
    max_rounds: int = MAX_ENCOUNTER_ROUNDS
    last_results: list[dict[str, Any]] = field(default_factory=list)


def perceptions_since(world: World, actor_id: str, event_id: int) -> list[str]:
    rows = world.perceptions_for(actor_id, limit=24)
    texts = [p["text"] for p in rows if int(p["event_id"]) >= event_id]
    texts.reverse()
    return texts


def format_action_return(world: World, actor_id: str, result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return f"不成：{result.get('reason', '未知')}"
    eid = int(result.get("event_id") or 0)
    seen = perceptions_since(world, actor_id, eid) if eid else []
    held = result.get("encounter") or {}
    extra = held.get("perceived") or []
    lines = seen + [p for p in extra if p not in seen]
    if not lines:
        return "你動了，但沒有新的見聞。"
    return "你感知到：\n" + "\n".join(f"- {t}" for t in lines)


def dispatch_action(deps: ActorDeps, action: Action) -> dict[str, Any]:
    if deps.mutates_used >= deps.mutate_budget:
        return {"ok": False, "reason": "budget", "detail": "這一時辰你已動得夠多。"}
    deps.mutates_used += 1
    result = apply_action(deps.world, deps.actor_id, action)
    result["action"] = action.model_dump()
    if result.get("event_id"):
        ev = deps.world.cx.execute(
            "SELECT summary FROM events WHERE id=?", (result["event_id"],)
        ).fetchone()
        if ev:
            result["summary"] = ev["summary"]
    target = result.get("expect_reaction")
    if (
        deps.allow_encounter
        and not deps.in_encounter
        and target
        and deps.encounter_rounds < deps.max_rounds
    ):
        from playout.agents.encounter import hold_encounter

        deps.encounter_rounds += 1
        result["encounter"] = hold_encounter(
            deps.world, deps.llm, deps.actor_id, target, result
        )
    deps.last_results.append(result)
    return result


def _maybe_reflect(world: World, llm: LLM, actor_id: str) -> None:
    diaries = world.diary_for(actor_id, limit=6)
    if len(diaries) < 4 or world.scene % 2 != 0:
        return
    if llm.mode == "mock":
        world.write_reflection(actor_id, f"我仍想要：{world.actor(actor_id)['goal']}")
        return
    blob = "\n".join(d["text"] for d in diaries[:6])
    ref = llm.complete(
        with_prose("用這人的口吻，兩句話寫出私心。不准添新事實。"),
        blob,
        strong=False,
    )
    if ref:
        world.write_reflection(actor_id, ref[:500])


class ActorAgent:
    def __init__(self, llm: LLM | None = None):
        self.llm = llm or LLM()

    def run(
        self,
        world: World,
        actor_id: str,
        extra: str = "",
        *,
        in_encounter: bool = False,
        allow_encounter: bool = True,
        mutate_budget: int | None = None,
        max_rounds: int | None = None,
    ) -> dict[str, Any]:
        a = world.actor(actor_id)
        if not a["alive"]:
            return {"ok": False, "reason": "dead"}
        budget = 1 if in_encounter else (mutate_budget if mutate_budget is not None else MUTATE_BUDGET)
        deps = ActorDeps(
            world=world,
            llm=self.llm,
            actor_id=actor_id,
            extra=extra,
            in_encounter=in_encounter,
            allow_encounter=allow_encounter and not in_encounter,
            mutate_budget=budget,
            max_rounds=max_rounds if max_rounds is not None else MAX_ENCOUNTER_ROUNDS,
        )
        if self.llm.mode == "mock" or llm_mode() == "mock":
            return self._run_mock(deps)
        return self._run_live(deps)

    def _run_mock(self, deps: ActorDeps) -> dict[str, Any]:
        from playout.actors import decide

        decision = decide(deps.world, deps.llm, deps.actor_id, deps.extra)
        if decision.goal_update:
            deps.world.set_actor_goal(deps.actor_id, decision.goal_update[:240])
        if decision.mood:
            deps.world.set_actor_mood(deps.actor_id, decision.mood[:40])
        result = dispatch_action(deps, decision.action)
        thought = decision.thought.strip()
        if thought:
            event_id = result.get("event_id")
            deps.world.write_diary(
                deps.actor_id,
                f"{thought} 於是：{getattr(decision.action, 'type', 'act')}。",
                importance=6
                if decision.action.type in ("attack", "kill", "examine")
                else 4,
                event_id=event_id,
            )
        _maybe_reflect(deps.world, deps.llm, deps.actor_id)
        result["thought"] = thought
        result["action"] = decision.action.model_dump()
        result["mutates_used"] = deps.mutates_used
        return result

    def _run_live(self, deps: ActorDeps) -> dict[str, Any]:
        from pydantic_ai import Agent, RunContext

        agent: Agent[ActorDeps, ActorInner] = Agent(
            openrouter_model(actor_model_name()),
            deps_type=ActorDeps,
            output_type=ActorInner,
            instructions=ACTOR_SYSTEM,
        )

        @agent.instructions
        def _ctx(ctx: RunContext[ActorDeps]) -> str:
            note = ""
            if ctx.deps.in_encounter:
                note = "這是對持中的即時反應。只動一次。不可再開對持。"
            left = ctx.deps.mutate_budget - ctx.deps.mutates_used
            return (
                view_as_prompt(ctx.deps.world, ctx.deps.actor_id, ctx.deps.extra)
                + f"\n剩餘可改世界的行動：{left}。\n{note}"
            )

        @agent.tool
        def survey(ctx: RunContext[ActorDeps]) -> str:
            """再看一眼此地：誰在、何物、相鄰何處。"""
            return view_as_prompt(ctx.deps.world, ctx.deps.actor_id, ctx.deps.extra)

        @agent.tool
        def recall(ctx: RunContext[ActorDeps], query: str) -> str:
            """從自己的日記裡想起與這句相關的事。"""
            rows = retrieve(ctx.deps.world, ctx.deps.actor_id, query)
            return "\n".join(f"- {m}" for m in rows) or "（日記空白）"

        def _go(ctx: RunContext[ActorDeps], action: Action) -> str:
            result = dispatch_action(ctx.deps, action)
            return format_action_return(ctx.deps.world, ctx.deps.actor_id, result)

        @agent.tool
        def move(ctx: RunContext[ActorDeps], to: str) -> str:
            """走到相鄰地點。"""
            return _go(ctx, MoveAction(to=to))

        @agent.tool
        def speak_to(ctx: RunContext[ActorDeps], target: str, speech: str) -> str:
            """對在場之人說話。對方可能立刻回應，結果會回到這裡。"""
            return _go(ctx, SpeakAction(target=target, speech=speech))

        @agent.tool
        def take(ctx: RunContext[ActorDeps], object_id: str) -> str:
            """取走眼前之物。"""
            return _go(ctx, TakeAction(object_id=object_id))

        @agent.tool
        def drop(ctx: RunContext[ActorDeps], object_id: str) -> str:
            """放下隨身之物。"""
            return _go(ctx, DropAction(object_id=object_id))

        @agent.tool
        def examine(ctx: RunContext[ActorDeps], target: str) -> str:
            """察看物件或此地。"""
            return _go(ctx, ExamineAction(target=target))

        @agent.tool
        def wait(ctx: RunContext[ActorDeps]) -> str:
            """等候、傾聽，或在對持裡不理對方。"""
            return _go(ctx, WaitAction())

        @agent.tool
        def write_note(ctx: RunContext[ActorDeps], text: str) -> str:
            """寫下一紙。"""
            return _go(ctx, WriteNoteAction(text=text))

        @agent.tool
        def attack(ctx: RunContext[ActorDeps], target: str) -> str:
            """襲擊在場之人。對方可能立刻還手。"""
            return _go(ctx, AttackAction(target=target))

        @agent.tool
        def kill(ctx: RunContext[ActorDeps], target: str) -> str:
            """試圖殺死在場之人。勿輕易為之。"""
            return _go(ctx, KillAction(target=target))

        prompt = "在這一時辰行動。用工具改世界，再交出心思。"
        if deps.extra:
            prompt = deps.extra + "\n" + prompt
        out = agent.run_sync(prompt, deps=deps)
        inner = out.output if isinstance(out.output, ActorInner) else ActorInner()
        last = deps.last_results[-1] if deps.last_results else {"ok": True, "action": {"type": "wait"}}
        action_dump = last.get("action")
        action_obj = None
        if deps.last_results:
            # recover type from last applied
            pass
        if inner.goal_update:
            deps.world.set_actor_goal(deps.actor_id, inner.goal_update[:240])
        if inner.mood:
            deps.world.set_actor_mood(deps.actor_id, inner.mood[:40])
        thought = (inner.thought or "").strip()
        if thought:
            last_eid = last.get("event_id")
            kind = "act"
            if isinstance(action_dump, dict):
                kind = action_dump.get("type", "act")
            deps.world.write_diary(
                deps.actor_id,
                f"{thought} 於是：{kind}。",
                importance=6 if kind in ("attack", "kill", "examine") else 4,
                event_id=last_eid,
            )
        _maybe_reflect(deps.world, deps.llm, deps.actor_id)
        last = dict(last)
        last["thought"] = thought
        last["mutates_used"] = deps.mutates_used
        last["inner"] = inner.model_dump()
        return last
