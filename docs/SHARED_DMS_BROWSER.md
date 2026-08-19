# 共享 DMS 浏览器与强刷保护

事故车提醒、VIP 保养提醒、区域报表自动化共用 **一套** Playwright Chromium + CDP 会话。

## 环境变量

```bash
export DFMC_DMS_SESSION_HOME=/Users/i/dms-shared-session
export DFMC_DMS_BROWSER_EXECUTABLE="…/ms-playwright/chromium-…/Google Chrome for Testing"
```

未设置 `DFMC_DMS_SESSION_HOME` 时，各插件回落到自己目录下的独立 `.browser-profile`（不推荐在生产混用）。

## 目录布局

```text
$DFMC_DMS_SESSION_HOME/
  .browser-profile/              # Chromium --user-data-dir（单实例）
  .runtime/
    browser-state.json           # CDP port / pid
    keepalive-state.json         # 保活状态 / 下次刷新
    keepalive.log                # 保活轮次日志（约 2MB 轮转）
    exporting.lock               # 爬虫互斥
    crawl_schedule.json          # 爬取时刻表（本文重点）
    crawl_registry.json          # 爬取登记（进行中 / 今日已完成）
```

实现代码（三仓各有一份副本，应保持同步）：

- `accident-vehicle-reminder/scripts/dfmc_browser_utils.py`
- `m-hero-vip-custom-alert/scripts/dfmc_browser_utils.py`
- `mhero_district_form/scripts/dfmc_browser_utils.py`
- 保活：`*/scripts/keepalive_browser.py`

---

## 爬取时刻表（`crawl_schedule.json`）

用途：让 keepalive **强刷**在定时爬取前后自动让路，避免 `page.reload` 打断导出。

### 默认条目（北京时间）

| id | 名称 | 计划时间 | 所属项目 / owner | 典型任务 |
|----|------|----------|-------------------|----------|
| `district-form` | 区域报表 | **08:30** | `mhero_district_form` | launchd pipeline，爬 7 份源表并出报表 |
| `vip-alert` | VIP保养提醒 | **09:00** | `vip_maintenance_reminder` | 导出保养提醒 → 匹配发送 |
| `accident-morning` | 事故车上午任务 | **10:00** | `crawl_maintenance_orders` | 爬维修工单 + 告警 |
| `accident-evening` | 事故车下午报表 | **17:00** | `crawl_maintenance_orders` | 爬维修工单 + 报表 |

### 保护窗口参数

| 字段 | 默认 | 含义 |
|------|------|------|
| `pre_minutes` | **3** | 计划时间前 N 分钟开始禁刷 |
| `await_start_minutes` | **45** | 计划时间后若仍未登记，最长再禁刷 N 分钟 |

对某一启用且今日尚未完成的条目，禁刷区间为：

```text
[计划时间 − pre_minutes, 计划时间 + await_start_minutes]
```

示例（区域报表 08:30）：

| 时刻 | 强刷行为 |
|------|----------|
| 08:26 | 可刷新 |
| **08:27–08:30** | 禁刷（pre 窗口） |
| 08:30 后爬虫已 `register` | 继续禁刷，直到 `unregister` |
| 08:30 后一直没开跑 | 最迟到约 **09:15** 解除（await 到期） |
| 爬取结束并登记完成 | 立即恢复可刷新 |

### 登记表（`crawl_registry.json`）

| 字段 | 说明 |
|------|------|
| `active` | 当前爬取：`owner` / `pid` / `scheduleId` / `startedAt`；无则为 `null` |
| `completedToday.date` | 北京时间日期 `YYYY-MM-DD` |
| `completedToday.ids` | 今日已完成的时刻表 `id` 列表 |

生命周期：

1. 爬虫 `acquire_export_lock(...)` → 自动 `register_crawl`（可带 `schedule_id`）
2. keepalive 见 `active` 或时刻表窗口 → **跳过** `page.reload`
3. `release_export_lock(...)` → `unregister_crawl`，并把对应 `scheduleId` 记入今日已完成
4. 若 `active.pid` 已死，keepalive 会清理陈旧登记

手动爬取（不在时刻表窗口内）同样会登记：从拿锁到放锁全程禁刷，只是没有「提前 3 分钟」窗口。

