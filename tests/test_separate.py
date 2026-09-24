import json
import os
import tempfile
import unittest
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen.canvas import Canvas
from scrollferry.core import crop_region, detect, export, read_pages, render_page


class SeparatePaperTest(unittest.TestCase):
    def test_section_number_restarts_and_unnumbered_reference_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            qpath, apath = Path(directory)/'q.pdf', Path(directory)/'a.pdf'
            self.make_pdf(qpath,['单项选择题','1.选择正确项','A.甲','B.乙',
                                  '名词解释','1.常设机构','简答题','1.简述特点',
                                  '计算题','1.计算税额','论述题','1.论述制度'])
            self.make_pdf(apath,['单项选择题','1.【答案】B','【解析】应选择乙',
                                  '名词解释','1.【参考答案】固定营业场所',
                                  '简答题','1.【参考答案】三个特点',
                                  '计算题','1.【参考答案】税额为一百',
                                  '论述题','【参考答案】制度分析'])
            project = detect(qpath, answer_source=apath)
            self.assertEqual(len(project['questions']),5)
            self.assertEqual(project['questions'][0]['answer'],'B')
            self.assertTrue(all(not q['issues'] for q in project['questions']))
            self.assertTrue(all(q['type']=='solution' for q in project['questions'][1:]))
            self.assertTrue(all(len(q['assets'][-1]['regions'])==1 for q in project['questions']))

    def test_running_header_and_chinese_page_footer_are_outside_bounds(self):
        from scrollferry.separate import Paper
        pages=[]
        for n in range(2):
            lines=[{'text':'重复页眉','top':30,'bottom':40,'x0':80},
                   {'text':f'{n+1}.正文','top':100,'bottom':115,'x0':40},
                   {'text':f'第 {n+1} 页 共 12 页','top':660,'bottom':675,'x0':80}]
            pages.append({'width':500,'height':700,'lines':lines})
        paper=Paper(pages)
        self.assertEqual(paper.bounds,[(97,118),(97,118)])
        self.assertEqual(len(paper.lines),2)

    def make_pdf(self, path, lines):
        pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
        canvas = Canvas(str(path), pagesize=(500, 700))
        canvas.setFont('STSong-Light', 12)
        for i, line in enumerate(lines):
            canvas.drawString(40, 660-i*28, line)
        canvas.save()

    def test_shared_material_writing_and_reordered_solutions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qpath, apath = root/'q.pdf', root/'a.pdf'
            self.make_pdf(qpath, ['一、逻辑推理', '1～2题基于以下题干：', '甲和乙分别去两个城市。',
                                 '1. 谁去北京？', 'A. 甲    B. 乙', '2. 谁去上海？', 'A. 甲    B. 乙',
                                 '三、写作', '3.论证有效性分析', '阅读材料并分析。'])
            self.make_pdf(apath, ['2、【答案】B', '第二题解释。', '1.答案：A.', '解析：第一题解释。',
                                 '三、写作部分', '3.论证有效性分析', '参考思路：',
                                 '1. 这里是分析要点，不是新题。', '2. 这里是另一个分析要点。'])
            p = detect(qpath, answer_source=apath)
            self.assertEqual([q['answer'] for q in p['questions']], ['A','B',''])
            self.assertTrue(all(not q['issues'] for q in p['questions']))
            self.assertEqual(p['questions'][2]['type'], 'solution')
            self.assertEqual(p['questions'][2]['answer_status'], 'in_explanation')
            stems = [q['assets'][0]['regions'] for q in p['questions'][:2]]
            self.assertEqual(stems[0][0], stems[1][0])
            self.assertIsNot(stems[0][0], stems[1][0])
            exp = p['questions'][0]['assets'][-1]['regions'][0]
            self.assertEqual(exp['page'], 1)
            restored = json.loads(json.dumps(p))
            self.assertEqual(render_page(restored, 1, 1).tobytes(), render_page(apath, 0, 1).tobytes())
            out = root/'export'
            rows = export(restored, out)
            from PIL import Image
            file = next(i['filename'] for i in rows[0]['images'] if i['kind']=='explanation')
            with Image.open(out/file) as actual:
                self.assertEqual(actual.tobytes(), crop_region(apath, dict(exp,page=0), tight=True).tobytes())
            self.assertEqual(rows[2]['type'], 'solution')

    def test_missing_duplicate_and_extra_numbers_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_pdf(root/'q.pdf', ['1. 第一题', 'A. 甲 B. 乙', '2. 第二题', 'A. 甲 B. 乙'])
            self.make_pdf(root/'a.pdf', ['1.答案：A', '解析：第一条。', '1.答案：B', '解析：重复条目。', '9.答案：A'])
            p = detect(root/'q.pdf', answer_source=root/'a.pdf')
            self.assertIn('题号重复，无法可靠匹配解析', p['questions'][0]['issues'])
            self.assertIn('未匹配到答案解析', p['questions'][1]['issues'])
            self.assertFalse(any(q['answer'] for q in p['questions']))
            self.assertIn('9', p['warnings'][0])

    @unittest.skipUnless(os.getenv('SCROLLFERRY_SEPARATE_QUESTIONS') and os.getenv('SCROLLFERRY_SEPARATE_ANSWERS'),
                         'Set both SCROLLFERRY_SEPARATE_QUESTIONS and SCROLLFERRY_SEPARATE_ANSWERS for the 396 sample')
    def test_real_396_paper(self):
        source, answers = os.environ['SCROLLFERRY_SEPARATE_QUESTIONS'], os.environ['SCROLLFERRY_SEPARATE_ANSWERS']
        pages = read_pages(source)
        p = detect(source, pages=pages, answer_source=answers)
        self.assertEqual([q['original_number'] for q in p['questions']], [str(n) for n in range(1,58)])
        self.assertFalse(p['warnings'])
        for q in p['questions']:
            self.assertFalse(q['issues'], q['original_number'])
            for a in q['assets']:
                self.assertTrue(a['regions'])
                self.assertTrue(all(r['box'][3]>r['box'][1] and r['box'][2]>r['box'][0] for r in a['regions']))
        for q in p['questions'][:55]:
            self.assertEqual([a['kind'] for a in q['assets']], ['stem']+['option_'+c for c in 'ABCDE']+['explanation'])
            self.assertEqual(len(q['answer']), 1)
        self.assertEqual([q['type'] for q in p['questions'][55:]], ['solution','solution'])
        for n in [45,46,54,55]:
            self.assertEqual(len(p['questions'][n-1]['assets'][0]['regions']), 2)
        # Check the segmentation before whitespace tightening: bitmap margins
        # need not remain inside the final editable crop.
        from scrollferry.core import _detect
        raw = _detect(source, pages=pages, answer_source=answers)
        stem = raw['questions'][1]['assets'][0]['regions'][0]
        image = next(i for i in pages[0]['images'] if 330<i['top']<335)
        self.assertLessEqual(stem['box'][1], image['top'])
        self.assertGreaterEqual(stem['box'][3], image['bottom'])
        # Every formula bitmap must fit wholly within at least one crop; a fixed
        # top padding must not shave the preceding fraction's bottom edge.
        for pn, page in enumerate(pages):
            boxes = [r['box'] for q in raw['questions'] for a in q['assets'] for r in a['regions'] if r['page']==pn]
            for im in page['images']:
                self.assertTrue(any(b[0]<=im['x0'] and b[1]<=im['top'] and b[2]>=im['x1'] and b[3]>=im['bottom'] for b in boxes),
                                f'Formula clipped on page {pn+1}: {im}')


if __name__ == '__main__':
    unittest.main()
