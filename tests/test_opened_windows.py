"""Text pre-filled in a dialog CIG itself opened is the program's default (7-Zip FM 'New Folder', 2026-11-20);
the same text in a window that was already there is someone's and stays an overwrite."""
from cig.adapters.fixture import FixtureAdapter
from cig.engine import Engine

APP = "fixture:editor"
DIALOG = {"control_type": "Window", "name": "Create Folder", "is_modal": True, "patterns": ["Window"],
          "children": [{"control_type": "Edit", "name": "Folder name:", "patterns": ["Value"], "value": "New Folder",
                        "is_read_only": False},
                       {"control_type": "Button", "name": "OK", "patterns": ["Invoke"]}]}


class OpensDialog(FixtureAdapter):
    """Pressing 'Press me'-like buttons opens a dialog with a pre-filled name, as 7-Zip's File > Create Folder does."""
    def execute(self, target, locator, node, action, args):
        r = super().execute(target, locator, node, action, args)
        if action == "invoke" and node.get("name") == "Löschen":
            import copy
            self._data(target)["windows"].append(copy.deepcopy(DIALOG))
        return r


def act(e, action, label):
    return next(a["id"] for a in e.actions(APP)["actions"] if a["action"] == action and f"'{label}'" in a["label"])


def test_default_in_a_dialog_cig_opened_is_a_plain_write(idle):
    idle(120)
    e = Engine([OpensDialog()])
    e.register_launch(4242, "editor.exe")
    assert e.do(APP, act(e, "invoke", "Löschen"), {}, confirm="yes, the owner asked")["ok"]   # opens the dialog
    r = e.do(APP, act(e, "set_text", "Folder name:"), {"text": "made-by-cig"})
    assert r["ok"] and r["verified"] is True


def test_the_same_default_in_a_window_that_was_already_there_stays_an_overwrite(idle):
    idle(120)
    fx = OpensDialog()
    e = Engine([fx])
    e.register_launch(4242, "editor.exe")
    fx.resolve(APP)
    import copy
    fx.state["editor"]["windows"].append(copy.deepcopy(DIALOG))          # present before CIG did anything
    r = e.do(APP, act(e, "set_text", "Folder name:"), {"text": "made-by-cig"})
    assert r["refused"] and r["status"] == "confirm_required"
