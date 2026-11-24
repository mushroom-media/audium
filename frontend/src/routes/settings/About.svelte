<script lang="ts">
  // Settings > About: the versions, where the source code is, the license.
  import { isApp, serverUrl } from "../../lib/api";
  import { APP_DOWNLOADS, appUpdate, checkForAppUpdate, restartForUpdate } from "../../lib/appUpdate.svelte";
  import { msg, t } from "../../lib/i18n.svelte";
  import { toast } from "../../lib/ui.svelte";

  const mb = (bytes: number) => (bytes / 1_000_000).toFixed(1);
  const pct = $derived(
    appUpdate.progress?.total ? Math.min(100, Math.round((appUpdate.progress.downloaded / appUpdate.progress.total) * 100)) : null,
  );

  async function updateNow() {
    try {
      await restartForUpdate();
    } catch {
      toast(
        appUpdate.mode === "next-start"
          ? t("audium ließ sich nicht neu starten. Die neue Version ist beim nächsten Start da.")
          : t("Das Update ließ sich nicht starten. audium versucht es beim Schließen noch einmal."),
      );
    }
  }

  const REPO = "https://github.com/mushroom-media/audium";

  let server = $state<string | null>(null);
  $effect(() => {
    fetch(`${serverUrl()}/api/health`, { credentials: "omit" })
      .then((r) => r.json())
      .then((h: { version?: string }) => (server = h.version ?? null))
      .catch(() => (server = null));
  });

  const links = [
    { label: msg("Quellcode"), href: REPO },
    { label: msg("Änderungen"), href: `${REPO}/blob/main/CHANGELOG.md` },
    { label: msg("Fehler melden"), href: `${REPO}/issues` },
  ];
</script>

<section class="set-group">
  <h2>{t("Version")}</h2>
  <div class="set-card">
    <div class="set-row compact">
      <span class="set-label">{t("audium-Server")}</span>
      <span class="value">{server ?? "–"}</span>
    </div>
    {#if isApp && appUpdate.current}
      <div class="set-row compact">
        <span class="set-label">{t("Diese App")}</span>
        <span class="value">{appUpdate.current}</span>
      </div>
    {/if}
  </div>
</section>

{#if isApp && appUpdate.mode === "manual"}
  <!-- An app that cannot replace itself (app/src-tauri/src/update.rs, Mode::Manual). -->
  <section class="set-group">
    <h2>{t("Updates")}</h2>
    <div class="set-card">
      <div class="set-row">
        <div class="set-label">
          <strong>{t("Neue Versionen von Hand")}</strong>
          <small>{t("Diese App aktualisiert sich nicht selbst: Sie ist als Paket installiert oder liegt in einem Ordner, in den sie nicht schreiben darf (auf dem Mac: zuerst in „Programme“ ziehen). Neue Versionen gibt es auf der Download-Seite.")}</small>
        </div>
        <a class="btn small" href={APP_DOWNLOADS} target="_blank" rel="noopener noreferrer">{t("Download-Seite")}</a>
      </div>
    </div>
  </section>
{:else if isApp && appUpdate.mode && appUpdate.current}
  <!-- The desktop app (app/src-tauri/src/update.rs, frontend/src/lib/appUpdate.svelte.ts). -->
  <section class="set-group">
    <h2>{t("Updates")}</h2>
    <div class="set-card">
      <div class="set-row">
        <div class="set-label">
          {#if appUpdate.version}
            <strong>{t("Version {version} ist bereit", { version: appUpdate.version })}</strong>
            {#if appUpdate.mode === "next-start"}
              <small>{t("Installiert. Sie ist da, sobald du audium das nächste Mal startest. Oder jetzt: audium startet dann kurz neu.")}</small>
            {:else}
              <small>{t("Heruntergeladen. Wird installiert, wenn du audium schließt. Oder jetzt: audium startet dann kurz neu.")}</small>
            {/if}
          {:else if appUpdate.progress}
            <strong>{t("Neue Version wird heruntergeladen …")}</strong>
            <small>
              {#if appUpdate.progress.total}
                {t("{done} von {total} MB", { done: mb(appUpdate.progress.downloaded), total: mb(appUpdate.progress.total) })}
              {:else}
                {t("{done} MB", { done: mb(appUpdate.progress.downloaded) })}
              {/if}
            </small>
          {:else if appUpdate.checking}
            <strong>{t("Suche nach Updates …")}</strong>
          {:else if appUpdate.result === "latest"}
            <strong>{t("audium ist auf dem neuesten Stand")}</strong>
            <small>{t("Version {version}", { version: appUpdate.current })}</small>
          {:else if appUpdate.result === "failed"}
            <strong>{t("Suche fehlgeschlagen")}</strong>
            <small>{t("GitHub war nicht erreichbar. Prüfe die Internetverbindung und versuch es noch einmal.")}</small>
          {:else}
            <strong>{t("Nach Updates suchen")}</strong>
            <small>{t("Neue Versionen lädt audium auch von selbst im Hintergrund.")}</small>
          {/if}
        </div>
        {#if appUpdate.version}
          <button class="btn small primary" disabled={appUpdate.installing} onclick={updateNow}>
            {appUpdate.mode === "next-start" ? t("Jetzt neu starten") : t("Jetzt neu starten und installieren")}
          </button>
        {:else}
          <button class="btn small" disabled={appUpdate.checking || !!appUpdate.progress} onclick={checkForAppUpdate}>
            {t("Nach Updates suchen")}
          </button>
        {/if}
      </div>
      {#if !appUpdate.version && (appUpdate.progress || appUpdate.checking)}
        <div class="set-row compact">
          <div class="set-progress bar">
            {#if pct !== null}<div style:width="{pct}%"></div>{:else}<div class="indeterminate"></div>{/if}
          </div>
        </div>
      {/if}
    </div>
  </section>
{/if}

<section class="set-group">
  <h2>{t("Projekt")}</h2>
  <div class="set-card">
    {#each links as l (l.href)}
      <a class="set-row compact link" href={l.href} target="_blank" rel="noopener noreferrer">
        <span class="set-label">{t(l.label)}</span>
        <span class="url">{l.href.replace("https://", "")}</span>
      </a>
    {/each}
  </div>
</section>

<section class="set-group">
  <h2>{t("Lizenz")}</h2>
  <div class="set-card">
    <div class="set-row compact"><span class="set-label">{t("Server")}</span><span class="value">AGPL-3.0</span></div>
    <div class="set-row compact"><span class="set-label">{t("Weboberfläche und Apps")}</span><span class="value">{t("MIT-Lizenz")}</span></div>
  </div>
  <p class="set-note">{t("audium ist freie Software: kostenlos, ohne Konto bei irgendwem, ohne Telemetrie.")}</p>
</section>

<style>
  .value {
    font-variant-numeric: tabular-nums;
    color: var(--text-muted);
  }
  .bar {
    flex: 1;
  }
  .link {
    color: inherit;
    text-decoration: none;
  }
  .link:hover .url {
    text-decoration: underline;
  }
  .url {
    color: var(--accent);
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
