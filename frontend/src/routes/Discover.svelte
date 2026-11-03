<script lang="ts">
  // Entdecken: what to listen to. "Wieder reinhören" (only when there is something), the broad
  // genres as tiles (all of them under "Alle Genres"), then the published auto-playlists by kind.
  // The admin manages the suggestions in Einstellungen > Auto-Playlists.
  import { get, type AutoPlaylist, type GenreOverview, type Rediscover } from "../lib/api";
  import AutoCard from "../lib/components/AutoCard.svelte";
  import Cover from "../lib/components/Cover.svelte";
  import GenreTile from "../lib/components/GenreTile.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import { ago } from "../lib/format";
  import { ORIGINS } from "../lib/origin";
  import { keepScroll } from "../lib/keepScroll";
  import { href, recallEntry, rememberEntry } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";

  const MAX_GENRE_TILES = 10;
  const isAdmin = $derived(session.user?.role === "admin");

  let rediscover = $state<Rediscover[]>(recallEntry("discover:rediscover") ?? []);
  let genres = $state<GenreOverview | null>(recallEntry("discover:genres") ?? null);
  let lists = $state<AutoPlaylist[] | null>(recallEntry("discover:lists") ?? null);
  let filter = $state(recallEntry<string>("discover:filter") ?? "");

  $effect(() => {
    rememberEntry("discover:filter", filter);
  });

  $effect(() => {
    const ctrl = new AbortController();
    get<Rediscover[]>("/discover/rediscover", undefined, ctrl.signal).then(
      (r) => {
        rediscover = r;
        rememberEntry("discover:rediscover", r);
      },
      () => {},
    );
    get<GenreOverview>("/discover/genres", undefined, ctrl.signal).then(
      (g) => {
        genres = g;
        rememberEntry("discover:genres", g);
      },
      (e) => {
        if (e.name !== "AbortError") genres ??= { families: [], others: [] };
      },
    );
    // Admins get every status from this endpoint; the page shows what everybody sees.
    get<AutoPlaylist[]>("/autoplaylists", undefined, ctrl.signal).then(
      (l) => {
        lists = l.filter((a) => (a.status ?? "published") === "published");
        rememberEntry("discover:lists", lists);
      },
      () => {},
    );
    return () => ctrl.abort();
  });

  // Genre playlists live in the tiles and under "Alle Genres".
  const isGenre = (a: AutoPlaylist) => a.key.startsWith("genre:") || a.key.startsWith("family:");
  const GROUPS: { title: string; test: (a: AutoPlaylist) => boolean }[] = [
    { title: "Stimmung & Aktivität", test: (a) => a.generator === "rule" },
    { title: "Mixe aus deiner Bibliothek", test: (a) => a.generator === "cluster" },
    { title: "Klang-Mixe", test: (a) => a.generator === "sound" && !isGenre(a) },
    { title: "Eigene Regeln", test: (a) => a.generator === "custom" },
    { title: "Stile (Klangerkennung)", test: (a) => a.key.startsWith("style:") },
    { title: "Jahrzehnte", test: (a) => a.key.startsWith("decade:") },
    { title: "Genre & Jahrzehnt", test: (a) => a.key.startsWith("genre-decade:") },
  ];
  const grouped = (a: AutoPlaylist) => GROUPS.some((g) => g.test(a));

  // Every word must appear in the name (case and accents ignored), like the library search.
  const fold = (s: string) => s.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const shown = $derived.by(() => {
    const rest = lists?.filter((a) => !isGenre(a)) ?? null;
    const words = fold(filter).split(/\s+/).filter(Boolean);
    if (!rest || !words.length) return rest;
    return rest.filter((a) => words.every((w) => fold(a.name).includes(w)));
  });

  const tiles = $derived(genres?.families.slice(0, MAX_GENRE_TILES) ?? []);
  const allGenres = $derived((genres?.families.length ?? 0) + (genres?.others.length ?? 0));
</script>

