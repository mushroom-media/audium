<script lang="ts">
  import { get, type Album, type Page } from "../lib/api";
  import AlbumCard from "../lib/components/AlbumCard.svelte";
  import VirtualGrid from "../lib/components/VirtualGrid.svelte";
  import { plural } from "../lib/format";
  import { mine } from "../lib/mine.svelte";
  import { PagedList } from "../lib/paged.svelte";

  // Reload when the set of favorite albums changes (hearts clicked on an album page).
  const list = $derived.by(() => {
    void mine.favoriteAlbums.size;
    return new PagedList<Album>((offset, limit, signal) => get<Page<Album>>("/favorites/album", { offset, limit }, signal));
  });
</script>

{#snippet header()}
  <header class="head">
    <h1>Lieblingsalben</h1>
    {#if list.total !== null}<p class="count">{plural(list.total, "Album", "Alben")}</p>{/if}
    {#if list.total === 0}<p class="empty">Markiere Alben mit dem Herz auf der Albumseite, dann erscheinen sie hier.</p>{/if}
  </header>
{/snippet}

{#key list}
  <VirtualGrid count={list.total ?? 0} onrange={(s, e) => list.ensure(s, e)} {header} keep="favoriteAlbums">
    {#snippet cell(i)}
      <AlbumCard album={list.get(i)} />
    {/snippet}
  </VirtualGrid>
{/key}

<style>
  .head {
    padding: 28px 24px 16px;
  }
  h1 {
    font-size: clamp(1.5rem, 4vw, 2.4rem);
    margin: 0 0 4px;
    letter-spacing: -0.02em;
  }
  .count {
    margin: 0;
    color: var(--text-muted);
  }
  .empty {
    margin: 16px 0 0;
  }
  @media (max-width: 560px) {
    .head {
      padding: 18px 16px 12px;
    }
  }
</style>
