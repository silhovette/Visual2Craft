"""One local-to-Minecraft transform for blocks, entities and their directions.

Minecraft space: +X east, +Y up, +Z south. A facade scene has +X to the
observer's right and +Z into the building. Converting its *Z* axis places the
facade on the south edge, viewed looking north, without changing its left/right
layout. Unmarked legacy scenes already use Minecraft coordinates and stay put.
"""
from copy import deepcopy
import json
import math
from pathlib import Path

from .block_rules import split_block
from .entity_nbt import (compound_fields, numeric_list, number, render_fields,
                         PAINTING_DIRECTIONS, ENTITY_DIRECTIONS)

VECTORS = {'north': (0, -1), 'south': (0, 1), 'east': (1, 0), 'west': (-1, 0)}
BY_VECTOR = {value: key for key, value in VECTORS.items()}
# Factual vanilla defaults, exported from the official 26.3 block registry.
# This is input data, not an allowlist: unknown IDs/states remain supported.
DIRECTIONAL_DEFAULTS = json.loads(
    (Path(__file__).resolve().parents[1] / 'data' / 'directional_defaults_26_3.json')
    .read_text(encoding='utf-8'))['blocks']


def entity_position(entity):
    x, y, z = entity['position']
    mode = entity.get('position_mode')
    if mode is None:
        mode = ('cell' if entity['entity'] == 'minecraft:armor_stand'
                and type(x) is int and type(z) is int else 'exact')
    return [x + 0.5, y, z + 0.5] if mode == 'cell' else [x, y, z]


