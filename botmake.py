"""
BOT MAKE  -  resellers create their own copy of the shop bot from the website.

How it works
  * bot_template/main.py is the bot code (your main.py). Every created bot is a separate
    Python process started from its own folder:  data/bot_instances/<instance_id>/
        main.py            copy of the template (refreshed on every start, so updating the template updates all bots)
        shop_data.db       the bot's OWN database (nobody else's data is ever mixed in)
        .bot_env.json      bot name, token, admin IDs (never shown to resellers)
        bot.log            output of the bot (Admin > Bots > Log)
  * Name / token / admin IDs are handed to the bot through environment variables
    (BOT_BRAND_NAME, BOT_TOKEN, BOT_ADMIN_IDS) - exactly the way the bot already expects them.
  * Admin IDs of a created bot = YOUR admin ID (always, cannot be removed inside the bot) + the ID the reseller typed.
  * A watchdog restarts bots that crashed, and starts all bots again after the website restarts.
"""
import os, re, json, time, shutil, signal, socket, sqlite3, hashlib, secrets, subprocess, sys, threading, zipfile, io, tempfile
from pathlib import Path
from flask import request, redirect, render_template, flash, Response, send_file, abort

HERE = Path(__file__).resolve().parent


def find_template():
    """Where is the bot code?  1) uploaded in Admin > Bots  2) bot_main.py next to app.py  3) bot_template/main.py  4) main.py.
    Returns the main.py path (a main.enc next to it is copied too) or None."""
    for p in (Path(H["data_dir"]) / "bot_template" / "main.py", HERE / "bot_main.py",
              HERE / "bot_template" / "main.py", HERE / "main.py"):
        try:
            if p.is_file() and p.stat().st_size > 1000:
                return p
        except OSError:
            pass
    return None

TOKEN_RE = re.compile(r"^\d{6,14}:[A-Za-z0-9_-]{30,60}$")
DEFAULT_MAX_BOTS = 5

H = {}                      # helpers handed over by app.py
_locks = {}
_locks_guard = threading.Lock()
_procs = {}                 # instance_id -> Popen (only for processes started by this worker)
_gave_up = set()            # instance ids the watchdog stopped retrying (crash loop)
_restarts = {}              # instance_id -> [timestamps of automatic restarts]


# ------------------------------------------------------------------ small helpers
def _lock(iid):
    with _locks_guard:
        return _locks.setdefault(iid, threading.RLock())


def root():
    p = Path(H["data_dir"]) / "bot_instances"
    p.mkdir(parents=True, exist_ok=True)
    return p.resolve()


def inst_dir(iid):
    if not re.fullmatch(r"[0-9a-f]{16}", str(iid or "")):
        raise ValueError("bad instance id")
    return root() / iid


def _read_env(iid):
    try:
        return json.loads((inst_dir(iid) / ".bot_env.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_env(iid, data):
    p = inst_dir(iid) / ".bot_env.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def _clean(text, token=""):
    text = str(text or "")
    if token:
        text = text.replace(token, "***TOKEN***")
    return re.sub(r"\d{6,14}:[A-Za-z0-9_-]{30,60}", "***TOKEN***", text)


def _tail(path, n=6000):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - n))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _owner_id():
    return re.sub(r"\D", "", str(H["owner_admin"]() or ""))


def _admin_list(extra):
    out = []
    for x in (_owner_id(), re.sub(r"\D", "", str(extra or ""))):
        if x and x not in out:
            out.append(x)
    return out


def get_max():
    try:
        return max(1, int(H["get_setting"]("bot_max") or DEFAULT_MAX_BOTS))
    except (TypeError, ValueError):
        return DEFAULT_MAX_BOTS


def rows():
    return H["q"]("SELECT * FROM reseller_bots ORDER BY id DESC")


def row_by_iid(iid):
    return H["q"]("SELECT * FROM reseller_bots WHERE instance_id=?", (iid,), one=True)


def row_for_reseller(rid):
    return H["q"]("SELECT * FROM reseller_bots WHERE reseller_id=?", (rid,), one=True)


