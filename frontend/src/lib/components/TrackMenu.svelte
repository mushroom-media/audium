<script lang="ts">
  // The "…" menu for tracks: queue actions, add to playlist, favorite. Rendered once in App.
  // Wide screens get a popover next to the button; phones a sheet that rises from the bottom.
  import { tick, untrack } from "svelte";
  import { cubicOut } from "svelte/easing";
  import { fade } from "svelte/transition";
  import { addToPlaylist, createPlaylist, editable, mine, toggleFavorite } from "../mine.svelte";
  import { player } from "../player.svelte";
  import { radioPath } from "../radio";
  import { navigate } from "../router.svelte";
  import { promptText, toast, ui } from "../ui.svelte";
  import Cover from "./Cover.svelte";
  import Icon from "./Icon.svelte";
  import { t } from "../i18n.svelte";

  const phone = typeof matchMedia === "function" ? matchMedia("(max-width: 860px)") : null;
  const reducedMotion = typeof matchMedia === "function" ? matchMedia("(prefers-reduced-motion: reduce)") : null;
  // A sheet pulled down this far, or flicked down this fast (px/ms), closes.
  const CLOSE_DRAG_PX = 90;
  const CLOSE_VELOCITY = 0.5;

  let el: HTMLDivElement | undefined = $state();
  let sub = $state(false);
  const menu = $derived(ui.menu);
  const open = $derived(!!ui.menu);
  // Decided when the menu opens.
  const sheet = $derived(open && !!phone?.matches);
  const lists = $derived(menu ? editable() : []);
  const single = $derived(menu && menu.tracks.length === 1 ? menu.tracks[0] : null);

  // Keep the menu on screen.
  const pos = $derived.by(() => {
    if (!menu) return { left: 0, top: 0 };
    const w = 260;
    const h = 440;
    return {
      left: Math.max(8, Math.min(menu.x - w, window.innerWidth - w - 8)),
      top: Math.max(8, Math.min(menu.y, window.innerHeight - h - 8)),
    };
  });

  // The sheet has a history entry of its own, so "back" (the system's swipe back too) closes it
  // and leaves what is under it, the now playing view included, as it was.
  let inHistory = false;
  let leaving: Promise<void> = Promise.resolve();

  $effect(() => {
    if (!open) {
      sub = false;
      return;
    }
    drag = 0;
    if (sheet) {
      history.pushState({ ...(history.state ?? {}), sheet: true }, "", window.location.href);
      inHistory = true;
    }
    if (!sheet) untrack(() => el)?.querySelector<HTMLElement>("button")?.focus();
    const close = (e: Event) => {
      if (el && e.target instanceof Node && el.contains(e.target)) return;
      ui.menu = null;
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && (ui.menu = null);
    const back = () => {
      if (!inHistory || history.state?.sheet) return;
      inHistory = false;
      ui.menu = null;
    };
    setTimeout(() => {
      document.addEventListener("pointerdown", close);
      document.addEventListener("keydown", esc);
    });
    window.addEventListener("popstate", back);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", esc);
      window.removeEventListener("popstate", back);
      // Closed some other way than "back": take its history entry away again.
      if (inHistory) {
        inHistory = false;
        leaving = new Promise((resolve) => window.addEventListener("popstate", () => resolve(), { once: true }));
        history.back();
      }
    };
  });

  /** Closes the menu; resolves once its history entry is gone, so a navigation lands after it. */
  async function done(text?: string) {
    ui.menu = null;
    if (text) toast(text);
    await tick();
    await leaving;
  }

  async function go(path: string) {
    await done();
    navigate(path);
  }

  async function addTo(id: number, name: string) {
    const tracks = menu!.tracks;
    done();
    try {
      await addToPlaylist(id, tracks.map((t) => t.id));
      toast(t("Zu „{name}“ hinzugefügt", { name }));
    } catch {
      toast(t("Hinzufügen fehlgeschlagen"));
    }
  }

  async function addToNew() {
    const tracks = menu!.tracks;
    await done();
    const name = await promptText("Neue Playlist", "", "Erstellen");
    if (!name) return;
    await createPlaylist(name, tracks.map((t) => t.id));
    toast(t("Playlist „{name}“ erstellt", { name }));
  }

  // --- pulling the sheet down ------------------------------------------------------------------
  let drag = $state(0);
  let pull: { y: number; samples: { y: number; t: number }[]; active: boolean } | null = null;

  function onTouchStart(e: TouchEvent) {
    if (e.touches.length !== 1) return;
    const scroller = (e.target as HTMLElement).closest(".body");
    // Inside the list only from its top, so scrolling it stays scrolling.
    if (scroller && scroller.scrollTop > 0) return;
    pull = { y: e.touches[0].clientY, samples: [], active: false };
  }
  function onTouchMove(e: TouchEvent) {
    if (!pull) return;
    const dy = e.touches[0].clientY - pull.y;
    if (!pull.active) {
      if (dy < 6) {
        if (dy < -6) pull = null; // an upward move scrolls the list
        return;
      }
      pull.active = true;
      pull.y = e.touches[0].clientY;
    }
    if (e.cancelable) e.preventDefault();
    pull.samples.push({ y: e.touches[0].clientY, t: e.timeStamp });
    while (pull.samples.length > 2 && e.timeStamp - pull.samples[0].t > 100) pull.samples.shift();
    drag = Math.max(0, e.touches[0].clientY - pull.y);
  }
  function onTouchEnd(e: TouchEvent) {
    const p = pull;
    pull = null;
    if (!p?.active) return;
    const first = p.samples[0];
    const last = p.samples[p.samples.length - 1];
    const velocity = first && last.t > first.t ? (last.y - first.y) / (last.t - first.t) : 0;
    if (e.type !== "touchcancel" && (drag > CLOSE_DRAG_PX || velocity > CLOSE_VELOCITY)) done();
    else drag = 0;
  }

  /** The sheet rises from the bottom and sinks back from wherever a pull left it. */
  function rise(node: HTMLElement) {
    const from = open ? 0 : drag;
    const h = node.offsetHeight;
    return {
      duration: reducedMotion?.matches ? 0 : 260,
      easing: cubicOut,
      css: (_t: number, u: number) => `transform: translateY(${from + u * (h - from)}px)`,
    };
  }

  // Svelte 5 sets non-passive touch handlers through an action, so a pull can stop the page scrolling.
  function pullable(node: HTMLElement) {
    node.addEventListener("touchstart", onTouchStart, { passive: true });
    node.addEventListener("touchmove", onTouchMove, { passive: false });
    node.addEventListener("touchend", onTouchEnd);
    node.addEventListener("touchcancel", onTouchEnd);
    return {
      destroy() {
        node.removeEventListener("touchstart", onTouchStart);
        node.removeEventListener("touchmove", onTouchMove);
        node.removeEventListener("touchend", onTouchEnd);
        node.removeEventListener("touchcancel", onTouchEnd);
      },
    };
  }
