<script lang="ts">
  // The admin's side of Entdecken: which auto-playlists everybody sees. New suggestions wait here
  // until published; genre playlists are published at once and can be hidden here.
  import { ApiError, get, patch, post, put, type AutoPlaylist, type Rule } from "../../lib/api";
  import AutoCard from "../../lib/components/AutoCard.svelte";
  import Icon from "../../lib/components/Icon.svelte";
  import RuleEditor from "../../lib/components/RuleEditor.svelte";
  import { navigate } from "../../lib/router.svelte";
  import { toast } from "../../lib/ui.svelte";
  import { msg, t } from "../../lib/i18n.svelte";

  type Status = "published" | "suggested" | "dismissed";
  const TABS: Record<Status, string> = { suggested: msg("Vorschläge"), published: msg("Veröffentlicht"), dismissed: msg("Ausgeblendet") };
  let tab = $state<Status>("suggested");
  let lists = $state<AutoPlaylist[] | null>(null);
  let reload = $state(0);
  let creating = $state(false);
  let filter = $state("");

  $effect(() => {
    void reload;
    const status = tab;
    lists = null;
    get<AutoPlaylist[]>("/autoplaylists", { status }).then((l) => {
      if (status === tab) lists = l;
    });
  });

  const fold = (s: string) => s.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const shown = $derived.by(() => {
    const words = fold(filter).split(/\s+/).filter(Boolean);
    if (!lists || !words.length) return lists;
    return lists.filter((a) => words.every((w) => fold(a.name).includes(w)));
  });

  const GROUPS: { title: string; test: (a: AutoPlaylist) => boolean }[] = [
    { title: "Grundgenres", test: (a) => a.key.startsWith("family:") },
    { title: "Genres", test: (a) => a.key.startsWith("genre:") },
    { title: msg("Stimmung & Aktivität"), test: (a) => a.generator === "rule" },
    { title: msg("Mixe aus der Bibliothek"), test: (a) => a.generator === "cluster" },
    { title: "Klang-Mixe", test: (a) => a.key.startsWith("sound:") },
    { title: "Eigene Regeln", test: (a) => a.generator === "custom" },
    { title: "Stile (Klangerkennung)", test: (a) => a.key.startsWith("style:") },
    { title: "Jahrzehnte", test: (a) => a.key.startsWith("decade:") },
    { title: "Genre & Jahrzehnt", test: (a) => a.key.startsWith("genre-decade:") },
  ];
  const grouped = (a: AutoPlaylist) => GROUPS.some((g) => g.test(a));

  // What new suggestions are made from: everything, or only the sound recognition.
  let source = $state<"all" | "sound" | null>(null);
  $effect(() => {
    get<{ source: "all" | "sound" }>("/admin/autoplaylists/source").then((s) => (source = s.source));
  });

  async function setSource(value: "all" | "sound") {
    await put("/admin/autoplaylists/source", { source: value });
    source = value;
    toast(value === "sound" ? t("Nur Klangerkennung – wird neu erzeugt") : t("Alle Quellen – wird neu erzeugt"));
    setTimeout(() => reload++, 4000);
  }

  async function setStatus(a: AutoPlaylist, status: Status, e: Event) {
    e.preventDefault();
    e.stopPropagation();
    await patch(`/admin/autoplaylists/${a.id}`, { status });
    toast(status === "published" ? t("„{name}“ veröffentlicht", { name: a.name }) : status === "dismissed" ? t("Ausgeblendet") : t("Zurückgezogen"));
    reload++;
  }

  async function regenerate() {
    await post("/admin/autoplaylists/regenerate");
    toast(t("Wird im Hintergrund neu erzeugt"));
    setTimeout(() => reload++, 4000);
  }

  async function createRule(name: string, rule: Rule) {
    const a = await post<AutoPlaylist>("/admin/autoplaylists", { name, rule });
    creating = false;
    navigate(`/discover/${a.id}`);
  }

  async function publishAll() {
    if (!lists || !confirm(t("Alle {n} Vorschläge veröffentlichen?", { n: lists.length }))) return;
    try {
      for (const a of lists) await patch(`/admin/autoplaylists/${a.id}`, { status: "published" });
      toast(t("Alle veröffentlicht"));
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("Fehlgeschlagen"));
    }
    reload++;
  }
</script>

