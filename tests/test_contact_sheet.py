"""Tests for scripts/contact_sheet.py. Run by gates/python-scripts.sh on every push.

    /opt/homebrew/bin/python3 -m unittest discover -s tests

The fixture videos are made with ffmpeg at test time. In the "ramp" video every
frame is a flat grey whose brightness is its own frame number, so a grabbed tile
says exactly which frame it is: that is how these tests prove the seeking lands
on the right frame and never repeats the first one.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import contact_sheet as cs  # noqa: E402
from PIL import Image  # noqa: E402

RAMP_FPS = 10


def make_ramp(path, seconds):
    """Video at 10 fps, 64x36, where frame N is grey with luma 16 + N (lossless)."""
    subprocess.run(
        [cs.FFMPEG, "-v", "error", "-y", "-f", "lavfi",
         "-i", f"color=c=black:s=64x36:r={RAMP_FPS}:d={seconds},format=yuv420p,"
               "geq=lum='16+N':cb=128:cr=128",
         "-c:v", "libx264", "-qp", "0", "-g", "50", "-pix_fmt", "yuv420p", path],
        check=True)


def frame_number(img):
    """Read the ramp's frame number back out of a grabbed tile."""
    r, _, _ = img.getpixel((img.width // 2, img.height // 4))
    # Limited-range luma 16 + N decodes to full-range RGB as N * 255 / 219.
    return round(r * 219 / 255)


class Fixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="contact sheet ")
        cls.ramp = os.path.join(cls.dir, "ramp take 1.mp4")      # 21 s: two seams
        cls.short = os.path.join(cls.dir, "short take.mp4")      # 6 s: no seams
        make_ramp(cls.ramp, 21)
        make_ramp(cls.short, 6)
        cls.text = os.path.join(cls.dir, "notes.txt")
        with open(cls.text, "w") as fh:
            fh.write("not a video\n")
        cls.png = os.path.join(cls.dir, "still.png")
        Image.new("RGB", (32, 18), (200, 0, 0)).save(cls.png)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)


class TimeMaths(unittest.TestCase):
    def test_fmt_time(self):
        self.assertEqual(cs.fmt_time(0), "0:00.0")
        self.assertEqual(cs.fmt_time(12.5), "0:12.5")
        self.assertEqual(cs.fmt_time(9.9), "0:09.9")
        self.assertEqual(cs.fmt_time(69.94), "1:09.9")
        self.assertEqual(cs.fmt_time(59.99), "1:00.0")   # rounds into the next minute
        self.assertEqual(cs.fmt_time(600), "10:00.0")

    def test_ratio(self):
        self.assertAlmostEqual(cs._ratio("24000/1001"), 23.976, places=3)
        self.assertEqual(cs._ratio("31.25"), 31.25)
        self.assertEqual(cs._ratio("0/0"), 0.0)
        self.assertEqual(cs._ratio("N/A"), 0.0)
        self.assertEqual(cs._ratio(None), 0.0)

    def test_overview_every_half_second_to_the_last_frame(self):
        # The brief: a 30 s video gives 60 tiles, 0:00.0 to 0:29.5.
        times = cs.overview_times(30.0, 24)
        self.assertEqual(len(times), 60)
        self.assertEqual((times[0], times[1], times[-1]), (0.0, 0.5, 29.5))
        # 31.29 s at 24 fps: the last frame starts at 31.25, so 31.0 is the last tile.
        self.assertEqual(cs.overview_times(31.291667, 24)[-1], 31.0)

    def test_overview_of_a_clip_shorter_than_one_frame(self):
        self.assertEqual(cs.overview_times(0.01, 30), [0.0])

    def test_seams_before_and_after_each_ten_second_mark(self):
        self.assertEqual(cs.seam_times(31.29, 24), [(9.9, 10.3), (19.9, 20.3), (29.9, 30.3)])
        self.assertEqual(cs.seam_times(30.0, 24), [(9.9, 10.3), (19.9, 20.3)])
        self.assertEqual(cs.seam_times(9.99, 24), [])
        # A mark whose after-frame (10.3) doesn't exist is left out.
        self.assertEqual(cs.seam_times(10.2, 24), [])

    def test_seam_pairs_fit_the_overview_width(self):
        sheet_w = cs.LINE + cs.COLUMNS * (cs.TILE_W + cs.LINE)
        sw = cs.seam_tile_width(cs.TILE_W)
        used = cs.COLUMNS * sw + (cs.PAIRS_PER_ROW - 1) * cs.PAIR_GAP + cs.PAIRS_PER_ROW * 3 * cs.LINE
        self.assertEqual(sw % 2, 0)
        self.assertLessEqual(used, sheet_w)
        self.assertGreater(used, sheet_w - 12)

    def test_output_path_sits_next_to_the_video(self):
        self.assertEqual(cs.output_path("/v/take 1.mp4"), "/v/take 1.contact.jpg")
        self.assertEqual(cs.output_path("/v/a.b.mov"), "/v/a.b.contact.jpg")
        self.assertEqual(cs.output_path("/v/noext"), "/v/noext.contact.jpg")


