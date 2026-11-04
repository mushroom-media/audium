<script lang="ts">
  import { untrack } from "svelte";
  import { get, type Track } from "../lib/api";
  import Cover from "../lib/components/Cover.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import TrackRow from "../lib/components/TrackRow.svelte";
  import { radioPath } from "../lib/radio";
  import { player } from "../lib/player.svelte";
  import { keepScroll } from "../lib/keepScroll";
  import { pageTitle } from "../lib/headerTitle.svelte";
  import { navigate, recallEntry, rememberEntry } from "../lib/router.svelte";
  import { t } from "../lib/i18n.svelte";

  let { id }: { id: string } = $props();
  const kept = untrack(() => recallEntry<{ seed: Track; tracks: Track[] }>(`similar:${id}`));
  let seed = $state<Track | null>(kept?.seed ?? null);
  let tracks = $state<Track[] | null>(kept?.tracks ?? null);

  $effect(() => {
    const ctrl = new AbortController();
    Promise.all([
      get<Track>(`/tracks/${id}`, undefined, ctrl.signal),
      get<Track[]>(`/tracks/${id}/similar`, { limit: 50 }, ctrl.signal),
    ]).then(([t, s]) => {
      seed = t;
      tracks = s;
      rememberEntry(`similar:${id}`, { seed: t, tracks: s });
    }).catch(() => {});
    return () => ctrl.abort();
  });

  const similarSource = (track: Track) => ({ kind: t("Ähnlich wie"), name: track.title, path: `/tracks/${track.id}/similar` });
</script>

<div class="page" use:keepScroll>
  {#if seed}
    <header class="hero">
      <div class="art"><Cover hash={seed.cover} size={256} /></div>
      <div>
        <p class="kind">{t("Ähnlich wie")}</p>
        <h1 use:pageTitle={seed.title}>{seed.title}</h1>
        <p class="by">{seed.artist}</p>
        <div class="actions">
          <button class="btn primary" onclick={() => seed && navigate(radioPath("track", seed.id))}><Icon name="radio" size={18} /> {t("Zum Radio")}</button>
          <button class="btn" disabled={!tracks?.length} onclick={() => seed && tracks && player.playTracks([seed, ...tracks], 0, undefined, similarSource(seed))}>
            <Icon name="play" size={18} /> {t("Alle abspielen")}
          </button>
        </div>
      </div>
    </header>
  {/if}
  {#if tracks && !tracks.length}
    <p class="empty">{t("Keine ähnlichen Titel gefunden.")}</p>
  {:else if tracks}
    <div class="list">
      {#each tracks as t, i (t.id)}
        <div class="row-h"><TrackRow track={t} number={i + 1} note={t.reason} onplay={() => tracks && player.playTracks(tracks, i, undefined, seed && similarSource(seed))} /></div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .hero {
    display: flex;
    gap: 24px;
    align-items: flex-end;
    padding: 32px 24px 20px;
  }
  .art {
    width: min(160px, 32vw);
    flex: none;
  }
  .kind {
    margin: 0;
    color: var(--text-muted);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  h1 {
    margin: 6px 0 4px;
    font-size: clamp(1.4rem, 3.5vw, 2.4rem);
  }
  .by {
    color: var(--text-muted);
    margin: 0 0 16px;
  }
  .actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
  }
  .list {
    padding: 0 16px 32px;
  }
  .row-h {
    height: 56px;
  }
</style>
