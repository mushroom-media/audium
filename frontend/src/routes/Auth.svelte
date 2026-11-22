<script lang="ts">
  import { ApiError, currentConnection, get, isApp, patch, post } from "../lib/api";
  import { navigate } from "../lib/router.svelte";
  import { loadSession, login, session } from "../lib/session.svelte";
  import { LANGUAGES, i18n, setLanguage, t, type Lang } from "../lib/i18n.svelte";

  let { mode, token = "" }: { mode: "login" | "setup" | "invite"; token?: string } = $props();

  // Apps only: which server to log in to (remembered from the last time).
  let server = $state(currentConnection()?.server ?? "");
  let username = $state("");
  let password = $state("");
  let password2 = $state("");
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
      if (e.status === 429) return t("Zu viele Versuche. Bitte in {s} Sekunden erneut versuchen.", { s: e.retryAfter ?? 60 });
      if (e.status === 401) return t("Benutzername oder Passwort falsch.");
      if (e.status === 409) return t("Dieser Benutzername ist schon vergeben.");
      return e.message; // includes "server not reachable" / "not an audium server" of the apps
    }
    if (isApp) return t("Keine Verbindung zum Server. Stimmt die Adresse, und ist der Server erreichbar?");
    return t("Keine Verbindung zum Server.");
  }

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    error = null;
    if (mode !== "login" && password !== password2) {
      error = t("Die Passwörter stimmen nicht überein.");
      return;
    }
    busy = true;
    try {
      if (mode === "login") {
        await login(username, password, server);
      } else if (mode === "setup") {
        await post("/setup", { username, password });
        // The language chosen on this page becomes the server language (the wizard can change it).
        await patch("/admin/settings", { language: i18n.lang }).catch(() => {});
        await loadSession();
        navigate("/setup", { replace: true });
        return;
      } else {
        await post("/auth/register", { invite_token: token, username, password });
        await loadSession();
      }
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 403 && mode === "setup") session.setupWindowOpen = false;
      error = message(err);
    } finally {
      busy = false;
    }
  }

  const minPassword = $derived(mode === "setup" ? 8 : mode === "invite" ? 3 : 1);
</script>

<main class="auth">
  {#if mode === "setup" && !session.setupWindowOpen}
  <div class="card">
    <h1>{t("Einrichtung gesperrt")}</h1>
    <p class="hint">
      {t("Das Admin-Konto lässt sich nur in den ersten 30 Minuten nach dem Start anlegen, damit niemand anderes dir zuvorkommt. Starte den Container neu, dann hast du wieder 30 Minuten. Das geht auch in Portainer, Unraid oder Synology.")}
    </p>
    <button class="btn primary wide" onclick={() => loadSession()}>{t("Erneut prüfen")}</button>
  </div>
  {:else}
  <form class="card" onsubmit={submit}>
    <div class="brand">
      <svg aria-hidden="true" viewBox="0 0 64 64" width="44" height="44"><g fill="currentColor"><rect x="14" y="26" width="6" height="12" rx="3" /><rect x="24" y="18" width="6" height="28" rx="3" /><rect x="34" y="12" width="6" height="40" rx="3" /><rect x="44" y="22" width="6" height="20" rx="3" /></g></svg>
      <!-- Only for this page: the language after logging in is the user's or the server's. -->
      <select class="lang" aria-label="Sprache / Language" value={i18n.lang} onchange={(e) => setLanguage(e.currentTarget.value as Lang)}>
        {#each Object.entries(LANGUAGES) as [key, name] (key)}<option value={key}>{name}</option>{/each}
      </select>
    </div>
    {#if mode === "login"}
      <h1>{t("Anmelden")}</h1>
    {:else if mode === "setup"}
      <h1>{t("Willkommen bei audium")}</h1>
      <p class="hint">{t("Lege zuerst dein Admin-Konto an. Danach hilft dir audium, deine Musik einzubinden.")}</p>
    {:else}
      <h1>{t("Konto erstellen")}</h1>
      {#if inviteValid === false}<p class="error">{t("Diese Einladung ist ungültig oder abgelaufen.")}</p>{/if}
    {/if}

    {#if isApp && mode === "login"}
      <label>
        {t("Server")}
        <input bind:value={server} required placeholder={t("z. B. {example}", { example: "192.168.1.5:8091" })} inputmode="url" autocomplete="url" autocapitalize="none" spellcheck="false" />
      </label>
    {/if}
    <label>{t("Benutzername")}<input bind:value={username} required autocomplete="username" autocapitalize="none" spellcheck="false" /></label>
    <label>
      {t("Passwort")}
      <input type="password" bind:value={password} required minlength={minPassword} autocomplete={mode === "login" ? "current-password" : "new-password"} />
    </label>
    {#if mode !== "login"}
      <label>{t("Passwort wiederholen")}<input type="password" bind:value={password2} required minlength={minPassword} autocomplete="new-password" /></label>
    {/if}
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    <button class="btn primary wide" disabled={busy || (mode === "invite" && inviteValid === false)}>
      {mode === "login" ? t("Anmelden") : t("Konto erstellen")}
    </button>
  </form>
  {/if}
</main>

<style>
  .auth {
    min-height: calc(100dvh - var(--frame-top, 0px));
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
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
  }
  .brand .lang {
    width: auto;
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
