"""Audio descriptors with Essentia, computed in a separate low-priority process.

The file is decoded by ffmpeg (same formats as playback) to mono float32 at 44.1 kHz, and only a
window of at most WINDOW_S seconds is analysed (skipping the intro of long tracks). That keeps
memory per track around 20 MB and time around 1-3 s, also for hour-long recordings.

All descriptors are mapped to fixed 0..1 scales (not library percentiles), so a rule such as
"energy >= 0.7" means the same in every library and does not drift as the library grows.
"""

import json
import math
import os
import shutil
import subprocess
from pathlib import Path

ANALYZER_VERSION = 1
SAMPLE_RATE = 44100
WINDOW_S = 120
SKIP_INTRO_S = 30
MIN_AUDIO_S = 3
_DECODE_TIMEOUT_S = 120

MOODS = ("happy", "sad", "aggressive", "relaxed")
KEYS = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
_KEY_ALIASES = {"Db": "C#", "D#": "Eb", "Gb": "F#", "G#": "Ab", "A#": "Bb"}


class AnalysisError(Exception):
    pass


def essentia_available() -> bool:
    try:
        import essentia.standard  # noqa: F401
    except Exception:
        return False
    return True


def ml_models(models_dir: Path) -> dict[str, Path] | None:
    """Mood models (Essentia's MusiCNN classifiers) if the user put them into models_dir."""
    try:
        import essentia.standard as es
    except Exception:
        return None
    if not hasattr(es, "TensorflowPredictMusiCNN"):
        return None
    found = {m: models_dir / f"mood_{m}-msd-musicnn-1.pb" for m in MOODS}
    return found if all(p.is_file() for p in found.values()) else None


def backend_name(models_dir: Path) -> str:
    if not essentia_available():
        return "none"
    return "essentia+ml" if ml_models(models_dir) else "essentia"


def _clip(x: float) -> float:
    return 0.0 if not math.isfinite(x) else max(0.0, min(1.0, x))


def decode(path: str, duration_ms: int):
    import numpy as np

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AnalysisError("ffmpeg not found")
    duration_s = duration_ms / 1000
    start = SKIP_INTRO_S if duration_s > SKIP_INTRO_S + WINDOW_S / 2 else 0
    cmd = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error"]
    if start:
        cmd += ["-ss", str(start)]
    cmd += [
        "-i",
        path,
        "-t",
        str(WINDOW_S),
        "-map",
        "0:a:0",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "f32le",
        "pipe:1",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=_DECODE_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired as exc:
        raise AnalysisError("decoding timed out") from exc
    if out.returncode != 0:
        raise AnalysisError(f"decoding failed: {out.stderr.decode(errors='replace').strip()[-200:]}")
    audio = np.frombuffer(out.stdout, dtype=np.float32)
    if len(audio) < MIN_AUDIO_S * SAMPLE_RATE:
        raise AnalysisError("too short to analyse")
    if not np.isfinite(audio).all():
        audio = np.nan_to_num(audio)
    return np.ascontiguousarray(audio)


def analyze(path: str, duration_ms: int, models_dir: Path | None = None) -> dict:
    """Descriptors of one file. Raises AnalysisError for files that cannot be analysed."""
    import essentia
    import essentia.standard as es
    import numpy as np

    essentia.log.infoActive = False
    essentia.log.warningActive = False
    audio = decode(path, duration_ms)

    bpm, _beats, _confidence, _estimates, _intervals = es.RhythmExtractor2013(method="multifeature")(audio)
    key, scale, _strength = es.KeyExtractor(profileType="edma")(audio)
    dynamic_complexity, loudness_db = es.DynamicComplexity()(audio)
    rms = float(es.RMS()(audio))
    danceability, _dfa = es.Danceability()(audio)

    # Spectral centroid, weighted by frame energy: silent frames (centroid 0) must not pull
    # sparse music towards "dark".
    window = es.Windowing(type="hann")
    spectrum = es.Spectrum()
    centroid = es.Centroid(range=SAMPLE_RATE / 2)
    values, weights = [], []
    for frame in es.FrameGenerator(audio, frameSize=2048, hopSize=4096):
        energy = float(np.dot(frame, frame))
        if energy > 1e-6:
            values.append(centroid(spectrum(window(frame))))
            weights.append(energy)
    centroid_hz = float(np.average(values, weights=weights)) if values else 0.0

    rms_db = 20 * math.log10(rms) if rms > 0 else -90.0
    result = {
        "bpm": round(float(bpm), 1) if 30 <= bpm <= 260 else None,
        "key": _KEY_ALIASES.get(key, key) if key in KEYS or key in _KEY_ALIASES else None,
        "mode": scale if scale in ("major", "minor") else None,
        "loudness": round(float(loudness_db), 2),
        # -40 dBFS RMS (very quiet) .. -8 dBFS (brickwall-mastered)
        "energy": round(_clip((rms_db + 40) / 32), 4),
        # Essentia's dynamic complexity is roughly 0 (constant) .. 10+ (classical)
        "dynamics": round(_clip(float(dynamic_complexity) / 10), 4),
        # Essentia's danceability is roughly 0 .. 3
        "danceability": round(_clip(float(danceability) / 3), 4),
        # mean spectral centroid 500 Hz (dark) .. 4 kHz (bright)
        "brightness": round(_clip((centroid_hz - 500) / 3500), 4),
    }
    models = ml_models(models_dir) if models_dir else None
    if models:
        result.update(_moods(audio, models))
    return result


def _moods(audio, models: dict[str, Path]) -> dict:
    """Experimental: Essentia's pre-trained MusiCNN mood classifiers (user-supplied models)."""
    import essentia.standard as es
    import numpy as np

    audio16 = es.Resample(inputSampleRate=SAMPLE_RATE, outputSampleRate=16000)(audio)
    out = {}
    for mood, model in models.items():
        meta_file = model.with_suffix(".json")
        positive = 0
        if meta_file.is_file():
            classes = json.loads(meta_file.read_text()).get("classes", [])
            positive = classes.index(mood) if mood in classes else 0
        predictions = es.TensorflowPredictMusiCNN(graphFilename=str(model))(audio16)
        out[f"mood_{mood}"] = round(_clip(float(np.mean(predictions[:, positive]))), 4)
    return out


def fingerprint(size: int, mtime_ns: int, quick_hash: str) -> str:
    return f"{size}:{mtime_ns}:{quick_hash}"


def analyze_one(args: tuple) -> tuple[int, str, dict | None, str | None]:
    """Process-pool entry point. Never raises: returns (track_id, fingerprint, features, error)."""
    track_id, path, duration_ms, fp, models_dir = args
    try:
        if not os.path.isfile(path):
            return track_id, fp, None, "file not found"
        return track_id, fp, analyze(path, duration_ms, Path(models_dir) if models_dir else None), None
    except AnalysisError as exc:
        return track_id, fp, None, str(exc)[:300]
    except Exception as exc:
        return track_id, fp, None, f"{type(exc).__name__}: {exc}"[:300]
