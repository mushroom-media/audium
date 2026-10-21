<script lang="ts">
  import { get, type Album, type Page } from "../lib/api";
  import AlbumCard from "../lib/components/AlbumCard.svelte";
  import { href } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";

  let recent = $state<Album[] | null>(null);

  $effect(() => {
    const ctrl = new AbortController();
    get<Page<Album>>("/albums", { sort: "added", limit: 24 }, ctrl.signal)
      .then((p) => (recent = p.items))
      .catch(() => {});
    return () => ctrl.abort();
  });

  const greeting = $derived.by(() => {
    const h = new Date().getHours();
    return h < 11 ? "Guten Morgen" : h < 18 ? "Hallo" : "Guten Abend";
  });
</script>

<div class="page">
  <div class="toolbar"><h1>{greeting}, {session.user?.display_name}</h1></div>
  <div class="section-head">
    <h2>Neu hinzugefügt</h2>
    <a href={href("/albums")}>Alle Alben</a>
  </div>
  {#if recent && recent.length === 0}
    <p class="empty">
      Deine Bibliothek ist noch leer. Der erste Scan läuft im Hintergrund{session.user?.role === "admin"
        ? " – den Fortschritt siehst du in den Einstellungen."
        : "."}
    </p>
  {:else}
    <div class="grid">
      {#each recent ?? Array(12).fill(undefined) as album, i (album?.id ?? `p${i}`)}<AlbumCard {album} />{/each}
    </div>
  {/if}
</div>

<style>
  .section-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin: 12px 24px 14px;
  }
  h2 {
    font-size: 1.1rem;
    margin: 0;
  }
  .section-head a {
    color: var(--text-muted);
    font-size: 0.88rem;
    text-decoration: none;
  }
  .section-head a:hover {
    color: var(--text);
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
    gap: 20px;
    padding: 0 24px 32px;
  }
  @media (max-width: 560px) {
    .grid {
      grid-template-columns: repeat(2, 1fr);
      gap: 14px;
      padding: 0 16px 24px;
    }
  }
</style>
