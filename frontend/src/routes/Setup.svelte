<script lang="ts">
  // The first-run dialog: the admin account exists already (Auth.svelte or
  // AUDIUM_ADMIN_*); this page finds the music and asks what audium may do. Written for people who
  // do not know Docker: plain words first, the technical detail folded away.
  import { onMount } from "svelte";
  import { ApiError, get, patch, post } from "../lib/api";
  import Icon from "../lib/components/Icon.svelte";
  import Modal from "../lib/components/Modal.svelte";
  import { plural } from "../lib/format";
  import { href, navigate } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";
  import { toast } from "../lib/ui.svelte";
  import type { Job } from "./settings/common";
  import { i18n, type Lang, LANGUAGES, msg, num, setLanguage, t, tn } from "../lib/i18n.svelte";

  interface Mount {
    path: string;
    fstype: string;
    read_only: boolean;
    network: boolean;
  }
  interface Info {
    pending: boolean;
    admin_from_env: boolean;
    roots_from_env: boolean;
    music_dir: string;
    mounts: Mount[];
    candidates: string[];
    roots: { path: string; track_count: number }[];
    data_persistent: boolean | null;
    analysis_available: boolean;
    cpus: number;
    https: boolean;
    proxy_not_trusted: boolean;
    utc_offset_minutes: number;
  }
  interface Probe {
    path: string;
    readable: boolean;
    complete: boolean;
    audio_files: number;
    size_bytes: number;
    formats: { ext: string; count: number }[];
    image_files: number;
    other_files: number;
    folders: number;
    folders_with_music: number;
    folders_with_cover: number;
    unreadable_folders: number;
    unreadable_examples: string[];
    samples: { path: string; title: string | null; artist: string | null; album: string | null; tagged: boolean }[];
    warnings: string[];
    owner: string | null;
    mode: string | null;
    container_user: string | null;
  }
  interface Browse {
    path: string;
    parent: string | null;
    folders: { name: string; path: string }[];
  }
  interface ServerSettings {
    analysis_workers: string;
    analysis_paused: "on" | "off";
    analysis_schedule: "always" | "window";
    analysis_from: string;
    analysis_until: string;
    subsonic_api: "on" | "off";
    app_access: "on" | "off";
    model_download: "on" | "off";
  }
  interface Env {
    subsonic_available: boolean;
    model_download_available: boolean;
  }
  interface Sources {
    sources: { artists: { on: boolean } };
  }
  interface Stats {
    tracks: number;
    albums: number;
    artists: number;
  }
  type Step = "music" | "features" | "hints" | "done";

  const RECHECK_MS = 5000;

  let info = $state<Info | null>(null);
  let step = $state<Step>("music");
  let reconnecting = $state(false);
  let busy = $state(false);

  // --- music -------------------------------------------------------------------------------------

  let folders = $state<string[]>([]);
  let probes = $state<Record<string, Probe | undefined>>({});
  let probeErrors = $state<Record<string, string | undefined>>({});
  let probing = $state(0);
  let selected = $state<string[]>([]);
  let touched: string[] = []; // the admin decided about these; a new check must not undo that
  let hostPath = $state("");
  let browsing = $state<Browse | null>(null);

  const isRoot = (path: string) => !!info?.roots.some((r) => r.path === path);
  const hasMusic = $derived(folders.some((f) => (probes[f]?.audio_files ?? 0) > 0) || !!info?.roots.some((r) => r.track_count > 0));
  const canGoOn = $derived(selected.length > 0 || !!info?.roots.length);
  const envLine = $derived(`AUDIUM_MUSIC_PATH=${/\s/.test(hostPath.trim()) ? `"${hostPath.trim()}"` : hostPath.trim() || t("/pfad/zu/deiner/musik")}`);

  async function load() {
    try {
      const i = await get<Info>("/admin/setup");
      info = i;
      reconnecting = false;
      const known = [...i.roots.map((r) => r.path), ...i.candidates];
      folders = [...new Set([...known, ...folders.filter((f) => f !== i.music_dir || known.includes(f))])];
      await Promise.all(folders.map(probeFolder));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return; // the app goes to the login page
      reconnecting = true; // the container restarts, e.g. for a new music folder
    }
  }

  async function probeFolder(path: string) {
    probing++;
    try {
      const p = await post<Probe>("/admin/setup/probe", { path });
      probes[path] = p;
      probeErrors[path] = undefined;
      if (p.audio_files > 0 && !touched.includes(path) && !isRoot(path) && !selected.includes(path)) selected.push(path);
    } catch (e) {
      if (e instanceof ApiError) probeErrors[path] = e.message;
      else throw e;
    } finally {
      probing--;
    }
  }

  function toggle(path: string, on: boolean) {
    touched.push(path);
    selected = on ? [...selected, path] : selected.filter((p) => p !== path);
  }

  async function browse(path?: string) {
    try {
      browsing = await get<Browse>("/admin/browse", { path });
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("Fehlgeschlagen"));
    }
  }

  function addFolder(path: string) {
    browsing = null;
    if (!folders.includes(path)) folders = [...folders, path];
    probeFolder(path).catch(() => {});
  }

  /** Plain HTTP, usual in a home network, has no clipboard API. */
  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const area = document.createElement("textarea");
      area.value = text;
      document.body.append(area);
      area.select();
      const ok = document.execCommand("copy");
      area.remove();
      if (!ok) {
        toast(t("Bitte von Hand kopieren"));
        return;
      }
    }
    toast(t("Kopiert"));
  }

  const mountOf = (path: string) =>
    info?.mounts.filter((m) => path === m.path || path.startsWith(`${m.path}/`)).sort((a, b) => b.path.length - a.path.length)[0];

  function summary(p: Probe): string {
    const size = p.size_bytes >= 1e9 ? `${num(p.size_bytes / 1e9, { maximumFractionDigits: 1 })} GB` : `${num(Math.ceil(p.size_bytes / 1e6))} MB`;
    const files = plural(p.audio_files, "Musikdatei", "Musikdateien");
    return p.complete ? `${files} · ${size}` : t("mindestens {files} · mindestens {size}", { files, size });
  }

  function formats(p: Probe): string {
    const top = p.formats.slice(0, 4).map((f) => `${f.ext.toUpperCase()} ${Math.round((f.count / p.audio_files) * 100)} %`);
    return top.join(", ");
  }

  const WARNINGS: Record<string, string> = {
    no_audio: msg("Hier liegt keine Musik. Ist das der richtige Ordner?"),
    mostly_other_files: msg("Hier liegen vor allem andere Dateien als Musik. Ist das der richtige Ordner?"),
    few_tags: msg("Viele Dateien haben keine Angaben zu Künstler und Titel. audium nimmt dann die Ordner- und Dateinamen."),
    unreadable: msg("audium darf diesen Ordner nicht lesen."),
    unreadable_subfolders: msg("audium darf einige Unterordner nicht lesen. Sie fehlen dann in der Bibliothek."),
  };

  // --- what audium may do ------------------------------------------------------------------------

  let server = $state<ServerSettings | null>(null);
  let env = $state<Env | null>(null);
  let listenBrainz = $state(false);

  async function loadFeatures() {
    try {
      const [s, e, r] = await Promise.all([get<ServerSettings>("/admin/settings"), get<Env>("/admin/interfaces"), get<Sources>("/admin/radio/sources")]);
      server = s;
      env = e;
      listenBrainz = r.sources.artists.on;
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("Einstellungen konnten nicht geladen werden"));
    }
  }

  async function save(changes: Partial<ServerSettings>) {
    const before = server;
    server = server && { ...server, ...changes };
    try {
      server = await patch<ServerSettings>("/admin/settings", changes);
    } catch (e) {
      server = before;
      toast(e instanceof ApiError ? e.message : t("Speichern fehlgeschlagen"));
    }
  }

  async function saveListenBrainz(on: boolean) {
    try {
      listenBrainz = (await patch<Sources>("/admin/radio/sources", { artists: { on } })).sources.artists.on;
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("Speichern fehlgeschlagen"));
    }
  }

  const workerChoices = $derived(Array.from({ length: Math.min(16, info?.cpus ?? 1) }, (_, i) => String(i + 1)));

  // --- hints -------------------------------------------------------------------------------------

  const hints = $derived.by(() => {
    const out: { title: string; text: string; code?: string }[] = [];
    if (!info) return out;
    if (info.data_persistent === false)
      out.push({
        title: t("Deine Daten könnten verloren gehen"),
        text: t("Konto, Playlists und Favoriten liegen nicht in einem festen Ordner auf dem Server. Wird der Container neu erstellt, sind sie weg. Binde dafür einen Ordner als /data ein, zum Beispiel:"),
        code: "./data:/data",
      });
    if (info.admin_from_env)
      out.push({
        title: t("Passwort aus der .env entfernen"),
        text: t("Dein Konto ist angelegt. Die Zeilen AUDIUM_ADMIN_USER und AUDIUM_ADMIN_PASSWORD werden nicht mehr gebraucht und können aus der .env raus."),
      });
    if (info.proxy_not_trusted)
      out.push({
        title: t("Reverse-Proxy noch nicht eingetragen"),
        text: t("Deine Anfragen laufen über einen Proxy, dem audium noch nicht vertraut. Login-Sperren treffen dann alle Nutzer gemeinsam. Trage ihn so ein (Adresse anpassen):"),
        code: "AUDIUM_TRUSTED_PROXIES=172.16.0.1",
      });
    if (!info.https)
      out.push({
        title: t("Verbindung ohne HTTPS"),
        text: t("Im Heimnetz funktioniert alles. Nur audium als App auf dem Handy installieren geht erst mit HTTPS, und von unterwegs solltest du nie ohne zugreifen. Wie das geht, steht in docs/reverse-proxy.md."),
      });
    if (-new Date().getTimezoneOffset() !== info.utc_offset_minutes)
      out.push({
        title: t("Der Server hat eine andere Zeitzone"),
        text: t("Das Zeitfenster der Analyse richtet sich nach der Serverzeit. Stelle bei Bedarf die Zeitzone ein:"),
        code: "TZ=Europe/Berlin",
      });
    return out;
  });

  const steps = $derived<{ id: Step | "account"; label: string }[]>([
    { id: "account", label: t("Konto") },
    { id: "music", label: t("Musik") },
    { id: "features", label: t("Funktionen") },
    ...(hints.length ? [{ id: "hints" as const, label: t("Hinweise") }] : []),
    { id: "done", label: t("Fertig") },
  ]);
  const current = $derived(steps.findIndex((s) => s.id === step));

  // --- moving on -----------------------------------------------------------------------------------

  function go(to: Step) {
    step = to;
    if (to === "features" && !server) loadFeatures();
    document.querySelector(".wizard")?.scrollTo(0, 0);
  }

  let chose = $state(false);
  let job = $state<Job | null>(null);
  let stats = $state<Stats | null>(null);
  const scanning = $derived(!!job && (job.status === "queued" || job.status === "running"));

  async function finish() {
    busy = true;
    try {
      const roots = canGoOn ? [...selected] : null;
      await post("/admin/setup/complete", { roots });
      chose = roots !== null;
      session.setupPending = false;
      go("done");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("Fehlgeschlagen"));
    } finally {
      busy = false;
    }
  }

  /** Skipped: audium takes what it finds, as it would without the dialog. */
  async function skip() {
    busy = true;
    try {
      if (info?.pending) await post("/admin/setup/complete", { roots: null });
      session.setupPending = false;
      navigate(info?.pending ? "/" : "/settings/library", { replace: true });
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("Fehlgeschlagen"));
    } finally {
      busy = false;
    }
  }

  // The language is the first thing to choose: it becomes the server language, which every user
  // sees unless they pick their own. Until an admin chooses, the one the browser showed counts.
  async function chooseLanguage(lang: Lang) {
    setLanguage(lang);
    try {
      await patch("/admin/settings", { language: lang });
      session.settings = { ...session.settings, language_default: lang };
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("Fehlgeschlagen"));
    }
  }

  onMount(() => {
    load();
    get<{ language: Lang | null }>("/setup")
      .then((s) => {
        if (!s.language) chooseLanguage(i18n.lang);
      })
      .catch(() => {});
  });

  // Looks again while the music is missing: the folder may be mounted any moment now.
  $effect(() => {
    if (step !== "music" || probing > 0 || (hasMusic && !reconnecting)) return;
    const timer = setTimeout(load, RECHECK_MS);
    return () => clearTimeout(timer);
  });

  $effect(() => {
    if (step !== "done") return;
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    const tick = async () => {
      try {
        const [j, s] = await Promise.all([get<{ items: Job[] }>("/admin/jobs", { queue: "scan", limit: 1 }), get<Stats>("/admin/stats")]);
        job = j.items[0] ?? null;
        stats = s;
      } catch {
        /* the next tick tries again */
      }
      if (!stopped) timer = setTimeout(tick, 1500);
    };
    tick();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  });
