---
name: build-announcement-timeline
description: 拉取 A 股公告标题时间线，覆盖并购、担保诉讼、处罚、股权激励、增减持、业绩预告、再融资与回购。只记录日期、类别、标题和链接，不下载公告正文。
---

# 公告时间线

这个 skill 只跑脚本。失败时脚本仍会写出「公告缺失」，研究可以继续。

## 执行

优先 `run_python_script`（cwd=项目根）。禁止 `cd`。禁止下载或阅读公告 PDF。

```text
run_python_script(
  script_path="extensions/skills/build-announcement-timeline/scripts/build_events.py",
  argv=["--code", "600519", "--start-year", "2023", "--end-year", "2025"],
  timeout_seconds=90
)
```

输出文件：`data/research/{code}/events.md`。标准输出是一行 JSON：`status` 为 `ok` 或 `missing`，以及 `events_path` 和 `count`。

时间范围从起始年 1 月 1 日到运行当天。最多保留 40 条标题。定期报告标题会被丢掉，避免和年报材料重复。

## 返回

只报告路径、状态和条数。不要根据标题发挥结论。
