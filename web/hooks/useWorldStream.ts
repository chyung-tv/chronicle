"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { WorldSnapshot } from "@/lib/types";

export function useWorldStream() {
  const [state, setState] = useState<WorldSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [latch, setLatch] = useState(false);
  const genAtLatch = useRef(0);

  useEffect(() => {
    let poll: ReturnType<typeof setInterval> | undefined;
    let es: EventSource | null = null;

    const apply = (data: WorldSnapshot) => {
      setState(data);
      if (data.activity_error) setError(data.activity_error);
    };

    const pull = async () => {
      try {
        const r = await fetch("/api/state");
        if (!r.ok) return;
        apply(await r.json());
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    };

    const connect = () => {
      es = new EventSource("/api/stream");
      es.onmessage = (ev) => {
        try {
          apply(JSON.parse(ev.data) as WorldSnapshot);
        } catch {
          /* ignore malformed frames */
        }
      };
      es.onerror = () => {
        es?.close();
        es = null;
      };
    };

    connect();
    poll = setInterval(pull, 400);
    void pull();
    return () => {
      es?.close();
      if (poll) clearInterval(poll);
    };
  }, []);

  const busy =
    latch ||
    (!!state && state.activity !== "idle") ||
    !!state?.encounter?.active;

  useEffect(() => {
    if (!latch || !state) return;
    if (state.activity === "idle" && state.activity_gen !== genAtLatch.current) {
      setLatch(false);
    }
  }, [latch, state]);

  const runCommand = useCallback(
    async (fn: () => Promise<unknown>) => {
      genAtLatch.current = state?.activity_gen ?? 0;
      setLatch(true);
      setError(null);
      try {
        await fn();
      } catch (e) {
        setLatch(false);
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [state?.activity_gen]
  );

  return { state, error, setError, busy, runCommand };
}
