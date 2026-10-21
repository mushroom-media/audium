<script lang="ts">
  import { duration } from "../format";
  import { player } from "../player.svelte";
  import * as Q from "../queue";
  import Cover from "./Cover.svelte";
  import Icon from "./Icon.svelte";
  import VirtualList from "./VirtualList.svelte";

  const upcoming = $derived(Q.upcoming(player.queue));
  const current = $derived(player.current);
</script>

<aside class="panel" aria-label="Warteschlange">
  <header>
    <h2>Warteschlange</h2>
    <button class="icon-btn" aria-label="Schließen" onclick={() => (player.queueOpen = false)}><Icon name="close" /></button>
  </header>
  {#if current}
    <div class="label">Läuft gerade</div>
    <div class="item now">
      <div class="thumb"><Cover hash={current.cover} size={64} /></div>
      <div class="meta"><div class="t">{current.title}</div><div class="a">{current.artist}</div></div>
      <span class="d">{duration(current.duration_ms)}</span>
    </div>
  {/if}
  <div class="label">Als Nächstes{upcoming.length ? ` · ${upcoming.length}` : ""}</div>
  <div class="list">
    {#if upcoming.length}
      <VirtualList count={upcoming.length} rowHeight={56} label="Als Nächstes">
        {#snippet row(i)}
          {@const u = upcoming[i]}
          <div class="item">
            <button class="hit" onclick={() => player.jump(u.orderPos)} aria-label="{u.track.title} abspielen">
              <div class="thumb"><Cover hash={u.track.cover} size={64} /></div>
              <div class="meta"><div class="t">{u.track.title}</div><div class="a">{u.track.artist}</div></div>
            </button>
            <button class="icon-btn rm" aria-label="Entfernen" onclick={() => player.remove(u.orderPos)}><Icon name="close" size={16} /></button>
          </div>
        {/snippet}
      </VirtualList>
    {:else}
      <p class="empty">Danach ist Schluss. Füge Titel mit <Icon name="plus" size={14} /> hinzu.</p>
    {/if}
  </div>
</aside>

<style>
  .panel {
    display: flex;
    flex-direction: column;
    height: 100%;
    background: var(--surface-0);
    border-left: 1px solid var(--line);
    width: min(380px, 100vw);
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 12px 8px 20px;
  }
  h2 {
    font-size: 1.05rem;
    margin: 0;
  }
  .label {
    padding: 12px 20px 6px;
    color: var(--text-muted);
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .list {
    flex: 1;
    min-height: 0;
  }
  .item {
    display: flex;
    align-items: center;
    gap: 8px;
    height: 56px;
    padding: 0 8px 0 12px;
  }
  .item.now {
    padding: 0 20px;
    gap: 12px;
  }
  .hit {
    display: flex;
    align-items: center;
    gap: 12px;
    flex: 1;
    min-width: 0;
    border: 0;
    background: none;
    color: inherit;
    font: inherit;
    text-align: left;
    padding: 4px 8px;
    border-radius: var(--radius-sm);
    cursor: pointer;
  }
  .hit:hover {
    background: var(--surface-1);
  }
  .thumb {
    width: 40px;
    flex: none;
  }
  .meta {
    min-width: 0;
    flex: 1;
  }
  .t,
  .a {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .now .t {
    color: var(--accent);
  }
  .a,
  .d {
    color: var(--text-muted);
    font-size: 0.85rem;
  }
  .rm {
    opacity: 0;
  }
  .item:hover .rm,
  .rm:focus-visible {
    opacity: 1;
  }
  .empty {
    padding: 8px 20px;
    color: var(--text-faint);
    font-size: 0.9rem;
  }
</style>
