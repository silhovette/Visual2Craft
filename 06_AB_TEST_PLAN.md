# V2C Prompt v2.0 — A/B Test Plan

Run the old and v2.0 prompts on the exact same sampled frames, model/version, authentication mode and optional hints, with no other changes. Compare actual Minecraft builds, not just valid JSON.

## Test video categories
1. Simple small house: footprint, height, entry and roof.
2. Multi-angle build: consistent coordinates and mirrored/repeated features.
3. Complex roof, slabs, stairs and stained glass panes: directional block states.
4. Unusual materials outside the old 140-block palette: correct vanilla IDs, no invented IDs.
5. Video with **readable explicit on-screen instruction** to place Light level 8 at a locatable position: verify exact light ID, level and coordinate appear in both JSON and .mcfunction; compare with frame text.
6. Visually illuminated but no explicit video text, invisible-collision visual, or user hint alone: **zero Light/Barrier placements**.
7. Explicit Barrier video instruction and later occlusion: preserve Barrier through final blueprint.
8. Occluded final walls/roof and local unknown areas: no overlap-induced loss of confirmed blocks.

## Scoring
- Major structure: footprint, height, silhouette, roof, openings (manual or voxel ground truth).
- Block identity and state correctness in visible regions.
- Repeated-pattern consistency; fewer unsupported invention errors.
- Precision/recall of placed blocks and IoU/voxel-F1 where ground truth available.
- Fraction of confirmed operations with legitimate frame evidence; invented citations = failure.
- Special invisible blocks: false positives must be zero in negative controls; true positives must survive validation, operation resolution and export.
- Unknown/preserve masks never erase confirmed positions.
- Validity and export: model JSON passes schema; compiler accepts IDs/states; Minecraft executes commands and builds intended results.
- Count errors and cost: output operation count, invalid state incidence, model token consumption, latency. Do not assume prompt gains without comparative evidence.

## Acceptance caveats
- Prompt-only rules do not guarantee strict Light/Barrier activation or persistence without deterministic video-text verification and downstream protection.
- The existing sampled-frame interface can miss textual instructions between frames; prompt tuning alone cannot recover unseen text.
- The compiler's block whitelist/state validator must be updated separately to truly enable all vanilla block IDs.
