# 账号、权限与安全

面向管理员（`admin`）。事实来源：`app/web/admin.py`、`app/web/auth.py`、`app/web/common.py`、`app/services/users.py`、`app/security.py`、`app/middleware.py`。

---

## 1. 账号体系

只有两级角色（`app/models.py` 里的 `ROLE_ADMIN` / `ROLE_EDITOR`），没有更细的 Book 级授权。

### 1.1 权限矩阵

| 功能 | URL | `admin` | `editor` |
| --- | --- | :---: | :---: |
| 内容管理总览 | `GET /admin` | ✅ | ✅ |
| 新建 / 编辑 Book | `/admin/books/new`、`/admin/books/{id}/edit` | ✅ | ✅ |
| 删除 / 恢复 Book | `POST /admin/books/{id}/delete`、`/restore` | ✅ | ✅ |
| 新增 / 替换章节 | `/admin/books/{id}/chapters/...` | ✅ | ✅ |
| 发布 / 撤回 / 排序 / 删除 / 恢复章节 | `.../status`、`/move`、`/delete`、`/restore` | ✅ | ✅ |
| 历史版本 / diff / 回滚 | `.../versions`、`/diff`、`/rollback/{n}` | ✅ | ✅ |
| 回收站 | `GET /admin/trash` | ✅ | ✅ |
| 账号管理 | `GET|POST /admin/users*` | ✅ | ❌ 403 |
| 站点设置 | `GET|POST /admin/settings` | ✅ | ❌ 403 |
| 审计日志 | `GET /admin/audit` | ✅ | ❌ 403 |

结论：**`editor` 能删 Book、能回滚、能看回收站，但碰不到账号与设置**。侧栏也按角色隐藏这三项（`admin/base.html` 里判断 `current_user.role == 'admin'`）。

> 由此带来的实际风险：给某人 `editor` 等于让他可以删掉任意 Book（软删除，可恢复）。想限制破坏面只能靠审计日志追责，系统本身没有「只能改自己负责的 Book」这种能力。

### 1.2 会话与"踢下线"

- 会话是签名 cookie（`bookhub_session`，`httponly`，`samesite=lax`，`path=ROOT_PATH or /`），默认 8 小时。
- 每个账号有 `session_epoch`：**改密码**或**停用账号**都会让它 +1，从而让该账号所有已签发的会话**立即失效**（下次请求就被当成未登录）。
- 所以"重置密码"同时也是一个强制下线手段。

---

## 2. 初始管理员引导

配置这两个变量后启动（容器 entrypoint 会执行 `python -m app.bootstrap`，应用启动钩子也会跑同一段逻辑）：

```dotenv
BOOKHUB_INITIAL_ADMIN_USER=admin
BOOKHUB_INITIAL_ADMIN_PASSWORD=一串符合策略的密码
```

行为（`app/services/users.py:ensure_initial_admin`）：

| 情况 | 结果 |
| --- | --- |
| 两个变量都为空 | 什么都不做，日志 `admin.bootstrap.skipped` |
| 账号不存在 | 创建该账号，角色固定 `admin`，`display_name` 同用户名，日志 `admin.bootstrap` |
| 账号**已存在** | 直接跳过，**不会**重置密码、不会改角色 |
| 密码不符合策略 | 抛错（`bootstrap` 命令以非零码退出；应用内的启动钩子只记 `app.startup.error` 不阻止启动） |

这就是「改了 `BOOKHUB_INITIAL_ADMIN_*` 重启却没生效」的原因。找回密码的办法见 [README 第 7.1 节](../README.md)。

---

## 3. 账号操作

入口：`GET /admin/users`（仅 `admin`）。

### 3.1 新增账号

`POST /admin/users/new`

| 字段 | 规则 |
| --- | --- |
| `username` | 必填，`^[a-zA-Z0-9._-]{3,64}$`，保存时转小写（`Admin` 与 `admin` 视为同一个），重复则报「该用户名已存在」 |
| `password` | 见下方密码策略 |
| `display_name` | 可空，留空则用用户名；审计里记录的是这个值 |
| `role` | `admin` 或 `editor`（页面下拉默认选中 `editor`，要建管理员必须手动改选——注意别建出一堆"以为自己是管理员"的编辑账号） |

审计：`user.create`，`detail.role`。

### 3.2 重置密码

`POST /admin/users/{user_id}/password`，字段 `password`。只有 `admin` 能调，且**不需要旧密码**，适用于任何人（含自己）。

- 重置成功会让目标账号所有会话失效，本人需要重新登录。
- 审计：`user.password_reset`。
- **没有"修改自己的密码"的自助入口**：`editor` 想改密码只能找管理员；`admin` 改自己也是走同一张表单。

### 3.3 停用 / 启用

`POST /admin/users/{user_id}/toggle`，切换 `is_active`。

