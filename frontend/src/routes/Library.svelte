<script lang="ts">
  // The library: all titles, all albums or all artists, switched by tabs, narrowed by one filter
  // that stays when switching. Tab and filter live in the URL (?tab=albums&q=…). Matches outside
  // the open tab show up as "Auch gefunden" chips instead of being mixed into the list.
  import { get, type Album, type Artist, type Letter, type Page, type Track } from "../lib/api";
  import AlbumCard from "../lib/components/AlbumCard.svelte";
  import ArtistCard from "../lib/components/ArtistCard.svelte";
  import FilterField from "../lib/components/FilterField.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import TrackRow from "../lib/components/TrackRow.svelte";
  import VirtualGrid from "../lib/components/VirtualGrid.svelte";
  import VirtualList from "../lib/components/VirtualList.svelte";
  import { plural } from "../lib/format";
  import { PagedList } from "../lib/paged.svelte";
  import { player } from "../lib/player.svelte";
  import { href, navigate, router } from "../lib/router.svelte";

  type Tab = "tracks" | "albums" | "artists";
  const TABS: Tab[] = ["tracks", "albums", "artists"];
  const TRACK_SORTS = { title: "Titel", added: "Neu hinzugefügt", year: "Jahr" } as const;
  const ALBUM_SORTS = { title: "Titel", artist: "Künstler", year: "Jahr", added: "Neu hinzugefügt" } as const;
  type TrackSort = keyof typeof TRACK_SORTS;
  type AlbumSort = keyof typeof ALBUM_SORTS;
  const ARTIST_ROLES = { album: "Album-Künstler", all: "Alle" } as const;
  type ArtistRole = keyof typeof ARTIST_ROLES;
  const TAB_LABELS: Record<Tab, string> = { tracks: "Titel", albums: "Alben", artists: "Künstler" };
  const countLabel = (t: Tab, n: number) =>
    t === "tracks" ? plural(n, "Titel", "Titel") : t === "albums" ? plural(n, "Album", "Alben") : plural(n, "Künstler", "Künstler");
  const MIN_FILTER = 2; // the search index needs two characters

  function stored(key: string): string | null {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  }
  function store(key: string, value: string) {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* private mode */
    }
  }

  const tab = $derived.by<Tab>(() => {
    const t = router.route.query.get("tab") ?? stored("audium.library.tab");
    return TABS.find((x) => x === t) ?? "tracks";
  });
  const q = $derived(router.route.query.get("q")?.trim() ?? "");
  const filter = $derived(q.length >= MIN_FILTER ? q : "");

  function setParams(changes: Record<string, string>) {
    const params = new URLSearchParams(router.route.query);
    for (const [k, v] of Object.entries(changes)) {
      if (v) params.set(k, v);
      else params.delete(k);
    }
    const s = params.toString();
    navigate(`/library${s ? `?${s}` : ""}`, { replace: true });
  }

  function showTab(t: Tab) {
    store("audium.library.tab", t);
    setParams({ tab: t });
  }

  let trackSort = $state<TrackSort>((stored("audium.tracks.sort") as TrackSort) || "title");
  let albumSort = $state<AlbumSort>((stored("audium.albums.sort") as AlbumSort) || "title");
  $effect(() => store("audium.tracks.sort", trackSort));
  $effect(() => store("audium.albums.sort", albumSort));
  let artistRole = $state<ArtistRole>(stored("audium.artists.role") === "all" ? "all" : "album");
  $effect(() => store("audium.artists.role", artistRole));

  const tracks = $derived(
    tab === "tracks"
      ? new PagedList<Track>((offset, limit, signal) =>
          get<Page<Track>>("/tracks", { sort: trackSort, q: filter, offset, limit }, signal),
        )
      : null,
  );
  const albums = $derived(
    tab === "albums"
      ? new PagedList<Album>((offset, limit, signal) =>
          get<Page<Album>>("/albums", { sort: albumSort, q: filter, offset, limit }, signal),
        )
      : null,
  );
  const artists = $derived(
    tab === "artists"
      ? new PagedList<Artist>((offset, limit, signal) =>
          get<Page<Artist>>("/artists", { role: artistRole, q: filter, offset, limit }, signal),
        )
      : null,
  );
  const total = $derived((tracks ?? albums ?? artists)?.total ?? null);

  // The A-Z index only makes sense for the alphabetical sorts.
  let letters = $state<Letter[] | null>(null);
  $effect(() => {
    letters = null;
    const path =
      tab === "artists" ? "/artists/letters"
      : tab === "tracks" ? (trackSort === "title" ? "/tracks/letters" : null)
      : albumSort === "title" || albumSort === "artist" ? "/albums/letters" : null;
    if (!path) return;
    const params = tab === "artists" ? { role: artistRole, q: filter } : { sort: tab === "albums" ? albumSort : undefined, q: filter };
    const ctrl = new AbortController();
    get<Letter[]>(path, params, ctrl.signal)
      .then((l) => (letters = l))
      .catch(() => {});
    return () => ctrl.abort();
  });

  // Matches outside the open tab: how many in each other tab.
  let also = $state<{ tab: Tab; count: number }[]>([]);
  $effect(() => {
    const f = filter;
    const others = TABS.filter((t) => t !== tab);
    also = [];
    if (!f) return;
    const ctrl = new AbortController();
    Promise.all(others.map((t) => get<Page<unknown>>(`/${t}`, { q: f, limit: 1 }, ctrl.signal)))
      .then((pages) => (also = others.map((t, i) => ({ tab: t, count: pages[i].total ?? 0 })).filter((o) => o.count > 0)))
      .catch(() => {});
    return () => ctrl.abort();
  });

  // Phones: the app's top bar is part of this page and scrolls away with the list; the filter
  // head comes back as soon as one scrolls up, and stays put (scrolls away) when scrolling down.
  // Both float over the list (which starts with a spacer), so typing a filter never remounts them.
  const phoneQuery = typeof matchMedia === "function" ? matchMedia("(max-width: 860px)") : null;
  let phone = $state(phoneQuery?.matches ?? false);
  $effect(() => {
    if (!phoneQuery) return;
    const update = () => (phone = phoneQuery.matches);
    phoneQuery.addEventListener("change", update);
    return () => phoneQuery.removeEventListener("change", update);
  });

  let topHeight = $state(0); // top bar + head
  let headHeight = $state(0);
  let shown = 0; // how much of the head peeks in while scrolled down
  let lastTop = 0;
  let lift = $state(0); // how far the floating top is pushed up

  function onListScroll(e: Event) {
    if (!phone || !(e.target instanceof HTMLElement)) return;
    const top = Math.max(0, e.target.scrollTop);
    shown = Math.min(headHeight, Math.max(0, shown - (top - lastTop)));
    lastTop = top;
    lift = Math.min(top, topHeight - shown);
  }

  // A new list starts at the top.
  $effect(() => {
    void (tracks ?? albums ?? artists);
    lastTop = 0;
    shown = 0;
    lift = 0;
  });

  /** The whole (filtered) track list goes into the queue, so shuffle mixes all of it. On the
   * album and artist tabs the shuffle button plays the titles matching the filter. */
  function playAll(startId: number | null, shuffle?: boolean) {
    const path = `/library?tab=tracks${filter ? `&q=${encodeURIComponent(filter)}` : ""}`;
    const sort = tab === "tracks" ? trackSort : "title";
    player.playPool({ sort, q: filter || undefined }, startId, shuffle, { kind: "Bibliothek", name: filter ? `„${filter}“` : "Alle Titel", path });
  }
