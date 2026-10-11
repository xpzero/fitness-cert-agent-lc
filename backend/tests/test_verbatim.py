import unittest

from app.rag.citation import verbatim_coverage


class TestVerbatimIn(unittest.TestCase):
    def test_exact_substring(self):
        content = "（1）动作要求：双脚着地，身体保持一条直线。（2）合格标准：男子40次。"
        ev = "合格标准：男子40次"
        self.assertGreaterEqual(verbatim_coverage(ev, content), 0.99)

    def test_markdown_decorated_still_matches(self):
        # 出题模型常把依据句包上 **加粗**、引号——清洗后应仍可定位
        content = "合格标准：男子初、中、高级均为 40次。"
        ev = '**合格标准：男子初、中、高级均为 **40次**。**'
        self.assertGreaterEqual(verbatim_coverage(ev, content), 0.9)

    def test_paraphrase_fails_gate(self):
        # 改写句不是逐字依据——应低于 0.9（防幻觉闸门拒绝）
        content = "俯卧撑主要锻炼胸大肌和肱三头肌。"
        ev = "俯卧撑能锻炼胸部与手臂后侧肌群"
        self.assertLess(verbatim_coverage(ev, content), 0.9)

    def test_short_evidence_rejected(self):
        self.assertEqual(verbatim_coverage("40次", "男子40次"), 0.0)

    def test_evidence_longer_than_content(self):
        self.assertLess(verbatim_coverage("一段很长很长的依据" * 5, "短文本"), 0.9)


if __name__ == "__main__":
    unittest.main()
