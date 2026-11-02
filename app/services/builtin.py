"""内置 Book 的身份判定与不可变约束。

内置 Book 由系统在启动时幂等创建（内容见 `app/services/guide.py`），随系统生命周期
存在，语义与「默认分组」一致：

- 整本不可删除（删除会让人再也找不到使用说明，且启动时会话不会被重建）；
- 访问标识与文档类型锁定：改了 slug，写进各处的 `/b/<slug>` 链接与 MCP 配置全部失效；
  改了 format，Markdown 正文会被当成 HTML 渲染；
- 章与节也不可删除（可以编辑正文、新增、排序、发布/撤回），否则指南会被删成空壳。

这些约束在服务层强制，网页端与 API 都会得到同一个拒绝原因。
"""

from __future__ import annotations

from app.errors import ValidationFailed
from app.services.slug import slugify

# 对外承诺的固定访问标识与标题；`/api/v1/site` 的 `guide.slug` 就是它。
BUILTIN_SLUG = "ai-agent-guide"
BUILTIN_TITLE = "AI Agent 接入使用指南"


def is_builtin(book: object) -> bool:
    """是不是内置 Book。只认列上的标记：slug 相同不代表内置。

    用 slug 兜底会把「用户自己建了一本同名书」误判成内置，反而让用户的书既删不掉
    也改不了标识。
    """
    if book is None:
        return False
    return bool(getattr(book, "is_builtin", False))


def reject_book_delete(book: object) -> None:
    if is_builtin(book):
        raise ValidationFailed(
            "内置指南 Book 不能删除：它由系统创建、随系统生命周期存在；"
            "不需要读者看到时把可见性改成「未列出」即可"
        )


def reject_book_identity_change(
    book: object, *, slug_raw: object = None, fmt: object = None
) -> None:
    """访问标识与文档类型是外部集成（链接、MCP 配置、导出的 .md 后缀）的锚点。"""
    if not is_builtin(book):
        return
    if (
        isinstance(slug_raw, str)
        and slug_raw.strip()
        and slugify(slug_raw) != str(getattr(book, "slug", ""))
    ):
        raise ValidationFailed(
            "内置指南 Book 的访问标识固定为 "
            f"{BUILTIN_SLUG}，不能修改（外部工具按它拼地址）"
        )
    if isinstance(fmt, str) and fmt != getattr(book, "format", None):
        raise ValidationFailed("内置指南 Book 的文档类型固定为 Markdown，不能修改")


def reject_content_delete(book: object, label: str) -> None:
    if is_builtin(book):
        raise ValidationFailed(
            f"内置指南的{label}不能删除：需要隐藏时改发布状态（章）或改正文，"
            "整本指南必须始终可用"
        )
