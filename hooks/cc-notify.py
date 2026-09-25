#!/usr/bin/env python3
"""Claude Code -> exactly ONE macOS banner + ONE sound per event.

    project name          (title)
    chat name             (subtitle)
    Done | Awaiting input (body)

Claude Code fires Stop and Notification within moments of each other for a
background agent, so a naive hook emits two banners and two sounds. Every
event is journalled instead, and a detached settler waits SETTLE seconds and
lets only the LAST event of the burst speak.

Ranking inside a burst: if the turn ENDED (a `done` event is present) the
result is Done, because a finished agent is trivially also "idle". Awaiting
input only wins when no stop arrived, which is the genuine blocked case.

Clicking a banner does nothing by design.
Usage: cc-notify.py done|input|agent-start|agent-stop   (hook JSON on stdin)
       done becomes "working" (workflow.wav) while subagents/workflows still run;
       "working" plays once per batch, then silence until the real done
       cc-notify.py --settle <sid> <token>   (internal)"""
import glob, json, os, subprocess, sys, time

APP = "/Applications/Claude Code Notify.app"
HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, ".claude", ".notify-state")
SOUNDS = {"done": "done.wav", "working": "workflow.wav", "input": "needs-input.wav"}
BODY = {"done": "Done", "working": "Agents running", "input": "Awaiting input"}
AGENT_TTL = 6 * 3600  # a tracked agent older than this is assumed dead
SETTLE = 1.5          # burst window; both hooks land well inside it
WINDOW = 6.0          # how far back a settler looks


def journal(sid):
    os.makedirs(STATE, exist_ok=True)
    safe = "".join(c for c in (sid or "nosession") if c.isalnum() or c in "-_")
    return os.path.join(STATE, safe + ".jsonl")


def agents_file(sid):
    return journal(sid)[:-len(".jsonl")] + ".agents.json"


def tracked_agents(sid):
    try:
        with open(agents_file(sid)) as f:
            d = json.load(f)
    except Exception:
        return {}
    now = time.time()
    return {k: v for k, v in d.items() if now - float(v) < AGENT_TTL}


def track_agent(sid, agent_id, running):
    if not agent_id:
        return
    d = tracked_agents(sid)
    if running:
        d[agent_id] = time.time()
    else:
        d.pop(agent_id, None)
    with open(agents_file(sid), "w") as f:
        json.dump(d, f)


def is_agent_task(t):
    """Subagents and workflows count; background shells (dev servers) don't."""
    typ = str(t.get("type") or "").lower()
    status = str(t.get("status") or "").lower()
    if status not in ("running", "pending", "in_progress", "queued"):
        return False
    return "agent" in typ or "workflow" in typ


def agents_running(data, sid):
    tasks = data.get("background_tasks")
    if isinstance(tasks, list):          # authoritative when Claude Code sends it
        return any(is_agent_task(t) for t in tasks if isinstance(t, dict))
    return bool(tracked_agents(sid))     # fallback: SubagentStart/Stop ledger


def phase_file(sid):
    return journal(sid)[:-len(".jsonl")] + ".phase"


def announced_working(sid):
    """True if "Agents running" already played for the current batch of agents."""
    try:
        return time.time() - os.path.getmtime(phase_file(sid)) < AGENT_TTL
    except OSError:
        return False


def set_announced_working(sid, on):
    try:
        if on:
            with open(phase_file(sid), "w") as f:
                f.write(str(time.time()))
        else:
            os.remove(phase_file(sid))
    except OSError:
        pass


def session_record(sid):
    if not sid:
        return {}
    for f in glob.glob(os.path.join(HOME, ".claude", "sessions", "*.json")):
        try:
            with open(f) as fh:
                o = json.load(fh)
        except Exception:
            continue
        if str(o.get("sessionId")) == sid:
            return o
    return {}


def chat_name(data):
    path = data.get("transcript_path")
    if not path:
        sid = data.get("session_id") or data.get("sessionId")
        cwd = data.get("cwd") or os.getcwd()
        if sid:
            path = os.path.join(HOME, ".claude", "projects",
                                cwd.replace("/", "-"), sid + ".jsonl")
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 400_000))
            lines = f.read().decode("utf-8", "replace").splitlines()
        for line in reversed(lines):
            if '"aiTitle"' not in line and '"agentName"' not in line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            t = o.get("aiTitle") or o.get("agentName")
            if t:
                return str(t).strip()
    except Exception:
        pass
    return ""


def claude_bin():
    for c in (os.path.join(HOME, ".local/bin/claude"),
              "/opt/homebrew/bin/claude", "/usr/local/bin/claude"):
        if os.path.exists(c):
            return c
    return None


