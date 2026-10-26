<script lang="ts">
  import type { Theme } from "../../lib/api";
  import { saveSettings, session } from "../../lib/session.svelte";

  const THEMES: Record<Theme, string> = { system: "System", dark: "Dunkel", light: "Hell" };
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
  </div>
</section>
