"""Everything known about one track for the "Info" dialog: tags and file (library.get_track),
the genres (from tags and detected), the audio analysis and the listener's own plays."""

from sqlalchemy import Connection, func, select

from audium.analysis.explain import key_name
from audium.analysis.styles import MIN_STYLE_PROB
from audium.db.schema import favorites, genres, play_history, styles, track_features, track_genres, track_styles
from audium.services import library as lib

_MAX_STYLES = 5


def track_info(conn: Connection, user_id: int, track_id: int) -> dict:
    track = lib.get_track(conn, track_id)  # raises NotFound
    genre_rows = conn.execute(
        select(genres.c.name, track_genres.c.source, track_genres.c.weight)
        .join(genres, genres.c.id == track_genres.c.genre_id)
        .where(track_genres.c.track_id == track_id)
        .order_by(track_genres.c.source.desc(), track_genres.c.weight.desc(), genres.c.name)
    ).all()
    f = conn.execute(select(track_features).where(track_features.c.track_id == track_id)).first()
    analysis = None
    if f is not None:
        analysis = {
            "status": f.status,
            "analyzed_at": f.analyzed_at,
            "sound": "effnet" in f.analyzer,
            **{
                k: getattr(f, k)
                for k in (
                    "bpm",
                    "loudness",
                    "energy",
                    "danceability",
                    "brightness",
                    "dynamics",
                    "mood_happy",
                    "mood_sad",
                    "mood_aggressive",
                    "mood_relaxed",
                )  # fmt: skip
            },
            "key": key_name(f.key, f.mode),
        }
    style_rows = conn.execute(
        select(styles.c.name, styles.c.parent, track_styles.c.prob)
        .join(styles, styles.c.id == track_styles.c.style_id)
        .where(track_styles.c.track_id == track_id)
        .order_by(track_styles.c.prob.desc())
        .limit(_MAX_STYLES)
    ).all()
    plays = conn.execute(
        select(func.count(), func.max(play_history.c.played_at)).where(
            play_history.c.user_id == user_id, play_history.c.track_id == track_id
        )
    ).first()
    favorite = (
        conn.execute(
            select(favorites.c.item_id).where(
                favorites.c.user_id == user_id, favorites.c.item_type == "track", favorites.c.item_id == track_id
            )
        ).first()
        is not None
    )
    return {
        "track": track,
        "genres": [{"name": r.name, "detected": r.source == "detected", "weight": r.weight} for r in genre_rows],
        # Only styles the model is fairly sure of; a track whose styles all lie below shows that
        # no style was clear instead of listing near-random guesses.
        "styles": [
            {"name": r.name, "parent": r.parent, "prob": r.prob} for r in style_rows if r.prob >= MIN_STYLE_PROB
        ],
        "styles_unclear": bool(style_rows) and style_rows[0].prob < MIN_STYLE_PROB,
        "analysis": analysis,
        "plays": plays[0] if plays else 0,
        "last_played": plays[1] if plays else None,
        "favorite": favorite,
    }
