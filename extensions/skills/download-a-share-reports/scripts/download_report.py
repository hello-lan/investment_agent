"""
A股上市公司财报爬取工具（巨潮资讯网）
支持按股票代码批量下载年报、半年报、季报等PDF文件
"""

import sys
import time
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from pathlib import Path

import requests


# ==================== 全局配置 ====================

class Config:
    """爬虫配置参数"""
    BASE_URL = "http://www.cninfo.com.cn/new/index"
    SEARCH_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
    DOWNLOAD_BASE = "http://static.cninfo.com.cn"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "http://www.cninfo.com.cn/new/index",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest"
    }
    REQUEST_DELAY = 0.5           # 请求间隔（秒），避免被封
    DOWNLOAD_DELAY = 1.0           # 下载间隔（秒）
    MAX_RETRIES = 3                # 最大重试次数
    
    # 公告类型映射
    CATEGORY_MAP = {
        "年报": "category_ndbg_szsh",
        "半年报": "category_sjdbg_szsh",
        "季报": "category_yjdbg_szsh",
    }
    
    # 板块映射
    PLATE_MAP = {
        "深市": "sz",
        "沪市": "sh",
        "北交所": "bj"
    }
    
    COLUMN_MAP = {
        "深市": "szse",
        "沪市": "sse",
        "北交所": "bj"
    }


# ==================== 核心爬虫类 ====================

