<script lang="ts">
  // Passwords for Subsonic apps (Symfonium, Amperfy, Feishin, ...). Each app gets its own, shown
  // once; the login password never leaves the browser. Guide: docs/apps.md.
  import { ApiError, del, get, post, serverUrl } from "../../lib/api";
  import Icon from "../../lib/components/Icon.svelte";
  import Modal from "../../lib/components/Modal.svelte";
  import { session } from "../../lib/session.svelte";
  import { toast } from "../../lib/ui.svelte";
  import { fmtDate } from "./common";

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
      toast(e instanceof ApiError ? e.message : "Fehlgeschlagen");
    }
  }

  async function revoke(e: AppPassword) {
    if (!confirm(`„${e.name}“ widerrufen? Die App kann sich danach nicht mehr anmelden.`)) return;
    try {
      await del(`/auth/app-passwords/${e.id}`);
      toast("Widerrufen");
      reload++;
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Fehlgeschlagen");
    }
  }

  async function copy(text: string, what: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast(`${what} kopiert`);
    } catch {
      toast("Kopieren geht nur über HTTPS – bitte von Hand übernehmen");
    }
  }
</script>

<p class="intro">
  Mit einer Subsonic-App wie <strong>Symfonium</strong> (Android), <strong>Amperfy</strong> (iPhone) oder <strong>Feishin</strong>
  (Desktop) hörst du deine Bibliothek auch offline, im Auto (CarPlay, Android Auto) und mit Sperrbildschirm-Steuerung. Lege für
  jede App ein eigenes Passwort an. Dein Login-Passwort funktioniert in Apps nicht, damit es nie in einer fremden App gespeichert wird.
</p>

<div class="top-actions">
  <button class="btn primary" onclick={() => (naming = true)}><Icon name="plus" size={16} /> App verbinden</button>
</div>

<section class="set-group">
  <h2>Verbundene Apps</h2>
  <div class="set-card">
    {#each entries as e (e.id)}
      <div class="set-row">
        <div class="set-label">
          <strong>{e.name} <span class="set-mono prefix">{e.prefix}…</span></strong>
          <small>
            angelegt {fmtDate(e.created_at)} ·
            {#if e.last_used_at}zuletzt benutzt {fmtDate(e.last_used_at)}{e.last_client ? ` von ${e.last_client}` : ""}{:else}noch nie benutzt{/if}
          </small>
        </div>
        <button class="btn small ghost" onclick={() => revoke(e)}>Widerrufen</button>
      </div>
    {:else}
      <div class="set-row">
        <div class="set-label"><small>{loaded ? "Noch keine App verbunden." : "Lädt …"}</small></div>
      </div>
    {/each}
  </div>
  <p class="set-note">
    Jede App mit Subsonic-Unterstützung funktioniert, Anleitungen für einige stehen in <span class="set-mono">docs/apps.md</span>. Smart
    Playlists anlegen, Discover und den Rule-Editor gibt es nur hier im Browser.
  </p>
</section>

{#if naming}
  <Modal title="App verbinden" onclose={() => (naming = false)}>
    <form class="form" onsubmit={(ev) => (ev.preventDefault(), create())}>
      <label>
        Name
        <input bind:value={name} required maxlength="64" placeholder="z. B. Symfonium Handy" />
      </label>
      <p class="hint">Damit du später erkennst, welches Gerät welches Passwort hat.</p>
      <div class="modal-buttons">
        <button type="button" class="btn ghost" onclick={() => (naming = false)}>Abbrechen</button>
        <button class="btn primary">Passwort erzeugen</button>
      </div>
    </form>
  </Modal>
{/if}

{#if created}
  <Modal title="„{created.name}“ verbinden" onclose={() => (created = null)}>
    <p class="hint">Trage diese Daten in der App ein. Das Passwort wird <strong>nur jetzt</strong> angezeigt.</p>
    <dl class="creds">
      <dt>Server</dt>
      <dd><code>{server}</code><button class="btn small ghost" onclick={() => copy(server, "Server")}>Kopieren</button></dd>
      <dt>Benutzername</dt>
      <dd><code>{session.user?.username}</code><button class="btn small ghost" onclick={() => copy(session.user?.username ?? "", "Benutzername")}>Kopieren</button></dd>
      <dt>Passwort</dt>
      <dd><code class="pw">{created.password}</code><button class="btn small ghost" onclick={() => copy(created!.password, "Passwort")}>Kopieren</button></dd>
    </dl>
    {#if insecure}
      <p class="hint warn">Die Verbindung ist unverschlüsselt (http). Für Apps außerhalb des Heimnetzes einen Reverse Proxy mit HTTPS verwenden.</p>
    {/if}
    <p class="hint">In der App „Legacy-Anmeldung“ bzw. „Klartext-Passwort“ ausgeschaltet lassen.</p>
    <div class="modal-buttons">
      <button class="btn primary" onclick={() => (created = null)}>Fertig</button>
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
  .hint.warn {
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
