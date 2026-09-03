"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, fetchMe, fetchStory, postStart } from "@/lib/api";
import type { StoryDetail, StorySetup } from "@/lib/types";

function clone<T>(s: T): T {
  return JSON.parse(JSON.stringify(s)) as T;
}

function Cell({
  value,
  onChange,
  readonly,
  multiline,
  type,
}: {
  value: string | number | boolean;
  onChange: (v: string) => void;
  readonly: boolean;
  multiline?: boolean;
  type?: string;
}) {
  if (readonly) {
    const text = typeof value === "boolean" ? (value ? "是" : "否") : String(value ?? "");
    return <span className="cell-read">{text || "—"}</span>;
  }
  if (multiline) {
    return (
      <textarea
        rows={2}
        value={String(value ?? "")}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  if (type === "checkbox") {
    return (
      <input
        type="checkbox"
        checked={Boolean(value)}
        onChange={(e) => onChange(e.target.checked ? "1" : "")}
      />
    );
  }
  return (
    <input
      type={type || (typeof value === "number" ? "number" : "text")}
      value={typeof value === "boolean" ? "" : String(value ?? "")}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

export function SetupReview({ storyRef }: { storyRef: string }) {
  const router = useRouter();
  const [story, setStory] = useState<StoryDetail | null>(null);
  const [setup, setSetup] = useState<StorySetup | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
        setSetup(clone(rec.setup));
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

  const saveFinal = async () => {
    if (!story || !setup || readonly) return null;
    const rec = await api<StoryDetail>(`/api/stories/${story.id}`, {
      method: "PATCH",
      body: JSON.stringify({ setup }),
    });
    setStory(rec);
    setSetup(clone(rec.setup));
    return rec;
  };

  const confirm = async () => {
    if (readonly) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await saveFinal();
      setNotice("已確認定稿。可以開始演繹。");
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
      if (!readonly) await saveFinal();
      const rec = await postStart(story.id);
      router.push(`/s/${rec.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  if (error && !story) {
    return (
      <header className="masthead">
        <div className="mast-title">
          <p className="chrome-links">
            <Link href="/">故事</Link>
          </p>
          <h1>巫師稿</h1>
          <p className="sub">{error}</p>
        </div>
      </header>
    );
  }

  if (!story || !setup) {
    return (
      <header className="masthead">
        <div className="mast-title">
          <h1>巫師稿</h1>
          <p className="sub">載入…</p>
        </div>
      </header>
    );
  }

  return (
    <>
      <header className="masthead">
        <div className="mast-title">
          <p className="chrome-links">
            <Link href="/">故事</Link>
            <Link href={`/s/${story.id}/design`}>速寫</Link>
            {story.status === "live" ? (
              <Link href={`/s/${story.id}`}>進入演繹</Link>
            ) : null}
          </p>
          <h1>{setup.title || "巫師稿"}</h1>
          <p className="sub">
            {readonly
              ? "世界已封。此表即開演時的設定 JSON，只讀。"
              : "巫師依速寫寫下的定稿。改格子即可，不必再跑巫師。確認後開始演繹。"}
          </p>
        </div>
        <div className="controls">
          {!readonly ? (
            <>
              <button type="button" disabled={busy} onClick={confirm}>
                確認定稿
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

      <form
        className="design review"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          confirm();
        }}
        aria-readonly={readonly}
      >
        <fieldset disabled={readonly} className="design-section">
          <h2>setup</h2>
          <div className="table-wrap">
            <table className="design-table">
              <thead>
                <tr>
                  <th>title</th>
                  <th>turns_per_day_min</th>
                  <th>turns_per_day_max</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>
                    <Cell
                      value={setup.title}
                      readonly={readonly}
                      onChange={(v) => set({ title: v })}
                    />
                  </td>
                  <td>
                    <Cell
                      value={setup.turns_per_day_min}
                      readonly
                      onChange={() => undefined}
                    />
                  </td>
                  <td>
                    <Cell
                      value={setup.turns_per_day_max}
                      readonly={readonly}
                      type="number"
                      onChange={(v) => set({ turns_per_day_max: Number(v) })}
                    />
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <label className="wide">
            worldview
            <Cell
              value={setup.worldview}
              readonly={readonly}
              multiline
              onChange={(v) => set({ worldview: v })}
            />
          </label>
          <label className="wide">
            opening_situation
            <Cell
              value={setup.opening_situation}
              readonly={readonly}
              multiline
              onChange={(v) => set({ opening_situation: v })}
            />
          </label>
          <label className="wide">
            opening_events
            <Cell
              value={setup.opening_events}
              readonly={readonly}
              multiline
              onChange={(v) => set({ opening_events: v })}
            />
          </label>
        </fieldset>

        <fieldset disabled={readonly} className="design-section">
          <h2>locations</h2>
          <div className="table-wrap">
            <table className="design-table">
              <thead>
                <tr>
                  <th>id</th>
                  <th>name</th>
                  <th>x</th>
                  <th>y</th>
                  <th>description</th>
                </tr>
              </thead>
              <tbody>
                {setup.locations.map((loc, i) => (
                  <tr key={loc.id}>
                    <td>
                      <Cell value={loc.id} readonly onChange={() => undefined} />
                    </td>
                    <td>
                      <Cell
                        value={loc.name}
                        readonly={readonly}
                        onChange={(v) =>
                          set({
                            locations: setup.locations.map((l, j) =>
                              j === i ? { ...l, name: v } : l
                            ),
                          })
                        }
                      />
                    </td>
                    <td>
                      <Cell value={loc.x} readonly onChange={() => undefined} />
                    </td>
                    <td>
                      <Cell value={loc.y} readonly onChange={() => undefined} />
                    </td>
                    <td>
                      <Cell
                        value={loc.description}
                        readonly={readonly}
                        multiline
                        onChange={(v) =>
                          set({
                            locations: setup.locations.map((l, j) =>
                              j === i ? { ...l, description: v } : l
                            ),
                          })
                        }
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="hint-inline">
            edges：
            {setup.edges.length
              ? setup.edges
                  .map(([a, b]) => `${locName(a)}–${locName(b)}`)
                  .join(" · ")
              : "（無）"}
          </p>
        </fieldset>

        <fieldset disabled={readonly} className="design-section">
          <h2>actors</h2>
          <div className="table-wrap">
            <table className="design-table">
              <thead>
                <tr>
                  <th>id</th>
                  <th>name</th>
                  <th>location</th>
                  <th>mood</th>
                  <th>voice</th>
                  <th>want</th>
                  <th>secret</th>
                  <th>constitution</th>
                  <th>goal</th>
                </tr>
              </thead>
              <tbody>
                {setup.actors.map((act, i) => (
                  <tr key={act.id}>
                    <td>
                      <Cell value={act.id} readonly onChange={() => undefined} />
                    </td>
                    <td>
                      <Cell
                        value={act.name}
                        readonly={readonly}
                        onChange={(v) =>
                          set({
                            actors: setup.actors.map((a, j) =>
                              j === i ? { ...a, name: v } : a
                            ),
                          })
                        }
                      />
                    </td>
                    <td>
                      <Cell value={locName(act.location)} readonly onChange={() => undefined} />
                    </td>
                    <td>
                      <Cell
                        value={act.mood}
                        readonly={readonly}
                        onChange={(v) =>
                          set({
                            actors: setup.actors.map((a, j) =>
                              j === i ? { ...a, mood: v } : a
                            ),
                          })
                        }
                      />
                    </td>
                    <td>
                      <Cell
                        value={act.voice}
                        readonly={readonly}
                        multiline
                        onChange={(v) =>
                          set({
                            actors: setup.actors.map((a, j) =>
                              j === i ? { ...a, voice: v } : a
                            ),
                          })
                        }
                      />
                    </td>
                    <td>
                      <Cell
                        value={act.want}
                        readonly={readonly}
                        multiline
                        onChange={(v) =>
                          set({
                            actors: setup.actors.map((a, j) =>
                              j === i ? { ...a, want: v } : a
                            ),
                          })
                        }
                      />
                    </td>
                    <td>
                      <Cell
                        value={act.secret}
                        readonly={readonly}
                        multiline
                        onChange={(v) =>
                          set({
                            actors: setup.actors.map((a, j) =>
                              j === i ? { ...a, secret: v } : a
                            ),
                          })
                        }
                      />
                    </td>
                    <td>
                      <Cell
                        value={act.constitution}
                        readonly={readonly}
                        multiline
                        onChange={(v) =>
                          set({
                            actors: setup.actors.map((a, j) =>
                              j === i ? { ...a, constitution: v } : a
                            ),
                          })
                        }
                      />
                    </td>
                    <td>
                      <Cell
                        value={act.goal}
                        readonly={readonly}
                        multiline
                        onChange={(v) =>
                          set({
                            actors: setup.actors.map((a, j) =>
                              j === i ? { ...a, goal: v } : a
                            ),
                          })
                        }
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </fieldset>

        <fieldset disabled={readonly} className="design-section">
          <h2>objects</h2>
          <div className="table-wrap">
            <table className="design-table">
              <thead>
                <tr>
                  <th>id</th>
                  <th>name</th>
                  <th>location_id</th>
                  <th>holder_id</th>
                  <th>hidden</th>
                  <th>description</th>
                </tr>
              </thead>
              <tbody>
                {setup.objects.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="cell-read">
                      （無）
                    </td>
                  </tr>
                ) : (
                  setup.objects.map((obj, i) => (
                    <tr key={obj.id}>
                      <td>
                        <Cell value={obj.id} readonly onChange={() => undefined} />
                      </td>
                      <td>
                        <Cell
                          value={obj.name}
                          readonly={readonly}
                          onChange={(v) =>
                            set({
                              objects: setup.objects.map((o, j) =>
                                j === i ? { ...o, name: v } : o
                              ),
                            })
                          }
                        />
                      </td>
                      <td>
                        <Cell
                          value={obj.location_id || ""}
                          readonly
                          onChange={() => undefined}
                        />
                      </td>
                      <td>
                        <Cell
                          value={obj.holder_id || ""}
                          readonly
                          onChange={() => undefined}
                        />
                      </td>
                      <td>
                        <Cell
                          value={obj.hidden}
                          readonly={readonly}
                          type="checkbox"
                          onChange={(v) =>
                            set({
                              objects: setup.objects.map((o, j) =>
                                j === i ? { ...o, hidden: Boolean(v) } : o
                              ),
                            })
                          }
                        />
                      </td>
                      <td>
                        <Cell
                          value={obj.description}
                          readonly={readonly}
                          multiline
                          onChange={(v) =>
                            set({
                              objects: setup.objects.map((o, j) =>
                                j === i ? { ...o, description: v } : o
                              ),
                            })
                          }
                        />
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </fieldset>

        <fieldset disabled={readonly} className="design-section">
          <h2>relationships</h2>
          <div className="table-wrap">
            <table className="design-table">
              <thead>
                <tr>
                  <th>a</th>
                  <th>b</th>
                  <th>trust</th>
                  <th>resentment</th>
                  <th>notes</th>
                </tr>
              </thead>
              <tbody>
                {setup.relationships.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="cell-read">
                      （無）
                    </td>
                  </tr>
                ) : (
                  setup.relationships.map((rel, i) => (
                    <tr key={`${rel.a}-${rel.b}-${i}`}>
                      <td>
                        <Cell
                          value={`${actorName(rel.a)} (${rel.a})`}
                          readonly
                          onChange={() => undefined}
                        />
                      </td>
                      <td>
                        <Cell
                          value={`${actorName(rel.b)} (${rel.b})`}
                          readonly
                          onChange={() => undefined}
                        />
                      </td>
                      <td>
                        <Cell
                          value={rel.trust}
                          readonly={readonly}
                          type="number"
                          onChange={(v) =>
                            set({
                              relationships: setup.relationships.map((r, j) =>
                                j === i ? { ...r, trust: Number(v) } : r
                              ),
                            })
                          }
                        />
                      </td>
                      <td>
                        <Cell
                          value={rel.resentment}
                          readonly={readonly}
                          type="number"
                          onChange={(v) =>
                            set({
                              relationships: setup.relationships.map((r, j) =>
                                j === i ? { ...r, resentment: Number(v) } : r
                              ),
                            })
                          }
                        />
                      </td>
                      <td>
                        <Cell
                          value={rel.notes}
                          readonly={readonly}
                          onChange={(v) =>
                            set({
                              relationships: setup.relationships.map((r, j) =>
                                j === i ? { ...r, notes: v } : r
                              ),
                            })
                          }
                        />
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </fieldset>
      </form>
    </>
  );
}
