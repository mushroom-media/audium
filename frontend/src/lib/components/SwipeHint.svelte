<script lang="ts">
  // The arrow at the window edge while swiping back or forward (swipeNav.svelte.ts).
  import { swipe } from "../swipeNav.svelte";
  import Icon from "./Icon.svelte";
</script>

{#if swipe.dir}
  <div
    class="hint"
    class:forward={swipe.dir === "forward"}
    class:full={swipe.progress >= 1}
    style:--p={swipe.progress}
    aria-hidden="true"
  >
    <Icon name={swipe.dir === "back" ? "back" : "chevron"} size={22} />
  </div>
{/if}

<style>
  .hint {
    position: fixed;
    top: 50%;
    left: 0;
    z-index: 2000;
    width: 44px;
    height: 44px;
    margin-top: -22px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: var(--surface-2, var(--surface-1));
    color: var(--text-muted);
    box-shadow: 0 2px 10px rgb(0 0 0 / 0.3);
    pointer-events: none;
    opacity: calc(0.3 + var(--p) * 0.7);
    transform: translateX(calc(-44px + var(--p) * 60px));
  }
  .hint.forward {
    left: auto;
    right: 0;
    transform: translateX(calc(44px - var(--p) * 60px));
  }
  .hint.full {
    background: var(--accent);
    color: var(--accent-contrast);
  }
</style>
