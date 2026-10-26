<script lang="ts">
  // Settings with subpages. Wide screens: the list on the left, the page beside it.
  // Phones: /settings is the list, /settings/<page> the page with a back button.
  import type { Component } from "svelte";
  import Icon, { type IconName } from "../lib/components/Icon.svelte";
  import { href } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";
  import Account from "./settings/Account.svelte";
  import Analysis from "./settings/Analysis.svelte";
  import Appearance from "./settings/Appearance.svelte";
  import Apps from "./settings/Apps.svelte";
  import Jobs from "./settings/Jobs.svelte";
  import Library from "./settings/Library.svelte";
  import LibraryOptions from "./settings/LibraryOptions.svelte";
  import Playback from "./settings/Playback.svelte";
  import Shortcuts from "./settings/Shortcuts.svelte";
  import Users from "./settings/Users.svelte";

  let { section }: { section?: string } = $props();

  interface PageDef {
    id: string;
    title: string;
    short: string;
    icon: IconName;
    admin?: boolean;
    component: Component;
  }
  const PAGES: PageDef[] = [
    { id: "playback", title: "Wiedergabe", short: "Streaming-Qualität", icon: "play", component: Playback },
    { id: "appearance", title: "Darstellung", short: "Farbschema", icon: "palette", component: Appearance },
    { id: "shortcuts", title: "Tastenkürzel", short: "Steuerung per Tastatur", icon: "keyboard", component: Shortcuts },
    { id: "account", title: "Konto", short: "Profil, Abmelden", icon: "user", component: Account },
    { id: "apps", title: "Apps verbinden", short: "Symfonium, Amperfy & Co.", icon: "phone", component: Apps },
    { id: "library-options", title: "Bibliothek", short: "Künstlerbilder", icon: "album", admin: true, component: LibraryOptions },
    { id: "library", title: "Musikordner", short: "Ordner, Scan, Statistik", icon: "folder", admin: true, component: Library },
    { id: "analysis", title: "Audioanalyse", short: "Fortschritt, Klangerkennung", icon: "wave", admin: true, component: Analysis },
    { id: "users", title: "Nutzer", short: "Konten, Einladungen", icon: "users", admin: true, component: Users },
    { id: "jobs", title: "Hintergrundjobs", short: "Scans, Analysen, Playlists", icon: "jobs", admin: true, component: Jobs },
  ];

  const isAdmin = $derived(session.user?.role === "admin");
  const visible = $derived(PAGES.filter((p) => !p.admin || isAdmin));
  const groups = $derived([
    { title: "Persönlich", pages: visible.filter((p) => !p.admin) },
    { title: "Server", pages: visible.filter((p) => p.admin) },
  ]);
  const page = $derived(visible.find((p) => p.id === section) ?? visible[0]);
</script>

<div class="page settings" class:has-section={!!section}>
  <nav class="index" aria-label="Einstellungen">
    <div class="toolbar"><h1>Einstellungen</h1></div>
    {#each groups as g (g.title)}
      {#if g.pages.length}
        <section class="set-group">
          <h2>{g.title}</h2>
          <div class="set-card">
            {#each g.pages as p (p.id)}
              <a class="entry" class:on={p.id === page.id} href={href(`/settings/${p.id}`)} aria-current={p.id === page.id && section ? "page" : undefined}>
                <span class="tile" aria-hidden="true"><Icon name={p.icon} size={18} /></span>
                <span class="text"><strong>{p.title}</strong><small>{p.short}</small></span>
                <span class="chev" aria-hidden="true"><Icon name="chevron" size={16} /></span>
              </a>
            {/each}
          </div>
        </section>
      {/if}
    {/each}
  </nav>

  <div class="body">
    <div class="toolbar"><h1>{page.title}</h1></div>
    <div class="content">
      {#key page.id}<page.component />{/key}
    </div>
  </div>
</div>

<style>
  .settings {
    display: grid;
    grid-template-columns: 280px minmax(0, 1fr);
    align-items: start;
  }
  .index {
    position: sticky;
    top: 0;
    padding: 0 0 24px 24px;
  }
  .index .toolbar {
    padding-left: 4px;
  }
  .index .set-card {
    background: transparent;
    border: 0;
  }
  .entry {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 10px;
    border-radius: 12px;
    color: var(--text);
    text-decoration: none;
  }
  .entry:hover {
    background: var(--surface-1);
  }
  .entry.on {
    background: var(--surface-1);
  }
  .entry.on .tile {
    background: var(--accent);
    color: var(--accent-contrast);
  }
  .tile {
    width: 34px;
    height: 34px;
    border-radius: 10px;
    display: grid;
    place-items: center;
    background: var(--surface-1);
    color: var(--accent);
    flex: none;
  }
  .text {
    display: flex;
    flex-direction: column;
    min-width: 0;
    flex: 1;
  }
  .text strong {
    font-weight: 550;
    font-size: 0.93rem;
  }
  .text small {
    color: var(--text-muted);
    font-size: 0.8rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .chev {
    display: none;
    color: var(--text-faint);
  }
  .body {
    min-width: 0;
  }
  .content {
    max-width: 760px;
    padding: 0 24px 40px;
  }

  @media (max-width: 860px) {
    .settings {
      display: block;
    }
    .settings:not(.has-section) .body,
    .settings.has-section .index {
      display: none;
    }
    .index {
      position: static;
      padding: 0 16px 24px;
    }
    .index .toolbar {
      padding-left: 0;
    }
    /* On phones the list is a grouped card with chevrons, like system settings. */
    .index .set-card {
      background: var(--surface-0);
      border: 1px solid var(--line);
    }
    .entry {
      border-radius: 0;
      padding: 12px 14px;
      min-height: 60px;
    }
    .entry + .entry {
      border-top: 1px solid var(--line);
    }
    .entry.on:not([aria-current]) {
      background: none;
    }
    .entry.on:not([aria-current]) .tile {
      background: var(--surface-1);
      color: var(--accent);
    }
    .chev {
      display: block;
    }
    .content {
      padding: 0 16px 32px;
    }
  }
</style>
