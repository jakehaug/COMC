from __future__ import annotations

import pytest

from comc_agent.valuation import net_proceeds, realized_pnl


def test_net_proceeds_accounts_for_seller_fee_and_processing():
    # $10 sale * (1 - 0.20) - $0.25 = $7.75
    assert net_proceeds(10.00) == pytest.approx(7.75)


def test_realized_pnl_on_flip():
    # bought for $3, sold for $10: $7.75 net - $3 cost = $4.75
    assert realized_pnl(3.00, 10.00) == pytest.approx(4.75)


def test_realized_pnl_can_be_negative_on_fees():
    # $2 sale nets only $1.35, vs $3 cost = -$1.65
    assert realized_pnl(3.00, 2.00) == pytest.approx(1.35 - 3.00)
