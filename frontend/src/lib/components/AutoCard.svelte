<script lang="ts">
  // An auto-playlist as a cover card (Discover, "Alle Genres", the admin page). `actions`: extra
  // buttons below, e.g. publish or restore for the admin.
  import type { Snippet } from "svelte";
  import type { AutoPlaylist } from "../api";
  import { plural } from "../format";
  import { ORIGINS } from "../origin";
  import { href } from "../router.svelte";
  import Cover from "./Cover.svelte";
  import Icon from "./Icon.svelte";
  import { t } from "../i18n.svelte";

  let { playlist, actions }: { playlist: AutoPlaylist; actions?: Snippet } = $props();
  const origin = $derived(ORIGINS[playlist.origin]);
</script>

<a class="card" href={href(`/discover/${playlist.id}`)}>
  <div class="art">
    <Cover hash={playlist.cover} size={256} />
    <span class="badge" title="{t(origin.label)}: {t(origin.hint)}"><Icon name={origin.icon} size={14} /></span>
  </div>
  <div class="title">{playlist.name}</div>
  <div class="sub">{plural(playlist.track_count, "Titel", "Titel")} · {t(origin.label)}</div>
  {#if actions}{@render actions()}{/if}
</a>

<style>
  .card {
    color: inherit;
    text-decoration: none;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .art {
    position: relative;
    margin-bottom: 8px;
  }
  .badge {
    position: absolute;
    top: 8px;
    left: 8px;
    width: 26px;
    height: 26px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: rgb(0 0 0 / 0.55);
    color: var(--accent);
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
</style>
