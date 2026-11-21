"""M5 proof: 7z.exe and a PowerShell module turned into typed tools by CIG, driven through its MCP server.

Everything happens inside CIG's own var/proof/m5 folder. The script plays the agent: it finds each command by the
label CIG generated, and checks every result on disk itself (hashes), independent of what CIG reports.

  py -3 tools/prove_m5.py      writes docs/proofs/M5-cli.md; exit 0 when every step passed
"""
import asyncio
import datetime
import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

SEVENZ = "cli:" + r"C:\Program Files\7-Zip\7z.exe"
PSMOD = "ps:Microsoft.PowerShell.Archive"
W = REPO / "var" / "proof" / "m5"
steps: list[dict] = []


class StopProof(Exception):
    pass


def step(name, ok, detail):
    steps.append({"step": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + " - " + json.dumps(detail, ensure_ascii=False, default=str)[:260])
    if not ok:
        raise StopProof(name)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def tree_hashes(root):
    root = Path(root)
    return {str(p.relative_to(root)).replace("\\", "/"): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


async def call(s, tool, **args):
    res = await s.call_tool(tool, args)
    txt = res.content[0].text if res.content else "{}"
    try:
        return json.loads(txt)
    except ValueError:
        return {"ok": False, "raw": txt}


def cmd(actions, startswith):
    return next((a for a in actions if a["label"].split("'")[1].startswith(startswith)), None)


async def _run(s):
    acts = (await call(s, "cig_actions", app=SEVENZ)).get("actions", [])
    step("7z.exe's own help became typed commands", len(acts) >= 10,
         {a["label"].split("'")[1][:28]: a["kind"] for a in acts})
    add, lst, dele, ext = cmd(acts, "a:"), cmd(acts, "l:"), cmd(acts, "d:"), cmd(acts, "x:")
    step("kinds come from the commands' own descriptions",
         add["kind"] == "write" and lst["kind"] == "read" and dele["kind"] == "destructive", None)
    step("the password switch is not offered",
         "-p" not in add["input_schema"]["properties"]["switches"]["properties"], None)

    arc = str(W / "proof.7z")
    r = await call(s, "cig_do", app=SEVENZ, action_id=add["id"],
                   args={"archive_name": arc, "file_names": [str(W / "src" / "*")], "switches": {"-r": "", "-y": True}})
    step("7z a: create the archive", r.get("ok") and Path(arc).is_file(), {k: r.get(k) for k in ("reason", "backup")})
    r = await call(s, "cig_do", app=SEVENZ, action_id=lst["id"], args={"archive_name": arc})
    out = str((r.get("detail") or {}).get("output", ""))
    step("7z l (read): the listing names both files", r.get("ok") and "alpha.txt" in out and "beta.txt" in out,
         out[-200:])
    r = await call(s, "cig_do", app=SEVENZ, action_id=dele["id"], args={"archive_name": arc, "file_names": ["alpha.txt"]})
    step("7z d (destructive) without confirm is refused", r.get("refused") and r.get("status") == "confirm_required",
         r.get("reason"))
    r = await call(s, "cig_do", app=SEVENZ, action_id=add["id"],
                   args={"archive_name": str(W / "x.7z"), "switches": {"-sdel": True}}, dry_run=True)
    step("a switch whose description deletes (-sdel) makes 'a' destructive", r.get("refused")
         and (r.get("preview") or {}).get("kind") == "destructive", r.get("reason"))
    r = await call(s, "cig_do", app=SEVENZ, action_id=ext["id"],
                   args={"archive_name": arc, "switches": {"-o": str(W / "out7z"), "-y": True}}, dry_run=True)
    step("dry run shows the exact command line and runs nothing", r.get("status") == "dry_run"
         and not (W / "out7z").exists(), (r.get("preview") or {}).get("would_run"))
    r = await call(s, "cig_do", app=SEVENZ, action_id=ext["id"],
                   args={"archive_name": arc, "switches": {"-o": str(W / "out7z"), "-y": True}})
    step("7z x: extracted files are byte-identical to the sources",
         r.get("ok") and tree_hashes(W / "out7z") == tree_hashes(W / "src"), r.get("reason"))

    acts = (await call(s, "cig_actions", app=PSMOD)).get("actions", [])
    comp, expd = cmd(acts, "Compress-Archive"), cmd(acts, "Expand-Archive")
    step("the PowerShell module's cmdlets became typed commands (schemas from Get-Command)", comp and expd,
         {"Compress-Archive": comp and list(comp["input_schema"]["properties"])})
    zipf = str(W / "proof.zip")
    r = await call(s, "cig_do", app=PSMOD, action_id=comp["id"],
                   args={"Path": [str(W / "src" / "alpha.txt"), str(W / "src" / "beta.txt")], "DestinationPath": zipf},
                   dry_run=True)
    wi = ((r.get("preview") or {}).get("program_dry_run") or {})
    step("dry run uses the cmdlet's own -WhatIf, and no zip is created", r.get("status") == "dry_run"
         and wi.get("whatif") and "what if" in str(wi.get("output", "")).lower() and not Path(zipf).exists(),
         str(wi.get("output", ""))[:160])
    r = await call(s, "cig_do", app=PSMOD, action_id=comp["id"],
                   args={"Path": [str(W / "src" / "alpha.txt"), str(W / "src" / "beta.txt")], "DestinationPath": zipf})
    step("Compress-Archive: the zip is created (and its creation was recorded as a backup)",
         r.get("ok") and Path(zipf).is_file() and r.get("backup"), {k: r.get(k) for k in ("reason", "backup")})
    bid = r["backup"]
    r = await call(s, "cig_do", app=PSMOD, action_id=expd["id"],
                   args={"Path": zipf, "DestinationPath": str(W / "outps"), "Force": True})
    step("Expand-Archive: files byte-identical to the sources",
         r.get("ok") and tree_hashes(W / "outps") == {k: v for k, v in tree_hashes(W / "src").items() if "/" not in k},
         r.get("reason"))
    u = await call(s, "cig_undo", backup_id=bid)
    step("cig_undo removes the zip the cmdlet created", u.get("ok") and not Path(zipf).exists(), u)
    return (await call(s, "cig_log", n=30)).get("entries", [])


async def run():
    if W.exists():
        shutil.rmtree(W)
    (W / "src" / "sub").mkdir(parents=True)
    (W / "src" / "alpha.txt").write_text("alpha - CIG M5 proof\n", encoding="utf-8")
    (W / "src" / "beta.txt").write_text("beta - CIG M5 proof\n" * 50, encoding="utf-8")
    (W / "src" / "sub" / "gamma.txt").write_text("gamma\n", encoding="utf-8")
    params = StdioServerParameters(command=sys.executable, args=[str(REPO / "cig_server.py")])
    try:
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                return await _run(s)
    except StopProof:
        return []


def write(log):
    out = REPO / "docs" / "proofs" / "M5-cli.md"
    ok = all(x["ok"] for x in steps) and len(steps) >= 14
    lines = [f"# M5 proof - 7z.exe and a PowerShell module as typed tools ({datetime.datetime.now():%Y-%m-%d %H:%M})",
             "", f"Result: **{'PASS' if ok else 'FAIL'}** - {sum(x['ok'] for x in steps)}/{len(steps)} steps.", "",
             "Generated by `tools/prove_m5.py` (MCP over stdio). 7-Zip's commands come from its own help text through",
             "`library/cli/help-formats.json`; the PowerShell cmdlets from `Get-Command` metadata. Results checked on",
             "disk by the script (SHA-256), independent of CIG's own report.", "",
             "| # | Step | Result | Detail |", "|---|---|---|---|"]
    for i, x in enumerate(steps, 1):
        d = json.dumps(x["detail"], ensure_ascii=False, default=str).replace("|", "\\|")[:200]
        lines.append(f"| {i} | {x['step']} | {'PASS' if x['ok'] else 'FAIL'} | {d} |")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ok


if __name__ == "__main__":
    lg = asyncio.run(asyncio.wait_for(run(), 400))
    sys.exit(0 if write(lg) else 1)
