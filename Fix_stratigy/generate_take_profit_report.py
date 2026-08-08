#!/usr/bin/env python3
"""
宽基智能定投止盈报告生成
输出: 定投止盈信息.html（策略说明 + 各基金止盈状态）
"""

import requests, json, os, re, argparse
from datetime import datetime, timedelta

OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "定投止盈信息.html")
INPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "input")

FUND_META = {
    "004744": {
        "fund_code": "004744",
        "fund_name": "易方达创业板ETF联接C",
        "index_code": "399006",
        "index_name": "创业板指",
        "pe_fallback_lg": "创业板50",
        "target_return": [20, 30, 50],
        "target_sell_pct": [30, 30, 40],
        "pe_sell_threshold": [85, 95],
        "pe_sell_pct": [50, 50],
    },
    "022429": {
        "fund_code": "022429",
        "fund_name": "天弘中证A500ETF联接C",
        "index_code": "000510",
        "index_name": "中证A500",
        "target_return": [20, 30, 50],
        "target_sell_pct": [30, 30, 40],
        "pe_sell_threshold": [85, 95],
        "pe_sell_pct": [50, 50],
    },
    "013309": {
        "fund_code": "013309",
        "fund_name": "易方达恒生科技ETF联接C",
        "index_code": "HSTECH",
        "index_name": "恒生科技",
        "target_return": [20, 30, 50],
        "target_sell_pct": [30, 30, 40],
        "pe_sell_threshold": [85, 95],
        "pe_sell_pct": [50, 50],
    },
}


def load_purchases():
    funds = []
    for code, meta in FUND_META.items():
        filepath = os.path.join(INPUT_DIR, code)
        purchases = []
        if os.path.isfile(filepath):
            with open(filepath) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split()
                    if len(parts) >= 2:
                        purchases.append({"date": parts[0], "amount": float(parts[1])})
        funds.append({**meta, "purchases": purchases})
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
                if records:
                    nav = float(records[0]["DWJZ"])
                    date = records[0]["FSRQ"]
                    return nav, date
        except Exception as e:
            print(f"  获取净值失败 {fund_code} attempt {attempt+1}: {e}")
    return None, None


def fetch_nav_history(fund_code):
    import akshare as ak
    try:
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
        nav_map = {}
        for _, row in df.iterrows():
            key = row["净值日期"].strftime("%Y-%m-%d") if hasattr(row["净值日期"], "strftime") else str(row["净值日期"])[:10]
            nav_map[key] = float(row["单位净值"])
        return nav_map
    except Exception as e:
        print(f"  获取历史净值失败 {fund_code}: {e}")
        return {}


def fetch_index_pe(index_code, fallback_lg=None):
    import akshare as ak
    try:
        if index_code in ("000510",):
            df = ak.stock_zh_index_value_csindex(symbol=index_code)
            col = "市盈率1"
            source_type = "pe"
        elif index_code == "HSTECH":
            df = ak.stock_hk_index_daily_sina(symbol=index_code)
            col = "close"
            source_type = "price"
        elif fallback_lg:
            df = ak.stock_index_pe_lg(symbol=fallback_lg)
            col = "滚动市盈率"
            source_type = "pe"
        else:
            return None

        vals = df[col].dropna()
        latest_val = vals.iloc[-1]
        percentile = round((vals < latest_val).sum() / len(vals) * 100, 1)
        return {
            "latest_pe": latest_val,
            "percentile": percentile,
            "source_type": source_type,
            "pe_20": round(vals.quantile(0.2), 2),
            "pe_40": round(vals.quantile(0.4), 2),
            "pe_60": round(vals.quantile(0.6), 2),
            "pe_80": round(vals.quantile(0.8), 2),
            "pe_85": round(vals.quantile(0.85), 2),
            "pe_95": round(vals.quantile(0.95), 2),
        }
    except Exception as e:
        print(f"  获取指数PE失败 {index_code}: {e}")
        return None


def match_purchase_nav(purchases, nav_map):
    str_nav_map = {}
    for d in sorted(nav_map.keys()):
        str_nav_map[d] = nav_map[d]
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


