"""Live Minecraft scene state and a batched Qt Quick 3D mesh.

The scene store deliberately consumes the same resolved operation plan used by
the datapack compiler.  It never turns an unknown/preserved region into air.
Qt Quick 3D receives one mesh for the whole visible scene, so a scene update is
one bounded upload instead of one QML object per block.
"""
from __future__ import annotations

from collections.abc import Iterable
from array import array
import math
import sys
from typing import Any

from .block_rules import prepare_plan, split_block
from .stair_rules import block_boxes

try:  # The pure scene store remains importable without Qt in unit tests.
    from PySide6.QtCore import QByteArray, Property, Signal
    from PySide6.QtGui import QVector3D
    from PySide6.QtQuick3D import QQuick3DGeometry
except ImportError:  # pragma: no cover - exercised only in non-Qt environments
    QByteArray = QVector3D = QQuick3DGeometry = None
    def Property(_type=None, **_kwargs):
        return lambda function: property(function)
    class Signal:  # pragma: no cover - compatibility shim for pure-store imports
        def __init__(self, *_args, **_kwargs): pass


MAX_RENDER_BLOCKS = 1_000_000


def _block_name(block: str) -> str:
    return split_block(block)[0].removeprefix("minecraft:")


def _is_transparent(block: str) -> bool:
    name = _block_name(block)
    return (name in {"air", "water", "glass", "tinted_glass"}
            or name.endswith(("_glass", "_glass_pane", "_leaves", "_pane")))


def _is_hidden(block: str) -> bool:
    # These blocks affect the datapack but have no normal in-game geometry.
    return _block_name(block) in {"light", "barrier", "structure_void"}


def scene_blocks(scene: dict[str, Any], *, limit: int = MAX_RENDER_BLOCKS) -> dict[tuple[int, int, int], str]:
    """Resolve a validated scene into final block coordinates.

    ``prepare_plan`` is shared with ``compile_datapack``.  Empty/unknown and
    explicit air cells remove an earlier placement; uncertainty is simply
    absent from the result.
    """
    from .video2pack import prepare_scene, MAX_COMMANDS
    scene = prepare_scene(scene)
    plan = prepare_plan(scene['ops'], MAX_COMMANDS)
    blocks: dict[tuple[int, int, int], str] = {}
    for op in plan:
        block = op.get("block")
        if not isinstance(block, str):
            continue
        action = op.get("action")
        for y in range(op["from"][1], op["to"][1] + 1):
            for z in range(op["from"][2], op["to"][2] + 1):
                for x in range(op["from"][0], op["to"][0] + 1):
                    point = (x, y, z)
                    if action == "clear" or block == "minecraft:air":
                        blocks.pop(point, None)
                    elif action == "place" and op.get("confidence") == "confirmed":
                        if _is_hidden(block):
                            blocks.pop(point, None)
                        else:
                            blocks[point] = block
                        if len(blocks) > limit:
                            raise ValueError(f"Live preview is limited to {limit:,} visible blocks")
    return blocks


