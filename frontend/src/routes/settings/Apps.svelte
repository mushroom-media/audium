<script lang="ts">
  // Passwords for Subsonic apps (Symfonium, Amperfy, Feishin, ...). Each app gets its own, shown
  // once; the login password never leaves the browser. Guide: docs/apps.md.
  import { ApiError, del, get, post, serverUrl } from "../../lib/api";
  import Icon from "../../lib/components/Icon.svelte";
  import Modal from "../../lib/components/Modal.svelte";
  import { session } from "../../lib/session.svelte";
  import { toast } from "../../lib/ui.svelte";
  import { fmtDate } from "./common";
  import { t } from "../../lib/i18n.svelte";

  interface AppPassword {
    id: number;
    name: string;
    prefix: string;
    created_at: number;
    last_used_at: number | null;
    last_client: string | null;
  }

  let entries = $state<AppPassword[]>([]);
  let loaded = $state(false);
  let reload = $state(0);
  let naming = $state(false);
  let name = $state("");
  let created = $state<{ name: string; password: string } | null>(null);

  const server = serverUrl();
  const insecure = location.protocol === "http:" && !["localhost", "127.0.0.1"].includes(location.hostname);

  $effect(() => {
    void reload;
    get<AppPassword[]>("/auth/app-passwords").then((r) => {
      entries = r;
      loaded = true;
    });
  });

  async function create() {
    try {
      const r = await post<AppPassword & { password: string }>("/auth/app-passwords", { name });
      created = { name: r.name, password: r.password };
      naming = false;
      name = "";
      reload++;
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("Fehlgeschlagen"));
    }
  }

  async function revoke(e: AppPassword) {
    if (!confirm(t("„{name}“ widerrufen? Die App kann sich danach nicht mehr anmelden.", { name: e.name }))) return;
    try {
      await del(`/auth/app-passwords/${e.id}`);
      toast(t("Widerrufen"));
      reload++;
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("Fehlgeschlagen"));
    }
  }

  async function copy(text: string, what: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast(`${what} kopiert`);
    } catch {
      toast(t("Kopieren geht nur über HTTPS – bitte von Hand übernehmen"));
    }
  }
</script>

<p class="intro">
  {t("Mit einer Subsonic-App wie")} <strong>{t("Symfonium")}</strong> {t("(Android),")} <strong>{t("Amperfy")}</strong> {t("(iPhone) oder")} <strong>{t("Feishin")}</strong>
  {t("(Desktop) hörst du deine Bibliothek auch offline.")}
</p>

