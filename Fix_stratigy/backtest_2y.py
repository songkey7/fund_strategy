#!/usr/bin/env python3
"""两年回测脚本 — 月底定投 + 每日回调追投 + 卖出双信号"""

import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

START_DATE = "2025-09-08"
END_DATE = "2026-09-08"
MONTHLY_BASE = 2000
PULLBACK_AMOUNT = 5000  # 每跌 5% 追加一份

FUNDS = {
    "004744": {
        "name": "易方达创业板ETF联接C",
        "index_code": "399006",
        "index_name": "创业板指",
        "target_return": [10, 20, 30, 40, 50],
        "target_sell_pct": [20, 20, 20, 20, 20],
        "pe_sell_threshold": [85, 95],
        "pe_sell_pct": [50, 50],
    },
    "022429": {
        "name": "天弘中证A500ETF联接C",
        "index_code": "000510",
        "index_name": "中证A500",
        "target_return": [20, 30, 50],
        "target_sell_pct": [30, 30, 40],
        "pe_sell_threshold": [85, 95],
        "pe_sell_pct": [50, 50],
    },
}


def load_nav_history(fund_code):
    df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
    df["date"] = pd.to_datetime(df["净值日期"])
    df["nav"] = df["单位净值"].astype(float)
    df = df[["date", "nav"]].set_index("date").sort_index()
    return df["nav"]


def load_pe_history_399006():
    df = ak.stock_market_pe_lg(symbol="创业板")
    df["date"] = pd.to_datetime(df["日期"])
    df["pe"] = df["平均市盈率"].astype(float)
    df = df[["date", "pe"]].set_index("date").sort_index()
    return df["pe"]


def load_pe_history_000510():
    """从 csindex API 获取 A500 真实 PE + 2026 年价格推算 PE"""
    import requests

    # 1. 从 csindex perf API 获取含 PE 的历史数据（2024-09 ~ 2025-12）
    url = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.csindex.com.cn/"}
    params = {"indexCode": "000510", "startDate": "2024-09-01", "endDate": "2025-12-31"}
    resp = requests.get(url, params=params, headers=headers, timeout=15)
    records = resp.json()["data"]

    real_pe = {}
    for r in records:
        dt = pd.Timestamp(r["tradeDate"])
        if r.get("peg") is not None:
            real_pe[dt] = float(r["peg"])

    # 2. 获取指数每日价格（用于推算 2026 年 PE）
    price_series = ak.stock_zh_index_daily(symbol="sh000510")
    price_series["date"] = pd.to_datetime(price_series["date"])
    price_series = price_series.set_index("date")["close"].astype(float).sort_index()

    # 3. 推算 2026 年 PE：PE ≈ 最近真实PE × (当日价格 / 基准日价格)
    last_pe_date = max(real_pe.keys())
    last_pe = real_pe[last_pe_date]
    last_price = price_series.get(last_pe_date)
    if last_price is None:
        last_price = price_series[price_series.index <= last_pe_date].iloc[-1]

    for dt in price_series.index:
        if dt in real_pe:
            continue
        if dt > last_pe_date and last_price and last_price > 0:
            real_pe[dt] = round(last_pe * (price_series[dt] / last_price), 2)

    pe_series = pd.Series(real_pe, name="pe").sort_index()
    return pe_series[pe_series.index >= "2024-01-01"]


def get_percentile(series, current_date, current_val):
    hist = series[series.index <= current_date]
    if len(hist) < 10:
        return 50, current_val
    pct = round((hist < current_val).sum() / len(hist) * 100, 1)
    return pct, current_val


def dca_multiplier(pe_pct):
    if pe_pct < 20:
        return 2.0
    elif pe_pct < 40:
        return 1.5
    elif pe_pct < 60:
        return 1.0
    elif pe_pct < 80:
        return 0.5
    else:
        return 0


def nearest_val(series, date):
    avail = series[series.index <= date]
    if len(avail) == 0:
        avail = series[series.index >= date]
    if len(avail) == 0:
        return None, None
    idx = avail.index[-1]
    return avail.iloc[-1], idx


def check_sell(total_cost, total_shares, nav, pe_pct, cfg):
    if total_cost <= 0:
        return []
    current_mv = total_shares * nav
    ret_pct = (current_mv / total_cost - 1) * 100

    signals = []
    for tr, sp in zip(cfg["target_return"], cfg["target_sell_pct"]):
        if ret_pct >= tr:
            signals.append({"type": "target", "label": f"累计收益 ≥ {tr}%", "sell_pct": sp, "priority": tr})

    for pt, sp in zip(cfg["pe_sell_threshold"], cfg["pe_sell_pct"]):
        if pe_pct >= pt:
            signals.append({"type": "pe", "label": f"PE百分位 ≥ {pt}%", "sell_pct": sp, "priority": pt})

    seen = set()
    unique = []
    for s in sorted(signals, key=lambda x: x["priority"], reverse=True):
        if s["type"] not in seen:
            seen.add(s["type"])
            unique.append(s)
    return unique


