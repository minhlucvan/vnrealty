"""The price model for the future: area price series, fitted and backtested index models, fans and asset projections.

series.py   store / read / splice monthly area price series (``price_series`` table), point in time
models.py   rw_drift, local_trend, ar_growth, driver_regression on monthly log index levels
backtest.py walk-forward out-of-sample errors per model and horizon, ensemble weights
fan.py      p10/p50/p90 per month from the weighted ensemble plus out-of-sample errors
asset.py    one asset: today's value × area fan × local catalyst overlay; sell timing
record.py   publish forecasts to the ``forecast`` table and grade them later
"""
