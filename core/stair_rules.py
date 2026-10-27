"""Deterministic stair states and collision boxes shared by export/preview."""
from .block_rules import cells, split_block, plan_lookup

DIRECTIONS = {'north': (0, 0, -1), 'east': (1, 0, 0),
              'south': (0, 0, 1), 'west': (-1, 0, 0)}
ORDER = tuple(DIRECTIONS)


def turn(direction, steps):
    return ORDER[(ORDER.index(direction) + steps) % 4]


def stair_shape(position, states, at):
    """Java StairBlock neighbor rule, including side-neighbor exclusion."""
    facing, half = states['facing'], states['half']

    def neighbor(direction, origin=position):
        delta = DIRECTIONS[direction]
        return tuple(origin[i] + delta[i] for i in range(3))

    def stairs(point):
        value = at(*point)
        if not value:
            return None
        name, other = split_block(value)
        return other if name.endswith('_stairs') and other.get('facing') in DIRECTIONS and other.get('half') == half else None

    def different(direction):
        other = stairs(neighbor(direction))
        return not other or other['facing'] != facing

    front = stairs(neighbor(facing))
    if front and (ORDER.index(front['facing']) - ORDER.index(facing)) % 2:
        if different(turn(front['facing'], 2)):
            return 'outer_left' if front['facing'] == turn(facing, -1) else 'outer_right'
    back = stairs(neighbor(turn(facing, 2)))
    if back and (ORDER.index(back['facing']) - ORDER.index(facing)) % 2:
        if different(back['facing']):
            return 'inner_left' if back['facing'] == turn(facing, -1) else 'inner_right'
    return 'straight'


def resolve_stairs(plan, at, diagnostics, limit):
    """Resolve missing states; never apply walk-flight rules to decorations.

    A walk annotation alone is insufficient: require a unique collinear run of
    at least three ascending stairs with bottom-half evidence. Top stairs and
    unclassified decorations keep their explicit video-supported facing.
    """
    prepared = []
    walk_at = plan_lookup([op for op in plan if op.get('stair_use') == 'walk'])
    for op in plan:
        name, states = split_block(op['block'])
        if not name.endswith('_stairs'):
            prepared.append(op)
            continue
        for point in cells(op):
            current = states.copy()
            candidates = []
            if op.get('stair_use') == 'walk' and current.get('half') != 'top':
                for direction, delta in DIRECTIONS.items():
                    def matches(step):
                        value = walk_at(point[0] + delta[0] * step, point[1] + step,
                                        point[2] + delta[2] * step)
                        if not value:
                            return False
                        other_name, other = split_block(value)
                        return other_name.endswith('_stairs') and other.get('half') == 'bottom'
                    if ((matches(-1) and matches(1)) or
                            (matches(1) and matches(2)) or (matches(-1) and matches(-2))):
                        candidates.append(direction)
            if len(candidates) == 1:
                facing = candidates[0]
                if current.get('facing') != facing:
                    diagnostics.append(f'Stair {point}: walk-flight geometry resolves facing={facing} (candidate={current.get("facing")}).')
                    current.pop('shape', None)
                current['facing'] = facing
                current.setdefault('half', 'bottom')
            if 'facing' not in current or 'half' not in current:
                diagnostics.append(f'Stair {point}: missing facing/half cannot be uniquely resolved; candidate {op["block"]} retained as unbuilt uncertainty.')
                continue
            prepared.append({**op, 'from': list(point), 'to': list(point),
                             'block': op['block'].split('[', 1)[0] + '[' + ','.join(f'{k}={v}' for k, v in current.items()) + ']'})
            if len(prepared) > limit:
                raise ValueError('Stair resolution produces too many command regions')

    # Lookups for the second pass must see corrected facings, not candidates.
    stair_cells = {tuple(op['from']): op['block'] for op in prepared
                   if split_block(op['block'])[0].endswith('_stairs')}

    def final_at(x, y, z):
        value = at(x, y, z)
        if value and split_block(value)[0].endswith('_stairs'):
            return stair_cells.get((x, y, z))
        return value

    result = []
    for op in prepared:
        name, states = split_block(op['block'])
        if not name.endswith('_stairs'):
            result.append(op)
            continue
        inferred = stair_shape(tuple(op['from']), states, final_at)
        if 'shape' in states and states['shape'] != inferred:
            diagnostics.append(f'Stair {op["from"]}: explicit shape={states["shape"]} retained; neighbor rule suggests {inferred}.')
        states.setdefault('shape', inferred)
        states.setdefault('waterlogged', 'false')
        result.append({**op, 'block': op['block'].split('[', 1)[0] + '[' + ','.join(f'{k}={v}' for k, v in states.items()) + ']'})
    return result


def block_boxes(block):
    """Local collision-like geometry; stair facing points toward its high end."""
    name, states = split_block(block)
    if name.endswith('_slab') and states.get('type') != 'double':
        yield (0, .5, 0, 1, 1, 1) if states.get('type') == 'top' else (0, 0, 0, 1, .5, 1)
        return
    if not name.endswith('_stairs'):
        yield (0, 0, 0, 1, 1, 1)
        return
    top = states['half'] == 'top'
    yield (0, .5 if top else 0, 0, 1, 1 if top else .5, 1)
    facing, shape = states['facing'], states.get('shape', 'straight')
    dx, _, dz = DIRECTIONS[facing]
    lx, _, lz = DIRECTIONS[turn(facing, -1)]
    for x in (0, .5):
        for z in (0, .5):
            forward = (x - .25) * dx + (z - .25) * dz > 0
            left = (x - .25) * lx + (z - .25) * lz > 0
            occupied = forward
            if shape.startswith('outer_'):
                occupied = forward and (left if shape.endswith('left') else not left)
            elif shape.startswith('inner_'):
                occupied = forward or (left if shape.endswith('left') else not left)
            if occupied:
                yield (x, 0 if top else .5, z, x + .5, .5 if top else 1, z + .5)
