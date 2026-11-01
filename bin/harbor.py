#!/usr/bin/env python3
"""Harbor: convoys of branches from several sessions, accounts and machines, integrated in
convoy/<n>, verified once and landed on main with one push. Stdlib only (Python 3.11+).

The shared state is the logbook: the orphan branch harbor/log on the remote. Only this script
writes it: fetch, one small commit, push; when the push is rejected because someone wrote first,
the change is replayed on the new tip (its preconditions checked again), never forced.

    harbor.py check [--hook]                 SessionStart: Keelokit present, landing policy, a brief
    harbor.py init                           create the logbook on the remote (once; again is a no-op)
    harbor.py account set ACCOUNT --max-sessions N
    harbor.py account pause ACCOUNT --until TIMESTAMP [--reason TEXT]
    harbor.py account resume ACCOUNT
    harbor.py worker register --role vessel|skipper|harbormaster [--convoy N] [--branch B] [--model M]
    harbor.py worker end [--branch B --head SHA] [--verified TEXT] [--pending TEXT]
                         [--worktree PATH] [--log PATH]
    harbor.py seal [--rerun]                 record the vessel verify of HEAD by hash: Keelokit's own run of
                                             this commit against today's main if it passed, else run it
    harbor.py convoy new [--title T] [--expect STORY ...] [--depends N ...]
    harbor.py convoy add N BRANCH [--head SHA] [--story ID] [--tier trivial|light|full]
    harbor.py convoy status [N]
    harbor.py log                            print LOGBOOK.md as the remote has it
    harbor.py import-board FILE              once: a hand-kept BOARD.md into the logbook

Global: --session ID (else $HARBOR_SESSION, else $CLAUDE_SESSION_ID). A worker is
<account>/<host>/<session>; account and host come from .keelokit/local.toml ([harbor]), which git
ignores. Exit codes: 0 done, 1 refused (the reason is printed as `harbor: CODE: why`), 2 the
environment or the command line is wrong. Design: docs/design.md.
"""
import sys

if sys.version_info < (3, 11):
    print(f"Harbor needs Python 3.11+ (found {sys.version.split()[0]}).")
    sys.exit(2)

import argparse  # noqa: E402
import datetime as dt  # noqa: E402
import fnmatch  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shlex  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import tomllib  # noqa: E402
import unicodedata  # noqa: E402
from pathlib import Path  # noqa: E402

SCHEMA = 1
LOG_BRANCH = "harbor/log"
MAIN = "main"
STATES = ("assembling", "waiting", "ready", "verifying", "sailed", "aborted")
OPEN = ("assembling", "waiting", "ready", "verifying")
ROLES = ("vessel", "skipper", "harbormaster")
TIERS = ("trivial", "light", "full")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# Attempts to land one logbook write when others keep writing first. An engineering bound, not a
# number from the survey: each attempt is a fetch and a push, and five rejections in a row means
# something is wrong with the remote, not with the timing.
PUSH_ATTEMPTS = 5
DEFAULTS = {
    "integrator": "any",
    # Keelokit's scoped verify against main; --keep-going lists every red in one run (one fix round).
    "vessel_verify": "pnpm verify --since {base} --keep-going",
    # JOUNA's values (survey 5.3): a control at least every 90 minutes, relief after 3 hours.
    "control_every_minutes": 90,
    "watch_expiry_minutes": 180,
}
ENV_CODES = {"NO_KEELOKIT", "POLICY_NOT_CONVOY", "NO_IDENTITY", "NO_SESSION", "NOT_A_REPO", "USAGE", "FETCH_FAILED",
             "PUSH_FAILED"}

ROOT = Path.cwd()
REMOTE = "origin"
# Called once, between building a logbook commit and its first push. Tests use it to make another
# clone write first; nothing else sets it.
BEFORE_PUSH = None


class HarborError(Exception):
    def __init__(self, code: str, why: str):
        super().__init__(f"{code}: {why}")
        self.code, self.why = code, why


# --- git ----------------------------------------------------------------------------------------

