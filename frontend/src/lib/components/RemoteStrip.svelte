<script lang="ts">
  // A strip above the player bar while the remote control is in use: here when this device
  // steers another one, and on the steered device itself.
  import { devices, self, stopControl, target } from "../devices.svelte";
  import { localPlayer, player } from "../player.svelte";
  import { tabs } from "../tabs.svelte";

  const steering = $derived(target());
  const steeredBy = $derived(self()?.controllers.map((c) => c.name) ?? []);
  // In another tab of this browser the tap works too: the player then moves into that tab.
  const blocked = $derived(tabs.role === "follower" ? !!tabs.mirror?.status?.blocked : localPlayer.blocked);
</script>

{#if devices.target}
  <div class="strip on" role="status">
    <button class="what" onclick={() => (devices.picker = true)}>
      Steuert: <strong>{steering?.name ?? "Gerät"}</strong>
      {#if steering && !steering.online}<span> · Verbindung unterbrochen …</span>
      {:else if steering?.status?.blocked}<span> · Auf dem Gerät einmal tippen, damit es abspielen darf</span>{/if}
    </button>
    <button class="end" onclick={() => stopControl()}>Trennen</button>
  </div>
{:else if steeredBy.length}
  <div class="strip" role="status">
    <span class="what">Wird von <strong>{steeredBy.join(", ")}</strong> gesteuert</span>
    {#if blocked}
      <button class="end" onclick={() => player.toggle()}>Abspielen erlauben</button>
    {/if}
  </div>
{/if}

<style>
  .strip {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 100%;
    z-index: 1;
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 28px;
    padding: 3px 16px;
    font-size: 0.8rem;
    background: var(--surface-2);
    color: var(--text);
  }
  .strip.on {
    background: var(--accent);
    color: var(--accent-contrast);
  }
  .what {
    flex: 1;
    min-width: 0;
    padding: 0;
    border: 0;
    background: none;
    color: inherit;
    font: inherit;
    text-align: left;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  button.what {
    cursor: pointer;
  }
  .end {
    flex: none;
    padding: 2px 10px;
    border: 1px solid currentColor;
    border-radius: 12px;
    background: none;
    color: inherit;
    font: inherit;
    font-weight: 600;
    cursor: pointer;
  }
</style>
