# m-hero 统一登录（Casdoor SSO）设计 / 上线方案

## 0. 实施状态（2026-10-09 更新）
- **Phase 0 已完成**：Casdoor v4.18.0 已在 dfms 上运行（supervisor 程序 `casdoor`，只监听 127.0.0.1:8000，SQLite 在 `~/m-hero-run/data/casdoor/`，每日备份程序 `casdoor-backup`），公网 `https://sso-m-hero.41box.com`（新隧道 `m-hero-sso`，程序 `tunnel-m-hero-sso`，一条代理 CNAME）。内置管理员默认口令已改为随机口令，存于 `~/m-hero-run/casdoor-admin.secret`（600）。**尚未创建任何用户账号，没有任何现有应用启用登录。**
- **Phase 1 已在开发环境完成**（未部署）：两角色模型、30 天会话、静默 SSO、各应用 audit 模式补丁与测试、看门狗 token、reportdb 仅 OIDC。部署脚本 `m-hero-auth/deploy/phase1_apply.sh`（逐个应用、先 audit）。
- 代码在 `m-hero-auth/`；开发 Casdoor 跑在开发机 :18000（临时 SQLite，口令在 `/workspace/casdoor-dev/secrets.json`，600）。

> 下文 §4 为最新的两角色模型；§1~3、§6~9 中保留了早期设计，凡出现 supervisor/admin 即为现行角色（原 viewer→supervisor、operator→admin）。

## 1. 结论：怎么部署 Casdoor

| 项 | 结论 |
|---|---|
| 版本 | 最新稳定版 v4.18.0（2026-10-07）。GitHub Release 有 `casdoor_Linux_x86_64.tar.gz`（38.6MB，解压 124MB 单文件 + `web/build` 前端 + `conf/`），sha256 `96cb298d2e9cb543d847ff85b68f0c536e707895cc1a290e282b8dda5fc0827b` |
| 方式 | **单二进制 + SQLite**（官方支持 `driverName=sqlite`，已在开发机实测：初始化数据、登录、令牌、JWKS 全部正常）。不用 Docker（dfms 没装 docker，且 Docker Hub 不可达），不用 MySQL/PG（dfms 都没装） |
| 进程管理 | 加一个 supervisor program（dfms 已用 supervisor，见 `deploy/casdoor.supervisor.conf.example`），不需要 systemd 单元 |
| dfms 条件（只读检查） | Ubuntu 24.04 x86_64，30G 内存（Casdoor 空闲约 100~200MB），无 docker/mysql/postgres/sqlite3 命令行；`supervisorctl` 在；dfms 访问 github.com 返回 302（可用），`ghfast.top` 镜像 200。**下载包最稳的办法**：从开发机（已校验 sha256）经 scp/Tailscale 传过去，或 dfms 上 curl 并核对上面的 sha256 |
| 注意 | ① 内置管理员 `built-in/admin` 默认密码是 `123`，首次启动后**立即改**（开发实例已改）；② 二进制监听 `:8000` 全网卡，dfms 要靠防火墙/安全组只放行本机（cloudflared 走 127.0.0.1:8000）；③ 启动日志会报 LDAP 389 端口权限不足、Radius 1812，无害，可忽略；④ 登录页有少量静态资源走 `cdn.casbin.org`，国内可能慢，不影响功能（可在 Phase 0 验证，必要时把 `staticBaseUrl` 指向自托管） |
| 备份 | SQLite 每天用 `.backup` 一致性备份保留 14 天（`deploy/casdoor-backup.sh`），再加一份 Casdoor 内的 `init_data.json` 作为"可重建"清单 |

## 2. 各 Web 应用清单（读代码得出）

所有控制台目前都无认证，通过 Cloudflare 隧道公开。均只监听 127.0.0.1（cleaner 的 `__main__` 是 `0.0.0.0:5001 debug=True`，但生产用 `launchers/cleaner.py` 绑 127.0.0.1）。

