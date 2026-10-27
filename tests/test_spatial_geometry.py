"""Asymmetric geometry and coordinate/direction regressions, no model calls."""
from copy import deepcopy
from array import array
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch
import queue
import sys

from core.block_rules import cells, prepare_plan, split_block
from core.entity_nbt import compound_fields, numeric_list
from core.entity_geometry import armor_stand_diagnostics
from core.live_scene import scene_blocks, _mesh, _parts
from core.scene_transform import transform_scene
from core.stair_rules import block_boxes
from core.video2pack import (MAX_COMMANDS, SCENE_SCHEMA, check_block, compile_datapack,
                             make_commands, make_entity_commands, make_undo_commands,
                             prepare_scene, validate_scene, run)
from core.video2pack import infer_scene
from core.generation_runtime import generation_worker

EVIDENCE = {'frames': [1], 'observation': 'Visible asymmetric construction', 'hint': None}


def op(block, point, end=None, **extra):
    return {'block': block, 'from': list(point), 'to': list(end or point), **extra}


def entity(position, *, kind='minecraft:armor_stand', **extra):
    return {'entity': kind, 'position': list(position), 'evidence': deepcopy(EVIDENCE), **extra}


def scene(ops=None, entities=None, **extra):
    return {'name': 'asymmetric', 'size': [12, 8, 10], 'base_y': 1,
            'ops': ops or [op('minecraft:stone', (0, 0, 0), (11, 0, 9))],
            'entities': entities or [], **extra}


def planned(source, diagnostics=None):
    normalized = prepare_scene(source)
    return prepare_plan(normalized['ops'], MAX_COMMANDS, diagnostics=diagnostics)


def by_cell(plan):
    return {point: item['block'] for item in plan for point in cells(item)}


