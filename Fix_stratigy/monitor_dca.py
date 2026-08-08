#!/usr/bin/env python3
"""
宽基智能定投止盈监控
读取 input/ 下的定投记录，计算持仓，检测估值止盈 & 目标收益止盈信号
传输渠道: PushPlus Token
"""

import requests, json, os, re, argparse, glob
from datetime import datetime, timedelta

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
            purchases.append({"date": fields[0], "amount": float(fields[1])})

    config["purchases"] = purchases
    config["_filepath"] = filepath
    return config


def load_all_funds():
    funds = []
    for fp in sorted(glob.glob(os.path.join(INPUT_DIR, "*"))):
        if os.path.isfile(fp) and not fp.startswith("."):
            cfg = parse_fund_config(fp)
            if cfg:
                funds.append(cfg)
    return funds


def fetch_latest_nav(fund_code):
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")

    for attempt in range(3):
        try:
            url = (
                f"https://api.fund.eastmoney.com/f10/lsjz"
                f"?callback=jQuery&fundCode={fund_code}&pageIndex=1&pageSize=1"
                f"&startDate={start_date}&endDate={end_date}"
            )
            headers = {
                "Referer": "https://fundf10.eastmoney.com/",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            }
            resp = requests.get(url, headers=headers, timeout=15)
            text = resp.text.strip()
            m = re.match(r"^\w+\((.*)\)$", text, re.DOTALL)
            if m:
                data = json.loads(m.group(1))
                records = data["Data"]["LSJZList"]
                if not records:
                    continue
                latest = records[0]
                nav = float(latest["DWJZ"])
                date = latest["FSRQ"]
                return nav, date
        except Exception as e:
            print(f"  获取净值失败 {fund_code} attempt {attempt+1}: {e}")
    return None, None


def fetch_index_pe(index_code):
    """获取指数PE估值"""
    try:
        import akshare as ak
        df = ak.stock_zh_index_value_csindex(symbol=index_code)
        pe1 = df["市盈率1"].dropna()
        latest_pe = pe1.iloc[-1]
        percentile = round((pe1 < latest_pe).sum() / len(pe1) * 100, 1)
        pe_20 = pe1.quantile(0.2)
        pe_40 = pe1.quantile(0.4)
        pe_60 = pe1.quantile(0.6)
        pe_80 = pe1.quantile(0.8)
        pe_85 = pe1.quantile(0.85)
        pe_95 = pe1.quantile(0.95)
        return {
            "latest_pe": latest_pe,
            "percentile": percentile,
            "pe_20": pe_20,
            "pe_40": pe_40,
            "pe_60": pe_60,
            "pe_80": pe_80,
            "pe_85": pe_85,
            "pe_95": pe_95,
        }
    except Exception as e:
        print(f"  获取指数PE失败 {index_code}: {e}")
        return None


def match_purchase_nav(purchases, nav_map):
    str_nav_map = {}
    for d in sorted(nav_map.keys()):
        key = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
        str_nav_map[key] = nav_map[d]
    sorted_str_dates = sorted(str_nav_map.keys())

    result = []
    for p in purchases:
        p_date = f"{p['date'][:4]}-{p['date'][4:6]}-{p['date'][6:8]}"
        if p_date in str_nav_map:
            confirm_nav = str_nav_map[p_date]
        else:
            confirm_nav = None
            for d in sorted_str_dates:
                if d >= p_date:
                    confirm_nav = str_nav_map[d]
                    break
            if confirm_nav is None:
                confirm_nav = str_nav_map[sorted_str_dates[-1]] if str_nav_map else 1.0
        shares = p["amount"] / confirm_nav if confirm_nav else 0
        result.append({
            "date": p_date,
            "amount": p["amount"],
            "confirm_nav": confirm_nav,
            "shares": shares,
        })
    return result


def fetch_nav_history(fund_code):
    """获取基金历史净值"""
    import akshare as ak
    try:
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
        nav_map = {}
        for _, row in df.iterrows():
            nav_map[row["净值日期"]] = float(row["单位净值"])
        return nav_map
    except Exception as e:
        print(f"  获取历史净值失败 {fund_code}: {e}")
        return {}


