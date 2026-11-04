"""Short explanations why a track is in an auto-playlist, e.g. "128 BPM · hohe Energie" (German
or English, see audium/i18n.py)."""

from audium.i18n import tr

# German note names; English keeps the usual ones (C#, Bb, B)
_KEY_DE = {"C": "C", "C#": "Cis", "D": "D", "Eb": "Es", "E": "E", "F": "F", "F#": "Fis", "G": "G", "Ab": "As",
           "A": "A", "Bb": "B", "B": "H"}  # fmt: skip
_MOODS = {
    "mood_happy": "fröhlich",
    "mood_sad": "melancholisch",
    "mood_aggressive": "kraftvoll",
    "mood_relaxed": "entspannt",
}


def level(value: float | None, high: str, low: str | None = None, hi: float = 0.66, lo: float = 0.34) -> str | None:
    if value is None:
        return None
    if value >= hi:
        return high
    if low and value <= lo:
        return low
    return None


def key_name(key: str | None, mode: str | None, lang: str = "de") -> str | None:
    if not key:
        return None
    name = _KEY_DE.get(key, key) if lang == "de" else key
    if mode == "minor":
        return tr(lang, "{key}-Moll", key=name.lower() if lang == "de" else name)
    if mode == "major":
        return tr(lang, "{key}-Dur", key=name)
    return name


def _word(get, f: str) -> str | None:
    """The German word for one feature of a track, or None when it is unremarkable."""
    if f == "energy":
        return level(get("energy"), "hohe Energie", "ruhig")
    if f == "danceability":
        return level(get("danceability"), "tanzbar", hi=0.6)
    if f == "brightness":
        return level(get("brightness"), "heller Klang", "warmer Klang")
    if f == "dynamics":
        return level(get("dynamics"), "dynamisch", "gleichmäßig")
    if f.startswith("mood_"):
        return level(get(f), _MOODS[f], hi=0.6)
    return None


def describe(features, fields: tuple[str, ...] = ("bpm", "energy", "danceability"), lang: str = "de") -> str:
    """`features` is any mapping/row with the track_features columns."""
    get = features.get if hasattr(features, "get") else lambda k: getattr(features, k, None)
    parts: list[str | None] = []
    for f in fields:
        if f == "bpm":
            parts.append(f"{round(get('bpm'))} BPM" if get("bpm") else None)
        elif f == "key":
            parts.append(key_name(get("key"), get("mode"), lang))
        else:
            word = _word(get, f)
            parts.append(tr(lang, word) if word else None)
    return " · ".join(p for p in parts if p)
