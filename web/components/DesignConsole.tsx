"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { DesignMap } from "@/components/DesignMap";
import { api, fetchMe, fetchStory, postStart, postWizard } from "@/lib/api";
import type {
  ActorSketch,
  ObjectSketch,
  RelationshipSketch,
  StoryDetail,
  StorySetup,
  StorySketch,
} from "@/lib/types";

function nextId(prefix: string, used: string[]) {
  let n = 1;
  while (used.includes(`${prefix}${n}`)) n += 1;
  return `${prefix}${n}`;
}

function clone<T>(s: T): T {
  return JSON.parse(JSON.stringify(s)) as T;
}

export function DesignConsole({ storyRef }: { storyRef: string }) {
  const router = useRouter();
  const [story, setStory] = useState<StoryDetail | null>(null);
  const [sketch, setSketch] = useState<StorySketch | null>(null);
  const [setup, setSetup] = useState<StorySetup | null>(null);
  const [slug, setSlug] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [enriched, setEnriched] = useState(false);

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
        setSketch(clone(rec.sketch));
        setSetup(clone(rec.setup));
        setSlug(rec.slug);
        setEnriched(!!rec.setup.actors.some((a) => a.voice && a.voice !== "尚未定腔。"));
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [storyRef]);

  const readonly = !!story && !story.editable;

  const setSk = (patch: Partial<StorySketch>) => {
    setSketch((prev) => (prev ? { ...prev, ...patch } : prev));
  };
  const setSt = (patch: Partial<StorySetup>) => {
    setSetup((prev) => (prev ? { ...prev, ...patch } : prev));
  };

  const actorName = (id: string) =>
    sketch?.actors.find((a) => a.id === id)?.name ||
    setup?.actors.find((a) => a.id === id)?.name ||
    id;

  const persist = async () => {
    if (!story || !sketch || !setup || readonly) return null;
    const rec = await api<StoryDetail>(`/api/stories/${story.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        slug,
        sketch: { ...sketch, title: sketch.title },
        setup: { ...setup, title: sketch.title },
      }),
    });
    setStory(rec);
    setSketch(clone(rec.sketch));
    setSetup(clone(rec.setup));
    setSlug(rec.slug);
    return rec;
  };

  const save = async (ev?: FormEvent) => {
    ev?.preventDefault();
    if (readonly) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await persist();
      setNotice("已存速寫。");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const wizard = async () => {
    if (!story || readonly) return;
    if (enriched && !window.confirm("再請巫師會覆寫補完結果。速寫保留。繼續？")) {
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await persist();
      const rec = await postWizard(story.id);
      setStory(rec);
      setSketch(clone(rec.sketch));
      setSetup(clone(rec.setup));
      setEnriched(true);
      setNotice("巫師已補完。請核對下面的結果，再開始演繹。");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    if (!story) return;
    setBusy(true);
    setError(null);
    try {
      if (!readonly) await persist();
      const rec = await postStart(story.id);
      router.push(`/s/${rec.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  const usedLoc = useMemo(
    () => (sketch ? sketch.locations.map((l) => l.id) : []),
    [sketch]
  );
  const usedAct = useMemo(
    () => (sketch ? sketch.actors.map((a) => a.id) : []),
    [sketch]
  );
  const usedObj = useMemo(
    () => (sketch ? sketch.objects.map((o) => o.id) : []),
    [sketch]
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

  if (!story || !sketch || !setup) {
    return (
      <header className="masthead">
        <div className="mast-title">
          <h1>世界設定</h1>
          <p className="sub">載入…</p>
        </div>
      </header>
    );
  }

  const n = sketch.actors.length;
  const hi = Math.max(n, Math.min(8, sketch.turns_per_day_max || 8));

  const addActor = () => {
    if (sketch.actors.length >= 8) return;
    const id = nextId("actor", usedAct);
    const home = sketch.locations[0]?.id || "place";
    const act: ActorSketch = { id, name: "新人", note: "", location: home };
    setSk({ actors: [...sketch.actors, act] });
  };

  const addObject = () => {
    const id = nextId("obj", usedObj);
    const obj: ObjectSketch = {
      id,
      name: "物件",
      note: "",
      location_id: sketch.locations[0]?.id || null,
      holder_id: null,
    };
    setSk({ objects: [...sketch.objects, obj] });
  };

  const addRel = () => {
    if (sketch.actors.length < 2) return;
    const rel: RelationshipSketch = {
      a: sketch.actors[0].id,
      b: sketch.actors[1].id,
      note: "",
    };
    setSk({ relationships: [...sketch.relationships, rel] });
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
          <h1>{sketch.title || "世界設定"}</h1>
          <p className="sub">
            {readonly
              ? "世界已封。此為開演時的出生設定，只讀。要以神諭改明日，請回演繹。"
              : "先寫速寫，可請巫師補完細節，再開始演繹。世界即封。"}
          </p>
        </div>
        <div className="controls">
          {!readonly ? (
            <>
              <button type="button" disabled={busy} onClick={() => save()}>
                儲存速寫
              </button>
              <button type="button" disabled={busy} onClick={wizard}>
                {enriched ? "再請巫師" : "請巫師補完"}
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
              value={sketch.title}
              onChange={(e) => {
                setSk({ title: e.target.value });
                setSt({ title: e.target.value });
              }}
            />
            <span className="field-hint">給這則故事的名字。</span>
          </label>
          <label>
            短名
            <input value={slug} onChange={(e) => setSlug(e.target.value)} />
            <span className="field-hint">English id，用於網址。</span>
          </label>
          <label>
            當日拍數上限
            <input
              type="number"
              min={n}
              max={8}
              value={hi}
              onChange={(e) =>
                setSk({
                  turns_per_day_max: Number(e.target.value),
                })
              }
            />
            <span className="field-hint">
              一日每人至少一拍（現 {n} 人）；上限本版為 8。故事不設完結日數。
            </span>
          </label>
        </fieldset>

        <fieldset disabled={readonly} className="design-section">
          <h2>世界觀</h2>
          <textarea
            rows={5}
            value={sketch.worldview}
            onChange={(e) => setSk({ worldview: e.target.value })}
            placeholder="這世界的法則。一句也好。"
          />
        </fieldset>

        <fieldset disabled={readonly} className="design-section">
          <h2>開局</h2>
          <p className="hint-inline">
            引擎靠開場情勢與事件製造壓力。沒有衝突，演繹容易變成日復一日的早飯戲。安靜的故事也可以開始，只是拍會比較淡。
          </p>
          <label className="wide">
            開場情勢
            <textarea
              rows={4}
              value={sketch.opening_situation}
              onChange={(e) => setSk({ opening_situation: e.target.value })}
              placeholder="天氣、欠債、失蹤——此刻鎮上的空氣。"
            />
          </label>
          <label className="wide">
            開場事件
            <textarea
              rows={3}
              value={sketch.opening_events}
              onChange={(e) => setSk({ opening_events: e.target.value })}
              placeholder="開演前已經發生、人人略知的事。"
            />
          </label>
        </fieldset>

        <fieldset disabled={readonly} className="design-section">
          <h2>地圖</h2>
          <DesignMap
            locations={sketch.locations}
            edges={sketch.edges}
            descriptions={
              enriched
                ? Object.fromEntries(
                    setup.locations.map((l) => [l.id, l.description])
                  )
                : undefined
            }
            readonly={readonly}
            onLocations={(next) => setSk({ locations: next })}
            onEdges={(next) => setSk({ edges: next })}
            onDescription={
              enriched
                ? (id, description) =>
                    setSt({
                      locations: setup.locations.map((l) =>
                        l.id === id ? { ...l, description } : l
                      ),
                    })
                : undefined
            }
            onAdd={(x, y) => {
              const id = nextId("place", usedLoc);
              setSk({
                locations: [
                  ...sketch.locations,
                  { id, name: "新處", note: "", x, y },
                ],
              });
            }}
          />
        </fieldset>

        <fieldset disabled={readonly} className="design-section">
          <h2>人物速寫</h2>
          {sketch.actors.map((act, i) => (
            <div className="subcard" key={act.id}>
              <div className="row">
                <label>
                  id
                  <input
                    value={act.id}
                    onChange={(e) =>
                      setSk({
                        actors: sketch.actors.map((a, j) =>
                          j === i ? { ...a, id: e.target.value } : a
                        ),
                      })
                    }
                  />
                </label>
                <label>
                  名
                  <input
                    value={act.name}
                    onChange={(e) =>
                      setSk({
                        actors: sketch.actors.map((a, j) =>
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
                      setSk({
                        actors: sketch.actors.map((a, j) =>
                          j === i ? { ...a, location: e.target.value } : a
                        ),
                      })
                    }
                  >
                    {sketch.locations.map((l) => (
                      <option key={l.id} value={l.id}>
                        {l.name || l.id}
                      </option>
                    ))}
                  </select>
                </label>
                {sketch.actors.length > 1 ? (
                  <button
                    type="button"
                    className="ghost"
                    onClick={() =>
                      setSk({
                        actors: sketch.actors.filter((_, j) => j !== i),
                        relationships: sketch.relationships.filter(
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
                一句話
                <textarea
                  rows={2}
                  value={act.note}
                  placeholder="聰明漂亮的女孩；欠債的麵包師傅……"
                  onChange={(e) =>
                    setSk({
                      actors: sketch.actors.map((a, j) =>
                        j === i ? { ...a, note: e.target.value } : a
                      ),
                    })
                  }
                />
              </label>
            </div>
          ))}
          <button
            type="button"
            className="ghost"
            onClick={addActor}
            disabled={sketch.actors.length >= 8}
          >
            加一人{sketch.actors.length >= 8 ? "（已滿八人）" : ""}
          </button>
        </fieldset>

        <fieldset disabled={readonly} className="design-section">
          <h2>物件速寫</h2>
          <p className="hint-inline">可留空。巫師只在速寫提到時才補物。</p>
          {sketch.objects.map((obj, i) => (
            <div className="subcard" key={obj.id}>
              <div className="row">
                <label>
                  id
                  <input
                    value={obj.id}
                    onChange={(e) =>
                      setSk({
                        objects: sketch.objects.map((o, j) =>
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
                      setSk({
                        objects: sketch.objects.map((o, j) =>
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
                      setSk({
                        objects: sketch.objects.map((o, j) =>
                          j === i
                            ? { ...o, location_id: e.target.value || null }
                            : o
                        ),
                      })
                    }
                  >
                    <option value="">無</option>
                    {sketch.locations.map((l) => (
                      <option key={l.id} value={l.id}>
                        {l.name || l.id}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  className="ghost"
                  onClick={() =>
                    setSk({
                      objects: sketch.objects.filter((_, j) => j !== i),
                    })
                  }
                >
                  刪
                </button>
              </div>
              <label className="wide">
                一句話
                <input
                  value={obj.note}
                  onChange={(e) =>
                    setSk({
                      objects: sketch.objects.map((o, j) =>
                        j === i ? { ...o, note: e.target.value } : o
                      ),
                    })
                  }
                />
              </label>
            </div>
          ))}
          <button type="button" className="ghost" onClick={addObject}>
            加一物
          </button>
        </fieldset>

        <fieldset disabled={readonly} className="design-section">
          <h2>關係速寫</h2>
          {sketch.relationships.map((rel, i) => (
            <div className="subcard" key={`${rel.a}-${rel.b}-${i}`}>
              <div className="row">
                <label>
                  甲
                  <select
                    value={rel.a}
                    onChange={(e) =>
                      setSk({
                        relationships: sketch.relationships.map((r, j) =>
                          j === i ? { ...r, a: e.target.value } : r
                        ),
                      })
                    }
                  >
                    {sketch.actors.map((a) => (
                      <option key={a.id} value={a.id}>
                        {actorName(a.id)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  乙
                  <select
                    value={rel.b}
                    onChange={(e) =>
                      setSk({
                        relationships: sketch.relationships.map((r, j) =>
                          j === i ? { ...r, b: e.target.value } : r
                        ),
                      })
                    }
                  >
                    {sketch.actors.map((a) => (
                      <option key={a.id} value={a.id}>
                        {actorName(a.id)}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  className="ghost"
                  onClick={() =>
                    setSk({
                      relationships: sketch.relationships.filter((_, j) => j !== i),
                    })
                  }
                >
                  刪
                </button>
              </div>
              <label className="wide">
                一句話
                <input
                  value={rel.note}
                  onChange={(e) =>
                    setSk({
                      relationships: sketch.relationships.map((r, j) =>
                        j === i ? { ...r, note: e.target.value } : r
                      ),
                    })
                  }
                />
              </label>
            </div>
          ))}
          <button type="button" className="ghost" onClick={addRel}>
            加一層關係
          </button>
        </fieldset>

        {enriched ? (
          <fieldset disabled={readonly} className="design-section">
            <h2>補完結果</h2>
            <p className="hint-inline">
              巫師寫下的細節。可改。再請巫師會整份覆寫。
            </p>
            <label className="wide">
              世界觀
              <textarea
                rows={4}
                value={setup.worldview}
                onChange={(e) => setSt({ worldview: e.target.value })}
              />
            </label>
            <label className="wide">
              開場情勢
              <textarea
                rows={3}
                value={setup.opening_situation}
                onChange={(e) => setSt({ opening_situation: e.target.value })}
              />
            </label>
            <label className="wide">
              開場事件
              <textarea
                rows={3}
                value={setup.opening_events}
                onChange={(e) => setSt({ opening_events: e.target.value })}
              />
            </label>
            {setup.actors.map((act, i) => (
              <div className="subcard" key={act.id}>
                <p className="hint-inline">
                  {act.name}（{act.id}）
                </p>
                <label className="wide">
                  口吻
                  <textarea
                    rows={2}
                    value={act.voice}
                    onChange={(e) =>
                      setSt({
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
                      setSt({
                        actors: setup.actors.map((a, j) =>
                          j === i ? { ...a, want: e.target.value } : a
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
                      setSt({
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
                      setSt({
                        actors: setup.actors.map((a, j) =>
                          j === i ? { ...a, constitution: e.target.value } : a
                        ),
                      })
                    }
                  />
                </label>
              </div>
            ))}
            {setup.objects.map((obj, i) => (
              <div className="subcard" key={obj.id}>
                <div className="row">
                  <label>
                    物
                    <input
                      value={obj.name}
                      onChange={(e) =>
                        setSt({
                          objects: setup.objects.map((o, j) =>
                            j === i ? { ...o, name: e.target.value } : o
                          ),
                        })
                      }
                    />
                  </label>
                </div>
                <label className="wide">
                  描述
                  <textarea
                    rows={2}
                    value={obj.description}
                    onChange={(e) =>
                      setSt({
                        objects: setup.objects.map((o, j) =>
                          j === i ? { ...o, description: e.target.value } : o
                        ),
                      })
                    }
                  />
                </label>
              </div>
            ))}
            {setup.relationships.map((rel, i) => (
              <div className="subcard" key={`${rel.a}-${rel.b}-${i}`}>
                <p className="hint-inline">
                  {actorName(rel.a)} → {actorName(rel.b)}
                </p>
                <div className="row">
                  <label>
                    信
                    <input
                      type="number"
                      value={rel.trust}
                      onChange={(e) =>
                        setSt({
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
                      value={rel.resentment}
                      onChange={(e) =>
                        setSt({
                          relationships: setup.relationships.map((r, j) =>
                            j === i ? { ...r, resentment: Number(e.target.value) } : r
                          ),
                        })
                      }
                    />
                  </label>
                </div>
                <label className="wide">
                  註
                  <input
                    value={rel.notes}
                    onChange={(e) =>
                      setSt({
                        relationships: setup.relationships.map((r, j) =>
                          j === i ? { ...r, notes: e.target.value } : r
                        ),
                      })
                    }
                  />
                </label>
              </div>
            ))}
          </fieldset>
        ) : null}
      </form>
    </>
  );
}
