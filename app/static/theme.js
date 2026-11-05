/* 主题初始化：必须在 <head> 同步执行，避免首屏亮暗闪烁。
 * 三态：auto（跟随系统）/ light / dark，存 localStorage["bookhub-theme"]。 */
(function () {
  "use strict";

  var KEY = "bookhub-theme";
  var root = document.documentElement;

  function read() {
    try {
      var value = localStorage.getItem(KEY);
      return value === "light" || value === "dark" ? value : "auto";
    } catch (error) {
      return "auto";
    }
  }

  function systemDark() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function isDark(mode) {
    return mode === "dark" || (mode === "auto" && systemDark());
  }

  function apply(mode) {
    if (mode === "light" || mode === "dark") {
      root.setAttribute("data-theme", mode);
    } else {
      root.removeAttribute("data-theme");
    }

    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      meta.setAttribute("content", isDark(mode) ? "#16130f" : "#1f3a5f");
    }

    var buttons = document.querySelectorAll("[data-theme-choice]");
    for (var i = 0; i < buttons.length; i += 1) {
      buttons[i].setAttribute(
        "aria-pressed",
        buttons[i].getAttribute("data-theme-choice") === mode ? "true" : "false"
      );
    }
  }

  function save(mode) {
    try {
      if (mode === "auto") {
        localStorage.removeItem(KEY);
      } else {
        localStorage.setItem(KEY, mode);
      }
    } catch (error) {
      /* 隐私模式下写入失败，忽略即可，本次会话仍然生效 */
    }
  }

  function bind() {
    var buttons = document.querySelectorAll("[data-theme-choice]");
    for (var i = 0; i < buttons.length; i += 1) {
      buttons[i].addEventListener("click", function (event) {
        var mode = event.currentTarget.getAttribute("data-theme-choice") || "auto";
        save(mode);
        apply(mode);
      });
    }

    if (window.matchMedia) {
      var query = window.matchMedia("(prefers-color-scheme: dark)");
      var onChange = function () {
        if (read() === "auto") {
          apply("auto");
        }
      };
      if (query.addEventListener) {
        query.addEventListener("change", onChange);
      } else if (query.addListener) {
        query.addListener(onChange);
      }
    }
  }

  // 首屏立即生效（脚本位于 <head>，此时 DOM 尚未构建完，只处理 <html> 与 meta）
  apply(read());

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      apply(read());
      bind();
    });
  } else {
    bind();
  }

  window.bookhubTheme = { get: read, apply: apply };
})();
