<script lang="ts">
  // Every way in and out of the server, each with a switch (server settings, backend
  // services/server_settings.py). ListenBrainz is the radio source "artists"; its switch here is
  // the same as under "Radio & Mixe". An AUDIUM_* variable that is off wins over the switch.
  import { ApiError, get, patch } from "../../lib/api";
  import { session } from "../../lib/session.svelte";
  import { toast } from "../../lib/ui.svelte";

  type Key = "subsonic_api" | "app_access" | "model_download";
  type ServerSettings = Record<Key, "on" | "off">;
  interface Env {
    subsonic_available: boolean;
    model_download_available: boolean;
    app_origins: string[];
  }
  interface Sources {
    sources: { artists: { on: boolean } };
    artists_known: number;
  }

  let server = $state<ServerSettings | null>(null);
  let env = $state<Env | null>(null);
  let radio = $state<Sources | null>(null);

  $effect(() => {
    get<ServerSettings>("/admin/settings").then((s) => (server = s));
    get<Env>("/admin/interfaces").then((e) => (env = e));
    get<Sources>("/admin/radio/sources").then((r) => (radio = r));
  });

  async function saveServer(key: Key, on: boolean) {
    const before = server;
    server = server && { ...server, [key]: on ? "on" : "off" };
    try {
      server = await patch<ServerSettings>("/admin/settings", { [key]: on ? "on" : "off" });
      if (key === "subsonic_api") session.settings = { ...session.settings, subsonic_api: server.subsonic_api };
    } catch (e) {
      server = before;
      toast(e instanceof ApiError ? e.message : "Speichern fehlgeschlagen");
    }
  }

  async function saveListenBrainz(on: boolean) {
    try {
      radio = await patch<Sources>("/admin/radio/sources", { artists: { on } });
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Speichern fehlgeschlagen");
    }
  }
</script>

{#if !server || !env || !radio}
  <p class="set-note">Lädt …</p>
{:else}
  <section class="set-group">
    <h2>Von außen</h2>
    <div class="set-card">
      <label class="set-row">
        <span class="set-label">
          <strong>Subsonic-API</strong>
          <small>
            Für Apps wie Symfonium, Amperfy oder Feishin, unter <code>/rest</code>. Sie melden sich mit App-Passwörtern an, die jeder Nutzer unter „Apps verbinden“ anlegt.
            {#if !env.subsonic_available}<br /><b>Abgeschaltet mit AUDIUM_SUBSONIC_ENABLED=false.</b>{/if}
          </small>
        </span>
        <input
          type="checkbox"
          class="toggle"
          disabled={!env.subsonic_available}
          checked={env.subsonic_available && server.subsonic_api === "on"}
          onchange={(e) => saveServer("subsonic_api", e.currentTarget.checked)}
        />
      </label>
      <label class="set-row">
        <span class="set-label">
          <strong>audium-Apps und API-Tokens</strong>
          <small>
            Die audium-Apps für Desktop und Handy, außerdem eigene Skripte mit einem API-Token. Aus: Sie werden abgewiesen, auch bereits angemeldete. Der Browser ist nicht betroffen.
            {#if !env.app_origins.length}<br /><b>Die Apps können sich nicht verbinden: AUDIUM_APP_ORIGINS ist leer.</b>{/if}
          </small>
        </span>
        <input type="checkbox" class="toggle" checked={server.app_access === "on"} onchange={(e) => saveServer("app_access", e.currentTarget.checked)} />
      </label>
    </div>
  </section>

  <section class="set-group">
    <h2>Nach außen</h2>
    <div class="set-card">
      <label class="set-row">
        <span class="set-label">
          <strong>ListenBrainz und MusicBrainz</strong>
          <small>
            Holt ähnliche Künstler für Radios und Mixe. Gesendet wird nur die MusicBrainz-ID oder der Name eines Künstlers, nichts über die Nutzer. Dasselbe wie die Quelle „Ähnliche Künstler“ unter „Radio & Mixe“.
            {#if radio.artists_known}Bisher für {radio.artists_known.toLocaleString("de-DE")} Künstler geholt.{/if}
          </small>
        </span>
        <input type="checkbox" class="toggle" checked={radio.sources.artists.on} onchange={(e) => saveListenBrainz(e.currentTarget.checked)} />
      </label>
      <label class="set-row">
        <span class="set-label">
          <strong>Modelle für die Audioanalyse laden</strong>
          <small>
            Lädt einmalig rund 20 MB von essentia.upf.edu für Stilrichtungen und Klang-Fingerabdruck. Aus: Ohne die Modelle erkennt die Analyse Tempo, Tonart und Energie, aber keine Stile und keinen Klang.
            {#if !env.model_download_available}<br /><b>Abgeschaltet mit AUDIUM_ANALYSIS_DOWNLOAD_MODELS=false.</b>{/if}
          </small>
        </span>
        <input
          type="checkbox"
          class="toggle"
          disabled={!env.model_download_available}
          checked={env.model_download_available && server.model_download === "on"}
          onchange={(e) => saveServer("model_download", e.currentTarget.checked)}
        />
      </label>
    </div>
    <p class="set-note">Sonst nimmt audium keine Verbindung nach außen auf: keine Telemetrie, keine Update-Prüfung. Cover und Künstlerbilder kommen nur aus den Musikordnern.</p>
  </section>
{/if}

<style>
  code {
    font-size: 0.85em;
  }
</style>
