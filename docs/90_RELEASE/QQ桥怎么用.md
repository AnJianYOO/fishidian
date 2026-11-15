# QQ 桥怎么用

> 这份只讲一件事：怎么让她在 QQ 里能说话。不涉及记忆、五行、窗口外观。

## 先说清楚：QQ 是可选的

不装 QQ，双击桌面「大肥鱼」照样能聊 —— 记忆、五行、表达层、主动发消息全都正常。
装了 QQ，只是多一条「在手机 QQ 里找她」的通道。

装的时候第一个 QQ 号直接回车，就等于不装 QQ。

## 本版默认用哪个桥

`dsh-qq-onebot-bridge` —— 第三方开源项目，MIT 许可。

| 项 | 值 |
|---|---|
| 上游 | [cheesehaqi/dsh-qq-onebot-bridge](https://github.com/cheesehaqi/dsh-qq-onebot-bridge) |
| 这个包里附带 | 基于上游 v0.8.9 打的补丁版 |
| 补丁内容 | `/记忆` `/状态` `/天气` `/五行` `/冷战` 等命令免模型直通；回复按情绪分条；天气入口 |

**用上游原版也能连上 QQ**，但那几个斜杠命令不会有反应 —— 补丁不在上游里。

## 它是怎么连上的

桥在你自己电脑上**开一个端口**（默认 `6700`）等着，NapCat 那边**反向连过来**。
所以是 OneBot 那边填地址，不是桥去找它。

```
NapCat ──反向 WS──> ws://127.0.0.1:6700 ──> 桥 ──> 她
```

## 方式 A：NapCat（本版默认，验证过）

1. 按 `START-HERE.md` 第 3 步装 NapCat（解压到 `%USERPROFILE%\NapCat`）
2. 装包时填两个号：机器人 QQ 号 + 你的白名单号
3. 双击桌面「大肥鱼」，右下角点「连 QQ」，手机 QQ 扫码
4. QQ 里给机器人号发一条消息

UAC 提示、二维码过期怎么刷新，都在 `START-HERE.md` 第 3、4 步。

## 方式 B：换别的 OneBot 11 实现

桥对外就是标准 OneBot 11 反向 WebSocket，任何实现都能接：

- Lagrange.OneBot
- LLOneBot
- 自建实现

要做的只有一件事：**在那个实现的「反向 WebSocket」配置里，把地址填成 `ws://127.0.0.1:6700`**。

如果桥这边改过端口或加了 token，对应改 `cordis.patch.yml`：

```yaml
- id: dsh-qq-onebot-bridge
  config:
    port: 6700          # 桥监听的端口，OneBot 那边要连这个
    accessToken: ""     # 非空时，OneBot 那边必须带同样的 token
```

**如实说明**：本版只在 NapCat 这条链路上验证过。别的实现按协议应该能通，但没跑过验证；接的时候按 OneBot 11 标准报文对齐即可，插件本身不用改。

## 方式 C：不用 QQ

装的时候机器人号直接回车。窗口里聊，一切正常。

## 她不回你？按这个顺序查

1. **白名单里有没有你** —— `%USERPROFILE%\fishidian\data\profiles\desktop\cordis.patch.yml` 里的 `allowUsers`。空 = 谁都不回，这是最常见的一条
2. **机器人在线吗** —— 看 6700 端口有没有 ESTABLISHED（`netstat -ano | findstr 6700`）
3. **NapCat 和 QQ 版本对不上** —— 跑 `check_napcat.ps1`，它报两个 build 号，不下结论
4. **群里不回** —— 默认只有被 @ 才回（`replyOnlyWhenMentioned: true`）
5. **二维码出不来** —— 去 NapCat 的 releases 页找匹配你这版 QQ build 的版本
6. **还是不回** —— 把 `%USERPROFILE%\fishidian\logs\` 和 `cordis.patch.yml` 丢给 AI

## 不懂就交给 AI

把这三份一起丢给 AI，让它照着做：

- `START-HERE.md` —— 从装到验收
- `FOR-AI.md` —— 排错手册，专门写给 AI 看的
- `QQ桥怎么用.md` —— 这份

它知道该跑哪个脚本、该看哪个文件、该改哪个键。你只要告诉它「QQ 连不上」或者「她不回我」。
