<script lang="ts">
  import { ApiError, patch, post, type User } from "../../lib/api";
  import { AVATAR_COLORS, avatarInitial, avatarStyle } from "../../lib/avatar";
  import Icon from "../../lib/components/Icon.svelte";
  import { navigate } from "../../lib/router.svelte";
  import { logout, session } from "../../lib/session.svelte";
  import { toast } from "../../lib/ui.svelte";
  import { t } from "../../lib/i18n.svelte";

  async function doLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  const fail = (e: unknown) => toast(e instanceof ApiError ? e.message : t("Speichern fehlgeschlagen"));

  async function saveProfile(changes: { display_name?: string; username?: string; avatar_color?: string }, done?: string) {
    try {
      session.user = await patch<User>("/auth/me", changes);
      if (done) toast(done);
      return true;
    } catch (e) {
      fail(e);
      return false;
    }
  }

  let displayName = $state(session.user?.display_name ?? "");
  let username = $state(session.user?.username ?? "");
  const nameChanged = $derived(displayName.trim() !== "" && displayName.trim() !== session.user?.display_name);
  const usernameChanged = $derived(username.trim() !== "" && username.trim().toLowerCase() !== session.user?.username);

  async function saveDisplayName(e: Event) {
    e.preventDefault();
    if (nameChanged && (await saveProfile({ display_name: displayName }, t("Anzeigename gespeichert")))) displayName = session.user!.display_name;
  }

  async function saveUsername(e: Event) {
    e.preventDefault();
    if (usernameChanged && (await saveProfile({ username }, t("Benutzername geändert")))) username = session.user!.username;
  }

  // The color shows at once and goes back if the server refuses.
  let pickedColor = $state<string | null>(null);
  const color = $derived(pickedColor ?? session.user?.avatar_color ?? "");
  async function pickColor(c: string) {
    pickedColor = c;
    await saveProfile({ avatar_color: c });
    pickedColor = null;
  }

  let currentPw = $state("");
  let newPw = $state("");
  let repeatPw = $state("");
  let pwBusy = $state(false);
  const pwMismatch = $derived(repeatPw !== "" && newPw !== repeatPw);

  async function changePassword(e: Event) {
    e.preventDefault();
    if (newPw !== repeatPw) return;
    pwBusy = true;
    try {
      await post("/auth/me/password", { current_password: currentPw, new_password: newPw });
      currentPw = newPw = repeatPw = "";
      toast(t("Passwort geändert – andere Geräte sind abgemeldet"));
    } catch (e) {
      fail(e);
    } finally {
      pwBusy = false;
    }
  }
</script>

