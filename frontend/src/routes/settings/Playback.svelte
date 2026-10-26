<script lang="ts">
  import type { StreamQuality } from "../../lib/api";
  import { player } from "../../lib/player.svelte";
  import { saveSettings, session } from "../../lib/session.svelte";

  const QUALITIES: Record<StreamQuality, string> = {
    auto: "Original (wenn möglich)",
    high: "Hoch (≈ 192–256 kbit/s)",
    medium: "Mittel (≈ 128–160 kbit/s)",
    low: "Niedrig (≈ 64–96 kbit/s, mobile Daten)",
  };
</script>

<section class="set-group">
  <h2>Wiedergabe</h2>
  <div class="set-card">
    <div class="set-row">
      <div class="set-label"><strong>Streaming-Qualität</strong><small>Niedriger spart Datenvolumen unterwegs.</small></div>
      <select
        aria-label="Streaming-Qualität"
        value={session.settings.stream_quality}
        onchange={(e) => saveSettings({ stream_quality: e.currentTarget.value as StreamQuality }).then(() => (player.quality = session.settings.stream_quality))}
      >
        {#each Object.entries(QUALITIES) as [k, v] (k)}<option value={k}>{v}</option>{/each}
      </select>
    </div>
  </div>
  <p class="set-note">Formate, die dein Browser nicht abspielen kann (z. B. WMA, APE), werden immer umgewandelt.</p>
</section>
