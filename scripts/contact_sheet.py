#!/opt/homebrew/bin/python3
"""Contact Sheet: one JPEG per video, for reviewing takes at a glance.

    contact_sheet.py VIDEO [VIDEO ...]

For each video, writes <video name>.contact.jpg next to it and opens it in Preview:

  * Overview grid: one frame every 0.5 s through the whole video, 6 columns of
    ~448 px tiles, aspect ratio kept, each tile labelled with its time (0:12.5).
  * Seams row (videos of 10 s or more): for each 10 s mark inside the video, the
    frame 0.1 s before it and the frame 0.3 s after it, side by side, so a jump
    where two 10-second shots were joined stands out.

Called by the "Contact Sheet" Quick Action, which runs the copy that install.sh
puts in ~/Library/Application Support/automator/. Edit the one in the repo.

Frames are grabbed one at a time with -ss BEFORE -i (fast seek, then exact decode
to the first frame at or after that time). Never switch this to the select or fps
filters: they can repeat the first frame and fake a frozen hold. A gate enforces it.

Failures (not a video, ffmpeg error, Pillow missing) become a notification rather
than failing silently, since a Quick Action has no terminal to print to.
"""
import io
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # handled in main() with a notification that says how to fix it
    Image = ImageDraw = ImageFont = None

# Finder Quick Actions don't inherit the shell PATH, so name the tools in full.
FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"

STEP = 0.5            # overview: seconds between frames
COLUMNS = 6
TILE_W = 448          # overview tile width; height follows the video's aspect
SEAM_EVERY = 10.0     # shots are joined every 10 s
SEAM_BEFORE = 0.1     # grab the frame this long before each mark ...
SEAM_AFTER = 0.3      # ... and this long after it
PAIRS_PER_ROW = COLUMNS // 2

LINE = 2              # the thin line between tiles (and round the edge)
PAIR_GAP = 24         # space between seam pairs, so each pair reads as one unit
SECTION_GAP = 28      # space above the Seams heading
HEADING_H = 40        # height of the "Seams" heading band
PAPER = (240, 240, 240)
INK = (30, 30, 30)
FONT_PATHS = ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/SFNSMono.ttf")
JPEG_MAX = 65500      # JPEG can't be taller or wider than this
WORKERS = max(2, (os.cpu_count() or 4) // 2)


class SheetError(Exception):
    """A failure the user should see as a notification."""


def fmt_time(t):
    """Seconds -> m:ss.s, e.g. 12.5 -> '0:12.5', 69.9 -> '1:09.9'."""
    tenths = int(round(t * 10))
    minutes, rest = divmod(tenths, 600)
    return f"{minutes}:{rest // 10:02d}.{rest % 10}"


def _ratio(text):
    """'24000/1001' -> 23.976...; '0/0', '', None -> 0.0."""
    try:
        num, _, den = (text or "").partition("/")
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(path):
    """Return (duration, fps) of the first video stream, or raise SheetError."""
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_type,duration,avg_frame_rate,r_frame_rate:format=duration",
         "-of", "json", path],
        capture_output=True, text=True)
    try:
        info = json.loads(result.stdout)
    except ValueError:
        info = {}
    streams = info.get("streams") or [{}]
    stream, fmt = streams[0], info.get("format") or {}
    # Still images (a .png has a "video" stream too) report no duration and are
    # rejected below; audio-only files have no video stream at all.
    if result.returncode != 0 or stream.get("codec_type") != "video":
        raise SheetError("not a video")
    duration = _ratio(stream.get("duration")) or _ratio(fmt.get("duration"))
    if duration <= 0:
        raise SheetError("not a video (no running time)")
    fps = _ratio(stream.get("avg_frame_rate")) or _ratio(stream.get("r_frame_rate")) or 30.0
    return duration, fps


def overview_times(duration, fps):
    """0, 0.5, 1.0 ... up to the last frame of the video."""
    last = duration - 1.0 / fps     # a seek past the last frame's start returns nothing
    count = int(last / STEP + 1e-9) + 1 if last >= 0 else 1
    return [round(i * STEP, 3) for i in range(count)]


def seam_times(duration, fps):
    """[(9.9, 10.3), (19.9, 20.3), ...] for each 10 s mark whose after-frame exists."""
    last = duration - 1.0 / fps
    pairs = []
    mark = SEAM_EVERY
    while mark + SEAM_AFTER <= last + 1e-9:
        pairs.append((round(mark - SEAM_BEFORE, 3), round(mark + SEAM_AFTER, 3)))
        mark += SEAM_EVERY
    return pairs


def grab_command(path, t, width):
    # -ss before -i: seek to the keyframe before t, then decode exactly to t.
    # setsar folds any non-square pixels into the width, so the aspect ratio holds.
    # Converting to RGB before shrinking keeps colours true; shrinking in YUV
    # shifts them a couple of levels.
    return [FFMPEG, "-nostdin", "-v", "error", "-ss", f"{t:.3f}", "-i", path,
            "-frames:v", "1", "-an", "-sn", "-dn",
            "-vf", f"scale=iw*sar:ih,setsar=1,format=rgb24,scale={width}:-2",
            "-f", "image2pipe", "-c:v", "ppm", "-"]


def grab(path, t, width):
    """One frame at time t, scaled to width, as an RGB image."""
    result = subprocess.run(grab_command(path, t, width), capture_output=True)
    if result.returncode != 0 or not result.stdout:
        detail = result.stderr.decode(errors="replace").strip().splitlines()
        raise SheetError(f"ffmpeg failed at {fmt_time(t)}"
                         + (f": {detail[-1]}" if detail else ""))
    return Image.open(io.BytesIO(result.stdout)).convert("RGB")


