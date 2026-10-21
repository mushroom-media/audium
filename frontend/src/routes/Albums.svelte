<script lang="ts">
  import { get, type Album, type Page } from "../lib/api";
  import AlbumCard from "../lib/components/AlbumCard.svelte";
  import VirtualGrid from "../lib/components/VirtualGrid.svelte";
  import { plural } from "../lib/format";
  import { PagedList } from "../lib/paged.svelte";

  const SORTS = { title: "Titel", artist: "Künstler", year: "Jahr", added: "Neu hinzugefügt" } as const;
  type SortKey = keyof typeof SORTS;

  let sort = $state<SortKey>((localStorage.getItem("audium.albums.sort") as SortKey) || "title");
  const list = $derived(
    new PagedList<Album>((offset, limit, signal) => get<Page<Album>>("/albums", { sort, offset, limit }, signal)),
  );

  $effect(() => {
    try {
      localStorage.setItem("audium.albums.sort", sort);
    } catch {
      /* private mode */
    }
  });
</script>

<VirtualGrid count={list.total ?? 0} onrange={(s, e) => list.ensure(s, e)}>
  {#snippet header()}
    <div class="toolbar">
      <div>
        <h1>Alben</h1>
        {#if list.total !== null}<p class="count">{plural(list.total, "Album", "Alben")}</p>{/if}
      </div>
      <label class="select">
        <span class="sr-only">Sortierung</span>
        <select bind:value={sort}>
          {#each Object.entries(SORTS) as [key, label] (key)}<option value={key}>{label}</option>{/each}
        </select>
      </label>
    </div>
    {#if list.total === 0}<p class="empty">Noch keine Alben. Läuft der erste Scan noch?</p>{/if}
  {/snippet}
  {#snippet cell(i)}
    <AlbumCard album={list.get(i)} subtitle={sort === "year" ? "year" : "artist"} />
  {/snippet}
</VirtualGrid>
