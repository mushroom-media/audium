<script lang="ts">
  // One artist in the library grid, laid out like AlbumCard but with a round image; a placeholder while it loads.
  import type { Artist } from "../api";
  import { plural } from "../format";
  import { href } from "../router.svelte";
  import Cover from "./Cover.svelte";

  let { artist }: { artist: Artist | undefined } = $props();
</script>

{#if artist}
  <a class="card" href={href(`/artists/${artist.id}`)} title={artist.name}>
    <Cover hash={artist.cover} alt="" round />
    <div class="name">{artist.name}</div>
    <div class="sub">{plural(artist.album_count, "Album", "Alben")} · {plural(artist.track_count, "Titel", "Titel")}</div>
  </a>
{:else}
  <div class="card" aria-hidden="true">
    <div class="ph"></div>
    <div class="name bar"></div>
    <div class="sub bar short"></div>
  </div>
{/if}

<style>
  .card {
    display: block;
    color: inherit;
    text-decoration: none;
    min-width: 0;
    text-align: center;
  }
  .ph {
    aspect-ratio: 1;
    border-radius: 50%;
    background: var(--surface-2);
  }
  .name {
    margin-top: 10px;
    font-weight: 550;
    font-size: 0.92rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sub {
    color: var(--text-muted);
    font-size: 0.85rem;
    min-height: 1.2em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .bar {
    height: 0.8em;
    border-radius: 4px;
    background: var(--surface-2);
    width: 70%;
    margin-inline: auto;
  }
  .bar.short {
    width: 45%;
    margin-top: 6px;
  }
</style>
