#!/usr/bin/env python3
"""
月度智能定投建议推送
每月最后一个工作日，根据PE百分位计算各基金定投金额
基准金额: 2000/月/基金
"""

import requests, json, os, re
from datetime import datetime, timedelta

FUND_META = {
    "004744": {
        "fund_code": "004744",
        "fund_name": "易方达创业板ETF联接C",
        "index_code": "399006",
        "pe_fallback_lg": "创业板50",
    },
    "022429": {
        "fund_code": "022429",
        "fund_name": "天弘中证A500ETF联接C",
        "index_code": "000510",
    },
}

BASE_AMOUNT = 2000


def fetch_index_pe(index_code, fallback_lg=None):
    import akshare as ak
    try:
        if index_code == "000510":
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
            "latest_val": latest_val,
            "percentile": percentile,
            "source_type": source_type,
        }
    except Exception as e:
        print(f"  获取PE失败 {index_code}: {e}")
        return None


def is_last_workday():
    today = datetime.now().date()
    if today.weekday() >= 5:
        return False

    day = today + timedelta(days=1)
    remaining_workdays = 0
    while day.month == today.month:
        if day.weekday() < 5:
            remaining_workdays += 1
        day += timedelta(days=1)
    return remaining_workdays == 0


def calc_dca_multiplier(percentile):
    if percentile < 20:
        return 2.0, "极度低估"
    elif percentile < 40:
        return 1.5, "低估"
    elif percentile < 60:
        return 1.0, "适中"
    elif percentile < 80:
        return 0.5, "偏高"
    else:
        return 0, "高估 · 暂停"


def push_to_wechat(title, content, token, template="html"):
    url = "https://www.pushplus.plus/send"
    payload = {"token": token, "title": title, "content": content, "template": template}
    resp = requests.post(url, json=payload, timeout=10)
    return resp.status_code == 200


def generate_html(advices, month_label):
    css = "font-family:-apple-system,'PingFang SC',sans-serif;max-width:480px;color:#222;font-size:14px;line-height:1.6"
    card = "background:#fff;border-radius:10px;padding:12px;margin-bottom:8px;box-shadow:0 1px 2px rgba(0,0,0,0.06)"

    rows = ""
    total = 0
    for a in advices:
        amount = BASE_AMOUNT * a["multiplier"]
        total += amount
        multiplier_str = f"{a['multiplier']:.1f}x"
        amount_str = f"¥{amount:,.0f}" if amount > 0 else "¥0（暂停）"
        status_color = {
            "极度低估": "#c53030",
            "低估": "#dd6b20",
            "适中": "#666",
            "偏高": "#38a169",
            "高估 · 暂停": "#63b3ed",
        }.get(a["status"], "#666")

        note = ""
        if a.get("pe_fallback_lg"):
            note = f'<span style="font-size:10px;color:#aaa;font-weight:400"> · {a["pe_fallback_lg"]}近似</span>'

        pe_line = ""
        if a["pe"] > 0:
            label = "PE" if a.get("source_type") == "pe" else "点位"
            pe_line = f'<span>{label} {a["pe"]:.2f} · 百分位 {a["percentile"]}%{note}</span>'
        else:
            pe_line = '<span style="color:#aaa">暂无估值数据</span>'

        rows += f"""
<div style="{card}">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
<span style="font-size:15px;font-weight:600">{a['fund_name']}</span>
<span style="color:{status_color};font-weight:600;font-size:14px">{amount_str}</span>
</div>
<div style="font-size:12px;color:#666;display:flex;justify-content:space-between">
<span>{a['fund_code']}</span>
<span style="color:{status_color}">{multiplier_str} · {a['status']}</span>
</div>
<div style="font-size:12px;color:#888;margin-top:4px;display:flex;justify-content:space-between">
{pe_line}
</div>
</div>"""

    total_row = f"""
<div style="background:#edf2ff;border-radius:10px;padding:12px;text-align:center;margin-bottom:8px">
<span style="font-size:14px;color:#666">本月定投合计：</span>
<span style="font-size:18px;font-weight:700;color:#2b6cb0">¥{total:,.0f}</span>
</div>"""

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>月度定投建议</title></head>
<body style="{css};background:#f0f0f0;padding:12px;margin:0">

