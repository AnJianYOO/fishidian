// R38 验收：turn-merge（QQ 连发收成一轮）
// 跑：node test/turn-merge.test.mjs
import { createTurnMerger } from "../lib/turn-merge.js";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PASS = [];
function check(name, cond, detail = "") {
  PASS.push([name, !!cond, detail]);
  console.log((cond ? "PASS " : "FAIL ") + name + (cond ? "" : `  <- ${detail}`));
}

const W = 300; // 测试用最小窗口

// 1) 连发 5 条 + 5 个 turn/end → 只落一次；user 合并成 5 行
let calls = [];
const m1 = createTurnMerger({ windowMs: W, onObserve: (u, a, ids) => calls.push({ u, a, ids }) });
["在吗", "今天", "有点", "累", "陪我聊聊"].forEach((t, i) => {
  m1.pushUser(t);
  m1.endTurn(i === 4 ? ["7", "9"] : []);
});
await sleep(W + 250);
check("连发 5 条只落 1 次 observe", calls.length === 1, `n=${calls.length}`);
check("合并后 user 是 5 行", calls[0] && calls[0].u.split("\n").length === 5, JSON.stringify(calls[0]?.u));
check("合并后 user 逐条都在",
  calls[0] && ["在吗", "今天", "有点", "累", "陪我聊聊"].every((t) => calls[0].u.includes(t)),
  JSON.stringify(calls[0]?.u));

// 2) 单轮：1 条 user + 1 条 asst
calls = [];
const m2 = createTurnMerger({ windowMs: W, onObserve: (u, a, ids) => calls.push({ u, a, ids }) });
m2.pushUser("今天加班到十点");
m2.pushAsst("辛苦了");
m2.endTurn(["3"]);
await sleep(W + 250);
check("单轮照常落一次", calls.length === 1 && calls[0].u === "今天加班到十点", JSON.stringify(calls));

// 3) 两轮间隔大于窗口 → 分两次，不能误并
calls = [];
const m3 = createTurnMerger({ windowMs: W, onObserve: (u, a, ids) => calls.push({ u, a, ids }) });
m3.pushUser("第一句");
m3.endTurn([]);
await sleep(W + 250);
m3.pushUser("第二句");
m3.endTurn([]);
await sleep(W + 250);
check("间隔超过窗口不误并", calls.length === 2 && calls[0].u === "第一句" && calls[1].u === "第二句",
  JSON.stringify(calls.map((c) => c.u)));

// 4) assistant 分条发送（按情绪条数分几次发）→ 必须全部累积，不能只留最后一条
calls = [];
const m4 = createTurnMerger({ windowMs: W, onObserve: (u, a, ids) => calls.push({ u, a, ids }) });
m4.pushUser("你在干嘛");
m4.pushAsst("在改稿");
m4.pushAsst("有点烦");
m4.endTurn([]);
await sleep(W + 250);
check("assistant 分条不丢", calls.length === 1 && calls[0].a === "在改稿\n有点烦", JSON.stringify(calls[0]?.a));

// 5) cited ids 跨轮合并去重
calls = [];
const m5 = createTurnMerger({ windowMs: W, onObserve: (u, a, ids) => calls.push({ u, a, ids }) });
m5.pushUser("a"); m5.endTurn(["1", "2"]);
m5.pushUser("b"); m5.endTurn(["2", "3"]);
await sleep(W + 250);
check("cited ids 并集去重", calls.length === 1 && calls[0].ids.join(",") === "1,2,3", JSON.stringify(calls[0]?.ids));

// 6) 空 user 不落盘（系统事件被过滤后不该产生空观测）
calls = [];
const m6 = createTurnMerger({ windowMs: W, onObserve: (u, a, ids) => calls.push({ u, a, ids }) });
m6.pushAsst("自己冒出来的一句话");
m6.endTurn([]);
await sleep(W + 250);
check("没有用户消息不落 observe", calls.length === 0, JSON.stringify(calls));

// 7) flushAll 立刻落（卸载时不丢最后一句）
calls = [];
const m7 = createTurnMerger({ windowMs: W, onObserve: (u, a, ids) => calls.push({ u, a, ids }) });
m7.pushUser("卸载前的最后一句");
m7.flushAll();
check("flushAll 立刻落盘", calls.length === 1 && calls[0].u === "卸载前的最后一句", JSON.stringify(calls));

// 8) 窗口参数下限保护（配成 10 也按 300 走，防止配错把两轮并一起）
calls = [];
const m8 = createTurnMerger({ windowMs: 10, onObserve: (u, a, ids) => calls.push({ u, a, ids }) });
m8.pushUser("x");
m8.endTurn([]);
await sleep(60);
check("窗口下限 300ms 生效", calls.length === 0, `n=${calls.length}`);
await sleep(400);
check("下限到点后正常落盘", calls.length === 1, `n=${calls.length}`);

for (const m of [m1, m2, m3, m4, m5, m6, m7, m8]) m.dispose();

const ok = PASS.filter((x) => x[1]).length;
console.log(`\n== ${ok}/${PASS.length} passed ==`);
process.exit(ok === PASS.length ? 0 : 1);
