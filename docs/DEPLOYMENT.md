# 部署总览（Mac Studio）

## 端口与域名

| 服务 | 本地 | Tunnel 名 | 公网 |
|------|------|-----------|------|
| 事故车提醒 | 127.0.0.1:9000 | accident-vehicle-reminder | http://127.0.0.1:9000 |
| VIP 保养提醒 | 127.0.0.1:9002 | m-hero-vip-alert | http://127.0.0.1:9002 |
| 区域报表 | 127.0.0.1:9003 | m-hero-district-form | http://127.0.0.1:9003 |
| 门店超时审计 | 127.0.0.1:3001 | store-audit | http://127.0.0.1:3001 |
| 超时机器人统计 | 127.0.0.1:5001 | store-timeout-cleaner | http://127.0.0.1:5001 |
| 控制台黄页 | 127.0.0.1:9004 | m-hero-hub | http://127.0.0.1:9004 |

Cloudflared 配置一般在 `~/.cloudflared/config-*.yml`。

## launchd（节选）

| Label | 作用 |
|-------|------|
| `com.accident-vehicle-reminder.web` | 事故车控制台 |
| `com.m-hero-vip-custom-alert.web` | VIP 控制台 |
| `com.m-hero-vip-custom-alert.watchdog` | VIP HTTP 健康监控 |
| `com.mhero-district-form.web` | 区域报表控制台 |
| `com.mhero-district-form.pipeline` | 每天 08:30 流水线 |
| `com.store-timeout-cleaner.web` | 超时机器人统计 |
| `com.m-hero-hub.web` | 黄页 |
| `com.cloudflare.cloudflared.*` | 各隧道 |

门店超时审计当前多用 **pm2**（`store-audit`）而非 launchd。

## 共享会话

所有 DMS 相关 launchd / `.env` 应设置：

```text
DFMC_DMS_SESSION_HOME=/Users/i/dms-shared-session
DFMC_DMS_BROWSER_EXECUTABLE=…/ms-playwright/chromium-…/Google Chrome for Testing
TZ=Asia/Shanghai
```

详见 [SHARED_DMS_BROWSER.md](SHARED_DMS_BROWSER.md)。
