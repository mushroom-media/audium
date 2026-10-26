<script lang="ts">
  import { devices, others } from "../devices.svelte";
  import { duration } from "../format";
  import { player } from "../player.svelte";
  import { href } from "../router.svelte";
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
  function tapNow(e: MouseEvent) {
    if (!track || !phone?.matches || (e.target as Element).closest(".heart")) return;
    e.preventDefault();
    openNowPlaying();
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
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions (cover and title are the keyboard targets) -->
  <div class="now" onclickcapture={tapNow}>
    {#if track}
      <a class="art" href={href(`/albums/${track.album_id}`)} title={track.album} aria-label="Album {track.album} öffnen"><Cover hash={track.cover} size={64} /></a>
      <div class="meta">
        <button class="title" title={track.title} onclick={openNowPlaying}>{track.title}</button>
        <a class="artist" href={href(`/artists/${track.artist_id}`)}>{track.artist}</a>
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
  .artist:hover {
    color: var(--text);
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
      cursor: pointer;
    }
    .meta {
      flex: 1;
    }
  }
</style>
