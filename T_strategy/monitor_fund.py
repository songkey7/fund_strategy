#!/usr/bin/env python3
"""
多基金 T 策略净值监控
扫描 input/ 目录下的基金配置文件，合并推送微信提醒
传输渠道: PushPlus Token for WeChat notification
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
            purchases.append({"date": fields[0], "amount": float(fields[1].lstrip("+"))})

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


def t_position_status(cfg, nav):
    t_cost = cfg["t_cost"]
    t_shares = cfg["t_shares"]
    t_entry_nav = cfg["t_entry_nav"]

    if t_shares <= 0 or t_cost <= 0:
        return None

    t_market = t_shares * nav
    t_pnl = t_market - t_cost
    t_pnl_pct = (nav / t_entry_nav - 1) * 100

    tp_levels = [
        {"nav": t_entry_nav * 1.05, "pct": +5, "sell_pct": 60, "sell_shares": int(t_shares * 0.6), "triggered": False},
        {"nav": t_entry_nav * 1.08, "pct": +8, "sell_pct": 40, "sell_shares": int(t_shares * 0.4), "triggered": False},
    ]
    sl_nav = t_entry_nav * 0.92
    sl_triggered = False

    triggered_tp = []
    for tp in tp_levels:
        if nav >= tp["nav"]:
            tp["triggered"] = True
            triggered_tp.append(tp)
    if nav <= sl_nav:
        sl_triggered = True

    return {
        "t_market": t_market,
        "t_pnl": t_pnl,
        "t_pnl_pct": t_pnl_pct,
        "tp_levels": tp_levels,
        "sl_nav": sl_nav,
        "sl_triggered": sl_triggered,
        "triggered_tp": triggered_tp,
    }


def new_t_entry_status(cfg, nav):
    triggered = []
    pending = []
    for entry in cfg.get("new_t_entries", []):
        gap_pct = (entry["nav"] / nav - 1) * 100
        if nav <= entry["nav"]:
            triggered.append(entry)
        else:
            pending.append({**entry, "gap_pct": gap_pct})
    return triggered, pending


def color(v):
    return "#e53e3e" if v >= 0 else "#38a169"


def generate_combined_report(funds_data, nav_date):
    css = "font-family:-apple-system,'PingFang SC',sans-serif;max-width:100%;color:#222;font-size:14px;line-height:1.6"
    card = "background:#fff;border-radius:10px;padding:12px;margin-bottom:8px;box-shadow:0 1px 2px rgba(0,0,0,0.06)"
    up = "#e53e3e"
    dn = "#38a169"

    has_any_alert = False
    fund_sections = []
    fund_names = []

    for fd in funds_data:
        cfg = fd["config"]
        nav = fd["nav"]
        t_status = fd["t_status"]
        new_triggered = fd["new_triggered"]
        new_pending = fd["new_pending"]

        fund_names.append(cfg["fund_name"])

        confirmed_mv = cfg.get("confirmed_mv", cfg["position_cost"])
        base_nav = cfg.get("base_nav", nav)
        total_shares = confirmed_mv / base_nav if base_nav != 0 else 0

        overall_market = total_shares * nav
        overall_pnl = overall_market - cfg["position_cost"]
        overall_pnl_pct = (overall_pnl / cfg["position_cost"]) * 100 if cfg["position_cost"] != 0 else 0

        has_alert = False
        if t_status:
            has_alert = has_alert or bool(t_status["triggered_tp"]) or t_status["sl_triggered"]
        has_alert = has_alert or bool(new_triggered)
        if has_alert:
            has_any_alert = True

        section = f"""
<div style="background:#2b4c7e;color:#fff;border-radius:10px;padding:14px 16px;text-align:center;margin-bottom:8px">
<div style="font-size:16px;font-weight:600;margin:0">{cfg['fund_name']}</div>
<div style="font-size:11px;opacity:0.6;margin:3px 0">{cfg['fund_code']}</div>
</div>

<div style="{card}">
<div style="font-size:13px;font-weight:600;color:#888;margin-bottom:6px">💰 整体持仓</div>
<div style="display:flex;justify-content:space-between;padding:2px 0"><span style="color:#999">净值</span><span style="font-weight:600">{nav:.4f}</span></div>
<div style="display:flex;justify-content:space-between;padding:2px 0"><span style="color:#999">市值</span><span>¥{overall_market:,.0f}</span></div>
<div style="display:flex;justify-content:space-between;padding:2px 0"><span style="color:#999">盈亏</span><span style="color:{color(overall_pnl_pct)};font-weight:600">{overall_pnl_pct:+.1f}%</span></div>
<div style="display:flex;justify-content:space-between;padding:2px 0"><span style="color:#999">浮动</span><span style="color:{color(overall_pnl)};font-weight:600">¥{overall_pnl:+,.0f}</span></div>
</div>
"""

        if t_status:
            section += f"""
