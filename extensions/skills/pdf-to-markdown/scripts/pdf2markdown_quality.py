import argparse
import os
import shutil
import subprocess
import sys


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


def pdf2markdown(src_path: str, target_path: str) -> None:
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    result = converter.convert(src_path)
    markdown_output = result.document.export_to_markdown()
    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
    with open(target_path, "w") as f:
        f.write(markdown_output)


def main():
    ap = argparse.ArgumentParser(description="将 PDF 文件转换为 Markdown 格式")
    ap.add_argument("pdf", help="待转换的 PDF 文件路径")
    ap.add_argument("-o", "--output", default=None, help="转换结果保存路径（默认与 PDF 同目录同名 .md）")
    args = ap.parse_args()

    _ensure_package("docling")

    input_file = args.pdf
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
