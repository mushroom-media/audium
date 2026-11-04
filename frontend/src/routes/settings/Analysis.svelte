<script lang="ts">
  import { ApiError, get, patch, post, type AnalysisStatus } from "../../lib/api";
  import { toast } from "../../lib/ui.svelte";
  import Icon from "../../lib/components/Icon.svelte";
  import { href } from "../../lib/router.svelte";
  import { fmtDate, isBusy, type Job } from "./common";
  import { locale, t, tn } from "../../lib/i18n.svelte";

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
      startError = e instanceof ApiError ? e.message : t("Start fehlgeschlagen");
    } finally {
      starting = false;
    }
  }

  const jobPct = $derived(job && job.total ? pct(job.progress, job.total) : null);
  const stuck = $derived(job?.status === "queued" && now - job.created_at > STUCK_MS);
  const result = $derived(job?.result as { analyzed?: number; failed?: number; skipped?: string } | null | undefined);

  const num = (n: number) => n.toLocaleString(locale());

  // --- processes, pause, time window (server settings) ------------------------------------------

  interface Power {
    analysis_workers: string;
    analysis_paused: "on" | "off";
    analysis_schedule: "always" | "window";
    analysis_from: string;
    analysis_until: string;
  }
  let power = $state<Power | null>(null);
  $effect(() => {
    get<Power>("/admin/settings").then((s) => (power = s));
  });
  const HOURS = Array.from({ length: 24 }, (_, h) => String(h).padStart(2, "0"));
  const MAX_WORKERS = 16;
  const workerChoices = $derived(Array.from({ length: Math.min(MAX_WORKERS, Math.max(analysis?.cpus ?? 1, 1)) }, (_, i) => String(i + 1)));

  async function savePower(changes: Partial<Power>) {
    const before = power;
    power = power && { ...power, ...changes };
    try {
      power = await patch<Power>("/admin/settings", changes);
      await refresh();
    } catch (e) {
      power = before;
      toast(e instanceof ApiError ? e.message : t("Speichern fehlgeschlagen"));
    }
  }
  const windowText = $derived(power ? t("{from}–{until} Uhr", { from: Number(power.analysis_from), until: Number(power.analysis_until) }) : "");
  const soundOn = $derived(!!analysis?.backend.includes("+effnet"));
</script>

