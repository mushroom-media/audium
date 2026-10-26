<script lang="ts">
  import { ApiError, get, patch, post, put, type AutoPlaylist, type Rule } from "../lib/api";
  import Cover from "../lib/components/Cover.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import RuleEditor from "../lib/components/RuleEditor.svelte";
  import { plural } from "../lib/format";
  import { ORIGINS } from "../lib/origin";
  import { href, navigate, router } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";
  import { toast } from "../lib/ui.svelte";

  const isAdmin = $derived(session.user?.role === "admin");
  const tab = $derived((router.route.query.get("tab") as "published" | "suggested" | "dismissed" | null) ?? "published");
  let lists = $state<AutoPlaylist[] | null>(null);
  let creating = $state(false);
  let reload = $state(0);
  let filter = $state("");

  // Every word must appear in the name (case and accents ignored), like the library search.
  const fold = (s: string) => s.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const shown = $derived.by(() => {
    const words = fold(filter).split(/\s+/).filter(Boolean);
    if (!lists || !words.length) return lists;
    return lists.filter((a) => {
      const name = fold(a.name);
      return words.every((w) => name.includes(w));
    });
  });

  $effect(() => {
    void reload;
    const status = isAdmin ? tab : undefined;
    lists = null;
    get<AutoPlaylist[]>("/autoplaylists", { status }).then((l) => (lists = l));
  });

  // What new suggestions are made from (admin): everything, or only the sound recognition.
  let source = $state<"all" | "sound" | null>(null);
  $effect(() => {
    if (isAdmin) get<{ source: "all" | "sound" }>("/admin/autoplaylists/source").then((s) => (source = s.source));
  });

  async function setSource(value: "all" | "sound") {
    await put("/admin/autoplaylists/source", { source: value });
    source = value;
    toast(value === "sound" ? "Nur Klangerkennung – wird neu erzeugt" : "Alle Quellen – wird neu erzeugt");
    setTimeout(() => reload++, 4000);
  }

  const GROUPS: { title: string; test: (a: AutoPlaylist) => boolean }[] = [
    { title: "Stimmung & Aktivität", test: (a) => a.generator === "rule" },
    { title: "Mixe aus deiner Bibliothek", test: (a) => a.generator === "cluster" },
    { title: "Klang-Mixe", test: (a) => a.generator === "sound" },
    { title: "Eigene Regeln", test: (a) => a.generator === "custom" },
    { title: "Genres", test: (a) => a.key.startsWith("genre:") },
    { title: "Stile (Klangerkennung)", test: (a) => a.origin === "styles" },
    { title: "Jahrzehnte", test: (a) => a.key.startsWith("decade:") },
    { title: "Genre & Jahrzehnt", test: (a) => a.key.startsWith("genre-decade:") },
  ];
  // Anything a newer generator adds still shows up somewhere.
  const grouped = (a: AutoPlaylist) => GROUPS.some((g) => g.test(a));

  async function setStatus(a: AutoPlaylist, status: "published" | "suggested" | "dismissed", e?: Event) {
    e?.preventDefault();
    e?.stopPropagation();
    await patch(`/admin/autoplaylists/${a.id}`, { status });
    toast(status === "published" ? `„${a.name}“ veröffentlicht` : status === "dismissed" ? "Ausgeblendet" : "Zurückgezogen");
    reload++;
  }

  async function regenerate() {
    await post("/admin/autoplaylists/regenerate");
    toast("Wird im Hintergrund neu erzeugt");
    setTimeout(() => reload++, 4000);
  }

  async function createRule(name: string, rule: Rule) {
    const a = await post<AutoPlaylist>("/admin/autoplaylists", { name, rule });
    creating = false;
    navigate(`/discover/${a.id}`);
  }

  async function publishAll() {
    if (!lists || !confirm(`Alle ${lists.length} Vorschläge veröffentlichen?`)) return;
    try {
      for (const a of lists) await patch(`/admin/autoplaylists/${a.id}`, { status: "published" });
      toast("Alle veröffentlicht");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Fehlgeschlagen");
    }
    reload++;
  }
</script>