class GrabCommand(unittest.TestCase):
    def test_seeks_before_the_input_and_never_filters_by_select_or_fps(self):
        cmd = cs.grab_command("/v/take.mp4", 12.5, 448)
        self.assertEqual(cmd[0], "/opt/homebrew/bin/ffmpeg")
        self.assertLess(cmd.index("-ss"), cmd.index("-i"))
        self.assertEqual(cmd[cmd.index("-ss") + 1], "12.500")
        vf = cmd[cmd.index("-vf") + 1]
        self.assertNotIn("select", vf)
        self.assertNotIn("fps", vf)
        self.assertEqual(cmd[cmd.index("-frames:v") + 1], "1")

    def test_tools_come_from_homebrew(self):
        self.assertEqual(cs.FFPROBE, "/opt/homebrew/bin/ffprobe")


class WithVideos(Fixtures):
    def test_probe(self):
        duration, fps = cs.probe(self.ramp)
        self.assertAlmostEqual(duration, 21.0, places=1)
        self.assertEqual(fps, RAMP_FPS)

    def test_probe_rejects_files_that_are_not_videos(self):
        for path in (self.text, self.png, os.path.join(self.dir, "missing.mp4")):
            with self.subTest(path=path), self.assertRaises(cs.SheetError) as err:
                cs.probe(path)
            self.assertIn("not a video", str(err.exception))

    def test_probe_treats_unreadable_ffprobe_output_as_not_a_video(self):
        with mock.patch.object(cs.subprocess, "run",
                               return_value=mock.Mock(returncode=1, stdout="garbage")):
            with self.assertRaises(cs.SheetError):
                cs.probe("x.mp4")

    def test_probe_falls_back_to_the_container_duration(self):
        fake = '{"streams":[{"codec_type":"video","duration":"N/A","r_frame_rate":"25/1"}],' \
               '"format":{"duration":"8.0"}}'
        with mock.patch.object(cs.subprocess, "run",
                               return_value=mock.Mock(returncode=0, stdout=fake)):
            self.assertEqual(cs.probe("x.mkv"), (8.0, 25.0))

    def test_probe_defaults_to_30_fps_when_unknown(self):
        fake = '{"streams":[{"codec_type":"video","duration":"5"}]}'
        with mock.patch.object(cs.subprocess, "run",
                               return_value=mock.Mock(returncode=0, stdout=fake)):
            self.assertEqual(cs.probe("x.mkv"), (5.0, 30.0))

    def test_every_overview_tile_is_the_frame_at_its_time(self):
        times = cs.overview_times(*cs.probe(self.ramp))
        frames = cs.grab_all(self.ramp, times, cs.TILE_W)
        self.assertEqual(frames[0].size, (448, 252))          # 16:9 kept
        got = [frame_number(f) for f in frames]
        self.assertEqual(got, [round(t * RAMP_FPS) for t in times])
        self.assertEqual(len(set(got)), len(got), "a frame repeated: fake frozen hold")

    def test_seam_frames_straddle_the_mark(self):
        frames = cs.grab_all(self.ramp, [9.9, 10.3, 19.9, 20.3], 300)
        self.assertEqual([frame_number(f) for f in frames], [99, 103, 199, 203])

    def test_grab_past_the_end_reports_ffmpeg_failure(self):
        with self.assertRaises(cs.SheetError) as err:
            cs.grab(self.short, 50.0, 448)
        self.assertIn("ffmpeg failed at 0:50.0", str(err.exception))

    def test_grab_failure_includes_ffmpeg_error_text(self):
        with self.assertRaises(cs.SheetError) as err:
            cs.grab(os.path.join(self.dir, "missing.mp4"), 1.0, 448)
        self.assertIn("No such file", str(err.exception))

    def test_sheet_with_seams(self):
        out = cs.make_sheet(self.ramp)
        self.assertEqual(out, os.path.join(self.dir, "ramp take 1.contact.jpg"))
        with Image.open(out) as jpeg:
            self.assertEqual(jpeg.format, "JPEG")
            sheet = jpeg.convert("RGB")
        tile_w, tile_h = 448, 252
        seam_w = cs.seam_tile_width(tile_w)
        seam_h = round(seam_w * 36 / 64 / 2) * 2
        rows = -(-42 // 6)                                    # 0.0 .. 20.5 = 42 tiles
        grid_h = cs.LINE + rows * (tile_h + cs.LINE)
        seams_top = grid_h + cs.SECTION_GAP + cs.HEADING_H
        self.assertEqual(sheet.size, (cs.LINE + 6 * (tile_w + cs.LINE),
                                      seams_top + 1 * (seam_h + 2 * cs.LINE) + cs.LINE))
        # Overview tile 7 (row 1, col 1) is the frame at 3.5 s.
        x = cs.LINE + 1 * (tile_w + cs.LINE) + tile_w // 2
        y = cs.LINE + 1 * (tile_h + cs.LINE) + tile_h // 4
        self.assertAlmostEqual(round(sheet.getpixel((x, y))[0] * 219 / 255), 35, delta=1)
        # Seams: second pair's before/after tiles are frames 199 and 203.
        pair_w = 2 * seam_w + 3 * cs.LINE
        sy = seams_top + cs.LINE + seam_h // 4
        bx = pair_w + cs.PAIR_GAP + cs.LINE + seam_w // 2
        ax = bx + seam_w + cs.LINE
        self.assertAlmostEqual(round(sheet.getpixel((bx, sy))[0] * 219 / 255), 199, delta=1)
        self.assertAlmostEqual(round(sheet.getpixel((ax, sy))[0] * 219 / 255), 203, delta=1)
        # The empty cells after the last tile stay paper, not the dark line colour.
        corner = sheet.getpixel((sheet.width - 20, grid_h - 20))
        self.assertTrue(all(abs(a - b) <= 3 for a, b in zip(corner, cs.PAPER)), corner)
        # Each tile carries its time label: the bottom-left corner is the black label box.
        self.assertLess(sum(sheet.getpixel((cs.LINE + 2, cs.LINE + tile_h - 3))), 40)

    def test_short_video_has_no_seams_row(self):
        with Image.open(cs.make_sheet(self.short)) as sheet:
            size = sheet.size
        rows = -(-12 // 6)                                    # 0.0 .. 5.5 = 12 tiles
        self.assertEqual(size, (2702, cs.LINE + rows * (252 + cs.LINE)))

    def test_too_long_for_one_jpeg(self):
        frames = [Image.new("RGB", (40, 20))] * 12
        # 12 tiles of 40x20 make 2 rows: 2 + 2 * 22 = 46 px, over a 40 px limit.
        with mock.patch.object(cs, "JPEG_MAX", 40), self.assertRaises(cs.SheetError):
            cs.build_sheet(frames, [0.0] * 12, [], [])


class Fonts(unittest.TestCase):
    def test_falls_back_to_the_built_in_font(self):
        with mock.patch.object(cs, "FONT_PATHS", ("/nowhere/font.ttf",)):
            font = cs.load_font(20)
        self.assertEqual(font.size, 20)


class Main(Fixtures):
    def setUp(self):
        self.notify = mock.patch.object(cs, "notify").start()
        self.preview = mock.patch.object(cs, "open_in_preview").start()
        self.addCleanup(mock.patch.stopall)

    def test_several_files_each_get_a_sheet_opened_in_preview(self):
        self.assertEqual(cs.main([self.ramp, self.short]), 0)
        self.assertEqual([c.args[0] for c in self.preview.call_args_list],
                         [os.path.join(self.dir, "ramp take 1.contact.jpg"),
                          os.path.join(self.dir, "short take.contact.jpg")])
        self.notify.assert_not_called()

    def test_a_bad_file_notifies_and_the_rest_still_run(self):
        self.assertEqual(cs.main([self.text, self.short]), 1)
        self.notify.assert_called_once_with("Skipped: not a video", subtitle="notes.txt")
        self.preview.assert_called_once()

    def test_unexpected_errors_still_notify(self):
        with mock.patch.object(cs, "make_sheet", side_effect=OSError("disk full")):
            self.assertEqual(cs.main([self.short]), 1)
        self.notify.assert_called_once_with("Failed: OSError: disk full", subtitle="short take.mp4")

    def test_missing_pillow_says_how_to_install_it(self):
        # Load a fresh copy of the script with Pillow made unimportable.
        spec = importlib.util.spec_from_file_location("contact_sheet_no_pil", cs.__file__)
        bare = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {"PIL": None}):
            spec.loader.exec_module(bare)
        self.assertIsNone(bare.Image)
        with mock.patch.object(bare, "notify") as notify:
            self.assertEqual(bare.main([self.short]), 1)
        self.assertIn("pip install --break-system-packages Pillow", notify.call_args.args[0])

    def test_missing_ffmpeg_says_how_to_install_it(self):
        with mock.patch.object(cs, "FFMPEG", "/nowhere/ffmpeg"):
            self.assertEqual(cs.main([self.short]), 1)
        self.assertIn("brew install ffmpeg", self.notify.call_args.args[0])


class SystemCalls(unittest.TestCase):
    def test_notify_escapes_quotes_for_applescript(self):
        with mock.patch.object(cs.subprocess, "run") as run:
            cs.notify('Skipped: not a video', subtitle='my "best" take\\1.mov')
        script = run.call_args.args[0][2]
        self.assertEqual(run.call_args.args[0][:2], ["/usr/bin/osascript", "-e"])
        self.assertEqual(script, 'display notification "Skipped: not a video" with title '
                                 '"Contact Sheet" subtitle "my \\"best\\" take\\\\1.mov"')

    def test_notify_without_subtitle(self):
        with mock.patch.object(cs.subprocess, "run") as run:
            cs.notify("hello")
        self.assertNotIn("subtitle", run.call_args.args[0][2])

    def test_open_in_preview(self):
        with mock.patch.object(cs.subprocess, "run") as run:
            cs.open_in_preview("/v/take 1.contact.jpg")
        self.assertEqual(run.call_args.args[0],
                         ["/usr/bin/open", "-a", "Preview", "/v/take 1.contact.jpg"])


if __name__ == "__main__":
    unittest.main()
