"""Headless tests. Run with the `bpy` wheel (pip install bpy) or Blender:

    python tests/test_timelender.py
    blender -b --python tests/test_timelender.py
"""
import os
import sys
import tempfile
import time
import unittest

import bpy  # noqa: I001 (must come first: puts addon_utils on sys.path)
import addon_utils

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(REPO))
ADDON = os.path.basename(REPO)
addon_utils.enable(ADDON, default_set=True)
tl = sys.modules[ADDON]



class Clock:
    def __init__(self):
        self.now, self.cpu = time.monotonic(), 0.0

    def tick(self, seconds=1.0, cpu=0.0):
        self.now += seconds
        self.cpu += cpu
        tl._step(self.now, self.cpu)


class TimeLenderTest(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_homefile(app_template="")
        tl._load_from_file()
        self.clock = Clock()
        tl._S.last_tick, tl._S.last_cpu = self.clock.now, self.clock.cpu
        tl._S.ignore_until = 0.0
        self.prefs = tl._prefs()
        self.prefs.auto_pause = True
        self.prefs.auto_resume = True
        self.prefs.inactivity_minutes = 1

    def test_fmt(self):
        self.assertEqual(tl._fmt(0), "00:00:00")
        self.assertEqual(tl._fmt(3725.9), "01:02:05")
        self.assertEqual(tl._fmt(-5), "00:00:00")

    def test_prefs_registered(self):
        self.assertIsNot(self.prefs, tl._DefaultPrefs)

    def test_auto_start_waits_for_activity(self):
        self.assertTrue(tl._S.pending_auto_start)
        for _ in range(5):
            self.clock.tick()
        self.assertFalse(tl._S.running)
        self.assertEqual(tl._S.elapsed, 0)
        tl._touch(self.clock.now)
        self.clock.tick()
        self.assertTrue(tl._S.running)

    def test_counts_wall_time_not_ticks(self):
        bpy.ops.timelender.start()
        self.clock.tick(1.5)
        self.clock.tick(0.5)
        self.assertAlmostEqual(tl._S.elapsed, 2.0)

    def test_auto_pause_refunds_idle_time_and_resumes(self):
        bpy.ops.timelender.start()
        for _ in range(30):
            tl._touch(self.clock.now)
            self.clock.tick()
        worked = tl._S.elapsed
        for _ in range(70):
            self.clock.tick()
        self.assertFalse(tl._S.running)
        self.assertTrue(tl._S.idle_paused)
        self.assertLessEqual(tl._S.elapsed, worked + 1)
        tl._touch(self.clock.now)
        self.clock.tick()
        self.assertTrue(tl._S.running)

    def test_manual_pause_does_not_auto_resume(self):
        bpy.ops.timelender.start()
        bpy.ops.timelender.pause()
        tl._touch(self.clock.now)
        self.clock.tick()
        self.assertFalse(tl._S.running)

    def test_sleep_gap_not_billed_busy_gap_billed(self):
        self.prefs.auto_pause = False
        bpy.ops.timelender.start()
        self.clock.tick(600, cpu=1)       # laptop asleep
        self.assertAlmostEqual(tl._S.elapsed, 1.0)
        self.clock.tick(30, cpu=29)      # blocking bake
        self.assertAlmostEqual(tl._S.elapsed, 31.0)

    def test_save_load_roundtrip_with_multiple_scenes(self):
        bpy.ops.timelender.start()
        for _ in range(42):
            tl._touch(self.clock.now)
            self.clock.tick()
        bpy.data.scenes.new("Other")
        path = os.path.join(tempfile.mkdtemp(), "t.blend")
        bpy.ops.wm.save_as_mainfile(filepath=path)
        bpy.ops.wm.read_homefile(app_template="")
        self.assertEqual(tl._S.elapsed, 0)
        bpy.ops.wm.open_mainfile(filepath=path)
        self.assertEqual(int(tl._S.elapsed), 42)
        self.assertTrue(all(s.tl_elapsed == 42 for s in bpy.data.scenes))
        events = [e for _, e, _ in tl._S.log]
        self.assertIn("Project saved", events)
        self.assertEqual(events[-1], "Project opened")
        self.assertFalse(tl._S.running)

    def test_export_csv(self):
        bpy.ops.timelender.start()
        path = os.path.join(tempfile.mkdtemp(), "log.csv")
        self.assertEqual(bpy.ops.timelender.export_log(filepath=path), {'FINISHED'})
        with open(path, encoding="utf-8") as f:
            self.assertIn("Timer started", f.read())


if __name__ == "__main__":
    argv = [sys.argv[0]] + (sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    result = unittest.main(argv=argv, exit=False).result
    addon_utils.disable(ADDON)
    sys.exit(not result.wasSuccessful())
