"""Run with python3 -m unittest discover -s tests. Needs ffmpeg/ffprobe; skipped otherwise."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "video-compress/scripts/compress_video.py"
HAVE_FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


def make_video(path, size="1280x720", seconds=4, crf=8):
    # Noise keeps the source large, so size-targeted runs really have to work.
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", str(seconds),
                    "-vf", "noise=alls=30:allf=t", "-c:v", "libx264", "-crf", str(crf), "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(path)], check=True)


def info(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,height",
                        "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe not installed")
class VideoCompress(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.big = Path(cls.tmp.name) / "big.mp4"
        make_video(cls.big)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def run_script(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True, timeout=300)

    def test_max_size_fits_and_keeps_streams_and_source(self):
        before = digest(self.big)
        limit = self.big.stat().st_size // 3
        r = self.run_script(self.big, "-o", self.dir, "--max-size", f"{limit / 1024:.0f}K", "--preset", "veryfast")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.dir / "big.mp4"
        self.assertLessEqual(out.stat().st_size, limit)
        streams = {s["codec_type"]: s["codec_name"] for s in info(out)["streams"]}
        self.assertEqual(streams, {"video": "h264", "audio": "aac"})
        self.assertAlmostEqual(float(info(out)["format"]["duration"]), 4.0, delta=0.5)
        self.assertEqual(digest(self.big), before, "source must stay untouched")

    def test_crf_mode_and_max_height_never_upscales(self):
        r = self.run_script(self.big, "-o", self.dir / "a", "--crf", "30", "--max-height", "360", "--preset", "veryfast")
        self.assertEqual(r.returncode, 0, r.stderr)
        height = [s for s in info(self.dir / "a/big.mp4")["streams"] if s["codec_type"] == "video"][0]["height"]
        self.assertEqual(height, 360)
        r = self.run_script(self.big, "-o", self.dir / "b", "--crf", "30", "--max-height", "2160", "--preset", "veryfast")
        self.assertEqual(r.returncode, 0, r.stderr)
        height = [s for s in info(self.dir / "b/big.mp4")["streams"] if s["codec_type"] == "video"][0]["height"]
        self.assertEqual(height, 720)

    def test_already_small_mp4_is_copied_but_other_containers_are_encoded(self):
        r = self.run_script(self.big, "-o", self.dir / "copy", "--max-size", "1G")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(digest(self.dir / "copy/big.mp4"), digest(self.big))
        self.assertIn("copied unchanged", r.stdout)
        mov = self.dir / "clip.mov"
        shutil.copy2(self.big, mov)
        r = self.run_script(mov, "-o", self.dir / "mov", "--max-size", "1G", "--preset", "veryfast")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("copied unchanged", r.stdout)
        self.assertTrue((self.dir / "mov/clip.mp4").exists())

    def test_unreachable_size_fails_without_leaving_a_partial_file(self):
        r = self.run_script(self.big, "-o", self.dir, "--max-size", "1K", "--preset", "ultrafast")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--max-height", r.stderr)
        self.assertFalse((self.dir / "big.mp4").exists())

    def test_directory_source_keeps_structure_and_refuses_nested_output(self):
        src = self.dir / "src"
        (src / "nested").mkdir(parents=True)
        shutil.copy2(self.big, src / "nested/one.mov")
        (src / "notes.txt").write_text("not a video")
        r = self.run_script(src, "--crf", "32", "--preset", "ultrafast")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.dir / "src-compressed/nested/one.mp4").exists())
        self.assertFalse((self.dir / "src-compressed/notes.txt").exists())
        r = self.run_script(src, "-o", src / "out")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((src / "out").exists())

    def test_dry_run_writes_nothing(self):
        r = self.run_script(self.big, "-o", self.dir / "plan", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("big.mp4", r.stdout)
        self.assertFalse((self.dir / "plan").exists())


if __name__ == "__main__":
    unittest.main()
