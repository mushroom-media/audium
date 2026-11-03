"""Genre tags -> a small, consistent set of genre names.

Tags in the wild: "Rock; Pop", "Hip Hop", "hiphop", "Hip-Hop/Rap", "(17)" (ID3v1 numbers are
resolved by mutagen), "Electronica", "Drum & Bass", "Indie Rock". Rules:
- one tag may hold several genres, separated by ; / , | (not by "&": "Drum & Bass", "R&B")
- spelling variants are folded together (case, hyphens, spaces, "n'", "&" vs "and")
- known aliases map to a canonical name; unknown genres keep their own name, title-cased
"""

import functools
import re
import unicodedata

_SPLIT_RE = re.compile(r"\s*(?:;|/|,|\||\\)\s*")
_FOLD_RE = re.compile(r"[\s\-_.'’]+")
MAX_GENRES_PER_TRACK = 4

# folded alias -> canonical name. Folded form: lower-case, no accents, without spaces,
# hyphens, dots and apostrophes, "&" and "and" as "n".
_ALIASES_RAW = {
    "Rock": ["rock", "rock n roll", "rocknroll", "classic rock", "rock & roll", "rock and roll"],
    "Alternative": ["alternative", "alternative rock", "alt rock", "alt"],
    "Indie": ["indie", "indie rock", "indie pop", "indierock"],
    "Pop": ["pop", "pop music", "popmusic", "dance pop"],
    "Hip-Hop": ["hip hop", "hiphop", "hip-hop", "rap", "hip hop rap", "rap hip hop", "trap", "gangsta rap"],
    "R&B": ["r&b", "rnb", "r n b", "rhythm and blues", "rhythm & blues", "contemporary r&b"],
    "Soul": ["soul", "neo soul", "neo-soul"],
    "Funk": ["funk"],
    "Electronic": ["electronic", "electronica", "electro", "edm", "electronic music", "elektronisch"],
    "House": ["house", "deep house", "tech house", "progressive house"],
    "Techno": ["techno", "minimal techno", "minimal"],
    "Trance": ["trance", "psytrance", "psy trance", "goa"],
    "Drum & Bass": ["drum & bass", "drum and bass", "drum n bass", "dnb", "d&b", "jungle"],
    "Dubstep": ["dubstep"],
    "Ambient": ["ambient", "chillout", "chill out", "downtempo", "chill"],
    "Jazz": ["jazz", "smooth jazz", "jazz fusion", "bebop", "swing"],
    "Blues": ["blues"],
    "Classical": ["classical", "klassik", "classic", "orchestral", "baroque", "opera", "oper"],
    "Soundtrack": ["soundtrack", "film score", "score", "ost", "filmmusik", "original soundtrack"],
    "Metal": ["metal", "heavy metal", "heavy-metal", "death metal", "black metal", "thrash metal", "nu metal"],
    "Hard Rock": ["hard rock", "hardrock"],
    "Punk": ["punk", "punk rock", "pop punk", "hardcore punk"],
    "Folk": ["folk", "folk rock", "singer songwriter", "singer/songwriter", "liedermacher"],
    "Country": ["country", "americana", "bluegrass"],
    "Reggae": ["reggae", "ska", "dub", "dancehall"],
    "Latin": ["latin", "salsa", "reggaeton", "bossa nova", "latin pop"],
    "World": ["world", "world music", "weltmusik"],
    "Schlager": ["schlager", "volksmusik", "deutscher schlager"],
    "Deutschrock": ["deutschrock", "deutsch rock"],
    "Deutschrap": ["deutschrap", "deutsch rap", "german rap", "german hip hop"],
    "Disco": ["disco", "nu disco"],
    "Gospel": ["gospel", "christian"],
    "Children's": ["children's", "childrens", "kinder", "kindermusik"],
    "Audiobook": ["audiobook", "hörbuch", "hoerbuch", "spoken word"],
    "Podcast": ["podcast"],
}


def fold(s: str) -> str:
    decomposed = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
    s = s.replace("&", " n ").replace(" and ", " n ")
    return _FOLD_RE.sub("", s)


ALIASES: dict[str, str] = {fold(alias): canon for canon, aliases in _ALIASES_RAW.items() for alias in [canon, *aliases]}

_NOT_GENRES = {"", "other", "unknown", "misc", "genre", "none", "various", "sonstige", "unbekannt", "default"}


def _title(name: str) -> str:
    # "deep house" -> "Deep House", but keep deliberate capitals like "EBM" or "J-Pop".
    if name.isupper() and len(name) <= 5:
        return name

    def cap(word: str) -> str:
        return word if any(c.isupper() for c in word[1:]) else word[:1].upper() + word[1:]

    return " ".join("-".join(cap(part) for part in w.split("-")) for w in name.split())


def canonical(tag: str) -> str | None:
    name = " ".join(tag.split()).strip(" -")
    if not name or len(name) > 60:
        return None
    key = fold(name)
    if key in _NOT_GENRES or key.isdigit():
        return None
    return ALIASES.get(key) or _title(name)


