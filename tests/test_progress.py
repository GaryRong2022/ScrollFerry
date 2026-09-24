import unittest
from unittest.mock import MagicMock, patch
from scrollferry.progress import ProgressView


class ProgressViewTest(unittest.TestCase):
    def view(self):
        view = ProgressView.__new__(ProgressView)
        view.cancelled = False
        view.last_stage = ''
        view.waiting = True
        for name in ('stage','count','bar','hint','log','window','cancel_button'):
            setattr(view, name, MagicMock())
        view.log.index.return_value = '2.0'
        return view

    def test_waiting_does_not_invent_percentage(self):
        view = self.view()
        view.update('等待后台', 0, 0)
        self.assertIn('暂无可核实', view.count.set.call_args.args[0])
        view.bar.__setitem__.assert_not_called()
        view.update('检查素材', 25, 100)
        view.bar.__setitem__.assert_called_with('value', 25)
        view.update('保存题目', 0, 0)
        view.bar.configure.assert_called_with(mode='indeterminate')

    def test_cancel_label_survives_queued_progress(self):
        view = self.view()
        view.cancelling()
        view.stage.reset_mock()
        view.update('旧进度', 10, 100)
        view.stage.set.assert_not_called()
        view.cancel_button.configure.assert_called_with(state='disabled')

    def test_close_stops_animation(self):
        view = self.view()
        view.timer = 'timer-1'
        view.close()
        view.window.after_cancel.assert_called_once_with('timer-1')
        view.bar.stop.assert_called_once()
        self.assertIsNone(view.timer)

    def test_completion_waits_for_confirmation_and_keeps_summary(self):
        view = self.view()
        view.started = 0
        view.scene_elapsed = 7.25
        view.close = MagicMock()
        view.clock = MagicMock()
        view.sea = MagicMock()
        view.scene_title, view.scene_subtitle = 1, 2
        view.draw_scene = MagicMock()
        confirm = MagicMock()
        view.finish('已识别 57 题。\n需要校对 2 题。', True, confirm)
        confirm.assert_not_called()
        view.window.destroy.assert_not_called()
        view.cancel_button.configure.assert_called_with(text='确定', state='normal', command=confirm)
        view.cancel_button.set_primary.assert_called_once()
        self.assertIn('需要校对 2 题', view.log.insert.call_args.args[1])
        view.draw_scene.assert_called_once()
        self.assertTrue(view.draw_scene.call_args.kwargs['arrived'])
        self.assertEqual(view.draw_scene.call_args.args[0],7.25)
        self.assertTrue(view.animation_frozen)
        view.cancel_button.configure.call_args.kwargs['command']()
        confirm.assert_called_once()

    def test_logo_animation_moves_gently_and_completion_is_still(self):
        from pathlib import Path
        from PIL import Image, ImageChops
        from scrollferry.ferry_animation import ferry_frame, prepare_ferry_logo
        with Image.open(Path(__file__).parents[1]/'scrollferry/assets/logo.png') as logo:
            logo = prepare_ferry_logo(logo)
            self.assertEqual(logo.getpixel((16,144))[3], 0)
            self.assertEqual(logo.getpixel((270,214))[3], 0)  # bow bubble
            self.assertEqual(logo.getpixel((58,230))[3], 0)  # attached cyan wave
            self.assertGreater(logo.getchannel('A').getextrema()[1], 240)
            first = ferry_frame(0, logo=logo).convert('RGB')
            moving = ferry_frame(2, logo=logo).convert('RGB')
            self.assertIsNotNone(ImageChops.difference(first,moving).getbbox())
            # Completed scenes use the saved frame time, not a fixed berth.
            complete = ferry_frame(7.25, True, logo=logo)
            self.assertEqual(complete.tobytes(), ferry_frame(7.25, True, logo=logo).tobytes())
            self.assertEqual(logo.getpixel((140,149))[3],255)

    def test_cancelling_freezes_scene_while_waiting_for_worker(self):
        view = self.view()
        view.started = view.changed = 0
        view.clock = MagicMock()
        view.draw_scene = MagicMock()
        view.cancelling()
        self.assertTrue(view.animation_frozen)
        view.tick()
        view.draw_scene.assert_not_called()
        view.window.after.assert_called_once()

    def test_boat_tracks_water_surface_throughout_travel(self):
        from scrollferry.ferry_animation import boat_pose, water_height
        for phase in (0,1,3,7,20):
            for x in (30,150,350,490):
                y, tilt = boat_pose(x,phase)
                self.assertAlmostEqual(y+25, water_height(x,phase))
                self.assertLessEqual(abs(tilt),2.5)

    def test_ferry_turns_at_edges_without_position_jump(self):
        from scrollferry.ferry_animation import travel_position
        self.assertEqual(travel_position(0,520),(66,1))
        self.assertEqual(travel_position(20,520),(454,-1))
        self.assertEqual(travel_position(40,520),(66,1))
        before, direction = travel_position(19.99,520)
        after, reverse = travel_position(20.01,520)
        self.assertAlmostEqual(before,after)
        self.assertEqual((direction,reverse),(1,-1))
        self.assertLess(travel_position(30,520)[0],after)

    def test_clouds_drift_independently_above_the_shore(self):
        from scrollferry.ferry_animation import drifting_clouds, sea_background
        a, b = drifting_clouds(520,0), drifting_clouds(520,5)
        self.assertNotEqual(a.tobytes(), b.tobytes())
        self.assertLess(a.getchannel('A').getbbox()[3],100)
        backdrop=sea_background(520)
        self.assertNotEqual(backdrop.getpixel((10,200)),backdrop.getpixel((10,400)))

    def test_animation_reuses_tk_image_instead_of_blanking_between_frames(self):
        from PIL import Image
        view = self.view()
        view.sea = MagicMock()
        view.sea.winfo_width.return_value = 520
        view.scene = 1
        view.logo_source = Image.new('RGBA',(10,10))
        with patch('scrollferry.progress.ImageTk.PhotoImage') as factory, \
                patch('scrollferry.ferry_animation.ferry_frame', return_value=Image.new('RGBA',(1040,480))) as render:
            photo = factory.return_value
            photo.width.return_value = 520
            photo.height.return_value = 138
            view.draw_scene(1)
            view.draw_scene(1.04)
            self.assertAlmostEqual(render.call_args.args[0], 18.2)
            factory.assert_called_once()
            view.sea.itemconfigure.assert_called_once()
            photo.paste.assert_called_once()
            self.assertEqual(photo.paste.call_args.args[0].mode,'RGB')
            self.assertIs(view.scene_photo,photo)
