<script lang="ts">
  import { ApiError, get, post } from "../../lib/api";
  import { toast } from "../../lib/ui.svelte";
  import { fmtDate, isBusy, type Job } from "./common";
  import { locale, msg, num, t } from "../../lib/i18n.svelte";

  const LABELS: Record<string, string> = {
    scan: msg("Bibliotheks-Scan"),
    analyze: msg("Audioanalyse"),
    autoplaylists: msg("Auto-Playlists"),
    genres: msg("Genres vereinheitlichen"),
    similar_artists: msg("Ähnliche Künstler (ListenBrainz)"),
  };
  const RESULT_LABELS: Record<string, string> = {
    files_seen: msg("Dateien"),
    added: msg("neu"),
    updated: msg("geändert"),
    removed: msg("entfernt"),
    missing: msg("fehlend"),
    errors: msg("Fehler|Anzahl"),
    analyzed: msg("analysiert"),
    artists: msg("Künstler|Anzahl"),
    matched: msg("Treffer"),
    no_mbid: msg("ohne MusicBrainz-ID"),
    left: msg("offen"),
    failed: msg("fehlgeschlagen"),
    created: msg("erstellt"),
    covers_added: msg("Cover|Anzahl"),
  };
  const STATUS: Record<string, string> = {
    queued: msg("wartet"),
    running: msg("läuft"),
    done: msg("fertig"),
    failed: msg("fehlgeschlagen"),
    cancelled: msg("abgebrochen"),
  };

  let jobs = $state<Job[] | null>(null);
  const load = () => get<{ items: Job[] }>("/admin/jobs", { limit: 50 }).then((r) => (jobs = r.items));

  $effect(() => {
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  });

  function summary(r: Record<string, number>): string {
    return (
      Object.entries(RESULT_LABELS)
        .filter(([k]) => typeof r[k] === "number" && r[k] > 0)
        .map(([k, label]) => `${num(r[k])} ${t(label)}`)
        .join(" · ") || t("keine Änderungen")
    );
  }

  async function cancel(j: Job) {
    try {
      await post(`/admin/jobs/${j.id}/cancel`);
      toast(t("Wird abgebrochen"));
      load();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("Fehlgeschlagen"));
    }
  }
</script>

<div class="set-card">
  {#each jobs ?? [] as j (j.id)}
    <div class="set-row job">
      <span class="set-dot {j.status === 'failed' ? 'bad' : j.status === 'running' ? 'ok' : ''}"></span>
      <div class="set-label">
        <strong>{LABELS[j.type] ? t(LABELS[j.type]) : j.type} <span class="status">· {STATUS[j.status] ? t(STATUS[j.status]) : j.status}</span></strong>
        <small>
          {fmtDate(j.created_at)}
          {#if j.status === "running" && j.total} · {j.progress.toLocaleString(locale())} / {j.total.toLocaleString(locale())}{/if}
          {#if j.message && j.status === "running"}<br /><span class="set-mono">{j.message}</span>{/if}
          {#if j.error}<br /><span class="set-warn set-mono">{j.error}</span>{/if}
          {#if j.result && j.status === "done"}<br />{summary(j.result)}{/if}
        </small>
      </div>
      {#if isBusy(j)}<button class="btn small ghost" onclick={() => cancel(j)}>{t("Abbrechen")}</button>{/if}
    </div>
  {:else}
    <div class="set-row"><span class="set-label"><small>{jobs === null ? t("Lädt …") : t("Keine Jobs.")}</small></span></div>
  {/each}
</div>

<style>
  .job {
    align-items: flex-start;
  }
  .job .set-dot {
    margin-top: 6px;
  }
  .status {
    color: var(--text-muted);
    font-weight: 400;
  }
</style>
