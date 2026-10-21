<script lang="ts">
  // The "…" menu for tracks: queue actions, add to playlist, favorite. Rendered once in App.
  import { addToPlaylist, createPlaylist, editable, mine, toggleFavorite } from "../mine.svelte";
  import { player } from "../player.svelte";
  import { promptText, toast, ui } from "../ui.svelte";
  import Icon from "./Icon.svelte";

  let el: HTMLDivElement | undefined = $state();
  let sub = $state(false);
  const menu = $derived(ui.menu);
  const lists = $derived(menu ? editable() : []);
  const single = $derived(menu && menu.tracks.length === 1 ? menu.tracks[0] : null);

  // Keep the menu on screen.
  const pos = $derived.by(() => {
    if (!menu) return { left: 0, top: 0 };
    const w = 260;
    const h = 320;
    return {
      left: Math.max(8, Math.min(menu.x - w, window.innerWidth - w - 8)),
      top: Math.max(8, Math.min(menu.y, window.innerHeight - h - 8)),
    };
  });

  $effect(() => {
    if (!menu) {
      sub = false;
      return;
    }
    el?.querySelector<HTMLElement>("button")?.focus();
    const close = (e: Event) => {
      if (el && e.target instanceof Node && el.contains(e.target)) return;
      ui.menu = null;
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && (ui.menu = null);
    setTimeout(() => {
      document.addEventListener("pointerdown", close);
      document.addEventListener("keydown", esc);
    });
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", esc);
    };
  });

  function done(text?: string) {
    ui.menu = null;
    if (text) toast(text);
  }

  async function addTo(id: number, name: string) {
    const tracks = menu!.tracks;
    done();
    try {
      await addToPlaylist(id, tracks.map((t) => t.id));
      toast(`Zu „${name}“ hinzugefügt`);
    } catch {
      toast("Hinzufügen fehlgeschlagen");
    }
  }

  async function addToNew() {
    const tracks = menu!.tracks;
    done();
    const name = await promptText("Neue Playlist", "", "Erstellen");
    if (!name) return;
    await createPlaylist(name, tracks.map((t) => t.id));
    toast(`Playlist „${name}“ erstellt`);
  }
</script>

{#if menu}
  <div class="menu" bind:this={el} role="menu" style:left="{pos.left}px" style:top="{pos.top}px" aria-label={menu.label}>
    <div class="label">{menu.label}</div>
    {#if !sub}
      <button role="menuitem" onclick={() => (player.playNext(menu.tracks), done("Wird als Nächstes gespielt"))}>
        <Icon name="next" size={16} /> Als Nächstes spielen
      </button>
      <button role="menuitem" onclick={() => (player.append(menu.tracks), done("Zur Warteschlange hinzugefügt"))}>
        <Icon name="queue" size={16} /> Zur Warteschlange
      </button>
      <button role="menuitem" onclick={() => (sub = true)}>
        <Icon name="plus" size={16} /> Zu Playlist hinzufügen <span class="chev">›</span>
      </button>
      {#if single}
        <button role="menuitem" onclick={() => { toggleFavorite(single); done(); }}>
          <Icon name="heart" size={16} /> {mine.favoriteTracks.has(single.id) ? "Aus Lieblingssongs entfernen" : "Zu Lieblingssongs"}
        </button>
      {/if}
    {:else}
      <button role="menuitem" onclick={() => (sub = false)}><Icon name="back" size={16} /> Zurück</button>
      <button role="menuitem" onclick={addToNew}><Icon name="plus" size={16} /> Neue Playlist …</button>
      <div class="scroll">
        {#each lists as p (p.id)}
          <button role="menuitem" onclick={() => addTo(p.id, p.name)}>
            <span class="pl">{p.name}</span>{#if p.role === "editor"}<span class="tag">geteilt</span>{/if}
          </button>
        {:else}
          <p class="empty">Noch keine Playlists.</p>
        {/each}
      </div>
    {/if}
  </div>
{/if}

<style>
  .menu {
    position: fixed;
    z-index: 50;
    width: 260px;
    padding: 6px;
    border-radius: 12px;
    background: var(--surface-1);
    border: 1px solid var(--surface-2);
    box-shadow: 0 16px 40px rgb(0 0 0 / 0.4);
  }
  .label {
    padding: 6px 10px 8px;
    font-size: 0.78rem;
    color: var(--text-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  button {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    padding: 9px 10px;
    border: 0;
    border-radius: 8px;
    background: none;
    color: var(--text);
    text-align: left;
    cursor: pointer;
  }
  button:hover,
  button:focus-visible {
    background: var(--surface-2);
    outline: none;
  }
  .chev {
    margin-left: auto;
    color: var(--text-muted);
  }
  .scroll {
    max-height: 220px;
    overflow-y: auto;
  }
  .pl {
    flex: 1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .tag {
    font-size: 0.7rem;
    color: var(--text-muted);
  }
  .empty {
    color: var(--text-muted);
    font-size: 0.85rem;
    padding: 6px 10px;
    margin: 0;
  }
</style>
