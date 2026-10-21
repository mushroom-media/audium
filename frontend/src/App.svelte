<script lang="ts">
  import { onMount } from "svelte";
  import { setUnauthorizedHandler } from "./lib/api";
  import Icon, { type IconName } from "./lib/components/Icon.svelte";
  import PlayerBar from "./lib/components/PlayerBar.svelte";
  import QueuePanel from "./lib/components/QueuePanel.svelte";
  import { player } from "./lib/player.svelte";
  import { defineRoutes, href, navigate, router, startRouter } from "./lib/router.svelte";
  import { loadSession, session } from "./lib/session.svelte";
  import Album from "./routes/Album.svelte";
  import Albums from "./routes/Albums.svelte";
  import Artist from "./routes/Artist.svelte";
  import Artists from "./routes/Artists.svelte";
  import Auth from "./routes/Auth.svelte";
  import Home from "./routes/Home.svelte";
  import Search from "./routes/Search.svelte";
  import Settings from "./routes/Settings.svelte";
  import Tracks from "./routes/Tracks.svelte";

  defineRoutes({
    home: "/",
    albums: "/albums",
    album: "/albums/:id",
    artists: "/artists",
    artist: "/artists/:id",
    tracks: "/tracks",
    search: "/search",
    settings: "/settings",
    login: "/login",
    setup: "/setup",
    invite: "/invite/:token",
  });

  const NAV: { name: string; path: string; label: string; icon: IconName }[] = [
    { name: "home", path: "/", label: "Start", icon: "home" },
    { name: "albums", path: "/albums", label: "Alben", icon: "album" },
    { name: "artists", path: "/artists", label: "Künstler", icon: "artist" },
    { name: "tracks", path: "/tracks", label: "Titel", icon: "track" },
    { name: "search", path: "/search", label: "Suche", icon: "search" },
  ];
  const PUBLIC = new Set(["login", "setup", "invite"]);

  let searchInput: HTMLInputElement | undefined = $state();
  let searchValue = $state("");
  let searchTimer: ReturnType<typeof setTimeout> | undefined;

  onMount(() => {
    setUnauthorizedHandler(() => {
      session.user = null;
    });
    startRouter();
    player.init();
    loadSession();
  });

  // Gatekeeping: unauthenticated users only see login/setup/invite.
  $effect(() => {
    if (!session.ready) return;
    const name = router.route.name;
    if (!session.user && !PUBLIC.has(name)) navigate(session.needsSetup ? "/setup" : "/login", { replace: true });
    else if (session.user && (name === "login" || name === "setup")) navigate("/", { replace: true });
  });

  $effect(() => {
    player.quality = session.settings.stream_quality;
  });

  $effect(() => {
    if (router.route.name === "search") searchValue = router.route.query.get("q") ?? "";
  });

  function onSearch(value: string) {
    searchValue = value;
    clearTimeout(searchTimer);
    // Debounced: one request per pause in typing, not per keystroke.
    searchTimer = setTimeout(() => {
      const q = value.trim();
      const target = `/search${q ? `?q=${encodeURIComponent(q)}` : ""}`;
      navigate(target, { replace: router.route.name === "search" });
    }, 220);
  }

  function onKey(e: KeyboardEvent) {
    const t = e.target as HTMLElement;
    if (t.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(t.tagName)) {
      if (e.key === "Escape") t.blur();
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const actions: Record<string, () => void> = {
      " ": () => player.toggle(),
      ArrowLeft: () => (e.shiftKey ? player.prev() : player.seek(player.position - 10)),
      ArrowRight: () => (e.shiftKey ? player.next() : player.seek(player.position + 10)),
      ArrowUp: () => player.setVolume(player.volume + 0.05),
      ArrowDown: () => player.setVolume(player.volume - 0.05),
      m: () => player.setMuted(!player.muted),
      s: () => player.toggleShuffle(),
      r: () => player.cycleRepeat(),
      q: () => (player.queueOpen = !player.queueOpen),
      "/": () => searchInput?.focus(),
    };
    const action = actions[e.key];
    if (action) {
      e.preventDefault();
      action();
    }
  }

  const active = (name: string) =>
    router.route.name === name || (name === "albums" && router.route.name === "album") || (name === "artists" && router.route.name === "artist");
</script>

<svelte:window onkeydown={onKey} />

{#if !session.ready}
  <div class="boot" aria-busy="true"></div>
{:else if !session.user || PUBLIC.has(router.route.name)}
  {#if router.route.name === "invite"}
    <Auth mode="invite" token={router.route.params.token} />
  {:else}
    <Auth mode={session.needsSetup ? "setup" : "login"} />
  {/if}
{:else}
  <div class="shell" class:queue-open={player.queueOpen}>
    <nav class="side" aria-label="Navigation">
      <a class="logo" href={href("/")} aria-label="audium Start">
        <svg viewBox="0 0 64 64" width="26" height="26" aria-hidden="true"><g fill="currentColor"><rect x="14" y="26" width="6" height="12" rx="3" /><rect x="24" y="18" width="6" height="28" rx="3" /><rect x="34" y="12" width="6" height="40" rx="3" /><rect x="44" y="22" width="6" height="20" rx="3" /></g></svg>
        <span>audium</span>
      </a>
      {#each NAV.filter((n) => n.name !== "search") as n (n.name)}
        <a href={href(n.path)} class:active={active(n.name)} aria-current={active(n.name) ? "page" : undefined}>
          <Icon name={n.icon} /> <span>{n.label}</span>
        </a>
      {/each}
      <div class="spacer"></div>
      <a href={href("/settings")} class:active={active("settings")}><Icon name="settings" /> <span>Einstellungen</span></a>
    </nav>

    <header class="top">
      <label class="search">
        <Icon name="search" size={18} />
        <span class="sr-only">Suche</span>
        <input
          bind:this={searchInput}
          type="search"
          placeholder="Titel, Künstler, Alben"
          value={searchValue}
          oninput={(e) => onSearch(e.currentTarget.value)}
          autocomplete="off"
          spellcheck="false"
        />
      </label>
      <a class="icon-btn settings-link" href={href("/settings")} aria-label="Einstellungen"><Icon name="settings" /></a>
    </header>

    <main class="content">
      {#key router.route.name + (router.route.params.id ?? "")}
        {#if router.route.name === "home"}<Home />
        {:else if router.route.name === "albums"}<Albums />
        {:else if router.route.name === "album"}<Album id={router.route.params.id} />
        {:else if router.route.name === "artists"}<Artists />
        {:else if router.route.name === "artist"}<Artist id={router.route.params.id} />
        {:else if router.route.name === "tracks"}<Tracks />
        {:else if router.route.name === "search"}<Search />
        {:else if router.route.name === "settings"}<Settings />
        {:else}<div class="page"><p class="empty">Diese Seite gibt es nicht. <a href={href("/")}>Zur Startseite</a></p></div>
        {/if}
      {/key}
    </main>

    {#if player.queueOpen}<div class="queue"><QueuePanel /></div>{/if}

    <div class="player"><PlayerBar /></div>

    <nav class="tabs" aria-label="Navigation">
      {#each NAV as n (n.name)}
        <a href={href(n.path)} class:active={active(n.name)} aria-current={active(n.name) ? "page" : undefined}>
          <Icon name={n.icon} /><span>{n.label}</span>
        </a>
      {/each}
    </nav>
  </div>
{/if}

<style>
  .boot {
    height: 100dvh;
  }
  .shell {
    display: grid;
    grid-template-columns: var(--side-w) minmax(0, 1fr) auto;
    grid-template-rows: var(--top-h) minmax(0, 1fr) var(--player-h);
    grid-template-areas:
      "side top queue"
      "side main queue"
      "player player player";
    height: 100dvh;
  }
  .side {
    grid-area: side;
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 18px 12px;
    border-right: 1px solid var(--line);
  }
  .side a {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 9px 12px;
    border-radius: var(--radius-sm);
    color: var(--text-muted);
    text-decoration: none;
    font-weight: 500;
  }
  .side a:hover {
    color: var(--text);
  }
  .side a.active {
    color: var(--text);
    background: var(--surface-1);
  }
  .side .logo {
    color: var(--text);
    font-weight: 650;
    font-size: 1.1rem;
    letter-spacing: -0.01em;
    margin-bottom: 18px;
  }
  .spacer {
    flex: 1;
  }
  .top {
    grid-area: top;
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 0 24px;
  }
  .search {
    display: flex;
    align-items: center;
    gap: 10px;
    width: min(440px, 100%);
    height: 40px;
    padding: 0 14px;
    border-radius: 20px;
    background: var(--surface-1);
    color: var(--text-muted);
  }
  .search:focus-within {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }
  .search input {
    flex: 1;
    border: 0;
    background: none;
    color: var(--text);
    font: inherit;
    outline: none;
    min-width: 0;
    padding: 0;
  }
  .settings-link {
    display: none;
    margin-left: auto;
  }
  .content {
    grid-area: main;
    min-height: 0;
    overflow: hidden;
  }
  .queue {
    grid-area: queue;
    min-height: 0;
  }
  .player {
    grid-area: player;
  }
  .tabs {
    display: none;
  }

  @media (max-width: 860px) {
    .shell {
      grid-template-columns: minmax(0, 1fr);
      grid-template-rows: var(--top-h) minmax(0, 1fr) var(--player-h) var(--tabs-h);
      grid-template-areas: "top" "main" "player" "tabs";
    }
    .side {
      display: none;
    }
    .top {
      padding: 0 16px;
    }
    .settings-link {
      display: grid;
    }
    .queue {
      position: fixed;
      inset: 0 0 calc(var(--player-h) + var(--tabs-h)) 0;
      z-index: 10;
    }
    .tabs {
      grid-area: tabs;
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      background: var(--surface-0);
      border-top: 1px solid var(--line);
      padding-bottom: env(safe-area-inset-bottom);
    }
    .tabs a {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 3px;
      font-size: 0.68rem;
      color: var(--text-muted);
      text-decoration: none;
    }
    .tabs a.active {
      color: var(--text);
    }
  }
</style>
