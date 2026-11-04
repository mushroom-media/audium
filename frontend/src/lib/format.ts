import { t, tn } from "./i18n.svelte";

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
  if (minutes < 60) return t("{m} Min.", { m: minutes });
  return t("{h} Std. {m} Min.", { h: Math.floor(minutes / 60), m: minutes % 60 });
}

/** "1.234 Titel": the count and the word for it. The keys are "{n} Titel" and so on; where German
 * has one form for both ("1 Titel", "5 Titel"), the singular is "{n} Titel|eins" (English differs). */
export function plural(n: number, one: string, many: string): string {
  return tn(n, one === many ? `{n} ${one}|eins` : `{n} ${one}`, `{n} ${many}`);
}

/** "vor 3 Wochen", "vor 5 Monaten": how long ago a time (ms) was, roughly. */
export function ago(ms: number, now = Date.now()): string {
  const days = Math.max(0, Math.floor((now - ms) / 86_400_000));
  if (days < 1) return t("heute");
  if (days < 14) return days === 1 ? t("gestern") : t("vor {n} Tagen", { n: days });
  if (days < 60) return t("vor {n} Wochen", { n: Math.round(days / 7) });
  if (days < 365) return t("vor {n} Monaten", { n: Math.round(days / 30) });
  return tn(Math.round(days / 365), "vor einem Jahr", "vor {n} Jahren");
}