<section class="set-group">
  <div class="set-card">
    <div class="set-row">
      <div class="set-label">
        <strong>{t("Woraus Vorschläge entstehen")}</strong>
        <small>{t("„Nur Klangerkennung“ ignoriert Genre- und Jahres-Tags und nutzt nur, was die Audioanalyse am Klang erkannt hat.")}</small>
      </div>
      {#if source}
        <select aria-label={t("Quelle")} value={source} onchange={(e) => setSource(e.currentTarget.value as "all" | "sound")}>
          <option value="all">{t("Alle Quellen")}</option>
          <option value="sound">{t("Nur Klangerkennung")}</option>
        </select>
      {/if}
    </div>
  </div>
  <div class="actions">
    <button class="btn ghost" onclick={regenerate}><Icon name="spark" size={18} /> {t("Neu erzeugen")}</button>
    <button class="btn" onclick={() => (creating = true)}><Icon name="plus" size={18} /> {t("Regel-Playlist")}</button>
  </div>
  <p class="set-note">{t("Genres und Grundgenres sind sofort für alle sichtbar; alles andere erst nach dem Veröffentlichen. Ausgeblendetes kommt beim Neu-Erzeugen nicht wieder.")}</p>
</section>

<div class="segmented tabs" role="tablist" aria-label={t("Status")}>
  {#each Object.entries(TABS) as [k, label] (k)}
    <button role="tab" aria-selected={tab === k} class:on={tab === k} onclick={() => ((tab = k as Status), (filter = ""))}>{label}</button>
  {/each}
</div>

{#if lists?.length}
  <div class="bar">
    <label class="filter">
      <Icon name="search" size={16} />
      <span class="sr-only">{t("Filtern")}</span>
      <input type="search" placeholder={t("Filtern, z. B. Rock oder 90er")} bind:value={filter} autocomplete="off" spellcheck="false" />
    </label>
    {#if tab === "suggested"}<button class="btn small" onclick={publishAll}>{t("Alle veröffentlichen")}</button>{/if}
  </div>
{/if}

{#if lists === null || shown === null}
  <p class="set-note">{t("Lädt …")}</p>
{:else if !lists.length}
  <p class="set-note">{tab === "suggested" ? t("Keine offenen Vorschläge.") : tab === "dismissed" ? t("Nichts ausgeblendet.") : t("Noch nichts veröffentlicht.")}</p>
{:else if !shown.length}
  <p class="set-note">{t("Nichts passt zu „{filter}“.", { filter: filter.trim() })}</p>
{:else}
  {#each [...GROUPS, { title: msg("Weitere"), test: (a: AutoPlaylist) => !grouped(a) }] as g (g.title)}
    {@const items = shown.filter(g.test)}
    {#if items.length}
      <h3>{t(g.title)}</h3>
      <div class="grid">
        {#each items as a (a.id)}
          <AutoCard playlist={a}>
            {#snippet actions()}
              <div class="card-actions">
                {#if tab === "suggested"}
                  <button class="btn primary small" onclick={(e) => setStatus(a, "published", e)}>{t("Veröffentlichen")}</button>
                  <button class="icon-btn" title={t("Ausblenden")} aria-label={t("Ausblenden")} onclick={(e) => setStatus(a, "dismissed", e)}><Icon name="close" size={16} /></button>
                {:else if tab === "published"}
                  <button class="btn small" onclick={(e) => setStatus(a, "dismissed", e)}>{t("Ausblenden")}</button>
                {:else}
                  <button class="btn small" onclick={(e) => setStatus(a, "suggested", e)}>{t("Wiederherstellen")}</button>
                {/if}
              </div>
            {/snippet}
          </AutoCard>
        {/each}
      </div>
    {/if}
  {/each}
{/if}

{#if creating}
  <RuleEditor title={t("Neue Regel-Playlist (für alle)")} onsave={createRule} onclose={() => (creating = false)} />
{/if}

<style>
  .actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: 12px;
  }
  .tabs {
    margin: 8px 0 12px;
  }
  .bar {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    margin-bottom: 4px;
  }
  .filter {
    display: flex;
    align-items: center;
    gap: 8px;
    width: min(320px, 100%);
    height: 36px;
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
  h3 {
    font-size: 0.95rem;
    margin: 20px 0 10px;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 16px;
  }
  .card-actions {
    display: flex;
    align-items: center;
    gap: 4px;
    margin-top: 6px;
  }
  .small {
    height: 30px;
    padding: 0 10px;
    font-size: 0.82rem;
  }
  @media (max-width: 560px) {
    .grid {
      grid-template-columns: repeat(2, 1fr);
    }
  }
</style>
