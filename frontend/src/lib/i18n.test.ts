// Every text of the UI goes through t()/tn()/msg() and has an English translation. The German text
// is the key, so a text that changes in the code needs its entry in i18n/en.ts changed too.
import { describe, expect, it } from "vitest";
import { en } from "./i18n/en";

// Every source file as text, keyed by its path below src/ (e.g. "routes/Setup.svelte").
const SOURCES: Record<string, string> = Object.fromEntries(
  Object.entries(
    import.meta.glob<string>(["../**/*.svelte", "../**/*.ts", "!../**/*.test.ts", "!./i18n.svelte.ts", "!./i18n/**"], {
      query: "?raw",
      import: "default",
      eager: true,
    }),
  ).map(([p, code]) => [p.replace(/^\.\.\//, ""), code]),
);

const STRING = String.raw`"(?:[^"\\\n]|\\.)*"`;
const KEY_CALL = new RegExp(String.raw`\b(?:t|msg)\(\s*(${STRING})`, "g");
// plural(n, "Titel", "Titel") translates "{n} Titel" (format.ts)
const PLURAL_CALL = new RegExp(String.raw`\bplural\([^,()]*(?:\([^()]*\))?[^,()]*,\s*(${STRING}),\s*(${STRING})`, "g");
const COUNT_CALL = new RegExp(String.raw`\btn\([^,()]*(?:\([^()]*\))?[^,()]*,\s*(${STRING}),\s*(${STRING})`, "g");
const LITERAL = /"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`/g;

// Words that only German text has (none of them is a JavaScript or CSS word).
const GERMAN = new RegExp(
  String.raw`[äöüÄÖÜß„“]|\b(?:der|die|das|und|nicht|eine?n?|mit|von|für|auf|ist|im|den|dem|des|noch|schon|alle|keine?|bitte|oder|wird|werden|wurde|gibt|hier|jetzt|deine?[nrs]?|du|dich|dir|sich|aus|bei|nach|wie|wenn|dann|auch|nur|mehr|ohne|zum|zur|neu|titel|alben|künstler|lädt|speichern|abbrechen|löschen|fehlgeschlagen|einstellungen|gerade|zuletzt|gehört|weiter|fertig|suchen|entfernen|umbenennen|sortieren|ändern|anmelden|abmelden|jahr|jahre|minuten|sekunden|stunden|tage|heute|gestern|vor|seit|bis|uhr)\b`,
  "i",
);

function keysOf(code: string): string[] {
  const keys: string[] = [];
  for (const m of code.matchAll(KEY_CALL)) keys.push(JSON.parse(m[1]));
  for (const m of code.matchAll(COUNT_CALL)) keys.push(JSON.parse(m[1]), JSON.parse(m[2]));
  for (const m of code.matchAll(PLURAL_CALL)) {
    const [one, many] = [JSON.parse(m[1]), JSON.parse(m[2])];
    keys.push(one === many ? `{n} ${one}|eins` : `{n} ${one}`, `{n} ${many}`);
  }
  return keys;
}

/** Code without comments and without the texts that are already translated. */
function untranslated(code: string): string {
  return code
    // comments keep their line breaks, so the line numbers stay right
    .replace(/<!--[\s\S]*?-->|\/\*[\s\S]*?\*\//g, (c) => c.replace(/[^\n]/g, ""))
    .replace(/(^|[^:"'`\\])\/\/.*$/gm, "$1")
    .replace(KEY_CALL, (all, lit: string) => all.replace(lit, '""'))
    .replace(COUNT_CALL, (all, a: string, b: string) => all.replace(a, '""').replace(b, '""'))
    .replace(PLURAL_CALL, (all, a: string, b: string) => all.replace(a, '""').replace(b, '""'));
}

function leaks(file: string): string[] {
  const code = untranslated(SOURCES[file]);
  const found: string[] = [];
  let inStyle = false;
  let inScript = !file.endsWith(".svelte");
  code.split("\n").forEach((line, i) => {
    if (/<style/.test(line)) inStyle = true;
    if (/<script/.test(line)) inScript = true;
    if (!inStyle) {
      const literals = line.match(LITERAL) ?? [];
      // In the markup, the text between tags counts too.
      const text = inScript ? "" : line.replace(LITERAL, "").replace(/\{[^{}]*\}/g, "").replace(/<[^>]*>?/g, " ");
      const hit = [...literals, text].find((s) => GERMAN.test(s));
      if (hit) found.push(`${file}:${i + 1}: ${hit.trim().slice(0, 100)}`);
    }
    if (/<\/style>/.test(line)) inStyle = false;
    if (/<\/script>/.test(line)) inScript = false;
  });
  return found;
}

describe("i18n", () => {
  const files = Object.keys(SOURCES);
  const keys = new Set(files.flatMap((f) => keysOf(SOURCES[f])));

  it("reads the sources", () => {
    expect(files).toContain("routes/Setup.svelte");
  });

  it("has no German text outside t(), tn() and msg()", () => {
    expect(files.flatMap(leaks)).toEqual([]);
  });

  it("has an English translation for every text", () => {
    expect([...keys].filter((k) => !(k in en)).sort()).toEqual([]);
  });

  it("has no translations that are not used any more", () => {
    expect(Object.keys(en).filter((k) => !keys.has(k)).sort()).toEqual([]);
  });

  it("keeps the placeholders of the German text", () => {
    const names = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    const broken = Object.entries(en).filter(([de, english]) => names(de).join() !== names(english).join());
    expect(broken.map(([de]) => de)).toEqual([]);
  });
});
