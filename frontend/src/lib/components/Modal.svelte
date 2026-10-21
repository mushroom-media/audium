<script lang="ts">
  import type { Snippet } from "svelte";

  let { title, onclose, children }: { title: string; onclose: () => void; children: Snippet } = $props();
  let dialog: HTMLDialogElement;

  $effect(() => {
    dialog.showModal();
    return () => dialog.close();
  });
</script>

<dialog
  bind:this={dialog}
  aria-label={title}
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
    max-width: calc(100vw - 32px);
  }
  dialog::backdrop {
    background: rgb(0 0 0 / 0.55);
  }
  .box {
    width: min(440px, calc(100vw - 32px));
    padding: 22px;
    border-radius: 16px;
    background: var(--surface-0);
    border: 1px solid var(--surface-2);
  }
  h2 {
    margin: 0 0 16px;
    font-size: 1.15rem;
  }
</style>
