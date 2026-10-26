<script lang="ts">
  import { ApiError, get, post } from "../../lib/api";
  import { toast } from "../../lib/ui.svelte";
  import { fmtDate, isBusy, type Job } from "./common";

  const LABELS: Record<string, string> = {
    scan: "Bibliotheks-Scan",
    analyze: "Audioanalyse",
    autoplaylists: "Auto-Playlists",
    genres: "Genres vereinheitlichen",
  };
  const RESULT_LABELS: Record<string, string> = {
    files_seen: "Dateien", added: "neu", updated: "geändert", removed: "entfernt", missing: "fehlend", errors: "Fehler",
    analyzed: "analysiert", failed: "fehlgeschlagen", created: "erstellt", covers_added: "Cover",
  };
  const STATUS: Record<string, string> = {
    queued: "wartet", running: "läuft", done: "fertig", failed: "fehlgeschlagen", cancelled: "abgebrochen",
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
        .map(([k, label]) => `${r[k].toLocaleString("de-DE")} ${label}`)
        .join(" · ") || "keine Änderungen"
    );
  }

  async function cancel(j: Job) {
    try {
      await post(`/admin/jobs/${j.id}/cancel`);
      toast("Wird abgebrochen");
      load();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Fehlgeschlagen");
    }
  }
</script>

<div class="set-card">
  {#each jobs ?? [] as j (j.id)}
    <div class="set-row job">
      <span class="set-dot {j.status === 'failed' ? 'bad' : j.status === 'running' ? 'ok' : ''}"></span>
      <div class="set-label">
        <strong>{LABELS[j.type] ?? j.type} <span class="status">· {STATUS[j.status] ?? j.status}</span></strong>
        <small>
          {fmtDate(j.created_at)}
          {#if j.status === "running" && j.total} · {j.progress.toLocaleString("de-DE")} / {j.total.toLocaleString("de-DE")}{/if}
          {#if j.message && j.status === "running"}<br /><span class="set-mono">{j.message}</span>{/if}
          {#if j.error}<br /><span class="set-warn set-mono">{j.error}</span>{/if}
          {#if j.result && j.status === "done"}<br />{summary(j.result)}{/if}
        </small>
      </div>
      {#if isBusy(j)}<button class="btn small ghost" onclick={() => cancel(j)}>Abbrechen</button>{/if}
    </div>
  {:else}
    <div class="set-row"><span class="set-label"><small>{jobs === null ? "Lädt …" : "Keine Jobs."}</small></span></div>
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
