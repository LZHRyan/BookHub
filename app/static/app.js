/* 轻量交互：二次确认、移动端搜索展开、页内目录高亮。无构建步骤、无依赖。 */
(function () {
  "use strict";

  /* data-confirm：替代内联 onclick，兼容严格 CSP */
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    var message = form.getAttribute("data-confirm");
    if (message && !window.confirm(message)) {
      event.preventDefault();
    }
  });

  /* 图标面板：点选把图标名写进 #icon，并把按钮内的 SVG 直接搬进预览 */
  var iconInput = document.querySelector("#icon");
  if (iconInput) {
    var preview = document.querySelector("[data-icon-preview]");
    var emptyPreview = preview ? preview.innerHTML : "";

    var renderPreview = function (svg) {
      if (!preview) return;
      if (svg) {
        preview.innerHTML = svg;
      } else {
        preview.innerHTML = emptyPreview;
      }
    };

    iconInput.addEventListener("input", function () {
      var value = iconInput.value.trim();
      if (!value) {
        renderPreview("");
        return;
      }
      // 手输的是图标名，客户端没有图标表，先按文字显示；保存后由服务端渲染成 SVG
      preview.textContent = value;
    });

    document.addEventListener("click", function (event) {
      var target = event.target;
      if (!(target instanceof Element)) return;

      var option = target.closest("[data-icon]");
      if (option) {
        event.preventDefault();
        iconInput.value = option.getAttribute("data-icon") || "";
        renderPreview(option.innerHTML);
        iconInput.focus();
        return;
      }

      if (target.closest("[data-icon-clear]")) {
        event.preventDefault();
        iconInput.value = "";
        renderPreview("");
        iconInput.focus();
      }
    });
  }

  /* [data-back]：不用 javascript: 链接（被 CSP 拦），改成按钮 + 事件 */
  var back = document.querySelector("[data-back]");
  if (back) {
    back.addEventListener("click", function () {
      if (window.history.length > 1) {
        window.history.back();
      } else {
        window.location.href = "/";
      }
    });
  }

  /* 移动端搜索：点顶部图标展开输入框 */
  var toggle = document.querySelector("[data-search-toggle]");
  var topbar = document.querySelector(".topbar");
  if (toggle && topbar) {
    toggle.addEventListener("click", function () {
      var open = topbar.classList.toggle("searching");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) {
        var input = topbar.querySelector(".search-form input");
        if (input) input.focus();
      }
    });
  }

  /* 媒体上传：粘贴截图 / 拖入文件 / 点选上传，三种入口共用同一个端点 */
  var mediaBox = document.querySelector("[data-media-upload]");
  if (mediaBox) {
    var uploadUrl = mediaBox.getAttribute("data-upload-url") || "";
    var mediaCsrf = mediaBox.getAttribute("data-csrf") || "";
    var mediaFormat = mediaBox.getAttribute("data-format") || "markdown";
    var targetSelector = mediaBox.getAttribute("data-target") || "";
    var editor = targetSelector ? document.querySelector(targetSelector) : null;
    var statusBox = mediaBox.querySelector("[data-media-status]");
    var fileInput = mediaBox.querySelector("[data-media-input]");

    var setStatus = function (text, kind) {
      if (!statusBox) return;
      statusBox.textContent = text || "";
      statusBox.setAttribute("data-kind", kind || "");
    };

    var referenceOf = function (payload) {
      var label = (payload.filename || "附件").replace(/[[\]|]/g, "-");
      if (payload.kind === "image") {
        return mediaFormat === "html"
          ? '<img src="' + payload.url + '" alt="' + label + '">'
          : "![" + label + "](" + payload.url + ")";
      }
      return mediaFormat === "html"
        ? '<a href="' + payload.url + '">' + label + "</a>"
        : "[" + label + "](" + payload.url + ")";
    };

    var insertReference = function (payload) {
      if (!editor) return;
      var snippet = referenceOf(payload);
      if (editor.tagName === "TEXTAREA") {
        var start = editor.selectionStart || 0;
        var end = editor.selectionEnd || 0;
        editor.setRangeText(snippet, start, end, "end");
      } else {
        editor.value = (editor.value || "") + snippet;
      }
      editor.dispatchEvent(new Event("input", { bubbles: true }));
      editor.focus();
    };

    var uploadOne = function (file) {
      var body = new FormData();
      body.append("csrf_token", mediaCsrf);
      body.append("upload", file, file.name || "pasted.png");
      return fetch(uploadUrl, {
        method: "POST",
        body: body,
        credentials: "same-origin",
        headers: { "X-CSRF-Token": mediaCsrf }
      }).then(function (response) {
        return response.json().then(function (data) {
          if (!response.ok) {
            var message = (data && data.error && data.error.message) || "上传失败";
            throw new Error(message);
          }
          return data;
        });
      });
    };

    var uploadFiles = function (files) {
      var list = Array.prototype.slice.call(files || []).filter(Boolean);
      if (list.length === 0) return;
      setStatus("正在上传 " + list.length + " 个文件…", "pending");
      var chain = Promise.resolve();
      var done = 0;
      list.forEach(function (file) {
        chain = chain.then(function () {
          return uploadOne(file).then(function (payload) {
            insertReference(payload);
            done += 1;
          });
        });
      });
      chain
        .then(function () {
          setStatus("已插入 " + done + " 个引用", "ok");
        })
        .catch(function (error) {
          setStatus(error.message || "上传失败", "error");
        });
    };

    if (editor) {
      editor.addEventListener("paste", function (event) {
        var clipboard = event.clipboardData;
        if (!clipboard) return;
        var files = Array.prototype.slice.call(clipboard.files || []);
        if (files.length === 0) {
          files = Array.prototype.slice
            .call(clipboard.items || [])
            .filter(function (item) {
              return item.kind === "file";
            })
            .map(function (item) {
              return item.getAsFile();
            });
        }
        if (files.length === 0) return;
        event.preventDefault();
        uploadFiles(files);
      });
    }

    ["dragenter", "dragover"].forEach(function (name) {
      mediaBox.addEventListener(name, function (event) {
        event.preventDefault();
        mediaBox.classList.add("is-dragging");
      });
    });
    ["dragleave", "dragend"].forEach(function (name) {
      mediaBox.addEventListener(name, function () {
        mediaBox.classList.remove("is-dragging");
      });
    });
    mediaBox.addEventListener("drop", function (event) {
      event.preventDefault();
      mediaBox.classList.remove("is-dragging");
      if (event.dataTransfer) uploadFiles(event.dataTransfer.files);
    });

    if (fileInput) {
      fileInput.addEventListener("change", function () {
        uploadFiles(fileInput.files);
        fileInput.value = "";
      });
    }
  }

  /* 文件选择：原生按钮太丑，改成整块可拖放区域；选中后显示文件名与总大小 */
  document.querySelectorAll("[data-file-field]").forEach(function (field) {
    var input = field.querySelector('input[type="file"]');
    var names = field.querySelector("[data-file-names]");
    if (!input || !names) return;

    var emptyLabel = names.getAttribute("data-empty") || "未选择文件";

    var formatSize = function (bytes) {
      if (bytes >= 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + " MB";
      if (bytes >= 1024) return Math.round(bytes / 1024) + " KB";
      return bytes + " B";
    };

    var sync = function () {
      var files = Array.prototype.slice.call(input.files || []);
      if (!files.length) {
        field.classList.remove("has-files");
        names.textContent = emptyLabel;
        names.removeAttribute("title");
        return;
      }
      var total = files.reduce(function (sum, file) { return sum + file.size; }, 0);
      var shown = files.slice(0, 2).map(function (file) { return file.name; }).join("、");
      if (files.length > 2) shown += " 等 " + files.length + " 个文件";
      field.classList.add("has-files");
      names.textContent = shown + " · " + formatSize(total);
      names.title = files.map(function (file) { return file.name; }).join("\n");
    };

    input.addEventListener("change", sync);

    /* 拖放：浏览器允许直接往 file input 上放文件，这里只负责高亮与兜底赋值 */
    ["dragenter", "dragover"].forEach(function (name) {
      field.addEventListener(name, function (event) {
        event.preventDefault();
        field.classList.add("is-dragover");
      });
    });
    field.addEventListener("dragleave", function (event) {
      if (!field.contains(event.relatedTarget)) field.classList.remove("is-dragover");
    });
    field.addEventListener("drop", function (event) {
      field.classList.remove("is-dragover");
      if (!event.dataTransfer || !event.dataTransfer.files.length) return;
      // 不拦默认行为：浏览器会把文件直接填进 file input；这里只补一次同步，
      // 兼容「填了 files 但没触发 change」的实现。
      window.setTimeout(sync, 0);
    });
  });

  /* Book 范围选择器：分组筛选 + 搜索 + 分页；勾选状态跨页、跨筛选保留 */
  document.querySelectorAll("[data-book-picker]").forEach(function (picker) {
    var url = picker.getAttribute("data-url") || "";
    var list = picker.querySelector("[data-book-list]");
    var groupSelect = picker.querySelector("[data-book-group]");
    var search = picker.querySelector("[data-book-search]");
    var countBox = picker.querySelector("[data-book-count]");
    var rangeBox = picker.querySelector("[data-book-range]");
    var prevBtn = picker.querySelector("[data-book-prev]");
    var nextBtn = picker.querySelector("[data-book-next]");
    var selectedBox = picker.querySelector("[data-book-selected]");
    var chipsBox = picker.querySelector("[data-book-chips]");
    var hiddenBox = picker.querySelector("[data-book-hidden]");
    var clearBtn = picker.querySelector("[data-book-clear]");
    if (!list || !url || !groupSelect || !search) return;

    var state = {
      page: parseInt(picker.getAttribute("data-page"), 10) || 1,
      pages: parseInt(picker.getAttribute("data-pages"), 10) || 1,
      group: picker.getAttribute("data-group") || "",
      query: picker.getAttribute("data-query") || ""
    };
    var selected = new Map(); // id -> {title, icon}

    var syncHidden = function () {
      hiddenBox.textContent = "";
      var visible = {};
      list.querySelectorAll("[data-book-id]").forEach(function (cb) {
        visible[cb.value] = true;
      });
      selected.forEach(function (meta, id) {
        if (visible[String(id)]) return; // 当前页的复选框本身会随表单提交
        var input = document.createElement("input");
        input.type = "hidden";
        input.name = "book_ids";
        input.value = String(id);
        hiddenBox.appendChild(input);
      });
    };

    var renderChips = function () {
      chipsBox.textContent = "";
      selectedBox.hidden = selected.size === 0;
      selected.forEach(function (meta, id) {
        var chip = document.createElement("span");
        chip.className = "book-chip";
        var label = document.createElement("span");
        label.textContent = (meta.icon ? meta.icon + " " : "") + meta.title;
        var remove = document.createElement("button");
        remove.type = "button";
        remove.setAttribute("aria-label", "取消选择 " + meta.title);
        remove.textContent = "×";
        remove.addEventListener("click", function () {
          selected.delete(id);
          var cb = list.querySelector('[data-book-id="' + id + '"]');
          if (cb) cb.checked = false;
          renderChips();
          syncHidden();
        });
        chip.appendChild(label);
        chip.appendChild(remove);
        chipsBox.appendChild(chip);
      });
    };

    var renderRows = function (items) {
      list.textContent = "";
      if (!items.length) {
        var empty = document.createElement("p");
        empty.className = "small muted book-picker-empty";
        empty.textContent = "没有符合条件的 Book。";
        list.appendChild(empty);
        return;
      }
      items.forEach(function (book) {
        var row = document.createElement("label");
        row.className = "book-pick-row";
        var box = document.createElement("input");
        box.type = "checkbox";
        box.name = "book_ids";
        box.value = String(book.id);
        box.setAttribute("data-book-id", String(book.id));
        box.setAttribute("data-book-title", book.title);
        box.setAttribute("data-book-icon", book.icon || "");
        box.checked = selected.has(book.id);
        var title = document.createElement("span");
        title.className = "book-pick-title";
        title.textContent = (book.icon ? book.icon + " " : "") + book.title;
        var meta = document.createElement("span");
        meta.className = "book-pick-meta";
        meta.textContent = book.slug + (book.group ? " · " + book.group : "");
        row.appendChild(box);
        row.appendChild(title);
        row.appendChild(meta);
        list.appendChild(row);
      });
    };

    var applyPage = function (data) {
      state.page = data.page;
      state.pages = data.pages;
      renderRows(data.books || []);
      countBox.textContent = "共 " + data.total + " 本";
      rangeBox.textContent = "第 " + data.page + " / " + data.pages + " 页";
      prevBtn.disabled = data.page <= 1;
      nextBtn.disabled = data.page >= data.pages;
      syncHidden();
    };

    var showError = function () {
      list.textContent = "";
      var message = document.createElement("p");
      message.className = "small muted book-picker-empty";
      message.textContent = "加载 Book 列表失败，请刷新页面重试。";
      list.appendChild(message);
    };

    var load = function (page) {
      var params = new URLSearchParams();
      if (state.group) params.set("group", state.group);
      if (state.query) params.set("q", state.query);
      params.set("page", String(page || 1));
      list.classList.add("is-loading");
      fetch(url + "?" + params.toString(), { headers: { Accept: "application/json" } })
        .then(function (response) {
          if (!response.ok) throw new Error("book list failed");
          return response.json();
        })
        .then(applyPage)
        .catch(showError)
        .then(function () { list.classList.remove("is-loading"); });
    };

    list.addEventListener("change", function (event) {
      var box = event.target;
      if (!(box instanceof HTMLInputElement) || !box.hasAttribute("data-book-id")) return;
      var id = parseInt(box.value, 10);
      if (box.checked) {
        selected.set(id, {
          title: box.getAttribute("data-book-title") || "",
          icon: box.getAttribute("data-book-icon") || ""
        });
      } else {
        selected.delete(id);
      }
      renderChips();
      syncHidden();
    });

    groupSelect.addEventListener("change", function () {
      state.group = groupSelect.value;
      load(1);
    });

    var timer = 0;
    search.addEventListener("input", function () {
      window.clearTimeout(timer);
      timer = window.setTimeout(function () {
        state.query = search.value.trim();
        load(1);
      }, 250);
    });

    prevBtn.addEventListener("click", function () {
      if (state.page > 1) load(state.page - 1);
    });
    nextBtn.addEventListener("click", function () {
      if (state.page < state.pages) load(state.page + 1);
    });
    clearBtn.addEventListener("click", function () {
      selected.clear();
      list.querySelectorAll("[data-book-id]").forEach(function (box) { box.checked = false; });
      renderChips();
      syncHidden();
    });

    syncHidden();
  });

  /* 复制媒体地址 */
  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!(target instanceof Element)) return;
    var button = target.closest("[data-copy]");
    if (!button) return;
    event.preventDefault();
    var text = button.getAttribute("data-copy") || "";
    var originalHtml = button.innerHTML;
    var done = function () {
      button.textContent = "已复制";
      window.setTimeout(function () {
        button.innerHTML = originalHtml;
      }, 1200);
    };
    var fallback = function () {
      // 剪贴板不可用（老浏览器 / 非 HTTPS / 用户拒绝）时给一个可手动复制的输入框
      window.prompt("复制这个链接：", text);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, fallback);
    } else {
      fallback();
    }
  });

  /* 防止重复提交：POST 表单提交后锁住按钮，确认弹窗取消则不锁 */
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if ((form.getAttribute("method") || "get").toLowerCase() !== "post") return;
    var button = event.submitter;
    if (!button) return;
    window.setTimeout(function () {
      if (event.defaultPrevented) return; // data-confirm 被取消
      if (button.disabled) return;
      button.disabled = true;
      button.setAttribute("data-original-label", button.textContent.trim());
      button.textContent = "处理中…";
    }, 0);
  });


  /* 目录拖拽排序：只在同一个 tbody（同一父级）内生效 */
  var sortRoot = document.querySelector("#chapter-sort-root");
  if (sortRoot) {
    var reorderUrl = sortRoot.getAttribute("data-reorder-url") || "";
    var reorderCsrf = sortRoot.getAttribute("data-csrf") || "";
    var draggedRow = null;
    var draggedFrom = null;

    var submitOrder = function (tbody) {
      var ids = Array.prototype.slice
        .call(tbody.querySelectorAll("tr[data-chapter-id]"))
        .map(function (row) {
          return parseInt(row.getAttribute("data-chapter-id"), 10);
        })
        .filter(function (value) {
          return !isNaN(value);
        });
      if (ids.length === 0) return;
      fetch(reorderUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": reorderCsrf },
        body: JSON.stringify({
          parent: tbody.getAttribute("data-parent") || null,
          chapter_ids: ids
        })
      }).then(function (response) {
        if (!response.ok) {
          return response.json().then(function (data) {
            throw new Error((data && data.error && data.error.message) || "排序失败");
          });
        }
        window.location.reload();
      }).catch(function (error) {
        window.alert(error.message || "排序失败，已恢复原顺序");
        window.location.reload();
      });
    };

    sortRoot.addEventListener("dragstart", function (event) {
      var row = event.target instanceof Element ? event.target.closest("tr[data-chapter-id]") : null;
      if (!row) return;
      draggedRow = row;
      draggedFrom = row.parentElement;
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", row.getAttribute("data-chapter-id") || "");
      }
      row.classList.add("is-dragging");
    });

    sortRoot.addEventListener("dragover", function (event) {
      if (!draggedRow) return;
      var row = event.target instanceof Element ? event.target.closest("tr[data-chapter-id]") : null;
      if (!row || row === draggedRow) return;
      // 只允许同父级（同一 tbody）内交换
      if (row.parentElement !== draggedFrom) return;
      event.preventDefault();
      var rect = row.getBoundingClientRect();
      var after = event.clientY > rect.top + rect.height / 2;
      row.parentElement.insertBefore(draggedRow, after ? row.nextSibling : row);
    });

    sortRoot.addEventListener("drop", function (event) {
      if (!draggedRow) return;
      event.preventDefault();
      var target = draggedRow.parentElement;
      if (target === draggedFrom) submitOrder(target);
    });

    sortRoot.addEventListener("dragend", function () {
      if (draggedRow) draggedRow.classList.remove("is-dragging");
      draggedRow = null;
      draggedFrom = null;
    });
  }

  /* 批量操作：勾选计数 + 删除确认 */
  var batchForm = document.querySelector("[data-batch-form]");
  if (batchForm) {
    var batchCount = batchForm.querySelector("[data-batch-count]");
    var batchConfirm = batchForm.querySelector("[data-batch-confirm]");

    var syncBatch = function () {
      var picked = document.querySelectorAll('input[name="chapter_id"]:checked').length;
      if (batchCount) {
        batchCount.textContent = picked ? "已选择 " + picked + " 个章节" : "未选择章节";
      }
    };
    document.addEventListener("change", function (event) {
      var target = event.target;
      if (target instanceof Element && target.matches('input[name="chapter_id"]')) syncBatch();
    });
    syncBatch();

    batchForm.addEventListener("submit", function (event) {
      var action = event.submitter ? event.submitter.value : "";
      var picked = document.querySelectorAll('input[name="chapter_id"]:checked').length;
      if (picked === 0) {
        event.preventDefault();
        window.alert("请先勾选要操作的章节");
        return;
      }
      if (action === "delete") {
        if (!window.confirm("确认批量删除选中的 " + picked + " 个章节？删除后进入回收站，可恢复。")) {
          event.preventDefault();
          return;
        }
        if (batchConfirm) batchConfirm.value = "1";
      }
    });
  }

  /* 页内目录滚动高亮 */
  var links = Array.prototype.slice.call(document.querySelectorAll(".toc-side a"));
  if (links.length === 0) return;

  var targets = links
    .map(function (link) {
      var href = link.getAttribute("href") || "";
      if (href.charAt(0) !== "#") return null;
      var id = decodeURIComponent(href.slice(1));
      var el = document.getElementById(id);
      return el ? { link: link, el: el } : null;
    })
    .filter(Boolean);

  if (targets.length === 0) return;

  function update() {
    var offset = 120;
    var active = null;
    for (var i = 0; i < targets.length; i += 1) {
      if (targets[i].el.getBoundingClientRect().top <= offset) active = targets[i];
    }
    for (var j = 0; j < targets.length; j += 1) {
      targets[j].link.classList.remove("is-active");
      targets[j].link.removeAttribute("aria-current");
    }
    if (active) {
      active.link.classList.add("is-active");
      active.link.setAttribute("aria-current", "true");
    }
  }

  var ticking = false;
  window.addEventListener("scroll", function () {
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(function () {
      update();
      ticking = false;
    });
  }, { passive: true });

  update();
})();
