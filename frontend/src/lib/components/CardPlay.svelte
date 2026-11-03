<script lang="ts">
  // The round button on an album or playlist cover. It knows when that list is what plays: then
  // it stays visible and pauses, and after a pause it carries on instead of starting over.
  import { player } from "../player.svelte";
  import Icon from "./Icon.svelte";

  /** `ref`: the source.ref this list plays under (see QueueSource). */
  let { ref, name, start }: { ref: string; name: string; start: () => Promise<void> } = $props();

  /** A list with nothing to play, or a device that does not answer, doesn't leave it on "pause". */
  const START_TIMEOUT_MS = 2500;

  const current = $derived(player.source?.ref === ref);
  // The click shows at once: the tracks still have to be fetched, and with another tab or device
  // playing, its report still has to arrive.
  let starting = $state(false);
  const playing = $derived(starting || (current && player.playing));

  $effect(() => {
    if (starting && current && player.playing) starting = false;
  });

  async function onclick(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    if (starting) return;
    if (current) return player.toggle();
    starting = true;
    try {
      await start();
      setTimeout(() => (starting = false), START_TIMEOUT_MS);
    } catch (err) {
      starting = false;
      throw err;
    }
  }
</script>

<button class="play" class:on={current || starting} aria-label="{name} {playing ? 'pausieren' : 'abspielen'}" {onclick}>
  <Icon name={playing ? "pause" : "play"} size={22} />
</button>

<style>
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
  :global(.card:hover) .play,
  .play:focus-visible,
  .play.on {
    opacity: 1;
    transform: none;
  }
  @media (hover: none) {
    .play {
      display: none;
    }
  }
</style>
