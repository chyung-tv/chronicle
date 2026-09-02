export async function command(
  path: string,
  opts?: RequestInit
): Promise<{ accepted?: boolean } & Record<string, unknown>> {
  const r = await fetch(path, opts);
  if (r.status === 409) {
    throw new Error("正在演繹，請稍候");
  }
  if (!r.ok) {
    throw new Error(await r.text());
  }
  return r.json();
}

export function postTick() {
  return command("/api/tick", { method: "POST" });
}

export function postDay() {
  return command("/api/day", { method: "POST" });
}

export function postReset() {
  return command("/api/reset", { method: "POST" });
}

export function postInject(text: string) {
  return command("/api/inject", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}

export function postSteer(text: string) {
  return command("/api/steer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}
