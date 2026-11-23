"""Tests for scripts/extract_audio.py. Run by gates/python-scripts.sh on every push.

    /opt/homebrew/bin/python3 -m unittest discover -s tests

The fixture videos are made with ffmpeg at test time, one per audio codec. The
core proof is that the extracted file holds the very same audio packets as the
video (a stream hash of both), so nothing was re-encoded.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import extract_audio as ea  # noqa: E402

VIDEO = ["-f", "lavfi", "-i", "color=c=blue:s=64x36:r=10:d=1"]
TONE = ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1"]
BEEP = ["-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=1"]


def make(path, inputs, *options):
    subprocess.run([ea.FFMPEG, "-v", "error", "-y", *inputs, "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", *options, "-shortest", path], check=True)


def probe(path, entry):
    """codec_name (or another stream field) of every audio stream, in order."""
    out = subprocess.run([ea.FFPROBE, "-v", "error", "-select_streams", "a",
                          "-show_entries", f"stream={entry}", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout
    return out.split()


def packet_hash(path, stream="0:a:0"):
    """MD5 of the audio packets exactly as stored (no decode)."""
    return subprocess.run([ea.FFMPEG, "-v", "error", "-i", path, "-map", stream,
                           "-c", "copy", "-f", "streamhash", "-hash", "md5", "-"],
                          capture_output=True, text=True, check=True).stdout.split("=")[-1]


def sample_hash(path):
    """MD5 of the decoded samples, as 32-bit little-endian, whatever the storage."""
    return subprocess.run([ea.FFMPEG, "-v", "error", "-i", path, "-map", "0:a:0",
                           "-c:a", "pcm_s32le", "-f", "md5", "-"],
                          capture_output=True, text=True, check=True).stdout


class Fixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="extract audio ")
        p = lambda name: os.path.join(cls.dir, name)  # noqa: E731
        cls.aac = p("take 1.mp4");       make(cls.aac, VIDEO + TONE, "-c:a", "aac")
        cls.mp3 = p("mp3 take.mp4");     make(cls.mp3, VIDEO + TONE, "-c:a", "libmp3lame")
        cls.opus = p("opus take.mkv");   make(cls.opus, VIDEO + TONE, "-c:a", "libopus")
        cls.flac = p("flac take.mkv");   make(cls.flac, VIDEO + TONE, "-c:a", "flac")
        cls.pcm = p("camera.mov");       make(cls.pcm, VIDEO + TONE, "-c:a", "pcm_s16be")
        cls.mp2 = p("broadcast.mkv");    make(cls.mp2, VIDEO + TONE, "-c:a", "mp2")
        cls.two = p("two tracks.mp4")
        make(cls.two, VIDEO + TONE + BEEP, "-map", "0:v", "-map", "1:a", "-map", "2:a",
             "-c:a:0", "aac", "-c:a:1", "libmp3lame")
        cls.silent = p("silent.mp4");    make(cls.silent, VIDEO)
        cls.text = p("notes.txt")
        with open(cls.text, "w") as fh:
            fh.write("not a video\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def fresh(self, src):
        """Copy a fixture into its own folder, so outputs never collide between tests."""
        folder = tempfile.mkdtemp(dir=self.dir)
        return shutil.copy(src, folder)


class Plan(unittest.TestCase):
    def test_compressed_codecs_are_copied_into_their_own_container(self):
        self.assertEqual(ea.plan("aac"), ("m4a", "copy"))
        self.assertEqual(ea.plan("alac"), ("m4a", "copy"))
        self.assertEqual(ea.plan("mp3"), ("mp3", "copy"))
        self.assertEqual(ea.plan("opus"), ("opus", "copy"))
        self.assertEqual(ea.plan("vorbis"), ("ogg", "copy"))
        self.assertEqual(ea.plan("flac"), ("flac", "copy"))
        self.assertEqual(ea.plan("ac3"), ("ac3", "copy"))
        self.assertEqual(ea.plan("eac3"), ("eac3", "copy"))

    def test_pcm_goes_to_wav_little_endian_at_the_same_depth(self):
        self.assertEqual(ea.plan("pcm_s16le"), ("wav", "copy"))
        self.assertEqual(ea.plan("pcm_s24le"), ("wav", "copy"))
        self.assertEqual(ea.plan("pcm_s16be"), ("wav", "pcm_s16le"))
        self.assertEqual(ea.plan("pcm_s24be"), ("wav", "pcm_s24le"))
        self.assertEqual(ea.plan("pcm_f32be"), ("wav", "pcm_f32le"))

    def test_anything_else_is_copied_into_matroska(self):
        self.assertEqual(ea.plan("mp2"), ("mka", "copy"))
        self.assertEqual(ea.plan("dts"), ("mka", "copy"))
        self.assertEqual(ea.plan("pcm_s8"), ("mka", "copy"))   # PCM that WAV can't hold


class OutputPath(Fixtures):
    def test_named_after_the_video_next_to_it(self):
        self.assertEqual(ea.output_path("/nowhere/take 1.mp4", "m4a"), "/nowhere/take 1.m4a")
        self.assertEqual(ea.output_path("/nowhere/a.b.mov", "wav"), "/nowhere/a.b.wav")
        self.assertEqual(ea.output_path("/nowhere/noext", "mp3"), "/nowhere/noext.mp3")

    def test_never_overwrites_it_numbers_like_finder(self):
        video = self.fresh(self.aac)
        stem = os.path.splitext(video)[0]
        for taken in (f"{stem}.m4a", f"{stem} 2.m4a"):
            open(taken, "w").close()
        self.assertEqual(ea.output_path(video, "m4a"), f"{stem} 3.m4a")

    def test_a_broken_symlink_counts_as_taken(self):
        video = self.fresh(self.aac)
        stem = os.path.splitext(video)[0]
        os.symlink("/nowhere/at/all", f"{stem}.m4a")
        self.assertEqual(ea.output_path(video, "m4a"), f"{stem} 2.m4a")


class Command(unittest.TestCase):
    def test_first_audio_track_only_never_overwriting(self):
        cmd = ea.extract_command("/v/in.mp4", "/v/in.m4a", "copy")
        self.assertEqual(cmd[0], "/opt/homebrew/bin/ffmpeg")
        self.assertIn("-n", cmd)
        self.assertNotIn("-y", cmd)
        self.assertEqual(cmd[cmd.index("-map") + 1], "0:a:0")
        self.assertEqual(cmd[cmd.index("-c:a") + 1], "copy")
        self.assertEqual(cmd[cmd.index("-i") + 1], "/v/in.mp4")
        self.assertEqual(cmd[-1], "/v/in.m4a")


class Extract(Fixtures):
    def check_copied(self, src, ext, codec):
        video = self.fresh(src)
        out = ea.extract(video)
        self.assertEqual(out, os.path.splitext(video)[0] + "." + ext)
        self.assertEqual(probe(out, "codec_name"), [codec])
        self.assertEqual(packet_hash(out), packet_hash(video))
        self.assertTrue(os.path.exists(video))   # the original is untouched
        return out

    def test_aac_mp4_becomes_an_identical_m4a(self):
        self.check_copied(self.aac, "m4a", "aac")

    def test_mp3(self):
        self.check_copied(self.mp3, "mp3", "mp3")

    def test_opus(self):
        self.check_copied(self.opus, "opus", "opus")

    def test_flac(self):
        self.check_copied(self.flac, "flac", "flac")

    def test_unknown_codec_falls_back_to_mka(self):
        self.check_copied(self.mp2, "mka", "mp2")

    def test_big_endian_pcm_becomes_a_wav_with_the_same_samples(self):
        video = self.fresh(self.pcm)
        out = ea.extract(video)
        self.assertTrue(out.endswith("camera.wav"))
        self.assertEqual(probe(out, "codec_name"), ["pcm_s16le"])
        self.assertEqual(sample_hash(out), sample_hash(video))

    def test_only_the_first_of_two_tracks(self):
        out = self.check_copied(self.two, "m4a", "aac")
        self.assertNotEqual(packet_hash(out), packet_hash(self.two, "0:a:1"))

    def test_second_run_adds_a_number_instead_of_overwriting(self):
        video = self.fresh(self.aac)
        first = ea.extract(video)
        before = os.path.getmtime(first)
        second = ea.extract(video)
        self.assertTrue(second.endswith("take 1 2.m4a"))
        self.assertEqual(os.path.getmtime(first), before)

    def test_video_with_no_audio(self):
        video = self.fresh(self.silent)
        with self.assertRaisesRegex(ea.ExtractError, "no audio track"):
            ea.extract(video)
        self.assertEqual(os.listdir(os.path.dirname(video)), ["silent.mp4"])

    def test_not_a_video(self):
        with self.assertRaisesRegex(ea.ExtractError, "not a video"):
            ea.audio_codec(self.text)

    def test_unreadable_probe_output_means_no_audio(self):
        bad = subprocess.CompletedProcess([], 0, stdout="not json", stderr="")
        with mock.patch.object(ea.subprocess, "run", return_value=bad):
            with self.assertRaisesRegex(ea.ExtractError, "no audio track"):
                ea.audio_codec("/v/x.mp4")

    def test_ffmpeg_failure_removes_the_half_written_file(self):
        video = self.fresh(self.aac)
        out = os.path.splitext(video)[0] + ".m4a"
        real_run = subprocess.run

        def fail_midway(cmd, **kw):
            if cmd[0] == ea.FFMPEG:
                open(out, "w").close()
                return subprocess.CompletedProcess(cmd, 1, "", "header\nDisk full\n")
            return real_run(cmd, **kw)

        with mock.patch.object(ea.subprocess, "run", side_effect=fail_midway):
            with self.assertRaisesRegex(ea.ExtractError, "^ffmpeg failed: Disk full$"):
                ea.extract(video)
        self.assertFalse(os.path.exists(out))

    def test_ffmpeg_failure_with_no_message(self):
        video = self.fresh(self.aac)
        real_run = subprocess.run
        fail = lambda cmd, **kw: (subprocess.CompletedProcess(cmd, 1, "", "")  # noqa: E731
                                  if cmd[0] == ea.FFMPEG else real_run(cmd, **kw))
        with mock.patch.object(ea.subprocess, "run", side_effect=fail):
            with self.assertRaisesRegex(ea.ExtractError, "^ffmpeg failed$"):
                ea.extract(video)

    def test_a_file_that_appeared_meanwhile_is_left_alone(self):
        # Someone took the name between output_path() and ffmpeg: -n refuses, and
        # that file is not ours to delete.
        video = self.fresh(self.aac)
        out = os.path.splitext(video)[0] + ".m4a"
        real_out = ea.output_path

        def taken_meanwhile(v, ext):
            path = real_out(v, ext)
            with open(path, "w") as fh:
                fh.write("someone else's")
            return path

        with mock.patch.object(ea, "output_path", side_effect=taken_meanwhile):
            with self.assertRaisesRegex(ea.ExtractError, "already exists"):
                ea.extract(video)
        with open(out) as fh:
            self.assertEqual(fh.read(), "someone else's")


class Main(Fixtures):
    def run_main(self, paths):
        with mock.patch.object(ea, "notify") as notify:
            code = ea.main(paths)
        return code, [c.args + tuple(c.kwargs.values()) for c in notify.call_args_list]

    def test_all_good_is_silent_and_writes_each_file(self):
        a, b = self.fresh(self.aac), self.fresh(self.mp3)
        code, notes = self.run_main([a, b])
        self.assertEqual((code, notes), (0, []))
        self.assertTrue(os.path.exists(os.path.splitext(a)[0] + ".m4a"))
        self.assertTrue(os.path.exists(os.path.splitext(b)[0] + ".mp3"))

    def test_a_bad_file_is_reported_and_the_rest_still_run(self):
        good = self.fresh(self.aac)
        code, notes = self.run_main([self.silent, self.text, good])
        self.assertEqual(code, 1)
        self.assertEqual(notes, [("Skipped: no audio track", "silent.mp4"),
                                 ("Skipped: not a video", "notes.txt")])
        self.assertTrue(os.path.exists(os.path.splitext(good)[0] + ".m4a"))

    def test_unexpected_errors_still_reach_the_user(self):
        with mock.patch.object(ea, "extract", side_effect=PermissionError("read-only")):
            code, notes = self.run_main(["/v/take.mp4"])
        self.assertEqual((code, notes), (1, [("Failed: PermissionError: read-only", "take.mp4")]))

    def test_missing_ffmpeg_says_how_to_install_it(self):
        with mock.patch.object(ea, "FFMPEG", "/nonexistent/ffmpeg"):
            code, notes = self.run_main([self.aac])
        self.assertEqual(code, 1)
        self.assertIn("brew install ffmpeg", notes[0][0])


class Notify(unittest.TestCase):
    def test_quotes_and_backslashes_are_escaped_for_applescript(self):
        with mock.patch.object(ea.subprocess, "run") as run:
            ea.notify('say "hi" \\ bye', subtitle='take "1".mp4')
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[:2], ["/usr/bin/osascript", "-e"])
        self.assertEqual(cmd[2], 'display notification "say \\"hi\\" \\\\ bye" '
                                 'with title "Extract Audio" subtitle "take \\"1\\".mp4"')

    def test_no_subtitle(self):
        with mock.patch.object(ea.subprocess, "run") as run:
            ea.notify("hello")
        self.assertEqual(run.call_args.args[0][2],
                         'display notification "hello" with title "Extract Audio"')


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
