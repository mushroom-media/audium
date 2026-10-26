<script lang="ts">
  import { onMount, tick, untrack } from "svelte";
  import { setUnauthorizedHandler } from "./lib/api";
  import Icon, { type IconName } from "./lib/components/Icon.svelte";
  import PlaylistCover from "./lib/components/PlaylistCover.svelte";
  import Overlays from "./lib/components/Overlays.svelte";
  import NowPlaying from "./lib/components/NowPlaying.svelte";
  import PlayerBar from "./lib/components/PlayerBar.svelte";
  import QueuePanel from "./lib/components/QueuePanel.svelte";
  import DevicePicker from "./lib/components/DevicePicker.svelte";
  import { devices } from "./lib/devices.svelte";
  import { startTabs } from "./lib/tabs.svelte";
  import { player } from "./lib/player.svelte";
  import { defineRoutes, goBack, href, navigate, router, startRouter } from "./lib/router.svelte";
  import { disconnectEvents, loadMine, mine, newPlaylistFlow } from "./lib/mine.svelte";
  import { loadRecentSearches, rememberSearch } from "./lib/recentSearches.svelte";
  import { loadSession, session } from "./lib/session.svelte";
  import { ui } from "./lib/ui.svelte";
  import RuleEditor from "./lib/components/RuleEditor.svelte";
  import { post, type Playlist as PlaylistT, type Rule } from "./lib/api";
  import Album from "./routes/Album.svelte";
  import AutoPlaylist from "./routes/AutoPlaylist.svelte";
  import Discover from "./routes/Discover.svelte";
  import Similar from "./routes/Similar.svelte";
  import Radio from "./routes/Radio.svelte";
  import Artist from "./routes/Artist.svelte";
  import Auth from "./routes/Auth.svelte";
  import Profile from "./routes/Profile.svelte";
  import FavoriteAlbums from "./routes/FavoriteAlbums.svelte";
  import Favorites from "./routes/Favorites.svelte";
  import Home from "./routes/Home.svelte";
  import Library from "./routes/Library.svelte";
  import Playlist from "./routes/Playlist.svelte";
  import Search from "./routes/Search.svelte";
  import Settings from "./routes/Settings.svelte";

  // Creating smart playlists from the sidebar is switched off for now; existing ones keep working.
  const SMART_PLAYLIST_BUTTON = false;

  defineRoutes({
    home: "/",
    library: "/library",
    albums: "/albums",
    album: "/albums/:id",
    artists: "/artists",
    artist: "/artists/:id",
    tracks: "/tracks",
    playlist: "/playlists/:id",
    discover: "/discover",
    auto: "/discover/:id",
    similar: "/tracks/:id/similar",
    radio: "/radio/:kind/:id",
    favorites: "/favorites",
    favoriteAlbums: "/favorites/albums",
    profile: "/profile",
    search: "/search",
    settings: "/settings",
    settingsPage: "/settings/:section",
    admin: "/admin",
    login: "/login",
    setup: "/setup",
    invite: "/invite/:token",
  });

  const NAV: { name: string; path: string; label: string; icon: IconName }[] = [
    { name: "home", path: "/", label: "Start", icon: "home" },
    { name: "search", path: "/search", label: "Suche", icon: "search" },
    { name: "library", path: "/library", label: "Bibliothek", icon: "album" },
    { name: "discover", path: "/discover", label: "Entdecken", icon: "compass" },
    { name: "profile", path: "/profile", label: "Profil", icon: "user" },
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
    startTabs(); // several tabs of this browser are one player
    loadSession();
  });

  // Gatekeeping: unauthenticated users only see login/setup/invite.
  $effect(() => {
    if (!session.ready) return;
    const name = router.route.name;
    if (!session.user && !PUBLIC.has(name)) navigate(session.needsSetup ? "/setup" : "/login", { replace: true });
    else if (session.user && (name === "login" || name === "setup")) navigate("/", { replace: true });
  });

  // The former admin page is part of the settings now; keep old links working.
  $effect(() => {
    if (router.route.name !== "admin") return;
    const tab = router.route.query.get("tab");
    navigate(`/settings/${tab === "users" || tab === "jobs" ? tab : "library"}`, { replace: true });
  });

  // Alben, Titel and Künstler are tabs of the library now; keep old links (and saved queue sources) working.
  $effect(() => {
    const name = router.route.name;
    if (name !== "albums" && name !== "tracks" && name !== "artists") return;
    const q = router.route.query.get("q");
    navigate(`/library?tab=${name}${q ? `&q=${encodeURIComponent(q)}` : ""}`, { replace: true });
  });

  $effect(() => {
    player.quality = session.settings.stream_quality;
  });

  // Playlists, favorites and the live-update connection belong to the logged-in user.
  $effect(() => {
    if (session.user) {
      loadMine().catch(() => {});
      loadRecentSearches();
    }
    else disconnectEvents();
  });

  async function createSmart(name: string, rule: Rule) {
    const pl = await post<PlaylistT>("/playlists", { name, rule });
    ui.smartEditor = false;
    await loadMine();
    navigate(`/playlists/${pl.id}`);
  }

  async function newPlaylist() {
    const pl = await newPlaylistFlow();
    if (pl) navigate(`/playlists/${pl.id}`);
  }

  // Follow the URL (back/forward, links), but not our own debounced navigation: the URL holds the
  // trimmed query, and copying it back would eat the space the user just typed.
  $effect(() => {
    if (router.route.name !== "search") return;
    const q = router.route.query.get("q") ?? "";
    if (q !== untrack(() => searchValue).trim()) searchValue = q;
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

  // Enter: search right away, and remember the query.
  function onSearchKey(e: KeyboardEvent & { currentTarget: HTMLInputElement }) {
    if (e.key !== "Enter") return;
    const q = e.currentTarget.value.trim();
    clearTimeout(searchTimer);
    navigate(`/search${q ? `?q=${encodeURIComponent(q)}` : ""}`, { replace: router.route.name === "search" });
    rememberSearch({ kind: "query", q });
    if (window.matchMedia("(max-width: 860px)").matches) e.currentTarget.blur(); // closes the keyboard
  }

  // Phones show the search field only on the search page; opening it empty starts typing there.
  $effect(() => {
    if (router.route.name !== "search" || untrack(() => searchValue)) return;
    tick().then(() => searchInput?.focus());
  });

  function onKey(e: KeyboardEvent) {
    const t = e.target as HTMLElement;
    if (t.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(t.tagName)) {
      if (e.key === "Escape") t.blur();
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey || session.settings.shortcuts === "off") return;
    const actions: Record<string, (() => void) | undefined> = {
      " ": () => player.toggle(),
      ArrowLeft: () => (e.shiftKey ? player.prev() : player.seek(player.position - 10)),
      ArrowRight: () => (e.shiftKey ? player.next() : player.seek(player.position + 10)),
      // Plain ↑/↓ scroll the page; with Shift they change the volume.
      ArrowUp: e.shiftKey ? () => player.setVolume(player.volume + 0.05) : undefined,
      ArrowDown: e.shiftKey ? () => player.setVolume(player.volume - 0.05) : undefined,
      m: () => player.setMuted(!player.muted),
      s: () => player.toggleShuffle(),
      r: () => player.cycleRepeat(),
      q: () => (player.queueOpen = !player.queueOpen),
      n: () => (player.nowPlayingOpen = !player.nowPlayingOpen),
      "/": () => searchInput?.focus(),
    };
    const action = actions[e.key];
    if (action) {
      e.preventDefault();
      action();
    }
  }

  // Detail pages get a back button; the fallback is where it leads when there is no app history.
  const BACK: Record<string, string> = {
    album: "/library?tab=albums",
    artist: "/library?tab=artists",
    playlist: "/",
    favorites: "/profile",
    favoriteAlbums: "/profile",
    auto: "/discover",
    similar: "/library?tab=tracks",
    radio: "/",
    settingsPage: "/settings",
  };
  const backTo = $derived(BACK[router.route.name]);
  const initial = $derived((session.user?.display_name ?? "?").trim().charAt(0).toUpperCase());

  const active = (name: string) =>
    router.route.name === name ||
    (name === "library" && (router.route.name === "album" || router.route.name === "artist")) ||
    (name === "discover" && router.route.name === "auto") ||
    (name === "profile" && (router.route.name === "favorites" || router.route.name === "favoriteAlbums")) ||
    (name === "settings" && router.route.name === "settingsPage");
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
  <div class="shell" class:queue-open={player.queueOpen} class:own-top={router.route.name === "library"}>
    <nav class="side" aria-label="Navigation">
      <a class="logo" href={href("/")} aria-label="audium Start">
        <svg viewBox="0 0 64 64" width="26" height="26" aria-hidden="true"><g fill="currentColor"><rect x="14" y="26" width="6" height="12" rx="3" /><rect x="24" y="18" width="6" height="28" rx="3" /><rect x="34" y="12" width="6" height="40" rx="3" /><rect x="44" y="22" width="6" height="20" rx="3" /></g></svg>
        <span>audium</span>
      </a>
      <!-- Search and profile live in the top bar on wide screens. -->
      {#each NAV.filter((n) => n.name !== "search" && n.name !== "profile") as n (n.name)}
        <a href={href(n.path)} class:active={active(n.name)} aria-current={active(n.name) ? "page" : undefined}>
          <Icon name={n.icon} /> <span>{n.label}</span>
        </a>
      {/each}

      <div class="side-head">
        <span>Playlists</span>
        <span class="side-btns">
          {#if SMART_PLAYLIST_BUTTON}
            <button class="icon-btn" title="Neue Smart-Playlist (füllt sich nach Regeln)" aria-label="Neue Smart-Playlist" onclick={() => (ui.smartEditor = true)}><Icon name="spark" size={17} /></button>
          {/if}
          <button class="icon-btn" title="Neue Playlist" aria-label="Neue Playlist" onclick={newPlaylist}><Icon name="plus" size={18} /></button>
        </span>
      </div>
      <div class="side-lists">
        <a href={href("/favorites")} class:active={active("favorites")} class="pl">
          <span class="pl-art fav" aria-hidden="true"><Icon name="heart" size={14} filled /></span><span class="pl-name">Lieblingssongs</span>
        </a>
        {#each mine.playlists as p (p.id)}
          <a href={href(`/playlists/${p.id}`)} class="pl" class:active={router.route.name === "playlist" && router.route.params.id === String(p.id)} title={p.role === "owner" ? p.name : `${p.name} – von ${p.owner.display_name}`}>
            <span class="pl-art"><PlaylistCover playlist={p} size={64} /></span>
            <span class="pl-name">{p.name}</span>
            {#if p.role !== "owner"}<span class="pl-shared" aria-label="geteilt"><Icon name="share" size={13} /></span>{/if}
          </a>
        {/each}
      </div>
    </nav>

    <header class="top" class:searching={router.route.name === "search"}>
      {#if backTo}
        <button class="icon-btn back" title="Zurück" aria-label="Zurück" onclick={() => goBack(backTo)}><Icon name="back" /></button>
      {:else}
        <a class="top-logo" href={href("/")} aria-label="audium Start">
          <svg viewBox="0 0 64 64" width="24" height="24" aria-hidden="true"><g fill="currentColor"><rect x="14" y="26" width="6" height="12" rx="3" /><rect x="24" y="18" width="6" height="28" rx="3" /><rect x="34" y="12" width="6" height="40" rx="3" /><rect x="44" y="22" width="6" height="20" rx="3" /></g></svg>
          <span>audium</span>
        </a>
      {/if}
      <label class="search">
        <Icon name="search" size={18} />
        <span class="sr-only">Suche</span>
        <input
          bind:this={searchInput}
          type="search"
          placeholder="Titel, Künstler, Alben"
          value={searchValue}
          oninput={(e) => onSearch(e.currentTarget.value)}
          onkeydown={onSearchKey}
          autocomplete="off"
          autocapitalize="off"
          autocorrect="off"
          spellcheck="false"
          enterkeyhint="search"
        />
      </label>
      <div class="top-end">
        {#if router.route.name === "profile"}<a class="icon-btn" href={href("/settings")} aria-label="Einstellungen" title="Einstellungen"><Icon name="settings" /></a>{/if}
        <a class="me" class:active={active("profile")} href={href("/profile")} aria-label="Profil" title={session.user.display_name}>{initial}</a>
      </div>
    </header>

    <main class="content">
      {#key router.route.name + (router.route.params.kind ?? "") + (router.route.params.id ?? "")}
        {#if router.route.name === "home"}<Home />
        {:else if router.route.name === "library"}<Library />
        {:else if router.route.name === "album"}<Album id={router.route.params.id} />
        {:else if router.route.name === "artist"}<Artist id={router.route.params.id} />
        {:else if router.route.name === "search"}<Search />
        {:else if router.route.name === "settings" || router.route.name === "settingsPage"}<Settings section={router.route.params.section} />
        {:else if router.route.name === "playlist"}<Playlist id={router.route.params.id} />
        {:else if router.route.name === "favorites"}<Favorites />
        {:else if router.route.name === "favoriteAlbums"}<FavoriteAlbums />
        {:else if router.route.name === "profile"}<Profile />
        {:else if router.route.name === "discover"}<Discover />
        {:else if router.route.name === "auto"}<AutoPlaylist id={router.route.params.id} />
        {:else if router.route.name === "similar"}<Similar id={router.route.params.id} />
        {:else if router.route.name === "radio"}<Radio kind={router.route.params.kind} id={router.route.params.id} />
        {:else if router.route.name === "albums" || router.route.name === "tracks"}<!-- redirecting -->
        {:else}<div class="page"><p class="empty">Diese Seite gibt es nicht. <a href={href("/")}>Zur Startseite</a></p></div>
        {/if}
      {/key}
    </main>

    {#if player.queueOpen}<div class="queue"><QueuePanel /></div>{/if}

    <div class="player"><PlayerBar /></div>
    {#if player.nowPlayingOpen}<NowPlaying />{/if}

    <Overlays />
    {#if devices.picker}<DevicePicker />{/if}
    {#if ui.smartEditor}
      <RuleEditor title="Neue Smart-Playlist" onsave={createSmart} onclose={() => (ui.smartEditor = false)} />
    {/if}

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
  .side-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin: 22px 4px 6px 12px;
    color: var(--text-muted);
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .side-lists {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    margin: 0 -4px 8px;
    padding: 0 4px;
  }
  .side a.pl {
    padding: 6px 8px;
    gap: 10px;
    font-weight: 450;
  }
  .pl-art {
    width: 32px;
    flex: none;
  }
  .pl-art.fav {
    height: 32px;
    border-radius: 6px;
    display: grid;
    place-items: center;
    color: var(--accent-contrast);
    background: var(--accent);
  }
  .pl-name {
    flex: 1;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .pl-shared {
    color: var(--text-faint);
    display: grid;
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
  .back {
    flex: none;
    margin-left: -8px;
  }
  .top-end {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-left: auto;
  }
  .me {
    width: 34px;
    height: 34px;
    flex: none;
    border-radius: 50%;
    display: grid;
    place-items: center;
    font-weight: 650;
    color: var(--accent-contrast);
    text-decoration: none;
    background: linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 40%, #6b3fa0));
  }
  .me:hover,
  .me.active {
    outline: 2px solid var(--text);
    outline-offset: 2px;
  }
  .top-logo {
    display: none;
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
    /* The library brings its own top bar that scrolls away with the list. */
    .shell.own-top {
      grid-template-rows: minmax(0, 1fr) var(--player-h) var(--tabs-h);
      grid-template-areas: "main" "player" "tabs";
    }
    .own-top .top {
      display: none;
    }
    .side {
      display: none;
    }
    .top {
      padding: 0 16px;
    }
    /* Phones reach the profile through the tab bar. */
    .me {
      display: none;
    }
    /* Phones: no search field except on the search page (the tab bar leads there). */
    .top:not(.searching) .search {
      display: none;
    }
    .top:not(.searching) .top-logo {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--text);
      text-decoration: none;
      font-weight: 650;
      font-size: 1.05rem;
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
