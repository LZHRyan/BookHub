# Design

## Context

`chapters.replace_content()` 目前无条件 `current_version_no += 1` 并写版本记录，所以「同一份内容保存两次 = v2、v3」。管理端写完内容后统一 303 回目标页，但页面没有任何结果提示（只有 `?error=` 分支），用户无法判断这次点击是否生效。分享能力目前完全缺失：没有复制按钮，`<head>` 里也没有任何 meta。动机见 `proposal.md`。

## Goals / Non-Goals

**Goals:**

- 让"这次保存是否产生了新版本"变得确定且可见。
- 没有改动时保存是幂等的（版本号不动、审计不多、Webhook 不抖）。
- 任何页面都能一键拿到可分享的绝对地址，且 IM 里有像样的预览。

**Non-Goals:**

- 短链、二维码、分享统计、分享权限控制。
- 前端框架/富文本编辑器。
- 改变 API 的保存契约（API 也复用同一幂等逻辑，返回原版本号）。

## Decisions

### D1. 幂等判定放在服务层，比较"将要写入的值"与"当前值"

在 `replace_content()` 计算完 `new_title / new_fmt / new_raw` 与 slug 变更后：

```python
unchanged = (
    new_title == chapter.title
    and new_fmt == chapter.format
    and new_raw == chapter.content_raw
    and not slug_changing
)
if unchanged:
    return chapter           # 不 bump 版本、不写审计、不推事件
```

- **理由**：网页端与管理 API 都调用它，一处判定两边同时受益；调用方用「版本号有没有变」就能区分结果，不需要改返回值签名（避免动 3 处调用点与既有测试）。
- **备选**：让服务返回 `(chapter, changed)` —— 语义更直白，但要改全部调用点与测试；收益不抵改动面，放弃。
- 只改标题也算改动（标题属于内容），只改 slug 也算。

### D2. 结果提示用 PRG + `?notice=<code>`

成功 303 回目标页并带上稳定的 code：`chapter-created` / `chapter-saved` / `chapter-unchanged` / `book-created` / `book-saved`。模板片段 `admin/_notice.html` 负责把 code 映射成文案，版本号直接读页面里的对象（编辑页有 `chapter`，详情页有 `book`），因此**不需要把文案放进 URL**，也不会引入注入面。

- **理由**：仓库已有 `?error=` 与 `?batch=` 两套同类约定，保持一致；无脚本也能工作（服务端渲染），刷新不会重复提交。
- **备选**：session flash —— 需要引入会话存储字段与清理逻辑，收益不值得。

### D3. 防重复提交在 `document` 上统一拦截，避开确认弹窗

`app.js` 在既有 `data-confirm` 监听器**之后**再注册一个 `submit` 监听：`setTimeout(0)` 后若 `event.defaultPrevented` 为真（说明被确认弹窗取消）就直接返回，否则禁用 `event.submitter` 并改文案为「处理中…」。

- **理由**：一处覆盖所有 POST 表单（章节、Book、分组、批量、Token、媒体），不用给每个模板加属性；`defaultPrevented` 判断解决"取消后按钮被锁死"。
- **代价**：禁用后若服务端返回 500 且浏览器停留在原页，按钮会保持禁用——可接受（错误页本身要重新加载）。

### D4. 分享地址在服务端拼，不在前端猜

`public.py` 用一个 `share_url(request, path)` 助手：`str(request.base_url).rstrip("/") + root_path + path`。模板只拿现成字符串放进 `data-copy`，并同时写进 `og:url`。

- **理由**：`request.base_url` 已包含 `ROOT_PATH`（与 `sitemap` 里 `_absolute()` 同一手法），反代剥离前缀时也不会丢；前端 `window.location.href` 在子路径部署下容易拼错。
- 复制交互复用媒体库已有的 `data-copy` 处理器，只补一个"剪贴板不可用时 `prompt` 兜底"。

### D5. OG 元数据用模板 block 注入

`base.html` 的 `<head>` 里加 `{% block meta %}{% endblock %}`；`book.html` / `chapter.html` 覆盖它，输出 `og:title/description/url/type/image`。

- **理由**：不动 base 的其它部分，也不给每个页面都塞一份 OG。
- 封面 `og:image` 用 `media_url` + `share_url` 转绝对地址；没有封面就不输出该标签。

### D6. 保存按钮预告版本号

编辑页按钮从「保存并生成新版本」改为「保存为 v{{ chapter.current_version_no + 1 }}」；无改动保存后版本不变，按钮又变回同一个数字，与提示互相印证。

## Risks / Trade-offs

- [用户真的想"用同一内容打一个版本标记"]（例如只想改 note）→ 现在不允许；需要时可先用 API `PATCH` 带不同 content 或后续加"强制新版本"开关。文档里说明。
- [幂等比较是字符串级]：仅空白差异也算改动 → 会生成新版本；这是保守方向（不吞掉用户的真实编辑），可接受。
- [`?notice=` 可被手动构造] → 只是显示一条固定文案，无数据泄露与注入风险。
- [禁用按钮在无 JS 环境失效] → 服务端幂等已经兜住"重复提交"的后果（不会多出版本），JS 只是体验优化。

## Migration Plan

无数据结构变更，不需要迁移。发布后：
1. 老版本的重复保存行为不再可能（同一内容不再产出新版本）；
2. 已有历史版本不受影响。