def backtest(fund_code, cfg, nav_series, val_series, source_type):
    start_dt = pd.Timestamp(START_DATE)
    end_dt = pd.Timestamp(END_DATE)

    # 回测区间内的交易日
    trading_days = nav_series[(nav_series.index >= start_dt) & (nav_series.index <= end_dt)].index

    # 每月最后一个交易日
    df_td = pd.DataFrame({"date": trading_days})
    df_td["ym"] = df_td["date"].dt.to_period("M")
    month_ends = set(df_td.groupby("ym")["date"].last().apply(lambda x: pd.Timestamp(x)))

    total_cost = 0.0
    total_shares = 0.0
    cash_returned = 0.0
    transactions = []
    pullback_txns = []
    sell_events = []
    peak_nav = None

    label = "PE" if source_type == "pe" else "点位"

    for date in trading_days:
        nav = nav_series[date]

        val, _ = nearest_val(val_series, date)
        if val is None:
            continue
        pe_pct, pe_val = get_percentile(val_series, date, val)

        # ── 每日：净值回调追投 ──
        allow_buy = (pe_pct <= 80) or cfg.get("no_pe_pause")
        if allow_buy and total_shares > 0:
            avg_cost = total_cost / total_shares
            if peak_nav is None:
                peak_nav = max(nav, avg_cost)

            drop = (nav / peak_nav - 1) * 100
            pullback_invest = 0
            if drop <= -10:
                pullback_invest = PULLBACK_AMOUNT * 2
                peak_nav = nav
            elif drop <= -5:
                pullback_invest = PULLBACK_AMOUNT
                peak_nav = nav

            if pullback_invest > 0:
                shares = pullback_invest / nav
                total_cost += pullback_invest
                total_shares += shares
                pullback_txns.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "amount": round(pullback_invest, 0),
                    "nav": round(nav, 4),
                    "shares": round(shares, 0),
                    "drop_pct": round(drop, 1),
                })

        # 更新净值高点
        if peak_nav is None or nav > peak_nav:
            peak_nav = nav

        # ── 月底：PE定投 + 卖出检查 ──
        if date in month_ends:
            allow_dca = (pe_pct <= 80) or cfg.get("no_pe_pause")
            if allow_dca:
                invest = MONTHLY_BASE * (1.0 if cfg.get("no_pe_pause") else dca_multiplier(pe_pct))
                if invest > 0:
                    shares = invest / nav
                    total_cost += invest
                    total_shares += shares
                    mul = invest / MONTHLY_BASE
                    if cfg.get("no_pe_pause"):
                        note = ""
                    elif mul >= 2:
                        note = "×2 低估加倍"
                    elif mul >= 1.5:
                        note = "×1.5 低估"
                    elif mul <= 0.5:
                        note = "×0.5 偏高"
                    else:
                        note = ""
                    transactions.append({
                        "date": date.strftime("%Y-%m-%d"),
                        "amount": round(invest, 0),
                        "nav": round(nav, 4),
                        "shares": round(shares, 0),
                        "pe_pct": pe_pct,
                        "pe_val": round(pe_val, 2),
                        "note": note,
                    })

            # 月底卖出检查
            if total_shares > 0:
                signals = check_sell(total_cost, total_shares, nav, pe_pct, cfg)
                for sig in signals:
                    sold_shares = total_shares * sig["sell_pct"] / 100
                    sold_mv = sold_shares * nav
                    total_shares -= sold_shares
                    cash_returned += sold_mv
                    sell_events.append({
                        "date": date.strftime("%Y-%m-%d"),
                        "label": sig["label"],
                        "type": sig["type"],
                        "sell_pct": sig["sell_pct"],
                        "sold_shares": sold_shares,
                        "sold_mv": round(sold_mv, 0),
                        "nav": round(nav, 4),
                    })

    final_nav, _ = nearest_val(nav_series, end_dt)
    if final_nav is None and transactions:
        final_nav = transactions[-1]["nav"]
    elif final_nav is None:
        final_nav = 1.0

    current_mv = total_shares * final_nav
    total_assets = current_mv + cash_returned
    total_ret = (total_assets / total_cost - 1) * 100 if total_cost > 0 else 0

    return {
        "total_cost": total_cost,
        "total_shares": total_shares,
        "current_mv": current_mv,
        "cash_returned": cash_returned,
        "total_assets": total_assets,
        "total_ret": total_ret,
        "final_nav": final_nav,
        "transactions": transactions,
        "pullback_txns": pullback_txns,
        "sell_events": sell_events,
        "label": label,
    }