| 应用 | 端口 / 域名 | 框架 | 必须保持公开 | 需要保护（建议角色） |
|---|---|---|---|---|
| hub 黄页 | 9004 / oa-m-hero.41box.com | Flask (`app.py`) | 无（建议新增 `/healthz` 供探活） | `/`、`/api/status`（supervisor） |
| VIP 保养提醒 | 9002 / m-hero-vip-alert.41box.com | Flask (`scripts/web_console.py`, 1371 行) | **`/feishu/card`（GET+POST，飞书卡片回调，飞书服务器调用，自带验签/解密）**；watchdog 探活 `GET /api/vip/status`（本机 127.0.0.1:9002，由 `health_watchdog.py` 调用，见 §4） | GET 页面：`/`、`/contacts`、`/api/status`、`/api/vip/status`、`/api/recorder/list`（supervisor）；写：`/contacts/*` POST、`/api/vip/sync|pipeline|crawl|scheduler/*`（admin）；`/api/browser/launch|disconnect`、`/api/recorder/*`（admin，因会操作 DMS 浏览器） |
| 区域报表 district | 9003 / m-hero-district-form.41box.com | Flask (`scripts/web_console.py`) | **无公开路径（最终决定：飞书卡片里的下载链接 `GET /api/report/latest` 也必须先登录）**。未登录访问会 302 到 `/_auth/login?next=%2Fapi%2Freport%2Flatest`，登录后回到该地址直接下载（开发环境用真实 Casdoor + 浏览器验证：督导登录后下载到 `区域各指标情况一览1010.xlsx`，5 张汇总表）。 | 全部：GET `/`、`/contacts`、`/api/status`、`/api/template*`、`/api/report/latest`（督导可看）；POST `/api/settings`、`/api/template`、`/api/pipeline/run`、`/contacts/national/*`（管理员） |
| 区域报表旧 FastAPI | 8000（本机未用） | FastAPI (`app/main.py`) | 无 | 全部 admin（`/api/generate`）；默认未启动 |
| reportdb 自建库报表 | 9013（开发，未部署） | FastAPI (`reportdb/webapp.py`) | `/healthz`（如有） | 汇总表/明细页/JSON/xlsx 导出：supervisor；明细里的车架号/姓名脱敏逻辑沿用，完整信息需 admin 以上（见 §5.4） |
| 超时机器人 cleaner | 5001 / store-timeout-cleaner.41box.com | Flask (`app.py`) | 无 | GET：`/`、`/timeout`、`/parse`、`/api/export*`、`/api/timeout/meta|chart|export`（supervisor）；POST：`/api/timeout/import`、`/api/timeout/import-scan`（admin） |
| NSS 问卷提醒 | 9005 / m-hero-nss-questionnaire.41box.com | Flask (`app.py`) | **无！** 读代码确认：9005 只有管理控制台（`/`、`/api/status|due|upload|sync|settings|run|scheduler/*|logs`），**没有门店打开的问卷页**——"questionnaire"只是产品名，问卷本身在别的系统，飞书私聊里没有指向本控制台的链接（代码里没硬编码链接）。所以 §Phase 2 的风险比预想小 | GET：`/`、`/api/status|due|logs`（supervisor）；POST：`/api/upload|sync|settings|run|scheduler/*`（admin） |
| 事故车 accident | 9000（**停用**） | Flask (`scripts/web_console.py`, 1451 行) | 无（`/`、`/rules`、`/trigger`、`/data`、`/reports`、`/contacts`、`/mode` 等页面和 `/api/run-*`、`/api/crawl`、`/api/browser/*`） | 同 VIP 规则；保持不启动，等启用时再接入 |

另有不是 Web 的后台任务（cron 程序、调度器、爬虫）走进程内，不经 HTTP，**不受登录影响**。

## 3. 架构

```
浏览器 ──https──▶ Cloudflare ──▶ cloudflared ──▶ 各控制台 (127.0.0.1:900x)
                                                   │ mhero_auth 中间件（Flask before_request / ASGI）
未登录 ─302─▶ /_auth/login ─302─▶ https://sso-m-hero.41box.com (Casdoor)  ──输入账号密码/飞书──▶
        ◀── /_auth/callback?code&state ◀──
应用后端用 client_secret 换 token → 用 Casdoor JWKS 验 ID Token(RS256) 的签名/iss/aud/exp/nbf/nonce
→ 从 token 的 roles 算出本应用角色 → 写入 HMAC 签名、HttpOnly、SameSite=Lax、Secure 的会话 Cookie
```

- **协议**：OIDC 授权码流程（Casdoor 标准端点，已用真实 Casdoor 验证）。ID Token 校验用 `cryptography` 做 RS256 验签（JWKS 缓存 1 小时，遇到未知 kid 会强制刷新一次）。
- **会话 Cookie 范围（评估结论）**：**每个应用独立的 host-only Cookie**（推荐，已实现为默认）。SSO 体验靠 Casdoor 自己的登录会话：第一次登录后，访问另一个应用只会闪一下重定向，不用再输密码。不选共享父域 `.41box.com` Cookie 的原因：41box.com 下还有别的子域（leadshunter、dfm-skyeye 等无关服务），父域 Cookie 会被它们收到；一个应用被攻破就能冒用所有应用的会话。若以后真要共享，可用 `MHERO_AUTH_COOKIE_DOMAIN=.41box.com`（已支持，Cookie 里带 app 字段并按 Cookie 名绑定，但仍不推荐）。
- **会话**：默认 **30 天**（`MHERO_AUTH_SESSION_HOURS=720`），不超过 ID Token 剩余有效期（Casdoor 应用的 token / refresh / cookie 有效期均设为 720 小时）；无服务端存储，重启应用不掉登录（只要 `SESSION_SECRET` 不变）。**重新校验**：页面请求每 12 小时（`MHERO_AUTH_REVALIDATE_HOURS`）静默回 Casdoor 走一次授权（用户无感），从而让角色变更、禁用账号在 ≤12 小时内生效；Casdoor 会话失效/账号被禁用时会弹登录页。API/XHR 请求不被中断，到 30 天硬过期才 401。
- **CSRF**：Cookie `SameSite=Lax` + 对写请求校验 `Origin`/`Sec-Fetch-Site` 必须同源。
- **open-redirect**：`next` 只接受站内路径。
- **/api/ 请求**未登录返回 401 JSON（不是 302），页面请求才跳登录。
- **登出**：`/_auth/logout`（清本应用 Cookie），`/_auth/logout?sso=1`（同时登出 Casdoor）。`/_auth/me` 返回当前用户。
- **公共路径白名单**：`public_paths`（任意方法，如 `/feishu/card`）、`public_get_paths`（仅 GET，如 `/healthz`）；代码里给默认，也可用环境变量 `MHERO_AUTH_<APP>_PUBLIC_PATHS` 追加（glob 匹配）。
- **服务到服务**：`MHERO_AUTH_SERVICE_TOKENS="watchdog:supervisor:<随机≥20位>,ops:admin:<...>"`，请求带 `Authorization: Bearer …` 或 `X-MHero-Token`，常量时间比较；token 带角色，supervisor token 不能写。另有可选的"本机直连放行" `MHERO_AUTH_TRUST_LOOPBACK=1`：仅当请求来自 127.0.0.1 **且不带** `Cf-Connecting-Ip / Cf-Ray / X-Forwarded-For` 等代理头时放行（cloudflared 也是从 127.0.0.1 来，但一定带 Cf-* 头；已测）。默认关闭。
- **紧急开关（break-glass）**：① `MHERO_AUTH=off`（或按应用 `MHERO_AUTH_HUB=off`）重启生效；② **`touch $MHERO_AUTH_OFF_FILE`（如 `/home/ubuntu/m-hero-run/auth-off.flag`）无需重启立刻关闭认证**，删文件恢复，已实测；③ `MHERO_AUTH=audit` 只记日志"本来会拦截 X"，不拦截，用于上线前观察。配置缺失（没配 client secret 等）时 `on`/`audit` 模式**启动即报错**（fail closed，不会静默放行）；要放行必须显式 `off`。

