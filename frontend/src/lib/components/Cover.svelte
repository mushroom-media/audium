<script lang="ts">
  import { coverUrl } from "../api";

  let {
    hash,
    size = 256,
    alt = "",
    round = false,
  }: { hash: string | null | undefined; size?: 64 | 256 | 600; alt?: string; round?: boolean } = $props();

  let failed = $state(false);
  // Never ship the original image to a list: 64 px for rows, 256 (600 on hi-dpi) for cards.
  const src = $derived(coverUrl(hash ?? null, size));
  const srcset = $derived(
    hash && size === 256 ? `${coverUrl(hash, 256)} 1x, ${coverUrl(hash, 600)} 2x` : undefined,
  );
  $effect(() => {
    void src;
    failed = false;
  });
</script>

<div class="cover" class:round>
  {#if src && !failed}
    <img {src} {srcset} {alt} loading="lazy" decoding="async" draggable="false" onerror={() => (failed = true)} />
  {:else}
    <div class="placeholder" aria-hidden="true">
      <svg viewBox="0 0 24 24" width="38%" height="38%" fill="none" stroke="currentColor" stroke-width="1.2">
        <circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="2.5" />
      </svg>
    </div>
  {/if}
</div>

<style>
  .cover {
    position: relative;
    width: 100%;
    aspect-ratio: 1;
    border-radius: var(--radius-sm);
    overflow: hidden;
    background: var(--surface-2);
  }
  .round {
    border-radius: 50%;
  }
  img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .placeholder {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    color: var(--text-faint);
  }
</style>
