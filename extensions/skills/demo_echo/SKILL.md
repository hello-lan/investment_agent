---
name: demo_echo
description: 回显输入参数，便于验证 skill 调用链是否生效
tools:
  - local_script
entry: scripts/run.py
---

# Demo Echo

用于快速验证：
- skill 是否被 loader 扫描到
- agent 是否正确挂载了 skill
- chat 中是否能够调用并返回脚本输出
