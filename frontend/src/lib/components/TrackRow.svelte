<script lang="ts">
  import type { Track } from "../api";
  import { duration } from "../format";
  import { player } from "../player.svelte";
  import { href } from "../router.svelte";
  import { openTrackMenu } from "../ui.svelte";
  import Cover from "./Cover.svelte";
  import Heart from "./Heart.svelte";
  import Icon from "./Icon.svelte";

  let {
    track,
    number,
    showCover = true,
    showAlbum = true,
    onplay,
    onremove,
    unavailable = false,
    note,
  }: {
    track: Track | undefined;
    number?: number | null;
    showCover?: boolean;
    showAlbum?: boolean;
    onplay: () => void;
    onremove?: () => void;
    unavailable?: boolean;
    /** Shown instead of the album, e.g. why the track is in an auto-playlist. */
    note?: string | null;
  } = $props();

  const active = $derived(track && player.current?.id === track.id);
  const touch = typeof matchMedia !== "undefined" && matchMedia("(hover: none)").matches;

  // Desktop: double-click plays (single click selects nothing, like other players).
  // Touch: a tap plays, except on the artist/album links and buttons inside the row.
  function onRowClick(e: MouseEvent) {
    if (touch && !(e.target as Element).closest("a, button")) onplay();
  }
</script>

{#if track}
  <div
    class="row"
    class:active
    class:unavailable
    title={unavailable ? "Datei fehlt gerade in der Bibliothek" : undefined}
    oncontextmenu={(e) => openTrackMenu(e, [track])}
    class:no-album={!showAlbum}
    role="button"
    tabindex="0"
    ondblclick={onplay}
    onclick={onRowClick}
    onkeydown={(e) => e.key === "Enter" && onplay()}
  >
    <button class="num" aria-label="{track.title} abspielen" onclick={onplay}>
      <span class="n">{#if active && player.playing}<span class="eq" aria-hidden="true"><i></i><i></i><i></i></span>{:else}{number ?? ""}{/if}</span>
      <span class="p"><Icon name="play" size={16} /></span>
    </button>
    {#if showCover}<div class="thumb"><Cover hash={track.cover} size={64} /></div>{/if}
    <div class="main">
      <div class="title">{track.title}</div>
      <a class="artist" href={href(`/artists/${track.artist_id}`)}>{track.artist}</a>
    </div>
    {#if showAlbum}
      {#if note}<span class="album note" title={note}>{note}</span>
      {:else}<a class="album" href={href(`/albums/${track.album_id}`)}>{track.album}</a>{/if}
    {/if}
    <div class="actions">
      <Heart {track} size={17} />
      {#if onremove}
        <button class="icon-btn" title="Aus Playlist entfernen" aria-label="Aus Playlist entfernen" onclick={(e) => (e.stopPropagation(), onremove())}>
          <Icon name="close" size={16} />
        </button>
      {/if}
      <button class="icon-btn" title="Mehr" aria-label="Mehr zu {track.title}" onclick={(e) => openTrackMenu(e, [track])}>
        <Icon name="more" size={18} />
      </button>
    </div>
    <div class="dur">{duration(track.duration_ms)}</div>
  </div>
{:else}
  <div class="row skeleton" aria-hidden="true"><div class="num"></div><div class="main"><div class="bar"></div></div></div>
{/if}

<style>
  .row {
    display: grid;
    grid-template-columns: 40px 44px minmax(0, 1fr) minmax(0, 0.8fr) auto 56px;
    align-items: center;
    gap: 12px;
    height: 100%;
    padding: 0 16px 0 8px;
    border-radius: var(--radius-sm);
    outline: none;
  }
  .row.no-album {
    grid-template-columns: 40px minmax(0, 1fr) auto 56px;
  }
  .row:not(.skeleton):hover,
  .row:focus-visible {
    background: var(--surface-1);
  }
  .num {
    width: 40px;
    height: 40px;
    border: 0;
    background: none;
    color: var(--text-muted);
    font: inherit;
    font-variant-numeric: tabular-nums;
    cursor: pointer;
    display: grid;
    place-items: center;
  }
  .num .p {
    display: none;
    color: var(--text);
  }
  .row:hover .num .n {
    display: none;
  }
  .row:hover .num .p {
    display: grid;
  }
  .thumb {
    width: 40px;
  }
  .main,
  .album {
    min-width: 0;
  }
  .title,
  .artist,
  .album {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .title {
    font-weight: 500;
  }
  .active .title {
    color: var(--accent);
  }
  .artist,
  .album {
    color: var(--text-muted);
    font-size: 0.88rem;
    text-decoration: none;
    display: block;
  }
  .artist:hover,
  .album:hover {
    color: var(--text);
    text-decoration: underline;
  }
  .dur {
    color: var(--text-muted);
    font-size: 0.88rem;
    font-variant-numeric: tabular-nums;
    text-align: right;
  }
  .actions {
    display: flex;
    align-items: center;
  }
  /* Actions appear on hover; a filled heart stays visible so favorites stand out. */
  .actions > :global(*) {
    opacity: 0;
  }
  .row:hover .actions > :global(*),
  .row:focus-within .actions > :global(*),
  .actions > :global(.heart.on) {
    opacity: 1;
  }
  .bar {
    height: 0.8em;
    width: 40%;
    border-radius: 4px;
    background: var(--surface-1);
  }
  .eq {
    display: inline-flex;
    gap: 2px;
    align-items: flex-end;
    height: 14px;
  }
  .eq i {
    width: 3px;
    background: var(--accent);
    animation: eq 0.9s ease-in-out infinite alternate;
  }
  .eq i:nth-child(2) {
    animation-delay: -0.3s;
  }
  .eq i:nth-child(3) {
    animation-delay: -0.6s;
  }
  @keyframes eq {
    from {
      height: 3px;
    }
    to {
      height: 14px;
    }
  }
  .unavailable {
    opacity: 0.45;
  }
  .note {
    color: var(--accent);
    font-size: 0.82rem;
  }
  @media (max-width: 720px) {
    .row {
      grid-template-columns: 44px minmax(0, 1fr) auto;
      gap: 8px;
      padding: 0 4px 0 8px;
    }
    .row.no-album {
      grid-template-columns: 32px minmax(0, 1fr) auto;
    }
    .album,
    .dur {
      display: none;
    }
    .actions > :global(*) {
      opacity: 1;
    }
    .actions :global(.heart:not(.on)) {
      display: none;
    }
    .row.no-album .num {
      display: grid;
    }
    .row:not(.no-album) .num {
      display: none;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .eq i {
      animation: none;
      height: 10px;
    }
  }
</style>
