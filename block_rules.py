"""Java block semantics and small, deterministic scene-planning helpers.

No vision model is run here. Unknown/preserved space is an exclusion mask, not air.
"""
from itertools import product
from pathlib import Path

COLORS = ('white', 'orange', 'magenta', 'light_blue', 'yellow', 'lime', 'pink',
          'gray', 'light_gray', 'cyan', 'purple', 'blue', 'brown', 'green', 'red', 'black')
SPECIAL_PALETTE = ['light', 'barrier', 'structure_void'] + [
    f'{color}_stained_glass{suffix}' for color in COLORS for suffix in ('', '_pane')]
BOOL = {'true', 'false'}
HORIZONTAL = {'north', 'south', 'east', 'west'}
SIX_WAY = HORIZONTAL | {'up', 'down'}
DIRECTIONS = {'north': (0, 0, -1), 'south': (0, 0, 1),
              'east': (1, 0, 0), 'west': (-1, 0, 0)}

try:
    BLOCK_KNOWLEDGE = Path(__file__).with_name("02_BLOCK_KNOWLEDGE.txt").read_text(
        encoding="utf-8").strip()
except OSError as exc:  # pragma: no cover - packaging failure, not model logic
    raise RuntimeError("Missing prompt asset: 02_BLOCK_KNOWLEDGE.txt") from exc


def split_block(block):
    name = block.split('[', 1)[0].removeprefix('minecraft:')
    states = dict(pair.split('=') for pair in block.split('[', 1)[1][:-1].split(',')) if '[' in block else {}
    return name, states


def is_pane(name):
    return name == 'glass_pane' or name.endswith('_stained_glass_pane')


