<script lang="ts">
  import Icon from "../../lib/components/Icon.svelte";
  import { navigate } from "../../lib/router.svelte";
  import { logout, session } from "../../lib/session.svelte";
  import { t } from "../../lib/i18n.svelte";

  async function doLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  const initial = $derived((session.user?.display_name || session.user?.username || "?").slice(0, 1).toUpperCase());
</script>

<section class="set-group">
  <div class="set-card">
    <div class="set-row profile">
      <span class="avatar" aria-hidden="true">{initial}</span>
      <div class="set-label">
        <strong>{session.user?.display_name}</strong>
        <small>@{session.user?.username}{session.user?.role === "admin" ? " · Admin" : ""}</small>
      </div>
    </div>
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
    background: var(--accent);
    color: var(--accent-contrast);
    font-weight: 650;
    font-size: 1.2rem;
    flex: none;
  }
</style>
