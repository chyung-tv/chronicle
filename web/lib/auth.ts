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
 */

import type { SessionUser } from "./types";

export const DEV_USER: SessionUser = {
  id: "dev-owner",
  name: "開發者",
};

const KEY = "playout-user-id";
const NAME_KEY = "playout-user-name";

export function getCurrentUser(): SessionUser {
  if (typeof window === "undefined") return DEV_USER;
  const id = window.localStorage.getItem(KEY) || DEV_USER.id;
  const name = window.localStorage.getItem(NAME_KEY) || DEV_USER.name;
  return { id, name };
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