<section class="set-group">
  <h2>{t("Profil")}</h2>
  <div class="set-card">
    <div class="set-row profile">
      <span class="avatar" style={avatarStyle(color)} aria-hidden="true">{avatarInitial(session.user?.display_name)}</span>
      <div class="set-label">
        <strong>{session.user?.display_name}</strong>
        <small>@{session.user?.username}{session.user?.role === "admin" ? " · Admin" : ""}</small>
      </div>
    </div>
    <div class="set-row">
      <div class="set-label">
        <strong>{t("Farbe des Profilbilds")}</strong>
        <small>{t("Der Hintergrund hinter deinem Anfangsbuchstaben.")}</small>
      </div>
      <div class="swatches" role="radiogroup" aria-label={t("Farbe des Profilbilds")}>
        <button class="swatch accent" role="radio" aria-checked={color === ""} class:on={color === ""} title={t("Akzentfarbe")} aria-label={t("Akzentfarbe")} onclick={() => pickColor("")}></button>
        {#each Object.keys(AVATAR_COLORS) as c (c)}
          <button class="swatch" role="radio" aria-checked={color === c} class:on={color === c} style={avatarStyle(c)} aria-label={c} onclick={() => pickColor(c)}></button>
        {/each}
      </div>
    </div>
    <form class="set-row" onsubmit={saveDisplayName}>
      <label class="set-label" for="display-name">
        <strong>{t("Anzeigename")}</strong>
        <small>{t("So sehen dich andere, z. B. bei geteilten Playlists.")}</small>
      </label>
      <div class="field">
        <input id="display-name" bind:value={displayName} maxlength="64" autocomplete="name" />
        <button class="btn" disabled={!nameChanged}>{t("Speichern")}</button>
      </div>
    </form>
    <form class="set-row" onsubmit={saveUsername}>
      <label class="set-label" for="username">
        <strong>{t("Benutzername")}</strong>
        <small>{t("Damit meldest du dich an. Wenn du ihn änderst, trag ihn auch in deinen Apps neu ein.")}</small>
      </label>
      <div class="field">
        <input id="username" bind:value={username} maxlength="32" autocapitalize="none" autocomplete="username" spellcheck="false" />
        <button class="btn" disabled={!usernameChanged}>{t("Ändern")}</button>
      </div>
    </form>
  </div>
</section>

<section class="set-group">
  <h2>{t("Passwort")}</h2>
  <form class="set-card" onsubmit={changePassword}>
    <!-- Lets password managers tell which account the new password belongs to. -->
    <input class="hidden-user" type="text" value={session.user?.username ?? ""} autocomplete="username" readonly tabindex="-1" aria-hidden="true" />
    <div class="set-row">
      <label class="set-label" for="pw-current"><strong>{t("Aktuelles Passwort")}</strong></label>
      <input id="pw-current" type="password" bind:value={currentPw} required autocomplete="current-password" />
    </div>
    <div class="set-row">
      <label class="set-label" for="pw-new"><strong>{t("Neues Passwort")}</strong></label>
      <input id="pw-new" type="password" bind:value={newPw} required minlength="3" autocomplete="new-password" />
    </div>
    <div class="set-row">
      <label class="set-label" for="pw-repeat">
        <strong>{t("Passwort wiederholen")}</strong>
        {#if pwMismatch}<small class="set-warn">{t("Die Passwörter sind nicht gleich.")}</small>{/if}
      </label>
      <input id="pw-repeat" type="password" bind:value={repeatPw} required autocomplete="new-password" />
    </div>
    <div class="set-row end">
      <small class="set-label hint">{t("Andere Geräte und Browser werden danach abgemeldet.")}</small>
      <button class="btn primary" disabled={pwBusy || !currentPw || !newPw || newPw !== repeatPw}>{t("Passwort ändern")}</button>
    </div>
  </form>
</section>

<section class="set-group">
  <div class="set-card">
    <div class="set-row">
      <div class="set-label"><strong>{t("Abmelden")}</strong></div>
      <button class="btn" onclick={doLogout}><Icon name="logout" size={18} /> {t("Abmelden")}</button>
    </div>
  </div>
</section>

<style>
  .profile {
    min-height: 76px;
  }
  .avatar {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 40%, #6b3fa0));
    color: var(--accent-contrast);
    font-weight: 650;
    font-size: 1.2rem;
    flex: none;
  }
  .swatches {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .swatch {
    width: 30px;
    height: 30px;
    padding: 0;
    border-radius: 50%;
    border: none;
    cursor: pointer;
    outline-offset: 2px;
  }
  .swatch.accent {
    background: linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 40%, #6b3fa0));
  }
  .swatch:hover {
    outline: 2px solid var(--text-faint);
  }
  .swatch.on {
    outline: 2px solid var(--text);
  }
  .field {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
  }
  .field input,
  .set-row > input {
    width: min(260px, 100%);
  }
  .hidden-user {
    position: absolute;
    width: 1px;
    height: 1px;
    opacity: 0;
    pointer-events: none;
  }
  .end {
    justify-content: flex-end;
  }
  .hint {
    color: var(--text-muted);
    font-size: 0.84rem;
  }
</style>
