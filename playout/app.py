"""FastAPI app: map, tape, diaries, chapters, inject, steer. No rewrite UI."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from playout.loop import SCENARIO, Simulation

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DB = Path(os.getenv("PLAYOUT_DB", str(ROOT / "playout.db")))

sim: Simulation | None = None


def get_sim() -> Simulation:
    global sim
    if sim is None:
        sim = Simulation.open(str(DB), str(SCENARIO))
    return sim


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_sim()
    yield
    if sim:
        sim.world.close()


app = FastAPI(title="Play Out", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(WEB)), name="static")


class TextIn(BaseModel):
    text: str


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/state")
def state():
    return get_sim().world.snapshot()


@app.post("/api/tick")
def tick():
    return get_sim().tick()


@app.post("/api/day")
def run_day():
    return {"ticks": get_sim().run_day(), "state": get_sim().world.snapshot()}


@app.post("/api/inject")
def inject(body: TextIn):
    if not body.text.strip():
        raise HTTPException(400, "empty")
    result = get_sim().inject(body.text.strip())
    return {"result": result, "state": get_sim().world.snapshot()}


@app.post("/api/steer")
def steer(body: TextIn):
    if not body.text.strip():
        raise HTTPException(400, "empty")
    result = get_sim().steer(body.text.strip())
    return {"result": result, "state": get_sim().world.snapshot()}


@app.post("/api/reset")
def reset():
    global sim
    if sim:
        sim.world.close()
    if DB.exists():
        DB.unlink()
    for suffix in ("-wal", "-shm"):
        p = Path(str(DB) + suffix)
        if p.exists():
            p.unlink()
    sim = Simulation.create(str(DB), str(SCENARIO))
    return sim.world.snapshot()
