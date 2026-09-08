import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from scrollferry.paths import user_data_dir, batch_runtime_dir
from scrollferry.browsers import browser_channels
from scrollferry.upload import prepare_upload, write_state


class DesktopTest(unittest.TestCase):
    def test_chrome_launch_failure_falls_back_to_edge(self):
        from scrollferry.xiaoe import XiaoeBrowser
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {'SCROLLFERRY_DATA_DIR': directory}), \
                patch('scrollferry.xiaoe.browser_channels', return_value=['chrome', 'msedge']), \
                patch('playwright.sync_api.sync_playwright') as factory:
            runtime = factory.return_value.start.return_value
            context = MagicMock()
            context.pages = [MagicMock()]
            runtime.chromium.launch_persistent_context.side_effect = [RuntimeError('not installed'), context]
            browser = XiaoeBrowser()
            browser.open(lambda *args: None)
            calls = runtime.chromium.launch_persistent_context.call_args_list
            self.assertEqual([call.kwargs['channel'] for call in calls], ['chrome', 'msedge'])
            self.assertNotEqual(calls[0].args[0], calls[1].args[0])
            self.assertEqual(browser.browser_name, 'Edge')
            browser.close()

    def test_browser_preference_and_fallback_order(self):
        for preferred, expected in [('msedge', ['msedge', 'chrome']),
                                    ('chrome', ['chrome', 'msedge']),
                                    (None, ['chrome', 'msedge'])]:
            with patch('scrollferry.browsers.default_channel', return_value=preferred):
                self.assertEqual(browser_channels(), expected)

    def test_windows_data_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'LOCALAPPDATA': directory}, clear=True), \
                    patch('scrollferry.paths.sys.platform', 'win32'):
                self.assertEqual(user_data_dir(), Path(directory)/'ScrollFerry')

    def test_legacy_receipts_migrate_without_resetting_saved_questions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch = root/'export'
            batch.mkdir()
            (batch/'stem.png').write_bytes(b'png')
            row = {'id':'Q0001', 'type':'solution', 'answer':'done', 'issues':[],
                   'images':[{'kind':'stem', 'filename':'stem.png'}]}
            (batch/'manifest.json').write_text(json.dumps([row]))
            (batch/'status.json').write_text('{"status":"completed"}')
            with patch.dict(os.environ, {'SCROLLFERRY_DATA_DIR': str(root/'user')}):
                state = prepare_upload(batch)
                state['questions'][0]['status'] = 'saved'
                state['images'][0]['status'] = 'uploaded'
                runtime = batch_runtime_dir(batch)
                # Recreate an old on-disk batch; new runtime receipt is absent.
                write_state(batch/'upload-queue.json', state)
                (runtime/'upload-queue.json').unlink()
                (runtime/'upload-assets').rename(batch/'upload-assets')
                legacy_bytes = (batch/'upload-queue.json').read_bytes()
                migrated = prepare_upload(batch)
                self.assertEqual(migrated['questions'][0]['status'], 'saved')
                self.assertEqual(migrated['images'][0]['status'], 'uploaded')
                self.assertEqual((batch/'upload-queue.json').read_bytes(), legacy_bytes)
                self.assertTrue((runtime/'upload-queue.json').is_file())
                self.assertTrue((runtime/'upload-assets'/state['images'][0]['upload_name']).is_file())
