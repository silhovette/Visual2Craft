# Visual2Craft — Qt Quick Edition

**From Construction Videos to Executable Minecraft Builds**

This edition migrates the **desktop frontend** from Tkinter to **PySide6 + Qt Quick / QML**. Its reconstruction backend is based on the archived `Visual2Craft-9f035beef44a4bcf76efa446946aac75cba87e9f.zip` you provided, with the documented standing-block grass behavior in undo.

- **Source of inference and rendering semantics:** old `video2pack.py`, `block_rules.py`, `chatgpt_auth.py`, `examples/`.
- **Visual reference only:** `main`'s `assets/logo.png` and `assets/scenery_2560.jpg`; reconstruction uses the reviewed Prompt Engineering v2.0 assets shipped beside `video2pack.py`.
- **Frontend:** `app.py`, `backend_bridge.py`, `generation_runtime.py`, `qml/Main.qml`, `qml/components/*.qml`.

## Run on Windows 11

1. Extract the ZIP fully to a writable folder. **Do not start from inside a ZIP preview.**
2. Install 64-bit Python **3.13** (preferred) from python.org; ensure the Windows `py` launcher is available.
3. Double-click **`START_WINDOWS.bat`**. The script creates a local `.venv`, installs dependencies, and opens the Qt Quick window.
4. Choose **ChatGPT Plan** and click **Sign in**, or use **API key** mode. Refresh available models and verify the exact model ID.
5. Choose a construction video (Browse, drag-drop, or Ctrl+O), set sample frames (2–1200), and choose an output ZIP.
6. Click **Generate Data Pack**. At completion, move the ZIP to `world/datapacks`, then run:

```mcfunction
/reload
/function vidbuild:check
/function vidbuild:build
/function vidbuild:undo
```

`/function vidbuild:undo` removes generated blocks except for the layer at `base_y - 1` (the player's standing block), where matching generated blocks are replaced with grass; it does **not** restore overwritten terrain. Back up the Minecraft world.

The first launch requires an internet connection to install dependencies; ChatGPT/OAuth inference also needs network access. Qt Multimedia preview depends on playable codecs on the target system. If the preview reports an unsupported format, try an H.264 MP4; this does not affect `video2pack.py`'s OpenCV frame extraction.

## Why this is smoother

Qt Quick renders textured background, controls, hover states, and video in a scenegraph (hardware accelerated where supported). Unlike Tkinter's Canvas/PIL design, the interface has **no repeated background screenshot/CPU blur, geometry-triggered background scaling, or full-window image reallocation**. Decorative motion is limited to short hover transitions and a single small active task indicator. The generation worker is a separate process, so long model calls do not occupy the Qt UI thread. Actual FPS still depends on GPU/graphics drivers and cannot be guaranteed without device testing.

The activity bar is **indeterminate**, on purpose: the original backend does not report per-frame/model-token completion percentages. It shows the true phase (`SAMPLING`, `RECONSTRUCTING`, `EXPORTING`) and elapsed time instead of pretending a fixed percentage is actual progress.

## Functional behavior

- Video preview: hardware-capable Qt Multimedia backend, play/pause, seek, change, clear.
- Multi-account ChatGPT sign-in: existing `ChatGPTAuth` and OS keyring; add/remove/select accounts and fetch server-listed models. Account credentials are **not stored in QML**.
- API mode: separately billed API key, same original inference path.
- Source video and frame sampling: old 9f035bee algorithms; model instructions use Prompt Engineering v2.0 (`01_RECONSTRUCTION_PROMPT.txt`, `02_BLOCK_KNOWLEDGE.txt`, and the user/frame wrappers).
- Scene coordinates use `base_y` as the player's standing/building baseline, so below-grade excavation and above-grade construction can coexist in one scene. Lava, magma blocks, and lava cauldrons are replaced with orange/yellow luminous solids.
- Output: write a temporary ZIP on the destination volume, then atomically replace only when the original destination has not changed. Confirmation is needed to overwrite an existing ZIP.
- Placeable entities: armor stands, paintings, item frames, glow item frames, and other explicitly evidenced `/summon` objects are emitted from the scene's `entities` array and tagged for scoped undo.
- Cancellation: terminates the local worker process; **does not guarantee refund or cancellation of a request already accepted remotely**.
- Commands: copy any `/reload`, `vidbuild:check`, `vidbuild:build`, `vidbuild:undo`; Ctrl+O to browse video, Ctrl+S to set output.
- Hints: optional, up to 8192 characters; preserved evidence and uncertainty rules.

## Code & tests

The CLI remains available unchanged:

```bash
python video2pack.py --scene examples/demo_house.json --out demo.zip
python -m pytest -q tests/test_generation_runtime.py tests/test_pack.py tests/test_special_blocks.py tests/test_video_frames.py tests/test_auth.py
```

To launch without the helper script (after installing `requirements.txt`):

```bash
python app.py
python app.py --video path/to/tutorial.mp4 --out output.zip
```

## Current verification status

- The old reconstruction, auth, frame-processing and pack tests run in the supplied offline environment (where their Python dependencies are present).
- The new process/ZIP safety tests run offline without Qt.
- Prompt v2.0 asset loading, hint/frame wrappers, and Light/Barrier mask protection are covered by the existing test suite.
- Block IDs are accepted when they use valid Minecraft identifier syntax, so registry additions and version-specific placeable blocks are not blocked; fluid-seal tagging remains conservative.
- Block-state validation checks syntax and duplicate keys without rejecting newer or less common vanilla properties such as `berries=true`.
- **Not verified on a running Windows/PySide6 GPU window here**: the build environment had no PySide6 installation and couldn't reach the package index to fetch it. You should run it on Windows to check codec/driver-specific behavior. This is a ready-to-try source project, not a claim of Windows UI performance benchmarking.
- The two original OAuth inference tests that import `openai` require the `openai` package. They were not runnable in this offline container, although the source is unmodified.

## Architecture

```text
app.py (QApplication + QQmlApplicationEngine)
   -> qml/Main.qml (Qt Quick UI, GPU-composited)
   -> backend_bridge.py (QObject properties / slots; Qt main thread)
     -> ChatGPTAuth (background thread for sign-in and model listing)
     -> multiprocessing child (generation_runtime.generation_worker)
       -> video2pack.run() (original 9f035bee version, unchanged)
          -> video_frames, infer_scene, validate_scene, compile_datapack
       -> temporary ZIP
     -> safe atomic commit of destination ZIP
```

The QML frontend never directly imports `cv2`, OpenAI, or Tkinter.
