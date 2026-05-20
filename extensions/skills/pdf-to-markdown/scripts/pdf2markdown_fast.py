#!/usr/bin/env python3
"""Convert PDF to Markdown using pdfplumber."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def _ensure_package(package_name: str):
    """Auto-install a missing Python package; exit on failure."""
    try:
        __import__(package_name)
        return
    except ImportError:
        pass

    print(f"[pdf-to-markdown] 缺少依赖: {package_name}，正在自动安装...")

    uv = shutil.which("uv")
    if uv:
        try:
            subprocess.check_call(
                [uv, "pip", "install", package_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"[pdf-to-markdown] 安装完成: {package_name}")
            return
        except subprocess.CalledProcessError:
            pass

    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", package_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"[pdf-to-markdown] 安装完成: {package_name}")
        return
    except Exception:
        pass

    print(f"[pdf-to-markdown] 自动安装失败，请手动执行: pip install {package_name}")
    sys.exit(1)


def extract_table_md(table) -> str:
    """Extract a table and format it as a GitHub-flavored markdown table."""
    rows = table.extract()
    if not rows:
        return ""

    # Use the first row as header
    header = rows[0]
    data_rows = rows[1:] if len(rows) > 1 else []

    def fmt(val):
        return str(val).replace("\n", " ").strip() if val else ""

    lines = []
    # Header
    lines.append("| " + " | ".join(fmt(h) for h in header) + " |")
    # Separator
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    # Data rows
    for row in data_rows:
        # Pad with empty strings if row has fewer cells than header
        cells = [fmt(c) for c in row]
        cells += [""] * (len(header) - len(cells))
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines) + "\n"


def convert_pdf_to_markdown(pdf_path: str, output_path: str | None = None) -> str:
    """Convert a PDF file to markdown text."""
    import pdfplumber

    md_lines: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            md_lines.append(f"\n## Page {i + 1}\n")

            # Extract tables first so we can place them at the right positions
            tables = page.find_tables()
            table_mds: dict[int, str] = {}
            table_bboxes: list[tuple[float, float, float, float]] = []

            for table in tables:
                md = extract_table_md(table)
                if md:
                    table_mds[table.bbox[1]] = md  # key by top y-coordinate
                    table_bboxes.append(table.bbox)

            # Extract text lines grouped by vertical position
            text_lines = []
            for line in page.extract_text_lines():
                text_lines.append(line)

            # Determine which text lines fall inside table regions
            def inside_table(y: float) -> bool:
                for bbox in table_bboxes:
                    if bbox[1] - 5 <= y <= bbox[3] + 5:
                        return True
                return False

            # Group consecutive non-table text into paragraphs
            paragraph: list[str] = []
            prev_y = None

            for line in text_lines:
                y = line["top"]
                text = line["text"].strip()
                if not text:
                    continue

                if inside_table(y):
                    # Flush current paragraph
                    if paragraph:
                        md_lines.append(" ".join(paragraph) + "\n")
                        paragraph = []
                    prev_y = None
                    continue

                if prev_y is not None and abs(y - prev_y) > 10:
                    # Gap detected — end paragraph
                    if paragraph:
                        md_lines.append(" ".join(paragraph) + "\n")
                        paragraph = []
                    paragraph.append(text)
                else:
                    paragraph.append(text)

                prev_y = y

            # Flush remaining paragraph
            if paragraph:
                md_lines.append(" ".join(paragraph) + "\n")

            # Insert tables at the end of each page
            for md in table_mds.values():
                md_lines.append("\n" + md + "\n")

    result = "\n".join(md_lines)
    # Clean up: collapse 3+ newlines into 2
    import re

    result = re.sub(r"\n{3,}", "\n\n", result)

    if output_path:
        Path(output_path).write_text(result, encoding="utf-8")
        print(f"Saved: {output_path}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert PDF to Markdown using pdfplumber"
    )
    parser.add_argument("pdf", help="Path to the input PDF file")
    parser.add_argument(
        "-o", "--output", default=None, help="Output markdown file path"
    )
    args = parser.parse_args()

    _ensure_package("pdfplumber")

    if not Path(args.pdf).exists():
        print(f"Error: file not found: {args.pdf}", file=sys.stderr)
        sys.exit(1)

    if not args.output:
        stem = Path(args.pdf).stem
        args.output = str(Path(args.pdf).parent / f"{stem}.md")

    convert_pdf_to_markdown(args.pdf, args.output)
    print(f"Done: {args.output}")


if __name__ == "__main__":
    main()
