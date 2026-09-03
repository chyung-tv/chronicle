"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchState } from "@/lib/api";
import { persistUser, userHeaders, getCurrentUser } from "@/lib/auth";
import type { WorldSnapshot } from "@/lib/types";

export function useWorldStream(storyId: string | null) {
  const [state, setState] = useState<WorldSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notLive, setNotLive] = useState(false);
  const [latch, setLatch] = useState(false);
  const genAtLatch = useRef(0);

  const apply = useCallback((data: WorldSnapshot) => {
    setState(data);
    if (data.activity_error) setError(data.activity_error);
  }, []);

  const pull = useCallback(async () => {
    if (!storyId) return;
    try {
      persistUser({
        id: userHeaders()["X-User-Id"],
        name: getCurrentUser().name,
      });
      const data = await fetchState(storyId);
      setNotLive(false);
      apply(data);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg === "尚未開演") {
        setNotLive(true);
        return;
      }
      setError(msg);
    }
  }, [apply, storyId]);

  useEffect(() => {
    if (!storyId) return;
    let poll: ReturnType<typeof setInterval> | undefined;
    let reconnect: ReturnType<typeof setTimeout> | undefined;
    let es: EventSource | null = null;
    let stopped = false;

    persistUser({
      id: userHeaders()["X-User-Id"],
      name: getCurrentUser().name,
    });

    const connect = () => {
      if (stopped) return;
      es = new EventSource(`/api/stories/${storyId}/stream`);
      es.onmessage = (ev) => {
        try {
          apply(JSON.parse(ev.data) as WorldSnapshot);
          setNotLive(false);
        } catch {
          /* ignore malformed frames */
        }
      };
      es.onerror = () => {
        es?.close();
        es = null;
        if (stopped) return;
        reconnect = setTimeout(connect, 800);
      };
    };

    connect();
    poll = setInterval(pull, 400);
    void pull();
    return () => {
      stopped = true;
      es?.close();
      if (poll) clearInterval(poll);
      if (reconnect) clearTimeout(reconnect);
    };
  }, [apply, pull, storyId]);

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
    async (fn: () => Promise<unknown>, opts?: { blocking?: boolean }) => {
      genAtLatch.current = state?.activity_gen ?? 0;
      setLatch(true);
      setError(null);
      try {
        await fn();
        if (opts?.blocking) {
          await pull();
          setLatch(false);
        }
      } catch (e) {
        setLatch(false);
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [state?.activity_gen, pull]
  );

  return { state, error, setError, busy, runCommand, notLive };
}
