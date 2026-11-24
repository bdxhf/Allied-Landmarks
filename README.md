# 盟约地标 · Allied Landmarks

《全面战争：战锤 3》单人战役模组。在防御同盟、军事同盟或直属仆从国持有的适配城市里，玩家可以使用独立的境外槽建造地标。支持超凡帝国与超凡帝国拓展（IEE）。

## 安装与使用

下载仓库中的 `allied_landmarks.pack`，放到游戏的 `data` 目录，在模组管理器里启用。完全重启游戏后，进入或继续战役，点选符合条件的城市，并通过城镇面板右下方的境外建筑视图查看地标。

首版成品由游戏 9.0.5 和开发时启用的创意工坊模组清单生成。来自其他模组的建筑需要相应模组提供原始数据。自定义效果和任务脚本的兼容性取决于它们的实现。首版通过了成品数据回读与 Lua 模拟，赫斯欧塔和失陷之门的最新建造修正仍待实机复测。

## 本地构建

准备 Python 3.9 或更新版本、`zstandard`、`lz4`，以及 RPFM 下载的战锤 3 数据表 schema。安装或调整地标模组后，用目标模组清单启动并退出游戏，让游戏写出 `used_mods.txt`。

在仓库根目录运行：

```powershell
$env:WH3_GAME_DIR = 'D:\SteamLibrary\steamapps\common\Total War WARHAMMER III'
python -m pip install zstandard lz4
python tools/wh3_build_alm.py
python tools/verify_sharing.py
```

`WH3_GAME_DIR` 指向包含 `data` 和 `used_mods.txt` 的实际游戏目录。`WH3_SCHEMA_PATH` 可指向自定义的 `schema_wh3.ron` 文件。构建会在仓库根目录生成 `allied_landmarks.pack` 与可供检查的 `allied_landmarks.lua`。

## 版本存档

每个版本将生成器源码和该版本的 `.pack` 一起提交，再为提交创建版本标签。标签和分支都推送到 GitHub，旧版本可通过对应标签找回。
