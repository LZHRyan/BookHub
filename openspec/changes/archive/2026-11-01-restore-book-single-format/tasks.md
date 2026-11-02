# Tasks

## 1. 服务层

- [x] 1.1 `resolve_section_format()`：节格式 MUST 等于 Book 类型，不一致抛 `ValidationFailed`
- [x] 1.2 `books.update_book()`：有章时拒绝改文档类型
- [x] 1.3 新建节 / 替换正文 / API 写入共用同一处校验

## 2. 录入端

- [x] 2.1 章节新建页：文件选择器 `accept` 按 Book 类型收窄，提示写明只接受哪些扩展名
- [x] 2.2 节编辑页：去掉格式单选，改为只读展示 + 隐藏字段；上传 `accept` 同步收窄
- [x] 2.3 网页端读取上传文件时校验扩展名与 Book 类型一致，整次请求不落库
- [x] 2.4 Book 编辑器：有章后锁定文档类型（radio 禁用 + hidden + 提示），空 Book 仍可改
- [x] 2.5 Book 详情页与章编辑器的格式说明改为「整本统一」

## 3. 验证

- [x] 3.1 测试：格式不匹配（服务层/网页上传/替换）被拒绝、Book 类型锁定、选择器静态展示
- [x] 3.2 全量 `pytest` + `ruff` + `node --check` 通过
- [x] 3.3 浏览器实测：Markdown 书 `accept=.md,.markdown,.txt`，HTML 书 `accept=.html,.htm`；节编辑器无格式单选；Book 编辑页类型锁定
- [x] 3.4 文档与规格同步（README / ai / authoring / content-model）
