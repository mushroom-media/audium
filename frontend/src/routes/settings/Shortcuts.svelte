<script lang="ts">
  import { saveSettings, session } from "../../lib/session.svelte";

  const KEYS: [string, string][] = [
    ["Leertaste", "Abspielen / Pause"],
    ["← / →", "10 Sekunden zurück / vor"],
    ["Shift + ← / →", "Vorheriger / nächster Titel"],
    ["Shift + ↑ / ↓", "Lautstärke"],
    ["M", "Stumm"],
    ["S", "Zufall"],
    ["R", "Wiederholen"],
    ["Q", "Warteschlange"],
    ["N", "Jetzt läuft"],
    ["/", "Suchen"],
  ];
  const on = $derived(session.settings.shortcuts === "on");
</script>

<section class="set-group">
  <div class="set-card">
    <label class="set-row">
      <span class="set-label"><strong>Tastenkürzel verwenden</strong><small>Gelten nicht, während du in ein Textfeld tippst.</small></span>
      <input type="checkbox" class="toggle" checked={on} onchange={(e) => saveSettings({ shortcuts: e.currentTarget.checked ? "on" : "off" })} />
    </label>
  </div>
</section>

<section class="set-group" class:off={!on}>
  <h2>Übersicht</h2>
  <div class="set-card">
    {#each KEYS as [key, what] (key)}
      <div class="set-row compact"><span class="set-label">{what}</span><kbd>{key}</kbd></div>
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
