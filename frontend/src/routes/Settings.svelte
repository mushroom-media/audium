<script lang="ts">
  import { get, post, type AnalysisStatus, type StreamQuality, type Theme } from "../lib/api";
  import { plural } from "../lib/format";
  import { player } from "../lib/player.svelte";
  import { href, navigate } from "../lib/router.svelte";
  import { logout, saveSettings, session } from "../lib/session.svelte";

  interface Root {
    id: number;
    path: string;
    enabled: boolean;
    status: "new" | "online" | "offline";
    status_message: string | null;
    track_count: number;
    last_scan_at: number | null;
  }
  interface Job {
    id: number;
    status: string;
    progress: number;
    total: number;
    message: string | null;
    error: string | null;
    result: Record<string, number> | null;
    finished_at: number | null;
  }
  interface Stats {
    tracks: number;
    albums: number;
    artists: number;
    missing_tracks: number;
    tag_status: Record<string, number>;
  }

  const THEMES: Record<Theme, string> = { system: "Wie das System", dark: "Dunkel", light: "Hell" };
  const QUALITIES: Record<StreamQuality, string> = {
    auto: "Original (wenn möglich)",
    high: "Hoch (≈ 192–256 kbit/s)",
    medium: "Mittel (≈ 128–160 kbit/s)",
    low: "Niedrig (≈ 64–96 kbit/s, mobile Daten)",
  };

  const isAdmin = $derived(session.user?.role === "admin");
  let roots = $state<Root[]>([]);
  let job = $state<Job | null>(null);
  let stats = $state<Stats | null>(null);
  let analysis = $state<AnalysisStatus | null>(null);
  let analysisJob = $state<Job | null>(null);
  let failures = $state<{ track_id: number; path: string; error: string | null }[]>([]);
  const analysisPercent = $derived(
    analysisJob && analysisJob.total ? Math.min(100, Math.round((analysisJob.progress / analysisJob.total) * 100)) : null,
  );

  async function startAnalysis() {
    await post("/admin/analysis/start");
    refresh();
  }

  async function refresh() {
    if (!isAdmin) return;
    const [r, j, s, a, aj, f] = await Promise.all([
      get<Root[]>("/admin/roots"),
      get<{ items: Job[] }>("/admin/jobs", { queue: "scan", limit: 1 }),
      get<Stats>("/admin/stats"),
      get<AnalysisStatus>("/admin/analysis"),
      get<{ items: (Job & { type: string })[] }>("/admin/jobs", { queue: "analysis", limit: 5 }),
      get<{ track_id: number; path: string; error: string | null }[]>("/admin/analysis/failures", { limit: 20 }),
    ]);
    roots = r;
    job = j.items[0] ?? null;
    stats = s;
    analysis = a;
    analysisJob = aj.items.find((x) => x.type === "analyze") ?? null;
    failures = f;
  }

  $effect(() => {
    if (!isAdmin) return;
    refresh();
    // Poll while a scan runs; slower otherwise.
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        await refresh();
      } finally {
        const busy = (x: Job | null) => !!x && ["queued", "running"].includes(x.status);
        timer = setTimeout(tick, busy(job) || busy(analysisJob) ? 1500 : 10000);
      }
    };
    timer = setTimeout(tick, 1500);
    return () => clearTimeout(timer);
  });

  async function scan(force: boolean) {
    job = await post<Job>("/admin/scan", { force });
  }
  async function cancel() {
    if (job) job = await post<Job>(`/admin/jobs/${job.id}/cancel`);
  }
  async function doLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  const running = $derived(job && (job.status === "running" || job.status === "queued"));
  const percent = $derived(job && job.total ? Math.min(100, Math.round((job.progress / job.total) * 100)) : null);
</script>

