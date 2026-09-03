import { persistUser, userHeaders } from "./auth";
import type { SessionUser, StoryDetail, WorldSnapshot } from "./types";

async function parseError(r: Response): Promise<string> {
  const text = await r.text();
  try {
    const j = JSON.parse(text);
    if (typeof j.detail === "string") return j.detail;
    if (Array.isArray(j.detail)) return j.detail.map((d: { msg?: string }) => d.msg).join("; ");
  } catch {
    /* raw */
  }
  return text || r.statusText;
}

export async function api<T = Record<string, unknown>>(
  path: string,
  opts?: RequestInit
): Promise<T> {
  const r = await fetch(path, {
    ...opts,
    headers: {
      ...userHeaders(),
      ...(opts?.body ? { "Content-Type": "application/json" } : {}),
      ...(opts?.headers || {}),
    },
  });
  if (r.status === 409) {
    const detail = await parseError(r);
    if (detail === "busy") throw new Error("正在演繹，請稍候");
    if (detail === "sealed") throw new Error("世界已封，不能改設定");
    if (detail === "already live") throw new Error("已在演繹中");
    if (detail === "already draft") throw new Error("尚未開演");
    if (detail === "not live") throw new Error("尚未開演");
    throw new Error(detail || "衝突");
  }
  if (r.status === 403) throw new Error("沒有權限");
  if (r.status === 404) throw new Error("找不到這則故事");
  if (!r.ok) throw new Error(await parseError(r));
  if (r.status === 204) return {} as T;
  return r.json();
}

export async function command(
  path: string,
  opts?: RequestInit
): Promise<{ accepted?: boolean } & Record<string, unknown>> {
  return api(path, opts);
}

export async function fetchMe(): Promise<SessionUser> {
  const me = await api<SessionUser>("/api/me");
  persistUser(me);
  return me;
}

export function postTick(storyId: string) {
  return command(`/api/stories/${storyId}/tick`, { method: "POST" });
}

export function postDay(storyId: string) {
  return command(`/api/stories/${storyId}/day`, { method: "POST" });
}

export function postReset(storyId: string) {
  return command(`/api/stories/${storyId}/reset`, { method: "POST" });
}

export function postInject(storyId: string, text: string) {
  return command(`/api/stories/${storyId}/inject`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export function postSteer(storyId: string, text: string) {
  return command(`/api/stories/${storyId}/steer`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export function postStart(storyId: string) {
  return api<StoryDetail>(`/api/stories/${storyId}/start`, { method: "POST" });
}

export function fetchStory(ref: string) {
  return api<StoryDetail>(`/api/stories/${ref}`);
}

export function fetchState(storyId: string) {
  return api<WorldSnapshot>(`/api/stories/${storyId}/state`);
}
