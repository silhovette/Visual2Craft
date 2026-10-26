"""Deterministic checks for the live scene data path and batched mesh."""
import json
from pathlib import Path
import queue
import tempfile
import unittest

from generation_runtime import generation_worker
from live_scene import BlockGeometry, scene_blocks

ROOT = Path(__file__).resolve().parents[1]


class LiveReconstructionTests(unittest.TestCase):
    def test_preview_uses_final_resolved_plan_and_air_removes_blocks(self):
        scene = json.loads((ROOT / 'examples' / 'demo_house.json').read_text(encoding='utf-8'))
        blocks = scene_blocks(scene)
        self.assertTrue(blocks)
        self.assertNotIn('minecraft:air', blocks.values())
        scene['ops'].append({
            'action': 'clear', 'confidence': 'confirmed', 'evidence': None,
            'replace': True, 'block': 'minecraft:air', 'from': [0, 0, 0], 'to': [0, 0, 0],
        })
        self.assertNotIn((0, 0, 0), scene_blocks(scene))

    def test_large_same_block_scene_is_one_mesh(self):
        scene = {
            'name': 'mesh', 'size': [32, 16, 32], 'base_y': 0,
            'ops': [{
                'action': 'place', 'confidence': 'confirmed',
                'evidence': {'frames': [0], 'observation': 'floor', 'hint': None},
                'replace': False, 'block': 'minecraft:stone',
                'from': [0, 0, 0], 'to': [31, 15, 31],
            }], 'entities': [],
        }
        blocks = scene_blocks(scene)
        self.assertEqual(len(blocks), 16_384)
        geometry = BlockGeometry()
        geometry.update_blocks(blocks)
        self.assertEqual(geometry.block_count, len(blocks))
        # Interior faces are culled, keeping the upload bounded for dense builds.
        self.assertLess(len(geometry.vertexData()), len(blocks) * 40 * 24)

    def test_qml_uses_batched_geometry_and_not_one_model_per_block(self):
        qml = (ROOT / 'qml' / 'components' / 'LiveReconstruction.qml').read_text(encoding='utf-8')
        self.assertIn('geometry: root.blockGeometry', qml)
        self.assertNotIn('Repeater3D', qml)
        self.assertNotIn('source: modelData', qml)

    def test_invisible_special_blocks_remain_datapack_only(self):
        scene = {
            'name': 'special', 'size': [3, 2, 3], 'base_y': 0,
            'ops': [{
                'action': 'place', 'confidence': 'confirmed',
                'evidence': {'frames': [0], 'observation': 'light', 'hint': None},
                'replace': False, 'block': 'minecraft:light[level=15,waterlogged=false]',
                'from': [1, 0, 1], 'to': [1, 0, 1],
            }], 'entities': [],
        }
        self.assertEqual(scene_blocks(scene), {})

    def test_terminal_worker_result_carries_scene_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            messages = queue.Queue()
            generation_worker({
                'scene_path': str(ROOT / 'examples' / 'demo_house.json'),
                'out': str(Path(temp) / 'build.zip'), 'frames': 500,
            }, messages)
            terminal = None
            while not messages.empty():
                kind, value = messages.get_nowait()
                if kind == 'result':
                    terminal = value
            self.assertIsInstance(terminal, dict)
            self.assertIn('_live_scene', terminal)
            self.assertTrue(terminal['_live_scene']['ops'])


if __name__ == '__main__':
    unittest.main()
