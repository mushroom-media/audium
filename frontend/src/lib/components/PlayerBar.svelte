<script lang="ts">
  import { tick } from "svelte";
  import type { Track } from "../api";
  import { devices, others } from "../devices.svelte";
  import { duration } from "../format";
  import { player } from "../player.svelte";
  import * as Q from "../queue";
  import { href } from "../router.svelte";
  import { resist, swipe } from "../swipe";
  import ArtistLinks from "./ArtistLinks.svelte";
  import Cover from "./Cover.svelte";
  import Heart from "./Heart.svelte";
  import Icon from "./Icon.svelte";
  import RemoteStrip from "./RemoteStrip.svelte";

  const track = $derived(player.current);
  let dragging = $state<number | null>(null);
  const shown = $derived(dragging ?? player.position);
  const max = $derived(Math.max(1, player.duration));
  const progress = $derived(Math.min(100, (shown / max) * 100));
  const openNowPlaying = () => (player.nowPlayingOpen = true);
  // Phones: the whole left part of the bar opens "Jetzt läuft", not just cover and title (the
  // heart keeps working). On wider screens the cover links to the album and the artist to the artist.
  const phone = typeof matchMedia === "function" ? matchMedia("(max-width: 720px)") : null;
  const reducedMotion = typeof matchMedia === "function" ? matchMedia("(prefers-reduced-motion: reduce)") : null;
  let isPhone = $state(!!phone?.matches);
  $effect(() => {
    const update = () => (isPhone = !!phone?.matches);
    phone?.addEventListener("change", update);
    return () => phone?.removeEventListener("change", update);
  });
  function tapNow(e: MouseEvent) {
    if (!track || !phone?.matches) return;
    e.preventDefault();
    openNowPlaying();
  }

  // --- swiping cover and title: the next or previous track comes in, the buttons stay ---------

  // Skips once dragged this share of the width, or flicked this fast (px/ms) over at least FLICK_MIN_PX.
  const SKIP_SHARE = 0.3;
  const SKIP_VELOCITY = 0.45;
  const FLICK_MIN_PX = 20;
  const SLIDE_GAP_PX = 16;

  /** Current track and, on phones, its neighbours lying ready left and right. Keyed by place in
   * the queue, so after a swipe the track that came in stays the same element, cover included. */
  const slides = $derived.by(() => {
    if (!track) return [];
    const q = player.queue;
    const out: { track: Track; key: string; offset: number }[] = [{ track, key: `${q.pos}`, offset: 0 }];
    if (!isPhone) return out;
    const n = Q.next(q, false);
    const nextTrack = n && n.pos !== q.pos ? Q.current(n) : null;
    if (nextTrack) out.push({ track: nextTrack, key: `${n!.pos}`, offset: 1 });
    const p = Q.prev(q);
    const prevTrack = p.pos !== q.pos ? Q.current(p) : null;
    if (prevTrack) out.push({ track: prevTrack, key: nextTrack && n!.pos === p.pos ? `prev${p.pos}` : `${p.pos}`, offset: -1 });
    return out;
  });
  let strip = $state<HTMLElement>();
  let busy = false; // the swipe's animation is running
  const canSkip = (dx: number) => slides.some((s) => s.offset === (dx < 0 ? 1 : -1));

  const slideSwipe = {
    enabled: () => !!phone?.matches && !busy && !!track,
    onmove(dx: number) {
      if (strip) strip.style.transform = `translateX(${canSkip(dx) ? dx : resist(dx, strip.offsetWidth, 0.15)}px)`;
    },
    onend: release,
  };

  async function release(dx: number, velocity: number, cancelled: boolean) {
    if (!strip) return;
    const w = strip.offsetWidth;
    const shown = canSkip(dx) ? dx : resist(dx, w, 0.15);
    const flicked = Math.abs(velocity) > SKIP_VELOCITY && Math.sign(velocity) === Math.sign(dx) && Math.abs(dx) > FLICK_MIN_PX;
    const reduced = !!reducedMotion?.matches;
    const from = `translateX(${shown}px)`;
    busy = true;
    if (!cancelled && canSkip(dx) && (Math.abs(dx) > w * SKIP_SHARE || flicked)) {
      const out = Math.sign(dx) * (w + SLIDE_GAP_PX);
      const to = `translateX(${out}px)`;
      strip.style.transform = to;
      if (!reduced) {
        const duration = Math.min(240, Math.max(110, Math.abs(out - dx) / Math.max(Math.abs(velocity), 1.2)));
        await strip.animate([{ transform: from }, { transform: to }], { duration, easing: "cubic-bezier(0.25, 0.6, 0.35, 1)" }).finished.catch(() => {});
      }
      if (dx < 0) player.next();
      else player.prev({ restart: false });
      await tick();
      strip.style.transform = "";
    } else {
      strip.style.transform = "";
      await strip
        .animate([{ transform: from }, { transform: "none" }], { duration: reduced ? 80 : 240, easing: "cubic-bezier(0.2, 0.9, 0.3, 1)" })
        .finished.catch(() => {});
    }
    busy = false;
  }
