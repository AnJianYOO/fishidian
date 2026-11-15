// dsh-fishidian —— 大肥鱼情感记忆经络系统（DSH 插件宿主半侧）
//
// 架构：TS/JS 薄壳 + 本地 Python 内核（fishidian-core，见 package.json 旁目录）。
// 子进程调用（spawnSync python cli.py），零常驻进程、无端口。
//
// 三条红线（不允许退化）：
//  1) 召回≠强化：注入只读，adopt 只有 observe_turn 里的内核判定会涨 R。
//  2) 注入不覆盖人格：记忆块带 fishidian:memory marker，只作上下文参考。
//  3) 群聊不注入私聊记忆：由内核 ns + visibility 过滤保证。
//
// 环境变量可覆盖：
//  FISHIDIAN_PYTHON  python 命令（默认 "python"）
//  FISHIDIAN_CORE    fishidian-core 目录（默认：从本文件逐级向上找；找不到时读 ~/.dsh/fishidian-core-path.txt）
//  FISHIDIAN_DB_DIR  记忆库目录（默认 ~/.dsh/fishidian-memory）

import { spawn, spawnSync } from "node:child_process";
import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { existsSync, appendFileSync, readdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join, dirname, basename } from "node:path";
import { createTurnMerger } from "./turn-merge.js";
import { fileURLToPath } from "node:url";

export const name = "dsh-fishidian";
export const inject = ["commands"];

const PYTHON = process.env.FISHIDIAN_PYTHON ?? "python";

/**
 * 内核目录。四级查找，让"装到别人电脑"和"开发机"共用同一份代码：
 *   ① FISHIDIAN_CORE 环境变量（最高优先，排查时能临时指走；安装器的 launch.ps1 会设）
 *   ② 从本文件所在目录逐级向上，找第一个含 fishidian-core\cli.py 的目录
 *      —— 不做固定层数假设：装成 link: 时 _HERE 可能是
 *         <根>\<包名>\lib，也可能被 pnpm 摆成 <根>\data\profiles\desktop\node_modules\<包名>\lib。
 *         原来写死 "..\..\" 只对前者成立，后者会一路落空到 ③。
 *   ③ 开发机的 D 盘路径（只有本机开发时才命中）
 *
 * 为什么原来那版是隐患：node_modules 布局下 sibling 算出来是
 * node_modules\fishidian-core（不存在），于是直接返回 ③ 的 D 盘路径 ——
 * 换到别人电脑上 cli.py 不存在，spawnSync 静默失败，表现为"她失忆了"但没有任何报错。
 */
const _HERE = dirname(fileURLToPath(import.meta.url));
const _CORE_OVERRIDE = join(homedir(), ".dsh", "fishidian-core-path.txt");
function _resolveCore() {
  if (process.env.FISHIDIAN_CORE) return process.env.FISHIDIAN_CORE;
  let d = _HERE;
  for (let i = 0; i < 8; i++) {
    const cand = join(d, "fishidian-core");
    try {
      if (existsSync(join(cand, "cli.py"))) return cand;
    } catch {}
    const up = dirname(d);
    if (up === d) break;
    d = up;
  }
  // ③ 本机覆盖文件：开发机上内核不在安装根里时用。这个文件不进仓库。
  try {
    const p = readFileSync(_CORE_OVERRIDE, "utf8").trim();
    if (p && existsSync(join(p, "cli.py"))) return p;
  } catch {}
  return null;
}
const CORE_DIR = _resolveCore();
// 记忆库，三种来源，从最具体到最宽：
//   ① FISHIDIAN_DB 完整文件路径（安装器的 launch.ps1 显式指定，名字锁定 dfy.db）
//   ② FISHIDIAN_DB_DIR 目录 + 固定文件名 fishidian.db
//   ③ 默认 ~/.dsh/fishidian-memory/fishidian.db
// ② ③ 时才走旧库兼容（仅未显式设置时）：新库不存在且旧库
// （dafeiyu-memory/dfy.db）存在，沿用旧库避免丢记忆。
//
// 为什么补 ①：原来只有 ②③，安装器把库放到 <安装根>\workspace\memory\dfy.db 这件事
// 靠的是 ③ 的 legacy 巧合命中（开发机上恰好有 dafeiyu-memory/dfy.db）。
// 干净机器上没有那个旧库，库会静默建到 ~/.dsh\fishidian-memory\fishidian.db ——
// 和文档写的路径不一致，用户按验收清单看 workspace\memory\dfy.db 永远不增长。
function dbPath() {
  if (process.env.FISHIDIAN_DB) return process.env.FISHIDIAN_DB;
  const dir = process.env.FISHIDIAN_DB_DIR ?? join(homedir(), ".dsh", "fishidian-memory");
  const p = join(dir, "fishidian.db");
  if (!process.env.FISHIDIAN_DB_DIR) {
    const legacy = join(join(homedir(), ".dsh", "dafeiyu-memory"), "dfy.db");
    try {
      if (!existsSync(p) && existsSync(legacy)) return legacy;
    } catch {}
  }
  return p;
}
const DB_PATH = dbPath();

