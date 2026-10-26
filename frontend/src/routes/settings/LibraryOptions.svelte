<script lang="ts">
  // How the library is shown, for everyone on this server (the folders are under "Musikordner").
  import { ApiError, get, patch } from "../../lib/api";
  import { toast } from "../../lib/ui.svelte";

  interface ServerSettings {
    artist_album_covers: "on" | "off";
  }

  let settings = $state<ServerSettings | null>(null);

  $effect(() => {
    get<ServerSettings>("/admin/settings").then((s) => (settings = s));
  });

  async function save(changes: Partial<ServerSettings>) {
    const before = settings;
    settings = settings && { ...settings, ...changes };
    try {
      settings = await patch<ServerSettings>("/admin/settings", changes);
    } catch (e) {
      settings = before;
      toast(e instanceof ApiError ? e.message : "Speichern fehlgeschlagen");
    }
  }
</script>

{#if settings === null}
  <p class="set-note">Lädt …</p>
{:else}
  <section class="set-group">
    <h2>Künstler</h2>
    <div class="set-card">
      <label class="set-row">
        <span class="set-label">
          <strong>Album-Cover als Künstlerbild</strong>
          <small>Künstler ohne eigenes Bild (artist.jpg im Ordner) zeigen das Cover ihres neuesten Albums. Aus: nur ein Platzhalter.</small>
        </span>
        <input type="checkbox" checked={settings.artist_album_covers === "on"} onchange={(e) => save({ artist_album_covers: e.currentTarget.checked ? "on" : "off" })} />
      </label>
    </div>
  </section>
  <p class="set-note">Gilt für alle Nutzer dieses Servers.</p>
{/if}
