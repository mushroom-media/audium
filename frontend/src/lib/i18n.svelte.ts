// Languages of the web UI. The German text is the key: t("Alle Alben") shows it as it is in German
// and looks it up in i18n/en.ts in English. A missing translation shows the German text, and the
// test in i18n.test.ts lists it, so nothing is lost when a text changes.
//
// A word that needs different English in different places gets a context after "|", which German
// does not show: t("Titel|Sortierung") is "Titel" in German and "Title" in English (t("Titel"): "Tracks").
//
// Placeholders: t("vor {n} Tagen", { n: 3 }). Numbers in placeholders are formatted for the
// language (1.000 / 1,000). Counted things: tn(n, "{n} Titel", "{n} Titel").

import { en } from "./i18n/en";

export type Lang = "de" | "en";
export const LANGUAGES: Record<Lang, string> = { de: "Deutsch", en: "English" };

export const i18n = $state({ lang: "de" as Lang });

/** The language the browser prefers, among the ones audium has (German or English). */
export function browserLanguage(): Lang {
  const prefs = navigator.languages?.length ? navigator.languages : [navigator.language];
  for (const pref of prefs) {
    const base = pref?.slice(0, 2).toLowerCase();
    if (base === "de" || base === "en") return base;
  }
  return "en";
}

export function setLanguage(lang: Lang) {
  i18n.lang = lang;
  document.documentElement.lang = lang;
}

/** For toLocaleString and Intl: "de-DE" or "en-US". */
export function locale(): string {
  return i18n.lang === "en" ? "en-US" : "de-DE";
}

export function num(n: number, options?: Intl.NumberFormatOptions): string {
  return n.toLocaleString(locale(), options);
}

type Params = Record<string, string | number>;

function fill(text: string, params?: Params): string {
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (all, key: string) => {
    const value = params[key];
    if (value === undefined) return all;
    return typeof value === "number" ? num(value) : value;
  });
}

/** The German text of a key: without its context ("Titel|Sortierung" -> "Titel"). */
function german(key: string): string {
  const bar = key.indexOf("|");
  return bar < 0 ? key : key.slice(0, bar);
}

/** The text in the current language. `de` is the German text, which is also the key. */
export function t(de: string, params?: Params): string {
  return fill(i18n.lang === "en" ? (en[de] ?? german(de)) : german(de), params);
}

/** A counted text: `one` for exactly 1, otherwise `many`; {n} is the count. */
export function tn(n: number, one: string, many: string, params?: Params): string {
  return t(n === 1 ? one : many, { n, ...params });
}

/** Marks a text for translation where it is defined (e.g. in a table of labels) without
 * translating it yet: it is shown later with t(label), in the language current at that time. */
export function msg(de: string): string {
  return de;
}
