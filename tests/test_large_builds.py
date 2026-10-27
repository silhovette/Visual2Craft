"""Exercise large geometry through planning, export, and the preview store."""
import tempfile
from pathlib import Path
import unittest
import zipfile

from core.block_rules import prepare_plan
from core.live_scene import scene_blocks
from core.video2pack import compile_datapack, validate_scene, MAX_COMMANDS, split_fill


def region(block, start, end=None):
    return {'block': block, 'from': list(start), 'to': list(end or start)}


class LargeBuildTests(unittest.TestCase):
    def export_commands(self, scene):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'large.zip'
            summary = compile_datapack(scene, target)
            with zipfile.ZipFile(target) as pack:
                commands = '\n'.join(pack.read(name).decode() for name in pack.namelist()
                                     if '/parts/part_' in name)
                self.assertIsNone(pack.testzip())
        return summary, commands

    def test_tower_preserves_all_300_floors_and_roof(self):
        ops = []
        for y in range(300):
            ops.extend([region('minecraft:stone', (0, y, 0), (15, y, 0)),
                        region('minecraft:glass', (0, y, 15), (15, y, 15))])
        ops.append(region('minecraft:gold_block', (0, 300, 0), (15, 300, 15)))
        summary, commands = self.export_commands({'size': [16, 301, 16], 'ops': ops})
        self.assertEqual(summary['operations'], 601)
        self.assertEqual(summary['commands'], 601)
        self.assertIn('~0 ~299 ~15 ~15 ~299 ~15 minecraft:glass', commands)
        self.assertIn('~0 ~300 ~0 ~15 ~300 ~15 minecraft:gold_block', commands)

    def test_estate_retains_distant_wings(self):
        summary, commands = self.export_commands({'size': [512, 80, 512], 'ops': [
            region('minecraft:stone_bricks', (0, 0, 0), (511, 0, 511)),
            region('minecraft:oak_planks', (480, 1, 480), (511, 79, 511)),
            region('minecraft:quartz_block', (0, 1, 480), (31, 79, 511)),
        ]})
        self.assertEqual(summary['size'], [512, 80, 512])
        self.assertIn('~511', commands)
        self.assertIn('~79', commands)
        self.assertIn('minecraft:quartz_block', commands)

    def test_full_capacity_compiles_without_expanding_100_million_cells(self):
        scene = validate_scene({'size': [512, 384, 512], 'ops': [
            region('minecraft:stone', (0, 0, 0), (511, 383, 511))]})
        plan = prepare_plan(scene['ops'], MAX_COMMANDS)
        self.assertEqual(len(plan), 1)
        pieces = list(split_fill((0, 0, 0), (511, 383, 511)))
        volumes = [(b[0]-a[0]+1)*(b[1]-a[1]+1)*(b[2]-a[2]+1) for a, b in pieces]
        self.assertEqual(sum(volumes), 100_663_296)
        self.assertLessEqual(max(volumes), 4096)
        summary, commands = self.export_commands(scene)
        self.assertEqual(summary['commands'], len(pieces))
        self.assertIn('~383', commands)

    def test_pane_connections_across_tile_boundary_with_large_solid(self):
        scene = validate_scene({'size': [512, 384, 512], 'ops': [
            region('minecraft:stone', (0, 0, 0), (511, 382, 511)),
            region('minecraft:glass_pane', (15, 383, 15)),
            region('minecraft:stone', (16, 383, 15)),
        ]})
        pane = next(op for op in prepare_plan(scene['ops'], MAX_COMMANDS)
                    if op['block'].startswith('minecraft:glass_pane'))
        self.assertIn('east=true', pane['block'])
        self.assertIn('west=false', pane['block'])

    def test_preview_keeps_top_and_far_edge_above_old_120k_cap(self):
        blocks = scene_blocks({'size': [512, 1, 256], 'ops': [
            region('minecraft:stone', (0, 0, 0), (511, 0, 255))]})
        self.assertEqual(len(blocks), 131_072)
        self.assertIn((511, 0, 255), blocks)

    def test_rejects_outside_expanded_dimensions(self):
        for dims in ([513, 1, 1], [1, 385, 1], [1, 1, 513]):
            with self.subTest(dims=dims), self.assertRaises(ValueError):
                validate_scene({'size': dims, 'ops': [region('minecraft:stone', (0, 0, 0))]})