<div class="page">
  <div class="toolbar">
    <div>
      <h1>Entdecken</h1>
      <p class="count">Automatisch zusammengestellt aus deiner Bibliothek – ohne Cloud.</p>
    </div>
    {#if isAdmin}
      <div class="admin-actions">
        {#if source}
          <label class="source" title="Woraus neue Vorschläge erzeugt werden">
            <span class="sr-only">Quelle</span>
            <select value={source} onchange={(e) => setSource(e.currentTarget.value as "all" | "sound")}>
              <option value="all">Alle Quellen</option>
              <option value="sound">Nur Klangerkennung</option>
            </select>
          </label>
        {/if}
        <button class="btn ghost" onclick={regenerate}><Icon name="spark" size={18} /> Neu erzeugen</button>
        <button class="btn" onclick={() => (creating = true)}><Icon name="plus" size={18} /> Regel-Playlist</button>
      </div>
    {/if}
  </div>

  {#if isAdmin}
    <div class="tabs" role="tablist">
      <a role="tab" aria-selected={tab === "published"} class:on={tab === "published"} href={href("/discover")}>Veröffentlicht</a>
      <a role="tab" aria-selected={tab === "suggested"} class:on={tab === "suggested"} href={href("/discover?tab=suggested")}>Vorschläge</a>
      <a role="tab" aria-selected={tab === "dismissed"} class:on={tab === "dismissed"} href={href("/discover?tab=dismissed")}>Ausgeblendet</a>
    </div>
    {#if tab === "suggested" && lists?.length}
      <p class="hint">
        Neue Vorschläge sieht nur der Admin. Erst nach dem Veröffentlichen erscheinen sie bei allen Nutzern.
        <button class="link" onclick={publishAll}>Alle veröffentlichen</button>
      </p>
    {/if}
  {/if}

  {#if lists?.length}
    <label class="filter">
      <Icon name="search" size={16} />
      <span class="sr-only">Playlists filtern</span>
      <input type="search" placeholder="Filtern, z. B. Rock oder 90er" bind:value={filter} autocomplete="off" autocapitalize="off" spellcheck="false" />
    </label>
  {/if}

  {#if lists === null || shown === null}
    <p class="empty">Lädt …</p>
  {:else if lists.length && !shown.length}
    <p class="empty">Keine Playlist passt zu „{filter.trim()}“.</p>
  {:else if lists.length === 0}
    <p class="empty">
      {#if isAdmin && tab === "published"}
        Noch nichts veröffentlicht. Schau bei den <a href={href("/discover?tab=suggested")}>Vorschlägen</a> vorbei.
      {:else if isAdmin}
        Hier ist nichts.
      {:else}
        Noch keine automatischen Playlists. Der Admin veröffentlicht sie, sobald die Bibliothek analysiert ist.
      {/if}
    </p>
  {:else}
    <ul class="legend" aria-label="Herkunft">
      {#each Object.values(ORIGINS) as o (o.label)}<li title={o.hint}><Icon name={o.icon} size={14} /> {o.label}</li>{/each}
    </ul>
    {#each [...GROUPS, { title: "Weitere", test: (a: AutoPlaylist) => !grouped(a) }] as g (g.title)}
      {@const items = shown.filter(g.test)}
      {#if items.length}
        <h2 class="section">{g.title}</h2>
        <div class="grid">
          {#each items as a (a.id)}
            <a class="card" href={href(`/discover/${a.id}`)}>
              <div class="art">
                <Cover hash={a.cover} size={256} />
                <span class="badge" title="{ORIGINS[a.origin].label}: {ORIGINS[a.origin].hint}"><Icon name={ORIGINS[a.origin].icon} size={14} /></span>
              </div>
              <div class="title">{a.name}</div>
              <div class="sub">{plural(a.track_count, "Titel", "Titel")} · {ORIGINS[a.origin].label}</div>
              {#if isAdmin && tab === "suggested"}
                <button class="btn primary small" onclick={(e) => setStatus(a, "published", e)}>Veröffentlichen</button>
              {:else if isAdmin && tab === "dismissed"}
                <button class="btn small" onclick={(e) => setStatus(a, "suggested", e)}>Wiederherstellen</button>
              {/if}
            </a>
          {/each}
        </div>
      {/if}
    {/each}
  {/if}
</div>

{#if creating}
  <RuleEditor title="Neue Regel-Playlist (für alle)" onsave={createRule} onclose={() => (creating = false)} />
{/if}

<style>
  .admin-actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
  }
  .tabs {
    display: flex;
    gap: 6px;
    padding: 0 24px 8px;
  }
  .tabs a {
    padding: 6px 14px;
    border-radius: 16px;
    color: var(--text-muted);
    text-decoration: none;
    font-size: 0.9rem;
  }
  .tabs a.on {
    background: var(--surface-1);
    color: var(--text);
  }
  .filter {
    display: flex;
    align-items: center;
    gap: 8px;
    width: min(360px, calc(100% - 48px));
    height: 36px;
    margin: 4px 24px 0;
    padding: 0 12px;
    border-radius: 18px;
    background: var(--surface-1);
    color: var(--text-muted);
  }
  .filter:focus-within {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }
  .filter input {
    flex: 1;
    min-width: 0;
    border: 0;
    padding: 0;
    background: none;
    color: var(--text);
    font: inherit;
    outline: none;
  }
  .hint {
    margin: 4px 24px 0;
    color: var(--text-muted);
    font-size: 0.88rem;
  }
  .link {
    border: 0;
    background: none;
    color: var(--accent);
    cursor: pointer;
    padding: 0;
    margin-left: 6px;
  }
  .section {
    font-size: 1.05rem;
    margin: 24px 24px 12px;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 20px;
    padding: 0 24px;
  }
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
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 16px;
    list-style: none;
    margin: 14px 24px 0;
    padding: 0;
    color: var(--text-muted);
    font-size: 0.8rem;
  }
  .legend li {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    cursor: help;
  }
  .legend :global(svg) {
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
  .small {
    height: 32px;
    padding: 0 12px;
    font-size: 0.85rem;
    margin-top: 6px;
    align-self: flex-start;
  }
  .page {
    padding-bottom: 32px;
  }
  @media (max-width: 560px) {
    .grid {
      grid-template-columns: repeat(2, 1fr);
      gap: 14px;
      padding: 0 16px;
    }
    .tabs {
      padding: 0 16px 8px;
    }
    .filter {
      width: calc(100% - 32px);
      margin: 4px 16px 0;
    }
    .legend {
      margin: 12px 16px 0;
    }
  }
</style>
