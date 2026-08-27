/* piu boot diagnostics.
 *
 * Inlined into the pygbag index.html template by tools/make_template.py, and
 * deliberately placed before pygbag's own loader so it can wrap fetch and XHR
 * before anything uses them.
 *
 * The problem this solves: when the runtime fails to load, the browser
 * surfaces "Failed to fetch" with no URL attached, which is unactionable. The
 * wrappers below attach the URL, HTTP status, byte count, and elapsed time to
 * every request, so a failure names the exact resource that broke.
 *
 * Everything is defensive: this must never itself be the reason the page
 * fails to load.
 */
(function () {
  "use strict";

  var START = performance.now();
  var LINES = [];
  var PENDING = 0;
  var FAILED = 0;
  var MAX_LINES = 400;

  function elapsed() {
    return (((performance.now() - START) / 1000).toFixed(3) + "s").padStart(9);
  }

  function bytes(n) {
    if (n === null || n === undefined || isNaN(n)) return "?";
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / 1048576).toFixed(2) + " MB";
  }

  function log(kind, message, detail) {
    var text = elapsed() + "  " + kind.padEnd(5) + "  " + message;
    if (detail) text += "\n" + String(detail).replace(/^/gm, " ".repeat(20));
    LINES.push(text);
    if (LINES.length > MAX_LINES) LINES.splice(0, LINES.length - MAX_LINES);

    try {
      (kind === "FAIL" ? console.error : console.log)("[piu] " + text);
    } catch (e) {
      /* console can be unavailable in odd embeddings */
    }

    if (kind === "FAIL") {
      FAILED += 1;
      show();
    }
    render();
  }

  window.piuBootLog = log;

  /* ---------------------------------------------------------------- panel */

  var panel, output, summary;

  function build() {
    if (panel || !document.body) return;

    panel = document.createElement("div");
    panel.id = "piu-boot-panel";
    panel.setAttribute(
      "style",
      "position:fixed;left:0;right:0;bottom:0;max-height:60vh;z-index:2147483647;" +
        "background:#0b0b12;color:#dfe1e8;font:12px/1.45 ui-monospace,SFMono-Regular," +
        "Menlo,Consolas,monospace;border-top:2px solid #3a76e8;display:flex;" +
        "flex-direction:column;box-shadow:0 -8px 24px rgba(0,0,0,.5)"
    );

    var bar = document.createElement("div");
    bar.setAttribute(
      "style",
      "display:flex;gap:8px;align-items:center;padding:6px 10px;" +
        "border-bottom:1px solid #23233a;flex:0 0 auto"
    );

    summary = document.createElement("span");
    summary.setAttribute("style", "flex:1 1 auto;color:#9aa0b4");
    bar.appendChild(summary);

    bar.appendChild(button("Copy", function () {
      var text = report();
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(
          function () { flash("Copied"); },
          function () { fallbackCopy(text); }
        );
      } else {
        fallbackCopy(text);
      }
    }));

    bar.appendChild(button("Hide", function () {
      panel.style.display = "none";
    }));

    output = document.createElement("pre");
    output.id = "piu-boot-log";
    output.setAttribute(
      "style",
      "margin:0;padding:8px 10px;overflow:auto;flex:1 1 auto;white-space:pre-wrap;" +
        "word-break:break-all"
    );

    panel.appendChild(bar);
    panel.appendChild(output);
    document.body.appendChild(panel);
    render();
  }

  function button(label, onclick) {
    var b = document.createElement("button");
    b.textContent = label;
    b.setAttribute(
      "style",
      "background:#1b1b2b;color:#dfe1e8;border:1px solid #3a3a55;border-radius:4px;" +
        "padding:3px 10px;cursor:pointer;font:inherit"
    );
    b.onclick = onclick;
    return b;
  }

  function flash(message) {
    if (!summary) return;
    var previous = summary.textContent;
    summary.textContent = message;
    setTimeout(function () { summary.textContent = previous; }, 1200);
  }

  function fallbackCopy(text) {
    try {
      var area = document.createElement("textarea");
      area.value = text;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      document.body.removeChild(area);
      flash("Copied");
    } catch (e) {
      flash("Copy failed - select the text manually");
    }
  }

  function render() {
    if (!output) return;
    var stuck = output.scrollTop + output.clientHeight >= output.scrollHeight - 40;
    output.textContent = LINES.join("\n");
    if (stuck) output.scrollTop = output.scrollHeight;
    if (summary) {
      summary.textContent =
        "piu boot log - " + LINES.length + " events, " + PENDING +
        " in flight, " + FAILED + " failed";
    }
  }

  function show() {
    build();
    if (panel) panel.style.display = "flex";
  }

  function report() {
    return [
      "piu boot report",
      "generated: " + new Date().toISOString(),
      "url: " + location.href,
      "userAgent: " + navigator.userAgent,
      "crossOriginIsolated: " + (typeof crossOriginIsolated !== "undefined" ? crossOriginIsolated : "n/a"),
      "SharedArrayBuffer: " + (typeof SharedArrayBuffer !== "undefined"),
      "WebAssembly: " + (typeof WebAssembly !== "undefined"),
      "",
    ].join("\n") + LINES.join("\n");
  }

  window.piuBootReport = report;

  /* ------------------------------------------------------------ wrappers */

  var nativeFetch = window.fetch;
  if (typeof nativeFetch === "function") {
    window.fetch = function (input, init) {
      var url;
      try {
        url = typeof input === "string" ? input : (input && input.url) || String(input);
      } catch (e) {
        url = "<unreadable request>";
      }
      var method = ((init && init.method) || (input && input.method) || "GET").toUpperCase();
      var started = performance.now();

      PENDING += 1;
      log("GET", method + " " + url);

      return nativeFetch
        .apply(this, arguments)
        .then(function (response) {
          PENDING -= 1;
          var ms = Math.round(performance.now() - started);
          var size = response.headers && response.headers.get("content-length");
          var kind = response.ok ? "OK" : "FAIL";
          log(
            kind,
            response.status + " " + response.statusText + "  " + url +
              "  (" + bytes(size ? Number(size) : NaN) + ", " + ms + "ms)"
          );
          if (!response.ok) {
            log("HINT", hintForStatus(response.status, url));
          }
          return response;
        })
        .catch(function (error) {
          PENDING -= 1;
          var ms = Math.round(performance.now() - started);
          // This is the case the browser normally reports as a bare
          // "Failed to fetch" with no URL. Now it has one.
          log("FAIL", "network error after " + ms + "ms: " + url, error && (error.stack || error.message));
          log("HINT", hintForNetworkError(url));
          throw error;
        });
    };
  }

  var NativeXHR = window.XMLHttpRequest;
  if (typeof NativeXHR === "function") {
    window.XMLHttpRequest = function () {
      var xhr = new NativeXHR();
      var url = "";
      var method = "GET";
      var started = 0;

      var open = xhr.open;
      xhr.open = function (m, u) {
        method = m;
        url = u;
        return open.apply(xhr, arguments);
      };

      var send = xhr.send;
      xhr.send = function () {
        started = performance.now();
        PENDING += 1;
        log("GET", method + " " + url + "  (xhr)");
        return send.apply(xhr, arguments);
      };

      xhr.addEventListener("load", function () {
        PENDING -= 1;
        var ms = Math.round(performance.now() - started);
        var size = xhr.response && xhr.response.byteLength;
        log(
          xhr.status >= 200 && xhr.status < 300 ? "OK" : "FAIL",
          xhr.status + " " + xhr.statusText + "  " + url +
            "  (" + bytes(size) + ", " + ms + "ms, xhr)"
        );
      });
      xhr.addEventListener("error", function () {
        PENDING -= 1;
        log("FAIL", "xhr network error: " + url);
        log("HINT", hintForNetworkError(url));
      });
      xhr.addEventListener("abort", function () {
        PENDING -= 1;
        log("WARN", "xhr aborted: " + url);
      });

      return xhr;
    };
    window.XMLHttpRequest.prototype = NativeXHR.prototype;
  }

  /* --------------------------------------------------------------- hints */

  function hintForStatus(status, url) {
    if (status === 404) {
      if (url.indexOf("browserfs") >= 0) {
        return "browserfs.min.js is missing from the pygbag CDN. Known upstream " +
          "gap in 0.9.3; the template loads it optionally so this is not fatal.";
      }
      return "Resource not found. If this is a CDN path, the pinned pygbag " +
        "version may not have published it.";
    }
    if (status === 403) return "Forbidden - check the file is published and public.";
    if (status >= 500) return "Server error - the host may be having trouble; retry.";
    return "Unexpected HTTP status.";
  }

  function hintForNetworkError(url) {
    var sameOrigin = url.indexOf("http") !== 0 || url.indexOf(location.origin) === 0;
    if (sameOrigin) {
      return "Same-origin request failed: usually the file is missing from the " +
        "deployed bundle, or the connection dropped mid-transfer.";
    }
    return "Cross-origin request failed. Causes, most likely first: the host is " +
      "unreachable or blocked (adblocker, network policy, offline); missing CORS " +
      "headers on the response; or the transfer was interrupted. Large files " +
      "such as main.wasm (13 MB) are the usual casualties of a flaky link.";
  }

  /* ------------------------------------------------------------ handlers */

  window.addEventListener(
    "error",
    function (event) {
      // Capture phase catches resource load failures (script, img, link),
      // which do not bubble and are invisible to window.onerror.
      var target = event.target;
      if (target && target !== window && (target.src || target.href)) {
        log("FAIL", "resource failed to load: " + (target.src || target.href));
        log("HINT", "A <" + String(target.tagName).toLowerCase() + "> tag could " +
          "not be fetched. If it is optional the app may still run.");
        return;
      }
      log(
        "FAIL",
        "uncaught error: " + (event.message || "(no message)") +
          (event.filename ? "  at " + event.filename + ":" + event.lineno + ":" + event.colno : ""),
        event.error && event.error.stack
      );
    },
    true
  );

  window.addEventListener("unhandledrejection", function (event) {
    var reason = event.reason;
    var message =
      (reason && (reason.message || reason.toString())) || "(no reason given)";
    log("FAIL", "unhandled promise rejection: " + message, reason && reason.stack);
    if (String(message).indexOf("Failed to fetch") >= 0) {
      log(
        "HINT",
        "The failing URL is the most recent GET above without a matching OK line."
      );
    }
  });

  /* --------------------------------------------------------------- start */

  log("BOOT", "diagnostics installed");
  log("ENV", "page: " + location.href);
  log("ENV", "agent: " + navigator.userAgent);
  log(
    "ENV",
    "wasm: " + (typeof WebAssembly !== "undefined") +
      "   crossOriginIsolated: " +
      (typeof crossOriginIsolated !== "undefined" ? crossOriginIsolated : "n/a") +
      "   SharedArrayBuffer: " + (typeof SharedArrayBuffer !== "undefined")
  );

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      build();
      log("BOOT", "DOM ready");
    });
  } else {
    build();
  }

  window.addEventListener("load", function () {
    log("BOOT", "window load event fired");
  });

  // If the canvas never becomes visible, the runtime did not finish booting.
  // Say so plainly rather than leaving a blank page.
  setTimeout(function () {
    var canvas = document.getElementById("canvas");
    var visible = canvas && canvas.style.visibility === "visible";
    if (!visible) {
      log(
        "WARN",
        "30s elapsed and the game canvas is still not visible - the runtime " +
          "has not finished booting. The last GET without a matching OK is the " +
          "stall point."
      );
      show();
    }
  }, 30000);
})();
