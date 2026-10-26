<script lang="ts">
  // A playlist's cover: one of the built-in designs, or an image (uploaded / first track).
  import { presetSvg } from "../coverPresets";
  import Cover from "./Cover.svelte";

  let {
    playlist,
    size = 256,
    alt = "",
  }: { playlist: { cover: string | null; cover_preset?: number | null }; size?: 64 | 256 | 600; alt?: string } = $props();

  const svg = $derived(playlist.cover_preset ? presetSvg(playlist.cover_preset) : null);
</script>

{#if svg}
  <div class="preset" role={alt ? "img" : undefined} aria-label={alt || undefined}>
    <!-- Static markup from coverPresets.ts, never user input. -->
    <svg viewBox="0 0 100 100" aria-hidden="true" preserveAspectRatio="xMidYMid slice">{@html svg}</svg>
  </div>
{:else}
  <Cover hash={playlist.cover} {size} {alt} />
{/if}

<style>
  .preset {
    width: 100%;
    aspect-ratio: 1;
    border-radius: var(--radius-sm);
    overflow: hidden;
    background: var(--surface-2);
  }
  svg {
    display: block;
    width: 100%;
    height: 100%;
  }
</style>
