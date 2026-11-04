<script lang="ts">
  import type { ReplayGainMode, StreamQuality } from "../../lib/api";
  import { player } from "../../lib/player.svelte";
  import { saveSettings, session } from "../../lib/session.svelte";
  import { msg, t } from "../../lib/i18n.svelte";

  const QUALITIES: Record<StreamQuality, string> = {
    auto: msg("Original (wenn möglich)"),
    high: msg("Hoch (≈ 192–256 kbit/s)"),
    medium: msg("Mittel (≈ 128–160 kbit/s)"),
    low: msg("Niedrig (≈ 64–96 kbit/s, mobile Daten)"),
  };
  const LEVELLING: Record<ReplayGainMode, string> = { off: msg("Aus"), track: msg("Pro Titel"), album: msg("Pro Album") };
  // The length while its slider is dragged; saved when it is let go.
  let fade = $state<number | null>(null);
</script>

<section class="set-group">
  <h2>{t("Wiedergabe")}</h2>
  <div class="set-card">
    <div class="set-row">
      <div class="set-label"><strong>{t("Streaming-Qualität")}</strong><small>{t("Niedriger spart Datenvolumen unterwegs.")}</small></div>
      <select
        aria-label={t("Streaming-Qualität")}
        value={session.settings.stream_quality}
        onchange={(e) => saveSettings({ stream_quality: e.currentTarget.value as StreamQuality }).then(() => (player.quality = session.settings.stream_quality))}
      >
        {#each Object.entries(QUALITIES) as [k, v] (k)}<option value={k}>{t(v)}</option>{/each}
      </select>
    </div>
  </div>
  <p class="set-note">{t("Formate, die dein Browser nicht abspielen kann (z. B. WMA, APE), werden immer umgewandelt.")}</p>
</section>

<section class="set-group">
  <h2>{t("Übergang")}</h2>
  <div class="set-card">
    <label class="set-row">
      <span class="set-label">
        <strong>{t("Überblenden")}</strong>
        <small>{t("Der nächste Titel setzt ein, während der aktuelle leiser wird. Nur wenn ein Titel zu Ende läuft, nicht beim Überspringen.")}</small>
      </span>
      <input type="checkbox" class="toggle" checked={session.settings.crossfade === "on"} onchange={(e) => saveSettings({ crossfade: e.currentTarget.checked ? "on" : "off" })} />
    </label>
    <div class="set-row slider" class:off={session.settings.crossfade !== "on"}>
      <span class="set-label"><strong>{t("Dauer")}</strong></span>
      <input
        type="range"
        min="1"
        max="12"
        value={fade ?? session.settings.crossfade_s}
        disabled={session.settings.crossfade !== "on"}
        aria-label={t("Dauer der Überblendung")}
        style:--p="{(((fade ?? session.settings.crossfade_s) - 1) / 11) * 100}%"
        oninput={(e) => (fade = +e.currentTarget.value)}
        onchange={(e) => saveSettings({ crossfade_s: +e.currentTarget.value }).finally(() => (fade = null))}
      />
      <span class="value">{fade ?? session.settings.crossfade_s} s</span>
    </div>
  </div>
  <p class="set-note">{t("Auf iPhone und iPad lässt der Browser die Lautstärke nicht regeln; dort überlappen sich die Titel nur.")}</p>
</section>

<section class="set-group">
  <h2>{t("Lautstärkeausgleich")}</h2>
  <div class="set-card">
    <div class="set-row">
      <div class="set-label">
        <strong>ReplayGain</strong>
        <small>{t("Gleicht laute und leise Aufnahmen an. „Pro Album“ behält die Abstufungen innerhalb eines Albums.")}</small>
      </div>
      <div class="segmented" role="radiogroup" aria-label={t("Lautstärkeausgleich")}>
        {#each Object.entries(LEVELLING) as [k, v] (k)}
          <button role="radio" aria-checked={session.settings.replay_gain === k} class:on={session.settings.replay_gain === k} onclick={() => saveSettings({ replay_gain: k as ReplayGainMode })}>{t(v)}</button>
        {/each}
      </div>
    </div>
  </div>
  <p class="set-note">
    {t("Nutzt die ReplayGain-Werte aus den Tags deiner Dateien (z. B. von foobar2000, beets oder MusicBrainz Picard); Titel ohne Werte bleiben unverändert. Laute Titel werden leiser, sehr leise nicht lauter als 100 %.")}
  </p>
</section>

<style>
  .slider input {
    flex: 1;
  }
  /* Unlike the seek bar, a setting shows where its knob is. */
  .slider input::-webkit-slider-thumb {
    opacity: 1;
  }
  .slider input::-moz-range-thumb {
    opacity: 1;
  }
  .slider .set-label {
    flex: none;
  }
  .value {
    width: 3.2em;
    text-align: right;
    font-variant-numeric: tabular-nums;
    color: var(--text-muted);
    font-size: 0.88rem;
  }
  .off input,
  .off .value {
    opacity: 0.45;
  }
</style>
