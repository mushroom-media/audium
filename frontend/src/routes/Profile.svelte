<script lang="ts">
  import { get, type Album, type Page, type Playlist, type Stats } from "../lib/api";
  import AlbumCard from "../lib/components/AlbumCard.svelte";
  import Cover from "../lib/components/Cover.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import PlaylistCover from "../lib/components/PlaylistCover.svelte";
  import TrackRow from "../lib/components/TrackRow.svelte";
  import { plural } from "../lib/format";
  import { mine, newPlaylistFlow } from "../lib/mine.svelte";
  import { player } from "../lib/player.svelte";
  import { href, navigate } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";

  const PERIODS = [
    { key: "month", label: "30 Tage" },
    { key: "year", label: "Dieses Jahr" },
    { key: "all", label: "Insgesamt" },
  ] as const;
  type Period = (typeof PERIODS)[number]["key"];
  const TOP_TRACKS = 10;
  const TOP_CARDS = 6;

  let period = $state<Period>("year");
  let stats = $state<Stats | null>(null);

  // The period starts in the viewer's own time zone, so the server gets a timestamp.
  function since(p: Period): number | undefined {
    if (p === "month") return Date.now() - 30 * 86_400_000;
    if (p === "year") return new Date(new Date().getFullYear(), 0, 1).getTime();
    return undefined;
  }

  $effect(() => {
    const ctrl = new AbortController();
    const s = since(period);
    get<Stats>("/stats", { limit: TOP_TRACKS, ...(s === undefined ? {} : { since: s }) }, ctrl.signal)
      .then((r) => (stats = r))
      .catch(() => {});
    return () => ctrl.abort();
  });

  const minutes = (ms: number) => `${Math.round(ms / 60000).toLocaleString("de-DE")} Min.`;

  function playTop(i: number) {
    if (stats) player.playTracks(stats.tracks.map((e) => e.track), i, false);
  }

  // The newest favorite albums; all of them are on their own page.
  const ALBUM_LIMIT = 12;

  let albums = $state<Album[] | null>(null);
  let albumTotal = $state(0);

  // Reload when the set of favorite albums changes (hearts clicked on an album page).
  $effect(() => {
    void mine.favoriteAlbums.size;
    const ctrl = new AbortController();
    get<Page<Album>>("/favorites/album", { limit: ALBUM_LIMIT }, ctrl.signal)
      .then((p) => {
        albums = p.items;
        albumTotal = p.total ?? p.items.length;
      })
      .catch(() => {});
    return () => ctrl.abort();
  });

  const own = $derived(mine.playlists.filter((p) => p.role === "owner"));
  const shared = $derived(mine.playlists.filter((p) => p.role !== "owner"));
  const initial = $derived((session.user?.display_name ?? "?").trim().charAt(0).toUpperCase());

  async function newPlaylist() {
    const pl = await newPlaylistFlow();
    if (pl) navigate(`/playlists/${pl.id}`);
  }
</script>

