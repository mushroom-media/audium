<script lang="ts">
  // Rule editor: rows of field / operator / value, match all or any, limit, order, and a live
  // preview of how many tracks match. Used for smart playlists and admin rule playlists.
  import { untrack } from "svelte";
  import { ApiError, get, post, type Rule, type RuleCondition, type RuleField, type Track } from "../api";
  import { ruleFieldLabels } from "../errors";
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

  let fields = $state<RuleField[]>([]);
  let orders = $state<string[]>(["random"]);
  let genres = $state<string[]>([]);
  let styles = $state<string[]>([]);
  // The editor starts from the props once and then owns its state.
  const start = untrack(() => ({ name: initialName, rule: initial }));
  let name = $state(start.name);
  let match = $state<"all" | "any">(start.rule?.match ?? "all");
  let limit = $state(start.rule?.limit ?? 200);
  let order = $state(start.rule?.order ?? "random");
  let conditions = $state<RuleCondition[]>(
    start.rule?.conditions.map((c) => ({ ...c })) ?? [{ field: "genre", op: "is", value: "" }],
  );
  let preview = $state<{ count: number; tracks: Track[]; needs_analysis: boolean } | null>(null);
  let previewError = $state<string | null>(null);
  let saving = $state(false);

  $effect(() => {
    get<{ fields: RuleField[]; orders: string[] }>("/rules/fields").then((r) => {
      fields = r.fields;
      for (const f of r.fields) ruleFieldLabels[f.name] = f.label;
      orders = r.orders;
    });
    get<{ name: string }[]>("/genres").then((g) => (genres = g.map((x) => x.name)));
    get<{ name: string }[]>("/styles").then((s) => (styles = s.map((x) => x.name)));
  });

  const fieldOf = (name: string) => fields.find((f) => f.name === name);
  const isScale = (c: RuleCondition) => fieldOf(c.field)?.kind === "scale";

  function setField(c: RuleCondition, fieldName: string) {
    const f = fieldOf(fieldName);
    c.field = fieldName;
    c.op = f?.ops[0] ?? "is";
    c.value = f?.kind === "scale" ? 0.6 : f?.kind === "number" ? (fieldName === "year" ? 2000 : 120) : (f?.options[0] ?? "");
  }

  function setOp(c: RuleCondition, op: string) {
    c.op = op;
    if (op === "between" && !Array.isArray(c.value)) {
      const v = Number(c.value) || 0;
      c.value = isScale(c) ? [Math.max(0, v - 0.2), Math.min(1, v + 0.2)] : [v, v + 10];
    } else if (op !== "between" && Array.isArray(c.value)) {
      c.value = c.value[0];
    }
  }

  const rule = $derived<Rule>({ match, conditions, limit: Number(limit) || 200, order });

  // Live preview, debounced: the server validates and counts.
  let timer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    const body = JSON.parse(JSON.stringify(rule));
    clearTimeout(timer);
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

  const display = (v: unknown) => (typeof v === "number" ? v : Number(v));
</script>

