"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { DesignMap } from "@/components/DesignMap";
import { api, fetchMe, fetchStory, postStart } from "@/lib/api";
import type {
  ActorSetup,
  LocationSetup,
  OpeningEventSetup,
  ObjectSetup,
  RelationshipSetup,
  StoryDetail,
  StorySetup,
} from "@/lib/types";

function nextId(prefix: string, used: string[]) {
  let n = 1;
  while (used.includes(`${prefix}${n}`)) n += 1;
  return `${prefix}${n}`;
}

function cloneSetup(s: StorySetup): StorySetup {
  return JSON.parse(JSON.stringify(s)) as StorySetup;
}

export function DesignConsole({ storyRef }: { storyRef: string }) {
  const router = useRouter();
  const [story, setStory] = useState<StoryDetail | null>(null);
  const [setup, setSetup] = useState<StorySetup | null>(null);
  const [slug, setSlug] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [locSel, setLocSel] = useState<string | null>(null);
  const [edgeFrom, setEdgeFrom] = useState("");
  const [edgeTo, setEdgeTo] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await fetchMe();
        const rec = await fetchStory(storyRef);
        if (cancelled) return;
        if (!rec.is_owner) {
          setError("只有主人可以看世界設定。");
          return;
        }
        setStory(rec);
        setSetup(cloneSetup(rec.setup));
        setSlug(rec.slug);
        setLocSel(rec.setup.locations[0]?.id || null);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [storyRef]);

  const readonly = !!story && !story.editable;

  const set = (patch: Partial<StorySetup>) => {
    setSetup((prev) => (prev ? { ...prev, ...patch } : prev));
  };

  const locName = (id: string) =>
    setup?.locations.find((l) => l.id === id)?.name || id;
  const actorName = (id: string) =>
    setup?.actors.find((a) => a.id === id)?.name || id;

  const save = async (ev?: FormEvent) => {
    ev?.preventDefault();
    if (!story || !setup || readonly) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const rec = await api<StoryDetail>(`/api/stories/${story.id}`, {
        method: "PATCH",
        body: JSON.stringify({ slug, setup: { ...setup, title: setup.title } }),
      });
      setStory(rec);
      setSetup(cloneSetup(rec.setup));
      setSlug(rec.slug);
      setNotice("已存設定。");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    if (!story || !setup) return;
    setBusy(true);
    setError(null);
    try {
      if (!readonly) {
        await api(`/api/stories/${story.id}`, {
          method: "PATCH",
          body: JSON.stringify({ slug, setup }),
        });
      }
      const rec = await postStart(story.id);
      router.push(`/s/${rec.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  const usedLoc = useMemo(
    () => (setup ? setup.locations.map((l) => l.id) : []),
    [setup]
  );
  const usedAct = useMemo(
    () => (setup ? setup.actors.map((a) => a.id) : []),
    [setup]
  );
  const usedObj = useMemo(
    () => (setup ? setup.objects.map((o) => o.id) : []),
    [setup]
  );

  if (error && !story) {
    return (
      <header className="masthead">
        <div className="mast-title">
          <p className="chrome-links">
            <Link href="/">故事</Link>
          </p>
          <h1>世界設定</h1>
          <p className="sub">{error}</p>
        </div>
      </header>
    );
  }

  if (!story || !setup) {
    return (
      <header className="masthead">
        <div className="mast-title">
          <h1>世界設定</h1>
          <p className="sub">載入…</p>
        </div>
      </header>
    );
  }

  const addLocation = () => {
    const id = nextId("place", usedLoc);
    const loc: LocationSetup = {
      id,
      name: "新處",
      description: "",
      x: 270,
      y: 180,
    };
    set({ locations: [...setup.locations, loc] });
    setLocSel(id);
  };

  const addActor = () => {
    const id = nextId("actor", usedAct);
    const home = setup.locations[0]?.id || "place";
    const act: ActorSetup = {
      id,
      name: "新人",
      location: home,
      voice: "",
      want: "",
      secret: "",
      constitution: "",
      goal: "",
      mood: "靜",
    };
    set({ actors: [...setup.actors, act] });
  };

  const addObject = () => {
    const id = nextId("obj", usedObj);
    const obj: ObjectSetup = {
      id,
      name: "物件",
      description: "",
      location_id: setup.locations[0]?.id || null,
      holder_id: null,
      hidden: false,
    };
    set({ objects: [...setup.objects, obj] });
  };

  const addRel = () => {
    if (setup.actors.length < 2) return;
    const rel: RelationshipSetup = {
      a: setup.actors[0].id,
      b: setup.actors[1].id,
      trust: 0,
      resentment: 0,
      notes: "",
    };
    set({ relationships: [...setup.relationships, rel] });
  };

  const addOpening = () => {
    const ev: OpeningEventSetup = {
      kind: "world",
      summary: "",
      perceive: setup.actors.map((a) => a.id),
    };
    set({ opening_events: [...setup.opening_events, ev] });
  };

  const addEdge = () => {
    if (!edgeFrom || !edgeTo || edgeFrom === edgeTo) return;
    const exists = setup.edges.some(
      ([a, b]) =>
        (a === edgeFrom && b === edgeTo) || (a === edgeTo && b === edgeFrom)
    );
    if (exists) return;
    set({ edges: [...setup.edges, [edgeFrom, edgeTo]] });
  };

  return (
    <>
      <header className="masthead">
        <div className="mast-title">
          <p className="chrome-links">
            <Link href="/">故事</Link>
            {story.status === "live" ? (
              <Link href={`/s/${story.id}`}>進入演繹</Link>
            ) : null}
          </p>
          <h1>{setup.title || "世界設定"}</h1>
          <p className="sub">
            {readonly
              ? "世界已封。此為開演時的出生設定，只讀。要以神諭改明日，請回演繹。"
              : "尚未開演。寫好地圖與人物後，開始演繹，世界即封。"}
          </p>
        </div>
        <div className="controls">
          {!readonly ? (
            <>
              <button type="button" disabled={busy} onClick={() => save()}>
                儲存設定
              </button>
              <button type="button" disabled={busy} onClick={start}>
                開始演繹
              </button>
            </>
          ) : (
            <Link className="btn" href={`/s/${story.id}`}>
              回演繹
            </Link>
          )}
        </div>
        {error ? <p className="banner">{error}</p> : null}
        {notice ? <p className="banner ok">{notice}</p> : null}
      </header>

      <form className="design" onSubmit={save} aria-readonly={readonly}>
        <fieldset disabled={readonly} className="design-section">
          <h2>識別</h2>
          <label>
            標題
            <input
              value={setup.title}
              onChange={(e) => set({ title: e.target.value })}
            />
          </label>
          <label>
            短名
            <input value={slug} onChange={(e) => setSlug(e.target.value)} />
          </label>
          <label>
            日數
            <input
              type="number"
              min={1}
              value={setup.days}
              onChange={(e) => set({ days: Number(e.target.value) })}
            />
          </label>
          <label>
            每日場次數
            <input
              type="number"
              min={1}
              value={setup.scenes_per_day}
              onChange={(e) =>
                set({ scenes_per_day: Number(e.target.value) })
              }
            />
          </label>
          <label>
            日行倍率
            <input
              type="number"
              min={1}
              value={setup.day_run_multiplier}
              onChange={(e) =>
                set({ day_run_multiplier: Number(e.target.value) })
              }
            />
          </label>
          <label className="wide">
            天氣
            <input
              value={setup.weather}
              onChange={(e) => set({ weather: e.target.value })}
            />
          </label>
          <label>
            期限（日）
            <input
              type="number"
              value={setup.clock.storm_in_days ?? ""}
              onChange={(e) =>
                set({
                  clock: {
                    ...setup.clock,
                    storm_in_days: e.target.value
                      ? Number(e.target.value)
                      : null,
                  },
                })
              }
            />
          </label>
          <label className="wide">
            時鐘備註
            <input
              value={setup.clock.note || ""}
              onChange={(e) =>
                set({ clock: { ...setup.clock, note: e.target.value } })
              }
            />
          </label>
        </fieldset>

        <fieldset disabled={readonly} className="design-section">
          <h2>世界觀</h2>
          <textarea
            rows={6}
            value={setup.worldview}
            onChange={(e) => set({ worldview: e.target.value })}
          />
        </fieldset>

        <fieldset disabled={readonly} className="design-section">
          <h2>地圖</h2>
          <p className="hint-inline">
            選一處，再點鎮圖空白處安放。用下拉連路。
          </p>
          <DesignMap
            locations={setup.locations}
            edges={setup.edges}
            selected={locSel}
            readonly={readonly}
            onSelect={setLocSel}
            onPlace={(id, x, y) =>
              set({
                locations: setup.locations.map((l) =>
                  l.id === id ? { ...l, x, y } : l
                ),
              })
            }
          />
          {setup.locations.map((loc, i) => (
            <div
              className={`subcard${loc.id === locSel ? " on" : ""}`}
              key={loc.id}
            >
              <div className="row">
                <label>
                  id
                  <input
                    value={loc.id}
                    onChange={(e) => {
                      const nid = e.target.value;
                      set({
                        locations: setup.locations.map((l, j) =>
                          j === i ? { ...l, id: nid } : l
                        ),
                        edges: setup.edges.map(([a, b]) => [
                          a === loc.id ? nid : a,
                          b === loc.id ? nid : b,
                        ]),
                        actors: setup.actors.map((a) =>
                          a.location === loc.id ? { ...a, location: nid } : a
                        ),
                        objects: setup.objects.map((o) =>
                          o.location_id === loc.id
                            ? { ...o, location_id: nid }
                            : o
                        ),
                      });
                      if (locSel === loc.id) setLocSel(nid);
                    }}
                  />
                </label>
                <label>
                  名
                  <input
                    value={loc.name}
                    onChange={(e) =>
                      set({
                        locations: setup.locations.map((l, j) =>
                          j === i ? { ...l, name: e.target.value } : l
                        ),
                      })
                    }
                  />
                </label>
                <button
                  type="button"
                  className="ghost"
                  onClick={() => setLocSel(loc.id)}
                >
                  選
                </button>
                {setup.locations.length > 1 ? (
                  <button
                    type="button"
                    className="ghost"
                    onClick={() =>
                      set({
                        locations: setup.locations.filter((_, j) => j !== i),
                        edges: setup.edges.filter(
                          ([a, b]) => a !== loc.id && b !== loc.id
                        ),
                      })
                    }
                  >
                    刪
                  </button>
                ) : null}
              </div>
              <textarea
                rows={2}
                value={loc.description}
                onChange={(e) =>
                  set({
                    locations: setup.locations.map((l, j) =>
                      j === i ? { ...l, description: e.target.value } : l
                    ),
                  })
                }
              />
            </div>
          ))}
          <button type="button" className="ghost" onClick={addLocation}>
            加一處
          </button>
          <div className="row">
            <select
              value={edgeFrom}
              onChange={(e) => setEdgeFrom(e.target.value)}
            >
              <option value="">從</option>
              {setup.locations.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
            <select value={edgeTo} onChange={(e) => setEdgeTo(e.target.value)}>
              <option value="">至</option>
              {setup.locations.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
            <button type="button" className="ghost" onClick={addEdge}>
              連路
            </button>
          </div>
          <ul className="edge-list">
            {setup.edges.map(([a, b], i) => (
              <li key={`${a}-${b}-${i}`}>
                {locName(a)} — {locName(b)}
                <button
                  type="button"
                  className="ghost"
                  onClick={() =>
                    set({ edges: setup.edges.filter((_, j) => j !== i) })
                  }
                >
                  刪
                </button>
              </li>
            ))}
          </ul>
        </fieldset>

        <fieldset disabled={readonly} className="design-section">
          <h2>人物</h2>
          {setup.actors.map((act, i) => (
            <div className="subcard" key={act.id}>
              <div className="row">
                <label>
                  id
                  <input
                    value={act.id}
                    onChange={(e) => {
                      const nid = e.target.value;
                      set({
                        actors: setup.actors.map((a, j) =>
                          j === i ? { ...a, id: nid } : a
                        ),
                        relationships: setup.relationships.map((r) => ({
                          ...r,
                          a: r.a === act.id ? nid : r.a,
                          b: r.b === act.id ? nid : r.b,
                        })),
                        objects: setup.objects.map((o) =>
                          o.holder_id === act.id ? { ...o, holder_id: nid } : o
                        ),
                        opening_events: setup.opening_events.map((ev) => ({
                          ...ev,
                          perceive: ev.perceive.map((p) =>
                            p === act.id ? nid : p
                          ),
                        })),
                      });
                    }}
                  />
                </label>
                <label>
                  名
                  <input
                    value={act.name}
                    onChange={(e) =>
                      set({
                        actors: setup.actors.map((a, j) =>
                          j === i ? { ...a, name: e.target.value } : a
                        ),
                      })
                    }
                  />
                </label>
                <label>
                  所在
                  <select
                    value={act.location}
                    onChange={(e) =>
                      set({
                        actors: setup.actors.map((a, j) =>
                          j === i ? { ...a, location: e.target.value } : a
                        ),
                      })
                    }
                  >
                    {setup.locations.map((l) => (
                      <option key={l.id} value={l.id}>
                        {l.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  心境
                  <input
                    value={act.mood}
                    onChange={(e) =>
                      set({
                        actors: setup.actors.map((a, j) =>
                          j === i ? { ...a, mood: e.target.value } : a
                        ),
                      })
                    }
                  />
                </label>
                {setup.actors.length > 1 ? (
                  <button
                    type="button"
                    className="ghost"
                    onClick={() =>
                      set({
                        actors: setup.actors.filter((_, j) => j !== i),
                        relationships: setup.relationships.filter(
                          (r) => r.a !== act.id && r.b !== act.id
                        ),
                      })
                    }
                  >
                    刪
                  </button>
                ) : null}
              </div>
              <label className="wide">
                聲口
                <textarea
                  rows={2}
                  value={act.voice}
                  onChange={(e) =>
                    set({
                      actors: setup.actors.map((a, j) =>
                        j === i ? { ...a, voice: e.target.value } : a
                      ),
                    })
                  }
                />
              </label>
              <label className="wide">
                深願
                <textarea
                  rows={2}
                  value={act.want}
                  onChange={(e) =>
                    set({
                      actors: setup.actors.map((a, j) =>
                        j === i ? { ...a, want: e.target.value } : a
                      ),
                    })
                  }
                />
              </label>
              <label className="wide">
                眼前之願
                <textarea
                  rows={2}
                  value={act.goal}
                  onChange={(e) =>
                    set({
                      actors: setup.actors.map((a, j) =>
                        j === i ? { ...a, goal: e.target.value } : a
                      ),
                    })
                  }
                />
              </label>
              <label className="wide">
                秘密
                <textarea
                  rows={2}
                  value={act.secret}
                  onChange={(e) =>
                    set({
                      actors: setup.actors.map((a, j) =>
                        j === i ? { ...a, secret: e.target.value } : a
                      ),
                    })
                  }
                />
              </label>
              <label className="wide">
                性情
                <textarea
                  rows={2}
                  value={act.constitution}
                  onChange={(e) =>
                    set({
                      actors: setup.actors.map((a, j) =>
                        j === i ? { ...a, constitution: e.target.value } : a
                      ),
                    })
                  }
                />
              </label>
            </div>
          ))}
          <button type="button" className="ghost" onClick={addActor}>
            加一人
          </button>
        </fieldset>

        <fieldset disabled={readonly} className="design-section">
          <h2>物件</h2>
          {setup.objects.map((obj, i) => (
            <div className="subcard" key={obj.id}>
              <div className="row">
                <label>
                  id
                  <input
                    value={obj.id}
                    onChange={(e) =>
                      set({
                        objects: setup.objects.map((o, j) =>
                          j === i ? { ...o, id: e.target.value } : o
                        ),
                      })
                    }
                  />
                </label>
                <label>
                  名
                  <input
                    value={obj.name}
                    onChange={(e) =>
                      set({
                        objects: setup.objects.map((o, j) =>
                          j === i ? { ...o, name: e.target.value } : o
                        ),
                      })
                    }
                  />
                </label>
                <label>
                  所在
                  <select
                    value={obj.location_id || ""}
                    onChange={(e) =>
                      set({
                        objects: setup.objects.map((o, j) =>
                          j === i
                            ? { ...o, location_id: e.target.value || null }
                            : o
                        ),
                      })
                    }
                  >
                    <option value="">無</option>
                    {setup.locations.map((l) => (
                      <option key={l.id} value={l.id}>
                        {l.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  持有
                  <select
                    value={obj.holder_id || ""}
                    onChange={(e) =>
                      set({
                        objects: setup.objects.map((o, j) =>
                          j === i
                            ? { ...o, holder_id: e.target.value || null }
                            : o
                        ),
                      })
                    }
                  >
                    <option value="">無</option>
                    {setup.actors.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={obj.hidden}
                    onChange={(e) =>
                      set({
                        objects: setup.objects.map((o, j) =>
                          j === i ? { ...o, hidden: e.target.checked } : o
                        ),
                      })
                    }
                  />
                  隱藏
                </label>
                <button
                  type="button"
                  className="ghost"
                  onClick={() =>
                    set({ objects: setup.objects.filter((_, j) => j !== i) })
                  }
                >
                  刪
                </button>
              </div>
              <textarea
                rows={2}
                value={obj.description}
                onChange={(e) =>
                  set({
                    objects: setup.objects.map((o, j) =>
                      j === i ? { ...o, description: e.target.value } : o
                    ),
                  })
                }
              />
            </div>
          ))}
          <button type="button" className="ghost" onClick={addObject}>
            加一物
          </button>
        </fieldset>

        <fieldset disabled={readonly} className="design-section">
          <h2>關係</h2>
          {setup.relationships.map((rel, i) => (
            <div className="subcard" key={`${rel.a}-${rel.b}-${i}`}>
              <div className="row">
                <select
                  value={rel.a}
                  onChange={(e) =>
                    set({
                      relationships: setup.relationships.map((r, j) =>
                        j === i ? { ...r, a: e.target.value } : r
                      ),
                    })
                  }
                >
                  {setup.actors.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
                <select
                  value={rel.b}
                  onChange={(e) =>
                    set({
                      relationships: setup.relationships.map((r, j) =>
                        j === i ? { ...r, b: e.target.value } : r
                      ),
                    })
                  }
                >
                  {setup.actors.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
                <label>
                  信
                  <input
                    type="number"
                    min={-10}
                    max={10}
                    value={rel.trust}
                    onChange={(e) =>
                      set({
                        relationships: setup.relationships.map((r, j) =>
                          j === i ? { ...r, trust: Number(e.target.value) } : r
                        ),
                      })
                    }
                  />
                </label>
                <label>
                  怨
                  <input
                    type="number"
                    min={-10}
                    max={10}
                    value={rel.resentment}
                    onChange={(e) =>
                      set({
                        relationships: setup.relationships.map((r, j) =>
                          j === i
                            ? { ...r, resentment: Number(e.target.value) }
                            : r
                        ),
                      })
                    }
                  />
                </label>
                <button
                  type="button"
                  className="ghost"
                  onClick={() =>
                    set({
                      relationships: setup.relationships.filter(
                        (_, j) => j !== i
                      ),
                    })
                  }
                >
                  刪
                </button>
              </div>
              <input
                placeholder="註"
                value={rel.notes}
                onChange={(e) =>
                  set({
                    relationships: setup.relationships.map((r, j) =>
                      j === i ? { ...r, notes: e.target.value } : r
                    ),
                  })
                }
              />
            </div>
          ))}
          <button type="button" className="ghost" onClick={addRel}>
            加一層
          </button>
        </fieldset>

        <fieldset disabled={readonly} className="design-section">
          <h2>開場事件</h2>
          {setup.opening_events.map((ev, i) => (
            <div className="subcard" key={i}>
              <div className="row">
                <label>
                  類
                  <input
                    value={ev.kind}
                    onChange={(e) =>
                      set({
                        opening_events: setup.opening_events.map((x, j) =>
                          j === i ? { ...x, kind: e.target.value } : x
                        ),
                      })
                    }
                  />
                </label>
                <button
                  type="button"
                  className="ghost"
                  onClick={() =>
                    set({
                      opening_events: setup.opening_events.filter(
                        (_, j) => j !== i
                      ),
                    })
                  }
                >
                  刪
                </button>
              </div>
              <textarea
                rows={2}
                value={ev.summary}
                onChange={(e) =>
                  set({
                    opening_events: setup.opening_events.map((x, j) =>
                      j === i ? { ...x, summary: e.target.value } : x
                    ),
                  })
                }
              />
              <p className="hint-inline">誰知覺</p>
              <div className="checks">
                {setup.actors.map((a) => (
                  <label className="check" key={a.id}>
                    <input
                      type="checkbox"
                      checked={ev.perceive.includes(a.id)}
                      onChange={(e) => {
                        const perceive = e.target.checked
                          ? [...ev.perceive, a.id]
                          : ev.perceive.filter((p) => p !== a.id);
                        set({
                          opening_events: setup.opening_events.map((x, j) =>
                            j === i ? { ...x, perceive } : x
                          ),
                        });
                      }}
                    />
                    {actorName(a.id)}
                  </label>
                ))}
              </div>
            </div>
          ))}
          <button type="button" className="ghost" onClick={addOpening}>
            加一則
          </button>
        </fieldset>
      </form>
    </>
  );
}
