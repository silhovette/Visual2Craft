"""Small lossless SNBT compound editor for entity placement fields.

Unknown payloads (items, poses, painting variants) remain verbatim. This is not
a second Minecraft NBT registry: only placement-related fields are interpreted.
"""
import json
import math
import re

PAINTING_DIRECTIONS = {0: 'south', 1: 'west', 2: 'north', 3: 'east'}
ENTITY_DIRECTIONS = {0: 'down', 1: 'up', 2: 'north', 3: 'south', 4: 'west', 5: 'east'}


def split_top(text, separator=','):
    result, start, stack, quote, escaped = [], 0, [], None, False
    for index, char in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char in '[{(':
            stack.append(char)
        elif char in ']})':
            if not stack or stack.pop() != {']': '[', '}': '{', ')': '('}[char]:
                raise ValueError('Unbalanced entity SNBT')
        elif char == separator and not stack:
            result.append(text[start:index].strip())
            start = index + 1
    if quote or stack:
        raise ValueError('Unbalanced entity SNBT')
    if text[start:].strip():
        result.append(text[start:].strip())
    return result


def compound_fields(text):
    text = text.strip() or '{}'
    if not (text.startswith('{') and text.endswith('}')):
        raise ValueError('Entity nbt must be an SNBT compound enclosed in braces')
    fields = {}
    for entry in split_top(text[1:-1]):
        parts = split_top(entry, ':')
        # Values can contain unquoted namespaced IDs: split at the first colon.
        if len(parts) < 2:
            raise ValueError('Malformed entity SNBT field')
        key = parts[0]
        if key.startswith('"'):
            key = json.loads(key)
        elif key.startswith("'"):
            key = key[1:-1].replace("\\'", "'").replace('\\\\', '\\')
        if key in fields:
            raise ValueError(f'Duplicate entity SNBT field: {key}')
        fields[key] = ':'.join(parts[1:])
    return fields


def number(text):
    value = float(re.sub(r'[bBsSlLfFdD]$', '', text.strip()))
    if not math.isfinite(value):
        raise ValueError('Entity numeric fields must be finite')
    return value


def numeric_list(text):
    text = text.strip()
    if not text.startswith('[') or not text.endswith(']'):
        raise ValueError('Expected entity numeric list')
    inner = re.sub(r'^[BILbil];', '', text[1:-1].strip())
    return [number(item) for item in split_top(inner)]


def render_fields(fields):
    return '{' + ','.join(f'{json.dumps(key)}:{value}' for key, value in fields.items()) + '}'


def normalize_hanging_nbt(entity_id, nbt):
    """26.3 painting uses lowercase 2D facing; frames use uppercase 3D Facing.

    Accept the project's legacy painting Facing convention as an alias, rather
    than emitting a key that the target game silently ignores.
    """
    if entity_id not in ('minecraft:painting', 'minecraft:item_frame', 'minecraft:glow_item_frame'):
        return nbt
    raw = isinstance(nbt, str)
    fields = compound_fields(nbt) if raw else dict(nbt)
    painting = entity_id == 'minecraft:painting'
    key = 'facing' if painting else 'Facing'
    source_key = key if key in fields else 'Facing' if painting and 'Facing' in fields else None
    if source_key is not None:
        value = fields[source_key]
        codec = PAINTING_DIRECTIONS if source_key == 'facing' and painting else ENTITY_DIRECTIONS
        try:
            numeric = number(value) if raw else float(value)
            if not math.isfinite(numeric) or numeric != int(numeric) or int(numeric) not in codec:
                raise ValueError('Invalid hanging-entity direction')
            facing = codec[int(numeric)]
        except (ValueError, TypeError):
            facing = str(value).strip('"\'')
            if facing not in codec.values():
                raise ValueError(f'Invalid {entity_id} {source_key}: {value}') from None
        output_codec = PAINTING_DIRECTIONS if painting else ENTITY_DIRECTIONS
        if facing not in output_codec.values():
            raise ValueError('Painting facing must be horizontal')
        encoded = {direction: code for code, direction in output_codec.items()}[facing]
        fields.pop(source_key)
        if painting:
            fields.pop('Facing', None)
        fields[key] = str(encoded) + 'b' if raw else encoded
    return render_fields(fields) if raw else fields
