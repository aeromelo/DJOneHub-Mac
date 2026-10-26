import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('builder', Path(__file__).with_name('build.py'))
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class BuildTests(unittest.TestCase):
    def test_local_upstream_can_be_reused_without_mounting(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            upstream = root / 'upstream/djonehub'
            (upstream / 'bin').mkdir(parents=True)
            (upstream / 'bin/djonehub-macos').write_text('backend')
            target = root / 'target'
            target.mkdir()
            with patch.dict(os.environ, {'DJONEHUB_UPSTREAM_DIR': str(upstream.parent)}):
                self.assertTrue(builder.copy_upstream(target))
            self.assertEqual((target / 'djonehub/bin/djonehub-macos').read_text(), 'backend')

    def test_local_upstream_rejects_incomplete_tree(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            upstream = root / 'upstream/djonehub'
            upstream.mkdir(parents=True)
            target = root / 'target'
            target.mkdir()
            with patch.dict(os.environ, {'DJONEHUB_UPSTREAM_DIR': str(upstream.parent)}):
                with self.assertRaisesRegex(RuntimeError, 'djonehub-macos'):
                    builder.copy_upstream(target)


if __name__ == '__main__':
    unittest.main()
