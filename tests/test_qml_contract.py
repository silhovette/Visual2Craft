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
    def test_original_core_is_exactly_pinned(self):
        hashes = {
            'video2pack.py': '37412d8afaa275d764d0a9789a0fd579ab66763f6c90273359deff89a29fad5a',
            'block_rules.py': 'f3deac3daa677fca9bd6b51ae13a8c3918ae63165b3d3197797afba1e867c69e',
            'chatgpt_auth.py': 'efc92ecd2fa0b300c4085b64b29cf6458c882a3c165be6859d9d17256a295c0e',
        }
        for filename, sha in hashes.items():
            with self.subTest(filename=filename):
                self.assertEqual(hashlib.sha256((ROOT / filename).read_bytes()).hexdigest(), sha)

    def test_qml_assets_exist_and_frontend_does_not_import_tkinter(self):
        for relative in ['qml/Main.qml', 'qml/components/StudioCard.qml',
                         'qml/components/StudioButton.qml', 'qml/components/StudioField.qml',
                         'qml/components/StudioCombo.qml', 'assets/logo.png',
                         'assets/scenery_2560.jpg']:
            self.assertTrue((ROOT / relative).is_file(), relative)
        for name in ('app.py', 'backend_bridge.py', 'generation_runtime.py'):
            tree = ast.parse((ROOT / name).read_text())
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
