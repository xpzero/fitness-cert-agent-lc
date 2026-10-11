import unittest

from app.rag.citation import find_missing_citations, extract_citations, verify_claim
from app.rag.fusion import rrf_merge


class TestRRF(unittest.TestCase):
    def test_overlap_boosted(self):
        merged = rrf_merge(["a", "b", "c"], ["b", "d"])
        self.assertEqual(merged[0][0], "b")

    def test_authority_weighting(self):
        # 同排名情况下，权威级 1 的 chunk 应排在权威级 3 前
        merged = rrf_merge(["x", "y"], [], authority={"x": 1, "y": 3}, k=60)
        self.assertEqual(merged[0][0], "x")

    def test_top_k(self):
        merged = rrf_merge(["a", "b", "c", "d"], ["e"], top_k=2)
        self.assertEqual(len(merged), 2)


class TestCitation(unittest.TestCase):
    def test_extract_citations_dedup_in_order(self):
        text = "胸大肌[chunk:c2]起于[chunk:c1]……[chunk:c2]"
        self.assertEqual(extract_citations(text), ["c2", "c1"])

    def test_find_missing_citations(self):
        text = "引用了 [chunk:a] 和 [chunk:ghost]"
        missing = find_missing_citations(text, {"a", "b"})
        self.assertEqual(missing, ["ghost"])

    def test_verify_claim_supported(self):
        r = verify_claim("卧推的目标肌群是胸大肌",
                         "杠铃卧推的目标肌群为胸大肌，起始姿势为仰卧")
        self.assertTrue(r["supported"])

    def test_verify_claim_unsupported(self):
        r = verify_claim("深蹲主要发展肱二头肌", "杠铃卧推的目标肌群为胸大肌")
        self.assertFalse(r["supported"])

    def test_nli_fn_takes_precedence(self):
        r = verify_claim("任意", "任意原文", nli_fn=lambda c, e: True)
        self.assertEqual(r["method"], "nli")


if __name__ == "__main__":
    unittest.main()
