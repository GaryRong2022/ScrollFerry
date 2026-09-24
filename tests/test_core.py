import tempfile
import unittest
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen.canvas import Canvas

from scrollferry.core import crop_region, detect, export, trim_content


class PipelineTest(unittest.TestCase):
    def test_answer_and_explanation_share_tight_bounds_and_export(self):
        from copy import deepcopy
        from unittest.mock import patch
        from PIL import Image, ImageDraw
        from scrollferry.core import tighten_regions, render_asset
        page = Image.new('RGB', (200, 160), 'white')
        draw = ImageDraw.Draw(page)
        draw.rectangle((40, 50, 100, 90), fill='black')
        draw.point((110, 40), fill='black')  # Isolated formula mark must survive.
        region = {'page':0, 'box':[0,0,100,80], 'masks':[]}
        assets = [{'kind':kind, 'regions':[deepcopy(region)]}
                  for kind in ('stem', 'option_A', 'answer', 'explanation')]
        project = {'questions':[{'reviewed':True, 'assets':assets}]}
        with patch('scrollferry.core.render_page', return_value=page):
            tighten_regions(project)
            self.assertEqual(assets[0]['regions'][0]['box'], [18,18,57.5,47.5])
            for asset in assets:
                self.assertEqual(asset['regions'][0]['box'], assets[0]['regions'][0]['box'])
                self.assertEqual(render_asset(project,asset).tobytes(), render_asset(project,assets[0]).tobytes())
            self.assertFalse(project['questions'][0]['reviewed'])

    def test_tight_crop_preserves_small_formula_marks(self):
        from PIL import Image, ImageDraw
        image = Image.new('RGB', (300,200), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((200,100,280,180), fill=(240,240,240))
        draw.rectangle((80,60,100,90), fill='black')
        draw.point((110,50), fill='black')
        result = trim_content(image)
        self.assertEqual(result.size, (41,51))
        self.assertEqual(result.getpixel((35,5)), (0,0,0))
        self.assertEqual(result.getpixel((0,0)), (255,255,255))

    def test_blank_crop_does_not_disappear(self):
        from PIL import Image
        self.assertEqual(trim_content(Image.new('RGB',(30,20),'white')).size, (38,28))

    def test_five_option_mixed_paper(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'five.pdf'
            pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
            canvas = Canvas(str(path), pagesize=(400, 600))
            canvas.setFont('STSong-Light', 14)
            lines = ['一、单选题', '1. 选择正确答案', 'A. 第一项', 'B. 第二项',
                     'C. 第三项', 'D. 第四项', 'E. 第五项', '【答案】 E', '【解析】 第五项正确']
            for i, line in enumerate(lines):
                canvas.drawString(30, 550-i*48, line)
            canvas.save()
            project = detect(path)
            question = project['questions'][0]
            self.assertFalse(question['issues'])
            self.assertEqual(question['answer'], 'E')
            self.assertEqual([a['kind'] for a in question['assets'] if a['kind'].startswith('option_')],
                             ['option_'+c for c in 'ABCDE'])
            result = export(project, Path(directory)/'export')
            self.assertTrue(any(i['kind']=='option_E' for i in result[0]['images']))

    def test_inline_options_and_separate_answer_section(self):
        def line(text, top):
            return {'text': text, 'x0': 30, 'top': top, 'bottom': top+14,
                    'chars': [{'text': c, 'x0': 30+i*9, 'x1': 39+i*9,
                               'top': top, 'bottom': top+14} for i, c in enumerate(text)]}
        lines = [line('1. 选择正确答案', 30), line('A. 第一项 B. 第二项', 90),
                 line('2. 第二道题', 150), line('A. 第三项', 190), line('B. 第四项', 230),
                 line('参考答案', 300), line('1. A', 330), line('【解析】 第一题解释', 360),
                 line('2. B 【解析】 第二题解释', 410)]
        progress = []
        project = detect('unused.pdf', pages=[{'width': 400, 'height': 500, 'lines': lines}],
                         progress=lambda *value: progress.append(value))
        self.assertEqual(len(project['questions']), 2)
        self.assertEqual([q['answer'] for q in project['questions']], ['A', 'B'])
        for q in project['questions']:
            self.assertEqual([a['kind'] for a in q['assets']], ['stem', 'option_A', 'option_B', 'explanation'])
            self.assertFalse(q['issues'])
        first = project['questions'][0]['assets']
        a, b = first[1]['regions'][0], first[2]['regions'][0]
        self.assertLessEqual(a['box'][2], b['box'][0])
        self.assertGreater(a['box'][3]-a['box'][1], 14)
        self.assertTrue(progress)

    def test_five_inline_options_with_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'inline-five.pdf'
            pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
            canvas = Canvas(str(path), pagesize=(500, 600))
            canvas.setFont('STSong-Light', 14)
            lines = ['一、单选题', '1. 选择正确答案', 'A. 第一项    B. 第二项',
                     'C. 第三项    D. 第四项', 'E. 第五项', '【答案】 E', '【解析】 第五项正确']
            for i, line in enumerate(lines):
                canvas.drawString(30, 550-i*60, line)
            canvas.save()
            q = detect(path)['questions'][0]
            options = [a for a in q['assets'] if a['kind'].startswith('option_')]
            self.assertEqual([a['kind'] for a in options], ['option_'+c for c in 'ABCDE'])
            self.assertFalse(q['issues'])
            self.assertLessEqual(options[0]['regions'][0]['box'][2], options[1]['regions'][0]['box'][0])

    def test_empty_scanned_pdf_is_not_reported_as_success(self):
        with self.assertRaisesRegex(ValueError, '未识别到题目'):
            detect('unused.pdf', pages=[{'width': 400, 'height': 500, 'lines': []}])

    def test_detect_masks_and_export(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'exam.pdf'
            pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
            canvas = Canvas(str(path), pagesize=(400, 500))
            canvas.setFont('STSong-Light', 14)
            for y, text in [(450, '1. 下列计算正确的是？'), (400, 'A. 2 + 2 = 4'), (360, 'B. 2 + 2 = 5'), (320, '【答案】 A'), (280, '【解析】 根据加法计算。'), (220, '2. 选择正确选项。'), (180, 'A. 正确选项'), (140, 'B. 错误选项'), (100, '【答案】 A'), (60, '【解析】 这是解析。')]:
                canvas.drawString(30, y, text)
            canvas.save()
            project = detect(path)
            self.assertEqual(len(project['questions']), 2)
            self.assertEqual([q['answer'] for q in project['questions']], ['A', 'A'])
            self.assertEqual([a['kind'] for a in project['questions'][0]['assets']], ['stem', 'option_A', 'option_B', 'explanation'])
            first = project['questions'][0]['assets'][0]['regions'][0]
            # Tight frames may exclude the erased number entirely. Expand only
            # this test crop to keep the original mask visible for inspection.
            x0, y0, x1, y1 = first['masks'][0]
            first = dict(first, box=[min(first['box'][0],x0-1), min(first['box'][1],y0-1),
                                     max(first['box'][2],x1+1), max(first['box'][3],y1+1)])
            image = crop_region(str(path), first)
            x0, y0, x1, y1 = first['masks'][0]
            bx, by, _, _ = first['box']
            pixels = image.crop((8+round((x0-bx)*2), 8+max(0, round((y0-by)*2)), 8+round((x1-bx)*2), 8+round((y1-by)*2)))
            self.assertEqual(pixels.getextrema(), ((255, 255), (255, 255), (255, 255)))
            automatic = export(project, Path(directory) / 'automatic')
            self.assertTrue(all(i['filename'].startswith(path.stem + '_') for q in automatic for i in q['images']))
            self.assertEqual(len(automatic), 2)
            self.assertFalse(automatic[0]['reviewed'])
            for q in project['questions']:
                q['reviewed'] = True
            out = Path(directory) / 'out'
            result = export(project, out)
            self.assertNotEqual(automatic[0]['images'][0]['filename'], result[0]['images'][0]['filename'])
            self.assertEqual(len(result), 2)
            self.assertEqual(len(list(out.glob('*.png'))), 8)
            self.assertTrue((out / 'manifest.json').exists())
            with self.assertRaises(ValueError):
                export(project, out)


if __name__ == '__main__':
    unittest.main()
