import json
import sys


def main() -> None:
    raw = sys.stdin.read().strip() or "{}"
    params = json.loads(raw)

    topic = str(params.get("topic", "未命名主题"))
    audience = str(params.get("audience", "通用读者"))
    bullets = int(params.get("bullets", 3) or 3)
    bullets = max(1, min(bullets, 6))

    lines = [
        f"## {topic} 简报",
        f"目标读者：{audience}",
        "",
        "### 要点",
    ]

    for i in range(1, bullets + 1):
        lines.append(f"- 要点 {i}：围绕“{topic}”的第 {i} 条观察。")

    lines.extend([
        "",
        "### 结论",
        f"{topic} 当前可继续跟踪，建议结合更多一手数据做进一步判断。",
    ])

    print("\n".join(lines))


if __name__ == "__main__":
    main()