class EntityGeometryTests(unittest.TestCase):
    def test_armor_stand_cell_center_and_feet_baseline(self):
        commands = make_entity_commands(scene(entities=[entity((5, 2, 4))]))
        self.assertIn('~5.5 ~1 ~4.5', commands[0])

    def test_row_and_different_heights_remain_aligned(self):
        commands = make_entity_commands(scene(entities=[entity((x, y, 4)) for x, y in ((1, 1), (3, 2), (5, 3))]))
        for command, expected in zip(commands, ('~1.5 ~0 ~4.5', '~3.5 ~1 ~4.5', '~5.5 ~2 ~4.5')):
            self.assertIn(expected, command)

    def test_exact_decimal_position_and_integer_exact_mode(self):
        commands = make_entity_commands(scene(entities=[entity((5.25, 2.5, 4.75)),
                                                       entity((5, 2, 4), position_mode='exact')]))
        self.assertIn('~5.25 ~1.5 ~4.75', commands[0])
        self.assertIn('~5 ~1 ~4', commands[1])

    def test_cell_mode_can_stand_on_half_slab(self):
        source = scene([op('minecraft:stone_slab[type=bottom]', (5, 0, 4))],
                       [entity((5, .5, 4), position_mode='cell')], base_y=0)
        normalized = prepare_scene(source)
        self.assertEqual(normalized['entities'][0]['position'], [5.5, .5, 4.5])
        self.assertEqual(armor_stand_diagnostics(normalized, planned(source)), [])

    def test_other_entity_positions_unchanged(self):
        for kind in ('minecraft:painting', 'minecraft:item_frame', 'minecraft:glow_item_frame'):
            with self.subTest(kind=kind):
                self.assertIn('~5 ~1 ~4 ', make_entity_commands(scene(entities=[entity((5, 2, 4), kind=kind)]))[0])

    def test_legacy_painting_facing_alias_maps_to_actual_26_3_field(self):
        for nbt in ({'Facing': 2, 'variant': 'minecraft:kebab'},
                    '{Facing:2b,variant:"minecraft:kebab"}'):
            normalized = prepare_scene(scene(entities=[entity((2, 2, 2), kind='minecraft:painting', nbt=nbt)]))
            ent = normalized['entities'][0]
            self.assertEqual(ent['position'], [2, 2, 2])
            values = compound_fields(ent['nbt']) if isinstance(ent['nbt'], str) else ent['nbt']
            self.assertNotIn('Facing', values)
            self.assertEqual(str(values['facing']).rstrip('b'), '2')
            self.assertIn('variant', values)

    def test_malformed_and_duplicate_placement_nbt_is_rejected(self):
        for nbt in ('{Rotation:[0f,0f],Rotation:[90f,0f]}', '{Tags:["unfinished]}'):
            with self.assertRaises(ValueError):
                validate_scene(scene(entities=[entity((1, 1, 1), nbt=nbt)]))

    def test_rotation_precedence_and_tags_match_dict_and_snbt(self):
        for nbt in ({'Rotation': [180, 10], 'Tags': ['original'], 'CustomName': 'A:B'},
                    '{Rotation:[180f,10f],Tags:["original"],CustomName:"A:B"}'):
            with self.subTest(nbt=nbt):
                command = make_entity_commands(scene(entities=[entity((1, 1, 1), rotation=[90, 0], nbt=nbt)]))[0]
                fields = compound_fields(command[command.index('{'):])
                self.assertEqual(numeric_list(fields['Rotation']), [90, 0])
                self.assertIn('original', fields['Tags'])
                self.assertIn('vidbuild_entity', fields['Tags'])
                self.assertIn('A:B', fields['CustomName'])
                self.assertEqual(command.count('Rotation'), 1)

    def test_nbt_only_rotation_rotates_and_is_not_duplicated(self):
        source = scene(entities=[entity((1, 1, 1), nbt='{Rotation:[90f,0f],Pose:{Head:[1f,2f,3f]}}')])
        changed = prepare_scene(source, rotation=90)
        self.assertEqual(changed['entities'][0]['rotation'], [180, 0])
        command = make_entity_commands(changed)[0]
        self.assertEqual(command.count('Rotation'), 1)
        self.assertIn('Pose', command)

    def test_support_and_body_collision_are_diagnosed_without_relocation(self):
        source = scene([op('minecraft:stone', (0, 0, 0), (11, 0, 9)),
                        op('minecraft:stone', (5, 1, 4), (5, 3, 4))],
                       [entity((5, 1, 4)), entity((7, 4, 4))])
        normalized = prepare_scene(source)
        before = deepcopy(normalized['entities'])
        messages = armor_stand_diagnostics(normalized, planned(source))
        self.assertTrue(any('intersects' in value for value in messages))
        self.assertTrue(any('no matching support' in value for value in messages))
        self.assertEqual(normalized['entities'], before)

    def test_supported_foot_position_is_not_shifted_vertically(self):
        source = scene(entities=[entity((5, 1, 4))])
        self.assertEqual(armor_stand_diagnostics(prepare_scene(source), planned(source)), [])

    def test_nonfinite_positions_and_conflicting_pos_are_rejected(self):
        for point in ((float('nan'), 1, 1), (1, float('inf'), 1)):
            with self.assertRaises(ValueError):
                validate_scene(scene(entities=[entity(point)]))
        for nbt in ({'Pos': [1, 2, 3]}, '{Pos:[1d,2d,3d]}'):
            with self.assertRaisesRegex(ValueError, 'conflicts'):
                validate_scene(scene(entities=[entity((1, 1, 1), nbt=nbt)]))


