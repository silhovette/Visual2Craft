"""Low-cost packaging/static frontend checks. Runtime QML is checked if Qt is installed."""
import ast
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UIContractTests(unittest.TestCase):
    def test_auth_source_is_pinned_and_core_keeps_offline_behavior(self):
        # Reconstruction/geometry are maintained code, not immutable archives.
        # Test their public behavior; retain the existing authentication check.
        hashes = {
            'core/chatgpt_auth.py': 'efc92ecd2fa0b300c4085b64b29cf6458c882a3c165be6859d9d17256a295c0e',
        }
        for filename, sha in hashes.items():
            with self.subTest(filename=filename):
                self.assertEqual(hashlib.sha256((ROOT / filename).read_bytes()).hexdigest(), sha)
        from core.video2pack import validate_scene, make_commands, make_undo_commands
        from core.live_scene import scene_blocks
        source = {'size': [3, 2, 4], 'base_y': 1, 'coordinate_system': 'facade', 'ops': [
            {'block': 'minecraft:stone', 'from': [0, 0, 0], 'to': [2, 0, 0]},
            {'block': 'minecraft:oak_stairs[facing=north,half=top]', 'from': [2, 1, 1], 'to': [2, 1, 1]},
        ]}
        validate_scene(source)
        blocks = scene_blocks(source)
        self.assertIn((0, 0, 3), blocks)
        self.assertIn('facing=south', blocks[(2, 1, 2)])
        self.assertTrue(any('~2 ~0 ~2 minecraft:oak_stairs' in line for line in make_commands(source)))
        self.assertTrue(any('replace minecraft:stone' in line for line in make_undo_commands(source)))

    def test_qml_assets_exist_and_frontend_does_not_import_tkinter(self):
        for relative in ['qml/Main.qml', 'qml/components/StudioCard.qml',
                         'qml/components/StudioButton.qml', 'qml/components/StudioField.qml',
                         'qml/components/StudioCombo.qml', 'assets/scenery_2560.jpg',
                         'assets/visual2craft-logo.png', 'assets/visual2craft-logo (1).png',
                         'assets/visual2craft-logo (3).png', 'assets/visual2craft-logo (4).png',
                         'assets/visual2craft-logo (5).png', 'assets/visual2craft-logo (6).png',
                         'assets/visual2craft-logo (7).png', 'assets/visual2craft-logo (8).png',
                         'assets/visual2craft-logo (9).png', 'assets/visual2craft-logo (10).png']:
            self.assertTrue((ROOT / relative).is_file(), relative)
        qml = (ROOT / 'qml/Main.qml').read_text(encoding='utf-8')
        self.assertIn('property string splashLogoSource: chooseSplashLogo()', qml)
        self.assertIn('Math.random() < 0.01', qml)
        self.assertIn('source: window.splashLogoSource', qml)
        for name in ('app.py', 'core/backend_bridge.py', 'core/generation_runtime.py'):
            tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
            imports = [n.names[0].name for n in ast.walk(tree) if isinstance(n, ast.Import)]
            self.assertNotIn('tkinter', imports)

    def test_qml_loads_if_pyside6_is_installed(self):
        try:
            import PySide6  # noqa: F401
        except ImportError:
            self.skipTest('PySide6 unavailable in offline test environment')
        env = os.environ.copy()
        env['QT_QPA_PLATFORM'] = 'offscreen'
        p = subprocess.run([sys.executable, str(ROOT / 'app.py'), '--check-ui'],
                           cwd=ROOT, env=env, text=True, capture_output=True, timeout=25)
        self.assertEqual(p.returncode, 0, p.stdout + '\n' + p.stderr)


if __name__ == '__main__':
    unittest.main()
