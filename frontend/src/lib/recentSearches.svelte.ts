// What the user searched for lately, shown on the empty search page: queries, and artists and
// albums opened from the results. Kept in this browser only, per user.

import { session } from "./session.svelte";

export type RecentSearch =
  | { kind: "query"; q: string }
  | { kind: "artist"; id: number; name: string; cover: string | null }
  | { kind: "album"; id: number; title: string; artist: string; cover: string | null };

const MAX = 15;

const key = () => `audium.recentSearches.${session.user?.id ?? 0}`;

const same = (a: RecentSearch, b: RecentSearch) =>
  a.kind === "query" ? b.kind === "query" && a.q.toLowerCase() === b.q.toLowerCase() : a.kind === b.kind && a.id === (b as { id: number }).id;

export const recentSearches = $state({ items: [] as RecentSearch[] });

export function loadRecentSearches() {
  try {
    const raw = JSON.parse(localStorage.getItem(key()) ?? "[]");
    recentSearches.items = Array.isArray(raw) ? raw.slice(0, MAX) : [];
  } catch {
    recentSearches.items = [];
  }
}

function save() {
  try {
    localStorage.setItem(key(), JSON.stringify(recentSearches.items));
  } catch {
    /* private mode */
  }
}

/** Puts an entry on top (moving it there if it was listed already). */
export function rememberSearch(entry: RecentSearch) {
  if (entry.kind === "query" && entry.q.trim().length < 2) return;
  recentSearches.items = [entry, ...recentSearches.items.filter((e) => !same(e, entry))].slice(0, MAX);
  save();
}

export function forgetSearch(entry: RecentSearch) {
  recentSearches.items = recentSearches.items.filter((e) => !same(e, entry));
  save();
}

export function clearSearches() {
  recentSearches.items = [];
  save();
}