<div class="page" use:keepScroll>
  <div class="toolbar">
    <div>
      <h1>Entdecken</h1>
      <p class="count">Automatisch zusammengestellt aus deiner Bibliothek – ohne Cloud.</p>
    </div>
    {#if isAdmin}
      <a class="btn ghost" href={href("/settings/autoplaylists")}><Icon name="settings" size={18} /> Verwalten</a>
    {/if}
  </div>

  {#if rediscover.length}
    <section>
      <div class="section-head"><h2>Wieder reinhören</h2></div>
      <div class="row" use:keepScroll={"rediscover"}>
        {#each rediscover as r (`${r.type}:${r.id}`)}
          <a class="card" href={href(r.type === "album" ? `/albums/${r.id}` : `/artists/${r.id}`)}>
            <Cover hash={r.cover} size={256} round={r.type === "artist"} />
            <div class="title">{r.name}</div>
            <div class="sub">{r.type === "album" ? r.subtitle : "Künstler"} · zuletzt {ago(r.last_played)}</div>
          </a>
        {/each}
      </div>
    </section>
  {/if}

  {#if tiles.length}
    <section>
      <div class="section-head">
        <h2>Genres</h2>
        {#if allGenres > tiles.length || genres?.families.some((f) => f.genres.length > 1)}
          <a href={href("/genres")}>Alle Genres <Icon name="chevron" size={14} /></a>
        {/if}
      </div>
      <div class="tiles">
        {#each tiles as f (f.name)}<GenreTile playlist={f.playlist} label={f.name} />{/each}
      </div>
    </section>
  {/if}

  {#if lists?.some((a) => !isGenre(a))}
    <label class="filter">
      <Icon name="search" size={16} />
      <span class="sr-only">Playlists filtern</span>
      <input type="search" placeholder="Filtern, z. B. Workout oder 90er" bind:value={filter} autocomplete="off" autocapitalize="off" spellcheck="false" />
    </label>
  {/if}

  {#if lists === null || genres === null}
    <p class="empty">Lädt …</p>
  {:else if !tiles.length && !lists.length && !rediscover.length}
    <p class="empty">
      Noch nichts zu entdecken. Genres erscheinen nach dem ersten Scan, Mixe und Stimmungen nach der Audioanalyse{isAdmin ? " – und wenn du sie unter Einstellungen > Auto-Playlists veröffentlichst" : ", sobald der Admin sie veröffentlicht"}.
    </p>
  {:else if shown && filter.trim() && !shown.length}
    <p class="empty">Keine Playlist passt zu „{filter.trim()}“.</p>
  {:else if shown?.length}
    {#each [...GROUPS, { title: "Weitere", test: (a: AutoPlaylist) => !grouped(a) }] as g (g.title)}
      {@const items = shown.filter(g.test)}
      {#if items.length}
        <section>
          <div class="section-head"><h2>{g.title}</h2></div>
          <div class="grid">
            {#each items as a (a.id)}<AutoCard playlist={a} />{/each}
          </div>
        </section>
      {/if}
    {/each}
    <ul class="legend" aria-label="Herkunft">
      {#each Object.values(ORIGINS) as o (o.label)}<li title={o.hint}><Icon name={o.icon} size={14} /> {o.label}</li>{/each}
    </ul>
  {/if}
</div>

<style>
  .page {
    padding-bottom: 32px;
  }
  .section-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin: 24px 24px 12px;
  }
  h2 {
    font-size: 1.05rem;
    margin: 0;
  }
  .section-head a {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    color: var(--text-muted);
    font-size: 0.88rem;
    text-decoration: none;
  }
  .section-head a:hover {
    color: var(--text);
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 20px;
    padding: 0 24px;
  }
  /* "Wieder reinhören": one row that scrolls sideways, so it stays small. */
  .row {
    display: grid;
    grid-auto-flow: column;
    grid-auto-columns: 160px;
    gap: 20px;
    padding: 0 24px 6px;
    overflow-x: auto;
    scrollbar-width: thin;
  }
  .toolbar .btn {
    text-decoration: none;
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 14px;
    padding: 0 24px;
  }
  .card {
    color: inherit;
    text-decoration: none;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .card :global(.cover) {
    margin-bottom: 8px;
  }
  .title {
    font-weight: 550;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sub {
    color: var(--text-muted);
    font-size: 0.85rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .filter {
    display: flex;
    align-items: center;
    gap: 8px;
    width: min(360px, calc(100% - 48px));
    height: 36px;
    margin: 28px 24px 0;
    padding: 0 12px;
    border-radius: 18px;
    background: var(--surface-1);
    color: var(--text-muted);
  }
  .filter:focus-within {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }
  .filter input {
    flex: 1;
    min-width: 0;
    border: 0;
    padding: 0;
    background: none;
    color: var(--text);
    font: inherit;
    outline: none;
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 16px;
    list-style: none;
    margin: 28px 24px 0;
    padding: 0;
    color: var(--text-muted);
    font-size: 0.8rem;
  }
  .legend li {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    cursor: help;
  }
  .legend :global(svg) {
    color: var(--accent);
  }
  @media (max-width: 560px) {
    .grid {
      grid-template-columns: repeat(2, 1fr);
      gap: 14px;
      padding: 0 16px;
    }
    .tiles {
      grid-template-columns: repeat(2, 1fr);
      gap: 10px;
      padding: 0 16px;
    }
    .row {
      grid-auto-columns: 42%;
      gap: 14px;
      padding: 0 16px 6px;
    }
    .section-head {
      margin: 20px 16px 10px;
    }
    .filter {
      width: calc(100% - 32px);
      margin: 24px 16px 0;
    }
    .legend {
      margin: 24px 16px 0;
    }
  }
</style>
