"""CIG's Python bridge - started by CIG in place of a Python GUI script it launches:
    python cig_bridge_boot.py <script.py> [args...]
It starts the bridge (loopback only, a fresh token, the channel file CIG named in CIG_BRIDGE_CHANNEL), then runs the
script exactly as `python script.py args` would (runpy, __main__). The bridge reads the program's own widget tree
(tkinter; Embarcadero's delphifmx) and acts through the toolkit's own methods on the toolkit's own thread. Without
CIG_BRIDGE_CHANNEL it only runs the script."""
import json
import os
import runpy
import secrets
import socket
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _toolkit():
    if "tkinter" in sys.modules:
        import tkinter
        if getattr(tkinter, "_default_root", None) is not None:
            import cig_bridge_tk
            return cig_bridge_tk
    if "delphifmx" in sys.modules:
        import cig_bridge_fmx
        return cig_bridge_fmx
    return None


def _handle(line, token):
    try:
        req = json.loads(line)
        if req.get("token") != token:
            return {"ok": False, "error": "bad token"}
        cmd, args = req.get("cmd"), req.get("args") or {}
        tk = _toolkit()
        if cmd == "ping":
            return {"ok": True, "framework": tk.NAME if tk else "none-yet", "pid": os.getpid()}
        if tk is None:
            return {"ok": False, "error": "no GUI toolkit is running yet"}
        if cmd == "tree":
            return {"ok": True, "framework": tk.NAME, "windows": tk.tree()}
        if cmd == "act":
            tk.act(args)
            return {"ok": True}
        return {"ok": False, "error": f"unknown cmd {cmd}"}
    except Exception as e:                                  # noqa: BLE001 - every failure goes back to CIG as text
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _serve(channel):
    token = secrets.token_hex(32)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    info = {"host": "127.0.0.1", "port": srv.getsockname()[1], "token": token, "pid": os.getpid(),
            "bridge": "python", "protocol": 1}
    tmp = channel + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(info, f)
    os.replace(tmp, channel)
    while True:
        conn, addr = srv.accept()
        if addr[0] != "127.0.0.1":
            conn.close()
            continue
        with conn, conn.makefile("rwb") as fh:
            for raw in fh:
                fh.write((json.dumps(_handle(raw.decode("utf-8"), token)) + "\n").encode("utf-8"))
                fh.flush()


def main():
    channel = os.environ.pop("CIG_BRIDGE_CHANNEL", "")
    if channel:
        threading.Thread(target=_serve, args=(channel,), daemon=True, name="cig-bridge").start()
    if len(sys.argv) < 2:
        sys.exit("usage: cig_bridge_boot.py <script.py> [args...]")
    script = os.path.abspath(sys.argv[1])
    sys.argv = [script, *sys.argv[2:]]
    sys.path[0] = os.path.dirname(script)
    if channel:
        try:
            with open(script, encoding="utf-8", errors="replace") as f:
                uses_fmx = "delphifmx" in f.read()
        except OSError:
            uses_fmx = False
        if uses_fmx:
            import cig_bridge_fmx
            cig_bridge_fmx.install()      # FMX's main-thread Timer, set up when the script calls Application.Run()
    runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main()
