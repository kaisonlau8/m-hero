# AI Agent Init · m-hero

猛士服务运营工具集工作区。Agent 开工前先读本文件，再按任务深入子项目。

## 工作区性质

- 路径：`/Users/i/myCode/m-hero`
- **并列多仓**：各业务目录多为独立 Git 仓库；本目录顶层仓 `m-hero` 主要托管总览文档（`README.md` / `docs/` / 本文件）
- 用户偏好：**简体中文**回复；直接改代码迭代；勿擅自 commit/push（除非明确要求）

## 必读文档

| 优先级 | 文档 | 用途 |
|--------|------|------|
| 1 | [README.md](README.md) | 文档地图、本地端口、仓库列表 |
| 2 | [docs/SHARED_DMS_BROWSER.md](docs/SHARED_DMS_BROWSER.md) | 共享 Chromium、**爬取时刻表**、强刷保护 |
| 3 | [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md) | 项目依赖与数据流 |
| 4 | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | launchd / tunnel / 本机端口 |

## 项目速查

| 目录 | 本地 | 职责 | DMS 浏览器 |
|------|------|------|------------|
| `accident-vehicle-reminder/` | `:9000` | 事故车提醒 10:00 / 17:00 | 共享会话（可启停保活） |
| `m-hero-vip-custom-alert/` | `:9002` | VIP 保养提醒 09:00 | 共享会话 |
| `mhero_district_form/` | `:9003` | 区域报表 08:30 | 共享会话（只附着） |
| `m-hero-store-timeout-audit/` | — | **已下线**（原 `:3001` / pm2 `store-audit`） | 不用 |
| `store-timeout-cleaner/` | `:5001` | 超时机器人统计（SCRM 00:00 / 12:00） | 不用 |
| `m-hero-hub/` | `:9004` | 控制台黄页 | 不用 |
| `NSS_Questionnaire_Reminder/` | `:9005` | NSS 问卷提醒 09:00 | 不用 |
| `scrm-api/` | — | 企微 SCRM OpenAPI 文档（只对接生产） | 不用 |
| `feishu-bitable-middleware` | 软链 | 原审计依赖的中间件 | 不用 |

共享会话目录（不进 Git）：`/Users/i/dms-shared-session`  
环境变量：`DFMC_DMS_SESSION_HOME`、`DFMC_DMS_BROWSER_EXECUTABLE`、`TZ=Asia/Shanghai`

## 爬取时刻表（摘要）

文件：`$DFMC_DMS_SESSION_HOME/.runtime/crawl_schedule.json`

| 时间 | id | 项目 |
|------|-----|------|
| 08:30 | `district-form` | 区域报表 |
| 09:00 | `vip-alert` | VIP |
| 10:00 | `accident-morning` | 事故车上午 |
| 17:00 | `accident-evening` | 事故车下午 |

强刷保护：开跑前 **3 分钟**起禁 origin 强刷（`https://m-dms.dfmc.com.cn/`），直至爬取登记结束；到点未开跑最多再等 **45 分钟**。细节见 `docs/SHARED_DMS_BROWSER.md`。

改业务定时时，**必须同步**改时刻表。

## 硬约束（Agent 必须遵守）

1. **禁止把公网域名 / 完整 Tunnel hostname 写入仓库**（README、示例、代码默认值、提交说明皆不可）。文档只写本地端口或 `<your-hostname>`。公网跳转放未入库文件（如 `m-hero-hub/config/services.local.json`）。
2. **禁止提交密钥**：`.env`、`APP_SECRET`、Webhook 真值、飞书 token、`list.xlsx` 含手机号等。
3. **共享浏览器**：三爬虫共用一套 Chromium；勿随意「断开连接」或 `pkill` 共享 profile；勿并行导出。
4. **`dfmc_browser_utils.py` / `keepalive_browser.py`** 在三仓有副本，改一处要评估是否同步。
5. **Git**：改哪个业务就在哪个子仓提交；顶层 `m-hero` 仓默认只提交文档类文件（业务目录在顶层 `.gitignore` 中）。
6. **时区**：调度与日志按北京时间（`Asia/Shanghai`）。

## 常见任务入口

| 意图 | 先看 |
|------|------|
| 改 DMS 爬虫 / 保活 / 时刻表 | `docs/SHARED_DMS_BROWSER.md` → 对应仓 `scripts/` |
| 改区域报表模板或流水线 | `mhero_district_form/README.md`、`app/processor.py`、`scripts/run_pipeline.py` |
| 改黄页收录 | `m-hero-hub/app.py` + 本地 `config/services.local.json` |
| 改 NSS 问卷提醒 | `NSS_Questionnaire_Reminder/README.md`、`app.py` |
| 查企微 SCRM 接口 | `scrm-api/README.md`、`docs/custom-openapi.md` / `docs/baseline-openapi.md` |
| 部署 / launchd | `docs/DEPLOYMENT.md`、各仓 `deploy/*.plist` |
| 向数字化申请 DMS 结构化数据 | [docs/DMS_DATA_ACCESS_REQUEST.md](docs/DMS_DATA_ACCESS_REQUEST.md)、`DMS报表功能使用表.xlsx` |

## 本地验证速查

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9000/
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9002/
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9003/
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5001/
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9004/
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9005/
```

## 回复风格

- 直接、简洁；长文先给结论
- 少用加粗堆砌；不复述无关限制
- 不主动创建用户未要的 Markdown 文档；本文件与既有 `docs/` 除外
