#!/usr/bin/env python3
"""MimetiCraft MVP: construction video -> approximate voxel scene -> Minecraft Java 26.3 datapack ZIP.

Use --video with ChatGPT Sign in (default) or an optional API key; --scene works offline.
No custom training. Video inference quality is not guaranteed.
"""
from __future__ import annotations

import argparse
import base64
import heapq
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import zipfile
from typing import Any, Callable

from .block_rules import (BLOCK_KNOWLEDGE, SPECIAL_PALETTE, build_phase,
                          has_water, prepare_plan, state_rules)
from .scene_transform import transform_scene, entity_position
from .entity_nbt import (compound_fields, render_fields, split_top, numeric_list,
                         normalize_hanging_nbt)

PACK_VERSION = [121, 0]  # Java 26.3
NAMESPACE = "vidbuild"
MAX_DIMENSIONS = (512, 384, 512)
MAX_VOLUME = 100_663_296
MAX_OPS = 8_000
MAX_FILL = 4096
MAX_COMMANDS = 200_000
MAX_FRAMES = 1200
DEFAULT_FRAMES = 500


def _prompt_asset(name: str) -> str:
    """Load a versioned prompt asset shipped beside this module.

    Keeping the prompt in text files makes the model contract reviewable and
    prevents a UI-only build from silently retaining an older inline prompt.
    """
    path = Path(__file__).resolve().parents[1] / "prompts" / name
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"Missing prompt asset: {path}") from exc


RECONSTRUCTION_PROMPT = _prompt_asset("01_RECONSTRUCTION_PROMPT.txt")
USER_HINTS_WRAPPER = _prompt_asset("03_USER_HINTS_WRAPPER.txt")
FRAME_WRAPPER = _prompt_asset("04_FRAME_WRAPPER.txt")

# Legacy IDs retained for conservative fluid-seal generation. The reference
# registry below is informational; ID validation remains syntax-based so newly
# added and version-specific placeable blocks are not blocked.
PALETTE = [
    "air", "stone", "cobblestone", "mossy_cobblestone", "stone_bricks", "mossy_stone_bricks",
    "cracked_stone_bricks", "andesite", "polished_andesite", "diorite", "polished_diorite",
    "granite", "polished_granite", "deepslate", "cobbled_deepslate", "deepslate_bricks",
    "deepslate_tiles", "tuff", "tuff_bricks", "bricks", "mud_bricks", "sandstone",
    "smooth_sandstone", "quartz_block", "smooth_quartz", "quartz_bricks", "white_concrete",
    "light_gray_concrete", "gray_concrete", "black_concrete", "brown_concrete", "red_concrete",
    "yellow_concrete", "blue_concrete", "green_concrete", "orange_concrete", "cyan_concrete",
    "white_terracotta", "orange_terracotta", "terracotta", "white_wool", "black_wool",
    "glass", "tinted_glass", "white_stained_glass", "light_blue_stained_glass", "glass_pane",
    "white_stained_glass_pane", "oak_planks", "spruce_planks", "dark_oak_planks",
    "birch_planks", "jungle_planks", "acacia_planks", "mangrove_planks", "cherry_planks",
    "oak_log", "spruce_log", "dark_oak_log", "stripped_oak_log", "stripped_spruce_log",
    "stripped_dark_oak_log", "oak_leaves", "spruce_leaves", "birch_leaves", "oak_fence",
    "spruce_fence", "dark_oak_fence", "iron_bars", "iron_block", "gold_block", "copper_block",
    "cut_copper", "oxidized_copper", "stone_slab", "stone_brick_slab", "smooth_stone_slab",
    "quartz_slab", "oak_slab", "spruce_slab", "dark_oak_slab", "brick_slab",
    "deepslate_brick_slab", "stone_stairs", "stone_brick_stairs", "quartz_stairs",
    "oak_stairs", "spruce_stairs", "dark_oak_stairs", "brick_stairs", "deepslate_brick_stairs",
    "oak_door", "spruce_door", "iron_door", "oak_trapdoor", "spruce_trapdoor",
    "lantern", "sea_lantern", "glowstone", "end_rod", "grass_block", "dirt",
    "coarse_dirt", "gravel", "sand", "water", "bookshelf", "barrel", "crafting_table",
    "smooth_quartz_slab",
]
PALETTE = list(dict.fromkeys(PALETTE + SPECIAL_PALETTE))


def _load_vanilla_block_ids() -> set[str]:
    registry = Path(__file__).resolve().parents[1] / "data" / "vanilla_blocks_26_3.txt"
    try:
        names = {line.strip() for line in registry.read_text(encoding="utf-8").splitlines()
                 if line.strip() and not line.startswith("#")}
    except OSError:
        # Keep the source project usable if an incomplete packaging step omitted
        # the registry; the legacy palette still provides a safe, small fallback.
        names = set(PALETTE)
    return {"minecraft:" + name for name in names} | {"minecraft:" + name for name in PALETTE}


PALETTE_SET = _load_vanilla_block_ids()
# Resource-location syntax used by vanilla and installed Minecraft content.
# The compiler deliberately does not maintain a second, incomplete block/state
# registry that can reject a newly added or mod-provided placeable block.
BLOCK_RE = re.compile(
    r"^(?P<namespace>[a-z0-9_.-]+):(?P<path>[a-z0-9/._-]+)"
    r"(?:\[(?P<states>[a-z0-9_.-]+=[a-z0-9_.-]+"
    r"(?:,[a-z0-9_.-]+=[a-z0-9_.-]+)*)\])?$")
