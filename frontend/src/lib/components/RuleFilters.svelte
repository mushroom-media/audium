<script module lang="ts">
  import type { Rule, RuleCondition } from "../api";

  export type Range = { from: number | null; to: number | null };

  /** What the filter form holds; all of it optional. */
  export interface FilterValues {
    genres: string[];
    artists: string[];
    bpm: Range;
    year: Range;
    addedDays: number | null;
  }

  export const emptyFilters = (): FilterValues => ({
    genres: [],
    artists: [],
    bpm: { from: null, to: null },
    year: { from: null, to: null },
    addedDays: null,
  });

  /** A number input's value, or null when it's empty. */
  const numberOf = (v: unknown) => (v === null || v === undefined || v === "" || Number.isNaN(Number(v)) ? null : Number(v));

  function rangeCondition(field: string, r: Range): RuleCondition | null {
    const from = numberOf(r.from);
    const to = numberOf(r.to);
    if (from !== null && to !== null) return { field, op: "between", value: [from, to] };
    if (from !== null) return { field, op: ">=", value: from };
    if (to !== null) return { field, op: "<=", value: to };
    return null;
  }

  /** The form as rule conditions, all combined with "and"; several genres or artists mean "any of them". */
  export function filterConditions(f: FilterValues): RuleCondition[] {
    const days = numberOf(f.addedDays);
    return [
      f.genres.length ? { field: "genre", op: "is", value: f.genres.length === 1 ? f.genres[0] : [...f.genres] } : null,
      f.artists.length ? { field: "like_artist", op: "is", value: [...f.artists] } : null,
      rangeCondition("bpm", f.bpm),
      rangeCondition("year", f.year),
      days !== null ? { field: "added_days", op: "<=", value: days } : null,
    ].filter((c): c is RuleCondition => c !== null);
  }

  /** Splits a rule into what the form shows and the conditions it keeps as they are. */
  export function parseRule(rule: Rule | null | undefined) {
    const out: FilterValues & { kept: RuleCondition[] } = { ...emptyFilters(), kept: [] };
    if (!rule) return out;
    const conds = rule.conditions;
    // "any" only fits the form when every condition is a genre: then it's one list of genres.
    if (rule.match === "any" && !conds.every((c) => c.field === "genre" && c.op === "is")) {
      out.kept = conds.map((c) => ({ ...c }));
      return out;
    }
    let genreTaken = false;
    let artistTaken = false;
    for (const c of conds) {
      const range = c.field === "bpm" ? out.bpm : c.field === "year" ? out.year : null;
      if (c.field === "genre" && c.op === "is" && (rule.match === "any" || !genreTaken)) {
        out.genres.push(...(Array.isArray(c.value) ? c.value.map(String) : [String(c.value)]));
        genreTaken = true;
      } else if (c.field === "like_artist" && c.op === "is" && !artistTaken) {
        out.artists.push(...(Array.isArray(c.value) ? c.value.map(String) : [String(c.value)]));
        artistTaken = true;
      } else if (range && range.from === null && range.to === null && ["between", ">=", "<=", "="].includes(c.op)) {
        const [lo, hi] = Array.isArray(c.value) ? c.value.map(Number) : [Number(c.value), Number(c.value)];
        if (c.op !== "<=") range.from = lo;
        if (c.op !== ">=") range.to = hi;
      } else if (c.field === "added_days" && c.op === "<=" && out.addedDays === null) {
        out.addedDays = Number(c.value);
      } else {
        out.kept.push({ ...c });
      }
    }
    return out;
  }
</script>

<script lang="ts">
  // The simple filters of a rule: genres, "in the direction of" artists, tempo, year, recently added.
  // Used by the rule editor (smart playlists) and by "fill automatically" in the new playlist dialog.
  import { get } from "../api";
  import ChipInput from "./ChipInput.svelte";
  import { t } from "../i18n.svelte";

  let { values = $bindable() }: { values: FilterValues } = $props();

  const uid = Math.random().toString(36).slice(2);
  let allGenres = $state<string[]>([]);
  let artistSuggestions = $state<string[]>([]);

  $effect(() => {
    get<{ name: string }[]>("/genres").then((g) => (allGenres = g.map((x) => x.name)));
  });

  // Artist suggestions come from the search, as you type.
  let artistQuery: AbortController | undefined;
  function findArtists(q: string) {
    artistQuery?.abort();
    if (!q) return;
    artistQuery = new AbortController();
    get<{ artists: { name: string }[] }>("/search", { q, types: "artist", limit: 10 }, artistQuery.signal)
      .then((r) => (artistSuggestions = r.artists.map((a) => a.name)))
      .catch(() => {});
  }
</script>

<div class="filters">
  <span class="label" id="genre-{uid}">{t("Genre")}</span>
  <ChipInput bind:values={values.genres} suggestions={allGenres} labelledby="genre-{uid}"
    placeholder={t("Genre wählen …")} morePlaceholder={t("weiteres Genre …")} />

  <span class="label" id="artist-{uid}">{t("In Richtung von")}</span>
  <div>
    <ChipInput bind:values={values.artists} suggestions={artistSuggestions} labelledby="artist-{uid}" onquery={findArtists}
      placeholder={t("Künstler eingeben …")} morePlaceholder={t("weiterer Künstler …")} />
    <p class="field-hint">{t("Titel dieser Künstler, dazu ähnliche Künstler und ihre Stilrichtung.")}</p>
  </div>

  <span class="label">{t("Tempo")} ✦</span>
  <div class="range">
    <input type="number" min="0" max="300" bind:value={values.bpm.from} placeholder={t("von")} aria-label={t("Tempo von")} />
    <span>–</span>
    <input type="number" min="0" max="300" bind:value={values.bpm.to} placeholder={t("bis")} aria-label={t("Tempo bis")} />
    <span class="unit">BPM</span>
  </div>

  <span class="label">{t("Jahr")}</span>
  <div class="range">
    <input type="number" min="1900" max="2100" bind:value={values.year.from} placeholder={t("von")} aria-label={t("Jahr von")} />
    <span>–</span>
    <input type="number" min="1900" max="2100" bind:value={values.year.to} placeholder={t("bis")} aria-label={t("Jahr bis")} />
    <span class="unit"></span>
  </div>

  <span class="label">{t("Hinzugefügt")}</span>
  <div class="range">
    <span>{t("in den letzten")}</span>
    <input type="number" min="1" bind:value={values.addedDays} aria-label={t("Hinzugefügt in den letzten … Tagen")} />
    <span>{t("Tagen")}</span>
  </div>
</div>

<style>
  .filters {
    display: grid;
    grid-template-columns: max-content minmax(0, 1fr);
    gap: 10px 14px;
    align-items: center;
  }
  .filters :global(input:not([type="checkbox"]):not([type="radio"])) {
    box-sizing: border-box;
    min-width: 0;
    max-width: 100%;
  }
  .label {
    color: var(--text-muted);
  }
  .field-hint {
    margin: 4px 0 0;
    color: var(--text-faint);
    font-size: 0.8rem;
  }
  .range {
    display: flex;
    gap: 8px;
    align-items: center;
    color: var(--text-muted);
  }
  .range input {
    width: 90px;
  }
  .unit {
    min-width: 2.5em;
  }
  /* Narrow screens: each label above its control. */
  @media (max-width: 640px) {
    .filters {
      grid-template-columns: minmax(0, 1fr);
      gap: 4px;
    }
    .filters > .label:not(:first-child) {
      margin-top: 8px;
    }
  }
</style>
