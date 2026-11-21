"""防止标的级科学/临床语料定向采集脚本混入 -NC/-ND/非排他许可、漏写 ticker/DOI/NCT 溯源头、或越界写入私人/配方目录。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
SCRIPTS_DIR = ROOT_DIR / "scripts"
for p in (SRC_DIR, SCRIPTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


class WatchlistScienceSyncTests(unittest.TestCase):
    def test_sync_watchlist_enforces_license_firewall_and_frontmatter(self):
        import sync_watchlist_science as sws

        ctgov_payload = {
            "studies": [
                {
                    "hasResults": True,
                    "protocolSection": {
                        "identificationModule": {"nctId": "NCT99887766", "briefTitle": "Moderna mRNA Trial"},
                        "statusModule": {"overallStatus": "COMPLETED"},
                        "designModule": {"studyType": "INTERVENTIONAL", "phases": ["PHASE3"], "enrollmentInfo": {"count": 120}},
                        "sponsorCollaboratorsModule": {"leadSponsor": {"name": "ModernaTX, Inc."}},
                        "conditionsModule": {"conditions": ["Respiratory Virus"]},
                        "armsInterventionsModule": {"interventions": [{"type": "BIOLOGICAL", "name": "mRNA-1345"}]},
                        "descriptionModule": {"briefSummary": "Phase 3 randomized efficacy trial."},
                    },
                    "resultsSection": {
                        "outcomeMeasuresModule": {
                            "outcomeMeasures": [
                                {
                                    "type": "PRIMARY",
                                    "title": "Vaccine Efficacy",
                                    "timeFrame": "Day 180",
                                    "unitOfMeasure": "Events",
                                    "groups": [{"id": "OG000", "title": "mRNA-1345"}, {"id": "OG001", "title": "Placebo"}],
                                    "classes": [
                                        {
                                            "categories": [
                                                {
                                                    "title": "Cases",
                                                    "measurements": [
                                                        {"groupId": "OG000", "value": "9"},
                                                        {"groupId": "OG001", "value": "41"},
                                                    ],
                                                }
                                            ]
                                        }
                                    ],
                                }
                            ]
                        }
                    },
                }
            ]
        }

        good_jats = b"""<?xml version="1.0" encoding="UTF-8"?>
        <article xmlns:xlink="http://www.w3.org/1999/xlink">
          <front>
            <article-meta>
              <article-id pub-id-type="pmcid">PMC7770001</article-id>
              <article-id pub-id-type="doi">10.1000/mrna.2025.1</article-id>
              <title-group><article-title>Moderna Clinical Assay Validation</article-title></title-group>
              <contrib-group><contrib><name><surname>Lin</surname><given-names>Kai</given-names></name></contrib></contrib-group>
              <permissions>
                <license license-type="open-access" xlink:href="https://creativecommons.org/licenses/by/4.0/">
                  <license-p>CC BY 4.0</license-p>
                </license>
              </permissions>
              <abstract><p>Summary of mRNA trial.</p></abstract>
            </article-meta>
          </front>
          <body>
            <sec><title>Results</title>
              <table-wrap id="T1"><label>Table 1</label><caption><p>Arm summary</p></caption>
                <table><thead><tr><th>Arm</th><th>Rate</th></tr></thead><tbody><tr><td>mRNA</td><td>83.7%</td></tr></tbody></table>
              </table-wrap>
            </sec>
          </body>
        </article>"""

        nc_jats = b"""<?xml version="1.0" encoding="UTF-8"?>
        <article xmlns:xlink="http://www.w3.org/1999/xlink">
          <front>
            <article-meta>
              <article-id pub-id-type="pmcid">PMC7770002</article-id>
              <title-group><article-title>Restricted NC Paper</article-title></title-group>
              <permissions>
                <license license-type="open-access" xlink:href="https://creativecommons.org/licenses/by-nc/4.0/">
                  <license-p>CC BY-NC 4.0</license-p>
                </license>
              </permissions>
            </article-meta>
          </front>
          <body><sec><title>Results</title><p>Should be rejected.</p></sec></body>
        </article>"""

        openalex_payload = {
            "results": [
                {
                    "id": "https://openalex.org/W1002",
                    "doi": "https://doi.org/10.48550/arxiv.2401.99999",
                    "title": "Restricted arXiv Paper",
                    "publication_year": 2024,
                    "cited_by_count": 50,
                    "primary_location": {"license": "cc-by-nc", "landing_page_url": "https://arxiv.org/abs/2401.99999"},
                    "abstract_inverted_index": {"Blocked": [0]},
                },
                {
                    "id": "https://openalex.org/W1001",
                    "doi": "https://doi.org/10.48550/arxiv.2407.10671",
                    "title": "Qwen2 Technical Report",
                    "publication_year": 2024,
                    "cited_by_count": 900,
                    "authorships": [{"author": {"display_name": "An Yang"}}, {"author": {"display_name": "Baosong Yang"}}],
                    "primary_location": {"license": "cc-by", "landing_page_url": "https://arxiv.org/abs/2407.10671"},
                    "abstract_inverted_index": {"Qwen2": [0], "models": [1]},
                },
            ]
        }

        def fake_get_json(url: str, timeout: float = 20.0):
            if "clinicaltrials.gov" in url:
                return ctgov_payload
            if "europepmc.org" in url or "ebi.ac.uk" in url:
                return {"resultList": {"result": [{"pmcid": "PMC7770002"}, {"pmcid": "PMC7770001"}]}}
            if "api.openalex.org" in url:
                return openalex_payload
            return {}

        def fake_get_bytes(url: str, timeout: float = 15.0):
            if "PMC7770002" in url:
                return nc_jats
            if "PMC7770001" in url:
                return good_jats
            return b""

        def fake_get_text(url: str, timeout: float = 15.0):
            if "arxiv.org/abs/2407.10671" in url:
                return '<div class="abs-license"><a href="http://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a></div>'
            if "arxiv.org/html/2407.10671" in url:
                return (
                    '<a id="license-tr" href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>'
                    "<figure class='ltx_table'><figcaption>Table 1: Qwen2 Benchmark</figcaption>"
                    "<table><tr><th>Model</th><th>MMLU</th></tr>"
                    "<tr><td>Qwen2-72B</td><td>84.2</td></tr>"
                    "<tr><td>Qwen2-7B</td><td>70.3</td></tr></table>"
                    "</figure>"
                )
            return ""

        with tempfile.TemporaryDirectory() as td:
            out_root = Path(td)
            res = sws.sync_watchlist_science(
                out_root=out_root,
                tickers=["MRNA", "BABA"],
                per_target_limit=1,
                fetch_json_fn=fake_get_json,
                fetch_bytes_fn=fake_get_bytes,
                fetch_text_fn=fake_get_text,
            )
            self.assertGreaterEqual(res["written"], 3)
            self.assertGreaterEqual(res["rejected_non_compliant"], 2)

            biomed_files = list((out_root / "biomed-clinical-ccby").glob("wl_MRNA_*.md"))
            self.assertEqual(len(biomed_files), 2)  # 1 ClinicalTrials CC0 + 1 EPMC CC-BY; NC rejected
            for bf in biomed_files:
                txt = bf.read_text(encoding="utf-8")
                self.assertIn("ticker: MRNA", txt)
                self.assertIn("corpus: biomed-clinical-ccby", txt)
                self.assertTrue("license: CC0-1.0" in txt or "license: CC-BY-4.0" in txt)
                self.assertNotIn("PMC7770002", txt)

            ai_files = list((out_root / "ai-papers-ccby").glob("wl_BABA_*.md"))
            self.assertEqual(len(ai_files), 1)
            ai_txt = ai_files[0].read_text(encoding="utf-8")
            self.assertIn("ticker: BABA", ai_txt)
            self.assertIn("license: CC-BY-4.0", ai_txt)
            self.assertIn("84.2", ai_txt)
            self.assertNotIn("Watchlist", ai_txt)
            self.assertIn("https://creativecommons.org/licenses/by/4.0/", ai_txt)


if __name__ == "__main__":
    unittest.main()
