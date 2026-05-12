---
name: demo_brief_report
description: 根据主题生成一段简短结构化报告，便于验证多参数输入
tools:
  - local_script
entry: scripts/run.py
---

# Demo Brief Report

输入参数示例：
- topic: "新能源车"
- audience: "投资经理"
- bullets: 3

脚本会输出一个简短 Markdown 报告。