def check_take_profit(purchases_matched, latest_nav, pe_info, cfg):
    total_cost = sum(p["amount"] for p in purchases_matched)
    total_shares = sum(p["shares"] for p in purchases_matched)
    current_mv = total_shares * latest_nav
    total_return_pct = round((current_mv / total_cost - 1) * 100, 2) if total_cost else 0

    signals = []

    # 目标收益止盈
    target_return = cfg.get("target_return", [20, 30, 50])
    target_sell_pct = cfg.get("target_sell_pct", [30, 30, 40])
    for tr, sp in zip(target_return, target_sell_pct):
        if total_return_pct >= tr:
            sell_mv = current_mv * sp / 100
            signals.append({
                "type": "target",
                "label": f"目标收益 ≥ {tr}%",
                "sell_pct": sp,
                "sell_mv": sell_mv,
                "sell_shares": total_shares * sp / 100,
                "priority": tr,
            })

    # 估值止盈
    if pe_info:
        pe_sell_threshold = cfg.get("pe_sell_threshold", [85, 95])
        pe_sell_pct = cfg.get("pe_sell_pct", [50, 50])
        for pt, sp in zip(pe_sell_threshold, pe_sell_pct):
            if pe_info["percentile"] >= pt:
                sell_mv = current_mv * sp / 100
                signals.append({
                    "type": "pe",
                    "label": f"PE百分位 ≥ {pt}%",
                    "sell_pct": sp,
                    "sell_mv": sell_mv,
                    "sell_shares": total_shares * sp / 100,
                    "priority": pt,
                })

    # 去重：同一卖点不重复触发，取最高优先级的同类信号
seen = set()
    unique_signals = []
    for s in sorted(signals, key=lambda x: x["priority"], reverse=True):
        if s["type"] not in seen:
            seen.add(s["type"])
            unique_signals.append(s)

    return {
        "total_cost": total_cost,
        "total_shares": total_shares,
        "current_mv": current_mv,
        "total_return_pct": total_return_pct,
        "avg_cost_nav": total_cost / total_shares if total_shares else 0,
        "signals": unique_signals,
        "pe_info": pe_info,
        "purchases_matched": purchases_matched,
    }


def push_to_wechat(title, content, token, template="html"):
    if not token:
        print("   WARNING: PUSHPLUS_TOKEN not configured")
        return

    url = "https://www.pushplus.plus/send"
    payload = {"token": token, "title": title, "content": content, "template": template}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            print(f"   PushPlus推送成功")
        else:
            print(f"   PushPlus推送失败: {resp.status_code}")
    except Exception as e:
        print(f"   PushPlus推送异常: {e}")