<div style="background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;border-radius:12px;padding:18px 16px;margin-bottom:10px;text-align:center">
<div style="font-size:18px;font-weight:600;margin:0">📊 {month_label} 定投建议</div>
<div style="font-size:11px;opacity:0.5;margin:4px 0 0">PE百分位驱动 · 每基金基准 ¥{BASE_AMOUNT:,}</div>
</div>

{total_row}
{rows}

<div style="background:#fff;border-radius:10px;padding:10px;margin-bottom:8px;box-shadow:0 1px 2px rgba(0,0,0,0.06);font-size:12px">
<div style="font-size:13px;font-weight:600;color:#888;margin-bottom:4px">倍率规则</div>
<div style="color:#666;line-height:1.7">
PE &lt; 20% · 极度低估 → <b style="color:#c53030">2.0x · ¥4,000</b><br>
PE 20%~40% · 低估 → <b style="color:#dd6b20">1.5x · ¥3,000</b><br>
PE 40%~60% · 适中 → <b>1.0x · ¥2,000</b><br>
PE 60%~80% · 偏高 → <b style="color:#38a169">0.5x · ¥1,000</b><br>
PE &gt; 80% · 高估 → <b style="color:#63b3ed">暂停 · ¥0</b>
</div>
</div>

<div style="text-align:center;color:#aaa;font-size:11px;margin-top:12px">下月定投日请手动买入 · 仅供参考</div>
</body></html>"""

    return html


def main():
    today = datetime.now()
    month_label = f"{today.year}年{today.month}月"

    # 非本地运行时（GitHub Actions），检查是否是最后一个工作日
    if os.environ.get("GITHUB_ACTIONS") and not is_last_workday():
        print(f"  今天不是本月最后一个工作日，跳过推送")
        return

    print("=" * 60)
    print(f"  月度定投建议 | {today.strftime('%Y-%m-%d')} | {month_label}")
    print("=" * 60)

    advices = []
    for code, meta in FUND_META.items():
        print(f"\n  [{code}] {meta['fund_name']}")
        index_code = meta.get("index_code")
        pe_info = None
        if index_code:
            pe_info = fetch_index_pe(index_code, meta.get("pe_fallback_lg"))

        if index_code and not pe_info:
            print(f"    ❌ PE获取失败，跳过")
            continue

        if pe_info:
            multiplier, status = calc_dca_multiplier(pe_info["percentile"])
            label = "PE" if pe_info["source_type"] == "pe" else "点位"
            pe_str = f"{label}: {pe_info['latest_val']:.2f} · 百分位 {pe_info['percentile']}% · {status}"
            pe_val = pe_info['latest_val']
            pct = pe_info['percentile']
        else:
            multiplier = 1.0
            status = "无估值数据"
            pe_str = "暂无PE数据（港股QDII）· 默认 1.0x"
            pe_val = 0
            pct = 0
        amount = BASE_AMOUNT * multiplier
        print(f"    {pe_str}")
        print(f"    定投: {multiplier:.1f}x → ¥{amount:,.0f}")

        pe_note = meta.get("pe_fallback_lg", "")

        advices.append({
            "fund_code": code,
            "fund_name": meta["fund_name"],
            "pe": pe_val,
            "percentile": pct,
            "source_type": pe_info.get("source_type") if pe_info else "pe",
            "multiplier": multiplier,
            "status": status,
            "pe_fallback_lg": pe_note,
        })

    if not advices:
        print("\n  ❌ 无有效数据")
        return

    html = generate_html(advices, month_label)

    out_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "月度定投建议.html")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n  📄 报告已生成: {out_file}")

    token = os.environ.get("PUSHPLUS_TOKEN")
    if token:
        title = f"📊 {month_label} 定投建议"
        if push_to_wechat(title, html, token):
            print(f"\n  ✅ 推送成功")
        else:
            print(f"\n  ❌ 推送失败")
    else:
        print(f"\n  WARNING: PUSHPLUS_TOKEN not configured")


if __name__ == "__main__":
    main()