# A small set of legacy names that changed in the target 26.3 registry.
# Normalize them before emitting commands/tags so one stale model token cannot
# make Minecraft reject an entire function file.
BLOCK_ID_ALIASES = {
    "minecraft:chain": "minecraft:iron_chain",
}
FORBIDDEN_MATERIAL_REPLACEMENTS = {
    "minecraft:lava": "minecraft:ochre_froglight",
    "minecraft:magma_block": "minecraft:ochre_froglight",
    "minecraft:lava_cauldron": "minecraft:ochre_froglight",
}
ENTITY_RE = re.compile(r"^[a-z0-9_.-]+:[a-z0-9/._-]+$")
SCENE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["name", "size", "base_y", "ops", "entities", "coordinate_system"],
    "properties": {
        "name": {"type": "string"},
        "size": {"type": "array", "items": {"type": "integer"}},
        "base_y": {"type": "integer"},
        "coordinate_system": {"type": "string", "enum": ["facade"]},
        "ops": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["action", "confidence", "evidence", "replace", "block", "from", "to", "stair_use"],
            "properties": {
                "action": {"type": "string", "enum": ["place", "clear", "preserve", "unknown"]},
                "confidence": {"type": "string", "enum": ["confirmed", "uncertain"]},
                "evidence": {"type": "object", "additionalProperties": False,
                             "required": ["frames", "observation", "hint"], "properties": {
                                 "frames": {"type": "array", "items": {"type": "integer"}},
                                 "observation": {"type": "string"},
                                 "hint": {"type": ["string", "null"]}}},
                "replace": {"type": "boolean"},
                "stair_use": {"type": ["string", "null"], "enum": ["walk", "decorative", None]},
                "block": {"type": ["string", "null"]},
                "from": {"type": "array", "items": {"type": "integer"}},
                "to": {"type": "array", "items": {"type": "integer"}},
            },
        }},
        "entities": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["entity", "position", "position_mode", "rotation", "nbt", "evidence"],
            "properties": {
                "entity": {"type": "string"},
                "position": {"type": "array", "items": {"type": "number"}},
                "position_mode": {"type": "string", "enum": ["cell", "exact"]},
                "rotation": {"type": ["array", "null"], "items": {"type": "number"}},
                # Strict Responses schemas cannot contain an arbitrary object
                # with unknown NBT keys. SNBT keeps entity-specific data open.
                "nbt": {"type": ["string", "null"]},
                "evidence": {"type": "object", "additionalProperties": False,
                             "required": ["frames", "observation", "hint"], "properties": {
                                 "frames": {"type": "array", "items": {"type": "integer"}},
                                 "observation": {"type": "string"},
                                 "hint": {"type": ["string", "null"]}}},
            },
        }},
    },
}

# A nullable block is meaningful only for non-placement operations. Keep that
# relationship in the model schema rather than relying on prompt compliance.
_OP_SCHEMA = SCENE_SCHEMA['properties']['ops']['items']
SCENE_SCHEMA['properties']['ops']['items'] = {'anyOf': [
    {**_OP_SCHEMA, 'properties': {**_OP_SCHEMA['properties'],
        'action': {'type': 'string', 'enum': [action]},
        'confidence': {'type': 'string', 'enum': confidence},
        'block': block}}
    for action, confidence, block in (
        ('place', ['confirmed'], {'type': 'string'}),
        ('clear', ['confirmed'], {'type': 'string', 'enum': ['minecraft:air']}),
        ('preserve', ['confirmed', 'uncertain'], {'type': 'null'}),
        ('unknown', ['uncertain'], {'type': 'null'}),
    )
]}


def check_block(block: str) -> str:
    if not isinstance(block, str):
        raise ValueError("block name must be a string")
    base, separator, state_suffix = block.partition('[')
    if base in FORBIDDEN_MATERIAL_REPLACEMENTS:
        # Lava-like material is intentionally rendered as an orange/yellow
        # luminous solid. Drop fluid/container states because they do not
        # belong to the replacement block.
        block = FORBIDDEN_MATERIAL_REPLACEMENTS[base]
    else:
        block = BLOCK_ID_ALIASES.get(base, base) + (separator + state_suffix if separator else '')
    m = BLOCK_RE.fullmatch(block)
    if m is None:
        raise ValueError(f"Malformed block identifier: {block}")
    states_raw = m.group('states')
    if states_raw:
        pairs = states_raw.split(",")
        seen = set()
        for pair in pairs:
            if pair.count("=") != 1:
                raise ValueError(f"Malformed block state: {block}")
            key, value = pair.split("=")
            # State families evolve with the target Java version and the model
            # can emit a legitimate property that this client does not know
            # yet (for example cave_vines[berries=true]). Validate only the
            # safe wire syntax and duplicate-key rule here; the game remains
            # the authoritative registry for block-specific state semantics.
            if key in seen:
                raise ValueError(f"Duplicate block state key: {block}")
            seen.add(key)
    if m.group('namespace') == 'minecraft' and m.group('path').endswith('_stairs'):
        rules = state_rules(m.group('path'))
        for key, value in (pair.split('=') for pair in (states_raw or '').split(',') if pair):
            if key not in rules or value not in rules[key]:
                raise ValueError(f'Invalid stair state {key}={value}: {block}')
    return block


def parse_point(value: Any, name: str) -> tuple[int, int, int]:
    if not isinstance(value, list) or len(value) != 3 or any(type(v) is not int for v in value):
        raise ValueError(f"{name} must be [integer x, integer y, integer z]")
    return tuple(value)


def _validate_entity_nbt(value: Any, name: str) -> dict[str, Any] | str:
    if value is None:
        return {}
    if isinstance(value, str):
        if '\n' in value or '\r' in value:
            raise ValueError(f'{name}.nbt cannot contain newlines')
        return value
    if not isinstance(value, dict):
        raise ValueError(f'{name}.nbt must be an SNBT string, object, or null')
    return value


def _validate_entity_entry(entity: Any, index: int, dims: tuple[int, int, int]) -> dict[str, Any]:
    if not isinstance(entity, dict):
        raise ValueError(f'entities[{index}] is not an object')
    entity_id = entity.get('entity')
    if not isinstance(entity_id, str) or ENTITY_RE.fullmatch(entity_id) is None:
        raise ValueError(f'entities[{index}].entity is not a valid resource ID')
    point = entity.get('position')
    if (not isinstance(point, list) or len(point) != 3 or
            any(type(v) not in (int, float) or not math.isfinite(v) for v in point)):
        raise ValueError(f'entities[{index}].position must contain three finite numbers')
    mode = entity.get('position_mode')
    if mode is None:
        mode = ('cell' if entity_id == 'minecraft:armor_stand'
                and type(point[0]) is int and type(point[2]) is int else 'exact')
    if mode not in ('cell', 'exact'):
        raise ValueError('Entity position_mode must be cell or exact')
    if mode == 'cell' and (entity_id != 'minecraft:armor_stand' or
                           any(type(point[i]) is not int for i in (0, 2))):
        raise ValueError('cell positions require armor_stand with integer X/Z; use exact for other entities')
    hanging = entity_id in ('minecraft:painting', 'minecraft:item_frame', 'minecraft:glow_item_frame')
    if any(point[i] < 0 or point[i] > dims[i] or
           (((mode == 'cell' and i in (0, 2)) or hanging) and point[i] == dims[i]) for i in range(3)):
        raise ValueError(f'entities[{index}].position is outside scene bounds: {point} within {dims}')
    rotation = entity.get('rotation')
    if rotation is not None:
        if (not isinstance(rotation, list) or len(rotation) != 2 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in rotation)):
            raise ValueError(f'entities[{index}].rotation must be [yaw, pitch]')
        rotation = [float(rotation[0]), float(rotation[1])]
    evidence = entity.get('evidence')
    if (not isinstance(evidence, dict) or not isinstance(evidence.get('frames'), list) or
            any(type(frame) is not int or frame < 0 for frame in evidence['frames']) or
            not isinstance(evidence.get('observation'), str) or
            evidence.get('hint') is not None and not isinstance(evidence.get('hint'), str)):
        raise ValueError(f'Invalid evidence in entities[{index}]')
    nbt = normalize_hanging_nbt(entity_id, _validate_entity_nbt(entity.get('nbt'), f'entities[{index}]'))
    fields = compound_fields(nbt) if isinstance(nbt, str) else nbt
    if 'Pos' in fields:
        raise ValueError('Entity Pos in NBT conflicts with position; use the Scene position field')
    if 'Rotation' in fields:
        values = numeric_list(fields['Rotation']) if isinstance(nbt, str) else fields['Rotation']
        if (not isinstance(values, list) or len(values) != 2 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in values)):
            raise ValueError('Entity NBT Rotation requires finite yaw and pitch')
    return {
        'entity': entity_id,
        'position': list(point),
        'position_mode': mode,
        'rotation': rotation,
        'nbt': nbt,
        'evidence': {
            'frames': list(evidence['frames']),
            'observation': evidence['observation'],
            'hint': evidence.get('hint'),
        },
    }


