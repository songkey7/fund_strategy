# T_strategy — 多基金做T策略监控

多基金持仓监控分析系统，扫描 `input/` 目录下的基金配置文件，自动获取净值并通过 PushPlus 推送到微信。

## 项目结构

```
├── monitor_fund.py          # 主监控脚本 (GitHub Actions + PushPlus推送)
├── recovery_analysis.py     # 回本分析 (基于 akshare + 购买记录)
├── monitor_012805.py        # 本地实时监控 (macOS系统通知，单基金)
├── analyze_012805.py        # 基金深度分析 (技术面 + 回本策略)
├── preview.html             # 推送预览模板
├── input/                   # 基金配置目录（每个文件一个基金）
│   ├── 012805_pingan        # 广发恒生科技ETF联接C
│   └── 001156_zhaohang      # 申万菱信新能源汽车
└── 012805_分析报告.md        # 分析报告示例
```

## 基金配置文件格式

`input/` 下每个文件对应一个基金，格式为 **JSON 头部 + `---` + 购买记录**：

```json
{
  "fund_code": "012805",
  "fund_name": "基金名称",
  "position_cost": 71704.83,
  "base_nav": 0.7761,
  "confirmed_mv": 65454.42,
  "t_cost": 10000.0,
  "t_entry_nav": 0.7442,
  "t_shares": 13437,
  "new_t_entries": [
    {"nav": 0.7606, "pct": -2.0, "shares": 8000, "label": "首次开仓"}
  ]
}
---
20250430 +30008.86
20260131 +18006.97
```

### 配置字段说明

| 字段 | 说明 |
|------|------|
| `fund_code` | 基金代码 |
| `fund_name` | 基金名称（推送显示用） |
| `position_cost` | 总投入成本 |
| `base_nav` | 基准净值 |
| `confirmed_mv` | 基准净值对应的确认市值 |
| `t_cost` | T仓总成本 |
| `t_entry_nav` | T仓加权均价 |
| `t_shares` | T仓持有份额 |
| `new_t_entries` | 新开T仓触发点位列表 |

## 使用方式

### GitHub Actions 自动推送

Workflow 每个工作日自动触发，向微信推送净值提醒。需要在 GitHub Secrets 中配置 `PUSHPLUS_TOKEN`。

### 本地运行

```bash
# 多基金监控并推送
python3 monitor_fund.py --push-token YOUR_PUSHPLUS_TOKEN

# 回本分析（所有基金）
python3 recovery_analysis.py

# 回本分析（指定基金）
python3 recovery_analysis.py input/012805_pingan
```

## 推送服务

使用 [PushPlus](https://www.pushplus.plus/) 发送微信通知。注册即可获得 token。

## 做T策略

| 持仓盈亏 | 策略 |
|---------|------|
| <-15% | 🚨 强力T |
| -10~-15% | ⚠️ 增强T |
| -5~-10% | ⚡ 常规T |
| >-5% | 🔄 被动持有 |
