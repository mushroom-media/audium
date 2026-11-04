<script lang="ts">
  // Where radio stations and mixes take their tracks from (backend analysis/sources.py): a switch
  // and a weight per source, for the whole server. At least one source stays on.
  import { ApiError, get, patch } from "../../lib/api";
  import { toast } from "../../lib/ui.svelte";
  import { locale, msg, t } from "../../lib/i18n.svelte";

  type Name = "sound" | "features" | "genre" | "artists" | "taste";
  interface Source {
    on: boolean;
    weight: number;
  }
  interface Sources {
    sources: Record<Name, Source>;
    artists_pending: number;
    artists_known: number;
    options: { smooth_tempo: boolean };
  }

  const INFO: { name: Name; title: string; text: string }[] = [
    { name: "sound", title: msg("Klang"), text: msg("Ähnlich klingende Titel nach dem Klang-Fingerabdruck der Audioanalyse. Aus: auch keine Klang-Mixe.") },
    { name: "features", title: msg("Audio-Merkmale"), text: msg("Tempo, Energie, Tanzbarkeit, Stimmung. Aus: auch keine Mixe aus der Bibliothek.") },
    {
      name: "genre",
      title: msg("Genre & Jahr"),
      text: msg("Gleiche Genres (aus den Tags und von der Audioanalyse erkannt) oder derselbe Künstler; das Jahr entscheidet nur unter diesen, allein nie. Braucht keine Audioanalyse."),
    },
    { name: "artists", title: msg("Ähnliche Künstler (ListenBrainz)"), text: msg("Künstler, die Fans gemeinsam hören: Wer X mag, mag auch Y.") },
    {
      name: "taste",
      title: msg("Eigener Geschmack"),
      text: msg("Für jeden Nutzer eigen: Von den Titeln, die die anderen Quellen finden, rücken Favoriten (Titel, Album, Künstler) und oft Gehörtes nach vorn. Bringt selbst keine Titel ins Radio."),
    },
  ];

  let data = $state<Sources | null>(null);
  // Weights while a slider is dragged; saved when it is let go.
  let draft = $state<Partial<Record<Name, number>>>({});

  $effect(() => {
    get<Sources>("/admin/radio/sources").then((d) => (data = d));
  });

  const onCount = $derived(data ? Object.values(data.sources).filter((s) => s.on).length : 0);
  const weightOf = (n: Name) => draft[n] ?? data!.sources[n].weight;
  /** How much a source counts now, of all switched-on ones. */
  function share(n: Name): number {
    if (!data?.sources[n].on) return 0;
    const total = INFO.reduce((sum, i) => sum + (data!.sources[i.name].on ? weightOf(i.name) : 0), 0);
    return Math.round((100 * weightOf(n)) / (total || 1));
  }

  async function saveOption(change: Partial<Sources["options"]>) {
    try {
      data = await patch<Sources>("/admin/radio/options", change);
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("Speichern fehlgeschlagen"));
    }
  }

  async function save(n: Name, change: Partial<Source>) {
    try {
      data = await patch<Sources>("/admin/radio/sources", { [n]: change });
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("Speichern fehlgeschlagen"));
    }
    delete draft[n];
  }
</script>