def state_rules(name):
    if name == 'light':
        return {'level': {str(i) for i in range(16)}, 'waterlogged': BOOL}
    if name == 'water':
        return {'level': {str(i) for i in range(16)}}
    if name == 'barrier':
        return {'waterlogged': BOOL}
    if is_pane(name) or name.endswith('_fence') or name == 'iron_bars':
        return {**{key: BOOL for key in HORIZONTAL}, 'waterlogged': BOOL}
    if name.endswith('_fence_gate'):
        return {'facing': HORIZONTAL, 'in_wall': BOOL, 'open': BOOL, 'powered': BOOL}
    if name.endswith('_button'):
        return {'face': {'floor', 'wall', 'ceiling'}, 'facing': HORIZONTAL, 'powered': BOOL}
    if name.endswith('_pressure_plate'):
        if name in {'light_weighted_pressure_plate', 'heavy_weighted_pressure_plate'}:
            return {'power': {str(i) for i in range(16)}}
        return {'powered': BOOL}
    if name.endswith('_stairs'):
        return {'facing': HORIZONTAL, 'half': {'top', 'bottom'}, 'waterlogged': BOOL,
                'shape': {'straight', 'inner_left', 'inner_right', 'outer_left', 'outer_right'}}
    if name.endswith('_trapdoor'):
        return {'facing': HORIZONTAL, 'half': {'top', 'bottom'}, 'open': BOOL,
                'powered': BOOL, 'waterlogged': BOOL}
    if name.endswith('_door'):
        return {'facing': HORIZONTAL, 'half': {'upper', 'lower'}, 'open': BOOL,
                'powered': BOOL, 'hinge': {'left', 'right'}}
    if name.endswith('_slab'):
        return {'type': {'top', 'bottom', 'double'}, 'waterlogged': BOOL}
    if name.endswith('_wall_hanging_sign'):
        return {'facing': HORIZONTAL, 'attached': BOOL, 'waterlogged': BOOL}
    if name.endswith('_hanging_sign'):
        return {'rotation': {str(i) for i in range(16)}, 'attached': BOOL, 'waterlogged': BOOL}
    if name.endswith('_wall_sign'):
        return {'facing': HORIZONTAL, 'waterlogged': BOOL}
    if name.endswith('_sign'):
        return {'rotation': {str(i) for i in range(16)}, 'waterlogged': BOOL}
    if name in {'chest', 'trapped_chest', 'copper_chest'}:
        return {'facing': HORIZONTAL, 'type': {'single', 'left', 'right'}, 'waterlogged': BOOL}
    if name in {'furnace', 'smoker', 'blast_furnace'}:
        return {'facing': HORIZONTAL, 'lit': BOOL}
    if name in {'campfire', 'soul_campfire'}:
        return {'facing': HORIZONTAL, 'lit': BOOL, 'signal_fire': BOOL, 'waterlogged': BOOL}
    if name == 'hopper':
        return {'facing': SIX_WAY, 'enabled': BOOL}
    if name in {'dispenser', 'dropper'}:
        return {'facing': SIX_WAY, 'triggered': BOOL}
    if name == 'observer':
        return {'facing': SIX_WAY, 'powered': BOOL}
    if name in {'repeater'}:
        return {'facing': HORIZONTAL, 'delay': {'1', '2', '3', '4'}, 'locked': BOOL, 'powered': BOOL}
    if name == 'comparator':
        return {'facing': HORIZONTAL, 'mode': {'compare', 'subtract'}, 'powered': BOOL}
    if name in {'rail', 'golden_rail', 'detector_rail', 'activator_rail'}:
        rules = {'shape': {'north_south', 'east_west', 'ascending_east', 'ascending_west',
                           'ascending_north', 'ascending_south', 'south_east', 'south_west',
                           'north_west', 'north_east'}}
        if name != 'rail':
            rules['powered'] = BOOL
        return rules
    if name.endswith('_candle'):
        return {'candles': {'1', '2', '3', '4'}, 'lit': BOOL, 'waterlogged': BOOL}
    if name in {'amethyst_cluster', 'large_amethyst_bud', 'medium_amethyst_bud', 'small_amethyst_bud'}:
        return {'facing': SIX_WAY, 'waterlogged': BOOL}
    if name.endswith(('_log', '_wood')):
        return {'axis': {'x', 'y', 'z'}}
    if name.endswith('_leaves'):
        return {'distance': {str(i) for i in range(1, 8)}, 'persistent': BOOL, 'waterlogged': BOOL}
    if name == 'lantern':
        return {'hanging': BOOL, 'waterlogged': BOOL}
    if name == 'end_rod':
        return {'facing': HORIZONTAL | {'up', 'down'}}
    if name == 'barrel':
        return {'facing': HORIZONTAL | {'up', 'down'}, 'open': BOOL}
    if name == 'lectern':
        return {'facing': HORIZONTAL, 'has_book': BOOL, 'powered': BOOL}
    if name == 'grass_block':
        return {'snowy': BOOL}
    return {}


def classify_block(block):
    name, _ = split_block(block)
    if name in ('air', 'light', 'barrier', 'structure_void', 'water'):
        return name
    if is_pane(name):
        return 'glass_pane'
    if name in ('glass', 'tinted_glass') or name.endswith('_stained_glass'):
        return 'glass'
    return 'solid_or_decoration'


def has_water(block):
    name, states = split_block(block)
    return name == 'water' or states.get('waterlogged') == 'true'


def full_seal(block):
    """Conservative full-cube subset of the compiler's supported palette."""
    name, states = split_block(block)
    if name.endswith('_slab'):
        return states.get('type') == 'double'
    return (name not in {'air', 'light', 'structure_void', 'water', 'lantern', 'end_rod', 'iron_bars'}
            and not is_pane(name) and not name.endswith(('_stairs', '_door', '_trapdoor', '_fence', '_leaves')))


def canonical_block(block):
    name, states = split_block(block)
    defaults = {'light': {'level': '15', 'waterlogged': 'false'},
                'water': {'level': '0'}, 'barrier': {'waterlogged': 'false'}}.get(name, {})
    return name, tuple(sorted({**defaults, **states}.items()))