def normalize(raw_values: list[str] | str | None) -> list[str]:
    """Canonical genre names for the genre values of one track, in tag order, without duplicates."""
    if not raw_values:
        return []
    if isinstance(raw_values, str):
        raw_values = [raw_values]
    out: list[str] = []
    for value in raw_values:
        for part in _SPLIT_RE.split(value):
            name = canonical(part)
            if name and name not in out:
                out.append(name)
    return out[:MAX_GENRES_PER_TRACK]


def slug(name: str) -> str:
    return fold(name)


# --- families: the broad genres on the Discover page -------------------------------------------
#
# A second level above the genres: "Rock" there covers Rock, Alternative, Indie, Punk, ... Genres
# not listed are placed by words in their name ("Post-Punk" -> Rock, "Folk Metal" -> Metal),
# checked in order, so the more telling word wins ("Folk Metal" is Metal, "Folk Rock" is Rock).

FAMILIES = (
    "Rock",
    "Metal",
    "Pop",
    "Hip-Hop",
    "Electronic",
    "R&B & Soul",
    "Jazz",
    "Blues",
    "Folk & Country",
    "Reggae",
    "Latin & World",
    "Klassik",
    "Soundtrack",
    "Schlager",
)

_FAMILY_OF: dict[str, str | None] = {
    **dict.fromkeys(("Rock", "Alternative", "Indie", "Hard Rock", "Punk", "Deutschrock"), "Rock"),
    "Metal": "Metal",
    **dict.fromkeys(("Pop", "Disco"), "Pop"),
    **dict.fromkeys(("Hip-Hop", "Deutschrap"), "Hip-Hop"),
    **dict.fromkeys(("Electronic", "House", "Techno", "Trance", "Drum & Bass", "Dubstep", "Ambient"), "Electronic"),
    **dict.fromkeys(("R&B", "Soul", "Funk", "Gospel"), "R&B & Soul"),
    "Jazz": "Jazz",
    "Blues": "Blues",
    **dict.fromkeys(("Folk", "Country"), "Folk & Country"),
    "Reggae": "Reggae",
    **dict.fromkeys(("Latin", "World"), "Latin & World"),
    "Classical": "Klassik",
    "Soundtrack": "Soundtrack",
    "Schlager": "Schlager",
    **dict.fromkeys(("Children's", "Audiobook", "Podcast"), None),
}

# (words, family): the first entry with a word in the genre name decides.
_FAMILY_WORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("metal", "metalcore", "deathcore", "grindcore", "doom", "sludge", "djent"), "Metal"),
    (("trip hop", "triphop", "synthwave", "electropop", "idm", "breakbeat", "garage", "jungle"), "Electronic"),
    (("rock", "punk", "grunge", "shoegaze", "emo", "post hardcore", "stoner", "britpop", "new wave"), "Rock"),
    (("hip hop", "hiphop", "rap", "trap", "grime", "drill"), "Hip-Hop"),
    (("reggae", "ska", "dub", "dancehall", "rocksteady"), "Reggae"),
    (
        ("house", "techno", "trance", "electro", "edm", "dubstep", "drum", "bass", "ambient", "downtempo", "dance"),
        "Electronic",
    ),
    (("jazz", "swing", "bebop", "bop", "big band"), "Jazz"),
    (("blues",), "Blues"),
    (("soul", "funk", "r&b", "rnb", "gospel", "motown"), "R&B & Soul"),
    (
        ("latin", "salsa", "bossa", "samba", "tango", "cumbia", "reggaeton", "flamenco", "world", "afro", "fado"),
        "Latin & World",
    ),
    (("folk", "country", "bluegrass", "americana", "singer", "acoustic"), "Folk & Country"),
    (("classical", "baroque", "opera", "symphon", "orchestr", "chamber", "romantic era", "choral"), "Klassik"),
    (("soundtrack", "score", "film", "musical"), "Soundtrack"),
    (("schlager", "volksmusik"), "Schlager"),
    (("pop", "synthpop", "disco", "chanson", "schlager pop"), "Pop"),
)


@functools.lru_cache(maxsize=8192)  # pure, and the Discover page asks for every genre each time
def family(genre: str) -> str | None:
    """The broad genre ("Rock") a genre ("Post-Punk") belongs to, or None (spoken word, unknown)."""
    if genre in _FAMILY_OF:
        return _FAMILY_OF[genre]
    name = " ".join(re.split(r"[\s/,\-]+", genre.casefold()))
    words = set(re.split(r"[\s&]+", name))
    for keys, fam in _FAMILY_WORDS:
        for key in keys:
            # Phrases ("hip hop", "r&b") anywhere; words whole, longer ones also as a prefix
            # ("symphonic", "electronica"); short ones not ("dub" is no "dubstep").
            if not key.isalnum():
                if key in name:
                    return fam
            elif key in words or (len(key) > 4 and any(w.startswith(key) for w in words)):
                return fam
    return None