<div style="{card}">
<div style="font-size:12px;font-weight:600;color:#888;margin-bottom:4px">T仓 · 成本 ¥{cfg['t_cost']:,.0f} · 均价 {cfg['t_entry_nav']:.4f}</div>
<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:13px"><span style="color:#999">T仓盈亏</span><span style="color:{color(t_status['t_pnl_pct'])};font-weight:600">{t_status['t_pnl_pct']:+.1f}%</span></div>
</div>
"""

        # Alerts
        if t_status:
            for tp in t_status["triggered_tp"]:
                proceeds = tp["sell_shares"] * nav
                section += f"""
<div style="background:#fff5f5;border:1px solid #fc8181;border-radius:10px;padding:10px;margin-bottom:6px;text-align:center">
<div style="font-size:14px;font-weight:700;color:#c53030;margin-bottom:4px">🟢 T止盈 +{tp['pct']}%</div>
<div style="font-size:13px;font-weight:600">→ 卖出 {tp['sell_shares']:,} 份（{tp['sell_pct']}%）约 ¥{proceeds:,.0f}</div>
</div>"""
            if t_status["sl_triggered"]:
                section += f"""
<div style="background:#fff5f5;border:1px solid #fc8181;border-radius:10px;padding:10px;margin-bottom:6px;text-align:center">
<div style="font-size:14px;font-weight:700;color:#c53030;margin-bottom:4px">🔴 T止损 -8%</div>
<div style="font-size:13px;font-weight:600">→ 全出 {cfg['t_shares']:,} 份约 ¥{cfg['t_shares'] * nav:,.0f}</div>
</div>"""

        for entry in new_triggered:
            cost = entry["shares"] * nav
            section += f"""
<div style="background:#fff5f5;border:1px solid #fc8181;border-radius:10px;padding:10px;margin-bottom:6px;text-align:center">
<div style="font-size:14px;font-weight:700;color:#c53030;margin-bottom:4px">🟢 开仓触发 {entry['pct']:+.0f}%</div>
<div style="font-size:13px;font-weight:600">→ 买入 {entry['shares']:,} 份 @ {entry['nav']:.4f} 约 ¥{cost:,.0f}</div>
</div>"""

        # Next action if no alert
        fund_has_alert = bool(new_triggered)
        if t_status:
            fund_has_alert = fund_has_alert or bool(t_status["triggered_tp"]) or t_status["sl_triggered"]

        if not fund_has_alert:
            upcoming = []
            if t_status:
                for tp in t_status["tp_levels"]:
                    if not tp["triggered"]:
                        upcoming.append(("止盈", tp["nav"], f"+{tp['pct']}% 卖{tp['sell_pct']}%"))
            for entry in new_pending:
                upcoming.append(("开仓", entry["nav"], f"{entry['pct']:+.0f}% 买{entry['shares']:,}份"))
            upcoming.sort(key=lambda x: abs(x[1] - nav))
            n = upcoming[0] if upcoming else ("—", 0, "")
            gap = abs(n[1] - nav)

            section += f"""
<div style="background:#edf2ff;border:1px solid #90b4f0;border-radius:10px;padding:12px;margin-bottom:6px;text-align:center">
<div style="color:#4a5568;font-size:13px;font-weight:600">⏳ 持仓观望，无触发</div>
<div style="color:#2b6cb0;font-size:13px;font-weight:600;margin-top:4px">下一步 {n[0]} {n[2]} @ {n[1]:.4f}</div>
<div style="color:#4a5568;font-size:11px;margin-top:2px">差 {gap:.4f}</div>
</div>"""

        # T仓止盈/止损
        if t_status:
            section += f"""
