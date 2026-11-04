<script lang="ts">
  import { get, type Page, type Track } from "../lib/api";
  import Icon from "../lib/components/Icon.svelte";
  import PlayToggle from "../lib/components/PlayToggle.svelte";
  import TrackRow from "../lib/components/TrackRow.svelte";
  import VirtualList from "../lib/components/VirtualList.svelte";
  import { plural } from "../lib/format";
  import { pageTitle } from "../lib/headerTitle.svelte";
  import { mine } from "../lib/mine.svelte";
  import { keptList } from "../lib/paged.svelte";
  import { player } from "../lib/player.svelte";
  import { t } from "../lib/i18n.svelte";

  const QUEUE_WINDOW = 500;
  // Reload when the set of favorites changes (hearts clicked elsewhere).
  const list = $derived.by(() => {
    void mine.favoriteTracks.size;
    return keptList<Track>("favorites", (offset, limit, signal) => get<Page<Track>>("/favorites/track", { offset, limit }, signal));
  });

  async function playFrom(index: number, shuffle = false) {
    const tracks = await list.slice(index, QUEUE_WINDOW);
    player.playTracks(tracks, shuffle ? null : 0, shuffle, { kind: "Playlist", name: "Lieblingssongs", path: "/favorites", ref: "favorites" });
  }
</script>

<VirtualList count={list.total ?? 0} rowHeight={56} onrange={(s, e) => list.ensure(s, e)} label={t("Lieblingssongs")} keep="favorites">
  {#snippet header()}
    <header class="hero">
      <div class="badge" aria-hidden="true"><Icon name="heart" size={56} filled /></div>
      <div>
        <p class="kind">{t("Playlist")}</p>
        <h1 use:pageTitle={"Lieblingssongs"}>{t("Lieblingssongs")}</h1>
        {#if list.total !== null}<p class="count">{plural(list.total, "Titel", "Titel")}</p>{/if}
        <div class="actions">
          <PlayToggle ref="favorites" disabled={!list.total} start={() => playFrom(0)} />
          <button class="btn square" disabled={!list.total} onclick={() => playFrom(0, true)} title={t("Zufällig abspielen")} aria-label={t("Zufällig abspielen")}><Icon name="shuffle" size={18} /></button>
        </div>
      </div>
    </header>
    {#if list.total === 0}<p class="empty">{t("Markiere Titel mit dem Herz, dann erscheinen sie hier.")}</p>{/if}
  {/snippet}
  {#snippet row(i)}
    <div class="pad"><TrackRow track={list.get(i)} number={i + 1} onplay={() => playFrom(i)} /></div>
  {/snippet}
</VirtualList>

<style>
  .hero {
    display: flex;
    gap: 28px;
    align-items: flex-end;
    padding: 32px 24px 20px;
  }
  .badge {
    width: min(180px, 30vw);
    aspect-ratio: 1;
    border-radius: var(--radius-sm);
    display: grid;
    place-items: center;
    color: var(--accent-contrast);
    background: linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 40%, #6b3fa0));
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
    font-size: clamp(1.6rem, 4vw, 2.8rem);
    margin: 6px 0 4px;
    letter-spacing: -0.02em;
  }
  .actions {
    display: flex;
    gap: 10px;
    margin-top: 14px;
  }
  .pad {
    height: 100%;
    padding: 0 16px;
  }
  @media (max-width: 560px) {
    .hero {
      flex-direction: column;
      align-items: flex-start;
      padding: 20px 16px 12px;
    }
    .badge {
      width: 120px;
    }
  }
</style>
