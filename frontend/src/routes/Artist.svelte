<script lang="ts">
  import { get, type Album, type Artist, type Page, type Track } from "../lib/api";
  import AlbumCard from "../lib/components/AlbumCard.svelte";
  import Cover from "../lib/components/Cover.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import { plural } from "../lib/format";
  import { player } from "../lib/player.svelte";

  let { id }: { id: string } = $props();
  let artist = $state<Artist | null>(null);
  let albums = $state<Album[]>([]);
  let error = $state<string | null>(null);
  const PLAY_LIMIT = 500;

  $effect(() => {
    const ctrl = new AbortController();
    artist = null;
    albums = [];
    error = null;
    Promise.all([
      get<Artist>(`/artists/${id}`, undefined, ctrl.signal),
      get<Page<Album>>("/albums", { artist_id: id, sort: "year", limit: 500 }, ctrl.signal),
    ])
      .then(([a, page]) => {
        artist = a;
        albums = page.items;
      })
      .catch((e) => e.name !== "AbortError" && (error = e.message));
    return () => ctrl.abort();
  });

  async function playAll(shuffle: boolean) {
    const page = await get<Page<Track>>("/tracks", { artist_id: id, sort: "year", order: "asc", limit: PLAY_LIMIT });
    if (shuffle !== player.queue.shuffle) player.toggleShuffle();
    player.playTracks(page.items, 0);
  }
</script>

<div class="page">
  {#if error}
    <p class="empty">{error}</p>
  {:else if artist}
    <header class="hero">
      <div class="avatar"><Cover hash={artist.cover} size={256} round /></div>
      <div>
        <p class="kind">Künstler</p>
        <h1>{artist.name}</h1>
        <p class="stats">{plural(artist.album_count, "Album", "Alben")} · {plural(artist.track_count, "Titel", "Titel")}</p>
        {#if artist.track_count > 0}
          <div class="actions">
            <button class="btn primary" onclick={() => playAll(false)}><Icon name="play" size={18} /> Alle abspielen</button>
            <button class="btn" onclick={() => playAll(true)}><Icon name="shuffle" size={18} /> Zufällig</button>
          </div>
        {/if}
      </div>
    </header>
    {#if albums.length}
      <h2 class="section">Alben</h2>
      <div class="grid">
        {#each albums as album (album.id)}<AlbumCard {album} subtitle="year" />{/each}
      </div>
    {/if}
  {/if}
</div>

<style>
  .hero {
    display: flex;
    align-items: center;
    gap: 28px;
    padding: 32px 24px 8px;
  }
  .avatar {
    width: min(180px, 34vw);
    flex: none;
  }
  .kind {
    margin: 0;
    color: var(--text-muted);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }
  h1 {
    font-size: clamp(1.6rem, 4vw, 3rem);
    margin: 6px 0 6px;
    letter-spacing: -0.02em;
  }
  .stats {
    color: var(--text-muted);
    margin: 0 0 18px;
  }
  .actions {
    display: flex;
    gap: 10px;
  }
  .section {
    font-size: 1.1rem;
    margin: 28px 24px 14px;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
    gap: 20px;
    padding: 0 24px 32px;
  }
  @media (max-width: 560px) {
    .hero {
      flex-direction: column;
      align-items: flex-start;
      padding: 20px 16px 0;
    }
    .grid {
      grid-template-columns: repeat(2, 1fr);
      padding: 0 16px 24px;
      gap: 14px;
    }
  }
</style>
