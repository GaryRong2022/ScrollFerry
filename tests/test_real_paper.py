"""Opt-in regression against the user's local sample; the PDF is not copied into the repo."""
import os
import unittest
from collections import Counter
from scrollferry.core import detect, read_pages


@unittest.skipUnless(os.environ.get('SCROLLFERRY_TEST_PDF'), 'Set SCROLLFERRY_TEST_PDF to the June math sample')
class RealPaperTest(unittest.TestCase):
    def test_mixed_types_complete_options_and_cross_page_solutions(self):
        source = os.environ['SCROLLFERRY_TEST_PDF']
        pages = read_pages(source)
        project = detect(source, pages=pages)
        questions = project['questions']
        self.assertEqual(len(questions), 22)
        self.assertEqual(Counter(q['type'] for q in questions), {'single_choice':10,'fill_blank':6,'solution':6})
        self.assertEqual(''.join(q['answer'] for q in questions[:10]), 'CABACBCCDA')
        for q in questions[:10]:
            self.assertEqual([a['kind'] for a in q['assets']], ['stem','option_A','option_B','option_C','option_D','explanation'])
        for q in questions[10:16]:
            self.assertEqual([a['kind'] for a in q['assets']], ['stem','answer','explanation'])
        for q in questions[16:]:
            self.assertEqual([a['kind'] for a in q['assets']], ['stem','explanation'])
            self.assertGreaterEqual(len(q['assets'][1]['regions']), 2)
        # All four tall piecewise formulas in question 9 must remain whole.
        options=questions[8]['assets'][1:5]
        formula_rects=[r for r in pages[4]['rects'] if isinstance(r['color'],str)
                       and r['color'].startswith('P') and 250<r['top']<440 and r['x0']<120]
        self.assertEqual(len(formula_rects),4)
        for asset, rect in zip(options,formula_rects):
            box=asset['regions'][0]['box']
            self.assertLessEqual(box[1],rect['top']+.01)
            self.assertGreaterEqual(box[3],rect['bottom']-.01)
