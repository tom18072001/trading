# Sector config sanity tests
from config import (
    EXECUTION_BASKETS, MAX_LONG_SECTORS, MAX_SHORT_SECTORS, PROXY_BASKETS,
    SECTORS,
)


def test_15_sectors():
    assert len(SECTORS) == 15


def test_proxy_basket_size_top5():
    for code, syms in PROXY_BASKETS.items():
        assert len(syms) == 5, f"{code} basket size != 5"
        assert code in SECTORS


def test_execution_basket_top3():
    for code, syms in EXECUTION_BASKETS.items():
        assert len(syms) == 3
        assert syms == PROXY_BASKETS[code][:3]


def test_position_caps_sane():
    assert 1 <= MAX_LONG_SECTORS <= 5
    assert 1 <= MAX_SHORT_SECTORS <= 5