</script>

{#snippet items(m: NonNullable<typeof menu>, size: number)}
  {#if !sub}
    <button role="menuitem" onclick={() => (player.playNext(m.tracks), done(t("Wird als Nächstes gespielt")))}>
      <Icon name="next" {size} /> {t("Als Nächstes spielen")}
    </button>
    <button role="menuitem" onclick={() => (player.enqueue(m.tracks), done(t("Zur Warteschlange hinzugefügt")))}>
      <Icon name="queue" {size} /> {t("Zur Warteschlange")}
    </button>
    <button role="menuitem" onclick={() => (sub = true)}>
      <Icon name="plus" {size} /> {t("Zu Playlist hinzufügen")} <span class="chev">›</span>
    </button>
    {#if single}
      <button role="menuitem" onclick={() => go(radioPath("track", single.id))}>
        <Icon name="radio" {size} /> {t("Zum Radio")}
      </button>
      <button role="menuitem" onclick={() => go(`/tracks/${single.id}/similar`)}>
        <Icon name="spark" {size} /> {t("Ähnliche Titel")}
      </button>
      {#if single.artists && single.artists.length > 1}
        {#each single.artists as a (a.id)}
          <button role="menuitem" onclick={() => go(`/artists/${a.id}`)}>
            <Icon name="artist" {size} /> {t("Zu {name}", { name: a.name })}
          </button>
        {/each}
      {:else}
        <button role="menuitem" onclick={() => go(`/artists/${single.artist_id}`)}>
          <Icon name="artist" {size} /> {t("Zum Künstler / zur Künstlerin")}
        </button>
      {/if}
      <button role="menuitem" onclick={() => go(`/albums/${single.album_id}`)}>
        <Icon name="album" {size} /> {t("Zum Album")}
      </button>
      <button role="menuitem" onclick={async () => { const id = single.id; await done(); ui.info = { trackId: id }; }}>
        <Icon name="info" {size} /> {t("Info")}
      </button>
      <button role="menuitem" onclick={() => { toggleFavorite(single); done(); }}>
        <Icon name="heart" {size} /> {mine.favoriteTracks.has(single.id) ? t("Aus Lieblingssongs entfernen") : t("Zu Lieblingssongs")}
      </button>
    {/if}
  {:else}
    <button role="menuitem" onclick={() => (sub = false)}><Icon name="back" {size} /> {t("Zurück")}</button>
    <button role="menuitem" onclick={addToNew}><Icon name="plus" {size} /> {t("Neue Playlist …")}</button>
    <div class="scroll">
      {#each lists as p (p.id)}
        <button role="menuitem" onclick={() => addTo(p.id, p.name)}>
          <span class="pl">{p.name}</span>{#if p.role === "editor"}<span class="tag">{t("geteilt")}</span>{/if}
        </button>
      {:else}
        <p class="empty">{t("Noch keine Playlists.")}</p>
      {/each}
    </div>
  {/if}
{/snippet}

{#if menu}
  {#if sheet}
    <div class="backdrop" transition:fade={{ duration: reducedMotion?.matches ? 0 : 200 }} style:opacity={drag ? Math.max(0.2, 1 - drag / 400) : undefined}></div>
    <div
      class="sheet"
      class:dragging={drag > 0}
      bind:this={el}
      role="menu"
      aria-label={menu.label}
      style:transform={drag ? `translateY(${drag}px)` : undefined}
      transition:rise
      use:pullable
    >
      <div class="handle" aria-hidden="true"></div>
      <div class="head">
        {#if single}
          <span class="cover"><Cover hash={single.cover} size={64} /></span>
          <span class="who"><strong>{single.title}</strong><small>{single.artist}</small></span>
        {:else}
          <span class="who"><strong>{menu.label}</strong></span>
        {/if}
      </div>
      <div class="body">{@render items(menu, 20)}</div>
    </div>
  {:else}
    <div class="menu" bind:this={el} role="menu" style:left="{pos.left}px" style:top="{pos.top}px" aria-label={menu.label}>
      <div class="label">{menu.label}</div>
      {@render items(menu, 16)}
    </div>
  {/if}
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

  /* --- the phone sheet --- */
  .backdrop {
    position: fixed;
    inset: 0;
    z-index: 50;
    background: rgb(0 0 0 / 0.5);
  }
  .sheet {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 51;
    display: flex;
    flex-direction: column;
    max-height: 85dvh;
    padding: 0 8px env(safe-area-inset-bottom);
    border-radius: 16px 16px 0 0;
    background: var(--surface-1);
    box-shadow: 0 -8px 32px rgb(0 0 0 / 0.35);
    transition: transform 0.22s cubic-bezier(0.2, 0.9, 0.3, 1);
  }
  .sheet.dragging {
    transition: none;
  }
  .handle {
    flex: none;
    width: 36px;
    height: 5px;
    margin: 8px auto 4px;
    border-radius: 3px;
    background: var(--text-muted);
    opacity: 0.5;
  }
  .head {
    flex: none;
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 12px 12px;
    border-bottom: 1px solid var(--surface-2);
  }
  .cover {
    width: 44px;
    flex: none;
  }
  .who {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .who strong,
  .who small {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .who strong {
    font-weight: 600;
  }
  .who small {
    color: var(--text-muted);
  }
  .body {
    overflow-y: auto;
    overscroll-behavior: contain;
    padding: 6px 0 10px;
  }
  .sheet button {
    gap: 16px;
    min-height: 50px;
    padding: 12px;
    font-size: 1rem;
    border-radius: 10px;
  }
  .sheet button:hover {
    background: none;
  }
  .sheet button:active {
    background: var(--surface-2);
  }
  .sheet .scroll {
    max-height: none;
    overflow: visible;
  }
</style>
