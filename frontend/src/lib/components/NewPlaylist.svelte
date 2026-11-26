<script lang="ts">
  // "New playlist": a name, and optionally "fill automatically": filters (genres, artists as a
  // template, tempo, year, ...) pick tracks; the list shows them before anything is saved, single
  // tracks can be removed (the next matching one takes their place), "Neu mischen" picks others.
  // The result is an ordinary playlist with these tracks, not a smart playlist; the filters are
  // kept with it (fill_rule).
  // With `playlist` it edits one (the pencil on the playlist page): the name, and the filters it
  // was filled with. Its tracks stay until the filters change or "Andere Auswahl" picks anew;
  // saving then replaces all of them.
  import { untrack } from "svelte";
  import { ApiError, coverUrl, patch, post, type Playlist, type Rule, type Track } from "../api";
  import { duration, longDuration, plural } from "../format";
  import { createPlaylist } from "../mine.svelte";
  import Icon from "./Icon.svelte";
  import Modal from "./Modal.svelte";
  import RuleFilters, { emptyFilters, filterConditions, parseRule, type FilterValues } from "./RuleFilters.svelte";
  import { locale, t } from "../i18n.svelte";

  let { playlist = null, ondone }: { playlist?: Playlist | null; ondone: (playlist: Playlist | null) => void } = $props();

  const MAX_TRACKS = 1000;

  // The dialog starts from the props once and then owns its state.
  const start = untrack(() => {
    const rule = playlist?.fill_rule ?? null;
    const { kept: _, ...form } = parseRule(rule);
    return { name: playlist?.name ?? "", rule, form, count: rule?.limit ?? 50 };
  });
  const editing = untrack(() => playlist !== null);

  let name = $state(start.name);
  let auto = $state(start.rule !== null);
  let filters = $state<FilterValues>(start.form);
  let count = $state<number | null>(start.count);
  let seed = $state(1);
  /** Removed by hand; the server leaves them out and fills up with the next ones. */
  let removed = $state<number[]>([]);
  let preview = $state<{ count: number; tracks: Track[]; needs_analysis: boolean } | null>(null);
  let loading = $state(false);
  let error = $state<string | null>(null);
  let saving = $state(false);

  const conditions = $derived(filterConditions(filters));
  const wanted = $derived(Math.min(MAX_TRACKS, Math.max(1, Math.round(Number(count) || 50))));
  const fillRule = $derived<Rule>({ match: "all", conditions, limit: wanted, order: "random" });
  // Editing: the playlist keeps its tracks until the filters or the number change, or
  // "Andere Auswahl" asks for others; only then is there a new selection to save.
  const startKey = untrack(() => JSON.stringify([filterConditions(start.form), start.count]));
  const refill = $derived(
    auto && conditions.length > 0 && (!editing || seed !== 1 || JSON.stringify([conditions, wanted]) !== startKey),
  );
  const list = $derived(refill && preview ? preview.tracks.filter((tr) => !removed.includes(tr.id)) : []);
  const total = $derived(list.reduce((sum, tr) => sum + tr.duration_ms, 0));

  // Live preview, debounced: the server validates the rule and picks the tracks.
  let timer: ReturnType<typeof setTimeout> | undefined;
  let request = 0;
  $effect(() => {
    const body = {
      rule: JSON.parse(JSON.stringify(fillRule)),
      tracks: wanted,
      seed,
      exclude: removed.slice(-MAX_TRACKS),
    };
    clearTimeout(timer);
    if (!refill) {
      preview = null;
      error = null;
      loading = false;
      return;
    }
    loading = true;
    const mine = ++request;
    timer = setTimeout(async () => {
      try {
        const out = await post<typeof preview>("/rules/preview", body);
        if (mine !== request) return;
        preview = out;
        error = null;
      } catch (e) {
        if (mine !== request) return;
        preview = null;
        error = e instanceof ApiError ? e.message : t("Fehler");
      } finally {
        if (mine === request) loading = false;
      }
    }, 350);
    return () => clearTimeout(timer);
  });

  function remove(id: number) {
    removed = [...removed, id];
  }

  function reshuffle() {
    removed = [];
    seed = (seed % 1_000_000) + 1 + Math.floor(Math.random() * 1000);
  }

  async function create(e: Event) {
    e.preventDefault();
    if (!name.trim() || saving) return;
    saving = true;
    const ids = list.map((tr) => tr.id);
    const rule = refill && ids.length ? JSON.parse(JSON.stringify(fillRule)) : undefined;
    try {
      if (playlist) {
        const changes: Record<string, unknown> = {};
        if (name.trim() !== playlist.name) changes.name = name.trim();
        if (rule) Object.assign(changes, { fill_rule: rule, track_ids: ids });
        ondone(Object.keys(changes).length ? await patch<Playlist>(`/playlists/${playlist.id}`, changes) : playlist);
      } else {
        ondone(await createPlaylist(name.trim(), ids, rule));
      }
    } catch (err) {
      error = err instanceof ApiError ? err.message : t("Speichern fehlgeschlagen");
      saving = false;
    }
  }
