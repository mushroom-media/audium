<script lang="ts" module>
  import { isApp } from "../api";

  const ua = typeof navigator !== "undefined" ? navigator.userAgent : "";

  /** The desktop app has no system title bar; the top bar of the page takes its place.
   * - "buttons" (Windows, Linux): no title bar at all (app/src-tauri/tauri.windows.conf.json,
   *   tauri.linux.conf.json); this component draws minimize, maximize and close.
   * - "mac" (macOS): the page reaches up under a transparent title bar that keeps the system's
   *   buttons at the top left (tauri.macos.conf.json); here only the room for them. */
  export const frameKind: "buttons" | "mac" | null = !isApp || /Android|iPhone|iPad/.test(ua)
    ? null
    : /Macintosh/.test(ua)
      ? "mac"
      : /Windows|Linux/.test(ua)
        ? "buttons"
        : null;
  export const ownFrame = frameKind !== null;
</script>

<script lang="ts">
  import type { Window } from "@tauri-apps/api/window";
  import { t } from "../i18n.svelte";

  // `strip`: a bar of its own above the page, for screens whose top bar cannot take the buttons
  // (login, narrow window, now playing). Otherwise the buttons sit at the right end of the top
  // bar, which is the drag area (App.svelte).
  let { strip }: { strip: boolean } = $props();

  let win: Window | undefined;
  let maximized = $state(false);

  $effect(() => {
    let unlisten: (() => void) | undefined;
    let gone = false;
    import("@tauri-apps/api/window").then(async ({ getCurrentWindow }) => {
      win = getCurrentWindow();
      maximized = await win.isMaximized();
      const off = await win.onResized(async () => {
        maximized = (await win?.isMaximized()) ?? false;
      });
      if (gone) off();
      else unlisten = off;
    }).catch(() => {
      /* not inside Tauri (the app build opened in a browser): the buttons do nothing */
    });
    return () => {
      gone = true;
      unlisten?.();
    };
  });

  // macOS: the height of its standard title bar, where its buttons sit.
  const stripHeight = frameKind === "mac" ? 28 : 32;

  $effect(() => {
    const root = document.documentElement;
    root.style.setProperty("--frame-top", strip ? `${stripHeight}px` : "0px");
    root.classList.add("own-frame");
    // Gone while "now playing" fills the screen (appFullscreen.svelte.ts): no space above the page.
    return () => root.style.setProperty("--frame-top", "0px");
  });
</script>

{#if strip}<div class="strip" style:height="{stripHeight}px" data-tauri-drag-region></div>{/if}
<!-- In the top bar the buttons are as tall as the bar, so their icons line up with the search
     field and the profile picture. macOS draws its own buttons. -->
{#if frameKind === "buttons"}
<div class="controls" class:tall={!strip}>
  <button title={t("Minimieren")} aria-label={t("Minimieren")} onclick={() => win?.minimize()}>
    <svg viewBox="0 0 10 10" aria-hidden="true"><path d="M0 5h10" /></svg>
  </button>
  <button
    title={maximized ? t("Verkleinern") : t("Maximieren")}
    aria-label={maximized ? t("Verkleinern") : t("Maximieren")}
    onclick={() => win?.toggleMaximize()}
  >
    {#if maximized}
      <svg viewBox="0 0 10 10" aria-hidden="true"><path d="M0.5 2.5h7v7h-7z M2.5 2.5v-2h7v7h-2" /></svg>
    {:else}
      <svg viewBox="0 0 10 10" aria-hidden="true"><path d="M0.5 0.5h9v9h-9z" /></svg>
    {/if}
  </button>
  <button class="close" title={t("Schließen")} aria-label={t("Schließen")} onclick={() => win?.close()}>
    <svg viewBox="0 0 10 10" aria-hidden="true"><path d="M0 0l10 10M10 0L0 10" /></svg>
  </button>
</div>
{/if}

<style>
  .strip {
    position: fixed;
    inset: 0 0 auto 0;
    z-index: 1000;
    background: var(--bg);
  }
  .controls {
    position: fixed;
    top: 0;
    right: 0;
    z-index: 1001;
    display: flex;
  }
  button {
    width: 46px;
    height: 32px;
    padding: 0;
    border: 0;
    display: grid;
    place-items: center;
    background: transparent;
    color: var(--text);
    cursor: default;
  }
  .tall button {
    height: var(--top-h);
  }
  button:hover {
    background: color-mix(in srgb, var(--text) 10%, transparent);
  }
  button:active {
    background: color-mix(in srgb, var(--text) 18%, transparent);
  }
  .close:hover,
  .close:active {
    background: #c42b1c;
    color: #fff;
  }
  button:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: -2px;
  }
  svg {
    width: 10px;
    height: 10px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1;
    shape-rendering: crispEdges;
  }
  .close svg {
    shape-rendering: geometricPrecision;
  }
</style>
