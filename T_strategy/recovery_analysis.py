#!/usr/bin/env python3
"""
基金回本分析 — 基于 akshare + 购买记录
用法: python3 recovery_analysis.py [input/012805_pingan]
      不传参数则分析 input/ 下所有基金
"""
import akshare as ak
from datetime import datetime
import sys, os, json, glob

INPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "input")


def parse_fund_config(filepath):
    with open(filepath) as f:
        content = f.read()

    parts = content.split("---", 1)
    if len(parts) != 2:
        return None

    try:
        config = json.loads(parts[0].strip())
    except json.JSONDecodeError:
        return None

    purchases = []
    for line in parts[1].strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) >= 2:
            date_str = fields[0]
            amount = float(fields[1].lstrip("+"))
            date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
            purchases.append((date, amount))

    config["_purchases"] = purchases
    config["_filepath"] = filepath
    return config


def fetch_nav_history(fund_code):
    print(f"  获取 {fund_code} 净值历史...")
    df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
    df = df.rename(columns={"净值日期": "date", "单位净值": "nav"})
    df["date"] = df["date"].astype(str)
    df["nav"] = df["nav"].astype(float)
    nav_map = dict(zip(df["date"], df["nav"]))
    return nav_map, df


def match_nav(purchases, nav_map):
    dates_sorted = sorted(nav_map.keys())
    results = []
    total_cost = 0
    total_shares = 0

    for purchase_date, amount in purchases:
        nav_date = None
        for d in dates_sorted:
            if d <= purchase_date:
                nav_date = d
            else:
                break
        if nav_date is None:
            for d in dates_sorted:
                if d >= purchase_date:
                    nav_date = d
                    break

        nav_price = nav_map.get(nav_date, 0)
        if nav_price == 0:
            print(f"  ⚠️ 无法匹配 {purchase_date} 的净值")
            continue

        shares = amount / nav_price
        total_cost += amount
        total_shares += shares

        results.append({
            "buy_date": purchase_date,
            "nav_date": nav_date,
            "amount": amount,
            "nav": nav_price,
            "shares": shares,
        })

    return results, total_cost, total_shares


def current_status(results, total_cost, total_shares, nav_map, df):
    latest_row = df.iloc[-1]
    latest_nav = latest_row["nav"]
    latest_date = latest_row["date"]

    market_value = total_shares * latest_nav
    profit = market_value - total_cost
    profit_pct = (profit / total_cost) * 100
    avg_cost = total_cost / total_shares

    return {
        "latest_nav": latest_nav,
        "latest_date": latest_date,
        "total_cost": total_cost,
        "total_shares": total_shares,
        "avg_cost": avg_cost,
        "market_value": market_value,
        "profit": profit,
        "profit_pct": profit_pct,
        "be_nav": avg_cost,
        "be_pct": (avg_cost / latest_nav - 1) * 100,
    }