def _colour(block: str) -> tuple[float, float, float, float]:
    """Stable, restrained Minecraft-like colours for the no-asset fallback.

    The block ID/state remains the source of truth; this palette is only a
    renderer fallback when a resource-pack atlas is unavailable.
    """
    name = _block_name(block)
    # Keep fluids and glass readable as ghosted geometry while leaving solid
    # construction blocks visible as a restrained translucent overlay.
    alpha = 0.06 if (name == "water" or "glass" in name or name.endswith("_pane")) else 0.72
    palette = (
        ("water", (0.16, 0.40, 0.78, 0.68)), ("glass", (0.56, 0.76, 0.90, 0.38)),
        ("ice", (0.56, 0.80, 0.94, 0.62)), ("oak", (0.58, 0.37, 0.16, 1.0)),
        ("spruce", (0.27, 0.16, 0.09, 1.0)), ("birch", (0.77, 0.69, 0.49, 1.0)),
        ("jungle", (0.42, 0.28, 0.14, 1.0)), ("deepslate", (0.22, 0.24, 0.28, 1.0)),
        ("stone", (0.49, 0.51, 0.53, 1.0)), ("cobble", (0.38, 0.40, 0.40, 1.0)),
        ("brick", (0.66, 0.25, 0.20, 1.0)), ("quartz", (0.82, 0.80, 0.74, 1.0)),
        ("sand", (0.78, 0.68, 0.45, 1.0)), ("grass", (0.30, 0.57, 0.23, 1.0)),
        ("leaves", (0.19, 0.48, 0.22, 0.78)), ("iron", (0.70, 0.72, 0.70, 1.0)),
        ("gold", (0.92, 0.66, 0.17, 1.0)), ("copper", (0.72, 0.38, 0.24, 1.0)),
        ("wool", (0.74, 0.74, 0.76, 1.0)), ("concrete", (0.56, 0.58, 0.61, 1.0)),
    )
    for token, colour in palette:
        if token in name:
            return (*colour[:3], alpha)
    return (0.48, 0.44, 0.39, alpha)


def _parts(block: str) -> Iterable[tuple[float, float, float, float, float, float]]:
    yield from block_boxes(block)


_FACES = (
    # normal, four corners in counter-clockwise order
    ((0, 0, -1), ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0))),
    ((0, 0, 1), ((1, 0, 1), (0, 0, 1), (0, 1, 1), (1, 1, 1))),
    ((-1, 0, 0), ((0, 0, 1), (0, 0, 0), (0, 1, 0), (0, 1, 1))),
    ((1, 0, 0), ((1, 0, 0), (1, 0, 1), (1, 1, 1), (1, 1, 0))),
    ((0, -1, 0), ((0, 0, 1), (1, 0, 1), (1, 0, 0), (0, 0, 0))),
    ((0, 1, 0), ((0, 1, 0), (1, 1, 0), (1, 1, 1), (0, 1, 1))),
)


def _mesh(blocks: dict[tuple[int, int, int], str]):
    if not blocks:
        return b"", b"", (0, 0, 0), (0, 0, 0), (0, 0, 0), 0
    first = next(iter(blocks))
    min_x = max_x = first[0]
    min_y = max_y = first[1]
    min_z = max_z = first[2]
    for x, y, z in blocks:
        min_x = min(min_x, x); max_x = max(max_x, x)
        min_y = min(min_y, y); max_y = max(max_y, y)
        min_z = min(min_z, z); max_z = max(max_z, z)
    minimum = (min_x, min_y, min_z)
    maximum = (max_x, max_y, max_z)
    center = ((min_x + max_x + 1) / 2, (min_y + max_y + 1) / 2,
              (min_z + max_z + 1) / 2)
    verts = array('f')
    indices = array('I')
    # Block states repeat heavily in normal builds. Cache renderer-only
    # properties once per state instead of reparsing them for every face.
    render_by_block = {
        block: (not _is_transparent(block), tuple(_parts(block)), _colour(block))
        for block in set(blocks.values())
    }
    for (x, y, z), block in blocks.items():
        opaque, shapes, rgba = render_by_block[block]
        for x0, y0, z0, x1, y1, z1 in shapes:
            for normal, corners in _FACES:
                neighbour = (x + normal[0], y + normal[1], z + normal[2])
                reaches_edge = ((normal[0] < 0 and x0 == 0) or (normal[0] > 0 and x1 == 1) or
                                (normal[1] < 0 and y0 == 0) or (normal[1] > 0 and y1 == 1) or
                                (normal[2] < 0 and z0 == 0) or (normal[2] > 0 and z1 == 1))
                neighbor_render = render_by_block.get(blocks.get(neighbour))
                if (reaches_edge and opaque and neighbor_render and neighbor_render[0]
                        and neighbor_render[1] == ((0, 0, 0, 1, 1, 1),)):
                    continue
                base = len(verts) // 10
                for cx, cy, cz in corners:
                    verts.extend((x + x0 + cx * (x1 - x0) - center[0],
                                  y + y0 + cy * (y1 - y0) - center[1],
                                  z + z0 + cz * (z1 - z0) - center[2], *normal, *rgba))
                indices.extend((base, base + 1, base + 2, base, base + 2, base + 3))
    radius = max(1.0, math.sqrt((max_x - min_x) ** 2 +
                                 (max_y - min_y) ** 2 +
                                 (max_z - min_z) ** 2) / 2)
    # Qt expects little-endian buffers. Packed arrays avoid Python objects
    # and the huge argument copies caused by struct.pack(*millions_of_values).
    if sys.byteorder != 'little':
        verts.byteswap()
        indices.byteswap()
    return (verts.tobytes(), indices.tobytes(),
            center, minimum, maximum, radius)


