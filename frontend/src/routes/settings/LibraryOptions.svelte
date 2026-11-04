<script lang="ts">
  // How the library looks for you (your account, on every device); below, for admins, what
  // applies to everyone on this server. The folders themselves are under "Musikordner".
  import { ApiError, get, patch, type UserSettings } from "../../lib/api";
  import { saveSettings, session } from "../../lib/session.svelte";
  import { toast } from "../../lib/ui.svelte";
  import { msg, t } from "../../lib/i18n.svelte";

  const TABS: Record<UserSettings["library_tab"], string> = { last: msg("Zuletzt geöffnet"), tracks: msg("Titel"), albums: msg("Alben"), artists: msg("Künstler") };
  const TRACK_SORTS: Record<UserSettings["track_sort"], string> = { title: msg("Titel|Sortierung"), added: msg("Neu hinzugefügt"), year: msg("Jahr") };
  const ALBUM_SORTS: Record<UserSettings["album_sort"], string> = { title: msg("Titel|Sortierung"), artist: msg("Künstler|Sortierung"), year: msg("Jahr"), added: msg("Neu hinzugefügt") };
  const ROLES: Record<UserSettings["artist_role"], string> = { album: msg("Nur Album-Künstler"), all: msg("Alle Künstler") };
  const onOff = (v: "on" | "off") => (v === "on" ? "Album-Cover" : "Platzhalter");
  const IMAGES = $derived<Record<UserSettings["artist_images"], string>>({
    server: `Server-Standard (${onOff(session.settings.artist_images_default)})`,
    on: "Album-Cover",
    off: "Platzhalter",
  });

  function save(changes: Partial<UserSettings>) {
    saveSettings(changes).catch((e) => toast(e instanceof ApiError ? e.message : t("Speichern fehlgeschlagen")));
  }

  // --- for everyone (admins) -----------------------------------------------------------------

  interface ServerSettings {
    artist_album_covers: "on" | "off";
    artist_folder_images: "on" | "off";
  }
  const isAdmin = $derived(session.user?.role === "admin");
  let server = $state<ServerSettings | null>(null);

  $effect(() => {
    if (isAdmin) get<ServerSettings>("/admin/settings").then((s) => (server = s));
  });

  async function saveServer(changes: Partial<ServerSettings>) {
    const before = server;
    server = server && { ...server, ...changes };
    try {
      server = await patch<ServerSettings>("/admin/settings", changes);
      session.settings = { ...session.settings, artist_images_default: server.artist_album_covers };
    } catch (e) {
      server = before;
      toast(e instanceof ApiError ? e.message : t("Speichern fehlgeschlagen"));
    }
  }
</script>

<section class="set-group">
  <h2>{t("Ansicht")}</h2>
  <div class="set-card">
    <div class="set-row">
      <div class="set-label"><strong>{t("Start-Tab")}</strong><small>{t("Womit die Bibliothek öffnet.")}</small></div>
      <select aria-label={t("Start-Tab")} value={session.settings.library_tab} onchange={(e) => save({ library_tab: e.currentTarget.value as UserSettings["library_tab"] })}>
        {#each Object.entries(TABS) as [k, v] (k)}<option value={k}>{t(v)}</option>{/each}
      </select>
    </div>
    <div class="set-row">
      <div class="set-label"><strong>{t("Titel sortieren nach")}</strong></div>
      <select aria-label={t("Titel sortieren nach")} value={session.settings.track_sort} onchange={(e) => save({ track_sort: e.currentTarget.value as UserSettings["track_sort"] })}>
        {#each Object.entries(TRACK_SORTS) as [k, v] (k)}<option value={k}>{t(v)}</option>{/each}
      </select>
    </div>
    <div class="set-row">
      <div class="set-label"><strong>{t("Alben sortieren nach")}</strong></div>
      <select aria-label={t("Alben sortieren nach")} value={session.settings.album_sort} onchange={(e) => save({ album_sort: e.currentTarget.value as UserSettings["album_sort"] })}>
        {#each Object.entries(ALBUM_SORTS) as [k, v] (k)}<option value={k}>{t(v)}</option>{/each}
      </select>
    </div>
    <div class="set-row">
      <div class="set-label"><strong>{t("Künstler-Liste")}</strong><small>{t("„Nur Album-Künstler“ lässt Gastauftritte auf fremden Alben weg.")}</small></div>
      <select aria-label={t("Künstler-Liste")} value={session.settings.artist_role} onchange={(e) => save({ artist_role: e.currentTarget.value as UserSettings["artist_role"] })}>
        {#each Object.entries(ROLES) as [k, v] (k)}<option value={k}>{t(v)}</option>{/each}
      </select>
    </div>
  </div>
</section>

<section class="set-group">
  <h2>{t("Künstlerbilder")}</h2>
  <div class="set-card">
    <div class="set-row">
      <div class="set-label">
        <strong>{t("Künstler ohne eigenes Bild")}</strong>
      </div>
      <select aria-label={t("Künstler ohne eigenes Bild")} value={session.settings.artist_images} onchange={(e) => save({ artist_images: e.currentTarget.value as UserSettings["artist_images"] })}>
        {#each Object.entries(IMAGES) as [k, v] (k)}<option value={k}>{t(v)}</option>{/each}
      </select>
    </div>
  </div>
</section>

{#if isAdmin}
  <section class="set-group">
    <h2>{t("Für alle Nutzer (Admin)")}</h2>
    {#if server === null}
      <p class="set-note">{t("Lädt …")}</p>
    {:else}
      <div class="set-card">
        <label class="set-row">
          <span class="set-label">
            <strong>{t("Album-Cover als Künstlerbild")}</strong>
          </span>
          <input type="checkbox" class="toggle" checked={server.artist_album_covers === "on"} onchange={(e) => saveServer({ artist_album_covers: e.currentTarget.checked ? "on" : "off" })} />
        </label>
        <label class="set-row">
          <span class="set-label">
            <strong>{t("folder.jpg als Künstlerbild")}</strong>
            <small>{t("Ohne artist.jpg zählt eine folder.jpg im Künstlerordner (Künstler/folder.jpg neben Künstler/Album/) als eigenes Bild. In Albumordnern bleibt sie das Cover. Ändern startet einen Scan.")}</small>
          </span>
          <input type="checkbox" class="toggle" checked={server.artist_folder_images === "on"} onchange={(e) => saveServer({ artist_folder_images: e.currentTarget.checked ? "on" : "off" })} />
        </label>
      </div>
      <p class="set-note">{t("Musikordner, Scan und Audioanalyse stehen unter „Server“.")}</p>
    {/if}
  </section>
{/if}