def transform_scene(scene, *, rotation=0, mirror=False):
    """Return a new scene; rotation is 0/90/180/270, mirror reflects local X.

    Coordinate metadata is consumed into canonical Minecraft coordinates, so
    compiler/preview normalization is idempotent. Explicit repeated rotations
    or mirrors still compose normally. Continuous positions reflect about W/D;
    block indices reflect about W-1/D-1.
    """
    if type(rotation) is not int or rotation not in (0, 90, 180, 270):
        raise ValueError('rotation must be 0, 90, 180 or 270')
    if type(mirror) is not bool:
        raise ValueError('mirror must be boolean')
    result = deepcopy(scene)
    facade = scene.get('coordinate_system', 'minecraft') == 'facade'
    if scene.get('coordinate_system', 'minecraft') not in ('minecraft', 'facade'):
        raise ValueError('Unknown scene coordinate_system')
    width, height, depth = scene['size']
    turns = rotation // 90

    def vector(x, z):
        if facade:
            z = -z
        if mirror:
            x = -x
        for _ in range(turns):
            x, z = -z, x
        return x, z

    def point(value, continuous=False):
        x, y, z = value
        w, d = width, depth
        edge = 0 if continuous else 1
        if facade:
            z = d - edge - z
        if mirror:
            x = w - edge - x
        for _ in range(turns):
            x, z = d - edge - z, x
            w, d = d, w
        return [x, y, z]

    def direction(value):
        return BY_VECTOR[vector(*VECTORS[value])] if value in VECTORS else value

    def yaw(value):
        # Minecraft yaw 0=south, 90=west, 180=north, 270=east.
        x, z = vector(-math.sin(math.radians(value)), math.cos(math.radians(value)))
        return round(math.degrees(math.atan2(-x, z)) % 360, 10) % 360

    reflected = facade != mirror

    def block(value):
        if not isinstance(value, str):
            return value
        _, states = split_block(value)
        name = value.split('[', 1)[0]
        # Legacy compact scenes can omit properties that vanilla defaults.
        # Materialize known directional defaults before rotating them; missing
        # stair facing/half deliberately remain unresolved, not game defaults.
        for key, state in DIRECTIONAL_DEFAULTS.get(name, {}).items():
            states.setdefault(key, state)
        updated = {}
        for key, state in states.items():
            target_key = direction(key)
            if key in ('facing', 'horizontal_facing'):
                state = direction(state)
            elif key == 'axis' and state in ('x', 'z') and turns % 2:
                state = 'z' if state == 'x' else 'x'
            elif key == 'rotation' and state.isdigit() and 0 <= int(state) < 16:
                state = str(round(yaw(int(state) * 22.5) / 22.5) % 16)
            elif key == 'orientation':
                state = '_'.join(direction(part) for part in state.split('_'))
            elif key == 'hinge' or (key == 'type' and name.endswith('chest')):
                if reflected and state in ('left', 'right'):
                    state = 'right' if state == 'left' else 'left'
            elif key == 'shape':
                if name.endswith('_stairs') and reflected and state.endswith(('_left', '_right')):
                    prefix, side = state.rsplit('_', 1)
                    state = prefix + ('_right' if side == 'left' else '_left')
                elif 'rail' in name:
                    parts = [direction(part) for part in state.split('_')]
                    if len(parts) == 2 and parts[0] != 'ascending':
                        pair = set(parts)
                        state = ('north_south' if pair == {'north', 'south'} else
                                 'east_west' if pair == {'east', 'west'} else
                                 next(p for p in ('north', 'south') if p in pair) + '_' +
                                 next(p for p in ('east', 'west') if p in pair))
                    else:
                        state = '_'.join(parts)
            updated[target_key] = state
        return name + ('[' + ','.join(f'{k}={v}' for k, v in updated.items()) + ']' if updated else '')

    for op in result['ops']:
        a, b = point(op['from']), point(op['to'])
        op['from'] = [min(a[i], b[i]) for i in range(3)]
        op['to'] = [max(a[i], b[i]) for i in range(3)]
        op['block'] = block(op.get('block'))

    changed = facade or mirror or rotation != 0
    for entity in result.get('entities', []):
        position = entity_position(entity)
        hanging = entity['entity'] in ('minecraft:painting', 'minecraft:item_frame', 'minecraft:glow_item_frame')
        if changed and hanging:
            # Java hanging entities floor summon coordinates to an attached
            # block anchor. An integer boundary must transform as a cell index,
            # otherwise D-z would attach it to the neighboring block.
            anchor = [math.floor(value) for value in position]
            target = point(anchor)
            fx, fz = vector(position[0] - anchor[0], position[2] - anchor[2])
            entity['position'] = [target[0] + fx % 1, position[1], target[2] + fz % 1]
        else:
            entity['position'] = point(position, continuous=True)
        entity['position_mode'] = 'exact'
        raw = entity.get('nbt')
        fields = compound_fields(raw) if isinstance(raw, str) else None
        nbt = fields if fields is not None else dict(raw or {})
        # Top-level rotation has a single, documented precedence over NBT.
        orientation = entity.get('rotation')
        if orientation is None and 'Rotation' in nbt:
            orientation = numeric_list(nbt['Rotation']) if fields is not None else nbt['Rotation']
        if orientation is not None:
            if len(orientation) != 2:
                raise ValueError('Entity Rotation must have yaw and pitch')
            entity['rotation'] = [yaw(float(orientation[0])) if changed else orientation[0], orientation[1]]
            nbt.pop('Rotation', None)
        if changed:
            # Hanging entities use an attached block anchor, not a body center.
            for keys in (('TileX', 'TileY', 'TileZ'),):
                if all(key in nbt for key in keys):
                    anchor = [int(number(nbt[key])) if fields is not None else nbt[key] for key in keys]
                    for key, value in zip(keys, point(anchor)):
                        nbt[key] = str(value) if fields is not None else value
            if 'block_pos' in nbt:
                anchor = numeric_list(nbt['block_pos']) if fields is not None else nbt['block_pos']
                if len(anchor) != 3 or any(int(value) != value for value in anchor):
                    raise ValueError('Hanging entity block_pos must contain three integers')
                target = point([int(value) for value in anchor])
                nbt['block_pos'] = '[I;' + ','.join(map(str, target)) + ']' if fields is not None else target
            for key in ('Facing', 'facing'):
                if key in nbt:
                    raw_direction = nbt[key]
                    try:
                        numeric = int(number(raw_direction)) if fields is not None else int(raw_direction)
                        # Painting's lowercase facing uses Java's 2D legacy
                        # codec; item-frame Facing uses the 3D legacy codec.
                        directions = (PAINTING_DIRECTIONS
                                      if key == 'facing' and entity['entity'] == 'minecraft:painting'
                                      else ENTITY_DIRECTIONS)
                        new = {v: k for k, v in directions.items()}.get(direction(directions.get(numeric)), numeric)
                        nbt[key] = str(new) + ('b' if raw_direction.lower().endswith('b') else '') if fields is not None else new
                    except (ValueError, TypeError):
                        text = raw_direction.strip('"\'') if fields is not None else raw_direction
                        nbt[key] = '"' + direction(text) + '"' if fields is not None else direction(text)
            if reflected and entity['entity'] in ('minecraft:item_frame', 'minecraft:glow_item_frame') and 'ItemRotation' in nbt:
                value = int(number(nbt['ItemRotation'])) if fields is not None else nbt['ItemRotation']
                nbt['ItemRotation'] = str((-value) % 8) + 'b' if fields is not None else (-value) % 8
        entity['nbt'] = render_fields(nbt) if fields is not None else nbt
    result['size'] = [depth, height, width] if turns % 2 else [width, height, depth]
    result['coordinate_system'] = 'minecraft'
    return result