def validate_scene(scene: Any) -> dict[str, Any]:
    if not isinstance(scene, dict):
        raise ValueError("Scene must be a JSON object")
    coordinate_system = scene.get('coordinate_system', 'minecraft')
    if coordinate_system not in ('minecraft', 'facade'):
        raise ValueError('coordinate_system must be minecraft or facade')
    dims = parse_point(scene.get("size"), "size")
    if any(not (1 <= d <= lim) for d, lim in zip(dims, MAX_DIMENSIONS)):
        raise ValueError('Scene dimensions limited to ' + ' x '.join(map(str, MAX_DIMENSIONS)))
    base_y = scene.get('base_y', 0)
    if type(base_y) is not int or not 0 <= base_y < dims[1]:
        raise ValueError(f"base_y must be an integer within 0..{dims[1] - 1}")
    if dims[0] * dims[1] * dims[2] > MAX_VOLUME:
        raise ValueError(f"Scene volume exceeds {MAX_VOLUME:,} cells")
    ops = scene.get("ops")
    if not isinstance(ops, list) or not 1 <= len(ops) <= MAX_OPS:
        raise ValueError(f"Scene requires 1..{MAX_OPS} ops")
    validated = []
    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            raise ValueError(f"Operation {i} isn't a JSON object")
        if 'block' not in op:
            raise ValueError(f'ops[{i}].block is missing; provide a block ID or explicit null for an unknown region')
        # Old offline scenes use an explicit block as the placement/clear request.
        # New model scenes have separate intent and confidence fields.
        action = op.get('action', 'clear' if op.get('block') == 'minecraft:air' else 'place')
        confidence = op.get('confidence', 'uncertain' if action == 'unknown' else 'confirmed')
        replace = op.get('replace', False)
        if action not in ('place', 'clear', 'preserve', 'unknown'):
            raise ValueError(f'Invalid action in operation {i}')
        if confidence not in ('confirmed', 'uncertain') or type(replace) is not bool:
            raise ValueError(f'Invalid confidence/replace in operation {i}')
        if op['block'] is None and action in ('place', 'clear'):
            # Safely recover an older/non-conforming model response. Missing a
            # block name is uncertainty, never permission to clear with air.
            action, confidence, replace = 'unknown', 'uncertain', False
        if action in ('preserve', 'unknown') or confidence == 'uncertain':
            block = op.get('block')
            if block is not None and not isinstance(block, str):
                raise ValueError(f'Invalid proposed block in operation {i}')
        else:
            try:
                block = check_block(op['block'])
            except ValueError as exc:
                kind = type(op['block']).__name__
                raise ValueError(f'ops[{i}].block ({kind}): {exc}') from None
            if (action == 'clear') != (block == 'minecraft:air'):
                raise ValueError('Air requires an explicit clear action; clear may only place minecraft:air')
        raw_a = parse_point(op.get("from"), f"ops[{i}].from")
        raw_b = parse_point(op.get("to"), f"ops[{i}].to")
        # Models occasionally emit the two opposite corners in reverse order
        # on one axis (for example z=6 .. z=0).  A cuboid is unordered by
        # nature, so normalize each axis before checking bounds and compiling.
        # This preserves the requested region while avoiding a needless
        # generation failure.
        a = tuple(min(raw_a[axis], raw_b[axis]) for axis in range(3))
        b = tuple(max(raw_a[axis], raw_b[axis]) for axis in range(3))
        if any(a[j] > b[j] or a[j] < 0 or b[j] >= dims[j] for j in range(3)):
            raise ValueError(f"Invalid bounds in operation {i}: {a}..{b} within {dims}")
        if block == "minecraft:air" and (b[0] - a[0] + 1)*(b[1] - a[1] + 1)*(b[2] - a[2] + 1) > 100000:
            raise ValueError(f"Air clearing too large in operation {i}; keep clears bounded to the building interior")
        evidence = op.get('evidence')
        if evidence is not None and (not isinstance(evidence, dict) or
                not isinstance(evidence.get('frames'), list) or
                any(type(frame) is not int or frame < 0 for frame in evidence['frames']) or
                not isinstance(evidence.get('observation'), str) or
                evidence.get('hint') is not None and not isinstance(evidence.get('hint'), str)):
            raise ValueError(f'Invalid evidence in operation {i}')
        stair_use = op.get('stair_use')
        if stair_use not in (None, 'walk', 'decorative'):
            raise ValueError('stair_use must be walk, decorative or null')
        validated.append({"action": action, "confidence": confidence, "replace": replace,
                          "evidence": evidence, "block": block, "from": list(a), "to": list(b),
                          "stair_use": stair_use})
    raw_entities = scene.get('entities', [])
    if not isinstance(raw_entities, list) or len(raw_entities) > MAX_OPS:
        raise ValueError(f'entities requires 0..{MAX_OPS} entries')
    entities = [_validate_entity_entry(entity, i, dims) for i, entity in enumerate(raw_entities)]
    return {"name": str(scene.get("name") or "video_build")[:80], "size": list(dims),
            "base_y": base_y, "ops": validated, "entities": entities,
            "coordinate_system": coordinate_system}


def prepare_scene(scene, *, rotation=0, mirror=False):
    """Canonical geometry shared by direct commands, export and preview."""
    return validate_scene(transform_scene(validate_scene(scene), rotation=rotation, mirror=mirror))