- **不能停用自己**：会返回 400「不能停用自己」（页面里自己那行的按钮也是 disabled）。
- 停用即刻生效（会话 epoch +1），该账号再登录会得到"用户名或密码错误"（登录逻辑对停用账号返回同一句提示，不泄露账号状态）。
- 审计：`user.toggle`，`detail.is_active`。
- 没有"删除账号"功能；账号只能停用。

### 3.4 密码策略（新增/重置/初始管理员共用）

`app/security.py:password_policy_errors`：

| 规则 | 说明 |
| --- | --- |
| 长度 ≥ 10 字符 | `PASSWORD_MIN_LENGTH` |
| 字节长度 ≤ 72 | bcrypt 上限，**中文密码一个字 3 字节，约 24 个汉字就到顶** |
| 不能等于用户名（忽略大小写与首尾空格） | |
| 不能是纯数字或纯字母 | 需要两类以上字符 |
| 不能为空 | |

不满足时返回 400，错误文案是分号连接的策略列表。算法是 bcrypt（`rounds=12`）。

---

## 4. 审计日志

入口：`GET /admin/audit`（仅 `admin`），每页 30 条，按 `created_at DESC, id DESC` 排序。

### 4.1 筛选

| Query 参数 | 语义 |
| --- | --- |
| `book_id` | 精确匹配 `audit_logs.book_id`（只接受数字，非数字当作不过滤） |
| `chapter_id` | 精确匹配 `target_type='chapter' AND target_id=该值` |
| `actor` | 对 `actor_name` 做 `ILIKE %值%`（`actor_name` 存的是显示名，显示名为空时是用户名） |
| `page` | 页码，`≥1` |

没有时间范围筛选、没有动作类型筛选——要查某天，只能按 `book_id`/`actor` 缩范围后翻页，或者直接查库：

```sql
SELECT created_at, actor_name, action, target_type, target_id, ip, detail
FROM audit_logs
WHERE created_at >= '2026-10-01'
ORDER BY created_at DESC;
```

### 4.2 记录内容

每条含：时间（UTC）、操作者、动作、对象（类型 + 标签）、Book ID、IP、`detail` JSON。

| 动作 | 触发点 | `detail` 里有什么 |
| --- | --- | --- |
| `book.create` | 新建 Book | `slug` |
| `book.update` | 编辑 Book | `before` / `after`（title、slug、visibility） |
| `book.delete` / `book.restore` | 删除 / 恢复 Book | 空 |
| `chapter.create` | 新建章节 | `slug`、`format`、`status`、`to_version=1` |
| `chapter.replace` | 替换内容**以及回滚** | `from_version`、`to_version`、`note` |
| `chapter.publish` / `chapter.unpublish` | 发布 / 撤回 | `status` |
| `chapter.reorder` | 上移 / 下移 | `from`、`to`（1 基序号） |
| `chapter.delete` / `chapter.restore` | 删除 / 恢复章节 | `version`（删除时的版本号）/ 空 |
| `user.create` | 新增账号 | `role` |
| `user.toggle` | 停用 / 启用 | `is_active` |
| `user.password_reset` | 重置密码 | 空 |
| `settings.update` | 保存站点设置 | 保存后的三键值 |

要点：

- **审计只追加**：代码里没有任何修改/删除审计的入口，`audit_logs` 也没有对应的服务函数。
- 回滚没有独立动作名，靠 `chapter.replace` 的 `note`（「回滚到版本 M」）区分。
- `ip` 取 `X-Forwarded-For` 第一段 → `X-Real-IP` → socket 地址。**反代不传这两个头时全是代理 IP**，审计就没有定位价值了。
- 审计不清洗正文，不记录密码（密码类字段从不会进 `detail`）。
- 审计表只会增长，没有自动清理；按每章每年几十次替换估算，量级很小，但值得在备份策略里留意。

---

## 5. CSRF 与登录限流

### 5.1 CSRF

- 登录后每个页面里的表单都带隐藏域 `csrf_token`（`base_context` 里用会话 nonce 签发，有效期 = `SESSION_MAX_AGE`）。
- 校验逻辑（`require_csrf`）：先取表单字段 `csrf_token`，为空则回退读请求头 `X-CSRF-Token`；用 `itsdangerous` 验签并比对 nonce。
- 失败分支：会话不存在 → 401「会话已失效，请重新登录」；token 不对/过期 → 403「CSRF 校验失败，请刷新页面后重试」。
- **所有**写操作（Book/章节/账号/设置/登出）都强制校验；唯一例外是登录表单本身（还没有会话）。
- 这意味着**不能用裸 `curl` 直接 POST 管理端接口**做自动化：要么先 GET 页面抓 token 与 cookie（见 `tests/conftest.py:csrf_token` 的写法），要么走只读 API。

### 5.2 登录限流

| 项 | 值 | 依据 |
| --- | --- | --- |
| 计数键 | `login:{IP}:{小写用户名}` | `app/web/auth.py` |
| 阈值 | 5 次失败 / 300 秒（可配 `LOGIN_FAIL_LIMIT`、`LOGIN_FAIL_WINDOW`） | |
| 超限 | **HTTP 429**，页面显示「登录失败次数过多，请 N 秒后再试」，不再校验密码 | |
| 清零 | 成功登录后清空该键 | |
| 存储 | 进程内内存（重启即清空，多副本各算各的） | `app/services/ratelimit.py` |

