<script lang="ts">
  // The name this browser has in "Gerät steuern" on the user's other devices. Kept in this
  // browser (all its tabs are one device); empty: the automatic name like "Chrome auf Windows".
  import { autoDeviceName, customDeviceName, deviceId, devices, renameDevice } from "../../lib/devices.svelte";
  import { toast } from "../../lib/ui.svelte";

  let stored = $state(customDeviceName() ?? "");
  let name = $state(customDeviceName() ?? "");
  const saved = $derived(stored === name.trim());
  const others = $derived(devices.list.filter((d) => d.id !== deviceId));

  async function save(e: SubmitEvent) {
    e.preventDefault();
    name = name.trim();
    await renameDevice(name);
    stored = name;
    toast(name ? `Dieses Gerät heißt jetzt „${name}“` : "Name zurückgesetzt");
  }
</script>

<section class="set-group">
  <h2>Dieses Gerät</h2>
  <form class="set-card" onsubmit={save}>
    <div class="set-row">
      <label class="set-label" for="device-name">
        <strong>Name</strong>
        <small>So erscheint dieser Browser bei „Gerät steuern“ auf deinen anderen Geräten. Leer: „{autoDeviceName()}“.</small>
      </label>
      <div class="name">
        <input id="device-name" bind:value={name} maxlength="60" placeholder={autoDeviceName()} autocomplete="off" />
        <button class="btn" disabled={saved}>Speichern</button>
      </div>
    </div>
  </form>
</section>

{#if others.length}
  <section class="set-group">
    <h2>Gerade verbunden</h2>
    <div class="set-card">
      {#each others as d (d.id)}
        <div class="set-row">
          <div class="set-label">
            <strong>{d.name}</strong>
            <small>{!d.online ? "Verbindung unterbrochen" : d.status?.track ? `${d.status.playing ? "Spielt" : "Pausiert"}: ${d.status.track.title}` : "Spielt nichts"}</small>
          </div>
        </div>
      {/each}
    </div>
  </section>
{/if}

<style>
  .name {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .name input {
    width: min(240px, 50vw);
  }
</style>
