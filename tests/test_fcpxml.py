"""fcpxml.py : un rush (sortie figée, octet pour octet) et plusieurs sources (projets)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
FCPXML = os.path.join(os.path.dirname(HERE), "derush", "fcpxml.py")

# Sortie de fcpxml.py AVANT l'ajout du mode multi-sources (2026-11-05), source a.mp4 1080x1920 30 i/s.
GOLDEN = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.9">
  <resources>
    <format id="r1" frameDuration="1/30s" width="1080" height="1920"/>
    <format id="r3" frameDuration="1/30s" width="1080" height="1920"/>
    <asset id="r2" name="a.mp4" start="0s" duration="3s" hasVideo="1" format="r3" hasAudio="1" audioSources="1" audioChannels="1" audioRate="44100">
      <media-rep kind="original-media" src="@@URL@@"/>
    </asset>
  </resources>
  <library>
    <event name="demo">
      <project name="demo derush">
        <sequence format="r1" duration="13/10s" tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="44.1k">
          <spine>
            <asset-clip ref="r2" name="demo" offset="0s" start="1/2s" duration="7/10s" tcFormat="NDF"/>
            <asset-clip ref="r2" name="demo" offset="7/10s" start="2s" duration="3/5s" tcFormat="NDF"/>
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
"""


def ff(args):
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y"] + args, check=True)


class TestFcpxml(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.a = os.path.join(t, "a.mp4")
        self.b = os.path.join(t, "b.mp4")
        self.m = os.path.join(t, "m.m4a")
        ff(["-f", "lavfi", "-i", "color=c=blue:s=1080x1920:r=30:d=3", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", self.a])
        ff(["-f", "lavfi", "-i", "color=c=red:s=720x1280:r=25:d=3", "-f", "lavfi", "-i", "sine=frequency=330:duration=3",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", self.b])
        ff(["-f", "lavfi", "-i", "sine=frequency=330:duration=2", "-c:a", "aac", self.m])
        self.out = os.path.join(t, "o.fcpxml")

    def tearDown(self):
        self.tmp.cleanup()

    def lancer(self, *args):
        return subprocess.run([sys.executable, "-I", FCPXML, *args], capture_output=True, text=True)

    def test_un_rush_identique(self):
        keep = os.path.join(self.tmp.name, "keep.json")
        json.dump([{"start": 0.5, "end": 1.2}, {"start": 2.0, "end": 2.6}], open(keep, "w"))
        r = self.lancer(self.a, keep, self.out, "demo")
        self.assertEqual(r.returncode, 0, r.stderr)
        url = "file://" + quote(os.path.realpath(self.a))
        self.assertEqual(open(self.out).read(), GOLDEN.replace("@@URL@@", url))

    def test_multi_sources(self):
        clips = os.path.join(self.tmp.name, "clips.json")
        json.dump([
            {"source": self.a, "start": 0.5, "end": 1.0},
            {"source": self.b, "start": 1.0, "end": 1.8},
            {"source": self.a, "start": 2.0, "end": 2.5},
        ], open(clips, "w"))
        r = self.lancer("--multi", clips, self.out, "proj")
        self.assertEqual(r.returncode, 0, r.stderr)
        x = open(self.out).read()
        self.assertEqual(x.count("<asset "), 2)
        self.assertIn('name="a.mp4"', x)
        self.assertIn('name="b.mp4"', x)
        self.assertEqual(x.count("<asset-clip"), 3)
        self.assertEqual([l.split('ref="')[1][:2] for l in x.splitlines() if "<asset-clip" in l], ["r2", "r4", "r2"])
        # le format de l'asset b garde ses dimensions (720x1280, 25 i/s)
        self.assertIn('<format id="r5" frameDuration="1/25s" width="720" height="1280"/>', x)
        # offsets contigus : 0, 1/2, 1/2 + 4/5 = 13/10
        self.assertIn('offset="0s"', x)
        self.assertIn('offset="1/2s"', x)
        self.assertIn('offset="13/10s"', x)
        self.assertIn('duration="9/5s"', x)  # 0.5 + 0.8 + 0.5

    def test_multi_audio_refuse(self):
        clips = os.path.join(self.tmp.name, "clips.json")
        json.dump([{"source": self.m, "start": 0.0, "end": 1.0}], open(clips, "w"))
        r = self.lancer("--multi", clips, self.out, "proj")
        self.assertEqual(r.returncode, 1)
        self.assertIn("source audio : pas de timeline vidéo", r.stderr)


if __name__ == "__main__":
    unittest.main()
