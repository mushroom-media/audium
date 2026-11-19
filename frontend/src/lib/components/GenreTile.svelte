<script lang="ts">
  // A broad genre as a wide tile: its name on the genre's own cover, so the genres stand apart
  // from the playlist cards below. The server makes that cover already blurred, with a gradient
  // (analysis/genre_covers.py), and it is the same one the start page and the playlist page show.
  import { coverUrl, type AutoPlaylist } from "../api";
  import { plural } from "../format";
  import { href } from "../router.svelte";

  let { playlist, label = playlist.name }: { playlist: AutoPlaylist; label?: string } = $props();
  const bg = $derived(coverUrl(playlist.cover, 256));
  // Without a cover: a gradient of its own, the same for a genre every time.
  const hue = $derived([...playlist.name].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7));
  const fallback = $derived(`linear-gradient(135deg, hsl(${hue} 55% 42%), hsl(${(hue + 40) % 360} 60% 24%))`);
</script>

<a class="tile" href={href(`/discover/${playlist.id}`)} title={playlist.description ?? playlist.name} style:background={bg ? undefined : fallback}>
  {#if bg}<span class="bg" style:background-image="url({bg})" aria-hidden="true"></span>{/if}
  <span class="name">{label}</span>
  <span class="count">{plural(playlist.track_count, "Titel", "Titel")}</span>
</a>

<style>
  .tile {
    position: relative;
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
    min-width: 0;
    aspect-ratio: 16 / 9;
    padding: 12px 14px;
    border-radius: var(--radius-sm);
    overflow: hidden;
    color: white;
    text-decoration: none;
    background: var(--surface-2);
    isolation: isolate;
  }
  .bg {
    position: absolute;
    inset: 0;
    z-index: -2;
    background-size: cover;
    background-position: center;
    transition: transform 0.3s ease;
  }
  .tile::after {
    content: "";
    position: absolute;
    inset: 0;
    z-index: -1;
    background: linear-gradient(160deg, rgb(0 0 0 / 0.05), rgb(0 0 0 / 0.55));
  }
  .tile:hover .bg {
    transform: scale(1.06);
  }
  .name {
    font-size: 1.15rem;
    font-weight: 700;
    line-height: 1.15;
    text-shadow: 0 1px 6px rgb(0 0 0 / 0.4);
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .count {
    font-size: 0.8rem;
    opacity: 0.85;
  }
</style>