def split_fill(a: tuple[int, ...], b: tuple[int, ...]):
    """Yield inclusive cuboids whose volumes are <= MAX_FILL."""
    volume = 1
    for i in range(3):
        volume *= b[i] - a[i] + 1
    if volume <= MAX_FILL:
        yield a, b
        return
    largest = max(range(3), key=lambda i: b[i] - a[i])
    if a[largest] == b[largest]:
        raise ValueError("Cannot split region")
    mid = (a[largest] + b[largest]) // 2
    left_b = list(b)
    left_b[largest] = mid
    right_a = list(a)
    right_a[largest] = mid + 1
    yield from split_fill(a, tuple(left_b))
    yield from split_fill(tuple(right_a), b)


def _snbt(value: Any) -> str:
    """Serialize JSON-compatible entity NBT into command SNBT."""
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return '[' + ','.join(_snbt(item) for item in value if item is not None) + ']'
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            if item is None:
                continue
            key_text = key if isinstance(key, str) and re.fullmatch(r'[A-Za-z0-9_.+-]+', key) else json.dumps(str(key))
            parts.append(f'{key_text}:{_snbt(item)}')
        return '{' + ','.join(parts) + '}'
    raise ValueError(f'Unsupported entity NBT value: {type(value).__name__}')


def _append_snbt_fields(raw: str, fields: dict[str, Any]) -> str:
    existing = compound_fields(raw)
    for key, value in fields.items():
        if key == 'Tags' and key in existing:
            previous = existing[key].strip()
            if not (previous.startswith('[') and previous.endswith(']')):
                raise ValueError('Entity Tags must be a list')
            existing[key] = '[' + ','.join(split_top(previous[1:-1]) + [_snbt(tag) for tag in value]) + ']'
        else:
            existing[key] = _snbt(value)
    return render_fields(existing)


def make_entity_commands(scene: dict[str, Any]) -> list[str]:
    scene = prepare_scene(scene)
    commands = []
    base_y = int(scene.get('base_y', 0))
    for entity in scene.get('entities', []):
        raw_nbt = entity.get('nbt')
        if isinstance(raw_nbt, str):
            nbt_text = _append_snbt_fields(raw_nbt, {
                'Tags': ['vidbuild_entity'],
                **({'Rotation': entity['rotation']} if entity.get('rotation') is not None else {}),
            })
        else:
            nbt = dict(raw_nbt or {})
            tags = nbt.get('Tags', [])
            if not isinstance(tags, list):
                tags = []
            nbt['Tags'] = [str(tag) for tag in tags] + ['vidbuild_entity']
            if entity.get('rotation') is not None:
                nbt['Rotation'] = entity['rotation']
            nbt_text = _snbt(nbt)
        x, y, z = entity_position(entity)
        commands.append(f"summon {entity['entity']} ~{x:.15g} ~{y - base_y:.15g} ~{z:.15g} {nbt_text}")
    return commands


def make_commands(scene: dict[str, Any], *, plan=None) -> list[str]:
    scene = prepare_scene(scene)
    plan = prepare_plan(scene['ops'], MAX_COMMANDS) if plan is None else plan
    base_y = int(scene.get('base_y', 0))
    lines = []
    for op in sorted(plan, key=build_phase):
        block = op["block"]
        for a, b in split_fill(tuple(op["from"]), tuple(op["to"])):
            ay, by = a[1] - base_y, b[1] - base_y
            if a == b:
                lines.append(f"setblock ~{a[0]} ~{ay} ~{a[2]} {block} strict")
            else:
                lines.append(f"fill ~{a[0]} ~{ay} ~{a[2]} ~{b[0]} ~{by} ~{b[2]} {block} strict")
    if len(lines) > MAX_COMMANDS:
        raise ValueError("Too many commands for first MVP")
    return lines


def make_undo_commands(scene: dict[str, Any], *, plan=None) -> list[str]:
    """Undo placed blocks, leaving the layer below the base as grass.

    Blocks at local ``base_y - 1`` (the player's standing block) are replaced
    with grass so the generated building's footprint remains visible. Other
    placed blocks are removed.
    This is still a destructive operation, not a world snapshot; it cannot
    restore terrain/blocks that were overwritten by the build.
    """
    scene = prepare_scene(scene)
    plan = prepare_plan(scene['ops'], MAX_COMMANDS) if plan is None else plan
    base_y = int(scene.get('base_y', 0))
    grass_y = base_y - 1
    commands = []
    # Remove sources/waterlogged hosts before opening their container walls.
    for op in sorted(reversed(plan), key=lambda item: not has_water(item['block'])):
        block = op["block"]
        if block == "minecraft:air":
            continue
        # Ignore states when matching to tolerate automatic stair/door updates.
        block_id = block.split("[", 1)[0]
        for a, b in split_fill(tuple(op["from"]), tuple(op["to"])):
            # A fill may span the standing-block layer. Split it first so only the
            # local ``base_y - 1`` slice is left as grass.
            regions = []
            if b[1] < grass_y or a[1] > grass_y:
                regions.append((a, b, "minecraft:air"))
            else:
                if a[1] < grass_y:
                    regions.append((a, (b[0], grass_y - 1, b[2]), "minecraft:air"))
                regions.append(((a[0], grass_y, a[2]),
                                (b[0], grass_y, b[2]),
                                "minecraft:grass_block"))
                if b[1] > grass_y:
                    regions.append(((a[0], grass_y + 1, a[2]), b, "minecraft:air"))

            for region_a, region_b, replacement in regions:
                ay, by = region_a[1] - base_y, region_b[1] - base_y
                if region_a == region_b:
                    commands.append(
                        f"execute if block ~{region_a[0]} ~{ay} ~{region_a[2]} {block_id} "
                        f"run setblock ~{region_a[0]} ~{ay} ~{region_a[2]} {replacement} strict"
                    )
                else:
                    commands.append(
                        f"fill ~{region_a[0]} ~{ay} ~{region_a[2]} ~{region_b[0]} ~{by} ~{region_b[2]} "
                        f"{replacement} replace {block_id} strict"
                    )
    if len(commands) > MAX_COMMANDS:
        raise ValueError("Too many undo commands for this MVP")
    return commands


