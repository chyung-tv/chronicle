/**
 * Session stub. Replace getCurrentUser() with better-auth / Auth.js:
 *
 *   import { auth } from "@/lib/auth"; // better-auth
 *   const session = await auth.api.getSession({ headers: await headers() });
 *   return session?.user ?? null;
 *
 * or Auth.js: `const session = await auth(); return session?.user ?? null;`
 *
 * Keep the User { id, name } shape so catalog, ownership, and god gates stay put.
 * Unsigned visitors are audience, not the seeded 港尾 owner.
 */

import type { SessionUser } from "./types";

export const GUEST_USER: SessionUser = {
  id: "audience",
  name: "訪客",
};

const KEY = "playout-user-id";
const NAME_KEY = "playout-user-name";

function newGuestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `guest-${crypto.randomUUID()}`;
  }
  return `guest-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
}

export function getCurrentUser(): SessionUser {
  if (typeof window === "undefined") return GUEST_USER;
  let id = window.localStorage.getItem(KEY);
  let name = window.localStorage.getItem(NAME_KEY);
  if (!id) {
    id = newGuestId();
    name = GUEST_USER.name;
    persistUser({ id, name });
  }
  return { id, name: name || GUEST_USER.name };
}

export function persistUser(user: SessionUser) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(KEY, user.id);
  window.localStorage.setItem(NAME_KEY, user.name);
  document.cookie = `playout_user=${encodeURIComponent(user.id)}; path=/; SameSite=Lax`;
  document.cookie = `playout_name=${encodeURIComponent(user.name)}; path=/; SameSite=Lax`;
}

export function userHeaders(): Record<string, string> {
  const u = getCurrentUser();
  // Fetch forbids non-ISO-8859-1 header values; id stays ASCII.
  return { "X-User-Id": u.id };
}
