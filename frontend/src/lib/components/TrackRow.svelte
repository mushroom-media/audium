<script lang="ts">
  import type { Track } from "../api";
  import { duration } from "../format";
  import { player } from "../player.svelte";
  import { href } from "../router.svelte";
  import { swipe } from "../swipe";
  import { openTrackMenu, toast } from "../ui.svelte";
  import ArtistLinks from "./ArtistLinks.svelte";
  import Cover from "./Cover.svelte";
  import Heart from "./Heart.svelte";
  import Icon from "./Icon.svelte";
  import { locale, t } from "../i18n.svelte";

  let {
    track,
    number,
    showCover = true,
    showAlbum = true,
    linkArtist = true,
    onplay,
    onremove,
    ondislike,
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
    /** Radio stations: the track doesn't fit, take it out. */
    ondislike?: () => void;
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

  // --- swipe left: into the queue, like the "archive" of a mail app ---------------------------

  // Far enough at a third of the row, but no more than this on wide phones and tablets.
  const QUEUE_SHARE = 1 / 3;
  const QUEUE_MAX_PX = 140;
  /** Past the threshold the row follows the finger only this much, so going further feels like an end. */
  const PAST_THRESHOLD = 0.3;

  let rowEl = $state<HTMLElement>();
  let pull = $state(0); // how far the row is moved, in px to the left
  let pastThreshold = $state(false);
  let settling = $state(false);

  const threshold = () => Math.min(QUEUE_MAX_PX, (rowEl?.offsetWidth ?? 0) * QUEUE_SHARE);

  const queueSwipe = {
    enabled: () => touch && !!track && !unavailable,
    onmove(dx: number) {
      const finger = Math.max(0, -dx);
      const t = threshold();
      settling = false;
      pull = finger > t ? t + (finger - t) * PAST_THRESHOLD : finger;
      const past = finger > t;
      if (past !== pastThreshold) navigator.vibrate?.(8);
      pastThreshold = past;
    },
    onend(_dx: number, _velocity: number, cancelled: boolean) {
      if (pastThreshold && !cancelled && track) {
        player.enqueue([track]);
        toast(t("Zur Warteschlange hinzugefügt"));
      }
      settling = pull > 0;
      pull = 0;
      pastThreshold = false;
    },
  };
</script>

{#if track}
  <div class="swipe" class:open={pull > 0 || settling} use:swipe={queueSwipe}>
  {#if pull > 0 || settling}
    <div class="to-queue" class:past={pastThreshold} class:settling style:width="{pull}px" aria-hidden="true">
      <Icon name="queue" size={20} />
    </div>
  {/if}
  <div
    bind:this={rowEl}
    class="row"
    class:settling
    style:transform={pull ? `translateX(${-pull}px)` : undefined}
    ontransitionend={() => (settling = false)}
    ontransitioncancel={() => (settling = false)}
    class:active
    class:unavailable
    title={unavailable ? t("Datei fehlt gerade in der Bibliothek") : undefined}
    oncontextmenu={(e) => openTrackMenu(e, [track], "", ondislike)}
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
      <div class="artist"><ArtistLinks {track} link={linkArtist || !touch} /></div>
    </div>
    {#if showAlbum}
      {#if note}<span class="album note" title={note}>{note}</span>
      {:else}<a class="album" href={href(`/albums/${track.album_id}`)}>{track.album}</a>{/if}
    {/if}
    {#if count != null}<div class="count">{count.toLocaleString(locale())}</div>{/if}
    <div class="dur">{duration(track.duration_ms)}</div>
    <div class="actions">
      {#if ondislike}
        <button class="icon-btn dislike" title={t("Mag ich nicht")} aria-label={t("{title}: Mag ich nicht", { title: track.title })} onclick={(e) => (e.stopPropagation(), ondislike())}>
          <Icon name="dislike" size={17} />
        </button>
      {/if}
      <Heart {track} size={17} />
      {#if onremove}
        <button class="icon-btn" title={t("Aus Playlist entfernen")} aria-label={t("Aus Playlist entfernen")} onclick={(e) => (e.stopPropagation(), onremove())}>
          <Icon name="close" size={16} />
        </button>
      {/if}
      <button class="icon-btn" title={t("Mehr")} aria-label={t("Mehr zu {title}", { title: track.title })} onclick={(e) => openTrackMenu(e, [track], "", ondislike)}>
        <Icon name="more" size={18} />
      </button>
    </div>
  </div>
  </div>
{:else}
  <div class="row skeleton" aria-hidden="true"><div class="num"></div><div class="main"><div class="bar"></div></div></div>
{/if}

<style>
  .swipe {
    position: relative;
    height: 100%;
  }
  .swipe.open {
    overflow: hidden;
    border-radius: var(--radius-sm);
  }
  @media (hover: none) {
    .swipe {
      touch-action: pan-y;
    }
  }
  .to-queue {
    position: absolute;
    top: 0;
    bottom: 0;
    right: 0;
    display: flex;
    align-items: center;
    justify-content: flex-end;
    overflow: hidden;
    background: var(--surface-2);
    color: var(--text-muted);
    transition: background-color 0.12s, color 0.12s;
  }
  .to-queue.past {
    background: var(--accent);
    color: var(--bg);
  }
  .to-queue :global(svg) {
    flex: none;
    margin-right: 20px;
    transition: transform 0.12s;
  }
  .to-queue.past :global(svg) {
    transform: scale(1.2);
  }
  .to-queue.settling {
    transition: width 0.22s cubic-bezier(0.2, 0.9, 0.3, 1);
  }
  .row.settling {
    transition: transform 0.22s cubic-bezier(0.2, 0.9, 0.3, 1);
  }
  @media (prefers-reduced-motion: reduce) {
    .to-queue.settling,
    .row.settling {
      transition-duration: 0.08s;
    }
    .to-queue.past :global(svg) {
      transform: none;
    }
  }
  .row {
    display: grid;
    grid-template-columns: 40px 44px minmax(0, 1fr) minmax(0, 0.8fr) 56px auto;
    align-items: center;
    gap: 12px;
    height: 100%;
    padding: 0 16px 0 8px;
    border-radius: var(--radius-sm);
    outline: none;
    /* A double-click plays; it shouldn't also mark a word. */
    user-select: none;
    -webkit-user-select: none;
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
    .actions :global(.heart:not(.on)),
    .actions .dislike {
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
