"""The command-line adapter (plan 1.4 / 4.1, milestone M5).

  ps:<Module>        a PowerShell module - every cmdlet/function becomes a typed command, its input schema built from
                     Get-Command's own parameter metadata (types, ValidateSet, switches); kind from the verb and
                     ConfirmImpact; dry runs use the command's own -WhatIf where it supports ShouldProcess
  cli:<exe>          a native tool - its own help text is parsed by a format from library/cli/help-formats.json
                     (sub-commands, switches with value placeholders, positional arguments from the usage line)

Nothing here knows a particular tool. A run is an argument list (never a shell string); PowerShell arguments travel as
JSON in an environment variable, so no value can be spliced into the script. Secret-looking parameters (SecureString,
PSCredential, a 'password' switch) are left out of the schema: CIG never passes secrets.
"""
from __future__ import annotations

import base64
import functools
import json
import os
import re
import shutil
import subprocess
from typing import Optional

from .. import config
from ..classify import destructive_hits
from .base import Adapter, AdapterError, Target

COMMON = {"Verbose", "Debug", "ErrorAction", "WarningAction", "InformationAction", "ErrorVariable", "WarningVariable",
          "InformationVariable", "OutVariable", "OutBuffer", "PipelineVariable", "WhatIf", "Confirm", "ProgressAction"}
PS_READ_VERBS = {"Get", "Test", "Find", "Measure", "Show", "Read", "Search", "Resolve", "Compare", "Select", "Format",
                 "ConvertTo", "ConvertFrom", "Import", "Watch", "Wait", "Trace", "Debug", "Request", "Use"}
PS_DESTRUCTIVE_VERBS = {"Remove", "Clear", "Reset", "Uninstall", "Unregister", "Disable", "Stop", "Dismount",
                        "Unpublish", "Revoke", "Deny", "Block", "Uninstall"}
IN_PLACE_VERBS = {"Set", "Add", "Clear", "Remove", "Rename", "Move", "Write", "Out", "Update", "Edit", "Reset",
                  "Rename", "Protect", "Unprotect", "Lock", "Unlock", "Merge", "Split"}
PS_TYPES = {"String": "string", "Int32": "integer", "Int64": "integer", "UInt32": "integer", "UInt64": "integer",
            "Int16": "integer", "Byte": "integer", "Double": "number", "Single": "number", "Decimal": "number",
            "Boolean": "boolean", "SwitchParameter": "boolean"}
NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

META_PS = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Import-Module $env:CIG_PS_MODULE
$out = foreach ($c in (Get-Command -Module $env:CIG_PS_MODULE -CommandType Cmdlet, Function)) {
  $impact = 'Medium'
  if ($c.CommandType -eq 'Cmdlet' -and $c.ImplementingType) {
    $a = $c.ImplementingType.GetCustomAttributes([System.Management.Automation.CmdletAttribute], $true) | Select-Object -First 1
    if ($a) { $impact = [string]$a.ConfirmImpact }
  } elseif ($c.ScriptBlock) {
    $a = $c.ScriptBlock.Attributes | Where-Object { $_ -is [System.Management.Automation.CmdletBindingAttribute] } | Select-Object -First 1
    if ($a) { $impact = [string]$a.ConfirmImpact }
  }
  $params = foreach ($p in $c.Parameters.Values) {
    $vs = $p.Attributes | Where-Object { $_ -is [System.Management.Automation.ValidateSetAttribute] } | Select-Object -First 1
    $t = $p.ParameterType
    [pscustomobject]@{
      name = $p.Name; type = $t.Name; element = $(if ($t.IsArray) { $t.GetElementType().Name } else { $null })
      mandatory = [bool]($p.ParameterSets.Values | Where-Object { $_.IsMandatory })
      validate_set = $(if ($vs) { @($vs.ValidValues) } else { $null })
    }
  }
  [pscustomobject]@{ name = $c.Name; verb = $c.Verb; impact = $impact; whatif = $c.Parameters.ContainsKey('WhatIf');
                     version = [string]$c.Version; params = @($params) }
}
ConvertTo-Json -InputObject @($out) -Depth 6 -Compress
"""

RUN_PS = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Import-Module $env:CIG_PS_MODULE
$j = $env:CIG_PS_ARGS | ConvertFrom-Json
$h = @{}
foreach ($p in $j.psobject.properties) { $v = $p.Value; if ($v -is [object[]]) { $v = [string[]]$v }; $h[$p.Name] = $v }
if ($env:CIG_PS_WHATIF -eq '1') { $h['WhatIf'] = $true }
& $env:CIG_PS_COMMAND @h *>&1 | Out-String -Width 240
"""


def _ps(script: str, env: dict, timeout: float) -> subprocess.CompletedProcess:
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          env={**os.environ, **env}, stdin=subprocess.DEVNULL)


@functools.lru_cache(maxsize=1)
def help_formats() -> dict:
    return json.loads((config.LIBRARY_DIR / "cli" / "help-formats.json").read_text(encoding="utf-8"))


def _secret(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in help_formats()["secret_words"])


