import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from scrollferry.app import App, reveal_offset, wheel_pixels, touchpad_pixels


class ScrollingTest(unittest.TestCase):
    def test_continuous_view_drag_targets_second_page_and_ignores_gap(self):
        app = App.__new__(App)
        app.mode = MagicMock()
        app.mode.get.return_value = 'crop'
        app.project = {'source':'paper.pdf'}
        app.scale = 1.2
        app.pages = [{'width':500,'height':600}]*2
        app.page_offsets = [0,740]
        app.canvas = MagicMock()
        app.canvas.canvasx.side_effect = lambda x:x
        app.canvas.canvasy.side_effect = lambda y:y+700
        app.start_drag(SimpleNamespace(x=60,y=100))
        self.assertEqual(app.drag_page,1)
        self.assertEqual(app.origin,(60,800))
        app.start_drag(SimpleNamespace(x=60,y=30))
        self.assertIsNone(app.origin)

    def test_tk9_signed_precise_deltas(self):
        self.assertEqual(touchpad_pixels(0xfffd), (0,3))
        self.assertEqual(touchpad_pixels((4 << 16) | 0xfffe), (-4,2))
        self.assertEqual(touchpad_pixels(-65536), (1,0))
        self.assertEqual(touchpad_pixels(0), (0,0))

    def test_wheel_routes_to_pointer_region_not_focused_widget(self):
        app = App.__new__(App)
        app.root = MagicMock()
        app.root.winfo_pointerxy.return_value = (100,200)
        canvas = SimpleNamespace(_scroll_target=None, master=None)
        child = SimpleNamespace(master=canvas)
        canvas._scroll_target = (canvas,'y')
        app.root.winfo_containing.return_value = child
        app.scroll_content = MagicMock(return_value='break')
        event = SimpleNamespace(widget=app.root, delta=-3, state=0)
        self.assertEqual(app.route_wheel(event),'break')
        app.scroll_content.assert_called_once_with(canvas,event,'y')
        event.state = 1
        app.route_wheel(event)
        app.scroll_content.assert_called_with(canvas,event,'x')

    def test_small_wheel_steps_across_platforms(self):
        with patch('scrollferry.app.sys.platform', 'darwin'):
            self.assertEqual(wheel_pixels(SimpleNamespace(delta=1)), -2)
            self.assertEqual(wheel_pixels(SimpleNamespace(delta=-100)), 36)
        with patch('scrollferry.app.sys.platform', 'win32'):
            self.assertEqual(wheel_pixels(SimpleNamespace(delta=-120)), 18)
            self.assertEqual(wheel_pixels(SimpleNamespace(delta=30)), -4.5)
        self.assertEqual(wheel_pixels(SimpleNamespace(num=4)), -18)
        self.assertEqual(wheel_pixels(SimpleNamespace(num=5)), 18)
        self.assertEqual(wheel_pixels(SimpleNamespace(delta=0)), 0)

    def test_crop_fits_or_starts_within_view(self):
        for start, end, viewport, total in [(700,800,300,1000), (0,100,300,1000), (950,990,300,1000)]:
            offset = reveal_offset(start,end,viewport,total)*total
            self.assertLessEqual(offset, start)
            self.assertGreaterEqual(offset+viewport, end)
            self.assertLessEqual(offset, total-viewport)
        self.assertEqual(reveal_offset(400,950,300,1000), .376)
        self.assertEqual(reveal_offset(50,100,1000,500), 0)

    def test_select_reveals_first_region_after_rendering(self):
        app = App.__new__(App)
        app.tree = MagicMock()
        app.tree.selection.return_value = ['q0a0']
        for attr in ('answer','reviewed','question_type','issue_text'):
            setattr(app, attr, MagicMock())
        region = {'page':16, 'box':[20,600,500,700]}
        app.selected = lambda: ({'answer':'B','reviewed':False,'type':'single_choice'}, {'regions':[region]})
        calls = []
        app.show_page = lambda: calls.append(('render',app.page))
        app.reveal_region = lambda r: calls.append(('reveal',r))
        app.select()
        self.assertEqual(calls, [('render',16),('reveal',region)])

    def test_canvas_motion_is_pixels_not_viewport_units(self):
        app = App.__new__(App)
        target = MagicMock()
        target.bbox.return_value = (0,0,800,2000)
        target.yview.return_value = (.25,.5)
        with patch('scrollferry.app.sys.platform','win32'):
            app.scroll_content(target, SimpleNamespace(delta=-120))
        target.yview_moveto.assert_called_once_with(.259)
        target.yview_scroll.assert_not_called()


if __name__ == '__main__':
    unittest.main()