</script>

{#snippet command(text: string)}
  <div class="command">
    <code>{text}</code>
    <button class="btn small ghost" type="button" onclick={() => copy(text)}>{t("Kopieren")}</button>
  </div>
{/snippet}

<div class="wizard">
  <main>
    <header>
      <svg viewBox="0 0 64 64" width="32" height="32" aria-hidden="true"><g fill="currentColor"><rect x="14" y="26" width="6" height="12" rx="3" /><rect x="24" y="18" width="6" height="28" rx="3" /><rect x="34" y="12" width="6" height="40" rx="3" /><rect x="44" y="22" width="6" height="20" rx="3" /></g></svg>
      <ol aria-label={t("Schritte der Einrichtung")}>
        {#each steps as s, i (s.id)}
          <li class:now={i === current} class:past={i < current} aria-current={i === current ? "step" : undefined}>
            <span class="dot" aria-hidden="true">{i < current ? "✓" : i + 1}</span><span class="name">{s.label}</span>
          </li>
        {/each}
      </ol>
      <select class="lang" aria-label="Sprache / Language" value={i18n.lang} onchange={(e) => chooseLanguage(e.currentTarget.value as Lang)}>
        {#each Object.entries(LANGUAGES) as [key, name] (key)}<option value={key}>{name}</option>{/each}
      </select>
    </header>

    {#if reconnecting}<p class="banner" role="status">{t("audium startet gerade neu … Diese Seite macht gleich von selbst weiter.")}</p>{/if}

    {#if !info}
      {#if !reconnecting}<p class="set-note">{t("Lädt …")}</p>{/if}
    {:else if step === "music"}
      <h1>{t("Wo liegt deine Musik?")}</h1>
      {#if hasMusic}
        <p class="lead">{t("audium hat Musik gefunden. Wähle aus, was in deine Bibliothek soll. Deine Dateien werden nie verändert.")}</p>
      {:else if probing > 0 && !folders.some((f) => probes[f])}
        <p class="lead">{t("audium sucht nach Musik …")}</p>
      {:else}
        <p class="lead"><strong>{t("audium sieht noch keine Musik.")}</strong> {t("Es läuft in einem Docker-Container und sieht nur Ordner, die du ihm freigibst. Du hast zwei Möglichkeiten. Diese Seite merkt von selbst, wenn es geklappt hat.")}</p>
        <div class="set-card help">
          <div class="set-row">
            <div class="set-label">
              <strong>{t("Am einfachsten: Musik in den Ordner „music“ legen")}</strong>
              <small>{t("Wenn du nichts weiter eingestellt hast, gibt es neben der Datei")} <code>{t("docker-compose.yml")}</code> {t("einen Ordner")} <code>{t("music")}</code>{t(". Kopiere deine Musik einfach dorthin.")}</small>
            </div>
          </div>
          <div class="set-row host">
            <div class="set-label">
              <strong>{t("Oder: einen vorhandenen Ordner freigeben")}</strong>
              <small>{t("Wo liegt deine Musik auf dem Server?")}</small>
              <input bind:value={hostPath} placeholder={t(t("/pfad/zu/deiner/musik"))} aria-label={t("Musikordner auf dem Server")} autocomplete="off" autocapitalize="none" spellcheck="false" />
              <details open>
                <summary>{t("Mit docker compose")}</summary>
                <ol class="howto">
                  <li>{t("Trage diese Zeile in die Datei")} <code>{t(".env")}</code> {t("neben")} <code>{t("docker-compose.yml")}</code> {t("ein:")} {@render command(envLine)}</li>
                  <li>{t("Starte audium im selben Ordner neu:")} {@render command("docker compose up -d")}</li>
                </ol>
              </details>
              <details>
                <summary>{t("Mit Portainer, Unraid oder Synology")}</summary>
                <p class="note">{t("Bearbeite den audium-Container und ergänze bei den Volumes oder Ordnern:")} {t("Pfad auf dem Server")} <code>{hostPath.trim() || t("/pfad/zu/deiner/musik")}</code>, {t("Pfad im Container")} <code>/music/main</code>, {t("nur lesen. Starte ihn danach neu.")}</p>
              </details>
            </div>
          </div>
        </div>
      {/if}

      {#if folders.length}
        <div class="folders">
          {#each folders as path (path)}
            {@const p = probes[path]}
            {@const mount = mountOf(path)}
            <div class="set-card folder">
              <div class="set-row">
                <input
                  type="checkbox"
                  aria-label={t("{path} in die Bibliothek", { path })}
                  checked={isRoot(path) || selected.includes(path)}
                  disabled={isRoot(path) || (!!p && !p.readable)}
                  onchange={(e) => toggle(path, e.currentTarget.checked)}
                />
                <div class="set-label">
                  <strong class="set-mono">{path}</strong>
                  {#if probeErrors[path]}
                    <small class="set-warn">{probeErrors[path]}</small>
                  {:else if !p}
                    <small>{t("Wird geprüft …")}</small>
                  {:else if p.readable}
                    <small>
                      {#if isRoot(path)}{t("Schon in der Bibliothek.")} {/if}
                      {#if p.audio_files}
                        {summary(p)}<br />{formats(p)}<br />
                        {t("{folders} mit Musik, davon {covers} mit Coverbild", { folders: plural(p.folders_with_music, "Ordner", "Ordner"), covers: p.folders_with_cover })}
                      {/if}
                    </small>
                  {/if}
                </div>
              </div>
              {#if p?.warnings.length || (mount && (mount.network || !mount.read_only))}
                <ul class="warnings">
                  {#each p?.warnings ?? [] as w (w)}<li class="set-warn">{WARNINGS[w] ? t(WARNINGS[w]) : w}</li>{/each}
                  {#if mount?.network}<li>{t("Das ist eine Netzwerkfreigabe. Der erste Scan kann etwas länger dauern.")}</li>{/if}
                  {#if mount && !mount.read_only}
                    <li>{t("audium könnte in diesen Ordner schreiben. Es tut das nie, aber sicherer ist es, ihn nur zum Lesen freizugeben (")}<code>{t(":ro")}</code> {t("am Ende der Volume-Zeile).")}</li>
                  {/if}
                </ul>
              {/if}
              {#if p && !p.readable}
                <details class="more">
                  <summary>{t("Details und Lösung")}</summary>
                  <p class="note">
                    {t("audium läuft als Nutzer")} <code>{p.container_user ?? "1000:1000"}</code>{t(", der Ordner gehört")} <code>{p.owner ?? "?"}</code> {t("(Rechte")} <code>{p.mode ?? "?"}</code>{t("). Das hier gibt allen Lesezugriff. Führe es auf dem Server aus, mit deinem Ordner statt des Beispielpfads:")}
                  </p>
                  {@render command(`sudo chmod -R a+rX ${hostPath.trim() || t("/pfad/zu/deiner/musik")}`)}
                </details>
              {/if}
              {#if p?.unreadable_examples.length}
                <details class="more">
                  <summary>{t("{folders} nicht lesbar", { folders: plural(p.unreadable_folders, "Unterordner", "Unterordner") })}</summary>
                  <ul class="samples">{#each p.unreadable_examples as u (u)}<li class="set-mono">{u}</li>{/each}</ul>
                </details>
              {/if}
              {#if p?.samples.length}
                <details class="more">
                  <summary>{t("Beispiele ansehen")}</summary>
                  <ul class="samples">
                    {#each p.samples as s (s.path)}
                      <li>
                        {#if s.tagged}<strong>{s.artist}</strong> – {s.title}{#if s.album} <span class="muted">({s.album})</span>{/if}
                        {:else}<span class="set-mono">{s.path}</span> <span class="muted">{t("(keine Angaben)")}</span>{/if}
                      </li>
                    {/each}
                  </ul>
                </details>
              {/if}
            </div>
          {/each}
        </div>
      {/if}

      <button class="btn ghost other" onclick={() => browse()}><Icon name="folder" size={16} /> {t("Anderen Ordner wählen")}</button>

      <footer>
        <button class="btn ghost" disabled={busy} onclick={skip}>{info.pending ? t("Überspringen") : t("Schließen")}</button>
        <button class="btn primary" disabled={!canGoOn} onclick={() => go("features")}>{t("Weiter")}</button>
      </footer>
    {:else if step === "features"}
      <h1>{t("Was soll audium tun?")}</h1>
      <p class="lead">{t("Die Voreinstellungen passen für die meisten. Du kannst alles später unter Einstellungen ändern.")}</p>
      {#if !server || !env}
        <p class="set-note">{t("Lädt …")}</p>
      {:else}
        <section class="set-group">
          <h2>{t("Audioanalyse")}</h2>
          <div class="set-card">
            {#if info.analysis_available}
              <label class="set-row">
                <span class="set-label">
                  <strong>{t("Musik analysieren")}</strong>
                  <small>{t("Erkennt Tempo, Stimmung und Klang für Radio, Mixe und „Ähnliche Titel“. Läuft im Hintergrund mit niedriger Priorität, Musikhören geht immer vor. Große Sammlungen brauchen dafür Tage.")}</small>
                </span>
                <input type="checkbox" class="toggle" checked={server.analysis_paused === "off"} onchange={(e) => save({ analysis_paused: e.currentTarget.checked ? "off" : "on" })} />
              </label>
              {#if server.analysis_paused === "off"}
                <div class="set-row">
                  <div class="set-label"><strong>{t("Gleichzeitige Analysen")}</strong><small>{tn(info.cpus, "Jede nutzt einen CPU-Kern. Der Server hat {n} Kern. Mehr geht schneller, macht den Server aber lauter.", "Jede nutzt einen CPU-Kern. Der Server hat {n} Kerne. Mehr geht schneller, macht den Server aber lauter.")}</small></div>
                  <select aria-label={t("Gleichzeitige Analysen")} value={server.analysis_workers} onchange={(e) => save({ analysis_workers: e.currentTarget.value })}>
                    <option value="default">{t("Standard")}</option>
                    {#each workerChoices as n (n)}<option value={n}>{n}</option>{/each}
                  </select>
                </div>
                <label class="set-row">
                  <span class="set-label"><strong>{t("Nur nachts")}</strong><small>{t("Von {from} bis {until} Uhr, wenn der Server sonst nichts zu tun hat.", { from: Number(server.analysis_from), until: Number(server.analysis_until) })}</small></span>
                  <input type="checkbox" class="toggle" checked={server.analysis_schedule === "window"} onchange={(e) => save({ analysis_schedule: e.currentTarget.checked ? "window" : "always" })} />
                </label>
              {/if}
            {:else}
              <div class="set-row"><span class="set-label">
                <strong>{t("Auf diesem Server nicht verfügbar")}</strong>
                <small>{t("Die Audioanalyse gibt es nur für x86_64-Prozessoren. Auto-Playlists nach Genre und Jahrzehnt und das Radio nach Genre und Jahr funktionieren trotzdem.")}</small>
              </span></div>
            {/if}
          </div>
        </section>

        <section class="set-group">
          <h2>{t("Verbindungen nach außen")}</h2>
          <div class="set-card">
            {#if info.analysis_available}
              <label class="set-row">
                <span class="set-label">
                  <strong>{t("Modelle für die Klangerkennung laden")}</strong>
                  <small>{t("Lädt einmalig rund 20 MB von essentia.upf.edu, für Stilrichtungen und „klingt ähnlich“. Dabei wird nichts über dich gesendet. Die Modelle sind nur für nicht-kommerzielle Nutzung freigegeben (CC BY-NC-SA).")}</small>
                </span>
                <input type="checkbox" class="toggle" disabled={!env.model_download_available} checked={env.model_download_available && server.model_download === "on"} onchange={(e) => save({ model_download: e.currentTarget.checked ? "on" : "off" })} />
              </label>
            {/if}
            <label class="set-row">
              <span class="set-label">
                <strong>{t("Ähnliche Künstler von ListenBrainz")}</strong>
                <small>{t("Verbessert das Radio. Gesendet werden nur Künstlernamen oder MusicBrainz-IDs, nichts über die Nutzer.")}</small>
              </span>
              <input type="checkbox" class="toggle" checked={listenBrainz} onchange={(e) => saveListenBrainz(e.currentTarget.checked)} />
            </label>
          </div>
        </section>

        <section class="set-group">
          <h2>{t("Apps")}</h2>
          <div class="set-card">
            <label class="set-row">
              <span class="set-label"><strong>{t("audium-Apps")}</strong><small>{t("Die audium-Apps für Desktop und Handy.")}</small></span>
              <input type="checkbox" class="toggle" checked={server.app_access === "on"} onchange={(e) => save({ app_access: e.currentTarget.checked ? "on" : "off" })} />
            </label>
            <label class="set-row">
              <span class="set-label"><strong>{t("Andere Musik-Apps (Subsonic)")}</strong><small>{t("Zum Beispiel Symfonium, Amperfy oder Feishin.")}</small></span>
              <input type="checkbox" class="toggle" disabled={!env.subsonic_available} checked={env.subsonic_available && server.subsonic_api === "on"} onchange={(e) => save({ subsonic_api: e.currentTarget.checked ? "on" : "off" })} />
            </label>
          </div>
        </section>
      {/if}

      <footer>
        <button class="btn ghost" onclick={() => go("music")}>{t("Zurück")}</button>
        {#if hints.length}
          <button class="btn primary" onclick={() => go("hints")}>{t("Weiter")}</button>
        {:else}
          <button class="btn primary" disabled={busy} onclick={finish}>{t("Einrichtung abschließen")}</button>
        {/if}
      </footer>
    {:else if step === "hints"}
      <h1>{t("Gut zu wissen")}</h1>
      <p class="lead">{t("Das musst du nicht jetzt erledigen. audium funktioniert auch so.")}</p>
      <div class="set-card">
        {#each hints as h (h.title)}
          <div class="set-row">
            <div class="set-label">
              <strong>{h.title}</strong>
              <small>{h.text}</small>
              {#if h.code}{@render command(h.code)}{/if}
            </div>
          </div>
        {/each}
      </div>
      <footer>
        <button class="btn ghost" onclick={() => go("features")}>{t("Zurück")}</button>
        <button class="btn primary" disabled={busy} onclick={finish}>{t("Einrichtung abschließen")}</button>
      </footer>
    {:else}
      <h1>{t("Fertig!")}</h1>
      {#if chose}
        {#if scanning}
          <p class="lead">{t("audium liest jetzt deine Musik ein. Du kannst schon loslegen, neue Titel erscheinen nach und nach.")}</p>
        {:else}
          <p class="lead">{t("audium hat deine Musik eingelesen.")}</p>
        {/if}
        <div class="set-card">
          <div class="set-row">
            <div class="set-label">
              <strong>{plural(stats?.tracks ?? 0, "Titel", "Titel")} · {plural(stats?.albums ?? 0, "Album", "Alben")} · {plural(stats?.artists ?? 0, "Künstler", "Künstler")}</strong>
              {#if scanning && job}
                <small>{t("{n} Dateien geprüft", { n: job.progress })}</small>
                <div class="set-progress" role="progressbar"><div class="indeterminate" style:width="100%"></div></div>
              {:else if job?.status === "failed"}
                <small class="set-warn">{t("Der Scan ist fehlgeschlagen: {error}", { error: job.error ?? "" })}</small>
              {/if}
            </div>
          </div>
        </div>
      {:else}
        <p class="lead">{t("Es ist noch keine Musik eingebunden. Das kannst du jederzeit unter Einstellungen → Musikordner nachholen.")}</p>
      {/if}

      <section class="set-group next">
        <h2>{t("Als Nächstes")}</h2>
        <div class="set-card">
          <a class="set-row link" href={href("/settings/users")}><span class="set-label"><strong>{t("Andere einladen")}</strong><small>{t("Familie und Freunde bekommen eigene Konten und Playlists.")}</small></span><Icon name="chevron" size={16} /></a>
          <a class="set-row link" href={href("/settings/apps")}><span class="set-label"><strong>{t("Apps verbinden")}</strong><small>{t("Musik auf dem Handy oder am Desktop hören.")}</small></span><Icon name="chevron" size={16} /></a>
        </div>
        <p class="set-note">{t("Denk an Backups: Sichere den Ordner")} <code>{t("data")}</code>{t(", darin liegen Konten, Playlists und Favoriten. Besonders wichtig sind")} <code>{t("audium.db")}</code> {t("und")} <code>{t("secret.key")}</code>.</p>
      </section>
      <footer>
        <span></span>
        <button class="btn primary" onclick={() => navigate("/", { replace: true })}>{t("Zur Musik")}</button>
      </footer>
    {/if}
  </main>
</div>

{#if browsing}
  <Modal title={t("Ordner wählen")} width={560} onclose={() => (browsing = null)}>
    <div class="crumb set-mono">{browsing.path}</div>
    <ul class="picker">
      {#if browsing.parent}
        <li><button class="pick" onclick={() => browse(browsing!.parent!)}><Icon name="back" size={16} /> ..</button></li>
      {/if}
      {#each browsing.folders as f (f.path)}
        <li><button class="pick" onclick={() => browse(f.path)}><Icon name="folder" size={16} /> {f.name}</button></li>
      {:else}
        <li class="set-note">{t("Keine Unterordner.")}</li>
      {/each}
    </ul>
    <p class="set-note">{t("audium sieht nur Ordner, die dem Container freigegeben sind.")}</p>
    <div class="modal-buttons">
      <button class="btn ghost" onclick={() => (browsing = null)}>{t("Abbrechen")}</button>
      <button class="btn primary" onclick={() => addFolder(browsing!.path)}>{t("Diesen Ordner prüfen")}</button>
    </div>
  </Modal>
{/if}

<style>
  .wizard {
    height: calc(100dvh - var(--frame-top, 0px));
    overflow-y: auto;
  }
  main {
    width: min(680px, 100%);
    margin: 0 auto;
    padding: 28px 16px 40px;
    display: flex;
    flex-direction: column;
  }
  header {
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 28px;
  }
  header > svg,
  header .lang {
    flex: none;
  }
  header .lang {
    align-self: flex-start;
    width: auto;
  }
  header ol {
    display: flex;
    flex: 1;
    flex-wrap: wrap;
    gap: 6px 14px;
    list-style: none;
    margin: 0;
    padding: 0;
    font-size: 0.82rem;
    color: var(--text-muted);
  }
  header li {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  header li.now {
    color: var(--text);
    font-weight: 600;
  }
  .dot {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    font-size: 0.72rem;
    background: var(--surface-1);
  }
  .now .dot,
  .past .dot {
    background: var(--accent);
    color: var(--accent-contrast);
  }
  h1 {
    font-size: 1.6rem;
    letter-spacing: -0.01em;
    margin: 0 0 8px;
  }
  .lead {
    color: var(--text-muted);
    line-height: 1.5;
    margin: 0 0 20px;
  }
  .lead strong {
    color: var(--text);
  }
  .banner {
    padding: 10px 14px;
    border-radius: var(--radius-sm);
    background: var(--surface-1);
    margin: 0 0 16px;
  }
  .help {
    margin-bottom: 16px;
  }
  .host input {
    margin: 8px 0 10px;
    width: 100%;
  }
  details {
    font-size: 0.88rem;
    color: var(--text-muted);
  }
  details + details {
    margin-top: 6px;
  }
  summary {
    cursor: pointer;
    color: var(--text);
    padding: 3px 0;
  }
  .howto {
    margin: 6px 0;
    padding-left: 20px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .note {
    margin: 6px 0;
    line-height: 1.5;
  }
  code {
    font-family: ui-monospace, monospace;
    font-size: 0.85em;
    overflow-wrap: anywhere;
  }
  .command {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 6px;
    padding: 6px 6px 6px 10px;
    border-radius: 8px;
    background: var(--surface-1);
  }
  .command code {
    flex: 1;
    min-width: 0;
    color: var(--text);
  }
  .command button {
    flex: none;
  }
  .folders {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .folder .set-row {
    align-items: flex-start;
  }
  .folder input[type="checkbox"] {
    flex: none;
    margin-top: 2px;
  }
  .warnings {
    list-style: none;
    margin: 0;
    padding: 0 16px 12px;
    font-size: 0.85rem;
    line-height: 1.45;
    color: var(--text-muted);
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .more {
    padding: 0 16px 10px;
  }
  .samples {
    list-style: none;
    margin: 6px 0 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
    overflow-wrap: anywhere;
  }
  .samples strong {
    color: var(--text);
    font-weight: 550;
  }
  .muted {
    color: var(--text-faint);
  }
  .other {
    align-self: flex-start;
    margin-top: 14px;
  }
  .next {
    margin-top: 24px;
  }
  .link {
    color: inherit;
    text-decoration: none;
  }
  footer {
    display: flex;
    justify-content: space-between;
    gap: 10px;
    margin-top: 28px;
  }
  .crumb {
    padding: 8px 10px;
    background: var(--surface-1);
    border-radius: var(--radius-sm);
  }
  .picker {
    list-style: none;
    padding: 0;
    margin: 10px 0;
    max-height: 340px;
    overflow-y: auto;
  }
  .pick {
    width: 100%;
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
  .pick:hover {
    background: var(--surface-1);
  }
  .modal-buttons {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  @media (max-width: 560px) {
    .name {
      display: none;
    }
    .now .name {
      display: inline;
    }
  }
</style>
