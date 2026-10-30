# SolidCraft 版（参数化时间线）

FreeCAD 那套已经**完整迁移**到这里。SolidCraft 用的是"草图 → 拉伸 → 特征"的时间线 +
命名参数，改一个数整条时间线自动重建。

---

## 1. 文件

| 文件 | 说明 |
|---|---|
| `prismtv.solidcraft` | **原生设计**（双击用 SolidCraft 打开）|
| `prismtv.design.json` | 同一份设计的纯文本版（可 diff / 版本管理）|
| `prismtv.step` | STEP AP242（给别的 CAD / 加工）|
| `prismtv.json` | 生成用的命令脚本（可再生成整套模型）|
| `prismtv.png` | 预览图 |

打开方式（任选）：

```bash
solidcraft  cad/solidcraft/prismtv.solidcraft     # 桌面应用
# 或浏览器版：把 .solidcraft / .design.json 拖进去
```

命令行查看/导出：

```bash
solidcraft-cli eval    cad/solidcraft/prismtv.solidcraft          # 体积、质量、包围盒
solidcraft-cli snapshot cad/solidcraft/prismtv.solidcraft --out x.png --view iso
solidcraft-cli run     cad/solidcraft/prismtv.solidcraft --out x.step
```

---

## 2. 怎么改（三种方式）

### ① 改参数（最常用）
时间线最上面的 **参数**（36 个，带中文注释）。双击改值即可，整机自动重建。

| 参数 | 当前值 | 作用 |
|---|---|---|
| `TILT` | 30° | **光学头后仰角 = 人眼仰角** |
| `BW` / `BD` | 33 / 40 | 外壳宽 / 深 |
| `WALL` / `FLOOR` | 2 / 2 | 壁厚 / 底板厚 |
| `CORNER_R` | 4 | 外壳四角圆角 |
| `SLOT_W/H/D` | 22 / 6 / 6 | 正面盲槽 |
| `USBC_W/H` | 9.5 / 3.4 | USB-C 开口 |
| `PRISM` | 25.4 | 分光棱镜边长 |
| `YH` | 14 | 光学头半深（屏幕板 28） |
| `MAIN_W/D/T` | 28 / 28 / 1 | 主板 |

`HY`、`HZ`、`HL_Z`、`HEAD_T`、`TOTAL_H`、`PL_UP`、`PL_LO` 是**派生参数**，
用表达式跟着上游走，不用手改：

```
HY = -18 mm + YH * cos(TILT)      # 光学头原点的世界 Y
HZ =  3.6 mm + YH * sin(TILT)     # 光学头原点的世界 Z
TOTAL_H = HZ + YH*sin(TILT) + HEAD_T*cos(TILT)
```

> 已验证：`TILT` 从 30° 改成 45°，整机高度自动 41.03 → 42.14 mm。

### ② 改特征
时间线里每个特征都能双击重编辑：

| 要改什么 | 找哪个特征 |
|---|---|
| 外壳侧剖面（前高/后平台） | `SK_外壳轮廓` 草图 |
| 内腔大小 | 盒体裁剪（31×38） |
| 正面盲槽 | 盒体裁剪 + 后面那条 R2 圆角 |
| USB-C 开口 | 盒体裁剪 |
| 透光孔 | `solid.cylinder`（φ3，轴向 X） |
| 四角圆角 | `solid.fillet`（R4） |
| 光学头倾斜 | 最后一条 `solid.move`（`angle = 0 - TILT`） |

### ③ 改零件位置
- 光学头零件都在**局部坐标**里建模，最后被一条 `solid.move`（轴 X、−TILT、平移到 HY/HZ）整体搬过去。
  所以改位置就改这条 move，不要单独动 P02–P08。
- 主板和元件在世界坐标，直接改各自盒体的 center。

---

## 3. 浏览器分组

树里已经分好三组：

```
01 外壳组件      P01_外壳底座
02 光学头组件    P02 托台 / P03 屏幕板 / P04 面板 / P05 遮光框
                 P06 光学胶 / P07 棱镜 / P08 分光膜
03 主板与元件    P09_主板 + C01…C12
```

---

## 4. 和 FreeCAD 版的差异（有意为之）

| 项目 | FreeCAD | SolidCraft | 原因 |
|---|---|---|---|
| 四角圆角 | R5 | **R4** | 后壁只有 6mm 高，5mm 圆角会越过相邻面，内核报"最大只能 4" |
| 托台圆角 | R2.5 | **R1.5** | 托台仅 3.9mm 厚，同理 |
| 盲槽圆角 | 直接带圆角 | 盒体 + 后补 R2 fillet | 效果一致 |
| 分光棱镜/胶层 | 独立零件 | 独立实体 | 一致 |

其余尺寸、位置、倾角、光路关系**完全一致**（包围盒逐件核对过）。

---

## 5. 重新生成

```bash
python3 cad/build_solidcraft.py
```

脚本会写出 `prismtv.json` → 跑 `solidcraft-cli run` → 产出 `.solidcraft` / `.step` / `.png` / `.design.json`。

---

## 6. 光学约束（改参数前必看）

`TILT` 不是造型参数，是光学量：出射光方向 `= (0, −cos TILT, +sin TILT)`。

- 它等于人眼观察仰角。坐姿看桌面设备 30° 合适，45° 更接近低头看手机。
- 改大 → 更"正对眼睛"，但整机更高。
- 改小 → 更矮，但画面被竖向压扁（30° 压 13%，15° 压 26%）。
- **托台前唇不能高出棱镜底面**：30° 视线下前唇每高 1mm 就挡掉约 1.7mm 画面，
  而有效显示区只留 1mm 边距。
