import json
from pathlib import Path
import queue
import struct
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from windows_capture import Area, CaptureSession, png_size, validate_settings


class CaptureTests(unittest.TestCase):
    def test_negative_monitor_coordinates_are_physical_pixels(self):
        rect = Area(-1920, 20, 1920, 1080)
        self.assertTrue(rect.fits({"left": -1920, "top": 0, "width": 4480, "height": 1440}))
        self.assertFalse(rect.fits({"left": 0, "top": 0, "width": 2560, "height": 1440}))
        with self.assertRaises(ValueError):Area(0, 0, 0, 1080)
        with self.assertRaises(ValueError):Area(True, 0, 640, 360)

    def test_long_monitoring_and_all_frame_mode_are_allowed(self):
        validate_settings(600, 20, 1)
        validate_settings(600, 20, 0)
        for settings in [(0, 20, 1), (600, 0, 1), (600, 20, -1), (float('nan'), 20, 1), (600, True, 1)]:
            with self.assertRaises(ValueError):validate_settings(*settings)

    def test_png_dimensions_not_derived_from_dpi_or_title_bar(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'frame.png'
            p.write_bytes(b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR' + struct.pack('>II', 1920, 1080))
            self.assertEqual(png_size(p), (1920, 1080))
            p.write_bytes(b'not a png')
            with self.assertRaises(ValueError):png_size(p)

    def test_writer_backpressure_is_bounded_and_actual_frames_are_logged(self):
        class Shot:
            rgb = b'\x20\x40\x60' * 4
            size = (2, 2)
            def pixel(self, x, y):return (32, 64, 96)
        class Grabber:
            monitors = [{"left": 0, "top": 0, "width": 1920, "height": 1080}]
            def __enter__(self):return self
            def __exit__(self, *args):return False
            def grab(self, region):
                self_test.assertEqual(region, {"left": 1, "top": 2, "width": 2, "height": 2})
                if session.snapshot()['captured'] >= 18:session.stop.set()
                return Shot()
        def encode(rgb, size, level, output):
            time.sleep(.045)
            Path(output).write_bytes(b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR' + struct.pack('>II', *size))
        self_test = self
        api = SimpleNamespace(dpi_mode='test', title=lambda hwnd:'fixture', dpi=lambda hwnd:144,
                              area=lambda hwnd:Area(1, 2, 2, 2), foreground=lambda hwnd:True,
                              user=SimpleNamespace(IsWindow=lambda hwnd:True, IsIconic=lambda hwnd:False))
        modules = {'mss':SimpleNamespace(MSS=Grabber), 'mss.tools':SimpleNamespace(to_png=encode)}
        with tempfile.TemporaryDirectory() as directory, patch.dict('sys.modules', modules):
            session = CaptureSession(api, 123, Path(directory), duration=2, fps=60, interval=0)
            session.thread.start(); session.thread.join(5)
            self.assertFalse(session.thread.is_alive())
            stats = session.snapshot()
            self.assertIsNone(stats['failure'])
            self.assertGreater(stats['save_queue_dropped'], 0)
            self.assertEqual(stats['saved'] + stats['save_queue_dropped'], stats['captured'])
            self.assertEqual(session.pending.maxsize, 3)
            records = [json.loads(line) for line in (session.folder/'frames.jsonl').read_text().splitlines()]
            self.assertEqual(len(records), stats['saved'])
            self.assertEqual(records[0]['window_dpi'], 144)
            self.assertTrue(all(png_size(session.folder/row['file']) == (2, 2) for row in records))
            self.assertTrue(all(a['elapsed_s'] < b['elapsed_s'] for a,b in zip(records, records[1:])))
            self.assertFalse(list(session.folder.glob('*.part')))


if __name__ == '__main__':unittest.main()
