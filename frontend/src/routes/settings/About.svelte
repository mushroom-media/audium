<script lang="ts">
  // Settings > About: the versions, where the source code is, the license.
  import { isApp, serverUrl } from "../../lib/api";
  import { appUpdate } from "../../lib/appUpdate.svelte";
  import { msg, t } from "../../lib/i18n.svelte";

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