</script>

<Modal title={editing ? t("Playlist bearbeiten") : t("Neue Playlist")} width={auto ? 680 : 440} onclose={() => ondone(null)}>
  <form class="new" onsubmit={create}>
    <!-- svelte-ignore a11y_autofocus -->
    <input class="full" bind:value={name} autofocus maxlength="200" aria-label={t("Name")} placeholder={t("Name der Playlist")} />

    {#if !auto}
      <button type="button" class="btn ghost auto-btn" onclick={() => (auto = true)}>
        <Icon name="spark" size={16} /> {t("Automatisch füllen")}
      </button>
    {:else}
      <div class="auto">
        <div class="auto-head">
          <strong>{t("Automatisch füllen")}</strong>
          <button type="button" class="icon-btn" aria-label={t("Nicht automatisch füllen")} onclick={() => (auto = false)}>
            <Icon name="close" size={16} />
          </button>
        </div>
        <RuleFilters bind:values={filters} />
        <label class="count">
          {t("Anzahl")}
          <input type="number" min="1" max={MAX_TRACKS} bind:value={count} />
          {t("Titel|Anzahl")}
        </label>
        <p class="hint">{t("✦ = aus der Audioanalyse.")}</p>

        <div class="preview" role="status" aria-busy={loading}>
          {#if !conditions.length}
            <p class="muted">{t("Wähle ein Genre oder einen Künstler, oder grenze Tempo, Jahr oder Hinzugefügt ein.")}</p>
          {:else if error}
            <p class="err">{error}</p>
          {:else if !refill}
            <!-- Editing, nothing changed yet: the playlist keeps its tracks. -->
            <div class="preview-head">
              <span class="muted">{t("Die Playlist behält ihre {n}. Ändere die Filter oder wähle andere, um sie neu zu füllen.", { n: plural(playlist?.item_count ?? 0, "Titel", "Titel") })}</span>
              <button type="button" class="btn ghost small" onclick={reshuffle}>
                <Icon name="shuffle" size={15} /> {t("Andere Auswahl")}
              </button>
            </div>
          {:else if preview}
            <div class="preview-head">
              <span>
                <strong>{plural(list.length, "Titel", "Titel")}</strong>{list.length ? ` · ${longDuration(total)}` : ""}
                {#if preview.count === 0 && preview.needs_analysis}
                  <span class="muted">{t("– das Tempo braucht die Audioanalyse; ist sie fertig?")}</span>
                {:else if list.length < wanted}
                  <span class="muted">{t("– mehr passen nicht")}</span>
                {/if}
              </span>
              <span class="head-actions">
                {#if removed.length}
                  <button type="button" class="link" onclick={() => (removed = [])}>
                    {t("{n} entfernte zurückholen", { n: removed.length.toLocaleString(locale()) })}
                  </button>
                {/if}
                <button type="button" class="btn ghost small" onclick={reshuffle} disabled={loading}>
                  <Icon name="shuffle" size={15} /> {t("Andere Auswahl")}
                </button>
              </span>
            </div>
            {#if list.length}
              <ul class="tracks" class:stale={loading}>
                {#each list as track (track.id)}
                  {@const cover = coverUrl(track.cover, 64)}
                  <li>
                    {#if cover}<img src={cover} alt="" loading="lazy" />{:else}<span class="nocover"><Icon name="track" size={16} /></span>{/if}
                    <span class="what">
                      <span class="title">{track.title}</span>
                      <small>{track.artist}{track.year ? ` · ${track.year}` : ""}</small>
                    </span>
                    <span class="time">{duration(track.duration_ms)}</span>
                    <button type="button" class="icon-btn" aria-label={t("{name} entfernen", { name: track.title })} onclick={() => remove(track.id)}>
                      <Icon name="close" size={16} />
                    </button>
                  </li>
                {/each}
              </ul>
            {/if}
          {:else}
            <p class="muted">…</p>
          {/if}
        </div>
      </div>
    {/if}

    {#if error && !auto}<p class="err">{error}</p>{/if}

    <div class="buttons">
      <button type="button" class="btn ghost" onclick={() => ondone(null)}>{t("Abbrechen")}</button>
      <button class="btn primary" disabled={!name.trim() || saving || (refill && (loading || !list.length))}>
        {#if editing}
          {refill ? t("Neu füllen mit {n}", { n: plural(list.length, "Titel", "Titel") }) : t("Speichern")}
        {:else}
          {auto && list.length ? t("Erstellen mit {n}", { n: plural(list.length, "Titel", "Titel") }) : t("Erstellen")}
        {/if}
      </button>
    </div>
  </form>
</Modal>

<style>
  .new {
    display: flex;
    flex-direction: column;
    gap: 14px;
    min-width: 0;
  }
  .full {
    width: 100%;
    box-sizing: border-box;
  }
  .auto-btn {
    align-self: flex-start;
    display: inline-flex;
    gap: 6px;
    align-items: center;
  }
  .auto {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding-top: 12px;
    border-top: 1px solid var(--surface-2);
  }
  .auto-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .count {
    display: flex;
    gap: 8px;
    align-items: center;
    color: var(--text-muted);
  }
  .count input {
    width: 90px;
  }
  .hint {
    margin: 0;
    color: var(--text-faint);
    font-size: 0.8rem;
  }
  .preview {
    background: var(--surface-1);
    border-radius: var(--radius-sm);
    padding: 10px 12px;
    min-height: 44px;
  }
  .preview p {
    margin: 0;
  }
  .preview-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px 12px;
    flex-wrap: wrap;
  }
  .head-actions {
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
  }
  .small {
    display: inline-flex;
    gap: 6px;
    align-items: center;
    padding: 4px 10px;
    font-size: 0.85rem;
  }
  .link {
    background: none;
    border: 0;
    padding: 0;
    color: var(--accent);
    cursor: pointer;
    font: inherit;
    font-size: 0.85rem;
  }
  .tracks {
    list-style: none;
    margin: 8px 0 0;
    padding: 0;
    max-height: min(40vh, 360px);
    overflow-y: auto;
    transition: opacity 0.15s;
  }
  .tracks.stale {
    opacity: 0.6;
  }
  .tracks li {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 4px 0;
  }
  .tracks img,
  .nocover {
    width: 36px;
    height: 36px;
    flex: none;
    border-radius: 4px;
    object-fit: cover;
    background: var(--surface-2);
    display: grid;
    place-items: center;
    color: var(--text-faint);
  }
  .what {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .what > * {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  small,
  .muted,
  .time {
    color: var(--text-muted);
  }
  .time {
    font-size: 0.85rem;
    font-variant-numeric: tabular-nums;
  }
  .err {
    margin: 0;
    color: var(--danger);
  }
  .buttons {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
  }
</style>
