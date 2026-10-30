# CAD — 零件 / 装配体结构版

方案二的结构模型，按**机械设计习惯**组织：**总装 → 子装配 → 零件 → 特征**。

> **推荐用 SolidCraft 版**：`cad/solidcraft/prismtv.solidcraft`
> 原生参数化时间线 + 36 个命名参数，改一个数整机重建。
> 说明见 **[solidcraft/README.md](solidcraft/README.md)**。
> FreeCAD 版保留作为对照与出工程图（FreeCAD 的 TechDraw 可视化更成熟）。

> 怎么改 FreeCAD 版 → **[MODIFY.md](MODIFY.md)**

---

## 1. 文件

```
cad/
├── solidcraft/               # ★ 推荐：SolidCraft 参数化版
│   ├── prismtv.solidcraft     原生设计（双击打开）
│   ├── prismtv.design.json    纯文本版设计
│   ├── prismtv.step           STEP AP242
│   ├── prismtv.json           生成脚本
│   ├── prismtv.png            预览
│   └── README.md              怎么在 SolidCraft 里改
├── build_solidcraft.py       # 生成 SolidCraft 设计
├── build_assembly.py         # FreeCAD 零件+装配体
├── make_drawings.py          # 工程图（零件图/装配图）
├── MODIFY.md                 # FreeCAD 版怎么改
├── build_v1_vertical.py      # 历史版本
├── build_v2_tilt30.py
├── build_prototype.py
└── out/                      # FreeCAD 版产物
    ├── PrismTV_Assembly.FCStd
    ├── PrismTV_Assembly.step
    ├── stl/                       # 43 个零件 STL
    ├── 图纸/                      # P01/P02 零件图 + 装配图
    └── render/
```

## 2. 运行

```bash
# 建模 + 导出（无界面即可）
freecadcmd cad/build_assembly.py

# 生成工程图
freecadcmd cad/make_drawings.py

# 顺便渲染效果图（需要 X）
DISPLAY=:1 freecad cad/build_assembly.py
```

## 3. 树结构

```
PrismTV_总装
├── ASM-01 外壳组件
│   └── P01 外壳底座      ← Part::Fillet
│       └── CUT_透光孔 → CUT_USBC → CUT_前槽 → CUT_内腔
│           └── EX_外壳毛坯 (Part::Extrusion)
│               └── SK 外壳侧剖面 (Sketch)   ← 侧剖面在这里改
├── ASM-02 光学头组件      ← Placement 里带 −30° 后仰
│   ├── P02 棱镜托台 / P03 屏幕板 / P04 显示面板
│   ├── P05 遮光框 / P06 光学胶
│   └── P07 分光棱镜 / P08 分光膜
├── ASM-03 主板组件
│   ├── P09 主板
│   └── C01…C12 元件
├── 参数                   ← 带别名的电子表格
└── BOM                    ← 明细表
```

## 4. 关键尺寸（2026-10 版）

| 项目 | 值 |
|---|---|
| 整机 | 33 × 40 × 41.0 mm |
| 底座 | 前高 18.75 / 后平台 6.0，四角 R5 |
| 正面盲槽 | 22 × 6，深 6 |
| 棱镜 | 25.4³，UV 胶粘接 |
| 托台 | 外 32 / 上口 25.6 / 下口 28.2 |
| 光学头后仰 | 30° |
| 主板 | 28 × 28 |

## 5. 工程图

- **P01 / P02 零件图**：主视 / 左视 / 俯视 + 等轴测 + 总体尺寸 + 技术要求 + 标题栏
- **装配图**：**主视图 / 左视图 / 剖视图 A-A / 爆炸等轴测** + 明细表 + 装配关系说明
  - 剖视图沿 x=0 切开，能看到腔体、主板、屏幕板叠层
  - 爆炸图把光学头零件沿 30° 光轴拉开、主板元件上抬，**全部零件都可见**
  - 所有零件逐件投影后叠加（不用 compound 投影，避免杂散线）

投影用 `TechDraw.projectEx`（带消隐），失败时退化为普通边投影。
图纸是脚本生成的 PNG，改了模型重跑 `make_drawings.py` 即可。

## 6. 与旧流程的区别

| | 旧（build_prototype.py） | 新（build_assembly.py） |
|---|---|---|
| 结构 | 一个 Python 函数熔出一个实体 | 独立零件 + 装配体 |
| 改尺寸 | 改代码重新跑 | **GUI 里改草图/属性/表格** |
| 中间步骤 | 不可见 | 完整特征链（Extrusion/Cut/Fillet） |
| 工程图 | 无 | 零件图 + 装配图 |
| 明细表 | CSV | FCStd 内 Spreadsheet |