{#if session.settings.subsonic_api === "off"}
  <p class="intro warn">{t("Die Subsonic-API ist auf diesem Server gerade abgeschaltet. Verbundene Apps werden abgewiesen, bis ein Admin sie unter „Schnittstellen“ wieder einschaltet.")}</p>
{/if}

<div class="top-actions">
  <button class="btn primary" onclick={() => (naming = true)}><Icon name="plus" size={16} /> {t("App verbinden")}</button>
</div>

<section class="set-group">
  <h2>{t("Verbundene Apps")}</h2>
  <div class="set-card">
    {#each entries as e (e.id)}
      <div class="set-row">
        <div class="set-label">
          <strong>{e.name} <span class="set-mono prefix">{e.prefix}…</span></strong>
          <small>
            {t("angelegt {date}", { date: fmtDate(e.created_at) })} ·
            {#if e.last_used_at}{e.last_client ? t("zuletzt benutzt {date} von {client}", { date: fmtDate(e.last_used_at), client: e.last_client }) : t("zuletzt benutzt {date}", { date: fmtDate(e.last_used_at) })}{:else}{t("noch nie benutzt")}{/if}
          </small>
        </div>
        <button class="btn small ghost" onclick={() => revoke(e)}>{t("Widerrufen")}</button>
      </div>
    {:else}
      <div class="set-row">
        <div class="set-label"><small>{loaded ? t("Noch keine App verbunden.") : t("Lädt …")}</small></div>
      </div>
    {/each}
  </div>
  <p class="set-note">{t("Jede App mit Subsonic-Unterstützung funktioniert.")}</p>
</section>

{#if naming}
  <Modal title={t("App verbinden")} onclose={() => (naming = false)}>
    <form class="form" onsubmit={(ev) => (ev.preventDefault(), create())}>
      <label>
        {t("Name")}
        <input bind:value={name} required maxlength="64" placeholder={t("z. B. Symfonium Handy")} />
      </label>
      <p class="hint">{t("Damit du später erkennst, welches Gerät welches Passwort hat.")}</p>
      <div class="modal-buttons">
        <button type="button" class="btn ghost" onclick={() => (naming = false)}>{t("Abbrechen")}</button>
        <button class="btn primary">{t("Passwort erzeugen")}</button>
      </div>
    </form>
  </Modal>
{/if}

{#if created}
  <Modal title={t("„{name}“ verbinden", { name: created.name })} onclose={() => (created = null)}>
    <p class="hint">{t("Trage diese Daten in der App ein. Das Passwort wird")} <strong>{t("nur jetzt")}</strong> {t("angezeigt.")}</p>
    <dl class="creds">
      <dt>{t("Server")}</dt>
      <dd><code>{server}</code><button class="btn small ghost" onclick={() => copy(server, "Server")}>{t("Kopieren")}</button></dd>
      <dt>{t("Benutzername")}</dt>
      <dd><code>{session.user?.username}</code><button class="btn small ghost" onclick={() => copy(session.user?.username ?? "", "Benutzername")}>{t("Kopieren")}</button></dd>
      <dt>{t("Passwort")}</dt>
      <dd><code class="pw">{created.password}</code><button class="btn small ghost" onclick={() => copy(created!.password, "Passwort")}>{t("Kopieren")}</button></dd>
    </dl>
    {#if insecure}
      <p class="hint warn">{t("Die Verbindung ist unverschlüsselt (http). Für Apps außerhalb des Heimnetzes einen Reverse Proxy mit HTTPS verwenden.")}</p>
    {/if}
    <p class="hint">{t("In der App „Legacy-Anmeldung“ bzw. „Klartext-Passwort“ ausgeschaltet lassen.")}</p>
    <div class="modal-buttons">
      <button class="btn primary" onclick={() => (created = null)}>{t("Fertig")}</button>
    </div>
  </Modal>
{/if}

<style>
  .intro {
    margin: 0 4px 16px;
    color: var(--text-muted);
    font-size: 0.9rem;
    line-height: 1.5;
  }
  .top-actions,
  .modal-buttons {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    align-items: center;
  }
  .top-actions {
    margin: 0 0 20px;
  }
  .modal-buttons {
    justify-content: flex-end;
    margin-top: 8px;
  }
  .prefix {
    color: var(--text-faint);
    font-weight: 400;
    margin-left: 4px;
  }
  .form {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .form label {
    display: flex;
    flex-direction: column;
    gap: 6px;
    color: var(--text-muted);
    font-size: 0.88rem;
  }
  .hint {
    margin: 0 0 12px;
    color: var(--text-muted);
    font-size: 0.86rem;
    line-height: 1.45;
  }
  .hint.warn,
  .intro.warn {
    color: var(--danger);
  }
  .creds {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    gap: 10px 14px;
    align-items: center;
    margin: 0 0 16px;
  }
  .creds dt {
    color: var(--text-muted);
    font-size: 0.85rem;
  }
  .creds dd {
    margin: 0;
    display: flex;
    gap: 8px;
    align-items: center;
    min-width: 0;
  }
  .creds code {
    flex: 1;
    min-width: 0;
    font-family: ui-monospace, monospace;
    font-size: 0.86rem;
    background: var(--surface-1);
    padding: 6px 8px;
    border-radius: 8px;
    word-break: break-all;
  }
  .creds code.pw {
    font-size: 0.95rem;
    letter-spacing: 0.02em;
  }
  @media (max-width: 520px) {
    .creds {
      grid-template-columns: minmax(0, 1fr);
      gap: 4px;
    }
    .creds dd {
      margin-bottom: 8px;
    }
  }
</style>