def grab_all(path, times, width):
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return list(pool.map(lambda t: grab(path, t, width), times))


def load_font(size):
    for candidate in FONT_PATHS:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def stamp(draw, x, y, text, font):
    """Time label in the tile's bottom-left corner, white on a dark box."""
    pad = max(3, font.size // 5)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    w, h = right - left, bottom - top
    draw.rectangle([x, y - h - 2 * pad, x + w + 2 * pad, y], fill=(0, 0, 0))
    draw.text((x + pad - left, y - h - pad - top), text, font=font, fill=(255, 255, 255))


def build_sheet(frames, times, seam_frames, seam_pairs):
    """Lay the overview grid and the seams row out on one image."""
    tile_w, tile_h = frames[0].size
    rows = -(-len(frames) // COLUMNS)
    width = LINE + COLUMNS * (tile_w + LINE)
    height = LINE + rows * (tile_h + LINE)

    # Seam tiles shrink a little so three pairs plus their gaps fit the same width.
    if seam_pairs:
        seam_w, seam_h = seam_frames[0][0].size
        seam_rows = -(-len(seam_pairs) // PAIRS_PER_ROW)
        seams_top = height + SECTION_GAP + HEADING_H
        height = seams_top + seam_rows * (seam_h + 2 * LINE) + LINE
    if height > JPEG_MAX:
        raise SheetError("video too long for one sheet")

    sheet = Image.new("RGB", (width, height), PAPER)
    draw = ImageDraw.Draw(sheet)
    font = load_font(max(12, tile_w // 22))

    # The thin lines are a dark frame drawn behind each tile, so neighbours share
    # one line and the empty cells at the end of the last row stay blank paper.
    for i, (img, t) in enumerate(zip(frames, times)):
        x = LINE + (i % COLUMNS) * (tile_w + LINE)
        y = LINE + (i // COLUMNS) * (tile_h + LINE)
        draw.rectangle([x - LINE, y - LINE, x + tile_w + LINE - 1, y + tile_h + LINE - 1], fill=INK)
        sheet.paste(img, (x, y))
        stamp(draw, x, y + tile_h, fmt_time(t), font)

    if seam_pairs:
        heading = load_font(HEADING_H * 2 // 3)
        draw.text((LINE, seams_top - HEADING_H // 2), "Seams", font=heading, fill=INK, anchor="lm")
        pair_w = 2 * seam_w + 3 * LINE
        for i, ((before, after), (b_img, a_img)) in enumerate(zip(seam_pairs, seam_frames)):
            x = (i % PAIRS_PER_ROW) * (pair_w + PAIR_GAP)
            y = seams_top + (i // PAIRS_PER_ROW) * (seam_h + 2 * LINE)
            draw.rectangle([x, y, x + pair_w - 1, y + seam_h + 2 * LINE - 1], fill=INK)
            for j, (img, t) in enumerate(((b_img, before), (a_img, after))):
                tx = x + LINE + j * (seam_w + LINE)
                sheet.paste(img, (tx, y + LINE))
                stamp(draw, tx, y + LINE + seam_h, fmt_time(t), font)
    return sheet


def seam_tile_width(tile_w):
    """Width that puts 3 seam pairs, with their gaps, across the overview's width."""
    sheet_w = LINE + COLUMNS * (tile_w + LINE)
    inner = sheet_w - (PAIRS_PER_ROW - 1) * PAIR_GAP - PAIRS_PER_ROW * 3 * LINE
    return inner // COLUMNS // 2 * 2   # even, as ffmpeg's -2 scaling needs


def output_path(video):
    folder, name = os.path.split(video)
    stem = os.path.splitext(name)[0]
    return os.path.join(folder, f"{stem}.contact.jpg")


def make_sheet(video):
    """Build and save the sheet for one video; return the output path."""
    duration, fps = probe(video)
    times = overview_times(duration, fps)
    pairs = seam_times(duration, fps)
    frames = grab_all(video, times, TILE_W)
    flat = grab_all(video, [t for pair in pairs for t in pair], seam_tile_width(frames[0].width))
    seam_frames = list(zip(flat[0::2], flat[1::2]))
    sheet = build_sheet(frames, times, seam_frames, pairs)
    out = output_path(video)
    sheet.save(out, "JPEG", quality=88, optimize=True)
    return out


def _applescript_string(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(message, subtitle=""):
    script = f"display notification {_applescript_string(message)} with title \"Contact Sheet\""
    if subtitle:
        script += f" subtitle {_applescript_string(subtitle)}"
    subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True)


def open_in_preview(path):
    subprocess.run(["/usr/bin/open", "-a", "Preview", path], capture_output=True)


def main(paths):
    if Image is None:
        notify("Pillow is missing. In Terminal run: "
               "/opt/homebrew/bin/python3 -m pip install --break-system-packages Pillow")
        return 1
    if not os.access(FFMPEG, os.X_OK) or not os.access(FFPROBE, os.X_OK):
        notify("ffmpeg not found in /opt/homebrew/bin. In Terminal run: brew install ffmpeg")
        return 1
    failed = 0
    for video in paths:
        name = os.path.basename(video)
        try:
            open_in_preview(make_sheet(video))
        except SheetError as err:
            failed += 1
            notify(f"Skipped: {err}", subtitle=name)
        except Exception as err:   # anything unexpected still reaches the user
            failed += 1
            notify(f"Failed: {type(err).__name__}: {err}", subtitle=name)
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
