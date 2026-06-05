"""上下文卸载机制：将大体积 tool_result 写入临时文件，替换为摘要+路径占位符。

Agent 看到占位符后可通过 run_command: cat 文件路径 重新加载原始内容。
卸载目录位于项目 data/.offload/ 下（AccessPolicy 允许读写）。

摘要策略（通过 summary_strategy 配置）：
- "truncate": 取前 N 字符（默认，零成本）
- "local": 通用抽取式摘要（5 维打分，领域无关）
- "llm": 调用 LLM 生成语义摘要（高质量，有额外 token 消耗）
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from typing import TYPE_CHECKING

from ..constants import OffloadSummaryStrategy

if TYPE_CHECKING:
    from ..core.provider import ModelProvider

_log = logging.getLogger(__name__)


# ── 通用停用词（中英文，领域无关）──────────────────────────────────────
_STOPWORDS = frozenset(
    "的是 在了 是有 也不 就是 而且 但是 因为 所以 如果 虽然 然后 "
    "可以 这个 那个 我们 他们 它们 什么 怎么 已经 还是 或者 "
    "以及 关于 通过 对于 进行 其中 此外 另外 没有 不是 而是 "
    "这些 那些 自己 其他 一些 这样 那样 一个 每个 之后 之前 "
    "不会 不能 应该 需要 使用 用于 目前 当前 主要 基本 一般 "
    "the and for are but not you all any had her was one our "
    "will has been have from they with that this would were your "
    "can may its his its out been than then into some such only "
    "also very after before just each which their there when what".split()
)

# ── 通用话语标记词（总结/转折/因果，领域无关）─────────────────────────
_DISCOURSE_MARKERS = (
    "总结", "综上", "结论", "总之", "因此", "所以", "可见",
    "关键", "核心", "重要", "注意", "发现", "结果", "概述",
    "summary", "conclusion", "result", "key", "important", "note",
    "overall", "therefore", "thus", "findings",
)

# ── LLM 摘要系统提示 ─────────────────────────────────────────────────
_SUMMARIZE_SYSTEM = (
    "用 1-2 句话概括以下工具输出内容的核心信息，保留关键数字和结论。"
    "中文输出，不要添加解释。"
)


class ContextOffloader:
    """将大体积 tool_result 内容卸载到临时文件，替换为摘要+路径占位符。

    卸载目录位于项目 data/.offload/ 下，
    因为 AccessPolicy 会阻止 agent 通过 run_command 访问项目目录之外的路径。
    """

    def __init__(
        self,
        offload_dir: str,
        threshold: int = 800,
        summary_strategy: str = OffloadSummaryStrategy.TRUNCATE,
        summary_chars: int = 200,
        provider: "ModelProvider | None" = None,
    ):
        self._dir = offload_dir
        self._threshold = threshold
        self._summary_strategy = summary_strategy
        self._summary_chars = summary_chars
        self._provider = provider
        self._counter = 0
        self._llm_tokens_used = 0
        os.makedirs(offload_dir, exist_ok=True)

    def should_offload(self, content: str) -> bool:
        """判断内容是否需要卸载：超过阈值且尚未卸载。"""
        return (
            len(content) > self._threshold
            and not content.startswith("[上下文已卸载")
        )

    async def offload(self, content: str) -> str:
        """卸载内容到文件，返回占位符文本。async 以支持 llm 摘要策略。"""
        self._counter += 1
        ext = ".md" if len(content) > 5000 else ".txt"
        filename = f"tr_{self._counter:03d}{ext}"
        filepath = os.path.join(self._dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        summary = await self._generate_summary(content)
        _log.debug(
            "[Offload] %s → %s (%d chars, strategy=%s)",
            filename, filepath, len(content), self._summary_strategy,
        )
        return (
            f"[上下文已卸载 → {filepath} "
            f"(原始 {len(content):,} 字符)]\n"
            f"摘要: {summary}"
        )

    async def _generate_summary(self, content: str) -> str:
        """根据策略生成摘要。"""
        if self._summary_strategy == OffloadSummaryStrategy.LLM and self._provider:
            return await self._summarize_llm(content)
        elif self._summary_strategy == OffloadSummaryStrategy.LOCAL:
            return self._summarize_local(content)
        else:
            return self._summarize_truncate(content)

    # ── 策略 1：截断（默认，零成本）─────────────────────────────────────

    def _summarize_truncate(self, content: str) -> str:
        """取前 N 个字符，零延迟零成本。"""
        return content[:self._summary_chars].replace("\n", " ").strip()

    # ── 策略 2：通用抽取式摘要（5 维打分，领域无关）──────────────────────

    def _summarize_local(self, content: str) -> str:
        """通用抽取式摘要：分句 → 5 维打分 → 取 top-K → 按原文顺序拼接。

        打分维度（全部领域无关）：
        - 位置 (0.30): 首句/末句权重高
        - 词频覆盖 (0.30): 句中"文档高频内容词"占比
        - 结构信息密度 (0.20): 含数字/日期/百分比/路径
        - 话语标记 (0.10): 含总结/转折/因果标记词
        - 句长适中 (0.10): 15-120 字符信息密度最优
        """
        max_chars = self._summary_chars
        sentences = re.split(r'(?<=[。！？\n.!?])', content)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 5]
        if not sentences:
            return content[:max_chars].replace("\n", " ")

        # 提取全文内容词并统计词频
        all_words = self._extract_content_words(content)
        word_freq: dict[str, int] = {}
        for w in all_words:
            word_freq[w] = word_freq.get(w, 0) + 1
        # 仅保留出现 >= 2 次的词作为文档级重要概念
        important_words = {w for w, c in word_freq.items() if c >= 2}

        n = len(sentences)
        scored = []
        for i, s in enumerate(sentences):
            score = 0.0

            # 位置 (0.30)
            if i == 0:
                score += 0.30
            elif i == 1:
                score += 0.15
            if i >= n - 1 and n > 1:
                score += 0.20
            elif i >= n * 0.8:
                score += 0.10

            # 词频覆盖 (0.30)
            s_words = self._extract_content_words(s)
            if s_words:
                hits = sum(1 for w in s_words if w in important_words)
                score += 0.30 * (hits / len(s_words))

            # 结构信息密度 (0.20)
            structural = sum([
                bool(re.search(r'\d', s)),                      # 含数字
                bool(re.search(r'\d{4}[-/年]', s)),              # 日期
                bool(re.search(r'%|％', s)),                     # 百分比
                bool(re.search(r'[a-zA-Z_/]+\.[a-z]{2,}', s)),  # 文件路径/URL
            ])
            score += 0.20 * min(structural / 2, 1.0)

            # 话语标记 (0.10)
            s_lower = s.lower()
            if any(m in s_lower for m in _DISCOURSE_MARKERS):
                score += 0.10

            # 句长适中 (0.10)
            slen = len(s)
            if 15 <= slen <= 120:
                score += 0.10

            scored.append((score, i, s))

        k = max(2, max_chars // 40)
        top = sorted(scored, key=lambda x: -x[0])[:k]
        top_ordered = sorted(top, key=lambda x: x[1])  # 按原文顺序
        return " ".join(s for _, _, s in top_ordered)[:max_chars]

    @staticmethod
    def _extract_content_words(text: str) -> list[str]:
        """提取内容词（无分词库，中英文通用）。

        中文：连续 2+ 个汉字的片段（覆盖术语、名词、动词）
        英文：3+ 字母的单词
        过滤通用停用词
        """
        zh_words = re.findall(r'[一-鿿]{2,}', text)
        en_words = re.findall(r'[a-zA-Z]{3,}', text)
        words = [w.lower() for w in zh_words + en_words]
        return [w for w in words if w not in _STOPWORDS]

    # ── 策略 3：LLM 语义摘要 ──────────────────────────────────────────

    async def _summarize_llm(self, content: str) -> str:
        """调用 LLM 生成语义摘要，失败 fallback 到 truncate。"""
        try:
            resp = await self._provider.chat(
                messages=[{"role": "user", "content": content[:4000]}],
                system=_SUMMARIZE_SYSTEM,
                max_tokens=150,
                temperature=0.2,
            )
            self._llm_tokens_used += resp.input_tokens + resp.output_tokens
            return resp.content.strip()[:self._summary_chars]
        except Exception:
            _log.warning("LLM summary failed, falling back to truncate", exc_info=True)
            return self._summarize_truncate(content)

    # ── 清理 ──────────────────────────────────────────────────────────

    def cleanup(self):
        """删除卸载临时目录。"""
        shutil.rmtree(self._dir, ignore_errors=True)
