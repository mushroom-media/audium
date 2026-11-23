<script lang="ts">
  // Rule editor: a few simple filters (genres, "in the direction of" artists, tempo, year, recently
  // added), all optional and all combined with "and"; several genres or artists mean "any of them". Plus limit, order and a live preview
  // of how many tracks match. Used for smart playlists and admin rule playlists.
  // Conditions of older rules the form can't show (energy, "is not", …) are kept and listed.
  import { untrack } from "svelte";
  import { ApiError, get, post, type Rule, type RuleCondition, type RuleField, type Track } from "../api";
  import { ruleFieldLabels } from "../errors";
  import Icon from "./Icon.svelte";
  import Modal from "./Modal.svelte";
  import RuleFilters, { emptyFilters, filterConditions, type FilterValues } from "./RuleFilters.svelte";
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

  /** Splits a rule into what the form shows and the conditions it keeps as they are. */
  function parse(rule: Rule | null | undefined) {
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

  let fields = $state<RuleField[]>([]);
  let orders = $state<string[]>(["random"]);
  // The editor starts from the props once and then owns its state.
  const start = untrack(() => ({ name: initialName, rule: initial, form: parse(initial) }));
  let name = $state(start.name);
  const match = start.rule?.match === "any" && start.form.kept.length ? "any" : "all";
  let limit = $state(start.rule?.limit ?? 200);
  let order = $state(start.rule?.order ?? "random");
  const { kept: keptStart, ...filterStart } = start.form;
  let filters = $state<FilterValues>(filterStart);
  let kept = $state<RuleCondition[]>(keptStart);
  let preview = $state<{ count: number; tracks: Track[]; needs_analysis: boolean } | null>(null);
  let previewError = $state<string | null>(null);
  let saving = $state(false);

  $effect(() => {
    get<{ fields: RuleField[]; orders: string[] }>("/rules/fields").then((r) => {
      fields = r.fields;
      for (const f of r.fields) ruleFieldLabels[f.name] = f.label;
      orders = r.orders;
    });
  });

  const conditions = $derived<RuleCondition[]>([...kept, ...filterConditions(filters)]);
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

    <RuleFilters bind:values={filters} />

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
  @media (max-width: 640px) {
    .row {
      flex-direction: column;
      gap: 8px;
    }
  }
</style>
