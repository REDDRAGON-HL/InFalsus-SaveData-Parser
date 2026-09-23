# In Falsus 存档解析工具

把In Falsus的存档读成一份可读的 JSON

读出来的内容包括：**成绩记录**、**卡牌**、**各遭遇保存过的卡组**、**粒子库存**、**剧情进度**、**六边形网格**、**已解锁的配方加成区域**、配方 id 与全文件字符串

> **免责声明**
>
> 本工具仅供个人学习研究使用，请勿用于商业用途或未经授权的传播。
> 
> 使用本工具提取的任何资源，其所有权和著作权均归属于游戏原始开发者/发行方，请遵守相关法律法规和用户协议。
>  
> 因使用本工具所引发的任何法律后果、数据丢失、或对游戏文件造成的损坏，作者概不负责。
> 使用前请确认您有权访问和备份相关游戏文件！

---

## 需要的数据

工具自带几张数据表（歌名、卡名、配方名、特性名、粒子类型、故事 id、加成区域），
来自 **<https://github.com/REDDRAGON-HL/InFalsus-Resource>** 的 `output/info/`

**游戏更新后想更新它们**：把下面这 4 个文件拷到本目录，然后运行 `refresh_tables.py`

| 需要的文件                    | 提供什么               |
| ----------------------------- | ---------------------- |
| `songs.json`                  | 歌名                   |
| `dynamic_string_mapping.json` | 卡名 / 配方名 / 特性名 |
| `recipe_specifications.json`  | 粒子类型表、加成区域表 |
| `story_details.json`          | 故事 id → 条目下标     |


### 存档位置

```
%USERPROFILE%\AppData\LocalLow\lowiro\infalsus\<SteamID64>\release\savestate_V3.sav
```


---

## 运行

```bash
python savefile.py                     # 摘要 + 导出 save_export.json
python savefile.py --cards             # 卡牌表
python savefile.py --decks             # 各遭遇保存过的卡组
python savefile.py --iotas             # 粒子库存
python savefile.py --grids             # 配方网格
python savefile.py --json 别的名.json   # 改导出文件名
python savefile.py --save <路径>        # 指定存档文件
python savefile.py --raw cyaegha       # 某首歌载荷的逐字节 + u16/u32 视图
python savefile.py --strings           # 列出全部字符串（含偏移）
python savefile.py --map               # 文件分区图
python savefile.py --diff A.sav B.sav  # 比对两份存档
```

## 导出的 JSON

顶层字段：

| 字段                | 说明                           |
| ------------------- | ------------------------------ |
| `file` / `size`     | 存档路径与字节数               |
| `recordArrayOffset` | 成绩记录数组的起始偏移         |
| `songs`             | 成绩记录，见下                 |
| `cards`             | 卡牌                           |
| `decks`             | 各遭遇的卡组                   |
| `iotas`             | 粒子库存                       |
| `storyProgress`     | 剧情进度                       |
| `hexGrids`          | 六边形网格                     |
| `guids`             | 已解锁的配方加成区域 GUID      |
| `bonusAreas`        | 上面那批 GUID 的解读版         |
| `recipeIds`         | 已解锁的配方 id                |
| `strings`           | 全文件扫出来的字符串（含偏移） |

下面各字段表里**带 🟡 的表示语义未完全确认**

### songs（成绩记录）


| 字段              | 说明                                                                                 |
| ----------------- | ------------------------------------------------------------------------------------ |
| `songId`          | 歌曲编号                                                                             |
| `baseName`        | 歌曲文件名                                                                           |
| `difficultyFlag`  | 难度标志位，`1/2/4/8` = `1 << 难度`                                                  |
| `difficultyIndex` | 难度序号（0 基）                                                                     |
| `score`           | 分数                                                                                 |
| `maxCombo`        | 最大连击                                                                             |
| `lamp`            | 通关状态：`0` 无 / `1` Fail / `2` Clear                                              |
| `resultClear`     | 完成结果：`0` 无 / `1` DiveFailed / `2` DiveCleared / `3` FullLink / `4` PerfectDive |
| `paceValue`       | 该局算出的 pace 值                                                                   |
| `counts`          | **八个判定档位**的分类型计数，见下                                                   |
| `exactPlus`       | EXACT+ 的分类型计数，是 `counts` 里的 `shiny`                                        |
| `judgementTotal`  | 每个类型的**判定点总数**                                                             |
| `payloadHex`      | 这条记录的原始载荷（hex），想自己核对时用                                            |

`counts` 与 `exactPlus` 都是按类型分组的对象，键是
**`tap` / `hold` / `skyArea` / `flick`**（即 Field）
每个类型下有八个档位：

| 档位                           | 含义                         |
| ------------------------------ | ---------------------------- |
| `shiny`                        | EXACT+                       |
| `perfectEarly` / `perfectLate` | EXACT                        |
| `nearEarly` / `nearLate`       | NEAR                         |
| `miss`                         | MISS                         |
| `none`                         | 该类型里没有产生判定的判定点 |
| `unused`                       | 保留字段，实测为 0           |


