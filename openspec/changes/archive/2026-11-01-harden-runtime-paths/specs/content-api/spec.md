## MODIFIED Requirements

### Requirement: 错误响应 MUST 使用统一结构

所有错误响应 MUST 使用统一结构 `{"error": {"code", "message", "request_id"}}`，其中 `request_id` 用于跨日志排查对应请求。状态码 MUST 保持语义一致：参数校验失败 400、鉴权失败 401、权限不足 403、资源不存在或不可见 404、方法不允许 405、超出限流 429、请求体过大 413。`message` MUST NOT 暴露内部实现细节或调用栈。

未预期异常 MUST 由统一的兜底处理器接住：`/api/` 与 JSON 请求返回 `error.code = internal_error` 的统一错误体（带 `request_id`，且 `request_id` 与实际日志条目一致），HTML 页面返回同一份错误说明页；MUST NOT 落到框架默认的裸文本 `Internal Server Error`。堆栈与内部路径 MUST 只进日志、不进响应。

#### Scenario: 参数校验失败返回统一错误体

- **WHEN** 外部程序传入非整数分页值或其他不符合约束的参数
- **THEN** 返回 400，响应体含 `error.code`、`error.message`、`error.request_id`
- **AND** `message` 说明哪个参数不合法而不含内部细节

#### Scenario: 服务端异常也返回统一错误体

- **WHEN** 请求处理过程中发生未预期错误
- **THEN** 返回 5xx，响应体仍为统一错误结构并含可追踪的 `request_id`
- **AND** 响应中不包含调用栈或内部路径信息

#### Scenario: 500 的 code 与日志可对上

- **WHEN** 未预期异常发生在 JSON 接口上
- **THEN** 响应 `error.code` 为 `internal_error`，`error.request_id` 与响应头 `X-Request-ID` 相同
- **AND** 服务端日志里能用同一个 request id 找到异常类型与消息

#### Scenario: 请求体过大是 413 而不是 500

- **WHEN** 请求的 `Content-Length` 超过服务端上限
- **THEN** 返回 413 与 `error.code = payload_too_large`
- **AND** 该响应同样带 `request_id`
