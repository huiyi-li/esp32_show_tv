# PrismTV · NX MCP 交接包

> 目标：在 **Windows + Siemens NX 2412 + CAD-Agent-Hub/MCP/UG** 上，让 AI 用 MCP
> 在 10–20 分钟内重建这份**参数化、可编辑**的棱镜小电视结构。
>
> 本目录是自包含的：规格、参数、工具调用序列、可执行脚本都在这里。

---

## 0. 先决条件

| 项 | 要求 |
|---|---|
| 系统 | Windows 10/11 |
| CAD | **Siemens NX 2412**（版本不对时部分模板/API 会变） |
| 权限 | NX 正版许可，能正常打开并新建零件 |
| MCP | `CAD-Agent-Hub/MCP/UG` 已 `install_codex.ps1` + `install_nx_autostart.ps1` |
| 客户端 | Codex / OpenCode / Claude Desktop 任一（stdio，服务名 `siemens-nx`） |
| 用户 | MCP 进程与 NX **同一 Windows 用户、同权限级别** |

装完先验证（缺一步后面全白搭）：

```powershell
cd C:\path\to\CAD-Agent-Hub\MCP\UG
.\.venv\Scripts\python.exe .\diagnose.py
.\.venv\Scripts\python.exe .\smoke.py
.\.venv\Scripts\python.exe .\smoke.py --create-block
```

NX 里必须看到 `ping → part summary → create block` 全通。

---

## 1. 这个包里有啥

| 文件 | 用途 |
|---|---|
| `DESIGN_SPEC.md` | **设计说明**：坐标系、零件清单、逐件尺寸、光学约束、构建顺序、验收标准 |
| `params.csv` | 机器可读参数表（36 项，含派生关系） |
| `nx_tool_calls.json` | **按顺序的 MCP 工具调用清单**（AI 可直接照做，也可被脚本执行） |
| `build_nx_prismtv.py` | 执行器：读 JSON → 逐条调 MCP → 回读校验 → 导 STEP |

---

## 2. 三种用法（选一个）

### A. 直接跑脚本（最省事）

```powershell
cd C:\path\to\CAD-Agent-Hub\MCP\UG
python .\build_nx_prismtv.py C:\path\to\handoff\nx_tool_calls.json
```

脚本会自己起 stdio MCP、调 `server.py`、按顺序执行、最后打印回读结果。

### B. 让 AI 读 JSON 一条条调（最灵活）

把 `DESIGN_SPEC.md` + `nx_tool_calls.json` 丢给 AI，说：

> 按 nx_tool_calls.json 的顺序调用 MCP 工具。遇到 `"note"` 字段先读懂再调。
> 每次 `boolean_bodies` 之后重新调 `inspect_work_part_geometry` 确认 body 索引，
> 不要沿用旧索引。全部跑完按 `verify` 段做验收，把结果贴给我。

### C. 人工照文档在 NX 里建（最稳）

`DESIGN_SPEC.md` 第 6 节是逐特征的建模顺序，NX 老手照着点 10 分钟就完事。

---

## 3. 唯一可能需要手动的一步

**光学头的 30° 后仰**。这份 MCP 没有"移动实体"的工具，只有装配层的
`move_component`。所以两种做法：

1. **脚本做法**：`nx_tool_calls.json` 里的 `assembly` 段会调 `add_component` +
   `move_component`。这两个工具的参数**没有公开示例**，字段名请以仓库
   `MCP/UG/server.py` / `nx_remote_ops.py` 为准；跑之前先 `solidcraft-cli` 那套思路——
   先在 NX 里手动插一个组件试参数。
2. **手动做法（推荐，30 秒）**：装配里插入光学头后，用
   **装配 → 组件 → 移动组件**：
   - 旋转：绕 **X 轴 −30°**
   - 平移：`(0, −5.876, 10.6) mm`
   - 基准点：光学头局部原点（屏幕板底面中心）

  这两个数不是拍脑袋的，是 `HY = -18 + YH·cos30`、`HZ = 3.6 + YH·sin30` 算出来的。
   改倾角要同步改它们（见 `DESIGN_SPEC.md` 5.2）。

---

## 4. 验收（必做）

跑完后在 NX 里核对，或让 AI 调 `inspect_work_part_geometry`：

| 检查 | 期望 |
|---|---|
| 外壳 bbox | **33 × 40 × 18.75 mm** |
| 主板 bbox | 28 × 28 × 1.0 |
| 棱镜 bbox（装配/世界） | **25.4 × 34.7 × 34.7** |
| 整机 bbox | **33 × 40 × 41.7 mm** |
| 实体数 | 主体 1 + 元件 9 + 光学头 7 ≈ 17 |
| 关键特征 | 正面盲槽 22×6 深 6；USB-C 口 9.5×3.4；透光孔 φ3 |

⚠️ 仓库自己的原则：**COM/API 返回成功 ≠ 模型正确**。必须在 NX 模型树里看一眼。

---

## 5. 安全

- 桥只绑 `127.0.0.1`，别暴露。
- `run_python` = NX 内任意代码执行。不需要就设 `NX_MCP_ALLOW_EXECUTE=0`。
- 本包不涉及 CAM / 后处理，不碰任何生产认证流程。

---

## 6. 和已有模型的对应关系

本机已有的两种实现，几何完全一致，可用来交叉校验：

| 实现 | 路径 | 用途 |
|---|---|---|
| SolidCraft（参数化时间线） | `../cad/solidcraft/prismtv.solidcraft` | 快速改尺寸 |
| FreeCAD（零件+装配+图） | `../cad/out/PrismTV_Assembly.FCStd` | 出工程图 |
| STEP（死实体） | `../cad/solidcraft/prismtv.step` | 导进 NX 做几何基准 |

> 建议：先在 NX 里 `import_exchange` 那个 STEP 当"对位参考"（不要基于它建模，
> 它没有特征树），然后按本包重建真特征。
