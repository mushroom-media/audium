<script lang="ts">
  // Prompt, share dialog and toast; one instance in App.
  import { ApiError, del, get, patch, put, type Playlist, type Share, type UserRef } from "../api";
  import { loadPlaylists, mine } from "../mine.svelte";
  import { toast, ui } from "../ui.svelte";
  import Icon from "./Icon.svelte";
  import Modal from "./Modal.svelte";
  import TrackInfo from "./TrackInfo.svelte";
  import TrackMenu from "./TrackMenu.svelte";
  import { t } from "../i18n.svelte";

  let promptValue = $state("");
  $effect(() => {
    if (ui.prompt) promptValue = ui.prompt.value;
  });

  function answer(value: string | null) {
    const p = ui.prompt;
    ui.prompt = null;
    p?.resolve(value && value.trim() ? value.trim() : null);
  }

  // --- sharing -------------------------------------------------------------------------------
  let shares = $state<Share[]>([]);
  let people = $state<UserRef[]>([]);
  let addUser = $state<number | "">("");
  let addRole = $state<"viewer" | "editor">("viewer");
  const playlist = $derived(ui.share ? mine.playlists.find((p) => p.id === ui.share!.playlistId) : undefined);
  const candidates = $derived(people.filter((u) => !shares.some((s) => s.user.id === u.id)));

  $effect(() => {
    const id = ui.share?.playlistId;
    if (!id) return;
    Promise.all([get<Share[]>(`/playlists/${id}/shares`), get<UserRef[]>("/users")]).then(([s, u]) => {
      shares = s;
      people = u;
    });
  });

  async function guard(fn: () => Promise<void>) {
    try {
      await fn();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("Fehlgeschlagen"));
    }
  }

  const setVisibility = (v: "private" | "users") =>
    guard(async () => {
      await patch<Playlist>(`/playlists/${ui.share!.playlistId}`, { visibility: v });
      await loadPlaylists();
    });
  const setRole = (userId: number, role: string) =>
    guard(async () => {
      shares = await put<Share[]>(`/playlists/${ui.share!.playlistId}/shares/${userId}`, { role });
    });
  const removeShare = (userId: number) =>
    guard(async () => {
      shares = await del<Share[]>(`/playlists/${ui.share!.playlistId}/shares/${userId}`);
    });
  const addShare = () =>
    guard(async () => {
      if (addUser === "") return;
      await setRole(addUser, addRole);
      addUser = "";
    });
</script>

<TrackMenu />
{#if ui.info}<TrackInfo trackId={ui.info.trackId} onclose={() => (ui.info = null)} />{/if}

{#if ui.prompt}
  <Modal title={ui.prompt.title} onclose={() => answer(null)}>
    <form
      onsubmit={(e) => {
        e.preventDefault();
        answer(promptValue);
      }}
    >
      <!-- svelte-ignore a11y_autofocus -->
      <input class="full" bind:value={promptValue} autofocus maxlength="200" aria-label={ui.prompt.title} />
      <div class="buttons">
        <button type="button" class="btn ghost" onclick={() => answer(null)}>{t("Abbrechen")}</button>
        <button class="btn primary" disabled={!promptValue.trim()}>{ui.prompt.confirm}</button>
      </div>
    </form>
  </Modal>
{/if}

{#if ui.share && playlist}
  <Modal title={t("„{name}“ teilen", { name: playlist.name })} width={520} onclose={() => (ui.share = null)}>
    <label class="switch">
      <input type="checkbox" checked={playlist.visibility === "users"} onchange={(e) => setVisibility(e.currentTarget.checked ? "users" : "private")} />
      <span>
        <strong>{t("Für alle Nutzer sichtbar")}</strong><br />
        <small>{t("Alle auf diesem Server können sie sehen und abspielen. Bearbeiten nur wer unten Editor ist.")}</small>
      </span>
    </label>

    <h3>{t("Mit einzelnen Personen")}</h3>
    <ul class="shares">
      {#each shares as s (s.user.id)}
        <li>
          <span class="who">{s.user.display_name} <small>@{s.user.username}</small></span>
          <select value={s.role} onchange={(e) => setRole(s.user.id, e.currentTarget.value)} aria-label={t("Rolle")}>
            <option value="viewer">{t("Kann ansehen")}</option>
            <option value="editor">{t("Kann bearbeiten")}</option>
          </select>
          <button class="icon-btn" aria-label={t("Freigabe entfernen")} onclick={() => removeShare(s.user.id)}><Icon name="close" size={16} /></button>
        </li>
      {:else}
        <li class="none">{t("Noch mit niemandem geteilt.")}</li>
      {/each}
    </ul>
    {#if candidates.length}
      <div class="add">
        <select bind:value={addUser} aria-label={t("Person")}>
          <option value="">{t("Person wählen …")}</option>
          {#each candidates as u (u.id)}<option value={u.id}>{u.display_name} (@{u.username})</option>{/each}
        </select>
        <select bind:value={addRole} aria-label={t("Rolle")}>
          <option value="viewer">{t("Kann ansehen")}</option>
          <option value="editor">{t("Kann bearbeiten")}</option>
        </select>
        <button class="btn" disabled={addUser === ""} onclick={addShare}>{t("Teilen")}</button>
      </div>
    {:else if !people.length}
      <p class="none">{t("Es gibt noch keine anderen Nutzer. Einladen kann der Admin.")}</p>
    {/if}
    <div class="buttons"><button class="btn primary" onclick={() => (ui.share = null)}>{t("Fertig")}</button></div>
  </Modal>
{/if}

{#if ui.toast}
  {#key ui.toast.id}<div class="toast" role="status">{ui.toast.text}</div>{/key}
{/if}

<style>
  .full {
    width: 100%;
  }
  .buttons {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    margin-top: 18px;
  }
  .switch {
    display: flex;
    gap: 12px;
    align-items: flex-start;
    cursor: pointer;
  }
  .switch input {
    margin-top: 4px;
    width: 18px;
    height: 18px;
    accent-color: var(--accent);
  }
  small {
    color: var(--text-muted);
  }
  h3 {
    font-size: 0.9rem;
    margin: 20px 0 8px;
  }
  .shares {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .shares li {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 0;
  }
  .who {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .none {
    color: var(--text-muted);
    font-size: 0.9rem;
  }
  .add {
    display: flex;
    gap: 8px;
    margin-top: 10px;
    flex-wrap: wrap;
  }
  .add select:first-child {
    flex: 1;
    min-width: 0;
  }
  .toast {
    position: fixed;
    left: 50%;
    bottom: calc(var(--player-h) + 20px);
    transform: translateX(-50%);
    z-index: 60;
    padding: 10px 16px;
    border-radius: 10px;
    background: var(--text);
    color: var(--bg);
    font-weight: 500;
    font-size: 0.9rem;
    animation: pop 0.18s ease-out;
    max-width: calc(100vw - 32px);
  }
  @keyframes pop {
    from {
      opacity: 0;
      transform: translate(-50%, 8px);
    }
  }
  @media (max-width: 860px) {
    .toast {
      bottom: calc(var(--player-h) + var(--tabs-h) + 16px);
    }
  }
</style>
