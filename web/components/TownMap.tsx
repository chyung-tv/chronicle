"use client";

import type { WorldSnapshot } from "@/lib/types";

const colors = ["#e7d8b8", "#8eb3b0", "#d4a574", "#c97b84"];

export function TownMap({
  state,
  onSelect,
}: {
  state: WorldSnapshot;
  onSelect: (id: string) => void;
}) {
  const loc = Object.fromEntries(state.locations.map((l) => [l.id, l]));
  const edges = state.edges
    .map((e) => {
      const a = loc[e.a];
      const b = loc[e.b];
      if (!a || !b || e.a > e.b) return "";
      return `<line class="edge" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" />`;
    })
    .join("");
  const nodes = state.locations
    .map((l) => {
      const cls = l.intact ? "node-circle" : "node-ruined";
      const people = l.actors
        .map((a, i) => {
          const c = colors[i % colors.length];
          const ox = (i - (l.actors.length - 1) / 2) * 14;
          const faded = a.alive ? 1 : 0.35;
          return `<circle class="actor-dot" data-actor="${a.id}" cx="${l.x + ox}" cy="${l.y - 22}" r="6" fill="${c}" opacity="${faded}"><title>${a.name}</title></circle>`;
        })
        .join("");
      return `<g>
        <circle class="${cls}" cx="${l.x}" cy="${l.y}" r="16" />
        <text class="node-label" x="${l.x}" y="${l.y + 32}" text-anchor="middle">${l.name}</text>
        ${people}
      </g>`;
    })
    .join("");

  return (
    <svg
      className="map"
      viewBox="0 0 540 360"
      role="img"
      aria-label="鎮圖"
      dangerouslySetInnerHTML={{ __html: edges + nodes }}
      onClick={(ev) => {
        const t = ev.target as SVGElement;
        const id = t.getAttribute("data-actor");
        if (id) onSelect(id);
      }}
    />
  );
}
