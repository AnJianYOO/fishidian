// 给窗口里那个「连 QQ」按钮供图的小服务。
// 只做一件事：把 NapCat 写在本地的登录二维码读出来，用 HTTP 给渲染进程。
// 不碰桥、不碰记忆库、不写任何文件。
const http = require("http");
const fs = require("fs");
const path = require("path");
const os = require("os");
const { execFile } = require("child_process");

// 用户目录：优先用环境变量，没有就取系统 home。绝不写死任何一台机器的路径。
const USER_HOME = process.env.USERPROFILE || os.homedir();

const PORT = 8799;
const QR = path.join(
  USER_HOME,
  "NapCat",
  "cache",
  "qrcode.png"
);

const server = http.createServer((req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Cache-Control", "no-store");

  // 跨域 POST 会先发一次预检，不答它浏览器就把请求掐了。
  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    });
    res.end();
    return;
  }

  if (req.url && req.url.startsWith("/qr")) {
    try {
      const buf = fs.readFileSync(QR);
      res.writeHead(200, {
        "Content-Type": "image/png",
        "Content-Length": buf.length,
      });
      res.end(buf);
    } catch (e) {
      res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
      res.end("qrcode not ready");
    }
    return;
  }

  // 首启配置：安装时问过的称呼、QQ 号、白名单。
  // 渲染进程读不了文件，所以从这里读出去给窗口里的新手指引用。
  if (req.url === "/setup") {
    const roots = [
      path.join(process.env.USERPROFILE || os.homedir(), "fishidian", "config", "setup.json"),
      path.join(process.env.USERPROFILE || os.homedir(), "大肥鱼", "config", "setup.json"),
      path.join(process.env.USERPROFILE || os.homedir(), ".dsh-fatfish", "config", "setup.json"),
    ];
    let body = null;
    for (const p of roots) {
      try {
        body = fs.readFileSync(p, "utf8");
        break;
      } catch (e) {}
    }
    res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
    res.end(body || JSON.stringify({ onboarded: true, nickname: "", botQq: "", allowUsers: [] }));
    return;
  }

  // 新手指引答完写回来。只写 config\setup.json，不碰记忆库。
  if (req.method === "POST" && req.url === "/save") {
    let body = "";
    req.on("data", (d) => { body += d; });
    req.on("end", () => {
      try {
        const incoming = JSON.parse(body || "{}");
        // 三段目录优先级：新布局 fishidian\ > 老布局 大肥鱼\ > 最早 .dsh-fatfish\
        // 写成"哪个存在用哪个"而不是硬编码一个，是为了同一份脚本在
        // 新装机器 / 这台开发机 上都能跑出正确结果。
        const inst = path.join(process.env.USERPROFILE || os.homedir(), "fishidian", "config");
        const home = path.join(process.env.USERPROFILE || os.homedir(), "大肥鱼", "config");
        const fallback = path.join(process.env.USERPROFILE || os.homedir(), ".dsh-fatfish", "config");
        let target = fallback;
        if (fs.existsSync(inst)) { target = inst; }
        else if (fs.existsSync(home)) { target = home; }
        const file = path.join(target, "setup.json");
        let cur = {};
        try { cur = JSON.parse(fs.readFileSync(file, "utf8")); } catch (e) {}
        const merged = Object.assign({}, cur, incoming, { onboarded: true });
        fs.mkdirSync(target, { recursive: true });
        fs.writeFileSync(file, JSON.stringify(merged, null, 2), "utf8");
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ok: true, savedTo: file }));
      } catch (e) {
        res.writeHead(500, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ok: false, error: String(e && e.message) }));
      }
    });
    return;
  }

  // 要不要出二维码 / 是不是已经连上了。
  //
  // 判据为什么不是"文件两分钟内更新过"：登录成功以后 NapCat 就不再写 qrcode.png 了，
  // 用文件年龄判会得出"刚登录成功 = 需要扫码"的荒谬结论（两分钟后 ageSec 一大又提示扫）。
  //
  // 真正硬的证据是 6700 上有没有 ESTABLISHED —— 桥在 6700 监听，NapCat 登录后作为
  // 反向 ws 客户端连上来。有连接 = 已登录。netstat 一次约几十毫秒，加 2 秒缓存。
  let onlineCache = { at: 0, val: false };
  // 本次启动以来有没有连上过。桥是 DSH 插件，窗口起来后还要几秒才监听，
  // NapCat 的反向重连又有间隔——所以"此刻没连上"和"从来没连上"必须分开。
  // 只要连上过一次，之后短暂断开也不该再弹二维码。
  let everOnline = false;
  function bridgeOnline(cb) {
    const now = Date.now();
    if (now - onlineCache.at < 2000) {
      if (onlineCache.val) everOnline = true;
      return cb(onlineCache.val);
    }
    execFile("netstat", ["-ano", "-p", "TCP"], { timeout: 3000 }, (err, stdout) => {
      let val = false;
      if (!err && stdout) {
        const lines = String(stdout).split(/\r?\n/);
        for (const ln of lines) {
          if (ln.indexOf(":6700") === -1) continue;
          if (ln.toUpperCase().indexOf("ESTABLISHED") === -1) continue;
          val = true;
          break;
        }
      }
      if (val) everOnline = true;
      onlineCache = { at: Date.now(), val };
      cb(val);
    });
  }

  if (req.url === "/qqstatus") {
    bridgeOnline((online) => {
      let ageSec = -1;
      let hasQR = false;
      let mtime = 0;
      try {
        const st = fs.statSync(QR);
        ageSec = Math.round((Date.now() - st.mtimeMs) / 1000);
        hasQR = st.size > 100;
        mtime = Math.round(st.mtimeMs);
      } catch (e) {}
      res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({
        online: !!online,
        everOnline: !!everOnline,
        needQR: !(online || everOnline),
        hasQR,
        staleQR: hasQR && ageSec > 180,
        ageSec,
        mtime,
      }));
    });
    return;
  }

  if (req.url === "/status") {
    let ok = false;
    let mtime = 0;
    try {
      const st = fs.statSync(QR);
      ok = st.size > 100;
      mtime = st.mtimeMs;
    } catch (e) {}
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok, mtime }));
    return;
  }

  res.writeHead(404);
  res.end();
});

server.listen(PORT, "127.0.0.1");
