"use client";

import type { LocationSetup } from "@/lib/types";

const colors = ["#e7d8b8", "#8eb3b0", "#d4a574", "#c97b84"];

export function DesignMap({
  locations,
  edges,
  selected,
  readonly,
  onSelect,
  onPlace,
}: {
  locations: LocationSetup[];
  edges: [string, string][];
  selected: string | null;
  readonly: boolean;
  onSelect: (id: string) => void;
  onPlace: (id: string, x: number, y: number) => void;
}) {
  const loc = Object.fromEntries(locations.map((l) => [l.id, l]));
  const edgeMarkup = edges
    .map(([a, b]) => {
      const pa = loc[a];
      const pb = loc[b];
      if (!pa || !pb || a > b) return "";
      return `<line class="edge" x1="${pa.x}" y1="${pa.y}" x2="${pb.x}" y2="${pb.y}" />`;
    })
    .join("");
  const nodes = locations
    .map((l, i) => {
      const on = l.id === selected;
      const fill = on ? colors[i % colors.length] : "#2a4e58";
      return `<g data-loc="${l.id}" class="map-loc">
        <circle class="node-circle" cx="${l.x}" cy="${l.y}" r="${on ? 18 : 16}" fill="${fill}" />
        <text class="node-label" x="${l.x}" y="${l.y + 32}" text-anchor="middle">${l.name}</text>
      </g>`;
    })
    .join("");

  return (
    <svg
      className="map"
      viewBox="0 0 540 360"
      role="img"
      aria-label="鎮圖編輯"
      dangerouslySetInnerHTML={{ __html: edgeMarkup + nodes }}
      onClick={(ev) => {
        const svg = ev.currentTarget;
        const t = ev.target as SVGElement;
        const locId =
          t.closest("[data-loc]")?.getAttribute("data-loc") ||
          t.getAttribute("data-loc");
        if (locId) {
          onSelect(locId);
          return;
        }
        if (readonly || !selected) return;
        const pt = svg.createSVGPoint();
        pt.x = ev.clientX;
        pt.y = ev.clientY;
        const ctm = svg.getScreenCTM();
        if (!ctm) return;
        const p = pt.matrixTransform(ctm.inverse());
        onPlace(
          selected,
          Math.round(Math.max(24, Math.min(516, p.x))),
          Math.round(Math.max(24, Math.min(336, p.y)))
        );
      }}
    />
  );
}
