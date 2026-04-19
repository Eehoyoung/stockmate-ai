import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import normalize_stock_code


def test_normalize_stock_code_strips_kiwoom_suffix():
    assert normalize_stock_code("483650_AL") == "483650"


def test_normalize_stock_code_uses_canonical_digits_when_present():
    assert normalize_stock_code("A483650_AL") == "483650"


def test_normalize_stock_code_returns_empty_on_blank():
    assert normalize_stock_code("   ") == ""