### 示例 `crawl_schedule.json`

文件路径：`$DFMC_DMS_SESSION_HOME/.runtime/crawl_schedule.json`  
若不存在，代码会按默认值创建。

```json
{
  "pre_minutes": 3,
  "await_start_minutes": 45,
  "entries": [
    {
      "id": "district-form",
      "name": "区域报表",
      "time": "08:30",
      "owners": ["mhero_district_form"],
      "enabled": true
    },
    {
      "id": "vip-alert",
      "name": "VIP保养提醒",
      "time": "09:00",
      "owners": ["vip_maintenance_reminder"],
      "enabled": true
    },
    {
      "id": "accident-morning",
      "name": "事故车上午任务",
      "time": "10:00",
      "owners": ["crawl_maintenance_orders"],
      "enabled": true
    },
    {
      "id": "accident-evening",
      "name": "事故车下午报表",
      "time": "17:00",
      "owners": ["crawl_maintenance_orders"],
      "enabled": true
    }
  ]
}
```

### 如何改时刻表

1. 编辑 `$DFMC_DMS_SESSION_HOME/.runtime/crawl_schedule.json`（立即生效，keepalive 下一轮检查即读）
2. **同时**改各项目真正的定时触发（launchd / 控制台 scheduler），否则会出现「禁刷了但任务没跑」或「任务跑了但没进窗口」
3. 若改了 `owners` / `id`，确认爬虫传入的 `schedule_id` 或 `CRAWLER_OWNER` 仍能对上

---

## 强刷（keepalive）判定顺序

进程：`keepalive_browser.py`（通常由事故车或 VIP 控制台拉起），默认每 **300s** 短连一次 CDP，把 DMS 标签导航到 `#/dashboard`（去掉 `?code=`，不停留在业务页），然后立刻断开。睡眠期间不占 Playwright 连接，避免和定时爬虫抢 CDP。爬虫切页用 `goto_dms_route` 打开干净地址并核对 hash，避免停在上一张表上误点按钮。

`refresh_block_reason()` 任一命中则跳过刷新（本轮不连 CDP）：

1. `exporting.lock` 被存活进程持有  
2. `crawl_registry.json` 存在有效 `active`  
3. 当前时间落在某条未完成时刻表的保护窗口内  

Watchdog（事故车 / VIP，每 30s）：

1. 先按共享 profile 找回 `browser-state`；没有进程则按同一 profile 拉起 Chromium  
2. 浏览器活着但没有 DMS 标签时，用 CDP 打开干净地址，不杀保活  
3. 页面在登录 / SSO 时状态为 `need_login`，需人工登录（不填账密）  
4. 只有浏览器确实不存在且拉起失败，才停保活  

## 启动参数（避免每次输系统密码）

冷启动 Chromium 时统一带：

- `--disable-extensions`：共享 profile 里残留的 1Password / MetaMask 等扩展不再弹密码
- `--use-mock-keychain` / `--password-store=basic`：不走 macOS「Chrome Safe Storage」钥匙串

已在跑的进程不会自动换参数。下次冷启动生效；换 mock keychain 后已加密的 Cookie 可能读不出来，**可能要重新登一次 DMS**，之后不应再弹系统密码。

冷启动不要再往命令行塞 DMS URL（profile 会恢复上次标签，再加一条 URL 就会变成两页）。启动后只 `ensure_dms_tab`：已有 DMS/SSO/登录页则复用并关掉重复页。

## 操作注意

1. 不要在某一控制台随意点「断开连接」——会清共享 `browser-state` 并停保活，影响其他爬虫。
2. 不要并行跑两个导出；锁会拒绝，且共用同一 DMS 标签页。
3. 改业务定时后务必同步 `crawl_schedule.json`。

各仓库简版：

- [accident-vehicle-reminder/docs/shared-browser-session.md](../accident-vehicle-reminder/docs/shared-browser-session.md)
- [m-hero-vip-custom-alert/docs/shared-browser-session.md](../m-hero-vip-custom-alert/docs/shared-browser-session.md)
- 区域报表见 [mhero_district_form/README.md](../mhero_district_form/README.md)「DMS 自动爬取」一节
