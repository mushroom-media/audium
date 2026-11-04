<script lang="ts">
  import { untrack } from "svelte";
  import { get, type Album, type Artist, type SearchResult } from "../lib/api";
  import AlbumCard from "../lib/components/AlbumCard.svelte";
  import Cover from "../lib/components/Cover.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import TrackRow from "../lib/components/TrackRow.svelte";
  import { player } from "../lib/player.svelte";
  import { clearSearches, forgetSearch, recentSearches, rememberSearch, type RecentSearch } from "../lib/recentSearches.svelte";
  import { keepScroll } from "../lib/keepScroll";
  import { href, recallEntry, rememberEntry, router } from "../lib/router.svelte";
  import { t } from "../lib/i18n.svelte";

  const q = $derived(router.route.query.get("q")?.trim() ?? "");
  let result = $state<SearchResult | null>(untrack(() => recallEntry(`search:${q}`)) ?? null);
  let loading = $state(false);

  $effect(() => {
    const query = q;
    if (query.length < 2) {
      result = null;
      return;
    }
    const ctrl = new AbortController();
    loading = true;
    get<SearchResult>("/search", { q: query, limit: 24 }, ctrl.signal)
      .then((r) => {
        result = r;
        rememberEntry(`search:${query}`, r);
      })
      .catch(() => {})
      .finally(() => (loading = false));
    return () => ctrl.abort();
  });

  const nothing = $derived(result && !result.tracks.length && !result.albums.length && !result.artists.length);

  // Opening an artist or album remembers that; playing a title remembers the query.
  const openedArtist = (a: Artist) => rememberSearch({ kind: "artist", id: a.id, name: a.name, cover: a.cover });
  const openedAlbum = (a: Album) => rememberSearch({ kind: "album", id: a.id, title: a.title, artist: a.artist, cover: a.cover });

  function recentHref(e: RecentSearch): string {
    if (e.kind === "artist") return href(`/artists/${e.id}`);
    if (e.kind === "album") return href(`/albums/${e.id}`);
    return href(`/search?q=${encodeURIComponent(e.q)}`);
  }
</script>

<div class="page" use:keepScroll>
  <div class="toolbar"><h1>{q ? t("„{filter}“", { filter: q }) : t("Suche")}</h1></div>
  {#if q.length < 2}
    {#if recentSearches.items.length}
      <div class="recent-head">
        <h2 class="section">{t("Zuletzt gesucht")}</h2>
        <button class="link" onclick={clearSearches}>{t("Alle löschen")}</button>
      </div>
      <ul class="recent">
        {#each recentSearches.items as e (e.kind === "query" ? `q:${e.q}` : `${e.kind}:${e.id}`)}
          <li>
            <a href={recentHref(e)} onclick={() => rememberSearch(e)}>
              {#if e.kind === "query"}
                <span class="thumb icon" aria-hidden="true"><Icon name="search" size={20} /></span>
                <span class="text"><span class="name">{e.q}</span></span>
              {:else if e.kind === "artist"}
                <span class="thumb"><Cover hash={e.cover} size={64} round /></span>
                <span class="text"><span class="name">{e.name}</span><span class="sub">{t("Künstler|einzeln")}</span></span>
              {:else}
                <span class="thumb"><Cover hash={e.cover} size={64} /></span>
                <span class="text"><span class="name">{e.title}</span><span class="sub">{t("Album")} · {e.artist}</span></span>
              {/if}
            </a>
            <button class="icon-btn" aria-label={t("Aus dem Verlauf entfernen")} title={t("Entfernen")} onclick={() => forgetSearch(e)}><Icon name="close" size={18} /></button>
          </li>
        {/each}
      </ul>
    {:else}
      <p class="empty">{t("Suche nach Titeln, Künstlern und Alben.")}</p>
    {/if}
  {:else if nothing && !loading}
    <p class="empty">{t("Nichts gefunden.")}</p>
  {:else if result}
    {#if result.artists.length}
      <h2 class="section">{t("Künstler")}</h2>
      <div class="artists" use:keepScroll={"artists"}>
        {#each result.artists as a (a.id)}
          <a class="artist" href={href(`/artists/${a.id}`)} onclick={() => openedArtist(a)}>
            <Cover hash={a.cover} size={256} round />
            <span>{a.name}</span>
          </a>
        {/each}
      </div>
    {/if}
    {#if result.albums.length}
      <h2 class="section">{t("Alben")}</h2>
      <div class="grid">
        {#each result.albums.slice(0, 12) as album (album.id)}
          <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
          <div onclick={() => openedAlbum(album)}><AlbumCard {album} /></div>
        {/each}
      </div>
    {/if}
    {#if result.tracks.length}
      <h2 class="section">{t("Titel")}</h2>
      <div class="tracks">
        {#each result.tracks as track, i (track.id)}
          <div class="row-h">
            <TrackRow
              {track}
              number={i + 1}
              onplay={() => {
                if (!result) return;
                rememberSearch({ kind: "query", q });
                player.playTracks(result.tracks, i, undefined, { kind: t("Suche"), name: t("„{filter}“", { filter: q }), path: `/search?q=${encodeURIComponent(q)}` });
              }}
            />
          </div>
        {/each}
      </div>
    {/if}
  {/if}
</div>

<style>
  .section {
    font-size: 1.05rem;
    margin: 24px 24px 12px;
  }
  .recent-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    padding-right: 24px;
  }
  .recent-head .section {
    margin-top: 4px;
  }
  .link {
    border: 0;
    background: none;
    color: var(--text-muted);
    font-size: 0.85rem;
    cursor: pointer;
    padding: 4px;
  }
  .link:hover {
    color: var(--text);
  }
  .recent {
    list-style: none;
    margin: 0;
    padding: 0 16px 32px;
    max-width: 720px;
  }
  .recent li {
    display: flex;
    align-items: center;
    gap: 4px;
    border-radius: var(--radius-sm);
  }
  .recent li:hover {
    background: var(--surface-1);
  }
  .recent a {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 8px;
    color: inherit;
    text-decoration: none;
  }
  .thumb {
    width: 44px;
    flex: none;
  }
  .thumb.icon {
    height: 44px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: var(--surface-2);
    color: var(--text-muted);
  }
  .text {
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .name,
  .sub {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .name {
    font-weight: 500;
  }
  .sub {
    color: var(--text-muted);
    font-size: 0.85rem;
  }
  .recent .icon-btn {
    flex: none;
    margin-right: 4px;
    color: var(--text-muted);
  }
  .artists {
    display: flex;
    gap: 20px;
    overflow-x: auto;
    padding: 0 24px 8px;
  }
  .artist {
    width: 130px;
    flex: none;
    text-align: center;
    color: inherit;
    text-decoration: none;
    font-weight: 500;
  }
  .artist span {
    display: block;
    margin-top: 8px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 20px;
    padding: 0 24px;
  }
  .tracks {
    padding: 0 16px 32px;
  }
  .row-h {
    height: 56px;
  }
  @media (max-width: 560px) {
    .section {
      margin-left: 16px;
      margin-right: 16px;
    }
    .recent-head {
      padding-right: 16px;
    }
    .recent {
      padding: 0 8px 32px;
    }
  }
</style>
