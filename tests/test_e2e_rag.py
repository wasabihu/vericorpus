"""防止 E2E RAG 评测出现检索正文缺失、跨块表格丢表头、指标口径漂移及训练集标的泄漏。"""
from __future__ import annotations

import json
import math
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

HELDOUT_SEC_TICKERS = frozenset(
    {"ARM", "BABA", "GS", "JNJ", "JPM", "MRNA", "MSFT", "OXY", "TSM", "WFC", "XOM"}
)

TRAIN_SEC_TICKERS = frozenset(
    {
        "AAPL", "AMD", "AVGO", "AXP", "BA", "BAC", "BEKE", "BIDU", "BRK_B", "BZ",
        "CB", "COST", "CSCO", "CVX", "FUTU", "GOOGL", "HSBC", "INTC", "JD", "LI",
        "LMT", "META", "MU", "NET", "NTES", "NVDA", "PDD", "PFE", "QCOM", "SPCX",
        "TCOM", "TME", "TSLA", "UNH", "VIPS", "WMT", "ZTO", "ALAB", "CRDO", "CRWV",
    }
)


class _MockXerjHandler(BaseHTTPRequestHandler):
    responses: list[dict[str, Any]] = []
    captured_bodies: list[dict[str, Any]] = []

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or "0")
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        self.__class__.captured_bodies.append(body)
        payload = self.__class__.responses.pop(0) if self.__class__.responses else {"took": 1, "hits": {"total": {"value": 0}, "hits": []}}
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class E2ERagTests(unittest.TestCase):
    def test_query_cn_include_body_flag_preserves_backward_compatibility(self):
        from vericorpus import query_cn

        default_body = query_cn.build_search_body("微软 2025 营业收入", limit=3, scope="docs")
        self.assertNotIn("body", default_body["_source"])
        self.assertNotIn("section", default_body["_source"])

        with_body = query_cn.build_search_body("微软 2025 营业收入", limit=3, scope="docs", include_body=True)
        self.assertIn("body", with_body["_source"])
        self.assertIn("section", with_body["_source"])

        _MockXerjHandler.captured_bodies = []
        _MockXerjHandler.responses = [
            {
                "took": 2,
                "hits": {
                    "total": {"value": 1},
                    "hits": [
                        {
                            "_score": 42.5,
                            "_source": {
                                "ax_path": "sec-10y-core/xbrl_summaries/MSFT_10y_xbrl.md",
                                "ax_format": "md",
                                "title": "微软 XBRL 财务总表",
                                "section": "核心财务指标年度对比表",
                                "start_line": 22,
                                "end_line": 24,
                                "body": "| 2025-06-30 | USD 281,724.00M (281,724,000,000) |",
                            },
                            "fields": {},
                        }
                    ],
                },
            }
        ]
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _MockXerjHandler)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            res = query_cn.search_index(
                f"http://127.0.0.1:{srv.server_address[1]}",
                "e2e",
                "MSFT 2025 营业收入",
                limit=3,
                include_body=True,
            )
        finally:
            srv.shutdown()
            srv.server_close()

        self.assertEqual(len(res["hits"]), 1)
        hit = res["hits"][0]
        self.assertEqual(hit["section"], "核心财务指标年度对比表")
        self.assertIn("USD 281,724.00M", hit["body"])
        self.assertIn("body", _MockXerjHandler.captured_bodies[0]["_source"])

    def test_assemble_retrieved_context_prepends_doc_header_and_missing_table_header(self):
        from vericorpus import eval_e2e_rag

        source_md = (
            "# 微软 (Microsoft Corporation / MSFT) — SEC 官方 XBRL 近 10 年审计财务总表\n\n"
            "## 核心财务指标年度对比表\n\n"
            "| 财年结束(FY End) | 营业收入 Revenue | 毛利润 Gross Profit |\n"
            "| --- | --- | --- |\n"
            "| 2026-06-30 | USD 331,839.00M | USD 225,465.00M |\n"
            "| 2025-06-30 | USD 281,724.00M | USD 193,893.00M |\n"
            "| 2024-06-30 | USD 245,122.00M | USD 171,008.00M |\n"
        )
        raw_lookup = {"sec-10y-core/xbrl_summaries/MSFT_10y_xbrl.md": source_md}

        hits = [
            {
                "title": "微软 XBRL 财务总表",
                "path": "sec-10y-core/xbrl_summaries/MSFT_10y_xbrl.md",
                "section": "核心财务指标年度对比表",
                "start_line": 8,
                "body": "| 2025-06-30 | USD 281,724.00M | USD 193,893.00M |\n| 2024-06-30 | USD 245,122.00M | USD 171,008.00M |",
            },
            {
                "title": "完整表格块",
                "path": "sec-10y-core/xbrl_summaries/MSFT_10y_xbrl.md",
                "section": "核心财务指标年度对比表",
                "start_line": 5,
                "body": "| 财年结束(FY End) | 营业收入 Revenue | 毛利润 Gross Profit |\n| --- | --- | --- |\n| 2026-06-30 | USD 331,839.00M | USD 225,465.00M |",
            },
        ]

        assembled = eval_e2e_rag.assemble_retrieved_context(hits, raw_lookup)
        self.assertIn("[DOC_1 | title: 微软 XBRL 财务总表 | path: sec-10y-core/xbrl_summaries/MSFT_10y_xbrl.md | section: 核心财务指标年度对比表]", assembled)
        doc1_seg, doc2_seg = assembled.split("[DOC_2", 1)
        self.assertIn("| 财年结束(FY End) | 营业收入 Revenue | 毛利润 Gross Profit |", doc1_seg)
        self.assertIn("| --- | --- | --- |", doc1_seg)
        self.assertIn("| 2025-06-30 | USD 281,724.00M | USD 193,893.00M |", doc1_seg)
        # DOC_2 already starts with table header + separator; do not duplicate
        self.assertEqual(doc2_seg.count("| 财年结束(FY End) |"), 1)
        self.assertEqual(eval_e2e_rag.assemble_retrieved_context([], raw_lookup), "")

    def test_official_xerj_scorer_computes_rwn_net_bootstrap_ci_and_retrieval_metrics(self):
        from vericorpus import eval_e2e_rag

        doc_a = "Microsoft FY2025 revenue was USD 281,724.00M."
        doc_b = "Arm SoftBank Group holds 90.6% ordinary shares."
        cases = [
            {
                "id": "C1",
                "expect_absent": False,
                "expect_path_sub": "msft",
                "expect_snippet_any": ["281,724.00M"],
                "expected": {"status": "ANSWER", "value": "281724", "type": "number"},
            },
            {
                "id": "C2",
                "expect_absent": False,
                "expect_path_sub": "arm",
                "expect_snippet_any": ["90.6%"],
                "expected": {"status": "ANSWER", "value": "90.6", "type": "number"},
            },
            {
                "id": "C3",
                "expect_absent": False,
                "expect_path_sub": "law",
                "expect_snippet_any": ["五年"],
                "expected": {"status": "ANSWER", "value": "5", "type": "number"},
            },
            {
                "id": "C4",
                "expect_absent": True,
                "expected": {"status": "ABSENT", "value": None, "type": None},
            },
        ]

        # Retrieval hits for 3 answerable cases: rank 1, rank 2, miss
        retrieval_hits = {
            "C1": [{"path": "msft_10y.md", "body": doc_a}],
            "C2": [{"path": "noise.md", "body": "irrelevant"}, {"path": "arm_424b4.md", "body": doc_b}],
            "C3": [{"path": "noise.md", "body": "irrelevant"}],
        }
        ret_metrics = eval_e2e_rag.compute_retrieval_metrics(cases, retrieval_hits)
        self.assertAlmostEqual(ret_metrics["r_at_1"], 1 / 3, places=4)
        self.assertAlmostEqual(ret_metrics["r_at_3"], 2 / 3, places=4)
        expected_ndcg3 = (1.0 + (1.0 / math.log2(3)) + 0.0) / 3.0
        self.assertAlmostEqual(ret_metrics["ndcg_at_3"], expected_ndcg3, places=4)

        s_a = doc_a.index("USD 281,724.00M")
        s_b = doc_b.index("90.6%")
        oracle_records = [
            {"id": "C1", "status": "ANSWER", "value": "281724", "evidence": [{"start": s_a, "end": s_a + len("USD 281,724.00M"), "quote": "USD 281,724.00M"}], "doc": doc_a},
            {"id": "C2", "status": "ANSWER", "value": "90.6", "evidence": [{"start": s_b, "end": s_b + len("90.6%"), "quote": "90.6%"}], "doc": doc_b},
            {"id": "C3", "status": "ANSWER", "value": "5", "evidence": [{"start": 0, "end": 2, "quote": "五年"}], "doc": "五年内缴足"},
            {"id": "C4", "status": "ABSENT", "value": None, "evidence": [], "doc": ""},
        ]
        # Arm records: C1=R, C2=W (wrong number), C3=N (declined), C4=R (absent detected)
        arm_records = [
            {"id": "C1", "status": "ANSWER", "value": "281724", "evidence": [{"start": s_a, "end": s_a + len("USD 281,724.00M"), "quote": "USD 281,724.00M"}], "doc": doc_a},
            {"id": "C2", "status": "ANSWER", "value": "88.0", "evidence": [{"start": s_b, "end": s_b + len("90.6%"), "quote": "90.6%"}], "doc": doc_b},
            {"id": "C3", "status": "ABSENT", "value": None, "evidence": [], "doc": ""},
            {"id": "C4", "status": "ABSENT", "value": None, "evidence": [], "doc": ""},
        ]

        oracle_summary = eval_e2e_rag.score_e2e_arm(cases, oracle_records)
        arm_summary = eval_e2e_rag.score_e2e_arm(cases, arm_records, oracle_records=oracle_records, n_draws=4000, seed=42)
        self.assertEqual((oracle_summary["R"], oracle_summary["W"], oracle_summary["N"]), (4, 0, 0))
        self.assertEqual(oracle_summary["net"], 4)
        self.assertEqual((arm_summary["R"], arm_summary["W"], arm_summary["N"]), (2, 1, 1))
        self.assertEqual(arm_summary["net"], 0)  # 2 - 2*1 = 0
        self.assertEqual(arm_summary["bootstrap_draws"], 4000)
        lo, hi = arm_summary["net_ci95"]
        self.assertLessEqual(lo, arm_summary["net"])
        self.assertLessEqual(arm_summary["net"], hi)

    def test_e2e_rag_60_zero_leakage_and_schema(self):
        eval_path = ROOT_DIR / "evals" / "e2e_rag_60.json"
        self.assertTrue(eval_path.is_file(), f"缺少评测集文件: {eval_path}")
        cases = json.loads(eval_path.read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 60)

        sec_fin = [c for c in cases if c.get("track") == "sec_fin"]
        arm_ipo = [c for c in cases if c.get("track") == "arm_ipo"]
        cn_law = [c for c in cases if c.get("track") == "cn_law"]
        absent = [c for c in cases if c.get("expect_absent") is True]

        self.assertEqual(len(sec_fin), 20)
        self.assertEqual(sum(1 for c in sec_fin if c.get("category") == "extract"), 10)
        self.assertEqual(sum(1 for c in sec_fin if c.get("category") == "arithmetic"), 10)
        self.assertEqual(len(arm_ipo), 10)
        self.assertEqual(len(cn_law), 15)
        self.assertEqual(len(absent), 15)

        seen_ids = set()
        for c in cases:
            cid = c["id"]
            self.assertNotIn(cid, seen_ids)
            seen_ids.add(cid)
            self.assertTrue(c.get("question"))
            self.assertIn("expected", c)
            tk = c.get("ticker")
            if tk:
                self.assertIn(tk, HELDOUT_SEC_TICKERS, f"严禁使用非保留 SEC 标的: {tk}")
                self.assertNotIn(tk, TRAIN_SEC_TICKERS)
            if not c.get("expect_absent"):
                self.assertTrue(c.get("oracle_document"), f"{cid} 缺少 oracle_document")
                self.assertTrue(c.get("expect_path_sub"), f"{cid} 缺少 expect_path_sub")
                self.assertEqual(c["expected"]["status"], "ANSWER")
                # Also verify no training ticker sneaks into SEC case paths or questions
                if c.get("track") in ("sec_fin", "arm_ipo"):
                    blob = f"{c.get('expect_path_sub', '')} {c.get('question', '')}"
                    for tr_tk in TRAIN_SEC_TICKERS:
                        self.assertNotRegex(blob, rf"\b{tr_tk}\b", f"{cid} 疑似泄漏训练标的 {tr_tk}")
            else:
                self.assertEqual(c["expected"]["status"], "ABSENT")


if __name__ == "__main__":
    unittest.main()