def compile_datapack(scene: dict[str, Any], output: Path, offset: tuple[int, int, int] = (5, 0, 5)) -> dict[str, Any]:
    scene = prepare_scene(scene)
    diagnostics = []
    plan = prepare_plan(scene['ops'], MAX_COMMANDS, diagnostics=diagnostics)
    from .entity_geometry import armor_stand_diagnostics
    diagnostics.extend(armor_stand_diagnostics(scene, plan))
    forward = make_commands(scene, plan=plan) + make_entity_commands(scene)
    reverse = make_undo_commands(scene, plan=plan)
    if scene.get('entities'):
        reverse.append(f'kill @e[tag=vidbuild_entity,distance=..{sum(scene["size"]) + 2}]')
    if not forward:
        raise ValueError('No confirmed placements remain; unknown/preserved space is not built')
    output.parent.mkdir(parents=True, exist_ok=True)
    pack = {"pack": {"description": f"MimetiCraft build/undo: {scene['name']}",
                     "min_format": PACK_VERSION, "max_format": PACK_VERSION}}
    build_chunks = [forward[i:i + 400] for i in range(0, len(forward), 400)]
    undo_chunks = [reverse[i:i + 400] for i in range(0, len(reverse), 400)]

    # The last origin is saved as precise NBT coordinates + dimension. Do not
    # allow a second build while one is active; this avoids losing undo state.
    build = (
        "# Only one pending build per world. Undo before building again.\n"
        'execute if data storage vidbuild:history last run tellraw @s {"text":"A build is pending. Run /function vidbuild:undo first.","color":"yellow"}\n'
        'execute unless data storage vidbuild:history last if dimension minecraft:overworld run function vidbuild:internal/start\n'
        'execute unless data storage vidbuild:history last if dimension minecraft:the_nether run function vidbuild:internal/start\n'
        'execute unless data storage vidbuild:history last if dimension minecraft:the_end run function vidbuild:internal/start\n'
        'execute unless dimension minecraft:overworld unless dimension minecraft:the_nether unless dimension minecraft:the_end run tellraw @s {"text":"Only the three vanilla dimensions are supported by tracked undo.","color":"red"}\n'
    )
    for op in scene['ops']:
        if op['action'] in ('preserve', 'unknown') or op['confidence'] == 'uncertain':
            build = f"# Keep world unchanged: {op['action']} {op['from']}..{op['to']}\n" + build
    start = (
        f"# Align position to block corner; origin offset = {offset}.\n"
        f"execute align xyz positioned ~{offset[0]} ~{offset[1]} ~{offset[2]} "
        'summon minecraft:marker run function vidbuild:internal/build_at_origin\n'
    )
    # /execute summon sets @s to the transient marker; access its exact Pos
    # with /data modify ... set from entity, avoiding integer rounding bugs.
    commit_build = (
        'data modify storage vidbuild:history last set value {dimension:"minecraft:overworld",x:0.0d,y:0.0d,z:0.0d}\n'
        'execute if dimension minecraft:the_nether run data modify storage vidbuild:history last.dimension set value "minecraft:the_nether"\n'
        'execute if dimension minecraft:the_end run data modify storage vidbuild:history last.dimension set value "minecraft:the_end"\n'
        'data modify storage vidbuild:history last.x set from entity @s Pos[0]\n'
        'data modify storage vidbuild:history last.y set from entity @s Pos[1]\n'
        'data modify storage vidbuild:history last.z set from entity @s Pos[2]\n'
        'function vidbuild:parts/all\n'
    )
    build_at_origin = commit_build + 'kill @s\n'
    # Test for missing state before a successful undo removes that state.
    undo = (
        'execute unless data storage vidbuild:history last run tellraw @s {"text":"Nothing to undo; use /function vidbuild:build first.","color":"yellow"}\n'
        'execute if data storage vidbuild:history last run function vidbuild:internal/undo_from_saved_origin with storage vidbuild:history last\n'
    )
    # Function macros are supported by Java since 1.20.2. This can locate the
    # previous build even if the player has moved or changed dimension.
    undo_macro = (
        '# Dynamic origin and dimension from vidbuild:history last.\n'
        '$execute in $(dimension) positioned $(x) $(y) $(z) run function vidbuild:internal/undo_at_origin\n'
    )
    max_x, _, max_z = [n-1 for n in scene["size"]]
    # 4 corner checks prevent deletion of the undo record if building chunks
    # are unloaded. Stay nearby when undoing. The last Y is already in range
    # because the user originally built there.
    undo_at_origin = (
        'data modify storage vidbuild:history loaded set value {ok:0b}\n'
        f'execute if loaded ~0 ~0 ~0 if loaded ~{max_x} ~0 ~0 '
        f'if loaded ~0 ~0 ~{max_z} if loaded ~{max_x} ~0 ~{max_z} '
        'run data modify storage vidbuild:history loaded.ok set value 1b\n'
        'execute if data storage vidbuild:history loaded{ok:1b} run function vidbuild:internal/commit_undo\n'
        'execute unless data storage vidbuild:history loaded{ok:1b} run tellraw @s {"text":"Undo paused: return near the structure so its chunks are loaded, then retry.","color":"yellow"}\n'
        'data remove storage vidbuild:history loaded\n'
    )
    commit_undo = (
        'function vidbuild:parts/undo_all\n'
        'data remove storage vidbuild:history last\n'
    )

    base = f"data/{NAMESPACE}/function"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("pack.mcmeta", json.dumps(pack, ensure_ascii=False, indent=2) + "\n")
        z.writestr(f"{base}/build.mcfunction", build)
        z.writestr(f"{base}/undo.mcfunction", undo)
        z.writestr(f"{base}/check.mcfunction",
                   'tellraw @s {"text":"MimetiCraft 26.3 ready: /function vidbuild:build and /function vidbuild:undo","color":"green"}\n')
        z.writestr(f"{base}/internal/start.mcfunction", start)
        z.writestr(f"{base}/internal/build_at_origin.mcfunction", build_at_origin)
        z.writestr(f'{base}/internal/commit_build.mcfunction', commit_build)
        z.writestr(f"{base}/internal/undo_from_saved_origin.mcfunction", undo_macro)
        z.writestr(f"{base}/internal/undo_at_origin.mcfunction", undo_at_origin)
        z.writestr(f"{base}/internal/commit_undo.mcfunction", commit_undo)
        z.writestr(f"{base}/parts/all.mcfunction",
                   "".join(f"function {NAMESPACE}:parts/part_{i:03d}\n" for i in range(len(build_chunks))))
        z.writestr(f"{base}/parts/undo_all.mcfunction",
                   "".join(f"function {NAMESPACE}:parts/undo_part_{i:03d}\n" for i in range(len(undo_chunks))))
        for i, commands in enumerate(build_chunks):
            z.writestr(f"{base}/parts/part_{i:03d}.mcfunction", "\n".join(commands) + "\n")
        for i, commands in enumerate(undo_chunks):
            z.writestr(f"{base}/parts/undo_part_{i:03d}.mcfunction", "\n".join(commands) + "\n")
    return {"zip": str(output), "scene": scene["name"], "size": scene["size"],
            "base_y": scene["base_y"], "operations": len(scene["ops"]),
            "entities": len(scene.get('entities', [])), "commands": len(forward),
            "undo_commands": len(reverse), "parts": len(build_chunks),
            "offset": list(offset), "undo_function": f"{NAMESPACE}:undo",
            "diagnostics": diagnostics,
            "skipped_regions": sum(op['action'] in ('unknown', 'preserve') or
                                   op['confidence'] == 'uncertain' for op in scene['ops'])}

