"""Actor agent: reads ActorView, mutates World only through referee tools."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import Agent, RunContext, ToolDefinition

from playout.agents.model import llm_mode, openrouter_model, actor_model_name
from playout.agents.referee import (
    RefereeAgent,
    action_as_interact_text,
    named_present_actor,
)
from playout.agents.views import view_as_prompt
from playout.canon import World
from playout.llm import LLM
from playout.memory import retrieve
from playout.models import (
    Action,
    ActorInner,
    InteractAction,
    MoveAction,
    WaitAction,
)
from playout.referee import apply_action
from playout.zh import with_prose

MUTATE_BUDGET = 4
MAX_ENCOUNTER_ROUNDS = 3

ACTION_ACTIVITY = {
    "move": "正在前往",
    "interact": "正在行事",
    "wait": "正在等候",
}

ACTOR_SYSTEM = with_prose("""你是活在故事裡的人物，須守住人格，不是助手。
你只知道自己感知過、寫進日記的事。別人的秘密，除非你已得知，否則你不知道。
目標由你自己從所見所聞長出。誰也不能替你派一個目標。

用工具在世上行動。讀類工具（survey、recall）不計次數。
改世界的工具每回合最多四次：move、interact、wait。
interact 用自然語言寫出你此刻試圖做的事（對誰說話、取物、察看、動手、寫紙等）。
若你點了在場之人的名，工具會先讓對方反應，再由裁判判定雙方實際做成什麼，把你能感知到的結果回給你。
對方不理、走開、或已來回三次，這場對持即止。

最後輸出 JSON 形的心思：thought、goal_update、mood。不要敘述世界。
speech、thought、goal_update、interact 的 text 一律繁體中文。
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


def prepare_move(ctx: RunContext[ActorDeps], tool_def: ToolDefinition) -> ToolDefinition | None:
    """Inject current intact exits as the only accepted `to` values."""
    a = ctx.deps.world.actor(ctx.deps.actor_id)
    exits = ctx.deps.world.exits(a["location_id"])
    if not exits:
        return None
    ids = [e.id for e in exits]
    schema = tool_def.parameters_json_schema
    props = schema.setdefault("properties", {})
    to_schema = props.setdefault("to", {"type": "string"})
    to_schema["enum"] = ids
    to_schema["description"] = "、".join(f"{e.id}（{e.name}）" for e in exits)
    return tool_def


def _activity_for(deps: ActorDeps, action: Action) -> None:
    name = deps.world.actor(deps.actor_id)["name"]
    kind = getattr(action, "type", "act")
    verb = ACTION_ACTIVITY.get(kind, "正在行動")
    deps.world.set_activity(
        "thinking", actor=deps.actor_id, detail=f"{name}{verb}"
    )


def _finish(deps: ActorDeps, result: dict[str, Any], action: Action | None = None) -> dict[str, Any]:
    if action is not None and "action" not in result:
        result["action"] = action.model_dump()
    deps.last_results.append(result)
    return result


async def _solo_or_held_interact(deps: ActorDeps, text: str) -> dict[str, Any]:
    world = deps.world
    if deps.in_encounter:
        return await _complete_held_interact(deps, text)

    counterpart = named_present_actor(world, deps.actor_id, text)
    if (
        counterpart
        and deps.allow_encounter
        and not deps.in_encounter
        and deps.encounter_rounds < deps.max_rounds
    ):
        deps.encounter_rounds += 1
        from playout.agents.encounter import hold_encounter

        held = await hold_encounter(
            world, deps.llm, deps.actor_id, counterpart, text
        )
        verdict = held.get("verdict") or {}
        result = {
            "ok": held.get("ok", True),
            "event_id": held.get("event_id") or verdict.get("event_id"),
            "summary": held.get("summary") or verdict.get("summary"),
            "kind": verdict.get("kind"),
            "action": {"type": "interact", "text": text},
            "encounter": held,
        }
        if not result.get("ok") and held.get("result", {}).get("reason"):
            result["reason"] = held["result"]["reason"]
        return _finish(deps, result, InteractAction(text=text))

    world.set_activity("thinking", actor="referee", detail="裁判正在判定")
    verdict = await RefereeAgent(deps.llm).judge(
        world,
        a_id=deps.actor_id,
        a_text=text,
        b_id=None,
        b_text=None,
    )
    verdict = dict(verdict)
    verdict["action"] = {"type": "interact", "text": text}
    return _finish(deps, verdict, InteractAction(text=text))


async def _complete_held_interact(deps: ActorDeps, b_text: str | None) -> dict[str, Any]:
    world = deps.world
    meta = world.get_encounter() or {}
    if meta.get("resolved") and meta.get("verdict"):
        result = dict(meta["verdict"])
        return _finish(deps, result)

    if not meta.get("active"):
        text = b_text or ""
        world.set_activity("thinking", actor="referee", detail="裁判正在判定")
        verdict = await RefereeAgent(deps.llm).judge(
            world,
            a_id=deps.actor_id,
            a_text=text,
            b_id=None,
            b_text=None,
        )
        verdict = dict(verdict)
        verdict["action"] = {"type": "interact", "text": text}
        return _finish(deps, verdict)

    meta["b_text"] = b_text
    world.set_encounter(meta)
    world.set_activity("thinking", actor="referee", detail="裁判正在判定")
    verdict = await RefereeAgent(deps.llm).judge(
        world,
        a_id=str(meta.get("initiator") or deps.actor_id),
        a_text=str(meta.get("a_text") or ""),
        b_id=str(meta.get("counterpart") or deps.actor_id),
        b_text=b_text,
    )
    meta = world.get_encounter() or meta
    meta["resolved"] = True
    meta["verdict"] = verdict
    meta["b_text"] = b_text
    world.set_encounter(meta)
    result = dict(verdict)
    result["action"] = {"type": "interact", "text": b_text or ""}
    return _finish(deps, result)


