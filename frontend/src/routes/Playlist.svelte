<script lang="ts">
  import { untrack } from "svelte";
  import { ApiError, del, get, patch, post, type Page, type Playlist, type PlaylistItem, type Rule } from "../lib/api";
  import RuleEditor from "../lib/components/RuleEditor.svelte";
  import CoverPicker from "../lib/components/CoverPicker.svelte";
  import PlaylistCover from "../lib/components/PlaylistCover.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import { pageTitle } from "../lib/headerTitle.svelte";
  import PlayToggle from "../lib/components/PlayToggle.svelte";
  import TrackRow from "../lib/components/TrackRow.svelte";
  import VirtualList from "../lib/components/VirtualList.svelte";
  import { longDuration, plural } from "../lib/format";
  import { loadPlaylists, mine } from "../lib/mine.svelte";
  import { keptList } from "../lib/paged.svelte";
  import { player } from "../lib/player.svelte";
  import { navigate, recallEntry, rememberEntry } from "../lib/router.svelte";
  import { promptText, toast, ui } from "../lib/ui.svelte";

  let { id }: { id: string } = $props();
  const pid = $derived(Number(id));
  const PLAY_LIMIT = 2000;

  let meta = $state<Playlist | null>(untrack(() => recallEntry<Playlist>(`playlist:${id}`)) ?? null);
  let error = $state<string | null>(null);
  let loadedVersion = $state(0);
  let reloads = $state(0);
  let dragFrom = $state<number | null>(null);
  let dropAt = $state<{ index: number; below: boolean } | null>(null);

  const list = $derived.by(() => {
    void reloads;
    return keptList<PlaylistItem>(
      `playlist:${pid}:items`,
      (offset, limit, signal) =>
        get<{ items: PlaylistItem[]; total: number; version: number }>(
          `/playlists/${pid}/items`,
          { offset, limit },
          signal,
        ).then((r): Page<PlaylistItem> => ({ items: r.items, total: r.total, next_cursor: null })),
      200,
    );
  });

  async function loadMeta() {
    try {
      meta = await get<Playlist>(`/playlists/${pid}`);
      rememberEntry(`playlist:${id}`, meta);
      loadedVersion = meta.version;
      error = null;
    } catch (e) {
      meta = null;
      error = e instanceof ApiError && e.status === 404 ? "Diese Playlist gibt es nicht (mehr) oder sie ist nicht für dich freigegeben." : String(e);
    }
  }

  function reload() {
    reloads++;
    loadMeta();
  }

  $effect(() => {
    void pid;
    loadMeta();
  });

  // Live updates: someone else (or this user in another tab) changed the playlist.
  // Only the announcement is tracked; reload() itself must not become a dependency.
  let seenResync = mine.resync;
  $effect(() => {
    const announced = mine.changed[pid] ?? 0;
    const resync = mine.resync;
    if (!loadedVersion) return; // first load still running
    if (announced > loadedVersion || resync !== seenResync) {
      seenResync = resync;
      untrack(reload);
    }
  });

  const isSmart = $derived(meta?.kind === "smart");
  // Smart playlists fill themselves from their rule: no manual add/remove/reorder.
  const canEdit = $derived((meta?.role === "owner" || meta?.role === "editor") && !isSmart);
  let editingRule = $state(false);
  let pickingCover = $state(false);

  async function saveRule(_name: string, rule: Rule) {
    await patch(`/playlists/${pid}`, { rule });
    editingRule = false;
    reload();
    loadPlaylists();
  }
  const isOwner = $derived(meta?.role === "owner");

  /** `index` null: no particular track first (with `shuffle`, a random one). */
  async function play(index: number | null = 0, shuffle = false) {
    const items = await list.slice(0, Math.min(list.total ?? PLAY_LIMIT, PLAY_LIMIT));
    const playable = items.filter((i) => i.available);
    if (!playable.length) return;
    const start = index === null ? null : Math.max(0, playable.findIndex((i) => i.item_id === items[index]?.item_id));
    player.playTracks(
      playable.map((i) => i.track),
      start,
      shuffle,
      meta && { kind: "Playlist", name: meta.name, path: `/playlists/${pid}`, ref: `playlist:${pid}` },
    );
  }

  async function act(fn: () => Promise<unknown>, done?: string) {
    try {
      await fn();
      if (done) toast(done);
      reload();
      loadPlaylists();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Fehlgeschlagen");
    }
  }

  async function rename() {
    const name = await promptText("Playlist umbenennen", meta?.name ?? "", "Speichern");
    if (name) act(() => patch(`/playlists/${pid}`, { name }));
  }

  async function describe() {
    const description = await promptText("Beschreibung", meta?.description ?? "", "Speichern");
    if (description !== null) act(() => patch(`/playlists/${pid}`, { description }));
  }

  async function remove() {
    if (!confirm(`„${meta?.name}“ wirklich löschen? Das kann nicht rückgängig gemacht werden.`)) return;
    try {
      await del(`/playlists/${pid}`);
      await loadPlaylists();
      navigate("/", { replace: true });
      toast("Playlist gelöscht");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Fehlgeschlagen");
    }
  }

  async function leave() {
    await post(`/playlists/${pid}/leave`);
    await loadPlaylists();
    navigate("/", { replace: true });
  }

  const removeItem = (item: PlaylistItem) =>
    act(() => post(`/playlists/${pid}/items/remove`, { item_ids: [item.item_id] }), "Entfernt");

  // --- drag & drop reordering (editors) -------------------------------------------------------

  function onDragStart(e: DragEvent, index: number) {
    if (!canEdit) return;
    dragFrom = index;
    e.dataTransfer!.effectAllowed = "move";
    e.dataTransfer!.setData("text/plain", String(index));
  }

  function onDragOver(e: DragEvent, index: number) {
    if (dragFrom === null) return;
    e.preventDefault();
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    dropAt = { index, below: e.clientY > r.top + r.height / 2 };
  }

  async function onDrop(e: DragEvent) {
    e.preventDefault();
    const from = dragFrom;
    const at = dropAt;
    dragFrom = null;
    dropAt = null;
    if (from === null || !at) return;
    const moving = list.get(from);
    // Target slot: behind the row we dropped below, or behind the one before the row we dropped above.
    let afterIndex = at.below ? at.index : at.index - 1;
    if (afterIndex === from) return; // dropped onto itself
    let after = afterIndex >= 0 ? list.get(afterIndex) : null;
    if (after?.item_id === moving?.item_id) after = afterIndex - 1 >= 0 ? list.get(afterIndex - 1) : null;
    if (!moving) return;
    if (!at.below && at.index === from + 1) return; // already there
    act(() => post(`/playlists/${pid}/items/${moving.item_id}/move`, { after_item_id: after?.item_id ?? null }));
  }
