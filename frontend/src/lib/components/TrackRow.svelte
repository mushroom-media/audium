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
    linkArtist = true,
    onplay,
    onremove,
    unavailable = false,
    note,
    count,
  }: {
    track: Track | undefined;
    number?: number | null;
    showCover?: boolean;
    showAlbum?: boolean;
    /** false: on touch screens the artist is plain text, so a tap anywhere plays (album pages). */
    linkArtist?: boolean;
    onplay: () => void;
    onremove?: () => void;
    unavailable?: boolean;
    /** Shown instead of the album, e.g. why the track is in an auto-playlist. */
    note?: string | null;
    /** A number in its own last column, e.g. how often the track was played. */
    count?: number | null;
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
    class:has-count={count != null}
    role="button"
    tabindex="0"
    ondblclick={onplay}
    onclick={onRowClick}
    onkeydown={(e) => e.key === "Enter" && onplay()}
  >
    <button
      class="num"
      aria-label="{track.title} {active && player.playing ? 'pausieren' : 'abspielen'}"
      onclick={() => (active ? player.toggle() : onplay())}
    >
      <span class="n">{#if active && player.playing}<span class="eq" aria-hidden="true"><i></i><i></i><i></i></span>{:else}{number ?? ""}{/if}</span>
      <span class="p"><Icon name={active && player.playing ? "pause" : "play"} size={16} /></span>
    </button>
    {#if showCover}<div class="thumb"><Cover hash={track.cover} size={64} /></div>{/if}
    <div class="main">
      <div class="title">{track.title}</div>
      {#if linkArtist || !touch}<a class="artist" href={href(`/artists/${track.artist_id}`)}>{track.artist}</a>
      {:else}<span class="artist">{track.artist}</span>{/if}
    </div>
    {#if showAlbum}
      {#if note}<span class="album note" title={note}>{note}</span>
      {:else}<a class="album" href={href(`/albums/${track.album_id}`)}>{track.album}</a>{/if}
    {/if}
    {#if count != null}<div class="count">{count.toLocaleString("de-DE")}</div>{/if}
    <div class="dur">{duration(track.duration_ms)}</div>
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
  </div>
{:else}
  <div class="row skeleton" aria-hidden="true"><div class="num"></div><div class="main"><div class="bar"></div></div></div>
{/if}

<style>
  .row {
    display: grid;
    grid-template-columns: 40px 44px minmax(0, 1fr) minmax(0, 0.8fr) 56px auto;
    align-items: center;
    gap: 12px;
    height: 100%;
    padding: 0 16px 0 8px;
    border-radius: var(--radius-sm);
    outline: none;
  }
  .row.no-album {
    grid-template-columns: 40px minmax(0, 1fr) 56px auto;
  }
  .row.has-count {
    grid-template-columns: 40px 44px minmax(0, 1fr) minmax(0, 0.8fr) 56px 56px auto;
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
    /* Only as wide as the text, so the empty space beside it isn't a link. */
    width: fit-content;
    max-width: 100%;
  }
  .artist:hover,
  .album:hover {
    color: var(--text);
    text-decoration: underline;
  }
  .count {
    font-variant-numeric: tabular-nums;
    text-align: right;
  }
  .dur {
    color: var(--text-muted);
    font-size: 0.88rem;
    font-variant-numeric: tabular-nums;
    text-align: right;
  }
  /* Always the last column, so the menu sits at the row's end in every list. */
  .actions {
    display: flex;
    align-items: center;
    justify-content: flex-end;
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
    /* Heart + menu at a fixed width: the heart only shows when filled, and the count
       in front of it has to line up from row to row. */
    .row.has-count {
      grid-template-columns: 44px minmax(0, 1fr) 40px 72px;
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