<div style="{card}">
<div style="font-size:13px;font-weight:600;color:#888;margin-bottom:6px">T仓止盈/止损</div>"""
            for tp in t_status["tp_levels"]:
                gap = abs(tp["nav"] - nav)
                if tp["triggered"]:
                    tag = '<span style="background:#c6f6d5;color:#276749;font-size:11px;padding:1px 5px;border-radius:3px">已触发</span>'
                else:
                    tag = f'<span style="color:#aaa;font-size:12px">差{gap:.4f}</span>'
                section += f'<div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid #f2f2f2;font-size:13px"><span>+{tp["pct"]}% {tp["nav"]:.4f} 卖{tp["sell_pct"]}%</span>{tag}</div>'

            sl_gap = nav - t_status["sl_nav"]
            if t_status["sl_triggered"]:
                sl_tag = '<span style="background:#fed7d7;color:#9b2c2c;font-size:11px;padding:1px 5px;border-radius:3px">已触发</span>'
            else:
                sl_tag = f'<span style="color:#aaa;font-size:12px">距离{sl_gap:.4f}</span>'
            section += f'<div style="display:flex;justify-content:space-between;padding:3px 0;font-size:13px"><span>-8% {t_status["sl_nav"]:.4f} 全出</span>{sl_tag}</div>'
            section += '</div>'

        # 新开T仓点位
        entries = cfg.get("new_t_entries", [])
        if entries:
            section += f"""
<div style="{card}">
<div style="font-size:13px;font-weight:600;color:#888;margin-bottom:6px">新开T仓点位</div>"""
            for entry in entries:
                gap = (entry["nav"] / nav - 1) * 100
                if nav <= entry["nav"]:
                    tag = '<span style="background:#c6f6d5;color:#276749;font-size:11px;padding:1px 5px;border-radius:3px">已触发</span>'
                else:
                    tag = f'<span style="color:#aaa;font-size:12px">距{gap:+.1f}%</span>'
                section += f'<div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid #f2f2f2;font-size:13px"><span>{entry["nav"]:.4f} ({entry["pct"]:+.0f}%) {entry["shares"]:,}份</span>{tag}</div>'
            section += '</div>'

        fund_sections.append(section)

    title = " | ".join(fund_names)
    if has_any_alert:
        title = "⚡ " + title

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="{css};background:#f0f0f0;padding:12px;margin:0">

<div style="background:#1a1a2e;color:#fff;padding:18px 16px;border-radius:12px;text-align:center;margin-bottom:10px">
<div style="font-size:18px;font-weight:600;margin:0">📊 基金T策略监控</div>
<div style="font-size:11px;opacity:0.5;margin:4px 0 0">{nav_date}</div>
</div>

{'<div style="border-top:2px dashed #d0d0d0;margin:14px 0 8px"></div>'.join(fund_sections)}

<div style="text-align:center;color:#aaa;font-size:11px;margin-top:12px">数据来源: 东方财富 | 仅供参考</div>
</body></html>"""

    return title, html


def main(pushplus_token=None):
    if pushplus_token is None:
        pushplus_token = os.environ.get("PUSHPLUS_TOKEN")

    print("=" * 60)
    print(f"  多基金T策略监控 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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
        print(f"\n  [{code}] {name}")

        nav, date = fetch_latest_nav(code)
        if nav is None:
            print(f"    ❌ 获取净值失败，跳过")
            continue

        print(f"    净值: {nav:.4f} ({date})")
        nav_date = date or nav_date

        t_status = t_position_status(cfg, nav)
        new_triggered, new_pending = new_t_entry_status(cfg, nav)

        if t_status:
            print(f"    T仓盈亏: {t_status['t_pnl_pct']:+.1f}%")
            for tp in t_status["triggered_tp"]:
                print(f"    ⚡ T止盈触发: +{tp['pct']}% ¥{tp['nav']:.4f}")
            if t_status["sl_triggered"]:
                print(f"    🔴 T止损触发: ¥{t_status['sl_nav']:.4f}")

        for e in new_triggered:
            print(f"    🟢 新T入场: ¥{e['nav']:.4f} 买 {e['shares']:,}份")

        if t_status and not (t_status["triggered_tp"] or t_status["sl_triggered"]) and not new_triggered:
            print(f"    无触发")

        funds_data.append({
            "config": cfg,
            "nav": nav,
            "t_status": t_status,
            "new_triggered": new_triggered,
            "new_pending": new_pending,
        })

    if not funds_data:
        print("\n  ❌ 所有基金净值获取失败")
        return

    title, content = generate_combined_report(funds_data, nav_date)
    push_to_wechat(title, content, pushplus_token)

    print(f"\n  ✅ 推送完成（{len(funds_data)}/{len(funds)} 只基金）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--push-token", help="PushPlus Token")
    args = parser.parse_args()
    main(args.push_token)
