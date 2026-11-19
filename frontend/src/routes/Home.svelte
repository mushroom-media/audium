<script lang="ts">
  import { get, type Album, type Page, type RecentItem } from "../lib/api";
  import AlbumCard from "../lib/components/AlbumCard.svelte";
  import PlaylistCover from "../lib/components/PlaylistCover.svelte";
  import RecentCard from "../lib/components/RecentCard.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import { plural } from "../lib/format";
  import { mine, newPlaylistFlow } from "../lib/mine.svelte";
  import { keepScroll } from "../lib/keepScroll";
  import { href, navigate, recallEntry, rememberEntry } from "../lib/router.svelte";
  import { ui } from "../lib/ui.svelte";
  import { session } from "../lib/session.svelte";
  import { t } from "../lib/i18n.svelte";

  let recent = $state<Album[] | null>(recallEntry("home:recent") ?? null);
  let played = $state<RecentItem[]>(recallEntry("home:played") ?? []);
  // Stations that fit what was played lately (artists, an album, favourite tracks)
  let radios = $state<RecentItem[]>(recallEntry("home:radios") ?? []);

  $effect(() => {
    const ctrl = new AbortController();
    get<RecentItem[]>("/radio/suggestions", { limit: 6 }, ctrl.signal)
      .then((r) => {
        radios = r;
        rememberEntry("home:radios", r);
      })
      .catch(() => {});
    get<Page<Album>>("/albums", { sort: "added", limit: 12 }, ctrl.signal)
      .then((p) => {
        recent = p.items;
        rememberEntry("home:recent", p.items);
      })
      .catch(() => {});
    get<RecentItem[]>("/history/recent", { limit: 6 }, ctrl.signal)
      .then((r) => {
        played = r;
        rememberEntry("home:played", r);
      })
      .catch(() => {});
    return () => ctrl.abort();
  });

  async function newPlaylist() {
    const pl = await newPlaylistFlow();
    if (pl) navigate(`/playlists/${pl.id}`);
  }

  const greeting = $derived.by(() => {
    const h = new Date().getHours();
    return h < 11 ? "Guten Morgen" : h < 18 ? "Hallo" : "Guten Abend";
  });
</script>

<div class="page" use:keepScroll>
  <div class="toolbar"><h1>{greeting}, {session.user?.display_name}</h1></div>

  {#if played.length}
    <div class="section-head"><h2>{t("Zuletzt gehört")}</h2></div>
    <div class="grid played">
      {#each played as item (`${item.type}:${item.radio_of}:${item.id}`)}<RecentCard {item} compact />{/each}
    </div>
  {/if}

  {#if radios.length}
    <div class="section-head"><h2>{t("Radios für dich")}</h2></div>
    <div class="grid">
      {#each radios as item (`${item.radio_of}:${item.id}`)}<RecentCard {item} />{/each}
    </div>
  {/if}

  <div class="section-head">
    <h2>{t("Playlists")}</h2>
    <span class="head-actions">
      <button class="btn ghost small" onclick={() => (ui.smartEditor = true)}><Icon name="spark" size={16} /> {t("Smart")}</button>
      <button class="btn small" onclick={newPlaylist}><Icon name="plus" size={16} /> {t("Neu")}</button>
    </span>
  </div>
  <div class="lists">
    <a class="list" href={href("/favorites")}>
      <span class="art fav" aria-hidden="true"><Icon name="heart" size={22} filled /></span>
      <span class="meta"><strong>{t("Lieblingssongs")}</strong><small>{plural(mine.favoriteTracks.size, "Titel", "Titel")}</small></span>
    </a>
    {#each mine.playlists.slice(0, 11) as p (p.id)}
      <a class="list" href={href(`/playlists/${p.id}`)}>
        <span class="art"><PlaylistCover playlist={p} size={64} /></span>
        <span class="meta">
          <strong>{p.name}</strong>
          <small>{p.role === "owner" ? plural(p.item_count, "Titel", "Titel") : t("von {name}", { name: p.owner.display_name })}</small>
        </span>
      </a>
    {/each}
  </div>

  <div class="section-head">
    <h2>{t("Neu hinzugefügt")}</h2>
    <a href={href("/library?tab=albums&sort=added")}>{t("Alle Alben")}</a>
  </div>
  {#if recent && recent.length === 0}
    <p class="empty">
      {session.user?.role === "admin"
        ? t("Deine Bibliothek ist noch leer. Der erste Scan läuft im Hintergrund – den Fortschritt siehst du in den Einstellungen.")
        : t("Deine Bibliothek ist noch leer. Der erste Scan läuft im Hintergrund.")}
    </p>
  {:else}
    <div class="grid">
      {#each recent ?? Array(12).fill(undefined) as album, i (album?.id ?? `p${i}`)}<AlbumCard {album} />{/each}
    </div>
  {/if}
</div>

<style>
  .section-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin: 12px 24px 14px;
  }
  h2 {
    font-size: 1.1rem;
    margin: 0;
  }
  .section-head a {
    color: var(--text-muted);
    font-size: 0.88rem;
    text-decoration: none;
  }
  .head-actions {
    display: flex;
    gap: 8px;
  }
  .small {
    height: 32px;
    padding: 0 12px;
    font-size: 0.85rem;
  }
  .section-head a:hover {
    color: var(--text);
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
    gap: 20px;
    padding: 0 24px 24px;
  }
  .lists {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 10px;
    padding: 0 24px 24px;
  }
  .list {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px;
    border-radius: var(--radius-sm);
    background: var(--surface-1);
    color: inherit;
    text-decoration: none;
    min-width: 0;
  }
  .list:hover {
    background: var(--surface-2);
  }
  .art {
    width: 48px;
    flex: none;
  }
  .art.fav {
    height: 48px;
    border-radius: 6px;
    display: grid;
    place-items: center;
    background: var(--accent);
    color: var(--accent-contrast);
  }
  .meta {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .meta strong,
  .meta small {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .meta strong {
    font-weight: 550;
  }
  .meta small {
    color: var(--text-muted);
  }
  @media (max-width: 560px) {
    .grid {
      grid-template-columns: repeat(2, 1fr);
      gap: 14px;
      padding: 0 16px 20px;
    }
    .lists,
    .grid.played {
      grid-template-columns: 1fr 1fr;
      padding: 0 16px 20px;
      gap: 8px;
    }
    .section-head {
      margin: 8px 16px 10px;
    }
  }
</style>
