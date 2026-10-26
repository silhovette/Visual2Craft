"""Pure Python generation runtime; no GUI dependencies or inference algorithm changes.

All inference and datapack logic remains in the archived old-version
video2pack module.
Qt runs this function in a spawned child process so cancellation is real.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile


def safe_filename(video: str) -> str:
    name = Path(video).stem.strip() or 'video_build'
    # Windows-reserved characters and legacy DOS device basenames.
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).rstrip('. ')
    if not name or name.upper().split('.')[0] in {
        'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
        *(f'LPT{i}' for i in range(1, 10))
    }:
        name = 'video_build'
    return name[:90]


def available_output(video: str, directory: str | Path) -> str:
    parent = Path(directory).expanduser()
    stem = safe_filename(video)
    candidate = parent / f'{stem}.zip'
    i = 2
    while candidate.exists():
        candidate = parent / f'{stem}_{i}.zip'
        i += 1
    return str(candidate)


def output_snapshot(path: str | Path):
    try:
        stat = Path(path).stat()
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    except FileNotFoundError:
        return None


def validate_output_path(path: str) -> Path:
    if not path.strip():
        raise ValueError('Choose an output ZIP path.')
    dest = Path(path).expanduser().absolute()
    if dest.suffix.lower() != '.zip':
        raise ValueError('Output path must end with .zip.')
    if not dest.parent.is_dir():
        raise ValueError('Output folder does not exist: ' + str(dest.parent))
    return dest


def commit_output(temp_zip: str, destination: str, expected_snapshot):
    """Preserve the destination if another program touched it during generation."""
    dest = validate_output_path(destination)
    if output_snapshot(dest) != expected_snapshot:
        raise FileExistsError('The output ZIP changed while generating. Select a new path before saving.')
    source = Path(temp_zip)
    if not source.is_file() or source.stat().st_size <= 0:
        raise RuntimeError('Temporary Data Pack ZIP was not generated.')
    # temp and destination must be in the same directory/volume for os.replace.
    os.replace(source, dest)
    return str(dest)


def generation_worker(params: dict, messages):
    """Top-level entrypoint required by Windows multiprocessing spawn."""
    try:
        from . import video2pack
        run = video2pack.run
        params = dict(params)
        if params.get('auth_mode') == 'chatgpt':
            from .chatgpt_auth import ChatGPTAuth
            params['access_token'] = ChatGPTAuth().access_token()
        # Keep the archived core's public API and source contract unchanged.
        # Wrapping its compiler lets us publish the exact validated scene only
        # after the same plan has successfully produced the ZIP.
        published_scene = None
        original_compile = video2pack.compile_datapack
        def compile_and_publish(scene, output, offset=(5, 0, 5)):
            nonlocal published_scene
            summary = original_compile(scene, output, offset=offset)
            published_scene = scene
            return summary
        video2pack.compile_datapack = compile_and_publish
        summary = run(**params,
                      progress=lambda message: messages.put(('progress', message)))
        if published_scene is not None:
            # Keep the Scene payload attached to the terminal result. A large
            # multiprocessing payload can otherwise overtake a preceding
            # queue item while its feeder thread is still serializing it.
            summary = dict(summary)
            summary['_live_scene'] = published_scene
        messages.put(('result', summary))
    except BaseException as exc:
        messages.put(('error', f'{type(exc).__name__}: {exc}'))
