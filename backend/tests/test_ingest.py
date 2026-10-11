import unittest

from app.rag.chunking import make_chunks, parse_pages, split_section

SAMPLE = """# 第三章 抗阻训练技术
[[P88]]
## 3.1 杠铃卧推
目标肌群为胸大肌。起始姿势：仰卧于凳上，双脚平放地面。
""" + "动作过程细节。" * 200 + """
[[P89]]
## 3.2 保护技术
保护者站位于练习者头部后方，杠铃进行保护。
"""


class TestIngest(unittest.TestCase):
    def test_parse_pages(self):
        pages = parse_pages(SAMPLE)
        # 样例首行标题在首个页码标记之前 → 归为 page 0
        self.assertEqual([p for p, _ in pages], [0, 88, 89])

    def test_parse_pages_no_marker(self):
        self.assertEqual(parse_pages("纯文本无页码"), [(0, "纯文本无页码")])

    def test_split_section_extracts_headings(self):
        pages = dict(parse_pages(SAMPLE))
        sections = split_section(pages[88])
        self.assertEqual(sections[0][0], "3.1 杠铃卧推")

    def test_make_chunks_respects_max_chars(self):
        chunks = make_chunks(SAMPLE, max_chars=100, overlap=10)
        self.assertTrue(all(len(c.content) <= 110 for c in chunks))

    def test_make_chunks_carries_metadata(self):
        chunks = make_chunks(SAMPLE)
        self.assertEqual(chunks[0].page_no, 88)
        self.assertEqual(chunks[0].source_type, "教材")
        self.assertEqual(chunks[0].authority_level, 1)
        self.assertTrue(all(c.page_no in (88, 89) for c in chunks))

    def test_chunk_ids_sequential(self):
        chunks = make_chunks(SAMPLE)
        self.assertEqual([c.chunk_index for c in chunks], list(range(len(chunks))))


if __name__ == "__main__":
    unittest.main()
