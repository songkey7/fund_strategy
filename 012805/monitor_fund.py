#!/usr/bin/env python3
"""
012805 基金净值监控 (每日一次)
通过 GitHub Actions 每天自动检查净值并推送微信提醒
传输渠道: PushPlus Token for WeChat notification

Usage:
  本地: python3 monitor_fund.py --push-token YOUR_TOKEN
  GitHub Actions: 默认读取环境变量 PUSHPLUS_TOKEN
"""

import requests, json, os, sys, argparse
from datetime import datetime

# ============================================================
# Config
# ============================================================
FUND_CODE = "012805"
# 投资记录
POSITION_COST = 71704.83
POSITION_SHARES = 83236.35

# 关键价位 (以最新净值 0.7761 基准)
ALERT_LEVELS = [
    {
        "nav": 0.7070,
        "pct": -9.0,
        "type": "BUY_HEAVY",
        "title": "重磅买入",
        "color": "red",
        "diff": +1150,
    },
    {
        "nav": 0.7455,
        "pct": -4.0,
        "type": "BUY_NORMAL",
        "title": "正常买入",
        "color": "orange",
        "diff": +5400,
    },
    {"nav": 0.7609, "pct": -2.0, "type": "BUY_LIGHT", "title": "小额买入", "color": "orange"},
    {
        "nav": 0.7992,
        "pct": +3.0,
        "type": "SELL_30",
        "title": "卖30%",
        "color": "darkseagreen",
    },
    {
        "nav": 0.8151,
        "pct": +5.0,
        "type": "SELL_30",
        "title": "卖30%",
        "badge": 12,
    },
    {
        "nav": 0.8382,
        "pct": +8.0,
        "type": "SELL_40",
        "title": "卖40%",
        "badge": 20,
    },
    {"nav": 0.7140, "pct": 0, "type": "STOP_LOSS", "title": "止损", "color": "danger"},
]

# ============================================================
# Data fetching
# ============================================================


def fetch_latest_nav(fund_code):
    """获取最新的基金净值"""
    for attempt in range(3):
        try:
            url = (
                f"https://api.fund.eastmoney.com/f10/lsjz"
                f"?callback=jQuery&fundCode={fund_code}&pageIndex=1&pageSize=1"
                f"&startDate={datetime.now().strftime('%Y-%m-%d')}&endDate={datetime.now().strftime('%Y-%m-%d')}"
            )
            headers = {
                "Referer": "https://fundf10.eastmoney.com/",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=15)
            text = resp.text.strip()
            import re
            m = re.match(r'^\w+\((.*)\)$', text, re.DOTALL)
            if m:
                data = json.loads(m.group(1))
                records = data["Data"]["LSJZList"]
                if not records:
                    print(f"  API返回空 [{attempt+1}]")
                    continue
                latest = records[0]
                nav = float(latest["DWJZ"])
                date = latest["FSRQ"]
                return nav, date
            else:
                print(f"  未能解析JSON [{attempt+1}]: {text[:200]}")
        except Exception as e:
            print(f"  获取净值失败 attempt {attempt+1}: {e}")
    return None, None


# ============================================================
# PushPlus 推送
# ============================================================


def push_to_wechat(title, content, token, template="markdown"):
    """通过 PushPlus 发送微信消息 (https://www.pushplus.plus)"""
    if not token:
        print("   WARNING: PUSHPLUS_TOKEN not configured, skipping push")
        return

    url = "https://www.pushplus.plus/send"
    payload = {"token": token, "title": title, "content": content, "template": template}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            print(f"   PushPlus推送成功: {resp.text}")
        else:
            print(f"   PushPlus推送失败: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"   PushPlus推送异常: {e}")


# ============================================================
# Alert Message
# ============================================================


def generate_alert_message(nav, date, triggered):
    """根据触发的价位生成消息"""
    position_pnl = ((nav * POSITION_SHARES) - POSITION_COST) / POSITION_COST * 100
    current_value = nav * POSITION_SHARES

    # 构建详细的提醒消息 (Markdown格式)
    content = f"""
## 📊 012805 净值监控报告

**数据日期**: {date}
**当前净值**: ¥{nav:.4f}
**市值**: ¥{current_value:,.2f}
**持仓盈亏**: {position_pnl:+.2f}% (¥{current_value-POSITION_COST:+,.0f})

---

### ⚡ 关键价位触发

"""

    for lvl in triggered:
        direction = "跌至" if nav <= lvl["nav"] else "接近"
        content += f"- **{lvl['title']}**: {direction} ¥{lvl['nav']:.4f} ({lvl['pct']:+d}%)\n"

    content += """
---
> 来源: 基金012805智能监控 | <a href='https://github.com'>查看详情</a>
"""
    return content


# ============================================================
# Alert Logic
# ============================================================


def main(pushplus_token=None):

    # Check if we're running in GitHub Actions context
    if pushplus_token is None:
        pushplus_token = os.environ.get("PUSHPLUS_TOKEN")

    print("=" * 65)
    print(f"  012805 净值监控 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)
    print(f"  获取最新净值...")

    nav, date = fetch_latest_nav(FUND_CODE)
    if nav is None:
        print("  ❌ 获取净值失败，停止监控")
        return

    print(f"  最新净值: ¥{nav:.4f} ({date})")

    # 计算持仓盈亏
    position_pnl = ((nav * POSITION_SHARES) - POSITION_COST) / POSITION_COST * 100

    # 确定触发哪些价位
    triggered = []
    for lvl in ALERT_LEVELS:
        if lvl["type"] in ("BUY_HEAVY", "BUY_NORMAL", "BUY_LIGHT"):
            if nav <= lvl["nav"]:
                triggered.append(lvl)
        elif lvl["type"] in ("SELL_30", "SELL_40"):
            if nav >= lvl["nav"]:
                triggered.append(lvl)
        elif lvl["type"] == "STOP_LOSS":
            if nav <= lvl["nav"]:
                triggered.append(lvl)

    # 生成提醒内容
    if triggered:

        title_for_push = "012805"

        for lvl in triggered:
            if lvl["type"] in ("BUY_HEAVY", "BUY_NORMAL", "BUY_LIGHT"):
                title_for_push += "🔴"
            elif lvl["type"] in ("SELL_30", "SELL_40"):
                title_for_push += "🟢"

        content = generate_alert_message(nav, date, triggered)
        push_to_wechat(title_for_push, content, pushplus_token)

        print(f"\n  ✅ 已推送微信提醒")
    else:
        print(f"\n  无触发价位, 当前盈亏: {position_pnl:+.1f}%")
        # 发轻量状态摘要
        summary = f"012805 ¥{nav:.4f} (持仓{position_pnl:+.1f}%) [{date}]"
        push_to_wechat("012815监控", summary, pushplus_token)

    return not triggered


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--push-token", help="PushPlus Token for WeChat push")
    args = parser.parse_args()

    main(args.push_token)
