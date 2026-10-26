// Logged-in user and their settings.

import {
  ApiError,
  connectServer,
  currentConnection,
  forgetToken,
  get,
  isApp,
  patch,
  post,
  refreshMediaToken,
  type Theme,
  type User,
  type UserSettings,
} from "./api";

export const session = $state({
  ready: false,
  needsSetup: false,
  user: null as User | null,
  settings: { theme: "system", stream_quality: "auto", shortcuts: "on" } as UserSettings,
});

export function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.dataset.theme = theme;
}

export async function loadSession() {
  if (isApp && !currentConnection()?.token) {
    // An app that is not connected yet: the login screen asks for the server too.
    session.user = null;
    session.needsSetup = false;
    session.ready = true;
    return;
  }
  try {
    await refreshMediaToken();
    session.user = await get<User>("/auth/me");
    session.settings = await get<UserSettings>("/auth/me/settings");
    applyTheme(session.settings.theme);
  } catch (e) {
    if (!(e instanceof ApiError && e.status === 401)) throw e;
    session.user = null;
    if (isApp) {
      forgetToken(); // revoked in the settings, or the account was disabled
      session.needsSetup = false;
    } else {
      session.needsSetup = (await get<{ needs_setup: boolean }>("/setup")).needs_setup;
    }
  } finally {
    session.ready = true;
  }
}

/** `server`: only in the apps, where logging in also means choosing the server. */
export async function login(username: string, password: string, server?: string) {
  if (isApp) await connectServer(server ?? currentConnection()?.server ?? "", username, password, deviceName());
  else await post<User>("/auth/login", { username, password });
  await loadSession();
}

export async function logout() {
  try {
    await post("/auth/logout"); // in an app this revokes its token on the server
  } finally {
    if (isApp) forgetToken();
    session.user = null;
  }
}

/** Shown next to the app's token in the settings, so it can be told apart and revoked. */
function deviceName(): string {
  const ua = navigator.userAgent;
  const os = /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Mac/.test(ua) ? "macOS" : /Windows/.test(ua) ? "Windows" : /Linux/.test(ua) ? "Linux" : "";
  return os ? `audium (${os})` : "audium";
}

export async function saveSettings(changes: Partial<UserSettings>) {
  session.settings = await patch<UserSettings>("/auth/me/settings", changes);
  applyTheme(session.settings.theme);
}