def check_take_profit(purchases_matched, latest_nav, pe_info, cfg):
    total_cost = sum(p["amount"] for p in purchases_matched)
    total_shares = sum(p["shares"] for p in purchases_matched)
    current_mv = total_shares * latest_nav
    total_return_pct = round((current_mv / total_cost - 1) * 100, 2) if total_cost else 0

    signals = []

    target_return = cfg.get("target_return", [20, 30, 50])
    target_sell_pct = cfg.get("target_sell_pct", [30, 30, 40])
    for tr, sp in zip(target_return, target_sell_pct):
        if total_return_pct >= tr:
            sell_mv = current_mv * sp / 100
            signals.append({
                "type": "target",
                "label": f"累计收益 ≥ {tr}%",
                "sell_pct": sp,
                "sell_mv": sell_mv,
                "sell_shares": total_shares * sp / 100,
                "priority": tr,
            })

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
        "avg_cost_nav": round(total_cost / total_shares, 4) if total_shares else 0,
        "signals": unique_signals,
        "pe_info": pe_info,
        "purchases_matched": purchases_matched,
    }


def color(v):
    return "#e53e3e" if v >= 0 else "#38a169"


def generate_html(funds_data, nav_date):
    css = "font-family:-apple-system,'PingFang SC',sans-serif;max-width:480px;color:#222;font-size:14px;line-height:1.6"
    card = "background:#fff;border-radius:10px;padding:12px;margin-bottom:8px;box-shadow:0 1px 2px rgba(0,0,0,0.06)"
    red = "#e53e3e"
    green = "#38a169"
    blue = "#2b6cb0"

    has_any_signal = any(fd["status"]["signals"] for fd in funds_data)

    fund_sections = []
    for fd in funds_data:
        cfg = fd["config"]
        st = fd["status"]
        pe = st["pe_info"]
        nav = fd["nav"]

        c = red if st["total_return_pct"] >= 0 else green
        signals = st["signals"]
        pe_note = f'<span style="font-size:10px;color:#aaa;font-weight:400"> · {cfg.get("pe_fallback_lg","")}近似</span>' if cfg.get("pe_fallback_lg") else ""

        # 标题头部
        section = f"""
<div style="background:#2b4c7e;color:#fff;border-radius:10px;padding:14px 16px;text-align:center;margin-bottom:8px">
<div style="font-size:16px;font-weight:600;margin:0">{cfg['fund_name']}</div>
<div style="font-size:11px;opacity:0.6;margin:3px 0">{cfg['fund_code']} · 跟踪 {cfg.get('index_name','')}</div>
</div>
"""

        # 持仓卡片
        section += f"""
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

        # PE估值卡片
        if pe:
            pe_label = "PE" if pe.get("source_type") == "pe" else "点位"
            pe_pct_color = red if pe["percentile"] >= 80 else (blue if pe["percentile"] < 40 else "#666")
            section += f"""
<div style="{card}">
<div style="font-size:13px;font-weight:600;color:#888;margin-bottom:6px">📊 {cfg.get('index_name','指数')} 估值{pe_note}</div>
<div style="display:flex;justify-content:space-between;padding:2px 0"><span style="color:#999">当前{pe_label}</span><span style="font-weight:600">{pe['latest_pe']:.2f}</span></div>
<div style="display:flex;justify-content:space-between;padding:2px 0"><span style="color:#999">{pe_label}百分位</span><span style="color:{pe_pct_color};font-weight:600">{pe['percentile']}%</span></div>
<div style="background:#f2f2f2;border-radius:6px;padding:6px 8px;margin-top:6px;font-size:12px">
<div style="display:flex;justify-content:space-between;color:#999">
<span>20%</span><span>40%</span><span>60%</span><span>80%</span>
</div>
<div style="display:flex;justify-content:space-between;font-weight:600">
<span>{pe['pe_20']:.2f}</span><span>{pe['pe_40']:.2f}</span><span>{pe['pe_60']:.2f}</span><span>{pe['pe_80']:.2f}</span>
</div>
</div>
</div>
"""

        # 止盈信号 OR 无信号提示
        if signals:
            for sig in signals:
                section += f"""