<Modal {title} {onclose} width={680}>
  <div class="editor">
    {#if askName}
      <label class="name">{t("Name")}<input bind:value={name} maxlength="200" placeholder={t("z. B. Schnelle 90er")} /></label>
    {/if}
    <div class="match">
      {t("Titel, die")}
      <select bind:value={match} aria-label={t("Verknüpfung")}>
        <option value="all">{t("alle")}</option>
        <option value="any">{t("mindestens eine")}</option>
      </select>
      {t("Bedingungen erfüllen:")}
    </div>

    {#each conditions as c, i (i)}
      {@const f = fieldOf(c.field)}
      <div class="cond">
        <select value={c.field} onchange={(e) => setField(c, e.currentTarget.value)} aria-label={t("Feld")}>
          {#each fields as opt (opt.name)}<option value={opt.name}>{opt.label}{opt.needs_analysis ? " ✦" : ""}</option>{/each}
        </select>
        <select value={c.op} onchange={(e) => setOp(c, e.currentTarget.value)} aria-label={t("Operator")}>
          {#each f?.ops ?? [] as op (op)}<option value={op}>{OP_LABELS[op] ? t(OP_LABELS[op]) : op}</option>{/each}
        </select>
        <span class="value">
          {#if f?.kind === "enum"}
            <select bind:value={c.value} aria-label={t("Wert")}>
              {#each f.options as o (o)}<option value={o}>{OPTION_LABELS[o] ? t(OPTION_LABELS[o]) : o}</option>{/each}
            </select>
          {:else if f?.kind === "text"}
            <input bind:value={c.value} list={c.field === "genre" ? "genre-list" : c.field === "style" ? "style-list" : undefined} aria-label={t("Wert")} />
          {:else if Array.isArray(c.value)}
            <input type="number" step={isScale(c) ? 0.05 : 1} min={isScale(c) ? 0 : undefined} max={isScale(c) ? 1 : undefined}
              value={display(c.value[0])} oninput={(e) => ((c.value as [number, number])[0] = Number(e.currentTarget.value))} aria-label={t("Von")} />
            <span>{t("und")}</span>
            <input type="number" step={isScale(c) ? 0.05 : 1} min={isScale(c) ? 0 : undefined} max={isScale(c) ? 1 : undefined}
              value={display(c.value[1])} oninput={(e) => ((c.value as [number, number])[1] = Number(e.currentTarget.value))} aria-label={t("Bis")} />
          {:else if isScale(c)}
            <input type="range" min="0" max="1" step="0.05" bind:value={c.value} style:--p="{Number(c.value) * 100}%" aria-label={t("Wert")} />
            <span class="pct">{Math.round(Number(c.value) * 100)} %</span>
          {:else}
            <input type="number" bind:value={c.value} aria-label={t("Wert")} />{#if f?.unit}<span>{f.unit}</span>{/if}
          {/if}
        </span>
        <button class="icon-btn" aria-label={t("Bedingung entfernen")} disabled={conditions.length === 1}
          onclick={() => conditions.splice(i, 1)}><Icon name="close" size={16} /></button>
      </div>
    {/each}
    <datalist id="genre-list">{#each genres as g (g)}<option value={g}></option>{/each}</datalist>
    <datalist id="style-list">{#each styles as s (s)}<option value={s}></option>{/each}</datalist>
    <button class="btn ghost small" onclick={() => conditions.push({ field: "year", op: ">=", value: 2000 })}>
      <Icon name="plus" size={16} /> {t("Bedingung")}
    </button>

    <div class="row">
      <label>{t("Höchstens")} <input type="number" min="1" max="1000" bind:value={limit} class="short" /> {t("Titel|Anzahl")}</label>
      <label>{t("sortiert nach")}
        <select bind:value={order}>{#each orders as o (o)}<option value={o}>{ORDER_LABELS[o] ? t(ORDER_LABELS[o]) : o}</option>{/each}</select>
      </label>
    </div>

    <div class="preview" role="status">
      {#if previewError}
        <span class="err">{previewError}</span>
      {:else if preview}
        <strong>{preview.count.toLocaleString(locale())}</strong> {t("passende Titel")}{#if preview.count === 0 && preview.needs_analysis}
          {t("– ✦-Felder brauchen die Audioanalyse; ist sie fertig?")}{/if}
        {#if preview.tracks.length}
          <ul>{#each preview.tracks.slice(0, 5) as t (t.id)}<li>{t.title} <small>· {t.artist}</small></li>{/each}</ul>
        {/if}
      {:else}
        …
      {/if}
    </div>
    <p class="hint">{t("✦ = aus der Audioanalyse. Energie, Tanzbarkeit usw. gehen von 0 % bis 100 %.")}</p>

    <div class="buttons">
      <button class="btn ghost" onclick={onclose}>{t("Abbrechen")}</button>
      <button class="btn primary" disabled={saving || !!previewError || (askName && !name.trim())} onclick={save}>{t("Speichern")}</button>
    </div>
  </div>
</Modal>

<style>
  .editor {
    display: flex;
    flex-direction: column;
    gap: 12px;
    min-width: 0;
  }
  .editor :global(input:not([type="range"]):not([type="checkbox"]):not([type="radio"])),
  .editor :global(select) {
    box-sizing: border-box;
    min-width: 0;
    max-width: 100%;
  }
  .name input {
    width: 100%;
  }
  .name {
    display: flex;
    flex-direction: column;
    gap: 6px;
    color: var(--text-muted);
    font-size: 0.88rem;
  }
  .match {
    color: var(--text-muted);
  }
  .match select {
    margin: 0 4px;
  }
  .cond {
    display: grid;
    grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.9fr) minmax(0, 1.4fr) 36px;
    gap: 8px;
    align-items: center;
  }
  .value {
    display: flex;
    gap: 6px;
    align-items: center;
    min-width: 0;
  }
  .value input:not([type="range"]),
  .value select {
    min-width: 0;
    flex: 1;
  }
  .value input[type="range"] {
    flex: 1;
  }
  .pct {
    width: 3.2em;
    text-align: right;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
  }
  .small {
    align-self: flex-start;
    height: 34px;
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
  /* Narrow screens: field + operator side by side, the value on its own row below. */
  @media (max-width: 640px) {
    .cond {
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) 36px;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--line);
    }
    .value {
      grid-column: 1 / 3;
      grid-row: 2;
    }
    .row {
      flex-direction: column;
      gap: 8px;
    }
  }
</style>
