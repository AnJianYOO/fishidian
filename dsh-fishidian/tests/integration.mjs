// dsh-fishidian 集成测试：真实插件 apply + mock DSH 事件外壳 + 真实内核 CLI/DB
// 运行：node tests/integration.mjs   （需 node >= 20）
// 注意：lib/index.js 在模块加载时求值 DB 路径 → 必须先设 FISHIDIAN_DB_DIR 再动态 import。
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// 默认内核目录：从本测试文件往上两级（dsh-fishidian/tests → 仓库根）再进 fishidian-core。
// 不写死任何一台机器的路径；需要换位置时用环境变量 FISHIDIAN_CORE 覆盖。
const DEFAULT_CORE = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "fishidian-core");

let pass = 0, fail = 0;
const ok = (cond, name) => { if (cond) { pass++; console.log("  PASS " + name); } else { fail++; console.log("  FAIL " + name); } };

const testDbDir = mkdtempSync(join(tmpdir(), "fishidian-test-"));
process.env.FISHIDIAN_DB_DIR = testDbDir;
const { apply } = await import("../lib/index.js");

// --- mock DSH ctx ---
const registered = [];
const agentEvents = [];   // agent/created listeners
const listeners = {};     // per-agent ctx events
const agents = [];

function makeAgentCtx(agentId) {
  const ac = { on: (ev, fn, opts) => { (listeners[agentId] ??= {})[ev] ??= []; listeners[agentId][ev].push({ fn, opts }); } };
  return ac;
}

const ctx = {
  logger: { info: (...a) => console.log("  [ctx.logger.info]", ...a) },
  commands: {
    // 复刻 dsh-commands normalizeDefinition 的硬约束：
    // 命令名必须匹配 /^[a-z][a-z0-9_-]*$/u，中文名注册必抛 TypeError（真实 DSH 行为）。
    register: (def) => {
      if (!/^[a-z][a-z0-9_-]*$/u.test(def.name)) throw new TypeError(`command name "${def.name}" must match /^[a-z][a-z0-9_-]*$/u`);
      if (typeof def.description !== "string" || def.description.trim() === "") throw new TypeError("command description must be a string");
      if (typeof def.handler !== "function") throw new TypeError("command handler must be a function");
      registered.push(def);
      return def.name;
    },
  },
  on: (ev, fn) => { if (ev === "agent/created") agentEvents.push(fn); },
  effect: (fn) => fn(),
};

const ns = "test:integ";
// （DB 路径已在 import 前通过 FISHIDIAN_DB_DIR 指向 testDbDir，见文件头）

const dispose = apply(ctx, { ns });

// 1) 命令注册 7 个（英文名；中文别名在 description 提示——中文名注册会被 DSH 拒绝）
ok(registered.map((r) => r.name).join(",") === "memory,state,forget,wuxing,coldwar,proactive,expression",
  "7 commands registered (英文名)");
ok(registered.every((r) => /记忆|状态|忘|五行|冷战|主动|表达/.test(r.description)),
  "description 含中文别名提示");

// 1b) 中文命令名确实会被 DSH 命令名约束拒绝（插件不假装"中英双名"）
const zhRejected = ["记忆", "状态", "忘", "五行", "冷战", "主动", "表达"].every((zh) => {
  try {
    ctx.commands.register({ name: zh, description: "x", handler: () => ({ kind: "success" }) });
    return false;
  } catch {
    return true;
  }
});
ok(zhRejected, "中文命令名注册被 DSH 约束拒绝（与真实 DSH 一致）");

// 2) agent/created 挂接存在
ok(agentEvents.length === 1, "agent/created listener attached");

// 3) 模拟 agent 创建 → attach 应注册 session/event（回写）。稳定版注入已禁用（避免宿主崩溃）。
const fakeAgent = { ctx: makeAgentCtx("a1") };
agentEvents[0](fakeAgent);
const a1 = listeners["a1"];
ok(a1 && a1["session/event"] && a1["session/event"].length === 1, "session/event listener attached");
ok(!(a1["agent/pre-step"] && a1["agent/pre-step"].length), "pre-step injection disabled in stable version");

// 4) 注入已暂停（待不动地基的注入方式），此段不再断言注入行为。

// 5) 回写：session/event user/message + assistant/message + turn/end → observe 入库
const sessEvt = a1["session/event"][0];
sessEvt.fn({}, { type: "user/message", data: { content: "我今天升职了，特别开心" } });
sessEvt.fn({}, { type: "assistant/message", data: { text: "恭喜你！" } });
sessEvt.fn({}, { type: "turn/end", data: null });
await new Promise((r) => setTimeout(r, 300)); // 让同步 spawn 完成（spawnSync 同步，实际不需要；保险起见）
{
  const { spawnSync } = await import("node:child_process");
  const py = process.env.FISHIDIAN_PYTHON ?? "python";
  const core = process.env.FISHIDIAN_CORE ?? DEFAULT_CORE;
  const db = join(testDbDir, "fishidian.db");
  const r = spawnSync(py, [join(core, "cli.py"), ns, db, "list"], { encoding: "utf8" });
  const lst = JSON.parse(r.stdout);
  ok((lst.memories ?? []).some((m) => m.text.includes("升职")), "observe_turn wrote turn into memory store");
}

// 6) 命令 handler 可执行（memory/state/forget 英文名）
const memCmd = registered.find((r) => r.name === "memory");
const memOut = memCmd.handler();
ok(memOut.kind === "success", "/memory works");
const stCmd = registered.find((r) => r.name === "state");
const stOut = stCmd.handler();
ok(stOut.kind === "success" && stOut.text.includes("体质"), "/state works");
const fgCmd = registered.find((r) => r.name === "forget");
ok(fgCmd.handler("abc").kind === "error", "/forget rejects bad id");
ok(fgCmd.handler({ rawInput: "abc" }).kind === "error", "/forget accepts {rawInput} arg shape");

// 7) 人格涌现层命令：wuxing / coldwar / proactive
const wxCmd = registered.find((r) => r.name === "wuxing");
const wxOut = wxCmd.handler();
ok(wxOut.kind === "success" && wxOut.text.includes("五行引擎"), "/wuxing works");
const cwCmd = registered.find((r) => r.name === "coldwar");
const cwOut = cwCmd.handler();
ok(cwOut.kind === "success" && cwOut.text.includes("关系温度"), "/coldwar works");
const paCmd = registered.find((r) => r.name === "proactive");
const paOut = paCmd.handler();
ok(paOut.kind === "success" && paOut.text.includes("主动性愿望"), "/proactive works");

// 6c) 表达层命令：/expression 可执行（17 号 §12.8 表达涌现）
const exCmd = registered.find((r) => r.name === "expression");
const exOut = exCmd.handler();
ok(exOut.kind === "success" && exOut.text.includes("口癖库"), "/expression works");

// 8) 状态画像：state 已并入 wuxing/coldwar（注入段用，供表达参考）
{
  const { spawnSync } = await import("node:child_process");
  const py = process.env.FISHIDIAN_PYTHON ?? "python";
  const core = process.env.FISHIDIAN_CORE ?? DEFAULT_CORE;
  const db = join(testDbDir, "fishidian.db");
  const r = spawnSync(py, [join(core, "cli.py"), ns, db, "state"], { encoding: "utf8" });
  const st = JSON.parse(r.stdout);
  ok(st.wuxing && st.coldwar && st.wuxing.emotion_boost !== undefined, "state includes wuxing/coldwar/emotion_boost");
}

dispose();
rmSync(testDbDir, { recursive: true, force: true });

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