<div style="background:#fff5f5;border:2px solid #fc8181;border-radius:10px;padding:12px;margin-bottom:6px;text-align:center">
<div style="font-size:15px;font-weight:700;color:#c53030;margin-bottom:4px">🔔 止盈信号触发</div>
<div style="font-size:14px;font-weight:600;color:#c53030">{sig['label']}</div>
<div style="font-size:13px;color:#666;margin-top:6px">
→ 卖出 {sig['sell_pct']}%（{sig['sell_shares']:,.0f} 份）约 ¥{sig['sell_mv']:,.0f}
</div>
</div>"""
        else:
            target_return = cfg.get("target_return", [20, 30, 50])
            pe_sell_threshold = cfg.get("pe_sell_threshold", [85, 95])
            gap_tr = target_return[0] - st["total_return_pct"]
            section += f"""
<div style="background:#edf2ff;border:1px solid #90b4f0;border-radius:10px;padding:10px;margin-bottom:6px;text-align:center">
<div style="font-size:13px;font-weight:600;color:#444">⏳ 持仓中 · 无止盈信号</div>
<div style="font-size:12px;color:#888;margin-top:4px">
目标收益止盈: 距 {target_return[0]}% 还剩 {gap_tr:.1f}%（当前 {st['total_return_pct']:+.1f}%）</div>"""
            if pe:
                gap_pe = pe_sell_threshold[0] - pe["percentile"]
                section += f"""
<div style="font-size:12px;color:#888">
估值止盈: 距 PE百分位 {pe_sell_threshold[0]}% 还剩 {gap_pe:.1f}%（当前 {pe['percentile']}%）</div>"""
            section += "</div>"

        # 定投明细
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

        fund_sections.append(section)

    # 止盈策略说明
    strategy_html = f"""
<div style="background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;border-radius:12px;padding:18px 16px;margin-bottom:10px">
<div style="font-size:18px;font-weight:600;text-align:center;margin:0 0 12px 0">📊 宽基智能定投 · 买卖策略</div>

<div style="background:rgba(255,255,255,0.08);border-radius:8px;padding:12px;margin-bottom:8px">
<div style="font-size:13px;font-weight:600;margin-bottom:8px;color:#90b4f0">📈 买入三原则</div>

<div style="font-size:12px;color:#ccc;line-height:1.7;margin-bottom:10px">
<b style="color:#fdaf6b">原则一 · PE百分位定方向</b><br>
PE &lt; 60% → 正常定投 | PE 60%~80% → 减半定投 | PE &gt; 80% → 暂停定投
</div>

<div style="font-size:12px;color:#ccc;line-height:1.7;margin-bottom:10px">
<b style="color:#fdaf6b">原则二 · 净值回调抓节奏</b><br>
持仓净值每跌 <b>5%</b> 追加 1 份（约 ¥5,000）；再跌 <b>10%</b> 追加 2 份
</div>

<div style="font-size:12px;color:#ccc;line-height:1.7">
<b style="color:#fdaf6b">原则三 · 低估区加倍</b><br>
PE &lt; 40% 时，每期定投金额 × 1.5；PE &lt; 20% 时 × 2.0
</div>
</div>

<div style="background:rgba(255,255,255,0.08);border-radius:8px;padding:12px;margin-bottom:8px">
<div style="font-size:13px;font-weight:600;margin-bottom:6px;color:#fc8181">🔔 卖出双信号（谁先触发按谁执行）</div>

<div style="margin-bottom:8px">
<div style="font-size:12px;font-weight:600;color:#fdaf6b;margin-bottom:3px">信号一 · 目标收益止盈</div>
<table style="width:100%;border-collapse:collapse;font-size:12px">
<tr style="color:#ccc;border-bottom:1px solid rgba(255,255,255,0.1)"><td>累计收益率</td><td style="text-align:center">操作</td></tr>
<tr style="border-bottom:1px solid rgba(255,255,255,0.05)"><td>≥ 20%</td><td style="text-align:center;color:#fc8181">卖出 30%</td></tr>
<tr style="border-bottom:1px solid rgba(255,255,255,0.05)"><td>≥ 30%</td><td style="text-align:center;color:#fc8181">再卖 30%</td></tr>
<tr><td>≥ 50%</td><td style="text-align:center;color:#fc8181">清仓</td></tr>
</table>
</div>

