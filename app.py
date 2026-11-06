import os, re, json, sqlite3, secrets, time, threading, base64, hmac, hashlib, zipfile, tempfile
import html as _html
import requests
from flask import (Flask, request, session, redirect, render_template, flash,
                   jsonify, send_from_directory, abort, Response, make_response, send_file, after_this_request)
from werkzeug.middleware.proxy_fix import ProxyFix
import tgbot
from jinja2 import DictLoader
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

DATA_DIR = os.environ.get("DATA_DIR", "data")
MUSIC_DIR = os.path.join(DATA_DIR, "music")
os.makedirs(MUSIC_DIR, exist_ok=True)
DB = os.path.join(DATA_DIR, "panel.db")
ADMIN_USER = "RGCHEAT"  # fixed on purpose (env vars ignored) - change later
ADMIN_PASS = "909090"
TZ_OFFSET = int(os.environ.get("TZ_OFFSET_MIN", "330")) * 60  # default IST
MAX_MUSIC = 20
# ---- TELEGRAM BOT (edit here, nothing else to configure) ----------------------------------------
TG_BOT_TOKEN = ""   # NEVER write the bot token here (GitHub leak!). Set it in Admin > Telegram. Optional backup: Render env TG_BOT_TOKEN
TG_ADMIN_ID = "6739795427"      # default admin Chat ID (not secret). Admin > Telegram can change it any time
EMOJI_PACKS = [x for x in (os.environ.get("EMOJI_PACKS") or "RGCHEAT99,botd3,NewsEmoji").replace(" ", "").split(",") if x]   # premium emoji packs (first = highest priority)
BRAND = "RG CHEAT"      # name shown on login + panel header
CURRENCY = "₹"         # symbol shown before money amounts (all prices are INR)
DEFAULT_API_BASE = "https://adminshops.com/api/v1"   # main provider API (editable in Admin > Main API)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-" + ADMIN_PASS)
app.config.update(SESSION_COOKIE_SAMESITE="Lax", MAX_CONTENT_LENGTH=250 * 1024 * 1024)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)   # real client IP / https behind Render


