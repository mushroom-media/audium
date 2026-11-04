<script lang="ts">
  import { get, type Album, type Page } from "../lib/api";
  import AlbumCard from "../lib/components/AlbumCard.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import { pageTitle } from "../lib/headerTitle.svelte";
  import VirtualGrid from "../lib/components/VirtualGrid.svelte";
  import { plural } from "../lib/format";
  import { mine } from "../lib/mine.svelte";
  import { keptList } from "../lib/paged.svelte";
  import { player } from "../lib/player.svelte";
  import { t } from "../lib/i18n.svelte";

  // Reload when the set of favorite albums changes (hearts clicked on an album page).
  const list = $derived.by(() => {
    void mine.favoriteAlbums.size;
    return keptList<Album>("favoriteAlbums", (offset, limit, signal) => get<Page<Album>>("/favorites/album", { offset, limit }, signal));
  });

  /** All titles of all favorite albums, mixed (the pool fetches them in batches while playing). */
  function shuffleAll() {
    player.playPool({ favorite_albums: 1, sort: "year" }, null, true, { kind: "Playlist", name: "Lieblingsalben", path: "/favorites/albums" });
  }
</script>

{#snippet header()}
  <header class="head">
    <h1 use:pageTitle={"Lieblingsalben"}>{t("Lieblingsalben")}</h1>
    {#if list.total !== null}<p class="count">{plural(list.total, "Album", "Alben")}</p>{/if}
    {#if list.total}
      <div class="actions">
        <button class="btn" onclick={shuffleAll} title={t("Alle Titel der Lieblingsalben zufällig abspielen")}>
          <Icon name="shuffle" size={18} /> {t("Zufällig")}
        </button>
      </div>
    {/if}
    {#if list.total === 0}<p class="empty">{t("Markiere Alben mit dem Herz auf der Albumseite, dann erscheinen sie hier.")}</p>{/if}
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
  .actions {
    display: flex;
    gap: 10px;
    margin-top: 14px;
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
