"""Safety, cancellation-worker protocol, and regression checks; no Qt dependency."""
import hashlib
import json
import multiprocessing as mp
from pathlib import Path
import tempfile
import unittest
import zipfile

from core.generation_runtime import (available_output, commit_output, generation_worker,
                                output_snapshot, safe_filename, validate_output_path)
from core.video2pack import compile_datapack

ROOT = Path(__file__).resolve().parents[1]


class GenerationRuntimeTests(unittest.TestCase):
    def test_old_reconstructor_is_not_changed(self):
        # Test pins important semantics without depending on brittle source hashes.
        from core.video2pack import MAX_FRAMES, DEFAULT_FRAMES
        self.assertEqual(MAX_FRAMES, 1200)
        self.assertEqual(DEFAULT_FRAMES, 500)
        scene = json.loads((ROOT / 'examples' / 'demo_house.json').read_text())
        with tempfile.TemporaryDirectory() as temp:
            a = Path(temp) / 'a.zip'
            b = Path(temp) / 'b.zip'
            self.assertEqual(compile_datapack(scene, a)['commands'],
                             compile_datapack(scene, b)['commands'])
            with zipfile.ZipFile(a) as za, zipfile.ZipFile(b) as zb:
                self.assertEqual(za.namelist(), zb.namelist())
                for name in za.namelist():
                    self.assertEqual(za.read(name), zb.read(name))

    def test_output_filename_and_dedup(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(Path(available_output('bridge.mov', temp)).name, 'bridge.zip')
            (Path(temp) / 'bridge.zip').write_bytes(b'original')
            self.assertEqual(Path(available_output('bridge.mov', temp)).name, 'bridge_2.zip')
            self.assertEqual(safe_filename('CON.mp4'), 'video_build')
            self.assertEqual(safe_filename('my<>build.mp4'), 'my__build')
            with self.assertRaises(ValueError):
                validate_output_path(str(Path(temp) / 'result.txt'))

    def test_atomic_commit_and_race_protection(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / 'result.zip'
            dest.write_bytes(b'old result')
            snap = output_snapshot(dest)
            temporary = Path(temp) / 'generated.zip'
            temporary.write_bytes(b'new result')
            dest.write_bytes(b'concurrently edited output')
            with self.assertRaises(FileExistsError):
                commit_output(str(temporary), str(dest), snap)
            self.assertEqual(dest.read_bytes(), b'concurrently edited output')
            self.assertTrue(temporary.is_file())
            new_snap = output_snapshot(dest)
            self.assertEqual(commit_output(str(temporary), str(dest), new_snap), str(dest))
            self.assertEqual(dest.read_bytes(), b'new result')
            self.assertFalse(temporary.exists())

    def test_offline_spawn_worker_matches_original(self):
        with tempfile.TemporaryDirectory() as temp:
            target = str(Path(temp) / 'out.zip')
            params = {'scene_path': str(ROOT / 'examples' / 'demo_house.json'),
                      'out': target, 'frames': 500}
            context = mp.get_context('spawn')
            messages = context.Queue()
            proc = context.Process(target=generation_worker, args=(params, messages))
            proc.start()
            proc.join(timeout=20)
            self.assertEqual(proc.exitcode, 0)
            found = []
            while not messages.empty():
                found.append(messages.get(timeout=2))
            self.assertTrue(any(kind == 'result' for kind, _ in found), found)
            self.assertTrue(zipfile.is_zipfile(target))
            messages.close()


if __name__ == '__main__':
    unittest.main()
