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

interface SetupStatus {
  needs_setup: boolean;
  window_open: boolean;
  dialog_pending: boolean;
}

export const session = $state({
  ready: false,
  /** Before `ready`: why the session is not loaded yet (the server is starting or not reachable). */
  waiting: null as "starting" | "unreachable" | null,
  needsSetup: false,
  /** The first admin can be created right now (only for a while after the server started). */
  setupWindowOpen: false,
  /** An admin has not finished the first-run dialog yet. Browser only: the apps have no dialog. */
  setupPending: false,
  user: null as User | null,
  settings: {
    theme: "system",
    stream_quality: "auto",
    shortcuts: "on",
    replay_gain: "off",
    crossfade: "off",
    crossfade_s: 5,
    backdrop_motion: 50,
    library_tab: "last",
    track_sort: "title",
    album_sort: "title",
    artist_role: "album",
    artist_images: "server",
    artist_images_default: "on",
    subsonic_api: "on",
  } as UserSettings,
});

export function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.dataset.theme = theme;
}

/** Who is logged in. Only a 401 means "nobody"; anything else (the server is starting, busy or
 * unreachable) throws and leaves the session as it was, so it never looks like a logout. */
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
    session.setupPending = !isApp && session.user.role === "admin" && (await get<SetupStatus>("/setup")).dialog_pending;
  } catch (e) {
    if (!(e instanceof ApiError && e.status === 401)) throw e;
    session.user = null;
    if (isApp) {
      forgetToken(); // revoked in the settings, or the account was disabled
      session.needsSetup = false;
    } else {
      const setup = await get<SetupStatus>("/setup");
      session.needsSetup = setup.needs_setup;
      session.setupWindowOpen = setup.window_open;
    }
  }
  session.waiting = null;
  session.ready = true;
}

const RETRY_MAX_MS = 10_000;

/** At start: loads the session, and while the server does not answer properly (e.g. right
 * after an update, when it migrates the database) says so and tries again. */
export async function startSession(attempt = 0) {
  try {
    await loadSession();
  } catch (e) {
    session.waiting = e instanceof ApiError && e.code === "starting" ? "starting" : "unreachable";
    const after = e instanceof ApiError && e.retryAfter ? e.retryAfter * 1000 : 1000 * 2 ** attempt;
    setTimeout(() => startSession(attempt + 1), Math.min(after, RETRY_MAX_MS));
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

/** Shows the change at once and takes it back if the server refuses. */
export async function saveSettings(changes: Partial<UserSettings>) {
  const before = session.settings;
  session.settings = { ...before, ...changes };
  applyTheme(session.settings.theme);
  try {
    session.settings = await patch<UserSettings>("/auth/me/settings", changes);
  } catch (e) {
    session.settings = before;
    applyTheme(before.theme);
    throw e;
  }
}
