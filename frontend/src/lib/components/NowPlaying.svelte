<script lang="ts">
  // Full-screen view of the current track: large cover, all transport controls. On phones it
  // replaces the hidden parts of the player bar (shuffle, repeat, volume); swipe down to close.
  import { coverUrl } from "../api";
  import { devices, others, target } from "../devices.svelte";
  import { duration } from "../format";
  import { player, REPEAT_LABELS } from "../player.svelte";
  import * as Q from "../queue";
  import { href } from "../router.svelte";
  import { session } from "../session.svelte";
  import { resist } from "../swipe";
  import { openTrackMenu } from "../ui.svelte";
  import { fade } from "svelte/transition";
  import ArtistLinks from "./ArtistLinks.svelte";
  import Cover from "./Cover.svelte";
  import Heart from "./Heart.svelte";
  import Icon from "./Icon.svelte";
  import { t } from "../i18n.svelte";

  const CLOSE_SWIPE_PX = 110;

  const track = $derived(player.current);
  let dragging = $state<number | null>(null);
  const shown = $derived(dragging ?? player.position);
  const max = $derived(Math.max(1, player.duration));
  const progress = $derived(Math.min(100, (shown / max) * 100));
  const backdrop = $derived(coverUrl(track?.cover ?? null, 256));
  // The backdrop's pace (a user setting): 0 stands still, 50 twice the base pace, 100 four times.
  const motion = $derived(session.settings.backdrop_motion / 25);

  // A touch first moves this far before it is decided whether it is a horizontal or a vertical gesture.
  const AXIS_LOCK_PX = 8;
  // Swiping the cover skips once it is dragged this share of its width, or flicked this fast (px/ms).
  const SKIP_SHARE = 0.3;
  const SKIP_VELOCITY = 0.45;

  // The cover swipe is for the phone layout only; the desktop layout starts at 900 px.
  const phone = typeof matchMedia === "function" ? matchMedia("(max-width: 899px)") : null;
  const reducedMotion = typeof matchMedia === "function" ? matchMedia("(prefers-reduced-motion: reduce)") : null;

  type Gesture = { x: number; y: number; axis: "x" | "y" | null; onArt: boolean; dx: number; samples: { x: number; t: number }[] };
  let gesture: Gesture | null = null;
  let swipe = $state(0);
  let art = $state<HTMLElement>();
  let artBusy = false; // a skip animation is running

  // A new track's backdrop fades in over the old one.
  const BACKDROP_FADE_MS = 900;

  /** A new backdrop layer drifts on from where the fading one is, so nothing jumps. */
  function keepDrift(layer: HTMLElement) {
    const kind = layer.classList.contains("a") ? "a" : "b";
    const old = [...(layer.closest(".np")?.querySelectorAll<HTMLElement>(`.layer.${kind}`) ?? [])].find((l) => l !== layer);
    const time = old?.getAnimations()[0]?.currentTime;
    const anim = layer.getAnimations()[0];
    if (anim && time != null) anim.currentTime = time;
  }

  const close = () => (player.nowPlayingOpen = false);

  /** Closing (button, swipe down, the system's back) mirrors the rise: down and fading out,
   * starting from wherever a swipe left the view. */
  function sink(_: Element) {
    const from = swipe;
    return {
      duration: reducedMotion?.matches ? 0 : 220,
      css: (t: number, u: number) => `transform: translateY(${from + u * 40}px); opacity: ${t}`,
    };
  }

  function onTouchStart(e: TouchEvent) {
    const target = e.target as HTMLElement;
    // Sliders and buttons keep their own gestures.
    if (e.touches.length !== 1 || target.closest("input, button, a")) {
      gesture = null;
      return;
    }
    const t = e.touches[0];
    const onArt = !artBusy && !!phone?.matches && !!art?.contains(target);
    gesture = { x: t.clientX, y: t.clientY, axis: null, onArt, dx: 0, samples: [] };
  }
  function onTouchMove(e: TouchEvent) {
    if (!gesture) return;
    const t = e.touches[0];
    const dx = t.clientX - gesture.x;
    const dy = t.clientY - gesture.y;
    if (!gesture.axis) {
      if (Math.hypot(dx, dy) < AXIS_LOCK_PX) return;
      gesture.axis = Math.abs(dx) > Math.abs(dy) ? "x" : "y";
    }
    if (gesture.axis === "y") swipe = Math.max(0, dy);
    else if (gesture.onArt) dragArt(gesture, dx, e.timeStamp);
  }
  function onTouchEnd(e: TouchEvent) {
    const g = gesture;
    gesture = null;
    if (g?.axis === "x" && g.onArt) releaseArt(g, e.type === "touchcancel");
    // Closing leaves the view where the finger let go; the out transition takes it from there.
    if (g?.axis === "y" && swipe > CLOSE_SWIPE_PX) close();
    else swipe = 0;
  }

  // --- cover swipe: left plays the next track, right the previous one (no restart) ----------

  const canSkip = (dx: number) =>
    dx < 0
      ? Q.next(player.queue, false) !== null
      : Q.prev(player.queue).pos !== player.queue.pos;

  const artTransform = (x: number, w: number) => (x ? `translateX(${x}px) rotate(${(x / w) * 5}deg)` : "");

  function dragArt(g: Gesture, dx: number, t: number) {
    if (!art) return;
    const w = art.offsetWidth;
    g.dx = canSkip(dx) ? dx : resist(dx, w);
    g.samples.push({ x: dx, t });
    while (g.samples.length > 2 && t - g.samples[0].t > 100) g.samples.shift();
    art.style.transform = artTransform(g.dx, w);
  }

  function velocity(g: Gesture): number {
    const first = g.samples[0];
    const last = g.samples[g.samples.length - 1];
    return first && last && last.t > first.t ? (last.x - first.x) / (last.t - first.t) : 0;
  }

  function animateArt(frames: Keyframe[], options: KeyframeAnimationOptions): Promise<unknown> {
    if (!art) return Promise.resolve();
    // The inline style holds the end state; the animation covers the way there.
    art.style.transform = (frames[frames.length - 1].transform as string) ?? "";
    return art.animate(frames, options).finished.catch(() => {});
  }

  async function releaseArt(g: Gesture, cancelled: boolean) {
    if (!art) return;
    const w = art.offsetWidth;
    const from = artTransform(g.dx, w);
    const v = velocity(g);
    const flicked = Math.abs(v) > SKIP_VELOCITY && Math.sign(v) === Math.sign(g.dx) && Math.abs(g.dx) > 20;
    const skip = !cancelled && g.dx !== 0 && canSkip(g.dx) && (Math.abs(g.dx) > w * SKIP_SHARE || flicked);
    const reduced = !!reducedMotion?.matches;

    if (!skip) {
      // Spring back, with a slight overshoot unless motion is reduced.
      await animateArt([{ transform: from }, { transform: "" }], {
        duration: reduced ? 120 : 320,
        easing: reduced ? "ease-out" : "cubic-bezier(0.3, 1.5, 0.55, 1)",
      });
      return;
    }

    artBusy = true;
    const dir = Math.sign(g.dx);
    if (reduced) {
      // No flying: the cover fades out where it was let go and the new one fades in in place.
      await animateArt([{ transform: from, opacity: 1 }, { transform: from, opacity: 0 }], { duration: 100, fill: "forwards" });
      if (dir < 0) player.next();
      else player.prev({ restart: false });
      art.getAnimations().forEach((a) => a.cancel());
      await animateArt([{ transform: "", opacity: 0 }, { transform: "", opacity: 1 }], { duration: 140 });
    } else {
      // Fly out the side it was thrown to, at least as fast as the finger moved, then let the
      // new cover glide in from the other side.
      const out = dir * (window.innerWidth / 2 + w);
      const duration = Math.min(260, Math.max(120, Math.abs(out - g.dx) / Math.max(Math.abs(v), 1.4)));
      await animateArt([{ transform: from }, { transform: artTransform(out, w) }], { duration, easing: "cubic-bezier(0.3, 0.5, 0.6, 1)" });
      if (dir < 0) player.next();
      else player.prev({ restart: false });
      await animateArt([{ transform: artTransform(-out * 0.6, w) }, { transform: "" }], {
        duration: 300,
        easing: "cubic-bezier(0.2, 0.8, 0.25, 1)",
      });
    }
    artBusy = false;
  }

  function showQueue() {
    // On phones the queue page takes this view's place in the history; wide screens show it beside the page.
    player.queueOpen = true;
    if (player.nowPlayingOpen) close();
  }
