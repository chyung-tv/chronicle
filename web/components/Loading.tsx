"use client";

import type { ReactNode } from "react";

export function Loading({
  title = "載入中",
  children,
}: {
  title?: string;
  children?: ReactNode;
}) {
  return (
    <div className="loading-overlay" role="status" aria-busy="true" aria-live="polite">
      <div className="loading-card">
        <p className="loading-kicker">{title}</p>
        {children}
      </div>
    </div>
  );
}
