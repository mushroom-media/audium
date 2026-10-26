<script lang="ts">
  // Renders only the rows in view (+ overscan). Rows have a fixed height, so the scroll
  // position maps directly to an index and the scrollbar covers the whole list, however long.
  import { untrack, type Snippet } from "svelte";
  import type { Letter } from "../api";
  import { recallScroll, rememberScroll } from "../router.svelte";
  import LetterIndex from "./LetterIndex.svelte";

  // Short lists scroll fine without an A-Z index.
  const MIN_INDEXED_ROWS = 100;

  let {
    count,
    rowHeight,
    overscan = 6,
    row,
    onrange,
    header,
    label = "Liste",
    letters,
    keep,
  }: {
    count: number;
    rowHeight: number;
    overscan?: number;
    row: Snippet<[number]>;
    onrange?: (start: number, end: number) => void;
    header?: Snippet;
    label?: string;
    /** A-Z index: the row each initial starts at (alphabetically sorted lists only). */
    letters?: Letter[] | null;
    /** Remember the scroll position under this id, to come back to it with "back". */
    keep?: string;
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

  // Back on the page: scroll to where it was once the list is long enough (it loads after mounting).
  let restore = untrack(() => (keep ? recallScroll(keep) : 0));
  $effect(() => {
    void count;
    void headerHeight;
    if (!restore || scroller.scrollHeight - scroller.clientHeight < restore) return;
    scroller.scrollTop = restore;
    restore = 0;
  });

  function onScroll() {
    scrollTop = scroller.scrollTop;
    if (keep) rememberScroll(keep, scrollTop);
  }

  export function scrollToIndex(index: number) {
    scroller.scrollTop = headerHeight + index * rowHeight;
  }
</script>

<div class="host">
  <div
    class="scroller"
    bind:this={scroller}
    bind:clientHeight={viewport}
    onscroll={onScroll}
    onpointerdown={() => (restore = 0)}
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
  {#if letters && letters.length > 1 && count >= MIN_INDEXED_ROWS}
    <LetterIndex {letters} onjump={scrollToIndex} />
  {/if}
</div>

<style>
  .host {
    position: relative;
    height: 100%;
  }
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