def cells(op):
    return product(*(range(a, b + 1) for a, b in zip(op['from'], op['to'])))


def intersect(first, second):
    return all(first['from'][i] <= second['to'][i] and second['from'][i] <= first['to'][i]
               for i in range(3))


def subtract(box, mask):
    if not intersect(box, mask):
        return [box]
    a, b = list(box['from']), list(box['to'])
    result = []
    for axis in range(3):
        lo, hi = max(a[axis], mask['from'][axis]), min(b[axis], mask['to'][axis])
        if a[axis] < lo:
            end = b.copy()
            end[axis] = lo - 1
            result.append({**box, 'from': a.copy(), 'to': end})
            a[axis] = lo
        if b[axis] > hi:
            start = a.copy()
            start[axis] = hi + 1
            result.append({**box, 'from': start, 'to': b.copy()})
            b[axis] = hi
    return result


def resolve_operations(ops, limit):
    masks = [op for op in ops if op['action'] in ('preserve', 'unknown') or op['confidence'] == 'uncertain']
    # Unknown/preserve masks are deliberately conservative, but they must not
    # erase a confirmed invisible special block that the v2 prompt traced to
    # readable on-video placement text.
    confirmed_special = [
        op for op in ops
        if op['action'] == 'place' and op['confidence'] == 'confirmed'
        and split_block(op.get('block', ''))[0] in ('light', 'barrier')
    ]
    for mask in masks:
        if any(intersect(mask, special) for special in confirmed_special):
            raise ValueError('Unknown/preserve mask overlaps a confirmed Light/Barrier placement')
    plan = []
    for op in ops:
        if op in masks:
            continue
        pieces = [op]
        for mask in masks:
            pieces = [part for piece in pieces for part in subtract(piece, mask)]
        for piece in pieces:
            kept = []
            for old in plan:
                # Operations are an ordered final plan. If the model repeats a
                # coordinate, the later operation wins deterministically;
                # missing replace=true must not abort an otherwise usable scene.
                kept.extend(subtract(old, piece))
            plan = kept + [piece]
            if len(plan) > limit:
                raise ValueError('Scene exclusions/overlaps produce too many command regions')
    return plan


def prepare_plan(ops, limit):
    plan = resolve_operations(ops, limit)
    world = {point: op['block'] for op in plan for point in cells(op)}
    resolved = []
    for op in plan:
        name, states = split_block(op['block'])
        if not is_pane(name) or HORIZONTAL <= states.keys():
            resolved.append(op)
            continue
        # Resolve missing pane connections from final planned geometry. Explicit
        # states win; unknown world neighbors are never assumed to be supports.
        runs = []
        for y in range(op['from'][1], op['to'][1] + 1):
            for z in range(op['from'][2], op['to'][2] + 1):
                for x in range(op['from'][0], op['to'][0] + 1):
                    connected = states.copy()
                    for direction, delta in DIRECTIONS.items():
                        neighbor = world.get((x + delta[0], y, z + delta[2]))
                        value = neighbor and (is_pane(split_block(neighbor)[0]) or full_seal(neighbor))
                        connected.setdefault(direction, 'true' if value else 'false')
                    block = 'minecraft:' + name + '[' + ','.join(f'{k}={v}' for k, v in sorted(connected.items())) + ']'
                    if runs and runs[-1]['block'] == block and runs[-1]['to'] == [x - 1, y, z]:
                        runs[-1]['to'][0] = x
                    else:
                        runs.append({**op, 'block': block, 'from': [x, y, z], 'to': [x, y, z]})
        resolved.extend(runs)
    if len(resolved) > limit:
        raise ValueError('Pane connections produce too many command regions')
    return resolved


def build_phase(op):
    if op['block'] == 'minecraft:air':
        return 0
    if has_water(op['block']):
        return 3
    if full_seal(op['block']):
        return 1
    return 2