<div>
<div style="font-size:12px;font-weight:600;color:#fdaf6b;margin-bottom:3px">信号二 · 估值止盈（PE百分位）</div>
<table style="width:100%;border-collapse:collapse;font-size:12px">
<tr style="color:#ccc;border-bottom:1px solid rgba(255,255,255,0.1)"><td>PE百分位</td><td style="text-align:center">操作</td></tr>
<tr style="border-bottom:1px solid rgba(255,255,255,0.05)"><td>≥ 85%</td><td style="text-align:center;color:#fc8181">卖出 50%</td></tr>
<tr><td>≥ 95%</td><td style="text-align:center;color:#fc8181">清仓</td></tr>
</table>
</div>
</div>
</div>
"""

    signals_badge = ""
    if has_any_signal:
        signals_badge = '<span style="background:#c53030;color:#fff;font-size:11px;padding:2px 6px;border-radius:3px;margin-left:8px">有信号</span>'

    title = "📊 宽基定投止盈监控"
    if has_any_signal:
        title = "🔔 " + title

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>定投止盈信息</title></head>
<body style="{css};background:#f0f0f0;padding:12px;margin:0">

{strategy_html}

<div style="background:#1a1a2e;color:#fff;padding:12px 16px;border-radius:12px;text-align:center;margin-bottom:10px">
<div style="font-size:16px;font-weight:600;margin:0">{title}{signals_badge}</div>
<div style="font-size:11px;opacity:0.5;margin:4px 0 0">{nav_date} 更新</div>
</div>

{'<div style="border-top:2px dashed #d0d0d0;margin:14px 0 8px"></div>'.join(fund_sections)}

<div style="text-align:center;color:#aaa;font-size:11px;margin-top:12px">数据来源: 东方财富 · 中证指数 | 仅供参考 · 不构成投资建议</div>
</body></html>"""

    return html


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


def main():
    print("=" * 60)
    print(f"  宽基定投止盈报告 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    funds = load_purchases()
    print(f"  加载 {len(funds)} 个基金配置")
    funds_data = []
    nav_date = datetime.now().strftime("%Y-%m-%d")

    for cfg in funds:
        code = cfg["fund_code"]
        name = cfg["fund_name"]
        index_code = cfg.get("index_code")
        print(f"\n  [{code}] {name}")

        nav, date = fetch_latest_nav(code)
        if nav is None:
            print(f"    ❌ 获取净值失败，跳过")
            continue
        print(f"    净值: {nav:.4f} ({date})")
        nav_date = date or nav_date

        nav_map = fetch_nav_history(code)
        purchases_matched = match_purchase_nav(cfg["purchases"], nav_map)

        pe_info = None
        if index_code:
            pe_info = fetch_index_pe(index_code, cfg.get("pe_fallback_lg"))
            if pe_info:
                label = "PE" if pe_info.get("source_type") == "pe" else "点位"
                print(f"    {label}: {pe_info['latest_pe']:.2f} (百分位 {pe_info['percentile']}%)")

        status = check_take_profit(purchases_matched, nav, pe_info, cfg)
        print(f"    总投入: ¥{status['total_cost']:,.0f}")
        print(f"    市值: ¥{status['current_mv']:,.0f}")
        print(f"    累计收益: {status['total_return_pct']:+.2f}%")

        for s in status["signals"]:
            print(f"    🔔 止盈: {s['label']} → 卖 {s['sell_pct']}%")

        funds_data.append({"config": cfg, "nav": nav, "status": status})

    if not funds_data:
        print("\n  ❌ 无有效数据")
        return

    html = generate_html(funds_data, nav_date)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n  ✅ 报告已生成: {OUTPUT_FILE}")

    pushplus_token = os.environ.get("PUSHPLUS_TOKEN")
    if pushplus_token:
        title = "📊 宽基定投止盈监控"
        has_any_signal = any(fd["status"]["signals"] for fd in funds_data)
        if has_any_signal:
            title = "🔔 " + title
        push_to_wechat(title, html, pushplus_token)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--push-token", help="PushPlus Token")
    args = parser.parse_args()
    if args.push_token:
        os.environ["PUSHPLUS_TOKEN"] = args.push_token
    main()