def generate_report(funds_data, nav_date):
    css = "font-family:-apple-system,'PingFang SC',sans-serif;max-width:100%;color:#222;font-size:14px;line-height:1.6"
    card = "background:#fff;border-radius:10px;padding:12px;margin-bottom:8px;box-shadow:0 1px 2px rgba(0,0,0,0.06)"
    green = "#38a169"
    red = "#e53e3e"
    blue = "#2b6cb0"

    has_any_signal = any(fd["status"]["signals"] for fd in funds_data)
    sections = []
    fund_names = []

    for fd in funds_data:
        cfg = fd["config"]
        st = fd["status"]
        pe = st["pe_info"]
        nav = fd["nav"]

        fund_names.append(cfg["fund_name"])

        c = red if st["total_return_pct"] >= 0 else green

        section = f"""
<div style="background:#2b4c7e;color:#fff;border-radius:10px;padding:14px 16px;text-align:center;margin-bottom:8px">
<div style="font-size:16px;font-weight:600;margin:0">{cfg['fund_name']}</div>
<div style="font-size:11px;opacity:0.6;margin:3px 0">{cfg['fund_code']}</div>
</div>

<div style="{card}">
<div style="font-size:13px;font-weight:600;color:#888;margin-bottom:6px">📈 定投持仓</div>
<div style="display:flex;justify-content:space-between;padding:2px 0"><span style="color:#999">总投入</span><span style="font-weight:600">¥{st['total_cost']:,.0f}</span></div>
<div style="display:flex;justify-content:space-between;padding:2px 0"><span style="color:#999">持仓份额</span><span>{st['total_shares']:,.0f}</span></div>
<div style="display:flex;justify-content:space-between;padding:2px 0"><span style="color:#999">持仓均价</span><span>{st['avg_cost_nav']:.4f}</span></div>
<div style="display:flex;justify-content:space-between;padding:2px 0"><span style="color:#999">当前净值</span><span style="font-weight:600">{nav:.4f}</span></div>
<div style="display:flex;justify-content:space-between;padding:2px 0"><span style="color:#999">当前市值</span><span style="font-weight:600">¥{st['current_mv']:,.0f}</span></div>
<div style="display:flex;justify-content:space-between;padding:2px 0"><span style="color:#999">累计收益率</span><span style="color:{c};font-weight:600">{st['total_return_pct']:+.2f}%</span></div>
<div style="display:flex;justify-content:space-between;padding:2px 0"><span style="color:#999">浮动盈亏</span><span style="color:{c};font-weight:600">¥{st['current_mv'] - st['total_cost']:+,.0f}</span></div>
</div>
"""

        # PE 估值卡片
        if pe:
            pe_pct_color = red if pe["percentile"] >= 80 else (blue if pe["percentile"] < 40 else "#666")
            section += f"""
<div style="{card}">
<div style="font-size:13px;font-weight:600;color:#888;margin-bottom:6px">📊 {cfg.get('index_name', '指数')} 估值</div>
<div style="display:flex;justify-content:space-between;padding:2px 0"><span style="color:#999">当前PE</span><span style="font-weight:600">{pe['latest_pe']:.2f}</span></div>
<div style="display:flex;justify-content:space-between;padding:2px 0"><span style="color:#999">PE百分位</span><span style="color:{pe_pct_color};font-weight:600">{pe['percentile']}%</span></div>
<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:12px">
<span style="color:#999">20%</span><span style="color:#999">40%</span><span style="color:#999">60%</span><span style="color:#999">80%</span>
</div>
<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:12px;font-weight:600">
<span>{pe['pe_20']:.2f}</span><span>{pe['pe_40']:.2f}</span><span>{pe['pe_60']:.2f}</span><span>{pe['pe_80']:.2f}</span>
</div>
</div>
"""

        # 止盈信号
        signals = st["signals"]
        if signals:
            for sig in signals:
                section += f"""
<div style="background:#fff5f5;border:2px solid #fc8181;border-radius:10px;padding:10px;margin-bottom:6px;text-align:center">
<div style="font-size:14px;font-weight:700;color:#c53030;margin-bottom:4px">
🔔 止盈信号 · {sig['label']}
</div>
<div style="font-size:13px;font-weight:600">
→ 卖出 {sig['sell_pct']}%（{sig['sell_shares']:,.0f} 份）约 ¥{sig['sell_mv']:,.0f}
</div>
</div>"""
        else:
            # 无信号，显示最近的止盈关注点位
            pe_sell_threshold = cfg.get("pe_sell_threshold", [85, 95])
            target_return = cfg.get("target_return", [20, 30, 50])

            section += f"""
<div style="background:#edf2ff;border:1px solid #90b4f0;border-radius:10px;padding:10px;margin-bottom:6px;text-align:center">
<div style="font-size:13px;font-weight:600;color:#444">⏳ 持仓中，无止盈信号</div>
<div style="font-size:12px;color:#888;margin-top:4px">
目标收益止盈: 还剩 {target_return[0] - st['total_return_pct']:.1f}%（当前 {st['total_return_pct']:+.1f}% → {target_return[0]}%）</div>"""

            if pe:
                gap_pe = pe_sell_threshold[0] - pe["percentile"]
                section += f"""
<div style="font-size:12px;color:#888">
估值止盈: 还剩 {gap_pe:.1f}%（当前 PE百分位 {pe['percentile']}% → {pe_sell_threshold[0]}%）</div>"""
            section += "</div>"

        # 定投明细表
        section += f"""
<div style="{card}">
<div style="font-size:13px;font-weight:600;color:#888;margin-bottom:6px">📋 定投记录</div>
<table style="width:100%;border-collapse:collapse;font-size:12px">
<tr style="color:#999;border-bottom:1px solid #eee">
<td style="padding:4px 0">日期</td><td style="text-align:right;padding:4px 0">金额</td><td style="text-align:right;padding:4px 0">确认净值</td><td style="text-align:right;padding:4px 0">份额</td>
</tr>"""

        for pm in st["purchases_matched"]:
            section += f"""
<tr style="border-bottom:1px solid #f6f6f6">
<td>{pm['date']}</td><td style="text-align:right">¥{pm['amount']:,.0f}</td><td style="text-align:right">{pm['confirm_nav']:.4f}</td><td style="text-align:right">{pm['shares']:,.0f}</td>
</tr>"""
        section += "</table></div>"

        sections.append(section)

    title = " | ".join(fund_names)
    if has_any_signal:
        title = "🔔 " + title + " · 止盈信号"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="{css};background:#f0f0f0;padding:12px;margin:0">

