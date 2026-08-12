# 项目依赖关系

## 依赖矩阵

| 项目 | 运行时 | 依赖其他 m-hero 项目 | 外部依赖 | 共享资源 |
|------|--------|----------------------|----------|----------|
| accident-vehicle-reminder | Python / Flask | — | DMS、飞书应用 | `dms-shared-session` |
| m-hero-vip-custom-alert | Python / Flask | — | DMS、飞书多维表 / HeroClaw | `dms-shared-session` |
| mhero_district_form | Python / Flask + FastAPI | — | DMS、飞书群 Webhook | `dms-shared-session` |
| m-hero-store-timeout-audit | Node / Express / Vue | feishu-bitable-middleware（本地包） | 飞书多维表 | — |
| store-timeout-cleaner | Python / Flask | — | 本地上传 Excel | — |
| m-hero-hub | Python / Flask | 无代码依赖，仅链接各控制台 URL | Cloudflare Tunnel | — |

## 共享 DMS 浏览器（运行时耦合）

以下三者**运行时强耦合**，共用同一 Chromium 进程与 profile：

```text
accident-vehicle-reminder  ──┐
m-hero-vip-custom-alert    ──┼── DFMC_DMS_SESSION_HOME
mhero_district_form        ──┘         │
                                       ▼
                         /Users/i/dms-shared-session
                           .browser-profile/
                           .runtime/
                             browser-state.json
                             keepalive-state.json
                             exporting.lock
                             crawl_schedule.json
                             crawl_registry.json
```

| 能力 | 事故车 | VIP | 区域报表 |
|------|--------|-----|----------|
| 启动 / 断开浏览器 | ✅ | ✅ | ❌（只附着） |
| 保活强刷进程 | ✅（主） | ✅（可拉起） | ❌ |
| 定时爬取 | 10:00 / 17:00 | 09:00 | 08:30 |
| 导出互斥锁 | ✅ | ✅ | ✅ |

权威说明：[SHARED_DMS_BROWSER.md](SHARED_DMS_BROWSER.md)。

## 数据流

### 事故车提醒

```text
DMS 维修工单页
  → crawl_maintenance_orders.py
  → output/*.xlsx → import → rule_engine
  → 飞书卡片 / Excel 报表
```

### VIP 保养提醒

```text
飞书多维表（00:00 同步 VIP + 提醒人）
DMS 保养提醒任务（09:00 导出）
  → VIN 匹配 → 飞书卡片（任务编码去重）
```

### 区域报表

```text
DMS × 7 份源表（08:30）
  → download/*.xlsx
  → app.processor.build_report
  → output/区域各指标情况一览*.xlsx
  → 飞书群 Webhook（下载链接）
```

### 门店超时审计

```text
store_list.xlsx（主数据）
  ↔ 飞书「门店清单」多维表（自动同步）
  ↔ 飞书「超时提醒专属名称」
  → 未登记比对 → 督导私聊 + 仪表板
依赖：feishu-bitable-middleware
```

### 超时机器人统计

```text
上传 Excel / 历史数据
  → Flask 解析统计
  → data.json + 控制台展示 / CSV 导出
（不访问 DMS，不依赖共享浏览器）
```

### 黄页

```text
探活各控制台本地端口
  → 展示在线状态 + 跳转链接（公网 URL 来自未入库 local 配置）
```

## 错峰与互斥

| 时刻 | 任务 | 强刷保护 |
|------|------|----------|
| 08:27–完成 | 区域报表窗口 | 时刻表 pre=3min + 登记 |
| 08:57–完成 | VIP | 同上 |
| 09:57–完成 | 事故车上午 | 同上 |
| 16:57–完成 | 事故车下午 | 同上 |

手动并行爬取仍会因 `exporting.lock` 互斥失败（刻意为之）。

## 不构成依赖的关系

- 黄页 ↔ 各业务：仅 HTTP 探活与超链接，业务可独立运行。
- 超时审计 ↔ 超时机器人统计：业务相关但代码/数据不互通。
- 区域报表桌面 App / FastAPI `:8000`：与控制台 `:9003` 流水线并行存在，共享 `app/processor`。
