<script lang="ts">
  import { ApiError, get, post } from "../lib/api";
  import { navigate } from "../lib/router.svelte";
  import { loadSession, login } from "../lib/session.svelte";

  let { mode, token = "" }: { mode: "login" | "setup" | "invite"; token?: string } = $props();

  let username = $state("");
  let password = $state("");
  let password2 = $state("");
  let setupToken = $state("");
  let busy = $state(false);
  let error = $state<string | null>(null);
  let inviteValid = $state<boolean | null>(null);

  $effect(() => {
    if (mode === "invite" && token) {
      get(`/invites/${encodeURIComponent(token)}`)
        .then(() => (inviteValid = true))
        .catch(() => (inviteValid = false));
    }
  });

  function message(e: unknown): string {
    if (e instanceof ApiError) {
      if (e.status === 429) return `Zu viele Versuche. Bitte in ${e.retryAfter ?? 60} Sekunden erneut versuchen.`;
      if (e.status === 401) return "Benutzername oder Passwort falsch.";
      if (e.status === 403 && mode === "setup") return "Das Setup-Token stimmt nicht.";
      if (e.status === 409) return "Dieser Benutzername ist schon vergeben.";
      return e.message;
    }
    return "Keine Verbindung zum Server.";
  }

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    error = null;
    if (mode !== "login" && password !== password2) {
      error = "Die Passwörter stimmen nicht überein.";
      return;
    }
    busy = true;
    try {
      if (mode === "login") {
        await login(username, password);
      } else if (mode === "setup") {
        await post("/setup", { setup_token: setupToken, username, password });
        await loadSession();
      } else {
        await post("/auth/register", { invite_token: token, username, password });
        await loadSession();
      }
      navigate("/", { replace: true });
    } catch (err) {
      error = message(err);
    } finally {
      busy = false;
    }
  }
</script>

<main class="auth">
  <form class="card" onsubmit={submit}>
    <div class="brand" aria-hidden="true">
      <svg viewBox="0 0 64 64" width="44" height="44"><g fill="currentColor"><rect x="14" y="26" width="6" height="12" rx="3" /><rect x="24" y="18" width="6" height="28" rx="3" /><rect x="34" y="12" width="6" height="40" rx="3" /><rect x="44" y="22" width="6" height="20" rx="3" /></g></svg>
    </div>
    {#if mode === "login"}
      <h1>Anmelden</h1>
    {:else if mode === "setup"}
      <h1>Willkommen bei audium</h1>
      <p class="hint">
        Lege das Admin-Konto an. Das Setup-Token steht im Log des Containers:
        <code>docker compose logs audium | grep setup_token</code>
      </p>
      <label>Setup-Token<input bind:value={setupToken} required autocomplete="off" spellcheck="false" /></label>
    {:else}
      <h1>Konto erstellen</h1>
      {#if inviteValid === false}<p class="error">Diese Einladung ist ungültig oder abgelaufen.</p>{/if}
    {/if}

    <label>Benutzername<input bind:value={username} required autocomplete="username" autocapitalize="none" spellcheck="false" /></label>
    <label>
      Passwort
      <input type="password" bind:value={password} required minlength={mode === "login" ? 1 : 8} autocomplete={mode === "login" ? "current-password" : "new-password"} />
    </label>
    {#if mode !== "login"}
      <label>Passwort wiederholen<input type="password" bind:value={password2} required minlength="8" autocomplete="new-password" /></label>
    {/if}
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    <button class="btn primary wide" disabled={busy || (mode === "invite" && inviteValid === false)}>
      {mode === "login" ? "Anmelden" : "Konto erstellen"}
    </button>
  </form>
</main>

<style>
  .auth {
    min-height: 100dvh;
    display: grid;
    place-items: center;
    padding: 24px 16px;
  }
  .card {
    width: min(380px, 100%);
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .brand {
    color: var(--text);
  }
  h1 {
    font-size: 1.6rem;
    margin: 4px 0 4px;
    letter-spacing: -0.01em;
  }
  .hint {
    color: var(--text-muted);
    font-size: 0.9rem;
    margin: 0;
    line-height: 1.5;
  }
  code {
    display: block;
    margin-top: 6px;
    font-size: 0.8rem;
    background: var(--surface-1);
    padding: 6px 8px;
    border-radius: 6px;
    overflow-x: auto;
    white-space: nowrap;
  }
  label {
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: 0.88rem;
    color: var(--text-muted);
  }
  .error {
    color: var(--danger);
    margin: 0;
    font-size: 0.9rem;
  }
  .wide {
    width: 100%;
    justify-content: center;
    margin-top: 6px;
  }
</style>
