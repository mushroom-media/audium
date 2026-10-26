<script lang="ts">
  import { get, type Album, type AlbumDetail } from "../api";
  import { player } from "../player.svelte";
  import { href } from "../router.svelte";
  import Cover from "./Cover.svelte";
  import Icon from "./Icon.svelte";

  /** `showYear`: the year sits right-aligned next to the artist (lists sorted by year). */
  let { album, showYear = false }: { album: Album | undefined; showYear?: boolean } = $props();

  async function play(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    if (!album) return;
    const detail = await get<AlbumDetail>(`/albums/${album.id}`);
    player.playTracks(detail.tracks, 0, false, { kind: "Album", name: detail.title, path: `/albums/${album.id}`, ref: `album:${album.id}` });
  }
</script>

{#if album}
  <a class="card" href={href(`/albums/${album.id}`)} title={album.title}>
    <div class="art">
      <Cover hash={album.cover} alt="" />
      <button class="play" aria-label="{album.title} abspielen" onclick={play}><Icon name="play" size={22} /></button>
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
  .play {
    position: absolute;
    right: 10px;
    bottom: 10px;
    width: 44px;
    height: 44px;
    border-radius: 50%;
    border: 0;
    display: grid;
    place-items: center;
    background: var(--accent);
    color: var(--accent-contrast);
    box-shadow: 0 6px 18px rgb(0 0 0 / 0.35);
    opacity: 0;
    transform: translateY(6px);
    transition:
      opacity 0.15s,
      transform 0.15s;
    cursor: pointer;
  }
  .card:hover .play,
  .play:focus-visible {
    opacity: 1;
    transform: none;
  }
  @media (hover: none) {
    .play {
      display: none;
    }
  }
</style>
