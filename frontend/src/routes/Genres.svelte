<script lang="ts">
  // "Alle Genres": every broad genre with all of its genres, then genres that belong to none.
  import { get, type GenreOverview } from "../lib/api";
  import AutoCard from "../lib/components/AutoCard.svelte";
  import GenreTile from "../lib/components/GenreTile.svelte";
  import { keepScroll } from "../lib/keepScroll";
  import { pageTitle } from "../lib/headerTitle.svelte";
  import { recallEntry, rememberEntry } from "../lib/router.svelte";
  import { t } from "../lib/i18n.svelte";

  let overview = $state<GenreOverview | null>(recallEntry("genres") ?? null);
  $effect(() => {
    const ctrl = new AbortController();
    get<GenreOverview>("/discover/genres", undefined, ctrl.signal)
      .then((o) => {
        overview = o;
        rememberEntry("genres", o);
      })
      .catch(() => {});
    return () => ctrl.abort();
  });
</script>

<div class="page" use:keepScroll>
  <div class="toolbar"><h1 use:pageTitle={t("Alle Genres")}>{t("Alle Genres")}</h1></div>

  {#if overview === null}
    <p class="empty">{t("Lädt …")}</p>
  {:else if !overview.families.length && !overview.others.length}
    <p class="empty">{t("Noch keine Genres. Sie erscheinen nach dem ersten Scan, sobald ein Genre mindestens 30 Titel hat.")}</p>
  {:else}
    {#each overview.families as f (f.name)}
      <section>
        <h2>{f.name}</h2>
        <div class="grid">
          <GenreTile playlist={f.playlist} label={t("Alles aus {name}", { name: f.name })} />
          {#each f.genres as g (g.id)}<AutoCard playlist={g} />{/each}
        </div>
      </section>
    {/each}
    {#if overview.others.length}
      <section>
        <h2>{t("Weitere Genres")}</h2>
        <div class="grid">
          {#each overview.others as g (g.id)}<AutoCard playlist={g} />{/each}
        </div>
      </section>
    {/if}
  {/if}
</div>

<style>
  .page {
    padding-bottom: 32px;
  }
  h2 {
    font-size: 1.05rem;
    margin: 24px 24px 12px;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 20px;
    padding: 0 24px;
    align-items: start;
  }
  /* The family tile spans two columns, as wide as it is tall as two covers. */
  .grid :global(.tile) {
    grid-column: span 2;
  }
  @media (max-width: 560px) {
    .grid {
      grid-template-columns: repeat(2, 1fr);
      gap: 14px;
      padding: 0 16px;
    }
    h2 {
      margin: 20px 16px 10px;
    }
  }
</style>