</script>

<svelte:window onkeydown={(e) => e.key === "Escape" && close()} />

<div
  class="np"
  role="dialog"
  aria-modal="true"
  aria-label={t("Jetzt läuft")}
  tabindex="-1"
  style:transform={swipe ? `translateY(${swipe}px)` : undefined}
  class:swiping={swipe > 0}
  ontouchstart={onTouchStart}
  ontouchmove={onTouchMove}
  ontouchend={onTouchEnd}
  ontouchcancel={onTouchEnd}
  out:sink
>
  {#if backdrop}
    {#key backdrop}
      <div class="backdrop" class:paused={!player.playing || !motion} style:--speed={motion || 1} aria-hidden="true" transition:fade={{ duration: reducedMotion?.matches ? 0 : BACKDROP_FADE_MS }}>
        <div class="layer a" style:background-image="url({backdrop})" use:keepDrift></div>
        <div class="layer b" style:background-image="url({backdrop})" use:keepDrift></div>
      </div>
    {/key}
  {/if}

  <header>
    <button class="icon-btn" onclick={close} aria-label={t("Schließen")} title={t("Schließen (Esc)")}><Icon name="down" size={24} /></button>
    <div class="source">
      {#if player.source}
        <span class="label">{player.source.kind}</span>
        {#if player.source.path}<a class="name" href={href(player.source.path)}>{player.source.name}</a>
        {:else}<span class="name">{player.source.name}</span>{/if}
      {:else}
        <span class="label">{t("Jetzt läuft")}{#if player.radio} {t("· Radio")}{/if}</span>
      {/if}
      {#if devices.target}<span class="remote">{target()?.name ? t("Auf {device}", { device: target()!.name }) : t("Auf anderem Gerät")}</span>{/if}
    </div>
    {#if others().length || devices.target}
      <button class="icon-btn" class:on={!!devices.target} onclick={() => (devices.picker = true)} aria-label={t("Gerät steuern")} title={t("Gerät steuern")}><Icon name="devices" size={20} /></button>
    {/if}
    <button class="icon-btn" onclick={showQueue} aria-label={t("Warteschlange")} title={t("Warteschlange")}><Icon name="queue" size={20} /></button>
  </header>

  {#if track}
    <div class="body">
      <div class="art" bind:this={art}><Cover hash={track.cover} size={600} alt={t("Cover von {album}", { album: track.album ?? "" })} /></div>

      <div class="info">
        <div class="meta">
          <h2 title={track.title}>{track.title}</h2>
          <div class="artist"><ArtistLinks {track} /></div>
          <a class="album" href={href(`/albums/${track.album_id}`)}>{track.album}</a>
        </div>
        <Heart {track} size={22} />
        <button class="icon-btn" aria-label={t("Mehr zu {title}", { title: track.title })} title={t("Mehr")} onclick={(e) => openTrackMenu(e, [track])}><Icon name="more" size={22} /></button>
      </div>

      <div class="transport">
        <div class="seek">
          <input
            type="range"
            min="0"
            {max}
            step="0.1"
            value={shown}
            style:--p="{progress}%"
            aria-label={t("Position")}
            aria-valuetext={t("{pos} von {total}", { pos: duration(shown * 1000), total: duration(player.duration * 1000) })}
            oninput={(e) => (dragging = Number(e.currentTarget.value))}
            onchange={(e) => {
              player.seek(Number(e.currentTarget.value));
              dragging = null;
            }}
          />
          <div class="times"><span>{duration(shown * 1000)}</span><span>{duration(player.duration * 1000)}</span></div>
        </div>

        <div class="controls">
          <button class="icon-btn" class:on={player.queue.shuffle} onclick={() => player.toggleShuffle()} disabled={player.radio} title={player.radio ? t("Radio hat schon eine eigene Reihenfolge") : t("Zufallswiedergabe")} aria-pressed={player.queue.shuffle} aria-label={t("Zufallswiedergabe")}>
            <Icon name="shuffle" size={22} />
          </button>
          <button class="icon-btn big" onclick={() => player.prev()} aria-label={t("Zurück")}><Icon name="prev" size={28} /></button>
          <button class="playpause" onclick={() => player.toggle()} aria-label={player.playing ? "Pause" : "Abspielen"}>
            {#if player.buffering && player.playing}<span class="spin" aria-hidden="true"></span>{/if}
            <Icon name={player.playing ? "pause" : "play"} size={30} />
          </button>
          <button class="icon-btn big" onclick={() => player.next()} aria-label={t("Weiter")}><Icon name="next" size={28} /></button>
          <button class="icon-btn repeat" class:on={player.queue.repeat !== "off"} onclick={() => player.cycleRepeat()} aria-label={t(REPEAT_LABELS[player.queue.repeat])} title={t("Wiederholen")}>
            <Icon name="repeat" size={22} />
            {#if player.queue.repeat === "one"}<span class="one">1</span>{/if}
          </button>
        </div>

        <div class="volume" class:remote={!!devices.target}>
          <button class="icon-btn" onclick={() => player.setMuted(!player.muted)} aria-label={player.muted ? "Ton an" : "Stumm"}>
            <Icon name={player.muted || player.volume === 0 ? "mute" : "volume"} size={18} />
          </button>
          <input
            type="range"
            min="0"
            max="1"
            step="0.01"
            value={player.muted ? 0 : player.volume}
            style:--p="{(player.muted ? 0 : player.volume) * 100}%"
            aria-label={t("Lautstärke")}
            oninput={(e) => player.setVolume(Number(e.currentTarget.value))}
          />
        </div>
      </div>
      {#if player.error}<p class="error" role="status">{player.error}</p>{/if}
    </div>
  {:else}
    <p class="idle">{t("Nichts in der Warteschlange")}</p>
  {/if}
</div>

<style>
  .np {
    position: fixed;
    inset: var(--frame-top, 0px) 0 0 0;
    z-index: 30;
    display: flex;
    flex-direction: column;
    background: var(--bg);
    overflow: hidden auto;
    padding: env(safe-area-inset-top) 0 env(safe-area-inset-bottom);
    animation: rise 0.22s ease-out;
    transition: transform 0.2s ease-out;
  }
  .np.swiping {
    transition: none;
  }
  @keyframes rise {
    from {
      transform: translateY(40px);
      opacity: 0;
    }
  }
  /* Two blurred copies of the cover drift, turn and breathe against each other very slowly, so
     the colours flow like a calm visualisation. Only transforms animate, so the blur is not
     recomputed per frame. It rests while playback is paused. */
  .backdrop {
    position: absolute;
    inset: 0;
    overflow: hidden;
    opacity: 0.4;
    pointer-events: none;
  }
  .layer {
    position: absolute;
    inset: -25%;
    background-size: cover;
    background-position: center;
    filter: blur(56px) saturate(1.4);
    will-change: transform;
    animation: drift-a calc(30s / var(--speed, 1)) ease-in-out infinite alternate;
  }
  .layer.b {
    opacity: 0.6;
    animation: drift-b calc(39s / var(--speed, 1)) ease-in-out infinite alternate;
  }
  .paused .layer {
    animation-play-state: paused;
  }
  @keyframes drift-a {
    from {
      transform: translate(-4%, -3%) rotate(-6deg) scale(1.05);
    }
    to {
      transform: translate(4%, 3%) rotate(8deg) scale(1.2);
    }
  }
  /* Mirrored and turned, so its colours land in different places than layer a. */
  @keyframes drift-b {
    from {
      transform: translate(5%, 2%) rotate(180deg) scale(-1.2, 1.2);
    }
    to {
      transform: translate(-3%, -4%) rotate(160deg) scale(-1.05, 1.05);
    }
  }
  header,
  .body,
  .idle {
    position: relative;
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 16px;
  }
  .source {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
  }
  .label {
    color: var(--text-muted);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }
  .name {
    max-width: 100%;
    color: var(--text);
    font-weight: 600;
    font-size: 0.92rem;
    text-decoration: none;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  a.name:hover {
    text-decoration: underline;
  }
  .remote {
    max-width: 100%;
    color: var(--accent);
    font-size: 0.8rem;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .body {
    flex: 1;
    width: min(440px, 100%);
    margin: 0 auto;
    padding: 8px 24px 28px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 22px;
  }
  .art {
    width: min(100%, 46dvh);
    margin: 0 auto;
    box-shadow: 0 24px 60px rgb(0 0 0 / 0.4);
    border-radius: var(--radius-sm);
  }
  .info {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .meta {
    flex: 1;
    min-width: 0;
  }
  h2 {
    margin: 0 0 4px;
    font-size: 1.4rem;
    letter-spacing: -0.01em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .meta a,
  .artist {
    display: block;
    color: var(--text-muted);
    text-decoration: none;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .meta a:hover {
    color: var(--text);
  }
  .meta .album {
    font-size: 0.88rem;
    color: var(--text-faint);
  }
  .seek input {
    width: 100%;
    display: block;
  }
  .times {
    display: flex;
    justify-content: space-between;
    margin-top: 4px;
    color: var(--text-muted);
    font-size: 0.8rem;
    font-variant-numeric: tabular-nums;
  }
  .controls {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .icon-btn.big {
    width: 52px;
    height: 52px;
    color: var(--text);
  }
  .playpause {
    position: relative;
    width: 68px;
    height: 68px;
    border-radius: 50%;
    border: 0;
    display: grid;
    place-items: center;
    background: var(--text);
    color: var(--bg);
    cursor: pointer;
  }
  .spin {
    position: absolute;
    inset: -5px;
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
    right: 4px;
    bottom: 3px;
    font-size: 0.6rem;
    font-weight: 700;
  }
  .volume {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .volume input {
    flex: 1;
  }
  .error {
    margin: 0;
    text-align: center;
    color: var(--danger);
    font-size: 0.88rem;
  }
  .idle {
    margin: auto;
    color: var(--text-muted);
  }
  .transport {
    display: flex;
    flex-direction: column;
    gap: 22px;
  }
  /* Desktop: everything fits the window; the cover takes the height that is left, and seek bar,
     controls and volume share one row across the full width. */
  @media (min-width: 900px) {
    .np {
      overflow: hidden;
    }
    .body {
      width: 100%;
      min-height: 0;
      padding: 0 32px 24px;
      gap: 20px;
    }
    .art {
      flex: 1 1 0;
      min-height: 0;
      width: auto;
      max-width: 100%;
      aspect-ratio: 1;
    }
    .info {
      width: min(640px, 100%);
      margin: 0 auto;
    }
    .transport {
      flex-direction: row;
      align-items: center;
      gap: 28px;
    }
    .controls {
      order: -1;
      gap: 6px;
    }
    .playpause {
      width: 56px;
      height: 56px;
    }
    .seek {
      flex: 1;
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .times {
      display: contents;
    }
    .times span:first-child {
      order: -1;
    }
    .volume {
      width: 180px;
    }
  }
  /* Phones set the volume with their own buttons, except while they steer another device:
     a web page cannot take over the volume buttons. */
  @media (hover: none) and (pointer: coarse) {
    .volume:not(.remote) {
      display: none;
    }
  }
  /* Phones swipe the cover sideways to skip; vertical scrolling stays with the browser. */
  @media (max-width: 899px) {
    .art {
      touch-action: pan-y;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .np,
    .layer {
      animation: none;
    }
  }
</style>
