import unittest
from unittest.mock import MagicMock
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from scrollferry.xiaoe import XiaoeBrowser, MenuNotReady


class MaterialMenuTest(unittest.TestCase):
    def browser(self):
        browser = XiaoeBrowser()
        browser.page = MagicMock()
        browser.editor_body = MagicMock()
        browser.click_material_menu = MagicMock()
        return browser

    def test_collapsed_menu_reopens_then_succeeds(self):
        browser = self.browser()
        dialog = MagicMock()
        browser.material_dialog = MagicMock(side_effect=[None, None, dialog])
        browser.click_material_menu.side_effect = [MenuNotReady('collapsed'), None]
        browser.open_materials(2)
        self.assertEqual(browser.editor_body.call_count, 2)
        self.assertEqual(browser.click_material_menu.call_count, 2)
        self.assertIs(browser.material, dialog)

    def test_late_dialog_is_reused_without_second_menu_click(self):
        browser = self.browser()
        dialog = MagicMock()
        browser.material_dialog = MagicMock(side_effect=[None, dialog])
        browser.click_material_menu.side_effect = PlaywrightTimeout('late')
        browser.open_materials()
        browser.click_material_menu.assert_called_once()
        self.assertIs(browser.material, dialog)

    def test_retry_is_bounded(self):
        browser = self.browser()
        browser.material_dialog = MagicMock(return_value=None)
        browser.click_material_menu.side_effect = MenuNotReady('collapsed')
        with self.assertRaisesRegex(RuntimeError, '重试 3 次'):
            browser.open_materials()
        self.assertEqual(browser.click_material_menu.call_count, 3)
        self.assertEqual(browser.page.wait_for_timeout.call_count, 2)

    def test_ambiguous_dialog_is_not_retried(self):
        browser = self.browser()
        browser.material_dialog = MagicMock(side_effect=ValueError('ambiguous'))
        with self.assertRaises(ValueError):
            browser.open_materials()
        browser.click_material_menu.assert_not_called()

    def test_submenu_activation_does_not_move_pointer(self):
        browser = XiaoeBrowser()
        parent, target = MagicMock(), MagicMock()
        browser.on_screen_text = MagicMock(side_effect=[parent, target])
        target.evaluate.return_value = True
        browser.click_material_menu()
        parent.hover.assert_called_once()
        target.evaluate.assert_called_once()
        target.click.assert_not_called()
        target.hover.assert_not_called()

    def test_submenu_collapse_before_activation_is_retryable(self):
        browser = XiaoeBrowser()
        target = MagicMock()
        target.evaluate.return_value = False
        browser.on_screen_text = MagicMock(return_value=target)
        with self.assertRaises(MenuNotReady):
            browser.click_material_menu()