<div class="page narrow">
  <div class="toolbar"><h1>Einstellungen</h1></div>

  <section>
    <h2>Darstellung & Wiedergabe</h2>
    <label class="field">
      <span>Farbschema</span>
      <select value={session.settings.theme} onchange={(e) => saveSettings({ theme: e.currentTarget.value as Theme })}>
        {#each Object.entries(THEMES) as [k, v] (k)}<option value={k}>{v}</option>{/each}
      </select>
    </label>
    <label class="field">
      <span>Streaming-Qualität</span>
      <select
        value={session.settings.stream_quality}
        onchange={(e) => saveSettings({ stream_quality: e.currentTarget.value as StreamQuality }).then(() => (player.quality = session.settings.stream_quality))}
      >
        {#each Object.entries(QUALITIES) as [k, v] (k)}<option value={k}>{v}</option>{/each}
      </select>
    </label>
    <p class="note">Formate, die dein Browser nicht abspielen kann (z. B. WMA, APE), werden immer umgewandelt.</p>
  </section>

  {#if isAdmin}
    <section>
      <h2>Bibliothek</h2>
      <p><a href={href("/admin")}>Ordner, Nutzer und Jobs verwalten →</a></p>
      {#if stats}
        <p class="stats">
          {plural(stats.tracks, "Titel", "Titel")} · {plural(stats.albums, "Album", "Alben")} · {plural(stats.artists, "Künstler", "Künstler")}
          {#if stats.missing_tracks}· {stats.missing_tracks} vorübergehend fehlend{/if}
        </p>
      {/if}
      <ul class="roots">
        {#each roots as r (r.id)}
          <li>
            <span class="dot {r.status}" title={r.status}></span>
            <span class="path">{r.path}</span>
            <span class="muted">{r.enabled ? plural(r.track_count, "Titel", "Titel") : "deaktiviert"}</span>
            {#if r.status_message}<span class="warn">{r.status_message}</span>{/if}
          </li>
        {/each}
      </ul>
      <p class="note">
        audium sieht nur Ordner, die in den Container unter <code>/music</code> eingebunden sind. Weitere Ordner fügst du in
        <code>docker-compose.yml</code> hinzu. Ordner, Nutzer und Jobs verwaltest du unter <a href={href("/admin")}>Verwaltung</a>.
      </p>
      <div class="scan">
        {#if running && job}
          <div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={percent ?? undefined}>
            <div style:width="{percent ?? 100}%" class:indeterminate={percent === null}></div>
          </div>
          <p class="muted small">
            {job.status === "queued" ? "Wartet …" : `${job.progress.toLocaleString("de-DE")} Dateien geprüft`}
            {#if job.message}<br /><span class="msg">{job.message}</span>{/if}
          </p>
          <button class="btn" onclick={cancel}>Scan abbrechen</button>
        {:else}
          {#if job?.result}
            <p class="muted small">
              Letzter Scan: {job.result.added ?? 0} neu, {job.result.updated ?? 0} geändert, {job.result.missing ?? 0} fehlend,
              {job.result.errors ?? 0} nicht lesbar
            </p>
          {:else if job?.status === "failed"}
            <p class="warn small">Letzter Scan fehlgeschlagen: {job.error}</p>
          {/if}
          <div class="row">
            <button class="btn primary" onclick={() => scan(false)}>Jetzt scannen</button>
            <button class="btn ghost" onclick={() => scan(true)} title="Liest auch die Tags unveränderter Dateien neu">Alles neu einlesen</button>
          </div>
        {/if}
      </div>
    </section>
  {/if}

  {#if isAdmin && analysis}
    <section>
      <h2>Audioanalyse</h2>
      {#if analysis.backend === "none"}
        <p class="note">
          Auf dieser Plattform ist keine Audioanalyse verfügbar (Essentia gibt es nur für x86_64). Auto-Playlists nach
          Genre und Jahrzehnt funktionieren trotzdem.
        </p>
      {:else}
        <p class="stats">
          {analysis.analyzed.toLocaleString("de-DE")} von {analysis.tracks.toLocaleString("de-DE")} Titeln analysiert
          {#if analysis.pending}· {analysis.pending.toLocaleString("de-DE")} ausstehend{/if}
          {#if analysis.failed}· {analysis.failed} nicht analysierbar{/if}
          <span class="muted small">({analysis.backend})</span>
        </p>
        {#if analysisJob && (analysisJob.status === "running" || analysisJob.status === "queued")}
          <div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={analysisPercent ?? undefined}>
            <div style:width="{analysisPercent ?? 100}%" class:indeterminate={analysisPercent === null}></div>
          </div>
          <p class="muted small">Läuft mit niedriger Priorität im Hintergrund. {analysisJob.message ?? ""}</p>
        {:else if analysis.pending}
          <button class="btn" onclick={startAnalysis}>Jetzt analysieren</button>
        {/if}
        {#if failures.length}
          <details>
            <summary class="muted small">Nicht analysierbare Dateien ({analysis.failed})</summary>
            <ul class="failures">{#each failures as f (f.track_id)}<li><code>{f.path}</code> – {f.error}</li>{/each}</ul>
          </details>
        {/if}
      {/if}
      <p><a href={href("/discover?tab=suggested")}>Auto-Playlists verwalten →</a></p>
    </section>
  {/if}

  <section>
    <h2>Konto</h2>
    <p class="muted">Angemeldet als <strong>{session.user?.username}</strong>{isAdmin ? " (Admin)" : ""}</p>
    <button class="btn" onclick={doLogout}>Abmelden</button>
  </section>

  <section class="shortcuts">
    <h2>Tastenkürzel</h2>
    <dl>
      <dt>Leertaste</dt><dd>Abspielen / Pause</dd>
      <dt>← / →</dt><dd>10 Sekunden zurück / vor</dd>
      <dt>Shift + ← / →</dt><dd>Vorheriger / nächster Titel</dd>
      <dt>↑ / ↓</dt><dd>Lautstärke</dd>
      <dt>M · S · R · Q</dt><dd>Stumm · Zufall · Wiederholen · Warteschlange</dd>
      <dt>/</dt><dd>Suchen</dd>
    </dl>
  </section>
</div>

<style>
  section {
    padding: 8px 24px 20px;
    border-bottom: 1px solid var(--line);
  }
  section:last-child {
    border: 0;
  }
  h2 {
    font-size: 1rem;
    margin: 16px 0 12px;
  }
  .field {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 6px 0;
  }
  .note,
  .muted {
    color: var(--text-muted);
  }
  .note {
    font-size: 0.85rem;
    line-height: 1.5;
  }
  .small {
    font-size: 0.85rem;
  }
  code {
    font-size: 0.8rem;
    background: var(--surface-1);
    padding: 1px 5px;
    border-radius: 4px;
  }
  .roots {
    list-style: none;
    padding: 0;
    margin: 0 0 8px;
  }
  .roots li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
    padding: 6px 0;
  }
  .path {
    font-family: ui-monospace, monospace;
    font-size: 0.88rem;
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--text-faint);
  }
  .dot.online {
    background: var(--ok);
  }
  .dot.offline {
    background: var(--danger);
  }
  .warn {
    color: var(--danger);
  }
  .row {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
  }
  .progress {
    height: 6px;
    border-radius: 3px;
    background: var(--surface-2);
    overflow: hidden;
    margin: 8px 0;
  }
  .progress div {
    height: 100%;
    background: var(--accent);
    transition: width 0.4s;
  }
  .progress .indeterminate {
    width: 30% !important;
    animation: slide 1.2s ease-in-out infinite;
  }
  @keyframes slide {
    from {
      transform: translateX(-100%);
    }
    to {
      transform: translateX(340%);
    }
  }
  .msg {
    font-family: ui-monospace, monospace;
    font-size: 0.78rem;
    word-break: break-all;
  }
  dl {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 6px 18px;
    margin: 0;
    font-size: 0.9rem;
  }
  .failures {
    font-size: 0.82rem;
    color: var(--text-muted);
    max-height: 200px;
    overflow-y: auto;
  }
  dt {
    font-family: ui-monospace, monospace;
    color: var(--text-muted);
  }
  dd {
    margin: 0;
  }
</style>
