# 部署总览（Mac Studio）

## 本机端口与 Tunnel 名

公网 hostname **不要**写进 Git；在本机 `~/.cloudflared/config-*.yml` 与 DNS 中配置。

| 服务 | 本地 | Tunnel 名（示例） |
|------|------|-------------------|
| 事故车提醒 | 127.0.0.1:9000 | accident-vehicle-reminder |
| VIP 保养提醒 | 127.0.0.1:9002 | m-hero-vip-alert |
| 区域报表 | 127.0.0.1:9003 | m-hero-district-form |
| 超时机器人统计 | 127.0.0.1:5001 | store-timeout-cleaner |
| 控制台黄页 | 127.0.0.1:9004 | m-hero-hub |
| NSS 问卷提醒 | 127.0.0.1:9005 | m-hero-nss-questionnaire |

仓库内 `deploy/*.yml.example` 的 `hostname` 使用占位符 `<your-hostname>`。

黄页公网跳转列表放在未入库文件：`m-hero-hub/config/services.local.json`（参见同目录 `*.example`）。

## launchd（节选）

| Label | 作用 |
|-------|------|
| `com.accident-vehicle-reminder.web` | 事故车控制台 |
| `com.m-hero-vip-custom-alert.web` | VIP 控制台 |
| `com.m-hero-vip-custom-alert.watchdog` | VIP HTTP 健康监控 |
| `com.mhero-district-form.web` | 区域报表控制台 |
| `com.mhero-district-form.pipeline` | 每天 08:30 流水线 |
| `com.store-timeout-cleaner.web` | 超时机器人统计 |
| `com.store-timeout-cleaner.sync` | 每天 00:00 / 12:00 从 SCRM 同步客户群 |
| `com.m-hero-hub.web` | 黄页 |
| `com.nss-questionnaire-reminder.web` | NSS 问卷提醒（00:00 同步 / 09:00 发送） |
| `com.cloudflare.cloudflared.*` | 各隧道 |

门店超时审计已于 2026-08-13 下线（原 `:3001` / pm2 `store-audit` / 系统级 `com.cloudflare.cloudflared`）。勿再 `pm2 start`。若系统隧道仍在跑：`sudo cloudflared service uninstall`。

`scrm-api` 为文档仓，无 launchd / 本地端口。

## 共享会话

所有 DMS 相关 launchd / `.env` 应设置：

```text
DFMC_DMS_SESSION_HOME=/Users/i/dms-shared-session
DFMC_DMS_BROWSER_EXECUTABLE=…/ms-playwright/chromium-…/Google Chrome for Testing
TZ=Asia/Shanghai
```

详见 [SHARED_DMS_BROWSER.md](SHARED_DMS_BROWSER.md)。