</script>

{#if error}
  <div class="page"><p class="empty">{error}</p></div>
{:else if meta}
  <VirtualList count={list.total ?? 0} rowHeight={56} onrange={(s, e) => list.ensure(s, e)} label="Titel der Playlist" keep="playlist:{id}">
    {#snippet header()}
      <header class="hero">
        {#if isOwner}
          <button class="art edit" onclick={() => (pickingCover = true)} aria-label="Cover ändern" title="Cover ändern">
            <PlaylistCover playlist={meta!} />
            <span class="edit-badge" aria-hidden="true"><Icon name="image" size={18} /></span>
          </button>
        {:else}
          <div class="art"><PlaylistCover playlist={meta!} /></div>
        {/if}
        <div class="info">
          <p class="kind">
            {isSmart ? "Smart-Playlist" : "Playlist"}{#if meta!.visibility === "users"} · für alle sichtbar{/if}{#if meta!.role !== "owner"} · von {meta!.owner.display_name}{/if}
          </p>
          <h1 use:pageTitle={meta!.name}>{meta!.name}</h1>
          {#if meta!.description}<p class="desc">{meta!.description}</p>{/if}
          <p class="by">
            {plural(meta!.item_count, "Titel", "Titel")}{#if meta!.duration_ms}, {longDuration(meta!.duration_ms)}{/if}
            {#if meta!.role === "editor"} · du kannst bearbeiten{:else if meta!.role === "viewer"} · nur ansehen{/if}
          </p>
          <div class="actions">
            <PlayToggle ref="playlist:{pid}" disabled={!meta!.item_count} start={() => play(0, false)} />
            <button class="btn square" disabled={!meta!.item_count} onclick={() => play(null, true)} title="Zufällig abspielen" aria-label="Zufällig abspielen"><Icon name="shuffle" size={18} /></button>
            {#if isOwner}
              <button class="btn ghost" onclick={() => (ui.share = { playlistId: pid })}><Icon name="share" size={18} /> Teilen</button>
              {#if isSmart}<button class="btn ghost" onclick={() => (editingRule = true)}><Icon name="spark" size={18} /> Regel</button>{/if}
              <button class="icon-btn" title="Umbenennen" aria-label="Umbenennen" onclick={rename}><Icon name="edit" size={18} /></button>
              <button class="icon-btn" title="Beschreibung" aria-label="Beschreibung bearbeiten" onclick={describe}><Icon name="list" size={18} /></button>
              <button class="icon-btn" title="Löschen" aria-label="Playlist löschen" onclick={remove}><Icon name="trash" size={18} /></button>
            {:else if meta!.role !== "viewer" || meta!.visibility !== "users"}
              <button class="btn ghost" onclick={leave}>Aus meiner Liste entfernen</button>
            {/if}
          </div>
        </div>
      </header>
      {#if meta!.item_count === 0}
        <p class="empty">
          Noch leer. Füge Titel über das <Icon name="more" size={14} />-Menü bei einem Titel oder Album hinzu.
        </p>
      {/if}
    {/snippet}
    {#snippet row(i)}
      {@const item = list.get(i)}
      <div
        class="pad"
        class:drop-above={dropAt?.index === i && !dropAt.below}
        class:drop-below={dropAt?.index === i && dropAt.below}
        class:dragging={dragFrom === i}
        draggable={canEdit && !!item}
        ondragstart={(e) => onDragStart(e, i)}
        ondragover={(e) => onDragOver(e, i)}
        ondragleave={() => dropAt?.index === i && (dropAt = null)}
        ondrop={onDrop}
        ondragend={() => ((dragFrom = null), (dropAt = null))}
        role="presentation"
      >
        {#if canEdit && item}<span class="grip" aria-hidden="true"><Icon name="drag" size={16} /></span>{/if}
        <div class="track">
          <TrackRow
            track={item?.track}
            number={i + 1}
            unavailable={item ? !item.available : false}
            onplay={() => play(i)}
            onremove={canEdit && item ? () => removeItem(item) : undefined}
          />
        </div>
      </div>
    {/snippet}
  </VirtualList>
{:else}
  <div class="page"></div>
{/if}

{#if pickingCover && meta}
  <CoverPicker
    playlist={meta}
    onchange={(p) => {
      meta = p;
      loadedVersion = p.version;
      loadPlaylists();
    }}
    onclose={() => (pickingCover = false)}
  />
{/if}

{#if editingRule && meta?.rule}
  <RuleEditor title="Regel von „{meta.name}“" initial={meta.rule as Rule} askName={false} onsave={saveRule} onclose={() => (editingRule = false)} />
{/if}

<style>
  .hero {
    display: flex;
    gap: 28px;
    align-items: flex-end;
    padding: 32px 24px 20px;
  }
  .art {
    width: min(220px, 36vw);
    flex: none;
    box-shadow: 0 18px 44px rgb(0 0 0 / 0.3);
    border-radius: var(--radius-sm);
  }
  .art.edit {
    position: relative;
    padding: 0;
    border: 0;
    background: none;
    cursor: pointer;
  }
  .edit-badge {
    position: absolute;
    right: 8px;
    bottom: 8px;
    width: 34px;
    height: 34px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: rgb(0 0 0 / 0.6);
    color: #fff;
    opacity: 0;
    transition: opacity 0.15s;
  }
  .art.edit:hover .edit-badge,
  .art.edit:focus-visible .edit-badge {
    opacity: 1;
  }
  @media (hover: none) {
    .edit-badge {
      opacity: 1;
    }
  }
  .info {
    min-width: 0;
  }
  .kind {
    margin: 0;
    color: var(--text-muted);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }
  h1 {
    font-size: clamp(1.6rem, 4vw, 2.8rem);
    line-height: 1.1;
    margin: 6px 0 8px;
    letter-spacing: -0.02em;
    word-break: break-word;
  }
  .desc {
    margin: 0 0 8px;
    color: var(--text-muted);
  }
  .by {
    color: var(--text-muted);
    margin: 0 0 18px;
  }
  .actions {
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
  }
  .pad {
    position: relative;
    display: flex;
    align-items: center;
    height: 100%;
    padding: 0 16px 0 4px;
  }
  .grip {
    width: 16px;
    color: var(--text-faint);
    cursor: grab;
    opacity: 0;
  }
  .pad:hover .grip {
    opacity: 1;
  }
  .track {
    flex: 1;
    min-width: 0;
    height: 100%;
  }
  .dragging {
    opacity: 0.4;
  }
  .drop-above::before,
  .drop-below::after {
    content: "";
    position: absolute;
    left: 16px;
    right: 16px;
    height: 2px;
    background: var(--accent);
  }
  .drop-above::before {
    top: 0;
  }
  .drop-below::after {
    bottom: 0;
  }
  @media (max-width: 640px) {
    .hero {
      flex-direction: column;
      align-items: flex-start;
      padding: 20px 16px 12px;
    }
    .art {
      width: min(200px, 60vw);
    }
  }
</style>
