# 从这里开始

> **如果你是 AI / 智能助手在替用户装**：别读本文，读同目录的 **`FOR-AI.md`**。
> 本文是写给人的，里面有"双击""右键解压"这类你没法执行的动作；
> `FOR-AI.md` 里是从链接下载、非交互安装、失败判据、以及"哪三件事必须停下交回给人"的完整流程。

装完你会得到什么：**桌面上多一个「大肥鱼」图标，双击开出一个单独的窗口**。
这个窗口和她自己的记忆库是一套，和你的工作 DSH 完全分开 —— 工作窗口里聊的东西不进她的记忆，她也不去碰你的工作资料。

QQ 是可选的：不开 QQ 也能在窗口里和她聊；开了 QQ，她在 QQ 里也能回你。
接 QQ 的完整做法 —— 默认的 NapCat 链路、换成别的 OneBot 实现（Lagrange / LLOneBot / 自建）、以及不装 QQ —— 都在同目录的 **`QQ桥怎么用.md`**。

---

## 这个包怎么带到另一台电脑

一个 zip，1 MB 出头。U 盘、网盘、微信 / QQ 传文件都行 —— 里面没有一个字节是凭据或聊天记录，随便传。

**先解压再装**：右键 → 全部解压缩。

- 解压到哪都行（桌面、D 盘、下载目录），装完后这个文件夹就可以删了 —— 程序本体已经复制到 `%USERPROFILE%\fishidian\`，五份文档也一起复制过去了
- ⚠️ **不要在压缩包里直接双击 `install.cmd`**。Windows 有时会用临时目录解包再跑，路径一变就出问题

装出来的位置：

| 位置 | 是什么 |
|---|---|
| `%USERPROFILE%\fishidian\` | 程序本体 + 五份文档（这就是你的安装根） |
| `%USERPROFILE%\fishidian\data\` | 她这个实例的运行数据（profile、会话、登录态） |
| `%USERPROFILE%\fishidian\workspace\memory\dfy.db` | **她的记忆库**。新装是空的，聊几天就有了 |
| 桌面 `大肥鱼.lnk` | 双击开她的窗口 |

> 想装到别的盘（比如 `D:\fishidian`）也行，高级用法见 `FOR-AI.md` 的 `-TargetRoot`。**装到别处之后，本文下面所有 `%USERPROFILE%\fishidian\` 都换成你自己的安装根。**
>
> **记忆库位置是写死的**：`launch.ps1` 每次起窗口前会设三个环境变量 —— `FISHIDIAN_DB`（记忆库完整路径，就是上面那个 `workspace\memory\dfy.db`）、`FISHIDIAN_CORE`（内核目录）、`FISHIDIAN_PYTHON`（python 绝对路径）。所以**别去 `cordis.patch.yml` 里找这三样**：那里没有这些键，插件也不读，写上去不会生效。想换盘就整个重装，别手改配置。

---

## 装之前，先确认这四样都在

| 要有的东西 | 怎么确认 | 没有的话 |
|---|---|---|
| **DeepSeek Harness** | 开始菜单搜得到，且你登录过一次 | dsh.deepseek.com 下载安装。**DSH 账号和 Key 不用另外准备** —— 登录一次它就自己带着走了，安装器不会再问你 |
| **Node.js 18+** | 命令行敲 `node --version`，必须是 `v18.` 或更高 | nodejs.org 下 LTS 版。**这条是硬要求**：桥用到 `fetch` / `AbortSignal.timeout` / `structuredClone`，都是 Node 18 才有的内置 API —— 16 能装完，但 QQ 通道起不来 |
| **Python 3.8+** | 命令行敲 `python --version` | python.org 下 3.10 以上（3.8 也能跑，但装新的省事），安装时勾 **Add python.exe to PATH**。⚠️ 如果敲 `python` 会弹出微软商店，说明你装的是占位程序，不是真 Python |
| **DSH 当前没在运行** | 托盘里没有它的图标 | 右键退出，全部关掉再装 |

少一样，安装器会在第一步就告诉你缺哪个、去哪装，不会装一半坏掉。**版本不够也一样会当场拦住**，不会让你装完才发现 QQ 通不了。

### 关于 DSH 的账号和 API Key

**不用另外准备 Key，也不用去后台抄什么。**

DSH 的模型调用走的就是"你登录的那个账号"。登录一次之后，登录态存在本机，她的窗口启动时直接沿用 —— 安装器不会问你 Key，也不会把任何 Key 写进配置文件。

所以在新机器上只有一件事要做：

1. `dsh.deepseek.com` 下载 DSH，装
2. 打开它，用你的账号登录一次
3. 关掉它（**托盘图标也要右键退出**）
4. 回来装大肥鱼

第 3 步容易漏。DSH 关窗口不等于退出，托盘里还挂着进程，安装器会卡在第一步。

---

## 新机器上的完整顺序

1. 解压 zip（右键 → 全部解压缩）
2. 装 DSH（`dsh.deepseek.com`）→ 打开 → **登录一次** → 托盘图标右键退出
3. 装 Node.js 18+、Python 3.10+（机器上已经有的跳过）
4. 双击 `install.cmd`，按提示填机器人 QQ 号
5. 双击桌面「大肥鱼」→ 要用 QQ 就先装 NapCat（见第 3 步）→ 点右下角「连 QQ」扫码

除了第 1 步要等 1–3 分钟联网装依赖，其余都是几下点完。

---

## 四步装完

### 第 1 步：双击 `install.cmd`

黑框会滚一段字，看到 `装完了` 就成了。中间要联网装依赖，第一次大概 1–3 分钟，别关窗口。

它会问**两句**，都是 QQ 号，别弄混：

**第一句 · 机器人 QQ 号**（她的号）

- 想用 QQ 就填一个能登录的号 —— **这个号登在 NapCat 上，你就不能用手机 QQ 再登同一个号**
- 填的号必须是 **5–12 位纯数字**（真 QQ 号都满足）。带空格、全角数字、字母都会被判成"填错"，安装器当场提示并按未填处理（写占位 `0`），不会把坏号写进配置让你之后查半天
- 不想用 QQ 直接回车，装完照样能在窗口里聊；之后想加 QQ 也行，改 `cordis.patch.yml` 再重跑一次 `install.cmd`

**第二句 · 你的 QQ 号（白名单）**（谁的号能和她说话）

- 填**你自己**的号，不是上面那个机器人号
- 多个人用英文逗号分开，最多 5 个
- **这句不能省**。早期版本把这里默认成机器人自己的号，装完在 QQ 里发消息她一条都不回 —— 因为白名单里只有她自己。现在改成单独问，填错会当场提示

装完**安装根里会多出这几份文档**（就是你现在看的这份和它的同伴的副本）—— 以后不用回头翻压缩包：

```
README.md       使用手册：她怎么用、哪些配置能改
START-HERE.md   本文，从装到验收
FOR-AI.md       给 AI 看的安装 / 排错手册（要重装、要搬家时整个文件夹丢给 AI 就行）
VERSION.txt     这版装了哪几个模块、构建日期
README.txt      目录说明：workspace / logs / backup 各放什么
```

### 第 2 步：双击桌面「大肥鱼」

会先后发生两件事，别急：

1. 一个看不见的小服务起来（端口 8799，只监听本机，给窗口供二维码图）
2. 她的窗口弹出来 —— 第一次打开会让你填个称呼、给几条新手指引

窗口左下栏应该写着「大肥鱼」，配色和你平时用的 DSH 不一样。**这一步不需要任何授权。**

### 第 3 步：装 NapCat（只有要用 QQ 才做）

NapCat 是让她的 QQ 桥能连上真 QQ 的中间层，110 MB，**没有放进这个包**。原因就一个：它必须和本机 QQ 的版本对上，硬塞一个版本进去，你的 QQ 版本不对它就白装。

**先跑一次体检**：

```
powershell -NoProfile -ExecutionPolicy Bypass -File "%USERPROFILE%\fishidian\check_napcat.ps1"
```

它会报两个数：

```
NapCat     : C:\Users\你\NapCat
             按 QQ 9.9.22-40990 做的，目标 build 40990
