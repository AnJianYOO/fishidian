# dsh-client-ui-fatfish

大肥鱼的界面身份插件。把 DeepSeek Harness（DSH）左侧栏顶部的品牌位——
官方那个鲸鱼标 + `deepseek HARNESS`——换成她的小鱼标 + `大肥鱼`。

只改外观，不改任何功能、不碰会话、不碰记忆库。

---

## 一、它改了哪里

DSH 的界面是插件化的，左侧栏预留了两个插槽：

| 插槽 | 官方占位 | 本插件换成 |
| --- | --- | --- |
| `sidebar.brand.mark` | 鲸鱼 SVG | 粉色小鱼 SVG |
| `sidebar.brand.name` | `deepseek HARNESS` | `大肥鱼` |

实现方式与官方 `dsh-client-ui-brand-official` 同构：浏览器侧 `inject = ["slots"]`，
用 `ctx.slots.inject` + `ctx.slots.register` 覆盖同一插槽。后者注册的组件会盖住先注册的，
所以不需要「禁掉官方插件」，也不会影响它。

---

## 二、文件构成

```
dsh-client-ui-fatfish/
├── package.json        插件清单（含 dsh.bundle / dsh.client 两段声明）
├── cordis.patch.yml    bundle patch：把自己插进 DSH 的配置树
└── lib/
    ├── index.js        宿主侧（Node）入口，只有一个空 apply + 一个加载探针
    └── client.js       浏览器侧，画小鱼 + 写「大肥鱼」三个字
```

开发时用 junction 把源码目录挂进 `~/.dsh/profiles/desktop/node_modules/dsh-client-ui-fatfish`，改完源码重启 DSH 才会生效。

---

## 三、怎么装（换一台机器时照这个做）

三个条件缺一不可 —— **都是踩过坑才知道的**：

1. **包必须是 bundle**：`package.json` 的 `dsh.bundle.patch` 指向自己的
   `cordis.patch.yml`，里面用 `- insert:` 把自己挂进配置树。
   只把包名写进 `dsh.profile.bundles` 而不给 `dsh.bundle.patch`，DSH 不会加载它。
2. **必须进 pnpm 依赖树**：只手工建 junction 不够，DSH 不认。
   在 profile 目录跑一次 `pnpm install`，让 lock 里有记录。
3. **浏览器侧组件必须用 `react/jsx-runtime`**，不能 `require("react")`。
   DSH 的 web 模块表里只有 `jsx-runtime`，用 `react` 会抛错、
   而且错误是静默的——界面照常显示，只是皮肤不生效，极难排查。

完整步骤：

```powershell
# 1) 把包放好（或 junction 到源码目录）
# 2) profile 的 package.json 里加两处：
#      dependencies: "dsh-client-ui-fatfish": "link:C:/Users/你的用户名/dsh-client-ui-fatfish"
#      dsh.profile.bundles: 末尾加 "dsh-client-ui-fatfish"
# 3) 关掉 DSH，跑 pnpm install（约 60 秒）
$pnpm = (Get-ChildItem -LiteralPath "$env:LOCALAPPDATA\Programs\DeepSeek Harness\resources\runtime\primary-runtime\dependencies\pnpm\bin" -Filter "pnpm.cjs").FullName
Set-Location "$env:USERPROFILE\.dsh\profiles\desktop"
node $pnpm install --prefer-offline --config.confirmModulesPurge=false
# 4) 启动 DSH
```

---

## 四、怎么开关（现成的双击入口）

项目根目录下有两个 `.cmd`，双击即可：

| 文件 | 作用 |
| --- | --- |
| `还原DSH皮肤.cmd` | 撤掉皮肤，左栏恢复官方 `deepseek HARNESS` |
| `再打开DSH皮肤.cmd` | 重新打开皮肤 |

两者都会自动重启 DSH（约 40 秒）。

背后的脚本在 `tools/restore_dsh_skin.ps1` 与 `tools/apply_dsh_skin.ps1`，
逻辑完全对称：**只是把 `profiles\desktop` 里的 `package.json` 与 `cordis.patch.yml`
两个文件换成另一份，然后重启**。

`node_modules` 里的插件链接**故意保留**：不列进 bundle 列表时它永远不会被加载，
留着它可以让「再打开」只是一次文件复制，不必重装依赖。

---

## 五、怎么确认它到底加载了没有

**别用 HTTP 猜**。DSH 的本地 web 端口上
`/plugins/<包名>/client.js` 对**所有**插件都返回 404（含官方插件），
首页 `/` 返回 401（要登录态），这个方法测不出任何东西。

可靠的办法有两个：

1. **看界面**：左栏顶部是 `deepseek HARNESS` 还是 `大肥鱼`。
2. **看探针日志**：`~/.dsh/fatfish-ui-load.log`。
   宿主侧 `apply()` 被调用时会追加一行 `apply-called pid=...`。
   有这行 = 宿主侧加载成功，问题只可能在浏览器侧；
   没有这行 = 连包都没被加载，回头检查 bundle 与依赖树。

---

## 六、踩过的弯路（别再重复）

| 尝试 | 结果 | 原因 |
| --- | --- | --- |
| 只在 profile 的 `cordis.patch.yml` 末尾写 `- insert:` | 不生效 | profile patch 是给**已存在的 id** 改配置用的，不是新插件的入口 |
| 只把包名加进 `dsh.profile.bundles`，不给 `dsh.bundle.patch` | 不生效 | 没有 bundle patch 就不会插进配置树 |
| 手工 `New-Item -ItemType Junction` 建依赖，不跑 pnpm | 不生效 | DSH 只认 pnpm 依赖树 |
| 跑完 pnpm 但仍用 `require("react")` 画组件 | 不生效（静默） | web 模块表里只有 `react/jsx-runtime` |
| 用 web 端 `/plugins/<包>/client.js` 探测 | 永远 404 | 路径对所有插件都 404，本方法无效 |

另外：`pnpm install` 会把不在依赖树里的 `ws` 挪到 `node_modules\.ignored\ws`，
控制台会打一行 `[WARN] Moving ws to "node_modules\.ignored\ws"`。这是 pnpm 的正常提示，
不是皮肤插件造成的。

---

## 七、下一步

- 现在只换了左栏品牌位，属于「一眼认出这是她的地方」的最小版。
- 要更像她的专属界面，下一步可以往下做：
  - 换配色 token（全站走 `--dsw-alias-*` / `--dsw-specific-sidebar-fill`）
  - 左栏加她的情绪条 / 状态行
  - 工作区分区：一个工作区叫「大肥鱼」、一个叫「工作」
- 这三项做完再谈打包进安装包。
