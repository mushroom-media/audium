<script lang="ts">
  import type { Letter } from "../api";

  // A-Z strip at the right edge of long alphabetical lists (touch devices): drag along it to jump
  // straight to a letter, like the contacts app. Letters without entries jump to the one before.
  let { letters, onjump }: { letters: Letter[]; onjump: (offset: number) => void } = $props();

  const ALL = ["#", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ"];
  const present = $derived(new Map(letters.map((l) => [l.letter, l.offset])));

  let strip: HTMLDivElement;
  let active = $state<{ letter: string; y: number } | null>(null);

  function offsetFor(i: number): number {
    // The nearest letter at or before i that has entries, else the first one after it.
    for (let j = i; j >= 0; j--) if (present.has(ALL[j])) return present.get(ALL[j])!;
    return letters[0]?.offset ?? 0;
  }

  function pick(clientY: number) {
    const r = strip.getBoundingClientRect();
    const i = Math.max(0, Math.min(ALL.length - 1, Math.floor(((clientY - r.top) / r.height) * ALL.length)));
    const letter = ALL[i];
    if (active?.letter !== letter) {
      onjump(offsetFor(i));
      navigator.vibrate?.(5);
    }
    active = { letter, y: Math.max(r.top, Math.min(r.bottom, clientY)) - r.top };
  }

  function down(e: PointerEvent) {
    e.preventDefault();
    strip.setPointerCapture(e.pointerId);
    pick(e.clientY);
  }
</script>

<div
  class="index"
  bind:this={strip}
  onpointerdown={down}
  onpointermove={(e) => active && pick(e.clientY)}
  onpointerup={() => (active = null)}
  onpointercancel={() => (active = null)}
  role="navigation"
  aria-label="Zu Buchstabe springen"
>
  {#each ALL as l, i (l)}
    <button class="l" class:off={!present.has(l)} tabindex="-1" aria-label="Zu {l}" onclick={() => onjump(offsetFor(i))}>{l}</button>
  {/each}
  {#if active}<div class="bubble" style:top="{active.y}px" aria-hidden="true">{active.letter}</div>{/if}
</div>

<style>
  .index {
    position: absolute;
    top: 50%;
    right: 2px;
    transform: translateY(-50%);
    z-index: 2;
    display: none;
    flex-direction: column;
    align-items: center;
    height: min(78%, 560px);
    padding: 6px 0;
    border-radius: 14px;
    background: color-mix(in srgb, var(--surface-1) 70%, transparent);
    backdrop-filter: blur(6px);
    touch-action: none;
    user-select: none;
    -webkit-user-select: none;
  }
  .l {
    flex: 1;
    width: 22px;
    min-height: 0;
    padding: 0;
    border: 0;
    background: none;
    color: var(--accent);
    font-size: 0.66rem;
    font-weight: 600;
    line-height: 1;
    display: grid;
    place-items: center;
  }
  .l.off {
    color: var(--text-faint);
    font-weight: 400;
  }
  .bubble {
    position: absolute;
    right: calc(100% + 18px);
    width: 64px;
    height: 64px;
    margin-top: -32px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: var(--accent);
    color: var(--accent-contrast);
    font-size: 1.9rem;
    font-weight: 600;
    box-shadow: 0 8px 24px rgb(0 0 0 / 0.35);
    pointer-events: none;
  }
  /* Phones and tablets: there is no scrollbar to grab. With a mouse the scrollbar does the job. */
  @media (pointer: coarse) {
    .index {
      display: flex;
    }
  }
</style>
