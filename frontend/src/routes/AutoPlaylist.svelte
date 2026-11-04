<script lang="ts">
  import { untrack } from "svelte";
  import { ApiError, del, get, patch, post, type AutoItem, type AutoPlaylist, type Playlist, type Rule,
    type UserRef } from "../lib/api";
  import Cover from "../lib/components/Cover.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import { pageTitle } from "../lib/headerTitle.svelte";
  import PlayToggle from "../lib/components/PlayToggle.svelte";
  import Modal from "../lib/components/Modal.svelte";
  import RuleEditor from "../lib/components/RuleEditor.svelte";
  import TrackRow from "../lib/components/TrackRow.svelte";
  import VirtualList from "../lib/components/VirtualList.svelte";
  import { longDuration, plural } from "../lib/format";
  import { ORIGINS, originText } from "../lib/origin";
  import { loadPlaylists } from "../lib/mine.svelte";
  import { player } from "../lib/player.svelte";
  import { navigate, recallEntry, rememberEntry } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";
  import { promptText, toast } from "../lib/ui.svelte";
  import { msg, t } from "../lib/i18n.svelte";

  let { id }: { id: string } = $props();
  const kept = untrack(() => recallEntry<{ auto: AutoPlaylist; items: AutoItem[] }>(`auto:${id}`));
  let auto = $state<AutoPlaylist | null>(kept?.auto ?? null);
  let items = $state<AutoItem[]>(kept?.items ?? []);
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
        rememberEntry(`auto:${id}`, { auto: a, items: page.items });
      })
      .catch((e) => {
        if (e.name !== "AbortError") error = e instanceof ApiError && e.status === 404 ? t("Diese Playlist ist nicht (mehr) verfügbar.") : String(e);
      });
    return () => ctrl.abort();
  });

  function play(index: number | null = 0, shuffle = false) {
    if (items.length) player.playTracks(items.map((i) => i.track), index, shuffle, auto && { kind: "Playlist", name: auto.name, path: `/discover/${id}`, ref: `auto:${id}` });
  }

  async function freeze() {
    const name = await promptText(t("Als eigene Playlist speichern"), auto?.name ?? "", t("Speichern"));
    if (!name) return;
    const pl = await post<Playlist>(`/autoplaylists/${id}/freeze`, { name });
    await loadPlaylists();
    toast(t("Gespeichert – du kannst sie jetzt bearbeiten und teilen"));
    navigate(`/playlists/${pl.id}`);
  }

  async function admin(changes: Record<string, unknown>, done?: string) {
    try {
      await patch(`/admin/autoplaylists/${id}`, changes);
      if (done) toast(done);
      reload++;
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("Fehlgeschlagen"));
    }
  }

  async function rename() {
    const name = await promptText(t("Umbenennen"), auto?.name ?? "", t("Speichern"));
    if (name) admin({ name });
  }

  async function remove() {
    const custom = auto?.generator === "custom";
    if (!confirm(custom ? t("Diese Regel-Playlist löschen?") : t("Ausblenden? Sie wird dann nicht mehr erzeugt."))) return;
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

  const STATUS: Record<string, string> = { suggested: msg("Vorschlag"), published: msg("Veröffentlicht"), dismissed: msg("Ausgeblendet") };
  const ACCESS: Record<string, string> = { all: msg("Alle Nutzer"), restricted: msg("Ausgewählte Nutzer"), admin_only: msg("Nur Admin") };
</script>

{#if error}
  <div class="page"><p class="empty">{error}</p></div>
{:else if auto}
  <VirtualList count={items.length} rowHeight={56} label={t("Titel")} keep="auto:{id}">
    {#snippet header()}
      <header class="hero">
        <div class="art"><Cover hash={auto!.cover} size={256} /></div>
        <div class="info">
          <p class="kind">
            <Icon name={ORIGINS[auto!.origin].icon} size={13} /> {t("Automatische Playlist")} · {t(ORIGINS[auto!.origin].label)}
            {#if isAdmin && auto!.status}· {t(STATUS[auto!.status])} · {t(ACCESS[auto!.access ?? "all"])}{/if}
          </p>
          <h1 use:pageTitle={auto!.name}>{auto!.name}</h1>
          {#if auto!.description}<p class="desc">{auto!.description}</p>{/if}
          <p class="origin">{originText(auto!)}</p>
          <p class="by">{plural(auto!.track_count, "Titel", "Titel")}{#if auto!.duration_ms}, {longDuration(auto!.duration_ms)}{/if}</p>
          <div class="actions">
            <PlayToggle ref="auto:{id}" disabled={!items.length} start={() => play(0)} />
            <button class="btn square" disabled={!items.length} onclick={() => play(null, true)} title={t("Zufällig abspielen")} aria-label={t("Zufällig abspielen")}><Icon name="shuffle" size={18} /></button>
            <button class="btn ghost" disabled={!items.length} onclick={freeze}><Icon name="plus" size={18} /> {t("Als Playlist speichern")}</button>
          </div>
          {#if isAdmin}
            <div class="actions admin">
              {#if auto!.status === "published"}
                <button class="btn small" onclick={() => admin({ status: "suggested" }, t("Zurückgezogen"))}>{t("Zurückziehen")}</button>
              {:else}
                <button class="btn primary small" onclick={() => admin({ status: "published" }, t("Veröffentlicht"))}>{t("Veröffentlichen")}</button>
              {/if}
              <button class="btn small ghost" onclick={openAccess}>{t("Zugriff")}</button>
              <button class="btn small ghost" onclick={rename}>{t("Umbenennen")}</button>
              {#if auto!.generator === "custom"}<button class="btn small ghost" onclick={() => (editingRule = true)}>{t("Regel bearbeiten")}</button>{/if}
              <button class="btn small ghost" onclick={remove}>{auto!.generator === "custom" ? t("Löschen") : t("Ausblenden")}</button>
            </div>
          {/if}
        </div>
      </header>
      {#if !items.length}<p class="empty">{t("Gerade passt kein Titel.")}</p>{/if}
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
  <Modal title={t("Wer sieht „{name}“?", { name: auto.name })} onclose={() => (accessOpen = false)}>
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
            <p class="empty">{t("Keine anderen Nutzer.")}</p>
          {/each}
        </div>
      {/if}
      <p class="note">{t("Sichtbar ist sie nur, solange sie veröffentlicht ist.")}</p>
      <div class="buttons"><button class="btn primary" onclick={() => (accessOpen = false)}>{t("Fertig")}</button></div>
    </div>
  </Modal>
{/if}

{#if editingRule && auto?.rule}
  <RuleEditor title={t("Regel bearbeiten")} initial={auto.rule} askName={false} onsave={saveRule} onclose={() => (editingRule = false)} />
{/if}

<style>
  .origin {
    margin: 4px 0 0;
    color: var(--text-muted);
    font-size: 0.82rem;
  }
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
