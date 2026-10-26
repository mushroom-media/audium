<script lang="ts">
  import { ApiError, get, post, type AnalysisStatus } from "../../lib/api";
  import Icon from "../../lib/components/Icon.svelte";
  import { href } from "../../lib/router.svelte";
  import { fmtDate, isBusy, type Job } from "./common";

  let analysis = $state<AnalysisStatus | null>(null);
  let job = $state<Job | null>(null);
  let failures = $state<{ track_id: number; path: string; error: string | null }[]>([]);

  const pct = (n: number, of: number) => (of ? Math.min(100, Math.round((n / of) * 100)) : 0);
  // A job still queued after this long: the analysis worker is not picking it up.
  const STUCK_MS = 30_000;

  let starting = $state(false);
  let startError = $state<string | null>(null);
  let now = $state(Date.now());

  async function refresh() {
    const [a, jobs, f] = await Promise.all([
      get<AnalysisStatus>("/admin/analysis"),
      // Auto-playlist jobs share the queue; look far enough back to find the last analysis.
      get<{ items: Job[] }>("/admin/jobs", { queue: "analysis", limit: 30 }),
      get<{ track_id: number; path: string; error: string | null }[]>("/admin/analysis/failures", { limit: 20 }),
    ]);
    analysis = a;
    job = jobs.items.find((x) => x.type === "analyze") ?? null;
    failures = f;
    now = Date.now();
  }

  let timer: ReturnType<typeof setTimeout> | undefined;
  async function tick() {
    clearTimeout(timer);
    try {
      await refresh();
    } finally {
      timer = setTimeout(tick, isBusy(job) || starting ? 1500 : 15000);
    }
  }
  $effect(() => {
    tick();
    return () => clearTimeout(timer);
  });

  async function start() {
    starting = true;
    startError = null;
    try {
      await post("/admin/analysis/start");
      await tick();
    } catch (e) {
      startError = e instanceof ApiError ? e.message : "Start fehlgeschlagen";
    } finally {
      starting = false;
    }
  }

  const jobPct = $derived(job && job.total ? pct(job.progress, job.total) : null);
  const stuck = $derived(job?.status === "queued" && now - job.created_at > STUCK_MS);
  const result = $derived(job?.result as { analyzed?: number; failed?: number; skipped?: string } | null | undefined);

  const num = (n: number) => n.toLocaleString("de-DE");
  const soundOn = $derived(!!analysis?.backend.includes("+effnet"));
</script>