## 4. 角色与权限模型（定稿：只有两个角色）

- Casdoor：组织 `mhero`、应用 `mhero-sso`（所有控制台共用，一个 client，回调地址已登记 6 个域名 + reportdb 的 `/auth/oidc/callback`）。
- 角色（Casdoor Role，全局）：**`mhero-supervisor`（督导）** 与 **`mhero-admin`（管理员）**。也支持单应用角色 `mhero-<app>-supervisor|admin`（app = hub / vip / district / cleaner / nss / accident）。没有这两种角色的账号：登录后显示 403，不建立会话。旧的 viewer/operator 角色一律无效。
- **督导**：查看**全部**数据（完整、不脱敏），并可调用各应用声明为"提交申请"的接口（`supervisor_write_paths`，目前 reportdb 的豁免申请；其它应用暂无）。**管理员**：督导的全部权限 + 审批/管理/触发（所有写操作：同步、抓取、上传、设置、定时器、DMS 浏览器等，以及 `admin_paths`）。
- **service token**（看门狗等机器调用）：`name:supervisor|admin:<≥20 位随机>`，只读（supervisor）即可。
- **看门狗（已定：X-MHero-Token）**：`health_watchdog.py` 从环境变量 `WATCHDOG_AUTH_TOKEN` 或 600 权限文件 `WATCHDOG_AUTH_TOKEN_FILE`（部署后为 `~/m-hero-run/watchdog.token`）读取随机令牌，发 `X-MHero-Token` 头访问 `/api/vip/status`；VIP 控制台里配置同一令牌（`watchdog:supervisor:<token>`）。补丁 `patches/vip-watchdog-token.patch`，开发中用真实 VIP 控制台验证：无令牌 401、正确令牌 ok、错误令牌 401。
- **reportdb 映射**（reportdb 自带 OIDC 后端，不使用本中间件）：`REPORTDB_OIDC_ADMIN_GROUPS=mhero-admin`、`REPORTDB_OIDC_SUPERVISOR_GROUPS=mhero-supervisor`、`REPORTDB_OIDC_USERNAME_CLAIM=preferred_username`、`REPORTDB_AUTH_BACKEND=oidc`（生产只走 OIDC，本地账号密码登录代码保留但关闭）、`REPORTDB_OIDC_REQUIRE_ROLE=1`（补丁 `patches/reportdb-oidc-require-role.patch`：没有这两个角色就拒绝，而不是降级成 viewer）、`REPORTDB_SESSION_HOURS=720`。reportdb 里 supervisor 本来就是"看全部明细 + 提交豁免申请"，admin 审批，与新模型一致。已在开发环境用真实 Casdoor + 浏览器验证：admin→admin、supervisor→supervisor、无角色用户→"没有访问权限"，会话 cookie 30 天。

### 单点登录体验（静默 SSO）
Casdoor 应用必须开启 `enableSigninSession` 和 `enableAutoSignin`（dfms 上已开启，`init_data` 示例里已写）。开启后：用户在任一应用登录一次，访问其它应用时 Casdoor 直接发 code，浏览器只是快速跳转，不出现第二次登录框。已用 Playwright 真实浏览器在开发环境验证（hub 登录后访问另一个应用，直接进入且角色正确，各应用 cookie 是各自域名下独立的 host-only cookie）。

## 5. 开发产出