</script>

{#snippet spacer()}<div style:height="{topHeight}px"></div>{/snippet}

<div class="lib">
  <div class="top" class:float={phone} style:transform={phone && lift ? `translateY(${-lift}px)` : undefined} bind:clientHeight={topHeight}>
    {#if phone}
      <div class="brand">
        <a class="logo" href={href("/")} aria-label="audium Start">
          <svg viewBox="0 0 64 64" width="24" height="24" aria-hidden="true"><g fill="currentColor"><rect x="14" y="26" width="6" height="12" rx="3" /><rect x="24" y="18" width="6" height="28" rx="3" /><rect x="34" y="12" width="6" height="40" rx="3" /><rect x="44" y="22" width="6" height="20" rx="3" /></g></svg>
          <span>audium</span>
        </a>
      </div>
    {/if}
    <div class="head" bind:clientHeight={headHeight}>
      <div class="title">
        <h1>Bibliothek</h1>
        {#if total !== null}
          <span class="count">{countLabel(tab, total)}</span>
        {/if}
        <button class="btn shuffle" disabled={total === 0} onclick={() => playAll(null, true)} title={filter ? `Titel zu „${filter}“ zufällig abspielen` : "Ganze Bibliothek zufällig abspielen"}>
          <Icon name="shuffle" size={18} /> Zufällig
        </button>
      </div>
      <FilterField query={q} placeholder="{TAB_LABELS[tab]} filtern" onchange={(v) => setParams({ q: v })} />
      <div class="bar">
        <div class="segmented" role="tablist" aria-label="Ansicht">
          {#each TABS as t (t)}
            <button role="tab" aria-selected={tab === t} class:on={tab === t} onclick={() => showTab(t)}>{TAB_LABELS[t]}</button>
          {/each}
        </div>
        <label class="sort">
          <span class="sr-only">Sortierung</span>
          {#if tab === "tracks"}
            <select bind:value={trackSort}>
              {#each Object.entries(TRACK_SORTS) as [key, label] (key)}<option value={key}>{label}</option>{/each}
            </select>
          {:else if tab === "albums"}
            <select bind:value={albumSort}>
              {#each Object.entries(ALBUM_SORTS) as [key, label] (key)}<option value={key}>{label}</option>{/each}
            </select>
          {:else}
            <select bind:value={artistRole}>
              {#each Object.entries(ARTIST_ROLES) as [key, label] (key)}<option value={key}>{label}</option>{/each}
            </select>
          {/if}
        </label>
      </div>
      {#if also.length}
        <div class="also">
          <span class="also-label">Auch gefunden:</span>
          {#each also as o (o.tab)}
            <button class="chip" onclick={() => showTab(o.tab)}>{countLabel(o.tab, o.count)}</button>
          {/each}
        </div>
      {/if}
    </div>
  </div>

  <div class="list" class:under={phone} style:--covered="{phone ? topHeight - lift : 0}px" onscrollcapture={onListScroll}>
    {#if total === 0}
      {#if phone}{@render spacer()}{/if}
      <p class="empty">
        {#if filter}Keine {TAB_LABELS[tab]} für „{filter}“.
        {:else}Noch keine {TAB_LABELS[tab]}. Läuft der erste Scan noch?{/if}
      </p>
    {:else if tracks}
      {#key tracks}
        <VirtualList count={tracks.total ?? 0} rowHeight={56} onrange={(s, e) => tracks.ensure(s, e)} label="Titel" {letters} header={phone ? spacer : undefined} keep="library:tracks:{trackSort}:{filter}">
          {#snippet row(i)}
            <div class="pad"><TrackRow track={tracks.get(i)} number={i + 1} onplay={() => { const t = tracks.get(i); if (t) playAll(t.id); }} /></div>
          {/snippet}
        </VirtualList>
      {/key}
    {:else if albums}
      {#key albums}
        <VirtualGrid count={albums.total ?? 0} onrange={(s, e) => albums.ensure(s, e)} {letters} header={phone ? spacer : undefined} keep="library:albums:{albumSort}:{filter}">
          {#snippet cell(i)}
            <AlbumCard album={albums.get(i)} showYear={albumSort === "year"} />
          {/snippet}
        </VirtualGrid>
      {/key}
    {:else if artists}
      {#key artists}
        <VirtualGrid count={artists.total ?? 0} onrange={(s, e) => artists.ensure(s, e)} {letters} header={phone ? spacer : undefined} keep="library:artists:{artistRole}:{filter}">
          {#snippet cell(i)}
            <ArtistCard artist={artists.get(i)} />
          {/snippet}
        </VirtualGrid>
      {/key}
    {/if}
  </div>
</div>

<style>
  .lib {
    position: relative;
    height: 100%;
    display: flex;
    flex-direction: column;
  }
  /* Floating over the list: only the controls take touches, a drag elsewhere scrolls the list. */
  .top.float {
    position: absolute;
    inset: 0 0 auto 0;
    z-index: 3;
    background: var(--bg);
    pointer-events: none;
    will-change: transform;
  }
  .top.float :global(:is(a, button, input, select, label)) {
    pointer-events: auto;
  }
  .brand {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: var(--top-h);
    padding: 0 16px;
  }
  .logo {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--text);
    text-decoration: none;
    font-weight: 650;
    font-size: 1.05rem;
  }
  .head {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 20px 24px 14px;
  }
  h1 {
    margin: 0;
    font-size: 1.7rem;
    letter-spacing: -0.02em;
  }
  .title {
    display: flex;
    align-items: baseline;
    gap: 12px;
  }
  .title .count {
    margin: 0;
  }
  .title .shuffle {
    margin-left: auto;
    align-self: center;
  }
  .bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  /* On phones three tabs and the sort leave little room; the sort gives way. */
  .bar .segmented {
    flex: none;
  }
  .sort {
    display: flex;
    min-width: 0;
  }
  .sort select {
    max-width: 100%;
    text-overflow: ellipsis;
  }
  .also {
    display: flex;
    align-items: center;
    gap: 8px;
    overflow-x: auto;
    scrollbar-width: none;
    margin: 0 -24px;
    padding: 0 24px;
  }
  .also-label {
    flex: none;
    color: var(--text-muted);
    font-size: 0.85rem;
  }
  .chip {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    height: 32px;
    padding: 0 14px;
    border: 1px solid var(--line);
    border-radius: 16px;
    background: none;
    color: var(--text);
    font-size: 0.85rem;
    text-decoration: none;
    white-space: nowrap;
    cursor: pointer;
  }
  .chip:hover {
    background: var(--surface-1);
  }
  .list {
    flex: 1;
    min-height: 0;
  }
  /* The A-Z index keeps to the part of the list the floating top leaves visible. */
  .list.under :global(.index) {
    top: calc(50% + var(--covered) / 2);
    height: min(calc((100% - var(--covered)) * 0.78), 560px);
  }
  .pad {
    height: 100%;
    padding: 0 16px;
  }
  /* Wider panes: the head packs into two rows, then into one, to leave the list the room. */
  .top {
    container-type: inline-size;
  }
  @container (min-width: 580px) {
    .head {
      display: grid;
      grid-template-columns: auto minmax(160px, 1fr) auto;
      grid-template-areas: "title title title" "tabs filter sort" "also also also";
      align-items: center;
      gap: 10px 16px;
      padding: 14px 24px 10px;
    }
    .bar {
      display: contents;
    }
    .title {
      grid-area: title;
    }
    .segmented {
      grid-area: tabs;
    }
    .head > :global(.filter) {
      grid-area: filter;
    }
    .sort {
      grid-area: sort;
    }
    .also {
      grid-area: also;
    }
    h1 {
      font-size: 1.4rem;
    }
  }
  @container (min-width: 900px) {
    .head {
      grid-template-columns: auto auto minmax(160px, 1fr) auto;
      grid-template-areas: "title tabs filter sort" "also also also also";
      column-gap: 20px;
    }
  }
  @media (max-width: 560px) {
    .head {
      padding: 16px 16px 12px;
      gap: 12px;
    }
    h1 {
      font-size: 1.4rem;
    }
    .also {
      margin: 0 -16px;
      padding: 0 16px;
    }
  }
</style>
