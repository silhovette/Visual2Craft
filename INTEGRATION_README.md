# Visual2Craft Prompt Engineering v2.0

These prompt assets are integrated into the existing Visual2Craft Qt Quick one-call JSON scene inference flow.

- `01_RECONSTRUCTION_PROMPT.txt` replaces the reconstruction instructions currently in `video2pack.py`.
- `02_BLOCK_KNOWLEDGE.txt` replaces `BLOCK_KNOWLEDGE` in `block_rules.py`.
- `03_USER_HINTS_WRAPPER.txt` is used only if Building Hints are entered.
- `04_FRAME_WRAPPER.txt` precedes every sampled frame image.
- `00_FULL_MODEL_PROMPT.txt` concatenates the first two, exactly once.
- `05_IMPLEMENTATION_NOTES.txt` documents the compiler implications: block registry/state validation, mask preservation, and sampled-video text.

The runtime now loads `01_RECONSTRUCTION_PROMPT.txt`, `02_BLOCK_KNOWLEDGE.txt`,
`03_USER_HINTS_WRAPPER.txt`, and `04_FRAME_WRAPPER.txt` beside `video2pack.py`.
`vanilla_blocks_26_3.txt` is retained as the Java 26.3 reference registry;
compiler ID validation uses valid Minecraft identifier syntax so version-specific
or newly added placeable IDs such as `minecraft:chain` are not blocked.
State syntax is checked for malformed or duplicate entries while unknown
vanilla properties remain pass-through, so properties such as
`minecraft:cave_vines[berries=true]` do not stop generation.

The scene contract also supports an optional `entities` array for evidenced
placeable objects. The compiler emits tagged `/summon` commands for armor
stands, paintings, item frames, glow item frames, and other entity IDs, then
removes only those tagged entities during undo.
Confirmed Light/Barrier operations are also protected from unknown/preserve mask
subtraction during datapack planning.

**Behavioral promise vs guarantee:** The prompts instruct the model to retain text-confirmed Light/Barrier blocks in the final scene. A deterministic guarantee cannot come from prompt engineering alone while the existing mask-subtraction and whitelist validation code remains unchanged.