def run(*args: str, env: dict | None = None, input: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    res = subprocess.run(list(args), cwd=ROOT, capture_output=True, text=True, env=env, input=input)
    if check and res.returncode != 0:
        raise HarborError("GIT", f"{' '.join(args[:3])}… failed: {(res.stderr or res.stdout).strip()[:300]}")
    return res


def git(*args: str, **kw) -> str:
    return run("git", *args, **kw).stdout.strip()


def rev(ref: str) -> str | None:
    res = run("git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
    return res.stdout.strip() or None


def fetch(branch: str) -> str | None:
    """Fetch one branch of the remote into its remote-tracking ref. None when the remote has no such branch."""
    res = run("git", "fetch", "--quiet", "--no-tags", REMOTE, f"+refs/heads/{branch}:refs/remotes/{REMOTE}/{branch}", check=False)
    if res.returncode == 0:
        return rev(f"refs/remotes/{REMOTE}/{branch}")
    if "couldn't find remote ref" in res.stderr or "could not find remote ref" in res.stderr:
        run("git", "update-ref", "-d", f"refs/remotes/{REMOTE}/{branch}", check=False)
        return None
    raise HarborError("FETCH_FAILED", f"git fetch {REMOTE} {branch}: {res.stderr.strip()[:300]}")


def read_tree(sha: str) -> dict[str, str]:
    names = [n for n in git("ls-tree", "-r", "--name-only", "-z", sha).split("\0") if n]
    if not names:
        return {}
    res = subprocess.run(["git", "cat-file", "--batch"], cwd=ROOT, capture_output=True,
                         input="".join(f"{sha}:{n}\n" for n in names).encode())
    if res.returncode != 0:
        raise HarborError("GIT", f"git cat-file --batch failed: {res.stderr.decode(errors='replace')[:300]}")
    out, files, pos = res.stdout, {}, 0
    for n in names:
        header_end = out.index(b"\n", pos)
        size = int(out[pos:header_end].split()[2])
        files[n] = out[header_end + 1:header_end + 1 + size].decode("utf-8")
        pos = header_end + 1 + size + 1
    return files


def write_commit(files: dict[str, str], old: dict[str, str], parent: str | None, message: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        if not git("config", "user.email", check=False) and "GIT_AUTHOR_EMAIL" not in env:
            env.update(GIT_AUTHOR_NAME="Harbor", GIT_AUTHOR_EMAIL="harbor@localhost",
                       GIT_COMMITTER_NAME="Harbor", GIT_COMMITTER_EMAIL="harbor@localhost")
        if parent:
            git("read-tree", f"{parent}^{{tree}}", env=env)
        else:
            git("read-tree", "--empty", env=env)
        for path in sorted(set(old) - set(files)):
            git("update-index", "--force-remove", "--", path, env=env)
        for path, text in sorted(files.items()):
            if old.get(path) != text:
                blob = git("hash-object", "-w", "--stdin", input=text, env=env)
                git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
        tree = git("write-tree", env=env)
        return git("commit-tree", tree, *(["-p", parent] if parent else []), "-m", message, env=env)


def push(commit: str) -> bool:
    """True when the logbook moved to `commit`; False when the remote had moved first (rejected)."""
    res = run("git", "push", "--quiet", "--porcelain", REMOTE, f"{commit}:refs/heads/{LOG_BRANCH}", check=False)
    if res.returncode == 0:
        git("update-ref", f"refs/remotes/{REMOTE}/{LOG_BRANCH}", commit)
        return True
    text = res.stdout + res.stderr
    if any(s in text for s in ("[rejected]", "non-fast-forward", "fetch first", "stale info", "[remote rejected]")):
        return False
    raise HarborError("PUSH_FAILED", f"git push {REMOTE} {LOG_BRANCH}: {res.stderr.strip()[:300]}")


# --- TOML out (tomllib only reads) --------------------------------------------------------------

def _key(k: str) -> str:
    return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else json.dumps(k, ensure_ascii=False)


def _val(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False).replace("\x7f", "\\u007f")
    if isinstance(v, list):
        return "[" + ", ".join(_val(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{_key(k)} = {_val(x)}" for k, x in v.items() if x is not None) + " }"
    raise TypeError(f"no TOML for {type(v).__name__}")


def dumps(data: dict) -> str:
    """Scalars and lists first, then [tables], then [[arrays of tables]]; None means absent."""
    lines, tables, arrays = [], [], []
    for k, v in data.items():
        if v is None:
            continue
        if isinstance(v, dict):
            tables.append((k, v))
        elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            arrays.append((k, v))
        else:
            lines.append(f"{_key(k)} = {_val(v)}")
    for k, v in tables:
        lines += ["", f"[{_key(k)}]"] + [f"{_key(a)} = {_val(b)}" for a, b in v.items() if b is not None]
    for k, v in arrays:
        for item in v:
            lines += ["", f"[[{_key(k)}]]"] + [f"{_key(a)} = {_val(b)}" for a, b in item.items() if b is not None]
    return "\n".join(lines).lstrip("\n") + "\n"


# --- time, config, identity ---------------------------------------------------------------------

def now() -> str:
    return os.environ.get("HARBOR_NOW") or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(s: str) -> dt.datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    t = dt.datetime.fromisoformat(s)
    if t.tzinfo is None:
        raise HarborError("USAGE", f"'{s}' has no time zone; write it in UTC, like 2026-11-01T21:00:00Z")
    return t.astimezone(dt.timezone.utc)


def fmt_ts(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def keelokit() -> dict:
    """The project's .keelokit/state.toml, or a refusal: Harbor runs only on Keelokit with the convoy policy."""
    if not (ROOT / ".keelokit").is_dir():
        raise HarborError("NO_KEELOKIT", "this repo has no .keelokit/: Harbor works on top of Keelokit "
                          "(/keelokit:project-adopt) and does nothing here")
    try:
        state = tomllib.loads((ROOT / ".keelokit/state.toml").read_text(encoding="utf-8"))
    except FileNotFoundError:
        state = {}
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise HarborError("NO_KEELOKIT", f".keelokit/state.toml is not valid TOML: {e}")
    policy = (state.get("landing") or {}).get("policy")
    if policy != "convoy":
        raise HarborError("POLICY_NOT_CONVOY", f"[landing] policy is {json.dumps(policy) if policy else 'not set'} in "
                          ".keelokit/state.toml; Harbor runs only with policy = \"convoy\" (/harbor:adopt)")
    return state


def config(state: dict) -> dict:
    cfg = {**DEFAULTS, **{k: v for k, v in (state.get("harbor") or {}).items() if not isinstance(v, dict)}}
    harbor = state.get("harbor") or {}
    cfg["hotspots"] = harbor.get("hotspots") or {}
    cfg["generated"] = harbor.get("generated") or {}
    cfg["models"] = harbor.get("models") or {}
    return cfg


def identity(session: str | None, need_session: bool = True) -> dict:
    try:
        local = tomllib.loads((ROOT / ".keelokit/local.toml").read_text(encoding="utf-8")).get("harbor") or {}
    except FileNotFoundError:
        local = {}
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise HarborError("NO_IDENTITY", f".keelokit/local.toml is not valid TOML: {e}")
    account, host = local.get("account"), local.get("host")
    if not (isinstance(account, str) and NAME.fullmatch(account) and isinstance(host, str) and NAME.fullmatch(host)):
        raise HarborError("NO_IDENTITY", "set [harbor] account and host in .keelokit/local.toml (letters, digits, . _ -); "
                          "the file is git-ignored, one per clone")
    session = session or os.environ.get("HARBOR_SESSION") or os.environ.get("CLAUDE_SESSION_ID") or None
    if session is not None and not NAME.fullmatch(session):
        raise HarborError("NO_SESSION", f"session id '{session}' has characters outside letters, digits, . _ -")
    if not session and need_session:
        raise HarborError("NO_SESSION", "this command needs the session id: --session ID or $HARBOR_SESSION "
                          "(the SessionStart line 'this session: …' gives it)")
    return {"account": account, "host": host, "session": session,
            "id": f"{account}/{host}/{session}" if session else f"{account}/{host}/-"}


# --- the logbook --------------------------------------------------------------------------------

def load(files: dict, path: str) -> dict | None:
    text = files.get(path)
    return tomllib.loads(text) if text is not None else None


def save(files: dict, path: str, data: dict) -> None:
    files[path] = dumps(data)


def convoys(files: dict) -> dict[int, dict]:
    out = {}
    for path in files:
        m = re.fullmatch(r"harbor/convoys/(\d+)\.toml", path)
        if m:
            out[int(m.group(1))] = load(files, path)
    return dict(sorted(out.items()))


def workers(files: dict) -> dict[str, dict]:
    return {d["id"]: d for p in sorted(files) if p.startswith("harbor/workers/") and p.endswith(".toml")
            for d in [load(files, p)]}


def accounts(files: dict) -> dict[str, dict]:
    return {d["account"]: d for p in sorted(files) if p.startswith("harbor/accounts/") and p.endswith(".toml")
            for d in [load(files, p)]}


def worker_path(wid: str) -> str:
    return f"harbor/workers/{wid}.toml"


def event(by: str, what: str, detail: str = "") -> dict:
    return {"at": now(), "by": by, "what": what, "detail": detail or None}


def transact(message: str, by: str, mutate, init: bool = False):
    """Fetch the logbook, apply `mutate(files)` (it checks its own preconditions and raises HarborError),
    regenerate the views, commit, push. Rejected: someone wrote first, so start again from their tip —
    the change is replayed and its preconditions checked again, never forced."""
    global BEFORE_PUSH
    for attempt in range(PUSH_ATTEMPTS):
        head = fetch(LOG_BRANCH)
        if head is None and not init:
            raise HarborError("NOT_INITIALIZED", f"the remote has no {LOG_BRANCH} yet: /harbor:adopt (harbor.py init)")
        old = read_tree(head) if head else {}
        files = dict(old)
        result = mutate(files, head)
        render(files)
        if files == old:
            return result
        commit = write_commit(files, old, head, f"harbor: {message}\n\nHarbor-Worker: {by}")
        if BEFORE_PUSH is not None and attempt == 0:
            hook, BEFORE_PUSH = BEFORE_PUSH, None
            hook()
        if push(commit):
            return result
    raise HarborError("PUSH_RETRIES_EXHAUSTED", f"{PUSH_ATTEMPTS} pushes to {LOG_BRANCH} were rejected in a row; "
                      "nothing was written. Run it again; if it repeats, look at the remote")


def snapshot() -> tuple[str | None, dict]:
    head = fetch(LOG_BRANCH)
    if head is None:
        raise HarborError("NOT_INITIALIZED", f"the remote has no {LOG_BRANCH} yet: /harbor:adopt (harbor.py init)")
    return head, read_tree(head)


# --- views (generated, never edited) ------------------------------------------------------------

GENERATED = "<!-- Generated by harbor.py from harbor/*.toml. Do not edit: every logbook write regenerates it. -->"


def short(sha: str | None) -> str:
    return sha[:9] if sha else "—"


def cell(v) -> str:
    return str(v if v not in (None, "", []) else "—").replace("|", "\\|").replace("\n", " ")


def render(files: dict) -> None:
    for path in [p for p in files if re.fullmatch(r"convoys/\d+\.md", p)]:
        del files[path]
    cs = convoys(files)
    for n, c in cs.items():
        files[f"convoys/{n}.md"] = render_convoy(c, files)
    files["LOGBOOK.md"] = render_logbook(files, cs)


def render_logbook(files: dict, cs: dict) -> str:
    out = [GENERATED, "", "# Logbook", ""]
    hm = load(files, "harbor/harbormaster.toml") or {}
    out += ["## Harbormaster", ""]
    if hm.get("worker"):
        out.append(f"{hm['worker']}, since {hm.get('since', '—')} · last control {hm.get('last_control', '—')}"
                   f" · expires {hm.get('expires', '—')}")
    else:
        out.append("Nobody holds the watch.")
    out += ["", "## Convoys", ""]
    if cs:
        out += ["| Convoy | State | Skipper | Integrator | Vessels | Base | Last event |", "|---|---|---|---|---|---|---|"]
        order = sorted(cs.items(), key=lambda kv: (kv[1].get("state") not in OPEN, kv[0]))
        for n, c in order:
            last = (c.get("events") or [{}])[-1]
            skipper = c.get("skipper") or (f"{c['imported_skipper']} (imported)" if c.get("imported_skipper") else None)
            out.append(f"| [{n}](convoys/{n}.md) | {c.get('state')} | {cell(skipper)} | {cell(c.get('integrator'))} | "
                       f"{len(c.get('vessels') or [])} | {short(c.get('base'))} | "
                       f"{cell(' '.join(x for x in (last.get('at'), last.get('what')) if x))} |")
    else:
        out.append("No convoys yet.")
    ws = workers(files)
    live = {k: w for k, w in ws.items() if w.get("state") != "ended"}
    out += ["", "## Workers", ""]
    if live:
        out += ["| Worker | Role | Convoy | Branch | Model | Last seen | State |", "|---|---|---|---|---|---|---|"]
        for wid, w in live.items():
            out.append(f"| {wid} | {cell(w.get('role'))} | {cell(w.get('convoy'))} | {cell(w.get('branch'))} | "
                       f"{cell(w.get('model'))} | {cell(w.get('last_seen'))} | {w.get('state')} |")
    else:
        out.append("No active workers.")
    ended = len(ws) - len(live)
    if ended:
        out += ["", f"{ended} ended worker(s), with their handovers, in `harbor/workers/`."]
    acs = accounts(files)
    if acs:
        out += ["", "## Accounts", "", "| Account | Max sessions | Active | Paused until |", "|---|---|---|---|"]
        for a, d in acs.items():
            active = sum(1 for w in live.values() if w.get("account") == a and w.get("state") == "active")
            until = d.get("paused_until")
            if until and d.get("reason"):
                until = f"{until} ({d['reason']})"
            out.append(f"| {a} | {d.get('max_sessions')} | {active} | {cell(until)} |")
    imp = load(files, "harbor/imported/board.toml")
    if imp:
        out += ["", "## Imported", "",
                f"`BOARD.md` imported on {imp.get('imported')} (sha256 {imp.get('sha256', '')[:12]}): "
                f"{len(imp.get('convoys') or [])} convoy(s); {len(imp.get('skipped') or [])} row(s) left out. "
                "The original is in `harbor/imported/BOARD.md`."]
    return "\n".join(out) + "\n"


def render_convoy(c: dict, files: dict) -> str:
    n = c["number"]
    title = f"# Convoy {n}" + (f": {c['title']}" if c.get("title") else "")
    out = [GENERATED, "", title, ""]
    meta = [("State", c.get("state")), ("Skipper", c.get("skipper") or c.get("imported_skipper")),
            ("Integrator", c.get("integrator")), ("Branch", f"`{c.get('branch')}`"), ("Base", short(c.get("base"))),
            ("Depends on", ", ".join(str(d) for d in c.get("depends_on") or []) or None),
            ("Expected", ", ".join(c.get("expected") or []) or None)]
    if c.get("imported"):
        meta.append(("Imported", "from BOARD.md; no vessel entered through Harbor yet"))
    out += [f"- {k}: {cell(v)}" for k, v in meta]
    seals = {p.removeprefix("harbor/seals/").removesuffix(".toml"): p for p in files if p.startswith("harbor/seals/")}
    out += ["", "## Vessels", ""]
    vs = c.get("vessels") or []
    if vs:
        out += ["| Branch | Head | Story | Tier | Vessel verify | Hotspots | Added |", "|---|---|---|---|---|---|---|"]
        for v in vs:
            s = load(files, seals[v["head"]]) if v["head"] in seals else None
            sv = f"exit {s['exit']}, base {short(s.get('base'))}, {s.get('duration_seconds')} s" if s else "—"
            out.append(f"| `{v['branch']}` | {short(v['head'])} | {cell(v.get('story'))} | {cell(v.get('tier'))} | {sv} | "
                       f"{cell(', '.join(v.get('hotspots') or []))} | {v.get('added')} |")
    else:
        out.append("None yet.")
    delivered = {v.get("story") for v in vs}
    missing = [s for s in c.get("expected") or [] if s not in delivered]
    if missing:
        out += ["", "## Expected, not delivered", ""] + [f"- {s}" for s in missing]
    out += ["", "## Events", "", "| At | By | What | Detail |", "|---|---|---|---|"]
    out += [f"| {e.get('at')} | {cell(e.get('by'))} | {e.get('what')} | {cell(e.get('detail'))} |" for e in c.get("events") or []]
    return "\n".join(out) + "\n"


# --- commands -----------------------------------------------------------------------------------

def cmd_check(args) -> int:
    """SessionStart. Never fails the session: everything it can't do becomes one line."""
    session = None
    if args.hook and not sys.stdin.isatty():
        try:
            session = (json.loads(sys.stdin.read() or "{}") or {}).get("session_id")
        except (ValueError, OSError):
            session = None
    try:
        state = keelokit()
    except HarborError as e:
        print(f"Harbor: {e.why}.")
        return 0
    cfg = config(state)
    lines = []
    try:
        me = identity(args.session or session, need_session=False)
        lines.append(f"Harbor: this session is {me['account']}/{me['host']}/{session or args.session or '<session>'}"
                     " — pass --session to harbor.py.")
    except HarborError as e:
        lines.append(f"Harbor: {e.why}.")
    head = rev(f"refs/remotes/{REMOTE}/{LOG_BRANCH}")
    if not head:
        lines.append(f"Harbor: no logbook fetched ({REMOTE}/{LOG_BRANCH}); /harbor:adopt creates it, /harbor:log fetches it.")
        print("\n".join(lines))
        return 0
    files = read_tree(head)
    hm = load(files, "harbor/harbormaster.toml") or {}
    cs = convoys(files)
    counts = {}
    for c in cs.values():
        if c.get("state") in OPEN:
            counts[c["state"]] = counts.get(c["state"], 0) + 1
    watch = f"harbormaster {hm['worker']} (last control {hm.get('last_control')})" if hm.get("worker") else "nobody holds the watch"
    open_line = ", ".join(f"{k} {v}" for k, v in counts.items()) or "none"
    lines.append(f"Harbor: logbook @{short(head)} as of the last fetch · {watch} · open convoys: {open_line} · "
                 f"integrator: {cfg['integrator']}.")
    print("\n".join(lines))
    return 0


def cmd_init(args) -> int:
    keelokit()
    me = identity(args.session, need_session=False)

    def mutate(files, head):
        if head:
            return "exists"
        save(files, "harbor/harbormaster.toml", {"schema": SCHEMA})
        save(files, "harbor/logbook.toml", {"schema": SCHEMA, "created": now(), "created_by": me["id"]})
        return "created"

    result = transact("init the logbook", me["id"], mutate, init=True)
    print(f"harbor: logbook {LOG_BRANCH} {'already existed; nothing changed' if result == 'exists' else 'created on ' + REMOTE}")
    return 0


def cmd_account(args) -> int:
    keelokit()
    me = identity(args.session, need_session=False)
    if not NAME.fullmatch(args.account):
        raise HarborError("USAGE", f"account '{args.account}' has characters outside letters, digits, . _ -")
    if args.account != me["account"]:
        raise HarborError("NOT_YOUR_ACCOUNT", f"this clone is account '{me['account']}' (.keelokit/local.toml); "
                          f"only a session of '{args.account}' changes it")
    path = f"harbor/accounts/{args.account}.toml"

    def mutate(files, head):
        cur = load(files, path) or {"schema": SCHEMA, "account": args.account}
        if args.action == "set":
            if args.max_sessions < 1:
                raise HarborError("USAGE", "--max-sessions is at least 1")
            cur["max_sessions"] = args.max_sessions
        else:
            if "max_sessions" not in cur:
                raise HarborError("ACCOUNT_UNKNOWN", f"account '{args.account}' has no cap yet: account set first")
            if args.action == "pause":
                cur["paused_until"] = fmt_ts(parse_ts(args.until))
                cur["reason"] = args.reason
            else:
                cur.pop("paused_until", None)
                cur.pop("reason", None)
        cur["updated"], cur["updated_by"] = now(), me["id"]
        save(files, path, cur)
        return cur

    cur = transact(f"account {args.action} {args.account}", me["id"], mutate)
    print(f"harbor: account {args.account}: max {cur.get('max_sessions')} session(s)"
          + (f", paused until {cur['paused_until']}" if cur.get("paused_until") else ""))
    return 0


def paused(acc: dict | None) -> str | None:
    if acc and acc.get("paused_until") and parse_ts(acc["paused_until"]) > parse_ts(now()):
        return acc["paused_until"]
    return None


def cmd_worker(args) -> int:
    keelokit()
    me = identity(args.session)
    path = worker_path(me["id"])

    def register(files, head):
        acc = accounts(files).get(me["account"])
        if not acc:
            raise HarborError("ACCOUNT_UNKNOWN", f"account '{me['account']}' has no cap in the logbook: "
                              f"harbor.py account set {me['account']} --max-sessions N (the number is yours to choose)")
        if until := paused(acc):
            raise HarborError("ACCOUNT_PAUSED", f"account '{me['account']}' is paused until {until}"
                              + (f" ({acc['reason']})" if acc.get("reason") else ""))
        others = [w["id"] for w in workers(files).values()
                  if w.get("account") == me["account"] and w.get("state") == "active" and w["id"] != me["id"]]
        if len(others) >= acc["max_sessions"]:
            raise HarborError("ACCOUNT_AT_CAP", f"account '{me['account']}' already runs {len(others)} of "
                              f"{acc['max_sessions']} session(s): {', '.join(others)}")
        cur = load(files, path) or {"schema": SCHEMA, "id": me["id"], "account": me["account"], "host": me["host"],
                                    "session": me["session"], "registered": now()}
        cur.pop("handover", None)
        cur.pop("ended", None)
        cur.update(role=args.role, convoy=args.convoy, branch=args.branch, model=args.model, state="active", last_seen=now())
        save(files, path, cur)
        return cur

    def end(files, head):
        cur = load(files, path)
        if not cur:
            raise HarborError("NOT_REGISTERED", f"{me['id']} never registered")
        handover = {"branch": args.branch, "head": args.head, "verified": args.verified, "pending": args.pending,
                    "worktree": args.worktree, "log": args.log}
        if args.head and not args.branch:
            raise HarborError("USAGE", "--head needs --branch")
        if args.branch:
            tip = fetch(args.branch)
            if tip is None:
                raise HarborError("HANDOVER_NOT_PUSHED", f"{args.branch} is not on {REMOTE}: push it before ending")
            if args.head and tip != rev(args.head):
                raise HarborError("HANDOVER_NOT_PUSHED", f"{REMOTE}/{args.branch} is at {short(tip)}, not "
                                  f"{short(args.head)}: push the last commit before ending")
            handover["head"] = tip
        cur.update(state="ended", ended=now(), last_seen=now())
        if any(handover.values()):
            cur["handover"] = handover
        save(files, path, cur)
        return cur

    if args.action == "register":
        cur = transact(f"worker register {me['id']} as {args.role}", me["id"], register)
        print(f"harbor: {cur['id']} registered as {cur['role']}" + (f" in convoy {cur['convoy']}" if cur.get("convoy") else ""))
    else:
        cur = transact(f"worker end {me['id']}", me["id"], end)
        print(f"harbor: {cur['id']} ended" + (" with a handover" if cur.get("handover") else ""))
    return 0


def cmd_seal(args) -> int:
    state = keelokit()
    cfg = config(state)
    me = identity(args.session, need_session=False)
    if git("status", "--porcelain", "--untracked-files=normal"):
        raise HarborError("DIRTY_TREE", "commit or stash first: a seal speaks for one exact commit and a clean tree")
    branch = run("git", "symbolic-ref", "--quiet", "--short", "HEAD", check=False).stdout.strip()
    if not branch:
        raise HarborError("DETACHED", "check out the vessel's branch: the seal records which branch it was")
    head = git("rev-parse", "HEAD")
    base = fetch(MAIN)
    if not base:
        raise HarborError("NO_MAIN", f"{REMOTE} has no {MAIN}")
    previous = None if args.rerun else keelokit_history(head)
    if previous and full_run(previous, head, base):
        # build-story already ran Keelokit's verify on this exact commit against today's main: record it
        # instead of running it a second time.
        seal = {"schema": SCHEMA, "kind": "vessel", "head": head, "branch": branch, "base": base,
                "command": "pnpm verify (run by Keelokit, read from keelokit-verify.history)", "exit": 0,
                "result": "pass", "started": fmt_ts(dt.datetime.fromtimestamp(previous["t"], dt.timezone.utc)),
                "finished": now(), "duration_seconds": sum(int(t) for _, t in previous.get("steps") or []
                                                           if isinstance(t, (int, float))),
                "by": me["id"], "reused": True}
        rc = 0
        print(f"harbor: {branch}@{short(head)} already passed Keelokit's verify against {short(base)}; recording that run")
    else:
        cmd = cfg["vessel_verify"].format(base=base, head=head, branch=branch)
        started, t0, wall = now(), time.monotonic(), int(time.time()) - 1
        print(f"harbor: sealing {branch}@{short(head)} with `{cmd}`", flush=True)
        try:
            rc = subprocess.run(shlex.split(cmd), cwd=ROOT).returncode
        except FileNotFoundError as e:
            raise HarborError("VERIFY_NOT_FOUND", f"`{cmd}`: {e}")
        duration = int(time.monotonic() - t0)
        if git("rev-parse", "HEAD") != head or git("status", "--porcelain", "--untracked-files=normal"):
            raise HarborError("SEAL_INVALID", "HEAD or the tree changed during the run, so the result speaks for no commit; "
                              "commit what changed and seal again")
        seal = {"schema": SCHEMA, "kind": "vessel", "head": head, "branch": branch, "base": base, "command": cmd,
                "exit": rc, "result": "pass" if rc == 0 else "fail", "started": started, "finished": now(),
                "duration_seconds": duration, "by": me["id"]}
        previous = keelokit_history(head, since=wall)
    if previous:
        seal.update(steps_from(previous))
        # Keelokit's pre-push accepts this file as a shared seal only with `level`, so it is written only
        # when Keelokit's own record says the run was a whole verify (not partial), green, on a clean
        # tree, against this base. Anything less proves less, and must not skip the pre-push.
        if rc == 0 and full_run(previous, head, base):
            seal["level"] = previous["level"]

    def mutate(files, h):
        save(files, f"harbor/seals/{head}.toml", seal)

    transact(f"seal {branch}@{short(head)} exit {rc}", me["id"], mutate)
    shared = (f"Keelokit's pre-push accepts it ({seal['level']})" if seal.get("level")
              else "not a shared seal: Keelokit's pre-push will run its verify")
    print(f"harbor: seal for {short(head)} recorded: {seal['result']} (exit {rc}, {seal['duration_seconds']} s); {shared}")
    return 0 if rc == 0 else 1


def keelokit_history(head: str, since: float = 0) -> dict | None:
    """The newest line Keelokit's verify.sh appended to keelokit-verify.history for this commit (since
    `since`): time per step, planned, passed and failed steps, scope, packages, causes. Read, never
    required: a command other than Keelokit's verify leaves none."""
    common = Path(git("rev-parse", "--git-common-dir"))
    path = (common if common.is_absolute() else ROOT / common) / "keelokit-verify.history"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
    except OSError:
        return None
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and head.startswith(str(entry.get("head") or "-")) and entry.get("t", 0) >= since:
            return entry
    return None


def full_run(entry: dict, head: str, base: str) -> bool:
    """A whole Keelokit verify of exactly this commit against this base: green, not partial (no --steps,
    --packages, --filter or --rerun-failed), started on a clean tree. Older history lines lack these
    fields and never qualify."""
    return (entry.get("head") == head and entry.get("base") == base and entry.get("result") == "pass"
            and entry.get("rc") == 0 and entry.get("partial") is False and entry.get("clean") is True
            and entry.get("level") in ("changed", "all"))


def steps_from(entry: dict) -> dict:
    def names(key):
        return [str(x) for x in entry.get(key) or [] if isinstance(x, str)]
    return {"keelokit_level": str(entry.get("level") or "") or None, "partial": entry.get("partial"),
            "scope": str(entry.get("scope") or "") or None, "planned": names("planned"), "passed": names("passed"),
            "failed_steps": names("failed_steps") or names("failed"), "causes": names("causes"),
            "packages": names("packages"),
            "steps": [{"name": str(n), "seconds": int(t)} for n, t in entry.get("steps") or []
                      if isinstance(t, (int, float))]}


def hotspots_of(paths: list[str], spots: dict) -> list[str]:
    hit = []
    for name, patterns in spots.items():
        pats = [patterns] if isinstance(patterns, str) else list(patterns)
        if any(p.startswith(pt) if pt.endswith("/") else fnmatch.fnmatchcase(p, pt) for p in paths for pt in pats):
            hit.append(name)
    return sorted(hit)


def cmd_convoy(args) -> int:
    state = keelokit()
    cfg = config(state)
    if args.action == "status":
        return convoy_status(args)
    me = identity(args.session)

    def registered(files) -> dict:
        w = workers(files).get(me["id"])
        if not w or w.get("state") != "active":
            raise HarborError("NOT_REGISTERED", f"{me['id']} is not an active worker: harbor.py worker register first")
        if until := paused(accounts(files).get(me["account"])):
            raise HarborError("ACCOUNT_PAUSED", f"account '{me['account']}' is paused until {until}")
        return w

    if args.action == "new":
        base = fetch(MAIN)
        if not base:
            raise HarborError("NO_MAIN", f"{REMOTE} has no {MAIN}")

        def mutate(files, head):
            w = registered(files)
            cs = convoys(files)
            for d in args.depends or []:
                if d not in cs or cs[d].get("state") == "aborted":
                    raise HarborError("UNKNOWN_CONVOY", f"convoy {d} (in --depends) doesn't exist or was aborted")
            n = max(cs, default=0) + 1
            integrator = cfg["integrator"]
            save(files, f"harbor/convoys/{n}.toml", {
                "schema": SCHEMA, "number": n, "title": args.title, "state": "assembling", "branch": f"convoy/{n}",
                "skipper": me["id"], "integrator": me["id"] if integrator == "any" else f"account:{integrator}",
                "base": base, "created": now(), "depends_on": args.depends or [], "expected": args.expect or [],
                "vessels": [], "events": [event(me["id"], "new", f"base {short(base)}")]})
            w.update(role="skipper", convoy=n, last_seen=now())
            save(files, worker_path(me["id"]), w)
            return n

        n = transact(f"convoy new by {me['id']}", me["id"], mutate)
        print(f"harbor: convoy {n} assembling on base {short(base)}; skipper {me['id']}")
        return 0

    # add
    if not git("check-ref-format", "--branch", args.branch, check=False):
        raise HarborError("USAGE", f"'{args.branch}' is not a branch name")
    tip = fetch(args.branch)
    if tip is None:
        raise HarborError("BRANCH_NOT_PUSHED", f"{args.branch} is not on {REMOTE}: the vessel pushes its branch first")
    if args.head and rev(args.head) != tip:
        raise HarborError("HEAD_MISMATCH", f"{REMOTE}/{args.branch} is at {short(tip)}, not the delivered {args.head}: "
                          "a commit after the delivery voids it; seal the new tip and deliver that")
    base = fetch(MAIN)
    if not base:
        raise HarborError("NO_MAIN", f"{REMOTE} has no {MAIN}: the hotspots are measured against it")
    mb = git("merge-base", base, tip, check=False)
    if not mb:
        raise HarborError("UNRELATED_BRANCH", f"{args.branch} shares no history with {MAIN}")
    changed = [p for p in git("diff", "--name-only", mb, tip).splitlines() if p]
    story = args.story
    if not story:
        found = {s.strip() for s in git("log", f"{mb}..{tip}", "--format=%(trailers:key=Story,valueonly)").splitlines() if s.strip()}
        story = ", ".join(sorted(found)) or None
    spots = hotspots_of(changed, cfg["hotspots"])

    def mutate(files, head):
        w = registered(files)
        cs = convoys(files)
        c = cs.get(args.number)
        if not c:
            raise HarborError("UNKNOWN_CONVOY", f"there is no convoy {args.number}")
        if c.get("state") not in ("assembling", "waiting"):
            raise HarborError("CONVOY_CLOSED", f"convoy {args.number} is {c.get('state')}: vessels enter while it is "
                              "assembling or waiting")
        if c.get("skipper") != me["id"]:
            raise HarborError("NOT_SKIPPER", f"convoy {args.number}'s skipper is {c.get('skipper') or 'nobody'}; "
                              "vessels hand their branch and hash to the skipper")
        seal = load(files, f"harbor/seals/{tip}.toml")
        if not seal:
            raise HarborError("NO_SEAL", f"{args.branch}@{short(tip)} has no seal: the vessel runs harbor.py seal on "
                              "that exact commit")
        if seal.get("exit") != 0:
            raise HarborError("SEAL_RED", f"the seal of {short(tip)} failed (exit {seal.get('exit')}, `{seal.get('command')}`)")
        for m, other in cs.items():
            if other.get("state") not in OPEN:
                continue
            for v in other.get("vessels") or []:
                if v["branch"] == args.branch and m != args.number:
                    raise HarborError("VESSEL_TAKEN", f"{args.branch} is already in convoy {m}")
                if v["branch"] != args.branch and (shared := sorted(set(spots) & set(v.get("hotspots") or []))):
                    raise HarborError("HOTSPOT_HELD", f"{args.branch} touches hotspot {', '.join(shared)}, held by "
                                      f"{v['branch']} in convoy {m}: it waits until that one sails, then rebases")
        vessels = [v for v in c.get("vessels") or [] if v["branch"] != args.branch]
        again = len(vessels) != len(c.get("vessels") or [])
        vessels.append({"branch": args.branch, "head": tip, "story": story, "tier": args.tier, "hotspots": spots,
                        "seal_base": seal.get("base"), "added": now(), "added_by": me["id"]})
        c["vessels"] = vessels
        c.setdefault("events", []).append(event(me["id"], "redelivered" if again else "add", f"{args.branch}@{short(tip)}"))
        save(files, f"harbor/convoys/{args.number}.toml", c)
        w["last_seen"] = now()
        save(files, worker_path(me["id"]), w)
        return again

    again = transact(f"convoy {args.number} add {args.branch}@{short(tip)}", me["id"], mutate)
    print(f"harbor: {args.branch}@{short(tip)} {'redelivered to' if again else 'added to'} convoy {args.number}"
          + (f" (hotspots: {', '.join(spots)})" if spots else ""))
    return 0


def convoy_status(args) -> int:
    head, files = snapshot()
    cs = convoys(files)
    main_tip = fetch(MAIN)
    pick = {args.number: cs[args.number]} if args.number else {n: c for n, c in cs.items() if c.get("state") in OPEN}
    if args.number and args.number not in cs:
        raise HarborError("UNKNOWN_CONVOY", f"there is no convoy {args.number}")
    if not pick:
        print(f"harbor: no open convoys (logbook @{short(head)})")
        return 0
    for n, c in pick.items():
        vs = c.get("vessels") or []
        print(f"convoy {n} · {c.get('state')} · skipper {c.get('skipper') or c.get('imported_skipper') or '—'} · "
              f"{len(vs)} vessel(s) · base {short(c.get('base'))}")
        if c.get("state") in OPEN and c.get("base") and main_tip and c["base"] != main_tip:
            print(f"  main moved: {short(c['base'])} → {short(main_tip)}")
        for v in vs:
            tip = fetch(v["branch"]) if c.get("state") in OPEN else v["head"]
            note = "" if tip == v["head"] else (" · branch gone from the remote" if tip is None
                                                  else f" · moved to {short(tip)} after delivery: the delivery is void")
            print(f"  {v['branch']}@{short(v['head'])} {v.get('story') or ''}{note}".rstrip())
        missing = [s for s in c.get("expected") or [] if s not in {v.get("story") for v in vs}]
        if missing:
            print(f"  expected, not delivered: {', '.join(missing)}")
    return 0


def cmd_log(args) -> int:
    keelokit()
    head, files = snapshot()
    sys.stdout.write(files.get("LOGBOOK.md", ""))
    print(f"\n(logbook @{short(head)})")
    return 0


# --- one-time import of a hand-kept board -------------------------------------------------------

BOARD_STATES = [("armando", "assembling"), ("assembling", "assembling"), ("esperando", "waiting"), ("waiting", "waiting"),
                ("listo", "ready"), ("ready", "ready"), ("verificando", "verifying"), ("verifying", "verifying"),
                ("en main", "sailed"), ("on main", "sailed"), ("sailed", "sailed"), ("abortado", "aborted"),
                ("cancelado", "aborted"), ("aborted", "aborted")]
COLS = {"number": ("tren", "train", "convoy", "#", "n", "numero"), "skipper": ("jefe", "jefa", "skipper", "chief", "conductor"),
        "branch": ("rama", "branch"), "state": ("estado", "state"), "handoff": ("handoff", "enlace", "link")}


def plain(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(ch) != "Mn").strip()


def board_tables(text: str) -> list[list[list[str]]]:
    tables, cur = [], []
    for line in text.splitlines() + [""]:
        s = line.strip()
        if s.startswith("|") and s.endswith("|"):
            cells = [x.strip() for x in s.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", x) for x in cells if x):
                cur.append(cells)
        elif cur:
            tables.append(cur)
            cur = []
    return tables


def parse_board(text: str) -> tuple[list[dict], list[str], str | None]:
    rows, skipped = [], []
    for table in board_tables(text):
        header = [plain(h) for h in table[0]]
        idx = {k: next((i for i, h in enumerate(header) if h in names), None) for k, names in COLS.items()}
        if idx["number"] is None or idx["state"] is None:
            continue
        for r in table[1:]:
            get = (lambda k: r[idx[k]] if idx[k] is not None and idx[k] < len(r) else "")
            num = re.search(r"\d+", get("number"))
            st = next((v for k, v in BOARD_STATES if k in plain(get("state"))), None)
            if not num or not st:
                skipped.append(" | ".join(r))
                continue
            rows.append({"number": int(num.group()), "state": st, "skipper": get("skipper").strip("` ") or None,
                         "branch": (re.findall(r"`([^`]+)`", get("branch")) or [get("branch").strip()])[0] or None,
                         "handoff": get("handoff") or None, "row": " | ".join(r)})
    m = re.search(r"coordina[^:\n]*:\s*(.+)", text, re.IGNORECASE)
    return rows, skipped, (m.group(1).strip() if m else None)


def cmd_import_board(args) -> int:
    keelokit()
    me = identity(args.session, need_session=False)
    src = Path(args.file)
    try:
        text = src.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise HarborError("USAGE", f"can't read {src}: {e}")
    rows, skipped, coordinator = parse_board(text)

    def mutate(files, head):
        if "harbor/imported/BOARD.md" in files:
            raise HarborError("ALREADY_IMPORTED", "a BOARD.md was imported already (harbor/imported/); the import runs once")
        cs = convoys(files)
        done, left = [], list(skipped)
        for r in rows:
            if r["number"] in cs:
                left.append(f"{r['row']} (convoy {r['number']} already exists)")
                continue
            save(files, f"harbor/convoys/{r['number']}.toml", {
                "schema": SCHEMA, "number": r["number"], "state": r["state"], "branch": r["branch"] or f"convoy/{r['number']}",
                "imported": True, "imported_skipper": r["skipper"], "handoff": r["handoff"], "created": now(),
                "vessels": [], "events": [event(me["id"], "imported", r["row"])]})
            cs[r["number"]] = True
            done.append(r["number"])
        files["harbor/imported/BOARD.md"] = text
        save(files, "harbor/imported/board.toml", {
            "schema": SCHEMA, "source": str(args.file), "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "imported": now(), "by": me["id"], "coordinator": coordinator, "convoys": done, "skipped": left})
        return done, left

    done, left = transact(f"import BOARD.md ({len(rows)} convoy rows)", me["id"], mutate)
    print(f"harbor: imported {len(done)} convoy(s) from {src.name}: {', '.join(map(str, done)) or 'none'}"
          + (f"; {len(left)} row(s) left out, listed in harbor/imported/board.toml" if left else ""))
    if coordinator:
        print(f"harbor: the board names a coordinator ({coordinator}); the watch is not imported: "
              "/harbor:harbormaster takeover")
    return 0


# --- entry --------------------------------------------------------------------------------------

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="harbor.py", description="Harbor: convoys of branches on top of Keelokit.")
    p.add_argument("--session", help="this session's id (else $HARBOR_SESSION or $CLAUDE_SESSION_ID)")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--hook", action="store_true", help="read the SessionStart JSON on stdin")
    sub.add_parser("init")
    a = sub.add_parser("account")
    asub = a.add_subparsers(dest="action", required=True)
    s = asub.add_parser("set")
    s.add_argument("account")
    s.add_argument("--max-sessions", type=int, required=True)
    s = asub.add_parser("pause")
    s.add_argument("account")
    s.add_argument("--until", required=True)
    s.add_argument("--reason")
    s = asub.add_parser("resume")
    s.add_argument("account")
    w = sub.add_parser("worker")
    wsub = w.add_subparsers(dest="action", required=True)
    s = wsub.add_parser("register")
    s.add_argument("--role", choices=ROLES, required=True)
    s.add_argument("--convoy", type=int)
    s.add_argument("--branch")
    s.add_argument("--model")
    s = wsub.add_parser("end")
    for f in ("--branch", "--head", "--verified", "--pending", "--worktree", "--log"):
        s.add_argument(f)
    s = sub.add_parser("seal")
    s.add_argument("--rerun", action="store_true", help="run the verify even if Keelokit already passed this commit")
    cv = sub.add_parser("convoy")
    csub = cv.add_subparsers(dest="action", required=True)
    s = csub.add_parser("new")
    s.add_argument("--title")
    s.add_argument("--expect", nargs="*")
    s.add_argument("--depends", nargs="*", type=int)
    s = csub.add_parser("add")
    s.add_argument("number", type=int)
    s.add_argument("branch")
    s.add_argument("--head")
    s.add_argument("--story")
    s.add_argument("--tier", choices=TIERS)
    s = csub.add_parser("status")
    s.add_argument("number", type=int, nargs="?")
    sub.add_parser("log")
    i = sub.add_parser("import-board")
    i.add_argument("file")
    return p


COMMANDS = {"check": cmd_check, "init": cmd_init, "account": cmd_account, "worker": cmd_worker, "seal": cmd_seal,
            "convoy": cmd_convoy, "log": cmd_log, "import-board": cmd_import_board}


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    global ROOT, REMOTE
    try:
        args = parser().parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 2
    start = Path(root or os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True)
    if top.returncode != 0:
        if args.cmd == "check":
            return 0
        print("harbor: NOT_A_REPO: run it inside the project's git repository", file=sys.stderr)
        return 2
    ROOT = Path(top.stdout.strip())
    REMOTE = os.environ.get("HARBOR_REMOTE", "origin")
    try:
        return COMMANDS[args.cmd](args)
    except HarborError as e:
        print(f"harbor: {e.code}: {e.why}", file=sys.stderr)
        return 2 if e.code in ENV_CODES else 1


if __name__ == "__main__":
    sys.exit(main())
