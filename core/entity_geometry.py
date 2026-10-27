"""Check armor-stand feet/body against known planned geometry, without moving it."""
import math

from .block_rules import plan_lookup, split_block, full_seal
from .entity_nbt import compound_fields
from .stair_rules import block_boxes


def armor_stand_diagnostics(scene, plan):
    stands = [entity for entity in scene.get('entities', [])
              if entity['entity'] == 'minecraft:armor_stand']
    if not stands:
        return []
    at = plan_lookup(plan)
    diagnostics = []
    for entity in stands:
        x, y, z = entity['position']  # normalized exact feet coordinates
        raw = entity.get('nbt')
        nbt = compound_fields(raw) if isinstance(raw, str) else raw or {}

        def flag(key):
            value = nbt.get(key, False)
            if isinstance(value, str):
                return value.lower() == 'true' or value.lower() in ('1', '1b')
            return bool(value)

        if flag('Marker'):
            continue
        radius, height = (.125, .9875) if flag('Small') else (.25, 1.975)
        supported, collides = False, False
        for bx in range(math.floor(x - radius), math.floor(x + radius - 1e-9) + 1):
            for bz in range(math.floor(z - radius), math.floor(z + radius - 1e-9) + 1):
                for by in range(math.floor(y) - 1, math.floor(y + height - 1e-9) + 1):
                    block = at(bx, by, bz)
                    if not block:
                        continue
                    name, _ = split_block(block)
                    if not (full_seal(block) or name.endswith(('_stairs', '_slab'))):
                        continue
                    if name in ('air', 'water', 'light', 'structure_void'):
                        continue
                    for a, b, c, d, e, f in block_boxes(block):
                        horizontal = bx + a < x + radius and bx + d > x - radius and bz + c < z + radius and bz + f > z - radius
                        if horizontal and abs(by + e - y) < 1e-7:
                            supported = True
                        if horizontal and by + b < y + height - 1e-7 and by + e > y + 1e-7:
                            collides = True
        if collides:
            diagnostics.append(f'Armor stand feet {entity["position"]}: body intersects known planned geometry; verify cell/floor in source evidence. Position was not moved.')
        if not supported and not flag('NoGravity'):
            diagnostics.append(f'Armor stand feet {entity["position"]}: no matching support surface in the plan; existing terrain is unknown and gravity may change its landing. Position was not moved.')
    return diagnostics