{#if analysis === null}
  <p class="set-note">{t("Lädt …")}</p>
{:else if analysis.backend === "none"}
  <div class="set-card"><div class="set-row"><span class="set-label">
    <strong>{t("Keine Audioanalyse auf dieser Plattform")}</strong>
    <small>{t("Essentia gibt es nur für x86_64. Auto-Playlists nach Genre und Jahrzehnt und das Radio nach Genre/Jahr funktionieren trotzdem.")}</small>
  </span></div></div>
{:else}
  <section class="set-group">
    <h2>{t("Fortschritt")}</h2>
    <div class="set-card">
      <div class="set-row meter">
        <span class="icon" aria-hidden="true"><Icon name="spark" size={18} /></span>
        <div class="set-label">
          <strong>{t("Audio-Merkmale")}</strong>
          <small>{t("Tempo, Energie, Tanzbarkeit, Tonart – für „Stimmung & Aktivität“ und die Mixe.")}</small>
          <div class="set-progress"><div style:width="{pct(analysis.analyzed, analysis.tracks)}%"></div></div>
        </div>
        <span class="value"><strong>{num(analysis.analyzed)}</strong> / {num(analysis.tracks)}</span>
      </div>
      <div class="set-row meter">
        <span class="icon" aria-hidden="true"><Icon name="wave" size={18} /></span>
        <div class="set-label">
          <strong>{t("Klangerkennung (Fingerabdrücke)")}</strong>
          <small>
            {#if soundOn}{t("Für Radio und „Ähnliche Titel“.")}
            {:else}{t("Modelle nicht geladen – Radio und „Ähnliche Titel“ nutzen die Audio-Merkmale.")}{/if}
          </small>
          <div class="set-progress"><div style:width="{pct(analysis.fingerprints, analysis.tracks)}%"></div></div>
        </div>
        <span class="value"><strong>{num(analysis.fingerprints)}</strong> / {num(analysis.tracks)}</span>
      </div>
      <div class="set-row">
        <span class="icon" aria-hidden="true"><Icon name="tag" size={18} /></span>
        <div class="set-label">
          <strong>{t("Erkannte Stile")}</strong>
          <small>{t("Titel mit mindestens einem erkannten Stil; ab 25 Titeln wird daraus ein Playlist-Vorschlag.")}</small>
        </div>
        <span class="value"><strong>{num(analysis.styles)}</strong></span>
      </div>
    </div>
  </section>

  {#if power}
    <section class="set-group">
      <h2>{t("Rechenleistung")}</h2>
      <div class="set-card">
        <div class="set-row">
          <div class="set-label">
            <strong>{t("Gleichzeitige Analysen")}</strong>
            <small>{tn(analysis.cpus, "Jede nutzt einen CPU-Kern, mit niedrigster Priorität: Wiedergabe und Bedienung gehen immer vor. Der Server hat {n} Kern.", "Jede nutzt einen CPU-Kern, mit niedrigster Priorität: Wiedergabe und Bedienung gehen immer vor. Der Server hat {n} Kerne.")}</small>
          </div>
          <select aria-label={t("Gleichzeitige Analysen")} value={power.analysis_workers} onchange={(e) => savePower({ analysis_workers: e.currentTarget.value })}>
            <option value="default">{t("Standard ({n})", { n: analysis.workers_default })}</option>
            {#each workerChoices as n (n)}<option value={n}>{n}</option>{/each}
          </select>
        </div>
        <label class="set-row">
          <span class="set-label"><strong>{t("Analyse pausieren")}</strong><small>{t("Ein laufender Durchgang hält nach den gerade bearbeiteten Titeln an.")}</small></span>
          <input type="checkbox" class="toggle" checked={power.analysis_paused === "on"} onchange={(e) => savePower({ analysis_paused: e.currentTarget.checked ? "on" : "off" })} />
        </label>
        <label class="set-row">
          <span class="set-label">
            <strong>{t("Nur in einem Zeitfenster")}</strong>
            <small>{t("Zum Beispiel nachts, wenn der Server sonst nichts zu tun hat. Uhrzeit des Servers, gerade {time} Uhr.", { time: analysis.server_time })}</small>
          </span>
          <input type="checkbox" class="toggle" checked={power.analysis_schedule === "window"} onchange={(e) => savePower({ analysis_schedule: e.currentTarget.checked ? "window" : "always" })} />
        </label>
        {#if power.analysis_schedule === "window"}
          <div class="set-row">
            <div class="set-label"><strong>{t("Von – bis")}</strong><small>{t("Bis zur vollen Stunde; über Mitternacht geht auch (z. B. 22–6 Uhr).")}</small></div>
            <div class="hours">
              <select aria-label={t("Von")} value={power.analysis_from} onchange={(e) => savePower({ analysis_from: e.currentTarget.value })}>
                {#each HOURS as h (h)}<option value={h}>{h}:00</option>{/each}
              </select>
              <span>–</span>
              <select aria-label={t("Bis")} value={power.analysis_until} onchange={(e) => savePower({ analysis_until: e.currentTarget.value })}>
                {#each HOURS as h (h)}<option value={h}>{h}:00</option>{/each}
              </select>
            </div>
          </div>
        {/if}
      </div>
    </section>
  {/if}

  <section class="set-group">
    <h2>{t("Status")}</h2>
    <div class="set-card">
      <div class="set-row">
        <div class="set-label">
          {#if stuck}
            <strong>{t("Wartet auf den Analyse-Worker")}</strong>
            <small>{t("Der Job steht seit {date} in der Warteschlange. Läuft der Worker? Siehe Server-Log.", { date: fmtDate(job?.created_at ?? null) })}</small>
          {:else if analysis.waiting && !isBusy(job)}
            <strong>{analysis.waiting === "paused" ? t("Pausiert") : t("Wartet auf das Zeitfenster ({window})", { window: windowText })}</strong>
            <small>{t("{n} Titel ausstehend.", { n: num(analysis.pending) })} {analysis.waiting === "paused" ? t("Geht weiter, sobald du die Pause aufhebst.") : t("Geht von selbst weiter, sobald das Zeitfenster beginnt.")}</small>
          {:else if isBusy(job)}
            <strong>{job?.status === "queued" ? t("Analyse startet …") : t("Analyse läuft")}</strong>
            {#if job?.message}<small>{job.message}</small>{/if}
            <div class="set-progress job">
              {#if jobPct === null}<div class="indeterminate"></div>{:else}<div style:width="{jobPct}%"></div>{/if}
            </div>
          {:else if analysis.pending}
            <strong>{t("{n} Titel ausstehend", { n: num(analysis.pending) })}</strong>
            <small>{t("Startet sonst automatisch nach dem nächsten Scan.")}</small>
          {:else}
            <strong>{t("Alles analysiert")}</strong>
            <small>{t("Neue Titel werden nach jedem Scan analysiert.")}</small>
          {/if}
        </div>
        {#if !isBusy(job) && analysis.pending && !analysis.waiting}
          <button class="btn primary" onclick={start} disabled={starting}>{starting ? t("Startet …") : t("Jetzt analysieren")}</button>
        {/if}
      </div>
      {#if startError}
        <div class="set-row"><span class="set-label"><strong class="bad">{t("Start fehlgeschlagen")}</strong><small>{startError}</small></span></div>
      {:else if job && !isBusy(job)}
        <div class="set-row">
          <span class="set-label">
            <strong class:bad={job.status === "failed"}>
              {t("Letzter Lauf {date}:", { date: fmtDate(job.finished_at ?? job.created_at) })}
              {#if job.status === "failed"}{t("fehlgeschlagen")}
              {:else if job.status === "cancelled"}{t("abgebrochen")}
              {:else if result?.skipped}{t("übersprungen")}
              {:else}{t("{n} analysiert", { n: num(result?.analyzed ?? 0) })}{#if result?.failed}, {t("{n} nicht analysierbar", { n: num(result.failed) })}{/if}{/if}
            </strong>
            {#if job.error}<small class="set-mono">{job.error}</small>
            {:else if result?.skipped}<small>{result.skipped}</small>
            {:else if job.status === "done" && !result?.analyzed && !result?.failed && analysis.pending}
              <small>{t("Der Lauf fand nichts zu tun, obwohl Titel ausstehen. Details im Server-Log.")}</small>
            {/if}
          </span>
        </div>
      {/if}
      <div class="set-row">
        <div class="set-label"><strong>{t("Analyse-Backend")}</strong><small class="set-mono">{analysis.backend}</small></div>
      </div>
      {#if analysis.failed}
        <details class="set-row failures">
          <summary><strong>{t("{n} nicht analysierbar", { n: num(analysis.failed) })}</strong> <small>{t("Details")}</small></summary>
          <ul>{#each failures as f (f.track_id)}<li><code>{f.path}</code> – {f.error}</li>{/each}</ul>
        </details>
      {/if}
    </div>
  </section>

  <p class="set-note"><a href={href("/settings/autoplaylists")}>{t("Auto-Playlist-Vorschläge ansehen →")}</a></p>
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
  .hours {
    display: flex;
    align-items: center;
    gap: 8px;
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
