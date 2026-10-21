<script lang="ts">
  import { get, type Artist, type Page } from "../lib/api";
  import Cover from "../lib/components/Cover.svelte";
  import VirtualList from "../lib/components/VirtualList.svelte";
  import { plural } from "../lib/format";
  import { PagedList } from "../lib/paged.svelte";
  import { href } from "../lib/router.svelte";

  let role = $state<"album" | "all">("album");
  const list = $derived(
    new PagedList<Artist>((offset, limit, signal) => get<Page<Artist>>("/artists", { role, offset, limit }, signal)),
  );
</script>

<VirtualList count={list.total ?? 0} rowHeight={64} onrange={(s, e) => list.ensure(s, e)} label="Künstler">
  {#snippet header()}
    <div class="toolbar">
      <div>
        <h1>Künstler</h1>
        {#if list.total !== null}<p class="count">{plural(list.total, "Künstler", "Künstler")}</p>{/if}
      </div>
      <div class="segmented" role="group" aria-label="Filter">
        <button class:on={role === "album"} onclick={() => (role = "album")}>Album-Künstler</button>
        <button class:on={role === "all"} onclick={() => (role = "all")}>Alle</button>
      </div>
    </div>
  {/snippet}
  {#snippet row(i)}
    {@const a = list.get(i)}
    {#if a}
      <a class="artist" href={href(`/artists/${a.id}`)}>
        <div class="avatar"><Cover hash={a.cover} size={64} round /></div>
        <div class="name">{a.name}</div>
        <div class="stats">{plural(a.album_count, "Album", "Alben")} · {plural(a.track_count, "Titel", "Titel")}</div>
      </a>
    {:else}
      <div class="artist" aria-hidden="true"><div class="avatar"><div class="ph"></div></div></div>
    {/if}
  {/snippet}
</VirtualList>

<style>
  .artist {
    display: grid;
    grid-template-columns: 48px minmax(0, 1fr) auto;
    align-items: center;
    gap: 14px;
    height: 100%;
    margin: 0 16px;
    padding: 0 12px;
    border-radius: var(--radius-sm);
    color: inherit;
    text-decoration: none;
  }
  a.artist:hover {
    background: var(--surface-1);
  }
  .avatar {
    width: 48px;
  }
  .ph {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    background: var(--surface-2);
  }
  .name {
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .stats {
    color: var(--text-muted);
    font-size: 0.85rem;
  }
  @media (max-width: 560px) {
    .stats {
      display: none;
    }
  }
</style>