### cards（卡牌）

| 字段                                                 | 说明                                                     |
| ---------------------------------------------------- | -------------------------------------------------------- |
| `slot`                                               | 槽位号（0 基，按获得顺序）                               |
| `cardId`                                             | 卡牌实例 id                                              |
| `recipeId`                                           | 配方 id，查 `dynamic_string_mapping.json` 可得卡名       |
| `tier`                                               | 等级减一（`tier: 2` 即 3 级）                            |
| `isSR`                                               | 是否 SR（0/1）                                           |
| `color`                                              | 颜色：**1 红 / 2 黄 / 3 绿 / 4 蓝 / 5 紫**               |
| `attack` / `defense`                                 | 攻 / 防数值                                              |
| `hasTrait`                                           | 是否装了特性                                             |
| `traitIds`                                           | 三个特性槽的 id；`65535` = 空槽，`0` = 未装，`>0` = 已装 |
| `traitSlotTypes`                                     | 🟡 三个槽的"类型"字节（多数为 0，语义未确认）             |
| `createdAt` / `createdAtText`                        | 创建时间（Unix 秒 / UTC 文本）                           |
| `nameEnglish` / `nameSimplified` / `nameTraditional` | 卡名                                                     |

### decks（各遭遇的卡组）

| 字段                  | 说明                                                     |
| --------------------- | -------------------------------------------------------- |
| `header`              | 🟡 卡牌数组之间的一个整数                                 |
| `count`               | 记录条数                                                 |
| `records[].index`     | **遭遇 id**（记录按遭遇顺序排，下标即遭遇）              |
| `records[].cardSlots` | 该遭遇保存的卡组：**5 个卡槽**，每槽是卡牌 id，`-1` = 空 |
| `records[].flag`      | 🟡 实测 0/1，疑似"是否已指派给该遭遇"                     |

只列**非空**记录

**已删除的卡牌在cardSlots中id也显示为-1**

### iotas（粒子库存）

库存是 1024 个固定槽位，这里按"堆"给出

| 字段                                | 说明                                                          |
| ----------------------------------- | ------------------------------------------------------------- |
| `base` / `slots` / `used` / `total` | 数组起始偏移 / 槽位数 / 非空堆数 / 粒子总数                   |
| `stacks[].offset`                   | 这条记录的文件偏移                                            |
| `stacks[].baseIotaId`               | 粒子类型 id（1..40）                                          |
| `stacks[].baseIotaName`             | 粒子名，如 `r-2-1`（字母 = 颜色 r/y/g/b/p，后面是等级和序号） |
| `stacks[].baseColor`                | 颜色编号（1 红 / 2 黄 / 3 绿 / 4 蓝 / 5 紫）                  |
| `stacks[].baseTier`                 | 粒子等级                                                      |
| `stacks[].baseSize`                 | 形状占几个六边形格                                            |
| `stacks[].potency`                  | 效能                                                          |
| `stacks[].traitIds` / `traitNames`  | 装了的特性 id 与英文名                                        |
| `stacks[].freeTraitSlot`            | 剩余特性槽数                                                  |
| `stacks[].traitCount`               | 已装特性数                                                    |
| `stacks[].count`                    | 这一堆的数量                                                  |

### storyProgress（剧情进度）

| 字段           | 说明                                                      |
| -------------- | --------------------------------------------------------- |
| `id` / `idHex` | 故事条目的标识                                            |
| `storyIndex`   | 在 `story_details.json` 的 `orderedStoryEntries` 里的下标 |
| `value`        | 🟡 该条目的进度值                                          |

### hexGrids（制卡网格）

制卡时的网格（配方的已揭示格子）

| 字段          | 说明                                                    |
| ------------- | ------------------------------------------------------- |
| `offset`      | 这段网格的文件偏移                                      |
| `cellCount`   | 格子数                                                  |
| `filledCount` | 🟡 有值的格数                                            |
| `cells[]`     | 🟡 每格 `{q, r, s, fill}`；`fill` 实测恒为 0，语义未确认 |

### guids 与 bonusAreas（已解锁的配方加成区域）

`guids` 是存档里那批 36 字符 GUID。它们全部是
`recipe_specifications.json` 里 `sparseRecipes[].BonusAreas[].Id`，
也就是**已经解锁的配方加成区域**

`bonusAreas` 是同一批数据的解读版（顺序与 `guids` 一致）：

| 字段                                      | 说明                                            |
| ----------------------------------------- | ----------------------------------------------- |
| `guid`                                    | 加成区域自身的 GUID（= `guids` 里的那一项）     |
| `recipeId` / `recipeIdStr` / `recipeName` | 它属于哪个配方（编号 / `1-1-a` 式 id / 英文名） |
| `areaIndex`                               | 是那个配方里的第几个加成区域（0 基）            |
| `cells`                                   | 该区域由几个六边形格子组成                      |
| `effects`                                 | 该区域带几个加成效果                            |
