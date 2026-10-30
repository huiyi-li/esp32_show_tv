#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PrismTV · NX MCP 执行器

读 handoff/nx_tool_calls.json，通过 stdio MCP 逐条调用 CAD-Agent-Hub/MCP/UG 的
server.py，最后做回读校验并导出 STEP / Parasolid。

用法（在 Windows、已装好 MCP 的机器上）：

    cd C:\\path\\to\\CAD-Agent-Hub\\MCP\\UG
    .\\.venv\\Scripts\\python.exe ^
        C:\\path\\to\\esp32-prism-tv\\handoff\\build_nx_prismtv.py ^
        C:\\path\\to\\esp32-prism-tv\\handoff\\nx_tool_calls.json

依赖：mcp（MCP Python SDK），由 MCP/UG/requirements.txt 提供。

设计要点：
  * 支持 "_as"        给某个调用命名，后面引用
  * 支持 "target_from"/"tool_from"：secondary_last / last，自动换算 body 索引
  * 支持 "_edges_from"：把 resolve_topology 的结果填进 fillet_edges.edge_indices
  * 任一步失败即中止并打印上下文（宁可不写，也不要写坏）
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:
    print("缺少 mcp SDK：先跑 MCP/UG/install_codex.ps1，或 pip install mcp")
    raise

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("NX_MCP_DIR", HERE))  # server.py 所在目录


def as_json(v):
    return v.model_dump(mode="json") if hasattr(v, "model_dump") else v


class Runner:
    def __init__(self, session):
        self.s = session
        self.named = {}          # _as -> 结果
        self.body_count = 0
        self.log = []

    async def call(self, tool, args, ctx=""):
        resp = await self.s.call_tool(tool, args)
        if resp.isError:
            raise RuntimeError(
                "工具 %s 失败（%s）：%s" % (tool, ctx, resp.content))
        value = as_json(resp)
        self.log.append({"tool": tool, "args": args, "ok": True})
        return value

    async def refresh_geometry(self):
        g = await self.call("inspect_work_part_geometry", {"max_bodies": 64},
                            "刷新 body 索引")
        self.body_count = int(g.get("body_count", 0) or 0)
        return g

    def resolve_relative(self, which):
        if which == "last":
            return self.body_count - 1
        if which == "second_last":
            return self.body_count - 2
        raise ValueError("未知相对索引: %s" % which)

    async def run_call(self, item):
        tool = item["tool"]
        args = dict(item.get("args") or {})

        # 相对 body 索引
        if "target_from" in item or "tool_from" in item:
            await self.refresh_geometry()
            if "target_from" in item:
                args["target_body_index"] = self.resolve_relative(item["target_from"])
            if "tool_from" in item:
                args["tool_body_index"] = self.resolve_relative(item["tool_from"])

        # fillet 的边索引
        if "_edges_from" in item:
            idx = []
            for key in item["_edges_from"]:
                r = self.named[key]
                sel = r.get("selected") or {}
                if "index" not in sel:
                    raise RuntimeError("resolve_topology %s 没返回 index：%s" % (key, r))
                idx.append(int(sel["index"]))
            args["edge_indices"] = idx

        result = await self.call(tool, args, item.get("note", ""))

        if "_as" in item:
            self.named[item["_as"]] = result

        # 布尔/新建 body 后让缓存失效，下次用相对索引会重新查
        if tool in ("boolean_bodies", "create_block", "extrude_sketch"):
            self.body_count = -1

        return result


async def run(json_path: Path):
    spec = json.loads(json_path.read_text(encoding="utf-8"))
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "server.py")],
        env=env,
    )

    report = {"meta": spec.get("meta", {}), "stages": [], "verify": None}

    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            r = Runner(session)

            # 0. 连通性
            ping = await r.call("ping", {}, "前置检查")
            print("[ping]", json.dumps(ping, ensure_ascii=False)[:300])
            report["ping"] = ping

            for stage in spec["stages"]:
                name = stage["part"]
                print("\n=== %s ===" % name)
                stage_report = {"part": name, "calls": []}
                for i, item in enumerate(stage["calls"], 1):
                    tool = item["tool"]
                    try:
                        res = await r.run_call(item)
                    except Exception as e:
                        print("  [%02d] %-28s FAIL" % (i, tool))
                        print("       ", e)
                        raise
                    brief = res.get("name") or res.get("feature_name") or res.get("ok")
                    print("  [%02d] %-28s ok %s" % (i, tool, brief or ""))
                    stage_report["calls"].append({"tool": tool, "ok": True})

                # 每个零件存盘
                if any(c["tool"] == "save_work_part" for c in stage["calls"]):
                    pass
                report["stages"].append(stage_report)

            # 1. 回读校验
            print("\n=== 验收 ===")
            geo = await r.call("inspect_work_part_geometry", {"max_bodies": 64}, "验收")
            bodies = geo.get("bodies") or geo.get("body_geometry") or []
            for b in bodies:
                bb = b.get("bbox") or {}
                if bb.get("min") and bb.get("max"):
                    d = [round(bb["max"][i] - bb["min"][i], 3) for i in range(3)]
                    print("  %-24s %s" % (b.get("name", "?"), d))
            report["verify"] = {"geometry": geo}

            # 2. 导出
            print("\n=== 导出 ===")
            for item in spec.get("export", []):
                try:
                    res = await r.call(item["tool"], item["args"], "导出")
                    print("  %-40s ok" % item["args"].get("file_name", ""))
                    report.setdefault("export", []).append(res)
                except Exception as e:
                    print("  导出失败：", e)

    out = json_path.parent / "nx_build_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n报告：", out)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    asyncio.run(run(Path(sys.argv[1]).resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