def _sample_frame_ids(length: int, count: int) -> list[int]:
    """Distinct chronological samples, biased slightly toward later construction."""
    count = min(count, length)
    if count == 1:
        return [length - 1]
    ids = []
    for i in range(count):
        proposed = round((length - 1) * (i / (count - 1)) ** .72)
        # Reserve enough unused positions for the remaining samples.
        lower = ids[-1] + 1 if ids else 0
        ids.append(min(max(proposed, lower), length - count + i))
    return ids


def _frame_difference(first, second) -> float:
    """Cheap appearance difference; local tiles keep small changes relevant."""
    import numpy as np

    difference = np.abs(first.astype(np.float32) - second.astype(np.float32)).mean(axis=2)
    tiles = difference.reshape(6, 12, 8, 12).mean(axis=(1, 3)).ravel()
    local = np.partition(tiles, -4)[-4:].mean()
    return float((difference.mean() + local) / 2)


def _select_frame_indices(signatures, sharpness, target: int) -> list[int]:
    """Remove least-novel interior frames; update their surviving neighbors.

    This is an appearance heuristic, not semantic scene understanding. Keep the
    first and last decoded frames and return exactly target if enough exist.
    """
    total = len(signatures)
    if total <= target:
        return list(range(total))
    if target == 1:
        return [total - 1]
    previous = [i - 1 for i in range(total)]
    following = [i + 1 for i in range(total)]
    active = [True] * total
    versions = [0] * total
    edges = [_frame_difference(signatures[i], signatures[i + 1]) for i in range(total - 1)] + [0.0]
    heap = []

    def enqueue(index):
        if 0 < index < total - 1 and active[index]:
            versions[index] += 1
            novelty = min(edges[previous[index]], edges[index])
            heapq.heappush(heap, (novelty, sharpness[index], index, versions[index]))

    for index in range(1, total - 1):
        enqueue(index)
    remaining = total
    while remaining > target:
        _, _, index, version = heapq.heappop(heap)
        if not active[index] or version != versions[index]:
            continue
        left, right = previous[index], following[index]
        active[index] = False
        following[left], previous[right] = right, left
        edges[left] = _frame_difference(signatures[left], signatures[right])
        remaining -= 1
        enqueue(left)
        enqueue(right)
    return [index for index in range(total) if active[index]]


def video_frames(path: Path, count: int):
    if type(count) is not int or not 1 <= count <= MAX_FRAMES:
        raise ValueError(f"frame count must be 1..{MAX_FRAMES}")
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("Install dependencies: pip install -r requirements.txt") from exc
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {path}")
    try:
        length = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if length <= 0:
            raise RuntimeError("Video has no readable frames")
        target = min(count, length)
        candidate_count = min((count * 11 + 9) // 10, length)
        frame_ids = _sample_frame_ids(length, candidate_count)
        frames = []
        signatures, sharpness = [], []
        # Dense sampling avoids repeatedly decoding the same keyframe interval.
        sequential = length <= candidate_count * 64
        next_frame = 0
        for frame_id in frame_ids:
            if sequential:
                while next_frame < frame_id:
                    if not capture.grab():
                        break
                    next_frame += 1
                if next_frame != frame_id:
                    break
            else:
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_id)
            ok, frame = capture.read()
            next_frame = frame_id + 1
            if not ok:
                continue
            height, width = frame.shape[:2]
            factor = min(1., 1280/max(width, height))
            if factor < 1:
                frame = cv2.resize(frame, (int(width*factor), int(height*factor)), interpolation=cv2.INTER_AREA)
            ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                frames.append((frame_id, jpeg.tobytes()))
                thumbnail = cv2.resize(frame, (96, 72), interpolation=cv2.INTER_AREA)
                signatures.append(thumbnail)
                gray = cv2.cvtColor(thumbnail, cv2.COLOR_BGR2GRAY)
                sharpness.append(float(cv2.Laplacian(gray, cv2.CV_32F).var()))
        if not frames:
            raise RuntimeError("Unable to decode frames")
        selected = _select_frame_indices(signatures, sharpness, target)
        result = [frames[index] for index in selected]
        print(f"Local frame filter: requested {count}, sampled {len(frames)}/{candidate_count} "
              f"candidates, removed {len(frames) - len(result)}, kept {len(result)}.", flush=True)
        if len(result) < count:
            print('Video has fewer readable sampled frames than requested; using all available samples.', flush=True)
        return result
    finally:
        capture.release()


class _ModelFailure(RuntimeError):
    def __init__(self, message: str, code: str = 'unknown_error'):
        super().__init__(message)
        self.code = code


def _report_progress(progress, message: str):
    print(message, flush=True)
    if progress:
        progress(message)


