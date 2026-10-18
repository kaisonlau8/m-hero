# 统一人机交互规范

适用：黄页、区域表及 reportdb、NSS、VIP、超时机器人、事故车控制台。登录服务的页面保持独立。

## 折叠与信息层级
- 列表页的主体表格（页面存在的意义就是这张表，如门店列表、得分表、超期车辆表）不折叠，模板给 table 标 `data-ds-primary`；编辑表单内的勾选表格也不折叠。
- 汇总、统计和关键状态始终可见。超过 8 行的列表、明细区块和次要详情默认折叠；标题显示名称、实时计数和本地 `i-down`（展开后旋转）。STC 门店明细继续全部默认折叠。
- 使用 `.ds-collapse`、`data-ds-title="明细名称"` 包裹明细；`cards.js` 创建整行 button，维护 `aria-expanded`、`aria-controls` 和面板 hidden。Enter / Space 可操作，刷新计数不重置用户开合状态。
- 移动端 ≤860px 的筛选区使用 `.ds-filter`：折叠时显示已生效筛选摘要；桌面展开。表单值、提交和重置逻辑保持原样。
- 未提交的筛选修改保留原生效摘要并提示「有未应用修改」；即时本地搜索可标记 `data-ds-filter-live`。
- 原生 `details` 可保留，但 summary 应有名称、计数、箭头；不得把统计卡或主要操作藏入明细。计数徽标紧跟在标题文字后（间距约 8px），剩余空间只由最右箭头占用；`.ant-collapse-extra` 等右侧操作区保持靠右。
- 长面板展开后向下滚动再收起时，若折叠头已被顶栏/子标题栏遮住或滚出视口上方，`cards.js` 将头部平滑滚回固定区下方 8px（`prefers-reduced-motion` 时用 `auto`）；头部仍完整可见则保持视口不动。复位偏移统一取 `--ds-header-h`（存在子标题栏时再加 `--ds-subbar-h`），不得写死像素。

## 表格和列表
- 每列有明确表头，操作列统一「操作」，序号列「序号」；不留空 th。分组表头保留层级。
- 卡片化继续使用 `data-label` / `data-card-title`，每个数据字段都有名称。纯空态不伪造数据行。

## 返回、关闭和跳转
- 桌面（>860px）：标题上方显示 antd Breadcrumb「上级 / 当前页」（`nav.ant-breadcrumb`、`aria-label="面包屑"`、分隔符 `/`，当前页 `aria-current="page"`），不设独立返回按钮。
- 移动（≤860px）：sticky 子标题栏固定在顶栏下方，最左仅图标 chevron 返回（44×44，`aria-label="返回上级：XXX"`），其后单行标题；页面 h1 视觉隐藏，最右仍是唯一汉堡。`h1` 的隐藏在 CSS 媒体查询内完成，子标题栏空间由模板/CSS 首帧预留，不靠 JS 延迟显示。
- 点击返回：同源 referrer 且存在历史时 `history.back()`，否则跳固定上级。模板用 `data-ds-back="上级路由"` + `data-ds-back-label="上级名称"` 显式声明上级，不猜测业务动作。
- 弹窗、抽屉和提示关闭按钮使用 `.ds-close`、`aria-label="关闭"`，桌面热区至少 32×32px、移动至少 40×40px，图标 16px，hover 浅灰底，键盘焦点可见。
- 普通站内页面链接末尾用 `i-right`；外部系统和新窗口用 `i-export`，`target="_blank" rel="noopener"`。顶栏/侧栏导航菜单、面包屑不加箭头；导航中的当前页、锚点、下载、表单动作和抽屉按钮不冒充页面跳转。
- 可点击行/单元格应有 hover、pointer 和箭头或下划线，并提供真实链接或 Enter/Space 键盘操作。

## 动效
- Token：`--ds-motion-fast: .1s` / `--ds-motion-mid: .2s` / `--ds-motion-slow: .3s`，缓动 `cubic-bezier(.23,1,.32,1)`。
- 页面切换使用 View Transitions；浏览器不支持时首帧淡入（`.ds-page-enter`），不等待数据。
- 折叠/展开用 WAAPI 高度动画；视口变化时取消动画并清理内联高度，桌面筛选恒展开。原生 `details` 同样处理。
- 抽屉 `translateX` 滑入，弹窗 `scale + opacity`，遮罩淡入，关闭时反向播放。
- 异步容器使用骨架屏，占位尺寸与最终内容一致；列表首次渲染前 20 项按 20ms 步进 stagger。
- 按钮按压 `scale(.97)`；toast / notification 进出场；移动菜单滑入；锚点平滑滚动；sticky 顶栏滚动后加阴影。
- `prefers-reduced-motion` 下全部动效关闭。
- 只动画 `transform` / `opacity`，不以高度、位移或延迟显示制造 CLS。

## 触控反馈
- 全局 `-webkit-tap-highlight-color: transparent`，不再出现浏览器默认蓝色蒙层。
- 按下反馈：块状可点区浅灰底 `rgba(0,0,0,.06)`，卡片/表格行用 `#f0f0f0`；深色顶栏内改用 `rgba(255,255,255,.12)`；链接按下变 `#0958d9` 并轻微降透明。
- 按钮沿用 `scale(.97)`，可点卡片 `scale(.98)`；过渡时长走 `--ds-motion-fast`，按下即时生效。
- hover 背景只写在 `@media (hover:hover)` 内，触屏抬手后不残留。
- `:focus-visible` 保留 2px 蓝色描边；`:focus:not(:focus-visible)` 清除点按后的焦点环。
- `prefers-reduced-motion: reduce` 下取消缩放，保留底色/文字反馈；禁用态无按下反馈。

## 视觉与复用
- 蓝白 Ant Design，主色 `#1677ff`；图标仅使用本地 sprite，反馈沿用 `feedback.js` 的 message / notification / spin。
- 移动端只保留一只汉堡，最右上角 `order:999; margin-left:auto`。
- 共性样式与增强在 `antd-lite.css` / `cards.js`；业务模板显式指定折叠边界和返回父路由，不猜测业务动作。执行 `bash design-system/sync.sh` 同步副本。

## 验收
- 每个 GET 页面及真实参数详情在 1280 / 390 宽检查：默认折叠、展开后数据完整、计数、筛选摘要、表头及卡片字段、返回目标、关闭热区、链接提示、唯一汉堡、无横向页面溢出。
- 不触发通知、抓取、同步、删除等业务动作；页面 200 且无新增 JavaScript 错误。截图和审计记录置于工作区外报告目录。
