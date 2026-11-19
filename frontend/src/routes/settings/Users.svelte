<script lang="ts">
  import { ApiError, del, get, patch, post, serverUrl, type User } from "../../lib/api";
  import Icon from "../../lib/components/Icon.svelte";
  import Modal from "../../lib/components/Modal.svelte";
  import { avatarStyle } from "../../lib/avatar";
  import { session } from "../../lib/session.svelte";
  import { promptText, toast } from "../../lib/ui.svelte";
  import { fmtDate } from "./common";
  import { t } from "../../lib/i18n.svelte";

  interface Invite {
    id: number;
    role: "admin" | "user";
    created_at: number;
    expires_at: number;
    used_at: number | null;
  }
  type FullUser = User & { created_at: number; last_login_at: number | null };

  let users = $state<FullUser[]>([]);
  let invites = $state<Invite[]>([]);
  let creating = $state(false);
  let newUser = $state({ username: "", password: "", display_name: "", role: "user" as "user" | "admin" });
  let lastInvite = $state<string | null>(null);
  let reload = $state(0);

  $effect(() => {
    void reload;
    get<{ items: FullUser[] }>("/admin/users", { limit: 500 }).then((r) => (users = r.items));
    get<Invite[]>("/admin/invites").then((r) => (invites = r));
  });

  async function guard<T>(fn: () => Promise<T>, done?: string): Promise<T | undefined> {
    try {
      const r = await fn();
      if (done) toast(done);
      reload++;
      return r;
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("Fehlgeschlagen"));
    }
  }

  async function createUser() {
    const ok = await guard(() => post("/admin/users", newUser), t("Konto „{name}“ angelegt", { name: newUser.username }));
    if (ok) {
      creating = false;
      newUser = { username: "", password: "", display_name: "", role: "user" };
    }
  }

  async function resetPassword(u: FullUser) {
    const pw = await promptText(t("Neues Passwort für {name} (mind. 3 Zeichen)", { name: u.username }), "", t("Setzen"));
    if (pw) guard(() => patch(`/admin/users/${u.id}`, { password: pw }), t("Passwort gesetzt, alle Sitzungen beendet"));
  }

  async function invite(role: "user" | "admin") {
    const r = await guard(() => post<{ token: string }>("/admin/invites", { role }));
    if (r) {
      lastInvite = `${serverUrl()}/invite/${r.token}`;
      try {
        await navigator.clipboard.writeText(lastInvite);
        toast(t("Einladungslink kopiert"));
      } catch {
        /* clipboard needs HTTPS; the link is shown below anyway */
      }
    }
  }

  const initial = (u: FullUser) => (u.display_name || u.username).slice(0, 1).toUpperCase();
</script>

<div class="top-actions">
  <button class="btn primary" onclick={() => (creating = true)}><Icon name="plus" size={16} /> {t("Konto anlegen")}</button>
  <button class="btn" onclick={() => invite("user")}>{t("Einladungslink")}</button>
  <button class="btn ghost" onclick={() => invite("admin")}>{t("Admin einladen")}</button>