{#snippet playlistLink(p: Playlist)}
  <a class="list" href={href(`/playlists/${p.id}`)}>
    <span class="art"><PlaylistCover playlist={p} size={64} /></span>
    <span class="meta">
      <strong>{p.name}</strong>
      <small>{p.role === "owner" ? plural(p.item_count, "Titel", "Titel") : `von ${p.owner.display_name}`}</small>
    </span>
  </a>
{/snippet}

<div class="page">
  <header class="profile">
    <span class="avatar" aria-hidden="true">{initial}</span>
    <div>
      <p class="kind">Profil</p>
      <h1>{session.user?.display_name}</h1>
    </div>
  </header>

  <div class="section-head">
    <h2>Dein Hören</h2>
    <div class="periods" role="group" aria-label="Zeitraum">
      {#each PERIODS as p (p.key)}
        <button class="chip" class:on={period === p.key} aria-pressed={period === p.key} onclick={() => (period = p.key)}>{p.label}</button>
      {/each}
    </div>
  </div>
  <div class="tiles">
    <div class="tile"><span class="value">{stats ? minutes(stats.listening_ms) : "–"}</span><span class="label">Hörzeit</span></div>
    <div class="tile"><span class="value">{stats ? stats.plays.toLocaleString("de-DE") : "–"}</span><span class="label">Wiedergaben</span></div>
  </div>

  {#if stats && stats.plays === 0}
    <p class="empty">In diesem Zeitraum hast du noch nichts gehört.</p>
  {:else if stats}
    <div class="section-head sub"><h3>Meistgehörte Titel</h3></div>
    <div class="tracks">
      <div class="tracks-head"><span>Wiedergaben</span></div>
      {#each stats.tracks as e, i (e.track.id)}
        <div class="row-h"><TrackRow track={e.track} number={i + 1} count={e.plays} onplay={() => playTop(i)} /></div>
      {/each}
    </div>

    <div class="section-head sub"><h3>Meistgehörte Künstler</h3></div>
    <div class="artists">
      {#each stats.artists.slice(0, TOP_CARDS) as e (e.artist.id)}
        <a class="artist" href={href(`/artists/${e.artist.id}`)}>
          <span class="artist-art"><Cover hash={e.artist.cover} alt="" round /></span>
          <span class="meta"><strong>{e.artist.name}</strong><small>{minutes(e.listening_ms)}</small></span>
        </a>
      {/each}
    </div>
  {/if}

  <div class="section-head"><h2>Favoriten</h2></div>

  <div class="lists">
    <a class="list" href={href("/favorites")}>
      <span class="art fav" aria-hidden="true"><Icon name="heart" size={22} filled /></span>
      <span class="meta"><strong>Lieblingssongs</strong><small>{plural(mine.favoriteTracks.size, "Titel", "Titel")}</small></span>
    </a>
  </div>

  <div class="section-head sub">
    <h3>Lieblingsalben</h3>
    {#if albumTotal > 0}<a class="all" href={href("/favorites/albums")}>Alle ansehen</a>{/if}
  </div>
  {#if albums && albums.length === 0}
    <p class="empty">Markiere Alben mit dem Herz auf der Albumseite, dann erscheinen sie hier.</p>
  {:else}
    <div class="grid">
      {#each albums ?? Array(6).fill(undefined) as album, i (album?.id ?? `p${i}`)}<AlbumCard {album} />{/each}
    </div>
  {/if}

  <div class="section-head">
    <h2>Deine Playlists</h2>
    <button class="btn small" onclick={newPlaylist}><Icon name="plus" size={16} /> Neu</button>
  </div>
  {#if own.length}
    <div class="lists">
      {#each own as p (p.id)}{@render playlistLink(p)}{/each}
    </div>
  {:else}
    <p class="empty">Noch keine eigenen Playlists.</p>
  {/if}

  {#if shared.length}
    <div class="section-head"><h2>Mit dir geteilt</h2></div>
    <div class="lists">
      {#each shared as p (p.id)}{@render playlistLink(p)}{/each}
    </div>
  {/if}
</div>

<style>
  .profile {
    display: flex;
    align-items: center;
    gap: 18px;
    padding: 28px 24px 20px;
  }
  .avatar {
    width: 72px;
    height: 72px;
    flex: none;
    border-radius: 50%;
    display: grid;
    place-items: center;
    font-size: 1.9rem;
    font-weight: 650;
    color: var(--accent-contrast);
    background: linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 40%, #6b3fa0));
  }
  .kind {
    margin: 0;
    color: var(--text-muted);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }
  h1 {
    font-size: clamp(1.5rem, 4vw, 2.4rem);
    margin: 4px 0 0;
    letter-spacing: -0.02em;
  }
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
  h3 {
    font-size: 0.95rem;
    margin: 0;
    color: var(--text-muted);
    font-weight: 550;
  }
  .section-head.sub {
    margin-top: 4px;
    margin-bottom: 10px;
  }
  .periods {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }
  .chip {
    height: 30px;
    padding: 0 12px;
    border: 0;
    border-radius: 15px;
    background: var(--surface-1);
    color: var(--text-muted);
    font: inherit;
    font-size: 0.82rem;
    cursor: pointer;
  }
  .chip:hover {
    color: var(--text);
  }
  .chip.on {
    background: var(--text);
    color: var(--surface-0);
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 10px;
    padding: 0 24px 20px;
  }
  .tile {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 14px 16px;
    border-radius: var(--radius-sm);
    background: var(--surface-1);
  }
  .value {
    font-size: 1.6rem;
    font-weight: 650;
    letter-spacing: -0.01em;
    font-variant-numeric: tabular-nums;
  }
  .label {
    color: var(--text-muted);
    font-size: 0.85rem;
  }
  .tracks {
    padding: 0 16px 20px;
  }
  .row-h {
    height: 56px;
  }
  /* Lines up with TrackRow's count column: right padding = row padding + menu (72px)
     + gap + duration (56px) + gap; on phones the duration is hidden, gaps are 8px. */
  .tracks-head {
    display: flex;
    justify-content: flex-end;
    padding: 0 168px 4px 8px;
    color: var(--text-muted);
    font-size: 0.8rem;
  }
  @media (max-width: 720px) {
    .tracks-head {
      padding-right: 84px; /* 4 + 72 + 8 */
    }
  }
  .artists {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 10px;
    padding: 0 24px 28px;
  }
  .artist {
    display: flex;
    align-items: center;
    gap: 12px;
    min-width: 0;
    color: inherit;
    text-decoration: none;
    padding: 6px;
    border-radius: var(--radius-sm);
  }
  .artist:hover {
    background: var(--surface-1);
  }
  .artist-art {
    width: 52px;
    flex: none;
  }
  .all {
    color: var(--text-muted);
    font-size: 0.85rem;
    font-weight: 550;
    text-decoration: none;
  }
  .all:hover {
    color: var(--text);
    text-decoration: underline;
  }
  .small {
    height: 32px;
    padding: 0 12px;
    font-size: 0.85rem;
  }
  .empty {
    margin: 0 24px 24px;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
    gap: 20px;
    padding: 0 24px 24px;
  }
  .lists {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 10px;
    padding: 0 24px 24px;
  }
  .list {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px;
    border-radius: var(--radius-sm);
    background: var(--surface-1);
    color: inherit;
    text-decoration: none;
    min-width: 0;
  }
  .list:hover {
    background: var(--surface-2);
  }
  .art {
    width: 48px;
    flex: none;
  }
  .art.fav {
    height: 48px;
    border-radius: 6px;
    display: grid;
    place-items: center;
    background: var(--accent);
    color: var(--accent-contrast);
  }
  .meta {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .meta strong,
  .meta small {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .meta strong {
    font-weight: 550;
  }
  .meta small {
    color: var(--text-muted);
  }
  @media (max-width: 560px) {
    .profile {
      padding: 18px 16px 14px;
      gap: 14px;
    }
    .avatar {
      width: 56px;
      height: 56px;
      font-size: 1.5rem;
    }
    .grid {
      grid-template-columns: repeat(2, 1fr);
      gap: 14px;
      padding: 0 16px 20px;
    }
    .lists {
      grid-template-columns: 1fr;
      padding: 0 16px 20px;
      gap: 8px;
    }
    .section-head {
      margin: 8px 16px 10px;
      flex-wrap: wrap;
      gap: 8px;
    }
    .tiles {
      grid-template-columns: 1fr 1fr;
      padding: 0 16px 16px;
    }
    .tracks {
      padding: 0 4px 16px;
    }
    .artists {
      grid-template-columns: 1fr 1fr;
      padding: 0 16px 20px;
    }
    .empty {
      margin: 0 16px 20px;
    }
  }
</style>
