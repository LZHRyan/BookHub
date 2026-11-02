# Tasks

## 1. 登录路径（P0/P1）

- [x] 1.1 `security.DUMMY_PASSWORD_HASH`：固定的合法 bcrypt hash（60 字符），替换拼接假串
- [x] 1.2 `verify_password` 超长/空密码分支只花一次哈希时间、绝不抛异常（`_bcrypt_work` + `suppress`）
- [x] 1.3 `users.authenticate` 用户不存在时用它做真实校验（等时）
- [x] 1.4 每 IP 登录总闸 `login_ip_limiter`（默认 `max(10, login_fail_limit×6)` / 窗口），命中返回 429
- [x] 1.5 `RateLimiter` 增加 `max_entries` + 过期清扫 + 超限按最旧命中淘汰

## 2. Webhook 两阶段投递（P1）

- [x] 2.1 `dispatch()` 只写待投递记录（`status_code` 留空）并把 id 登记到 `session.info`
- [x] 2.2 `app.db` 的 `after_commit` 监听器把 id 交给后台线程；`after_rollback` 丢弃
- [x] 2.3 `deliver_pending()`：独立会话发送、失败只记日志、跳过已投递/已停用
- [x] 2.4 `send_now()` 供管理端「测试」按钮同步发送（并从待投递队列摘除）
- [x] 2.5 测试用 `InlineExecutor` 替换执行器，仍然走真实两阶段路径
- [x] 2.6 应用退出时关闭线程池

## 3. 上传与请求体上限（P1/P2）

- [x] 3.1 `app/uploads.read_limited()`：1 MiB 分块、边读边计数、超限立刻 413
- [x] 3.2 五处上传入口改用它（章节 multipart ×2、媒体 API、网页正文、网页媒体）
- [x] 3.3 `BodySizeLimitMiddleware`：`Content-Length` 超限直接 413（带 request id）
- [x] 3.4 `MAX_REQUEST_BYTES` 配置（默认 `文件个数 × 单文件上限 + 1 MiB`）+ `.env.example`

## 4. 统一 500（P2）

- [x] 4.1 注册 `Exception` 兜底处理器：JSON 走统一错误体，HTML 走错误页，日志带 request id
- [x] 4.2 响应与日志都不含堆栈与内部路径

## 5. 验证

- [x] 5.1 新增 `tests/test_runtime_hardening.py`（等时/长密码 401/每 IP 限流/桶上限/分块读/413/两阶段投递/回滚/500 兜底/默认请求体上限）
- [x] 5.2 全量 `pytest`（447 passed）+ `ruff` 通过
- [x] 5.3 容器实测：长密码+不存在用户 → 401；存在/不存在用户耗时 172/174 ms；300 MB `Content-Length` → 413（带 request id）
