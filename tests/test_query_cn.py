"""防止中文检索在停用字切分、Linux 简繁回退、法条零值与子款、双公司对比查询上漏召回或误劈核心实体。"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


class QueryCnTests(unittest.TestCase):
    def test_simplified_traditional_and_clause_numeral_bidirectional_expansion(self):
        from vericorpus import query_cn

        self.assertIn("貝萊德", query_cn.to_traditional("贝莱德"))
        self.assertIn("亿美元", query_cn.to_simplified("億美元"))

        # 验证 macOS 与无 CoreFoundation 的 Linux 回退路径均不会把“注册制”错转为“注冊製”，且支持多对一繁转简
        for cf_val in (query_cn._CF_TRANSFORM, None):
            with mock.patch.object(query_cn, "_CF_TRANSFORM", cf_val):
                trad_reg = query_cn.to_traditional("注册制")
                self.assertEqual(trad_reg, "註冊制")
                self.assertNotIn("注冊製", trad_reg)
                self.assertEqual(query_cn.to_simplified("病歷"), "病历")
                self.assertEqual(query_cn.to_simplified("幹細胞"), "干细胞")
                self.assertEqual(query_cn.to_simplified("問詢回復"), "问询回复")

        # 验证零值与亿单位及“第X条之一”子条
        self.assertIsNone(query_cn.zh_to_int("零"))
        self.assertIsNone(query_cn.zh_to_int("〇"))
        self.assertEqual(query_cn.zh_to_int("二十亿"), 2_000_000_000)
        q_zero = query_cn.analyze_query("第零条")
        flat_zero = [v for g in q_zero["clause_groups"] for v in g]
        self.assertNotIn("第0条", flat_zero)
        self.assertNotIn("0条", flat_zero)

        q_subclause = query_cn.analyze_query("《公司法》第一百零一条之一")
        flat_sub = [v for g in q_subclause["clause_groups"] for v in g]
        self.assertIn("第一百零一条之一", flat_sub)
        self.assertIn("第101条之一", flat_sub)
        self.assertNotIn("之一", q_subclause["cjk_words"])

        q_clause = query_cn.analyze_query("公司法 第47条 五年认缴")
        flat = [v for g in q_clause["clause_groups"] for v in g]
        self.assertIn("第47条", flat)
        self.assertIn("第四十七条", flat)
        self.assertNotIn("47", q_clause["ascii_terms"])

        q_zh = query_cn.analyze_query("民法典 第五百八十四条 违约赔偿")
        flat_zh = [v for g in q_zh["clause_groups"] for v in g]
        self.assertIn("第584条", flat_zh)
        self.assertIn("第五百八十四条", flat_zh)

        q_18c = query_cn.analyze_query("18C章 特专科技")
        flat_18c = [v for g in q_18c["clause_groups"] for v in g]
        self.assertIn("18C章", flat_18c)
        self.assertIn("第十八C章", flat_18c)

    def test_stop_chars_do_not_split_core_entities_and_multi_ticker_uses_should(self):
        from vericorpus import query_cn

        q_ent = query_cn.analyze_query("阿里巴巴 云计算 过敏反应 长和")
        for entity in ("阿里巴巴", "云计算", "过敏反应", "长和"):
            self.assertIn(entity, q_ent["cjk_words"], f"核心实体 {entity!r} 不应被停用字词劈碎")
        for bg in ("阿里", "里巴", "云计", "计算", "过敏", "长和"):
            self.assertIn(bg, q_ent["bigrams"])

        # 双 Ticker 对比查询应通过 should(minimum_should_match=1) 召回两家各自财报分块，而非强制同块共现
        cmp_body = query_cn.build_search_body("对比 NVDA 与 AMD 2025年研发费用", scope="docs", limit=5)
        must_clauses = cmp_body["query"]["bool"]["must"]
        top_level_single_ticker_musts = [
            c for c in must_clauses
            if ("NVDA" in json.dumps(c) and "AMD" not in json.dumps(c))
            or ("AMD" in json.dumps(c) and "NVDA" not in json.dumps(c))
        ]
        self.assertEqual(top_level_single_ticker_musts, [], "双公司对比查询严禁将两个 Ticker 分别塞入顶层 must")
        combined_ticker_should = [
            c for c in must_clauses
            if "NVDA" in json.dumps(c) and "AMD" in json.dumps(c) and c.get("bool", {}).get("minimum_should_match") == 1
        ]
        self.assertGreaterEqual(len(combined_ticker_should), 1)

        # 默认不应硬编码私人备份前缀过滤，且支持显式传入 exclude_format_prefixes
        self.assertNotIn("must_not", cmp_body["query"]["bool"])
        filtered_body = query_cn.build_search_body(
            "阿里巴巴 营业收入", scope="docs", limit=5, exclude_format_prefixes=("tmp-",)
        )
        self.assertEqual(filtered_body["query"]["bool"]["must_not"], [{"prefix": {"ax_format": "tmp-"}}])

    def test_preserves_financial_medical_symbols_and_expands_domain_synonyms(self):
        from vericorpus import query_cn

        q1 = query_cn.analyze_query("VC/PE 估值与 P/E 及 PD-1 BRCA1/2")
        for tok in ("VC/PE", "P/E", "PD-1", "BRCA1/2"):
            self.assertIn(tok, q1["ascii_terms"])

        q2 = query_cn.analyze_query("归母净利润 阿里巴巴")
        self.assertTrue(any("股東應佔溢利" in g for g in q2["synonym_groups"]))
        self.assertTrue(any("net income attributable" in g for g in q2["synonym_groups"]))

        q3 = query_cn.analyze_query("即时检验 电化学传感器")
        self.assertTrue(any("POCT" in g or "point-of-care" in g for g in q3["synonym_groups"]))

        body = query_cn.build_search_body("归母净利润 阿里巴巴", scope="docs", limit=5)
        must_dump = json.dumps(body["query"]["bool"], ensure_ascii=False)
        self.assertIn("股東應佔溢利", must_dump)
        self.assertIn("歸屬於普通股股東的淨利潤", must_dump)
        self.assertIn('"text"', must_dump)
        self.assertNotIn('"code"', must_dump)
        fmt_filter = [f["terms"]["ax_format"] for f in body["query"]["bool"]["filter"] if "terms" in f][0]
        self.assertIn("txt-lines", fmt_filter)

        q_year = query_cn.analyze_query("腾讯 2026年九月三十日 盈利")
        self.assertNotIn("2026", q_year["ascii_terms"])
        flat_years = [v for g in q_year["clause_groups"] for v in g]
        self.assertIn("2026年", flat_years)
        self.assertIn("二零二六年", flat_years)

        body_no_bg = query_cn.build_search_body("中国肺癌 低剂量CT 筛查指南", scope="docs", require_anchors=True, require_bigrams=False)
        no_bg_must = json.dumps(body_no_bg["query"]["bool"]["must"], ensure_ascii=False)
        self.assertIn("lung cancer", no_bg_must)
        self.assertNotIn("筛查", no_bg_must)

        q_num = query_cn.analyze_query("海光信息 2025年报 归母净利润 14,376,889,476.95 第999期")
        self.assertIn("14,376,889,476.95", q_num["ascii_terms"])
        self.assertNotIn("376", q_num["ascii_terms"])
        flat_clauses = [v for g in q_num["clause_groups"] for v in g]
        self.assertIn("2025年度", flat_clauses)
        self.assertIn("第999期", flat_clauses)
        flat_syns = [v for g in q_num["synonym_groups"] for v in g]
        self.assertIn("归属于上市公司股东的净利润", flat_syns)

        q_ent = query_cn.analyze_query("SpaceX B轮优先股 对赌回购利率")
        self.assertFalse(q_ent["synonym_groups"])


if __name__ == "__main__":
    unittest.main()
