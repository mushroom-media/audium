<script lang="ts">
  import { ApiError, get, patch, post, type AutoPlaylist, type Rule } from "../lib/api";
  import Cover from "../lib/components/Cover.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import RuleEditor from "../lib/components/RuleEditor.svelte";
  import { plural } from "../lib/format";
  import { href, navigate, router } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";
  import { toast } from "../lib/ui.svelte";

  const isAdmin = $derived(session.user?.role === "admin");
  const tab = $derived((router.route.query.get("tab") as "published" | "suggested" | "dismissed" | null) ?? "published");
  let lists = $state<AutoPlaylist[] | null>(null);
  let creating = $state(false);
  let reload = $state(0);

  $effect(() => {
    void reload;
    const status = isAdmin ? tab : undefined;
    lists = null;
    get<AutoPlaylist[]>("/autoplaylists", { status }).then((l) => (lists = l));
  });

  const GROUPS: { title: string; test: (a: AutoPlaylist) => boolean }[] = [
    { title: "Stimmung & Aktivität", test: (a) => a.generator === "rule" },
    { title: "Mixe aus deiner Bibliothek", test: (a) => a.generator === "cluster" },
    { title: "Eigene Regeln", test: (a) => a.generator === "custom" },
    { title: "Genres", test: (a) => a.key.startsWith("genre:") },
    { title: "Jahrzehnte", test: (a) => a.key.startsWith("decade:") },
    { title: "Genre & Jahrzehnt", test: (a) => a.key.startsWith("genre-decade:") },
  ];

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

  {#if lists === null}
    <p class="empty">Lädt …</p>
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
    {#each GROUPS as g (g.title)}
      {@const items = lists.filter(g.test)}
      {#if items.length}
        <h2 class="section">{g.title}</h2>
        <div class="grid">
          {#each items as a (a.id)}
            <a class="card" href={href(`/discover/${a.id}`)}>
              <div class="art">
                <Cover hash={a.cover} size={256} />
                {#if a.generator === "rule" || a.generator === "cluster"}<span class="badge"><Icon name="spark" size={14} /></span>{/if}
              </div>
              <div class="title">{a.name}</div>
              <div class="sub">{plural(a.track_count, "Titel", "Titel")}</div>
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
  .title {
    font-weight: 550;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sub {
    color: var(--text-muted);
    font-size: 0.85rem;
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
  }
</style>