def _request_scene_text(client, request: dict, model: str, frame_count: int,
                        progress=None) -> str:
    """Retry a transient failure once, only before any model output arrives."""
    transient = {'server_error', 'internal_error', 'server_is_overloaded',
                 'service_unavailable', 'service_unavailable_error',
                 'rate_limit_exceeded', 'slow_down', 'stream_ended'}
    no_retry = {'subscription_sharing_usage_limit_exceeded', 'subscription_sharing_usage_unavailable',
                'insufficient_quota', 'context_length_exceeded', 'invalid_request_error',
                'invalid_prompt', 'response_incomplete'}
    for attempt in range(2):
        output_started = False
        http_status, request_id, retry_after = None, None, None

        def metadata(response):
            nonlocal http_status, request_id, retry_after
            if response is not None:
                http_status = getattr(response, 'status_code', http_status)
                headers = getattr(response, 'headers', {})
                request_id = headers.get('x-request-id') or request_id
                retry_after = headers.get('retry-after') or retry_after

        try:
            result = client.responses.create(**request)
            if not request.get('stream'):
                request_id = getattr(result, '_request_id', None)
                if getattr(result, 'status', None) == 'incomplete':
                    raise _ModelFailure('Model stopped before completing the scene.', 'response_incomplete')
                return result.output_text
            deltas = []
            completed = False
            with result as stream:
                metadata(getattr(stream, 'response', None))
                for event in stream:
                    kind = event.type
                    if kind.startswith(('response.output_', 'response.reasoning')):
                        output_started = True
                    if kind == 'response.output_text.delta':
                        if not deltas:
                            _report_progress(progress, 'Receiving building scene from OpenAI...')
                        deltas.append(event.delta)
                    elif kind in ('response.failed', 'error'):
                        error = getattr(getattr(event, 'response', None), 'error', None) or event
                        code = getattr(error, 'code', None) or 'unknown_error'
                        raise _ModelFailure('OpenAI reported a failed generation.', code)
                    elif kind == 'response.incomplete':
                        raise _ModelFailure('Model stopped before completing the scene.', 'response_incomplete')
                    elif kind == 'response.completed':
                        completed = True
                        if not deltas:
                            for item in (getattr(event.response, 'output', None) or []):
                                for part in (getattr(item, 'content', None) or []):
                                    if getattr(part, 'type', '') == 'output_text':
                                        deltas.append(part.text)
            if not completed:
                raise _ModelFailure('Stream ended without response.completed; no ZIP was written.', 'stream_ended')
            return ''.join(deltas)
        except Exception as exc:
            metadata(getattr(exc, 'response', None))
            request_id = getattr(exc, 'request_id', None) or request_id
            body = getattr(exc, 'body', None)
            error = body.get('error', body) if isinstance(body, dict) else {}
            if not isinstance(error, dict):
                error = {}
            code = getattr(exc, 'code', None) or error.get('code') or error.get('type') or 'unknown_error'
            # Some streaming APIError exceptions omit response headers and only
            # include the public request ID in their diagnostic message.
            match = re.search(r'\breq_[A-Za-z0-9_-]+', str(exc))
            request_id = request_id or (match.group() if match else None)
            network_error = type(exc).__name__ in ('APIConnectionError', 'APITimeoutError')
            retryable = code not in no_retry and (code in transient or network_error or
                                                 isinstance(http_status, int) and 500 <= http_status < 600)
            delay = 2.0
            if retry_after:
                try:
                    delay = max(delay, float(retry_after))
                except (TypeError, ValueError):
                    # Do not ignore an HTTP-date or unrecognized Retry-After.
                    delay = 31.0
            if retryable and not output_started and attempt == 0 and delay <= 30:
                _report_progress(progress, f'OpenAI temporary error ({code}); retrying once in {delay:g}s with the same frames and model...')
                time.sleep(delay)
                continue
            # Only expose bounded diagnostic metadata, never bodies, headers,
            # authorization credentials, input images, or partial scene text.
            safe_code = str(code) if re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', str(code)) else 'unknown_error'
            safe_id = str(request_id) if request_id and re.fullmatch(r'req_[A-Za-z0-9_-]{1,200}', str(request_id)) else 'unavailable'
            lines = ['OpenAI image analysis failed; no new ZIP was generated.',
                     f'Model: {model}', f'Frames submitted: {frame_count}',
                     f'Attempt: {attempt + 1}/2', f'HTTP status: {http_status or "unavailable"}',
                     f'Error code: {safe_code}', f'Request ID: {safe_id}']
            if isinstance(exc, _ModelFailure):
                lines.append(str(exc))
            if output_started:
                lines.append('Model output had already started. Not automatically replayed to avoid duplicate usage.')
            elif code in no_retry:
                lines.append('This error is not automatically retried. Check account limits, input size or model support.')
            elif retryable:
                lines.append('The temporary error persisted or the server requested a longer wait. Try again later.')
            else:
                lines.append('Retry only after checking the error details. If it repeats, try fewer frames or another listed model.')
            raise RuntimeError('\n'.join(lines)) from None


def _downgrade_malformed_model_blocks(scene: dict[str, Any]) -> int:
    """Keep malformed confirmed model blocks as explicit untouched regions."""
    downgraded = 0
    for op in scene.get('ops', []):
        if not isinstance(op, dict):
            continue
        if op.get('action') not in ('place', 'clear') or op.get('confidence') != 'confirmed':
            continue
        try:
            check_block(op.get('block'))
        except (TypeError, ValueError):
            # A stray token such as "/6" is model uncertainty, never a reason
            # to abort the whole scene and never permission to place air.
            op.update(action='unknown', confidence='uncertain', replace=False, block=None)
            downgraded += 1
    return downgraded


