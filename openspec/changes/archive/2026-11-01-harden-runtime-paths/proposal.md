## Why

全仓巡检（读代码 + 对运行实例做异常输入探测）发现四处运行时问题，都不涉及"越权拿到数据"，但会让服务在真实压力下不可用：

1. **匿名即可打出 500**：登录对不存在的用户用了一个拼出来的假 bcrypt hash，`checkpw` 立刻抛 `ValueError`；密码超过 72 字节时又走到 `hashpw(..., 假 hash)`，异常未被捕获 → 任意人可稳定制造 500。
2. **用户名可被枚举**：同一个假 hash 让"用户不存在"分支根本不做哈希，实测存在用户 ~172 ms、不存在用户 ~4 ms，差 40 倍。
3. **Webhook 在写事务里同步投递**：`dispatch()` 在 `set_status`/`create_chapter` 内同步发 HTTP（5 s 超时），一 publish 含 N 节的章 = N+1 次串行请求，且事务未提交 → 全站写入排队；注册一个不回包的地址就能拖死写路径，启动阶段建内置指南时同样会被拖慢。
4. **上传先整读再校验大小**：`await upload.read()` 之后才比上限，2 GB 文件先吃掉 2 GB 内存再 413；请求体整体也没有任何上限。

## What Changes

- **登录等时与 500**：改用固定的**合法** dummy bcrypt hash；超长/空密码分支也只花一次哈希时间且绝不抛异常。
- **登录限流补一层**：在原有「(IP, 用户名)」计数之外，新增**每 IP 每分钟/窗口总尝试数**上限，换用户名刷登录会被 429 挡下；`RateLimiter` 增加硬上限与过期清扫，避免海量 key 把内存拖爆。
- **Webhook 改成两阶段投递**：`dispatch()` 只在事务里写待投递记录；`after_commit` 监听器把记录 id 交给后台线程池，用独立会话发送（失败只落库 + 日志）；回滚则丢弃待投递。管理端「测试」按钮仍同步发送以便立刻看到结果。
- **上传与请求体上限**：所有上传入口改为分块读取、边读边计数（超限立刻 413，不再整份进内存）；新增 `BodySizeLimitMiddleware` 与 `MAX_REQUEST_BYTES`（默认按「文件个数 × 单文件上限 + 1 MiB」计算），`Content-Length` 超限直接 413。
- **统一 500**：补 `Exception` 兜底处理器，未预期异常返回 `internal_error` 统一错误体（带 request id、不含堆栈），HTML 侧渲染错误页。

## Impact

- 代码：`app/{security,users,main,middleware,db,config}.py`、`app/services/{webhooks,ratelimit}.py`、`app/uploads.py`（新增）、`app/api/admin.py`、`app/web/{admin,auth}.py`、`tests/conftest.py`。
- 行为变化：webhook 投递从"同步"变为"提交后异步"（同一 hook 的事件不保证到达顺序，按 `occurred_at` 处理）；单 IP 登录尝试有了总量上限；超过 `MAX_REQUEST_BYTES` 的请求直接 413。
- 规格：`admin-auth`（等时与每 IP 限流）、`webhooks`（两阶段投递）、`management-api`（分块读取与请求体上限）、`content-api`（500 统一错误体）。
- 测试：`tests/test_runtime_hardening.py`（12 条）+ 既有 webhook/集成用例改为同步执行器；全量 447 passed。