def db():
    c = sqlite3.connect(DB, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def q(sql, args=(), one=False, commit=False):
    c = db()
    try:
        cur = c.execute(sql, args)
        if commit:
            c.commit()
            return cur.lastrowid
        rows = cur.fetchall()
        return (rows[0] if rows else None) if one else rows
    finally:
        c.close()


def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY,
      product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
      name TEXT NOT NULL, days INTEGER NOT NULL, price REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS resellers(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
      pw TEXT NOT NULL, balance REAL NOT NULL DEFAULT 0, api_key TEXT UNIQUE NOT NULL,
      active INTEGER NOT NULL DEFAULT 1, created INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS custom_prices(
      reseller_id INTEGER REFERENCES resellers(id) ON DELETE CASCADE,
      plan_id INTEGER REFERENCES plans(id) ON DELETE CASCADE,
      price REAL NOT NULL, PRIMARY KEY(reseller_id, plan_id));
    CREATE TABLE IF NOT EXISTS license_keys(id INTEGER PRIMARY KEY,
      reseller_id INTEGER NOT NULL REFERENCES resellers(id) ON DELETE CASCADE,
      product_name TEXT, plan_name TEXT, key TEXT NOT NULL, price REAL NOT NULL,
      created INTEGER NOT NULL, expires INTEGER NOT NULL, via TEXT DEFAULT 'panel');
    CREATE TABLE IF NOT EXISTS music(id INTEGER PRIMARY KEY, title TEXT, url TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS stock(id INTEGER PRIMARY KEY,
      plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
      key TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0, used_by TEXT, used_at INTEGER, created INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE IF NOT EXISTS topups(id INTEGER PRIMARY KEY,
      reseller_id INTEGER NOT NULL REFERENCES resellers(id) ON DELETE CASCADE,
      amount REAL NOT NULL, order_id TEXT, qr_url TEXT, upi_id TEXT, status TEXT NOT NULL DEFAULT 'pending',
      utr TEXT, created INTEGER NOT NULL, expires INTEGER, deadline INTEGER NOT NULL, paid_at INTEGER,
      last_check INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS broadcasts(id INTEGER PRIMARY KEY, reseller_id INTEGER,
      title TEXT, body TEXT NOT NULL, created INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS broadcast_reads(broadcast_id INTEGER NOT NULL, reseller_id INTEGER NOT NULL,
      PRIMARY KEY(broadcast_id, reseller_id));
    CREATE TABLE IF NOT EXISTS devices(id INTEGER PRIMARY KEY,
      reseller_id INTEGER NOT NULL REFERENCES resellers(id) ON DELETE CASCADE,
      dev_id TEXT NOT NULL, label TEXT, ip TEXT, status TEXT NOT NULL DEFAULT 'pending',
      created INTEGER NOT NULL, decided INTEGER, last_seen INTEGER);
    CREATE TABLE IF NOT EXISTS otps(reseller_id INTEGER PRIMARY KEY, h TEXT NOT NULL, exp INTEGER NOT NULL,
      tries INTEGER NOT NULL DEFAULT 0, sent INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS tg_seen(chat_id TEXT PRIMARY KEY, name TEXT, username TEXT, ts INTEGER NOT NULL);
    """)
    cols = [r[1] for r in c.execute("PRAGMA table_info(plans)")]
    for col, ddl in (("mode", "TEXT DEFAULT 'random'"), ("ext_url", "TEXT DEFAULT ''"),
                     ("ext_method", "TEXT DEFAULT 'POST'"), ("ext_headers", "TEXT DEFAULT ''"),
                     ("ext_body", "TEXT DEFAULT ''"), ("ext_path", "TEXT DEFAULT ''"),
                     ("prov_pid", "INTEGER")):
        if col not in cols:
            c.execute("ALTER TABLE plans ADD COLUMN %s %s" % (col, ddl))
    rcols = [r[1] for r in c.execute("PRAGMA table_info(resellers)")]
    for col, ddl in (("theme", "TEXT DEFAULT ''"), ("tg_chat", "TEXT DEFAULT ''"),
                     ("otp_on", "INTEGER NOT NULL DEFAULT 1"), ("notify", "INTEGER NOT NULL DEFAULT 1"),
                     ("low_bal", "REAL NOT NULL DEFAULT 50")):
        if col not in rcols:
            c.execute("ALTER TABLE resellers ADD COLUMN %s %s" % (col, ddl))
    c.commit()
    c.close()


init_db()


# ---------------------------------------------------------------- helpers
def new_api_key():
    return "rk_" + secrets.token_hex(20)


def fmt(ts):
    return time.strftime("%d %b %Y %H:%M", time.gmtime(ts + TZ_OFFSET))


app.jinja_env.filters["dt"] = fmt
app.jinja_env.filters["dt2"] = lambda ts: time.strftime("%d/%m/%y %I:%M %p", time.gmtime(ts + TZ_OFFSET))
app.jinja_env.filters["money"] = lambda v: ("%.2f" % float(v)).rstrip("0").rstrip(".") if v is not None else "0"


def _cur(v):
    return CURRENCY + app.jinja_env.filters["money"](v)


app.jinja_env.filters["cur"] = _cur
app.jinja_env.globals.update(BRAND=BRAND, year=time.gmtime().tm_year, CURRENCY=CURRENCY)


def plan_label(days):
    days = max(int(days), 1)
    return "%d Day%s" % (days, "" if days == 1 else "s")


def price_for(rid, plan):
    cp = q("SELECT price FROM custom_prices WHERE reseller_id=? AND plan_id=?", (rid, plan["id"]), one=True)
    return (cp["price"], True) if cp else (plan["price"], False)



def get_setting(k, default=""):
    r = q("SELECT v FROM settings WHERE k=?", (k,), one=True)
    return r["v"] if r and r["v"] is not None else default


def set_setting(k, v):
    q("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)", (k, v), commit=True)


def same(a, b):
    """constant-time compare that never crashes on non-ASCII text"""
    return secrets.compare_digest(str(a).encode("utf-8"), str(b).encode("utf-8"))


# ---- main provider API (adminshops style: Bearer token, {"ok":..,"data":..})
def prov_call(method, path, payload=None):
    base = (get_setting("api_base") or DEFAULT_API_BASE).rstrip("/")
    tok = get_setting("api_token")
    if not tok:
        raise ValueError("API token not set (Admin > Main API)")
    r = requests.request(method, base + path, headers={"Authorization": "Bearer " + tok},
                         json=payload, timeout=25)
    try:
        j = r.json()
    except ValueError:
        raise ValueError("Provider HTTP %s (not JSON)" % r.status_code)
    if not isinstance(j, dict) or not j.get("ok"):
        err = j.get("error") if isinstance(j, dict) else None
        msg = err.get("message") if isinstance(err, dict) else err
        raise ValueError(str(msg or "Provider HTTP %s" % r.status_code)[:150])
    return j.get("data") or {}


def prov_generate(pid, idem):
    """Buy ONE key. Network failures are retried once with the SAME idempotency key (never double-charges)."""
    for _ in range(2):
        try:
            d = prov_call("POST", "/generate", {"product_id": int(pid), "quantity": 1, "idempotency_key": idem})
        except (requests.Timeout, requests.ConnectionError):
            continue
        keys = d.get("keys") or []
        if not keys:
            raise ValueError("Provider returned no key")
        return str(keys[0])
    raise ValueError("Provider not reachable")


def prov_status():
    """Test the connection (GET /balance) and remember the result."""
    try:
        d = prov_call("GET", "/balance")
        st = dict(ok=True, balance=float(d.get("balance", 0)), balance_usd=d.get("balance_usd"),
                  currency=d.get("currency", "INR"))
    except Exception as e:
        st = dict(ok=False, msg=str(e)[:150])
    st["ts"] = int(time.time())
    set_setting("api_status", json.dumps(st))
    return st


def load_catalog(refresh=False):
    if not refresh:
        try:
            return json.loads(get_setting("catalog_cache"))
        except ValueError:
            pass
    d = prov_call("GET", "/catalog")
    obj = dict(ts=int(time.time()), currency=d.get("currency", "INR"), usd_rate=d.get("usd_rate") or 50,
               products=d.get("products") or [])
    set_setting("catalog_cache", json.dumps(obj))
    return obj


USD_TO_INR = 30         # fixed rate: $1 = Rs 30 (used for provider prices)
DAY_PLAN_EXTRA = 2      # Rs added on every day/week/month/life plan (hour plans get +0)


def is_hour_plan(dur):
    """True for durations like '1 Hour', '2 Hours', '3hr', '6 h'."""
    return bool(re.search(r"\d\s*(hours?|hrs?|h)\b", (dur or "").lower()))


def inr_of(p, cat):
    """Price of a catalog row in INR: provider USD price x 30, +Rs 2 for day plans, +0 for hour plans."""
    usd = p.get("price_usd")
    if usd is None:  # catalog gave only a local price -> convert back to USD with the catalog's own rate
        base_rate = float(cat.get("usd_rate") or 50)
        usd = float(p.get("price") or 0) / base_rate if base_rate else 0
    price = float(usd or 0) * USD_TO_INR
    if not is_hour_plan(p.get("duration")):
        price += DAY_PLAN_EXTRA
    return round(price, 2)


def parse_days(text):
    s = (text or "").lower()
    if "life" in s:
        return 3650
    m = re.search(r"(\d+)\s*(hour|hr|h\b|day|d\b|week|w\b|month|mo|year|yr|y\b)?", s)
    if not m:
        return 1
    n, u = int(m.group(1)), (m.group(2) or "day")
    if u.startswith("h"):
        return max(1, -(-n // 24))
    if u.startswith("w"):
        return max(1, n * 7)
    if u.startswith("mo"):
        return max(1, n * 30)
    if u.startswith("y"):
        return max(1, n * 365)
    return max(1, n)


def catalog(rid):
    out = []
    for p in q("SELECT * FROM products ORDER BY id"):
        plans = []
        for pl in q("SELECT * FROM plans WHERE product_id=? ORDER BY days, id", (p["id"],)):
            price, custom = price_for(rid, pl)
            sc = q("SELECT COUNT(*) FROM stock WHERE plan_id=? AND used=0", (pl["id"],), one=True)[0]
            plans.append(dict(id=pl["id"], name=pl["name"], days=pl["days"], price=price, custom=custom,
                              mode=pl["mode"] or "random", stock=sc))
        out.append(dict(id=p["id"], name=p["name"], plans=plans))
    return out


def _dig(obj, path):
    for part in [p for p in path.split(".") if p]:
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    return obj


def fetch_external(pl):
    """Call the provider API configured on the plan and return the key text."""
    import requests
    rep = {"{days}": str(pl["days"]), "{plan}": pl["name"], "{product}": pl["pname"]}

    def sub(t):
        for k, v in rep.items():
            t = t.replace(k, v)
        return t
    headers = json.loads(sub(pl["ext_headers"])) if (pl["ext_headers"] or "").strip() else {}
    body = json.loads(sub(pl["ext_body"])) if (pl["ext_body"] or "").strip() else None
    m = (pl["ext_method"] or "POST").upper()
    kw = dict(headers=headers, timeout=25)
    if m == "GET":
        kw["params"] = body
    else:
        kw["json"] = body
    r = requests.request(m, sub(pl["ext_url"]), **kw)
    if r.status_code >= 400:
        raise ValueError("Provider HTTP %s" % r.status_code)
    if (pl["ext_path"] or "").strip():
        val = _dig(r.json(), pl["ext_path"].strip())
    else:
        val = r.text.strip()
    if not val:
        raise ValueError("Provider returned no key")
    return str(val)


def buy(rid, plan_id, via="panel"):
    c = sqlite3.connect(DB, timeout=20, isolation_level=None)
    c.row_factory = sqlite3.Row
    try:
        c.execute("BEGIN IMMEDIATE")
        r = c.execute("SELECT * FROM resellers WHERE id=?", (rid,)).fetchone()
        pl = c.execute("SELECT pl.*, pr.name pname FROM plans pl JOIN products pr ON pr.id=pl.product_id WHERE pl.id=?",
                       (plan_id,)).fetchone()
        if not r or not r["active"]:
            raise ValueError("Account disabled")
        if not pl:
            raise ValueError("Plan not found")
        cp = c.execute("SELECT price FROM custom_prices WHERE reseller_id=? AND plan_id=?", (rid, plan_id)).fetchone()
        price = cp["price"] if cp else pl["price"]
        if r["balance"] < price:
            raise ValueError("Insufficient balance")
        now = int(time.time())
        mode, key = (pl["mode"] or "random"), None
        if mode == "provider" and not pl["prov_pid"]:
            raise ValueError("Plan is not linked to the main API")
        if mode == "stock":
            row = c.execute("SELECT * FROM stock WHERE plan_id=? AND used=0 ORDER BY id LIMIT 1", (plan_id,)).fetchone()
            if not row:
                raise ValueError("Out of stock")
            key = row["key"]
            c.execute("UPDATE stock SET used=1, used_by=?, used_at=? WHERE id=?", (r["username"], now, row["id"]))
        elif mode == "random":
            pre = re.sub(r"[^A-Z0-9]", "", pl["pname"].upper())[:6] or "KEY"
            raw = secrets.token_hex(8).upper()
            key = pre + "-" + "-".join(raw[i:i + 4] for i in range(0, 16, 4))
        exp = now + int(pl["days"]) * 86400
        c.execute("UPDATE resellers SET balance=balance-? WHERE id=?", (price, rid))
        if key:
            c.execute("INSERT INTO license_keys(reseller_id,product_name,plan_name,key,price,created,expires,via) "
                      "VALUES(?,?,?,?,?,?,?,?)", (rid, pl["pname"], pl["name"], key, price, now, exp, via))
        c.execute("COMMIT")
    except Exception:
        try:
            c.execute("ROLLBACK")
        except Exception:
            pass
        c.close()
        raise
    if mode in ("api", "provider"):  # balance already reserved; refund if the provider fails
        try:
            if mode == "provider":
                key = prov_generate(pl["prov_pid"], "rp-%d-%d-%s" % (rid, now, secrets.token_hex(4)))
            else:
                key = fetch_external(pl)
        except Exception as e:
            c.execute("UPDATE resellers SET balance=balance+? WHERE id=?", (price, rid))
            c.close()
            raise ValueError("Provider error, balance refunded: %s" % str(e)[:120])
        c.execute("INSERT INTO license_keys(reseller_id,product_name,plan_name,key,price,created,expires,via) "
                  "VALUES(?,?,?,?,?,?,?,?)", (rid, pl["pname"], pl["name"], key, price, now, exp, via))
    c.close()
    bal = q("SELECT balance FROM resellers WHERE id=?", (rid,), one=True)["balance"]
    try:
        notify_purchase(r, pl, price, bal, key, via)
    except Exception:
        pass
    return dict(key=key, price=price, expires=exp, balance=bal, product=pl["pname"], plan=pl["name"])


# ---- payment gateway (FamPay style: /api/create_order.php + /api/verify.php)
DEFAULT_AMOUNTS = [200, 500, 1000, 1500, 2000, 2500]   # used until the admin sets his own list (Admin > Gateway)


def wallet_amounts():
    out = []
    for x in re.split(r"[,\s]+", get_setting("wallet_amounts", "")):
        if x.isdigit() and 1 <= int(x) <= 100000 and int(x) not in out:
            out.append(int(x))
    return out[:12] or list(DEFAULT_AMOUNTS)
DEFAULT_GW_BASE = "https://fampaygateway.site"


def gw_base():
    return (get_setting("gw_base") or DEFAULT_GW_BASE).rstrip("/")


def gw_abs(u):
    u = str(u or "")
    return gw_base() + u if u.startswith("/") else u


def gw_get(path, **params):
    key = get_setting("gw_key")
    if not key:
        raise ValueError("Payment gateway is not set up (Admin > Gateway)")
    params["api_key"] = key
    r = requests.get(gw_base() + path, params=params, timeout=20)
    try:
        return r.json()
    except ValueError:
        raise ValueError("Gateway HTTP %s (not JSON)" % r.status_code)


def gw_create(amount):
    j = gw_get("/api/create_order.php", amount=int(amount))
    d = j.get("data") if isinstance(j, dict) else None
    if not isinstance(j, dict) or j.get("status") != "success" or not isinstance(d, dict) \
            or not d.get("order_id") or not d.get("qr_url"):
        msg = (j.get("message") or j.get("error") or "Gateway error") if isinstance(j, dict) else "Gateway error"
        raise ValueError(str(msg)[:120])
    return d


def gw_verify(order_id):
    """Returns the payment data dict only when the gateway confirms a paid order (has a UTR)."""
    try:
        j = gw_get("/api/verify.php", order_id=order_id)
    except Exception:
        return None
    d = j.get("data") if isinstance(j, dict) else None
    if isinstance(j, dict) and j.get("status") == "success" and isinstance(d, dict) and d.get("utr"):
        return d
    return None


def parse_iso(v):
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(str(v)).timestamp())
    except Exception:
        return 0


def credit_topup(tid, d):
    """Add the money exactly once (safe even if several workers verify the same order)."""
    c = sqlite3.connect(DB, timeout=20, isolation_level=None)
    c.row_factory = sqlite3.Row
    try:
        c.execute("BEGIN IMMEDIATE")
        t = c.execute("SELECT * FROM topups WHERE id=?", (tid,)).fetchone()
        utr = str(d.get("utr"))
        done = (not t or t["status"] == "paid"
                or c.execute("SELECT 1 FROM topups WHERE utr=? AND id!=?", (utr, tid)).fetchone())
        try:
            paid_amt = float(d.get("amount") or t["amount"])
        except Exception:
            paid_amt = t["amount"] if t else 0
        if done or paid_amt + 0.001 < t["amount"]:
            c.execute("COMMIT")
            return False
        c.execute("UPDATE topups SET status='paid', utr=?, paid_at=? WHERE id=?", (utr, int(time.time()), tid))
        c.execute("UPDATE resellers SET balance=balance+? WHERE id=?", (t["amount"], t["reseller_id"]))
        c.execute("COMMIT")
        try:
            rr = c.execute("SELECT * FROM resellers WHERE id=?", (t["reseller_id"],)).fetchone()
            notify_topup(rr, t["amount"])
        except Exception:
            pass
        return True
    except Exception:
        try:
            c.execute("ROLLBACK")
        except Exception:
            pass
        return False
    finally:
        c.close()


def check_topup(t):
    """Verify one top-up with the gateway; returns its status (pending / paid / expired)."""
    if t["status"] == "paid":
        return "paid"
    now = int(time.time())
    if t["status"] == "pending" and now > t["deadline"]:
        q("UPDATE topups SET status='expired' WHERE id=? AND status='pending'", (t["id"],), commit=True)
    elif t["status"] == "expired" and now - t["created"] > 3600:
        return "expired"
    q("UPDATE topups SET last_check=? WHERE id=?", (now, t["id"]), commit=True)
    d = gw_verify(t["order_id"])
    if d and credit_topup(t["id"], d):
        return "paid"
    return q("SELECT status FROM topups WHERE id=?", (t["id"],), one=True)["status"]


def topup_worker():
    """Keeps verifying pending payments for 5 minutes even if the customer left the page."""
    while True:
        try:
            now = int(time.time())
            for t in q("SELECT * FROM topups WHERE status='pending'"):
                if now > t["deadline"]:
                    q("UPDATE topups SET status='expired' WHERE id=? AND status='pending'", (t["id"],), commit=True)
                elif now - (t["last_check"] or 0) >= 5:
                    check_topup(t)
        except Exception:
            pass
        time.sleep(4)


@app.context_processor
def inject_unread():
    rid = session.get("rid")
    if not rid:
        return {}
    n = q("SELECT COUNT(*) FROM broadcasts b WHERE (b.reseller_id IS NULL OR b.reseller_id=?) "
          "AND b.created>=(SELECT created FROM resellers WHERE id=?) "
          "AND NOT EXISTS(SELECT 1 FROM broadcast_reads x WHERE x.broadcast_id=b.id AND x.reseller_id=?)",
          (rid, rid, rid), one=True)[0]
    return dict(unread=n)


def reseller_required(f):
    from functools import wraps

    @wraps(f)
    def w(*a, **k):
        if not session.get("rid"):
            return redirect("/login")
        r = q("SELECT * FROM resellers WHERE id=?", (session["rid"],), one=True)
        if not r or not r["active"]:
            session.clear()
            return redirect("/login")
        if session.get("pwh") and session["pwh"] != pw_fp(r):     # password was changed elsewhere
            session.clear()
            return redirect("/login")
        if dev_check_on() and not device_ok(r["id"]):      # this browser is not an approved device
            session.clear()
            return blocked_page()
        request.r = r
        return f(*a, **k)
    return w


def admin_required(f):
    from functools import wraps

    @wraps(f)
    def w(*a, **k):
        if not session.get("admin"):
            return redirect("/admin/login")
        return f(*a, **k)
    return w


def num(v, default=0.0):
    try:
        return float(str(v).strip())
    except Exception:
        return default


# ---------------------------------------------------------------- telegram + security helpers
def tg_token():
    """Panel (Admin > Telegram) wins. Render env var TG_BOT_TOKEN is only the fallback (e.g. after a free-disk wipe)."""
    return (get_setting("tg_token") or os.environ.get("TG_BOT_TOKEN") or TG_BOT_TOKEN or "").strip()


def tg_token_source():
    if get_setting("tg_token"):
        return "panel"
    return "env" if (os.environ.get("TG_BOT_TOKEN") or TG_BOT_TOKEN) else ""


def tg_admin():
    return str(get_setting("tg_admin") or os.environ.get("ADMIN_TG_ID") or TG_ADMIN_ID or "").strip()


def emoji_overrides():
    """{plain emoji: custom_emoji_id} picked in Admin > Telegram > Premium emoji picker."""
    try:
        d = json.loads(get_setting("emoji_map", "{}") or "{}")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


# every emoji the bot uses in its messages (the picker lets you choose a premium emoji for each one)
EMOJI_ROLES = [("\u2705", "Done / Product"), ("\u274C", "Reject / Error"), ("\U0001F6D2", "Quantity"),
               ("\U0001F4B0", "Balance"), ("\U0001F4B8", "Paid / Amount"),
               ("\u23F1", "Validity"), ("\U0001F552", "Time"), ("\U0001F6AB", "Paid by / Warning"),
               ("\U0001F511", "Key"), ("\U0001F464", "Reseller"), ("\U0001F4F1", "Device"),
               ("\U0001F310", "IP"), ("\U0001F514", "Notification"), ("\U0001F513", "Login"),
               ("\U0001F510", "Login code"), ("\U0001F6A8", "Low balance"), ("\U0001F4B3", "Method"),
               ("\U0001F44B", "Welcome")]


_CLAIMS = []


def claim_admin(chat_id, secret):
    """Bot command '/admin <admin password>' makes that Telegram chat the admin (device requests go there)."""
    now = time.time()
    _CLAIMS[:] = [t for t in _CLAIMS if now - t < 600]
    if len(_CLAIMS) >= 5:
        return False
    if same(secret.strip(), ADMIN_PASS):
        set_setting("tg_admin", str(chat_id))
        return True
    _CLAIMS.append(now)
    return False


def dev_check_on():
    """Device approval is active only when the admin has set his Telegram ID (so nobody can get locked out)."""
    return get_setting("dev_check", "1") == "1" and bool(tg_admin()) and bool(tg_token())


def esc(v):
    return _html.escape(str(v if v is not None else ""))


def money_txt(v):
    return CURRENCY + app.jinja_env.filters["money"](v)


def device_decision(did, approve):
    d = q("SELECT d.*, r.username FROM devices d JOIN resellers r ON r.id=d.reseller_id WHERE d.id=?", (did,), one=True)
    if not d:
        return "Request not found"
    q("UPDATE devices SET status=?, decided=? WHERE id=?", ("approved" if approve else "denied", int(time.time()), did),
      commit=True)
    return ("Approved: " if approve else "Rejected: ") + d["username"]


def tg_seen(chat_id, name, username):
    """Remember everybody who pressed /start in the bot, so the admin can link them with one click."""
    q("INSERT OR REPLACE INTO tg_seen(chat_id,name,username,ts) VALUES(?,?,?,?)",
      (str(chat_id), (name or "")[:60], (username or "")[:40], int(time.time())), commit=True)


def otp_global_on():
    """Master switch (Admin > Telegram). OFF = nobody needs a code (use it if the bot is not delivering yet)."""
    return get_setting("otp_global", "1") == "1"


def mask_id(tc):
    tc = str(tc or "")
    return ("•" * max(len(tc) - 4, 0) + tc[-4:]) if tc else ""


bot = tgbot.Bot(tg_token, tg_admin, device_decision, BRAND, claim_admin, tg_seen,
                packs=EMOJI_PACKS, prem_on=lambda: get_setting("prem_on", "1") == "1", get_overrides=emoji_overrides)


def ua_label(ua):
    ua = ua or ""
    os_ = next((n for k, n in (("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"), ("Windows", "Windows"),
                               ("Mac OS", "macOS"), ("Linux", "Linux")) if k in ua), "Unknown OS")
    br = next((n for k, n in (("Edg/", "Edge"), ("OPR/", "Opera"), ("SamsungBrowser", "Samsung Browser"),
                              ("Firefox", "Firefox"), ("Chrome", "Chrome"), ("Safari", "Safari")) if k in ua), "Browser")
    return "%s on %s" % (br, os_)


def inr(v):
    return "%s INR" % money_txt(v)


def purchase_text(pname, days, price, bal, key, via, buyer=None):
    line = "\u2500" * 16
    extra = ("\n\U0001F464 Bought by: <b>%s</b>\n\U0001F4B0 Reseller Current Balance: <b>%s</b>\n"
             % (esc(buyer), inr(bal))) if buyer else "\n"
    return ("<blockquote>\u2705 <b>NEW PURCHASE ALERT</b></blockquote>\n%s\n"
            "\u2705 Product: <b>%s</b>\n\U0001F6D2 Quantity: 1\n\U0001F4B0 Wallet Balance: <b>%s</b>\n"
            "\u23F1 Validity: %d days (%d DAYS)\n\U0001F4B8 Paid: <b>%s</b>\n\U0001F6AB Paid by: Wallet (%s)\n"
            "\U0001F552 Time: %s\n"
            "\U0001F511 Key Issued: <code>%s</code>%s%s"
            % (line, esc(pname), inr(bal), int(days), int(days), inr(price),
               "API" if via == "api" else "Panel", fmt(time.time()), esc(key), extra, line))


def low_text(bal, lim):
    line = "\u2500" * 16
    return ("<blockquote>\U0001F6A8 <b>LOW BALANCE ALERT</b></blockquote>\n%s\n"
            "\U0001F4B0 Wallet Balance: <b>%s</b>\n\U0001F6A8 Low balance limit: <b>%s</b>\n"
            "\U0001F4B0 Please add funds to your wallet to continue purchasing keys.\n%s"
            % (line, inr(bal), inr(lim), line))


def notify_purchase(r, pl, price, bal, key, via):
    """Telegram 'NEW PURCHASE ALERT' (+ low balance alert) to the reseller. Never raises, never blocks.
    Every outcome (sent / skipped / error) is written to the delivery log (Admin > Telegram)."""
    who = r["username"]
    try:                                                # admin always gets a copy (+ who bought, current balance)
        adm = tg_admin()
        if adm:
            bot.send(adm, purchase_text(pl["pname"], pl["days"], price, bal, key, via, buyer=who),
                     what="admin purchase alert (%s)" % who)
    except Exception as e:
        bot._note(False, "-", "admin purchase alert (%s)" % who, "error: %s" % str(e)[:150])
    try:
        if not r["tg_chat"]:
            bot._note(False, "-", "purchase alert (%s)" % who, "skipped: no Telegram Chat ID linked to this reseller")
            return
        if not r["notify"]:
            bot._note(False, r["tg_chat"], "purchase alert (%s)" % who, "skipped: reseller turned alerts OFF (Security page)")
            return
        items = [(purchase_text(pl["pname"], pl["days"], price, bal, key, via), None)]
        lim = r["low_bal"] or 0
        if lim > 0 and bal < lim:                       # wallet is under the limit -> warn after every purchase
            items.append((low_text(bal, lim), None))
        bot.send_many(r["tg_chat"], items, what="purchase alert (%s)" % who)
    except Exception as e:
        import traceback
        traceback.print_exc()
        bot._note(False, "-", "purchase alert (%s)" % who, "error: %s" % str(e)[:150])


def notify_topup(r, amount, how="UPI (auto)"):
    """BALANCE ADDED: admin always gets a copy (who, how much, current balance); the reseller gets one too."""
    if not r:
        return
    who = r["username"]
    line = "\u2500" * 16
    adm = tg_admin()
    try:
        if adm:
            bot.send(adm, "<blockquote>\U0001F4B0 <b>BALANCE ADDED</b></blockquote>\n%s\n"
                          "\U0001F464 Reseller: <b>%s</b>\n\u2705 Added: <b>%s</b>\n"
                          "\U0001F4B0 Current Balance: <b>%s</b>\n\U0001F4B3 Method: %s\n\U0001F552 Time: %s\n%s"
                     % (line, esc(who), inr(amount), inr(r["balance"]), esc(how), fmt(time.time()), line),
                     what="admin balance alert (%s)" % who)
    except Exception as e:
        bot._note(False, "-", "admin balance alert (%s)" % who, "error: %s" % str(e)[:150])
    if not r["tg_chat"] or not r["notify"] or str(r["tg_chat"]) == str(adm):
        return
    bot.send(r["tg_chat"], "<blockquote>\U0001F4B0 <b>BALANCE ADDED</b></blockquote>\n"
                           "\u2705 Added: <b>%s</b>\n\U0001F4B0 Wallet Balance: <b>%s</b>"
             % (inr(amount), inr(r["balance"])), what="balance added (%s)" % who)


# ---- login protection
_FAILS = {}


def rl_blocked(key, limit=8, window=600):
    now = time.time()
    _FAILS[key] = [t for t in _FAILS.get(key, []) if now - t < window]
    return len(_FAILS[key]) >= limit


def rl_hit(key):
    _FAILS.setdefault(key, []).append(time.time())


def otp_hash(rid, code):
    return hmac.new(app.secret_key.encode(), ("%d:%s" % (rid, code)).encode(), hashlib.sha256).hexdigest()


_OTP_STATE = {}          # reseller id -> {"state": "sending"|"ok"|"fail", "err": str}


def send_otp(r, force=False):
    """Make a NEW random 6-digit code and send it to the reseller's Telegram IN THE BACKGROUND.
    The login page never waits for Telegram (so it can never freeze); the verification page shows the result."""
    now = int(time.time())
    o = q("SELECT * FROM otps WHERE reseller_id=?", (r["id"],), one=True)
    if o and not force and now - o["sent"] < 30 and o["exp"] > now:
        return                                           # a fresh code was just sent
    code = "%06d" % secrets.randbelow(1000000)
    q("INSERT OR REPLACE INTO otps(reseller_id,h,exp,tries,sent) VALUES(?,?,?,?,?)",
      (r["id"], otp_hash(r["id"], code), now + 300, 0, now), commit=True)
    st = {"state": "sending", "err": "", "ts": now}
    _OTP_STATE[r["id"]] = st
    text = ("<blockquote>\U0001F510 <b>Login verification</b></blockquote>\n\n"
            "Use this one-time code to sign in to <b>%s</b>.\n\n<blockquote><code>%s</code></blockquote>\n\n"
            "\u23F1 Expires in <b>5 minutes</b>.\n\U0001F6AB Keep this code private. Our team will never ask for it."
            % (esc(BRAND), code))
    chat, uname, rid = r["tg_chat"], r["username"], r["id"]

    def work():
        try:
            ok, err = bot.send_now(chat, text, what="login code (%s)" % uname)
        except Exception as e:
            ok, err = False, str(e)[:150]
        st["state"], st["err"] = ("ok", "") if ok else ("fail", err)
        if not ok:
            try:
                q("DELETE FROM otps WHERE reseller_id=? AND sent=?", (rid, now), commit=True)   # nothing delivered = no valid code
            except Exception:
                pass
    threading.Thread(target=work, daemon=True, name="otp-send").start()


def check_otp(rid, code):
    o = q("SELECT * FROM otps WHERE reseller_id=?", (rid,), one=True)
    now = int(time.time())
    if not o or o["exp"] < now:
        return False, "Code expired. Press Resend to get a new one."
    if o["tries"] >= 5:
        q("DELETE FROM otps WHERE reseller_id=?", (rid,), commit=True)
        return False, "Too many wrong attempts. Please login again."
    if same(o["h"], otp_hash(rid, code.strip())):
        q("DELETE FROM otps WHERE reseller_id=?", (rid,), commit=True)
        return True, ""
    q("UPDATE otps SET tries=tries+1 WHERE reseller_id=?", (rid,), commit=True)
    return False, "Wrong code. %d attempt(s) left." % max(4 - o["tries"], 0)


# ---- device id (cookie issued by the server, bound to the reseller by the admin's approval)
def get_dev():
    d = request.cookies.get("rgd", "")
    return (d, False) if re.fullmatch(r"[0-9a-f]{32}", d) else (secrets.token_hex(16), True)


def set_dev_cookie(resp, dev, is_new):
    if is_new:
        resp.set_cookie("rgd", dev, max_age=63072000, httponly=True, samesite="Lax",
                        secure=request.is_secure)
    return resp


def device_blocked_any(dev):
    return bool(q("SELECT 1 FROM devices WHERE dev_id=? AND status='denied'", (dev,), one=True))


def device_ok(rid):
    d = request.cookies.get("rgd", "")
    if not re.fullmatch(r"[0-9a-f]{32}", d):
        return False
    row = q("SELECT id FROM devices WHERE reseller_id=? AND dev_id=? AND status='approved'", (rid, d), one=True)
    if row:
        q("UPDATE devices SET last_seen=? WHERE id=?", (int(time.time()), row["id"]), commit=True)
    return bool(row)


def blocked_page(msg=None):
    resp = make_response(render_template("blocked.html", msg=msg), 403)
    resp.headers["Cache-Control"] = "no-store"
    return resp


def ask_admin_approval(r, dev):
    """Create / refresh a pending device row and send the Accept / Reject message to the admin."""
    now = int(time.time())
    d = q("SELECT * FROM devices WHERE reseller_id=? AND dev_id=?", (r["id"], dev), one=True)
    label = ua_label(request.headers.get("User-Agent", ""))
    if d and d["status"] == "pending" and now - d["created"] < 120:
        return d["id"]                                   # request already sent a moment ago
    if d:
        did = d["id"]
        q("UPDATE devices SET status='pending', created=?, label=?, ip=? WHERE id=?",
          (now, label, request.remote_addr, did), commit=True)
    else:
        did = q("INSERT INTO devices(reseller_id,dev_id,label,ip,status,created) VALUES(?,?,?,?,?,?)",
                (r["id"], dev, label, request.remote_addr, "pending", now), commit=True)
    bot.send(tg_admin(),
             "<blockquote>\U0001F514 <b>NEW DEVICE LOGIN REQUEST</b></blockquote>\n\n"
             "\U0001F464 Reseller: <b>%s</b>\n\U0001F4F1 Device: %s\n\U0001F310 IP: <code>%s</code>\n"
             "\U0001F552 Time: %s\n\nAllow this device to open the panel?"
             % (esc(r["username"]), esc(label), esc(request.remote_addr), fmt(now)),
             [[("\u2705 Accept", "dv:a:%d" % did), ("\u274C Reject", "dv:d:%d" % did)]])
    return did


def pw_fp(r):
    return hashlib.sha256((r["pw"] + app.secret_key).encode()).hexdigest()[:16]


def finish_login(r, dev, alert=False):
    """Final step: the browser becomes logged in. Returns the URL to go to."""
    session.clear()
    session["rid"] = r["id"]
    session["pwh"] = pw_fp(r)
    q("UPDATE devices SET last_seen=? WHERE reseller_id=? AND dev_id=?", (int(time.time()), r["id"], dev), commit=True)
    try:                                                # admin is told about EVERY successful reseller login
        adm = tg_admin()
        if adm:
            bot.send(adm, "<blockquote>\U0001F513 <b>RESELLER LOGIN</b></blockquote>\n\U0001F464 Reseller: <b>%s</b>\n"
                          "\U0001F4F1 %s\n\U0001F310 IP: <code>%s</code>\n\U0001F552 Time: %s\n"
                          "\U0001F4B0 Balance: <b>%s</b>"
                     % (esc(r["username"]), esc(ua_label(request.headers.get("User-Agent", ""))),
                        esc(request.remote_addr), fmt(time.time()), inr(r["balance"])),
                     what="admin login alert (%s)" % r["username"])
    except Exception:
        pass
    if alert and r["tg_chat"] and r["notify"]:
        bot.send(r["tg_chat"], "<blockquote>\U0001F513 <b>NEW LOGIN</b></blockquote>\n\U0001F4F1 %s\n"
                               "\U0001F310 IP: <code>%s</code>\n\U0001F552 %s"
                 % (esc(ua_label(request.headers.get("User-Agent", ""))), esc(request.remote_addr), fmt(time.time())))
    return "/dashboard"


def next_step(r, dev, fresh=False):
    """After password (+ device approval): code check if enabled, otherwise straight in. Returns a URL."""
    if otp_global_on() and r["otp_on"] and r["tg_chat"] and tg_token():
        session.clear()
        session["pre"] = dict(rid=r["id"], dev=dev, ts=int(time.time()))
        send_otp(r, force=fresh)                 # fresh=True: every new login gets its own brand-new code
        return "/login/verify"
    return finish_login(r, dev, alert=True)


def with_theme(resp, r):
    if r["theme"]:
        resp.set_cookie("rg_theme", r["theme"][1:], max_age=31536000, samesite="Lax")
    return resp


PRE_TTL = 900


def pre_reseller():
    p = session.get("pre")
    if not p or time.time() - p.get("ts", 0) > PRE_TTL:
        return None, None
    r = q("SELECT * FROM resellers WHERE id=? AND active=1", (p["rid"],), one=True)
    return (r, p) if r else (None, None)


# ---------------------------------------------------------------- public
@app.route("/health")
def health():
    return "ok"


@app.route("/")
def index():
    return redirect("/admin" if session.get("admin") else "/dashboard" if session.get("rid") else "/login")


def do_login():
    """ONE login for everybody: admin credentials -> admin panel, reseller credentials -> reseller panel
    (reseller: password -> device approval by admin -> 6 digit Telegram code -> dashboard)."""
    dev, is_new = get_dev()
    ip = request.remote_addr or "?"

    def out(resp):
        return set_dev_cookie(resp, dev, is_new)
    if dev_check_on() and device_blocked_any(dev):          # rejected device: the login page is never shown
        return out(blocked_page())
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        raw = request.form.get("password", "")
        pw = raw.strip()
        if rl_blocked("ip:" + ip):
            flash("Too many attempts. Please wait 10 minutes.", "err")
            return out(make_response(render_template("login.html", title="Login", action=request.path)))
        if same(u.upper(), ADMIN_USER.upper()) and same(pw, ADMIN_PASS):
            session.clear()
            session["admin"] = True
            return out(redirect("/admin"))
        for r in q("SELECT * FROM resellers WHERE lower(username)=lower(?)", (u,)):
            if check_password_hash(r["pw"], raw) or (pw != raw and check_password_hash(r["pw"], pw)):
                if not r["active"]:
                    flash("Your account is disabled. Please contact admin.", "err")
                    break
                if dev_check_on():
                    d = q("SELECT * FROM devices WHERE reseller_id=? AND dev_id=?", (r["id"], dev), one=True)
                    if d and d["status"] == "denied":
                        return out(blocked_page())
                    if not d or d["status"] != "approved":
                        ask_admin_approval(r, dev)
                        session.clear()
                        session["pre"] = dict(rid=r["id"], dev=dev, ts=int(time.time()))
                        return out(redirect("/login/wait"))
                return out(with_theme(redirect(next_step(r, dev, fresh=True)), r))
        else:
            rl_hit("ip:" + ip)
            flash("Invalid username or password", "err")
    return out(make_response(render_template("login.html", title="Login", action=request.path)))


@app.route("/login/wait")
def login_wait():
    r, p = pre_reseller()
    if not r:
        return redirect("/login")
    return render_template("login_wait.html", title="Approval needed")


@app.route("/login/status")
def login_status():
    r, p = pre_reseller()
    if not r:
        return jsonify(status="gone", next="/login")
    d = q("SELECT * FROM devices WHERE reseller_id=? AND dev_id=?", (r["id"], p["dev"]), one=True)
    if not d:
        return jsonify(status="gone", next="/login")
    if d["status"] == "approved" and request.cookies.get("rgd") == p["dev"]:
        return with_theme(jsonify(status="approved", next=next_step(r, p["dev"])), r)
    if d["status"] == "denied":
        return jsonify(status="denied", next="/login")
    if int(time.time()) - d["created"] > 600:
        return jsonify(status="expired", next="/login")
    return jsonify(status="pending")


@app.route("/login/otp_status")
def login_otp_status():
    r, p = pre_reseller()
    if not r:
        return jsonify(state="gone")
    st = _OTP_STATE.get(r["id"]) or {"state": "ok", "err": ""}
    return jsonify(state=st["state"], err=st["err"][:200])


@app.route("/login/cancel")
def login_cancel():
    session.clear()
    return redirect("/login")


@app.route("/login/verify", methods=["GET", "POST"])
def login_verify():
    r, p = pre_reseller()
    if not r or request.cookies.get("rgd") != p["dev"]:
        return redirect("/login")
    if not (otp_global_on() and r["otp_on"] and r["tg_chat"]):
        return redirect("/login")                        # code was switched OFF meanwhile -> log in again, no code needed
    mk = mask_id(r["tg_chat"])
    if request.method == "POST":
        if request.form.get("action") == "resend":
            if rl_blocked("otp-send:%d" % r["id"], 5, 600):
                flash("Too many codes requested. Wait a few minutes.", "err")
            else:
                rl_hit("otp-send:%d" % r["id"])
                send_otp(r, force=True)
                flash("A new code is being sent to your Telegram.", "ok")
            return render_template("login_verify.html", title="Verification", tg_mask=mk)
        if rl_blocked("otp:%d" % r["id"], 10, 600):
            flash("Too many wrong codes. Please wait 10 minutes.", "err")
            return render_template("login_verify.html", title="Verification", tg_mask=mk)
        ok, msg = check_otp(r["id"], request.form.get("code", ""))
        if ok:
            return with_theme(redirect(finish_login(r, p["dev"])), r)
        rl_hit("otp:%d" % r["id"])
        flash(msg, "err")
    return render_template("login_verify.html", title="Verification", tg_mask=mk)


@app.route("/login", methods=["GET", "POST"])
def login():
    return do_login()


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ---------------------------------------------------------------- reseller panel
@app.route("/dashboard")
@reseller_required
def dashboard():
    import calendar
    rid, now = request.r["id"], int(time.time())
    lt = time.gmtime(now + TZ_OFFSET)
    midnight = now - ((now + TZ_OFFSET) % 86400)
    week_start = midnight - lt.tm_wday * 86400          # Monday 00:00 (local)
    month_start = calendar.timegm((lt.tm_year, lt.tm_mon, 1, 0, 0, 0)) - TZ_OFFSET
    cnt = lambda since: q("SELECT COUNT(*) FROM license_keys WHERE reseller_id=? AND created>=?", (rid, since), one=True)[0]
    stats = dict(
        today=cnt(midnight), week=cnt(week_start), month=cnt(month_start), total=cnt(0),
        month_spent=q("SELECT COALESCE(SUM(price),0) FROM license_keys WHERE reseller_id=? AND created>=?",
                      (rid, month_start), one=True)[0],
        products=q("SELECT COUNT(*) FROM products", one=True)[0],
        month_name=time.strftime("%B %Y", lt))
    recent = q("SELECT * FROM license_keys WHERE reseller_id=? ORDER BY id DESC LIMIT 5", (rid,))
    return render_template("dashboard.html", r=request.r, st=stats, recent=recent, page="dashboard")


@app.route("/generate")
@reseller_required
def generate():
    cat = [p for p in catalog(request.r["id"]) if p["plans"]]
    return render_template("generate.html", r=request.r, cat=cat, page="generate")


@app.route("/generate/one", methods=["POST"])
@reseller_required
def generate_one():
    try:
        res = buy(request.r["id"], int(request.form.get("plan_id", 0)))
        return jsonify(ok=True, key=res["key"], balance=res["balance"])
    except Exception as e:
        return jsonify(ok=False, error=str(e))


PRESETS = [10, 20, 30, 50, 70, 100, 200, 300, 500, 1000, 2000, 5000, 10000]


@app.route("/history")
@reseller_required
def history():
    rid = request.r["id"]
    rows = q("SELECT * FROM license_keys WHERE reseller_id=? ORDER BY id DESC LIMIT 5000", (rid,))
    total = q("SELECT COUNT(*) FROM license_keys WHERE reseller_id=?", (rid,), one=True)[0]
    return render_template("history.html", r=request.r, rows=rows, total=total,
                           opts=[n for n in PRESETS if n < total], page="history")


@app.route("/history/plain")
@reseller_required
def history_plain():
    n, s_ = int(num(request.args.get("n"), 0)), request.args.get("q", "").strip().lower()
    rows = q("SELECT key, product_name FROM license_keys WHERE reseller_id=? ORDER BY id DESC", (request.r["id"],))
    keys = [x["key"] for x in rows if not s_ or s_ in (x["key"] + " " + (x["product_name"] or "")).lower()]
    if n > 0:
        keys = keys[:n]
    return jsonify(count=len(keys), text="\n".join(keys))


@app.route("/theme", methods=["POST"])
@reseller_required
def set_theme():
    c = request.form.get("color", "").strip().lower()
    if not re.match(r"^#[0-9a-f]{6}$", c):
        return jsonify(ok=False), 400
    q("UPDATE resellers SET theme=? WHERE id=?", (c, request.r["id"]), commit=True)
    resp = jsonify(ok=True)
    resp.set_cookie("rg_theme", c[1:], max_age=31536000, samesite="Lax")
    return resp


# ---- security (reseller)
@app.route("/settings", methods=["GET", "POST"])
@reseller_required
def settings():
    r = request.r
    if request.method == "POST":
        key = "pw:%d" % r["id"]
        cur = request.form.get("current", "")
        new = request.form.get("new", "").strip()
        con = request.form.get("confirm", "").strip()
        if rl_blocked(key, 5, 600):
            flash("Too many wrong attempts. Try again in 10 minutes.", "err")
        elif not (check_password_hash(r["pw"], cur) or check_password_hash(r["pw"], cur.strip())):
            rl_hit(key)
            flash("Current password is wrong", "err")
        elif len(new) < 6:
            flash("New password must be at least 6 characters", "err")
        elif new != con:
            flash("New password and confirm password do not match", "err")
        elif check_password_hash(r["pw"], new):
            flash("New password must be different from the current one", "err")
        else:
            q("UPDATE resellers SET pw=? WHERE id=?", (generate_password_hash(new), r["id"]), commit=True)
            extra = ""
            if request.form.get("newkey"):
                q("UPDATE resellers SET api_key=? WHERE id=?", (new_api_key(), r["id"]), commit=True)
                extra = " A new API key was generated too (old key stopped working)."
            r2 = q("SELECT * FROM resellers WHERE id=?", (r["id"],), one=True)
            session["pwh"] = pw_fp(r2)            # this browser stays logged in, all other browsers are logged out
            try:
                if r2["tg_chat"] and r2["notify"]:
                    bot.send(r2["tg_chat"], "<blockquote>\U0001F511 <b>PASSWORD CHANGED</b></blockquote>\n"
                             "\U0001F310 IP: <code>%s</code>\n\U0001F552 %s\n\nIf this was not you, contact admin at once."
                             % (esc(request.remote_addr), fmt(time.time())))
            except Exception:
                pass
            flash("Password changed. Other logged-in browsers were logged out." + extra, "ok")
        return redirect("/settings")
    return render_template("settings.html", r=r, page="settings")


@app.route("/security", methods=["GET", "POST"])
@reseller_required
def security():
    r = request.r
    if request.method == "POST":
        a = request.form.get("action")
        if a == "otp_on":
            if not r["tg_chat"]:
                flash("Your Telegram is not linked yet. Ask admin to add your Chat ID.", "err")
            else:
                q("UPDATE resellers SET otp_on=1 WHERE id=?", (r["id"],), commit=True)
                flash("Login verification is ON", "ok")
        elif a == "otp_off":
            pw = request.form.get("password", "")
            if check_password_hash(r["pw"], pw) or check_password_hash(r["pw"], pw.strip()):
                q("UPDATE resellers SET otp_on=0 WHERE id=?", (r["id"],), commit=True)
                flash("Login verification is OFF. Username + password is enough to log in.", "ok")
            else:
                flash("Wrong password", "err")
        elif a == "alerts":
            q("UPDATE resellers SET notify=?, low_bal=? WHERE id=?",
              (1 if request.form.get("notify") else 0, max(num(request.form.get("low_bal")), 0), r["id"]), commit=True)
            flash("Alert settings saved", "ok")
        elif a == "test_alert":
            if not r["tg_chat"]:
                flash("Your Telegram is not linked yet. Ask admin to add your Chat ID.", "err")
            else:
                ok, err = send_bounded(r["tg_chat"], purchase_text("TEST PRODUCT", 1, 18, r["balance"], "TEST-KEY-0000", "panel")
                                       + "\n\n<i>(this is only a test)</i>", what="test alert (%s)" % r["username"])
                flash("Test alert sent to your Telegram" if ok else "Could not send: %s" % err, "ok" if ok else "err")
        elif a == "rm_device":
            q("DELETE FROM devices WHERE id=? AND reseller_id=?", (int(num(request.form.get("id"))), r["id"]), commit=True)
            flash("Device removed", "ok")
        return redirect("/security")
    devs = q("SELECT * FROM devices WHERE reseller_id=? ORDER BY id DESC", (r["id"],))
    tc = r["tg_chat"] or ""
    return render_template("security.html", r=r, devs=devs, cur_dev=request.cookies.get("rgd", ""),
                           tg_mask=("\u2022" * max(len(tc) - 3, 0) + tc[-3:]) if tc else "",
                           bot_ready=bool(tg_token()), dev_on=dev_check_on(), page="security")


# ---- wallet (UPI top-up)
def my_topup(tid):
    return q("SELECT * FROM topups WHERE id=? AND reseller_id=?", (tid, request.r["id"]), one=True) or abort(404)


@app.route("/wallet")
@reseller_required
def wallet():
    tops = q("SELECT * FROM topups WHERE reseller_id=? ORDER BY id DESC LIMIT 8", (request.r["id"],))
    return render_template("wallet.html", r=request.r, amts=wallet_amounts(), tops=tops,
                           ready=bool(get_setting("gw_key")), page="wallet")


@app.route("/wallet/create", methods=["POST"])
@reseller_required
def wallet_create():
    rid, now = request.r["id"], int(time.time())
    amt = int(num(request.form.get("amount")))
    if amt not in wallet_amounts():
        flash("Please choose one of the listed amounts", "err")
        return redirect("/wallet")
    ex = q("SELECT id FROM topups WHERE reseller_id=? AND amount=? AND status='pending' AND deadline>? ORDER BY id DESC",
           (rid, amt, now), one=True)
    if ex:
        return redirect("/wallet/pay/%d" % ex["id"])
    if q("SELECT COUNT(*) FROM topups WHERE reseller_id=? AND status='pending' AND deadline>?", (rid, now), one=True)[0] >= 5:
        flash("Too many pending payments. Please wait a few minutes.", "err")
        return redirect("/wallet")
    try:
        d = gw_create(amt)
    except Exception as e:
        flash("Could not create the QR: %s" % e, "err")
        return redirect("/wallet")
    exp = parse_iso(d.get("expires_at"))
    tid = q("INSERT INTO topups(reseller_id,amount,order_id,qr_url,upi_id,status,created,expires,deadline) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (rid, amt, str(d["order_id"]), gw_abs(d["qr_url"]), str(d.get("upi_id") or ""), "pending", now,
             exp or now + 300, min(max(now + 300, exp), now + 1800)), commit=True)
    return redirect("/wallet/pay/%d" % tid)


@app.route("/wallet/pay/<int:tid>")
@reseller_required
def wallet_pay(tid):
    check_topup(my_topup(tid))
    t = my_topup(tid)
    r = q("SELECT * FROM resellers WHERE id=?", (request.r["id"],), one=True)
    return render_template("wallet_pay.html", r=r, t=t, left=max(int(t["deadline"] - time.time()), 0), page="wallet")


@app.route("/wallet/status/<int:tid>")
@reseller_required
def wallet_status(tid):
    st = check_topup(my_topup(tid))
    return jsonify(status=st, balance=q("SELECT balance FROM resellers WHERE id=?", (request.r["id"],), one=True)[0])


@app.route("/wallet/qr/<int:tid>")
@reseller_required
def wallet_qr(tid):
    t = my_topup(tid)
    if not (t["qr_url"] or "").startswith(gw_base()):
        abort(404)
    try:
        r = requests.get(t["qr_url"], timeout=20)
        r.raise_for_status()
    except Exception:
        abort(502)
    return Response(r.content, mimetype=r.headers.get("Content-Type", "image/png"),
                    headers={"Content-Disposition": 'attachment; filename="%s.png"' % re.sub(r"\W", "", t["order_id"] or "qr")})


@app.route("/broadcast")
@reseller_required
def broadcast():
    rid = request.r["id"]
    rows = q("SELECT b.*, EXISTS(SELECT 1 FROM broadcast_reads x WHERE x.broadcast_id=b.id AND x.reseller_id=?) rd "
             "FROM broadcasts b WHERE (b.reseller_id IS NULL OR b.reseller_id=?) AND b.created>=? "
             "ORDER BY b.id DESC LIMIT 100", (rid, rid, request.r["created"]))
    html = render_template("broadcast.html", r=request.r, rows=rows, page="broadcast")
    for x in rows:
        if not x["rd"]:
            q("INSERT OR IGNORE INTO broadcast_reads(broadcast_id,reseller_id) VALUES(?,?)", (x["id"], rid), commit=True)
    return html


@app.route("/api-docs", methods=["GET", "POST"])
@reseller_required
def api_docs():
    if request.method == "POST":
        q("UPDATE resellers SET api_key=? WHERE id=?", (new_api_key(), request.r["id"]), commit=True)
        flash("New API key generated. Old key no longer works.", "ok")
        return redirect("/api-docs")
    return render_template("api.html", r=request.r, base=request.host_url.rstrip("/"), page="api")


@app.route("/music.json")
@reseller_required
def music_json():
    return jsonify([dict(title=m["title"], url=m["url"]) for m in q("SELECT * FROM music ORDER BY id")])


@app.route("/media/<path:name>")
def media(name):
    return send_from_directory(MUSIC_DIR, name)


# ---------------------------------------------------------------- reseller API
def api_token():
    """Token can come as X-API-Key header, Authorization: Bearer, ?api_key= / ?token= or in the body."""
    k = request.headers.get("X-API-Key") or ""
    if not k:
        a = request.headers.get("Authorization", "")
        if a.lower().startswith("bearer "):
            k = a[7:]
    if not k:
        k = request.args.get("api_key") or request.args.get("token") or ""
    if not k:
        d = request.get_json(silent=True)
        if isinstance(d, dict):
            k = str(d.get("api_key") or d.get("token") or "")
        elif request.form:
            k = request.form.get("api_key") or request.form.get("token") or ""
    return k.strip()


def api_auth():
    k = api_token()
    r = q("SELECT * FROM resellers WHERE api_key=?", (k,), one=True) if k else None
    if not r or not r["active"]:
        return None
    return r


def api_guard(f):
    from functools import wraps

    @wraps(f)
    def w(*a, **k):
        r = api_auth()
        if not r:
            return jsonify(success=False, connected=False, error="INVALID_API_KEY",
                           message="Not connected: API token is wrong, missing or the account is disabled."), 401
        request.r = r
        return f(*a, **k)
    return w


@app.after_request
def api_cors(resp):
    if request.path.startswith("/api/v1/"):
        resp.headers["Access-Control-Allow-Origin"] = "*"      # token based (no cookies) so this is safe
        resp.headers["Access-Control-Allow-Headers"] = "X-API-Key, Authorization, Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/v1/health")
def api_health():
    return jsonify(success=True, status="online")


@app.route("/api/v1/connect", methods=["GET", "POST"])
@api_guard
def api_connect():
    """Used by a bot when the reseller enters Server URL + API token: 'Connect successful' / 'Not connected'."""
    r = request.r
    return jsonify(success=True, connected=True, message="Connect successful",
                   username=r["username"], balance=r["balance"], currency="INR",
                   server=request.host_url.rstrip("/"))


@app.route("/api/v1/balance")
@api_guard
def api_balance():
    return jsonify(success=True, username=request.r["username"], balance=request.r["balance"], currency="INR")


def _id_list(raw):
    out = []
    if isinstance(raw, (list, tuple)):
        parts = raw
    else:
        parts = re.split(r"[,\s]+", str(raw or ""))
    for x in parts:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            pass
    return out


@app.route("/api/v1/products", methods=["GET", "POST"])
@api_guard
def api_products():
    """All products (default) or only the selected ones: ?ids=1,2,3  (or POST {"product_ids":[1,2,3]})."""
    raw = request.args.get("ids") or request.args.get("product_ids")
    body = request.get_json(silent=True) if request.method == "POST" else None
    if raw is None and isinstance(body, dict):
        raw = body.get("product_ids") or body.get("ids")
    want = _id_list(raw)
    cat = catalog(request.r["id"])
    missing = []
    if want and not str(request.args.get("all", "")).lower() in ("1", "true", "yes"):
        have = {p["id"] for p in cat}
        missing = [i for i in want if i not in have]
        cat = [p for p in cat if p["id"] in want]
    return jsonify(success=True, currency="INR", count=len(cat), missing_ids=missing, products=[
        dict(product_id=p["id"], name=p["name"],
             plans=[dict(plan_id=x["id"], name=x["name"], days=x["days"], price=x["price"],
                         currency="INR", available=(x["stock"] > 0 if x["mode"] == "stock" else True))
                    for x in p["plans"]])
        for p in cat])


@app.route("/api/v1/purchase", methods=["POST"])
@api_guard
def api_purchase():
    d = request.get_json(silent=True) or request.form
    try:
        pid = int(d.get("plan_id"))
    except Exception:
        return jsonify(success=False, error="plan_id required"), 400
    try:
        res = buy(request.r["id"], pid, via="api")
    except ValueError as e:
        code = 402 if "Insufficient" in str(e) else 400
        return jsonify(success=False, error=str(e)), code
    return jsonify(success=True, key=res["key"], product=res["product"], plan=res["plan"],
                   price=res["price"], expires_at=res["expires"], balance=res["balance"])


@app.route("/api/v1/history")
@api_guard
def api_history():
    rows = q("SELECT * FROM license_keys WHERE reseller_id=? ORDER BY id DESC LIMIT 100", (request.r["id"],))
    return jsonify(success=True, keys=[dict(key=x["key"], product=x["product_name"], plan=x["plan_name"],
                                            price=x["price"], created_at=x["created"], expires_at=x["expires"]) for x in rows])


# ---------------------------------------------------------------- admin
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    return do_login()


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect("/admin/login")


@app.route("/admin")
@admin_required
def admin_home():
    now = int(time.time())
    st = dict(resellers=q("SELECT COUNT(*) FROM resellers", one=True)[0],
              products=q("SELECT COUNT(*) FROM products", one=True)[0],
              keys=q("SELECT COUNT(*) FROM license_keys", one=True)[0],
              revenue=q("SELECT COALESCE(SUM(price),0) FROM license_keys", one=True)[0],
              credit=q("SELECT COALESCE(SUM(balance),0) FROM resellers", one=True)[0])
    recent = q("SELECT k.*, r.username FROM license_keys k JOIN resellers r ON r.id=k.reseller_id ORDER BY k.id DESC LIMIT 15")
    return render_template("admin_home.html", st=st, recent=recent, now=now, page="home")


@app.route("/admin/products", methods=["GET", "POST"])
@admin_required
def admin_products():
    if request.method == "POST":
        a = request.form.get("action")
        if a == "product" and request.form.get("name", "").strip():
            q("INSERT INTO products(name) VALUES(?)", (request.form["name"].strip(),), commit=True)
        elif a == "plan":
            try:
                days = max(int(num(request.form.get("days"), 1)), 1)
                q("INSERT INTO plans(product_id,name,days,price,mode) VALUES(?,?,?,?,?)",
                  (int(request.form["product_id"]), plan_label(days), days,
                   num(request.form.get("price")), request.form.get("mode", "stock")), commit=True)
            except Exception as e:
                flash("Error: %s" % e, "err")
        elif a == "edit_plan":
            days = max(int(num(request.form.get("days"), 1)), 1)
            plid = int(request.form["plan_id"])
            old = q("SELECT days,name,prov_pid FROM plans WHERE id=?", (plid,), one=True)
            mode = request.form.get("mode", "stock")
            if old and mode == "provider" and not old["prov_pid"]:
                flash("This plan is not linked to the main API", "err")
            elif old:
                name = old["name"] if old["days"] == days else plan_label(days)
                q("UPDATE plans SET name=?, days=?, price=?, mode=? WHERE id=?",
                  (name, days, num(request.form.get("price")), mode, plid), commit=True)
        elif a == "del_plan":
            q("DELETE FROM plans WHERE id=?", (int(request.form["plan_id"]),), commit=True)
        elif a == "del_product":
            q("DELETE FROM products WHERE id=?", (int(request.form["product_id"]),), commit=True)
        return redirect("/admin/products")
    prods = [dict(p=p, plans=[dict(pl=pl, stock=q("SELECT COUNT(*) FROM stock WHERE plan_id=? AND used=0", (pl["id"],), one=True)[0])
                              for pl in q("SELECT * FROM plans WHERE product_id=? ORDER BY days,id", (p["id"],))])
             for p in q("SELECT * FROM products ORDER BY id")]
    return render_template("admin_products.html", prods=prods, page="products")



@app.route("/admin/stock/<int:pid>", methods=["GET", "POST"])
@admin_required
def admin_stock(pid):
    pl = q("SELECT pl.*, pr.name pname FROM plans pl JOIN products pr ON pr.id=pl.product_id WHERE pl.id=?",
           (pid,), one=True) or abort(404)
    if request.method == "POST":
        a = request.form.get("action")
        if a == "add":
            keys = [k.strip() for k in request.form.get("keys", "").splitlines() if k.strip()]
            now = int(time.time())
            for k in keys:
                q("INSERT INTO stock(plan_id,key,created) VALUES(?,?,?)", (pid, k, now), commit=True)
            flash("%d key(s) added" % len(keys), "ok")
        elif a == "edit":
            q("UPDATE stock SET key=? WHERE id=? AND plan_id=? AND used=0",
              (request.form.get("key", "").strip(), int(request.form["id"]), pid), commit=True)
            flash("Key updated", "ok")
        elif a == "delete":
            q("DELETE FROM stock WHERE id=? AND plan_id=?", (int(request.form["id"]), pid), commit=True)
            flash("Key deleted", "ok")
        elif a == "clear_used":
            q("DELETE FROM stock WHERE plan_id=? AND used=1", (pid,), commit=True)
            flash("Used keys cleared", "ok")
        return redirect("/admin/stock/%d" % pid)
    rows = q("SELECT * FROM stock WHERE plan_id=? ORDER BY used, id DESC", (pid,))
    return render_template("admin_stock.html", pl=pl, rows=rows, page="products")


@app.route("/admin/plan-api/<int:pid>", methods=["GET", "POST"])
@admin_required
def admin_plan_api(pid):
    pl = q("SELECT pl.*, pr.name pname FROM plans pl JOIN products pr ON pr.id=pl.product_id WHERE pl.id=?",
           (pid,), one=True) or abort(404)
    if request.method == "POST":
        f = request.form
        try:
            for fld in ("ext_headers", "ext_body"):
                if f.get(fld, "").strip():
                    json.loads(f[fld].replace("{days}", "1").replace("{plan}", "x").replace("{product}", "x"))
        except ValueError:
            flash("Headers/Body must be valid JSON", "err")
            return redirect("/admin/plan-api/%d" % pid)
        q("UPDATE plans SET ext_url=?, ext_method=?, ext_headers=?, ext_body=?, ext_path=? WHERE id=?",
          (f.get("ext_url", "").strip(), f.get("ext_method", "POST"), f.get("ext_headers", "").strip(),
           f.get("ext_body", "").strip(), f.get("ext_path", "").strip(), pid), commit=True)
        flash("API settings saved. Set the plan mode to 'External API' on the Products page to use it.", "ok")
        return redirect("/admin/plan-api/%d" % pid)
    return render_template("admin_plan_api.html", pl=pl, page="products")


@app.route("/admin/keys")
@admin_required
def admin_keys():
    rows = q("SELECT k.*, r.username FROM license_keys k JOIN resellers r ON r.id=k.reseller_id ORDER BY k.id DESC LIMIT 500")
    return render_template("admin_keys.html", rows=rows, now=int(time.time()), page="keys")


def send_bounded(chat_id, text, what, wait=7):
    """Send now but NEVER make the page wait longer than `wait` seconds (the send goes on in the background)."""
    box = {}

    def work():
        box["r"] = bot.send_now(chat_id, text, what=what)
    t = threading.Thread(target=work, daemon=True, name="tg-bounded")
    t.start()
    t.join(wait)
    if "r" in box:
        return box["r"]
    return False, ("Telegram did not answer within %d seconds - this server cannot reach Telegram right now "
                   "(see Admin > Telegram > Delivery log)" % wait)


def link_notice(chat_id, username):
    """Tell a freshly linked chat that it is linked; returns (delivered, error) - this IS the delivery test."""
    return send_bounded(chat_id, "✅ <b>%s</b>\n\nYour account <b>%s</b> is now linked. Login codes and purchase "
                                 "alerts will arrive here." % (esc(BRAND), esc(username)), what="link test (%s)" % username)


def seen_unlinked():
    """People who pressed /start in the bot and are not linked to any reseller yet (newest first)."""
    return q("SELECT * FROM tg_seen WHERE chat_id NOT IN (SELECT tg_chat FROM resellers WHERE tg_chat<>'') "
             "ORDER BY ts DESC LIMIT 12")


@app.route("/admin/resellers", methods=["GET", "POST"])
@admin_required
def admin_resellers():
    if request.method == "POST":
        u, p = request.form.get("username", "").strip(), request.form.get("password", "").strip()
        if not u or not p:
            flash("Username and password required", "err")
        elif same(u.upper(), ADMIN_USER.upper()):
            flash("This username is reserved for the admin", "err")
        elif q("SELECT 1 FROM resellers WHERE lower(username)=lower(?)", (u,), one=True):
            flash("Username already exists", "err")
        else:
            tg = request.form.get("tg_chat", "").strip()
            if tg and not re.fullmatch(r"-?\d{5,15}", tg):
                flash("Telegram Chat ID must be numbers only", "err")
                return redirect("/admin/resellers")
            try:
                q("INSERT INTO resellers(username,pw,balance,api_key,created,tg_chat) VALUES(?,?,?,?,?,?)",
                  (u, generate_password_hash(p), num(request.form.get("credit")), new_api_key(), int(time.time()), tg),
                  commit=True)
                if tg:
                    ok, err = link_notice(tg, u)
                    flash("Reseller created. " + ("Telegram linked - test message delivered." if ok
                                                  else "Telegram saved BUT delivery failed: %s" % err), "ok" if ok else "err")
                else:
                    flash("Reseller created", "ok")
            except sqlite3.IntegrityError:
                flash("Username already exists", "err")
        return redirect("/admin/resellers")
    rows = q("SELECT r.*, (SELECT COUNT(*) FROM license_keys k WHERE k.reseller_id=r.id) kc FROM resellers r ORDER BY r.id DESC")
    return render_template("admin_resellers.html", rows=rows, seen=seen_unlinked(), page="resellers")


@app.route("/admin/reseller/<int:rid>", methods=["GET", "POST"])
@admin_required
def admin_reseller(rid):
    r = q("SELECT * FROM resellers WHERE id=?", (rid,), one=True) or abort(404)
    if request.method == "POST":
        a = request.form.get("action")
        if a == "credit":
            amt = abs(num(request.form.get("amount")))
            op = request.form.get("op", "add")
            if op == "sub":
                amt = -amt
            elif num(request.form.get("amount")) < 0:          # old behaviour: a negative number also deducts
                amt = num(request.form.get("amount"))
            if amt == 0:
                flash("Enter an amount", "err")
            else:
                before = r["balance"]
                q("UPDATE resellers SET balance=MAX(balance+?,0) WHERE id=?", (amt, rid), commit=True)
                after = q("SELECT balance FROM resellers WHERE id=?", (rid,), one=True)["balance"]
                if amt > 0:
                    try:
                        notify_topup(q("SELECT * FROM resellers WHERE id=?", (rid,), one=True), amt, "Admin panel")
                    except Exception:
                        pass
                    flash("Added %s. New balance %s" % (money_txt(amt), money_txt(after)), "ok")
                elif before + amt < 0:
                    flash("Balance cannot go below 0 - deducted only %s. New balance %s" % (money_txt(before - after), money_txt(after)), "ok")
                else:
                    flash("Deducted %s. New balance %s" % (money_txt(-amt), money_txt(after)), "ok")
        elif a == "password" and request.form.get("password", "").strip():
            q("UPDATE resellers SET pw=? WHERE id=?", (generate_password_hash(request.form["password"].strip()), rid), commit=True)
            flash("Password changed", "ok")
        elif a == "toggle":
            q("UPDATE resellers SET active=1-active WHERE id=?", (rid,), commit=True)
        elif a == "tg":
            tg = request.form.get("tg_chat", "").strip()
            if tg and not re.fullmatch(r"-?\d{5,15}", tg):
                flash("Telegram Chat ID must be numbers only", "err")
            else:
                q("UPDATE resellers SET tg_chat=? WHERE id=?", (tg, rid), commit=True)
                if tg:
                    ok, err = link_notice(tg, r["username"])
                    flash("Telegram linked - test message delivered to that chat." if ok else
                          "Chat ID saved BUT the test message failed: %s" % err, "ok" if ok else "err")
                else:
                    flash("Telegram unlinked", "ok")
        elif a == "tg_test":
            if not r["tg_chat"]:
                flash("No Chat ID saved for this reseller yet", "err")
            else:
                ok, err = link_notice(r["tg_chat"], r["username"])
                flash("Test message delivered" if ok else "Delivery failed: %s" % err, "ok" if ok else "err")
        elif a == "otp_toggle":
            q("UPDATE resellers SET otp_on=1-otp_on WHERE id=?", (rid,), commit=True)
            flash("Login verification changed", "ok")
        elif a == "prices":
            for pl in q("SELECT id FROM plans"):
                v = request.form.get("p_%d" % pl["id"], "").strip()
                if v == "":
                    q("DELETE FROM custom_prices WHERE reseller_id=? AND plan_id=?", (rid, pl["id"]), commit=True)
                else:
                    q("INSERT OR REPLACE INTO custom_prices(reseller_id,plan_id,price) VALUES(?,?,?)",
                      (rid, pl["id"], num(v)), commit=True)
            flash("Custom prices saved", "ok")
        elif a == "delete":
            q("DELETE FROM resellers WHERE id=?", (rid,), commit=True)
            return redirect("/admin/resellers")
        return redirect("/admin/reseller/%d" % rid)
    cat = catalog(rid)
    devs = q("SELECT * FROM devices WHERE reseller_id=? ORDER BY id DESC", (rid,))
    return render_template("admin_reseller.html", r=r, cat=cat, devs=devs, seen=seen_unlinked(), page="resellers")


@app.route("/admin/gateway", methods=["GET", "POST"])
@admin_required
def admin_gateway():
    test = None
    if request.method == "POST":
        f = request.form
        if f.get("action") == "save":
            base = f.get("base", "").strip().rstrip("/")
            if not re.match(r"^https?://", base):
                flash("Gateway URL must start with http:// or https://", "err")
                return redirect("/admin/gateway")
            amts = sorted({int(x) for x in re.split(r"[,\s]+", f.get("amounts", "")) if x.isdigit() and 1 <= int(x) <= 100000})
            if amts:
                set_setting("wallet_amounts", ",".join(str(x) for x in amts[:12]))
            set_setting("gw_base", base)
            set_setting("gw_upi", f.get("upi", "").strip())
            if f.get("token", "").strip():
                set_setting("gw_key", f["token"].strip())
            flash("Gateway settings saved", "ok")
            return redirect("/admin/gateway")
        try:                                   # test: Rs.1 order, never credited to anybody
            d = gw_create(1)
            test = dict(ok=True, qr=gw_abs(d["qr_url"]), order=d["order_id"], upi=d.get("upi_id"))
        except Exception as e:
            test = dict(ok=False, msg=str(e))
    key = get_setting("gw_key")
    tops = q("SELECT t.*, r.username FROM topups t JOIN resellers r ON r.id=t.reseller_id ORDER BY t.id DESC LIMIT 20")
    return render_template("admin_gateway.html", base=gw_base(), upi=get_setting("gw_upi"),
                           tail=key[-4:] if key else "", test=test, tops=tops, amounts=", ".join(str(x) for x in wallet_amounts()),
                           page="gateway")


@app.route("/admin/telegram", methods=["GET", "POST"])
@admin_required
def admin_telegram():
    if request.method == "POST":
        f = request.form
        a = f.get("action")
        if a == "save":
            tok = f.get("token", "").strip()
            adm_id = f.get("admin_id", "").strip()
            if adm_id and not re.fullmatch(r"-?\d{5,15}", adm_id):
                flash("Admin Chat ID must be numbers only", "err")
                return redirect("/admin/telegram")
            if tok:
                if not re.fullmatch(r"\d{6,12}:[\w-]{30,60}", tok):
                    flash("That does not look like a bot token (from @BotFather)", "err")
                    return redirect("/admin/telegram")
                ok, info = bot.check_token(tok)            # ask Telegram BEFORE saving
                if not ok and ("unauthorized" in info.lower() or "not found" in info.lower()):
                    flash("Telegram rejected this token - not saved. (%s)" % info, "err")
                    return redirect("/admin/telegram")
                if tok != tg_token():
                    set_setting("tg_token", tok)
                    bot.token_changed()                    # the bot switches to the new token right now
                if ok:
                    flash("New token saved - @%s is running now. No redeploy needed." % info.get("username", "bot"), "ok")
                else:
                    flash("Token saved, but Telegram could not be reached to check it (%s)." % info, "err")
            set_setting("tg_admin", adm_id)
            set_setting("dev_check", "1" if f.get("dev_check") else "0")
            set_setting("otp_global", "1" if f.get("otp_global") else "0")
            set_setting("prem_on", "1" if f.get("prem_on") else "0")
            if not tok:
                flash("Telegram settings saved", "ok")
        elif a == "clear_token":
            set_setting("tg_token", "")
            bot.token_changed()
            flash("Bot token removed. The bot is OFF until you paste a new token." if not tg_token()
                  else "Panel token removed. Now using the Render env TG_BOT_TOKEN.", "ok")
        elif a == "reset_emoji":
            set_setting("emoji_map", "{}")
            bot.refresh_map()
            flash("Emoji choices reset to automatic", "ok")
        elif a == "test_alert":
            ok, err = send_bounded(tg_admin(), purchase_text("SAMPLE PRODUCT", 1, 20, 824.44, "5456242 : 49892697",
                                                             "panel", buyer="RPSHIVA"), what="sample alert")
            flash("Sample alert sent to your Telegram" if ok else "Could not send: %s" % err, "ok" if ok else "err")
        elif a == "test":
            ok, err = send_bounded(tg_admin(), "\u2705 <b>%s</b>\nTest message - the bot is connected." % esc(BRAND),
                                   what="admin test")
            flash("Test message sent to your Telegram" if ok else "Could not send: %s" % err, "ok" if ok else "err")
        elif a == "test_reseller":
            r = q("SELECT * FROM resellers WHERE id=?", (int(num(f.get("id"))),), one=True)
            if r and r["tg_chat"]:
                ok, err = link_notice(r["tg_chat"], r["username"])
                flash(("Delivered to %s" % r["username"]) if ok else "%s: delivery FAILED - %s" % (r["username"], err),
                      "ok" if ok else "err")
            else:
                flash("That reseller has no Chat ID", "err")
        return redirect("/admin/telegram")
    me = bot.me_cached() if tg_token() else None
    rs = q("SELECT id, username, tg_chat, otp_on, notify, active FROM resellers ORDER BY (tg_chat='' OR tg_chat IS NULL), username")
    return render_template("admin_telegram.html", me=me, has_token=bool(tg_token()), tail=tg_token()[-4:],
                           admin_id=tg_admin(), dev_check=get_setting("dev_check", "1") == "1",
                           otp_global=otp_global_on(), rs=rs, log=list(bot.log), poll_err=bot.poll_err, me_err=bot.me_err,
                           sent_ok=bot.sent_ok, sent_fail=bot.sent_fail, seen=seen_unlinked(),
                           tok_src=tg_token_source(), roles=emoji_roles(), extras=emoji_extras(),
                           cat=bot.catalog(), n_over=len(emoji_overrides()),
                           active=dev_check_on(), prem_on=get_setting("prem_on", "1") == "1", prem=bot.status(), page="telegram")


def emoji_roles():
    ov, out = emoji_overrides(), []
    for em, label in EMOJI_ROLES:
        cid = ov.get(em) or bot.emap.get(em.replace("\ufe0f", "")) or ""
        out.append(dict(em=em, label=label, cid=cid, manual=bool(ov.get(em)), mine=ov.get(em) or ""))
    return out


def emoji_extras():
    """Emoji added by the admin that are not in the fixed list (Admin > Telegram > Emoji ID manager > Add any emoji)."""
    known = {e for e, _ in EMOJI_ROLES}
    return [dict(em=k, cid=v) for k, v in emoji_overrides().items() if k not in known]


def valid_emoji_key(k):
    """A plain emoji (1-12 characters, no letters/digits/spaces) that can be replaced by a premium emoji."""
    k = (k or "").strip()
    return 0 < len(k) <= 12 and not re.search(r"[A-Za-z0-9\s<>&]", k) and any(ord(c) > 0x2000 for c in k)


@app.route("/admin/emoji/thumb/<cid>")
@admin_required
def admin_emoji_thumb(cid):
    if not re.fullmatch(r"\d{5,25}", cid):
        abort(404)
    try:
        t = bot.thumb(cid)
    except Exception:
        t = None
    if not t:
        abort(404)
    resp = make_response(t[0])
    resp.headers["Content-Type"] = t[1]
    resp.headers["Cache-Control"] = "private, max-age=86400"
    return resp


@app.route("/admin/emoji/set", methods=["POST"])
@admin_required
def admin_emoji_set():
    """Set / clear the premium emoji ID of ONE plain emoji (any emoji, not only the fixed list)."""
    d = request.get_json(silent=True) or {}
    role, cid = str(d.get("role") or "").strip(), re.sub(r"\D", "", str(d.get("cid") or ""))
    if not valid_emoji_key(role) or (cid and not re.fullmatch(r"\d{5,25}", cid)):
        return jsonify(ok=False, msg="Wrong emoji or ID (the ID is only digits, e.g. 5368324170671202286)"), 400
    found = None
    if cid:
        try:                                    # ask Telegram if this ID really exists (so a typo is caught at once)
            found = bool(bot.lookup(cid))
        except Exception:
            found = None                        # Telegram not reachable now: still save it
    m = emoji_overrides()
    if cid:
        m[role] = cid
    else:
        m.pop(role, None)
    set_setting("emoji_map", json.dumps(m))
    bot.refresh_map()
    return jsonify(ok=True, cid=cid or bot.emap.get(role.replace("\ufe0f", ""), ""), found=found)


@app.route("/admin/emoji/bulk", methods=["POST"])
@admin_required
def admin_emoji_bulk():
    """Paste many lines like  '✅ 5368324170671202286'  (exactly what the bot's /emojis reply gives)."""
    txt = str((request.get_json(silent=True) or {}).get("text") or "")
    m, n = emoji_overrides(), 0
    for line in txt.splitlines():
        mm = re.match(r"^\s*(\S{1,12}?)\s*[:=>\-\u2192]*\s*(\d{5,25})\s*$", line)
        if mm and valid_emoji_key(mm.group(1)):
            m[mm.group(1)] = mm.group(2)
            n += 1
    if n:
        set_setting("emoji_map", json.dumps(m))
        bot.refresh_map()
    return jsonify(ok=bool(n), n=n)


@app.route("/admin/devices", methods=["GET", "POST"])
@admin_required
def admin_devices():
    if request.method == "POST":
        a, did = request.form.get("action"), int(num(request.form.get("id")))
        if a in ("approve", "deny"):
            device_decision(did, a == "approve")
        elif a == "delete":
            q("DELETE FROM devices WHERE id=?", (did,), commit=True)
        flash("Done", "ok")
        return redirect("/admin/devices")
    rows = q("SELECT d.*, r.username FROM devices d JOIN resellers r ON r.id=d.reseller_id "
             "ORDER BY (d.status='pending') DESC, d.id DESC LIMIT 300")
    return render_template("admin_devices.html", rows=rows, page="devices")


@app.route("/admin/broadcast", methods=["GET", "POST"])
@admin_required
def admin_broadcast():
    if request.method == "POST":
        f = request.form
        if f.get("action") == "delete":
            bid = int(num(f.get("id")))
            q("DELETE FROM broadcasts WHERE id=?", (bid,), commit=True)
            q("DELETE FROM broadcast_reads WHERE broadcast_id=?", (bid,), commit=True)
        elif not f.get("body", "").strip():
            flash("Write a message first", "err")
        else:
            tgt = f.get("target", "all")
            rid = None if tgt == "all" else int(num(tgt))
            q("INSERT INTO broadcasts(reseller_id,title,body,created) VALUES(?,?,?,?)",
              (rid, f.get("title", "").strip(), f["body"].strip(), int(time.time())), commit=True)
            flash("Broadcast sent to %s" % ("all resellers" if rid is None else "1 reseller"), "ok")
        return redirect("/admin/broadcast")
    rows = q("SELECT b.*, r.username FROM broadcasts b LEFT JOIN resellers r ON r.id=b.reseller_id ORDER BY b.id DESC LIMIT 50")
    return render_template("admin_broadcast.html", rows=rows, rs=q("SELECT id, username FROM resellers ORDER BY username"),
                           page="broadcast")


@app.route("/admin/music", methods=["GET", "POST"])
@admin_required
def admin_music():
    if request.method == "POST":
        if request.form.get("action") == "delete":
            m = q("SELECT * FROM music WHERE id=?", (int(request.form["id"]),), one=True)
            if m:
                if m["url"].startswith("/media/"):
                    try:
                        os.remove(os.path.join(MUSIC_DIR, m["url"][7:]))
                    except OSError:
                        pass
                q("DELETE FROM music WHERE id=?", (m["id"],), commit=True)
        elif q("SELECT COUNT(*) FROM music", one=True)[0] >= MAX_MUSIC:
            flash("Maximum %d songs allowed" % MAX_MUSIC, "err")
        else:
            title = request.form.get("title", "").strip()
            f = request.files.get("file")
            url = request.form.get("url", "").strip()
            if f and f.filename:
                ext = os.path.splitext(f.filename)[1].lower()
                if ext not in (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".oga", ".opus", ".flac", ".webm", ".mp4"):
                    flash("Audio files only (mp3, m4a, wav, ogg, flac ...)", "err")
                    return redirect("/admin/music")
                name = "%s_%s" % (secrets.token_hex(4), secure_filename(f.filename))
                try:
                    f.save(os.path.join(MUSIC_DIR, name))
                except OSError as e:
                    flash("Could not save the file: %s" % str(e)[:100], "err")
                    return redirect("/admin/music")
                url = "/media/" + name
                title = title or os.path.splitext(f.filename)[0]
            if url:
                q("INSERT INTO music(title,url) VALUES(?,?)", (title or url.split("/")[-1], url), commit=True)
                flash("Song added", "ok")
            else:
                flash("Upload a file or paste a direct audio URL", "err")
        return redirect("/admin/music")
    return render_template("admin_music.html", rows=q("SELECT * FROM music ORDER BY id"), mx=MAX_MUSIC, page="music")


# ---------------------------------------------------------------- admin: main API
@app.route("/admin/main-api", methods=["GET", "POST"])
@admin_required
def admin_main_api():
    if request.method == "POST":
        a = request.form.get("action")
        if a == "save":
            base = request.form.get("base", "").strip().rstrip("/")
            tok = request.form.get("token", "").strip()
            if not re.match(r"^https?://", base):
                flash("Base URL must start with http:// or https://", "err")
                return redirect("/admin/main-api")
            set_setting("api_base", base)
            if tok:
                set_setting("api_token", tok)
        st = prov_status()
        if st["ok"]:
            flash("Connected successfully. Balance: %s" % _cur(st["balance"]), "ok")
        else:
            flash("Connection failed: %s" % st["msg"], "err")
        return redirect("/admin/main-api")
    try:
        st = json.loads(get_setting("api_status"))
    except ValueError:
        st = None
    tok = get_setting("api_token")
    return render_template("admin_mapi.html", base=get_setting("api_base") or DEFAULT_API_BASE,
                           tail=tok[-4:] if tok else "", st=st, page="mapi")


@app.route("/admin/main-api/products", methods=["GET", "POST"])
@admin_required
def admin_main_api_products():
    if request.method == "POST":
        try:
            cat = load_catalog()
        except Exception as e:
            flash("Could not load catalog: %s" % e, "err")
            return redirect("/admin/main-api/products")
        rows = {int(p["product_id"]): p for p in cat["products"] if str(p.get("product_id", "")).isdigit()}
        if request.form.get("scope") == "all":
            ids = list(rows)
        else:
            ids = [int(x) for x in request.form.getlist("pid") if x.isdigit() and int(x) in rows]
        markup = max(num(request.form.get("markup")), 0.0)
        overwrite = bool(request.form.get("overwrite"))
        new_pl = upd = skip = new_pr = 0
        for pid in ids:
            p = rows[pid]
            price = round(inr_of(p, cat) * (1 + markup / 100.0), 2)
            ex = q("SELECT id FROM plans WHERE prov_pid=?", (pid,), one=True)
            if ex:
                if overwrite:
                    q("UPDATE plans SET price=? WHERE id=?", (price, ex["id"]), commit=True)
                    upd += 1
                else:
                    skip += 1
                continue
            pname = (p.get("product_name") or "Product %s" % pid).strip()
            pr = q("SELECT id FROM products WHERE lower(name)=lower(?)", (pname,), one=True)
            if pr:
                prid = pr["id"]
            else:
                prid = q("INSERT INTO products(name) VALUES(?)", (pname,), commit=True)
                new_pr += 1
            dur = str(p.get("duration") or "1 Day").strip()
            q("INSERT INTO plans(product_id,name,days,price,mode,prov_pid) VALUES(?,?,?,?,?,?)",
              (prid, dur, parse_days(dur), price, "provider", pid), commit=True)
            new_pl += 1
        flash("Imported %d plan(s), %d new product(s). Updated prices: %d. Skipped (already there): %d."
              % (new_pl, new_pr, upd, skip), "ok")
        return redirect("/admin/main-api/products")
    cat, err = None, None
    try:
        cat = load_catalog(refresh=bool(request.args.get("refresh")))
    except Exception as e:
        err = str(e)
        try:
            cat = json.loads(get_setting("catalog_cache"))
        except ValueError:
            cat = None
    if err:
        flash("Could not load catalog: %s" % err, "err")
    mine = {r["prov_pid"]: r["price"] for r in q("SELECT prov_pid, price FROM plans WHERE prov_pid IS NOT NULL")}
    groups, idx = [], {}
    for p in (cat or {}).get("products", []):
        try:
            pid = int(p["product_id"])
        except (KeyError, ValueError, TypeError):
            continue
        name = (p.get("product_name") or "Product").strip()
        if name not in idx:
            idx[name] = dict(name=name, plans=[])
            groups.append(idx[name])
        idx[name]["plans"].append(dict(pid=pid, dur=p.get("duration") or "", inr=inr_of(p, cat),
                                       usd=p.get("price_usd"), mine=mine.get(pid)))
    return render_template("admin_mapi_products.html", groups=groups, cat=cat, page="mapi")


# ---------------------------------------------------------------- admin: backup / restore
BACKUP_TABLES = ["products", "plans", "resellers", "custom_prices", "license_keys", "stock", "settings",
                 "topups", "broadcasts", "broadcast_reads", "devices"]      # music has its OWN backup (below)


@app.route("/admin/backup")
@admin_required
def admin_backup():
    counts = {t: q("SELECT COUNT(*) FROM %s" % t, one=True)[0] for t in BACKUP_TABLES}
    songs = q("SELECT * FROM music ORDER BY id")
    size = 0
    for m in songs:
        try:
            size += os.path.getsize(os.path.join(MUSIC_DIR, os.path.basename(m["url"]))) if m["url"].startswith("/media/") else 0
        except OSError:
            pass
    return render_template("admin_backup.html", counts=counts, songs=len(songs), msize=round(size / 1048576, 1), page="backup")


@app.route("/admin/backup/download")
@admin_required
def admin_backup_download():
    out = dict(app="reseller-panel", version=1, created=int(time.time()), tables={})
    for t in BACKUP_TABLES:
        out["tables"][t] = [dict(r) for r in q("SELECT * FROM %s" % t)]
    name = "backup_%s.json" % time.strftime("%Y%m%d_%H%M", time.gmtime(time.time() + TZ_OFFSET))
    return Response(json.dumps(out, ensure_ascii=False), mimetype="application/json",
                    headers={"Content-Disposition": 'attachment; filename="%s"' % name,
                             "Cache-Control": "no-store"})


@app.route("/admin/backup/restore", methods=["POST"])
@admin_required
def admin_backup_restore():
    f = request.files.get("file")
    try:
        data = json.loads(f.read().decode("utf-8")) if f and f.filename else None
        if not isinstance(data, dict) or data.get("app") != "reseller-panel" or not isinstance(data.get("tables"), dict):
            raise ValueError("This is not a backup file of this panel")
        tables = data["tables"]
    except (ValueError, UnicodeDecodeError) as e:
        flash("Restore failed: %s" % (e if isinstance(e, ValueError) and "backup" in str(e) else "invalid file"), "err")
        return redirect("/admin/backup")
    c = sqlite3.connect(DB, timeout=20, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=OFF")
    try:
        c.execute("BEGIN IMMEDIATE")
        for t in reversed(BACKUP_TABLES):
            c.execute("DELETE FROM %s" % t)
        total = 0
        for t in BACKUP_TABLES:          # table names come from the fixed list above
            cols = [r[1] for r in c.execute("PRAGMA table_info(%s)" % t)]
            for row in tables.get(t) or []:
                keys = [k for k in row if k in cols]      # only known column names are ever used
                if not keys:
                    continue
                vals = [row[k] for k in keys]
                if any(isinstance(v, (dict, list)) for v in vals):
                    raise ValueError("bad value in table %s" % t)
                c.execute("INSERT INTO %s(%s) VALUES(%s)" % (t, ",".join(keys), ",".join("?" * len(keys))), vals)
                total += 1
        c.execute("COMMIT")
        flash("Backup restored (%d records). Music is not part of this backup - restore it from the Music backup below." % total, "ok")
    except Exception as e:
        try:
            c.execute("ROLLBACK")
        except Exception:
            pass
        flash("Restore failed, nothing was changed: %s" % str(e)[:120], "err")
    finally:
        c.close()
    return redirect("/admin/backup")


# ---- separate MUSIC backup (one .zip: song list + the uploaded audio files)
@app.route("/admin/music/backup")
@admin_required
def admin_music_backup():
    rows = [dict(r) for r in q("SELECT title, url FROM music ORDER BY id")]
    fd, path = tempfile.mkstemp(suffix=".zip", dir=DATA_DIR)
    os.close(fd)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:          # audio is already compressed
        z.writestr("music.json", json.dumps(dict(app="reseller-panel-music", version=1, rows=rows), ensure_ascii=False))
        for m in rows:
            if m["url"].startswith("/media/"):
                fp = os.path.join(MUSIC_DIR, os.path.basename(m["url"]))
                if os.path.isfile(fp):
                    z.write(fp, "files/" + os.path.basename(m["url"]))

    @after_this_request
    def _rm(resp):
        try:
            os.remove(path)
        except OSError:
            pass
        return resp
    name = "music_backup_%s.zip" % time.strftime("%Y%m%d_%H%M", time.gmtime(time.time() + TZ_OFFSET))
    return send_file(path, as_attachment=True, download_name=name, mimetype="application/zip", max_age=0)


@app.route("/admin/music/restore", methods=["POST"])
@admin_required
def admin_music_restore():
    f = request.files.get("file")
    try:
        z = zipfile.ZipFile(f.stream)
        meta = json.loads(z.read("music.json").decode("utf-8"))
        if meta.get("app") != "reseller-panel-music" or not isinstance(meta.get("rows"), list):
            raise ValueError("bad")
    except Exception:
        flash("This is not a music backup file of this panel", "err")
        return redirect("/admin/backup")
    for m in q("SELECT * FROM music"):                                  # replace the current library
        if m["url"].startswith("/media/"):
            try:
                os.remove(os.path.join(MUSIC_DIR, os.path.basename(m["url"])))
            except OSError:
                pass
    q("DELETE FROM music", commit=True)
    names = {n for n in z.namelist() if n.startswith("files/") and not n.endswith("/")}
    n_files = n_rows = 0
    for n in names:
        safe = secure_filename(os.path.basename(n))
        if safe:
            with z.open(n) as src, open(os.path.join(MUSIC_DIR, safe), "wb") as dst:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    dst.write(chunk)
            n_files += 1
    for m in meta["rows"]:
        url = str(m.get("url") or "")
        if url.startswith("/media/") and not os.path.isfile(os.path.join(MUSIC_DIR, secure_filename(os.path.basename(url)))):
            continue                                                    # file missing inside the zip
        q("INSERT INTO music(title,url) VALUES(?,?)", (str(m.get("title") or "")[:200], url), commit=True)
        n_rows += 1
    flash("Music restored: %d song(s), %d audio file(s)." % (n_rows, n_files), "ok")
    return redirect("/admin/backup")


# ---------------------------------------------------------------- keep-alive (Render never sleeps)
def keep_alive():
    url = (os.environ.get("KEEP_ALIVE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
    if not url:
        return
    import requests
    time.sleep(60)
    while True:
        try:
            requests.get(url + "/health", timeout=20)
        except Exception:
            pass
        time.sleep(int(os.environ.get("KEEP_ALIVE_INTERVAL", "600")))


threading.Thread(target=keep_alive, daemon=True, name="keep-alive").start()
threading.Thread(target=topup_worker, daemon=True, name="topup-worker").start()
bot.start()                                   # Telegram bot (login codes, alerts, device approval)

from templates_ui2 import TEMPLATES, ic  # noqa: E402
app.jinja_env.globals["ic"] = ic
app.jinja_env.loader = DictLoader(TEMPLATES)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
