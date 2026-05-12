import argparse
import os
import sys

from docling.document_converter import DocumentConverter


def pdf2markdown(src_path: str, target_path: str) -> None:
    converter = DocumentConverter()
    result = converter.convert(src_path)
    markdown_output = result.document.export_to_markdown()
    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
    with open(target_path, "w") as f:
        f.write(markdown_output)


def main():
    ap = argparse.ArgumentParser(description="将 PDF 文件转换为 Markdown 格式")
    ap.add_argument("-i", "--input", required=True, help="待转换的 PDF 文件路径")
    ap.add_argument("-o", "--output", default=None, help="转换结果保存路径（默认与 PDF 同目录同名 .md）")
    args = ap.parse_args()

    input_file = args.input
    output_file = args.output

    if not os.path.exists(input_file):
        print(f"错误：文件不存在 - {input_file}")
        sys.exit(1)

    if output_file is None:
        base = os.path.splitext(os.path.basename(input_file))[0]
        output_dir = os.path.dirname(input_file) or "."
        output_file = os.path.join(output_dir, f"{base}.md")

    print(f"正在将 {input_file} 转换为 Markdown 格式，结果将保存到 {output_file}")
    pdf2markdown(input_file, output_file)
    print(f"转换完成：{input_file} -> {output_file}")


if __name__ == "__main__":
    main()
