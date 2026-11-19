<script lang="ts">
  import { ApiError, del, get, patch, post, type AnalysisStatus } from "../../lib/api";
  import Icon from "../../lib/components/Icon.svelte";
  import Modal from "../../lib/components/Modal.svelte";
  import { plural } from "../../lib/format";
  import { href } from "../../lib/router.svelte";
  import { promptText, toast } from "../../lib/ui.svelte";
  import { fmtDate, type Job } from "./common";
  import { locale, t, tn } from "../../lib/i18n.svelte";

  interface Root {
    id: number;
    path: string;
    enabled: boolean;
    status: "new" | "online" | "offline";
    status_message: string | null;
    track_count: number;
    last_scan_at: number | null;
    exclude_count: number;
  }
  interface Exclude {
    id: number;
    rel_path: string;
  }
  interface Browse {
    path: string;
    parent: string | null;
    root_id: number | null;
    folders: { name: string; path: string; root_id: number | null }[];
  }
  interface Stats {
    tracks: number;
    albums: number;
    artists: number;
    missing_tracks: number;
  }

  // null until the first answer: the page shows placeholders of the same height instead of jumping.
  let roots = $state<Root[] | null>(null);
  let excludes = $state<Record<number, Exclude[]>>({});
  let stats = $state<Stats | null>(null);
  let job = $state<Job | null>(null);
  let jobLoaded = $state(false);
  // For the further options: pending analysis, and whether similar artists are on at all.
  let analysis = $state<AnalysisStatus | null>(null);
  let similarOn = $state(false);
  let browsing = $state<Browse | null>(null);
  let reload = $state(0);

  const running = $derived(!!job && (job.status === "running" || job.status === "queued"));
  const percent = $derived(job && job.total ? Math.min(100, Math.round((job.progress / job.total) * 100)) : null);

  async function guard<T>(fn: () => Promise<T>, done?: string): Promise<T | undefined> {
    try {
      const r = await fn();
      if (done) toast(done);
      reload++;
      return r;
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("Fehlgeschlagen"));
    }
  }

  $effect(() => {
    void reload;
    get<Root[]>("/admin/roots").then(async (r) => {
      const withEx = r.filter((root) => root.exclude_count);
      const lists = await Promise.all(withEx.map((root) => get<Exclude[]>(`/admin/roots/${root.id}/excludes`)));
      excludes = Object.fromEntries(withEx.map((root, i) => [root.id, lists[i]]));
      roots = r; // together with the excludes, so the rows don't grow afterwards
    });
  });

  // Scan progress and counts: poll quickly while a scan runs, slowly otherwise.
  $effect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let wasRunning = false;
    const tick = async () => {
      try {
        const [j, s] = await Promise.all([get<{ items: Job[] }>("/admin/jobs", { queue: "scan", limit: 1 }), get<Stats>("/admin/stats")]);
        job = j.items[0] ?? null;
        jobLoaded = true;
        stats = s;
        if (wasRunning && !running) reload++; // track counts per folder changed
        wasRunning = running;
      } finally {
        timer = setTimeout(tick, running ? 1500 : 10000);
      }
    };
    tick();
    return () => clearTimeout(timer);
  });

  $effect(() => {
    void reload;
    get<AnalysisStatus>("/admin/analysis").then((a) => (analysis = a), () => {});
    get<{ sources: Record<string, { on: boolean }> }>("/admin/radio/sources").then((r) => (similarOn = r.sources.artists?.on ?? false), () => {});
  });

  async function scan(body: object, done: string) {
    const j = await guard(() => post<Job>("/admin/scan", body), done);
    if (j) job = j;
  }

  async function browse(path?: string) {
    browsing = await get<Browse>("/admin/browse", { path });
  }

  async function addRoot(path: string) {
    await guard(() => post("/admin/roots", { path }), t("Ordner hinzugefügt – der Scan startet"));
    browsing = null;
  }

  async function addExclude(root: Root) {
    const rel = await promptText(t("Unterordner von {path} ausschließen (relativer Pfad)", { path: root.path }), "", t("Ausschließen"));
    if (rel) guard(() => post(`/admin/roots/${root.id}/excludes`, { rel_path: rel }), t("Ausgeschlossen – wird beim Scan entfernt"));
  }