def main():
    print("=" * 70)
    print(f"  两年策略回测 ｜ {START_DATE} → {END_DATE}")
    print(f"  每月月底定投，基准 ¥{MONTHLY_BASE:,}/月")
    print(f"  每日检测：净值跌 5% → 追投 ¥{PULLBACK_AMOUNT:,}，跌 10% → 追投 ¥{PULLBACK_AMOUNT*2:,}")
    print("=" * 70)

    all_results = []

    for code, cfg in FUNDS.items():
        print(f"\n{'─' * 70}")
        print(f"  [{code}] {cfg['name']}（{cfg['index_name']}）")
        print(f"{'─' * 70}")

        print(f"  ⏳ 加载净值...", end=" ", flush=True)
        nav_series = load_nav_history(code)
        print(f"{len(nav_series)} 条  {nav_series.index[0].strftime('%Y-%m-%d')} ~ {nav_series.index[-1].strftime('%Y-%m-%d')}")

        if cfg["index_code"] == "399006":
            print(f"  ⏳ 加载 PE 数据...", end=" ", flush=True)
            val_series = load_pe_history_399006()
            source_type = "pe"
        else:
            print(f"  ⏳ 加载 A500 PE 数据...", end=" ", flush=True)
            val_series = load_pe_history_000510()
            source_type = "pe"

        print(f"{len(val_series)} 条  {val_series.index[0].strftime('%Y-%m-%d')} ~ {val_series.index[-1].strftime('%Y-%m-%d')}")

        result = backtest(code, cfg, nav_series, val_series, source_type)
        all_results.append((code, cfg, result))

        r = result
        print(f"\n  📊 回测结果")
        print(f"  {'─' * 50}")
        print(f"  总投入:        ¥{r['total_cost']:>10,.0f}")
        print(f"  月底定投次数:   {len(r['transactions']):>10}")
        print(f"  回调追投次数:   {len(r['pullback_txns']):>10}")
        print(f"  止盈卖出次数:   {len(r['sell_events']):>10}")
        print(f"  卖出回款:      ¥{r['cash_returned']:>10,.0f}")
        print(f"  剩余市值:      ¥{r['current_mv']:>10,.0f}")
        print(f"  总资产:        ¥{r['total_assets']:>10,.0f}")
        print(f"  总收益率:       {r['total_ret']:>+10.2f}%")

        if r["sell_events"]:
            print(f"\n  🔔 止盈记录:")
            for se in r["sell_events"]:
                print(f"    {se['date']} | {se['label']} | 卖 {se['sell_pct']}% | ¥{se['sold_mv']:>8,.0f}")

        print(f"\n  📋 月底定投明细 ({len(r['transactions'])} 次):")
        print(f"  {'日期':<12} {'金额':>8} {'净值':>8} {'份额':>8} {'百分位':>8} {'说明'}")
        for t in r["transactions"]:
            val_label = f"{r['label']}={t['pe_val']}" if source_type == "pe" else f"{r['label']}={t['pe_val']:.0f}"
            print(f"  {t['date']:<12} ¥{t['amount']:>6,.0f} {t['nav']:>8.4f} {t['shares']:>8,.0f} {t['pe_pct']:>6.1f}%  {val_label} {t['note']}")

        if r["pullback_txns"]:
            print(f"\n  📉 回调追投明细 ({len(r['pullback_txns'])} 次):")
            print(f"  {'日期':<12} {'跌幅':>8} {'金额':>8} {'净值':>8} {'份额':>8}")
            for pt in r["pullback_txns"]:
                print(f"  {pt['date']:<12} {pt['drop_pct']:>7.1f}% ¥{pt['amount']:>6,.0f} {pt['nav']:>8.4f} {pt['shares']:>8,.0f}")

    print(f"\n{'=' * 70}")
    print(f"  📊 汇总对比")
    print(f"{'=' * 70}")
    for code, cfg, r in all_results:
        print(
            f"  [{code}] {cfg['name']:<20s}  "
            f"投入 ¥{r['total_cost']:>8,.0f}  "
            f"总资产 ¥{r['total_assets']:>8,.0f}  "
            f"收益率 {r['total_ret']:>+7.2f}%  "
            f"月底{len(r['transactions'])}次  回调{len(r['pullback_txns'])}次  卖出{len(r['sell_events'])}次"
        )


if __name__ == "__main__":
    main()