# ------------------------------------------------------------------------------------------------ PowerShell
@functools.lru_cache(maxsize=16)
def ps_commands(module: str) -> tuple:
    if not NAME_RE.match(module):
        raise AdapterError(f"not a module name: {module!r}")
    r = _ps(META_PS, {"CIG_PS_MODULE": module}, 90)
    if r.returncode != 0:
        raise AdapterError(f"cannot read module {module}: {(r.stderr or r.stdout).strip()[:300]}")
    data = json.loads(r.stdout.strip() or "[]")
    nodes = []
    for c in data if isinstance(data, list) else [data]:
        props, required = {}, []
        for p in c.get("params") or []:
            if p["name"] in COMMON or p["type"] in ("SecureString", "PSCredential") or _secret(p["name"]):
                continue
            if p.get("element"):
                s = {"type": "array", "items": {"type": PS_TYPES.get(p["element"], "string")}}
            else:
                s = {"type": PS_TYPES.get(p["type"], "string")}
            if p.get("validate_set"):
                (s["items"] if s["type"] == "array" else s)["enum"] = list(p["validate_set"])
            props[p["name"]] = s
        verb = c.get("verb") or ""
        if c.get("impact") == "High" or verb in PS_DESTRUCTIVE_VERBS:
            kind = "destructive"
        elif verb in PS_READ_VERBS:
            kind = "read"
        else:
            kind = "write"
        nodes.append({"control_type": "Command", "name": c["name"], "automation_id": c["name"], "cli_kind": kind,
                      "input_schema": {"type": "object", "properties": props, "additionalProperties": False},
                      "cli": {"kind": "ps", "module": module, "command": c["name"], "whatif": bool(c.get("whatif")),
                              "impact": c.get("impact"), "version": c.get("version")}})
    return tuple(nodes)


# ------------------------------------------------------------------------------------------------ native help
def _exe_path(ref: str) -> str:
    p = ref if os.path.isfile(ref) else (shutil.which(ref) or "")
    if not p:
        raise AdapterError(f"no program '{ref}' found (give a full path or a name on PATH)")
    return os.path.abspath(p)


@functools.lru_cache(maxsize=16)
def native_commands(exe: str) -> tuple:
    formats = help_formats()
    for fmt in formats["formats"]:
        r = subprocess.run([exe, *fmt["help_args"]], capture_output=True, text=True, errors="replace", timeout=20,
                           stdin=subprocess.DEVNULL)
        text = (r.stdout or "") + "\n" + (r.stderr or "")
        if fmt["detect"] in text:
            return tuple(_parse_help(text, fmt, exe))
    raise AdapterError(f"{os.path.basename(exe)}'s help is in no format the library knows (library/cli/help-formats.json)")


def _section(lines: list[str], header: str) -> list[str]:
    out, inside = [], False
    for ln in lines:
        if ln.strip() == header:
            inside = True
            continue
        if inside:
            if not ln.strip() or re.match(r"^<\w+>$", ln.strip()):
                break
            out.append(ln)
    return out


def _parse_help(text: str, fmt: dict, exe: str) -> list[dict]:
    lines = text.splitlines()
    positionals = []
    for ln in lines:
        m = re.match(fmt["usage_re"], ln.strip())
        if m:
            for tok in m.group(1).split():
                if tok.startswith("[@") or tok.startswith("@"):
                    continue
                name = re.sub(r"[\[\]<>.]", "", tok)
                if name:
                    positionals.append({"name": name, "array": tok.endswith("...]") or tok.endswith("..."),
                                        "optional": tok.startswith("[")})
            break
    switches = {}
    for ln in _section(lines, fmt["switches_section"]):
        m = re.match(fmt["switch_re"], ln)
        if not m or m.group(1) == "--":
            continue
        name, suffix, desc = m.group(1), m.group(2), m.group(3).strip()
        if _secret(desc) or _secret(suffix):
            continue                                            # never offered: CIG passes no secrets
        switches[name] = {"type": "string" if "{" in suffix or "[" in suffix else "boolean",
                          "description": (desc + (f" (value form: {suffix})" if suffix else ""))[:200]}
    read_words = set(formats_read_words())
    nodes = []
    for ln in _section(lines, fmt["commands_section"]):
        m = re.match(fmt["command_re"], ln)
        if not m:
            continue
        cmd, desc = m.group(1), m.group(2).strip()
        first = desc.split()[0].lower() if desc.split() else ""
        kind = "destructive" if destructive_hits([desc]) else ("read" if first in read_words else "write")
        props = {}
        for p in positionals:
            props[p["name"]] = {"type": "array", "items": {"type": "string"}} if p["array"] else {"type": "string"}
        props["switches"] = {"type": "object", "properties": switches, "additionalProperties": False}
        nodes.append({"control_type": "Command", "name": f"{cmd}: {desc}", "automation_id": cmd, "cli_kind": kind,
                      "input_schema": {"type": "object", "properties": props, "additionalProperties": False},
                      "cli": {"kind": "native", "exe": exe, "command": cmd, "positionals": positionals,
                              "switch_style": "attached"}})
    return nodes


def formats_read_words():
    return help_formats()["read_words"]