<div style="background:#1a1a2e;color:#fff;padding:18px 16px;border-radius:12px;text-align:center;margin-bottom:10px">
<div style="font-size:18px;font-weight:600;margin:0">📊 宽基智能定投监控</div>
<div style="font-size:11px;opacity:0.5;margin:4px 0 0">{nav_date}</div>
</div>

{'<div style="border-top:2px dashed #d0d0d0;margin:14px 0 8px"></div>'.join(sections)}

<div style="text-align:center;color:#aaa;font-size:11px;margin-top:12px">数据来源: 东方财富 · 中证指数 | 仅供参考</div>
</body></html>"""

    return title, html


def main(pushplus_token=None):
    if pushplus_token is None:
        pushplus_token = os.environ.get("PUSHPLUS_TOKEN")

    print("=" * 60)
    print(f"  宽基智能定投止盈监控 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    funds = load_all_funds()
    if not funds:
        print("  ❌ input/ 目录下无有效基金配置文件")
        return

    print(f"  发现 {len(funds)} 个基金配置")
    funds_data = []
    nav_date = datetime.now().strftime("%Y-%m-%d")

    for cfg in funds:
        code = cfg["fund_code"]
        name = cfg["fund_name"]
        index_code = cfg.get("index_code")
        print(f"\n  [{code}] {name}")

        # 获取当前净值
        nav, date = fetch_latest_nav(code)
        if nav is None:
            print(f"    ❌ 获取净值失败，跳过")
            continue
        print(f"    净值: {nav:.4f} ({date})")
        nav_date = date or nav_date

        # 获取历史净值并匹配定投
        nav_map = fetch_nav_history(code)
        purchases_matched = match_purchase_nav(cfg["purchases"], nav_map)

        # 获取指数PE估值
        pe_info = None
        if index_code:
            pe_info = fetch_index_pe(index_code)
            if pe_info:
                print(f"    PE: {pe_info['latest_pe']:.2f} (百分位 {pe_info['percentile']}%)")

        # 止盈检查
        status = check_take_profit(purchases_matched, nav, pe_info, cfg)
        print(f"    总投入: ¥{status['total_cost']:,.0f}")
        print(f"    市值: ¥{status['current_mv']:,.0f}")
        print(f"    累计收益: {status['total_return_pct']:+.2f}%")

        if status["signals"]:
            for s in status["signals"]:
                print(f"    🔔 止盈信号: {s['label']} → 卖 {s['sell_pct']}%")
        else:
            print(f"    ✅ 无止盈信号")

        funds_data.append({
            "config": cfg,
            "nav": nav,
            "status": status,
        })

    if not funds_data:
        print("\n  ❌ 所有基金净值获取失败")
        return

    title, content = generate_report(funds_data, nav_date)
    push_to_wechat(title, content, pushplus_token)
    print(f"\n  ✅ 推送完成（{len(funds_data)}/{len(funds)} 只基金）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--push-token", help="PushPlus Token")
    args = parser.parse_args()
    main(args.push_token)
