"""Safety layer (plan 2.7 "Safety tests"): presence, confirm, deny lists, third-party rule, keys, dry run."""
from cig import presence
from cig.policy import Policy, Request, decide, READ, WRITE, DESTRUCTIVE


def P():
    return Policy.load()


def req(**kw):
    base = dict(app="editor.exe", action="set_text", kind=WRITE, pid=4242)
    base.update(kw)
    return Request(**base)


def test_read_always_allowed_even_while_active(idle):
    idle(0.1)
    d = decide(req(kind=READ, action="get_text"), presence.read(), P())
    assert d.allowed and d.status == "ok"


def test_write_refused_at_1_min_allowed_at_6(idle):
    idle(1)
    d = decide(req(), presence.read(), P())
    assert not d.allowed and d.status == "confirm_required"
    idle(6)
    assert decide(req(), presence.read(), P()).allowed


def test_write_while_active_allowed_with_confirm(idle):
    idle(1)
    d = decide(req(confirm="go ahead, type it"), presence.read(), P())
    assert d.allowed


def test_destructive_needs_confirm_even_when_away(idle):
    idle(120)
    d = decide(req(kind=DESTRUCTIVE, action="invoke"), presence.read(), P())
    assert not d.allowed and d.status == "confirm_required"
    assert decide(req(kind=DESTRUCTIVE, action="invoke", confirm="yes delete them"), presence.read(), P()).allowed


def test_deny_action_not_overridable(idle):
    idle(120)
    d = decide(req(action="set_secret", confirm="I really mean it"), presence.read(), P())
    assert not d.allowed and "deny" in d.reason


def test_deny_app_not_overridable(idle):
    idle(120)
    for exe in ("chrome.exe", "LibreWolf.exe", "consent.exe"):
        d = decide(req(app=exe, confirm="yes"), presence.read(), P())
        assert not d.allowed, exe


def test_deny_window_title(idle):
    idle(120)
    d = decide(req(window_title="Sign in to your account", confirm="yes"), presence.read(), P())
    assert not d.allowed


def test_deny_applies_to_reads_too(idle):
    idle(120)
    assert not decide(req(app="KeePassXC.exe", kind=READ, action="get_text"), presence.read(), P()).allowed


def test_third_party_foreground_rule(idle, monkeypatch):
    monkeypatch.setenv("CIG_FOREGROUND_PID", "4242")
    idle(10)                                   # past idle_min but within the foreground window
    d = decide(req(confirm="yes"), presence.read(), P())
    assert not d.allowed and "foreground" in d.reason
    idle(40)
    assert decide(req(), presence.read(), P()).allowed
    monkeypatch.setenv("CIG_FOREGROUND_PID", "999")   # another window in front: only the idle rule applies
    idle(10)
    assert decide(req(), presence.read(), P()).allowed


def test_first_party_skips_foreground_rule(idle, monkeypatch):
    monkeypatch.setenv("CIG_FOREGROUND_PID", "4242")
    idle(10)
    assert decide(req(app="ModOrganizer.exe"), presence.read(), P()).allowed


def test_keys_refused_while_active_even_confirmed(idle):
    idle(1)
    d = decide(req(action="keys", confirm="yes"), presence.read(), P())
    assert not d.allowed and "keys" in d.reason
    idle(20)
    assert decide(req(action="keys"), presence.read(), P()).allowed


def test_unknown_presence_needs_confirm(seams):
    # no watcher file, no system reading
    d = decide(req(), presence.read(), P())
    assert not d.allowed and d.status == "confirm_required"


def test_stale_watcher_falls_back_to_system_idle(idle, monkeypatch):
    idle(60, watcher_alive=False)              # the file says away, but its watcher is dead: not trusted
    monkeypatch.setenv("CIG_SYSTEM_IDLE_MIN", "0.5")
    p = presence.read()
    assert p.source == "system" and p.idle_min == 0.5
    assert not decide(req(), p, P()).allowed


def test_elevated_target_needs_confirm(idle):
    idle(60)
    assert not decide(req(elevated_target=True), presence.read(), P()).allowed
    assert decide(req(elevated_target=True, confirm="ok"), presence.read(), P()).allowed


def test_dry_run_passes_while_active_but_marks_dry(idle):
    idle(0.5)
    d = decide(req(dry_run=True), presence.read(), P())
    assert d.allowed and d.status == "dry_run"


def test_dry_run_still_refuses_denied(idle):
    idle(60)
    assert not decide(req(action="set_secret", dry_run=True), presence.read(), P()).allowed