</div>
{#if lastInvite}
  <p class="invite">{t("Einladungslink (7 Tage gültig, einmal nutzbar):")}<br /><code>{lastInvite}</code></p>
{/if}

<section class="set-group">
  <h2>{t("Konten")}</h2>
  <div class="set-card">
    {#each users as u (u.id)}
      <div class="set-row">
        <span class="avatar" class:off={u.status === "disabled"} style={avatarStyle(u.avatar_color)} aria-hidden="true">{initial(u)}</span>
        <div class="set-label">
          <strong>
            {u.display_name} <span class="handle">@{u.username}</span>
            {#if u.role === "admin"}<span class="set-chip">{t("Admin")}</span>{/if}
            {#if u.status === "disabled"}<span class="set-chip warn">{t("gesperrt")}</span>{/if}
          </strong>
          <small>{t("seit {created} · zuletzt angemeldet {login}", { created: fmtDate(u.created_at), login: fmtDate(u.last_login_at) })}</small>
        </div>
        {#if u.id !== session.user?.id}
          <div class="btns">
            <select value={u.role} aria-label={t("Rolle von {name}", { name: u.username })} onchange={(e) => guard(() => patch(`/admin/users/${u.id}`, { role: e.currentTarget.value }))}>
              <option value="user">{t("Nutzer")}</option><option value="admin">{t("Admin")}</option>
            </select>
            <button class="btn small ghost" onclick={() => resetPassword(u)}>{t("Passwort")}</button>
            <button
              class="btn small ghost"
              onclick={() => guard(() => patch(`/admin/users/${u.id}`, { status: u.status === "active" ? "disabled" : "active" }), u.status === "active" ? "Gesperrt – sofort abgemeldet" : "Entsperrt")}
            >
              {u.status === "active" ? "Sperren" : "Entsperren"}
            </button>
          </div>
        {:else}
          <span class="set-chip">{t("das bist du")}</span>
        {/if}
      </div>
    {/each}
  </div>
</section>

{#if invites.length}
  <section class="set-group">
    <h2>{t("Einladungen")}</h2>
    <div class="set-card">
      {#each invites as inv (inv.id)}
        <div class="set-row">
          <div class="set-label">
            <strong>{inv.role === "admin" ? t("Admin") : t("Nutzer")}</strong>
            <small>
              {t("erstellt {date}", { date: fmtDate(inv.created_at) })} ·
              {inv.used_at ? t("eingelöst {date}", { date: fmtDate(inv.used_at) }) : inv.expires_at < Date.now() ? t("abgelaufen") : t("gültig bis {date}", { date: fmtDate(inv.expires_at) })}
            </small>
          </div>
          {#if !inv.used_at}<button class="btn small ghost" onclick={() => guard(() => del(`/admin/invites/${inv.id}`), "Widerrufen")}>{t("Widerrufen")}</button>{/if}
        </div>
      {/each}
    </div>
  </section>
{/if}

{#if creating}
  <Modal title={t("Konto anlegen")} onclose={() => (creating = false)}>
    <form class="form" onsubmit={(e) => (e.preventDefault(), createUser())}>
      <label>{t("Benutzername")}<input bind:value={newUser.username} required autocapitalize="none" /></label>
      <label>{t("Anzeigename")}<input bind:value={newUser.display_name} placeholder={t("optional")} /></label>
      <label>{t("Passwort")}<input type="password" bind:value={newUser.password} required minlength="3" autocomplete="new-password" /></label>
      <label>{t("Rolle")}<select bind:value={newUser.role}><option value="user">{t("Nutzer")}</option><option value="admin">{t("Admin")}</option></select></label>
      <div class="modal-buttons">
        <button type="button" class="btn ghost" onclick={() => (creating = false)}>{t("Abbrechen")}</button>
        <button class="btn primary">{t("Anlegen")}</button>
      </div>
    </form>
  </Modal>
{/if}

<style>
  .top-actions,
  .btns,
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
  }
  .btns select {
    height: 32px;
    font-size: 0.85rem;
  }
  .avatar {
    width: 38px;
    height: 38px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: var(--surface-2);
    color: var(--text);
    font-weight: 650;
    flex: none;
  }
  .avatar.off {
    opacity: 0.45;
  }
  .handle {
    color: var(--text-muted);
    font-weight: 400;
  }
  .set-label strong .set-chip {
    margin-left: 4px;
    vertical-align: 1px;
  }
  .invite {
    font-size: 0.88rem;
    background: var(--surface-1);
    padding: 12px 14px;
    border-radius: 12px;
    margin: 0 0 20px;
  }
  .invite code {
    font-family: ui-monospace, monospace;
    font-size: 0.8rem;
    word-break: break-all;
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
</style>