QQ         : D:\QQ\QQ.exe
             文件版本 9.9.19.35469，build 35469
```

**这两个数不一致，不代表一定不能用**。实际见过两个数对不上、照样正常出码的情况。所以判断顺序是：

1. 两个数一致 → 直接用
2. 不一致 → **先真起一次，看二维码出不出来**（按第 4 步点「连 QQ」，看浮层里有没有码）
3. 出得来 → 继续用
4. 出不来 → 去 [NapCat 的 Releases 页](https://github.com/NapNeko/NapCatQQ/releases)，翻到对应你这版 QQ build 的 release，换那个 NapCat 版本

**为什么要这么绕**：NapCat 每个 release 页都写它支持的 QQ build 范围（比如 v4.18.37 写覆盖 40768–53644），这个范围每版都在变。写死在任何脚本里都会过期，所以脚本只报数、不下结论，判断留给看 release 页的人（或者你的 AI）。

**NapCat 装到哪**：解压 `NapCat.Shell.zip` 到 `%USERPROFILE%\NapCat`，确保里面有 `launcher.bat`。装到别处也行，改一下 `check_napcat.ps1` 的扫描位置就好。

### 第 4 步：窗口里点右下角「连 QQ」

点了会出一个二维码浮层，用手机 QQ 扫。

- **码大概一分钟就过期**。浮层上写着「这个码可能过期了，点一下刷新」就点一下
- 第一次会弹一次 **UAC 授权框**（管理员权限）。这是 NapCat 要注入 QQ 进程，Windows 规定必须本人点，绕不过
- 扫上之后，手机 QQ 上就登录了这个机器人号。**别再拿手机 QQ 登同一个号**，会把它顶掉

---

## 验收：怎么算装对了

### 先跑一次自动验证

装完在同一个命令行里跑：

```
powershell -NoProfile -ExecutionPolicy Bypass -File "%USERPROFILE%\fishidian\verify_install.ps1"
```

它只读不写，逐项报：Node / Python 版本够不够、安装根的文件齐不齐、三个插件有没有链进 profile、桥的 `ws` 装没装上、`cordis.patch.yml` 里的 QQ 号是不是还是占位 `0`、内核跑不跑得起来、桌面快捷方式在不在。

最后一行是汇总：

- **失败 0** → 窗口这块没问题，可以往下看人工核对
- **有失败** → 按每条提示改；改完重跑 `install.cmd`（不会覆盖记忆库），再跑一次这个验证
- **只有「注意」** → 不影响开窗口，但可能影响 QQ 通道（最常见的是 `ws` 没装、QQ 号还是 0）

装到别处时加参数：`-TargetRoot "D:\fishidian"`。

### 再人工核对四条

脚本能判的都判了，剩下这几条只有人看得出来：

1. **窗口能开**：双击桌面「大肥鱼」，出现一个和你的 DSH 长得不一样、配色偏深的窗口，左下栏写着「大肥鱼」
2. **她的记忆库在原地长大**：和她聊几句，过一会儿看 `%USERPROFILE%\fishidian\workspace\memory\dfy.db` 的文件大小有没有变
   - 没变的话，先看一眼 `%USERPROFILE%\.dsh\fishidian-memory\` 有没有多出 `fishidian.db`。出现了就说明 `launch.ps1` 的环境变量没生效（通常是没从桌面「大肥鱼」进、而是自己另起了 DSH），这个库里的记忆不会和她窗口里说的对上
3. **两套是分开的**：打开工作 DSH，在那边随便说几句 → 回到她的窗口问她「我刚才在工作窗口说了什么」→ 她应该答不上来
4. **QQ 通了**（如果装了）：QQ 里给机器人号发条消息，她的窗口里应该能看到会话；她的回复会出现在 QQ 里

---

## 出问题看这里

**「pnpm install 失败」**
九成是网络。换网络或开代理，再双击一次 `install.cmd`（重复装是安全的，不会覆盖你的记忆库）。
装的过程中会顺带装一个叫 `ws` 的小包（桥要用），装完这一步就好了 —— 桥不需要别的包。

**装到「DSH 正在运行」就停了**
DSH 还开着。右下角托盘图标右键 → 退出，把它的进程全部关掉（任务管理器里搜 `DeepSeek Harness` 也要没有），再双击一次 `install.cmd`。

**窗口开了，但没有「连 QQ」按钮**
皮肤插件没挂上。检查 `%USERPROFILE%\fishidian\data\profiles\desktop\node_modules\dsh-client-ui-fatfish` 在不在。不在就跑一次 `install.cmd`。

**点了「连 QQ」是白框**
二维码服务没起来，或者 NapCat 还没写码。按顺序查：
- 任务管理器里有没有一个 `node.exe` 命令行带 `qq-qrcode-server.js`
- `%USERPROFILE%\NapCat\cache\qrcode.png` 在不在
- 都没有 → NapCat 没起，见第 3 步

**QQ 发了消息她不理**
按顺序查：
- `check_napcat.ps1` 报的 build 对不对得上
- 发消息的号在不在白名单里（`%USERPROFILE%\fishidian\data\profiles\desktop\cordis.patch.yml` 的 `allowUsers`）
- 桥默认只在她被 @ 到的时候回（`replyOnlyWhenMentioned: true`）—— 群里要先 @ 她

**她像失忆了：记不住前面说的话、五行和情绪也不动**
这是最容易被误当成"她性格就这样"的问题：内核其实没跑起来，但**不报错**，只是每轮都当第一次聊天。按顺序查：
1. 跑 `verify_install.ps1`，看「4.5 内核路径」那几条有没有 `[FAIL]`（这段专查这件事）
2. 有没有从**桌面「大肥鱼」**进？自己另起一个 DSH 窗口的话，`launch.ps1` 的环境变量没设，记忆库会落到别处
3. `%USERPROFILE%\fishidian\workspace\memory\dfy.db` 在不在长大；`%USERPROFILE%\.dsh\fishidian-memory\` 有没有多出来的 `fishidian.db`（有就是路径跑偏了）
4. 安装根里有没有 `python-path.txt`。没有的话 `launch.ps1` 只能找裸 `python`，而窗口进程的 PATH 未必有它 —— 重跑一次 `install.cmd` 会补上

**装完想重装**
直接再双击 `install.cmd`。它不会删 `workspace\` 和 `backup\`，**你的记忆库不会被覆盖**。

**想彻底卸载**
删掉 `%USERPROFILE%\fishidian\` 整个目录，再删桌面快捷方式。
**注意：这会连记忆库一起删掉**，想留着就先备份 `workspace\` 和 `config\` 两个目录。

---

## 目录速查（想手动改东西时看）

```
%USERPROFILE%\fishidian\
├── START-HERE.md              本文
├── README.md                  使用手册
├── FOR-AI.md                  给 AI 的安装 / 排错手册
├── VERSION.txt                这版装了哪些模块
├── README.txt                 目录说明
├── fishidian-core\            她的内核（Python）
├── dsh-fishidian\             她的插件
├── dsh-client-ui-fatfish\     窗口皮肤
├── dsh-qq-onebot-bridge\      QQ 桥
├── tools\qq-qrcode-server.js  二维码小服务
├── launch.ps1                 双击快捷方式实际跑这个
├── run-fishidian.cmd          同上的命令行版
├── check_napcat.ps1           QQ 通道体检
├── data\profiles\desktop\     ★ 要改配置就改这里
│   ├── cordis.patch.yml         QQ 号 / 白名单 / 主动发消息时段
│   └── package.json             挂了哪几个插件
├── workspace\memory\dfy.db    ★ 她的记忆库，重装不覆盖
├── workspace\sessions\        对话记录
├── config\setup.json          称呼等首启信息
├── logs\                      日志
└── backup\                    备份
```

**装到别处了？** 上面所有路径里的 `%USERPROFILE%\fishidian\` 换成你的安装根就行。`launch.ps1` 会先看自己所在的目录找数据，不会认错。