def infer_scene(video: Path, model: str, frame_count: int, api_key: str | None = None,
                auth_mode: str = "chatgpt", access_token: str | None = None,
                progress: Callable[[str], None] | None = None,
                building_hints: str = '') -> dict[str, Any]:
    if not isinstance(building_hints, str) or len(building_hints) > 8192:
        raise ValueError('Building hints must be text up to 8192 characters')
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install dependencies: pip install -r requirements.txt") from exc
    if auth_mode not in ("chatgpt", "api"):
        raise ValueError("auth_mode must be chatgpt or api")
    if auth_mode == "chatgpt" and not access_token:
        raise RuntimeError("ChatGPT sign-in is required. Sign in from the desktop app.")
    if auth_mode == "api" and not (api_key or os.getenv("OPENAI_API_KEY")):
        raise RuntimeError("API key mode requires OPENAI_API_KEY")
    frames = video_frames(video, frame_count)
    _report_progress(progress, f"Extracted {len(frames)} frames; invoking {model}...")
    # Prompt v2.0 is supplied as reviewed, versioned text assets. The model
    # still receives one instruction message and one structured JSON request.
    prompt = RECONSTRUCTION_PROMPT + "\n\n" + BLOCK_KNOWLEDGE
    content = [{"type": "input_text", "text": prompt}]
    if building_hints.strip():
        content.append({'type': 'input_text',
                        'text': USER_HINTS_WRAPPER.format(building_hints=building_hints)})
    for index, (frame_id, jpg) in enumerate(frames):
        frame_text = (FRAME_WRAPPER
                      .replace("{index+1}", str(index + 1))
                      .replace("{len(frames)}", str(len(frames)))
                      .replace("{frame_id}", str(frame_id)))
        content.append({"type":"input_text", "text": frame_text})
        content.append({"type":"input_image", "image_url":"data:image/jpeg;base64," + base64.b64encode(jpg).decode("ascii"), "detail":"high"})
    request = dict(model=model, input=[{"role": "user", "content": content}],
                   text={"format": {"type": "json_schema", "name": "minecraft_build_scene", "strict": True, "schema": SCENE_SCHEMA}})
    if auth_mode == "api":
        client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"), max_retries=0)
        # Let the selected model use its output budget; the former 20k cap
        # could stop a detailed large-building scene before its upper floors.
    else:
        # OpenAI's Sign in with ChatGPT usage route specifically requires
        # store=False, stream=True and forbids max_output_tokens. It uses the
        # PUBLIC Responses API, never the ChatGPT backend-api.
        client = OpenAI(api_key=access_token, base_url="https://api.openai.com/v1", max_retries=0)
        request.update(store=False, stream=True)
    try:
        output_text = _request_scene_text(client, request, model, len(frames), progress)
    finally:
        close = getattr(client, 'close', None)
        if close:
            close()
    if not output_text:
        raise RuntimeError("Model did not return a JSON scene; try fewer frames or another model")
    try:
        raw_scene = json.loads(output_text)
        malformed_blocks = _downgrade_malformed_model_blocks(raw_scene)
        scene = validate_scene(raw_scene)
        available = {frame_id for frame_id, _ in frames}
        sanitized_frames = 0
        downgraded_ops = 0
        for raw_op, op in zip(raw_scene['ops'], scene['ops']):
            if not {'action', 'confidence', 'evidence', 'replace'} <= raw_op.keys():
                raise ValueError('Model scene requires explicit action, confidence, evidence and replace fields')
            evidence = op['evidence']
            if evidence is None:
                raise ValueError('Model scene requires explicit evidence and uncertainty metadata')
            valid_frames = [frame for frame in evidence['frames'] if frame in available]
            sanitized_frames += len(evidence['frames']) - len(valid_frames)
            evidence['frames'] = valid_frames
            if evidence['hint'] and (not building_hints.strip() or evidence['hint'] not in building_hints):
                evidence['hint'] = None
            if op['confidence'] == 'confirmed' and op['action'] in ('place', 'clear'):
                if not evidence['observation'].strip() or not (evidence['frames'] or evidence['hint']):
                    # Do not let a bad citation abort the entire generation.
                    # Retain the region as an explicit uncertainty, which
                    # produces no placement command and cannot clear terrain.
                    op['action'], op['confidence'], op['replace'], op['block'] = (
                        'unknown', 'uncertain', False, None)
                    downgraded_ops += 1
        if sanitized_frames:
            _report_progress(progress, f'Ignored {sanitized_frames} model frame citation(s) not present in the supplied samples.')
        if downgraded_ops:
            _report_progress(progress, f'Downgraded {downgraded_ops} model region(s) with unusable evidence to unknown; those regions remain untouched.')
        if malformed_blocks:
            _report_progress(progress, f'Downgraded {malformed_blocks} model region(s) with malformed block IDs to unknown; those regions remain untouched.')
        kept_entities = []
        dropped_entities = 0
        for entity in scene.get('entities', []):
            evidence = entity['evidence']
            valid_frames = [frame for frame in evidence['frames'] if frame in available]
            sanitized_frames += len(evidence['frames']) - len(valid_frames)
            evidence['frames'] = valid_frames
            if evidence['hint'] and (not building_hints.strip() or evidence['hint'] not in building_hints):
                evidence['hint'] = None
            if evidence['observation'].strip() and (evidence['frames'] or evidence['hint']):
                kept_entities.append(entity)
            else:
                dropped_entities += 1
        scene['entities'] = kept_entities
        if dropped_entities:
            _report_progress(progress, f'Dropped {dropped_entities} entity object(s) with unusable evidence; they will not be summoned.')
        unresolved = sum(op.get('block') is None and op.get('action') in ('place', 'clear')
                         for op in scene['ops'])
        if unresolved:
            _report_progress(progress, f'Model returned {unresolved} unnamed block region(s); leaving those regions untouched, never replacing them with air.')
        return scene
    except json.JSONDecodeError as exc:
        raise RuntimeError("Model returned malformed JSON; try a different model or fewer frames") from exc



def run(*, video: str | None = None, scene_path: str | None = None, out: str = "video_build.zip",
        model: str | None = None, frames: int = DEFAULT_FRAMES, api_key: str | None = None,
        auth_mode: str = "chatgpt", access_token: str | None = None,
        offset: tuple[int, int, int] = (5, 0, 5),
        progress: Callable[[str], None] | None = None,
        building_hints: str = '', rotation: int = 0, mirror: bool = False) -> dict[str, Any]:
    if (video is None) == (scene_path is None):
        raise ValueError("Choose exactly one: video or scene_path")
    if not 2 <= frames <= MAX_FRAMES:
        raise ValueError(f"frames must be 2..{MAX_FRAMES}")
    if scene_path:
        scene = validate_scene(json.loads(Path(scene_path).read_text(encoding="utf8")))
    else:
        scene = infer_scene(Path(video), model or "gpt-5.5", frames, api_key,
                            auth_mode=auth_mode, access_token=access_token, progress=progress,
                            building_hints=building_hints)
    _report_progress(progress, 'Scene received and validated. Writing Data Pack ZIP...')
    scene = prepare_scene(scene, rotation=rotation, mirror=mirror)
    dest = Path(out)
    summary = compile_datapack(scene, dest, offset=offset)
    for diagnostic in summary.get('diagnostics', []):
        _report_progress(progress, diagnostic)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Video -> Minecraft Java 26.3 datapack ZIP (MVP)")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--video", help="Construction video (MP4 etc.), ChatGPT login or API key")
    src.add_argument("--scene", help="Existing scene JSON, offline pack creation")
    parser.add_argument("--out", default="video_build.zip")
    parser.add_argument("--model", default=None, help="OAuth mode defaults to first account model")
    parser.add_argument("--auth", choices=("chatgpt", "api"), default="chatgpt", help="Video model authentication")
    parser.add_argument("--frames", type=int, default=DEFAULT_FRAMES,
                        help=f"Sample 2..{MAX_FRAMES} frames (default: {DEFAULT_FRAMES})")
    parser.add_argument("--offset", nargs=3, type=int, default=(5,0,5), metavar=("X","Y","Z"))
    parser.add_argument('--building-hints', default='', help='Optional explicit building instructions; kept separate from video evidence')
    parser.add_argument('--rotate', type=int, choices=(0, 90, 180, 270), default=0,
                        help='Rotate the whole normalized scene, including directional states and entities')
    parser.add_argument('--mirror', action='store_true', help='Reflect the normalized scene across its X axis')
    args = parser.parse_args()
    try:
        access_token = None
        model = args.model
        if args.video and args.auth == "chatgpt":
            from .chatgpt_auth import ChatGPTAuth
            auth = ChatGPTAuth()
            access_token = auth.access_token()
            if not model:
                model = auth.models()[0][1]
        summary = run(video=args.video, scene_path=args.scene, out=args.out, model=model,
                      frames=args.frames, auth_mode=args.auth, access_token=access_token,
                      offset=tuple(args.offset), building_hints=args.building_hints,
                      rotation=args.rotate, mirror=args.mirror)
        print(f"Created: {summary['zip']} ({summary['commands']} block commands)")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