### 5.1 `m-hero-auth/`
```
m-hero-auth/pyproject.toml          # 依赖仅 cryptography（Flask/FastAPI 用各自应用已有的）
m-hero-auth/mhero_auth/core.py      # 配置、会话签名、OIDC、JWKS 验签、角色、白名单、token、开关
m-hero-auth/mhero_auth/flask_adapter.py   # init_app(app, "hub", public_get_paths=[...])
m-hero-auth/mhero_auth/asgi.py      # AuthMiddleware（FastAPI/Starlette 纯 ASGI）
m-hero-auth/tests/                  # 25 个单元测试（内置 mock OIDC）+ 3 个真实 Casdoor 集成测试
m-hero-auth/deploy/                 # app.conf / supervisor / 备份脚本 / init_data 示例（无密钥）
```
测试：`cd m-hero-auth && PYTHONPATH=. pytest -q` → **28 passed**。覆盖：未登录跳转与 /api 401、完整登录回路、supervisor 不能写/admin 能写、单应用角色不串用、错误组织/被禁用用户、伪造签名、`iss/aud/exp/nonce` 错误、state 不匹配、Cookie 篡改/跨应用重放/过期、公共路径、服务 token（含 supervisor token 写被拒）、loopback（带代理头不放行）、break-glass 环境变量与文件、audit 模式、配置缺失 fail-closed、CSRF、open-redirect、登出。真实 Casdoor 集成：Flask 和 FastAPI 各走一遍"账号密码登录 → code → JWKS 验签 → Casdoor 角色 → Cookie → 受保护页面"，supervisor 写 403、错误密码拒绝。

### 5.2 开发环境
Casdoor v4.18.0 在开发机 `127.0.0.1:18000`（SQLite，`/workspace/casdoor-dev/`，`init_data.json` 预置了 mhero 组织、应用、alice(admin)、bob(supervisor)，管理员口令为随机值，均存于 600 权限的 `secrets.json`）。

### 5.3 接入示例（仅开发副本）
`/workspace/m-hero-auth-dev/m-hero-hub/`（hub 的拷贝，**未改动 /workspace/m-hero 里的 hub**）：加了 6 行 `init_app(app, "hub", public_get_paths=["/healthz"])` + `/healthz`。真实起服务实测：未登录 `/` 302、`/healthz` 200、`/api/status` 401；登录后页面和接口 200；`touch auth-off.flag` 立刻放行，删除后立刻恢复拦截。启动脚本 `run_hub_dev.sh`。

### 5.4 reportdb 适配片段（不修改 reportdb/ 目录；另一位开发者正在做本地账号登录）
reportdb 是 FastAPI `create_app()`，在 `webapp.py` 返回 `app` 之前加：
```python
import os
if os.getenv("MHERO_AUTH", "off") != "off":                      # 默认不变
    from mhero_auth.asgi import AuthMiddleware
    app.add_middleware(AuthMiddleware, app_name="reportdb", public_get_paths=["/healthz"])
```
- 当前登录用户：路由里 `request.state.mhero_session`（含 `.name/.role/.email`）；`/_auth/me` 可供前端使用。
- 与本地账号密码后端的关系：建议做成"可插拔后端"——`casdoor` 后端直接用本中间件，`local` 后端保留给开发/应急。明细脱敏逻辑（`masking.request_authorized`）可改为 `role in (admin, admin)` 时显示完整信息，取代现在的访问令牌。需要的话我再按他们的后端接口出补丁。

## 6. 部署步骤（dfms，需要你批准后才执行）

**Phase 0 — 部署 Casdoor（不影响任何现有服务）**
1. 在 dfms 建目录 `/home/ubuntu/casdoor/{data,logs,backup}`，传入并校验 `casdoor_Linux_x86_64.tar.gz`（sha256 见上），解压得到 `casdoor`、`web/`、`conf/`。
2. 写 `app.conf`（见 `deploy/casdoor.app.conf.example`；`origin` = 公网 SSO 域名；数据库密码类敏感项为空，SQLite 无需）。`initDataFile` 指向 `init_data.json`（组织/应用/角色/首批用户，`initDataNewOnly=true` 只在首次生效）。
3. 加 supervisor program（`deploy/casdoor.supervisor.conf.example`），`supervisorctl reread && update`。确认 `ss -ltn` 8000 不对公网开放（安全组/ufw）。
4. 本机 `curl 127.0.0.1:8000/.well-known/openid-configuration` 验证；用内置 `admin`/`123` 登录**立刻改密码**。
5. 加备份 cron（`casdoor-backup.sh`），验证能还原。
6. Cloudflare 隧道（**现在不建**）：新建隧道 `sso-m-hero`，配置 `ingress: - hostname: sso-m-hero.41box.com  service: http://127.0.0.1:8000`，再加兜底 `http_status:404`；DNS CNAME 到该隧道；supervisor 增加 `tunnel-sso-m-hero` program，写法与现有 5 个隧道相同（`--edge-ip-version 4 --config ~/.cloudflared/config-sso-m-hero.yml`）。凭据文件放 `~/.cloudflared`，不进仓库。
7. 在 Casdoor 里按 §4 建角色并给第一批用户授权；给自己建 `mhero-admin`，并**另外保留一个内置 admin 应急账号**（不依赖 mhero 组织）。

