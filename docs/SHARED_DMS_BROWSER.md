# 共享 DMS 浏览器与强刷保护

事故车提醒、VIP 保养提醒、区域报表自动化共用 **一套** Playwright Chromium + CDP 会话。

## 环境变量

```bash
export DFMC_DMS_SESSION_HOME=/Users/i/dms-shared-session
export DFMC_DMS_BROWSER_EXECUTABLE="/Users/i/Library/Caches/ms-playwright/chromium-1217/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
```

未设置 `DFMC_DMS_SESSION_HOME` 时，各插件回落到自己目录下的独立 `.browser-profile`（不推荐在生产混用）。

## 目录布局

```text
$DFMC_DMS_SESSION_HOME/
  .browser-profile/              # Chromium --user-data-dir（单实例）
  .runtime/
    browser-state.json           # CDP port / pid
    keepalive-state.json         # 保活状态 / 下次刷新
    exporting.lock               # 爬虫互斥
    crawl_schedule.json          # 时刻表
    crawl_registry.json          # 爬取登记（进行中 / 今日已完成）
```

## 强刷（keepalive）

- 进程：`keepalive_browser.py`（通常由事故车或 VIP 控制台拉起）
- 默认间隔：300 秒，对第一个 DMS 标签页 `page.reload`
- **跳过刷新** 当 `refresh_block_reason()` 返回原因：
  1. `exporting.lock` 被持有
  2. `crawl_registry.json` 有进行中登记
  3. 落在时刻表窗口内：`[计划时间 - pre_minutes, 计划时间 + await_start_minutes]`，且今日尚未完成该条目

## 默认时刻表

文件：`$DFMC_DMS_SESSION_HOME/.runtime/crawl_schedule.json`（缺失时由代码写入默认值）。

| id | 时间 | 项目 |
|----|------|------|
| district-form | 08:30 | mhero_district_form |
| vip-alert | 09:00 | m-hero-vip-custom-alert |
| accident-morning | 10:00 | accident-vehicle-reminder |
| accident-evening | 17:00 | accident-vehicle-reminder |

参数：

- `pre_minutes`：默认 3（开跑前禁刷）
- `await_start_minutes`：默认 45（计划点后若仍未登记，最长等待）

爬虫在 `acquire_export_lock` 时自动登记，在 `release_export_lock` 时注销并标记时刻表条目今日已完成。

## 操作注意

1. 不要在某一控制台随意点「断开连接」——会清共享 `browser-state` 并停保活，影响其他爬虫。
2. 不要并行跑两个导出；锁会拒绝，且共用同一 DMS 标签页。
3. 改定时后请同步更新 `crawl_schedule.json`。

各仓库内也有简版说明：

- [accident-vehicle-reminder/docs/shared-browser-session.md](../accident-vehicle-reminder/docs/shared-browser-session.md)
- [m-hero-vip-custom-alert/docs/shared-browser-session.md](../m-hero-vip-custom-alert/docs/shared-browser-session.md)
