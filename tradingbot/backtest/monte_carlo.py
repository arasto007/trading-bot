"""Monte Carlo — شبیه‌سازی ترتیب معاملات برای تخمین drawdown و احتمال ورشکستگی."""



from __future__ import annotations



import random

from typing import Any



from tradingbot.backtest.models import BacktestResult





def run_monte_carlo(

    result: BacktestResult,

    *,

    simulations: int = 1000,

    initial_balance: float | None = None,

    seed: int = 42,

) -> dict[str, Any]:

    """بازچینش تصادفی PnL معاملات — خروجی: DD میانه، بدترین ۵٪، احتمال ضرر >۲۰٪."""

    trades = result.trades

    if not trades:

        return {"simulations": 0, "message": "no trades"}



    pnls = [t.pnl for t in trades]

    balance0 = initial_balance or result.initial_balance

    rng = random.Random(seed)



    final_returns: list[float] = []

    max_dds: list[float] = []



    for _ in range(simulations):

        shuffled = pnls.copy()

        rng.shuffle(shuffled)

        equity = balance0

        peak = equity

        max_dd = 0.0

        for pnl in shuffled:

            equity += pnl

            peak = max(peak, equity)

            if peak > 0:

                max_dd = max(max_dd, (peak - equity) / peak)

        final_returns.append((equity - balance0) / balance0 * 100)

        max_dds.append(max_dd * 100)



    final_returns.sort()

    max_dds.sort()

    n = len(final_returns)

    p5 = final_returns[int(n * 0.05)]

    p50 = final_returns[int(n * 0.50)]

    p95 = final_returns[int(n * 0.95)]

    dd_median = max_dds[int(n * 0.50)]

    dd_worst5 = max_dds[int(n * 0.95)]

    ruin_prob = sum(1 for r in final_returns if r <= -20) / n * 100



    return {

        "simulations": simulations,

        "return_p5_pct": round(p5, 2),

        "return_median_pct": round(p50, 2),

        "return_p95_pct": round(p95, 2),

        "dd_median_pct": round(dd_median, 2),

        "dd_worst5_pct": round(dd_worst5, 2),

        "ruin_prob_20pct_loss": round(ruin_prob, 2),

    }