**Phase 1 — 逐个应用接入（每个应用都先 audit 再 on，随时可退）**
1. 给 dfms 各应用的 venv 装 `cryptography` 和 `m-hero-auth`（`pip install -e`，用国内 pip 源）。
2. 代码接入（仿 §5.3，约 6 行/应用），环境变量写入各应用的 `prod_env.sh` 或 supervisor `environment=`，密钥只放 600 权限的 env 文件：`MHERO_AUTH_ISSUER / _CLIENT_ID / _CLIENT_SECRET / _BASE_URL / _SESSION_SECRET(每应用不同) / _ORG=mhero / _OFF_FILE=/home/ubuntu/m-hero-run/auth-off.flag`。
3. 顺序：**hub → reportdb（上线时就带登录）→ cleaner → district → VIP → NSS**。每个应用：先 `MHERO_AUTH_<APP>=audit` 观察 1~2 天（日志里 `AUDIT would redirect/deny …` 能暴露所有未预料的外部/无头调用方，如飞书里的链接、脚本），确认无遗漏后改 `on`；重启单个 supervisor program 即可，回退 = 改 `off` 或 touch off 文件。
4. VIP 必须先确认：`/feishu/card` 在 `public_paths`，watchdog 带 token（或 loopback）；用飞书"卡片回调 URL 校验"（GET）验证。
5. 每步验证：带/不带登录的 curl、5 个公网域名、watchdog 日志、cron 程序（不走 HTTP，不应受影响）。

**Phase 2 — NSS**：与 Phase 1 同流程，但最后做并多观察一天——它 00:00 同步、09:00 发送，虽然是进程内调度不走 HTTP，仍要确认 09:00 后无 AUDIT 告警。读代码确认 NSS 无门店侧公开页面，因此不需要放行路径。

**Phase 3（暂不做）**：飞书登录已决定暂不上；admin_paths 细化。

## 7. 飞书登录（已决定：暂不上，以下仅备查）
Casdoor 自带 **Lark** OAuth 提供商（类型 Lark，Client ID = 飞书应用 App ID，Secret = App Secret；用户名取 UserId > UnionId > OpenId；还有 Lark 同步器可把飞书通讯录同步成 Casdoor 用户）。需要：飞书开放平台建（或复用）一个企业自建应用，**安全设置 → 重定向 URL** 里添加 `https://sso-m-hero.41box.com/callback`（注意是 Casdoor 的回调，不是各控制台的），开启网页应用/获取用户信息权限；Casdoor 里添加该提供商并挂到 `mhero-sso` 应用的登录方式上。**飞书登录只解决"你是谁"，仍需在 Casdoor 里给该用户授角色**，否则登录后 403。注意：目前我电脑上 lark-cli 的新应用尚未配置完，可以用新应用，也可复用现有的。（本次没有在开发环境测飞书登录。）

## 8. 风险与对策
| 风险 | 对策 |
|---|---|
| 锁死自己（Casdoor 挂了/改错配置） | 紧急开关：touch off 文件即时关闭；`MHERO_AUTH=off` 重启回退；Casdoor 内置 admin 独立应急账号；SQLite 日备份 |
| Casdoor 单点：它挂了，**已登录会话仍有效**（本地验签的 Cookie），新登录不可用；ID token 验签用 JWKS 缓存 1 小时 | supervisor 自启；监控 `sso-m-hero` 域名并加进 08:00 巡检；必要时 off |
| 飞书卡片回调被拦 | `/feishu/card` 公共白名单；先 audit；回调自带验签/解密 |
| 隐藏的外部调用方（脚本/飞书里的链接）被拦 | audit 模式观察日志后再 on |
| 会话过期 vs DMS 保活/watchdog | 登录只影响 Web 控制台。DMS 保活（`keepalive_browser.py`）、调度、爬虫、cron 都是进程内/本机任务，不经 HTTP，不依赖浏览器会话；watchdog 用服务 token/loopback。人用页面触发长任务时 12 小时会话足够；过期后 /api 请求返回 401 JSON，页面跳登录 |
| 会话密钥泄露 | 每个应用独立 `SESSION_SECRET`，600 权限 env；轮换=改密钥，所有人重登 |
| Casdoor 自身漏洞/默认口令 | 改默认 `admin/123`；只通过隧道暴露；及时升级（单二进制，替换+重启，先备份）；管理后台可再加 Cloudflare Access 或 IP 限制 |
| 公网 SSO 域名下 Casdoor 允许自助注册 | `enableSignUp=false`（已在示例里），用户由管理员创建 |
| 某些路径遗漏保护 | 中间件是"默认拒绝"（所有路径默认受保护，只有白名单放行），新增路由自动被保护 |
| 国内访问 Casdoor 登录页静态资源慢（cdn.casbin.org） | Phase 0 验证；必要时自托管 |
| 未实测项 | `internal_issuer`（用 127.0.0.1 回源取 token/JWKS 而 `origin` 是公网域名）：代码已支持，但开发环境同主机，上线 Phase 0 需验证 |

