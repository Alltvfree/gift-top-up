import pandas as pd

from backtest.metrics import model_metrics, trading_metrics


def test_model_metrics_perfect_classifier():
    y_true = pd.Series([0, 0, 1, 1, 1, 0])
    y_pred = pd.Series([0.05, 0.1, 0.9, 0.95, 0.8, 0.2])
    m = model_metrics(y_true, y_pred)
    assert m["auc"] == 1.0
    assert m["accuracy"] == 1.0
    assert m["confusion_matrix"]["fp"] == 0
    assert m["confusion_matrix"]["fn"] == 0


def test_model_metrics_single_class_gives_nan_auc_not_a_crash():
    y_true = pd.Series([1, 1, 1, 1])
    y_pred = pd.Series([0.6, 0.7, 0.8, 0.9])
    m = model_metrics(y_true, y_pred)
    assert m["auc"] != m["auc"]  # NaN


def test_trading_metrics_empty_trades_is_safe():
    result = trading_metrics(pd.DataFrame(), pd.DataFrame(), initial_balance=10000.0)
    assert result["total_trades"] == 0


def test_trading_metrics_separates_wins_and_losses_correctly():
    trades = pd.DataFrame(
        {
            "net_pnl": [100.0, -50.0, 200.0, -30.0],
            "commission": [1, 1, 1, 1], "spread_cost": [1, 1, 1, 1], "slippage_cost": [1, 1, 1, 1],
            "direction": ["BUY", "SELL", "BUY", "SELL"],
            "exit_reason": ["TP", "SL", "TP", "SL"],
            "holding_time": [pd.Timedelta(minutes=5)] * 4,
        }
    )
    equity_curve = pd.DataFrame({"drawdown": [0, 50, 0], "drawdown_percent": [0, 1.0, 0]})
    m = trading_metrics(trades, equity_curve, initial_balance=10000.0)
    assert m["total_trades"] == 4
    assert m["winning_trades"] == 2
    assert m["losing_trades"] == 2
    assert m["win_rate"] == 0.5
    assert m["gross_profit"] == 300.0
    assert m["gross_loss"] == -80.0
    assert m["profit_factor"] == 300.0 / 80.0
    assert m["net_profit"] == 220.0
    assert m["tp_exits"] == 2
    assert m["sl_exits"] == 2
    assert m["long_trades"] == 2
    assert m["short_trades"] == 2


def test_model_and_trading_metrics_are_reported_separately():
    """The report must never conflate classification performance with
    trading performance (README's own explicit lesson) — these two
    functions must stay independent, neither one reading the other's
    inputs."""
    import inspect

    model_params = set(inspect.signature(model_metrics).parameters)
    trading_params = set(inspect.signature(trading_metrics).parameters)
    assert model_params.isdisjoint(trading_params - {"threshold"})
