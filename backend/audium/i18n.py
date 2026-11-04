"""Texts audium writes itself (playlist names, reasons, labels, job messages), in German or English.

Like the web UI (frontend/src/lib/i18n.svelte.ts), the German text is the key: tr("en", "Oft gehört")
looks it up in EN, tr("de", ...) returns it as it is. Placeholders use str.format: tr(lang, "Die
{d}er", d=90). A text without an English entry stays German, so nothing is lost.

Which language: a user's own setting, else the server language (services/settings.py,
services/server_settings.py). Texts nobody in particular reads (job messages) follow the server.
"""

from sqlalchemy import Connection

LANGS = ("de", "en")

EN: dict[str, str] = {
    # auto-playlists: built-in rules (analysis/autoplaylists.py)
    "Workout": "Workout",
    "Schnell und energiegeladen.": "Fast and full of energy.",
    "Zum Entspannen": "To relax",
    "Ruhig und langsam.": "Calm and slow.",
    "Party": "Party",
    "Tanzbar mit Druck.": "Danceable with punch.",
    "Konzentration": "Focus",
    "Gleichmäßig, nicht zu laut, warmer Klang.": "Even, not too loud, warm sound.",
    "Gute Laune": "Good mood",
    "Dur, flott und lebendig.": "Major key, upbeat and lively.",
    "Fröhlich": "Happy",
    "Melancholisch": "Melancholic",
    "Kraftvoll": "Powerful",
    "Entspannt": "Relaxed",
    # auto-playlists: mixes named after their traits
    "schnell": "fast",
    "langsam": "slow",
    "energiegeladen": "energetic",
    "ruhig": "calm",
    "tanzbar": "danceable",
    "hell": "bright",
    "warm": "warm",
    "dynamisch": "dynamic",
    "gleichmäßig": "even",
    "in Dur": "in major",
    "in Moll": "in minor",
    "fröhlich": "happy",
    "melancholisch": "melancholic",
    "kraftvoll": "powerful",
    "entspannt": "relaxed",
    "Mix: {traits}": "Mix: {traits}",
    "bunt gemischt": "all sorts",
    "Ähnlich klingende Titel aus deiner Bibliothek, automatisch gruppiert.": "Tracks from your library that sound alike, grouped automatically.",
    "Titel mit ähnlichem Klang-Fingerabdruck, automatisch gruppiert.": "Tracks with a similar sound fingerprint, grouped automatically.",
    # auto-playlists: genres, decades, styles (genre names are English, except this one)
    "Klassik": "Classical",
    "{names} und mehr.": "{names} and more.",
    "Alles aus dem Genre {name}.": "Everything from the genre {name}.",
    "Die {d}er": "The {d}s",
    "{name} der {d}er": "{name} of the {d}s",
    "Musik aus den Jahren {start} bis {end}.": "Music from the years {start} to {end}.",
    "{name} aus den Jahren {start} bis {end}.": "{name} from the years {start} to {end}.",
    "Vom Klang her als {name} erkannt.": "Recognized as {name} by its sound.",
    "Vom Klang her als {name} erkannt (gehört zu {genre}).": "Recognized as {name} by its sound (part of {genre}).",
    # why a track is where it is (analysis/explain.py, analysis/why.py), for admins
    "hohe Energie": "high energy",
    "heller Klang": "bright sound",
    "warmer Klang": "warm sound",
    "{key}-Dur": "{key} major",
    "{key}-Moll": "{key} minor",
    "Startpunkt": "Starting point",
    "Eigener Titel": "Own track",
    "Vom Album": "From the album",
    "Vom Künstler": "From the artist",
    "Klingt ähnlich": "Sounds similar",
    "Ähnliche Merkmale ({text})": "Similar features ({text})",
    "Ähnliche Merkmale": "Similar features",
    "Passt zu deinem Geschmack": "Fits your taste",
    "Fans von {via} hören auch {artist}": "Fans of {via} also listen to {artist}",
    "Fans hören auch": "Fans also listen to",
    "diese Band": "this band",
    "Genre: {text}": "Genre: {text}",
    "Genre/Jahr": "Genre/year",
    "Ersatz, {text}": "Fallback, {text}",
    " · in ähnlichem Radio übersprungen (× {factor})": " · skipped in a similar radio (× {factor})",
    # radio suggestions on the start page (services/radio_suggestions.py)
    "Oft gehört": "Played a lot",
    "Gerade viel gehört": "Played a lot lately",
    "Länger nicht gehört": "Not played for a while",
    "Aus deinen Lieblingssongs": "From your favorite songs",
    # recently played (services/personal.py)
    "von {name}": "by {name}",
    # Discover (services/discover.py)
    "Künstler": "Artist",
    # rule fields (analysis/rules.py)
    "Genre": "Genre",
    "Stil (erkannt)": "Style (detected)",
    "Album": "Album",
    "Titel": "Title",
    "Jahr": "Year",
    "Hinzugefügt vor (Tage)": "Added (days ago)",
    "Länge": "Length",
    "Tempo": "Tempo",
    "Energie": "Energy",
    "Tanzbarkeit": "Danceability",
    "Klangfarbe (hell)": "Timbre (bright)",
    "Dynamik": "Dynamics",
    "Tonart": "Key",
    "Tongeschlecht": "Mode",
    "Traurig": "Sad",
    "Aggressiv": "Aggressive",
    # job messages (analysis/tasks.py, scanner/tasks.py)
    "Modelle werden geladen": "Loading the models",
    "Analyse startet": "Analysis is starting",
    "{done} von {total} analysiert · {last}": "{done} of {total} analyzed · {last}",
    "Genres werden vereinheitlicht": "Unifying genres",
    "Auto-Playlists werden erzeugt": "Generating auto playlists",
    "Ähnliche Künstler werden abgefragt": "Fetching similar artists",
    # devices (api/devices.py)
    "Unbekanntes Gerät": "Unknown device",
}


def tr(lang: str, de: str, **params) -> str:
    """`de` in `lang`, with its {placeholders} filled in."""
    text = EN.get(de, de) if lang == "en" else de
    return text.format(**params) if params else text


def server_language(conn: Connection) -> str:
    from audium.services.server_settings import server_setting

    return server_setting(conn, "language")


def user_language(conn: Connection, user_id: int) -> str:
    """The language a user sees: their own choice, else the server language."""
    from audium.services.settings import get_settings

    lang = get_settings(conn, user_id)["language"]
    return server_language(conn) if lang == "server" else lang
