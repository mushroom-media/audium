<script lang="ts">
  // Reset to factory settings (backend services/reset.py). Afterwards everyone is logged out and
  // the first-run dialog opens again, as on a new installation.
  import Modal from "../../lib/components/Modal.svelte";
  import Icon from "../../lib/components/Icon.svelte";
  import { ApiError, forgetToken, get, isApp, post } from "../../lib/api";
  import { navigate } from "../../lib/router.svelte";
  import { loadSession, session } from "../../lib/session.svelte";

  let adminFromEnv = $state<boolean | null>(null);
  let confirming = $state(false);
  let keepUsers = $state(true);
  let password = $state("");
  let error = $state("");
  let busy = $state(false);

  $effect(() => {
    get<{ admin_from_env: boolean }>("/admin/setup").then((i) => (adminFromEnv = i.admin_from_env));
  });

  function open() {
    keepUsers = true;
    password = "";
    error = "";
    confirming = true;
  }

  async function reset() {
    busy = true;
    error = "";
    try {
      await post("/admin/setup/reset", { password, keep_users: keepUsers });
    } catch (e) {
      error = e instanceof ApiError ? e.message : "Zurücksetzen fehlgeschlagen";
      busy = false;
      return;
    }
    if (isApp) forgetToken();
    session.user = null;
    confirming = false;
    await loadSession().catch(() => {});
    navigate("/", { replace: true });
  }
</script>

<section class="set-group">
  <div class="set-card">
    <div class="set-row">
      <div class="set-label">
        <strong>Server auf Werkseinstellungen zurücksetzen</strong>
        <small>
          Löscht Bibliothek, Audioanalyse, Playlists, Favoriten, Verlauf, Auto-Playlists und alle Server-Einstellungen. Danach sind alle abgemeldet und die Einrichtung beginnt von vorn. Die Musikdateien selbst bleiben unangetastet.
        </small>
      </div>
      <button class="btn danger" onclick={open}><Icon name="trash" size={16} /> Zurücksetzen …</button>
    </div>
  </div>
  <p class="set-note">Der nächste Scan liest die Musikordner neu ein, die Analyse läuft danach noch einmal komplett.</p>
</section>

{#if confirming}
  <Modal title="Server zurücksetzen?" onclose={() => !busy && (confirming = false)} width={480}>
    <form class="form" onsubmit={(e) => (e.preventDefault(), reset())}>
      <fieldset class="choice">
        <legend>Nutzerkonten</legend>
        <label class="option">
          <input type="radio" name="users" checked={keepUsers} onchange={() => (keepUsers = true)} />
          <span>
            <strong>Behalten</strong>
            <small>Konten mit ihren Passwörtern, persönlichen Einstellungen und App-Passwörtern bleiben. Alle müssen sich neu anmelden.</small>
          </span>
        </label>
        <label class="option">
          <input type="radio" name="users" checked={!keepUsers} onchange={() => (keepUsers = false)} />
          <span>
            <strong>Auch löschen</strong>
            <small>
              {#if adminFromEnv}
                Es bleibt nur der Admin aus <code>AUDIUM_ADMIN_USER</code>. Mit ihm meldest du dich danach an.
              {:else}
                Alle Konten werden gelöscht, deines auch. Danach legst du ein neues Admin-Konto an, innerhalb von 30 Minuten.
              {/if}
            </small>
          </span>
        </label>
      </fieldset>
      <label>
        Dein Passwort zur Bestätigung
        <input type="password" bind:value={password} required autocomplete="current-password" />
      </label>
      {#if error}<p class="set-warn">{error}</p>{/if}
      <p class="set-note warn-note">Das lässt sich nicht rückgängig machen.</p>
      <div class="modal-buttons">
        <button type="button" class="btn ghost" disabled={busy} onclick={() => (confirming = false)}>Abbrechen</button>
        <button class="btn danger solid" disabled={busy || !password}>{busy ? "Wird zurückgesetzt …" : "Jetzt zurücksetzen"}</button>
      </div>
    </form>
  </Modal>
{/if}

<style>
  .btn.danger {
    color: var(--danger);
    flex: none;
  }
  .btn.danger.solid {
    background: var(--danger);
    border-color: var(--danger);
    color: #fff;
  }
  .form {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .form > label {
    display: flex;
    flex-direction: column;
    gap: 6px;
    color: var(--text-muted);
    font-size: 0.88rem;
  }
  .choice {
    border: 0;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .choice legend {
    color: var(--text-muted);
    font-size: 0.88rem;
    margin-bottom: 6px;
  }
  .option {
    display: flex;
    gap: 10px;
    align-items: flex-start;
    padding: 10px 12px;
    border-radius: 12px;
    background: var(--surface-1);
    cursor: pointer;
  }
  .option input {
    margin-top: 3px;
  }
  .option strong {
    display: block;
    font-weight: 550;
  }
  .option small {
    display: block;
    color: var(--text-muted);
    font-size: 0.84rem;
    line-height: 1.45;
    margin-top: 2px;
  }
  .set-warn {
    margin: 0;
    font-size: 0.88rem;
  }
  .warn-note {
    margin: 0;
  }
  .modal-buttons {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
    flex-wrap: wrap;
  }
</style>
