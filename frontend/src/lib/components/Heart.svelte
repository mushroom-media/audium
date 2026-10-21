<script lang="ts">
  import type { Track } from "../api";
  import { mine, toggleFavorite } from "../mine.svelte";
  import { toast } from "../ui.svelte";

  let { track, size = 18 }: { track: Track; size?: number } = $props();
  const on = $derived(mine.favoriteTracks.has(track.id));

  async function click(e: MouseEvent) {
    e.stopPropagation();
    try {
      await toggleFavorite(track);
    } catch {
      toast("Konnte Favorit nicht speichern");
    }
  }
</script>

<button
  class="icon-btn heart"
  class:on
  aria-pressed={on}
  aria-label={on ? "Aus Lieblingssongs entfernen" : "Zu Lieblingssongs"}
  title={on ? "Aus Lieblingssongs entfernen" : "Zu Lieblingssongs"}
  onclick={click}
>
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" fill={on ? "currentColor" : "none"}
    stroke="currentColor" stroke-width="1.7" stroke-linejoin="round">
    <path d="M12 20s-7.5-4.6-9.2-9.3C1.6 7.4 3.7 4.5 6.9 4.5c2 0 3.5 1.1 4.3 2.5h1.6c.8-1.4 2.3-2.5 4.3-2.5 3.2 0 5.3 2.9 4.1 6.2C19.5 15.4 12 20 12 20Z" />
  </svg>
</button>

<style>
  .heart.on {
    color: var(--accent);
  }
</style>
