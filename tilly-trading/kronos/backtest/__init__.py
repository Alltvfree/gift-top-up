"""Kronos backtest — leakage-free walk-forward evaluation with realistic
trading costs.

See kronos/README.md ("Phase 3: the realistic backtester") for how this
fits into the rest of the pipeline. Nothing in this package replaces
train.py/features.py/labels.py/mt5_data.py — it reuses them (prepare_dataset,
train_model, feature_columns_for, compute_features, download_history) and
adds what they don't have: chronological walk-forward retraining, a
realistic bid/ask/spread/slippage/commission execution model, position
sizing, an equity/drawdown ledger, and a report that separates model
performance (AUC/accuracy) from trading performance (expectancy, Sharpe,
drawdown) — because the two are not the same question and conflating them
is exactly the mistake this project has already caught itself making once
(see the README's multi-timeframe leakage story).
"""
