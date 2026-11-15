# 从 GitHub 直接装，能到什么程度

> 实测日期 2026-11-14。结论来自实际跑过一遍的结果，不是推测。

## 一句话结论

**「把链接丢给 DSH，它自己装完」这条路走不通。**
不是网络问题，是机制问题：DSH 的插件安装只是把参数转给 pnpm，而 pnpm 装 GitHub 上的包时会**拦下安装期构建脚本**，必须先在 profile 里手写一个白名单文件才放行。

**能做到的是「一条命令 + 一个脚本」**：JS 插件由 `dsh plugin add` 装，Python 内核 / 启动器 / 独立窗口由脚本补。

## DSH 里"装插件"到底是什么

DSH 带一个 CLI，位置在：

```
%LOCALAPPDATA%\Programs\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd
```

它只有两个用法：

```
dsh [--profile] <name> [options]          # 启动一个 profile
dsh plugin --profile <name> <pnpm-args...> # 管这个 profile 的插件
```

`dsh plugin` 自己不做任何事，**把后面的参数原样转给 pnpm**，在 profile 目录里执行。所以：

```
dsh plugin --profile desktop add github:用户名/仓库名
```

等于在那个 profile 里跑 `pnpm add github:用户名/仓库名`。

装完还要**在 profile 的 `package.json` 里登记**，插件才会被加载：

```json
{
  "dependencies": { "某插件": "..." },
  "dsh": { "profile": { "bundles": ["@deepseek-ai/dsh-base", "...", "某插件"] } }
}
```

`pnpm add` 会自动写 `dependencies`，但 `dsh.profile.bundles` 是 DSH 自己的字段，**需要有人写进去**。

## 哪些能这么装，哪些不能

| 组件 | 能不能 `dsh plugin add` | 卡在哪 |
|---|---|---|
| QQ 桥（`dsh-qq-onebot-bridge`） | 能，但**装到的是上游原版** | 上游没有 fishidian 补丁，装上也没有 `/记忆` `/天气`。带补丁的版本得自己发一个仓库 |
| 她的插件（`dsh-fishidian`） | 能（前提是发到 npm，或用 `github:` 指仓库） | 这个仓库里有源码，但没发到 npm，所以只能用 `github:AnJianY00/fishidian` 或 `link:` 指向本地目录 |
| 窗口皮肤（`dsh-client-ui-fatfish`） | 同上 | 同上，仓库里有源码、没发到 npm |
| 内核（`fishidian-core`） | **不能** | 是 Python 包，pnpm 管不了 |
| 启动器 exe | **不能** | 需要编译好的二进制，不是包 |
| 独立窗口的数据根 | **不能** | 靠 `DSH_HOME` 环境变量，插件体系之外 |
| `cordis.patch.yml`（QQ 号、白名单、内核路径） | **不能** | 配置文件，得写进去 |

**六个组件里只有一个能纯靠链接装，而且装上来还是没打过补丁的原版。**

## 实测撞到的三道坎

### 第一道（最硬）：pnpm 拦构建脚本

真跑一次的结果是停在这儿：

```
dsh: git-hosted plugins build on install via their prepare script,
which pnpm blocks until allowed — add the exact key pnpm printed above
under allowBuilds in <profile>\pnpm-workspace.yaml, then re-run
```

意思是：从 GitHub 装的插件要先跑 `prepare` 脚本，pnpm 默认不让跑，**必须在 `pnpm-workspace.yaml` 里手写一条 `allowBuilds` 白名单，再重跑第二遍**。

也就是说，第一次安装**必然失败**，流程是「跑到报错 → 抄下 pnpm 打印的 key → 手改 YAML → 再跑」。这不是自动化，是两步人工。

#### 这个"白名单"到底是什么

pnpm 是 Node 的包管理器。它有一个安全默认：**不执行依赖包自带的 `prepare` / `postinstall` 这类构建脚本**。