</script>

<footer class="bar" aria-label="Player">
  <RemoteStrip />
  <input
    class="seek"
    type="range"
    min="0"
    {max}
    step="0.1"
    value={shown}
    style:--p="{progress}%"
    aria-label="Position"
    aria-valuetext="{duration(shown * 1000)} von {duration(player.duration * 1000)}"
    disabled={!track}
    oninput={(e) => (dragging = Number(e.currentTarget.value))}
    onchange={(e) => {
      player.seek(Number(e.currentTarget.value));
      dragging = null;
    }}
  />
  <div class="now">
    {#if track}
      <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions (cover and title are the keyboard targets) -->
      <div class="slides" use:swipe={slideSwipe} onclickcapture={tapNow}>
        <div class="strip" bind:this={strip}>
          {#each slides as s (s.key)}
            <div class="slide" style:--offset={s.offset} inert={s.offset !== 0}>
              <a class="art" href={href(`/albums/${s.track.album_id}`)} title={s.track.album} aria-label="Album {s.track.album} öffnen"><Cover hash={s.track.cover} size={64} /></a>
              <div class="meta">
                <button class="title" title={s.track.title} onclick={openNowPlaying}>{s.track.title}</button>
                <div class="artist"><ArtistLinks track={s.track} /></div>
              </div>
            </div>
          {/each}
        </div>
      </div>
      <Heart {track} />
    {:else}
      <div class="meta idle">Nichts in der Warteschlange</div>
    {/if}
  </div>

  <div class="controls">
    <button class="icon-btn side" class:on={player.queue.shuffle} onclick={() => player.toggleShuffle()} disabled={player.radio} title={player.radio ? "Radio hat schon eine eigene Reihenfolge" : "Zufallswiedergabe (S)"} aria-pressed={player.queue.shuffle} aria-label="Zufallswiedergabe">
      <Icon name="shuffle" size={18} />
    </button>
    <button class="icon-btn" onclick={() => player.prev()} title="Zurück (Shift+←)" aria-label="Zurück" disabled={!track}>
      <Icon name="prev" size={20} />
    </button>
    <button class="playpause" onclick={() => player.toggle()} title="Abspielen/Pause (Leertaste)" aria-label={player.playing ? "Pause" : "Abspielen"} disabled={!track}>
      {#if player.buffering && player.playing}<span class="spin" aria-hidden="true"></span>{/if}
      <Icon name={player.playing ? "pause" : "play"} size={22} />
    </button>
    <button class="icon-btn" onclick={() => player.next()} title="Weiter (Shift+→)" aria-label="Weiter" disabled={!track}>
      <Icon name="next" size={20} />
    </button>
    <button class="icon-btn side repeat" class:on={player.queue.repeat !== "off"} onclick={() => player.cycleRepeat()} title="Wiederholen (R)" aria-label="Wiederholen: {player.queue.repeat}">
      <Icon name="repeat" size={18} />
      {#if player.queue.repeat === "one"}<span class="one">1</span>{/if}
    </button>
  </div>

  <div class="right">
    <span class="time">{duration(shown * 1000)} / {duration(player.duration * 1000)}</span>
    <button class="icon-btn" onclick={() => player.setMuted(!player.muted)} title="Stumm (M)" aria-label={player.muted ? "Ton an" : "Stumm"}>
      <Icon name={player.muted || player.volume === 0 ? "mute" : "volume"} size={18} />
    </button>
    <input
      class="volume"
      type="range"
      min="0"
      max="1"
      step="0.01"
      value={player.muted ? 0 : player.volume}
      style:--p="{(player.muted ? 0 : player.volume) * 100}%"
      aria-label="Lautstärke"
      oninput={(e) => player.setVolume(Number(e.currentTarget.value))}
    />
    {#if others().length || devices.target}
      <button class="icon-btn" class:on={!!devices.target} onclick={() => (devices.picker = true)} title="Gerät steuern" aria-label="Gerät steuern">
        <Icon name="devices" size={18} />
      </button>
    {/if}
    <button class="icon-btn" class:on={player.queueOpen} onclick={() => (player.queueOpen = !player.queueOpen)} title="Warteschlange (Q)" aria-label="Warteschlange" aria-pressed={player.queueOpen}>
      <Icon name="queue" size={18} />
    </button>
    <button class="icon-btn" onclick={openNowPlaying} disabled={!track} title="Jetzt läuft (N)" aria-label="Jetzt läuft öffnen">
      <Icon name="expand" size={18} />
    </button>
  </div>
  {#if player.error}<div class="error" class:raised={devices.target} role="status">{player.error}</div>{/if}
</footer>

<style>
  .bar {
    position: relative;
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
    align-items: center;
    gap: 16px;
    height: var(--player-h);
    padding: 0 16px;
    background: var(--surface-0);
    border-top: 1px solid var(--line);
  }
  .seek {
    position: absolute;
    left: 0;
    right: 0;
    top: -7px;
    width: 100%;
    margin: 0;
  }
  .now {
    display: flex;
    align-items: center;
    gap: 12px;
    min-width: 0;
  }
  .slides,
  .strip,
  .slide {
    display: flex;
    align-items: center;
    gap: 12px;
    min-width: 0;
  }
  .art {
    display: block;
    width: 52px;
    flex: none;
  }
  .meta {
    min-width: 0;
  }
  .idle {
    color: var(--text-faint);
    font-size: 0.9rem;
  }
  .title {
    display: block;
    max-width: 100%;
    padding: 0;
    border: 0;
    background: none;
    color: inherit;
    text-align: left;
    cursor: pointer;
    font-weight: 550;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .artist {
    color: var(--text-muted);
    font-size: 0.86rem;
    text-decoration: none;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    display: block;
    width: fit-content;
    max-width: 100%;
  }
  .controls {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .playpause {
    position: relative;
    width: 46px;
    height: 46px;
    border-radius: 50%;
    border: 0;
    display: grid;
    place-items: center;
    background: var(--text);
    color: var(--bg);
    cursor: pointer;
    margin: 0 6px;
  }
  .playpause:disabled {
    opacity: 0.4;
    cursor: default;
  }
  .spin {
    position: absolute;
    inset: -4px;
    border-radius: 50%;
    border: 2px solid transparent;
    border-top-color: var(--accent);
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
  .repeat {
    position: relative;
  }
  .one {
    position: absolute;
    right: 3px;
    bottom: 2px;
    font-size: 0.6rem;
    font-weight: 700;
  }
  .right {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 6px;
  }
  .time {
    color: var(--text-muted);
    font-size: 0.82rem;
    font-variant-numeric: tabular-nums;
    margin-right: 6px;
    white-space: nowrap;
  }
  .volume {
    width: 96px;
  }
  .error {
    position: absolute;
    bottom: calc(100% + 12px);
    left: 50%;
    transform: translateX(-50%);
    background: var(--danger);
    color: white;
    padding: 6px 12px;
    border-radius: var(--radius-sm);
    font-size: 0.85rem;
  }
  .error.raised {
    bottom: calc(100% + 40px);
  }
  @media (max-width: 720px) {
    .bar {
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      padding: 0 10px;
    }
    .right {
      display: none;
    }
    .side {
      display: none;
    }
    .art {
      width: 44px;
    }
    .now {
      align-self: stretch;
      cursor: pointer;
    }
    .slides {
      position: relative;
      flex: 1;
      align-self: stretch;
      overflow: hidden;
      touch-action: pan-y;
    }
    .strip {
      position: absolute;
      inset: 0;
    }
    .slide {
      position: absolute;
      inset: 0;
      transform: translateX(calc(var(--offset) * (100% + 16px)));
    }
    .meta {
      flex: 1;
    }
  }
</style>
