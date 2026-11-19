---
name: build-research-corpus
description: 为多年综合研究生成语料清单。扫描本地年报 Markdown、必要时补一份更新的中期报告，并登记用户放入的外部材料。只写路径、类型和哈希，不分析内容。
---

# 语料清单

这个 skill 只做登记。它不下载、不转写、不抽取、不下结论。

## 执行

优先 `run_python_script`（cwd=项目根）。路径用相对路径和 `/`。禁止 `cd`。禁止打开年报或证据包正文。

```text
run_python_script(
  script_path="extensions/skills/build-research-corpus/scripts/build_corpus.py",
  argv=["--code", "600519", "--start-year", "2023", "--end-year", "2025"]
)
```

标准输出是一行 JSON。以它为准，不要再探目录。

## 清单里有什么

写入 `data/research/{code}/corpus.json`：

- 年份范围内的年报 Markdown（`data/reports/md/{code}/` 或 `data/reports/{code}/2_markdown/`）
- 若已有年报，且磁盘上还有**更晚**的一份半年报或季报，则额外登记这一份，`supplement=true`
- `data/research/{code}/sources/` 下用户放入的 `.md` / `.txt`，`trust=third_party`
- 每份材料的路径、同级章节索引路径、`sha256`、证据包路径、`evidence_status`（`current` / `stale` / `missing`）
- `missing_annual_years`：范围内还没有年报 Markdown 的年份

证据包在 `data/research/{code}/evidence/{doc_id}.md`。只有证据包前 40 行里的 `source_sha256` 与源文件一致时，状态才是 `current`。

## 返回

向调用方只报告：`corpus_path`、文档数、`missing_annual_years`、`needs_extract`、`needs_index`。不要复述材料内容。
