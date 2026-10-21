<script lang="ts">
  import { ApiError, del, get, patch, post, type AutoItem, type AutoPlaylist, type Playlist, type Rule,
    type UserRef } from "../lib/api";
  import Cover from "../lib/components/Cover.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import Modal from "../lib/components/Modal.svelte";
  import RuleEditor from "../lib/components/RuleEditor.svelte";
  import TrackRow from "../lib/components/TrackRow.svelte";
  import VirtualList from "../lib/components/VirtualList.svelte";
  import { longDuration, plural } from "../lib/format";
  import { loadPlaylists } from "../lib/mine.svelte";
  import { player } from "../lib/player.svelte";
  import { navigate } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";
  import { promptText, toast } from "../lib/ui.svelte";

  let { id }: { id: string } = $props();
  let auto = $state<AutoPlaylist | null>(null);
  let items = $state<AutoItem[]>([]);
  let error = $state<string | null>(null);
  let editingRule = $state(false);
  let accessOpen = $state(false);
  let people = $state<UserRef[]>([]);
  let reload = $state(0);
  const isAdmin = $derived(session.user?.role === "admin");

  $effect(() => {
    void reload;
    const ctrl = new AbortController();
    Promise.all([
      get<AutoPlaylist>(`/autoplaylists/${id}`, undefined, ctrl.signal),
      get<{ items: AutoItem[] }>(`/autoplaylists/${id}/items`, { limit: 1000 }, ctrl.signal),
    ])
      .then(([a, page]) => {
        auto = a;
        items = page.items;
        error = null;
      })
      .catch((e) => {
        if (e.name !== "AbortError") error = e instanceof ApiError && e.status === 404 ? "Diese Playlist ist nicht (mehr) verfügbar." : String(e);
      });
    return () => ctrl.abort();
  });

  function play(index = 0, shuffle = false) {
    if (!items.length) return;
    if (shuffle !== player.queue.shuffle) player.toggleShuffle();
    player.playTracks(items.map((i) => i.track), index);
  }

  async function freeze() {
    const name = await promptText("Als eigene Playlist speichern", auto?.name ?? "", "Speichern");
    if (!name) return;
    const pl = await post<Playlist>(`/autoplaylists/${id}/freeze`, { name });
    await loadPlaylists();
    toast("Gespeichert – du kannst sie jetzt bearbeiten und teilen");
    navigate(`/playlists/${pl.id}`);
  }

  async function admin(changes: Record<string, unknown>, done?: string) {
    try {
      await patch(`/admin/autoplaylists/${id}`, changes);
      if (done) toast(done);
      reload++;
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Fehlgeschlagen");
    }
  }

  async function rename() {
    const name = await promptText("Umbenennen", auto?.name ?? "", "Speichern");
    if (name) admin({ name });
  }

  async function remove() {
    const custom = auto?.generator === "custom";
    if (!confirm(custom ? "Diese Regel-Playlist löschen?" : "Ausblenden? Sie wird dann nicht mehr erzeugt.")) return;
    await del(`/admin/autoplaylists/${id}`);
    navigate("/discover", { replace: true });
  }

  async function openAccess() {
    people = await get<UserRef[]>("/users");
    accessOpen = true;
  }

  function toggleUser(userId: number, on: boolean) {
    const ids = new Set(auto?.user_ids ?? []);
    if (on) ids.add(userId);
    else ids.delete(userId);
    admin({ access: "restricted", user_ids: [...ids] });
  }

  async function saveRule(_name: string, rule: Rule) {
    await patch(`/admin/autoplaylists/${id}`, { rule });
    editingRule = false;
    reload++;
  }

  const STATUS: Record<string, string> = { suggested: "Vorschlag", published: "Veröffentlicht", dismissed: "Ausgeblendet" };
  const ACCESS: Record<string, string> = { all: "Alle Nutzer", restricted: "Ausgewählte Nutzer", admin_only: "Nur Admin" };
</script>

