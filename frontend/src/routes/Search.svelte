<script lang="ts">
  import { get, type SearchResult } from "../lib/api";
  import AlbumCard from "../lib/components/AlbumCard.svelte";
  import Cover from "../lib/components/Cover.svelte";
  import TrackRow from "../lib/components/TrackRow.svelte";
  import { player } from "../lib/player.svelte";
  import { href, router } from "../lib/router.svelte";

  const q = $derived(router.route.query.get("q")?.trim() ?? "");
  let result = $state<SearchResult | null>(null);
  let loading = $state(false);

  $effect(() => {
    const query = q;
    if (query.length < 2) {
      result = null;
      return;
    }
    const ctrl = new AbortController();
    loading = true;
    get<SearchResult>("/search", { q: query, limit: 24 }, ctrl.signal)
      .then((r) => (result = r))
      .catch(() => {})
      .finally(() => (loading = false));
    return () => ctrl.abort();
  });

  const nothing = $derived(result && !result.tracks.length && !result.albums.length && !result.artists.length);
</script>

<div class="page">
  <div class="toolbar"><h1>{q ? `„${q}“` : "Suche"}</h1></div>
  {#if q.length < 2}
    <p class="empty">Tippe mindestens zwei Buchstaben in das Suchfeld oben.</p>
  {:else if nothing && !loading}
    <p class="empty">Nichts gefunden.</p>
  {:else if result}
    {#if result.artists.length}
      <h2 class="section">Künstler</h2>
      <div class="artists">
        {#each result.artists as a (a.id)}
          <a class="artist" href={href(`/artists/${a.id}`)}>
            <Cover hash={a.cover} size={256} round />
            <span>{a.name}</span>
          </a>
        {/each}
      </div>
    {/if}
    {#if result.albums.length}
      <h2 class="section">Alben</h2>
      <div class="grid">
        {#each result.albums.slice(0, 12) as album (album.id)}<AlbumCard {album} />{/each}
      </div>
    {/if}
    {#if result.tracks.length}
      <h2 class="section">Titel</h2>
      <div class="tracks">
        {#each result.tracks as t, i (t.id)}
          <div class="row-h"><TrackRow track={t} number={i + 1} onplay={() => result && player.playTracks(result.tracks, i)} /></div>
        {/each}
      </div>
    {/if}
  {/if}
</div>

<style>
  .section {
    font-size: 1.05rem;
    margin: 24px 24px 12px;
  }
  .artists {
    display: flex;
    gap: 20px;
    overflow-x: auto;
    padding: 0 24px 8px;
  }
  .artist {
    width: 130px;
    flex: none;
    text-align: center;
    color: inherit;
    text-decoration: none;
    font-weight: 500;
  }
  .artist span {
    display: block;
    margin-top: 8px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 20px;
    padding: 0 24px;
  }
  .tracks {
    padding: 0 16px 32px;
  }
  .row-h {
    height: 56px;
  }
</style>
