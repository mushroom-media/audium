<script lang="ts">
  // The main button of an album or playlist page: while that list plays it pauses, and after a
  // pause it carries on instead of starting over (like CardPlay on the covers).
  import { player } from "../player.svelte";
  import Icon from "./Icon.svelte";

  /** `ref`: the source.ref this list plays under (see QueueSource). */
  let { ref, disabled = false, start }: { ref: string; disabled?: boolean; start: () => void } = $props();

  const current = $derived(player.source?.ref === ref);
  const playing = $derived(current && player.playing);
</script>

<button class="btn primary" disabled={disabled && !current} onclick={() => (current ? player.toggle() : start())}>
  <Icon name={playing ? "pause" : "play"} size={18} />
  {playing ? "Pause" : "Abspielen"}
</button>
