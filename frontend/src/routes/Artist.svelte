<script lang="ts">
  import { untrack } from "svelte";
  import { get, type Album, type AlbumDetail, type Artist, type Page } from "../lib/api";
  import AlbumCard from "../lib/components/AlbumCard.svelte";
  import Cover from "../lib/components/Cover.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import TrackRow from "../lib/components/TrackRow.svelte";
  import VirtualGrid from "../lib/components/VirtualGrid.svelte";
  import { plural } from "../lib/format";
  import { player } from "../lib/player.svelte";
  import { radioPath } from "../lib/radio";
  import { keepScroll } from "../lib/keepScroll";
  import { pageTitle } from "../lib/headerTitle.svelte";
  import { href, navigate, recallEntry, rememberEntry } from "../lib/router.svelte";
  import { msg, t } from "../lib/i18n.svelte";

  type View = "covers" | "tracks";
  const VIEW_KEY = "audium.artist.view";
  const VIEWS: { key: View; icon: "grid" | "list"; label: string }[] = [
    { key: "covers", icon: "grid", label: msg("Nur Cover") },
    { key: "tracks", icon: "list", label: msg("Cover mit Titeln") },
  ];
  const DETAIL_CONCURRENCY = 4;
  const ROW_H = 52; // .row-h

  let { id }: { id: string } = $props();
  const kept = untrack(() => recallEntry<{ artist: Artist; albums: Album[]; appears: Album[] }>(`artist:${id}`));
  let artist = $state<Artist | null>(kept?.artist ?? null);
  let albums = $state<Album[]>(kept?.albums ?? []);
  // Albums of other artists with tracks by this one: features, compilations
  let appears = $state<Album[]>(kept?.appears ?? []);
  // Track lists of the own albums, fetched in the track view as they come near the screen
  let details = $state<Record<string, AlbumDetail>>(untrack(() => recallEntry(`artist:${id}:details`)) ?? {});
  let error = $state<string | null>(null);
  let view = $state<View>(stored() === "tracks" ? "tracks" : "covers");

  const source = $derived(artist && { kind: t("Künstler|einzeln"), name: artist.name, path: `/artists/${id}` });

  function stored(): string | null {
    try {
      return localStorage.getItem(VIEW_KEY);
    } catch {
      return null;
    }
  }
  function setView(v: View) {
    view = v;
    try {
      localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* private mode */
    }
  }

  $effect(() => {
    const ctrl = new AbortController();
    error = null;
    Promise.all([
      get<Artist>(`/artists/${id}`, undefined, ctrl.signal),
      get<Page<Album>>("/albums", { artist_id: id, sort: "year", limit: 500 }, ctrl.signal),
      get<Page<Album>>("/albums", { appears_on: id, sort: "year", order: "desc", limit: 200 }, ctrl.signal),
    ])
      .then(([a, own, other]) => {
        artist = a;
        albums = own.items;
        appears = other.items;
        rememberEntry(`artist:${id}`, { artist: a, albums: own.items, appears: other.items });
      })
      .catch((e) => e.name !== "AbortError" && (error = e.message));
    return () => ctrl.abort();
  });

  // Track view: an artist can have hundreds of albums, so only the track lists near the screen
  // are fetched and drawn, a few at a time; the others hold their place at their final height.
  let wanted: number[] = [];
  let loading = 0;
  let detailCtrl = new AbortController();
  $effect(() => {
    void id;
    return () => {
      detailCtrl.abort();
      detailCtrl = new AbortController();
      wanted = [];
      loading = 0;
    };
  });

  function want(albumId: number) {
    if (details[albumId] || wanted.includes(albumId)) return;
    wanted.push(albumId);
    pump();
  }

  function pump() {
    while (loading < DETAIL_CONCURRENCY && wanted.length) {
      const albumId = wanted.shift()!;
      const signal = detailCtrl.signal;
      loading++;
      get<AlbumDetail>(`/albums/${albumId}`, undefined, signal)
        .then((d) => {
          details[albumId] = d;
          rememberEntry(`artist:${id}:details`, details);
        })
        .catch((e) => e.name !== "AbortError" && (error = e.message))
        .finally(() => {
          if (signal.aborted) return;
          loading--;
          pump();
        });
    }
  }

  /** Asks for the album's tracks once it is within a screen or so of the visible part. */
  function nearScreen(node: HTMLElement, albumId: number) {
    const io = new IntersectionObserver(
      (entries) => {
        if (!entries.some((e) => e.isIntersecting)) return;
        io.disconnect();
        untrack(() => want(albumId));
      },
      { root: node.closest(".page"), rootMargin: "1200px 0px" },
    );
    io.observe(node);
    return { destroy: () => io.disconnect() };
  }

  function playAll(shuffle: boolean) {
    player.playPool({ artist_id: id, sort: "year", order: "asc" }, null, shuffle, source);
  }

  function playAlbum(d: AlbumDetail, index: number) {
    player.playTracks(d.tracks, index, false, { kind: "Album", name: d.title, path: `/albums/${d.id}`, ref: `album:${d.id}` });
  }