</script>

<div class="tiles">
  {#each [[stats?.tracks, t("Titel")], [stats?.albums, t("Alben")], [stats?.artists, t("Künstler")]] as [n, label] (label)}
    <div class="tile">
      {#if n == null}<strong class="bar" aria-hidden="true"></strong>{:else}<strong>{n.toLocaleString(locale())}</strong>{/if}
      <span>{label}</span>
    </div>
  {/each}
</div>
{#if stats?.missing_tracks}<p class="set-note">{tn(stats.missing_tracks, "{n} Titel fehlt gerade (Ordner nicht erreichbar?). Er wird nach einigen Tagen entfernt.", "{n} Titel fehlen gerade (Ordner nicht erreichbar?). Sie werden nach einigen Tagen entfernt.")}</p>{/if}

<section class="set-group">
  <h2>{t("Scan")}</h2>
  <div class="set-card">
    <div class="set-row scan">
      {#if running && job}
        <div class="set-label">
          <strong>{job.status === "queued" ? t("Scan wartet …") : t("Scan läuft")}</strong>
          <small>{t("{n} Dateien geprüft", { n: job.progress })}{#if job.message}<br /><span class="set-mono">{job.message}</span>{/if}</small>
          <div class="set-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={percent ?? undefined}>
            <div style:width="{percent ?? 100}%" class:indeterminate={percent === null}></div>
          </div>
        </div>
        <button class="btn" onclick={() => job && guard(() => post(`/admin/jobs/${job!.id}/cancel`), t("Wird abgebrochen"))}>{t("Abbrechen")}</button>
      {:else}
        <div class="set-label">
          <strong>{t("Bibliothek scannen")}</strong>
          <small>
            {#if !jobLoaded}<span class="bar line" aria-hidden="true"></span>
            {:else if job?.status === "failed"}<span class="set-warn">{t("Letzter Scan fehlgeschlagen: {error}", { error: job.error ?? "" })}</span>
            {:else if job?.result}
              {t("Zuletzt {date}: {added} neu, {updated} geändert, {missing} fehlend, {errors} nicht lesbar", {
                date: fmtDate(job.finished_at),
                added: job.result.added ?? 0,
                updated: job.result.updated ?? 0,
                missing: job.result.missing ?? 0,
                errors: job.result.errors ?? 0,
              })}
            {:else}{t("Noch kein Scan gelaufen.")}{/if}
          </small>
          <small>{t("Liest neue und geänderte Dateien aller aktiven Ordner ein und erkennt gelöschte. Danach werden neue Titel analysiert und die Auto-Playlists aktualisiert.")}</small>
        </div>
        <div class="btns">
          <button class="btn primary" disabled={!jobLoaded} onclick={() => scan({}, t("Scan gestartet"))}>{t("Jetzt scannen")}</button>
        </div>
      {/if}
    </div>
    <details class="set-row more">
      <summary><Icon name="chevron" size={14} /> {t("Weitere Optionen")}</summary>
      <div class="set-row">
        <div class="set-label">
          <strong>{t("Alles neu einlesen")}</strong>
          <small>{t("Liest Tags und Cover aller Dateien neu, auch unveränderter. Hilft, wenn audium etwas falsch übernommen hat. Dauert deutlich länger.")}</small>
        </div>
        <button class="btn small" disabled={!jobLoaded || running} onclick={() => scan({ force: true }, t("Vollständiger Scan gestartet"))}>{t("Alles neu einlesen")}</button>
      </div>
      {#if analysis && analysis.backend !== "none"}
        <div class="set-row">
          <div class="set-label">
            <strong>{t("Audioanalyse")}</strong>
            <small>
              {analysis.pending ? t("{n} Titel ausstehend.", { n: analysis.pending.toLocaleString(locale()) }) : t("Alle Titel sind analysiert.")}
              {t("Läuft sonst von selbst im Hintergrund.")}
              <a href={href("/settings/analysis")}>{t("Einstellungen")}</a>
            </small>
          </div>
          <button class="btn small" disabled={!analysis.pending} onclick={() => guard(() => post("/admin/analysis/start"), t("Analyse gestartet"))}>{t("Jetzt analysieren")}</button>
        </div>
      {/if}
      {#if similarOn}
        <div class="set-row">
          <div class="set-label">
            <strong>{t("Ähnliche Künstler")}</strong>
            <small>{t("Fragt ListenBrainz für alle Künstler neu ab, etwa einen pro Sekunde. Sonst geschieht das alle 90 Tage von selbst. Bisherige Ergebnisse bleiben bis dahin erhalten.")}</small>
          </div>
          <button class="btn small" onclick={() => guard(() => post("/admin/similar-artists/refresh"), t("Ähnliche Künstler werden neu abgefragt"))}>{t("Neu abfragen")}</button>
        </div>
      {/if}
      <div class="set-row">
        <small class="set-note hint">{t("Einen einzelnen Ordner scannst du unten in der Ordnerliste. Musikdateien werden nie verändert.")}</small>
      </div>
    </details>
  </div>
</section>

<section class="set-group">
  <h2>{t("Ordner")}</h2>
  <div class="set-card">
    {#if !roots}
      <div class="set-row root" aria-hidden="true">
        <span class="set-dot"></span>
        <div class="set-label"><strong class="bar path"></strong><small class="bar line"></small></div>
      </div>
    {/if}
    {#each roots ?? [] as r (r.id)}
      <div class="set-row root">
        <span class="set-dot {!r.enabled ? '' : r.status === 'online' ? 'ok' : r.status === 'offline' ? 'bad' : ''}" title={r.status}></span>
        <div class="set-label">
          <strong class="set-mono">{r.path}</strong>
          <small>
            {r.enabled ? plural(r.track_count, "Titel", "Titel") : t("deaktiviert – Titel ausgeblendet")} · {t("letzter Scan {date}", { date: fmtDate(r.last_scan_at) })}
            {#if r.status_message}<br /><span class="set-warn">{r.status_message}</span>{/if}
          </small>
          {#if excludes[r.id]?.length}
            <div class="excl">
              {#each excludes[r.id] as ex (ex.id)}
                <span class="set-chip">{t("ohne")} <code>{ex.rel_path}</code>
                  <button class="icon-btn tiny" aria-label={t("Ausschluss entfernen")} onclick={() => guard(() => del(`/admin/roots/${r.id}/excludes/${ex.id}`))}><Icon name="close" size={12} /></button>
                </span>
              {/each}
            </div>
          {/if}
        </div>
        <div class="btns">
          <button class="btn small ghost" onclick={() => addExclude(r)}>{t("Unterordner ausschließen")}</button>
          <button class="btn small ghost" title={t("Nur diesen Ordner scannen")} onclick={() => scan({ root_ids: [r.id] }, t("Scan gestartet"))}>{t("Scannen")}</button>
          <label class="switch"><input type="checkbox" class="toggle" checked={r.enabled} onchange={(e) => guard(() => patch(`/admin/roots/${r.id}`, { enabled: e.currentTarget.checked }))} /> {t("aktiv")}</label>
        </div>
      </div>
    {:else}
      {#if roots}<div class="set-row"><span class="set-label"><small>{t("Noch keine Bibliotheksordner.")}</small></span></div>{/if}
    {/each}
    <div class="set-row">
      <button class="btn" onclick={() => browse()}><Icon name="plus" size={16} /> {t("Ordner hinzufügen")}</button>
    </div>
  </div>
  <p class="set-note">
    {t("audium sieht nur Ordner, die in den Container unter")} <code>{t("/music")}</code> {t("eingebunden sind (in")} <code>{t("docker-compose.yml")}</code> {t("unter")}
    <code>{t("volumes")}</code>{t("). Innerhalb davon wählst du hier, was zur Bibliothek gehört. Musikdateien werden nie verändert. Hilfe dabei gibt die")} <a href={href("/setup")}>{t("Einrichtung")}</a>{t(", die du jederzeit erneut öffnen kannst.")}
  </p>
</section>

{#if browsing}
  <Modal title={t("Ordner wählen")} width={560} onclose={() => (browsing = null)}>
    <div class="crumb set-mono">{browsing.path}</div>
    <ul class="folders">
      {#if browsing.parent}
        <li><button class="folder" onclick={() => browse(browsing!.parent!)}><Icon name="back" size={16} /> ..</button></li>
      {/if}
      {#each browsing.folders as f (f.path)}
        <li>
          <button class="folder" onclick={() => browse(f.path)}><Icon name="folder" size={16} /> {f.name}</button>
          {#if f.root_id}<span class="set-chip">{t("in der Bibliothek")}</span>{/if}
        </li>
      {:else}
        <li class="set-note">{t("Keine Unterordner.")}</li>
      {/each}
    </ul>
    <div class="modal-buttons">
      <button class="btn ghost" onclick={() => (browsing = null)}>{t("Abbrechen")}</button>
      <button class="btn primary" disabled={!!browsing.root_id} onclick={() => addRoot(browsing!.path)}>
        {browsing.root_id ? t("Schon in der Bibliothek") : t("Diesen Ordner hinzufügen")}
      </button>
    </div>
  </Modal>
{/if}

<style>
  .tiles {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
    margin: 0 0 24px;
  }
  .tile {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 14px 16px;
    border-radius: 14px;
    border: 1px solid var(--line);
    background: var(--surface-0);
    min-width: 0;
  }
  .tile strong {
    font-size: 1.35rem;
    font-weight: 650;
    letter-spacing: -0.01em;
    font-variant-numeric: tabular-nums;
  }
  .tile span {
    color: var(--text-muted);
    font-size: 0.82rem;
  }
  /* Placeholders while loading, as tall as the text they stand for. */
  .bar {
    display: block;
    border-radius: 4px;
    background: var(--surface-2);
  }
  .tile strong.bar {
    width: 3.5em;
    height: 1.2em;
    margin: 0.15em 0;
  }
  .bar.line {
    width: min(22em, 90%);
    height: 0.8em;
    margin: 0.3em 0;
  }
  .bar.path {
    width: min(14em, 70%);
    height: 0.95em;
    margin: 0.2em 0;
  }
  .more {
    display: block;
    min-height: 0;
    padding: 0;
  }
  .more summary {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 16px;
    cursor: pointer;
    list-style: none;
    font-size: 0.9rem;
    color: var(--text-muted);
  }
  .more summary::-webkit-details-marker {
    display: none;
  }
  .more summary :global(svg) {
    transition: transform 0.15s;
  }
  .more[open] summary :global(svg) {
    transform: rotate(90deg);
  }
  .more > .set-row {
    border-top: 1px solid var(--line);
  }
  .hint {
    margin: 0;
  }
  .scan .set-progress {
    margin-top: 10px;
  }
  .btns {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    align-items: center;
  }
  .root {
    align-items: flex-start;
  }
  .root .set-dot {
    margin-top: 6px;
  }
  .excl {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 8px;
  }
  .tiny {
    width: 20px;
    height: 20px;
  }
  code {
    font-family: ui-monospace, monospace;
    font-size: 0.8rem;
  }
  .switch {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.85rem;
    color: var(--text-muted);
    padding: 0 4px;
  }
  .crumb {
    padding: 8px 10px;
    background: var(--surface-1);
    border-radius: var(--radius-sm);
  }
  .folders {
    list-style: none;
    padding: 0;
    margin: 10px 0;
    max-height: 340px;
    overflow-y: auto;
  }
  .folders li {
    display: flex;
    align-items: center;
  }
  .folder {
    flex: 1;
    text-align: left;
    border: 0;
    background: none;
    color: var(--text);
    padding: 8px 10px;
    border-radius: var(--radius-sm);
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .folder:hover {
    background: var(--surface-1);
  }
  .modal-buttons {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  @media (max-width: 560px) {
    .tile {
      padding: 12px;
    }
    .tile strong {
      font-size: 1.1rem;
    }
  }
</style>
