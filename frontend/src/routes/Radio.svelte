<script lang="ts">
  // A radio station as a temporary playlist: shows the mix before it plays. Every load (and
  // "Neu mischen") draws a fresh station; playing starts with the list shown, the player adds
  // more on the go (see player.playRadio). Deliberately
  // not saveable as a playlist: a playing radio keeps growing, so there is no fixed list.
  import { untrack } from "svelte";
  import { ApiError, get, post, type AlbumDetail, type Artist, type Track } from "../lib/api";
  import Cover from "../lib/components/Cover.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import PlayToggle from "../lib/components/PlayToggle.svelte";
  import TrackRow from "../lib/components/TrackRow.svelte";
  import { pageTitle } from "../lib/headerTitle.svelte";
  import VirtualList from "../lib/components/VirtualList.svelte";

  import { player, RADIO_BATCH } from "../lib/player.svelte";
  import { radioPath, type RadioKind } from "../lib/radio";
  import { recallEntry, rememberEntry } from "../lib/router.svelte";
  import { toast } from "../lib/ui.svelte";

  // Only part of the station is shown, its last two rows fading out, so the list seems to go on.
  // While it plays, the rows after the current track are revealed one by one. Fewer rows than the
  // player keeps in its queue (RADIO_BATCH, refilled with 5 left), so there is always more to show.
  const VISIBLE = 15;
  const AHEAD = 4; // rows always shown after the current track
  const REVEAL_MS = 220;
  const REVEAL_MAX = 8; // further behind than this (back on the page): show them all at once

  let { kind, id }: { kind: string; id: string } = $props();
  type Seed = { name: string; by: string | null; cover: string | null };
  // Back on the page it is the same mix; only opening the station anew draws a fresh one.
  const kept = untrack(() => recallEntry<{ seed: Seed | null; tracks: Track[] | null; followLive: boolean }>(`radio:${kind}:${id}`));
  let seed = $state<Seed | null>(kept?.seed ?? null);
  let tracks = $state<Track[] | null>(kept?.tracks ?? null);
  let error = $state<string | null>(null);
  let mix = $state(0);

  const KINDS: Record<string, { api: string; label: string }> = {
    track: { api: "tracks", label: "Radio zu einem Titel" },
    album: { api: "albums", label: "Radio zu einem Album" },
    artist: { api: "artists", label: "Radio zu einem Künstler" },
  };
  const k = $derived(KINDS[kind]);

  $effect(() => {
    if (!k) {
      error = "Diese Seite gibt es nicht.";
      return;
    }
    const ctrl = new AbortController();
    get<Track | AlbumDetail | Artist>(`/${k.api}/${id}`, undefined, ctrl.signal)
      .then((s) => {
        // A station always gets a picture (and its colours), whatever the artist image setting.
        if (kind === "artist") seed = { name: (s as Artist).name, by: null, cover: (s as Artist).fallback_cover ?? s.cover };
        else seed = { name: (s as Track | AlbumDetail).title, by: (s as Track | AlbumDetail).artist, cover: s.cover };
      })
      .catch((e) => {
        if (e.name !== "AbortError") error = e instanceof ApiError && e.status === 404 ? "Das gibt es nicht (mehr)." : String(e);
      });
    return () => ctrl.abort();
  });

  $effect(() => {
    if (!k || (!mix && kept?.tracks)) return;
    const ctrl = new AbortController();
    tracks = null;
    get<Track[]>(`/${k.api}/${id}/radio`, { limit: RADIO_BATCH }, ctrl.signal)
      .then((t) => (tracks = t))
      .catch((e) => {
        if (e.name !== "AbortError") error = "Radio konnte nicht erstellt werden.";
      });
    return () => ctrl.abort();
  });

  // While this station plays, the page shows it as it grows (the player keeps adding tracks), not
  // the preview; "Neu mischen" goes back to a fresh preview.
  let followLive = $state(kept?.followLive ?? true);
  $effect(() => {
    rememberEntry(`radio:${kind}:${id}`, { seed, tracks: $state.snapshot(tracks), followLive });
  });
  const live = $derived(followLive && player.radio && player.source?.ref === `radio:${kind}:${id}`);
  const shown = $derived(live ? player.queue.order.map((i) => player.queue.tracks[i]) : tracks);

  let revealed = $state(VISIBLE);
  const count = $derived(Math.min(revealed, shown?.length ?? 0));
  const more = $derived((shown?.length ?? 0) > count);

  $effect(() => {
    if (!live) {
      revealed = VISIBLE;
      return;
    }
    const target = player.queue.pos + 1 + AHEAD;
    if (revealed >= target) return;
    if (target - revealed > REVEAL_MAX) {
      revealed = target;
      return;
    }
    const timer = setTimeout(() => revealed++, REVEAL_MS);
    return () => clearTimeout(timer);
  });

  /** Out of the list at once, and out of this station for good (backend analysis/taste.py). */
  function dislike(index: number) {
    const track = shown?.[index];
    if (!track) return;
    const saved = post("/radio/dislikes", { track_id: track.id, station: `${kind}:${id}` }).catch(() => {
      toast("Konnte nicht gespeichert werden");
    });
    if (live) {
      if (index === player.queue.pos) player.next();
      player.remove(index);
      return;
    }
    tracks = tracks?.filter((t) => t.id !== track.id) ?? null;
    if ((tracks?.length ?? 0) < VISIBLE + 3) saved.then(topUp);
  }

  /** The preview ran low: more of the same station (the player does this itself while it plays). */
  async function topUp() {
    const drawn = mix;
    if (!k || !tracks) return;
    try {
      const fresh = await get<Track[]>(`/${k.api}/${id}/radio`, { limit: RADIO_BATCH, exclude: tracks.map((t) => t.id) });
      if (drawn !== mix || !tracks) return;
      const have = new Set(tracks.map((t) => t.id));
      tracks = [...tracks, ...fresh.filter((t) => !have.has(t.id))];
    } catch {
      /* offline: the next dislike tries again */
    }
  }

  function play(index = 0) {
    if (live) {
      player.jump(index);
      return;
    }
    if (!tracks?.length || !seed) return;
    followLive = true;
    player.playRadio(tracks, { kind: "Radio", name: seed.name, path: radioPath(kind as RadioKind, +id), ref: `radio:${kind}:${id}` }, index);
  }

  function remix() {
    followLive = false;
    mix++;
  }
