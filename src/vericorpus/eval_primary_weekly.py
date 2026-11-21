"""一级市场硬科技招股书(12家) + 开源中文 AI 工程文档(Apache-2.0) 32 题隔离 XERJ 对比评测与报告生成器。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from . import compliance, eval_hub, ipo_prospectus, query_cn

PREFIX_PATHS = {
    "secipo": ("data", "raw", "sec-ipo-prospectus-pack"),
    "hkipo": ("data", "raw", "cn-hk-ipo-prospectus-recipe", "hkex"),
    "cnipo": ("data", "raw", "cn-hk-ipo-prospectus-recipe", "cninfo"),
    "cngh": ("data", "raw", "cn-github-stars"),
}


def run_primary_and_weekly_eval(repo_root: str | Path, port: int | None = None) -> dict[str, Any]:
    root = Path(repo_root)
    audited = compliance.audit_corpora_dir(root / "corpora")
    if port is None:
        port = eval_hub._find_free_port_triplet(19710)

    tmp_root = Path(tempfile.mkdtemp(prefix="vericorpus-primary-eval-"))
    tmp_data = tmp_root / "data"
    tmp_state = tmp_root / "state"
    for d in (tmp_data, tmp_state):
        d.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ, XERJ_DISABLE_FEEDBACK="true", XERJ_DISABLE_QUERY_CACHE="1")
    base_url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [
            eval_hub.XERJ_BIN,
            "--bind",
            "127.0.0.1",
            "--port",
            str(port),
            "--data-dir",
            str(tmp_data),
            "--insecure",
            "--disable-feedback",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    try:
        for _ in range(60):
            if proc.poll() is not None:
                err = proc.stderr.read() if proc.stderr else ""
                raise RuntimeError(f"隔离 XERJ 启动失败 rc={proc.returncode}: {err.strip()}")
            try:
                with compliance._safe_urlopen(f"{base_url}/", timeout=1, allow_localhost_http=True) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(0.15)
        else:
            raise RuntimeError("隔离 XERJ 启动超时")

        indexed_stats: dict[str, Any] = {}
        for prefix, rel_parts in PREFIX_PATHS.items():
            folder = root.joinpath(*rel_parts)
            if not folder.is_dir():
                indexed_stats[prefix] = {"files": 0, "elapsed_ms": 0.0, "chunks": 0}
                continue
            t0 = time.perf_counter()
            p = subprocess.run(
                [
                    eval_hub.XERJ_BIN,
                    "autoindex",
                    str(folder),
                    "--url",
                    base_url,
                    "--prefix",
                    prefix,
                    "--state-dir",
                    str(tmp_state),
                    "--no-graph",
                    "--fresh",
                    "--yes",
                    "--disable-feedback",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=180,
            )
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            if p.returncode not in (0, 3):
                raise RuntimeError(f"autoindex {prefix} 失败 rc={p.returncode}: {p.stderr or p.stdout}")
            file_cnt = len(list(folder.rglob("*.md")))
            indexed_stats[prefix] = {"files": file_cnt, "elapsed_ms": elapsed_ms}

        with compliance._safe_urlopen(f"{base_url}/_cat/indices?format=json", timeout=5, allow_localhost_http=True) as r:
            cat_rows = json.loads(r.read().decode("utf-8"))
        for row in cat_rows:
            idx_name = str(row.get("index") or "")
            for pfx in PREFIX_PATHS:
                if idx_name.startswith(pfx + "-"):
                    indexed_stats[pfx]["chunks"] = indexed_stats[pfx].get("chunks", 0) + int(row.get("docs.count") or 0)

        cases = json.loads((root / "evals" / "primary_market_and_weekly_eval_32.json").read_text(encoding="utf-8"))
        results: list[dict[str, Any]] = []
        base_top1 = base_top3 = base_abs = 0
        cn_top1 = cn_top3 = cn_abs = 0
        in_domain_total = sum(1 for c in cases if not c.get("expect_absent"))
        absent_total = len(cases) - in_domain_total

        for c in cases:
            q = c["query"]
            pfx = c["prefix"]
            b = eval_hub._baseline_search(base_url, pfx, q, limit=5)
            x = query_cn.search_index(base_url, pfx, q, limit=5, scope="docs")

            if c.get("expect_absent"):
                b_ok = b["total"] == 0
                x_ok = x["total"] == 0
                base_abs += int(b_ok)
                cn_abs += int(x_ok)
                results.append(
                    {
                        "id": c["id"],
                        "prefix": pfx,
                        "category": c["category"],
                        "query": q,
                        "expect_absent": True,
                        "baseline": {"total": b["total"], "top": b["hits"][0]["path"] if b["hits"] else "-", "ok": b_ok},
                        "vericorpus": {"total": x["total"], "top": x["hits"][0]["path"] if x["hits"] else "-", "ok": x_ok},
                    }
                )
            else:
                sub = c["expect_path_sub"].lower()

                def eval_hits(hits: list[dict[str, Any]]) -> tuple[bool, bool, str]:
                    if not hits:
                        return False, False, "-"
                    matched_idx = [i for i, h in enumerate(hits) if sub in str(h.get("path") or "").lower()]
                    top1 = 0 in matched_idx
                    top3 = any(i < 3 for i in matched_idx)
                    return top1, top3, str(hits[0].get("path") or "-")

                b_t1, b_t3, b_path = eval_hits(b["hits"])
                x_t1, x_t3, x_path = eval_hits(x["hits"])
                base_top1 += int(b_t1)
                base_top3 += int(b_t3)
                cn_top1 += int(x_t1)
                cn_top3 += int(x_t3)
                results.append(
                    {
                        "id": c["id"],
                        "prefix": pfx,
                        "category": c["category"],
                        "query": q,
                        "expect_absent": False,
                        "baseline": {"total": b["total"], "top1": b_t1, "top3": b_t3, "top_path": b_path},
                        "vericorpus": {"total": x["total"], "top1": x_t1, "top3": x_t3, "top_path": x_path, "relaxed": x["relaxed"]},
                    }
                )

        dobot_dir = ipo_prospectus._resolve_dobot_dir(root)
        dobot_cmp = ipo_prospectus.compare_dobot_txt_vs_rebuilt(
            dobot_dir / "04-可检索文本",
            root / "data" / "raw" / "cn-hk-ipo-prospectus-recipe" / "hkex" / "02432",
        )
        return {
            "audited_corpora": len(audited),
            "indexed": indexed_stats,
            "summary": {
                "in_domain_total": in_domain_total,
                "absent_total": absent_total,
                "baseline_top1": base_top1,
                "baseline_top3": base_top3,
                "baseline_absent_ok": base_abs,
                "vericorpus_top1": cn_top1,
                "vericorpus_top3": cn_top3,
                "vericorpus_absent_ok": cn_abs,
            },
            "dobot_compare": dobot_cmp,
            "cases": results,
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        shutil.rmtree(tmp_root, ignore_errors=True)


def write_primary_eval_report(repo_root: str | Path, report: dict[str, Any]) -> Path:
    root = Path(repo_root)
    s = report["summary"]
    d = report["dobot_compare"]
    in_tot = s["in_domain_total"]
    abs_tot = s["absent_total"]

    lines = [
        "# VeriCorpus 一级市场硬科技招股书与开源工程文档实测报告 (`PRIMARY_EVAL_REPORT.md`)",
        "",
        "> Not Legal, Investment, or Medical Advice — strictly for retrieval benchmarking and document verification research.",
        ">",
        "> 全部评测数据均在同一隔离本地 `xerj` 进程（`XERJ_DISABLE_QUERY_CACHE=1`）实测产生，未触碰线上个人索引。",
        "",
        "## 1. 隔离建索与合规资产总览",
        "",
        f"- **仓库 Manifest 合规通过数**：`{report['audited_corpora']}` 个语料目录全部通过 `compliance.audit_corpora_dir` 校验",
        "",
        "| 索引前缀 | 语料轨道 | 版权模式 | 收录文件数 | XERJ 分块数 | 建索耗时 (ms) |",
        "|---|---|---|---:|---:|---:|",
        f"| `secipo` | SEC 5 家硬科技招股书+年报 (`ALAB/CRDO/CRWV/ARM/SPCX`) | `pack` (`SEC-Public-Filing`) | {report['indexed']['secipo']['files']} | {report['indexed']['secipo'].get('chunks', 0)} | {report['indexed']['secipo']['elapsed_ms']} |",
        f"| `hkipo` | 港股 18C 4 家 (`02533/09660/ZHIPU/02432`) | `recipe` (`HKEX-Public-Disclosure`) | {report['indexed']['hkipo']['files']} | {report['indexed']['hkipo'].get('chunks', 0)} | {report['indexed']['hkipo']['elapsed_ms']} |",
        f"| `cnipo` | 科创板 3 家含问询回复 (`688041/688498/688295`) | `recipe` (`CNINFO-Public-Disclosure`) | {report['indexed']['cnipo']['files']} | {report['indexed']['cnipo'].get('chunks', 0)} | {report['indexed']['cnipo']['elapsed_ms']} |",
        f"| `cngh` | 5 座高星中文 AI 工程仓库文档 (`ragflow/PaddleOCR/LLaMA-Factory/Chatchat/self-llm`) | `pack` (`Apache-2.0`) | {report['indexed']['cngh']['files']} | {report['indexed']['cngh'].get('chunks', 0)} | {report['indexed']['cngh']['elapsed_ms']} |",
        "",
        "## 2. 32 题隔离 XERJ 对比结果（Native Baseline vs `vericorpus.query_cn`）",
        "",
        "| 指标 | XERJ 原生基线 | `vericorpus` 中文+繁简+双语增强 |",
        "|---|---:|---:|",
        f"| 域内真值题 Top-1 准确率 ({in_tot} 题) | {s['baseline_top1']}/{in_tot} ({s['baseline_top1']/in_tot*100:.1f}%) | **{s['vericorpus_top1']}/{in_tot} ({s['vericorpus_top1']/in_tot*100:.1f}%)** |",
        f"| 域内真值题 Top-3 召回率 ({in_tot} 题) | {s['baseline_top3']}/{in_tot} ({s['baseline_top3']/in_tot*100:.1f}%) | **{s['vericorpus_top3']}/{in_tot} ({s['vericorpus_top3']/in_tot*100:.1f}%)** |",
        f"| 严格缺失证据拒答率 (0 命中 / {abs_tot} 题) | {s['baseline_absent_ok']}/{abs_tot} ({s['baseline_absent_ok']/abs_tot*100:.1f}%) | **{s['vericorpus_absent_ok']}/{abs_tot} ({s['vericorpus_absent_ok']/abs_tot*100:.1f}%)** |",
        "",
        "## 3. 越疆机器人 (`02432.HK`) 纯文本导出 vs `pdf_table_fix` 坐标重建对比",
        "",
        "| 指标 | 纯文本导出 (`pypdfium2`) | 几何坐标重建 Markdown (`pdf_table_fix`) |",
        "|---|---:|---:|",
        f"| 文档份数 | {d['txt_files']} | {d['md_files']} |",
        f"| 提取总字符数 | {d['txt_chars']:,} | {d['md_chars']:,} |",
        f"| 结构化 Markdown 管道表格行 (`| ... |`) | {d['txt_pipe_rows']} | **{d['md_pipe_rows']}** |",
        f"| 顺序页码锚点 (`<!-- page: p/N -->`) | 0 (非结构化页号) | **{d['md_page_anchors']}** |",
        f"| Unicode 乱码替换符 `\\ufffd` / CMap 异常 `尸` 日期 | {d['txt_replacement_chars']} / - | **{d['md_replacement_chars']} / {d['md_bad_shi_dates']}** |",
        "",
        "## 4. 逐题实测明细",
        "",
        "| ID | 轨道 | 类别 | 查询语句 | 基线 Top-1 | `vericorpus` Top-1 | 判定 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in report["cases"]:
        if r["expect_absent"]:
            b_str = f"hits={r['baseline']['total']}"
            x_str = f"hits={r['vericorpus']['total']}"
            ok_str = "PASS (0-hit)" if r["vericorpus"]["ok"] else "FAIL"
        else:
            b_str = f"{'✅' if r['baseline']['top1'] else '❌'} `{r['baseline']['top_path']}`"
            x_str = f"{'✅' if r['vericorpus']['top1'] else '❌'} `{r['vericorpus']['top_path']}`"
            ok_str = "PASS" if r["vericorpus"]["top1"] else ("TOP3" if r["vericorpus"]["top3"] else "MISS")
        lines.append(f"| {r['id']} | `{r['prefix']}` | {r['category']} | {r['query']} | {b_str} | {x_str} | {ok_str} |")

    out_path = root / "PRIMARY_EVAL_REPORT.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


if __name__ == "__main__":
    repo = Path(__file__).resolve().parents[2]
    rep = run_primary_and_weekly_eval(repo)
    md_path = write_primary_eval_report(repo, rep)
    print("SUMMARY:", json.dumps(rep["summary"], ensure_ascii=False))
    print("REPORT_WRITTEN:", md_path)
