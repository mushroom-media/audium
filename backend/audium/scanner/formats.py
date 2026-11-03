"""File types the scanner picks up and how mutagen's classes map to codec/container names."""

AUDIO_EXTENSIONS = frozenset(
    {
        "mp3",
        "mp2",
        "flac",
        "ogg",
        "oga",
        "opus",
        "spx",
        "m4a",
        "m4b",
        "mp4",
        "aac",
        "alac",
        "wma",
        "asf",
        "wav",
        "wave",
        "aif",
        "aiff",
        "aifc",
        "ape",
        "wv",
        "mpc",
        "tta",
        "ofr",
        "dsf",
        "dff",
        "ac3",
        "mka",
        "webm",
        "caf",
    }
)
IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp", "gif", "bmp"})

# Folder images, best first. Matched against the lower-cased file stem.
FOLDER_COVER_NAMES = ("cover", "folder", "front", "album", "albumart", "albumartlarge", "thumb")
# Artist images (artist.jpg, ...) in the artist folder, best format first. Never an album cover.
ARTIST_IMAGE_STEM = "artist"
ARTIST_IMAGE_EXTENSIONS = ("jpg", "jpeg", "png", "webp")
# folder.jpg in the artist folder (Jellyfin/Kodi style), used when there is no artist.jpg and the
# server setting artist_folder_images is on. In an album folder it stays the album cover.
ARTIST_FOLDER_IMAGE_STEM = "folder"

# Directory names that are never music: NAS metadata, recycle bins, macOS resource forks.
IGNORED_DIRS = frozenset(
    {
        "@eadir",
        "#recycle",
        "#snapshot",
        ".@__thumb",
        "@recycle",
        "$recycle.bin",
        "lost+found",
        "system volume information",
        ".appledouble",
        ".trash",
        ".trashes",
    }
)

# mutagen class name -> (codec, container)
_CLASS_CODECS = {
    "MP3": ("mp3", "mp3"),
    "EasyMP3": ("mp3", "mp3"),
    "FLAC": ("flac", "flac"),
    "OggVorbis": ("vorbis", "ogg"),
    "OggOpus": ("opus", "ogg"),
    "OggFLAC": ("flac", "ogg"),
    "OggSpeex": ("speex", "ogg"),
    "ASF": ("wma", "asf"),
    "MonkeysAudio": ("ape", "ape"),
    "WavPack": ("wavpack", "wv"),
    "Musepack": ("mpc", "mpc"),
    "TrueAudio": ("tta", "tta"),
    "OptimFROG": ("ofr", "ofr"),
    "WAVE": ("pcm", "wav"),
    "AIFF": ("pcm", "aiff"),
    "DSF": ("dsd", "dsf"),
    "DSDIFF": ("dsd", "dff"),
    "AAC": ("aac", "aac"),
    "AC3": ("ac3", "ac3"),
}


def codec_for(audio) -> tuple[str | None, str | None]:
    name = type(audio).__name__
    if name in ("MP4", "EasyMP4"):
        codec = (getattr(audio.info, "codec", "") or "").lower()
        if codec.startswith("alac"):
            return "alac", "mp4"
        if codec.startswith("mp4a") or not codec:
            return "aac", "mp4"
        return codec, "mp4"
    codec, container = _CLASS_CODECS.get(name, (None, None))
    if codec == "wma":
        codec_name = (getattr(audio.info, "codec_name", "") or "").lower()
        if "lossless" in codec_name:
            codec = "wmalossless"
        elif "pro" in codec_name:
            codec = "wmapro"
    return codec, container


# ffprobe codec_name -> our codec name (only used when mutagen cannot read a file)
FFPROBE_CODECS = {
    "mp3": "mp3",
    "flac": "flac",
    "vorbis": "vorbis",
    "opus": "opus",
    "aac": "aac",
    "alac": "alac",
    "wmav1": "wma",
    "wmav2": "wma",
    "wmalossless": "wmalossless",
    "wmapro": "wmapro",
    "ape": "ape",
    "wavpack": "wavpack",
    "musepack7": "mpc",
    "musepack8": "mpc",
    "tta": "tta",
    "ac3": "ac3",
    "pcm_s16le": "pcm",
    "pcm_s24le": "pcm",
    "pcm_s32le": "pcm",
    "pcm_s16be": "pcm",
    "pcm_s24be": "pcm",
    "pcm_f32le": "pcm",
    "dsd_lsbf": "dsd",
    "dsd_msbf": "dsd",
}
