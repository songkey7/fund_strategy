# fund_strategy

012805 基金持仓监控分析系统

## 项目结构

```
├── monitor_fund.py          # 主监控脚本 (GitHub Actions + PushPlus推送)
├── analyze_012805.py        # 基金深度分析 (技术面 + 回本策略)
├── monitor_012805.py        # 本地监控脚本 (macOS系统通知)
├── 012805_pingan            # 持仓投资记录
└── 012805_分析报告.md        # 每日分析报告
```

## 🔧 Setup

### 1. PushPlus Token

在 GitHub Secrets 中配置 `PUSHPLUS_TOKEN`

### 2. Run on GitHub Actions

Workflow 自动每天触发一次, 向微信推送净值提醒

### 3. 本地运行监控

```bash
python3 monitor_fund.py --push-token YOUR_PUSHPLUS_TOKEN
```

## 📧 推送服务

使用 [PushPlus](https://www.pushplus.plus/) 发送微信通知。注册即可获得 token。

## 📊 策略

### 三级T策略
| 持仓盈亏 | 策略 |
|---------|------|
| <-15% | 🚨 强力T |
| -10~-15% | ⚠️ 增强T |
| -5~-10% | ⚡ 常规T |
| >-5% | 🔄 被动持有 |
