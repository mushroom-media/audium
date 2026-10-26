<script lang="ts">
  import { get, type AlbumDetail } from "../lib/api";
  import Cover from "../lib/components/Cover.svelte";
  import Heart from "../lib/components/Heart.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import TrackRow from "../lib/components/TrackRow.svelte";
  import { openTrackMenu } from "../lib/ui.svelte";
  import { longDuration, plural } from "../lib/format";
  import { player } from "../lib/player.svelte";
  import { startGroupRadio } from "../lib/radio";
  import { href } from "../lib/router.svelte";

  let { id }: { id: string } = $props();
  let album = $state<AlbumDetail | null>(null);
  let error = $state<string | null>(null);

  $effect(() => {
    const ctrl = new AbortController();
    album = null;
    error = null;
    get<AlbumDetail>(`/albums/${id}`, undefined, ctrl.signal)
      .then((a) => (album = a))
      .catch((e) => e.name !== "AbortError" && (error = e.message));
    return () => ctrl.abort();
  });

  const multiDisc = $derived(album ? new Set(album.tracks.map((t) => t.disc_no ?? 1)).size > 1 : false);

  function play(index: number | null = 0, shuffle = false) {
    if (album) player.playTracks(album.tracks, index, shuffle, { kind: "Album", name: album.title, path: `/albums/${album.id}`, ref: `album:${album.id}` });
  }
</script>

<div class="page">
  {#if error}
    <p class="empty">{error}</p>
  {:else if album}
    <header class="hero">
      <div class="art"><Cover hash={album.cover} size={600} alt="Cover von {album.title}" /></div>
      <div class="info">
        <p class="kind">{album.compilation ? "Compilation" : "Album"}</p>
        <h1>{album.title}</h1>
        <p class="by">
          <a href={href(`/artists/${album.artist_id}`)}>{album.artist}</a>
          {#if album.year}<span> · {album.year}</span>{/if}
          <span> · {plural(album.track_count, "Titel", "Titel")}, {longDuration(album.duration_ms)}</span>
        </p>
        <div class="actions">
          <button class="btn primary" onclick={() => play(0, false)}><Icon name="play" size={18} /> Abspielen</button>
          <button class="btn square" onclick={() => play(null, true)} title="Zufällig abspielen" aria-label="Zufällig abspielen"><Icon name="shuffle" size={18} /></button>
          <button class="btn" onclick={() => album && startGroupRadio("albums", album.id, album.title)}><Icon name="radio" size={18} /> Radio</button>
          <Heart kind="album" id={album.id} size={22} />
          <button class="icon-btn" title="Mehr" aria-label="Mehr zu {album.title}" onclick={(e) => album && openTrackMenu(e, album.tracks, album.title)}><Icon name="more" size={20} /></button>
        </div>
      </div>
    </header>
    <div class="tracks">
      {#each album.tracks as t, i (t.id)}
        {#if multiDisc && (i === 0 || (album.tracks[i - 1].disc_no ?? 1) !== (t.disc_no ?? 1))}
          <h2 class="disc">CD {t.disc_no ?? 1}</h2>
        {/if}
        <div class="row-h">
          <TrackRow track={t} number={t.track_no ?? i + 1} showCover={false} showAlbum={false} linkArtist={false} onplay={() => play(i, false)} />
        </div>
      {/each}
    </div>
  {:else}
    <div class="hero skeleton"><div class="art"><div class="ph"></div></div></div>
  {/if}
</div>

<style>
  .hero {
    display: flex;
    gap: 32px;
    align-items: flex-end;
    padding: 32px 24px 24px;
  }
  .art {
    width: min(260px, 40vw);
    flex: none;
    box-shadow: 0 20px 50px rgb(0 0 0 / 0.35);
    border-radius: var(--radius-sm);
  }
  .ph {
    aspect-ratio: 1;
    background: var(--surface-2);
    border-radius: var(--radius-sm);
  }
  .info {
    min-width: 0;
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
    line-height: 1.1;
    margin: 6px 0 10px;
    letter-spacing: -0.02em;
  }
  .by {
    color: var(--text-muted);
    margin: 0 0 20px;
  }
  .by a {
    color: var(--text);
    font-weight: 550;
    text-decoration: none;
  }
  .by a:hover {
    text-decoration: underline;
  }
  .actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
  }
  .tracks {
    padding: 0 16px 32px;
  }
  .row-h {
    height: 52px;
  }
  .disc {
    font-size: 0.85rem;
    color: var(--text-muted);
    margin: 18px 12px 6px;
  }
  @media (max-width: 640px) {
    .hero {
      flex-direction: column;
      align-items: flex-start;
      padding: 20px 16px;
      gap: 18px;
    }
    .art {
      width: min(240px, 70vw);
      align-self: center;
    }
  }
</style>
