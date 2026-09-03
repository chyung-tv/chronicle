# Play Out

A small sealed-canon story simulation. You design a town, let characters act, inject world events, and **steer** future plot without rewriting what already happened.

The sim writes in **Taiwan Traditional Chinese** (書面語 for narration, diaries, tape, and chapters; spoken register for dialogue). IDs stay English.

Stories are first-class objects. Each story has a **setup** (worldview, map, cast) and, once started, a sealed **canon**. Harbor's End / 港尾 is the first seeded live story: four people, six places, a stolen skiff, an affair, a storm in three days.

While a story is live, the owner cannot edit the birth sheet — only god tools (inject / steer). **重置世界** is temporary scaffolding: it unseals the story back to draft so you can edit setup again. It will be removed once stories are unique and irreplaceable.

## Run

Two processes locally: FastAPI (catalog, jobs, inference) and Next.js. Long LLM work (wizard, tick, day) is a **job** on the catalog. With no `DATABASE_URL`, the API also runs an inline worker. On Railway, `start.sh` runs FastAPI, `python -m playout.worker`, and Next.

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

Open [http://127.0.0.1:3000](http://127.0.0.1:3000). The catalog lists stories. Enter a live board at `/s/{id}`; the owner designs a draft at `/s/{id}/design`. The Next app rewrites `/api/*` to FastAPI on [http://127.0.0.1:8765](http://127.0.0.1:8765) (`PLAYOUT_API_ORIGIN` to override). `/api/auth/*` is reserved for better-auth / Auth.js later (Next `afterFiles` rewrite).

Without an API key the sim uses a heuristic mock LLM so the loop still runs. For live models, copy `.env.example` to `.env` and set `OPENROUTER_API_KEY`. Default model is `deepseek/deepseek-v4-flash-0731` via [OpenRouter](https://openrouter.ai/deepseek/deepseek-v4-flash-0731). Agents are [pydantic-ai](https://ai.pydantic.dev/) `Agent`s (`OpenRouterModel`); set `PLAYOUT_LLM_MODE=mock` to force heuristics even when a key is present.

The play UI subscribes to `GET /api/stories/{id}/stream`. `POST /api/stories/{id}/tick` enqueues a job and returns `{accepted: true}`; the tape updates as the worker commits.

Auth is stubbed (`X-User-Id` / cookie / `PLAYOUT_DEV_USER_ID`, default `dev-owner`). Session helpers in `playout/auth.py` and `web/lib/auth.ts` are the swap point for better-auth or Auth.js.

## Catalog and files

- `catalog.db` — story rows and the `jobs` queue (`PLAYOUT_CATALOG` to override). On Railway, the catalog is a Postgres table (`DATABASE_URL` from the Postgres plugin).
- `data/stories/{id}.db` — sealed canon per story (`PLAYOUT_STORIES_DIR`). On Railway each story is a Postgres schema `story_<id>`.
- `scenarios/harbors_end.json` — seed for 港尾

## Railway

The Dockerfile runs FastAPI on `127.0.0.1:8765`, a job worker, and Next.js on `$PORT`. Set `DATABASE_URL` to `${{Postgres.DATABASE_URL}}` on the `chronicle` service. Optional: `OPENROUTER_API_KEY` for live models. `PLAYOUT_WORKER=external` (the image default) so only the worker process drains jobs.

## How it works

Canon is append-only (SQLite locally, Postgres on Railway). The event tape, diaries, and chapters cannot be rewritten.

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