class TransformTests(unittest.TestCase):
    def test_single_model_request_keeps_raw_frame_then_compiles_canonical(self):
        source = self.asymmetric()
        for item in source['ops']:
            item.update(action='place', confidence='confirmed', replace=False, evidence=deepcopy(EVIDENCE))
        requests = []

        class Client:
            def __init__(self, **kwargs):
                self.responses = self

            def create(self, **kwargs):
                requests.append(kwargs)
                return SimpleNamespace(output_text=json.dumps(source), status='completed')

        with patch('core.video2pack.video_frames', return_value=[(1, b'jpeg')]), \
             patch.dict(sys.modules, {'openai': SimpleNamespace(OpenAI=Client)}):
            raw = infer_scene(Path('asymmetric.mp4'), 'test', 2, auth_mode='api', api_key='test')
        self.assertEqual(len(requests), 1)
        self.assertEqual(raw['coordinate_system'], 'facade')
        self.assertEqual(raw['ops'][0]['from'], [1, 2, 0])
        self.assertIn((1, 2, 9), scene_blocks(raw))

    def test_worker_publishes_exact_canonical_scene_used_by_export(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'scene.json'
            source.write_text(json.dumps(self.asymmetric()), encoding='utf-8')
            messages = queue.Queue()
            # The production worker is a fresh process. Restore its local
            # compiler wrapper after exercising the same entrypoint in-process.
            import core.video2pack as module
            original = module.compile_datapack
            try:
                generation_worker({'scene_path': str(source), 'out': str(Path(temp) / 'out.zip'),
                                   'rotation': 90, 'mirror': True}, messages)
            finally:
                module.compile_datapack = original
            received = []
            while not messages.empty():
                received.append(messages.get_nowait())
            self.assertFalse(any(kind == 'error' for kind, value in received), received)
            payload = next(value for kind, value in received if kind == 'result')
            expected = prepare_scene(self.asymmetric(), rotation=90, mirror=True)
            self.assertEqual(payload['_live_scene'], expected)
            self.assertEqual(scene_blocks(payload['_live_scene']), by_cell(planned(expected)))

    def test_known_omitted_directional_defaults_rotate_too(self):
        source = scene([op('minecraft:oak_door', (1, 1, 1)),
                        op('minecraft:oak_sign', (2, 1, 1)),
                        op('minecraft:rail', (3, 1, 1))])
        changed = prepare_scene(source, rotation=90, mirror=True)
        blocks = [item['block'] for item in changed['ops']]
        self.assertIn('facing=east', blocks[0])
        self.assertIn('hinge=right', blocks[0])
        # The official 26.3 default standing-sign rotation is 8, not 0.
        self.assertIn('rotation=12', blocks[1])
        self.assertIn('shape=east_west', blocks[2])

    def test_native_default_vertical_blocks_and_compact_legacy_roundtrip(self):
        source = prepare_scene(scene([op('minecraft:end_rod', (1, 1, 1)),
                                      op('minecraft:amethyst_cluster', (2, 1, 1)),
                                      op('minecraft:oak_door', (3, 1, 1)),
                                      op('minecraft:white_banner', (4, 1, 1))]))
        changed = prepare_scene(source, rotation=90, mirror=True)
        self.assertIn('facing=up', changed['ops'][0]['block'])
        self.assertIn('facing=up', changed['ops'][1]['block'])
        self.assertIn('rotation=8', source['ops'][3]['block'])
        self.assertIn('rotation=12', changed['ops'][3]['block'])
        self.assertEqual(transform_scene(transform_scene(source, mirror=True), mirror=True), source)

    def test_painting_2d_facing_and_current_block_pos_codec(self):
        for nbt in ({'facing': 2, 'block_pos': [1, 2, 3]},
                    '{facing:2b,block_pos:[I;1,2,3]}'):
            source = scene(entities=[entity((1, 2, 3), kind='minecraft:painting', nbt=nbt)])
            changed = prepare_scene(source, rotation=90)
            ent = changed['entities'][0]
            raw = ent['nbt']
            values = compound_fields(raw) if isinstance(raw, str) else raw
            self.assertEqual(str(values['facing']).rstrip('b'), '3')  # north -> east in 2D codec
            anchor = numeric_list(values['block_pos']) if isinstance(raw, str) else values['block_pos']
            self.assertEqual(anchor, [6, 2, 1])
            self.assertEqual(ent['position'], anchor)

    def test_hanging_fractional_anchors_restore_after_two_mirrors(self):
        for kind in ('minecraft:painting', 'minecraft:item_frame', 'minecraft:glow_item_frame'):
            source = prepare_scene(scene(entities=[entity((1.25, 2, 3.75), kind=kind)]))
            self.assertEqual(transform_scene(transform_scene(source, mirror=True), mirror=True), source)

    def asymmetric(self):
        return scene([
            op('minecraft:glass', (1, 2, 0)),
            op('minecraft:oak_door[facing=north,hinge=left,half=lower]', (8, 1, 0)),
            op('minecraft:bricks', (9, 6, 7)),
            op('minecraft:oak_stairs[facing=south,half=bottom,shape=inner_left]', (4, 1, 3)),
            op('minecraft:oak_log[axis=x]', (6, 1, 2)),
        ], [entity((2, 1, 2), rotation=[180, 0])], coordinate_system='facade')

    def test_default_facade_conversion_preserves_viewer_left_and_right(self):
        converted = prepare_scene(self.asymmetric())
        self.assertEqual(converted['ops'][0]['from'], [1, 2, 9])
        self.assertEqual(converted['ops'][1]['from'], [8, 1, 9])
        self.assertIn('facing=south', converted['ops'][1]['block'])
        self.assertIn('hinge=right', converted['ops'][1]['block'])
        self.assertEqual(converted['entities'][0]['position'], [2.5, 1, 7.5])
        self.assertEqual(converted['entities'][0]['rotation'], [0, 0])
        self.assertIn('shape=inner_right', converted['ops'][3]['block'])
        self.assertEqual(prepare_scene(converted), converted)

    def test_unmarked_legacy_blocks_are_not_mirrored(self):
        old = self.asymmetric()
        old.pop('coordinate_system')
        self.assertEqual(prepare_scene(old)['ops'][0]['from'], [1, 2, 0])

    def test_all_eight_transform_combinations_stay_in_bounds(self):
        source = self.asymmetric()
        for rotation in (0, 90, 180, 270):
            for mirror in (False, True):
                with self.subTest(rotation=rotation, mirror=mirror):
                    changed = prepare_scene(source, rotation=rotation, mirror=mirror)
                    validate_scene(changed)
                    self.assertEqual(changed['size'], [10, 8, 12] if rotation % 180 else [12, 8, 10])
                    self.assertEqual(len(changed['ops']), len(source['ops']))
                    for ent in changed['entities']:
                        self.assertTrue(all(0 <= v <= n for v, n in zip(ent['position'], changed['size'])))

    def test_double_mirror_and_four_rotations_restore_structure(self):
        source = prepare_scene(self.asymmetric())
        self.assertEqual(transform_scene(transform_scene(source, mirror=True), mirror=True), source)
        changed = source
        for _ in range(4):
            changed = transform_scene(changed, rotation=90)
        self.assertEqual(changed, source)

    def test_decimal_entity_and_yaw_compose_with_block_centers(self):
        source = prepare_scene(scene([op('minecraft:stone', (5, 2, 4))],
                                     [entity((5, 2, 4), rotation=[270, 0])]))
        for rotation in (0, 90, 180, 270):
            for mirror in (False, True):
                changed = prepare_scene(source, rotation=rotation, mirror=mirror)
                cell = changed['ops'][0]['from']
                self.assertEqual(changed['entities'][0]['position'], [cell[0] + .5, cell[1], cell[2] + .5])
        exact = prepare_scene(scene(entities=[entity((5.25, 2, 4.75))]), rotation=90, mirror=True)
        self.assertEqual(exact['entities'][0]['position'], [5.25, 2, 6.75])

    def test_state_semantics_for_axes_connections_rotation_rails_and_doors(self):
        source = scene([
            op('minecraft:oak_log[axis=x]', (1, 1, 1)),
            op('minecraft:oak_sign[rotation=0]', (2, 1, 1)),
            op('minecraft:glass_pane[north=true,east=false,south=false,west=true]', (3, 1, 1)),
            op('minecraft:rail[shape=ascending_north]', (4, 1, 1)),
            op('minecraft:rail[shape=north_east]', (5, 1, 1)),
            op('minecraft:oak_trapdoor[facing=east,half=top]', (6, 1, 1)),
            op('minecraft:oak_stairs[facing=east,half=top,shape=outer_left]', (7, 1, 1)),
        ])
        changed = prepare_scene(source, rotation=90, mirror=True)
        states = [split_block(item['block'])[1] for item in changed['ops']]
        self.assertEqual(states[0]['axis'], 'z')
        self.assertEqual(states[1]['rotation'], '4')
        self.assertEqual(states[2]['east'], 'true')
        self.assertEqual(states[2]['south'], 'true')
        self.assertEqual(states[3]['shape'], 'ascending_east')
        self.assertEqual(states[4]['shape'], 'north_east')
        self.assertEqual(states[5]['facing'], 'north')
        self.assertEqual(states[6]['shape'], 'outer_right')
        self.assertEqual(states[6]['half'], 'top')

    def test_hanging_entity_anchor_and_facing_transform_without_centering(self):
        for nbt in ({'Facing': 2, 'TileX': 1, 'TileY': 2, 'TileZ': 3, 'variant': 'minecraft:kebab'},
                    '{Facing:2b,TileX:1,TileY:2,TileZ:3,variant:"minecraft:kebab"}'):
            source = scene(entities=[entity((1, 2, 3), kind='minecraft:painting', nbt=nbt)])
            changed = prepare_scene(source, rotation=90)
            ent = changed['entities'][0]
            self.assertEqual(ent['position'], [6, 2, 1])
            raw = ent['nbt']
            values = compound_fields(raw) if isinstance(raw, str) else raw
            self.assertEqual(str(values['facing']).rstrip('b'), '3')
            self.assertEqual(int(values['TileX']), 6)
            self.assertEqual(int(values['TileZ']), 1)

    def test_export_preview_undo_and_saved_origin_use_same_geometry(self):
        source = self.asymmetric()
        normalized = prepare_scene(source, rotation=90, mirror=True)
        blocks = scene_blocks(normalized)
        expected = by_cell(planned(normalized))
        self.assertEqual(blocks, expected)
        self.assertEqual(scene_blocks(source), by_cell(planned(source)))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'asymmetric.zip'
            summary = compile_datapack(normalized, path)
            with zipfile.ZipFile(path) as pack:
                build = '\n'.join(pack.read(name).decode() for name in pack.namelist() if '/parts/part_' in name)
                undo = '\n'.join(pack.read(name).decode() for name in pack.namelist() if '/parts/undo_part_' in name)
                for command in make_commands(normalized) + make_entity_commands(normalized):
                    self.assertIn(command, build)
                for command in make_undo_commands(normalized):
                    self.assertIn(command, undo)
                self.assertIn('Pos[0]', pack.read('data/vidbuild/function/internal/build_at_origin.mcfunction').decode())
            self.assertEqual(summary['size'], normalized['size'])

    def test_cli_run_applies_transform_once(self):
        source = self.asymmetric()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'scene.json'
            path.write_text(json.dumps(source), encoding='utf-8')
            output = Path(temp) / 'build.zip'
            actual = run(scene_path=str(path), out=str(output), rotation=90, mirror=True)
            self.assertEqual(actual['size'], [10, 8, 12])


class StairTests(unittest.TestCase):
    def test_all_stair_shapes_transform_as_their_physical_quarter_cells(self):
        import itertools
        for facing, half, shape in itertools.product(('north', 'east', 'south', 'west'), ('top', 'bottom'),
                ('straight', 'inner_left', 'inner_right', 'outer_left', 'outer_right')):
            block = f'minecraft:oak_stairs[facing={facing},half={half},shape={shape}]'
            boxes = list(block_boxes(block))
            for rotation, mirror in itertools.product((0, 90, 180, 270), (False, True)):
                points = list(itertools.product((.25, .75), repeat=3))
                source = scene([op(block, (1, 1, 1))], [entity(tuple(v+1 for v in p), position_mode='exact') for p in points])
                converted = prepare_scene(source, rotation=rotation, mirror=mirror)
                converted_boxes = list(block_boxes(converted['ops'][0]['block']))
                origin = converted['ops'][0]['from']
                for original, target in zip(points, converted['entities']):
                    local = [v-o for v,o in zip(target['position'], origin)]
                    contains = lambda p, boxes: any(all(b[i]<p[i]<b[i+3] for i in range(3)) for b in boxes)
                    self.assertEqual(contains(original, boxes), contains(local, converted_boxes),
                                     (facing, half, shape, rotation, mirror, original))

    def test_four_facings_and_both_halves_are_explicit(self):
        for facing in ('north', 'south', 'east', 'west'):
            for half in ('top', 'bottom'):
                with self.subTest(facing=facing, half=half):
                    block = planned(scene([op(f'minecraft:oak_stairs[facing={facing},half={half}]', (1, 1, 1))]))[0]['block']
                    self.assertIn(f'facing={facing}', block)
                    self.assertIn(f'half={half}', block)
                    self.assertIn('shape=straight', block)

    def test_invalid_stair_properties_are_rejected(self):
        for state in ('facing=up', 'half=upper', 'shape=curved', 'waterlogged=maybe', 'axis=x'):
            with self.subTest(state=state), self.assertRaisesRegex(ValueError, 'Invalid stair state'):
                check_block(f'minecraft:oak_stairs[{state}]')

    def test_missing_orientation_keeps_candidate_as_unbuilt_uncertainty(self):
        messages = []
        source = scene([op('minecraft:stone', (0, 0, 0)), op('minecraft:oak_stairs', (1, 1, 1))])
        self.assertEqual(len(planned(source, messages)), 1)
        self.assertTrue(any('unbuilt uncertainty' in message for message in messages))
        self.assertNotIn((1, 1, 1), scene_blocks(source))
        self.assertEqual(source['ops'][1]['block'], 'minecraft:oak_stairs')

    def test_walk_flight_geometrically_corrects_all_four_ascent_directions(self):
        for facing, delta in {'north': (0, -1), 'south': (0, 1), 'east': (1, 0), 'west': (-1, 0)}.items():
            with self.subTest(facing=facing):
                source = scene([op('minecraft:oak_stairs[facing=north,half=bottom]',
                                   (5 + delta[0] * i, i + 1, 5 + delta[1] * i), stair_use='walk') for i in range(3)])
                for item in planned(source):
                    self.assertEqual(split_block(item['block'])[1]['facing'], facing)

    def test_missing_facing_is_resolved_only_with_unique_annotated_flight(self):
        source = scene([op('minecraft:oak_stairs[half=bottom]', (i + 1, i + 1, 5), stair_use='walk') for i in range(3)])
        self.assertEqual(len(planned(source)), 3)
        self.assertTrue(all('facing=east' in item['block'] for item in planned(source)))
        source['ops'][1]['stair_use'] = 'decorative'
        self.assertNotIn((2, 2, 5), by_cell(planned(source)))

    def test_roof_stairs_are_not_corrected_using_walk_rules(self):
        source = scene([op('minecraft:oak_stairs[facing=west,half=top,shape=straight]',
                           (i + 1, i + 1, 5), stair_use='decorative') for i in range(3)])
        self.assertTrue(all('facing=west,half=top' in item['block'] for item in planned(source)))

    def test_inner_outer_left_right_and_both_halves(self):
        for half in ('bottom', 'top'):
            for shape, neighbor_point, facing in (
                    ('outer_left', (3, 1, 2), 'west'), ('outer_right', (3, 1, 2), 'east'),
                    ('inner_left', (3, 1, 4), 'west'), ('inner_right', (3, 1, 4), 'east')):
                with self.subTest(half=half, shape=shape):
                    source = scene([op(f'minecraft:oak_stairs[facing=north,half={half}]', (3, 1, 3)),
                                    op(f'minecraft:oak_stairs[facing={facing},half={half}]', neighbor_point)])
                    block = by_cell(planned(source))[(3, 1, 3)]
                    self.assertIn('shape=' + shape, block)

    def test_corner_exclusion_and_different_half(self):
        source = scene([op('minecraft:oak_stairs[facing=north,half=bottom]', (3, 1, 3)),
                        op('minecraft:oak_stairs[facing=west,half=top]', (3, 1, 2))])
        self.assertIn('shape=straight', by_cell(planned(source))[(3, 1, 3)])
        source['ops'][1]['block'] = 'minecraft:oak_stairs[facing=west,half=bottom]'
        source['ops'].append(op('minecraft:oak_stairs[facing=north,half=bottom]', (4, 1, 3)))
        self.assertIn('shape=straight', by_cell(planned(source))[(3, 1, 3)])

    def test_explicit_decorative_shape_is_preserved_under_strict(self):
        source = scene([op('minecraft:oak_stairs[facing=north,half=top,shape=inner_left]', (3, 1, 3), stair_use='decorative')])
        messages = []
        self.assertIn('shape=inner_left', planned(source, messages)[0]['block'])
        self.assertTrue(messages)
        self.assertIn('shape=inner_left', make_commands(source)[0])
        self.assertTrue(make_commands(source)[0].endswith(' strict'))

    def test_preview_stair_volumes_and_high_half_match_direction(self):
        for facing in ('north', 'east', 'south', 'west'):
            for half in ('bottom', 'top'):
                for shape, volume in (('straight', .75), ('outer_left', .625), ('outer_right', .625),
                                      ('inner_left', .875), ('inner_right', .875)):
                    with self.subTest(facing=facing, half=half, shape=shape):
                        boxes = list(block_boxes(f'minecraft:oak_stairs[facing={facing},half={half},shape={shape}]'))
                        self.assertAlmostEqual(sum((d-a)*(e-b)*(f-c) for a,b,c,d,e,f in boxes), volume)
                        self.assertTrue(all(b == (0 if half == 'top' else .5) for _, b, _, _, _, _ in boxes[1:]))

    def test_mesh_applies_half_cell_bounds_and_does_not_cull_against_partial_neighbor(self):
        vertices, _, center, *_ = _mesh({(0, 0, 0): 'minecraft:oak_stairs[facing=east,half=bottom,shape=straight]',
                                        (1, 0, 0): 'minecraft:stone_slab[type=bottom]'})
        floats = array('f')
        floats.frombytes(vertices)
        points = [(floats[i]+center[0], floats[i+1]+center[1], floats[i+2]+center[2]) for i in range(0,len(floats),10)]
        self.assertTrue(any(abs(x-.5) < 1e-7 for x,y,z in points))
        self.assertTrue(any(abs(y-.5) < 1e-7 for x,y,z in points))
        self.assertTrue(any(abs(x-1) < 1e-7 and y > .5 for x,y,z in points))

    def test_preview_and_export_share_resolved_stair_states(self):
        source = scene([op('minecraft:oak_stairs[facing=north,half=bottom]', (3, 1, 3)),
                        op('minecraft:oak_stairs[facing=west,half=bottom]', (3, 1, 2))], coordinate_system='facade')
        self.assertEqual(scene_blocks(source), by_cell(planned(source)))
        self.assertTrue(any('shape=outer_right' in block for block in scene_blocks(source).values()))


if __name__ == '__main__':
    unittest.main()
