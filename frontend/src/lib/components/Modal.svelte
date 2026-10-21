<script lang="ts">
  import type { Snippet } from "svelte";

  let {
    title,
    onclose,
    children,
    width = 440,
  }: { title: string; onclose: () => void; children: Snippet; width?: number } = $props();
  let dialog: HTMLDialogElement;

  $effect(() => {
    dialog.showModal();
    return () => dialog.close();
  });
</script>

<dialog
  bind:this={dialog}
  aria-label={title}
  style:--modal-w="{width}px"
  oncancel={(e) => {
    e.preventDefault();
    onclose();
  }}
  onclick={(e) => e.target === dialog && onclose()}
>
  <div class="box">
    <h2>{title}</h2>
    {@render children()}
  </div>
</dialog>

<style>
  dialog {
    border: 0;
    padding: 0;
    background: transparent;
    color: var(--text);
    /* The box decides the size; the dialog only centres it. */
    max-width: none;
    max-height: none;
    overflow: visible;
  }
  dialog::backdrop {
    background: rgb(0 0 0 / 0.55);
  }
  .box {
    box-sizing: border-box;
    width: min(var(--modal-w), calc(100vw - 32px));
    /* Tall content (long rules) scrolls inside the box instead of being cut off. */
    max-height: calc(100dvh - 48px);
    overflow-y: auto;
    overflow-x: hidden;
    padding: 22px;
    border-radius: 16px;
    background: var(--surface-0);
    border: 1px solid var(--surface-2);
  }
  h2 {
    margin: 0 0 16px;
    font-size: 1.15rem;
  }
  @media (max-width: 560px) {
    .box {
      padding: 18px 16px;
    }
  }
</style>