async def dispatch_action_async(deps: ActorDeps, action: Action) -> dict[str, Any]:
    if deps.mutates_used >= deps.mutate_budget:
        return {"ok": False, "reason": "budget", "detail": "這一時辰你已動得夠多。"}
    _activity_for(deps, action)
    deps.mutates_used += 1

    if deps.in_encounter:
        if isinstance(action, WaitAction):
            return await _complete_held_interact(deps, None)
        text = action_as_interact_text(deps.world, deps.actor_id, action)
        if text is None:
            return _finish(
                deps,
                {"ok": False, "reason": "no_move_in_encounter"},
                action,
            )
        return await _complete_held_interact(deps, text)

    text = action_as_interact_text(deps.world, deps.actor_id, action)
    if isinstance(action, InteractAction) or (
        text is not None and not isinstance(action, (MoveAction, WaitAction))
    ):
        return await _solo_or_held_interact(deps, text or "")

    if isinstance(action, MoveAction) and deps.in_encounter:
        return _finish(deps, {"ok": False, "reason": "no_move_in_encounter"}, action)

    result = apply_action(deps.world, deps.actor_id, action)
    result["action"] = action.model_dump()
    if result.get("event_id"):
        ev = deps.world.cx.execute(
            "SELECT summary FROM events WHERE id=?", (result["event_id"],)
        ).fetchone()
        if ev:
            result["summary"] = ev["summary"]
    return _finish(deps, result, action)


def dispatch_action(deps: ActorDeps, action: Action) -> dict[str, Any]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(dispatch_action_async(deps, action))
    raise RuntimeError("await dispatch_action_async from a running event loop")


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
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.run_async(
                    world,
                    actor_id,
                    extra,
                    in_encounter=in_encounter,
                    allow_encounter=allow_encounter,
                    mutate_budget=mutate_budget,
                    max_rounds=max_rounds,
                )
            )
        raise RuntimeError("await ActorAgent.run_async from a running event loop")

    async def run_async(
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
        budget = 1 if in_encounter else (
            mutate_budget if mutate_budget is not None else MUTATE_BUDGET
        )
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
            return await self._run_mock(deps)
        return await self._run_live(deps)

    async def _run_mock(self, deps: ActorDeps) -> dict[str, Any]:
        from playout.actors import decide

        decision = decide(deps.world, deps.llm, deps.actor_id, deps.extra)
        if decision.goal_update:
            deps.world.set_actor_goal(deps.actor_id, decision.goal_update[:240])
        if decision.mood:
            deps.world.set_actor_mood(deps.actor_id, decision.mood[:40])
        result = await dispatch_action_async(deps, decision.action)
        thought = decision.thought.strip()
        if thought:
            event_id = result.get("event_id")
            kind = getattr(decision.action, "type", "act")
            deps.world.write_diary(
                deps.actor_id,
                f"{thought} 於是：{kind}。",
                importance=6
                if kind in ("attack", "kill", "examine", "interact")
                else 4,
                event_id=event_id,
            )
        _maybe_reflect(deps.world, deps.llm, deps.actor_id)
        result = dict(result)
        result["thought"] = thought
        result["action"] = decision.action.model_dump()
        result["mutates_used"] = deps.mutates_used
        return result

    async def _run_live(self, deps: ActorDeps) -> dict[str, Any]:
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
                note = (
                    "這是對持中的即時反應。只動一次。不可再開對持。"
                    "用 interact 寫出你試圖做的事，或 wait 不理。"
                )
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

        @agent.tool
        async def interact(ctx: RunContext[ActorDeps], text: str) -> str:
            """用自然語言寫出你此刻試圖做的事：對誰說話、取物、察看、動手、寫紙等。"""
            result = await dispatch_action_async(
                ctx.deps, InteractAction(text=text)
            )
            return format_action_return(ctx.deps.world, ctx.deps.actor_id, result)

        @agent.tool
        async def wait(ctx: RunContext[ActorDeps]) -> str:
            """等候、傾聽，或在對持裡不理對方。"""
            result = await dispatch_action_async(ctx.deps, WaitAction())
            return format_action_return(ctx.deps.world, ctx.deps.actor_id, result)

        if not deps.in_encounter:

            @agent.tool(prepare=prepare_move)
            async def move(ctx: RunContext[ActorDeps], to: str) -> str:
                """走到相鄰完好地點。to 只能是當前可走的 location_id。"""
                result = await dispatch_action_async(ctx.deps, MoveAction(to=to))
                return format_action_return(ctx.deps.world, ctx.deps.actor_id, result)

        prompt = "在這一時辰行動。用工具改世界，再交出心思。"
        if deps.extra:
            prompt = deps.extra + "\n" + prompt
        out = await agent.run(prompt, deps=deps)
        inner = out.output if isinstance(out.output, ActorInner) else ActorInner()
        last = (
            deps.last_results[-1]
            if deps.last_results
            else {"ok": True, "action": {"type": "wait"}}
        )
        action_dump = last.get("action")
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
                importance=6 if kind in ("attack", "kill", "examine", "interact") else 4,
                event_id=last_eid,
            )
        _maybe_reflect(deps.world, deps.llm, deps.actor_id)
        last = dict(last)
        last["thought"] = thought
        last["mutates_used"] = deps.mutates_used
        last["inner"] = inner.model_dump()
        return last
