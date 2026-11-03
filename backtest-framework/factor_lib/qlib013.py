"""Example factor only: Qlib Alpha158 VWAP0 (adjusted VWAP / adjusted close)."""
FACTOR_ID = "qlib_alpha013"
REQUIRED_COLUMNS = ("close_post", "vwap_post")


def calculate_factor(data, parameters):
    """Return one factor_raw value per input date/security; keep missing values as NaN."""
    out = data[["trade_date", "stock_code"]].copy()
    close = data.close_post.where(data.close_post > 0)
    vwap = data.vwap_post.where(data.vwap_post > 0)
    out["factor_raw"] = vwap / close
    return out
