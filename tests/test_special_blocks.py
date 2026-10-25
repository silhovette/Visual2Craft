"""Special-block semantics and executable command planning, without model calls."""
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
import zipfile

from block_rules import classify_block, cells, prepare_plan, split_block
from video2pack import (MAX_COMMANDS, PALETTE_SET, SCENE_SCHEMA, check_block,
                        compile_datapack, infer_scene, make_commands, make_entity_commands,
                        make_undo_commands, run, validate_scene)


def op(block, point=(0, 0, 0), end=None, **metadata):
    return {'block': block, 'from': list(point), 'to': list(end or point), **metadata}


def scene(*ops):
    return {'name':'special blocks', 'size':[12, 8, 12], 'ops':list(ops)}


class SpecialBlockTests(unittest.TestCase):
    def test_placeable_entities_are_summoned_and_undo_tagged(self):
        source = {
            'name': 'entity objects', 'size': [12, 8, 12],
            'ops': [op('minecraft:stone')],
            'entities': [
                {'entity': 'minecraft:armor_stand', 'position': [1, 1, 1],
                 'rotation': [90, 0], 'nbt': {'Invisible': False},
                 'evidence': {'frames': [4], 'observation': 'Armor stand is shown', 'hint': None}},
                {'entity': 'minecraft:painting', 'position': [2, 2, 2],
                 'nbt': {'variant': 'minecraft:kebab', 'Facing': 2},
                 'evidence': {'frames': [4], 'observation': 'Painting is shown', 'hint': None}},
                {'entity': 'minecraft:item_frame', 'position': [3, 2, 2],
                 'nbt': {'Facing': 4},
                 'evidence': {'frames': [4], 'observation': 'Item frame is shown', 'hint': None}},
            ],
        }
        commands = make_entity_commands(validate_scene(source))
        self.assertIn('summon minecraft:armor_stand', commands[0])
        self.assertIn('summon minecraft:painting', commands[1])
        self.assertIn('summon minecraft:item_frame', commands[2])
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'entities.zip'
            compile_datapack(source, output)
            with zipfile.ZipFile(output) as pack:
                build = pack.read('data/vidbuild/function/parts/part_000.mcfunction').decode()
                undo = pack.read('data/vidbuild/function/parts/undo_part_000.mcfunction').decode()
                self.assertIn('summon minecraft:armor_stand', build)
                self.assertIn('summon minecraft:painting', build)
                self.assertIn('summon minecraft:item_frame', build)
                self.assertIn('kill @e[tag=vidbuild_entity', undo)

    def test_classification_and_independent_commands(self):
        blocks = [('minecraft:air', 'air'), ('minecraft:glass', 'glass'),
                  ('minecraft:glass_pane', 'glass_pane'), ('minecraft:water[level=0]', 'water'),
                  ('minecraft:barrier', 'barrier'), ('minecraft:structure_void', 'structure_void')]
        for block, kind in blocks:
            with self.subTest(block=block):
                self.assertEqual(classify_block(check_block(block)), kind)
                commands = make_commands(scene(op(block)))
                self.assertTrue(commands[0].startswith('setblock ~0 ~0 ~0 ' + block.split('[')[0]))
                self.assertIn(' strict', commands[0])

    def test_light_levels_and_waterlogged_preserved(self):
        for level in (0, 8, 15):
            for wet in ('false', 'true'):
                block = f'minecraft:light[level={level},waterlogged={wet}]'
                self.assertEqual(check_block(block), block)
                self.assertEqual(make_commands(scene(op(block))), [f'setblock ~0 ~0 ~0 {block} strict'])

    def test_states_are_syntax_checked_without_a_stale_state_whitelist(self):
        invalid = ['minecraft:light[level=8,level=15]',
                   'minecraft:stone[level=8,foo]',
                   'minecraft:stone[level=8,level=9]']
        for block in invalid:
            with self.subTest(block=block), self.assertRaises(ValueError):
                check_block(block)
        check_block('minecraft:light[level=16]')
        check_block('minecraft:water[level=16]')
        check_block('minecraft:cave_vines[berries=true]')
        self.assertEqual(check_block('minecraft:chain[axis=y]'), 'minecraft:iron_chain[axis=y]')
        check_block('minecraft:stone[level=8]')
        check_block('minecraft:glass_pane[north=true,east=false,waterlogged=true]')

    def test_lava_like_materials_are_replaced_with_luminous_block(self):
        self.assertEqual(check_block('minecraft:lava[level=4]'), 'minecraft:ochre_froglight')
        self.assertEqual(check_block('minecraft:magma_block'), 'minecraft:ochre_froglight')
        self.assertEqual(check_block('minecraft:lava_cauldron[level=3]'), 'minecraft:ochre_froglight')

    def test_base_y_maps_below_and_above_player_baseline(self):
        source = {'name': 'base y', 'size': [4, 6, 4], 'base_y': 2,
                  'ops': [op('minecraft:stone', (0, 1, 0), (0, 3, 0))]}
        self.assertEqual(make_commands(source), [
            'fill ~0 ~-1 ~0 ~0 ~1 ~0 minecraft:stone strict'])

    def test_lectern_states_are_supported(self):
        block = 'minecraft:lectern[facing=west,has_book=true,powered=false]'
        self.assertEqual(check_block(block), block)

    def test_common_vanilla_state_families_are_supported(self):
        for block in (
                'minecraft:oak_fence_gate[facing=north,in_wall=false,open=true,powered=false]',
                'minecraft:oak_button[face=wall,facing=west,powered=false]',
                'minecraft:oak_sign[rotation=7,waterlogged=false]',
                'minecraft:chest[facing=south,type=single,waterlogged=false]',
                'minecraft:furnace[facing=east,lit=false]',
                'minecraft:campfire[facing=north,lit=true,signal_fire=false,waterlogged=false]',
                'minecraft:rail[shape=ascending_east]',
                'minecraft:white_candle[candles=2,lit=true,waterlogged=false]'):
            with self.subTest(block=block):
                self.assertEqual(check_block(block), block)

    def test_all_stained_glass_and_panes_are_supported(self):
        colors = ('white','orange','magenta','light_blue','yellow','lime','pink','gray',
                  'light_gray','cyan','purple','blue','brown','green','red','black')
        for color in colors:
            check_block(f'minecraft:{color}_stained_glass')
            check_block(f'minecraft:{color}_stained_glass_pane[west=true,waterlogged=false]')

    def test_preserve_and_unknown_mask_even_broad_overlapping_fills(self):
        for action in ('preserve', 'unknown'):
            source = scene(op('minecraft:stone', (0,0,0), (4,0,0)),
                           op('minecraft:structure_void' if action == 'preserve' else None,
                              (2,0,0), action=action))
            plan = prepare_plan(validate_scene(source)['ops'], MAX_COMMANDS)
            self.assertEqual({p for item in plan for p in cells(item)},
                             {(0,0,0),(1,0,0),(3,0,0),(4,0,0)})
            self.assertNotIn('structure_void', '\n'.join(make_commands(source)))
            self.assertNotIn('~2 ~0 ~0', '\n'.join(make_undo_commands(source)))
        self.assertIn('minecraft:structure_void', make_commands(scene(op('minecraft:structure_void')))[0])

    def test_malformed_block_id_rejected_not_substituted_with_air(self):
        with self.assertRaisesRegex(ValueError, 'Malformed block identifier'):
            make_commands(scene(op('minecraft:bad id')))
        with self.assertRaisesRegex(ValueError, 'No confirmed placements'):
            with tempfile.TemporaryDirectory() as temp:
                compile_datapack(scene(op(None, action='unknown')), Path(temp)/'bad.zip')
        commands = make_commands(scene(op('minecraft:stone', (1,0,0)),
                                       op('minecraft:unrecognized', action='unknown')))
        self.assertNotIn('minecraft:air', '\n'.join(commands))

    def test_air_requires_clear_intent_for_new_scenes(self):
        with self.assertRaisesRegex(ValueError, 'explicit clear'):
            validate_scene(scene(op('minecraft:air', action='place')))
        with self.assertRaises(ValueError):
            validate_scene(scene(op('minecraft:glass', action='clear')))
        self.assertIn('minecraft:air', make_commands(scene(op('minecraft:air', action='clear')))[0])

    def test_overlapping_operations_use_later_operation(self):
        for special in ('minecraft:light[level=8]', 'minecraft:barrier', 'minecraft:glass',
                        'minecraft:structure_void', 'minecraft:water[level=0]'):
            with self.subTest(block=special):
                source = scene(op(special), op('minecraft:stone'))
                self.assertEqual(make_commands(source), ['setblock ~0 ~0 ~0 minecraft:stone strict'])
                self.assertNotIn(special, '\n'.join(make_undo_commands(source)))

    def test_final_plan_keeps_adjacent_special_states_distinct(self):
        source = scene(op('minecraft:light[level=0]', (0,0,0), (1,0,0)),
                       op('minecraft:light[level=8]', (2,0,0), (3,0,0)),
                       op('minecraft:light[level=15,waterlogged=true]', (4,0,0), (5,0,0)),
                       op('minecraft:glass', (6,0,0)), op('minecraft:barrier', (7,0,0)))
        commands = make_commands(source)
        for state in ('level=0', 'level=8', 'level=15,waterlogged=true'):
            self.assertEqual(sum(state in command for command in commands), 1)
        self.assertEqual(len(commands), 5)

    def test_fill_keeps_water_levels_and_pane_connection_states_separate(self):
        blocks = ['minecraft:water[level=0]', 'minecraft:water[level=1]',
                  'minecraft:glass_pane[north=true,east=false,south=false,west=false,waterlogged=true]',
                  'minecraft:glass_pane[north=false,east=true,south=false,west=false,waterlogged=false]']
        source = scene(*(op(block, (i*2,1,1), (i*2+1,1,1)) for i, block in enumerate(blocks)))
        commands = make_commands(source)
        self.assertEqual(len(commands), 4)
        for block in blocks:
            self.assertEqual(sum(command.startswith('fill ') and command.endswith(block+' strict')
                                 for command in commands), 1)

    def test_pane_geometry_resolves_connections_and_respects_explicit_states(self):
        source = scene(op('minecraft:glass_pane', (1,1,1)),
                       op('minecraft:glass_pane[waterlogged=false]', (2,1,1)),
                       op('minecraft:stone', (0,1,1)),
                       op('minecraft:glass_pane[north=true,south=false,east=false,west=false]', (3,1,1)))
        plan = prepare_plan(validate_scene(source)['ops'], MAX_COMMANDS)
        by_point = {p: item['block'] for item in plan for p in cells(item)}
        states = split_block(by_point[(1,1,1)])[1]
        self.assertEqual(states, {'north':'false','south':'false','east':'true','west':'true'})
        self.assertIn('east=true', by_point[(2,1,1)])
        self.assertIn('north=true,south=false,east=false,west=false', by_point[(3,1,1)])

    def test_water_container_before_fluid_and_fluid_first_undo(self):
        source = scene(op('minecraft:water[level=0]', (1,1,1)),
                       op('minecraft:stone', (0,0,0), (2,0,2)),
                       op('minecraft:glass', (0,1,0), (0,1,2)),
                       op('minecraft:glass', (2,1,0), (2,1,2)),
                       op('minecraft:glass', (1,1,0)), op('minecraft:glass', (1,1,2)))
        self.assertIn('minecraft:water[level=0]', make_commands(source)[-1])
        self.assertIn('minecraft:water', make_undo_commands(source)[0])
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'water.zip'
            compile_datapack(source, output)
            with zipfile.ZipFile(output) as pack:
                self.assertIsNone(pack.testzip())
                self.assertNotIn('data/vidbuild/function/internal/check_water.mcfunction', pack.namelist())

    def test_water_accepts_any_occupied_planned_boundary_shape(self):
        source = scene(op('minecraft:water[level=0]', (1,1,1)),
                       op('minecraft:stone', (0,0,0), (2,0,2)),
                       op('minecraft:glass', (0,1,0), (0,1,2)),
                       op('minecraft:glass_pane', (2,1,0), (2,1,2)),
                       op('minecraft:glass', (1,1,0)), op('minecraft:glass', (1,1,2)))
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'pane_water.zip'
            compile_datapack(source, output)
            self.assertTrue(output.is_file())

    def test_open_water_builds_without_preflight_or_fluid_tags(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'water.zip'
            compile_datapack(scene(op('minecraft:water[level=0]')), out)
            with zipfile.ZipFile(out) as pack:
                root = 'data/vidbuild/function/'
                guard = pack.read(root+'internal/build_at_origin.mcfunction').decode()
                commit = pack.read(root+'internal/commit_build.mcfunction').decode()
                self.assertNotIn('water_check', guard)
                self.assertIn('data modify storage vidbuild:history last', guard)
                self.assertIn('function vidbuild:parts/all', guard)
                self.assertIn('last set value', commit)
                self.assertNotIn(root+'internal/check_water.mcfunction', pack.namelist())
                self.assertNotIn('data/vidbuild/tags/block/fluid_seals.json', pack.namelist())

    def test_planned_air_next_to_water_does_not_abort_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'open_water.zip'
            compile_datapack(scene(op('minecraft:water[level=0]', (1,1,1)),
                                   op('minecraft:air', (2,1,1))), out)
            self.assertEqual(list(Path(temp).iterdir()), [out])

    def test_special_zip_undo_uses_saved_origin_and_clears_history(self):
        source = scene(op('minecraft:light[level=15,waterlogged=true]', (1,1,1)),
                       op('minecraft:barrier', (4,1,1)), op('minecraft:structure_void', (6,1,1)))
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'special.zip'
            compile_datapack(source, out, offset=(7,2,9))
            self.assertEqual(list(Path(temp).iterdir()), [out])
            with zipfile.ZipFile(out) as pack:
                root = 'data/vidbuild/function/'
                build = pack.read(root+'parts/part_000.mcfunction').decode()
                undo = pack.read(root+'parts/undo_part_000.mcfunction').decode()
                self.assertIn('minecraft:light[level=15,waterlogged=true] strict', build)
                for block in ('light', 'barrier', 'structure_void'):
                    self.assertIn('minecraft:'+block, undo)
                self.assertIn('$(dimension) positioned $(x) $(y) $(z)', pack.read(root+'internal/undo_from_saved_origin.mcfunction').decode())
                self.assertIn('data remove storage vidbuild:history last', pack.read(root+'internal/commit_undo.mcfunction').decode())
                self.assertIn('~7 ~2 ~9', pack.read(root+'internal/start.mcfunction').decode())
                self.assertEqual(json.loads(pack.read('pack.mcmeta'))['pack']['min_format'], [121,0])
                names=set(pack.namelist())
                for name in names:
                    if name.endswith('.mcfunction'):
                        for ref in re.findall(r'\bfunction (vidbuild:[a-z0-9_/]+)', pack.read(name).decode()):
                            self.assertIn('data/'+ref.replace(':','/function/')+'.mcfunction', names)

    def test_schema_models_uncertainty_and_evidence(self):
        schema = SCENE_SCHEMA['properties']['ops']['items']
        branches = {branch['properties']['action']['enum'][0]: branch for branch in schema['anyOf']}
        self.assertEqual(set(branches), {'place', 'clear', 'preserve', 'unknown'})
        for branch in branches.values():
            self.assertEqual(set(branch['required']), set(branch['properties']))
        self.assertEqual(branches['place']['properties']['block']['type'], 'string')
        self.assertEqual(branches['clear']['properties']['block']['enum'], ['minecraft:air'])
        self.assertEqual(branches['unknown']['properties']['block']['type'], 'null')
        self.assertEqual(branches['unknown']['properties']['confidence']['enum'], ['uncertain'])

    def test_null_placement_is_unknown_and_never_clears_world(self):
        for action in ('place', 'clear'):
            for confidence in ('confirmed', 'uncertain'):
                with self.subTest(action=action, confidence=confidence):
                    source = scene(op('minecraft:stone', (0,0,0), (2,0,0)),
                                   op(None, (1,0,0), action=action, confidence=confidence))
                    checked = validate_scene(source)
                    self.assertEqual(checked['ops'][1]['action'], 'unknown')
                    self.assertEqual(checked['ops'][1]['confidence'], 'uncertain')
                    self.assertEqual(validate_scene(checked), checked)
                    plan = prepare_plan(checked['ops'], MAX_COMMANDS)
                    self.assertEqual({point for item in plan for point in cells(item)}, {(0,0,0),(2,0,0)})
                    self.assertNotIn('minecraft:air', '\n'.join(make_commands(source)))
                    self.assertNotIn('~1 ~0 ~0', '\n'.join(make_undo_commands(source)))
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'none.zip'
            with self.assertRaisesRegex(ValueError, 'No confirmed placements'):
                compile_datapack(scene(op(None, action='place', confidence='confirmed')), output)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_malformed_block_reports_operation_and_type(self):
        with self.assertRaisesRegex(ValueError, r'ops\[0\].block is missing'):
            validate_scene(scene({'from':[0,0,0], 'to':[0,0,0]}))
        for value in (42, {'id':'minecraft:stone'}, ['minecraft:stone']):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, r'ops\[0\].block'):
                validate_scene(scene(op(value)))

    def test_null_model_placement_compiles_only_confirmed_regions_to_one_zip(self):
        payload = scene(op('minecraft:stone', (0,0,0), (2,0,0)),
                        op(None, (1,0,0), action='place', confidence='confirmed'))
        for item in payload['ops']:
            item.update(action='place', confidence='confirmed', replace=False,
                        evidence={'frames':[1], 'observation':'Test model observation', 'hint':None})
        class Stream:
            def __enter__(self): return iter([NS(type='response.output_text.delta', delta=json.dumps(payload)),
                                             NS(type='response.completed', response=NS(output=[]))])
            def __exit__(self,*args): pass
        class Client:
            def __init__(self,**kwargs): self.responses=self
            def create(self,**kwargs): return Stream()
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'result.zip'
            with patch('video2pack.video_frames', return_value=[(1,b'jpeg')]), \
                 patch.dict(sys.modules, {'openai':NS(OpenAI=Client)}):
                summary = run(video='test.mp4', out=str(output), access_token='test')
            self.assertEqual(summary['skipped_regions'], 1)
            self.assertEqual(summary['commands'], 2)
            self.assertEqual(list(Path(temp).iterdir()), [output])
            with zipfile.ZipFile(output) as pack:
                self.assertIsNone(pack.testzip())
                build = pack.read('data/vidbuild/function/parts/part_000.mcfunction').decode()
                self.assertNotIn('~1 ~0 ~0', build)
                self.assertNotIn('minecraft:air', build)

    def test_uncertain_proposed_light_is_not_placed_or_cleared(self):
        source = scene(op('minecraft:stone', (0,0,0), (2,0,0)),
                       op('minecraft:light[level=15]', (1,0,0), confidence='uncertain'))
        plan = prepare_plan(validate_scene(source)['ops'], MAX_COMMANDS)
        self.assertNotIn((1,0,0), {p for item in plan for p in cells(item)})
        text = '\n'.join(make_commands(source) + make_undo_commands(source))
        self.assertNotIn('minecraft:light', text)

    def test_cuboid_exclusions_and_overlaps_match_final_voxel_plan(self):
        # Compare region subtraction against a direct reference for 3D overlaps.
        source = scene(op('minecraft:stone', (0,0,0), (4,4,4)),
                       op('minecraft:glass', (2,1,1), (5,3,3)),
                       op(None, (1,2,0), (3,2,4), action='preserve'))
        expected = {}
        for item in source['ops'][:2]:
            for point in cells(item):
                expected[point] = item['block']
        for point in cells(source['ops'][2]):
            expected.pop(point, None)
        plan = prepare_plan(validate_scene(source)['ops'], MAX_COMMANDS)
        actual = {}
        for item in plan:
            for point in cells(item):
                self.assertNotIn(point, actual)
                actual[point] = item['block']
        self.assertEqual(actual, expected)

    def test_special_example_produces_only_zip(self):
        path = Path(__file__).resolve().parents[1]/'examples'/'special_blocks.json'
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'special.zip'
            run(scene_path=str(path), out=str(output))
            self.assertEqual(list(Path(temp).iterdir()), [output])
            with zipfile.ZipFile(output) as pack:
                text = pack.read('data/vidbuild/function/parts/part_000.mcfunction').decode()
                self.assertIn('waterlogged=true', text)
                self.assertIn('minecraft:barrier', text)
                self.assertIn('minecraft:structure_void', text)
                self.assertIn('minecraft:water[level=0]', text)

    def test_model_hints_and_frame_provenance(self):
        payload = scene(op('minecraft:light[level=8]', action='place', confidence='confirmed', replace=False,
                           evidence={'frames':[], 'observation':'User instruction only; no direct video evidence',
                                     'hint':'Place light level 8'}))
        seen = {}
        class Stream:
            def __enter__(self): return iter([NS(type='response.output_text.delta', delta=json.dumps(payload)),
                                             NS(type='response.completed', response=NS(output=[]))])
            def __exit__(self,*args): pass
        class Client:
            def __init__(self,**params): self.responses=self
            def create(self,**request): seen.update(request); return Stream()
        with patch('video2pack.video_frames',return_value=[(45,b'jpeg')]), \
             patch.dict(sys.modules,{'openai':NS(OpenAI=Client)}):
            result = infer_scene(Path('mock.mp4'),'m',2,access_token='test',building_hints='Place light level 8')
            self.assertIn('level=8', result['ops'][0]['block'])
            prompt = '\n'.join(c.get('text','') for c in seen['input'][0]['content'])
            for text in ('Brightness alone is NOT evidence', 'waterlogged',
                         'USER BUILDING HINTS', 'TRANSPARENT MATERIAL VS INVISIBLE BARRIER'):
                self.assertIn(text, prompt)
            without_hint = infer_scene(Path('mock.mp4'),'m',2,access_token='test')
            self.assertEqual(without_hint['ops'][0]['action'], 'unknown')
            self.assertIsNone(without_hint['ops'][0]['block'])
            payload['ops'][0]['evidence']['frames'] = [999]
            sanitized = infer_scene(Path('mock.mp4'),'m',2,access_token='test',building_hints='Place light level 8')
            self.assertEqual(sanitized['ops'][0]['evidence']['frames'], [])
