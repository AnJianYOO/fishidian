小鱼 · 目录说明

workspace\   你的工作区和她的记忆都在这里
  memory\      记忆库 dfy.db 与每日快照
  sessions\    对话记录
  notes\       她写给你的东西
  files\       你发给她的附件

data\        程序运行数据（不要手动改）
logs\        日志，按天切分
  app\         运行日志   保留 7 天
  error\       报错日志   保留 30 天
  bridge\      QQ 桥记录  保留 7 天
  audit\       敏感操作   保留 90 天
backup\      备份
  daily\       每天一份，保留 7 份
  weekly\      每周一份，保留 4 份
  manual\      你手动留的，不会自动删
config\      可手改的配置

备份：整体复制 workspace 和 config 两个目录即可。
卸载程序不会删除 workspace 和 backup。