def init_table():
    H["q"]("""CREATE TABLE IF NOT EXISTS reseller_bots(
        id INTEGER PRIMARY KEY, instance_id TEXT UNIQUE NOT NULL,
        reseller_id INTEGER REFERENCES resellers(id) ON DELETE SET NULL, reseller_name TEXT,
        bot_name TEXT NOT NULL, bot_username TEXT, admin_id TEXT NOT NULL,
        token_hash TEXT NOT NULL, token_tail TEXT, desired TEXT NOT NULL DEFAULT 'running',
        created INTEGER NOT NULL, updated INTEGER NOT NULL, note TEXT DEFAULT '')""", commit=True)


# ------------------------------------------------------------------ process control
def _pid_of(iid):
    p = _procs.get(iid)
    if p is not None and p.poll() is None:
        return p.pid
    try:
        pid = int((inst_dir(iid) / ".pid").read_text().strip())
    except Exception:
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    try:                                           # make sure this pid really is OUR bot (pids get reused)
        cmd = Path("/proc/%d/cmdline" % pid).read_bytes().decode("utf-8", "ignore")
        if iid not in cmd:
            return None
    except OSError:
        pass
    return pid


def is_alive(iid):
    return _pid_of(iid) is not None


def is_ready(iid):
    return (inst_dir(iid) / ".bot_ready").exists()


def state_of(row):
    iid = row["instance_id"]
    if is_alive(iid):
        return "running" if is_ready(iid) else "starting"
    if row["desired"] == "stopped":
        return "stopped"
    return "gaveup" if iid in _gave_up else "down"


def _free_port():
    for _ in range(40):
        port = 20000 + secrets.randbelow(40000)
        if str(port) == os.environ.get("PORT"):
            continue
        s = socket.socket()
        try:
            s.bind(("0.0.0.0", port))
            return port
        except OSError:
            continue
        finally:
            s.close()
    return 18000 + secrets.randbelow(1000)


