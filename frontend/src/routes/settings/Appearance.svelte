<script lang="ts">
  import type { Theme } from "../../lib/api";
  import { saveSettings, session } from "../../lib/session.svelte";

  const THEMES: Record<Theme, string> = { system: "System", dark: "Dunkel", light: "Hell" };
  // The value while its slider is dragged; saved when it is let go.
  let motion = $state<number | null>(null);
  const shown = $derived(motion ?? session.settings.backdrop_motion);
  const label = $derived(shown === 0 ? "Still" : shown < 35 ? "Ruhig" : shown <= 65 ? "Normal" : "Lebhaft");
</script>

<section class="set-group">
  <h2>Darstellung</h2>
  <div class="set-card">
    <div class="set-row">
      <div class="set-label"><strong>Farbschema</strong><small>„System“ folgt der Einstellung deines Geräts.</small></div>
      <div class="segmented" role="radiogroup" aria-label="Farbschema">
        {#each Object.entries(THEMES) as [k, v] (k)}
          <button role="radio" aria-checked={session.settings.theme === k} class:on={session.settings.theme === k} onclick={() => saveSettings({ theme: k as Theme })}>{v}</button>
        {/each}
      </div>
    </div>
    <div class="set-row slider">
      <span class="set-label">
        <strong>Hintergrund in „Läuft gerade“</strong>
        <small>Wie lebhaft sich das verschwommene Cover hinter dem Player bewegt. Ganz links steht es still.</small>
      </span>
      <div class="control">
        <input
          type="range"
          min="0"
          max="100"
          step="5"
          value={shown}
          aria-label="Bewegung des Hintergrunds"
          style:--p="{shown}%"
          oninput={(e) => (motion = +e.currentTarget.value)}
          onchange={(e) => saveSettings({ backdrop_motion: +e.currentTarget.value }).finally(() => (motion = null))}
        />
        <span class="value">{label}</span>
      </div>
    </div>
  </div>
</section>

<style>
  .slider {
    flex-wrap: wrap;
  }
  .control {
    display: flex;
    align-items: center;
    gap: 12px;
    flex: 1 1 220px;
  }
  .control input {
    flex: 1;
  }
  /* Unlike the seek bar, a setting shows where its knob is. */
  .control input::-webkit-slider-thumb {
    opacity: 1;
  }
  .control input::-moz-range-thumb {
    opacity: 1;
  }
  .value {
    width: 4.2em;
    text-align: right;
    color: var(--text-muted);
    font-size: 0.88rem;
  }
</style>
