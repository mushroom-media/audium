<script lang="ts">
  import { get, type Album, type AlbumDetail } from "../api";
  import { player } from "../player.svelte";
  import { href } from "../router.svelte";
  import CardPlay from "./CardPlay.svelte";
  import Cover from "./Cover.svelte";

  /** `showYear`: the year sits right-aligned next to the artist (lists sorted by year). */
  let { album, showYear = false }: { album: Album | undefined; showYear?: boolean } = $props();

  async function play() {
    if (!album) return;
    const detail = await get<AlbumDetail>(`/albums/${album.id}`);
    player.playTracks(detail.tracks, 0, false, { kind: "Album", name: detail.title, path: `/albums/${album.id}`, ref: `album:${album.id}` });
  }
</script>

{#if album}
  <a class="card" href={href(`/albums/${album.id}`)} title={album.title}>
    <div class="art">
      <Cover hash={album.cover} alt="" />
      <CardPlay ref="album:{album.id}" name={album.title} start={play} />
    </div>
    <div class="title">{album.title}</div>
    <div class="sub">
      <span class="artist">{album.artist}</span>
      {#if showYear && album.year}<span class="year">{album.year}</span>{/if}
    </div>
  </a>
{:else}
  <div class="card skeleton" aria-hidden="true">
    <div class="art"><div class="ph"></div></div>
    <div class="title bar"></div>
    <div class="sub bar short"></div>
  </div>
{/if}

<style>
  .card {
    display: block;
    color: inherit;
    text-decoration: none;
    min-width: 0;
  }
  .art {
    position: relative;
  }
  .ph {
    aspect-ratio: 1;
    border-radius: var(--radius-sm);
    background: var(--surface-2);
  }
  .title {
    margin-top: 10px;
    font-weight: 550;
    font-size: 0.92rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sub {
    display: flex;
    gap: 8px;
    color: var(--text-muted);
    font-size: 0.85rem;
    min-height: 1.2em;
  }
  .artist {
    flex: 1;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .year {
    flex: none;
    font-variant-numeric: tabular-nums;
  }
  .bar {
    height: 0.8em;
    border-radius: 4px;
    background: var(--surface-2);
    width: 80%;
  }
  .bar.short {
    width: 50%;
    margin-top: 6px;
  }
</style>
