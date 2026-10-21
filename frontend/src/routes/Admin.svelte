<script lang="ts">
  import { ApiError, del, get, patch, post, type User } from "../lib/api";
  import Icon from "../lib/components/Icon.svelte";
  import Modal from "../lib/components/Modal.svelte";
  import { plural } from "../lib/format";
  import { basePath } from "../lib/api";
  import { href, router } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";
  import { promptText, toast } from "../lib/ui.svelte";

  interface Root {
    id: number;
    path: string;
    enabled: boolean;
    status: "new" | "online" | "offline";
    status_message: string | null;
    track_count: number;
    last_scan_at: number | null;
    exclude_count: number;
  }
  interface Exclude {
    id: number;
    rel_path: string;
  }
  interface Browse {
    path: string;
    parent: string | null;
    root_id: number | null;
    folders: { name: string; path: string; root_id: number | null }[];
  }
  interface Job {
    id: number;
    queue: string;
    type: string;
    status: string;
    progress: number;
    total: number;
    message: string | null;
    error: string | null;
    result: Record<string, unknown> | null;
    created_at: number;
    finished_at: number | null;
  }
  interface Invite {
    id: number;
    role: "admin" | "user";
    created_at: number;
    expires_at: number;
    used_at: number | null;
  }
  type FullUser = User & { created_at: number; last_login_at: number | null };

  const tab = $derived((router.route.query.get("tab") as "library" | "users" | "jobs" | null) ?? "library");
  let reload = $state(0);

  async function guard<T>(fn: () => Promise<T>, done?: string): Promise<T | undefined> {
    try {
      const r = await fn();
      if (done) toast(done);
      reload++;
      return r;
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Fehlgeschlagen");
    }
  }


  const fmtDate = (ms: number | null) => (ms ? new Date(ms).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" }) : "–");

  // --- library ---------------------------------------------------------------------------------
  let roots = $state<Root[]>([]);
  let excludes = $state<Record<number, Exclude[]>>({});
  let browsing = $state<Browse | null>(null);

  $effect(() => {
    void reload;
    if (tab !== "library") return;
    get<Root[]>("/admin/roots").then(async (r) => {
      roots = r;
      const ex: Record<number, Exclude[]> = {};
      for (const root of r) if (root.exclude_count) ex[root.id] = await get<Exclude[]>(`/admin/roots/${root.id}/excludes`);
      excludes = ex;
    });
  });

  async function browse(path?: string) {
    browsing = await get<Browse>("/admin/browse", { path });
  }

  async function addRoot(path: string) {
    await guard(() => post("/admin/roots", { path }), "Ordner hinzugefügt – der Scan startet");
    browsing = null;
  }

  async function addExclude(root: Root) {
    const rel = await promptText(`Unterordner von ${root.path} ausschließen (relativer Pfad)`, "", "Ausschließen");
    if (rel) guard(() => post(`/admin/roots/${root.id}/excludes`, { rel_path: rel }), "Ausgeschlossen – wird beim Scan entfernt");
  }

  // --- users -------------------------------------------------------------------------------------
  let users = $state<FullUser[]>([]);
  let invites = $state<Invite[]>([]);
  let creating = $state(false);
  let newUser = $state({ username: "", password: "", display_name: "", role: "user" as "user" | "admin" });
  let lastInvite = $state<string | null>(null);

  $effect(() => {
    void reload;
    if (tab !== "users") return;
    get<{ items: FullUser[] }>("/admin/users", { limit: 500 }).then((r) => (users = r.items));
    get<Invite[]>("/admin/invites").then((r) => (invites = r));
  });

  async function createUser() {
    const ok = await guard(() => post("/admin/users", newUser), `Konto „${newUser.username}“ angelegt`);
    if (ok) {
      creating = false;
      newUser = { username: "", password: "", display_name: "", role: "user" };
    }
  }

  async function resetPassword(u: FullUser) {
    const pw = await promptText(`Neues Passwort für ${u.username} (mind. 8 Zeichen)`, "", "Setzen");
    if (pw) guard(() => patch(`/admin/users/${u.id}`, { password: pw }), "Passwort gesetzt, alle Sitzungen beendet");
  }

  async function invite(role: "user" | "admin") {
    const r = await guard(() => post<{ token: string }>("/admin/invites", { role }));
    if (r) {
      lastInvite = `${location.origin}${basePath}/invite/${r.token}`;
      try {
        await navigator.clipboard.writeText(lastInvite);
        toast("Einladungslink kopiert");
      } catch {
        /* clipboard needs HTTPS; the link is shown below anyway */
      }
    }
  }

  // --- jobs ---------------------------------------------------------------------------------------
  let jobs = $state<Job[]>([]);
  $effect(() => {
    void reload;
    if (tab !== "jobs") return;
    const load = () => get<{ items: Job[] }>("/admin/jobs", { limit: 50 }).then((r) => (jobs = r.items));
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  });
  const JOB_LABELS: Record<string, string> = {
    scan: "Bibliotheks-Scan", analyze: "Audioanalyse", autoplaylists: "Auto-Playlists", genres: "Genres vereinheitlichen",
  };
  const RESULT_LABELS: Record<string, string> = {
    files_seen: "Dateien", added: "neu", updated: "geändert", removed: "entfernt", missing: "fehlend", errors: "Fehler",
    analyzed: "analysiert", failed: "fehlgeschlagen", created: "erstellt", covers_added: "Cover",
  };
  function summary(r: Record<string, unknown>): string {
    return Object.entries(RESULT_LABELS)
      .filter(([k]) => typeof r[k] === "number" && (r[k] as number) > 0)
      .map(([k, label]) => `${(r[k] as number).toLocaleString("de-DE")} ${label}`)
      .join(" · ") || "keine Änderungen";
  }
  const STATUS_LABELS: Record<string, string> = {
    queued: "wartet", running: "läuft", done: "fertig", failed: "fehlgeschlagen", cancelled: "abgebrochen",
  };
</script>

<div class="page">
  <div class="toolbar"><h1>Verwaltung</h1></div>
  <div class="tabs" role="tablist">
    <a role="tab" aria-selected={tab === "library"} class:on={tab === "library"} href={href("/admin")}>Bibliothek</a>
    <a role="tab" aria-selected={tab === "users"} class:on={tab === "users"} href={href("/admin?tab=users")}>Nutzer</a>
    <a role="tab" aria-selected={tab === "jobs"} class:on={tab === "jobs"} href={href("/admin?tab=jobs")}>Hintergrundjobs</a>
  </div>

  {#if tab === "library"}
    <section>
      <p class="note">
        audium sieht nur Ordner, die in den Container unter <code>/music</code> eingebunden sind (in
        <code>docker-compose.yml</code> unter <code>volumes</code>). Innerhalb davon wählst du hier, was zur Bibliothek gehört.
        Musikdateien werden nie verändert.
      </p>
      <ul class="list">
        {#each roots as r (r.id)}
          <li class="item">
            <span class="dot {r.enabled ? r.status : 'off'}" title={r.status}></span>
            <div class="grow">
              <div class="mono">{r.path}</div>
              <div class="muted small">
                {r.enabled ? plural(r.track_count, "Titel", "Titel") : "deaktiviert – Titel ausgeblendet"} · letzter Scan {fmtDate(r.last_scan_at)}
                {#if r.status_message}<br /><span class="warn">{r.status_message}</span>{/if}
              </div>
              {#if excludes[r.id]?.length}
                <div class="excl">
                  {#each excludes[r.id] as ex (ex.id)}
                    <span class="chip">ohne <code>{ex.rel_path}</code>
                      <button class="icon-btn tiny" aria-label="Ausschluss entfernen" onclick={() => guard(() => del(`/admin/roots/${r.id}/excludes/${ex.id}`))}><Icon name="close" size={12} /></button>
                    </span>
                  {/each}
                </div>
              {/if}
            </div>
            <button class="btn small ghost" onclick={() => addExclude(r)}>Unterordner ausschließen</button>
            <button class="btn small ghost" onclick={() => guard(() => post("/admin/scan", { root_ids: [r.id] }), "Scan gestartet")}>Scannen</button>
            <label class="switch"><input type="checkbox" checked={r.enabled} onchange={(e) => guard(() => patch(`/admin/roots/${r.id}`, { enabled: e.currentTarget.checked }))} /> aktiv</label>
          </li>
        {:else}
          <li class="muted">Noch keine Bibliotheksordner.</li>
        {/each}
      </ul>
      <div class="row">
        <button class="btn" onclick={() => browse()}><Icon name="plus" size={16} /> Ordner hinzufügen</button>
        <button class="btn ghost" onclick={() => guard(() => post("/admin/scan", {}), "Scan gestartet")}>Alles scannen</button>
        <button class="btn ghost" onclick={() => guard(() => post("/admin/scan", { force: true }), "Vollständiger Scan gestartet")}>Alles neu einlesen</button>
      </div>
    </section>
  {:else if tab === "users"}
    <section>
      <div class="row">
        <button class="btn" onclick={() => (creating = true)}><Icon name="plus" size={16} /> Konto anlegen</button>
        <button class="btn ghost" onclick={() => invite("user")}>Einladungslink</button>
        <button class="btn ghost" onclick={() => invite("admin")}>Admin einladen</button>
      </div>
      {#if lastInvite}
        <p class="invite">Einladungslink (7 Tage gültig, einmal nutzbar): <code>{lastInvite}</code></p>
      {/if}
      <ul class="list">
        {#each users as u (u.id)}
          <li class="item">
            <div class="grow">
              <div><strong>{u.display_name}</strong> <span class="muted">@{u.username}</span>
                {#if u.role === "admin"}<span class="chip">Admin</span>{/if}
                {#if u.status === "disabled"}<span class="chip warn">gesperrt</span>{/if}</div>
              <div class="muted small">seit {fmtDate(u.created_at)} · zuletzt angemeldet {fmtDate(u.last_login_at)}</div>
            </div>
            {#if u.id !== session.user?.id}
              <select value={u.role} aria-label="Rolle" onchange={(e) => guard(() => patch(`/admin/users/${u.id}`, { role: e.currentTarget.value }))}>
                <option value="user">Nutzer</option><option value="admin">Admin</option>
              </select>
              <button class="btn small ghost" onclick={() => resetPassword(u)}>Passwort</button>
              <button class="btn small ghost" onclick={() => guard(() => patch(`/admin/users/${u.id}`, { status: u.status === "active" ? "disabled" : "active" }), u.status === "active" ? "Gesperrt – sofort abgemeldet" : "Entsperrt")}>
                {u.status === "active" ? "Sperren" : "Entsperren"}
              </button>
            {:else}
              <span class="muted small">das bist du</span>
            {/if}
          </li>
        {/each}
      </ul>
      {#if invites.length}
        <h2>Einladungen</h2>
        <ul class="list">
          {#each invites as inv (inv.id)}
            <li class="item">
              <div class="grow small">
                {inv.role === "admin" ? "Admin" : "Nutzer"} · erstellt {fmtDate(inv.created_at)} ·
                {inv.used_at ? `eingelöst ${fmtDate(inv.used_at)}` : inv.expires_at < Date.now() ? "abgelaufen" : `gültig bis ${fmtDate(inv.expires_at)}`}
              </div>
              {#if !inv.used_at}<button class="btn small ghost" onclick={() => guard(() => del(`/admin/invites/${inv.id}`), "Widerrufen")}>Widerrufen</button>{/if}
            </li>
          {/each}
        </ul>
      {/if}
    </section>
  {:else}
    <section>
      <ul class="list">
        {#each jobs as j (j.id)}
          <li class="item">
            <span class="dot {j.status === 'failed' ? 'offline' : j.status === 'running' ? 'online' : ''}"></span>
            <div class="grow">
              <div><strong>{JOB_LABELS[j.type] ?? j.type}</strong> <span class="muted">· {STATUS_LABELS[j.status] ?? j.status}</span></div>
              <div class="muted small">
                {fmtDate(j.created_at)}
                {#if j.status === "running" && j.total} · {j.progress.toLocaleString("de-DE")} / {j.total.toLocaleString("de-DE")}{/if}
                {#if j.message && j.status === "running"}<br /><span class="mono">{j.message}</span>{/if}
                {#if j.error}<br /><span class="warn mono">{j.error}</span>{/if}
                {#if j.result && j.status === "done"}<br />{summary(j.result)}{/if}
              </div>
            </div>
            {#if j.status === "running" || j.status === "queued"}
              <button class="btn small ghost" onclick={() => guard(() => post(`/admin/jobs/${j.id}/cancel`), "Wird abgebrochen")}>Abbrechen</button>
            {/if}
          </li>
        {:else}
          <li class="muted">Keine Jobs.</li>
        {/each}
      </ul>
    </section>
  {/if}
</div>

{#if browsing}
  <Modal title="Ordner wählen" width={560} onclose={() => (browsing = null)}>
    <div class="browser">
      <div class="crumb mono">{browsing.path}</div>
      <ul class="folders">
        {#if browsing.parent}
          <li><button class="folder" onclick={() => browse(browsing!.parent!)}><Icon name="back" size={16} /> ..</button></li>
        {/if}
        {#each browsing.folders as f (f.path)}
          <li>
            <button class="folder" onclick={() => browse(f.path)}>📁 {f.name}</button>
            {#if f.root_id}<span class="chip">in der Bibliothek</span>{/if}
          </li>
        {:else}
          <li class="muted small">Keine Unterordner.</li>
        {/each}
      </ul>
      <div class="buttons">
        <button class="btn ghost" onclick={() => (browsing = null)}>Abbrechen</button>
        <button class="btn primary" disabled={!!browsing.root_id} onclick={() => addRoot(browsing!.path)}>
          {browsing.root_id ? "Schon in der Bibliothek" : "Diesen Ordner hinzufügen"}
        </button>
      </div>
    </div>
  </Modal>
{/if}

{#if creating}
  <Modal title="Konto anlegen" onclose={() => (creating = false)}>
    <form class="form" onsubmit={(e) => (e.preventDefault(), createUser())}>
      <label>Benutzername<input bind:value={newUser.username} required autocapitalize="none" /></label>
      <label>Anzeigename<input bind:value={newUser.display_name} placeholder="optional" /></label>
      <label>Passwort<input type="password" bind:value={newUser.password} required minlength="8" autocomplete="new-password" /></label>
      <label>Rolle<select bind:value={newUser.role}><option value="user">Nutzer</option><option value="admin">Admin</option></select></label>
      <div class="buttons">
        <button type="button" class="btn ghost" onclick={() => (creating = false)}>Abbrechen</button>
        <button class="btn primary">Anlegen</button>
      </div>
    </form>
  </Modal>
{/if}

<style>
  .tabs {
    display: flex;
    gap: 6px;
    padding: 0 24px 8px;
    flex-wrap: wrap;
  }
  .tabs a {
    padding: 6px 14px;
    border-radius: 16px;
    color: var(--text-muted);
    text-decoration: none;
    font-size: 0.9rem;
  }
  .tabs a.on {
    background: var(--surface-1);
    color: var(--text);
  }
  section {
    padding: 8px 24px 32px;
    max-width: 980px;
  }
  h2 {
    font-size: 1rem;
    margin: 24px 0 8px;
  }
  .note,
  .muted {
    color: var(--text-muted);
  }
  .note {
    font-size: 0.88rem;
    line-height: 1.5;
  }
  .small {
    font-size: 0.85rem;
  }
  .mono,
  code {
    font-family: ui-monospace, monospace;
    font-size: 0.84rem;
    word-break: break-all;
  }
  code {
    background: var(--surface-1);
    padding: 1px 5px;
    border-radius: 4px;
  }
  .list {
    list-style: none;
    padding: 0;
    margin: 12px 0;
  }
  .item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 0;
    border-bottom: 1px solid var(--line);
    flex-wrap: wrap;
  }
  .grow {
    flex: 1;
    min-width: 200px;
  }
  .row,
  .buttons {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    margin: 12px 0;
  }
  .buttons {
    justify-content: flex-end;
  }
  .btn.small {
    height: 32px;
    padding: 0 12px;
    font-size: 0.85rem;
  }
  .dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--text-faint);
    flex: none;
  }
  .dot.online {
    background: var(--ok);
  }
  .dot.offline {
    background: var(--danger);
  }
  .warn {
    color: var(--danger);
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 0.75rem;
    padding: 2px 8px;
    border-radius: 10px;
    background: var(--surface-1);
    color: var(--text-muted);
    margin-left: 6px;
  }
  .chip.warn {
    color: var(--danger);
  }
  .excl {
    margin-top: 6px;
  }
  .excl .chip {
    margin: 0 6px 0 0;
  }
  .tiny {
    width: 20px;
    height: 20px;
  }
  .switch {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.85rem;
    color: var(--text-muted);
  }
  .invite {
    font-size: 0.88rem;
    background: var(--surface-1);
    padding: 10px;
    border-radius: var(--radius-sm);
  }
  .browser .crumb {
    padding: 8px 10px;
    background: var(--surface-1);
    border-radius: var(--radius-sm);
  }
  .folders {
    list-style: none;
    padding: 0;
    margin: 10px 0;
    max-height: 340px;
    overflow-y: auto;
  }
  .folders li {
    display: flex;
    align-items: center;
  }
  .folder {
    flex: 1;
    text-align: left;
    border: 0;
    background: none;
    color: var(--text);
    padding: 8px 10px;
    border-radius: var(--radius-sm);
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .folder:hover {
    background: var(--surface-1);
  }
  .form {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .form label {
    display: flex;
    flex-direction: column;
    gap: 6px;
    color: var(--text-muted);
    font-size: 0.88rem;
  }
  @media (max-width: 560px) {
    section {
      padding: 8px 16px 24px;
    }
    .tabs {
      padding: 0 16px 8px;
    }
  }
</style>
