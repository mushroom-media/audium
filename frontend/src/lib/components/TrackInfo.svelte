<script lang="ts">
  // "Info" from the track menu: tags, file, genres, the audio analysis and the own plays.
  import { get, type TrackInfo } from "../api";
  import { ago, duration } from "../format";
  import ArtistLinks from "./ArtistLinks.svelte";
  import Modal from "./Modal.svelte";
  import { locale, msg, num, t } from "../i18n.svelte";

  let { trackId, onclose }: { trackId: number; onclose: () => void } = $props();

  let info = $state<TrackInfo | null>(null);
  let failed = $state(false);

  $effect(() => {
    info = null;
    failed = false;
    get<TrackInfo>(`/tracks/${trackId}/info`).then(
      (i) => (info = i),
      () => (failed = true),
    );
  });

  type Value = "energy" | "danceability" | "brightness" | "dynamics" | "mood_happy" | "mood_sad" | "mood_aggressive" | "mood_relaxed";
  // The analysis' 0..1 values as bars; moods only where the mood models ran.
  const BARS: { key: Value; label: string }[] = [
    { key: "energy", label: msg("Energie") },
    { key: "danceability", label: msg("Tanzbarkeit") },
    { key: "brightness", label: msg("Helligkeit") },
    { key: "dynamics", label: msg("Dynamik") },
    { key: "mood_happy", label: msg("Fröhlich") },
    { key: "mood_sad", label: msg("Melancholisch") },
    { key: "mood_aggressive", label: msg("Kraftvoll") },
    { key: "mood_relaxed", label: msg("Entspannt") },
  ];

  const pct = (v: number) => `${Math.round(v * 100)} %`;
  const date = (ms: number) => new Date(ms).toLocaleDateString(locale(), { day: "numeric", month: "long", year: "numeric" });
  const comma = (n: number, digits: number) => num(n, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  const size = (bytes: number) => (bytes >= 1e9 ? `${comma(bytes / 1e9, 2)} GB` : `${comma(bytes / 1e6, 1)} MB`);

  function format(track: TrackInfo["track"]): string {
    const bits = [
      (track.codec ?? track.container ?? "").toUpperCase(),
      track.bitrate ? `${Math.round(track.bitrate / 1000)} kbit/s` : "",
      track.sample_rate ? `${num(track.sample_rate / 1000)} kHz` : "",
      track.bit_depth ? `${track.bit_depth} Bit` : "",
      track.channels === 1 ? "Mono" : track.channels === 2 ? "Stereo" : track.channels ? t("{n} Kanäle", { n: track.channels }) : "",
    ];
    return bits.filter(Boolean).join(" · ");
  }
  function gains(track: TrackInfo["track"]): string {
    const db = (v: number) => `${v > 0 ? "+" : ""}${comma(v, 1)} dB`;
    const rg = track.replaygain;
    return [rg.track_gain != null ? t("Titel {gain}", { gain: db(rg.track_gain) }) : "", rg.album_gain != null ? t("Album {gain}", { gain: db(rg.album_gain) }) : ""]
      .filter(Boolean)
      .join(" · ");
  }
</script>

<Modal title={info?.track.title ?? "Info"} {onclose} width={520}>
  {#if failed}
    <p class="muted">{t("Die Infos konnten nicht geladen werden.")}</p>
  {:else if !info}
    <p class="muted">{t("Lädt …")}</p>
  {:else}
    {@const tr = info.track}
    {@const a = info.analysis}
    <dl>
      <dt>{t("Künstler|einzeln")}</dt>
      <dd><ArtistLinks track={tr} onfollow={onclose} /></dd>
      <dt>{t("Album")}</dt>
      <dd>{tr.album}{#if tr.track_no}&ensp;·&ensp;{t("Titel {n}", { n: tr.track_no })}{#if tr.disc_no && tr.disc_no > 1}, {t("CD {n}", { n: tr.disc_no })}{/if}{/if}</dd>
      {#if tr.date || tr.year}<dt>{t("Erschienen")}</dt><dd>{tr.date ?? tr.year}</dd>{/if}
      <dt>{t("Länge")}</dt>
      <dd>{duration(tr.duration_ms)}</dd>
    </dl>

    <h3>{t("Genres")}</h3>
    {#if info.genres.length}
      <div class="chips">
        {#each info.genres as g (g.name)}
          <span class="chip" class:detected={g.detected} title={g.detected ? t("Erkannt ({share})", { share: pct(g.weight) }) : t("Aus den Tags")}>{g.name}</span>
        {/each}
      </div>
      {#if info.genres.some((g) => g.detected)}<p class="hint">{t("Umrandet: von der Audioanalyse erkannt, die anderen stehen in den Tags.")}</p>{/if}
    {:else}
      <p class="muted">{t("Keine.")}</p>
    {/if}
    {#if info.styles.length}
      <p class="sub">{t("Erkannte Stilrichtungen")}</p>
      <ul class="bars">
        {#each info.styles as s (s.name)}
          <li>
            <span class="name">{s.name} <small>{s.parent}</small></span>
            <span class="bar"><i style:width={pct(s.prob)}></i></span>
            <span class="num">{pct(s.prob)}</span>
          </li>
        {/each}
      </ul>
    {:else if info.styles_unclear}
      <p class="sub">{t("Erkannte Stilrichtungen")}</p>
      <p class="muted">{t("Keine eindeutige Stilrichtung.")}</p>
    {/if}

    <h3>{t("Audioanalyse")}</h3>
    {#if !a}
      <p class="muted">{t("Noch nicht analysiert.")}</p>
    {:else if a.status === "failed"}
      <p class="muted">{t("Die Analyse ist für diesen Titel fehlgeschlagen.")}</p>
    {:else}
      <dl>
        {#if a.bpm}<dt>{t("Tempo")}</dt><dd><strong>{Math.round(a.bpm)} BPM</strong></dd>{/if}
        {#if a.key}<dt>{t("Tonart")}</dt><dd>{a.key}</dd>{/if}
      </dl>
      <ul class="bars">
        {#each BARS as b (b.key)}
          {@const v = a[b.key]}
          {#if v != null}
            <li>
              <span class="name">{t(b.label)}</span>
              <span class="bar"><i style:width={pct(v)}></i></span>
              <span class="num">{pct(v)}</span>
            </li>
          {/if}
        {/each}
      </ul>
      <p class="hint">{a.sound ? t("Analysiert {when}, mit Klang-Fingerabdruck.", { when: ago(a.analyzed_at) }) : t("Analysiert {when}.", { when: ago(a.analyzed_at) })}</p>
    {/if}

    <h3>{t("Du")}</h3>
    <dl>
      <dt>{t("Gehört")}</dt>
      <dd>{info.plays === 0 || !info.last_played ? t("noch nie") : t("{n}×, zuletzt {when}", { n: info.plays, when: ago(info.last_played) })}</dd>
      <dt>{t("Lieblingssong")}</dt>
      <dd>{info.favorite ? "Ja" : "Nein"}</dd>
    </dl>

    <h3>{t("Datei")}</h3>
    <dl>
      <dt>{t("Format")}</dt>
      <dd>{format(tr)}</dd>
      <dt>{t("Größe")}</dt>
      <dd>{size(tr.size)}</dd>
      {#if gains(tr)}<dt>ReplayGain</dt><dd>{gains(tr)}</dd>{/if}
      <dt>{t("Hinzugefügt")}</dt>
      <dd>{date(tr.added_at)}</dd>
      <dt>{t("Pfad")}</dt>
      <dd class="path">{tr.path}</dd>
    </dl>
  {/if}
  <div class="actions"><button class="btn" onclick={onclose}>{t("Schließen")}</button></div>
</Modal>

<style>
  h3 {
    margin: 20px 0 8px;
    font-size: 0.78rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-muted);
  }
  dl {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 4px 14px;
    margin: 0;
    font-size: 0.92rem;
  }
  dt {
    color: var(--text-muted);
  }
  dd {
    margin: 0;
    min-width: 0;
  }
  .path {
    word-break: break-all;
    font-size: 0.85rem;
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .chip {
    padding: 3px 10px;
    border-radius: 999px;
    background: var(--surface-2);
    font-size: 0.85rem;
  }
  .chip.detected {
    background: transparent;
    box-shadow: inset 0 0 0 1px var(--accent);
  }
  .sub {
    margin: 12px 0 0;
    font-size: 0.85rem;
    color: var(--text-muted);
  }
  .bars {
    list-style: none;
    margin: 8px 0 0;
    padding: 0;
    display: grid;
    gap: 6px;
    font-size: 0.9rem;
  }
  .bars li {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(60px, 120px) 3.2em;
    align-items: center;
    gap: 10px;
  }
  .name small {
    color: var(--text-muted);
    margin-left: 4px;
  }
  .bar {
    height: 6px;
    border-radius: 3px;
    background: var(--surface-2);
    overflow: hidden;
  }
  .bar i {
    display: block;
    height: 100%;
    background: var(--accent);
  }
  .num {
    text-align: right;
    font-variant-numeric: tabular-nums;
    color: var(--text-muted);
    font-size: 0.85rem;
  }
  .muted,
  .hint {
    color: var(--text-muted);
    font-size: 0.85rem;
    margin: 6px 0 0;
  }
  .actions {
    display: flex;
    justify-content: flex-end;
    margin-top: 20px;
  }
</style>