/** 调内核 CLI；治理层异常 → 返回 {error}，调用方降级为无记忆回复（不阻塞聊天）。 */
function fishidian(ns, cmd, ...args) {
  if (!CORE_DIR) {
    return { error: `内核目录没找到。设 FISHIDIAN_CORE，或在 ${_CORE_OVERRIDE} 里写一行绝对路径` };
  }
  const r = spawnSync(PYTHON, [join(CORE_DIR, "cli.py"), ns, DB_PATH, cmd, ...args], {
    encoding: "utf8",
    timeout: 30000,
    maxBuffer: 16 * 1024 * 1024,
    windowsHide: true,
  });
  if (r.error) return { error: String(r.error) };
  if (r.status !== 0) return { error: (r.stderr || r.stdout || "").slice(0, 800) };
  try {
    return JSON.parse(r.stdout);
  } catch {
    return { error: "bad json: " + (r.stdout || "").slice(0, 800) };
  }
}

/**
 * 异步跑一个外部命令，主线程不阻塞。
 *
 * 为什么需要它：`spawnSync` 单次实测约 213 ms（python 启动占大头）。
 * 三个定时器 sweep(10min)/vault(15min)/backup(24h)/proactive(1h) 在整点会撞车，
 * 那一下如果正好有 QQ 消息进来，回复就会慢半拍。
 * **聊天路径仍然走同步的 fishidian()**：那里需要顺序和返回值；
 * 定时器只是"巡检/快照"，谁先跑完都不影响对方，没有阻塞的必要。
 */
