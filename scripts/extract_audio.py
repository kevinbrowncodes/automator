#!/opt/homebrew/bin/python3
"""Extract Audio: the soundtrack of each video, as its own file, untouched.

    extract_audio.py VIDEO [VIDEO ...]

For each video, copies its first audio track into a file next to it, named after
the video, with no re-encode: the audio is bit for bit what was in the video, and
it takes about a second whatever the length. The extension follows the codec:

    AAC, Apple Lossless  -> .m4a      MP3  -> .mp3     Opus   -> .opus
    FLAC                 -> .flac     PCM  -> .wav     Vorbis -> .ogg
    AC-3 / E-AC-3        -> .ac3 / .eac3
    anything else        -> .mka (Matroska takes any codec; opens in VLC/IINA)

PCM is the one case that is not a plain copy: QuickTime and camera .mov files often
store it big-endian, which WAV cannot hold, so it is rewritten little-endian.
Same samples, same bit depth, only the byte order changes.

An existing file is never overwritten: "take.m4a" becomes "take 2.m4a", as Finder does.

Called by the "Extract Audio" Quick Action, which runs the copy that install.sh
puts in ~/Library/Application Support/automator/. Edit the one in the repo.

Failures (no audio track, not a video, ffmpeg error) become a notification rather
than failing silently, since a Quick Action has no terminal to print to.
"""
import json
import os
import subprocess
import sys

# Finder Quick Actions don't inherit the shell PATH, so name the tools in full.
FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"

EXTENSIONS = {
    "aac": "m4a", "alac": "m4a",
    "mp3": "mp3", "opus": "opus", "vorbis": "ogg", "flac": "flac",
    "ac3": "ac3", "eac3": "eac3",
}
FALLBACK = "mka"
# The PCM layouts a WAV file can hold, all little-endian.
WAV_PCM = {"pcm_u8", "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "pcm_f64le",
           "pcm_alaw", "pcm_mulaw"}


class ExtractError(Exception):
    """A failure the user should see as a notification."""


def audio_codec(path):
    """Codec name of the first audio stream (e.g. 'aac'), or raise ExtractError."""
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name", "-of", "json", path],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise ExtractError("not a video")
    try:
        streams = json.loads(result.stdout).get("streams") or []
    except ValueError:
        streams = []
    codec = (streams[0].get("codec_name") if streams else None) or ""
    if not codec:
        raise ExtractError("no audio track")
    return codec


def plan(codec):
    """(extension, ffmpeg audio codec option) that keeps the audio as it is."""
    if codec in EXTENSIONS:
        return EXTENSIONS[codec], "copy"
    if codec.startswith("pcm_"):
        little = codec[:-2] + "le" if codec.endswith("be") else codec
        if little in WAV_PCM:
            return "wav", "copy" if little == codec else little
    return FALLBACK, "copy"


def output_path(video, ext):
    """<stem>.<ext> next to the video, or <stem> 2.<ext>, <stem> 3.<ext>... if taken."""
    folder, name = os.path.split(video)
    stem = os.path.splitext(name)[0]
    candidate = os.path.join(folder, f"{stem}.{ext}")
    n = 2
    while os.path.lexists(candidate):
        candidate = os.path.join(folder, f"{stem} {n}.{ext}")
        n += 1
    return candidate


def extract_command(video, out, audio_option):
    # -map 0:a:0: the first audio track only, no video, subtitles or data.
    # -n: refuse to overwrite, in case the name was taken since output_path() looked.
    return [FFMPEG, "-nostdin", "-v", "error", "-n", "-i", video,
            "-map", "0:a:0", "-c:a", audio_option, "-map_metadata", "0", out]


def extract(video):
    """Write the audio of one video next to it; return the output path."""
    ext, option = plan(audio_codec(video))
    out = output_path(video, ext)
    result = subprocess.run(extract_command(video, out, option), capture_output=True, text=True)
    # The name got taken after output_path() looked, so -n refused. ffmpeg 8 exits 0
    # when it does that, so go by the message, and leave that file alone: it isn't ours.
    if "already exists" in result.stderr:
        raise ExtractError(f"{os.path.basename(out)} already exists")
    if result.returncode != 0:
        if os.path.exists(out):
            os.remove(out)   # don't leave a half-written file behind
        detail = result.stderr.strip().splitlines()
        raise ExtractError("ffmpeg failed" + (f": {detail[-1]}" if detail else ""))
    return out


def _applescript_string(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(message, subtitle=""):
    script = f"display notification {_applescript_string(message)} with title \"Extract Audio\""
    if subtitle:
        script += f" subtitle {_applescript_string(subtitle)}"
    subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True)


def main(paths):
    if not os.access(FFMPEG, os.X_OK) or not os.access(FFPROBE, os.X_OK):
        notify("ffmpeg not found in /opt/homebrew/bin. In Terminal run: brew install ffmpeg")
        return 1
    failed = 0
    for video in paths:
        name = os.path.basename(video)
        try:
            extract(video)
        except ExtractError as err:
            failed += 1
            notify(f"Skipped: {err}", subtitle=name)
        except Exception as err:   # anything unexpected still reaches the user
            failed += 1
            notify(f"Failed: {type(err).__name__}: {err}", subtitle=name)
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
