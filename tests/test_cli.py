"""CLI adapter, offline: the recorded 7z help becomes typed commands; the engine path (rules, classification, presence,
dry run, backups) runs over a fake executor - nothing is executed."""
from pathlib import Path

from cig import rules
from cig.adapters import cli
from cig.adapters.base import Target
from cig.engine import Engine

from conftest import REPO

HELP = (REPO / "tests" / "fixtures" / "cli" / "7z-26.02-help.txt").read_text(encoding="utf-8", errors="replace")
FMT = cli.help_formats()["formats"][0]
NODES = cli._parse_help(HELP, FMT, r"C:\Tools\7z.exe")


def by(cmd):
    return next(n for n in NODES if n["automation_id"] == cmd)


def test_help_becomes_typed_commands():
    assert {n["automation_id"] for n in NODES} >= {"a", "d", "e", "l", "t", "x", "u", "rn", "h"}
    assert by("d")["cli_kind"] == "destructive" and by("l")["cli_kind"] == "read" and by("a")["cli_kind"] == "write"
    props = by("a")["input_schema"]["properties"]
    assert props["archive_name"] == {"type": "string"}
    assert props["file_names"]["type"] == "array"
    sw = props["switches"]["properties"]
    assert sw["-o"]["type"] == "string" and sw["-y"]["type"] == "boolean"
    assert "-p" not in sw                                   # the password switch is never offered


def test_cli_rules_make_one_run_action_per_command():
    acts = rules.actions_for([{"control_type": "Window", "name": "cli:7z", "children": list(NODES)}], "cli")
    kinds = {a["label"].split("'")[1].split(":")[0]: a["kind"] for a in acts}
    assert kinds["d"] == "destructive" and kinds["l"] == "read" and kinds["x"] == "write"
    a = next(x for x in acts if x["label"].endswith("'a: Add files to archive'"))
    assert a["action"] == "run" and "switches" in a["input_schema"]["properties"]


def test_argv_is_a_list_never_a_shell_string():
    ad = cli.CliAdapter()
    argv = ad._argv(by("x"), {"archive_name": "a b.7z", "switches": {"-o": r"C:\out dir", "-y": True}})
    assert argv == [r"C:\Tools\7z.exe", "x", r"-oC:\out dir", "-y", "a b.7z"]


class FakeCli(cli.CliAdapter):
    """The real adapter with the executor and the help reader replaced: nothing runs."""
    def __init__(self):
        self.ran = []

    def resolve(self, app):
        return Target(key="cli|fake7z", exe="7z.exe", title="cli:fake7z", adapter="cli") if app == "cli:fake7z" else None

    def _nodes(self, target):
        return NODES

    def execute(self, target, locator, node, action, args):
        self.ran.append(self._argv(node, args))
        return {"detail": "fake"}


def act(e, cmd):
    return next(a["id"] for a in e.actions("cli:fake7z")["actions"] if f"'{cmd}:" in a["label"])


def test_engine_runs_reads_and_writes_and_refuses_destructive(idle, tmp_path):
    idle(60)
    f = FakeCli()
    e = Engine([f])
    arc = str(tmp_path / "t.7z")
    assert e.do("cli:fake7z", act(e, "l"), {"archive_name": arc})["ok"]
    r = e.do("cli:fake7z", act(e, "a"), {"archive_name": arc, "file_names": ["x.txt"]})
    assert r["ok"] and r["backup"]                         # the archive is backed up (here: noted as new) first
    r = e.do("cli:fake7z", act(e, "d"), {"archive_name": arc, "file_names": ["x.txt"]})
    assert r["refused"] and r["status"] == "confirm_required"
    assert len(f.ran) == 2


def test_a_destructive_switch_makes_the_run_destructive(idle, tmp_path):
    idle(60)
    e = Engine([FakeCli()])
    r = e.do("cli:fake7z", act(e, "a"), {"archive_name": str(tmp_path / "t.7z"), "switches": {"-sdel": True}})
    assert r["refused"] and r["status"] == "confirm_required" and r["preview"]["kind"] == "destructive"


def test_dry_run_shows_the_command_line_and_runs_nothing(idle, tmp_path):
    idle(60)
    f = FakeCli()
    e = Engine([f])
    r = e.do("cli:fake7z", act(e, "x"), {"archive_name": "t.7z", "switches": {"-o": str(tmp_path)}}, dry_run=True)
    assert r["status"] == "dry_run" and "7z.exe" in r["preview"]["would_run"]
    assert r["preview"]["program_dry_run"]["whatif"] is False and not f.ran


def test_cli_writes_still_need_the_person_away(idle, tmp_path):
    idle(1)
    e = Engine([FakeCli()])
    r = e.do("cli:fake7z", act(e, "a"), {"archive_name": str(tmp_path / "t.7z")})
    assert r["refused"] and r["status"] == "confirm_required"
