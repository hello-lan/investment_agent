"""
巨潮资讯网 A股财报爬虫
数据来源：巨潮资讯网 (cninfo.com.cn) — 中国证监会指定的上市公司信息披露平台
"""

import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import requests

DEFAULT_SAVE_DIR = str(Path(tempfile.gettempdir()) / "financial_reports")


class CninfoConfig:
    BASE_URL = "http://www.cninfo.com.cn/new/index"
    SEARCH_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
    DOWNLOAD_BASE = "http://static.cninfo.com.cn"
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "http://www.cninfo.com.cn/new/index",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
    }
    REQUEST_DELAY = 0.5
    DOWNLOAD_DELAY = 1.0
    MAX_RETRIES = 3

    CATEGORY_KEYWORDS = {
        "年报": ["年度报告", "年报"],
        "半年报": ["半年度报告", "半年报"],
        "季报": ["季度报告", "季报", "第一季度报告", "第三季度报告"],
    }

    PLATE_MAP = {"深市": "sz", "沪市": "sh", "北交所": "bj"}
    COLUMN_MAP = {"深市": "szse", "沪市": "sse", "北交所": "bj"}


class CninfoSpider:
    """巨潮资讯网爬虫"""

    source_name = "cninfo"

    def __init__(self, save_dir: str = None, delay: float = None):
        if save_dir is None:
            save_dir = DEFAULT_SAVE_DIR
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay if delay is not None else CninfoConfig.REQUEST_DELAY
        self.session = requests.Session()
        self.session.headers.update(CninfoConfig.HEADERS)

    def _log(self, message: str):
        print(f"  [cninfo] {message}")

    def _get_stock_orgid(self, stock_code: str) -> Optional[Tuple[str, str]]:
        """通过股票代码获取orgId"""
        url = "http://www.cninfo.com.cn/new/data/szse_stock.json"
        try:
            resp = self.session.get(url, timeout=10)
            data = resp.json()
            for stock in data.get("stockList", []):
                if stock["code"] == stock_code:
                    self._log(f"找到股票: {stock_code} -> {stock['orgId']}")
                    return stock["orgId"], stock.get("fullshortname", stock_code)
        except Exception as e:
            self._log(f"获取orgId失败 {stock_code}: {str(e)}")
        return None

    def search_announcements(
        self,
        stock_code: str,
        start_date: str = "1900-01-01",
        end_date: str = None,
        category: str = "年报",
        page_num: int = 1,
        page_size: int = 30,
    ) -> List[Dict]:
        """搜索公告列表"""
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")

        stock_info = self._get_stock_orgid(stock_code)
        if not stock_info:
            return []

        org_id, _ = stock_info
        stock_param = f"{stock_code},{org_id}"

        # 确定板块
        if stock_code.startswith(("6", "5")):
            plate, column = "sh", "sse"
        elif stock_code.startswith(("0", "3", "2")):
            plate, column = "sz", "szse"
        else:
            plate, column = "bj", "bj"

        category_value = {
            "年报": "category_ndbg_szsh",
            "半年报": "category_sjdbg_szsh",
            "季报": "category_yjdbg_szsh",
        }.get(category, "category_ndbg_szsh")

        data = {
            "stock": stock_param,
            "tabName": "fulltext",
            "pageSize": str(page_size),
            "pageNum": str(page_num),
            "column": column,
            "category": category_value,
            "plate": plate,
            "seDate": f"{start_date}~{end_date}",
            "searchkey": "",
            "secid": "",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }

        try:
            self._log(f"搜索 {stock_code} 页码: {page_num}")
            resp = self.session.post(CninfoConfig.SEARCH_URL, data=data, timeout=15)
            resp.raise_for_status()
            result = resp.json()
            announcements = result.get("announcements", [])
            for item in announcements:
                title = item.get("announcementTitle", "")
                year_match = re.search(r"(20\d{2}|19\d{2})", title)
                item["report_year"] = int(year_match.group(1)) if year_match else None
            return announcements
        except Exception as e:
            self._log(f"搜索失败 {stock_code}: {str(e)}")
            return []

    def download_pdf(
        self,
        stock_code: str,
        save_name: str,
        adjunct_url: str,
        overwrite: bool = False,
    ) -> bool:
        """下载PDF文件"""
        if not adjunct_url:
            self._log(f"跳过 {save_name}: 无下载链接")
            return False

        save_path = self.save_dir / stock_code / f"{save_name}.pdf"
        if save_path.exists() and not overwrite:
            self._log(f"跳过 {save_name}: 文件已存在")
            return True

        save_path.parent.mkdir(parents=True, exist_ok=True)
        download_url = f"{CninfoConfig.DOWNLOAD_BASE}/{adjunct_url.lstrip('/')}"

        for attempt in range(CninfoConfig.MAX_RETRIES):
            try:
                self._log(f"下载 [{attempt+1}/{CninfoConfig.MAX_RETRIES}]: {save_name}")
                resp = self.session.get(download_url, timeout=30)
                resp.raise_for_status()

                if b"%PDF" not in resp.content[:100]:
                    if attempt + 1 < CninfoConfig.MAX_RETRIES:
                        time.sleep(self.delay * (attempt + 1))
                        continue
                    self._log(f"下载失败 {save_name}: 文件可能无效")
                    return False

                with open(save_path, "wb") as f:
                    f.write(resp.content)
                self._log(f"下载完成: {save_path} ({len(resp.content) / 1024:.2f} KB)")
                return True
            except Exception as e:
                self._log(f"下载重试中... {str(e)}")
                time.sleep(self.delay * (attempt + 1))

        self._log(f"最终下载失败: {save_name}")
        return False

    def get_reports(
        self,
        stock_code: str,
        start_year: int = None,
        end_year: int = None,
        categories: List[str] = None,
    ) -> List[Dict]:
        """获取并下载指定股票的财报"""
        if categories is None:
            categories = ["年报"]

        start_date = f"{start_year}-01-01" if start_year else "1900-01-01"
        if end_year:
            end_date = min(f"{end_year + 1}-06-30", datetime.now().strftime("%Y-%m-%d"))
        else:
            end_date = datetime.now().strftime("%Y-%m-%d")

        all_announcements = []
        page = 1
        category = categories[0] if categories else "年报"

        while True:
            items = self.search_announcements(
                stock_code=stock_code,
                start_date=start_date,
                end_date=end_date,
                category=category,
                page_num=page,
            )
            if not items:
                break
            all_announcements.extend(items)
            if len(items) < 30:
                break
            page += 1
            time.sleep(self.delay)

        # 按年份筛选
        if start_year:
            all_announcements = [
                a for a in all_announcements
                if a.get("report_year") and start_year <= a["report_year"] <= (end_year or 9999)
            ]

        # 按标题关键词二次筛选
        keywords = CninfoConfig.CATEGORY_KEYWORDS.get(category, [category])
        all_announcements = [
            a for a in all_announcements
            if any(kw in a.get("announcementTitle", "") for kw in keywords)
        ]

        # 按年份去重（每年只保留一条）
        seen_years = set()
        deduped = []
        for a in all_announcements:
            y = a.get("report_year")
            if y and y not in seen_years:
                seen_years.add(y)
                deduped.append(a)
        all_announcements = deduped

        downloaded = []
        for item in all_announcements:
            title = item.get("announcementTitle", "").replace("/", "_").replace(" ", "_")
            year_info = f"_{item.get('report_year')}" if item.get("report_year") else ""
            save_name = f"{stock_code}_{title[:50]}{year_info}"

            success = self.download_pdf(
                stock_code=stock_code,
                save_name=save_name,
                adjunct_url=item.get("adjunctUrl", ""),
            )
            if success:
                downloaded.append({
                    "stock_code": stock_code,
                    "title": title,
                    "file_path": str(self.save_dir / stock_code / f"{save_name}.pdf"),
                    "year": item.get("report_year"),
                    "source": self.source_name,
                })
            time.sleep(CninfoConfig.DOWNLOAD_DELAY)

        return downloaded


# ==================== 独立运行入口 ====================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="巨潮资讯网财报下载")
    parser.add_argument("--stock", required=True, help="股票代码")
    parser.add_argument("--start", type=int, help="起始年份")
    parser.add_argument("--end", type=int, help="结束年份")
    parser.add_argument("--category", choices=["年报", "半年报", "季报"], default="年报")
    parser.add_argument("--save-dir", default=DEFAULT_SAVE_DIR, help=f"PDF保存目录（默认: {DEFAULT_SAVE_DIR}）")
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()

    spider = CninfoSpider(save_dir=args.save_dir, delay=args.delay)
    reports = spider.get_reports(
        stock_code=args.stock,
        start_year=args.start,
        end_year=args.end,
        categories=[args.category],
    )
    print(f"\n完成: 下载 {len(reports)} 个文件")