## 9. 已定决策（2026-10-09）与待办
已定：SSO 域名 `sso-m-hero.41box.com`；角色仅 督导/管理员（都能看全部数据，管理员另有审批/管理权）；暂不用飞书登录；会话 30 天；看门狗用 `X-MHero-Token`；所有系统统一走 Casdoor（静默 SSO），不保留页面级本地登录（reportdb 本地登录代码保留但生产关闭）；仅 `/feishu/card` 保持公开。
待办：
1. 管理员口令：当前为随机口令，在 dfms `~/m-hero-run/casdoor-admin.secret`（600）。请用户登录 `https://sso-m-hero.41box.com`（内置组织 built-in，用户名 `admin`）后自行改成自己的口令；忘记时在 dfms 上用该文件里的口令登录，或用 Casdoor API `set-password` 重置。
2. 创建账号（由用户通过安全表单提交，不经聊天明文）：管理员账号及督导账号，并分别授予 `mhero-admin` / `mhero-supervisor` 角色（密码规则：至少 8 位且含大小写字母与数字——Casdoor 不原生支持"至少 10 位"，可在密码策略里选更严的组合）。
3. 账号就绪后，依次执行 `deploy/phase1_apply.sh`：`prep` → 各应用 `app <name> audit` → 观察 → `mode <name> on`；reportdb 最后切到 OIDC（`deploy/reportdb-oidc.env.example` + 补丁），并保证至少一个管理员 Casdoor 账号已能登录，再关闭本地登录。

## 附：下载链接 `/api/report/latest`（需登录）与"只发日报"收紧
- 决定：该链接和其它页面一样需要 Casdoor 登录（`district-sso.patch` 不含任何公开路径；仅 VIP 的 `/feishu/card` 保持公开，hub 的 `/healthz` 仅返回 ok 供探活）。测试 `tests/test_district_report_requires_login.py`。
- **`_latest_report()` 收紧**（`patches/district-latest-report.patch`，新增 `scripts/report_select.py` + 7 个测试）：`MHERO_REPORT_ENGINE=reportdb` 时只提供 reportdb 引擎的日报——优先取 `output/pipeline_manifest.json` 里 `engine=reportdb 且 status=ok` 指向的文件（只取文件名，兼容绝对路径来自别的机器），否则取内容校验通过的最新文件：只含 5 张汇总表，且文件名不含 `_公式版` / `新模板` / `_legacy`；含明细页的文件一律不提供（找不到则 404）。`MHERO_REPORT_ENGINE=excel`（或未设置）保持原有行为不变，旧代码保留。
- **旧引擎文件归档**：`deploy/move_legacy_reports.sh`（默认只预览，`--apply` 才执行；只移动到 `output/_legacy/`，从不删除；已用临时目录验证）。dfms 上的 `区域各指标情况一览1009.xlsx`（11 张表，含明细）与 `_公式版`、`_2026Q3_新模板` 等会被移走。

## 上线状态（2026-10-09 19:xx HKT）
- Casdoor：`https://sso-m-hero.41box.com`（组织 mhero，应用 mhero-sso，30 天会话）。共享超管账号 `mhero/admin`（显示名 管理员，角色 mhero-admin，督导暂共用）。
- hub：`on`（需登录）；reportdb：OIDC-only（本地登录入口已关闭，需 mhero-admin/mhero-supervisor 角色）；cleaner / district / NSS / VIP：`audit`（只记录 `AUDIT would …`，不拦截），待 10-10 的 08:30/09:00 任务观察后切 `on`。
- 部署细节：dfms 无 uv，`phase1_apply.sh prep` 用系统 `pip3 --python <venv>` 装 cryptography，并用 `.pth` 指向 `~/m-hero-prod/m-hero-auth`。reportdb 的 OIDC 请求须带 User-Agent（Cloudflare 会 403 Python 默认 UA），已并入 `reportdb-oidc-require-role.patch`。
- 回滚：任一应用 `phase1_apply.sh mode <app> off`（即时）或 `touch ~/m-hero-run/auth-off.flag`（全局，hub/cleaner/district/NSS/VIP）；reportdb 将 `reportdb.env` 的 `REPORTDB_AUTH_BACKEND` 改回 `local`（备份 `reportdb.env.bak-pre-sso`）后重启 reportdb-web；代码补丁均有 `*.pre-sso` 备份文件。

