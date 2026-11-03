export function duration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "0:00";
  const total = Math.floor(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return `${h ? `${h}:` : ""}${mm}:${String(s).padStart(2, "0")}`;
}

export function longDuration(ms: number): string {
  const minutes = Math.round(ms / 60000);
  if (minutes < 60) return `${minutes} Min.`;
  return `${Math.floor(minutes / 60)} Std. ${minutes % 60} Min.`;
}

export function plural(n: number, one: string, many: string): string {
  return `${n.toLocaleString("de-DE")} ${n === 1 ? one : many}`;
}

/** "vor 3 Wochen", "vor 5 Monaten": how long ago a time (ms) was, roughly. */
export function ago(ms: number, now = Date.now()): string {
  const days = Math.max(0, Math.floor((now - ms) / 86_400_000));
  if (days < 1) return "heute";
  if (days < 14) return days === 1 ? "gestern" : `vor ${days} Tagen`;
  if (days < 60) return `vor ${Math.round(days / 7)} Wochen`;
  if (days < 365) return `vor ${Math.round(days / 30)} Monaten`;
  const years = Math.round(days / 365);
  return years === 1 ? "vor einem Jahr" : `vor ${years} Jahren`;
}