</script>

{#snippet head()}
  {#if artist}
    <header class="hero">
      <div class="avatar"><Cover hash={artist.cover} size={256} round /></div>
      <div>
        <p class="kind">{t("Künstler|einzeln")}</p>
        <h1 use:pageTitle={artist.name}>{artist.name}</h1>
        <p class="stats">{plural(artist.album_count, "Album", "Alben")} · {plural(artist.track_count, "Titel", "Titel")}</p>
        {#if artist.track_count > 0}
          <div class="actions">
            <button class="btn primary" onclick={() => playAll(false)}><Icon name="play" size={18} /> {t("Alle abspielen")}</button>
            <button class="btn square" onclick={() => playAll(true)} title={t("Zufällig abspielen")} aria-label={t("Zufällig abspielen")}><Icon name="shuffle" size={18} /></button>
            <button class="btn" onclick={() => artist && navigate(radioPath("artist", artist.id))}><Icon name="radio" size={18} /> {t("Radio")}</button>
          </div>
        {/if}
      </div>
    </header>
    {#if albums.length}
      <div class="section-bar">
        <h2 class="section">{t("Alben")}</h2>
        <div class="segmented" role="radiogroup" aria-label={t("Ansicht der Alben")}>
          {#each VIEWS as v (v.key)}
            <button role="radio" aria-checked={view === v.key} class:on={view === v.key} title={t(v.label)} aria-label={t(v.label)} onclick={() => setView(v.key)}>
              <Icon name={v.icon} size={16} />
            </button>
          {/each}
        </div>
      </div>
    {/if}
  {/if}
{/snippet}

{#snippet appearsOn()}
  {#if appears.length}
    <section class="appears">
      <h2 class="section">{t("Mitgewirkt auf")}</h2>
      <div class="shelf">
        {#each appears as album (album.id)}<AlbumCard {album} showYear />{/each}
      </div>
    </section>
  {/if}
{/snippet}

{#if artist && !error && albums.length && view === "covers"}
  <!-- An artist can have hundreds of albums (Various Artists): only those in view are drawn. -->
  <div class="fill">
    <VirtualGrid count={albums.length} header={head} footer={appearsOn} keep="artist:{id}">
      {#snippet cell(i)}<AlbumCard album={albums[i]} showYear />{/snippet}
    </VirtualGrid>
  </div>
{:else}
  <div class="page" use:keepScroll>
    {#if error}
      <p class="empty">{error}</p>
    {:else if artist}
      {@render head()}
      {#if albums.length}
        <div class="discography">
          {#each albums as album (album.id)}
            {@const d = details[album.id]}
            <section class="disc-album" use:nearScreen={album.id}>
              <a class="disc-art" href={href(`/albums/${album.id}`)} aria-label={album.title}><Cover hash={album.cover} size={256} alt="" /></a>
              <div class="disc-body">
                <div class="disc-head">
                  <a class="disc-title" href={href(`/albums/${album.id}`)}>{album.title}</a>
                  <p class="disc-meta">
                    {#if album.year}{album.year} · {/if}{plural(album.track_count, "Titel", "Titel")}
                  </p>
                </div>
                <div class="disc-tracks">
                  {#if d}
                    {#each d.tracks as t, i (t.id)}
                      <div class="row-h">
                        <TrackRow track={t} number={t.track_no ?? i + 1} showCover={false} showAlbum={false} linkArtist={false} onplay={() => playAlbum(d, i)} />
                      </div>
                    {/each}
                  {:else}
                    <div style:height="{album.track_count * ROW_H}px">
                      {#each { length: Math.min(album.track_count, 4) } as _, i (i)}
                        <div class="row-h"><TrackRow track={undefined} onplay={() => {}} /></div>
                      {/each}
                    </div>
                  {/if}
                </div>
              </div>
            </section>
          {/each}
        </div>
      {/if}
      {@render appearsOn()}
    {/if}
  </div>
{/if}

<style>
  .hero {
    display: flex;
    align-items: center;
    gap: 28px;
    padding: 32px 24px 8px;
  }
  .avatar {
    width: min(180px, 34vw);
    flex: none;
  }
  .kind {
    margin: 0;
    color: var(--text-muted);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }
  h1 {
    font-size: clamp(1.6rem, 4vw, 3rem);
    margin: 6px 0 6px;
    letter-spacing: -0.02em;
  }
  .stats {
    color: var(--text-muted);
    margin: 0 0 18px;
  }
  .actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
  }
  .section-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin: 28px 24px 14px;
  }
  .section {
    font-size: 1.1rem;
    margin: 0;
  }
  .segmented button {
    display: grid;
    place-items: center;
    padding: 6px 12px;
  }
  .fill {
    height: 100%;
  }
  .discography {
    display: flex;
    flex-direction: column;
    gap: 36px;
    padding: 0 24px 32px;
  }
  /* Desktop: cover on the left, sticky while its tracks scroll past. */
  .disc-album {
    display: grid;
    grid-template-columns: 200px minmax(0, 1fr);
    gap: 28px;
    align-items: start;
  }
  .disc-art {
    position: sticky;
    top: 16px;
    border-radius: var(--radius-sm);
    box-shadow: 0 12px 32px rgb(0 0 0 / 0.3);
  }
  .disc-head {
    margin: 4px 0 8px;
  }
  .disc-title {
    color: var(--text);
    font-weight: 650;
    font-size: 1.15rem;
    text-decoration: none;
  }
  .disc-title:hover {
    text-decoration: underline;
  }
  .disc-meta {
    margin: 4px 0 0;
    color: var(--text-muted);
    font-size: 0.88rem;
  }
  .disc-tracks {
    margin: 0 -8px;
  }
  .row-h {
    height: 52px;
  }
  .appears {
    padding-bottom: 32px;
  }
  .appears .section {
    margin: 28px 24px 14px;
  }
  /* One row that scrolls sideways, so a guest on many albums doesn't push the page long.
     Room below for the scrollbar: in the Linux app (WebKitGTK) it lies over the content. */
  .shelf {
    display: grid;
    grid-auto-flow: column;
    grid-auto-columns: 168px;
    gap: 20px;
    padding: 0 24px 16px;
    overflow-x: auto;
    scrollbar-width: thin;
  }
  @media (max-width: 560px) {
    .appears .section {
      margin: 24px 16px 12px;
    }
    .shelf {
      grid-auto-columns: 140px;
      gap: 14px;
      padding: 0 16px 6px;
    }
    .hero {
      flex-direction: column;
      align-items: flex-start;
      padding: 20px 16px 0;
    }
    .section-bar {
      margin: 24px 16px 12px;
    }
    .discography {
      padding: 0 16px 24px;
      gap: 28px;
    }
    /* Phone: a small cover next to the title, the tracks underneath at full width. */
    .disc-album {
      grid-template-columns: 88px minmax(0, 1fr);
      gap: 4px 14px;
    }
    .disc-art {
      position: static;
      grid-row: 1;
    }
    .disc-body {
      display: contents;
    }
    .disc-head {
      grid-row: 1;
      grid-column: 2;
      align-self: center;
      margin: 0;
    }
    .disc-tracks {
      grid-column: 1 / -1;
      margin: 6px -8px 0;
    }
  }
</style>