# ------------------------------------------------------------------------------------------------ the adapter
class CliAdapter(Adapter):
    name = "cli"
    rules_name = "cli"

    def resolve(self, app: str) -> Optional[Target]:
        a = str(app)
        if a.startswith("ps:"):
            mod = a[3:]
            if not NAME_RE.match(mod):
                return None
            return Target(key=f"ps|{mod}", exe="powershell.exe", title=a, adapter=self.name)
        if a.startswith("cli:"):
            exe = _exe_path(a[4:])
            return Target(key=f"cli|{exe.lower()}", exe=os.path.basename(exe), title=a, adapter=self.name)
        return None

    def _nodes(self, target: Target) -> tuple:
        if target.key.startswith("ps|"):
            return ps_commands(target.key.split("|", 1)[1])
        return native_commands(_exe_path(target.title[4:]))

    def snapshot(self, target: Target, depth: int = 12) -> list[dict]:
        return [{"control_type": "Window", "name": target.title, "automation_id": target.key,
                 "children": [dict(n) for n in self._nodes(target)]}]

    def read(self, target: Target, locator: str, node: dict) -> dict:
        return {"exists": True, "name": node.get("name"), "kind": node.get("cli_kind")}

    # ---- what a call would do, and what it writes
    def _argv(self, node: dict, args: dict) -> list[str]:
        c = node["cli"]
        argv = [c["exe"], c["command"]]
        for name, val in (args.get("switches") or {}).items():
            if val is True:
                argv.append(name)
            elif val not in (False, None, ""):
                argv.append(f"{name}{val}")
        for p in c["positionals"]:
            v = args.get(p["name"])
            if v is None:
                continue
            argv += [str(x) for x in v] if isinstance(v, list) else [str(v)]
        return argv

    def describe(self, target: Target, node: dict, action: str, args: dict):
        c = node.get("cli") or {}
        if c.get("kind") == "native":
            return subprocess.list2cmdline(self._argv(node, args))
        return {"module": c.get("module"), "command": c.get("command"), "parameters": args}

    def classify_texts(self, node: dict, args: dict) -> list[str]:
        sw = (node.get("input_schema", {}).get("properties", {}).get("switches") or {}).get("properties", {})
        return [sw[k]["description"] for k in (args.get("switches") or {}) if k in sw and args["switches"][k]]

    def files_written(self, target: Target, action: str, args: dict, node: Optional[dict] = None) -> list[str]:
        if not node or node.get("cli_kind") == "read":
            return []
        c = node.get("cli") or {}
        if c.get("kind") == "native":
            first = (c.get("positionals") or [{}])[0].get("name")
            v = args.get(first) if first else None
            return [str(v)] if isinstance(v, str) and v else []
        out = []
        verb = str(c.get("command", "")).split("-")[0]
        # Path / LiteralPath are what the command works ON: written only by verbs that change things in place
        # (Compress-Archive only reads its -Path; seen in the M5 proof, 2026-11-20)
        in_place = verb in IN_PLACE_VERBS
        for k in ("DestinationPath", "OutFile", "FilePath") + (("Path", "LiteralPath") if in_place else ()):
            v = args.get(k)
            for x in (v if isinstance(v, list) else [v] if v else []):
                if isinstance(x, str) and os.path.isfile(x):
                    out.append(x)
                elif k in ("DestinationPath", "OutFile", "FilePath") and isinstance(x, str):
                    out.append(x)                               # will be created: undo removes it
        return out

    # ---- running
    def dry_run_preview(self, target: Target, node: dict, action: str, args: dict):
        c = node.get("cli") or {}
        if c.get("kind") == "ps" and c.get("whatif"):
            return {"whatif": True, "output": self._run_ps(c, args, whatif=True)}
        return {"whatif": False, "note": "this command has no dry run of its own; nothing was run",
                "would_run": self.describe(target, node, action, args)}

    def _run_ps(self, c: dict, args: dict, whatif: bool = False) -> str:
        r = _ps(RUN_PS, {"CIG_PS_MODULE": c["module"], "CIG_PS_COMMAND": c["command"],
                         "CIG_PS_ARGS": json.dumps(args), "CIG_PS_WHATIF": "1" if whatif else "0"}, 300)
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0:
            raise AdapterError(f"{c['command']} failed (exit {r.returncode}): {out.strip()[-1500:]}")
        return out.strip()[-4000:]

    def execute(self, target: Target, locator: str, node: dict, action: str, args: dict) -> dict:
        c = node.get("cli") or {}
        if action != "run":
            raise AdapterError(f"the CLI adapter has no '{action}'")
        if c.get("kind") == "ps":
            return {"detail": "PowerShell", "output": self._run_ps(c, args)}
        argv = self._argv(node, args)
        r = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=600,
                           stdin=subprocess.DEVNULL, cwd=str(config.home()))
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        if r.returncode != 0:
            raise AdapterError(f"{subprocess.list2cmdline(argv)} -> exit {r.returncode}: {out[-1500:]}")
        return {"detail": subprocess.list2cmdline(argv), "exit": r.returncode, "output": out[-4000:]}
