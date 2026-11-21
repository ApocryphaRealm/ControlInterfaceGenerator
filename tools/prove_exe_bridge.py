"""Proof that a built cig.exe carries its in-process bridges: through the EXE's own MCP server (not the source tree),
launch CIG's Avalonia gallery with bridge="dotnet", choose a combo option Avalonia does not publish to UI Automation,
read it back, and close the program.

  py -3 tools/prove_exe_bridge.py <cig.exe> <CigAvaloniaGallery.exe>
"""
import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def body(r):
    return json.loads(r.content[0].text) if r.content else {}


async def main(cig_exe: str, gallery: str) -> int:
    checks = []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok)))
        print(("PASS " if ok else "FAIL ") + name + (f"  {detail}" if detail else ""))
        if not ok:
            raise SystemExit(1)

    params = StdioServerParameters(command=cig_exe, args=["serve"])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            lr = body(await s.call_tool("cig_launch", {"exe": gallery, "bridge": "dotnet"}))
            check("launched with the bundled .NET bridge", lr.get("ok", True) and not lr.get("error"), json.dumps(lr)[:300])
            app = str(lr.get("pid") or "CigAvaloniaGallery.exe")
            try:
                acts = {}
                for _ in range(20):
                    acts = body(await s.call_tool("cig_actions", {"app": app}))
                    if any(a.get("action") == "choose" for a in acts.get("actions", [])):
                        break
                    await asyncio.sleep(0.5)
                adapter = acts.get("adapter") or acts.get("target", {}).get("adapter")
                check("actions come from the bridge", str(adapter or "").startswith("bridge"), str(adapter))
                chooses = [a for a in acts.get("actions", []) if a.get("action") == "choose"]
                check("a choose action with options", chooses and chooses[0]["input_schema"]["properties"]["option"].get("enum"))
                a = chooses[0]
                opts = a["input_schema"]["properties"]["option"]["enum"]
                rd = body(await s.call_tool("cig_read", {"app": app, "element_id": a["id"].rsplit(".", 1)[0]}))
                cur = (rd.get("state") or {}).get("value")
                pick = next((o for o in opts if o != cur), opts[-1])
                dr = body(await s.call_tool("cig_do", {"app": app, "action_id": a["id"], "args": {"option": pick}}))
                check(f"choose '{pick}' done", dr.get("ok"), json.dumps(dr)[:300])
                after = body(await s.call_tool("cig_read", {"app": app, "element_id": a["id"].rsplit(".", 1)[0]}))
                check(f"read back independently: '{pick}'", (after.get("state") or {}).get("value") == pick,
                      f"was '{cur}', now {json.dumps(after.get('state'))[:200]}")
            finally:
                cr = body(await s.call_tool("cig_close", {"app": app}))
                print("close:", json.dumps(cr)[:200])
    print(f"{sum(ok for _, ok in checks)}/{len(checks)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1], sys.argv[2])))
