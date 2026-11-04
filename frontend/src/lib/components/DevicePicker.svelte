<script lang="ts">
  // "Gerät steuern": this user's open players. Picking one steers it from here (a remote
  // control only: this device keeps playing what it plays); "Dieses Gerät" goes back.
  import { controlDevice, deviceId, devices, stopControl, type Device } from "../devices.svelte";
  import Icon, { type IconName } from "./Icon.svelte";
  import Modal from "./Modal.svelte";
  import { t } from "../i18n.svelte";

  const close = () => (devices.picker = false);
  const list = $derived([...devices.list].sort((a, b) => Number(b.id === deviceId) - Number(a.id === deviceId) || Number(b.online) - Number(a.online)));
  const ICON: Record<Device["kind"], IconName> = { desktop: "desktop", phone: "phone", tablet: "phone", other: "devices" };

  function line(d: Device): string {
    if (!d.online) return "Verbindung unterbrochen …";
    const s = d.status;
    if (!s?.track) return "Spielt nichts";
    return `${s.playing ? "" : "Pausiert · "}${s.track.title} – ${s.track.artist}`;
  }

  function pick(d: Device) {
    close();
    if (d.id === deviceId) stopControl();
    else controlDevice(d.id);
  }

  const chosen = (d: Device) => (devices.target ?? deviceId) === d.id;
</script>

<Modal title={t("Gerät steuern")} onclose={close}>
  <ul>
    {#each list as d (d.id)}
      <li>
        <button class="dev" class:on={chosen(d)} class:off={!d.online} onclick={() => pick(d)} aria-pressed={chosen(d)}>
          <span class="icon"><Icon name={ICON[d.kind] ?? "devices"} size={22} /></span>
          <span class="meta">
            <strong>{d.id === deviceId ? t("Dieses Gerät") : d.name}</strong>
            <small>{d.id === deviceId ? d.name : line(d)}</small>
          </span>
          {#if d.status?.playing && d.online}<span class="eq" aria-label={t("spielt")}><Icon name="wave" size={18} /></span>{/if}
        </button>
      </li>
    {:else}
      <li class="empty">{t("Noch keine Geräte verbunden.")}</li>
    {/each}
  </ul>
  <p class="hint">
    {t("Öffne audium auf einem anderen Gerät mit deinem Konto, dann erscheint es hier. Das ist eine Fernbedienung: Dieses Gerät spielt weiter, was es gerade spielt.")}
  </p>
  {#if devices.target}
    <button class="btn ghost full" onclick={() => (stopControl(), close())}>{t("Fernsteuerung beenden")}</button>
  {/if}
</Modal>

<style>
  ul {
    list-style: none;
    margin: 0 -8px;
    padding: 0;
  }
  .dev {
    display: flex;
    align-items: center;
    gap: 14px;
    width: 100%;
    padding: 10px 8px;
    border: 0;
    border-radius: var(--radius-sm);
    background: none;
    color: var(--text);
    text-align: left;
    cursor: pointer;
    font: inherit;
  }
  .dev:hover {
    background: var(--surface-1);
  }
  .icon {
    flex: none;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: var(--surface-1);
    color: var(--text-muted);
  }
  .dev.on .icon {
    background: var(--accent);
    color: var(--accent-contrast);
  }
  .dev.on strong {
    color: var(--accent);
  }
  .dev.off {
    opacity: 0.55;
  }
  .meta {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .meta small {
    color: var(--text-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .eq {
    color: var(--accent);
    display: grid;
  }
  .empty {
    padding: 8px;
    color: var(--text-muted);
  }
  .hint {
    margin: 14px 0 0;
    color: var(--text-faint);
    font-size: 0.85rem;
  }
  .full {
    width: 100%;
    margin-top: 14px;
  }
</style>