def agent_state(sid):
    """'blocked' | 'working' | 'done' | None (not a listed agent)."""
    cb = claude_bin()
    if not cb or not sid:
        return None
    try:
        r = subprocess.run([cb, "agents", "--json"],
                           capture_output=True, text=True, timeout=20)
        for a in json.loads(r.stdout or "[]"):
            if str(a.get("sessionId")) == sid:
                return str(a.get("state") or "")
    except Exception:
        pass
    return None


def read_burst(path, now):
    out = []
    try:
        with open(path) as f:
            for line in f.readlines()[-40:]:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if now - float(o.get("ts", 0)) <= WINDOW:
                    out.append(o)
    except Exception:
        pass
    return out


def dbg(msg):
    if not os.environ.get("NOTIFY_DEBUG"):
        return
    try:
        with open(os.path.join(HOME, ".claude", "notify-settle.log"), "a") as f:
            f.write(f"{time.strftime('%T')} {msg}\n")
    except Exception:
        pass


def settle(sid, token):
    """Only the last event of the burst speaks."""
    time.sleep(SETTLE)
    path = journal(sid)
    burst = read_burst(path, time.time())
    if not burst:
        return
    newest = max(burst, key=lambda o: float(o.get("ts", 0)))
    if abs(float(newest.get("ts", 0)) - float(token)) > 1e-9:
        dbg(f"SKIP  token={token} (newer event owns burst)")
        return                                  # a later event owns this burst

    kinds = {o.get("kind") for o in burst}
    ended = [o for o in burst if o.get("kind") in ("done", "working")]
    if ended:   # the turn ended; the newest stop says whether agents are still out
        kind = max(ended, key=lambda o: float(o.get("ts", 0))).get("kind")
    else:
        kind = "input"

    # "Agents running" plays ONCE per batch. Each finished agent wakes the main
    # turn, which ends again while the rest are still out; those stops stay
    # silent until the batch is done and the real Done plays.
    if kind == "working":
        if announced_working(sid):
            dbg("SKIP  working (already announced for this batch)")
            return
        set_announced_working(sid, True)
    elif kind == "done":
        set_announced_working(sid, False)

    # An agent that simply FINISHED still gets an idle nudge about a minute
    # later. That is not a question, so it must not ring. Only announce
    # "Awaiting input" when the agent is genuinely blocked on the user.
    if kind == "input":
        st = agent_state(sid)
        if st != "blocked":
            dbg(f"SKIP  input for state={st!r} (not blocked - nothing to reply to)")
            return
    payload = dict(newest.get("payload") or {})
    payload["body"] = BODY.get(kind, "Done")

    dbg(f"POST  kinds={sorted(k for k in kinds if k)} -> {kind!r} "
        f"title={payload.get('title')!r} body={payload.get('body')!r}")
    snd = os.path.join(HOME, ".claude", "sounds", SOUNDS.get(kind, "done.wav"))
    if os.path.exists(snd):
        subprocess.Popen(["/usr/bin/afplay", snd],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.isdir(APP):
        subprocess.Popen(["/usr/bin/open", "-g", "-n", "-a", APP,
                          "--args", json.dumps(payload)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:                                         # keep the journal small
        with open(path) as f:
            tail = f.readlines()[-10:]
        with open(path, "w") as f:
            f.writelines(tail)
    except Exception:
        pass
    try:                                         # drop journals of dead sessions
        cutoff = time.time() - 7 * 86400
        for old in glob.glob(os.path.join(STATE, "*.jsonl")):
            if os.path.getmtime(old) < cutoff:
                os.remove(old)
    except Exception:
        pass


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--settle":
        settle(sys.argv[2], sys.argv[3])
        return

    kind = sys.argv[1] if len(sys.argv) > 1 else "done"
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        data = {}

    sid = data.get("session_id") or data.get("sessionId") or ""

    if kind in ("agent-start", "agent-stop"):     # SubagentStart / SubagentStop
        track_agent(sid, data.get("agent_id"), kind == "agent-start")
        return

    if kind == "done" and agents_running(data, sid):
        kind = "working"

    # Pre-warmed spare sessions have no conversation. Never notify for them.
    if session_record(sid).get("spare") is True:
        return

    project = os.path.basename(data.get("cwd") or os.getcwd()) or "Claude Code"
    payload = {"title": project, "subtitle": chat_name(data),
               "body": BODY.get(kind, "Done"), "sound": "none",
               "id": "cc-" + (sid or project)}

    ts = time.time()
    with open(journal(sid), "a") as f:
        f.write(json.dumps({"ts": ts, "kind": kind, "payload": payload}) + "\n")

    subprocess.Popen(["/usr/bin/python3", os.path.abspath(__file__),
                      "--settle", sid or "nosession", repr(ts)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


try:
    main()
except Exception:
    pass
sys.exit(0)
