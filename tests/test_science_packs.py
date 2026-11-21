"""防止 AI/生物医学开放获取语料混入非商用(NC)/ND/arXiv非排他许可、XML 实体攻击(DOCTYPE/ENTITY)、缺失 CC-BY-4.0 第 3(a) 条作者署名与改编声明，或 30 题评测集偏移失效。"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


class SciencePacksTests(unittest.TestCase):
    def test_corpora_audit_passes_all_11_corpora_with_new_science_packs(self):
        from vericorpus import compliance

        audited = compliance.audit_corpora_dir(ROOT_DIR / "corpora")
        self.assertEqual(len(audited), 11, f"应共有 11 个合规语料目录，实际: {len(audited)}")
        packs = [item for item in audited if item["mode"] == "pack"]
        recipes = [item for item in audited if item["mode"] == "recipe"]
        self.assertEqual(len(packs), 8)
        self.assertEqual(len(recipes), 3)

        by_slug = {item["slug"]: item for item in audited}
        self.assertIn("ai-papers-ccby", by_slug)
        self.assertEqual(by_slug["ai-papers-ccby"]["mode"], "pack")
        self.assertEqual(by_slug["ai-papers-ccby"]["license"], "CC-BY-4.0")

        self.assertIn("biomed-clinical-ccby", by_slug)
        self.assertEqual(by_slug["biomed-clinical-ccby"]["mode"], "pack")
        self.assertEqual(by_slug["biomed-clinical-ccby"]["license"], "CC-BY-4.0")

        biomed_mf = json.loads(Path(by_slug["biomed-clinical-ccby"]["manifest_path"]).read_text(encoding="utf-8"))
        sub_licenses = {str(s.get("license") or biomed_mf["license"]) for s in biomed_mf.get("sources", [])}
        self.assertTrue(sub_licenses.issubset({"CC-BY-4.0", "CC0-1.0"}))
        self.assertIn("CC0-1.0", sub_licenses)

    def test_license_firewall_and_xml_entity_bomb_protection(self):
        from vericorpus import science_packs

        for bad in (
            "",
            "cc-by-nc",
            "CC-BY-NC-4.0",
            "CC-BY-NC-SA-4.0",
            "CC-BY-NC-ND-4.0",
            "CC-BY-ND-4.0",
            "CC-BY-SA-4.0",
            "NOASSERTION",
            "arxiv-nonexclusive-1.0",
            "All Rights Reserved",
        ):
            self.assertIsNone(science_packs.is_allowed_oa_license(bad), f"应拦截非商用或受限许可: {bad!r}")

        self.assertEqual(science_packs.is_allowed_oa_license("cc-by"), "CC-BY-4.0")
        self.assertEqual(science_packs.is_allowed_oa_license("cc-by-4.0"), "CC-BY-4.0")
        self.assertEqual(science_packs.is_allowed_oa_license("https://creativecommons.org/licenses/by/4.0/"), "CC-BY-4.0")
        self.assertEqual(science_packs.is_allowed_oa_license("cc0"), "CC0-1.0")
        self.assertEqual(science_packs.is_allowed_oa_license("CC0-1.0"), "CC0-1.0")

        # Block <!DOCTYPE / <!ENTITY XML entity expansion / XXE attacks
        xxe_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]>
        <article><front><article-meta><permissions><license>CC BY 4.0</license></permissions></article-meta></front>
        <body><sec><title>Results</title><p>&lol2;</p></sec></body></article>"""
        self.assertIsNone(science_packs.parse_jats_article(xxe_xml))

        # Reject CC-BY-4.0 JATS XML when zero author names can be resolved (never emit 'See original publication')
        no_author_ccby = b"""<?xml version="1.0" encoding="UTF-8"?>
        <article>
          <front>
            <article-meta>
              <article-id pub-id-type="doi">10.1000/noauthor</article-id>
              <title-group><article-title>Anonymous Trial</article-title></title-group>
              <permissions>
                <license><license-p>https://creativecommons.org/licenses/by/4.0/</license-p></license>
              </permissions>
              <abstract><p>Body text.</p></abstract>
            </article-meta>
          </front>
        </article>"""
        self.assertIsNone(science_packs.parse_jats_article(no_author_ccby))

    def test_jats_xml_table_wrap_conversion_attribution_and_empty_table_suppression(self):
        from vericorpus import science_packs

        jats_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <article xmlns:xlink="http://www.w3.org/1999/xlink">
          <front>
            <journal-meta><journal-title-group><journal-title>Clinical Oncology Journal</journal-title></journal-title-group></journal-meta>
            <article-meta>
              <article-id pub-id-type="pmcid">PMC1234567</article-id>
              <article-id pub-id-type="doi">10.1000/test.2025.01</article-id>
              <title-group><article-title>Phase 3 PD-1 ADC Trial</article-title></title-group>
              <contrib-group>
                <contrib><name><surname>Lin</surname><given-names>Mei</given-names></name></contrib>
                <contrib><name><surname>Chen</surname><given-names>Wei</given-names></name></contrib>
              </contrib-group>
              <pub-date pub-type="epub"><year>2025</year></pub-date>
              <permissions>
                <license license-type="open-access" xlink:href="https://creativecommons.org/licenses/by/4.0/">
                  <license-p>This is an open access article distributed under CC BY 4.0.</license-p>
                </license>
              </permissions>
              <abstract><p>Median OS improved from 12.1 months to 18.4 months.</p></abstract>
            </article-meta>
          </front>
          <body>
            <sec>
              <title>Methods</title>
              <p>Patients were randomized 1:1 to ADC plus PD-1 vs chemotherapy.</p>
            </sec>
            <sec>
              <title>Results</title>
              <p>Confirmed ORR was 62.5% vs 38.0% (<inline-formula><alternatives><tex-math>\\documentclass[12pt]{minimal}\\begin{document}p &lt; 0.001\\end{document}</tex-math></alternatives></inline-formula>).</p>
              <table-wrap id="Tab1">
                <label>Table 1</label>
                <caption><p>Efficacy outcomes in ITT population<sup>a</sup></p></caption>
                <table>
                  <thead>
                    <tr><th rowspan="1" colspan="1">Subgroup</th><th rowspan="1" colspan="1">Endpoint</th><th rowspan="1" colspan="1">ADC + PD-1</th><th rowspan="1" colspan="1">Chemo</th></tr>
                  </thead>
                  <tbody>
                    <tr><td rowspan="2" colspan="1">ITT</td><td>ORR (%)</td><td>62.5%</td><td>38.0%</td></tr>
                    <tr><td>mOS (mo)</td><td>18.4</td><td>12.1</td></tr>
                  </tbody>
                </table>
              </table-wrap>
              <table-wrap id="Tab2">
                <label>Table 2</label>
                <caption><p>Graphic only table should be skipped</p></caption>
                <graphic xlink:href="fig.jpg"/>
              </table-wrap>
              <table-wrap id="Tab3">
                <label>Table 3</label>
                <caption><p>Empty table should be skipped</p></caption>
                <table><thead><tr><th>A</th><th>B</th></tr></thead><tbody><tr><td></td><td></td></tr></tbody></table>
              </table-wrap>
            </sec>
          </body>
        </article>"""

        parsed = science_packs.parse_jats_article(jats_xml, source_url="https://europepmc.org/article/PMC/PMC1234567")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["license"], "CC-BY-4.0")
        self.assertEqual(parsed["authors"], ["Mei Lin", "Wei Chen"])
        self.assertEqual(parsed["tables_count"], 1)
        md = parsed["markdown"]
        self.assertIn("Mei Lin, Wei Chen", md)
        self.assertIn("https://creativecommons.org/licenses/by/4.0/", md)
        self.assertIn("Adaptation Notice", md)
        self.assertNotIn("See original publication", md)
        self.assertIn("| Subgroup | Endpoint | ADC + PD-1 | Chemo |", md)
        self.assertIn("| ITT | ORR (%) | 62.5% | 38.0% |", md)
        self.assertIn("| ITT | mOS (mo) | 18.4 | 12.1 |", md)
        self.assertNotIn("\\documentclass", md)
        self.assertNotIn("Table 2", md)
        self.assertNotIn("Table 3", md)

    def test_arxiv_html_table_extraction_skips_spacer_and_footnotes(self):
        from vericorpus import science_packs

        html = """
        <html><body>
          <a id="license-tr" href="https://info.arxiv.org/help/license/index.html">License: CC BY 4.0</a>
          <table id="p1.1" class="ltx_tabular">
            <tr><td><span class="ltx_rule"></span></td></tr>
          </table>
          <figure id="S3.T1" class="ltx_table">
            <figcaption class="ltx_caption">Table 1: HotpotQA Benchmark Results</figcaption>
            <table class="ltx_tabular">
              <tr>
                <th>Method<span class="ltx_note ltx_role_footnote"><sup class="ltx_note_mark">1</sup><span class="ltx_note_outer"><span class="ltx_note_content">Long footnote noise should be excluded</span></span></span></th>
                <th>EM</th>
                <th>F1</th>
              </tr>
              <tr><td>Standard</td><td>25.4</td><td>34.1</td></tr>
              <tr><td>ReAct</td><td>32.2</td><td>43.8</td></tr>
            </table>
          </figure>
        </body></html>
        """
        tables = science_packs.extract_arxiv_html_tables(html)
        self.assertEqual(len(tables), 1)
        self.assertIn("Table 1: HotpotQA Benchmark Results", tables[0])
        self.assertIn("| Method | EM | F1 |", tables[0])
        self.assertIn("| ReAct | 32.2 | 43.8 |", tables[0])
        self.assertNotIn("Long footnote noise", tables[0])

    def test_clinicaltrials_v2_formatting_requires_results_and_cc0(self):
        from vericorpus import science_packs

        no_res = {
            "hasResults": False,
            "protocolSection": {"identificationModule": {"nctId": "NCT00000001", "briefTitle": "No Results Trial"}},
        }
        self.assertIsNone(science_packs.clinical_trial_to_markdown(no_res))

        with_res = {
            "hasResults": True,
            "protocolSection": {
                "identificationModule": {"nctId": "NCT04123456", "briefTitle": "Phase 3 Trial of Drug X vs Placebo"},
                "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Example Pharma"}},
                "statusModule": {"overallStatus": "COMPLETED"},
                "designModule": {
                    "studyType": "INTERVENTIONAL",
                    "phases": ["PHASE3"],
                    "enrollmentInfo": {"count": 420, "type": "ACTUAL"},
                },
                "conditionsModule": {"conditions": ["Non-Small Cell Lung Cancer"]},
                "armsInterventionsModule": {
                    "interventions": [{"type": "DRUG", "name": "Drug X"}],
                },
                "descriptionModule": {"briefSummary": "Randomized study evaluating OS."},
            },
            "resultsSection": {
                "outcomeMeasuresModule": {
                    "outcomeMeasures": [
                        {
                            "type": "PRIMARY",
                            "title": "Median Overall Survival",
                            "timeFrame": "Up to 36 months",
                            "unitOfMeasure": "months",
                            "groups": [
                                {"id": "OG000", "title": "Drug X", "description": "200 mg IV Q3W"},
                                {"id": "OG001", "title": "Placebo", "description": "Matched placebo"},
                            ],
                            "classes": [
                                {
                                    "title": "Overall",
                                    "categories": [
                                        {
                                            "measurements": [
                                                {"groupId": "OG000", "value": "21.4", "spread": "2.1"},
                                                {"groupId": "OG001", "value": "14.8", "spread": "1.9"},
                                            ]
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            },
        }
        res = science_packs.clinical_trial_to_markdown(with_res)
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res["license"], "CC0-1.0")
        self.assertEqual(res["nct_id"], "NCT04123456")
        md = res["markdown"]
        self.assertIn("license: CC0-1.0", md)
        self.assertIn("nct_id: NCT04123456", md)
        self.assertIn("| Category / Measure | Drug X | Placebo |", md)
        self.assertIn("21.4", md)
        self.assertIn("14.8", md)

    def test_sci_ai_biomed_eval_30_ccby_attribution_and_exact_offset_grounding(self):
        from vericorpus import eval_e2e_rag

        eval_path = ROOT_DIR / "evals" / "sci_ai_biomed_eval_30.json"
        self.assertTrue(eval_path.is_file(), f"缺少评测集文件: {eval_path}")
        cases = json.loads(eval_path.read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 30)

        ai_cases = [c for c in cases if c.get("track") == "ai_papers" and not c.get("expect_absent")]
        bio_cases = [c for c in cases if c.get("track") == "biomed_clinical" and not c.get("expect_absent")]
        abs_cases = [c for c in cases if c.get("expect_absent") is True]
        self.assertEqual(len(ai_cases), 12)
        self.assertEqual(len(bio_cases), 12)
        self.assertEqual(len(abs_cases), 6)

        ccby_count = 0
        seen_ids: set[str] = set()
        for c in cases:
            cid = c["id"]
            self.assertNotIn(cid, seen_ids)
            seen_ids.add(cid)
            self.assertTrue(str(c.get("question") or "").strip())
            exp = c["expected"]
            doc = str(c.get("oracle_document") or "")

            if "license: CC-BY-4.0" in doc:
                ccby_count += 1
                self.assertNotIn("See original publication", doc, f"{cid} 缺失真实原作者姓名")
                self.assertNotIn("See original paper", doc, f"{cid} 缺失真实原作者姓名")
                self.assertIn("https://creativecommons.org/licenses/by/4.0/", doc, f"{cid} 缺失 CC-BY-4.0 URI")
                self.assertIn("Adaptation Notice", doc, f"{cid} 缺失 CC-BY-4.0 第 3(a) 条改编声明")

            if c.get("expect_absent"):
                self.assertEqual(exp["status"], "ABSENT")
                self.assertIsNone(exp["value"])
                self.assertEqual(exp["evidence"], [])
                sc = eval_e2e_rag.score_output(c, {"status": "ABSENT", "value": None, "evidence": []}, doc)
                self.assertTrue(sc["strict_pass"], f"{cid} ABSENT oracle score failed")
            else:
                self.assertTrue(doc, f"{cid} 缺少 oracle_document")
                self.assertTrue(c.get("expect_path_sub"), f"{cid} 缺少 expect_path_sub")
                self.assertEqual(exp["status"], "ANSWER")
                ev = exp.get("evidence") or []
                self.assertGreaterEqual(len(ev), 1, f"{cid} 缺少 expected.evidence")
                for span in ev:
                    st, ed, qt = span["start"], span["end"], span["quote"]
                    self.assertIsInstance(st, int)
                    self.assertIsInstance(ed, int)
                    self.assertTrue(0 <= st < ed <= len(doc), f"{cid} 偏移越界: {st}:{ed} vs {len(doc)}")
                    self.assertEqual(doc[st:ed], qt, f"{cid} 原文引用不匹配: {doc[st:ed]!r} != {qt!r}")
                mock_pred = {"status": "ANSWER", "value": exp["value"], "evidence": ev}
                sc = eval_e2e_rag.score_output(c, mock_pred, doc)
                self.assertTrue(sc["strict_pass"], f"{cid} ANSWER oracle score failed: {sc}")

        self.assertEqual(ccby_count, 25)


if __name__ == "__main__":
    unittest.main()
