"""IP video encoder health checks over RTSP, using ffprobe/ffmpeg (no vendor SDK, no guessed API).

Three independent layers, matching the ISP's own notes:
  network  TCP reaches the RTSP port at all (see adapters.ping.tcp_ping, used by the caller)
  video    ffprobe can open the stream and finds a video track
  audio    ffprobe finds an audio track, AND ffmpeg actually decodes it and measures its level
           (volumedetect) -- packet arrival alone does not prove the audio isn't silent

Nothing here ever restarts anything: this module only looks.
"""
import re
import subprocess

MEAN_VOLUME = re.compile(r"mean_volume:\s*(-?[\d.]+)\s*dB")
MAX_VOLUME = re.compile(r"max_volume:\s*(-?[\d.]+)\s*dB")


class EncoderError(Exception):
    pass


def build_rtsp_url(host: str, port: int, path: str, username: str | None, password: str | None) -> str:
    path = path if path.startswith("/") else f"/{path}"
    auth = f"{username}:{password}@" if username else ""
    return f"rtsp://{auth}{host}:{port}{path}"


def _run(args: list[str], timeout_s: float) -> tuple[int, str, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout_s)
    except FileNotFoundError:
        raise EncoderError("ffmpeg/ffprobe is not installed in this container") from None
    except subprocess.TimeoutExpired:
        raise EncoderError(f"timed out after {timeout_s:.0f}s") from None
    return r.returncode, r.stdout, r.stderr


def _rtsp_opts(url: str) -> list[str]:
    return ["-rtsp_transport", "tcp"] if url.startswith("rtsp://") else []


def probe_tracks(url: str, timeout_s: float = 8.0) -> dict:
    """Does the stream open at all, and which tracks does it have? Never raises on a stream
    problem (bad URL, no response, no such track) -- that's the normal, expected failure this
    exists to detect, reported as {"ok": False, "error": ...}."""
    code, out, err = _run(["ffprobe", "-v", "error", *_rtsp_opts(url),
                           "-show_entries", "stream=codec_name,codec_type", "-of", "csv=p=0", url], timeout_s)
    if code != 0:
        return {"ok": False, "has_video": False, "has_audio": False, "error": err.strip()[-400:] or f"ffprobe exit {code}"}
    video_codec = audio_codec = None
    for line in out.splitlines():
        parts = line.split(",")  # ffprobe's csv=p=0 order here is codec_name,codec_type
        if len(parts) >= 2:
            codec, kind = parts[0].strip(), parts[1].strip()
            if kind == "video" and not video_codec:
                video_codec = codec
            elif kind == "audio" and not audio_codec:
                audio_codec = codec
    return {"ok": True, "has_video": bool(video_codec), "has_audio": bool(audio_codec),
            "video_codec": video_codec, "audio_codec": audio_codec}


def audio_level(url: str, duration_s: float = 4.0, timeout_s: float = 12.0) -> dict:
    """Decode `duration_s` of audio and measure its level (ffmpeg's volumedetect). This is the
    actual proof of sound, not just that an audio track/packets exist."""
    code, _out, err = _run(["ffmpeg", "-v", "info", *_rtsp_opts(url), "-i", url, "-t", str(duration_s),
                           "-vn", "-af", "volumedetect", "-f", "null", "-"], timeout_s)
    mean = MEAN_VOLUME.search(err)
    peak = MAX_VOLUME.search(err)
    if not mean:
        return {"ok": False, "mean_db": None, "peak_db": None, "error": err.strip()[-400:] or f"ffmpeg exit {code}"}
    return {"ok": True, "mean_db": float(mean.group(1)), "peak_db": float(peak.group(1)) if peak else None}
