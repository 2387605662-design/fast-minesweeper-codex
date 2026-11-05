# 快速扫雷 · Fast Minesweeper

在 Windows 上用 Codex 操作经典 XP 扫雷。插件只截取指定的游戏窗口，通过窗口消息点击棋盘。支持初级、中级和高级，以及全插旗、选择性插旗和不手动插旗三种策略。

## 安装

需要 Windows、Python 3.10+ 和自行准备的经典 XP 扫雷程序。自动整局还需要 Node.js 18+。打开扫雷并保持窗口处于非最小化状态。

在仓库根目录安装 Python 依赖并添加本地插件市场。

```powershell
python -m pip install -r plugins/fast-minesweeper/skills/fast-minesweeper/scripts/requirements.txt
codex plugin marketplace add .
```

重启桌面客户端，在插件目录中选 **Fast Minesweeper**，然后安装同名插件。可以对 Codex 说「检查当前 XP 扫雷盘面」「只标记确定的雷」或「用选择性插旗玩一局初级」。第一次使用时提供本机扫雷 EXE 的完整路径。

## 直接运行

```powershell
$runner = 'plugins/fast-minesweeper/skills/fast-minesweeper/scripts/run.py'
$game = 'C:\Games\winmine.exe'
python $runner inspect --exe $game
python $runner flag --exe $game
python $runner step --exe $game
python $runner play --exe $game --difficulty beginner --strategy selective --screenshot winmine-result.png
```

`inspect` 只读盘面。 `flag` 插旗， `step` 只打开一个可证明安全的格子， `play` 会重新开局。默认遇到必须猜的局面就停，加上 `--allow-guess` 可按最低雷率继续。计时从最终采用的开局首点开始，到脚本确认胜负为止。

仓库提供插件源代码。游戏程序和线上排行榜分别由其原作者提供。
