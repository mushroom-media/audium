<script lang="ts">
  import { get, type Page, type Track } from "../lib/api";
  import TrackRow from "../lib/components/TrackRow.svelte";
  import VirtualList from "../lib/components/VirtualList.svelte";
  import { plural } from "../lib/format";
  import { PagedList } from "../lib/paged.svelte";
  import { player } from "../lib/player.svelte";

  const SORTS = { title: "Titel", added: "Neu hinzugefügt", year: "Jahr" } as const;
  type SortKey = keyof typeof SORTS;
  const QUEUE_WINDOW = 300; // "play from here" queues this many following tracks

  let sort = $state<SortKey>("title");
  const list = $derived(
    new PagedList<Track>((offset, limit, signal) => get<Page<Track>>("/tracks", { sort, offset, limit }, signal)),
  );

  async function playFrom(index: number) {
    const tracks = await list.slice(index, QUEUE_WINDOW);
    player.playTracks(tracks, 0);
  }
</script>

<VirtualList count={list.total ?? 0} rowHeight={56} onrange={(s, e) => list.ensure(s, e)} label="Titel">
  {#snippet header()}
    <div class="toolbar">
      <div>
        <h1>Titel</h1>
        {#if list.total !== null}<p class="count">{plural(list.total, "Titel", "Titel")}</p>{/if}
      </div>
      <label class="select">
        <span class="sr-only">Sortierung</span>
        <select bind:value={sort}>
          {#each Object.entries(SORTS) as [key, label] (key)}<option value={key}>{label}</option>{/each}
        </select>
      </label>
    </div>
  {/snippet}
  {#snippet row(i)}
    <div class="pad"><TrackRow track={list.get(i)} number={i + 1} onplay={() => playFrom(i)} /></div>
  {/snippet}
</VirtualList>

<style>
  .pad {
    height: 100%;
    padding: 0 16px;
  }
</style>