def _child_env(iid, env_saved):
    keep = ("PATH", "HOME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "PYTHONPATH",
            "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
    env = {k: v for k, v in os.environ.items() if k in keep}      # nothing secret of the website is passed on
    d = inst_dir(iid)
    env.update({
        "BOT_TOKEN": env_saved["token"],
        "BOT_ADMIN_IDS": ",".join(_admin_list(env_saved.get("admin_id"))),
        "BOT_BRAND_NAME": env_saved["name"],
        "BOT_CREATOR_ENABLED": "0",
        "BOT_EXPIRES_AT": "0",
        "BOT_INSTANCE_ID": iid,
        "BOT_INSTANCES_DIR": str(root()),
        "BOT_DB_PATH": str(d / "shop_data.db"),
        "BOT_CHILD_READY_FILE": str(d / ".bot_ready"),
        "BOT_CHILD_HTTP_PORT": str(env_saved.get("port") or _free_port()),
        "BOT_TELEGRAM_WORKERS": "4", "USER_TASK_WORKERS": "4", "PAYMENT_TASK_WORKERS": "2", "HTTP_POOL_SIZE": "10",
        "PYTHONUNBUFFERED": "1",
    })
    return env


def _sync_code(iid):
    """Copy the current template code into the bot's folder (so a new main.py reaches every bot on its next start)."""
    src = find_template()
    if not src:
        raise RuntimeError("the bot code (bot_main.py) is not uploaded yet")
    d = inst_dir(iid)
    shutil.copy2(src, d / "main.py")
    enc = src.with_name("main.enc")
    if enc.exists():
        shutil.copy2(enc, d / "main.enc")


def spawn(iid, wait=20):
    """Start the bot process. Returns (ok, message)."""
    with _lock(iid):
        if is_alive(iid):
            return True, "already running"
        d = inst_dir(iid)
        saved = _read_env(iid)
        if not saved.get("token"):
            return False, "this bot has no saved token"
        try:
            _sync_code(iid)
        except Exception as e:
            return False, str(e)
        if not saved.get("port"):
            saved["port"] = _free_port()
            _write_env(iid, saved)
        for f in (".bot_ready", ".pid"):
            try:
                (d / f).unlink()
            except OSError:
                pass
        log_path = d / "bot.log"
        try:
            if log_path.exists() and log_path.stat().st_size > 2_000_000:
                keep = _tail(log_path, 200_000)
                log_path.write_text(keep, encoding="utf-8")
        except OSError:
            pass
        log = open(log_path, "a", encoding="utf-8")
        try:
            log.write("\n===== start %s =====\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
            log.flush()
            proc = subprocess.Popen([sys.executable, "-u", str(d / "main.py")], cwd=str(d), env=_child_env(iid, saved),
                                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        except Exception as e:
            log.close()
            return False, "could not start: %s" % e
        finally:
            try:
                log.close()
            except Exception:
                pass
        _procs[iid] = proc
        try:
            (d / ".pid").write_text(str(proc.pid))
        except OSError:
            pass
        deadline = time.time() + wait
        while time.time() < deadline:
            if proc.poll() is not None:
                _procs.pop(iid, None)
                return False, "the bot stopped while starting: " + _clean(_tail(log_path, 1500).strip()[-700:], saved["token"])
            if (d / ".bot_ready").exists():
                return True, "running"
            time.sleep(0.4)
        return True, "starting (still loading)"


def stop(iid, grace=8):
    with _lock(iid):
        pid = _pid_of(iid)
        if pid is None:
            _procs.pop(iid, None)
            return True
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        end = time.time() + grace
        p = _procs.get(iid)
        while time.time() < end:
            if p is not None:
                if p.poll() is not None:
                    break
            else:
                try:
                    os.kill(pid, 0)
                except OSError:
                    break
            time.sleep(0.2)
        else:
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
            if p is not None:
                try:
                    p.wait(3)
                except Exception:
                    pass
        _procs.pop(iid, None)
        for f in (".pid", ".bot_ready"):
            try:
                (inst_dir(iid) / f).unlink()
            except OSError:
                pass
        return True


def set_desired(iid, value, note=""):
    H["q"]("UPDATE reseller_bots SET desired=?, updated=?, note=? WHERE instance_id=?",
           (value, int(time.time()), note, iid), commit=True)


def delete_bot(iid):
    with _lock(iid):
        stop(iid)
        H["q"]("DELETE FROM reseller_bots WHERE instance_id=?", (iid,), commit=True)
        try:
            shutil.rmtree(inst_dir(iid), ignore_errors=True)
        except Exception:
            pass
        _gave_up.discard(iid)
        _restarts.pop(iid, None)


# ------------------------------------------------------------------ watchdog
def _watchdog():
    time.sleep(6)
    first = True
    while True:
        try:
            for r in rows():
                iid = r["instance_id"]
                if r["desired"] != "running" or is_alive(iid) or iid in _gave_up:
                    continue
                r2 = row_by_iid(iid)                      # the list above can be stale (admin pressed Stop/Delete meanwhile)
                if not r2 or r2["desired"] != "running":
                    continue
                now = time.time()
                hist = [t for t in _restarts.get(iid, []) if now - t < 600]
                if not first and len(hist) >= 4:
                    _gave_up.add(iid)
                    set_desired(iid, "running", "crashes again and again - see Log, then press Start")
                    continue
                if not first:
                    hist.append(now)
                    _restarts[iid] = hist
                ok, msg = spawn(iid, wait=25)
                print("[botmake] %s %s: %s" % ("boot-start" if first else "auto-restart", iid, msg), flush=True)
                time.sleep(2)                       # start bots one after the other (memory)
            first = False
        except Exception as e:
            print("[botmake] watchdog error: %s" % e, flush=True)
        time.sleep(30)


# ------------------------------------------------------------------ telegram helpers
def _tg(token, method, payload=None, read=10, tries=1):
    last = None
    for i in range(tries):
        try:
            r = H["tg_post"](token, method, payload or {}, read)
            return r.json()
        except Exception as e:
            last = {"ok": False, "network": True, "description": "Cannot reach Telegram (%s)" % type(e).__name__}
            time.sleep(0.5)
    return last


def _menu(token, admin_ids):
    _tg(token, "setMyCommands", {"commands": [{"command": "start", "description": "Open main menu"}]})
    for a in admin_ids:
        try:
            _tg(token, "setMyCommands", {"commands": [{"command": "start", "description": "Open main menu"},
                                                       {"command": "admin", "description": "Open admin panel"}],
                                         "scope": {"type": "chat", "chat_id": int(a)}})
        except Exception:
            pass


# ------------------------------------------------------------------ create
def create_bot(reseller, name, token, admin_id):
    """Returns (ok, message). reseller is a row of the resellers table."""
    name = re.sub(r"\s+", " ", (name or "").strip())
    token = (token or "").strip()
    admin_id = re.sub(r"\s", "", admin_id or "")
    if not (1 <= len(name) <= 40) or re.search(r"[<>\x00-\x1f]", name):
        return False, "Bot name must be 1-40 characters (no < > symbols)."
    if not TOKEN_RE.match(token):
        return False, "That does not look like a bot API token. Copy it from @BotFather (like 123456789:AAxxxx...)."
    if not re.fullmatch(r"\d{5,15}", admin_id):
        return False, "Admin ID must be a Telegram numeric ID (digits only)."
    if row_for_reseller(reseller["id"]):
        return False, "You already have a bot. Ask the admin if you need a new one."
    if not find_template():
        return False, "Bot creation is not ready yet (admin has not uploaded the bot code). Please tell the admin."
    if len(rows()) >= get_max():
        return False, "Bot limit reached. Please contact the admin."
    h = hashlib.sha256(token.encode()).hexdigest()
    if H["q"]("SELECT 1 FROM reseller_bots WHERE token_hash=?", (h,), one=True) or token == (H["site_token"]() or ""):
        return False, "This bot token is already in use. Make a new bot in @BotFather and use its token."
    me = _tg(token, "getMe", read=12, tries=3)
    if not me.get("ok"):
        if me.get("network"):
            return False, "Telegram is slow to answer right now. Nothing was created - please press CREATE BOT again."
        why = str(me.get("description") or "unknown error")
        return False, "Telegram refused this token: %s" % ("token is wrong or revoked" if "nauthorized" in why else why)
    username = (me.get("result") or {}).get("username") or ""
    iid = secrets.token_hex(8)
    d = inst_dir(iid)
    d.mkdir(parents=True, exist_ok=False)
    try:
        sqlite3.connect(str(d / "shop_data.db")).close()                      # fresh, empty database
        _write_env(iid, {"token": token, "name": name, "admin_id": admin_id, "port": _free_port()})
        now = int(time.time())
        H["q"]("INSERT INTO reseller_bots(instance_id,reseller_id,reseller_name,bot_name,bot_username,admin_id,token_hash,"
               "token_tail,desired,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               (iid, reseller["id"], reseller["username"], name, username, admin_id, h, token[-4:], "running", now, now),
               commit=True)
    except Exception as e:
        shutil.rmtree(d, ignore_errors=True)
        return False, "Could not create the bot folder: %s" % e
    admins = _admin_list(admin_id)
    threading.Thread(target=_menu, args=(token, admins), daemon=True).start()
    ok, msg = spawn(iid, wait=25)
    if not ok:
        delete_bot(iid)
        return False, "The bot could not start. %s" % msg
    try:
        H["notify_admin"]("<blockquote>\U0001F916 <b>NEW BOT CREATED</b></blockquote>\n\U0001F464 Reseller: <b>%s</b>\n"
                          "\U0001F4DB Bot name: <b>%s</b>\n\U0001F517 @%s\n\U0001F194 Admin ID: <code>%s</code>"
                          % (H["esc"](reseller["username"]), H["esc"](name), H["esc"](username), admin_id))
    except Exception:
        pass
    return True, "Your bot is ready: @%s" % username


# ------------------------------------------------------------------ database tools
def _find_db_bytes(upload):
    data = upload.read()
    if not data:
        raise ValueError("The file is empty.")
    if data[:16] == b"SQLite format 3\x00":
        return data
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = [i for i in zf.infolist() if not i.is_dir() and i.filename.lower().endswith((".db", ".sqlite", ".sqlite3"))
                     and ".." not in i.filename]
            if not names:
                raise ValueError("No database file (.db) inside this zip.")
            names.sort(key=lambda i: (0 if os.path.basename(i.filename).lower() == "shop_data.db" else 1, -i.file_size))
            blob = zf.read(names[0])
            if blob[:16] != b"SQLite format 3\x00":
                raise ValueError("The .db inside the zip is not a SQLite database.")
            return blob
    raise ValueError("Upload the bot's database (.db) or a .zip that contains it.")


def replace_db(iid, upload):
    blob = _find_db_bytes(upload)
    with _lock(iid):
        d = inst_dir(iid)
        tmp = d / "incoming.db"
        tmp.write_bytes(blob)
        try:
            c = sqlite3.connect(str(tmp))
            try:
                if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("The database is damaged (integrity check failed).")
                n = c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
                if not n:
                    raise ValueError("The database has no tables.")
            finally:
                c.close()
        except sqlite3.Error as e:
            tmp.unlink(missing_ok=True)
            raise ValueError("Not a valid database: %s" % e)
        except ValueError:
            tmp.unlink(missing_ok=True)
            raise
        was = is_alive(iid)
        stop(iid)
        cur = d / "shop_data.db"
        if cur.exists():
            shutil.copy2(cur, d / ("shop_data.db.before-%s" % time.strftime("%Y%m%d-%H%M%S")))
            olds = sorted(d.glob("shop_data.db.before-*"))
            for o in olds[:-3]:                                         # keep only the last 3 safety copies
                o.unlink(missing_ok=True)
        for suf in ("-wal", "-shm", "-journal"):
            Path(str(cur) + suf).unlink(missing_ok=True)
        os.replace(tmp, cur)
        r = row_by_iid(iid)
        if was or (r and r["desired"] == "running"):
            _gave_up.discard(iid)
            return spawn(iid, wait=25)
        return True, "Database replaced (bot is stopped)."


def snapshot_db(iid):
    """Consistent copy of the bot's database as bytes."""
    src = inst_dir(iid) / "shop_data.db"
    if not src.exists():
        raise FileNotFoundError("no database yet")
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        a = sqlite3.connect(str(src), timeout=20)
        b = sqlite3.connect(tmp)
        try:
            a.backup(b)
        finally:
            b.close()
            a.close()
        return Path(tmp).read_bytes()
    finally:
        Path(tmp).unlink(missing_ok=True)


def backup_all_zip():
    buf = io.BytesIO()
    reg = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in rows():
            iid = r["instance_id"]
            env = _read_env(iid)
            reg.append(dict(instance_id=iid, reseller_name=r["reseller_name"], bot_name=r["bot_name"], bot_username=r["bot_username"],
                            admin_id=r["admin_id"], desired=r["desired"], created=r["created"], token=env.get("token", "")))
            try:
                zf.writestr("%s/shop_data.db" % iid, snapshot_db(iid))
            except Exception:
                pass
        zf.writestr("registry.json", json.dumps(dict(app="reseller-bots", version=1, bots=reg), ensure_ascii=False))
    return buf.getvalue()


def restore_all_zip(upload):
    data = upload.read()
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise ValueError("This is not a bots backup (.zip).")
    done = skipped = 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        try:
            reg = json.loads(zf.read("registry.json").decode("utf-8"))
        except Exception:
            raise ValueError("registry.json is missing - this is not a bots backup.")
        if reg.get("app") != "reseller-bots":
            raise ValueError("This is not a bots backup of this panel.")
        for b in reg.get("bots", []):
            iid = str(b.get("instance_id") or "")
            token = str(b.get("token") or "")
            if not re.fullmatch(r"[0-9a-f]{16}", iid) or not TOKEN_RE.match(token):
                skipped += 1
                continue
            h = hashlib.sha256(token.encode()).hexdigest()
            if row_by_iid(iid) or H["q"]("SELECT 1 FROM reseller_bots WHERE token_hash=?", (h,), one=True):
                skipped += 1
                continue
            res = H["q"]("SELECT id, username FROM resellers WHERE username=?", (b.get("reseller_name"),), one=True)
            d = inst_dir(iid)
            d.mkdir(parents=True, exist_ok=True)
            member = "%s/shop_data.db" % iid
            if member in zf.namelist():
                (d / "shop_data.db").write_bytes(zf.read(member))
            else:
                sqlite3.connect(str(d / "shop_data.db")).close()
            _write_env(iid, {"token": token, "name": b.get("bot_name") or "BOT", "admin_id": str(b.get("admin_id") or ""),
                             "port": _free_port()})
            now = int(time.time())
            H["q"]("INSERT INTO reseller_bots(instance_id,reseller_id,reseller_name,bot_name,bot_username,admin_id,token_hash,"
                   "token_tail,desired,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (iid, res["id"] if res else None, b.get("reseller_name") or "", b.get("bot_name") or "BOT",
                    b.get("bot_username") or "", str(b.get("admin_id") or ""), h, token[-4:],
                    "stopped" if b.get("desired") == "stopped" else "running", int(b.get("created") or now), now), commit=True)
            done += 1
    return done, skipped          # the watchdog starts the restored bots within ~30 seconds


# ------------------------------------------------------------------ routes
def setup(app, **helpers):
    H.update(helpers)
    init_table()
    reseller_required, admin_required = H["reseller_required"], H["admin_required"]
    threading.Thread(target=_watchdog, daemon=True, name="bot-watchdog").start()

    @app.template_filter("botstate")
    def _botstate(r):
        return state_of(r)

    # ---------------- reseller
    @app.route("/bot-make", methods=["GET", "POST"])
    @reseller_required
    def bot_make():
        r = request.r
        mine = row_for_reseller(r["id"])
        if request.method == "POST" and mine:
            flash("You already have a bot. Ask the admin if you need a new one.", "err")
            return redirect("/bot-make")
        if request.method == "POST":
            key = "botmake:%s" % r["id"]
            if H["rl_blocked"](key, 6, 600):
                flash("Too many tries. Wait a few minutes.", "err")
                return redirect("/bot-make")
            H["rl_hit"](key)
            ok, msg = create_bot(r, request.form.get("name"), request.form.get("token"), request.form.get("admin_id"))
            flash(msg, "ok" if ok else "err")
            return redirect("/bot-make")
        return render_template("bot_make.html", r=r, mine=mine, page="botmake",
                               state=(state_of(mine) if mine else ""), full=(not mine and len(rows()) >= get_max()))

    # ---------------- admin
    @app.route("/admin/bots", methods=["GET", "POST"])
    @admin_required
    def admin_bots():
        if request.method == "POST" and request.form.get("action") == "max":
            try:
                n = max(1, min(200, int(request.form.get("max", ""))))
                H["set_setting"]("bot_max", str(n))
                flash("Bot limit saved: %d" % n, "ok")
            except ValueError:
                flash("Enter a number.", "err")
            return redirect("/admin/bots")
        rs = rows()
        return render_template("admin_bots.html", rows=rs, states={r["instance_id"]: state_of(r) for r in rs},
                               maxb=get_max(), owner=_owner_id(), page="bots",
                               template_ok=bool(find_template()),
                               template_info=(("%s (%d KB)" % (find_template().name if find_template().parent == HERE else
                                                              "uploaded code", find_template().stat().st_size // 1024))
                                              if find_template() else ""))

    @app.route("/admin/bots/code", methods=["POST"])
    @admin_required
    def admin_bots_code():
        f = request.files.get("file")
        data = f.read() if f and f.filename else b""
        try:
            if len(data) < 1000:
                raise ValueError("Choose your bot's main.py file.")
            compile(data.decode("utf-8"), "main.py", "exec")
        except (SyntaxError, UnicodeDecodeError, ValueError) as e:
            flash("Bot code not saved: %s" % e, "err")
            return redirect("/admin/bots")
        d = Path(H["data_dir"]) / "bot_template"
        d.mkdir(parents=True, exist_ok=True)
        (d / "main.py").write_bytes(data)
        flash("Bot code saved. New bots use it now; press 'Restart all bots' to update the running ones.", "ok")
        return redirect("/admin/bots")

    @app.route("/admin/bots/restart-all", methods=["POST"])
    @admin_required
    def admin_bots_restart_all():
        ids = [r["instance_id"] for r in rows() if r["desired"] == "running"]

        def work():
            for iid in ids:
                try:
                    stop(iid)
                    _gave_up.discard(iid)
                    spawn(iid, wait=25)
                except Exception as e:
                    print("[botmake] restart-all %s: %s" % (iid, e), flush=True)
        threading.Thread(target=work, daemon=True).start()
        flash("Restarting %d bot(s) one by one with the current bot code." % len(ids), "ok")
        return redirect("/admin/bots")

    @app.route("/admin/bots/<iid>/<action>", methods=["POST"])
    @admin_required
    def admin_bot_action(iid, action):
        r = row_by_iid(iid)
        if not r:
            abort(404)
        label = "%s (%s)" % (r["bot_name"], r["reseller_name"] or "-")
        if action == "stop":
            set_desired(iid, "stopped")
            stop(iid)
            flash("Stopped: %s" % label, "ok")
        elif action in ("start", "restart"):
            _gave_up.discard(iid)
            _restarts.pop(iid, None)
            if action == "restart":
                stop(iid)
            set_desired(iid, "running")
            ok, msg = spawn(iid, wait=25)
            flash(("Started: %s" % label) if ok else ("Could not start %s: %s" % (label, msg)), "ok" if ok else "err")
        elif action == "delete":
            delete_bot(iid)
            flash("Deleted: %s (its database is deleted too)" % label, "ok")
        elif action == "db":
            f = request.files.get("file")
            if not f or not f.filename:
                flash("Choose a database file first.", "err")
            else:
                try:
                    ok, msg = replace_db(iid, f)
                    flash(("Database added to %s. Bot: %s" % (label, msg)) if ok else ("Database saved but bot did not start: %s" % msg),
                          "ok" if ok else "err")
                except ValueError as e:
                    flash(str(e), "err")
        else:
            abort(404)
        return redirect("/admin/bots")

    @app.route("/admin/bots/<iid>/log")
    @admin_required
    def admin_bot_log(iid):
        r = row_by_iid(iid)
        if not r:
            abort(404)
        txt = _clean(_tail(inst_dir(iid) / "bot.log", 8000), _read_env(iid).get("token", "")) or "(no log yet)"
        return Response(txt, mimetype="text/plain; charset=utf-8", headers={"Cache-Control": "no-store"})

    @app.route("/admin/bots/<iid>/db.download")
    @admin_required
    def admin_bot_db_download(iid):
        r = row_by_iid(iid)
        if not r:
            abort(404)
        try:
            blob = snapshot_db(iid)
        except Exception as e:
            flash("No database to download: %s" % e, "err")
            return redirect("/admin/bots")
        return Response(blob, mimetype="application/octet-stream",
                        headers={"Content-Disposition": 'attachment; filename="%s_shop_data.db"' % re.sub(r"\W+", "_", r["bot_name"])[:30],
                                 "Cache-Control": "no-store"})

    @app.route("/admin/bots/backup")
    @admin_required
    def admin_bots_backup():
        name = "bots_backup_%s.zip" % time.strftime("%Y%m%d_%H%M", time.gmtime(time.time() + H["tz_offset"]))
        return Response(backup_all_zip(), mimetype="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="%s"' % name, "Cache-Control": "no-store"})

    @app.route("/admin/bots/restore", methods=["POST"])
    @admin_required
    def admin_bots_restore():
        f = request.files.get("file")
        if not f or not f.filename:
            flash("Choose the bots backup (.zip).", "err")
            return redirect("/admin/bots")
        try:
            done, skipped = restore_all_zip(f)
            flash("Restored %d bot(s)%s. They start within 30 seconds." % (done, (", %d skipped (already exist)" % skipped) if skipped else ""), "ok")
        except ValueError as e:
            flash(str(e), "err")
        return redirect("/admin/bots")
