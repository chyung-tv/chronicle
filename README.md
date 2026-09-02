# Play Out

A small sealed-canon story simulation. You design a town, let characters act, inject world events, and **steer** future plot without rewriting what already happened.

The sim writes in **Taiwan Traditional Chinese** (書面語 for narration, diaries, tape, and chapters; spoken register for dialogue). IDs stay English.

Harbor's End / 港尾 ships as the first pressure-cooker: four people, six places, a stolen skiff, an affair, a storm in three days.

If you already have a `playout.db` from an English seed, **Reset world** in the UI (or delete the database) so the Chinese scenario loads.

## Run

Two processes: FastAPI owns SQLite and inference; Next.js is the UI.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m playout
```

In another terminal:

```bash
cd web
npm install
npm run dev
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000). The Next app rewrites `/api/*` to FastAPI on [http://127.0.0.1:8765](http://127.0.0.1:8765) (`PLAYOUT_API_ORIGIN` to override).

Without an API key the sim uses a heuristic mock LLM so the loop still runs. For live models, copy `.env.example` to `.env` and set `OPENROUTER_API_KEY`. Default model is `deepseek/deepseek-v4-flash-0731` via [OpenRouter](https://openrouter.ai/deepseek/deepseek-v4-flash-0731). Agents are [pydantic-ai](https://ai.pydantic.dev/) `Agent`s (`OpenRouterModel`); set `PLAYOUT_LLM_MODE=mock` to force heuristics even when a key is present.

The UI subscribes to `GET /api/stream` (SSE from a read-only SQLite connection). `POST /api/tick` only starts a slot; the tape updates as referee tools commit.

## How it works

Canon is SQLite. The event tape, diaries, and chapters are append-only.

```
SteerAgent (dawn, off-budget) → queues injections
Day plan: shuffled actor bag (each living actor ≥1 run)
           length = randint(n, n × multiplier)  default multiplier 2
           event slots inserted at random gaps
ActorAgent reads a private view, mutates World only via referee tools
Encounter hold: if A speaks to / strikes co-located B, A's tool waits;
                B runs once (no nested hold); A sees the outcome as the tool result
EventAgent is the only patch writer (inject, steer rungs, idle pressure)
WriterAgent retells the tape at day end
```

Day start = the run sequence is planned. Day end = last slot done, then the chapter. There is no clock of 黎明/上午; a beat is one slot in that sequence.

Co-located replies do not consume B's later scheduled run. A's scheduled beat has a mutate budget of 4 (including up to 3 encounter rounds).

Steer never writes a kill, never overwrites a goal, never edits the past. Soft: the outcome can fail.

## Tests

```bash
pytest -q
cd web && npm run build
```
