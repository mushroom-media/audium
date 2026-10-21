"""Genre tags -> a small, consistent set of genre names.

Tags in the wild: "Rock; Pop", "Hip Hop", "hiphop", "Hip-Hop/Rap", "(17)" (ID3v1 numbers are
resolved by mutagen), "Electronica", "Drum & Bass", "Indie Rock". Rules:
- one tag may hold several genres, separated by ; / , | (not by "&": "Drum & Bass", "R&B")
- spelling variants are folded together (case, hyphens, spaces, "n'", "&" vs "and")
- known aliases map to a canonical name; unknown genres keep their own name, title-cased
"""

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