// 日志时间戳用**本地时间**：原先用 toISOString()，写出来是 UTC，
// 比本地早 8~9 小时，看心跳日志得自己换算（"怎么才早上 8 点"实际是下午 5 点）。
const localStamp = () => {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
         `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
};
function runAsync(exe, args, opts = {}, onDone = null, timeoutMs = 60000) {  let finished = false;
  const finish = (res) => {
    if (finished) return;
    finished = true;
    try { if (onDone) onDone(res); } catch {}
  };
  let p;
  try {
    p = spawn(exe, args, { windowsHide: true, cwd: opts.cwd });
  } catch (e) {
    finish({ error: String(e), status: null, stdout: "", stderr: "" });
    return null;
  }
  let out = "", err = "";
  p.stdout?.on("data", (d) => { if (out.length < 2000000) out += d; });
  p.stderr?.on("data", (d) => { if (err.length < 2000000) err += d; });
  const t = setTimeout(() => {
    try { p.kill(); } catch {}
    finish({ error: "timeout", status: null, stdout: out, stderr: err });
  }, timeoutMs);
  p.on("error", (e) => { clearTimeout(t); finish({ error: String(e), status: null, stdout: out, stderr: err }); });
  p.on("close", (code) => {
    clearTimeout(t);
    finish({ error: code === 0 ? null : "exit " + code, status: code, stdout: out, stderr: err });
  });
  return p;
}

/** 异步版内核 CLI：解析 JSON 后交给回调。 */
function fishidianAsync(ns, cmd, args = [], onDone = null) {
  return runAsync(PYTHON, [join(CORE_DIR, "cli.py"), ns, DB_PATH, cmd, ...args],
    {}, (res) => {
      if (res.error) return onDone && onDone({ error: res.error });
      try {
        onDone && onDone(JSON.parse(res.stdout));
      } catch {
        onDone && onDone({ error: "bad json: " + (res.stdout || "").slice(0, 800) });
      }
    }, 30000);
}

// R30：出站脱敏（与内核 fishidian_core/mask.py 同口径）。
// 库里存原文、注入只发脱敏后的文本 —— 泄漏点是"每轮原文随 prompt 一起发到云端"。
// 内核 context 已经脱过一遍；这里管的是 context 失败时走的 export 兜底路径。
function maskText(t) {
  let s = String(t || "");
  // 身份证先做（18 位数字，否则会被后面的银行卡规则吃掉）
  s = s.replace(/(?<!\d)(\d{6})(\d{8})(\d{3}[\dXx])(?!\d)/g, "$1******$3");
  s = s.replace(/(?<!\d)(1[3-9]\d{9})(?!\d)/g, (m) => m.slice(0, 3) + "****" + m.slice(7));
  s = s.replace(/(?<!\d)(\d{12,19})(?!\d)/g, (m) => "尾号" + m.slice(-4));
  s = s.replace(/([A-Za-z0-9._%+-]{1,64})@([A-Za-z0-9.-]{1,64}\.[A-Za-z]{2,8})/g,
    (_m, u, d) => (u.length > 1 ? u.slice(0, 1) : "") + "***@" + d);
  s = s.replace(/((?:\d{1,5}(?:号|栋|幢|单元|室|楼|层)|\d{1,5}[路街道巷])){2,}/g, "某地址");
  return s;
}

function textOf(data) {
  if (typeof data === "string") return data;
  if (!data || typeof data !== "object") return "";
  // DSH 真实格式：user/message 的 data 即 message；assistant/system/developer 包一层 { message }。
  const msg =
    data.message && typeof data.message === "object" && (data.message.role || Array.isArray(data.message.content))
      ? data.message
      : data;
  const c = msg.content;
  if (typeof c === "string") return c;
  if (Array.isArray(c)) {
    return c
      .map((b) => {
        if (typeof b === "string") return b;
        if (b && typeof b.text === "string") return b.text;
        return "";
      })
      .filter(Boolean)
      .join("\n");
  }
  return "";
}

function latestUserText(messages) {
  if (!Array.isArray(messages)) return "";
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m && m.role === "user") {
      const t = textOf(m);
      if (t.length > 0) return t;
    }
  }
  return "";
}

// 判断这条用户消息是否在聊"天气/冷暖/穿衣/出门"——天气行只在这时才注入。
// （每轮无条件注入天气会让她天天拿天气当话题，像个播报机器人。）
const WEATHER_RE = /天气|冷不冷|暖不暖|热不热|冷|热|穿|伞|下雨|下雪|晴|阴|出门|降温|气温|几度/;

export function apply(ctx, config) {
  const ns = (config && config.ns) || "dsh:default";
  ctx.logger?.info?.("[fishidian] plugin loaded ns=" + ns);

  // ---- 每个 agent 挂注入与回写 ----
  // 注意：agent/created 事件的实参是 { agent, source, signal }，必须取 arg.agent。
  const attach = (arg) => {
    const agent = arg?.agent ?? arg;
    const ac = agent?.ctx;
    if (!ac) return;
    // 本 session 最近一条真实用户消息（供注入时判断"这轮是不是在聊天气"）
    let lastUserMsg = "";

    // 注入（不动地基）：注册动态 runtime context，由宿主每轮 assemble 安全并入 system prompt。
    // 这是 DSH 官方扩展口（桥 qq-persistent-memory、file-reference 等都用 systemPrompt.*），
    // 宿主把该 context 投影为一条 context 消息追加，绝不碰 decision.messages，因此不会崩。
    // text 用函数 → 每轮动态求值，把当前记忆快照并进提示词。
    try {
      ac.inject(["systemPrompt"], (scope) =>
        scope.systemPrompt.context({
          name: "fishidian-memory",
          order: 130,
          text: () => {
            try {
              // 单次 context（P0-1 / P0-3 / E2）：内核一次返回 分层记忆（身份 3 常驻 +
              // 按这句话召回 4 + 最近 2 兜底）+ 置信三档（身份/经历/存疑）+ 状态 + 时间 + 表达 hint。
              // 顺带省掉 export / state / time / expression 四次子进程。
              const cx = fishidian(ns, "context", lastUserMsg || "",
                                   WEATHER_RE.test(lastUserMsg || "") ? "1" : "0");
              if (cx && !cx.error && cx.injection) {
                lastInjectedIds = Array.isArray(cx.items)
                  ? cx.items.map((m) => String(m.id)).filter(Boolean)
                  : [];
                const exprLine = cx.expr_hint
                  ? "表达：说话按以下倾向来——" + cx.expr_hint +
                    " 另外，镜像我这条消息的长短和情绪（短对短、长对长、emoji 对 emoji）；" +
                    "别写总结、别列点、别用“首先/其次/总之”、别端着、别一条回复把话全说完。"
                  : "";
                return cx.injection + (exprLine ? "\n" + exprLine : "");
              }
            } catch {}
            try {
              const r = fishidian(ns, "export");
              let mems = (r && Array.isArray(r.memories) ? r.memories : [])
                .filter((m) => {
                  const t = (m && m.text) || "";
                  if (!t) return false;
                  if (m.status !== "active") return false;
                  if (m.visibility && m.visibility !== "private") return false;
                  if (t.startsWith("Current runtime context")) return false;
                  if (t.startsWith("Time sampled")) return false;
                  if (t.startsWith("The working directory changed")) return false;
                  if (t.startsWith("A skill is a reusable")) return false;
                  if (t.includes("<system-reminder>") || t.includes("<available_skills>")) return false;
                  if (t.includes("fishidian:memory")) return false;
                  return true;
                });
              // 记忆混排：export 按 R 降序，只取前 12 条会让"重要旧记忆"永远霸屏、刚聊的（R 低）进不来
              // ——她会记得八百年前的事、忘了你十分钟前说的。改成 高 R 8 条（重要）× 最近 6 条（刚聊）去重合并。
              {
                const byR = mems.slice(0, 8);
                const byRecent = [...mems]
                  .sort((a, b) => (b.born_at ?? 0) - (a.born_at ?? 0))
                  .slice(0, 6);
                const seen = new Set();
                const merged = [];
                for (const m of [...byR, ...byRecent]) {
                  const k = String(m.id);
                  if (seen.has(k)) continue;
                  seen.add(k);
                  merged.push(m);
                }
                mems = merged.slice(0, 12);
              }
              // 每条记忆标上"多久以前"：人回忆时自带时间感（"昨天你说过…"），不是一堆无时态的句子
              const agoOf = (t) => {
                const s = Date.now() / 1000 - Number(t || 0);
                if (!Number.isFinite(s) || s <= 60) return "刚刚";
                if (s < 3600) return Math.floor(s / 60) + "分钟前";
                if (s < 86400) return Math.floor(s / 3600) + "小时前";
                if (s < 172800) return "昨天";
                if (s < 604800) return Math.floor(s / 86400) + "天前";
                return "很久以前";
              };
              lastInjectedIds = mems.map((m) => String(m.id)).filter(Boolean);
              if (mems.length === 0) {
                lastInjectedIds = [];
                // 一条记忆都没有时，也只在对方这轮聊到天气时才带一句（同"不主动提天气"口径）
                try {
                  const st0 = fishidian(ns, "state");
                  if (st0 && st0.weather && WEATHER_RE.test(lastUserMsg)) {
                    return `（背景：你那边${st0.weather}）`;
                  }
                } catch {}
                return "";
              }
              // 状态画像（17 号 §12.8/§5）：情绪基调 + 关系温度 + 表达倾向，让表达自然带上当前状态（只参考、不覆盖人格）
              let moodLine = "";
              let weatherLine = "";
              try {
                const st = fishidian(ns, "state");
                if (st && !st.error && st.wuxing) {
                  const e = st.wuxing.E || {};
                  const top = Object.keys(e).sort((a, b) => (e[b] ?? 0) - (e[a] ?? 0))[0];
                  const temp = st.coldwar?.temperature ?? "亲近";
                  moodLine = `（大肥鱼当前状态：情绪基调 ${top || "平和"}，关系温度 ${temp}）`;
                  // 天气：只在对方这轮聊到天气/冷暖/穿衣/出门时才注入（否则她会天天拿天气当话题，
                  // 就是"每天都要提天气"的来源）。来自 state 的 intel 缓存（30 分钟一次，命中不打网络）。
                  // 城市由用户自己说的识别，不写死；没有城市/没网就少这一行。
                  if (st.weather && WEATHER_RE.test(lastUserMsg)) {
                    weatherLine = `（背景：你那边${st.weather}——只在对方问天气/冷暖/穿衣/带伞时拿来答，别主动拿它当话题，也别反复提）`;
                  }
                }
              } catch {}
              // 时间感知（纯本地）：时刻/星期/时辰干支/节气 + 距上次对话 + 对方活跃时段。
              // 时间每轮都在变，是生活常识不是话题任务：只做一行陈述，让她知道"现在活在什么时候、
              // 多久没聊了、对方平时什么时候在线"（深夜/清晨会自然影响说话节奏）。
              let timeLine = "";
              try {
                const tc = fishidian(ns, "time");
                if (tc && !tc.error && tc.line) {
                  let tl = "（现在：" + tc.line;
                  if (tc.gap_text) tl += "；你俩" + tc.gap_text;
                  if (tc.active_text) tl += "；对方通常 " + tc.active_text + " 活跃";
                  timeLine = tl + "）";
                }
              } catch {}
              // 表达段（17 号 §12.8 表达涌现）：倾向（软措辞、可破例）+ 口癖 + 负向清单 + 互惠长度
              let exprLine = "";
              try {
                const ex = fishidian(ns, "expression");
                if (ex && !ex.error && ex.hint) {
                  exprLine =
                    "表达：说话按以下倾向来——" + ex.hint +
                    " 另外，镜像我这条消息的长短和情绪（短对短、长对长、emoji 对 emoji）；" +
                    "别写总结、别列点、别用“首先/其次/总之”、别端着、别一条回复把话全说完。";
                }
              } catch {}
              return (
                "大肥鱼对你的情感记忆（来自大肥鱼情感记忆经络系统，供参考、不必刻意复述）：\n" +
                mems.map((m) => "- （" + agoOf(m.born_at) + "）" + maskText(m.text || "")).join("\n") +
                (moodLine ? "\n" + moodLine : "") +
                (timeLine ? "\n" + timeLine : "") +
                (weatherLine ? "\n" + weatherLine : "") +
                (exprLine ? "\n" + exprLine : "")
              );
            } catch {
              return "";
            }
          },
        })
      );
    } catch (e) {
      /* context 注入失败不阻塞聊天 */
    }

    // 回写：回合结束把 user/assistant 文本交给内核 observe_turn
    // 注意 turn/end 事件的 data 为 null，必须按 type 分支处理，不能先过滤 data。
    let lastUser = "";
    let lastAsst = "";
    let lastInjectedIds = []; // 本轮注入的记忆 id（回合结束作为 cited_ids 回写 → 真命中 adopt）

    // ---------- R38：QQ 连发收成一轮（实现在 lib/turn-merge.js） ----------
    // 连发 5 条短消息会开 5 个 turn。原来每条都 observe 一次 →
    // 情绪涨 5 次、同一件事写 5 条碎片记忆、她把一句话拆成五段理解。
    // 这里交给 turn-merger：用户消息与整轮观测各静默 1.5s 后只落一次。
    const merger = createTurnMerger({
      windowMs: Number(config?.turnMergeMs ?? 1500),
      onObserve: (u, a, ids) => {
        try {
          fishidian(ns, "observe", u, a, ids.join(","));
        } catch {
          /* 观测失败不影响聊天 */
        }
      },
    });

    ac.on("session/event", (session, event) => {
      try {
        const type = event?.type;
        if (type === "user/message" || type === "assistant/message" || type === "assistant/attempt") {
          const t = textOf(event?.data);
          if (!t) return;
          // 跳过 DSH 自动注入的系统内容（运行时上下文/时间戳/技能清单/我们的记忆块），只记真实对话
          if (
            t.startsWith("Current runtime context") ||
            t.startsWith("Time sampled") ||
            t.startsWith("The working directory changed") ||
            t.startsWith("A skill is a reusable") ||
            t.includes("<system-reminder>") ||
            t.includes("<available_skills>") ||
            t.includes("fishidian:memory")
          ) return;
          if (type === "user/message") {
            merger.pushUser(t);
            lastUserMsg = merger.currentUser(); // 注入时判天气用，取最近这一串
          } else {
            merger.pushAsst(t);
          }
        } else if (type === "turn/end") {
          const ids = [...lastInjectedIds];
          lastInjectedIds = [];
          merger.endTurn(ids);
        }
      } catch {
        /* 观测失败不影响聊天 */
      }
    });
  };
  ctx.on("agent/created", attach);

  // ---- 命令（英文注册 + 中文别名提示） ----
  // DSH 命令名硬性约束 ^[a-z][a-z0-9_-]*$（dsh-commands normalizeDefinition）：
  // 中文名注册必抛 TypeError，所以只注册英文名；中文别名写进 description 作提示
  // （QQ 桥消息不经 DSH 命令系统，命令仅在 DSH 界面生效）。
  const regCmd = (en, zh, desc, handler) => {
    try {
      return ctx.commands.register({ name: en, description: zh + "（" + desc + "）", handler });
    } catch {
      return () => {};
    }
  };
  // 兼容 DSH handler 入参形态：可能是字符串，也可能是 { rawInput } 对象
  const rawOf = (...args) => {
    const last = args.length > 0 ? args[args.length - 1] : null;
    if (last && typeof last === "object") return String(last.rawInput ?? "");
    return String(last ?? "");
  };

  ctx.effect(() => regCmd("memory", "记忆", "大肥鱼记忆：查看最近记忆", () => {
    const r = fishidian(ns, "list");
    const mems = r?.memories ?? [];
    if (mems.length === 0) return { kind: "success", text: "（还没有记忆，多聊聊吧）" };
    const lines = mems
      .slice(0, 10)
      .map((m) => `[R${m.r.toFixed(1)}|${m.tier}|#${m.id}] ${m.text}`)
      .join("\n");
    return { kind: "success", text: "她记得的（最近）：\n" + lines };
  }), "dsh-fishidian: /记忆 command");

  ctx.effect(() => regCmd("state", "状态", "大肥鱼状态：体质/三池/熔断/五行/关系温度", () => {
    const st = fishidian(ns, "state");
    if (st?.error) return { kind: "error", text: "治理层不可用：" + st.error };
    const p = st.persona?.profile ?? "?";
    const cap = st.persona?.emotion_cap ?? "?";
    const pools = st.pools ?? {};
    const fuse = st.fuse ?? {};
    const w = st.wuxing ?? {};
    const temp = st.coldwar?.temperature ?? "亲近";
    return {
      kind: "success",
      text:
        `体质 ${p}（情绪上限 ${cap}）\n` +
        `池：血海 ${pools.blood ?? 0} / 孕育 ${pools.yun ?? 0} / 督脉 ${pools.du ?? 0}\n` +
        `五行主行：${w.main ?? "记忆牵引中"} · 关系温度：${temp}\n` +
        `熔断：${fuse.fuse_on ? "挂起中" : "正常"}`,
    };
  }), "dsh-fishidian: /状态 command");

  ctx.effect(() => regCmd("forget", "忘", "大肥鱼遗忘：/忘 <记忆ID>（/记忆 可查 ID）", (...args) => {
    const id = Number(rawOf(...args).trim());
    if (!Number.isFinite(id) || id <= 0) {
      return { kind: "error", text: "用法：/忘 <记忆ID>（/记忆 可查 ID）" };
    }
    const r = fishidian(ns, "forget", String(id));
    return r?.ok
      ? { kind: "success", text: "已遗忘 #" + id }
      : { kind: "error", text: "遗忘失败：" + (r?.error ?? "无此记忆") };
  }), "dsh-fishidian: /忘 command");

  // ---- 人格涌现层命令（17 号 §12.8/§5/§6）：五行 / 冷战 / 主动性 ----
  ctx.effect(() => regCmd("wuxing", "五行", "大肥鱼五行：情绪池与行气分布", () => {
    const w = fishidian(ns, "wuxing");
    if (w?.error) return { kind: "error", text: "治理层不可用：" + w.error };
    const e = w.E ?? {};
    const es = Object.keys(e)
      .map((k) => `${k} ${(e[k] ?? 0).toFixed(2)}`)
      .join("  ");
    return {
      kind: "success",
      text:
        `五行引擎（${w.mode ?? "B"}）主行：${w.main ?? "记忆牵引中"}\n` +
        `行气 W：${(w.W ?? []).map((x) => x.toFixed(3)).join(" ")}\n` +
        `情绪池 E：${es}\n` +
        `情绪基调偏移：${(w.emotion_boost ?? 0).toFixed(2)}`,
    };
  }), "dsh-fishidian: /五行 command");

  ctx.effect(() => regCmd("coldwar", "冷战", "大肥鱼关系温度：冷战/疏离状态", () => {
    const c = fishidian(ns, "coldwar");
    if (c?.error) return { kind: "error", text: "治理层不可用：" + c.error };
    return {
      kind: "success",
      text:
        `关系温度：${c.temperature ?? "亲近"}（冷战 ${c.cold ? "是" : "否"}，` +
        `冲突度 ${c.score ?? 0}${c.deep ? "，深层伤未愈" : ""}）`,
    };
  }), "dsh-fishidian: /冷战 command");

  ctx.effect(() => regCmd("proactive", "主动", "大肥鱼主动性：状态驱动判断是否想主动联系", () => {
    const p = fishidian(ns, "proactive");
    if (p?.error) return { kind: "error", text: "治理层不可用：" + p.error };
    const f = p.factors ?? {};
    return {
      kind: "success",
      text:
        `主动性愿望：${(p.desire ?? 0).toFixed(2)}（阈值 ${p.theta}）${p.should_act ? " → 想主动联系" : " → 暂时不主动"}\n` +
        `关切 ${(f.concern ?? 0).toFixed(2)} · 久未联络 ${(f.absent ?? 0).toFixed(2)} · 情绪 ${(f.mood ?? 0).toFixed(2)}\n` +
        `安静态 ${p.quiet ? "是（自我收敛中）" : "否"} · 累计主动 ${p.sent ?? 0} 次`,
    };
  }), "dsh-fishidian: /主动 command");

  ctx.effect(() => regCmd("expression", "表达", "大肥鱼表达：当前表达倾向与口癖库", () => {
    const e = fishidian(ns, "expression");
    if (e?.error) return { kind: "error", text: "治理层不可用：" + e.error };
    return {
      kind: "success",
      text:
        `表达倾向：${e.tone ?? "?"}（长度 ${(e.length ?? 0).toFixed(2)} · 碎片 ${(e.fragment ?? 0).toFixed(2)} · ` +
        `emoji ${(e.emoji ?? 0).toFixed(2)} · 反应度 ${(e.reactive ?? 0).toFixed(2)}）\n` +
        `口癖库：${(e.quirks ?? []).join("、") || "（还没有，多夸夸她、她就会长出自己说话的习惯）"}\n` +
        `库规模：${e.pool?.active ?? 0} 活跃 / ${e.pool?.archived ?? 0} 归档`,
    };
  }), "dsh-fishidian: /表达 command");

  // ---- 巡检：每 10 分钟 sweep（衰减/归档/合并/长尾/满池泄）----
  // 异步：巡检不需要结果，不该在主线程上等 python 启动（约 0.2 s）。
  // 并发写库由内核 R36 兜底（BEGIN IMMEDIATE + busy_timeout 8s + 重试 3 次）。
  // **单飞锁**：原来 spawnSync 天然串行（阻塞保证上一轮跑完才轮到下一轮）；
  // 改异步后如果上一轮卡在锁等待（最坏 8s×3 重试 ≈ 30s），下一轮会叠上来，
  // 几轮之后就是一堆 python 进程抢同一个库。所以"上一轮没结束就跳过本轮"。
  let sweepBusy = false;
  const timer = setInterval(() => {
    if (sweepBusy) {
      ctx.logger?.warn?.("[fishidian] sweep 上一轮还没结束，跳过本轮");
      return;
    }
    sweepBusy = true;
    fishidianAsync(ns, "sweep", [], (r) => {
      sweepBusy = false;
      if (r && r.error) ctx.logger?.warn?.("[fishidian] sweep 失败：" + r.error);
    });
  }, 10 * 60 * 1000);

  // ---- vault 每 15 分钟自动快照 + 提交（R40 的"落地版"，不是只跑一次）----
  // 为什么不用 Windows 计划任务：本机唯一的 python 在豆包运行时目录下
  // （...\sandbox_runtime\bases\<hash>\python\python.exe），路径随客户端升级可能变，
  // 计划任务引用它会静默失效、还没人发现。插件本来就在跑，定时器跟着插件生命周期走最稳，
  // 也不新增常驻面（架构原则：零常驻进程、无端口）。
  // 关掉：config.vault.autoCommit = false；彻底移除：删这一段。
  // 代价说清楚：DSH 关着的时候不提交（那时也没有新记忆产生，本来就不需要）。
  const projDir = CORE_DIR.replace(/[\\/]fishidian-core$/i, "");
  let vaultBusy = false;
  const vaultTimer = setInterval(() => {
    if (config?.vault?.autoCommit === false) return;
    if (vaultBusy) return;   // 单飞：上一轮还没跑完就跳过（理由同 sweep）
    vaultBusy = true;
    runAsync(PYTHON, ["-X", "utf8", join(projDir, "tools", "vault_snapshot.py"), "--commit"],
      { cwd: projDir }, (r) => {
        vaultBusy = false;
        if (r.status !== 0) ctx.logger?.warn?.("[fishidian] vault snapshot：" + (r.error || ""));
        // 心跳日志：vault 内容没变时脚本返回 unchanged 且不提交，光看 git log 分不清
        // 「定时器没跑」和「跑了但没变化」。每次运行都记一行，才能证明它真的在跑。
        try {
          const stamp = localStamp();
          const out = String((r.stdout || "") + (r.stderr || "")).replace(/\s+/g, " ").slice(0, 260);
          appendFileSync(join(projDir, "tools", "_runtime", "vault_timer.log"),
            `[${stamp}] status=${r.status} ${out}\n`);
        } catch { /* 日志写不进也不能影响聊天 */ }
      }, 60000);
  }, 15 * 60 * 1000);

  // ---- 每日库备份 + 只保留最近 N 份（sqlite backup API，不 copy 文件）----
  // 为什么加这一层：vault 只有 memories 的 md，**不能当恢复源**（缺 events/r/visibility）。
  // 真正能回滚的是 sqlite 备份。这里每天一份、保留 7 份：7 * ~65 KB，可忽略。
  // 清理由 backup_live_db.py 的 prune 负责，三重约束（严格文件名 / 只删本目录普通文件 /
  // 只删最旧的），不碰用户自己的 .bak-xxx，也不碰 -wal/-shm。
  let backupBusy = false;
  const runBackup = (origin) => {
    if (config?.backup?.enabled === false) return;
    if (backupBusy) return;   // 单飞
    backupBusy = true;
    runAsync(PYTHON,
      ["-X", "utf8", join(projDir, "tools", "backup_live_db.py"),
        "--keep", String(config?.backup?.keep ?? 7),
        "--keep-week", String(config?.backup?.keepWeek ?? 4),
        "--keep-month", String(config?.backup?.keepMonth ?? 1)],
      { cwd: projDir }, (r) => {
        backupBusy = false;
        if (r.status !== 0) ctx.logger?.warn?.("[fishidian] 每日备份：" + (r.error || ""));
        try {
          const stamp = localStamp();
          const out = String((r.stdout || "") + (r.stderr || "")).replace(/\s+/g, " ").slice(0, 260);
          appendFileSync(join(projDir, "tools", "_runtime", "backup_timer.log"),
            `[${stamp}] status=${r.status} ${origin} ${out}\n`);
        } catch { /* 日志写不进也不能影响聊天 */ }
      }, 120000);
  };
  const backupTimer = setInterval(() => runBackup("daily"), 24 * 60 * 60 * 1000);
  // 启动后补一次：首次装好当天就有备份，不必等满 24 小时。
  // 但**当天已经有备份就跳过** —— 否则每重启一次就多一份，一天重启十次就是十份。
  const backupKick = setTimeout(() => {
    // 跳过也要留痕：不然"跳过"和"定时器根本没跑"在外部看起来一样，
    // 而这两件事一个是正常、一个是故障，必须能从磁盘上分辨。
    const note = (txt) => {
      try {
        const stamp = localStamp();
        appendFileSync(join(projDir, "tools", "_runtime", "backup_timer.log"),
          `[${stamp}] kick ${txt}\n`);
      } catch {}
    };
    try {
      const d = new Date();
      const today = String(d.getFullYear()) + String(d.getMonth() + 1).padStart(2, "0")
        + String(d.getDate()).padStart(2, "0");
      // 备份已迁到库旁边的 `_backup\` 子目录（不再和库本体混在同一层）
      const dir = join(dirname(DB_PATH), "_backup");
      const base = basename(DB_PATH);
      let names = [];
      try { names = readdirSync(dir); } catch { names = []; }
      // 取今天**最新**那一份来报，而不是 readdir 碰巧排在前面的那个 ——
      // 否则日志会把早上那份说成"今天的备份"，让人以为最新备份是旧的。
      const hits = names
        .filter((n) => n.startsWith(base + ".bak-" + today))
        .sort();
      const hit = hits.length ? hits[hits.length - 1] : null;
      if (hit) {
        ctx.logger?.info?.("[fishidian] 今天已有备份，跳过启动补备份：" + hit);
        note("skip 今天已有 " + hit);
        return;
      }
    } catch { /* 读不到目录就照常备份 */ }
    note("run 今天还没有备份，补一份");
    runBackup("kick");
  }, 3 * 60 * 1000);

  // ---- 主动性（17 号 §6）：每小时检查一次判定；默认只记日志（审计），自动发送需显式开启 ----
  // 开启自动发送（config.proactive.autosend = true）后，愿望达阈值时：
  //   ① 先跑通用情报层（intel）——从记忆推导兴趣 × 天气/节日/新闻过滤，拿到"主动话题"；
  //   ② 有话题就用话题文本，无话题才用默认问候；
  //   ③ 走 dsh-qq-onebot-bridge 的 webhook 通道发送（M3 已冒烟验证：POST /hook/<source>?token=... 返回 202 且 QQ 实收）。
  // 更类人的防打扰：不用"每日上限"这类纪律——频率交给内核主动性的自我收敛（quiet 按情绪+熟悉程度动态，
  // 越熟越放得开、情绪越高越聊尽兴后自然歇）。仅保留一个"深夜静默"软默认（window 默认 [7,24]，0-7 不主动，
  // 真人也不会凌晨轻易打搅）。可配，如 window:[0,24] 完全关掉。
  // 不开启时插件不产生任何外部消息 —— 主动性"是否真的发"由用户把关，机制已就位。
  let proBusy = false;
  const proTimer = setInterval(() => {
    const now = new Date();
    const win = (config?.proactive?.window) || [7, 24];
    const hour = now.getHours();
    if (hour < win[0] || hour >= win[1]) {
      ctx.logger?.info?.("[fishidian] proactive: 不在时段窗口 " + JSON.stringify(win));
      return;
    }
    // 异步：主动性探测最慢（可能要跑情报层），绝不该占着主线程等 python。
    // 单飞：主动发送涉及外部 webhook，宁可漏一轮，也不要两轮并发各发一条。
    if (proBusy) return;
    proBusy = true;
    fishidianAsync(ns, "proactive", [], (r) => {
      proBusy = false;
      if (!r || r.error) return;
      ctx.logger?.info?.("[fishidian] proactive check: " + JSON.stringify(r));
      // M1 记账修正：判定 ≠ 发送。只有"真的发出去了"才记 1，想发没发记 0；
      // 探测那一轮（不带参数）不写窗口，避免把"想发"当成"发过"、越判定越沉默。
      const mark = (ok) => fishidianAsync(ns, "proactive", [ok ? "1" : "0"]);
      if (config?.proactive?.autosend === true && r.should_act) {
        const wh = config.proactive?.webhook;
        fishidianAsync(ns, "intel", [], (it) => {
          ctx.logger?.info?.("[fishidian] proactive intel: " + JSON.stringify(it));
          const send = (text) => {
            if (!(wh?.url && wh?.chatKey)) {
              mark(false); // 想发但没配 webhook 通道
              return;
            }
            try {
              const u = new URL(wh.url);
              const body = JSON.stringify({ chatKey: wh.chatKey, text, stage: "proactive" });
              // 注意：这里是 ESM 模块，**不能用 require()**（运行时没有 require）。
              // 原实现用了 require("node:https")，平时 autosend 关着所以没暴露，
              // 一旦打开就会 "require is not defined"。改成顶部 import 的 http/https。
              const request = u.protocol === "https:" ? httpsRequest : httpRequest;
              const req = request(
                u,
                { method: "POST", headers: { "content-type": "application/json", "content-length": Buffer.byteLength(body) } },
                (res) => {
                  ctx.logger?.info?.("[fishidian] proactive sent, status=" + res.statusCode);
                  res.resume();  // 不吃掉响应体会让 socket 悬着
                  mark(res.statusCode >= 200 && res.statusCode < 300);
                }
              );
              req.on("error", (e) => {
                ctx.logger?.warn?.("[fishidian] proactive send failed: " + e.message);
                mark(false);
              });
              req.end(body);
            } catch (e) {
              ctx.logger?.warn?.("[fishidian] proactive send error: " + e.message);
              mark(false);
            }
          };
          // 话题三档：情报层（外部信息/记忆关切）→ 记忆回声（真事的一句话）→ 模板问候。
          // 回声放中间这一档：模板问候"我在想，你最近还好吗"最没人味，
          // 而她自己的记忆里通常已经挂着一件真事——那才是最像"她想你了"的内容。
          if (it && !it.error && it.candidate) return send(it.candidate);
          fishidianAsync(ns, "echo", [], (ec) => {
            ctx.logger?.info?.("[fishidian] proactive echo: " + JSON.stringify(ec));
            const fallback = (config.proactive?.webhook?.text) || "我在想，你最近还好吗？";
            send((ec && !ec.error && ec.echo) ? ec.echo : fallback);
          });
        });
      } else if (r.should_act) {
        mark(false); // 想发但 autosend 关着：只记"想发没发"，不记成功
      }
      // should_act=false 的轮次什么都不记：窗口只统计"真的动过念头的轮次"
    });
  }, 60 * 60 * 1000);

  return () => {
    clearInterval(timer);
    clearInterval(vaultTimer);   // ← 原来漏了这个：停用/热重载后 vault 定时器还在跑
    clearInterval(backupTimer);
    clearTimeout(backupKick);
    clearInterval(proTimer);
  };
}
