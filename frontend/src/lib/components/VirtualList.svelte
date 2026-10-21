<script lang="ts">
  // Renders only the rows in view (+ overscan). Rows have a fixed height, so the scroll
  // position maps directly to an index and the scrollbar covers the whole list, however long.
  import type { Snippet } from "svelte";

  let {
    count,
    rowHeight,
    overscan = 6,
    row,
    onrange,
    header,
    label = "Liste",
  }: {
    count: number;
    rowHeight: number;
    overscan?: number;
    row: Snippet<[number]>;
    onrange?: (start: number, end: number) => void;
    header?: Snippet;
    label?: string;
  } = $props();

  let scroller: HTMLDivElement;
  let scrollTop = $state(0);
  let viewport = $state(800);
  let headerHeight = $state(0);

  const listTop = $derived(Math.max(0, scrollTop - headerHeight));
  const start = $derived(Math.max(0, Math.floor(listTop / rowHeight) - overscan));
  const end = $derived(Math.min(count, Math.ceil((listTop + viewport) / rowHeight) + overscan));
  const indices = $derived(Array.from({ length: Math.max(0, end - start) }, (_, i) => start + i));

  $effect(() => {
    onrange?.(start, end);
  });

  export function scrollToIndex(index: number) {
    scroller.scrollTop = headerHeight + index * rowHeight;
  }
</script>

<div
  class="scroller"
  bind:this={scroller}
  bind:clientHeight={viewport}
  onscroll={() => (scrollTop = scroller.scrollTop)}
  role="list"
  aria-label={label}
>
  {#if header}
    <div bind:clientHeight={headerHeight}>{@render header()}</div>
  {/if}
  <div class="spacer" style:height="{count * rowHeight}px">
    {#each indices as i (i)}
      <div class="row" role="listitem" style:transform="translateY({i * rowHeight}px)" style:height="{rowHeight}px">
        {@render row(i)}
      </div>
    {/each}
  </div>
</div>

<style>
  .scroller {
    height: 100%;
    overflow-y: auto;
    overscroll-behavior: contain;
    contain: strict;
  }
  .spacer {
    position: relative;
  }
  .row {
    position: absolute;
    inset: 0 0 auto 0;
    will-change: transform;
  }
</style>
