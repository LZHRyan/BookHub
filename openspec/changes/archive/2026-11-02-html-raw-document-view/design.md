# Design

## Context

- HTML 章节在 `app/services/render.py` 里经 nh3 白名单净化：`ALLOWED_TAGS` 不含 `style`/`script`/`nav`，`ALLOWED_ATTRIBUTES` 不含 `style`，`ALLOWED_URL_SCHEMES` 只有 `http/https/mailto`（所以 `img src="data:..."` 也被剥掉）。
- 站点 CSP（`app/middleware.py`）是 `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; ...`，且 `X-Frame-Options: DENY`、`frame-ancestors 'none'`。
- 响应头在中间件里用 `headers.setdefault(...)` 写入，所以路由自己设置的 CSP 不会被覆盖——这是 `/raw` 能拥有独立策略的前提。
- 原始上传一直保留在 `chapters.content_raw`，`content_safe`/`content_rendered` 才是净化产物；搜索、字数、API 都基于净化版。

## Goals / Non-Goals

**Goals:**

- 上传的完整 HTML 文档能按原样被读者看到：文档自己的 CSS、JS、base64 图片、内置导航全部生效。
- 不把站点的会话与后台暴露给文档里的脚本。
- 管理员能按 Book 选择"站内渲染"还是"原始文档"，默认保持现状（`inline`）。

**Non-Goals:**

- 不做附件/静态资源上传，因此**不支持相对路径资源**。
- 不做"从文档里提取导航替代站点目录"的静态解析（原始文档模式下由文档自己提供导航）。
- 不做 iframe 内嵌模式（选择的是新标签页）。
- 不放宽阅读页（章节页）的 CSP。

## Decisions

### D1. 新标签页 + CSP `sandbox`，而不是 iframe

新标签页打开的是一份独立文档，不需要动 `frame-ancestors` / `X-Frame-Options`，也不会有嵌套滚动与高度问题；缺点是脱离站点外壳（目录、上下篇）。

- 备选被否：页面内 iframe → 要放开 `frame-src`/`X-Frame-Options`，还要处理滚动、打印与移动端高度。
- 备选被否：直接把 `content_raw` 内联进章节页 + 放开 CSP → 上传文档的脚本会拿到本站会话，等同存储型 XSS。

### D2. 用 CSP 的 `sandbox` 指令而不是"独立域名"

`Content-Security-Policy: sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox allow-modals; ...`，**故意不写 `allow-same-origin`**：浏览器把顶层文档当作唯一源（opaque origin），脚本能跑但拿不到站点 Cookie/localStorage，也读不到同源 `fetch` 的响应。

- 备选被否：独立域名（如 `raw.example.com`）→ 隔离更彻底，但要再加一套反代、证书与 Cookie 域规划；CSP `sandbox` 零运维。
- 风险：Safari 对顶层文档 CSP `sandbox` 的支持需实测；不支持时会退化为无沙箱。文档里写明该前提，部署验证时用 Safari 复测一次。

### D3. 资源策略放到最宽，但保留 `form-action 'none'`

`default-src 'none'` 起手，再显式放开 `style-src * 'unsafe-inline' data:`、`script-src * 'unsafe-inline' data: blob:`、`img-src * data: blob:`、`font-src * data:`、`media-src * data: blob:`、`connect-src *`、`frame-src *`。这样 CDN 引用的 CSS/JS、base64 图片、内联脚本都能工作。

- `form-action 'none'`：沙箱也不给 `allow-forms`，避免文档把访客提交到任意地址。
- 混合内容（https 站点内引用 http 资源）仍由浏览器拦截，这是浏览器行为，不是站点规则。

### D4. 模式存在 Book 上，而不是章节上

`html_view` 是 Book 级字段：一个 Book 的文档类型已经整本统一，阅读方式也应当是整本统一，否则同一本书点不同章节会有不同打开方式。

- 值：HTML Book 默认 `document`，可显式改成 `inline`；Markdown Book 无论传什么都落成 `inline`（`resolve_html_view()` 统一处理），避免留下无意义数据。
- 列默认值保留 `inline`：这是给"绕过服务层直接写库"准备的**安全兜底**（净化渲染永远比执行脚本安全），正常业务路径由 `resolve_html_view()` 按格式落值。
- 切换不需要重新上传：`content_raw` 一直保留。
- 存量 HTML Book 由 `0005_backfill_html_view` 一次性回填为 `document`，避免"功能上线了但老书还是净化版"的割裂。

### D5. 章节页永远是"安全兜底"

即使 `html_view=document`，`/b/{slug}/{chapter}` 仍然可访问并渲染净化版，页面顶部横幅提示"本书按原始版式提供"并给出「原始排版」按钮。原因：搜索、历史链接、站内分享锚点都指向章节页，不能让它们 404；也让读者在脚本被浏览器拦截时有内容可读。

### D6. 草稿与热度

- `/raw` 复用 `chapters.find_chapter(allow_unpublished=user is not None)`：匿名只认已发布，登录用户可预览草稿（与章节页一致）。
- 匿名访问 `/raw` 计入 Book 热度（`visits.record_book_view`，同样 30 分钟去重）；登录用户不计，和章节页口径一致。

## Risks / Trade-offs

- **上传者可执行脚本**：`editor` 角色也能上传 HTML。沙箱保证拿不到会话，但文档仍可弹窗、跳外链、发匿名请求、做钓鱼页面。缓解：管理端表单写明"只上传可信来源"，`/raw` 不参与站内搜索与推荐。
- **Safari 降级**：若浏览器不支持顶层 CSP `sandbox`，文档脚本会以本站来源运行——这是真实的 XSS 面。上线前需实测；不支持时的兜底（如强制 `inline`）另开变更。
- **相对路径资源 404**：没有附件上传能力，文档作者需自行内联或使用绝对 URL。
- **绕过站点阅读体验**：`document` 模式下读者可能不再看到左栏目录、上下篇与站点搜索框；这是选择该模式的代价。

## Migration Plan

1. 执行 `alembic upgrade head`：`0004_book_html_view` 给 `books` 加列（`server_default='inline'`），`0005_backfill_html_view` 把存量 HTML Book 更新为 `document`。
2. Markdown Book 不受影响（服务层强制 `inline`）；需要站内渲染的 HTML Book 由管理员在 Book 设置里改回 `inline`。
3. 回滚：`alembic downgrade 0004_book_html_view` 会把 HTML Book 统一改回 `inline` 并删列；`/raw` 路由随镜像回滚消失，章节链接自动回到站内页。

## Open Questions

- Safari 对顶层 CSP `sandbox` 的支持需要实测；若不支持，是否需要按 UA 强制降级为 `inline`，留待验证后决定。
