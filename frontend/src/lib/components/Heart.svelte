<script lang="ts">
  import { mine, toggleFavoriteOf, type FavoriteKind } from "../mine.svelte";
  import { toast } from "../ui.svelte";

  /** A track's heart (Lieblingssongs) or, with `kind="album"`, an album's (Lieblingsalben). */
  let { track, id, kind = "track", size = 18 }: { track?: { id: number }; id?: number; kind?: FavoriteKind; size?: number } = $props();
  const itemId = $derived(id ?? track?.id ?? 0);
  const on = $derived((kind === "album" ? mine.favoriteAlbums : mine.favoriteTracks).has(itemId));
  const label = $derived(
    kind === "album"
      ? on ? "Aus Lieblingsalben entfernen" : "Zu Lieblingsalben"
      : on ? "Aus Lieblingssongs entfernen" : "Zu Lieblingssongs",
  );

  async function click(e: MouseEvent) {
    e.stopPropagation();
    try {
      await toggleFavoriteOf(kind, itemId);
    } catch {
      toast("Konnte Favorit nicht speichern");
    }
  }
</script>

<button class="icon-btn heart" class:on aria-pressed={on} aria-label={label} title={label} onclick={click}>
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