</script>

{#if error}
  <div class="page"><p class="empty">{error}</p></div>
{:else}
  <VirtualList {count} rowHeight={56} label="Titel" keep="radio:{kind}:{id}">
    {#snippet header()}
      <header class="hero">
        <div class="art">
          <Cover hash={seed?.cover ?? null} size={256} />
          <span class="badge" aria-hidden="true"><Icon name="radio" size={30} /></span>
        </div>
        <div class="info">
          <p class="kind"><Icon name="radio" size={13} /> {k?.label}</p>
          <h1 use:pageTitle={seed ? `Radio: ${seed.name}` : ""}>{seed ? `Radio: ${seed.name}` : " "}</h1>
          {#if seed?.by}<p class="by">{seed.by}</p>{/if}
          <!-- No count or length: a station has no end, it keeps adding tracks while it plays. -->
          <p class="by">{live ? "Läuft gerade" : tracks ? "Endlos, mischt beim Hören weiter" : "Wird gemischt …"}</p>
          <div class="actions">
            <PlayToggle ref="radio:{kind}:{id}" disabled={!tracks?.length} start={() => play(0)} />
            <button class="btn" disabled={!live && !tracks} onclick={remix}><Icon name="shuffle" size={18} /> Neu mischen</button>
          </div>
        </div>
      </header>
      {#if !live && tracks && !tracks.length}<p class="empty">Für dieses Radio wurden keine Titel gefunden.</p>{/if}
    {/snippet}
    {#snippet row(i)}
      <div class="pad" class:fade-from={more && i === count - 2} class:fade-out={more && i === count - 1}>
        {#if shown}
          <TrackRow
            track={shown[i]}
            number={i + 1}
            note={shown[i].reason}
            onplay={() => play(i)}
            ondislike={kind === "track" && shown[i]?.id === +id ? undefined : () => dislike(i)}
          />
        {/if}
      </div>
    {/snippet}
  </VirtualList>
{/if}

<style>
  .hero {
    display: flex;
    gap: 28px;
    align-items: flex-end;
    padding: 32px 24px 20px;
  }
  .art {
    position: relative;
    width: min(220px, 36vw);
    flex: none;
    box-shadow: 0 18px 44px rgb(0 0 0 / 0.3);
    border-radius: var(--radius-sm);
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
  }
  .info {
    min-width: 0;
  }
  .kind {
    margin: 0;
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--text-muted);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  h1 {
    font-size: clamp(1.6rem, 4vw, 2.8rem);
    line-height: 1.1;
    margin: 6px 0 8px;
    letter-spacing: -0.02em;
    overflow-wrap: anywhere;
  }
  .by {
    color: var(--text-muted);
    margin: 0 0 10px;
  }
  .actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: 8px;
  }
  .pad {
    padding: 0 16px;
    height: 100%;
    /* A mask, not a dark overlay: fades into whatever the (moving) background is. */
    --fade-top: 1;
    --fade-bottom: 1;
    -webkit-mask-image: linear-gradient(to bottom, rgb(0 0 0 / var(--fade-top)), rgb(0 0 0 / var(--fade-bottom)));
    mask-image: linear-gradient(to bottom, rgb(0 0 0 / var(--fade-top)), rgb(0 0 0 / var(--fade-bottom)));
    transition:
      --fade-top 0.4s,
      --fade-bottom 0.4s;
  }
  .fade-from {
    --fade-bottom: 0.45;
  }
  .fade-out {
    --fade-top: 0.45;
    --fade-bottom: 0;
    animation: reveal 0.4s ease-out;
  }
  @keyframes reveal {
    from {
      opacity: 0;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .pad {
      transition: none;
    }
    .fade-out {
      animation: none;
    }
  }
  @media (max-width: 640px) {
    .hero {
      flex-direction: column;
      align-items: flex-start;
      padding: 20px 16px 12px;
    }
    .art {
      width: min(200px, 60vw);
    }
  }
</style>
