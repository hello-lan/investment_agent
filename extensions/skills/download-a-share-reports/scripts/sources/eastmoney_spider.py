"""
东方财富网 A股财报爬虫
数据来源：东方财富网 (eastmoney.com) — A股市场主流的金融数据平台
"""

import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict

import requests

DEFAULT_SAVE_DIR = str(Path(tempfile.gettempdir()) / "financial_reports")


class EastmoneySpider:
    """东方财富财报爬虫"""

    source_name = "eastmoney"

    SEARCH_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://data.eastmoney.com/",
    }
    REQUEST_DELAY = 1.0
    DOWNLOAD_DELAY = 1.0
    MAX_RETRIES = 3

    CATEGORY_KEYWORDS = {
        "年报": ["年度报告", "年报"],
        "半年报": ["半年度报告", "半年报", "中期报告"],
        "季报": ["季度报告", "季报", "第一季度报告", "第三季度报告"],
    }

    def __init__(self, save_dir: str = None, delay: float = None):
        if save_dir is None:
            save_dir = DEFAULT_SAVE_DIR
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay if delay is not None else self.REQUEST_DELAY
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def _log(self, message: str):
        print(f"  [eastmoney] {message}")

    def _stock_market_code(self, code: str) -> str:
        """获取东方财富格式的股票代码（带交易所前缀）"""
        if code.startswith(("6", "5")):
            return f"SH{code}"
        elif code.startswith(("0", "3", "2")):
            return f"SZ{code}"
        elif code.startswith(("8", "4")):
            return f"BJ{code}"
        else:
            return f"SZ{code}"

    def search_announcements(
        self,
        stock_code: str,
        start_date: str = "1900-01-01",
        end_date: str = None,
        category: str = "年报",
        page: int = 1,
        page_size: int = 30,
    ) -> List[Dict]:
        """搜索公告列表"""
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")

        stock_list = self._stock_market_code(stock_code)

        params = {
            "page_size": page_size,
            "page_index": page,
            "stock_list": stock_list,
            "begin_time": start_date.replace("-", ""),
            "end_time": end_date.replace("-", ""),
            "f_node": "0",
            "s_node": "0",
        }

        try:
            self._log(f"搜索 {stock_code} ({stock_list}) 页码: {page}")
            resp = self.session.get(self.SEARCH_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                self._log(f"API返回异常 code={data.get('code')}: {data.get('message', '')}")
                return []

            items = data.get("data", {}).get("list", [])
            if not items:
                return []

            announcements = []
            for item in items:
                title = item.get("art_title", "")
                adjunct_url = item.get("adjunct_url", "")

                year_match = re.search(r"(20\d{2}|19\d{2})", title)
                year = int(year_match.group(1)) if year_match else None

                announcements.append({
                    "announcementTitle": title,
                    "adjunctUrl": adjunct_url,
                    "report_year": year,
                    "announcementId": item.get("art_code", ""),
                    "announcementTime": item.get("noticed_date", ""),
                })

            if announcements:
                self._log(f"获取到 {len(announcements)} 条公告")
            return announcements
        except requests.RequestException as e:
            self._log(f"网络请求失败: {str(e)}")
            return []
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

        # 东方财富的PDF链接可能是相对路径或绝对路径
        if adjunct_url.startswith("http"):
            download_url = adjunct_url
        elif adjunct_url.startswith("/"):
            download_url = f"https://np-anotice-stock.eastmoney.com{adjunct_url}"
        else:
            download_url = f"https://np-anotice-stock.eastmoney.com/{adjunct_url}"

        for attempt in range(self.MAX_RETRIES):
            try:
                self._log(f"下载 [{attempt+1}/{self.MAX_RETRIES}]: {save_name}")
                resp = self.session.get(download_url, timeout=30)
                resp.raise_for_status()

                if b"%PDF" not in resp.content[:100]:
                    if attempt + 1 < self.MAX_RETRIES:
                        time.sleep(self.delay * (attempt + 1))
                        continue
                    self._log(f"下载失败 {save_name}: 文件不是有效PDF")
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
            end_date = f"{end_year + 1}-06-30"
        else:
            end_date = datetime.now().strftime("%Y-%m-%d")

        category = categories[0] if categories else "年报"

        all_announcements = []
        page = 1

        while True:
            items = self.search_announcements(
                stock_code=stock_code,
                start_date=start_date,
                end_date=end_date,
                category=category,
                page=page,
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

        # 按标题关键词筛选
        keywords = self.CATEGORY_KEYWORDS.get(category, [category])
        all_announcements = [
            a for a in all_announcements
            if any(kw in a.get("announcementTitle", "") for kw in keywords)
        ]

        # 按年份去重
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
            time.sleep(self.DOWNLOAD_DELAY)

        return downloaded


# ==================== 独立运行入口 ====================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="东方财富财报下载")
    parser.add_argument("--stock", required=True, help="股票代码")
    parser.add_argument("--start", type=int, help="起始年份")
    parser.add_argument("--end", type=int, help="结束年份")
    parser.add_argument("--category", choices=["年报", "半年报", "季报"], default="年报")
    parser.add_argument("--save-dir", default=DEFAULT_SAVE_DIR, help=f"PDF保存目录（默认: {DEFAULT_SAVE_DIR}）")
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    spider = EastmoneySpider(save_dir=args.save_dir, delay=args.delay)
    reports = spider.get_reports(
        stock_code=args.stock,
        start_year=args.start,
        end_year=args.end,
        categories=[args.category],
    )
    print(f"\n完成: 下载 {len(reports)} 个文件")
