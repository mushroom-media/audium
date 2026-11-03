<script lang="ts">
  // "Info" from the track menu: tags, file, genres, the audio analysis and the own plays.
  import { get, type TrackInfo } from "../api";
  import { ago, duration } from "../format";
  import Modal from "./Modal.svelte";

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
    { key: "energy", label: "Energie" },
    { key: "danceability", label: "Tanzbarkeit" },
    { key: "brightness", label: "Helligkeit" },
    { key: "dynamics", label: "Dynamik" },
    { key: "mood_happy", label: "Fröhlich" },
    { key: "mood_sad", label: "Melancholisch" },
    { key: "mood_aggressive", label: "Kraftvoll" },
    { key: "mood_relaxed", label: "Entspannt" },
  ];

  const pct = (v: number) => `${Math.round(v * 100)} %`;
  const date = (ms: number) => new Date(ms).toLocaleDateString("de-DE", { day: "numeric", month: "long", year: "numeric" });
  const comma = (n: number, digits: number) => n.toFixed(digits).replace(".", ",");
  const size = (bytes: number) => (bytes >= 1e9 ? `${comma(bytes / 1e9, 2)} GB` : `${comma(bytes / 1e6, 1)} MB`);

  function format(t: TrackInfo["track"]): string {
    const bits = [
      (t.codec ?? t.container ?? "").toUpperCase(),
      t.bitrate ? `${Math.round(t.bitrate / 1000)} kbit/s` : "",
      t.sample_rate ? `${(t.sample_rate / 1000).toLocaleString("de-DE")} kHz` : "",
      t.bit_depth ? `${t.bit_depth} Bit` : "",
      t.channels === 1 ? "Mono" : t.channels === 2 ? "Stereo" : t.channels ? `${t.channels} Kanäle` : "",
    ];
    return bits.filter(Boolean).join(" · ");
  }
  function gains(t: TrackInfo["track"]): string {
    const db = (v: number) => `${v > 0 ? "+" : ""}${comma(v, 1)} dB`;
    const rg = t.replaygain;
    return [rg.track_gain != null ? `Titel ${db(rg.track_gain)}` : "", rg.album_gain != null ? `Album ${db(rg.album_gain)}` : ""]
      .filter(Boolean)
      .join(" · ");
  }
</script>

<Modal title={info?.track.title ?? "Info"} {onclose} width={520}>
  {#if failed}
    <p class="muted">Die Infos konnten nicht geladen werden.</p>
  {:else if !info}
    <p class="muted">Lädt …</p>
  {:else}
    {@const t = info.track}
    {@const a = info.analysis}
    <dl>
      <dt>Künstler</dt>
      <dd>{t.artist}</dd>
      <dt>Album</dt>
      <dd>{t.album}{#if t.track_no}&ensp;·&ensp;Titel {t.track_no}{#if t.disc_no && t.disc_no > 1}, CD {t.disc_no}{/if}{/if}</dd>
      {#if t.date || t.year}<dt>Erschienen</dt><dd>{t.date ?? t.year}</dd>{/if}
      <dt>Länge</dt>
      <dd>{duration(t.duration_ms)}</dd>
    </dl>

    <h3>Genres</h3>
    {#if info.genres.length}
      <div class="chips">
        {#each info.genres as g (g.name)}
          <span class="chip" class:detected={g.detected} title={g.detected ? `Erkannt (${pct(g.weight)})` : "Aus den Tags"}>{g.name}</span>
        {/each}
      </div>
      {#if info.genres.some((g) => g.detected)}<p class="hint">Umrandet: von der Audioanalyse erkannt, die anderen stehen in den Tags.</p>{/if}
    {:else}
      <p class="muted">Keine.</p>
    {/if}
    {#if info.styles.length}
      <p class="sub">Erkannte Stilrichtungen</p>
      <ul class="bars">
        {#each info.styles as s (s.name)}
          <li>
            <span class="name">{s.name} <small>{s.parent}</small></span>
            <span class="bar"><i style:width={pct(s.prob)}></i></span>
            <span class="num">{pct(s.prob)}</span>
          </li>
        {/each}
      </ul>
    {/if}

    <h3>Audioanalyse</h3>
    {#if !a}
      <p class="muted">Noch nicht analysiert.</p>
    {:else if a.status === "failed"}
      <p class="muted">Die Analyse ist für diesen Titel fehlgeschlagen.</p>
    {:else}
      <dl>
        {#if a.bpm}<dt>Tempo</dt><dd><strong>{Math.round(a.bpm)} BPM</strong></dd>{/if}
        {#if a.key}<dt>Tonart</dt><dd>{a.key}</dd>{/if}
      </dl>
      <ul class="bars">
        {#each BARS as b (b.key)}
          {@const v = a[b.key]}
          {#if v != null}
            <li>
              <span class="name">{b.label}</span>
              <span class="bar"><i style:width={pct(v)}></i></span>
              <span class="num">{pct(v)}</span>
            </li>
          {/if}
        {/each}
      </ul>
      <p class="hint">Analysiert {ago(a.analyzed_at)}{a.sound ? ", mit Klang-Fingerabdruck" : ""}.</p>
    {/if}

    <h3>Du</h3>
    <dl>
      <dt>Gehört</dt>
      <dd>{info.plays === 0 || !info.last_played ? "noch nie" : `${info.plays.toLocaleString("de-DE")}×, zuletzt ${ago(info.last_played)}`}</dd>
      <dt>Lieblingssong</dt>
      <dd>{info.favorite ? "Ja" : "Nein"}</dd>
    </dl>

    <h3>Datei</h3>
    <dl>
      <dt>Format</dt>
      <dd>{format(t)}</dd>
      <dt>Größe</dt>
      <dd>{size(t.size)}</dd>
      {#if gains(t)}<dt>ReplayGain</dt><dd>{gains(t)}</dd>{/if}
      <dt>Hinzugefügt</dt>
      <dd>{date(t.added_at)}</dd>
      <dt>Pfad</dt>
      <dd class="path">{t.path}</dd>
    </dl>
  {/if}
  <div class="actions"><button class="btn" onclick={onclose}>Schließen</button></div>
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