理由很实在 —— 这类脚本在安装时以你的身份跑任意命令。`event-stream`、`ua-parser-js` 那几次投毒事件就是靠这个偷密钥、装后门。所以 pnpm 把它们拦下来，要求你**逐个点名放行**。

从 Git 仓库装的包，上游一般把"生成产物 / 编译"放在 `prepare` 里，于是：

1. 第一次 `add` 跑到一半停下，打印出**它要求放行的那个精确 key**（形如 `包名@版本`）
2. 你把这个 key 抄进 profile 的 `pnpm-workspace.yaml`：

```yaml
allowBuilds:
  dsh-qq-onebot-bridge@0.8.9: true
```

3. 再跑一次，才装得上

所以它不是"选填配置项"，而是**一道强制人工确认的安全闸** —— pnpm 不会替你判断"这个包我信得过"。这也是为什么「把链接丢给 DSH 自己装」做不到：中间必须有人签一次字。

### 第二道：只覆盖 JS

就算白名单过了，能装的也只是 `package.json` 里那种 JS 插件。Python 内核、启动器、独立数据根都在插件体系外面，`dsh plugin` 碰不到。

### 第三道：网络要能连 github.com

pnpm 解析 `github:` 依赖用的是 HTTPS + `git ls-remote`。试的时候网络走了代理，直接被挡：

```
Failed to connect to github.com:443 over proxy 127.0.0.1
```

这条换机器可能就没有，但说明**这条路依赖你安装的那台机器能直连 GitHub**，比下载 zip 更挑网络。

## 关于"DSH 会不会把自己改坏"

这个担心不成立，因为**「改窗口」从头到尾没有动用过 DSH 安装目录**。

真实的做法是：给同一个 `DeepSeek Harness.exe` 换一套自己的数据根再拉起一次。

```
DSH_HOME=%USERPROFILE%\.dsh-fatfish
--user-data-dir=%USERPROFILE%\.dsh-fatfish\electron-data
```

- 程序本体还是原来那个，一个字节都没动
- 新窗口的配置、插件、会话、记忆都在 `~\.dsh-fatfish\` 里
- 工作 DSH 用的 `~\.dsh\` 完全不受影响

所以「改坏了修不回来」的风险不存在 —— 最坏的情况是删掉 `~\.dsh-fatfish\` 重新建一遍，工作窗口照样好好的。

这也解释了为什么不能只靠 `dsh plugin`：**它管的是某个 profile 里的 JS 插件，管不了「用哪套数据根起窗口」这件事。**

## 那到底该怎么做

**推荐仍然是现在这条：下载 zip → 双击 `install.cmd`。**

理由很实在：

- 一次性把六件事全做完（三个插件链进 profile、内核复制到位、`cordis.patch.yml` 写好、启动器落地、快捷键建好、依赖装上）
- 失败点集中在一个脚本里，日志一处可查
- 不挑网络（zip 能传过来就能装）
- 用户只需要点两下

**如果确实想走 GitHub**，可行形态是「一个 `install.ps1` 从 GitHub 拉」而不是「一条链接丢给 DSH」：

1. 脚本先 `dsh plugin --profile <名字> add <三个包的 GitHub 地址>`
2. 撞到 `allowBuilds` 报错 → 脚本读 pnpm 打印的 key，写进 `pnpm-workspace.yaml`，**自动重跑一次**
3. 其余（内核、启动器、配置）脚本自己做

这仍然是个脚本，只是脚本的来源从 zip 变成了 `raw.githubusercontent.com`。**换来的是「永远拿最新」，代价是「每次装都可能因为上游改动而失败」。**

## 一句话结论

想让别人装，**发 zip 最省事**；想让懂技术的人自己搞，**发仓库地址 + 让他跑 install 脚本**。
指望「丢个链接 DSH 就自己装好」，现在做不到，卡在 pnpm 的构建脚本白名单上。
