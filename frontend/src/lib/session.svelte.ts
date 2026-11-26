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
import { browserLanguage, setLanguage, type Lang } from "./i18n.svelte";
import { link, linkDown } from "./link.svelte";

interface SetupStatus {
  needs_setup: boolean;
  window_open: boolean;
  dialog_pending: boolean;
  /** null: no admin has chosen one yet. */
  language: Lang | null;
}

export const session = $state({
  ready: false,
  /** Before `ready`: why the session is not loaded yet (the server is starting or not reachable). */
  waiting: null as "starting" | "unreachable" | "connecting" | null,
  /** Shown from the last session on this device because the server did not answer at the start
   * (no network). startSession keeps trying and replaces it with the real one. */
  remembered: false,
  needsSetup: false,
  /** The first admin can be created right now (only for a while after the server started). */
  setupWindowOpen: false,
  /** An admin has not finished the first-run dialog yet. Browser only: the apps have no dialog. */
  setupPending: false,
  user: null as User | null,
  settings: {
    language: "server",
    language_default: "de",
    theme: "system",
    stream_quality: "auto",
    shortcuts: "on",
    seek_keys: "off",
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

/** The language a user sees: their own choice, or the server language. */
export function applyLanguage(settings: UserSettings) {
  setLanguage(settings.language === "server" ? settings.language_default : settings.language);
}

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
    setLanguage(browserLanguage());
    session.ready = true;
    return;
  }
  try {
    await refreshMediaToken();
    session.user = await get<User>("/auth/me");
    session.settings = await get<UserSettings>("/auth/me/settings");
    applyTheme(session.settings.theme);
    applyLanguage(session.settings);
    session.setupPending = !isApp && session.user.role === "admin" && (await get<SetupStatus>("/setup")).dialog_pending;
    remember();
  } catch (e) {
    if (!(e instanceof ApiError && e.status === 401)) throw e;
    session.user = null;
    forget();
    if (isApp) {
      forgetToken(); // revoked in the settings, or the account was disabled
      session.needsSetup = false;
      setLanguage(browserLanguage());
    } else {
      const setup = await get<SetupStatus>("/setup");
      session.needsSetup = setup.needs_setup;
      session.setupWindowOpen = setup.window_open;
      setLanguage(setup.language ?? browserLanguage());
    }
  }
  session.waiting = null;
  // Pages shown from the remembered session load again, now with the media token for covers.
  if (session.remembered) link.epoch++;
  session.remembered = false;
  session.ready = true;
}

const RETRY_MAX_MS = 10_000;
/** No answer at the start for this long: show the remembered session instead of an empty window. */
const SLOW_START_MS = 3000;

// The last session on this device, so a start without network shows the pages (with a notice)
// instead of a black window. Per server address; gone on logout or a revoked token.
const REMEMBER_KEY = "audium.session";

function rememberKey() {
  return `${REMEMBER_KEY}:${currentConnection()?.server ?? ""}`;
}

function remember() {
  try {
    localStorage.setItem(rememberKey(), JSON.stringify({ user: session.user, settings: session.settings }));
  } catch {
    /* private mode */
  }
}

function forget() {
  try {
    localStorage.removeItem(rememberKey());
  } catch {
    /* private mode */
  }
}

/** Shows the remembered session while the server is out of reach. False if there is none. */
function useRemembered(): boolean {
  if (session.ready) return true;
  let saved: { user: User; settings: UserSettings } | null = null;
  try {
    saved = JSON.parse(localStorage.getItem(rememberKey()) ?? "null");
  } catch {
    /* nothing usable */
  }
  if (!saved?.user || (isApp && !currentConnection()?.token)) return false;
  session.user = saved.user;
  session.settings = { ...session.settings, ...saved.settings };
  applyTheme(session.settings.theme);
  applyLanguage(session.settings);
  session.remembered = true;
  session.ready = true;
  linkDown();
  return true;
}

/** At start: loads the session, and while the server does not answer properly (e.g. right
 * after an update, when it migrates the database) says so and tries again. Without network the
 * remembered session stands in, so the app opens with a notice instead of an empty window. */
export async function startSession(attempt = 0) {
  const slow =
    attempt === 0 ? setTimeout(() => useRemembered() || (session.waiting ??= "connecting"), SLOW_START_MS) : undefined;
  try {
    await loadSession();
  } catch (e) {
    const starting = e instanceof ApiError && e.code === "starting";
    session.waiting = starting ? "starting" : "unreachable";
    if (!starting) useRemembered();
    const after = e instanceof ApiError && e.retryAfter ? e.retryAfter * 1000 : 1000 * 2 ** attempt;
    setTimeout(() => startSession(attempt + 1), Math.min(after, RETRY_MAX_MS));
  } finally {
    clearTimeout(slow);
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
    forget();
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
  applyLanguage(session.settings);
  try {
    session.settings = await patch<UserSettings>("/auth/me/settings", changes);
    applyLanguage(session.settings);
  } catch (e) {
    session.settings = before;
    applyTheme(before.theme);
    applyLanguage(before);
    throw e;
  }
}
