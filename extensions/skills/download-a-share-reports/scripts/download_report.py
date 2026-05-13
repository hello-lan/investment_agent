"""
A股上市公司财报下载工具（多数据源，自动切换）
按优先级尝试：巨潮资讯网 → 东方财富 → 新浪财经
"""

import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

DEFAULT_SAVE_DIR = str(Path(tempfile.gettempdir()) / "financial_reports")

from sources import CninfoSpider, EastmoneySpider, SinaSpider, SOURCE_PRIORITY


# ==================== 股票名称映射表 ====================

STOCK_NAME_MAP: dict[str, str] = {
    # --- 白酒 ---
    "茅台": "600519", "贵州茅台": "600519",
    "五粮液": "000858", "宜宾五粮液": "000858",
    "泸州老窖": "000568", "老窖": "000568",
    "山西汾酒": "600809", "汾酒": "600809",
    "洋河股份": "002304", "洋河": "002304",
    "古井贡酒": "000596", "古井": "000596",
    "舍得酒业": "600702", "舍得": "600702",
    "酒鬼酒": "000799",
    # --- 新能源/电池 ---
    "宁德时代": "300750", "宁德": "300750",
    "比亚迪": "002594",
    "亿纬锂能": "300014",
    "阳光电源": "300274",
    "隆基绿能": "601012", "隆基": "601012",
    "通威股份": "600438", "通威": "600438",
    "天齐锂业": "002466",
    "赣锋锂业": "002460",
    # --- 银行 ---
    "招商银行": "600036", "招行": "600036",
    "工商银行": "601398", "工行": "601398",
    "建设银行": "601939", "建行": "601939",
    "农业银行": "601288", "农行": "601288",
    "中国银行": "601988", "中行": "601988",
    "兴业银行": "601166", "兴业": "601166",
    "平安银行": "000001",
    # --- 保险 ---
    "中国平安": "601318", "平安": "601318",
    "中国人寿": "601628", "人寿": "601628",
    "中国太保": "601601", "太保": "601601",
    # --- 医药 ---
    "恒瑞医药": "600276", "恒瑞": "600276",
    "迈瑞医疗": "300760", "迈瑞": "300760",
    "药明康德": "603259", "药明": "603259",
    "片仔癀": "600436",
    "爱尔眼科": "300015", "爱尔": "300015",
    # --- 科技 ---
    "海康威视": "002415", "海康": "002415",
    "立讯精密": "002475", "立讯": "002475",
    "科大讯飞": "002230", "讯飞": "002230",
    "中兴通讯": "000063", "中兴": "000063",
    "中芯国际": "688981", "中芯": "688981",
    # --- 家电 ---
    "美的集团": "000333", "美的": "000333",
    "格力电器": "000651", "格力": "000651",
    "海尔智家": "600690", "海尔": "600690",
    "伊利股份": "600887", "伊利": "600887",
    "海天味业": "603288", "海天": "603288",
    "牧原股份": "002714", "牧原": "002714",
    # --- 汽车 ---
    "上汽集团": "600104", "上汽": "600104",
    "长城汽车": "601633", "长城": "601633",
    # --- 地产 ---
    "万科A": "000002", "万科": "000002",
    "保利发展": "600048", "保利": "600048",
    # --- 芯片/半导体 ---
    "韦尔股份": "603501", "韦尔": "603501",
    "北方华创": "002371",
    # --- 其他 ---
    "中国神华": "601088", "神华": "601088",
    "长江电力": "600900", "长电": "600900",
    "中国中免": "601888", "中免": "601888",
    "顺丰控股": "002352", "顺丰": "002352",
    "京东方A": "000725", "京东方": "000725",
}


def resolve_stock(raw: str) -> str:
    """将股票名称或代码解析为6位代码"""
    raw = raw.strip()
    if raw.isdigit() and len(raw) == 6:
        return raw
    if raw in STOCK_NAME_MAP:
        return STOCK_NAME_MAP[raw]
    # 部分匹配
    for name, code in STOCK_NAME_MAP.items():
        if len(name) >= 2 and (raw in name or name in raw):
            return code
    return raw


# ==================== 多源下载引擎 ====================

def _create_spider(source_name: str, save_dir: str, delay: float):
    """根据名称创建爬虫实例"""
    spider_map = {
        "cninfo": CninfoSpider,
        "eastmoney": EastmoneySpider,
        "sina": SinaSpider,
    }
    spider_cls = spider_map.get(source_name)
    if spider_cls is None:
        return None
    return spider_cls(save_dir=save_dir, delay=delay)


def download_single_stock(
    stock_code: str,
    save_dir: str = None,
    start_year: int = None,
    end_year: int = None,
    categories: List[str] = None,
    delay: float = None,
    preferred_source: str = None,
) -> tuple:
    """
    下载单只股票的财报，自动切换数据源

    Returns:
        (downloaded_list, used_source_name)
    """
    if categories is None:
        categories = ["年报"]

    # 确定尝试顺序（如果指定了首选源，将其排到最前）
    sources_to_try = list(SOURCE_PRIORITY)
    if preferred_source:
        sources_to_try = [
            (name, cls) for name, cls in sources_to_try if name == preferred_source
        ] + [
            (name, cls) for name, cls in sources_to_try if name != preferred_source
        ]

    for source_name, _ in sources_to_try:
        spider = _create_spider(source_name, save_dir, delay)
        if spider is None:
            continue

        try:
            print(f"\n  🔍 尝试数据源 [{source_name}]: {stock_code}")
            reports = spider.get_reports(
                stock_code=stock_code,
                start_year=start_year,
                end_year=end_year,
                categories=categories,
            )
            if reports:
                print(f"  ✅ [{source_name}] 成功下载 {len(reports)} 个文件")
                return reports, source_name
            else:
                print(f"  ⚠️  [{source_name}] 返回 0 条结果，切换下一数据源")
        except Exception as e:
            print(f"  ✗ [{source_name}] 异常: {str(e)[:80]}，切换下一数据源")
            continue

    print(f"  ❌ 所有数据源均失败: {stock_code}")
    return [], None


