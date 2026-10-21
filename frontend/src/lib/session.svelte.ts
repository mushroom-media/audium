// Logged-in user and their settings.

import { ApiError, get, patch, post, type Theme, type User, type UserSettings } from "./api";

export const session = $state({
  ready: false,
  needsSetup: false,
  user: null as User | null,
  settings: { theme: "system", stream_quality: "auto" } as UserSettings,
});

export function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.dataset.theme = theme;
}

export async function loadSession() {
  try {
    session.user = await get<User>("/auth/me");
    session.settings = await get<UserSettings>("/auth/me/settings");
    applyTheme(session.settings.theme);
  } catch (e) {
    if (!(e instanceof ApiError && e.status === 401)) throw e;
    session.user = null;
    session.needsSetup = (await get<{ needs_setup: boolean }>("/setup")).needs_setup;
  } finally {
    session.ready = true;
  }
}

export async function login(username: string, password: string) {
  await post<User>("/auth/login", { username, password });
  await loadSession();
}

export async function logout() {
  try {
    await post("/auth/logout");
  } finally {
    session.user = null;
  }
}

export async function saveSettings(changes: Partial<UserSettings>) {
  session.settings = await patch<UserSettings>("/auth/me/settings", changes);
  applyTheme(session.settings.theme);
}