class CninfoSpider:
    """巨潮资讯网爬虫核心类"""
    
    def __init__(self, save_dir: str = "./financial_reports", delay: float = None):
        """
        初始化爬虫
        
        Args:
            save_dir: PDF保存目录
            delay: 请求延迟（秒），默认使用Config中的配置
        """
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay if delay is not None else Config.REQUEST_DELAY
        self.session = requests.Session()
        self.session.headers.update(Config.HEADERS)
    
    def _log(self, message: str):
        print(message)
    
    def _get_stock_orgid(self, stock_code: str) -> Optional[Tuple[str, str]]:
        """
        通过股票代码获取orgId（公司内部ID）
        
        Args:
            stock_code: 6位股票代码（如'600519'）
            
        Returns:
            (orgId, stock_name) 或 None
        """
        url = "http://www.cninfo.com.cn/new/data/szse_stock.json"
        try:
            resp = self.session.get(url, timeout=10)
            data = resp.json()
            for stock in data.get("stockList", []):
                if stock["code"] == stock_code:
                    self._log(f"✓ 找到股票: {stock_code} -> {stock['orgId']}")
                    return stock["orgId"], stock["fullshortname"] if "fullshortname" in stock else stock_code
        except Exception as e:
            self._log(f"✗ 获取orgId失败 {stock_code}: {str(e)}")
        return None
    
    def search_announcements(
        self,
        stock_code: str,
        start_date: str = "1900-01-01",
        end_date: str = None,
        category: str = "年报",
        plate: str = "沪市",
        page_num: int = 1,
        page_size: int = 30
    ) -> List[Dict]:
        """
        搜索公告列表
        
        Args:
            stock_code: 6位股票代码
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD，默认今天
            category: 公告类型（年报/半年报/季报）
            plate: 板块（沪市/深市/北交所）
            page_num: 页码
            page_size: 每页数量
            
        Returns:
            公告列表，每条包含announcementTitle, adjunctUrl等字段
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        
        stock_info = self._get_stock_orgid(stock_code)
        if not stock_info:
            return []
        
        org_id, _ = stock_info
        stock_param = f"{stock_code},{org_id}"
        
        # 根据板块确定参数
        plate_lower = Config.PLATE_MAP.get(plate, "sh")
        column = Config.COLUMN_MAP.get(plate, "sse")
        
        # 按公告类型设置category参数
        category_value = "category_ndbg_szsh"
        if category == "半年报":
            category_value = "category_sjdbg_szsh"
        elif category == "季报":
            category_value = "category_yjdbg_szsh"
        
        data = {
            "stock": stock_param,
            "tabName": "fulltext",
            "pageSize": str(page_size),
            "pageNum": str(page_num),
            "column": column,
            "category": category_value,
            "plate": plate_lower,
            "seDate": f"{start_date}~{end_date}",
            "searchkey": "",
            "secid": "",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true"
        }
        
        try:
            self._log(f"正在搜索 {stock_code} -> 页码: {page_num}")
            resp = self.session.post(Config.SEARCH_URL, data=data, timeout=15)
            resp.raise_for_status()
            result = resp.json()
            announcements = result.get("announcements", [])
            # 增加调试输出
            if announcements:
                self._log(f"  第一条记录示例: {announcements[0].get('announcementTitle')}, adjunctUrl: {announcements[0].get('adjunctUrl')}")
            # 处理年份提取
            for item in announcements:
                title = item.get("announcementTitle", "")
                # 改进年份提取：从标题中提取4位数字，且一般是年份
                import re
                year_match = re.search(r'(20\d{2}|19\d{2})', title)
                if year_match:
                    item["report_year"] = int(year_match.group(1))
                else:
                    item["report_year"] = None
            return announcements
        except Exception as e:
            self._log(f"✗ 搜索失败 {stock_code}: {str(e)}")
            return []  # 返回空列表而不是None
    
    def download_pdf(
        self,
        stock_code: str,
        save_name: str,
        adjunct_url: str,
        overwrite: bool = False
    ) -> bool:
        """
        下载PDF文件，带有重试和异常处理
        
        Args:
            stock_code: 股票代码（用于目录组织）
            save_name: 保存的文件名
            adjunct_url: 公告的adjunctUrl字段
            overwrite: 是否覆盖已存在的文件
            
        Returns:
            是否下载成功
        """
        if not adjunct_url:
            self._log(f"✗ 跳过 {save_name}: 无下载链接")
            return False
        
        save_path = self.save_dir / stock_code / f"{save_name}.pdf"
        if save_path.exists() and not overwrite:
            self._log(f"⏭ 跳过 {save_name}: 文件已存在")
            return True
        
        save_path.parent.mkdir(parents=True, exist_ok=True)
        download_url = f"{Config.DOWNLOAD_BASE}/{adjunct_url.lstrip('/')}"
        
        for attempt in range(Config.MAX_RETRIES):
            try:
                self._log(f"⬇ 下载中 [{attempt+1}/{Config.MAX_RETRIES}]: {save_name}")
                resp = self.session.get(download_url, timeout=30)
                resp.raise_for_status()
                
                # 验证内容是否PDF
                if b"%PDF" not in resp.content[:100]:
                    if attempt + 1 < Config.MAX_RETRIES:
                        continue
                    self._log(f"✗ 下载失败 {save_name}: 文件可能无效")
                    return False
                
                with open(save_path, "wb") as f:
                    f.write(resp.content)
                self._log(f"✓ 下载完成: {save_path}")
                self._log(f"  大小: {len(resp.content) / 1024:.2f} KB")
                return True
            except Exception as e:
                self._log(f"  下载失败，尝试重试... {str(e)}")
                time.sleep(self.delay * (attempt + 1))
        
        self._log(f"✗ 最终下载失败: {save_name}")
        return False
    
    def get_stock_annual_reports(
        self,
        stock_code: str,
        start_year: int = None,
        end_year: int = None,
        categories: List[str] = None,
        max_results: int = None
    ) -> List[Dict]:
        """
        获取指定股票的财报并下载
        
        Args:
            stock_code: 6位股票代码
            start_year: 起始年份
            end_year: 结束年份
            categories: 公告类型列表，默认["年报"]
            max_results: 最大下载数量
            
        Returns:
            下载成功的报告列表
        """
        if categories is None:
            categories = ["年报"]
        
        start_date = f"{start_year}-01-01" if start_year else "1900-01-01"
        # 年报在次年4月底前发布，end_date 扩展到次年6月底以覆盖
        if end_year:
            extended_end = f"{end_year + 1}-06-30"
            today = datetime.now().strftime("%Y-%m-%d")
            end_date = min(extended_end, today)
        else:
            end_date = datetime.now().strftime("%Y-%m-%d")
        
        all_announcements = []
        page = 1
        
        # 多页搜索
        while True:
            report = self.search_announcements(
                stock_code=stock_code,
                start_date=start_date,
                end_date=end_date,
                category=categories[0] if categories else "年报",
                page_num=page
            )
            if not report:
                break
            all_announcements.extend(report)
            if len(report) < 30:  # 最后一页
                break
            page += 1
            time.sleep(self.delay)
        
        # 年份筛选
        if start_year:
            all_announcements = [a for a in all_announcements 
                                 if a.get("report_year") and start_year <= a.get("report_year") <= (end_year or 3000)]
        
        if max_results:
            all_announcements = all_announcements[:max_results]
        
        # 下载
        downloaded = []
        for item in all_announcements:
            title = item.get("announcementTitle", "").replace("/", "_").replace(" ", "_")
            year_info = f"_{item.get('report_year')}" if item.get("report_year") else ""
            save_name = f"{stock_code}_{title[:50]}{year_info}"
            
            success = self.download_pdf(
                stock_code=stock_code,
                save_name=save_name,
                adjunct_url=item.get("adjunctUrl", "")
            )
            if success:
                downloaded.append({
                    "stock_code": stock_code,
                    "title": title,
                    "file_path": str(self.save_dir / stock_code / f"{save_name}.pdf"),
                    "year": item.get("report_year"),
                    "adjunct_url": item.get("adjunctUrl")
                })
            time.sleep(Config.DOWNLOAD_DELAY)
        
        return downloaded


# ==================== 批量处理函数 ====================

def batch_download(
    stock_codes: List[str],
    save_dir: str = "./financial_reports",
    start_year: int = None,
    end_year: int = None,
    categories: List[str] = None,
    delay: float = None
) -> Dict[str, List[Dict]]:
    """
    批量下载多只股票的财报
    
    Args:
        stock_codes: 股票代码列表
        save_dir: 保存目录
        start_year: 起始年份
        end_year: 结束年份
        categories: 公告类型列表
        delay: 请求延迟
        
    Returns:
        {stock_code: downloaded_list} 字典
    """
    spider = CninfoSpider(save_dir, delay)
    results = {}
    
    for i, code in enumerate(stock_codes):
        spider._log(f"\n=== [{i+1}/{len(stock_codes)}] 处理股票: {code} ===")
        downloaded = spider.get_stock_annual_reports(
            stock_code=code,
            start_year=start_year,
            end_year=end_year,
            categories=categories
        )
        results[code] = downloaded
        spider._log(f"✅ 完成 {code}: 成功下载 {len(downloaded)} 个文件")
        time.sleep(spider.delay)
    
    return results



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
    """将股票名称或代码解析为6位代码。"""
    raw = raw.strip()
    if raw.isdigit() and len(raw) == 6:
        return raw
    if raw in STOCK_NAME_MAP:
        return STOCK_NAME_MAP[raw]
    for name, code in STOCK_NAME_MAP.items():
        if raw in name or name in raw:
            return code
    return raw


# ==================== CLI 入口 ====================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="A股上市公司财报下载工具（巨潮资讯网）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python download_report.py --stock 600519 --start 2020 --end 2024
  python download_report.py --name 茅台 --start 2020 --end 2024 --category 年报
  python download_report.py --names 茅台,五粮液 --start 2020 --end 2024
        """,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--stock", help="单个股票代码，如 600519")
    group.add_argument("--name", help="股票名称，如 茅台")
    group.add_argument("--names", help="多个股票名称/代码，逗号分隔，如 茅台,五粮液")

    parser.add_argument("--start", type=int, help="起始年份，默认当前年份-5")
    parser.add_argument("--end", type=int, help="结束年份，默认当前年份")
    parser.add_argument("--category", choices=["年报", "半年报", "季报"], default="年报")
    parser.add_argument("--max-results", type=int, default=None, help="每个股票最多下载数量")
    parser.add_argument("--save-dir", default="./financial_reports", help="PDF保存目录")
    parser.add_argument("--delay", type=float, default=0.5, help="请求间隔秒数")

    args = parser.parse_args()

    if args.stock:
        codes = [args.stock]
    elif args.name:
        codes = [resolve_stock(args.name)]
    else:
        codes = [resolve_stock(s.strip()) for s in args.names.split(",") if s.strip()]

    print(f"📊 准备下载财报")
    print(f"   股票代码: {', '.join(codes)}")
    print(f"   报告类型: {args.category}")
    print(f"   年份范围: {args.start or '不限'} ~ {args.end or '不限'}")
    print(f"   保存目录: {args.save_dir}")
    print()

    results = batch_download(
        stock_codes=codes,
        save_dir=args.save_dir,
        start_year=args.start,
        end_year=args.end,
        categories=[args.category],
        delay=args.delay,
    )

    if args.max_results:
        for code in results:
            results[code] = results[code][: args.max_results]

    total = sum(len(v) for v in results.values())
    print(f"\n📈 下载完成: {len(codes)} 只股票, 共 {total} 个文件")

    for code, reports in results.items():
        if reports:
            years = sorted(set(r.get("year") for r in reports if r.get("year")))
            print(f"   {code}: {len(reports)} 个文件, 年份: {years}")

    if total == 0:
        print("\n⚠️  未下载到任何文件，可能原因：年份范围内无对应报告、网络问题或被反爬限制")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()