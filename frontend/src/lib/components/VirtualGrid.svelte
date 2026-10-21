<script lang="ts">
  // Cover grid on top of VirtualList: as many columns as fit, one virtual row per grid row.
  import type { Snippet } from "svelte";
  import VirtualList from "./VirtualList.svelte";

  let {
    count,
    minCell = 168,
    gap = 20,
    textHeight = 56,
    cell,
    onrange,
    header,
  }: {
    count: number;
    minCell?: number;
    gap?: number;
    textHeight?: number;
    cell: Snippet<[number]>;
    onrange?: (start: number, end: number) => void;
    header?: Snippet;
  } = $props();

  let width = $state(0);
  const padding = 24;
  const inner = $derived(Math.max(0, width - 2 * padding));
  const cols = $derived(Math.max(2, Math.floor((inner + gap) / (minCell + gap))));
  const cellWidth = $derived((inner - gap * (cols - 1)) / cols);
  const rowHeight = $derived(Math.max(1, Math.round(cellWidth + textHeight + gap)));
  const rows = $derived(Math.ceil(count / cols));
</script>

<div class="grid-host" bind:clientWidth={width}>
  {#if width > 0}
    <VirtualList
      count={rows}
      {rowHeight}
      overscan={2}
      {header}
      label="Raster"
      onrange={(s, e) => onrange?.(s * cols, Math.min(count, e * cols))}
    >
      {#snippet row(r)}
        <div class="grid-row" style:grid-template-columns="repeat({cols}, 1fr)" style:gap="{gap}px" style:padding="0 {padding}px">
          {#each { length: cols } as _, c}
            {#if r * cols + c < count}
              <div class="cell">{@render cell(r * cols + c)}</div>
            {/if}
          {/each}
        </div>
      {/snippet}
    </VirtualList>
  {/if}
</div>

<style>
  .grid-host {
    height: 100%;
  }
  .grid-row {
    display: grid;
  }
  .cell {
    min-width: 0;
  }
</style>
