<script lang="ts">
  import { saveSettings, session } from "../../lib/session.svelte";
  import { msg, t } from "../../lib/i18n.svelte";

  const KEYS: [string, string][] = [
    // Key names are shown through t() too: only "Leertaste" has a translation, the rest are symbols.
    [msg("Leertaste"), msg("Abspielen / Pause")],
    ["Shift + ← / →", msg("Vorheriger / nächster Titel")],
    ["Shift + ↑ / ↓", msg("Lautstärke")],
    ["M", msg("Stumm")],
    ["S", msg("Zufall")],
    ["R", msg("Wiederholen")],
    ["Q", msg("Warteschlange")],
    ["N", msg("Jetzt läuft")],
    ["/", msg("Suchen")],
  ];
  const on = $derived(session.settings.shortcuts === "on");
</script>

<section class="set-group">
  <div class="set-card">
    <label class="set-row">
      <span class="set-label"><strong>{t("Tastenkürzel verwenden")}</strong><small>{t("Gelten nicht, während du in ein Textfeld tippst.")}</small></span>
      <input type="checkbox" class="toggle" checked={on} onchange={(e) => saveSettings({ shortcuts: e.currentTarget.checked ? "on" : "off" })} />
    </label>
    <label class="set-row" class:off={!on}>
      <span class="set-label"><strong>{t("Spulen mit ← / →")}</strong><small>{t("10 Sekunden zurück / vor. Aus: Die Pfeiltasten bleiben der Seite überlassen.")}</small></span>
      <input type="checkbox" class="toggle" disabled={!on} checked={session.settings.seek_keys === "on"} onchange={(e) => saveSettings({ seek_keys: e.currentTarget.checked ? "on" : "off" })} />
    </label>
  </div>
</section>

<section class="set-group" class:off={!on}>
  <h2>{t("Übersicht")}</h2>
  <div class="set-card">
    {#each KEYS as [key, what] (key)}
      <div class="set-row compact"><span class="set-label">{t(what)}</span><kbd>{t(key)}</kbd></div>
    {/each}
  </div>
</section>

<style>
  .off {
    opacity: 0.45;
  }
  .compact {
    min-height: 44px;
    padding: 6px 16px;
  }
  kbd {
    font-family: ui-monospace, monospace;
    font-size: 0.8rem;
    padding: 3px 8px;
    border-radius: 6px;
    border: 1px solid var(--surface-2);
    border-bottom-width: 2px;
    background: var(--surface-1);
    color: var(--text);
    white-space: nowrap;
  }
</style>