API 侧另有一层限流：`/api/v1` 每 IP 每分钟 `RATE_LIMIT_PER_MINUTE`（默认 120），超限 429 + `Retry-After`。

---

## 6. 安全建议

| 建议 | 原因 / 做法 |
| --- | --- |
| 生产必须 HTTPS，并设 `COOKIE_SECURE=true` | 否则会话 cookie 在明文链路上可被截获；开了 `Secure` 却在 HTTP 下访问会表现为"登录后立刻被踢回登录页" |
| `SECRET_KEY` 用随机长串（≥32 字节） | 它是会话与 CSRF 的签名根；泄露 = 可以伪造任意用户会话。轮换它会让所有人重新登录 |
| 反代传 `X-Forwarded-For` / `X-Real-IP` | 限流与审计都依赖它，否则全站共用一个 IP |
| 有反代时把反代网段写进 `TRUSTED_PROXIES` | 应用只在直连 peer 命中该名单时才采信转发头；留空 = 谁都不信（直连部署的正确选择）。不配就会把所有人算成代理 IP，配错网段则等同不配 |
| 收紧 `CORS_ORIGINS` | 默认 `*`（且 `allow_credentials=False`，不让带 cookie）。给外部脚本用的话按需列白名单 |
| 需要给脚本发 API 时再配 `API_KEY` | 一个全局共享密钥，无按客户端区分、无过期时间、轮换即全量失效；密钥用定长比较（`safe_compare`）防时序探测 |
| 生产可关 `API_DOCS_ENABLED` | 少暴露一份 schema；但内部团队通常更希望留着 `/docs`，自行权衡 |
| 慎给 `admin` | `admin` 能改站点设置，而首页说明支持一段 HTML（保存时经 `sanitize_html` 白名单净化，`<script>`/事件属性进不来，但仍可嵌入外链与图片，等于能往首页放内容/追踪像素） |
| 慎给 `editor` | `editor` 能删除/恢复任意 Book（见 1.1 的风险说明） |
| 定期看审计日志 | 关注非工作时间的 `book.delete`、`chapter.replace`、`user.*` |
| 别把 `_readyz_probe` 当异常 | `/readyz` 每次都会建/删一行，表存在是正常的 |

已内置、无需额外配置的防护：

- 响应头 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: same-origin`、`Permissions-Policy`；
- HTML 页面带 CSP：`default-src 'self'`、`script-src 'self'`（**不允许内联脚本**，所以模板里用 `data-confirm` 而不是 `onclick`）、`frame-ancestors 'none'`、`form-action 'self'`；
- 章节 HTML 白名单净化（`nh3`），去 `script`/事件属性/`javascript:`/`iframe`/`form`，链接统一加 `rel="noopener noreferrer nofollow"`；
- Webhook 回调地址不能指向本机/内网，投递前还会再解析一次域名（防 DNS rebinding），且不跟随 3xx 重定向；
- SVG 媒体以沙箱 CSP（`default-src 'none'; …; sandbox`）返回，同源直接打开也无法执行脚本；`unlisted` Book 的媒体还要求 Token 的 Book 范围覆盖该 Book；
- API Token 的 `admin` 作用域与 Book 范围互斥（签发时拒绝、存量的直接 403），用 Token 签发的 Token 不能超出签发者自身的作用域与范围；
- 内置《AI Agent 接入使用指南》：启动时幂等创建（`BUILTIN_GUIDE_ENABLED`，默认开），整本与其中章/节都**不可删除**，
  访问标识 `ai-agent-guide` 与文档类型锁定；标题、简介、可见性、正文都可以改，升级不会覆盖已有内容；
- 登录失败与账号不存在走相同的提示与相近耗时（`authenticate` 对不存在的用户也用固定的合法 dummy hash 真跑一次 bcrypt），不泄露账号是否存在；超长密码只会得到 401，不会 500；
- 登录限流两层：按「IP+用户名」防单账号爆破，按「IP 总尝试数」防换用户名喷洒（默认 `max(10, LOGIN_FAIL_LIMIT×6)` / `LOGIN_FAIL_WINDOW`）；
- Webhook 先落库、事务提交后才在后台线程投递，回调慢或不可达不会拖住内容写入；
- 上传分块读、边读边计数，超大文件在读取过程中就 413；请求体总量超 `MAX_REQUEST_BYTES` 在读正文前就 413；
- 日志里密码、token、`api_key`、cookie 等字段自动打码成 `***`。

目前的缺口（已知、未实现）：

- 没有自助改密码、没有 2FA、没有 SSO（OIDC/LDAP）——OpenSpec 设计里把认证入口收敛了，后续可插 provider；
- 没有按 Book 的授权，也没有只读角色；
- 进程内限流与登录计数在多副本部署下不共享。
