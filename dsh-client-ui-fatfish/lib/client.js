/**
 * 小鱼界面插件 —— 浏览器侧。
 *
 * 做两件事：
 * 1) 接管左侧栏品牌位（图标 + 名字），换成粉色小鱼 +「小鱼」。
 * 2) 把窗口收成「只有对话」的样子：导航列自动折叠成细条、右栏关掉。
 *    她的窗口不需要工作区列表、会话列表、对话摘要那一套。
 *
 * 与 DSH 官方 dsh-client-ui-brand-official 同构：inject "slots"，
 * 通过 ctx.slots.register 覆盖 sidebar.brand.mark / sidebar.brand.name。
 * 收栏逻辑走 ui-layout 暴露的 ctx.layout 服务（toggleSidebar / closeRightbar）。
 */
window.__ModuleLoader__.load({
  id: "dsh-client-ui-fatfish",
  factory: function (require) {
    var module = { exports: {} };

    var jsxRuntime = require("react/jsx-runtime");
    var jsx = jsxRuntime.jsx;
    var jsxs = jsxRuntime.jsxs;

    function FishMark(props) {
      var size = (props && props.size) || 18;
      return jsx("svg", {
        width: size,
        height: size,
        viewBox: "0 0 24 24",
        "aria-hidden": "true",
        style: { display: "block" },
        children: jsxs("g", {
          children: [
            jsx("ellipse", {
              cx: 9.6,
              cy: 12,
              rx: 6.6,
              ry: 4.9,
              fill: "#F5A9BC",
            }),
            jsx("polygon", {
              points: "15.8,12 22.4,7.6 22.4,16.4",
              fill: "#E8798C",
            }),
            jsx("circle", {
              cx: 6.4,
              cy: 10.6,
              r: 1.05,
              fill: "#3A2430",
            }),
            jsx("path", {
              d: "M8.9 14.1c1.1 1.1 2.6 1.1 3.7 0",
              stroke: "#3A2430",
              strokeWidth: 1,
              fill: "none",
            }),
          ],
        }),
      });
    }

    function FishName(props) {
      return jsx("span", {
        style: { fontWeight: 600, letterSpacing: "0.02em" },
        children: "小鱼",
      });
    }

    // ---- 连 QQ：扫码登录浮层 ----
    // NapCat 把登录二维码写在 cache\qrcode.png。
    // 渲染进程读不了本地文件（fs 和 file:// 都被拦），所以由 tools\qq-qrcode-server.js
    // 开一个 127.0.0.1:8799 的小服务把图吐出来。
    var QR_URL = "http://127.0.0.1:8799/qr?t=";

    function readQR() {
      return QR_URL + Date.now();
    }

    function openQQPanel() {
      var old = document.getElementById("fatfish-qq-mask");
      if (old) old.remove();

      var mask = document.createElement("div");
      mask.id = "fatfish-qq-mask";
      mask.style.cssText =
        "position:fixed;inset:0;z-index:2147483600;background:rgba(20,12,18,.5);" +
        "display:flex;align-items:center;justify-content:center;";

      var box = document.createElement("div");
      box.style.cssText =
        "width:320px;background:#fff;border-radius:18px;padding:24px 22px 18px;text-align:center;" +
        "box-shadow:0 20px 60px rgba(0,0,0,.25);" +
        "font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;";
      box.innerHTML =
        '<div id="fatfish-qq-title" style="font-size:16px;font-weight:600;color:#3A2430;margin-bottom:4px">连上 QQ</div>' +
        '<div id="fatfish-qq-sub" style="font-size:12px;color:#9A8A92;margin-bottom:8px">用单独的小号扫码，扫完用自己的号加她好友</div>' +
        '<div style="font-size:11px;color:#C2415C;line-height:1.6;margin:0 0 12px">⚠️ 请用单独注册的小号，别用你平时聊天的主号——QQ 会风控，主号有封号风险</div>' +
        '<div id="fatfish-qq-imgwrap" style="width:248px;height:248px;margin:0 auto;border-radius:12px;' +
        'background:#FBF7F9;display:flex;align-items:center;justify-content:center;overflow:hidden"></div>' +
        '<div id="fatfish-qq-tip" style="font-size:12px;color:#9A8A92;margin-top:12px;line-height:1.7"></div>' +
        '<div style="margin-top:16px;display:flex;gap:10px;justify-content:center">' +
        '<button id="fatfish-qq-refresh" style="padding:9px 18px;border-radius:10px;border:1px solid #EAD9DF;' +
        'background:#fff;color:#6B4A56;font-size:13px;cursor:pointer">刷新</button>' +
        '<button id="fatfish-qq-close" style="padding:9px 18px;border-radius:10px;border:0;background:#F5A9BC;' +
        'color:#4A2130;font-size:13px;font-weight:600;cursor:pointer">关闭</button></div>';

      var imgwrap = box.querySelector("#fatfish-qq-imgwrap");
      var tip = box.querySelector("#fatfish-qq-tip");
      var title = box.querySelector("#fatfish-qq-title");
      var sub = box.querySelector("#fatfish-qq-sub");
      var lastMtime = 0;
      var closed = false;
      var timer = null;

      function paintQR() {
        imgwrap.innerHTML = "";
        var img = document.createElement("img");
        img.style.cssText = "width:100%;height:100%;object-fit:contain;display:block;";
        img.onerror = function () {
          imgwrap.innerHTML =
            '<div style="font-size:12px;color:#B9A6AE;padding:0 24px;line-height:1.9">' +
            '二维码还没读出来<br>等几秒，或者点刷新</div>';
        };
        img.src = readQR();
        imgwrap.appendChild(img);
      }

      function stopPoll() {
        if (timer) { clearInterval(timer); timer = null; }
      }

      // 扫完以后不用等用户点任何东西：这里自己轮询，认出来就换成功态并自动关。
      function showSuccess() {
        closed = true;
        stopPoll();
        if (!mask.parentNode) return;
        title.textContent = "连上了";
        title.style.color = "#8A3F58";
        sub.textContent = "现在用你自己的 QQ 加这个小号，就能跟她聊了";
        imgwrap.innerHTML =
          '<div style="font-size:26px;font-weight:600;color:#8A3F58;letter-spacing:2px">已连接</div>';
        tip.textContent = "这个框马上会自己关掉。";
        var rf = box.querySelector("#fatfish-qq-refresh");
        if (rf) rf.style.display = "none";
        setTimeout(function () {
          if (mask.parentNode) mask.remove();
        }, 1800);
      }

      function tick() {
        if (closed) return;
        fetch("http://127.0.0.1:8799/qqstatus")
          .then(function (r) { return r.json(); })
          .then(function (s) {
            if (closed || !s) return;
            if (s.online === true) { showSuccess(); return; }
            // 有码就画出来，不管新不新。原来只有"新码"才画，旧码分支只留一句提示，
            // 结果是个空框——用户以为坏了他还得自己点刷新。
            if (s.hasQR) {
              if (s.mtime && s.mtime !== lastMtime) {
                lastMtime = s.mtime;
                paintQR();
              }
              tip.textContent = s.staleQR
                ? "这是上一次的码。要是已经登录过，这个框会自己关。"
                : "扫完等几秒，这里会自己认出来，不用你点。";
            } else {
              imgwrap.innerHTML =
                '<div style="font-size:12px;color:#B9A6AE;padding:0 24px;line-height:1.9">' +
                '二维码还没出来<br>正在把 QQ 拉起来，等几秒</div>';
              tip.textContent = "第一次启动要等一会儿，之后就快了。";
            }
          })
          .catch(function () {});
      }

      box.addEventListener("click", function (e) { e.stopPropagation(); });
      mask.addEventListener("click", function () { closed = true; stopPoll(); mask.remove(); });
      box.querySelector("#fatfish-qq-refresh").addEventListener("click", function () {
        lastMtime = 0;
        paintQR();
        tick();
      });
      box.querySelector("#fatfish-qq-close").addEventListener("click", function () {
        closed = true;
        stopPoll();
        mask.remove();
      });

      mask.appendChild(box);
      document.body.appendChild(mask);
      tick();
      timer = setInterval(tick, 1500);
    }

    // 新手指引：装完第一次打开，她先开口问两件事，确认完才继续。
    // 配置从本地小服务读（渲染进程读不了文件），答完写回去。
    function bootFlow() {
      fetch("http://127.0.0.1:8799/setup")
        .then(function (r) { return r.json(); })
        .then(function (cfg) {
          if (cfg && cfg.onboarded === false) {
            showOnboard(cfg, afterOnboard);
          } else {
            afterOnboard();
          }
        })
        .catch(function () { afterOnboard(); });
    }

    // 引导之后：只有真的要她扫码时才弹二维码。
    //
    // 不能只查一次。窗口刚起来时桥（6700）还没监听、NapCat 还没来得及反向连上来，
    // 这一瞬间 online 一定是 false。查一次就判定，会在"其实早就登录了"的情况下弹框，
    // 而框里只有半分钟前那张旧码 —— 就是用户看到的"空了十秒还得自己点刷新"。
    //
    // 规则：有新码就立刻弹（首次安装正是这个场景）；只有旧码或还没码，就多等几次，
    // 让连接自己建立起来。
    function afterOnboard() {
      try {
        if (sessionStorage.getItem("fatfish-qq-auto") === "1") return;
      } catch (e) { return; }

      var tries = 0;
      // 60 秒。冷启动这一段不是"几秒"：窗口起来后 1.2 秒才弹 UAC，用户点"是"还要花时间；
      // NapCat 起来后要注入 QQ、生成码、再反向连 6700，桥也得先加载完插件才开始监听。
      // 实战里从窗口出现到出现 ESTABLISHED 常常二十几秒，慢的更久。
      // 等待期间界面是干净空的（根本没弹框），所以等久没有代价；早弹才有代价。
      var MAX = 30;

      function openOnce() {
        try { sessionStorage.setItem("fatfish-qq-auto", "1"); } catch (e) {}
        openQQPanel();
      }

      function probe() {
        tries++;
        fetch("http://127.0.0.1:8799/qqstatus")
          .then(function (r) { return r.json(); })
          .then(function (s) {
            if (!s) return;
            // everOnline = 这次开机以来连上过。桥和 NapCat 重连要二十几秒，
            // 只看当下这一刻会误判成"从来没连上"。
            if (s.online === true || s.everOnline === true) return;
            if (s.hasQR && !s.staleQR) { openOnce(); return; }
            if (tries >= MAX) { openOnce(); return; }
            setTimeout(probe, 2000);
          })
          .catch(function () {
            if (tries < MAX) setTimeout(probe, 2000);
          });
      }

      probe();
    }

    function showOnboard(cfg, done) {
      var nick = (cfg && cfg.nickname) || "朋友";
      var mask = document.createElement("div");
      mask.style.cssText = "position:fixed;inset:0;z-index:2147483200;background:rgba(24,18,20,.55);display:flex;align-items:center;justify-content:center;";
      var card = document.createElement("div");
      card.style.cssText = "width:340px;background:#fff9f7;border-radius:16px;padding:24px;box-shadow:0 18px 50px rgba(0,0,0,.22);font-size:13px;color:#3a2f33;font-family:system-ui,'Microsoft YaHei';";
      card.innerHTML =
        '<div style="font-size:16px;font-weight:600;margin-bottom:10px;">你好，' + nick + '。</div>' +
        '<div style="line-height:1.75;margin-bottom:8px;">我是小鱼，从今天起就住在这台电脑里了。</div>' +
        '<div style="font-size:12px;color:#8a7a80;line-height:1.65;margin-bottom:16px;">我先住在一个 QQ 小号里（不是你平时用的号）。等你想在手机上找我，用自己的 QQ 加那个小号就行。</div>' +
        '<div style="margin-bottom:16px;">' +
          '<div style="color:#8a7a80;margin-bottom:8px;line-height:1.6;">我以后想找你的时候，能给你发消息嘛？</div>' +
          '<div style="display:flex;gap:8px;">' +
            '<div data-k="proactive" data-v="yes" style="flex:1;text-align:center;padding:9px;border-radius:9px;border:1px solid #f0d5dc;cursor:pointer;background:#fff;">当然可以</div>' +
            '<div data-k="proactive" data-v="no" style="flex:1;text-align:center;padding:9px;border-radius:9px;border:1px solid #f0d5dc;cursor:pointer;background:#fff;">我先说话就好</div>' +
          '</div>' +
        '</div>' +
        '<div style="margin-bottom:18px;">' +
          '<div style="color:#8a7a80;margin-bottom:8px;line-height:1.6;">还有，电脑开机以后，我自己起来还是等你叫我？</div>' +
          '<div style="display:flex;gap:8px;">' +
            '<div data-k="autostart" data-v="yes" style="flex:1;text-align:center;padding:9px;border-radius:9px;border:1px solid #f0d5dc;cursor:pointer;background:#fff;">我自己起来</div>' +
            '<div data-k="autostart" data-v="no" style="flex:1;text-align:center;padding:9px;border-radius:9px;border:1px solid #f0d5dc;cursor:pointer;background:#fff;">等你叫我</div>' +
          '</div>' +
        '</div>' +
        '<div style="font-size:12px;color:#a08f95;line-height:1.6;margin-bottom:14px;">我们说过的话都存在这台电脑的记忆文件夹里，那个文件夹你可以整个备份。</div>' +
        '<div id="ff-onb-ok" style="text-align:center;padding:9px;border-radius:9px;background:#e8899f;color:#fff;cursor:pointer;">好了</div>';
      mask.appendChild(card);
      document.body.appendChild(mask);

      var picked = {};
      var cells = card.querySelectorAll("[data-k]");
      for (var i = 0; i < cells.length; i++) {
        (function (cell) {
          cell.addEventListener("click", function () {
            var k = cell.getAttribute("data-k");
            picked[k] = cell.getAttribute("data-v");
            var siblings = card.querySelectorAll('[data-k="' + k + '"]');
            for (var j = 0; j < siblings.length; j++) {
              siblings[j].style.background = "#fff";
              siblings[j].style.color = "#3a2f33";
              siblings[j].style.borderColor = "#f0d5dc";
            }
            cell.style.background = "#fde8ed";
            cell.style.color = "#c2415c";
            cell.style.borderColor = "#e8899f";
          });
        })(cells[i]);
      }

      var ok = card.querySelector("#ff-onb-ok");
      ok.addEventListener("click", function () {
        mask.remove();
        try {
          fetch("http://127.0.0.1:8799/save", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ onboarded: true, answers: picked })
          }).catch(function () {});
        } catch (e) {}
        if (typeof done === "function") setTimeout(done, 200);
      });
    }

    function mountQQButton() {
      if (document.getElementById("fatfish-qq-btn")) return;
      var btn = document.createElement("div");
      btn.id = "fatfish-qq-btn";
      btn.textContent = "连 QQ";
      btn.style.cssText =
        "position:fixed;right:22px;bottom:92px;z-index:2147483000;padding:9px 16px;border-radius:999px;" +
        "background:#F5A9BC;color:#4A2130;font-size:13px;font-weight:600;letter-spacing:.02em;" +
        "cursor:pointer;user-select:none;border:1px solid rgba(232,121,140,.55);" +
        "box-shadow:0 6px 18px rgba(232,121,140,.35);" +
        "font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;";
      btn.addEventListener("click", openQQPanel);
      document.body.appendChild(btn);
    }

    var inject = ["slots", "layout"];

    function apply(ctx) {
      ctx.slots.inject("sidebar.brand.mark", function () {
        return ctx.slots.inject("sidebar.brand.name", function* () {
          yield ctx.slots.register({ name: "sidebar.brand.mark" }, FishMark);
          yield ctx.slots.register({ name: "sidebar.brand.name" }, FishName);
        });
      });

      // 窗口标题 / 任务栏名字也叫「小鱼」，折叠状态下也能一眼认出来。
      // DSH 会在切换会话时重设 <title>，所以用观察器把它按住。
      try {
        document.title = "小鱼";
        var titleNode = document.querySelector("title");
        if (titleNode && window.MutationObserver) {
          var mo = new MutationObserver(function () {
            if (document.title !== "小鱼") document.title = "小鱼";
          });
          mo.observe(titleNode, { childList: true, characterData: true, subtree: true });
        }
      } catch (e) {}

      // 她的窗口只留对话区：折叠导航列 + 关掉右栏。
      // 布局状态每次重载都会回到默认（导航列展开、右栏隐藏），所以这里只在
      // 检测到「导航列还展开」时切一次，避免把用户手动收好的又弹开。
      if (window.__fatfishCalmWindow) {
        mountQQButton();
        return;
      }
      window.__fatfishCalmWindow = true;
      setTimeout(mountQQButton, 500);
      // 打开窗口时主动弹一次二维码：重启电脑后不用自己找入口。
      // 本次会话只弹一次，关掉就不再打扰。
      // 启动流程：先看她是不是第一次来（引导），确认完再决定要不要出二维码。
      // 二维码只在「还没连上 QQ」时才弹，连上了就不打扰。
      setTimeout(bootFlow, 2200);

      setTimeout(function () {
        try {
          var layout = ctx.layout;
          if (!layout && ctx.get) layout = ctx.get("layout");
          if (!layout) return;

          if (typeof layout.closeRightbar === "function") {
            layout.closeRightbar();
          }

          // Windows 桌面折叠后会把 --dsh-windows-menu-start 设为 84px，展开时是 48px
          var start = "";
          try {
            start = getComputedStyle(document.documentElement)
              .getPropertyValue("--dsh-windows-menu-start")
              .trim();
          } catch (e) {}
          if (start !== "84px" && typeof layout.toggleSidebar === "function") {
            layout.toggleSidebar();
          }
        } catch (e) {}
      }, 1600);
    }

    module.exports.apply = apply;
    module.exports.inject = inject;
    return module.exports;
  },
});
