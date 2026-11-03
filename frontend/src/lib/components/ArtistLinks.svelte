<script lang="ts">
  import type { Track } from "../api";
  import { href } from "../router.svelte";

  let { track, link = true }: { track: Track; link?: boolean } = $props();

  const list = $derived(track.artists?.length ? track.artists : [{ id: track.artist_id, name: track.artist }]);
</script>

{#each list as a, i (a.id)}{i ? ", " : ""}{#if link}<a href={href(`/artists/${a.id}`)}>{a.name}</a>{:else}{a.name}{/if}{/each}

<style>
  a {
    color: inherit;
    text-decoration: none;
  }
  a:hover {
    color: var(--text);
    text-decoration: underline;
  }
</style>