<section class="set-group">
  <h2>{t("Quellen")}</h2>
  {#if data}
    <div class="set-card">
      {#each INFO as i (i.name)}
        {@const s = data.sources[i.name]}
        {@const last = s.on && onCount === 1}
        <div class="set-row source" class:off={!s.on}>
          <label class="head">
            <span class="set-label">
              <strong>{t(i.title)}</strong>
              <small>{t(i.text)}</small>
            </span>
            <input
              type="checkbox"
              class="toggle"
              checked={s.on}
              disabled={last}
              title={last ? t("Mindestens eine Quelle bleibt an") : undefined}
              onchange={(e) => save(i.name, { on: e.currentTarget.checked })}
            />
          </label>
          <div class="weight">
            <input
              type="range"
              min="1"
              max="100"
              value={weightOf(i.name)}
              disabled={!s.on}
              aria-label={t("Gewicht {source}", { source: t(i.title) })}
              style:--p="{weightOf(i.name)}%"
              oninput={(e) => (draft[i.name] = +e.currentTarget.value)}
              onchange={(e) => save(i.name, { weight: +e.currentTarget.value })}
            />
            <span class="pct">{s.on ? `${share(i.name)} %` : t("aus")}</span>
          </div>
          {#if i.name === "artists"}
            <p class="hint">
              {t("Beim Einschalten schickt audium die Namen bzw. MusicBrainz-IDs der Künstler deiner Bibliothek an ListenBrainz, für Künstler ohne ID in den Tags auch an MusicBrainz. Was die Nutzer hören, bleibt auf dem Server.")}
              {#if s.on}<br />{t("{n} Künstler mit Ergebnis", { n: data.artists_known })}{#if data.artists_pending}, {t("{n} noch nicht abgefragt (etwa ein Künstler pro Sekunde)", { n: data.artists_pending })}{/if}.{/if}
            </p>
          {/if}
        </div>
      {/each}
    </div>
    <p class="set-note">
      {t("Radio, „Ähnliche Titel“ und die Subsonic-Apps mischen ihre Titel aus den eingeschalteten Quellen. Der Regler legt fest, wie stark eine Quelle zählt; die Prozentzahl zeigt ihren Anteil an allen eingeschalteten. Titel, die mehrere Quellen vorschlagen, kommen zuerst. Findet keine eingeschaltete Quelle etwas (z. B. vor der Audioanalyse), springen Genre & Jahr ein.")}
    </p>
    <h2 class="sub">{t("Reihenfolge")}</h2>
    <div class="set-card">
      <label class="set-row">
        <span class="set-label">
          <strong>{t("Keine großen Tempo-Sprünge")}</strong>
          <small>{t("Von den nächsten Titeln eines Radios kommt der zuerst, dessen BPM am besten zum vorigen passt. Halbes und doppeltes Tempo (70 und 140 BPM) gelten als passend. Braucht die Audioanalyse.")}</small>
        </span>
        <input type="checkbox" class="toggle" checked={data.options.smooth_tempo} onchange={(e) => saveOption({ smooth_tempo: e.currentTarget.checked })} />
      </label>
    </div>
    <p class="set-note">
      {t("Überspringt jemand einen Titel in den ersten 30 Sekunden eines Radios, kommt er bei dieser Person in ähnlichen Radios seltener: im selben Radio deutlich, in Radios zu denselben Künstlern etwas weniger, bei laut ListenBrainz ähnlichen Künstlern nur leicht. Nach zwei Monaten zählt ein Überspringen nur noch halb, nach einem halben Jahr gar nicht mehr. Zufallswiedergabe, Playlists und „Ähnliche Titel“ bleiben davon unberührt.")}
    </p>
    <p class="set-note">{t("Warum ein Titel in einem Radio, bei „Ähnliche Titel“ oder in einer Auto-Playlist ist, sehen nur Admins, in der Spalte rechts neben dem Titel.")}</p>
  {:else}
    <p class="set-note">{t("Lädt …")}</p>
  {/if}
</section>

<style>
  .source {
    flex-direction: column;
    align-items: stretch;
    gap: 6px;
  }
  .head {
    display: flex;
    align-items: center;
    gap: 14px;
  }
  .head .set-label {
    flex: 1;
  }
  .weight {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .weight input {
    flex: 1;
  }
  /* Unlike the seek bar, a setting shows where its knob is. */
  .weight input::-webkit-slider-thumb {
    opacity: 1;
  }
  .weight input::-moz-range-thumb {
    opacity: 1;
  }
  .pct {
    width: 3.2em;
    text-align: right;
    font-variant-numeric: tabular-nums;
    color: var(--text-muted);
    font-size: 0.88rem;
  }
  .off .weight {
    opacity: 0.45;
  }
  h2.sub {
    margin-top: 22px;
  }
  .hint {
    margin: 2px 0 0;
    color: var(--text-muted);
    font-size: 0.84rem;
    line-height: 1.45;
  }
</style>
