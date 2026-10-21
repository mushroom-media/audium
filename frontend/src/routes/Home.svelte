<script lang="ts">
  import { get, type Album, type Page } from "../lib/api";
  import AlbumCard from "../lib/components/AlbumCard.svelte";
  import Cover from "../lib/components/Cover.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import { plural } from "../lib/format";
  import { mine } from "../lib/mine.svelte";
  import { href } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";

  let recent = $state<Album[] | null>(null);
  let played = $state<Album[]>([]);

  $effect(() => {
    const ctrl = new AbortController();
    get<Page<Album>>("/albums", { sort: "added", limit: 12 }, ctrl.signal)
      .then((p) => (recent = p.items))
      .catch(() => {});
    get<Album[]>("/history/albums", { limit: 6 }, ctrl.signal)
      .then((a) => (played = a))
      .catch(() => {});
    return () => ctrl.abort();
  });

  const greeting = $derived.by(() => {
    const h = new Date().getHours();
    return h < 11 ? "Guten Morgen" : h < 18 ? "Hallo" : "Guten Abend";
  });
</script>

<div class="page">
  <div class="toolbar"><h1>{greeting}, {session.user?.display_name}</h1></div>

  {#if played.length}
    <div class="section-head"><h2>Zuletzt gehört</h2></div>
    <div class="grid">
      {#each played as album (album.id)}<AlbumCard {album} />{/each}
    </div>
  {/if}

  <div class="section-head">
    <h2>Playlists</h2>
  </div>
  <div class="lists">
    <a class="list" href={href("/favorites")}>
      <span class="art fav" aria-hidden="true"><Icon name="heart" size={22} filled /></span>
      <span class="meta"><strong>Lieblingssongs</strong><small>{plural(mine.favoriteTracks.size, "Titel", "Titel")}</small></span>
    </a>
    {#each mine.playlists.slice(0, 11) as p (p.id)}
      <a class="list" href={href(`/playlists/${p.id}`)}>
        <span class="art"><Cover hash={p.cover} size={64} /></span>
        <span class="meta">
          <strong>{p.name}</strong>
          <small>{p.role === "owner" ? plural(p.item_count, "Titel", "Titel") : `von ${p.owner.display_name}`}</small>
        </span>
      </a>
    {/each}
  </div>

  <div class="section-head">
    <h2>Neu hinzugefügt</h2>
    <a href={href("/albums")}>Alle Alben</a>
  </div>
  {#if recent && recent.length === 0}
    <p class="empty">
      Deine Bibliothek ist noch leer. Der erste Scan läuft im Hintergrund{session.user?.role === "admin"
        ? " – den Fortschritt siehst du in den Einstellungen."
        : "."}
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
    .lists {
      grid-template-columns: 1fr 1fr;
      padding: 0 16px 20px;
      gap: 8px;
    }
    .section-head {
      margin: 8px 16px 10px;
    }
  }
</style>
