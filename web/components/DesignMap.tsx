"use client";

import { MouseEvent, PointerEvent, useRef, useState } from "react";
import type { LocationSketch } from "@/lib/types";

const colors = ["#e7d8b8", "#8eb3b0", "#d4a574", "#c97b84"];
const VB_W = 540;
const VB_H = 400;

type Sel =
  | { kind: "loc"; id: string }
  | { kind: "edge"; a: string; b: string }
  | null;

function undirectedKey(a: string, b: string) {
  return a < b ? `${a}|${b}` : `${b}|${a}`;
}

export function DesignMap({
  locations,
  edges,
  descriptions,
  readonly,
  onLocations,
  onEdges,
  onDescription,
  onAdd,
}: {
  locations: LocationSketch[];
  edges: [string, string][];
  descriptions?: Record<string, string>;
  readonly: boolean;
  onLocations: (next: LocationSketch[]) => void;
  onEdges: (next: [string, string][]) => void;
  onDescription?: (id: string, description: string) => void;
  onAdd: (x: number, y: number) => void;
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [sel, setSel] = useState<Sel>(null);
  const [tool, setTool] = useState<"select" | "add">("select");
  const [linkFrom, setLinkFrom] = useState<string | null>(null);
  const drag = useRef<{ id: string; dx: number; dy: number } | null>(null);
  const loc = Object.fromEntries(locations.map((l) => [l.id, l]));
  const selectedLoc =
    sel?.kind === "loc" ? locations.find((l) => l.id === sel.id) : null;

  const toSvg = (ev: { clientX: number; clientY: number }) => {
    const svg = svgRef.current;
    if (!svg) return null;
    const pt = svg.createSVGPoint();
    pt.x = ev.clientX;
    pt.y = ev.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return null;
    const p = pt.matrixTransform(ctm.inverse());
    return {
      x: Math.round(Math.max(24, Math.min(VB_W - 24, p.x))),
      y: Math.round(Math.max(24, Math.min(VB_H - 24, p.y))),
    };
  };

  const toggleEdge = (a: string, b: string) => {
    if (a === b) return;
    const exists = edges.some(
      ([x, y]) =>
        (x === a && y === b) || (x === b && y === a)
    );
    if (exists) {
      onEdges(edges.filter(([x, y]) => !((x === a && y === b) || (x === b && y === a))));
    } else {
      onEdges([...edges, [a, b]]);
    }
  };

  const onNodePointerDown = (id: string, ev: PointerEvent<SVGGElement>) => {
    ev.stopPropagation();
    ev.currentTarget.setPointerCapture(ev.pointerId);
    if (ev.ctrlKey || ev.metaKey) {
      if (linkFrom && linkFrom !== id) {
        toggleEdge(linkFrom, id);
        setLinkFrom(null);
      } else {
        setLinkFrom(id);
      }
      setSel({ kind: "loc", id });
      return;
    }
    if (tool === "add") return;
    setSel({ kind: "loc", id });
    setLinkFrom(null);
    if (readonly) return;
    const node = loc[id];
    const p = toSvg(ev);
    if (!node || !p) return;
    drag.current = { id, dx: p.x - node.x, dy: p.y - node.y };
  };

  const onPointerMove = (ev: PointerEvent<SVGSVGElement>) => {
    if (readonly || !drag.current) return;
    const p = toSvg(ev);
    if (!p) return;
    const { id, dx, dy } = drag.current;
    onLocations(
      locations.map((l) =>
        l.id === id ? { ...l, x: p.x - dx, y: p.y - dy } : l
      )
    );
  };

  const onPointerUp = () => {
    drag.current = null;
  };

  const onBgClick = (ev: PointerEvent<SVGSVGElement>) => {
    if (readonly) return;
    const t = ev.target as Element;
    if (t.closest("[data-loc]") || t.closest("[data-edge]")) return;
    const p = toSvg(ev);
    if (!p) return;
    if (tool === "add") {
      onAdd(p.x, p.y);
      setTool("select");
      return;
    }
    setSel(null);
    setLinkFrom(null);
  };

  const onDoubleClick = (ev: MouseEvent<SVGSVGElement>) => {
    if (readonly) return;
    const t = ev.target as Element;
    if (t.closest("[data-loc]") || t.closest("[data-edge]")) return;
    const p = toSvg(ev);
    if (!p) return;
    onAdd(p.x, p.y);
  };

  const drawn = new Set<string>();
  const edgePairs: [string, string][] = [];
  for (const [a, b] of edges) {
    const k = undirectedKey(a, b);
    if (drawn.has(k) || a === b) continue;
    drawn.add(k);
    edgePairs.push([a, b]);
  }

  return (
    <div className="design-map">
      {!readonly ? (
        <div className="map-toolbar">
          <button
            type="button"
            className={tool === "select" ? "on" : ""}
            onClick={() => setTool("select")}
          >
            選取
          </button>
          <button
            type="button"
            className={tool === "add" ? "on" : ""}
            onClick={() => setTool("add")}
          >
            加一處
          </button>
          <span className="map-hint">
            拖曳安放 · Ctrl/Cmd 點兩處連路 · 雙擊空白加處
          </span>
        </div>
      ) : null}
      <svg
        ref={svgRef}
        className="map"
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        role="img"
        aria-label="鎮圖編輯"
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerDown={onBgClick}
        onDoubleClick={onDoubleClick}
      >
        {edgePairs.map(([a, b]) => {
          const pa = loc[a];
          const pb = loc[b];
          if (!pa || !pb) return null;
          const on =
            sel?.kind === "edge" && undirectedKey(sel.a, sel.b) === undirectedKey(a, b);
          return (
            <line
              key={`${a}-${b}`}
              data-edge={`${a}|${b}`}
              className={on ? "edge on" : "edge"}
              x1={pa.x}
              y1={pa.y}
              x2={pb.x}
              y2={pb.y}
              onPointerDown={(ev) => {
                ev.stopPropagation();
                setSel({ kind: "edge", a, b });
                setLinkFrom(null);
              }}
            />
          );
        })}
        {locations.map((l, i) => {
          const on = sel?.kind === "loc" && sel.id === l.id;
          const linking = linkFrom === l.id;
          const fill = on || linking ? colors[i % colors.length] : "#2a4e58";
          return (
            <g
              key={l.id}
              data-loc={l.id}
              className="map-loc"
              onPointerDown={(ev) => onNodePointerDown(l.id, ev)}
            >
              <circle
                className="node-circle"
                cx={l.x}
                cy={l.y}
                r={on || linking ? 18 : 16}
                fill={fill}
              />
              <text className="node-label" x={l.x} y={l.y + 32} textAnchor="middle">
                {l.name || l.id}
              </text>
            </g>
          );
        })}
      </svg>
      {selectedLoc && !readonly ? (
        <div className="map-inspector">
          <label>
            名
            <input
              value={selectedLoc.name}
              onChange={(e) =>
                onLocations(
                  locations.map((l) =>
                    l.id === selectedLoc.id ? { ...l, name: e.target.value } : l
                  )
                )
              }
            />
          </label>
          <label className="wide">
            速寫
            <textarea
              rows={2}
              value={selectedLoc.note}
              onChange={(e) =>
                onLocations(
                  locations.map((l) =>
                    l.id === selectedLoc.id ? { ...l, note: e.target.value } : l
                  )
                )
              }
            />
          </label>
          {onDescription && descriptions ? (
            <label className="wide">
              補完描述
              <textarea
                rows={2}
                value={descriptions[selectedLoc.id] || ""}
                onChange={(e) => onDescription(selectedLoc.id, e.target.value)}
              />
            </label>
          ) : null}
          {locations.length > 1 ? (
            <button
              type="button"
              className="ghost"
              onClick={() => {
                onLocations(locations.filter((l) => l.id !== selectedLoc.id));
                onEdges(
                  edges.filter(([a, b]) => a !== selectedLoc.id && b !== selectedLoc.id)
                );
                setSel(null);
              }}
            >
              刪此處
            </button>
          ) : null}
        </div>
      ) : null}
      {sel?.kind === "edge" && !readonly ? (
        <div className="map-inspector">
          <p className="map-hint">
            {loc[sel.a]?.name || sel.a} — {loc[sel.b]?.name || sel.b}
          </p>
          <button
            type="button"
            className="ghost"
            onClick={() => {
              toggleEdge(sel.a, sel.b);
              setSel(null);
            }}
          >
            刪路
          </button>
        </div>
      ) : null}
    </div>
  );
}