{#if analysis === null}
  <p class="set-note">Lädt …</p>
{:else if analysis.backend === "none"}
  <div class="set-card"><div class="set-row"><span class="set-label">
    <strong>Keine Audioanalyse auf dieser Plattform</strong>
    <small>Essentia gibt es nur für x86_64. Auto-Playlists nach Genre und Jahrzehnt und das Radio nach Genre/Jahr funktionieren trotzdem.</small>
  </span></div></div>
{:else}
  <section class="set-group">
    <h2>Fortschritt</h2>
    <div class="set-card">
      <div class="set-row meter">
        <span class="icon" aria-hidden="true"><Icon name="spark" size={18} /></span>
        <div class="set-label">
          <strong>Audio-Merkmale</strong>
          <small>Tempo, Energie, Tanzbarkeit, Tonart – für „Stimmung & Aktivität“ und die Mixe.</small>
          <div class="set-progress"><div style:width="{pct(analysis.analyzed, analysis.tracks)}%"></div></div>
        </div>
        <span class="value"><strong>{num(analysis.analyzed)}</strong> / {num(analysis.tracks)}</span>
      </div>
      <div class="set-row meter">
        <span class="icon" aria-hidden="true"><Icon name="wave" size={18} /></span>
        <div class="set-label">
          <strong>Klangerkennung (Fingerabdrücke)</strong>
          <small>
            {#if soundOn}Für Radio und „Ähnliche Titel“; Titel ohne Fingerabdruck nutzen dort noch die Audio-Merkmale.
            {:else}Modelle nicht geladen – Radio und „Ähnliche Titel“ nutzen die Audio-Merkmale.{/if}
          </small>
          <div class="set-progress"><div style:width="{pct(analysis.fingerprints, analysis.tracks)}%"></div></div>
        </div>
        <span class="value"><strong>{num(analysis.fingerprints)}</strong> / {num(analysis.tracks)}</span>
      </div>
      <div class="set-row">
        <span class="icon" aria-hidden="true"><Icon name="tag" size={18} /></span>
        <div class="set-label">
          <strong>Erkannte Stile</strong>
          <small>Titel mit mindestens einem erkannten Stil; ab 25 Titeln wird daraus ein Playlist-Vorschlag.</small>
        </div>
        <span class="value"><strong>{num(analysis.styles)}</strong></span>
      </div>
    </div>
  </section>

  <section class="set-group">
    <h2>Status</h2>
    <div class="set-card">
      <div class="set-row">
        <div class="set-label">
          {#if stuck}
            <strong>Wartet auf den Analyse-Worker</strong>
            <small>Der Job steht seit {fmtDate(job?.created_at ?? null)} in der Warteschlange. Läuft der Worker? Siehe Server-Log.</small>
          {:else if isBusy(job)}
            <strong>{job?.status === "queued" ? "Analyse startet …" : "Analyse läuft"}</strong>
            <small>Mit niedriger Priorität im Hintergrund. {job?.message ?? ""}</small>
            <div class="set-progress job">
              {#if jobPct === null}<div class="indeterminate"></div>{:else}<div style:width="{jobPct}%"></div>{/if}
            </div>
          {:else if analysis.pending}
            <strong>{num(analysis.pending)} Titel ausstehend</strong>
            <small>Startet sonst automatisch nach dem nächsten Scan.</small>
          {:else}
            <strong>Alles analysiert</strong>
            <small>Neue Titel werden nach jedem Scan analysiert.</small>
          {/if}
        </div>
        {#if !isBusy(job) && analysis.pending}
          <button class="btn primary" onclick={start} disabled={starting}>{starting ? "Startet …" : "Jetzt analysieren"}</button>
        {/if}
      </div>
      {#if startError}
        <div class="set-row"><span class="set-label"><strong class="bad">Start fehlgeschlagen</strong><small>{startError}</small></span></div>
      {:else if job && !isBusy(job)}
        <div class="set-row">
          <span class="set-label">
            <strong class:bad={job.status === "failed"}>
              Letzter Lauf {fmtDate(job.finished_at ?? job.created_at)}:
              {#if job.status === "failed"}fehlgeschlagen
              {:else if job.status === "cancelled"}abgebrochen
              {:else if result?.skipped}übersprungen
              {:else}{num(result?.analyzed ?? 0)} analysiert{#if result?.failed}, {num(result.failed)} nicht analysierbar{/if}{/if}
            </strong>
            {#if job.error}<small class="set-mono">{job.error}</small>
            {:else if result?.skipped}<small>{result.skipped}</small>
            {:else if job.status === "done" && !result?.analyzed && !result?.failed && analysis.pending}
              <small>Der Lauf fand nichts zu tun, obwohl Titel ausstehen. Details im Server-Log.</small>
            {/if}
          </span>
        </div>
      {/if}
      <div class="set-row">
        <div class="set-label"><strong>Analyse-Backend</strong><small class="set-mono">{analysis.backend}</small></div>
      </div>
      {#if analysis.failed}
        <details class="set-row failures">
          <summary><strong>{num(analysis.failed)} nicht analysierbar</strong> <small>Details</small></summary>
          <ul>{#each failures as f (f.track_id)}<li><code>{f.path}</code> – {f.error}</li>{/each}</ul>
        </details>
      {/if}
    </div>
  </section>

  <p class="set-note"><a href={href("/discover?tab=suggested")}>Auto-Playlist-Vorschläge ansehen →</a></p>
{/if}

<style>
  .icon {
    width: 34px;
    height: 34px;
    border-radius: 10px;
    display: grid;
    place-items: center;
    background: var(--surface-1);
    color: var(--accent);
    flex: none;
  }
  .meter .set-progress,
  .set-progress.job {
    margin-top: 10px;
  }
  .bad {
    color: var(--danger);
  }
  .value {
    color: var(--text-muted);
    font-size: 0.88rem;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .value strong {
    color: var(--text);
    font-weight: 600;
  }
  .failures {
    display: block;
  }
  .failures summary {
    cursor: pointer;
    padding: 6px 0;
  }
  .failures small {
    color: var(--text-muted);
    margin-left: 6px;
  }
  .failures ul {
    font-size: 0.82rem;
    color: var(--text-muted);
    max-height: 220px;
    overflow-y: auto;
    padding-left: 18px;
  }
  code {
    font-family: ui-monospace, monospace;
    font-size: 0.8rem;
    word-break: break-all;
  }
</style>
