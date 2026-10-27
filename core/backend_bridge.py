"""Thread-safe Qt/QML adapter for the unmodified 9f035bee core.

Only this module knows about Qt. All OpenAI/video inference stays in the
package's video2pack module.
"""
from __future__ import annotations

import multiprocessing as mp
import os
from pathlib import Path
import queue
import shutil
import tempfile
import threading
import time
from typing import Any

from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from .chatgpt_auth import ChatGPTAuth
from .generation_runtime import (available_output, commit_output, generation_worker,
                                  output_snapshot, validate_output_path)
from .video2pack import DEFAULT_FRAMES, MAX_FRAMES
from .live_scene import BlockGeometry, MAX_RENDER_BLOCKS, scene_blocks

GAME_COMMANDS = ('/reload', '/function vidbuild:check', '/function vidbuild:build', '/function vidbuild:undo')


class StudioBridge(QObject):
    videoChanged = Signal()
    outputChanged = Signal()
    accountsChanged = Signal()
    modelsChanged = Signal()
    busyChanged = Signal()
    statusChanged = Signal()
    stageChanged = Signal()
    elapsedChanged = Signal()
    resultChanged = Signal()
    sceneChanged = Signal()
    sceneStatusChanged = Signal()
    toast = Signal(str)
    # Emitting from worker threads transfers payloads to the Qt GUI thread.
    _backgroundFinished = Signal(object)

    def __init__(self, *, video: str | None = None, output: str | None = None, parent=None):
        super().__init__(parent)
        self.auth = ChatGPTAuth()
        self._video = ''
        self._auto_output = output is None
        download_dir = Path.home() / 'Downloads'
        if not download_dir.is_dir():
            download_dir = Path.home()
        self._output = output or available_output('', download_dir)
        self._account_ids = []
        self._accounts = []
        self._account_index = -1
        self._model_ids = []
        self._models = []
        self._model_index = -1
        self._status = 'Connect an account, select a video, then generate your Data Pack.'
        self._stage = 'IDLE'
        self._busy_kind = ''
        self._elapsed = 0
        self._started_at = 0.0
        self._result_path = ''
        self._last_summary = None
        self._process = None
        self._messages = None
        self._tmp = None
        self._destination = None
        self._destination_snapshot = None
        self._received_terminal = False
        self._empty_polls = 0
        self._closing = False
        self._scene_status = 'Waiting for a validated building scene.'
        self._scene_version = 0
        self._block_count = 0
        self._entity_count = 0
        self._geometry = BlockGeometry(self)
        self._animation_items = []
        self._animation_blocks = {}
        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(24)
        self._animation_timer.timeout.connect(self._animate_scene_batch)
        self._backgroundFinished.connect(self._on_background_finished)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._poll_generation)
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(500)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        self._refresh_accounts()
        if video:
            self.setVideo(video)

    @Property(str, notify=videoChanged)
    def videoUrl(self):
        return QUrl.fromLocalFile(self._video).toString() if self._video else ''

    @Property(str, notify=videoChanged)
    def videoName(self):
        return Path(self._video).name if self._video else ''

    @Property(str, notify=videoChanged)
    def videoPath(self):
        return self._video

    @Property(bool, notify=videoChanged)
    def hasVideo(self):
        return bool(self._video)

    @Property(str, notify=outputChanged)
    def outputPath(self):
        return self._output

    @Property('QVariantList', notify=accountsChanged)
    def accounts(self):
        return self._accounts

    @Property(int, notify=accountsChanged)
    def accountIndex(self):
        return self._account_index

    @Property(str, notify=accountsChanged)
    def accountCaption(self):
        return self._accounts[self._account_index] if self._account_index >= 0 else 'Not connected'

    @Property('QVariantList', notify=modelsChanged)
    def models(self):
        return self._models

    @Property(int, notify=modelsChanged)
    def modelIndex(self):
        return self._model_index

    @Property(str, notify=statusChanged)
    def status(self):
        return self._status

    @Property(str, notify=stageChanged)
    def stage(self):
        return self._stage

    @Property(bool, notify=busyChanged)
    def busy(self):
        return bool(self._busy_kind)

    @Property(bool, notify=busyChanged)
    def generating(self):
        return self._busy_kind == 'generate'

    @Property(bool, notify=busyChanged)
    def canBrowseVideo(self):
        """Local video selection remains available during auth/model refresh."""
        return self._busy_kind != 'generate'

    @Property(int, notify=elapsedChanged)
    def elapsed(self):
        return self._elapsed

    @Property(str, notify=resultChanged)
    def resultPath(self):
        return self._result_path

    @Property(QObject, constant=True)
    def blockGeometry(self):
        return self._geometry

    @Property(int, notify=sceneChanged)
    def sceneVersion(self):
        return self._scene_version

    @Property(int, notify=sceneChanged)
    def blockCount(self):
        return self._block_count

    @Property(int, notify=sceneChanged)
    def entityCount(self):
        return self._entity_count

    @Property(str, notify=sceneStatusChanged)
    def sceneStatus(self):
        return self._scene_status

    @Property(str, constant=True)
    def maxFrames(self):
        return str(MAX_FRAMES)

    @Property(int, constant=True)
    def defaultFrames(self):
        return DEFAULT_FRAMES

    def _set_status(self, message: str):
        self._status = str(message)
        self.statusChanged.emit()

    def _set_stage(self, stage: str):
        if self._stage != stage:
            self._stage = stage
            self.stageChanged.emit()

    def _set_busy(self, kind: str):
        self._busy_kind = kind
        self.busyChanged.emit()
        if kind == 'generate':
            self._started_at = time.monotonic()
            self._elapsed = 0
            self.elapsedChanged.emit()
            self._elapsed_timer.start()
        else:
            self._elapsed_timer.stop()

    def _set_scene_status(self, status: str):
        status = str(status)
        if self._scene_status != status:
            self._scene_status = status
            self.sceneStatusChanged.emit()

    def _clear_scene(self, status: str = 'No confirmed structure yet. The live scene is empty.'):
        self._animation_timer.stop()
        self._animation_items = []
        self._animation_blocks = {}
        self._geometry.update_blocks({})
        self._block_count = 0
        self._entity_count = 0
        self._scene_version += 1
        self._set_scene_status(status)
        self.sceneChanged.emit()

    def _apply_scene(self, scene: dict[str, Any]):
        """Apply only a validated, compiler-ready scene in the GUI thread."""
        if self._closing:
            return
        try:
            blocks = scene_blocks(scene, limit=MAX_RENDER_BLOCKS)
        except Exception as exc:
            self._clear_scene(f'Live preview unavailable: {exc}')
            return
        self._animation_timer.stop()
        # The model supplied one validated final scene. Reveal that real
        # structure in deterministic, bounded batches; no coordinates are
        # invented while the model is still producing JSON.
        self._animation_items = sorted(blocks.items(), key=lambda item: (item[0][1], item[0][2], item[0][0]))
        self._animation_blocks = {}
        self._geometry.update_blocks({})
        self._block_count = 0
        self._entity_count = len(scene.get('entities', []))
        self._scene_version += 1
        special = sum(1 for op in scene.get('ops', [])
                      if op.get('action') == 'place' and op.get('confidence') == 'confirmed'
                      and str(op.get('block', '')).split('[', 1)[0]
                      in ('minecraft:light', 'minecraft:barrier', 'minecraft:structure_void'))
        note = f' · {self._entity_count} entities held as datapack-only data' if self._entity_count else ''
        if special:
            note += f' · {special} special blocks'
        self._set_scene_status(f'Building validated scene · 0/{len(blocks):,} blocks{note}')
        self.sceneChanged.emit()
        if self._animation_items:
            self._animation_timer.start()

    def _animate_scene_batch(self):
        if not self._animation_items:
            self._animation_timer.stop()
            return
        # Large scenes should be meshed once rather than rebuilding hundreds
        # of progressively larger meshes just to animate their arrival.
        batch_size = (len(self._animation_items) if len(self._animation_items) > 120_000
                      else max(256, min(4_000, max(1, len(self._animation_items) // 28))))
        for point, block in self._animation_items[:batch_size]:
            self._animation_blocks[point] = block
        del self._animation_items[:batch_size]
        self._geometry.update_blocks(self._animation_blocks)
        self._block_count = len(self._animation_blocks)
        self._scene_version += 1
        if self._animation_items:
            self._set_scene_status(f'Building validated scene · {self._block_count:,} blocks…')
        else:
            self._animation_timer.stop()
            self._set_scene_status(f'Validated scene · {self._block_count:,} visible blocks')
        self.sceneChanged.emit()

    def _tick_elapsed(self):
        seconds = int(time.monotonic() - self._started_at)
        if seconds != self._elapsed:
            self._elapsed = seconds
            self.elapsedChanged.emit()

    @Slot()
    def browseVideo(self):
        if self.generating:
            return
        path, _ = QFileDialog.getOpenFileName(None, 'Choose construction video', str(Path.home()),
                        'Video files (*.mp4 *.mov *.mkv *.avi *.webm);;All files (*)')
        if path:
            self.setVideo(path)

    @Slot(str)
    def setVideo(self, path):
        if self.generating:
            return
        candidate = Path(path).expanduser()
        if not candidate.is_file():
            self._show_error('Invalid video', 'Select an existing video file.')
            return
        self._video = str(candidate.absolute())
        self.videoChanged.emit()
        self._clear_scene('Ready to construct; the live scene is empty.')
        if self._auto_output:
            self._output = available_output(self._video, Path(self._output).parent)
            self.outputChanged.emit()
        self._set_status(f'Ready to sample frames from {candidate.name}.')
        self._set_stage('READY')

    @Slot(str)
    def importVideoUrl(self, value):
        url = QUrl(value)
        self.setVideo(url.toLocalFile() if url.isLocalFile() else value)

    @Slot()
    def clearVideo(self):
        if self.generating:
            return
        self._video = ''
        self.videoChanged.emit()
        self._clear_scene()
        self._set_status('Video cleared. Choose a new construction video.')
        self._set_stage('IDLE')

    @Slot()
    def browseOutput(self):
        if self.busy:
            return
        path, _ = QFileDialog.getSaveFileName(None, 'Save Data Pack ZIP', self._output, 'ZIP archive (*.zip)')
        if path:
            self._output = path if path.lower().endswith('.zip') else path + '.zip'
            self._auto_output = False
            self.outputChanged.emit()

    @Slot(str)
    def updateOutput(self, path):
        if path != self._output:
            self._output = path
            self._auto_output = False
            self.outputChanged.emit()

    @Slot(str)
    def copy(self, value):
        QApplication.clipboard().setText(value)
        self.toast.emit('Copied to clipboard')

    @Slot()
    def openOutputFolder(self):
        if not self._result_path:
            return
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._result_path).parent)))

    @Slot()
    def openUsage(self):
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl('https://chatgpt.com/#settings/Usage'))

    def _refresh_accounts(self):
        entries = self.auth.accounts()
        self._account_ids = [a.client_id for a in entries]
        self._accounts = [a.email or 'ChatGPT account' for a in entries]
        selected = self.auth.selected()
        self._account_index = (self._account_ids.index(selected.client_id)
                               if selected and selected.client_id in self._account_ids else -1)
        self.accountsChanged.emit()

    def _clear_models(self):
        self._model_ids = []
        self._models = []
        self._model_index = -1
        self.modelsChanged.emit()

    def _start_auth_job(self, label, operation):
        if self.busy:
            return
        self._set_busy('auth')
        self._set_status(label)

        def task():
            try:
                outcome = (True, operation())
            except Exception as exc:
                outcome = (False, f'{type(exc).__name__}: {exc}')
            self._backgroundFinished.emit(outcome)
        threading.Thread(target=task, name='visual2craft-auth', daemon=True).start()

    def _on_background_finished(self, outcome):
        if self._closing:
            return
        ok, value = outcome
        self._set_busy('')
        if ok:
            try:
                self._refresh_accounts()
                self._load_models(value)
            except Exception as exc:
                self._show_error('Model list error', str(exc))
                return
            self._set_status(f'{len(self._models)} models available · {self.accountCaption}.')
            self.toast.emit('ChatGPT models updated')
        else:
            self._set_status('Account connection failed. Check details.')
            self._show_error('ChatGPT connection', str(value))

    def _load_models(self, models):
        self._models = [f'{title}   ·   {slug}' for title, slug in models]
        self._model_ids = [slug for title, slug in models]
        # Reproduce the old version's gpt-6 preference exactly.
        self._model_index = next((i for i, slug in enumerate(self._model_ids)
                                  if 'gpt-6' in slug.lower()), 0 if models else -1)
        self.modelsChanged.emit()

    @Slot()
    def signIn(self):
        self._start_auth_job('Opening your browser for authorization…',
                             lambda: (self.auth.sign_in(add_account=False), self.auth.models())[1])

    @Slot()
    def addAccount(self):
        self._start_auth_job('Opening your browser to add an account…',
                             lambda: (self.auth.sign_in(add_account=True), self.auth.models())[1])

    @Slot()
    def refreshModels(self):
        self._start_auth_job('Refreshing models from your ChatGPT account…', self.auth.models)

    @Slot(int)
    def chooseAccount(self, index):
        if self.busy or index == self._account_index:
            return
        if not 0 <= index < len(self._account_ids):
            return
        try:
            self.auth.select(self._account_ids[index])
            self._refresh_accounts()
            self._clear_models()
            self.refreshModels()
        except Exception as exc:
            self._show_error('Account switch failed', str(exc))

    @Slot(int)
    def chooseModel(self, index):
        if 0 <= index < len(self._model_ids):
            self._model_index = index
            self.modelsChanged.emit()

    @Slot()
    def removeAccount(self):
        if self.busy or self._account_index < 0:
            return
        name = self.accountCaption
        if QMessageBox.question(None, 'Delete saved account',
                f'Delete the locally stored credentials for {name}?\n\n'
                'You can sign back in later.', QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            self.auth.delete_account(self._account_ids[self._account_index])
            self._refresh_accounts()
            self._clear_models()
            self._set_status('Saved account removed.')
            self.toast.emit('Account removed')
        except Exception as exc:
            self._show_error('Delete failed', str(exc))

    def _show_error(self, title, message):
        QMessageBox.critical(None, title, message)

    @Slot(str, int, str, str, int, str, str)
    def generate(self, provider, model_index, api_model, api_key, frames, hints, output):
        if self.busy:
            return
        try:
            if not self._video or not Path(self._video).is_file():
                raise ValueError('Select a construction video first.')
            if not (2 <= frames <= MAX_FRAMES):
                raise ValueError(f'Sample frames must be between 2 and {MAX_FRAMES}.')
            if len(hints) > 8192:
                raise ValueError('Building hints are limited to 8192 characters.')
            if provider == 'chatgpt':
                if not 0 <= model_index < len(self._model_ids):
                    raise ValueError('Sign in with ChatGPT and refresh models first.')
                model = self._model_ids[model_index]
            elif provider == 'api':
                if not api_key.strip():
                    raise ValueError('Enter an API key or switch to ChatGPT Plan.')
                model = api_model.strip()
                if not model:
                    raise ValueError('Choose an API model name.')
            else:
                raise ValueError('Unknown authentication mode.')
            dest = validate_output_path(output)
            snap = output_snapshot(dest)
            if snap is not None:
                if QMessageBox.question(None, 'Replace existing ZIP?',
                    f'This output already exists:\n{dest}\n\nReplace it after successful generation?',
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                    return
            self._tmp = Path(tempfile.mkdtemp(prefix='.visual2craft-', dir=str(dest.parent)))
            params = dict(video=self._video, out=str(self._tmp / 'generated.zip'),
                frames=int(frames), auth_mode=provider, model=model, building_hints=hints)
            if provider == 'api':
                params['api_key'] = api_key
            self._messages = mp.get_context('spawn').Queue()
            self._process = mp.get_context('spawn').Process(
                target=generation_worker, args=(params, self._messages),
                name='Visual2Craft-Inference', daemon=True)
            self._process.start()
            self._destination = str(dest)
            self._destination_snapshot = snap
            self._received_terminal = False
            self._empty_polls = 0
            self._result_path = ''
            self.resultChanged.emit()
            self._clear_scene('Analyzing video; waiting for the first validated scene…')
            self._set_busy('generate')
            self._set_stage('SAMPLING')
            self._set_status('Sampling and filtering frames locally…')
            self._poll_timer.start()
        except Exception as exc:
            self._cleanup_generation()
            self._show_error('Unable to generate', str(exc))

    def _poll_generation(self):
        if self._messages is None:
            return
        for _ in range(120):  # bound work per UI tick
            try:
                kind, value = self._messages.get_nowait()
            except queue.Empty:
                break
            except (EOFError, OSError, ValueError):
                break
            if kind == 'progress':
                value = str(value)
                if 'Extracted' in value or 'invoking' in value:
                    self._set_stage('RECONSTRUCTING')
                elif 'Writing Data Pack' in value:
                    self._set_stage('EXPORTING')
                self._set_status(value)
                if 'Receiving building scene' in value:
                    self._set_scene_status('Receiving model scene; waiting for complete validated structure…')
            elif kind == 'scene':
                self._apply_scene(value)
            elif kind == 'result':
                self._received_terminal = True
                self._finish_success(value)
                return
            elif kind == 'error':
                self._received_terminal = True
                self._finish_failure(str(value))
                return
        if self._process is not None and not self._process.is_alive():
            # Child's queue feeder may flush slightly after the process exits.
            self._empty_polls += 1
            if self._empty_polls >= 15:
                code = self._process.exitcode
                self._finish_failure(f'Generation worker exited without a result (exit code {code}).')

    def _finish_success(self, summary: dict):
        try:
            saved = commit_output(summary['zip'], self._destination, self._destination_snapshot)
        except Exception as exc:
            self._finish_failure(str(exc))
            return
        live_scene = summary.get('_live_scene')
        if isinstance(live_scene, dict):
            self._apply_scene(live_scene)
        self._last_summary = summary
        self._result_path = saved
        self.resultChanged.emit()
        blocks = summary.get('commands', '?')
        preserved = summary.get('skipped_regions', 0)
        note = f' · {preserved} preserved unknown regions' if preserved else ''
        self._cleanup_generation()
        self._set_stage('COMPLETE')
        self._set_status(f'Generated {blocks} block commands{note}. ZIP ready.')
        self.toast.emit('Data Pack ZIP created')

    def _finish_failure(self, message):
        self._cleanup_generation()
        self._clear_scene('Generation failed; no validated building is available.')
        self._set_stage('FAILED')
        self._set_status('Generation failed. The original output ZIP was not modified.')
        self._show_error('Generation failed', message)

    @Slot()
    def cancelGeneration(self):
        if self._busy_kind != 'generate':
            return
        # Qt/UI is not blocked waiting for model API completion.
        self._cleanup_generation()
        self._clear_scene('Generation canceled; no live structure is retained.')
        self._set_stage('CANCELED')
        self._set_status('Generation canceled; temporary output removed. Submitted API usage may still count.')
        self.toast.emit('Generation canceled')

    def _cleanup_generation(self):
        self._poll_timer.stop()
        self._elapsed_timer.stop()
        if self._process is not None:
            try:
                if self._process.is_alive():
                    self._process.terminate()
                self._process.join(timeout=0.15)
                if not self._process.is_alive():
                    self._process.close()
            except (AssertionError, ValueError, OSError):
                pass
            self._process = None
        if self._messages is not None:
            try:
                self._messages.close()
                self._messages.cancel_join_thread()
            except (OSError, ValueError):
                pass
            self._messages = None
        if self._tmp:
            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = None
        self._destination = None
        self._destination_snapshot = None
        if self._busy_kind == 'generate':
            self._set_busy('')

    @Slot()
    def shutdown(self):
        self._closing = True
        if self._busy_kind == 'generate':
            self._cleanup_generation()
