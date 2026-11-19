<script lang="ts">
  // Rule editor: a few simple filters (genres, "in the direction of" artists, tempo, year, recently
  // added), all optional and all combined with "and"; several genres or artists mean "any of them". Plus limit, order and a live preview
  // of how many tracks match. Used for smart playlists and admin rule playlists.
  // Conditions of older rules the form can't show (energy, "is not", …) are kept and listed.
  import { untrack } from "svelte";
  import { ApiError, get, post, type Rule, type RuleCondition, type RuleField, type Track } from "../api";
  import { ruleFieldLabels } from "../errors";
  import ChipInput from "./ChipInput.svelte";
  import Icon from "./Icon.svelte";
  import Modal from "./Modal.svelte";
  import { locale, msg, t } from "../i18n.svelte";

  let {
    title,
    initial,
    initialName = "",
    askName = true,
    onsave,
    onclose,
  }: {
    title: string;
    initial?: Rule | null;
    initialName?: string;
    askName?: boolean;
    onsave: (name: string, rule: Rule) => Promise<void>;
    onclose: () => void;
  } = $props();

  const OP_LABELS: Record<string, string> = {
    "=": msg("ist"),
    "!=": msg("ist nicht"),
    "<": msg("kleiner als"),
    "<=": msg("höchstens"),
    ">": msg("größer als"),
    ">=": msg("mindestens"),
    between: msg("zwischen"),
    is: msg("ist"),
    is_not: msg("ist nicht"),
    contains: msg("enthält"),
  };
  const ORDER_LABELS: Record<string, string> = {
    random: msg("Zufällig"),
    added: msg("Neu hinzugefügt"),
    year: msg("Jahr"),
    title: msg("Titel|Sortierung"),
    bpm: msg("Tempo"),
    energy: msg("Energie"),
  };
  const OPTION_LABELS: Record<string, string> = { major: msg("Dur"), minor: msg("Moll") };

  type Range = { from: number | null; to: number | null };

  /** Splits a rule into what the form shows and the conditions it keeps as they are. */
  function parse(rule: Rule | null | undefined) {
    const out = {
      genres: [] as string[],
      artists: [] as string[],
      bpm: { from: null, to: null } as Range,
      year: { from: null, to: null } as Range,
      addedDays: null as number | null,
      kept: [] as RuleCondition[],
    };
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

  let fields = $state<RuleField[]>([]);
  let orders = $state<string[]>(["random"]);
  let allGenres = $state<string[]>([]);
  // The editor starts from the props once and then owns its state.
  const start = untrack(() => ({ name: initialName, rule: initial, form: parse(initial) }));
  let name = $state(start.name);
  const match = start.rule?.match === "any" && start.form.kept.length ? "any" : "all";
  let limit = $state(start.rule?.limit ?? 200);
  let order = $state(start.rule?.order ?? "random");
  let chosen = $state<string[]>(start.form.genres);
  let bpm = $state<Range>(start.form.bpm);
  let year = $state<Range>(start.form.year);
  let addedDays = $state<number | null>(start.form.addedDays);
  let kept = $state<RuleCondition[]>(start.form.kept);
  let likeArtists = $state<string[]>(start.form.artists);
  let artistSuggestions = $state<string[]>([]);
  let preview = $state<{ count: number; tracks: Track[]; needs_analysis: boolean } | null>(null);
  let previewError = $state<string | null>(null);
  let saving = $state(false);

  $effect(() => {
    get<{ fields: RuleField[]; orders: string[] }>("/rules/fields").then((r) => {
      fields = r.fields;
      for (const f of r.fields) ruleFieldLabels[f.name] = f.label;
      orders = r.orders;
    });
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

  const conditions = $derived<RuleCondition[]>(
    [
      ...kept,
      chosen.length ? { field: "genre", op: "is", value: chosen.length === 1 ? chosen[0] : [...chosen] } : null,
      likeArtists.length ? { field: "like_artist", op: "is", value: [...likeArtists] } : null,
      rangeCondition("bpm", bpm),
      rangeCondition("year", year),
      numberOf(addedDays) !== null ? { field: "added_days", op: "<=", value: numberOf(addedDays)! } : null,
    ].filter((c): c is RuleCondition => c !== null),
  );
  const rule = $derived<Rule>({ match, conditions, limit: Number(limit) || 200, order });

  // Live preview, debounced: the server validates and counts.
  let timer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    const body = JSON.parse(JSON.stringify(rule));
    clearTimeout(timer);
    if (!body.conditions.length) {
      preview = null;
      previewError = null;
      return;
    }
    timer = setTimeout(async () => {
      try {
        preview = await post("/rules/preview", { rule: body });
        previewError = null;
      } catch (e) {
        preview = null;
        previewError = e instanceof ApiError ? e.message : t("Fehler");
      }
    }, 350);
    return () => clearTimeout(timer);
  });

  async function save() {
    saving = true;
    try {
      await onsave(name.trim(), JSON.parse(JSON.stringify(rule)));
    } catch (e) {
      previewError = e instanceof ApiError ? e.message : t("Speichern fehlgeschlagen");
    } finally {
      saving = false;
    }
  }

  /** A kept condition in words, e.g. "Energie mindestens 60 %". */
  function describe(c: RuleCondition) {
    const f = fields.find((x) => x.name === c.field);
    const one = (v: unknown) =>
      f?.kind === "scale" ? `${Math.round(Number(v) * 100)} %` : OPTION_LABELS[String(v)] ? t(OPTION_LABELS[String(v)]) : String(v);
    const value = Array.isArray(c.value)
      ? c.op === "between"
        ? `${one(c.value[0])} – ${one(c.value[1])}`
        : c.value.map(one).join(", ")
      : one(c.value);
    const op = OP_LABELS[c.op] ? t(OP_LABELS[c.op]) : c.op;
    return `${f?.label ?? c.field} ${op} ${value}${f?.unit && f.kind !== "scale" ? ` ${f.unit}` : ""}`;
  }
</script>

<Modal {title} {onclose} width={560}>
  <div class="editor">
    {#if askName}
      <label class="name">{t("Name")}<input bind:value={name} maxlength="200" placeholder={t("z. B. Schnelle 90er")} /></label>
    {/if}

    <div class="filters">
      <span class="label" id="genre-label">{t("Genre")}</span>
      <ChipInput bind:values={chosen} suggestions={allGenres} labelledby="genre-label"
        placeholder={t("Genre wählen …")} morePlaceholder={t("weiteres Genre …")} />

      <span class="label" id="artist-label">{t("In Richtung von")}</span>
      <div>
        <ChipInput bind:values={likeArtists} suggestions={artistSuggestions} labelledby="artist-label" onquery={findArtists}
          placeholder={t("Künstler eingeben …")} morePlaceholder={t("weiterer Künstler …")} />
        <p class="field-hint">{t("Titel dieser Künstler, dazu ähnliche Künstler und ihre Stilrichtung.")}</p>
      </div>

      <span class="label">{t("Tempo")} ✦</span>
      <div class="range">
        <input type="number" min="0" max="300" bind:value={bpm.from} placeholder={t("von")} aria-label={t("Tempo von")} />
        <span>–</span>
        <input type="number" min="0" max="300" bind:value={bpm.to} placeholder={t("bis")} aria-label={t("Tempo bis")} />
        <span class="unit">BPM</span>
      </div>

      <span class="label">{t("Jahr")}</span>
      <div class="range">
        <input type="number" min="1900" max="2100" bind:value={year.from} placeholder={t("von")} aria-label={t("Jahr von")} />
        <span>–</span>
        <input type="number" min="1900" max="2100" bind:value={year.to} placeholder={t("bis")} aria-label={t("Jahr bis")} />
        <span class="unit"></span>
      </div>

      <span class="label">{t("Hinzugefügt")}</span>
      <div class="range">
        <span>{t("in den letzten")}</span>
        <input type="number" min="1" bind:value={addedDays} aria-label={t("Hinzugefügt in den letzten … Tagen")} />
        <span>{t("Tagen")}</span>
      </div>
    </div>

    {#if kept.length}
      <div class="kept">
        <p>{match === "any" ? t("Weitere Bedingungen (mindestens eine muss passen):") : t("Weitere Bedingungen:")}</p>
        {#each kept as c, i (i)}
          <div class="kept-row">
            <span>{describe(c)}</span>
            <button class="icon-btn" aria-label={t("Bedingung entfernen")} onclick={() => kept.splice(i, 1)}><Icon name="close" size={16} /></button>
          </div>
        {/each}
      </div>
    {/if}

    <div class="row">
      <label>{t("Höchstens")} <input type="number" min="1" max="1000" bind:value={limit} class="short" /> {t("Titel|Anzahl")}</label>
      <label>{t("sortiert nach")}
        <select bind:value={order}>{#each orders as o (o)}<option value={o}>{ORDER_LABELS[o] ? t(ORDER_LABELS[o]) : o}</option>{/each}</select>
      </label>
    </div>

    <div class="preview" role="status">
      {#if !conditions.length}
        <span class="muted">{t("Wähle ein Genre oder einen Künstler, oder grenze Tempo, Jahr oder Hinzugefügt ein.")}</span>
      {:else if previewError}
        <span class="err">{previewError}</span>
      {:else if preview}
        <strong>{preview.count.toLocaleString(locale())}</strong> {t("passende Titel")}{#if preview.count === 0 && preview.needs_analysis}
          {t("– das Tempo braucht die Audioanalyse; ist sie fertig?")}{/if}
        {#if preview.tracks.length}
          <ul>{#each preview.tracks.slice(0, 5) as track (track.id)}<li>{track.title} <small>· {track.artist}</small></li>{/each}</ul>
        {/if}
      {:else}
        …
      {/if}
    </div>
    <p class="hint">{t("✦ = aus der Audioanalyse.")}</p>

    <div class="buttons">
      <button class="btn ghost" onclick={onclose}>{t("Abbrechen")}</button>
      <button class="btn primary" disabled={saving || !conditions.length || !!previewError || (askName && !name.trim())} onclick={save}>{t("Speichern")}</button>
    </div>
  </div>
</Modal>

<style>
  .editor {
    display: flex;
    flex-direction: column;
    gap: 14px;
    min-width: 0;
  }
  .editor :global(input:not([type="checkbox"]):not([type="radio"])),
  .editor :global(select) {
    box-sizing: border-box;
    min-width: 0;
    max-width: 100%;
  }
  .name {
    display: flex;
    flex-direction: column;
    gap: 6px;
    color: var(--text-muted);
    font-size: 0.88rem;
  }
  .name input {
    width: 100%;
  }
  .filters {
    display: grid;
    grid-template-columns: max-content minmax(0, 1fr);
    gap: 10px 14px;
    align-items: center;
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
  .kept {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .kept p {
    margin: 0;
    color: var(--text-muted);
    font-size: 0.88rem;
  }
  .kept-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
    padding: 2px 0 2px 10px;
    border-left: 2px solid var(--line);
  }
  .row {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    color: var(--text-muted);
  }
  .short {
    width: 80px;
  }
  .preview {
    background: var(--surface-1);
    border-radius: var(--radius-sm);
    padding: 10px 12px;
    min-height: 44px;
  }
  .preview ul {
    margin: 6px 0 0;
    padding-left: 18px;
    font-size: 0.88rem;
  }
  .muted {
    color: var(--text-muted);
  }
  .err {
    color: var(--danger);
  }
  .hint {
    margin: 0;
    color: var(--text-faint);
    font-size: 0.8rem;
  }
  small {
    color: var(--text-muted);
  }
  .buttons {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
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
    .row {
      flex-direction: column;
      gap: 8px;
    }
  }
</style>
