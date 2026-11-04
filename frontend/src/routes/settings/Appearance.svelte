<script lang="ts">
  import { ApiError, get, patch, type Theme, type UserSettings } from "../../lib/api";
  import { applyLanguage, saveSettings, session } from "../../lib/session.svelte";
  import { toast } from "../../lib/ui.svelte";
  import { LANGUAGES, msg, t, type Lang } from "../../lib/i18n.svelte";

  const THEMES: Record<Theme, string> = { system: msg("System"), dark: msg("Dunkel"), light: msg("Hell") };
  const isAdmin = $derived(session.user?.role === "admin");

  function save(changes: Partial<UserSettings>) {
    saveSettings(changes).catch((e) => toast(e instanceof ApiError ? e.message : t("Speichern fehlgeschlagen")));
  }

  // The server language (admins): what everyone sees who leaves theirs at "Wie der Server".
  let serverLanguage = $state<Lang | null>(null);
  $effect(() => {
    if (isAdmin) get<{ language: Lang }>("/admin/settings").then((s) => (serverLanguage = s.language));
  });

  async function saveServerLanguage(lang: Lang) {
    const before = serverLanguage;
    serverLanguage = lang;
    try {
      await patch("/admin/settings", { language: lang });
      session.settings = { ...session.settings, language_default: lang };
      applyLanguage(session.settings);
    } catch (e) {
      serverLanguage = before;
      toast(e instanceof ApiError ? e.message : t("Speichern fehlgeschlagen"));
    }
  }
  // The value while its slider is dragged; saved when it is let go.
  let motion = $state<number | null>(null);
  const shown = $derived(motion ?? session.settings.backdrop_motion);
  const label = $derived(shown === 0 ? t("Still") : shown < 35 ? t("Ruhig") : shown <= 65 ? t("Normal") : t("Lebhaft"));
</script>

<section class="set-group">
  <h2>{t("Sprache")}</h2>
  <div class="set-card">
    <div class="set-row">
      <div class="set-label">
        <strong>{t("Deine Sprache")}</strong>
        <small>{t("„Wie der Server“ folgt der Sprache, die der Admin für alle eingestellt hat (gerade: {lang}).", { lang: LANGUAGES[session.settings.language_default] })}</small>
      </div>
      <select aria-label={t("Deine Sprache")} value={session.settings.language} onchange={(e) => save({ language: e.currentTarget.value as UserSettings["language"] })}>
        <option value="server">{t("Wie der Server")}</option>
        {#each Object.entries(LANGUAGES) as [k, v] (k)}<option value={k}>{v}</option>{/each}
      </select>
    </div>
    {#if isAdmin && serverLanguage}
      <div class="set-row">
        <div class="set-label">
          <strong>{t("Sprache des Servers")}</strong>
          <small>{t("Für alle, die „Wie der Server“ eingestellt haben, und für Texte, die audium für Apps schreibt.")}</small>
        </div>
        <select aria-label={t("Sprache des Servers")} value={serverLanguage} onchange={(e) => saveServerLanguage(e.currentTarget.value as Lang)}>
          {#each Object.entries(LANGUAGES) as [k, v] (k)}<option value={k}>{v}</option>{/each}
        </select>
      </div>
    {/if}
  </div>
</section>

<section class="set-group">
  <h2>{t("Darstellung")}</h2>
  <div class="set-card">
    <div class="set-row">
      <div class="set-label"><strong>{t("Farbschema")}</strong><small>{t("„System“ folgt der Einstellung deines Geräts.")}</small></div>
      <div class="segmented" role="radiogroup" aria-label={t("Farbschema")}>
        {#each Object.entries(THEMES) as [k, v] (k)}
          <button role="radio" aria-checked={session.settings.theme === k} class:on={session.settings.theme === k} onclick={() => save({ theme: k as Theme })}>{t(v)}</button>
        {/each}
      </div>
    </div>
    <div class="set-row slider">
      <span class="set-label">
        <strong>{t("Hintergrund in „Läuft gerade“")}</strong>
        <small>{t("Wie lebhaft sich das verschwommene Cover hinter dem Player bewegt. Ganz links steht es still.")}</small>
      </span>
      <div class="control">
        <input
          type="range"
          min="0"
          max="100"
          step="5"
          value={shown}
          aria-label={t("Bewegung des Hintergrunds")}
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
