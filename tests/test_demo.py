import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retriever import retrieve_topk
from utils import load_products, parse_price_constraint, generate_recommendation_summary


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.products = load_products(str(ROOT / 'data/synthetic_products.json'))

    def test_chinese_budget(self):
        self.assertEqual(parse_price_constraint('二十万以内'), {'type': 'lte', 'min': None, 'max': 200000})
        self.assertEqual(parse_price_constraint('20-50万')['min'], 200000)

    def test_ranking(self):
        result = retrieve_topk(self.products, '石油化工便携式气相色谱仪，二十万以内', top_k=3)
        self.assertEqual(result[0]['model'], 'SYN-005')
        self.assertIn('价格命中', result[0]['match_reasons'])
        self.assertLessEqual(len(result), 3)

    def test_no_match(self):
        self.assertEqual(retrieve_topk(self.products, '不存在的类别xyz'), [])
        self.assertIn('暂未找到', generate_recommendation_summary('xyz', []))

    def test_offline_even_with_environment_key(self):
        with patch.dict(os.environ, {'QWEN_API_KEY': 'test-placeholder'}):
            with patch('urllib.request.urlopen', side_effect=AssertionError('Unexpected network call')):
                result = retrieve_topk(self.products, '环保便携气体分析仪，十万以内')
                self.assertEqual(result[0]['model'], 'SYN-002')
                self.assertIn('合成便携气体分析仪', generate_recommendation_summary('环保', result))

    def test_synthetic_data_hygiene(self):
        self.assertEqual(len(self.products), 12)
        for record in self.products:
            self.assertTrue(record['synthetic'])
            self.assertTrue(record['url'].startswith('https://example.invalid/'))
            self.assertFalse({'contact_name', 'contact_phone', 'email', 'phone'} & record.keys())
            self.assertNotIn('source_file', record)

    def test_streamlit_recommendation(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(ROOT / 'app.py')).run(timeout=20)
        self.assertFalse(app.exception)
        self.assertIn('合成数据', app.info[0].value)
        app.text_input[0].set_value('石油化工便携式气相色谱仪，二十万以内')
        app.button[0].click().run(timeout=20)
        self.assertFalse(app.exception)
        self.assertEqual(app.dataframe[0].value.iloc[0]['model'], 'SYN-005')
        self.assertTrue(any('规则生成' in item.value for item in app.subheader))
        app.text_input[0].set_value('')
        app.button[0].click().run(timeout=20)
        self.assertTrue(app.warning)


if __name__ == '__main__':
    unittest.main()