def batch_download(
    stock_codes: List[str],
    save_dir: str = None,
    start_year: int = None,
    end_year: int = None,
    categories: List[str] = None,
    delay: float = None,
) -> Dict[str, List[Dict]]:
    """
    批量下载多只股票的财报（多数据源自动切换）

    Returns:
        {stock_code: downloaded_list} 字典
    """
    results = {}
    source_stats = {}

    for i, code in enumerate(stock_codes):
        print(f"\n{'='*50}")
        print(f"[{i+1}/{len(stock_codes)}] 处理股票: {code}")
        print(f"{'='*50}")

        downloaded, source_used = download_single_stock(
            stock_code=code,
            save_dir=save_dir,
            start_year=start_year,
            end_year=end_year,
            categories=categories,
            delay=delay,
        )
        results[code] = downloaded

        if source_used:
            source_stats[source_used] = source_stats.get(source_used, 0) + 1
        else:
            source_stats["失败"] = source_stats.get("失败", 0) + 1

        # 股票间延迟
        if i < len(stock_codes) - 1:
            time.sleep(delay or 1.0)

    # 打印统计
    print(f"\n{'='*50}")
    print("📊 数据源使用统计:")
    for src, count in sorted(source_stats.items(), key=lambda x: -x[1]):
        print(f"   {src}: {count} 只股票")
    print(f"{'='*50}")

    return results


# ==================== CLI 入口 ====================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="A股上市公司财报下载工具（多数据源自动切换）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python download_report.py --stock 600519 --start 2020 --end 2024
  python download_report.py --name 茅台 --start 2020 --end 2024 --category 年报
  python download_report.py --names 茅台,五粮液 --start 2020 --end 2024
  python download_report.py --name 茅台 --source eastmoney   # 指定数据源

数据源优先级: 巨潮资讯网 → 东方财富 → 新浪财经
某个数据源失败时自动切换下一数据源。
        """,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--stock", help="单个股票代码，如 600519")
    group.add_argument("--name", help="股票名称，如 茅台")
    group.add_argument("--names", help="多个股票名称/代码，逗号分隔")

    parser.add_argument("--start", type=int, help="起始年份，默认当前年份-5")
    parser.add_argument("--end", type=int, help="结束年份，默认当前年份")
    parser.add_argument("--category", choices=["年报", "半年报", "季报"], default="年报")
    parser.add_argument("--max-results", type=int, default=None, help="每只股票最多下载数量")
    parser.add_argument("--save-dir", default=DEFAULT_SAVE_DIR, help=f"PDF保存目录（默认: {DEFAULT_SAVE_DIR}）")
    parser.add_argument("--delay", type=float, default=0.5, help="请求间隔秒数")
    parser.add_argument(
        "--source",
        choices=["cninfo", "eastmoney", "sina"],
        default=None,
        help="指定数据源（可选，默认自动切换）",
    )

    args = parser.parse_args()

    # 解析股票代码
    if args.stock:
        codes = [args.stock]
    elif args.name:
        codes = [resolve_stock(args.name)]
    else:
        codes = [resolve_stock(s.strip()) for s in args.names.split(",") if s.strip()]

    # 默认年份范围
    current_year = datetime.now().year
    start_year = args.start if args.start else current_year - 5
    end_year = args.end if args.end else current_year

    print(f"📊 准备下载财报")
    print(f"   股票代码: {', '.join(codes)}")
    print(f"   报告类型: {args.category}")
    print(f"   年份范围: {start_year} ~ {end_year}")
    print(f"   保存目录: {args.save_dir}")
    if args.source:
        print(f"   指定数据源: {args.source}")
    else:
        print(f"   数据源策略: 自动切换（cninfo → eastmoney → sina）")

    results = batch_download(
        stock_codes=codes,
        save_dir=args.save_dir,
        start_year=start_year,
        end_year=end_year,
        categories=[args.category],
        delay=args.delay,
    )

    # 应用 max_results
    if args.max_results:
        for code in results:
            results[code] = results[code][:args.max_results]

    total = sum(len(v) for v in results.values())
    print(f"\n📈 下载完成: {len(codes)} 只股票, 共 {total} 个文件")

    for code, reports in results.items():
        if reports:
            years = sorted(set(r.get("year") for r in reports if r.get("year")))
            sources = set(r.get("source", "?") for r in reports)
            print(f"   {code}: {len(reports)} 个文件, 年份: {years}, 来源: {', '.join(sources)}")

    if total == 0:
        print("\n⚠️  未下载到任何文件，可能原因：")
        print("   1. 年份范围内无对应报告")
        print("   2. 所有数据源均无法访问（网络问题或反爬限制）")
        print("   3. 建议稍后重试，或通过 --source 指定特定数据源")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
