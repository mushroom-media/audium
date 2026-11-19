<script lang="ts">
  // A "recently played" entry: an album, a playlist or a radio station. Playlists carry a large
  // centred badge on the cover and radios a cover of their own (RadioCover), so both stand apart
  // from albums at a glance.
  import { get, type AlbumDetail, type AutoItem, type Page, type PlaylistItem, type RecentItem, type Track } from "../api";
  import { player } from "../player.svelte";
  import { radioPath, startGroupRadio, startRadio } from "../radio";
  import { href } from "../router.svelte";
  import CardPlay from "./CardPlay.svelte";
  import Icon from "./Icon.svelte";
  import PlaylistCover from "./PlaylistCover.svelte";
  import RadioCover from "./RadioCover.svelte";

  /** `compact`: on phones a small row like the playlist links instead of a card. */
  let { item, compact = false }: { item: RecentItem; compact?: boolean } = $props();

  const path = $derived.by(() => {
    const { type, id, radio_of } = item;
    if (type === "favorites") return "/favorites";
    if (type === "playlist") return `/playlists/${id}`;
    if (type === "auto") return `/discover/${id}`;
    if (type === "radio" && id !== null) return radioPath(radio_of ?? "album", id);
    return `/albums/${id}`;
  });
  const badge = $derived(item.type === "radio" || item.type === "album" ? null : "list");

  // What this entry plays under: a station's ref also says what it is the radio of (see radio.ts).
  const ref = $derived.by(() => {
    const { type, id, radio_of } = item;
    if (type === "favorites") return "favorites";
    return type === "radio" ? `radio:${radio_of ?? "album"}:${id}` : `${type}:${id}`;
  });

  async function play() {
    const { type, id, name } = item;
    const source = { kind: "Playlist", name, path, ref };
    if (type === "album") {
      const detail = await get<AlbumDetail>(`/albums/${id}`);
      player.playTracks(detail.tracks, 0, undefined, { ...source, kind: "Album", name: detail.title });
    } else if (type === "playlist") {
      const page = await get<{ items: PlaylistItem[] }>(`/playlists/${id}/items`, { limit: 1000 });
      const tracks = page.items.filter((i) => i.available).map((i) => i.track);
      if (tracks.length) player.playTracks(tracks, 0, undefined, source);
    } else if (type === "auto") {
      const page = await get<{ items: AutoItem[] }>(`/autoplaylists/${id}/items`, { limit: 1000 });
      if (page.items.length) player.playTracks(page.items.map((i) => i.track), 0, undefined, source);
    } else if (type === "favorites") {
      const page = await get<Page<Track>>("/favorites/track", { limit: 500 });
      if (page.items.length) player.playTracks(page.items, 0, undefined, source);
    } else if (item.radio_of === "track") {
      await startRadio(await get<Track>(`/tracks/${id}`));
    } else if (id !== null) {
      await startGroupRadio(item.radio_of === "artist" ? "artists" : "albums", id, name);
    }
  }
</script>

<a class="card" class:compact href={href(path)} title={item.name}>
  <div class="art">
    {#if item.type === "favorites"}
      <div class="fav" aria-hidden="true"><Icon name="heart" size={48} filled /></div>
    {:else if item.type === "radio"}
      <RadioCover hash={item.cover} name={item.name} />
    {:else}
      <PlaylistCover playlist={item} alt="" />
    {/if}
    {#if badge}
      <span class="badge" title="Playlist"><Icon name={badge} size={30} /></span>
    {/if}
    <span class="play"><CardPlay {ref} name={item.name} start={play} /></span>
  </div>
  <div class="text">
    <div class="title">{item.name}</div>
    <div class="sub">{item.subtitle ?? ""}</div>
  </div>
</a>

<style>
  .card {
    display: block;
    color: inherit;
    text-decoration: none;
    min-width: 0;
  }
  .art {
    position: relative;
  }
  .fav {
    aspect-ratio: 1;
    border-radius: var(--radius-sm);
    display: grid;
    place-items: center;
    background: var(--accent);
    color: var(--accent-contrast);
  }
  .title {
    margin-top: 10px;
    font-weight: 550;
    font-size: 0.92rem;
  }
  .title,
  .sub {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sub {
    color: var(--text-muted);
    font-size: 0.85rem;
    min-height: 1.2em;
  }
  .badge {
    position: absolute;
    left: 50%;
    top: 50%;
    width: 30%;
    min-width: 44px;
    max-width: 64px;
    aspect-ratio: 1;
    transform: translate(-50%, -50%);
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: rgb(0 0 0 / 0.6);
    color: #fff;
    backdrop-filter: blur(4px);
    box-shadow: 0 4px 14px rgb(0 0 0 / 0.3);
    pointer-events: none;
  }
  .play {
    display: contents;
  }

  /* Phones: a row like the playlist links on the start page. */
  @media (max-width: 560px) {
    .compact {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 8px;
      border-radius: var(--radius-sm);
      background: var(--surface-1);
    }
    .compact:active {
      background: var(--surface-2);
    }
    .compact .art {
      width: 48px;
      flex: none;
    }
    .compact .fav :global(svg) {
      width: 22px;
      height: 22px;
    }
    .compact .badge {
      width: 24px;
      min-width: 0;
      backdrop-filter: none;
      box-shadow: none;
    }
    .compact .badge :global(svg) {
      width: 14px;
      height: 14px;
    }
    .compact .play {
      display: none;
    }
    .compact .text {
      min-width: 0;
    }
    .compact .title {
      margin-top: 0;
      font-size: inherit;
    }
  }
</style>