## 账号设置 / 修改密码入口（开发完成，尚未部署到 dfms）
- **Casdoor 个人中心 URL**：Casdoor v4.18 为 `<issuer>/account`（生产 `https://sso-m-hero.41box.com/account`）。已在本地 Casdoor 验证：登录后打开该页是 “My Account”，Password 行有 **Modify password…** 按钮，点击弹出 3 个密码输入框（旧密码/新密码/确认）。截图：`/workspace/hub-account-link.png`（hub 右上角用户栏）、`/workspace/casdoor-account-page.png`（个人中心修改密码弹窗）。
- **hub**：`mhero_auth` 新增 `userbar.py`，`flask_adapter.init_app(..., userbar=True)`（或 `MHERO_AUTH_USERBAR=1`）会在 HTML 页面右上角注入「姓名｜角色｜账号设置｜退出登录」。认证关闭（off / break-glass）、未登录、服务令牌/回环调用时不显示。链接目标可配置：`MHERO_AUTH_ACCOUNT_URL`（或 `MHERO_AUTH_<APP>_ACCOUNT_URL` / `SSO_ACCOUNT_URL`），默认 `<MHERO_AUTH_ISSUER>/account`。「退出登录」= `/_auth/logout`（同时退出 Casdoor）。补丁 `patches/hub-userbar.patch`（一行：`userbar=True`），已加入 `phase1_apply.sh` 的 hub 补丁列表。
- **reportdb**：OIDC 用户的用户菜单用「账号设置」（`#sso-account-link`）替换本地「修改密码」；新增模板变量 `account_url`，来源 `REPORTDB_SSO_ACCOUNT_URL`（或 `SSO_ACCOUNT_URL`，默认 `REPORTDB_OIDC_ISSUER + /account`）。本地后端不显示。补丁 `patches/reportdb-sso-account-link.patch`（webapp.py + base.html），测试在 `tests/test_reportdb_auth.py`。
- **其它控制台（cleaner / VIP / district / NSS）**：不需要改页面。部署时给对应应用的 `init_app(..., userbar=True)` 加一个参数（或 auth.env 里设 `MHERO_AUTH_USERBAR=1`，对全部 Flask 应用生效）即可注入同样的用户栏；仅对 `text/html` 的 200 响应生效，不影响 JSON/下载。非 Flask 应用可直接调用 `mhero_auth.userbar.userbar_html(session, cfg, mode)` 放进模板。
- **Casdoor 允许用户自改资料/密码的设置（开发库已核对，生产部署前请逐项确认，不要改动线上）**：
  - 组织 `mhero` → Account items：`Password` 的 View/Modify 规则 = `Self/Self`；`Display name`、`Email`、`Phone` 等 Modify = `Self`；`Roles`/`Permissions` = `Immutable`（用户不能给自己加角色）；`Name`、`Organization`、`Tag`、`Is admin` 等 = `Admin`/`Immutable`。
  - 应用 `mhero-sso`：`enablePassword = true`、`enableSignUp = false`、`enableSigninSession = true`、`enableAutoSignin = true`；组织密码规则 `passwordOptions = [AtLeast8, Aa123]`（修改密码也受此约束）。
  - 注意：个人中心的 “Modify password” 在用户已有 Casdoor 会话时使用旧密码校验；管理员可在 Casdoor 后台为用户重置密码。

## 10. 账号管理 / 分系统权限 / 选择身份（2026-10-10，仅开发环境，未部署）

**已批准的决定**：① 首页（hub）新增仅管理员可见的「账号管理」页，服务端调用 Casdoor 管理 API；② 初始密码一律由管理员手动设定（系统不生成），首次登录强制改密（Casdoor `needUpdatePassword`，已用真实 Casdoor 验证：未改密拿不到 code）；③ 分系统权限 = Casdoor 角色 `mhero-app-{report,nss,accident,vip,district,cleaner,hub}`，身份仍是全局 `mhero-supervisor / mhero-admin`；能进系统 X ⇔ 有 `mhero-app-X` 或是全局管理员；④ 范围覆盖所有系统，事故车角色先建好（事故车应用本身仍不运行）；⑤ 报表系统「选择身份」= 管理员给账号选 管理员/督导（同步到 Casdoor）+ 分配督导负责的门店/区域（`user_stores`）+ 「以某位督导身份」只读预览；⑥ 督导迁移到个人账号；管理员和共用账号先授予全部系统角色，共用账号**等用户说了才停用**（保留应急）；⑦ 任何管理员可建号；不能给自己降权 / 停用自己；不能停用 / 降级最后一名管理员；所有操作写审计日志，且需二次确认。

### 代码
- `m-hero-auth/mhero_auth/core.py`：会话里带 `apps / ga / iat`；`MHERO_AUTH_REQUIRE_APP=1`（**默认关闭**）时按上面的规则放行或 403；没有 app 信息的旧 cookie 不会被 403，而是走一次静默登录重新签发（防锁死）；audit 模式只记日志不拦截；服务令牌 / 紧急开关不受影响。`MHERO_AUTH_REVOKE_FILE`：强制下线文件（见下）。
- `mhero_auth/casdoor_admin.py`：Casdoor 管理 API 客户端，固定在 org `mhero`。凭据 = 专用「组织管理员」用户 `svc-accounts`（只在 mhero 组织内是管理员，没有任何 mhero-* 角色）+ 专用应用 `mhero-account-admin`（仅 password 授权）；Casdoor 自身会拒绝跨组织操作（实测 `Unauthorized operation`）。凭据文件 JSON、**必须 600**（否则拒绝读取），只在服务端使用。
- `mhero_auth/accounts.py`：权限规则 + 防锁死 + 审计 + 二次确认令牌（绑定操作者/动作/参数，5 分钟）。审计日志每行一条 JSON（`MHERO_ACCOUNTS_AUDIT_LOG`，600），**不含任何密码**。
- hub `app.py` + `templates/accounts.html`：`/admin/accounts`（列表、新建、改身份、改系统、停用/启用、重置密码）；必须是真实登录的全局管理员（紧急开关/令牌/本机直连都不能打开这个页面）。`REQUIRE_APP` 开启后，首页只显示有权限的系统卡片（应用自己仍会 403）。
- reportdb：`/admin/users` 在单点登录下改身份 / 停用会先同步 Casdoor（含防锁死校验，未配置账号服务时拒绝而不是只改本地）；`/admin/users/{id}/stores` 分配门店 / 区域；`POST /admin/preview/{id}/start|exit` 只读预览（任何写请求 403，顶部红色横幅，审计记录）；OIDC 登录在 `MHERO_AUTH_REQUIRE_APP=1` 时要求 `mhero-app-report` 或全局管理员；会话读取强制下线文件。
- `deploy/casdoor_accounts_bootstrap.py`：幂等准备脚本（建角色、`svc-accounts`、`mhero-account-admin`、写凭据文件、可选给指定账号授予全部系统角色；支持 `--dry-run`）。
- `reportdb/import_supervisors.py`：督导批量导入（见下）。

