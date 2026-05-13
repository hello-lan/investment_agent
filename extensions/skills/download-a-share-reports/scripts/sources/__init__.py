"""A股财报数据源包 - 支持多数据源自动切换"""

from .cninfo_spider import CninfoSpider
from .eastmoney_spider import EastmoneySpider
from .sina_spider import SinaSpider

# 数据源优先级列表（按可靠性排序）
SOURCE_PRIORITY = [
    ("cninfo", CninfoSpider),
    ("eastmoney", EastmoneySpider),
    ("sina", SinaSpider),
]

__all__ = ["CninfoSpider", "EastmoneySpider", "SinaSpider", "SOURCE_PRIORITY"]
