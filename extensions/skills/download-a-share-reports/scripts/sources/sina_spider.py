"""
新浪财经 A股财报爬虫
数据来源：新浪财经 (sina.com.cn) — 综合财经信息平台
"""

import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict

import requests

DEFAULT_SAVE_DIR = str(Path(tempfile.gettempdir()) / "financial_reports")


class SinaSpider:
    """新浪财经财报爬虫"""

    source_name = "sina"

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://vip.stock.finance.sina.com.cn/",
    }
    REQUEST_DELAY = 1.5
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
        print(f"  [sina] {message}")

    def _get_market_prefix(self, code: str) -> str:
        """获取新浪格式的股票代码"""
        if code.startswith(("6", "5")):
            return f"sh{code}"
        elif code.startswith(("0", "3", "2")):
            return f"sz{code}"
        elif code.startswith(("8", "4")):
            return f"bj{code}"
        else:
            return f"sz{code}"

    def search_announcements(
        self,
        stock_code: str,
        start_date: str = "1900-01-01",
        end_date: str = None,
        category: str = "年报",
        page: int = 1,
        page_size: int = 30,
    ) -> List[Dict]:
        """搜索公告列表（通过新浪财经公告页面）"""
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")

        # 新浪财经公告页
        url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCB_AllBulletin/stockid/{stock_code}.phtml"

        try:
            self._log(f"搜索 {stock_code} 页码: {page}")
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            resp.encoding = "gb2312"
            html = resp.text

            # 解析公告列表
            announcements = self._parse_bulletin_page(html, stock_code)

            # 过滤：只保留年报/半年报/季报类型
            keywords = self.CATEGORY_KEYWORDS.get(category, [category])
            announcements = [
                a for a in announcements
                if any(kw in a.get("announcementTitle", "") for kw in keywords)
            ]

            # 按日期范围过滤
            if start_date and start_date != "1900-01-01":
                announcements = [
                    a for a in announcements
                    if a.get("announcementTime", "") >= start_date
                ]
            announcements = [
                a for a in announcements
                if a.get("announcementTime", "") <= end_date
            ]

            self._log(f"获取到 {len(announcements)} 条公告")
            return announcements
        except requests.RequestException as e:
            self._log(f"网络请求失败: {str(e)}")
            return []
        except Exception as e:
            self._log(f"搜索失败 {stock_code}: {str(e)}")
            return []

    def _parse_bulletin_page(self, html: str, stock_code: str) -> List[Dict]:
        """解析新浪财经公告页面HTML"""
        announcements = []

        # 匹配公告表格行: 包含日期和标题的行
        # 新浪公告页面的表格结构: <tr> ... <td>日期</td> <td><a href="...">标题</a></td> ... </tr>
        row_pattern = re.compile(
            r'<tr[^>]*>.*?'
            r'<td[^>]*>.*?(\d{4}-\d{2}-\d{2}).*?</td>.*?'
            r'<td[^>]*>.*?<a[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>.*?</td>',
            re.DOTALL | re.IGNORECASE
        )

        matches = row_pattern.findall(html)
        for date_str, href, title in matches:
            title_clean = re.sub(r'<[^>]+>', '', title).strip()
            year_match = re.search(r"(20\d{2}|19\d{2})", title_clean)
            year = int(year_match.group(1)) if year_match else None

            # 构建PDF链接
            adjunct_url = self._build_pdf_url(href, stock_code)

            announcements.append({
                "announcementTitle": title_clean,
                "adjunctUrl": adjunct_url,
                "report_year": year,
                "announcementTime": date_str,
            })

        # 如果上面没匹配到，尝试更宽松的模式
        if not announcements:
            link_pattern = re.compile(
                r'<a[^>]*href=["\']([^"\']*(?:announcement|bulletin|PDF)[^"\']*)["\'][^>]*>'
                r'(.*?20\d{2}.*?)'
                r'</a>',
                re.DOTALL | re.IGNORECASE
            )
            date_pattern = re.compile(r'(\d{4}-\d{2}-\d{2})')

            links = link_pattern.findall(html)
            dates = date_pattern.findall(html)

            for i, (href, title) in enumerate(links):
                title_clean = re.sub(r'<[^>]+>', '', title).strip()
                year_match = re.search(r"(20\d{2}|19\d{2})", title_clean)
                year = int(year_match.group(1)) if year_match else None

                date_str = dates[i] if i < len(dates) else ""
                adjunct_url = self._build_pdf_url(href, stock_code)

                announcements.append({
                    "announcementTitle": title_clean,
                    "adjunctUrl": adjunct_url,
                    "report_year": year,
                    "announcementTime": date_str,
                })

        return announcements

    def _build_pdf_url(self, href: str, stock_code: str) -> str:
        """构建PDF下载链接"""
        if not href:
            return ""

        # 如果是完整URL
        if href.startswith("http"):
            return href

        # 如果是新浪的相对路径
        if href.startswith("/"):
            return f"https://vip.stock.finance.sina.com.cn{href}"

        # 其他相对路径
        return f"https://vip.stock.finance.sina.com.cn/{href}"

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

        for attempt in range(self.MAX_RETRIES):
            try:
                self._log(f"下载 [{attempt+1}/{self.MAX_RETRIES}]: {save_name}")
                resp = self.session.get(adjunct_url, timeout=30)

                # 新浪可能返回HTML重定向页或直接返回PDF
                if resp.status_code == 200:
                    content_type = resp.headers.get("Content-Type", "")

                    # 如果是HTML页面，尝试提取PDF链接
                    if "text/html" in content_type and b"%PDF" not in resp.content[:100]:
                        pdf_match = re.search(
                            rb'href=["\']([^"\']*\.pdf[^"\']*)["\']',
                            resp.content,
                            re.IGNORECASE
                        )
                        if pdf_match:
                            pdf_url = pdf_match.group(1).decode("utf-8", errors="ignore")
                            if not pdf_url.startswith("http"):
                                pdf_url = f"https://vip.stock.finance.sina.com.cn/{pdf_url.lstrip('/')}"
                            resp = self.session.get(pdf_url, timeout=30)
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

        all_announcements = self.search_announcements(
            stock_code=stock_code,
            start_date=start_date,
            end_date=end_date,
            category=category,
            page=1,
        )

        # 按年份筛选
        if start_year:
            all_announcements = [
                a for a in all_announcements
                if a.get("report_year") and start_year <= a["report_year"] <= (end_year or 9999)
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

    parser = argparse.ArgumentParser(description="新浪财经财报下载")
    parser.add_argument("--stock", required=True, help="股票代码")
    parser.add_argument("--start", type=int, help="起始年份")
    parser.add_argument("--end", type=int, help="结束年份")
    parser.add_argument("--category", choices=["年报", "半年报", "季报"], default="年报")
    parser.add_argument("--save-dir", default=DEFAULT_SAVE_DIR, help=f"PDF保存目录（默认: {DEFAULT_SAVE_DIR}）")
    parser.add_argument("--delay", type=float, default=1.5)
    args = parser.parse_args()

    spider = SinaSpider(save_dir=args.save_dir, delay=args.delay)
    reports = spider.get_reports(
        stock_code=args.stock,
        start_year=args.start,
        end_year=args.end,
        categories=[args.category],
    )
    print(f"\n完成: 下载 {len(reports)} 个文件")