### 角色缓存与强制下线
各应用的会话 cookie 里缓存了角色，默认每 12 小时才静默回 Casdoor 校验一次；reportdb 的 OIDC 会话更长（`REPORTDB_SESSION_HOURS=720`），登录时才同步角色。所以账号页每次「改身份 / 改系统 / 重置密码 / 停用」都会往共享文件 `MHERO_AUTH_REVOKE_FILE`（如 `~/m-hero-run/auth-revoke.json`，hub 与各应用同一路径，hub 可写、其余只读）写入时间戳：该用户在此之前签发的会话立即失效，下次访问走静默 SSO（被停用 / 改密的账号会被 Casdoor 拒绝）。文件损坏或不存在时不会锁住任何人。Casdoor 自己的 SSO 会话不会被主动踢掉（停用账号本身即可阻止其重新登录）。

### 环境变量（新增）
`MHERO_AUTH_REQUIRE_APP`（默认 0）、`MHERO_AUTH_REVOKE_FILE`、`MHERO_ADMIN_CRED_FILE`、`MHERO_ADMIN_API_BASE`（内网 `http://127.0.0.1:8000`）、`MHERO_ACCOUNTS_AUDIT_LOG`、`MHERO_HUB_URL`（reportdb 里跳转账号管理的链接）。

### 督导批量导入 `python -m reportdb.import_supervisors`
来源：`store_directory.json`（directory_sync 只读拉取多维表格「督导」{姓名、手机号、门店}）。用户名=手机号，显示名=督导姓名，角色 `mhero-supervisor` + `mhero-app-report`；初始密码只从环境变量 `MHERO_BULK_PASSWORD` 读取（不进命令行 / 日志 / 文档 / 审计），首次登录强制改密；同时写报表库 `users` 与 `user_stores`。默认 dry-run（手机号打码）；`--apply` 才创建。幂等：已存在的 Casdoor 账号不改密码不改角色，`user_stores` 只增不删。同一手机号对应多个姓名的不导入（需人工确认）；同一人多个手机号只导门店最多的那个。

### 测试
`cd m-hero-auth && PYTHONPATH=.:tests pytest`（含 test_accounts / test_hub_accounts / 真实 Casdoor 集成）、`cd mhero_district_form && pytest`（含 test_reportdb_identity）。

## 11. 上线记录（2026-10-10 18:xx，已部署 dfms 生产）
- 备份：`~/m-hero-backups/sso-accounts-rollout-<时间>/`（casdoor.db、reportdb.sqlite3、code.tgz、auth.env、reportdb.env）。
- 已执行 bootstrap：建 7 个 `mhero-app-*` 角色、`svc-accounts`、应用 `mhero-account-admin`，凭据 `~/m-hero-run/accounts-admin.cred`（600）；`mhero/admin`（共用超管）已授予全部系统角色。
- 环境变量写入 `~/m-hero-run/auth.env`（共享）：`MHERO_ADMIN_CRED_FILE / MHERO_ADMIN_API_BASE / MHERO_ACCOUNTS_AUDIT_LOG / MHERO_AUTH_REVOKE_FILE / MHERO_HUB_URL`。
- 强制开关状态：hub `MHERO_AUTH_HUB_REQUIRE_APP=1`（on，卡片过滤+门禁）；reportdb `REPORTDB_OIDC_REQUIRE_APP=1`（reportdb.env）；cleaner/district/vip/nss 保持 `audit`，`MHERO_AUTH_<APP>_REQUIRE_APP=1` 仅记录 `AUDIT would deny`。**这四个应用转 on 之前，需先确认 hub 状态探测（/api/status）等无头调用不会被拦。**
- 黄页规则：hub 只要账号拥有任意一个系统权限（或全局管理员）即可进入，只显示自己有权限的卡片（`mhero-app-hub` 不再是进黄页的必需条件）。
- 督导：7 人导入（用户名=手机号，角色 supervisor + app-report，首次登录强制改密），初始密码来自环境变量 `MHERO_BULK_PASSWORD`（未落盘）。
- 应急：`touch ~/m-hero-run/auth-off.flag` 全局关闭认证（hub/cleaner/district/NSS/VIP）；单应用 `sed -i 's/^export MHERO_AUTH_<APP>_REQUIRE_APP=1/…=0/' auth.env` 后重启；reportdb 删除 `REPORTDB_OIDC_REQUIRE_APP=1` 一行重启，或 `REPORTDB_AUTH_BACKEND=local`。auth.env 改动前备份 `auth.env.bak-pre-accounts`。
- 测试账号 `zz-rollout-test-*` 仅停用，不删除。
