# -*- coding: utf-8 -*-
"""quant_core 纯函数单元测试：手工计算期望值，pytest.approx 校验。"""
import pytest

import quant_core as qc

CAL = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05",
       "2024-02-01", "2024-02-26", "2024-02-27", "2024-02-28"]


def test_month_ends_picks_last_trading_day_of_each_month():
    assert qc.month_ends(CAL) == ["2024-01-05", "2024-02-28"]


def test_momentum_basic_and_missing_data():
    px = {"2024-01-02": 100.0, "2024-01-05": 110.0,
          "2024-02-28": 121.0}
    # idx=7（2024-02-28），lookback=4 → 基准日 calendar[3]=2024-01-05：121/110-1 = 0.10
    assert qc.momentum(lambda d: px.get(d), CAL, 7, 4) == pytest.approx(0.10)
    # lookback=5 → 基准日 2024-01-04 数据缺失 → None
    assert qc.momentum(lambda d: px.get(d), CAL, 7, 5) is None
    # 回看期不足 → None
    assert qc.momentum(lambda d: px.get(d), CAL, 2, 6) is None


def test_select_eligibles_applies_gate_and_sorts():
    mom = {"A": 0.30, "B": 0.05, "C": 0.20, "D": None}
    assert qc.select_eligibles(mom, cash_mom=0.10, top_n=2) == ["A", "C"]
    # 全部低于现金门 → 空表（全仓避险腿）
    assert qc.select_eligibles(mom, cash_mom=0.50, top_n=2) == []
    # 不开门 → 不过滤，纯排序
    assert qc.select_eligibles(mom, cash_mom=0.10, top_n=2, gate=False) == ["A", "C"]


def test_realized_vol_zero_for_constant_series():
    assert qc.realized_vol([100.0] * 10) == pytest.approx(0.0)


def test_realized_vol_matches_hand_calculation():
    closes = [100.0, 90.0, 100.0, 110.0]
    rs = [90 / 100 - 1, 100 / 90 - 1, 110 / 100 - 1]
    mu = sum(rs) / 3
    var = sum((r - mu) ** 2 for r in rs) / 2
    expect = var ** 0.5 * (243 ** 0.5)
    assert qc.realized_vol(closes) == pytest.approx(expect)


def test_realized_vol_none_when_too_short():
    assert qc.realized_vol([100.0, 105.0]) is None


def test_vol_scale_caps_at_one():
    assert qc.vol_scale([], 0.12) == 1.0
    assert qc.vol_scale([0.30], 0.12) == pytest.approx(0.4)
    assert qc.vol_scale([0.06], 0.12) == 1.0
    assert qc.vol_scale([0.0], 0.12) == 1.0


def test_net_month_return_charges_turnover_both_ways():
    # 换手 50%、单边成本 0.27% → 双边 0.54%... 不对：换手×2×cost
    assert qc.net_month_return(0.02, 0.5, 0.0027) == pytest.approx(0.02 - 0.5 * 2 * 0.0027)


def test_max_drawdown_known_sequence():
    # 曲线 1.1 → 0.88 → 0.968：峰 1.1，谷 0.88 → 回撤 = 1 - 0.88/1.1 = 0.2
    assert qc.max_drawdown([0.10, -0.20, 0.10]) == pytest.approx(0.20)


def test_max_drawdown_always_positive():
    assert qc.max_drawdown([0.10, 0.05, 0.02]) == 0.0
