// R38：QQ 连发收成一轮 —— 把"N 条消息 / N 个 turn"收敛成"一次观测量、一次情绪波动"。
//
// 为什么要有这个：用户随手连发 5 条短消息（"在吗" / "今天" / "有点" / "累" / "陪我聊"），
// 宿主会开 5 个 turn、触发 5 次 turn/end。原来每轮都回写一次 observe →
//   · 同一次情绪被累加 5 次（她莫名其妙就很激动）；
//   · 同一件事写成 5 条碎片记忆（检索时一条都找不全）；
//   · 她把一句完整的话拆成五个片段去理解。
//
// 做法（两级缓冲，都是"静默 N 毫秒才落盘"）：
//   ① 用户消息先攒成一段（换行分隔），静默 windowMs 后定稿为"这一串"；
//   ② 整轮观测再攒，静默 windowMs 后合成一次 onObserve。
// 正常一问一答的间隔远大于 1.5s，所以不会把两轮误并成一轮。
// 合并后的 user 用换行分隔：内核 observe_turn 会按行各记一条记忆，但情绪只涨一次。

export function createTurnMerger({ windowMs = 1500, onObserve = () => {} } = {}) {
  const W = Math.max(300, Number(windowMs) || 1500);
  let bufUser = [];
  let bufAsst = [];
  let queue = []; // 待合并落盘的整轮观测：[{ user, asst, ids }]
  let pendingUser = ""; // 已定稿、还没被 turn/end 取走的那一串
  let userTimer = null;
  let obsTimer = null;

  const flushUser = () => {
    if (userTimer) {
      clearTimeout(userTimer);
      userTimer = null;
    }
    if (!bufUser.length) return false;
    pendingUser = bufUser.join("\n");
    bufUser = [];
    return true;
  };

  const flushObs = () => {
    obsTimer = null;
    if (!queue.length) return false;
    const batch = queue;
    queue = [];
    const u = batch.map((x) => x.user).filter(Boolean).join("\n");
    const a = batch.map((x) => x.asst).filter(Boolean).join("\n");
    const ids = [...new Set(batch.flatMap((x) => x.ids || []))];
    try {
      onObserve(u, a, ids);
    } catch {
      /* 观测失败不影响聊天 */
    }
    return true;
  };

  return {
    pushUser(t) {
      const s = String(t || "");
      if (!s) return;
      bufUser.push(s);
      if (userTimer) clearTimeout(userTimer);
      userTimer = setTimeout(flushUser, W);
    },
    // assistant 可能被分条发送（按情绪条数分几次发），必须累积，不能只留最后一条
    pushAsst(t) {
      const s = String(t || "");
      if (!s) return;
      bufAsst.push(s);
    },
    // 当前"这一串用户消息"（注入时判天气用）
    currentUser() {
      return bufUser.length ? bufUser.join("\n") : pendingUser;
    },
    endTurn(ids = []) {
      flushUser();
      if (!pendingUser) return false;
      const asst = bufAsst.join("\n");
      bufAsst = [];
      queue.push({ user: pendingUser, asst, ids: Array.from(ids || []) });
      pendingUser = "";
      if (obsTimer) clearTimeout(obsTimer);
      obsTimer = setTimeout(flushObs, W);
      return true;
    },
    // 卸载 / 测试用：把手上所有内容立刻落一次
    flushAll() {
      flushUser();
      if (pendingUser) {
        queue.push({ user: pendingUser, asst: bufAsst.join("\n"), ids: [] });
        pendingUser = "";
        bufAsst = [];
      }
      return flushObs();
    },
    pending() {
      return { bufUser: bufUser.length, pendingUser: !!pendingUser, queue: queue.length };
    },
    dispose() {
      if (userTimer) clearTimeout(userTimer);
      if (obsTimer) clearTimeout(obsTimer);
      userTimer = null;
      obsTimer = null;
    },
  };
}
