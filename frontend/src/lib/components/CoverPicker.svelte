<script lang="ts">
  // Choose a playlist cover: a built-in design, an own image, or back to the first track's cover.
  import { ApiError, post, put, type Playlist } from "../api";
  import { COVER_PRESETS } from "../coverPresets";
  import { toast } from "../ui.svelte";
  import Icon from "./Icon.svelte";
  import Modal from "./Modal.svelte";
  import PlaylistCover from "./PlaylistCover.svelte";

  let { playlist, onchange, onclose }: { playlist: Playlist; onchange: (p: Playlist) => void; onclose: () => void } =
    $props();

  // Photos straight from a phone camera are large; the server keeps at most 600 px anyway.
  const MAX_UPLOAD_PX = 1200;
  let busy = $state(false);
  let fileInput: HTMLInputElement;

  async function save(fn: () => Promise<Playlist>, done: string) {
    busy = true;
    try {
      onchange(await fn());
      toast(done);
      onclose();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Fehlgeschlagen");
    } finally {
      busy = false;
    }
  }

  async function shrink(file: File): Promise<Blob> {
    try {
      const img = await createImageBitmap(file);
      const scale = Math.min(1, MAX_UPLOAD_PX / Math.max(img.width, img.height));
      if (scale === 1 && file.size < 2_000_000) return file;
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(img.width * scale);
      canvas.height = Math.round(img.height * scale);
      canvas.getContext("2d")!.drawImage(img, 0, 0, canvas.width, canvas.height);
      return await new Promise((resolve) => canvas.toBlob((b) => resolve(b ?? file), "image/jpeg", 0.9));
    } catch {
      return file; // let the server decide (it knows more formats)
    }
  }

  async function onFile(e: Event) {
    const file = (e.currentTarget as HTMLInputElement).files?.[0];
    if (!file) return;
    save(async () => post<Playlist>(`/playlists/${playlist.id}/cover`, await shrink(file)), "Cover hochgeladen");
  }
</script>

<Modal title="Cover ändern" onclose={onclose} width={520}>
  <div class="grid">
    {#each COVER_PRESETS as preset, i (preset.name)}
      {@const n = i + 1}
      <button
        class="choice"
        class:on={playlist.cover_preset === n}
        disabled={busy}
        title={preset.name}
        aria-label="Cover „{preset.name}“"
        aria-pressed={playlist.cover_preset === n}
        onclick={() => save(() => put<Playlist>(`/playlists/${playlist.id}/cover`, { preset: n }), "Cover geändert")}
      >
        <PlaylistCover playlist={{ cover: null, cover_preset: n }} />
      </button>
    {/each}
  </div>

  <div class="actions">
    <button class="btn" disabled={busy} onclick={() => fileInput.click()}><Icon name="upload" size={18} /> Eigenes Bild</button>
    {#if playlist.cover_source !== "auto"}
      <button class="btn ghost" disabled={busy} onclick={() => save(() => put<Playlist>(`/playlists/${playlist.id}/cover`, { preset: null }), "Cover zurückgesetzt")}>
        Cover des ersten Titels
      </button>
    {/if}
    <input bind:this={fileInput} type="file" accept="image/*" hidden onchange={onFile} />
  </div>
</Modal>

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 10px;
  }
  .choice {
    padding: 0;
    border: 0;
    border-radius: var(--radius-sm);
    background: none;
    cursor: pointer;
    outline: 2px solid transparent;
    outline-offset: 2px;
  }
  .choice:hover {
    outline-color: var(--text-faint);
  }
  .choice.on {
    outline-color: var(--accent);
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 18px;
  }
  @media (max-width: 420px) {
    .grid {
      grid-template-columns: repeat(4, 1fr);
    }
  }
</style>
