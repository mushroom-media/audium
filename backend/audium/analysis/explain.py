"""Short German explanations why a track is in an auto-playlist, e.g. "128 BPM · hohe Energie"."""

_KEY_DE = {"C": "C", "C#": "Cis", "D": "D", "Eb": "Es", "E": "E", "F": "F", "F#": "Fis", "G": "G", "Ab": "As",
           "A": "A", "Bb": "B", "B": "H"}  # fmt: skip


def level(value: float | None, high: str, low: str | None = None, hi: float = 0.66, lo: float = 0.34) -> str | None:
    if value is None:
        return None
    if value >= hi:
        return high
    if low and value <= lo:
        return low
    return None


def key_name(key: str | None, mode: str | None) -> str | None:
    if not key:
        return None
    name = _KEY_DE.get(key, key)
    if mode == "minor":
        return f"{name.lower()}-Moll"
    if mode == "major":
        return f"{name}-Dur"
    return name


def describe(features, fields: tuple[str, ...] = ("bpm", "energy", "danceability")) -> str:
    """`features` is any mapping/row with the track_features columns."""
    get = features.get if hasattr(features, "get") else lambda k: getattr(features, k, None)
    parts: list[str] = []
    for f in fields:
        if f == "bpm" and get("bpm"):
            parts.append(f"{round(get('bpm'))} BPM")
        elif f == "energy":
            parts.append(level(get("energy"), "hohe Energie", "ruhig"))
        elif f == "danceability":
            parts.append(level(get("danceability"), "tanzbar", hi=0.6))
        elif f == "brightness":
            parts.append(level(get("brightness"), "heller Klang", "warmer Klang"))
        elif f == "dynamics":
            parts.append(level(get("dynamics"), "dynamisch", "gleichmäßig"))
        elif f == "key":
            parts.append(key_name(get("key"), get("mode")))
        elif f.startswith("mood_"):
            labels = {"mood_happy": "fröhlich", "mood_sad": "melancholisch", "mood_aggressive": "kraftvoll",
                      "mood_relaxed": "entspannt"}  # fmt: skip
            parts.append(level(get(f), labels[f], hi=0.6))
    return " · ".join(p for p in parts if p)