class BlockGeometry(QQuick3DGeometry if QQuick3DGeometry is not None else object):
    """One indexed mesh containing all visible block faces."""
    radiusValueChanged = Signal()
    floorYChanged = Signal()
    def __init__(self, parent=None):
        if QQuick3DGeometry is None:
            return
        # QQuick3DGeometry accepts only a QQuick3DObject parent.  The bridge
        # retains this object for the lifetime of the application instead.
        super().__init__(None)
        self.setStride(40)  # position (3), normal (3), colour (4), all float32
        self.addAttribute(self._attribute(self.Attribute.PositionSemantic, self.Attribute.ComponentType.F32Type, 0))
        self.addAttribute(self._attribute(self.Attribute.NormalSemantic, self.Attribute.ComponentType.F32Type, 12))
        self.addAttribute(self._attribute(self.Attribute.ColorSemantic, self.Attribute.ComponentType.F32Type, 24))
        self.addAttribute(self._attribute(self.Attribute.IndexSemantic, self.Attribute.ComponentType.U32Type, 0))
        self.setPrimitiveType(self.PrimitiveType.Triangles)
        self._blocks = {}
        self._radius = 1.0
        self._floor_y = -0.5
        self.update_blocks({})

    @staticmethod
    def _attribute(semantic, component, offset):
        attr = QQuick3DGeometry.Attribute()
        attr.semantic = semantic
        attr.componentType = component
        attr.offset = offset
        return attr

    @property
    def radius(self):
        return self._radius

    # QML-facing read-only geometry hints used to keep the camera and ground
    # fitted as the final building dimensions become known.
    @Property(float, notify=radiusValueChanged)
    def radiusValue(self):
        return float(self._radius)

    @Property(float, notify=floorYChanged)
    def floorY(self):
        return float(self._floor_y)

    @property
    def block_count(self):
        return len(self._blocks)

    def update_blocks(self, blocks: dict[tuple[int, int, int], str]):
        old_radius, old_floor = self._radius, self._floor_y
        self._blocks = dict(blocks)
        vertex, index, center, minimum, maximum, self._radius = _mesh(self._blocks)
        if QQuick3DGeometry is None:
            return
        self.setVertexData(QByteArray(vertex))
        self.setIndexData(QByteArray(index))
        if self._blocks:
            self.setBounds(QVector3D(minimum[0] - center[0], minimum[1] - center[1], minimum[2] - center[2]),
                           QVector3D(maximum[0] + 1 - center[0], maximum[1] + 1 - center[1], maximum[2] + 1 - center[2]))
            self._floor_y = minimum[1] - center[1]
        else:
            self.setBounds(QVector3D(-1, -1, -1), QVector3D(1, 1, 1))
            self._floor_y = -0.5
        if self._radius != old_radius:
            self.radiusValueChanged.emit()
        if self._floor_y != old_floor:
            self.floorYChanged.emit()
        self.update()


__all__ = ["BlockGeometry", "MAX_RENDER_BLOCKS", "scene_blocks"]