def recovery_analysis(status):
    nav = status["latest_nav"]
    be = status["be_nav"]
    shares = status["total_shares"]
    loss = -status["profit"]

    print(f"\n{'='*65}")
    print("📊 回本策略分析")
    print(f"{'='*65}")
    print(f"\n  当前净值: ¥{nav:.4f}  |  回本目标: ¥{be:.4f}  |  差距: {(be/nav-1)*100:+.1f}%")
    print(f"  持仓亏损: ¥{loss:,.0f}")

    print(f"\n  {'─'*60}")
    print(f"  方案A: 一次性补仓 — 把均价拉到当前净值")
    print(f"  {'─'*60}")

    add_amounts = [5000, 10000, 20000, 50000, 100000]
    print(f"  {'追加金额':<12} {'新均价':<10} {'差距':<10}")
    print(f"  {'─'*35}")
    for add in add_amounts:
        new_shares = shares + add / nav
        new_avg = (status["total_cost"] + add) / new_shares
        gap = (new_avg / nav - 1) * 100
        print(f"  ¥{add:>8,.0f}     ¥{new_avg:.4f}    {gap:+.1f}%")

    print(f"\n  {'─'*60}")
    print(f"  方案B: 每月定投 — 拉低均价所需月数")
    print(f"  {'─'*60}")

    monthly_amounts = [3000, 5000, 8000, 10000, 15000]
    print(f"  {'每月定投':<12} {'6月后均价':<12} {'12月后均价':<12} {'18月后均价':<12}")
    print(f"  {'─'*50}")
    for monthly in monthly_amounts:
        for months in [6, 12, 18]:
            total_add = monthly * months
            new_shares = shares + total_add / nav
            new_avg = (status["total_cost"] + total_add) / new_shares
            if months == 6:
                a6 = new_avg
            elif months == 12:
                a12 = new_avg
            else:
                a18 = new_avg
        print(f"  ¥{monthly:>8,.0f}     ¥{a6:.4f}        ¥{a12:.4f}        ¥{a18:.4f}")

    print(f"\n  {'─'*60}")
    print(f"  方案C: 做T策略 — 每笔T盈利对回本的贡献")
    print(f"  {'─'*60}")

    t_lot = shares * 0.10
    print(f"  基础T仓: {t_lot:,.0f} 份 (总仓位的 10%)")
    print()

    for t_return in [2, 3, 5, 8]:
        profit_per_t = t_lot * nav * (t_return / 100)
        t_per_month = 2
        monthly_profit = profit_per_t * t_per_month
        months_to_recover = loss / monthly_profit if monthly_profit > 0 else float("inf")
        print(f"  T收益率 +{t_return}%: 每笔赚 ¥{profit_per_t:,.0f}, "
              f"月做{t_per_month}次 → ¥{monthly_profit:,.0f}/月, 约需 {months_to_recover:.0f} 个月回本")


def analyze_fund(config):
    fund_code = config["fund_code"]
    fund_name = config["fund_name"]
    purchases = config["_purchases"]

    print(f"\n{'='*65}")
    print(f"  {fund_name}（{fund_code}）回本分析")
    print(f"{'='*65}")

    if not purchases:
        print("❌ 无购买记录")
        return

    nav_map, df = fetch_nav_history(fund_code)
    results, total_cost, total_shares = match_nav(purchases, nav_map)
    status = current_status(results, total_cost, total_shares, nav_map, df)

    print(f"\n{'─'*65}")
    print("📋 持仓明细")
    print(f"{'─'*65}")
    print(f"  {'日期':<12} {'投入':>10} {'净值':>8} {'份额':>10} {'净值日期':<12}")
    print(f"  {'─'*55}")
    for r in results:
        print(f"  {r['buy_date']:<12} ¥{r['amount']:>8,.0f}  {r['nav']:>8.4f} {r['shares']:>10,.2f}  {r['nav_date']}")

    print(f"\n{'─'*65}")
    print("📊 当前持仓")
    print(f"{'─'*65}")
    print(f"  最新净值:      ¥{status['latest_nav']:.4f} ({status['latest_date']})")
    print(f"  持仓份额:      {status['total_shares']:,.2f} 份")
    print(f"  总投入:        ¥{status['total_cost']:,.2f}")
    print(f"  成本均价:      ¥{status['avg_cost']:.4f}")
    print(f"  当前市值:      ¥{status['market_value']:,.2f}")
    print(f"  持仓盈亏:      ¥{status['profit']:+,.2f} ({status['profit_pct']:+.2f}%)")
    print(f"  距回本还差:    {(status['be_nav']/status['latest_nav']-1)*100:+.1f}% 涨幅")

    recovery_analysis(status)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="基金回本分析")
    parser.add_argument("fund_file", nargs="?", help="基金配置文件路径（可选，默认分析 input/ 下所有）")
    args = parser.parse_args()

    if args.fund_file:
        config = parse_fund_config(args.fund_file)
        if config:
            analyze_fund(config)
        else:
            print(f"❌ 无效的配置文件: {args.fund_file}")
    else:
        fund_files = sorted(glob.glob(os.path.join(INPUT_DIR, "*")))
        fund_files = [f for f in fund_files if os.path.isfile(f) and not os.path.basename(f).startswith(".")]
        if not fund_files:
            print(f"❌ input/ 目录下无基金配置文件")
            return

        print(f"发现 {len(fund_files)} 个基金配置")
        for fp in fund_files:
            config = parse_fund_config(fp)
            if config:
                analyze_fund(config)

    print(f"\n{'='*65}")
    print("  分析完成")
    print(f"{'='*65}")


if __name__ == "__main__":
    main()
