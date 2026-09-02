# Play Out

A small sealed-canon story simulation. You design a town, let characters act, inject world events, and **steer** future plot without rewriting what already happened.

Harbor's End ships as the first pressure-cooker: four people, six places, a stolen skiff, an affair, a storm in three days.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m playout
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765).

Without an API key the sim uses a heuristic mock LLM so the loop still runs. For live models, copy `.env.example` to `.env` and set `OPENROUTER_API_KEY`. Default model is `deepseek/deepseek-v4-flash-0731` via [OpenRouter](https://openrouter.ai/deepseek/deepseek-v4-flash-0731).

## How it works

- **Canon** is SQLite. The event tape, diaries, and chapters are append-only.
- **Actors** only see their own perceptions. They choose structured actions; a referee applies them.
- **Storyteller** turns "a meteor strikes the quay" into state patches (ruin the quay, injure who is there, perceptions).
- **Steer** turns "Mara should ruin Tomas" into a campaign of motive / means / opportunity / escalation. It never writes a kill, never overwrites a goal, never edits the past. Soft: the outcome can fail.
- **Writer** retells each day from the tape. No rewrite box.

## Tests

```bash
pytest -q
```