{#if error}
  <div class="page"><p class="empty">{error}</p></div>
{:else if auto}
  <VirtualList count={items.length} rowHeight={56} label="Titel">
    {#snippet header()}
      <header class="hero">
        <div class="art"><Cover hash={auto!.cover} size={256} /></div>
        <div class="info">
          <p class="kind">
            <Icon name="spark" size={13} /> Automatische Playlist
            {#if isAdmin && auto!.status}· {STATUS[auto!.status]} · {ACCESS[auto!.access ?? "all"]}{/if}
          </p>
          <h1>{auto!.name}</h1>
          {#if auto!.description}<p class="desc">{auto!.description}</p>{/if}
          <p class="by">{plural(auto!.track_count, "Titel", "Titel")}{#if auto!.duration_ms}, {longDuration(auto!.duration_ms)}{/if}</p>
          <div class="actions">
            <button class="btn primary" disabled={!items.length} onclick={() => play(0)}><Icon name="play" size={18} /> Abspielen</button>
            <button class="btn" disabled={!items.length} onclick={() => play(0, true)}><Icon name="shuffle" size={18} /> Zufällig</button>
            <button class="btn ghost" disabled={!items.length} onclick={freeze}><Icon name="plus" size={18} /> Als Playlist speichern</button>
          </div>
          {#if isAdmin}
            <div class="actions admin">
              {#if auto!.status === "published"}
                <button class="btn small" onclick={() => admin({ status: "suggested" }, "Zurückgezogen")}>Zurückziehen</button>
              {:else}
                <button class="btn primary small" onclick={() => admin({ status: "published" }, "Veröffentlicht")}>Veröffentlichen</button>
              {/if}
              <button class="btn small ghost" onclick={openAccess}>Zugriff</button>
              <button class="btn small ghost" onclick={rename}>Umbenennen</button>
              {#if auto!.generator === "custom"}<button class="btn small ghost" onclick={() => (editingRule = true)}>Regel bearbeiten</button>{/if}
              <button class="btn small ghost" onclick={remove}>{auto!.generator === "custom" ? "Löschen" : "Ausblenden"}</button>
            </div>
          {/if}
        </div>
      </header>
      {#if !items.length}<p class="empty">Gerade passt kein Titel.</p>{/if}
    {/snippet}
    {#snippet row(i)}
      <div class="pad">
        <TrackRow track={items[i].track} number={i + 1} note={items[i].reason} onplay={() => play(i)} />
      </div>
    {/snippet}
  </VirtualList>
{:else}
  <div class="page"></div>
{/if}

{#if accessOpen && auto}
  <Modal title="Wer sieht „{auto.name}“?" onclose={() => (accessOpen = false)}>
    <div class="access">
      {#each Object.entries(ACCESS) as [k, label] (k)}
        <label><input type="radio" name="access" checked={auto.access === k} onchange={() => admin({ access: k })} /> {label}</label>
      {/each}
      {#if auto.access === "restricted"}
        <div class="people">
          {#each people as u (u.id)}
            <label><input type="checkbox" checked={auto.user_ids?.includes(u.id)} onchange={(e) => toggleUser(u.id, e.currentTarget.checked)} />
              {u.display_name} <small>@{u.username}</small></label>
          {:else}
            <p class="empty">Keine anderen Nutzer.</p>
          {/each}
        </div>
      {/if}
      <p class="note">Sichtbar ist sie nur, solange sie veröffentlicht ist.</p>
      <div class="buttons"><button class="btn primary" onclick={() => (accessOpen = false)}>Fertig</button></div>
    </div>
  </Modal>
{/if}

{#if editingRule && auto?.rule}
  <RuleEditor title="Regel bearbeiten" initial={auto.rule} askName={false} onsave={saveRule} onclose={() => (editingRule = false)} />
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
  .info {
    min-width: 0;
  }
  .kind {
    margin: 0;
    color: var(--text-muted);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  h1 {
    font-size: clamp(1.6rem, 4vw, 2.8rem);
    line-height: 1.1;
    margin: 6px 0 8px;
    letter-spacing: -0.02em;
  }
  .desc,
  .by {
    color: var(--text-muted);
    margin: 0 0 10px;
  }
  .actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: 8px;
  }
  .admin {
    margin-top: 14px;
    padding-top: 12px;
    border-top: 1px dashed var(--surface-2);
  }
  .small {
    height: 34px;
    padding: 0 14px;
    font-size: 0.86rem;
  }
  .pad {
    height: 100%;
    padding: 0 16px;
  }
  .access {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .access label {
    display: flex;
    gap: 10px;
    align-items: center;
    cursor: pointer;
  }
  .people {
    padding-left: 26px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-height: 220px;
    overflow-y: auto;
  }
  small,
  .note {
    color: var(--text-muted);
    font-size: 0.85rem;
  }
  .buttons {
    display: flex;
    justify-content: flex-end;
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
