import sqlite3
import datetime
import random
import requests
from requests.adapters import HTTPAdapter
import telebot
import time
import threading
import concurrent.futures
import os
import hashlib
import hmac
import html
import re
import ast
import copy
import json
import difflib
import io
import urllib.parse
import secrets
import subprocess
import shutil
import zipfile
import tarfile
import tempfile
from pathlib import Path
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from telebot import types

try:
    from cryptography.hazmat.primitives import padding as _crypto_padding
    from cryptography.hazmat.primitives.ciphers import Cipher as _CryptoCipher, algorithms as _crypto_algorithms, modes as _crypto_modes
    _PAYTM_CRYPTO_AVAILABLE = True
except Exception:
    _PAYTM_CRYPTO_AVAILABLE = False

# QR styling/decoding dependencies. The payment gateway and verification flow
# remain unchanged; these libraries are used only to render the QR beautifully.
import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers.pil import RoundedModuleDrawer, SquareModuleDrawer
from qrcode.image.styles.colormasks import SolidFillColorMask
from PIL import Image, ImageDraw, ImageFont
# cv2/numpy are imported lazily inside QR decoding so multiple created bots
# can start without each process paying the full OpenCV memory cost.

# RG CHEAT SHOP — feature-preserving UI/emoji/price-list update
# Version: 2026-08-26 — FamPay setup state-machine + multi-bot resource isolation + duplicate-token guard
# ID input safety patch: Telegram commands can no longer be saved as Product/Valid IDs.
# Wallet checkout stability patch: keep the checkout message alive, prevent double-charge taps, and isolate slow key/API work from the Telegram callback worker.

# ==================== CONSISTENT INDIA TIME ====================

# ==================== USER ACTIVITY AUDIT LOG ====================
_ACTIVITY_LOCK = threading.RLock()
def _activity_log(event, user, details=''):
    """Best-effort audit trail for actions performed inside this bot only."""
    # This switch controls ONLY the user/reseller button/activity tracking
    # notification. Purchase, balance, delivery and other business
    # notifications do not use this function and remain unaffected.
    try:
        if str(get_setting('user_activity_notifications') or '1').strip() != '1':
            return
    except Exception:
        # Preserve the historical/default behavior if the setting cannot be
        # read for any reason.
        pass
    try:
        uid = int(getattr(user, 'id', 0) or 0)
        if not uid: return
        try:
            if uid in set(_load_persistent_admin_ids()):
                return
        except Exception:
            if uid in set(ADMIN_IDS):
                return
        name = ' '.join(x for x in [getattr(user, 'first_name', ''), getattr(user, 'last_name', '')] if x).strip() or 'Unknown'
        username = getattr(user, 'username', None)
        role = 'User/Reseller'
        line = (f"🔎 <b>BOT ACTIVITY</b>\n👤 <b>Name:</b> {html.escape(name)}\n"
                f"🔗 <b>Username:</b> @{html.escape(username) if username else 'N/A'}\n"
                f"🆔 <b>Telegram User ID:</b> <code>{uid}</code>\n"
                f"👥 <b>Type:</b> {role}\n📍 <b>Action:</b> {html.escape(str(event))}\n"
                f"📝 <b>Details:</b> {html.escape(str(details)[:700])}\n🕒 <b>Time:</b> {_now_ist_text()}")
        with _ACTIVITY_LOCK:
            conn=sqlite3.connect(BOT_DB_PATH if 'BOT_DB_PATH' in globals() else 'shop_data.db', timeout=10)
            conn.execute('CREATE TABLE IF NOT EXISTS activity_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, event TEXT, details TEXT, created_at TEXT)')
            conn.execute('INSERT INTO activity_log(user_id,event,details,created_at) VALUES(?,?,?,?)',(uid,str(event),str(details),_now_ist_text()))
            conn.commit(); conn.close()
        for aid in ADMIN_IDS:
            try: bot.send_message(aid, line, parse_mode='HTML')
            except Exception: pass
    except Exception as exc:
        print('[ACTIVITY LOG]', exc)

def _admin_recent_activity_counts(window_minutes=5):
    """Return distinct recently active users/resellers for Admin reporting.

    Telegram bots cannot read a user's real online/presence state. The Admin
    Panel therefore reports recent bot activity and explicitly shows the time
    window used for the count.
    """
    try:
        minutes = max(1, int(window_minutes))
        cutoff = (datetime.datetime.now() - datetime.timedelta(minutes=minutes)).strftime('%Y-%m-%d %H:%M:%S')
        conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
        try:
            rows = conn.execute(
                """SELECT DISTINCT a.user_id, COALESCE(u.is_reseller, 0)
                   FROM activity_log a
                   LEFT JOIN users u ON u.user_id = a.user_id
                   WHERE a.created_at >= ?""",
                (cutoff,)
            ).fetchall()
        finally:
            conn.close()
        users = {int(r[0]) for r in rows if r and r[0] is not None}
        resellers = {int(r[0]) for r in rows if r and r[0] is not None and int(r[1] or 0) == 1}
        return len(users), len(resellers), minutes
    except Exception as exc:
        print(f"[ADMIN ACTIVE COUNT ERROR] {exc}")
        return 0, 0, max(1, int(window_minutes))

def _now_ist():
    try:
        if ZoneInfo is not None:
            return datetime.datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:
        pass
    return datetime.datetime.now()

def _now_ist_text(fmt="%Y-%m-%d %H:%M:%S"):
    return _now_ist().strftime(fmt)

# ==================== PER-INSTANCE RUNTIME CONFIGURATION ====================
# Customer-specific values are supplied by the Bot-Maker website through the
# generated bot instance environment. No customer's Telegram token, payment
# secret, server URL/key, or personal support contact is hard-coded here.
def _load_external_runtime_config():
    """Load only the public runtime inputs kept outside the protected bot code.

    Environment variables remain the first priority so generated child bots and
    existing deployments keep working exactly as before.  For a standalone
    deployment, bot_config.json may provide BOT_TOKEN and BOT_ADMIN_IDS.
    """
    config_path = Path(__file__).resolve().with_name('bot_config.json')
    try:
        if config_path.exists():
            raw = json.loads(config_path.read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                token = str(raw.get('BOT_TOKEN', '') or '').strip()
                admins = raw.get('BOT_ADMIN_IDS', [])
                if token and not os.getenv('BOT_TOKEN'):
                    os.environ['BOT_TOKEN'] = token
                if admins and not os.getenv('BOT_ADMIN_IDS'):
                    if isinstance(admins, (list, tuple, set)):
                        os.environ['BOT_ADMIN_IDS'] = ','.join(str(x).strip() for x in admins)
                    else:
                        os.environ['BOT_ADMIN_IDS'] = str(admins).strip()
    except Exception as exc:
        print(f'[CONFIG] Could not read bot_config.json: {exc}')

def _env_list_of_ints(name):
    raw = os.getenv(name, '').strip()
    values = []
    for part in raw.split(','):
        part = part.strip()
        if part.isdigit():
            try:
                values.append(int(part))
            except Exception:
                pass
    return list(dict.fromkeys(values))

_load_external_runtime_config()
BOT_BRAND_NAME = os.getenv('BOT_BRAND_NAME', 'RG CHEAT SHOP').strip() or 'RG CHEAT SHOP'
# Short brand used in the admin panel title: the main bot keeps its classic "RG" title, every
# created (reseller) bot shows its own name.
BOT_BRAND_SHORT = 'RG' if BOT_BRAND_NAME == 'RG CHEAT SHOP' else BOT_BRAND_NAME
TOKEN = os.getenv('BOT_TOKEN', '').strip()
ADMIN_IDS = _env_list_of_ints('BOT_ADMIN_IDS')
# The IDs supplied when a bot is created are its source/root admins. They are
# protected from removal, while admins added later remain removable.
_HARDCODED_ROOT_ADMIN_IDS = frozenset(ADMIN_IDS)

# --- FAMGATEWAY API CONFIGURATION ---
FAM_API_KEY = os.getenv('FAMPAY_API_KEY', '').strip()
# Official FamGateway endpoint. FAMPAY_GATEWAY_URL can still override this for
# an explicitly configured compatible/legacy gateway.
BASE_GATEWAY_URL = os.getenv('FAMPAY_GATEWAY_URL', 'https://fampaygateway.site').strip()
RECEIVER_UPI = os.getenv('FAMPAY_UPI_ID', '').strip()


# --- SAFE TELEGRAM LONG MESSAGE SENDER (ADDED PATCH) ---
def _send_long_html_message(chat_id, text, reply_markup=None):
    """Send long HTML messages without Telegram 4096 character errors."""
    text = str(text or "")
    limit = 3800
    if len(text) <= limit:
        return bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=reply_markup)
    parts = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            if current:
                parts.append(current)
            current = line
        else:
            current = (current + "\n" + line) if current else line
    if current:
        parts.append(current)
    last = None
    for part in parts:
        last = bot.send_message(chat_id, part, parse_mode="HTML")
    return last

# --- RESELLER / SERVER API CONFIGURATION ---
# Existing per-product server mappings stored in shop_data.db remain supported.
# Optional environment fallbacks are intentionally blank by default.
RESELLER_API_URL = os.getenv('RESELLER_API_URL', '').strip()
RESELLER_API_KEY = os.getenv('RESELLER_API_KEY', '').strip()
RESELLER_MASTER_KEY = os.getenv('RESELLER_MASTER_KEY', '').strip()
RESELLER_API_PUBLIC_URL_FALLBACK = os.getenv('RESELLER_API_PUBLIC_URL', '').strip()
NEW_SERVER_API_URL = os.getenv('NEW_SERVER_API_URL', '').strip()
NEW_SERVER_API_KEY = os.getenv('NEW_SERVER_API_KEY', '').strip()
NEW_SERVER_ENABLED_KEY = 'new_server_api_enabled'

# --- 9X API CONFIGURATION ---
NINEX_API_URL_KEY = 'ninex_api_url'
NINEX_API_TOKEN_KEY = 'ninex_api_token'
NINEX_PRODUCT_MAP_KEY = 'ninex_product_map'
NINEX_DEFAULT_API_URL = os.getenv('NINEX_DEFAULT_API_URL', '').strip()
NINEX_DEVICE_TYPE = 'single'

# --- TobiX Seller API CONFIGURATION ---
TOBIX_API_URL_KEY = 'tobix_api_url'
TOBIX_API_TOKEN_KEY = 'tobix_api_token'
TOBIX_PRODUCT_MAP_KEY = 'tobix_product_map'
TOBIX_DEFAULT_API_URL = os.getenv('TOBIX_DEFAULT_API_URL', '').strip()

# Support/contact configuration. Empty values intentionally mean these are not
# shown until an admin configures them for that bot instance.
WHATSAPP_NUM = os.getenv('WHATSAPP_NUM', '').strip()
TELEGRAM_USER = os.getenv('TELEGRAM_USER', '').strip()
UPDATE_CHANNEL_LINK = os.getenv('UPDATE_CHANNEL_LINK', '').strip()

BOT_CREATOR_ENABLED = os.getenv('BOT_CREATOR_ENABLED', '1').strip().lower() not in {'0','false','no','off'}

# Customer-facing Bot Make product. It is stored in the normal products table
# with an additive flag, but hidden from ordinary Hack/Product management so
# existing products and workflows are untouched.
BOT_MAKE_PRODUCT_NAME = 'Bot Make'
BOT_MAKE_ENABLED_KEY = 'bot_make_enabled'

BOT_EXPIRES_AT = float(os.getenv('BOT_EXPIRES_AT', '0') or 0)
BOT_INSTANCE_ID = os.getenv('BOT_INSTANCE_ID', '').strip()
BOT_INSTANCES_DIR = Path(os.getenv('BOT_INSTANCES_DIR', 'bot_instances')).resolve()
# Every bot process uses its own physical SQLite database.  The Master Bot
# keeps the default root database, while generated child bots receive an
# explicit BOT_DB_PATH pointing at their own instance directory.  This avoids
# accidental cross-bot data leakage caused by relative SQLite paths.
_CONFIGURED_BOT_DB_PATH = Path(os.getenv('BOT_DB_PATH', 'shop_data.db')).resolve()

# Hard isolation guard for generated/customer bots.  The child database path is
# derived from its immutable instance id instead of trusting a possibly stale
# or inherited BOT_DB_PATH value.  The Master Bot keeps its own root database.
if BOT_INSTANCE_ID and not BOT_CREATOR_ENABLED:
    _EXPECTED_CHILD_DB_PATH = (BOT_INSTANCES_DIR / str(BOT_INSTANCE_ID) / 'shop_data.db').resolve()
    if _CONFIGURED_BOT_DB_PATH != _EXPECTED_CHILD_DB_PATH:
        print(
            f'[BOT ISOLATION] Correcting child DB path from ' +
            f'{_CONFIGURED_BOT_DB_PATH} to {_EXPECTED_CHILD_DB_PATH}'
        )
    BOT_DB_PATH = _EXPECTED_CHILD_DB_PATH
else:
    BOT_DB_PATH = _CONFIGURED_BOT_DB_PATH

BOT_EXPIRED_RUNTIME = False
BOT_INSTANCES_DIR.mkdir(parents=True, exist_ok=True)
if BOT_INSTANCE_ID and not BOT_CREATOR_ENABLED:
    BOT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Child startup/readiness marker.  The Master Bot waits for this marker before
# reporting a newly-created bot as running, so a slow import/startup cannot
# produce a false-positive "Bot created" state.
BOT_CHILD_READY_FILE = Path(
    os.getenv('BOT_CHILD_READY_FILE', str((BOT_DB_PATH.parent / '.bot_ready').resolve()))
).resolve()

if not TOKEN:
    raise RuntimeError('BOT_TOKEN is not configured for this bot instance.')
if not ADMIN_IDS:
    raise RuntimeError('BOT_ADMIN_IDS is not configured for this bot instance.')

# Bounded per-process concurrency: multiple generated bots can run together
# without creating hundreds of OS threads and starving Telegram polling.
# Values remain configurable through environment variables.
def _runtime_int_env(name, default, minimum=1, maximum=128):
    try:
        value = int(os.getenv(name, str(default)))
        return max(minimum, min(maximum, value))
    except (TypeError, ValueError):
        return int(default)

BOT_TELEGRAM_WORKERS = _runtime_int_env(
    'BOT_TELEGRAM_WORKERS', 6 if (BOT_INSTANCE_ID and not BOT_CREATOR_ENABLED) else 16, 4, 64
)
USER_TASK_WORKERS = _runtime_int_env(
    'USER_TASK_WORKERS', 6 if (BOT_INSTANCE_ID and not BOT_CREATOR_ENABLED) else 16, 4, 64
)
PAYMENT_TASK_WORKERS = _runtime_int_env(
    'PAYMENT_TASK_WORKERS', 3 if (BOT_INSTANCE_ID and not BOT_CREATOR_ENABLED) else 8, 2, 32
)
HTTP_POOL_SIZE = _runtime_int_env(
    'HTTP_POOL_SIZE', 12 if (BOT_INSTANCE_ID and not BOT_CREATOR_ENABLED) else 32, 8, 64
)

try:
    bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=BOT_TELEGRAM_WORKERS)
except TypeError:
    # Compatibility with older pyTelegramBotAPI releases.
    bot = telebot.TeleBot(TOKEN)
admin_temp_data = {}

# Per-child-bot Admin Panel button visibility. The Master Admin can toggle any
# child Admin Panel button without deleting its underlying functionality.
ADMIN_BUTTON_VISIBILITY_KEY = "disabled_admin_buttons"
_ADMIN_BUTTON_REGISTRY = {}

def _disabled_admin_buttons():
    if BOT_CREATOR_ENABLED:
        return set()
    try:
        raw = get_setting(ADMIN_BUTTON_VISIBILITY_KEY) or "[]"
        data = json.loads(raw)
        return {str(x) for x in data if str(x).strip()} if isinstance(data, list) else set()
    except Exception:
        return set()

def _admin_button_is_disabled(button_key=None, callback_data=None):
    disabled = _disabled_admin_buttons()
    keys = []
    if button_key:
        keys.append(str(button_key))
    if callback_data:
        keys.append(f"admin:callback:{callback_data}")
    return any(k in disabled for k in keys)

def _register_admin_button(button_key, callback_data, text):
    if button_key:
        _ADMIN_BUTTON_REGISTRY[str(button_key)] = {
            "text": str(text or ""),
            "callback_data": str(callback_data or ""),
        }

def _filter_disabled_admin_markup(markup):
    if BOT_CREATOR_ENABLED or not isinstance(markup, types.InlineKeyboardMarkup):
        return markup
    disabled = _disabled_admin_buttons()
    if not disabled:
        return markup
    try:
        new_keyboard = []
        for row in (getattr(markup, "keyboard", None) or []):
            kept = []
            for button in (row or []):
                cb = str(getattr(button, "callback_data", "") or "")
                # Registered make_ui_button controls use their exact key; raw
                # InlineKeyboardButton admin controls fall back to callback key.
                key = _ADMIN_BUTTON_REGISTRY.get(cb, {}).get("button_key")
                if not key:
                    for k, info in _ADMIN_BUTTON_REGISTRY.items():
                        if str(info.get("callback_data") or "") == cb:
                            key = k
                            break
                fallback = f"admin:callback:{cb}" if cb else ""
                if (key and key in disabled) or (fallback and fallback in disabled):
                    continue
                kept.append(button)
            if kept:
                new_keyboard.append(kept)
        markup.keyboard = new_keyboard
    except Exception as exc:
        print(f"[ADMIN BUTTON VISIBILITY ERROR] {exc}")
    return markup

# Fast runtime caches: settings are updated immediately by set_setting(), while
# admin-ID checks are cached briefly to avoid repeated SQLite opens on callbacks.
_SETTINGS_CACHE = {}
_SETTINGS_CACHE_LOCK = threading.RLock()
_ADMIN_IDS_CACHE = None
_ADMIN_IDS_CACHE_TS = 0.0
_ADMIN_IDS_CACHE_TTL = 5.0

# Shared background executor keeps slow payment/API work isolated from Telegram
# callback workers. This prevents one user's slow gateway/API request from
# slowing down unrelated users.
USER_TASK_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=USER_TASK_WORKERS,
    thread_name_prefix="rg-user"
)

# Dedicated checkout workers keep Wallet/UPI payment actions responsive even if
# unrelated background user/API tasks temporarily fill the general pool.
PAYMENT_TASK_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=PAYMENT_TASK_WORKERS,
    thread_name_prefix="rg-payment"
)

# Per-admin navigation state. After an admin completes a multi-step action,
# return to the section they were working in instead of reopening the Main
# Admin Panel.
admin_return_state = {}
admin_nav_snapshots = {}
admin_nav_current = {}
admin_nav_skip_history = set()

# Fine-grained Admin navigation context.  This is intentionally separate from
# admin_return_state so the older category navigation remains backward compatible.
# It remembers the exact screen immediately before a multi-step save/edit action.
admin_pending_return = {}

# Persistent selected Product/Hack context for the Admin Product & Plans hub.
# This is intentionally separate from admin_temp_data because multi-step inputs
# replace/clear temporary fields while the admin is still inside the same hack.
admin_active_product = {}

def _pp_set_active_product(user_id, product_name):
    try:
        uid = int(user_id)
        name = str(product_name or '').strip()
        if name:
            admin_active_product[uid] = name
    except Exception:
        pass
    return str(product_name or '').strip()

def _pp_active_product(user_id):
    try:
        name = str(admin_active_product.get(int(user_id)) or '').strip()
    except Exception:
        name = ''
    if name and name in get_unique_products():
        return name
    return ''

def _pp_resolve_product(user_id, h=''):
    """Resolve a selected Product/Hack from catalog data or persistent context."""
    uid = int(user_id)
    raw_h = str(h or '').strip()
    data = admin_temp_data.get(uid, {}) or {}
    catalog = data.get('pp_hack_catalog', {}) or {}
    product_name = catalog.get(raw_h)
    if product_name:
        _pp_set_active_product(uid, product_name)
        return str(product_name)
    active = _pp_active_product(uid)
    if active:
        expected = _ui_hash(f'pp:{active}')
        legacy = _ui_hash(active)
        if not raw_h or raw_h in {expected, legacy}:
            admin_temp_data.setdefault(uid, {}).setdefault('pp_hack_catalog', {})[expected] = active
            return active
    return ''

def _admin_snapshot_equivalent(a, b):
    """Return True when two Admin snapshots represent the same visible screen."""
    if not a or not b:
        return False
    try:
        if int(a.get("message_id") or 0) != int(b.get("message_id") or 0):
            return False
        if str(a.get("text") or "") != str(b.get("text") or ""):
            return False
        return True
    except Exception:
        return False


def _admin_capture_live_parent(call):
    """Capture the actual Admin message before routing a callback.

    A number of legacy Admin helpers render directly with ``bot.send_message``
    instead of ``_admin_ui_send``.  In those screens the normal snapshot writer
    never sees the page, which is why Back could jump to an older page or Main
    Admin.  Capturing the live Telegram message at callback time makes the
    navigation stack independent of which renderer produced the page.
    """
    try:
        uid = int(call.from_user.id)
        if not _is_admin(uid) or not getattr(call, "message", None):
            return
        message = call.message
        text = str(getattr(message, "text", None) or getattr(message, "caption", None) or "")
        markup = copy.deepcopy(getattr(message, "reply_markup", None))
        if not text and not isinstance(markup, types.InlineKeyboardMarkup):
            return

        current = admin_nav_current.get(uid)
        screen_id = str(current.get("screen_id") or "") if current and int(current.get("message_id") or 0) == int(message.message_id) else ""
        if not screen_id:
            digest = hashlib.sha1((text + "|" + str(message.message_id)).encode("utf-8", "ignore")).hexdigest()[:12]
            screen_id = f"live_{digest}"

        live = {
            "screen_id": screen_id,
            "text": text,
            "markup": markup,
            "message_id": int(message.message_id),
            "temp_data": copy.deepcopy(admin_temp_data.get(uid, {})),
        }

        stack = admin_nav_snapshots.setdefault(uid, [])
        if not _admin_snapshot_equivalent(stack[-1] if stack else None, live):
            # The current live screen is the parent of the callback being
            # handled. Keep only a bounded history to prevent stale growth.
            stack.append(copy.deepcopy(live))
            admin_nav_snapshots[uid] = stack[-30:]
        admin_nav_current[uid] = live
    except Exception as exc:
        print(f"[ADMIN LIVE SNAPSHOT ERROR] {exc}")


def _admin_store_snapshot(user_id, text, markup, screen_id=None, message_id=None, record_history=True):
    """Store the current Admin screen and, when appropriate, remember its parent.

    Some older Admin screens render directly through helper functions instead of
    _admin_ui_send().  Previously those screens did not get pushed onto the
    navigation stack, so their Back button could fall through to the Main Admin
    Panel.  Recording the previous screen here makes both rendering paths use
    the same one-level navigation history.

    ``record_history=False`` is used only while restoring an already-saved parent
    so restoring a screen cannot create a navigation loop.
    """
    try:
        uid = int(user_id)
        new_id = str(screen_id or "")
        if new_id == "admin_main":
            admin_nav_snapshots.pop(uid, None)
            admin_nav_current.pop(uid, None)
        current = admin_nav_current.get(uid)
        if uid in admin_nav_skip_history:
            record_history = False
            admin_nav_skip_history.discard(uid)
        if record_history and current and str(current.get("screen_id") or "") != new_id:
            stack = admin_nav_snapshots.setdefault(uid, [])
            # The callback router may already have captured the live parent.
            # Never add that same page twice; duplicate snapshots were the main
            # cause of Back appearing to do nothing / loop on the same screen.
            if not _admin_snapshot_equivalent(stack[-1] if stack else None, current):
                stack.append(copy.deepcopy(current))
                admin_nav_snapshots[uid] = stack[-30:]
        admin_nav_current[uid] = {
            "screen_id": new_id,
            "text": str(text or ""),
            "markup": copy.deepcopy(markup) if isinstance(markup,types.InlineKeyboardMarkup) else None,
            "message_id": int(message_id or 0),
            # Dynamic Admin keyboards depend on temporary hash->record maps.
            # Snapshot those maps together with the keyboard so Back never
            # restores a button whose callback data no longer has a mapping.
            "temp_data": copy.deepcopy(admin_temp_data.get(uid, {})),
        }
    except Exception as exc: print(f"[ADMIN SNAPSHOT STORE ERROR] {exc}")

def _admin_push_current_snapshot(user_id,next_screen_id=None):
    try:
        uid=int(user_id); cur=admin_nav_current.get(uid)
        if not cur or (next_screen_id and cur.get("screen_id")==str(next_screen_id)): return
        admin_nav_snapshots.setdefault(uid,[]).append(copy.deepcopy(cur))
        admin_nav_snapshots[uid]=admin_nav_snapshots[uid][-30:]
    except Exception as exc: print(f"[ADMIN SNAPSHOT PUSH ERROR] {exc}")

def _admin_pop_snapshot(user_id):
    uid=int(user_id); stack=admin_nav_snapshots.get(uid) or []
    if not stack: return None
    # Collapse consecutive duplicate pages defensively. Older sessions may have
    # been created by the previous navigation implementation.
    snap = stack.pop()
    while stack and _admin_snapshot_equivalent(stack[-1], snap):
        snap = stack.pop()
    if not stack: admin_nav_snapshots.pop(uid,None)
    return snap

def _admin_navigation_barrier(user_id, keep_screen_ids=()):
    """Drop stale Admin navigation history while keeping one valid parent.

    Destructive operations and top-level returns must not leave deleted or
    previously visited sibling Product/Server screens in the Back stack.
    """
    try:
        uid = int(user_id)
        wanted = {str(x) for x in (keep_screen_ids or ())}
        stack = admin_nav_snapshots.get(uid) or []
        parent = None
        if wanted:
            for snap in reversed(stack):
                if str((snap or {}).get('screen_id') or '') in wanted:
                    parent = copy.deepcopy(snap)
                    break
        if parent is not None:
            admin_nav_snapshots[uid] = [parent]
        else:
            admin_nav_snapshots.pop(uid, None)
        admin_nav_current.pop(uid, None)
        admin_pending_return.pop(uid, None)
    except Exception as exc:
        print(f"[ADMIN NAV BARRIER ERROR] {exc}")


def _admin_restore_snapshot(call,snapshot):
    if not snapshot: return False
    try:
        markup=copy.deepcopy(snapshot.get("markup"))
        if isinstance(markup, types.InlineKeyboardMarkup) and str(snapshot.get("screen_id") or "") != "admin_main":
            markup = _style_admin_markup(_ensure_admin_back_button(markup))
        # Restore the exact temporary callback/catalog state belonging to this
        # screen before restoring its keyboard. Without this, a Back action
        # could show an old button whose hash no longer existed in
        # admin_temp_data, making the button appear frozen/unresponsive.
        saved_temp = snapshot.get("temp_data")
        if isinstance(saved_temp, dict):
            admin_temp_data[int(call.from_user.id)] = copy.deepcopy(saved_temp)
        bot.edit_message_text(snapshot.get("text") or "🛠️ <b>Admin</b>",chat_id=call.message.chat.id,message_id=call.message.message_id,parse_mode="HTML",reply_markup=markup)
        _admin_store_snapshot(call.from_user.id,snapshot.get("text"),markup,snapshot.get("screen_id"),call.message.message_id,record_history=False); return True
    except Exception as exc: print(f"[ADMIN SNAPSHOT RESTORE ERROR] {exc}"); return False


def _admin_restore_snapshot_by_chat(chat_id,user_id):
    """Restore the previous Admin screen after a text-input action completes."""
    snap=_admin_pop_snapshot(user_id)
    if not snap: return False
    mid=int(snap.get("message_id") or 0)
    if not mid: return False
    try:
        markup=copy.deepcopy(snap.get("markup"))
        if isinstance(markup, types.InlineKeyboardMarkup) and str(snap.get("screen_id") or "") != "admin_main":
            markup = _style_admin_markup(_ensure_admin_back_button(markup))
        bot.edit_message_text(snap.get("text") or "🛠️ <b>Admin</b>",chat_id=int(chat_id),message_id=mid,parse_mode="HTML",reply_markup=markup)
        _admin_store_snapshot(user_id,snap.get("text"),markup,snap.get("screen_id"),mid,record_history=False)
        return True
    except Exception as exc:
        print(f"[ADMIN SNAPSHOT CHAT RESTORE ERROR] {exc}")
        return False


def _admin_parent_context(user_id, callback_data):
    """Return the exact Admin screen to reopen after a successful step.

    The old navigation stored only the broad category (for example ``emoji``).
    That caused a save from All Button Emoji -> selected button -> Premium Emoji
    to jump all the way back to the category menu.  Keep the old state intact and
    add a precise one-level parent here.
    """
    uid = int(user_id)
    data = str(callback_data or "")

    # Product creation is a multi-step flow too.  Keep Back on every prompt
    # and return to the Product & Plans hub instead of the Main Admin Panel.
    if data == "pp_add_product":
        return {"callback": "admin_cat_setup"}

    # Hack/day management
    if data in {"admin_add_hack_plan", "admin_add_day_exist", "sel_hack_add_day_"}:
        return {"callback": "admin_hack_day_mgmt"}
    if data.startswith("sel_hack_add_day_"):
        return {"callback": "admin_add_day_exist"}
    if data.startswith("edit_hack_name_"):
        h = data.replace("edit_hack_name_", "", 1)
        return {"callback": f"edit_hack_select_{h}", "hash": h}
    if data.startswith("edit_hack_price_plan_"):
        pid = data.replace("edit_hack_price_plan_", "", 1)
        return {"callback": f"edit_hack_price_{pid}", "plan_id": int(pid) if str(pid).isdigit() else None}
    if data.startswith("edit_hack_days_plan_"):
        pid = data.replace("edit_hack_days_plan_", "", 1)
        return {"callback": f"edit_hack_days_{pid}", "plan_id": int(pid) if str(pid).isdigit() else None}
    if data.startswith("confirm_del_hack_"):
        return {"callback": "admin_del_hack"}
    if data.startswith("select_del_plan_hack_"):
        name = data.replace("select_del_plan_hack_", "", 1)
        return {"callback": f"select_del_plan_hack_{name}"}
    if data.startswith("confirm_del_plan_"):
        pid = data.replace("confirm_del_plan_", "", 1)
        try:
            prow = get_product_by_id(int(pid))
            if prow:
                return {"callback": f"select_del_plan_hack_{prow[1]}"}
        except Exception:
            pass
        return {"callback": "admin_del_plan"}

    # Product custom-price / key / Premium-design nested editors
    if data.startswith("pp_custom_price_plan_"):
        raw=data.replace("pp_custom_price_plan_", "", 1)
        try:
            _, h=raw.rsplit("_",1); return {"callback":"pp_custom_price_target","hash":h}
        except Exception: return {"callback":"pp_hacks"}
    if data.startswith("pp_key_edit_"):
        raw=data.replace("pp_key_edit_", "", 1)
        try:
            _, h=raw.rsplit("_",1); return {"callback":f"pp_keys_{h}"}
        except Exception: return {"callback":"pp_hacks"}
    if data.startswith("hpui_plan_"):
        ph=data.replace("hpui_plan_", "", 1); item=admin_temp_data.get(uid,{}).get("hpui_plan_catalog",{}) .get(ph)
        product=(item.get("product") if item else None) or admin_temp_data.get(uid,{}).get("hpui_return_product")
        return {"callback":f"hpui_select_{_ui_hash(product)}"} if product else {"callback":"admin_hack_price_ui"}
    if data.startswith("manual_key_edit_"):
        try:
            pid=int(data.replace("manual_key_edit_", "", 1)); prod=get_product_by_id(pid)
            if prod: return {"callback":f"manual_key_view_prod_{hashlib.sha1(str(prod[1]).encode()).hexdigest()[:12]}"}
        except Exception: pass
        return {"callback":"admin_manual_key_view"}

    # User-panel button editors
    if data.startswith("abe_select_"):
        return {"callback": "admin_all_button_emoji"}
    if data.startswith("upc_color_"):
        h=data.rsplit("_",1)[-1]
        key=admin_temp_data.get(uid,{}).get("product_plan_color_catalog",{}).get(h) or admin_temp_data.get(uid,{}).get("active_user_panel_color_key")
        product=admin_temp_data.get(uid,{}).get("product_plan_color_product")
        if product and key and (str(key).startswith("price:") or str(key).startswith("hack:")):
            return {"callback":f"upc_product_{_ui_hash(product)}"}
        return {"callback":f"upc_select_{h}","hash":h}
    if data.startswith("upc_select_"):
        return {"callback": "admin_button_colors"}
    if data.startswith("cust_name_"):
        return {"callback": "admin_button_cust"}
    if data.startswith("emoji_pick_"):
        h = data.replace("emoji_pick_", "", 1)
        key = admin_temp_data.get(uid, {}).get("emoji_catalog", {}).get(h, "")
        if str(key).startswith("hack:"):
            return {"callback": "emoji_group_hack_buttons", "group": "hack_buttons"}
        if str(key).startswith("price:"):
            return {"callback": "emoji_group_price_buttons", "group": "price_buttons"}
        if str(key).startswith("main:"):
            return {"callback": "emoji_group_main_buttons", "group": "main_buttons"}
        return {"callback": "admin_emoji_editor"}

    # Text/plan-text editors
    if data.startswith("edit_txt_"):
        return {"callback": "admin_text_editor"}
    if data.startswith("plantext_select_") or data.startswith("plantext_clear_"):
        return {"callback": "admin_plan_text_add"}

    if data in {"admin_all_panel_price_emoji", "admin_all_product_emoji", "admin_all_price_emoji"}:
        return {"callback": "admin_emoji_editor"}
    if data in {"admin_button_cust", "admin_all_button_emoji", "admin_button_colors"}:
        return {"callback": data}
    if data in {"admin_plan_text_add"}:
        return {"callback": "admin_text_editor"}

    # API / gateway / server editors
    if data in {"gw_edit_fam", "gw_edit_paytm"} or data.startswith("gw_"):
        return {"callback": "admin_gateway_manager"}
    if data.startswith(("api_srv_", "new_server_")):
        return {"callback": "new_server_api"}
    if data.startswith("hack_server_"):
        return {"callback": "admin_hack_server_manager"}
    if data.startswith("set_tg_hack_"):
        return {"callback": "admin_set_tg_group"}

    # Bot Make editor: all saves/deletes return to its own manager, never to
    # the generic Product/Hack setup screen.
    if data.startswith("botmake_") or data in {"admin_bot_creator", "admin_bot_list", "admin_created_bots"}:
        return {"callback": "admin_botmake_manager"}

    # Generic category-level fallback for all remaining admin workflows.
    kind, value = _admin_return_category_for_callback(data)
    if kind == "hack_day":
        return {"callback": "admin_hack_day_mgmt"}
    if kind == "gateway":
        return {"callback": "admin_gateway_manager"}
    if kind == "admins":
        return {"callback": "admin_manage_admins"}
    if kind == "hack_server":
        return {"callback": "admin_hack_server_manager"}
    if kind == "api":
        return {"callback": "new_server_api"}
    if kind == "hack_price":
        return {"callback": "admin_hack_price_ui"}
    if kind == "category":
        return {"callback": f"admin_cat_{value or 'setup'}"}
    return {"callback": "admin_main"}

def _remember_admin_pending_return(user_id, callback_data, message_id=None):
    """Remember one-level return destination for a multi-step Admin action."""
    try:
        ctx = _admin_parent_context(user_id, callback_data)
        if ctx:
            ctx["message_id"] = int(message_id) if message_id else None
            admin_pending_return[int(user_id)] = ctx
    except Exception as exc:
        print(f"[ADMIN NAV CONTEXT ERROR] {exc}")

def _render_admin_parent_screen(chat_id, user_id):
    """Render the exact parent screen saved before a multi-step action."""
    uid = int(user_id)
    ctx = admin_pending_return.pop(uid, None)
    if not ctx:
        return _send_admin_panel_after_success(chat_id, user_id=uid)

    cb = str(ctx.get("callback") or "admin_main")
    mid = ctx.get("message_id")

    try:
        # Existing dedicated screens.
        if cb == "admin_main":
            markup = _admin_main_markup()
            text = ("🛠️ <b>ADMIN CONTROL PANEL</b>\n\n"
                    "<i>Clean controls • Clear names • All important settings in sections</i>")
        elif cb == "pp_hack_direct" or cb.startswith("pp_hack_"):
            # Rebuild the exact selected-hack screen directly. This avoids using
            # an older snapshot whose temporary hash catalog may have been
            # replaced by a VIP-key/plan/link input step.
            raw_h = cb.replace("pp_hack_", "", 1) if cb.startswith("pp_hack_") else ""
            product_name = str(ctx.get("product_name") or "")
            if not product_name and raw_h:
                product_name = _pp_resolve_product(uid, raw_h)
            if not product_name:
                product_name = _pp_active_product(uid)
            if not product_name:
                return _send_admin_panel_after_success(chat_id, user_id=uid)
            _pp_set_active_product(uid, product_name)
            h = _ui_hash(f"pp:{product_name}")
            admin_temp_data.setdefault(uid, {}).setdefault('pp_hack_catalog', {})[h] = product_name
            admin_temp_data[uid]['edit_hack_name'] = product_name
            plans = get_product_plans(product_name)
            lines = [f"🎮 <b>{html.escape(product_name)}</b>", "━━━━━━━━━━━━━━━━━━━━", f"📦 <b>{len(plans)} Plan(s)</b>", ""]
            for idx, plan in enumerate(plans, 1):
                lines.append(f"{idx}. 📅 <b>{html.escape(str(plan[2]))}</b>  ·  User ₹{plan[3]:.2f}  ·  Reseller ₹{plan[4]:.2f}")
            markup = _pp_selected_hack_screen(uid, product_name)
            text = "\n".join(lines)
        elif cb == "admin_hack_day_mgmt":
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("➕ Add New Hack & Day Plan", callback_data="admin_add_hack_plan"),
                       types.InlineKeyboardButton("📅 Add Day to Existing Hack", callback_data="admin_add_day_exist"))
            markup.add(types.InlineKeyboardButton("✏️ Edit Existing Hack / Price / Plan", callback_data="admin_edit_hack_inside"))
            markup.add(types.InlineKeyboardButton("🗑️ Remove Entire Hack", callback_data="admin_del_hack"),
                       types.InlineKeyboardButton("❌ Remove Day / Plan", callback_data="admin_del_plan"))
            text = "⚙️ <b>HACK & DAY MANAGEMENT PANEL</b>\n\nSelect action:"
        elif cb == "admin_del_hack":
            products = get_unique_products()
            markup = types.InlineKeyboardMarkup()
            for prod in products:
                markup.add(types.InlineKeyboardButton(f"🗑️ Delete {prod}", callback_data=f"confirm_del_hack_{prod}"))
            text = ("⚠️ <b>SELECT ENTIRE HACK TO DELETE:</b>\n"
                    "<i>This will remove all plans associated with this hack!</i>")
        elif cb == "admin_del_plan":
            products = get_unique_products()
            markup = types.InlineKeyboardMarkup()
            for prod in products:
                markup.add(types.InlineKeyboardButton(f"🎮 {prod}", callback_data=f"select_del_plan_hack_{prod}"))
            text = "❌ <b>SELECT HACK TO DELETE A SPECIFIC PLAN/DAY:</b>"
        elif cb.startswith("select_del_plan_hack_"):
            prod_name = cb.replace("select_del_plan_hack_", "", 1)
            plans = get_product_plans(prod_name)
            markup = types.InlineKeyboardMarkup()
            for plan in plans:
                p_id, _, p_days, p_price, *_ = plan
                markup.add(types.InlineKeyboardButton(
                    f"🗑️ Delete {p_days} Plan (₹{p_price:.2f})",
                    callback_data=f"confirm_del_plan_{p_id}"
                ))
            text = f"🎮 <b>Selected Hack: {html.escape(prod_name)}</b>\nSelect Plan to Delete:"
        elif cb.startswith("edit_hack_select_"):
            h = cb.replace("edit_hack_select_", "", 1)
            product_name = admin_temp_data.get(uid, {}).get("edit_hack_catalog", {}).get(h)
            if not product_name:
                product_name = admin_temp_data.get(uid, {}).get("edit_hack_name")
            if not product_name:
                return _send_admin_panel_after_success(chat_id, user_id=uid)
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(types.InlineKeyboardButton("✏️ Edit Hack Name", callback_data=f"edit_hack_name_{h}"),
                       types.InlineKeyboardButton("💰 Edit Price", callback_data=f"edit_hack_price_{h}"))
            markup.add(types.InlineKeyboardButton("📅 Edit Plan / Days", callback_data=f"edit_hack_days_{h}"))
            text = f"✏️ <b>EDIT: {html.escape(product_name)}</b>\n\nChoose what you want to change:"
        elif cb.startswith("edit_hack_price_"):
            # The stored value can be either a hash or a plan id. Resolve both.
            raw = cb.replace("edit_hack_price_", "", 1)
            product_name = admin_temp_data.get(uid, {}).get("edit_hack_name")
            if not product_name:
                try:
                    prow = get_product_by_id(int(raw))
                    product_name = prow[1] if prow else None
                except Exception:
                    product_name = None
            if not product_name:
                return _send_admin_panel_after_success(chat_id, user_id=uid)
            plans = get_product_plans(product_name)
            markup = types.InlineKeyboardMarkup(row_width=1)
            for plan in plans:
                markup.add(types.InlineKeyboardButton(
                    f"💰 {plan[2]} — ₹{plan[3]:.2f} / Resell ₹{plan[4]:.2f}",
                    callback_data=f"edit_hack_price_plan_{plan[0]}"
                ))
            text = f"💰 <b>SELECT PLAN TO EDIT PRICE</b>\n\nHack: {html.escape(product_name)}"
        elif cb.startswith("edit_hack_days_"):
            raw = cb.replace("edit_hack_days_", "", 1)
            product_name = admin_temp_data.get(uid, {}).get("edit_hack_name")
            if not product_name:
                try:
                    prow = get_product_by_id(int(raw))
                    product_name = prow[1] if prow else None
                except Exception:
                    product_name = None
            if not product_name:
                return _send_admin_panel_after_success(chat_id, user_id=uid)
            plans = get_product_plans(product_name)
            markup = types.InlineKeyboardMarkup(row_width=1)
            for plan in plans:
                markup.add(types.InlineKeyboardButton(
                    f"📅 {plan[2]}", callback_data=f"edit_hack_days_plan_{plan[0]}"
                ))
            text = f"📅 <b>SELECT PLAN TO EDIT DURATION</b>\n\nHack: {html.escape(product_name)}"
        elif cb == "pp_custom_price_target":
            product_name = str(admin_temp_data.get(uid,{}).get("pp_custom_price_product") or "")
            target = admin_temp_data.get(uid,{}).get("pp_custom_price_target")
            h = str(ctx.get("hash") or admin_temp_data.get(uid,{}).get("pp_custom_price_hash") or "")
            if not product_name or not target:
                return _send_admin_panel_after_success(chat_id,user_id=uid)
            markup = _pp_custom_price_plan_markup(int(target),product_name,h)
            text=("💰 <b>CUSTOM PRICE — SELECT PLAN</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
                   f"🎮 <b>Product:</b> {html.escape(product_name)}\n"
                   f"👤 <b>User ID:</b> <code>{int(target)}</code>\n\nSelect a plan to customize.")
        elif cb.startswith("pp_keys_"):
            h=cb.replace("pp_keys_", "", 1)
            product_name=admin_temp_data.get(uid,{}).get("pp_hack_catalog",{}).get(h)
            if not product_name:
                return _send_admin_panel_after_success(chat_id,user_id=uid)
            text,markup=_pp_key_stock_view(uid,product_name,h)
        elif cb.startswith("manual_key_view_prod_"):
            h=cb.replace("manual_key_view_prod_", "", 1)
            product_name=admin_temp_data.get(uid,{}).get("manual_view_catalog",{}).get(h)
            if not product_name:
                return _send_admin_panel_after_success(chat_id,user_id=uid)
            conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
            try: rows=conn.execute('SELECT id,validity_days,panel_key FROM panels WHERE panel_name=? AND is_sold=0 ORDER BY id ASC',(product_name,)).fetchall()
            finally: conn.close()
            lines=[f'🔑 <b>MANUAL KEYS — {html.escape(str(product_name))}</b>','━━━━━━━━━━━━━━━━━━━━','']
            markup=types.InlineKeyboardMarkup(row_width=1); current=None
            for pid,days,key in rows:
                if str(days)!=current: current=str(days); lines.append(f'\n📅 <b>{html.escape(current)}</b>')
                lines.append(f'   🔑 <code>{html.escape(str(key),quote=False)}</code>')
                markup.row(types.InlineKeyboardButton('✏️ Edit',callback_data=f'manual_key_edit_{int(pid)}'),types.InlineKeyboardButton('🗑 Delete',callback_data=f'manual_key_delete_{int(pid)}'))
            lines.append(f'\n📦 <b>Total Remaining:</b> {len(rows)}')
            markup.add(types.InlineKeyboardButton('🔄 Refresh',callback_data=f'manual_key_view_prod_{h}'))
            text='\n'.join(lines)
        elif cb == "admin_all_button_emoji":
            return show_user_panel_button_emoji_catalog(chat_id, message_id=mid)
        elif cb == "admin_button_colors":
            return show_user_panel_button_color_catalog(chat_id, message_id=mid)
        elif cb == "admin_button_cust":
            markup = types.InlineKeyboardMarkup()
            for label, key in [
                ("🛍️ Open Store Button", "open_store"), ("💰 Top Up Button", "top_up"),
                ("📜 Orders Button", "orders"), ("👤 My Account Button", "my_account"),
                ("🎁 Invite & Earn Button", "invite_earn"), ("🎬 How To Use Button", "how_to_use"),
                ("📢 All Update Button", "all_update"), ("📞 Help Desk Button", "help_desk"),
                ("❌ Add Balance Cancel Button", "topkey_cancel"),
                ("💳 Add Balance Confirm Button", "topkey_confirm"),
                ("🔴 All Products Out of Stock Button", "all_products_oos"),
            ]:
                markup.add(types.InlineKeyboardButton(label, callback_data=f"cust_name_{key}"))
            text = "✏️ <b>Select a Main Menu Button to edit its Name & Emoji:</b>"
        elif cb.startswith("emoji_group_"):
            group = cb.replace("emoji_group_", "", 1)
            if group == "main_buttons":
                items = [("Open Store","main:open_store"),("Top Up","main:top_up"),("Orders","main:orders"),
                         ("My Account","main:my_account"),("Invite & Earn","main:invite_earn"),
                         ("How To Use","main:how_to_use"),("All Update","main:all_update"),("Help Desk","main:help_desk")]
                markup = types.InlineKeyboardMarkup()
                for title, key in items:
                    h = _ui_hash(key)
                    markup.add(types.InlineKeyboardButton(title, callback_data=f"emoji_pick_{h}"))
                    admin_temp_data.setdefault(uid, {}).setdefault("emoji_catalog", {})[h] = key
                text = "✨ Select a main button to set its Premium emoji."
            elif group in ("hack_buttons", "price_buttons"):
                markup = types.InlineKeyboardMarkup(row_width=2)
                for prod in get_unique_products():
                    if group == "hack_buttons":
                        key = f"hack:{prod}"; h = _ui_hash(key)
                        admin_temp_data.setdefault(uid, {}).setdefault("emoji_catalog", {})[h] = key
                        markup.add(types.InlineKeyboardButton(f"🎮 {prod}", callback_data=f"emoji_pick_{h}"))
                    else:
                        for plan in get_product_plans(prod):
                            key = f"price:{prod}:{plan[0]}"; h = _ui_hash(key)
                            admin_temp_data.setdefault(uid, {}).setdefault("emoji_catalog", {})[h] = key
                            markup.add(types.InlineKeyboardButton(f"💙 {prod} / {plan[2]}", callback_data=f"emoji_pick_{h}"))
                text = "✨ Select a button to set its Premium emoji."
            else:
                return _send_admin_panel_after_success(chat_id, user_id=uid)
        elif cb == "admin_text_editor":
            # The full Text Editor markup is generated by its existing callback.
            # Use a compact equivalent here so no old controls are removed.
            # Text Editor: compact two-column layout.  The universal Admin
            # Back helper below always keeps Back alone on the final row.
            markup = types.InlineKeyboardMarkup(row_width=2)
            text_items = [
                ("Main Menu Text","edit_txt_main_menu"),("Store Menu Text","edit_txt_store_menu"),
                ("🎬 How To Use Bot Text + Premium Emoji","edit_txt_how_to_use"),
                ("💰 Add Balance Text + Premium Emoji","edit_txt_top_up"),
                ("💠 Price List / Plans Text + Premium Emoji","edit_txt_price_list"),
                ("Order Summary Text","edit_txt_order_summary"),("My Profile Text","edit_txt_my_profile"),
                ("Order History Text","edit_txt_order_history"),("Referral Program Text","edit_txt_referral_program"),
                ("Help Desk Text","edit_txt_help_desk"),("Payment Expired Text","edit_txt_payment_expired"),
                ("👋 Verification / First Start Text","edit_txt_verification_required"),
                ("👋 Welcome Message Text + Premium Emoji","edit_txt_welcome_message"),
                ("📱 Phone Verified Text","edit_txt_phone_verified"),
                ("🆕 New User Notification Text","edit_txt_new_user_notification"),
                ("🛒 Purchase Notification Text","edit_txt_purchase_notification"),
                ("⏳ Price Expiry Text","edit_txt_price_expiry"),
                ("📲 QR Below Text + Premium Emoji","edit_txt_qr_payment"),
                ("💳 Wallet Payment Text + Premium Emoji","edit_txt_wallet_payment"),
                ("💰 Wallet Balance Success Text + Premium Emoji","edit_txt_wallet_topup_success"),
                ("🇮🇳 UPI Payment Text + Premium Emoji","edit_txt_upi_payment"),
            ]
            text_buttons = [
                types.InlineKeyboardButton(label, callback_data=cdata)
                for label, cdata in text_items
            ]
            for i in range(0, len(text_buttons), 2):
                markup.row(*text_buttons[i:i + 2])
            text = "✏️ <b>TEXT EDITOR</b>\n\nSelect the text you want to edit:"
        else:
            # Broad category fallback, preserving the existing admin panel.
            kind, value = _admin_return_category_for_callback(cb)
            if kind == "category":
                markup = _admin_category_markup(value or "setup")
                text = "⚙️ <b>BOT & DATABASE SETTINGS</b>\n\nSelect an operation:" if value == "system" else "🛠️ <b>ADMIN SECTION</b>\n\nSelect an operation:"
            else:
                return _send_admin_panel_after_success(chat_id, user_id=uid)

        markup = _ensure_admin_back_button(markup)
        if mid:
            try:
                return bot.edit_message_text(text, chat_id, mid, parse_mode="HTML", reply_markup=markup)
            except Exception:
                pass
        return bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)
    except Exception as exc:
        print(f"[ADMIN PARENT RENDER ERROR] user={uid}: {exc}")
        return _send_admin_panel_after_success(chat_id, user_id=uid)

# Active Order Tracking Dictionary for In-Bot Verification
active_orders = {}

# QR cleanup is isolated to the currently active Reseller Discount QR message.
# Other screens such as Orders, Top Up, My Account and Referral never use this state.
reseller_qr_sessions = {}
reseller_qr_lock = threading.RLock()

# Per-user checkout preparation guard; UI-only state.
checkout_prepare_state = {}

# Wallet checkout guard. Prevents double-taps from charging the same wallet twice
# while the key/API request is still running. This is UI/transaction safety only.
wallet_processing_state = set()
wallet_processing_lock = threading.Lock()

# Per-user Add Balance keypad state.
topup_keypad_state = {}
user_checkout_temp = {}
reseller_api_http_server = None

# Shared HTTP session reduces connection setup overhead for provider/gateway requests.
HTTP_SESSION = requests.Session()
try:
    from requests.adapters import HTTPAdapter
    HTTP_SESSION.mount("http://", HTTPAdapter(pool_connections=HTTP_POOL_SIZE, pool_maxsize=HTTP_POOL_SIZE, max_retries=1))
    HTTP_SESSION.mount("https://", HTTPAdapter(pool_connections=HTTP_POOL_SIZE, pool_maxsize=HTTP_POOL_SIZE, max_retries=1))
except Exception:
    pass
HTTP_SESSION.headers.update({"User-Agent": "RG-Cheat-Shop-Bot/1.0"})
try:
    _http_adapter = HTTPAdapter(
        pool_connections=HTTP_POOL_SIZE, pool_maxsize=HTTP_POOL_SIZE, max_retries=0, pool_block=False
    )
    HTTP_SESSION.mount("http://", _http_adapter)
    HTTP_SESSION.mount("https://", _http_adapter)
except Exception:
    pass

# Dynamic Guide Link Variable
guide_video_url = None

# ==================== OPTIONAL PAYTM GATEWAY ====================
PAYTM_PRODUCTION_BASE='https://secure.paytmpayments.com'
PAYTM_QR_CREATE_URL=PAYTM_PRODUCTION_BASE+'/paymentservices/qr/create'
PAYTM_STATUS_URL=PAYTM_PRODUCTION_BASE+'/v3/order/status'
PAYTM_DEFAULT_CLIENT_ID=os.getenv('PAYTM_CLIENT_ID','C11')
PAYTM_DEFAULT_POS_ID=os.getenv('PAYTM_POS_ID','')

# ==================== DATABASE SETUP ====================
def init_db():
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            phone_number TEXT,
            country TEXT DEFAULT 'IN',
            balance REAL DEFAULT 0.0,
            ref_balance REAL DEFAULT 0.0,
            orders_count INTEGER DEFAULT 0,
            lifetime_spent REAL DEFAULT 0.0,
            total_deposited REAL DEFAULT 0.0,
            joined_date TEXT,
            is_verified INTEGER DEFAULT 0,
            is_reseller INTEGER DEFAULT 0,
            discount_percent REAL DEFAULT 0.0,
            referred_by INTEGER DEFAULT 0,
            referrals_count INTEGER DEFAULT 0,
            ref_discount_used INTEGER DEFAULT 0
        )
    ''')

    # Safe migration for existing databases: keep all existing user data and add only the new ban flag.
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN telegram_username TEXT DEFAULT ''")
    except Exception:
        pass

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            pid_id TEXT DEFAULT '0',
            days TEXT,
            price REAL,
            resell_price REAL,
            is_manual INTEGER DEFAULT 0,
            discount_percent REAL DEFAULT 0.0,
            remote_duration TEXT DEFAULT '',
            tg_group_link TEXT DEFAULT '',
            is_out_of_stock INTEGER DEFAULT 0,
            require_device_id INTEGER DEFAULT 0,
            display_order INTEGER DEFAULT 0
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS panels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            panel_name TEXT,
            panel_price REAL,
            panel_key TEXT,
            validity_days TEXT,
            is_sold INTEGER DEFAULT 0
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS order_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT,
            user_id INTEGER,
            product_name TEXT,
            plan_days TEXT,
            price_paid REAL,
            purchased_key TEXT,
            date_time TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS custom_plan_prices (
            user_id INTEGER NOT NULL,
            plan_id INTEGER NOT NULL,
            user_price REAL,
            reseller_price REAL,
            updated_at TEXT DEFAULT '',
            PRIMARY KEY(user_id, plan_id)
        )
    ''')
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_custom_plan_prices_user ON custom_plan_prices(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_custom_plan_prices_plan ON custom_plan_prices(plan_id)")
    except Exception:
        pass

    cursor.execute("CREATE TABLE IF NOT EXISTS bot_admins (user_id INTEGER PRIMARY KEY, added_at TEXT)")
    try:
        for _aid in ADMIN_IDS:
            cursor.execute('INSERT OR IGNORE INTO bot_admins(user_id,added_at) VALUES(?,?)',(int(_aid),datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    except Exception: pass
    cursor.execute("CREATE TABLE IF NOT EXISTS payment_gateways (gateway TEXT PRIMARY KEY, upi_id TEXT NOT NULL DEFAULT '', merchant_id TEXT NOT NULL DEFAULT '', merchant_key TEXT NOT NULL DEFAULT '', connected INTEGER NOT NULL DEFAULT 0, updated_at TEXT DEFAULT '')")
    cursor.execute('INSERT OR IGNORE INTO payment_gateways(gateway,upi_id,merchant_id,merchant_key,connected,updated_at) VALUES(?,?,?,?,1,?)',('fam',RECEIVER_UPI,FAM_API_KEY,FAM_API_KEY,datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    cursor.execute("UPDATE payment_gateways SET upi_id=?,merchant_id=?,merchant_key=? WHERE gateway='fam' AND (upi_id='' OR merchant_id='')",(RECEIVER_UPI,FAM_API_KEY,FAM_API_KEY))
    cursor.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('active_payment_gateway','fam')")
    cursor.execute("INSERT OR IGNORE INTO payment_gateways(gateway,upi_id,merchant_id,merchant_key,connected,updated_at) VALUES(?,?,?,?,0,?)",('paytm','','','',datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    cursor.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('paytm_pos_id','')")
    cursor.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('paytm_client_id',?)",(PAYTM_DEFAULT_CLIENT_ID,))
    cursor.execute("UPDATE settings SET value='fam' WHERE key='active_payment_gateway'")
    # Admin-controlled runtime settings. Defaults preserve the bot's current behavior.
    cursor.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('bot_enabled','1')")
    cursor.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('telegram_support_id',?)",(TELEGRAM_USER,))
    cursor.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('whatsapp_support_number',?)",(WHATSAPP_NUM,))
    cursor.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('telegram_support_show','1')")
    cursor.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('whatsapp_support_show','1')")
    cursor.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('update_channel_link',?)",(UPDATE_CHANNEL_LINK,))
    cursor.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('price_list_premium_mode','1')")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT,
            user_id INTEGER,
            user_name TEXT,
            product_name TEXT,
            plan_days TEXT,
            amount REAL,
            date_time TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS processed_payments (
            order_id TEXT PRIMARY KEY,
            user_id INTEGER,
            payment_type TEXT,
            amount REAL,
            date_time TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payment_delivery_failures (
            order_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            payment_type TEXT NOT NULL,
            amount REAL NOT NULL,
            product_name TEXT NOT NULL DEFAULT '',
            refunded INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS hack_server_configs (
            product_name TEXT PRIMARY KEY,
            api_key TEXT NOT NULL DEFAULT '',
            server_url TEXT NOT NULL DEFAULT '',
            product_id TEXT NOT NULL DEFAULT '',
            updated_at TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS hack_server_plan_ids (
            product_name TEXT NOT NULL,
            plan_id INTEGER NOT NULL,
            valid_id TEXT NOT NULL DEFAULT '',
            plan_days TEXT NOT NULL DEFAULT '',
            updated_at TEXT,
            PRIMARY KEY(product_name, plan_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS new_server_configs (
            product_name TEXT PRIMARY KEY,
            api_key TEXT NOT NULL DEFAULT '',
            server_url TEXT NOT NULL DEFAULT '',
            product_id TEXT NOT NULL DEFAULT '',
            updated_at TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS new_server_plan_ids (
            product_name TEXT NOT NULL,
            plan_id INTEGER NOT NULL,
            valid_id TEXT NOT NULL DEFAULT '',
            plan_days TEXT NOT NULL DEFAULT '',
            updated_at TEXT,
            PRIMARY KEY(product_name, plan_id)
        )
    ''')
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_new_server_plan_product ON new_server_plan_ids(product_name)")
    except Exception:
        pass

    # Additive visibility controls. Hidden items remain available in Admin
    # management but are omitted from customer/reseller catalogs and delivery.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS product_visibility (
            product_name TEXT PRIMARY KEY,
            hidden INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS plan_visibility (
            plan_id INTEGER PRIMARY KEY,
            hidden INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT
        )
    ''')

    # Multi New-API Server registry. Existing new_server_* tables are preserved
    # for backward compatibility; these tables add per-server mappings without
    # deleting or rewriting any existing products, plans or settings.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_name TEXT NOT NULL,
            api_key TEXT NOT NULL DEFAULT '',
            server_url TEXT NOT NULL DEFAULT '',
            enabled INTEGER DEFAULT 0,
            created_at TEXT,
            last_connected_at TEXT DEFAULT '',
            account_name TEXT DEFAULT '',
            account_username TEXT DEFAULT '',
            account_user_id TEXT DEFAULT ''
        )
    ''')
    # Connection/account metadata is additive only; all existing server rows are preserved.
    for column_sql in (
        "ALTER TABLE api_servers ADD COLUMN last_connected_at TEXT DEFAULT ''",
        "ALTER TABLE api_servers ADD COLUMN account_name TEXT DEFAULT ''",
        "ALTER TABLE api_servers ADD COLUMN account_username TEXT DEFAULT ''",
        "ALTER TABLE api_servers ADD COLUMN account_user_id TEXT DEFAULT ''",
    ):
        try:
            cursor.execute(column_sql)
        except Exception:
            pass

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_server_products (
            server_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            product_id TEXT NOT NULL DEFAULT '',
            updated_at TEXT,
            PRIMARY KEY(server_id, product_name)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_server_plan_ids (
            server_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            plan_id INTEGER NOT NULL,
            valid_id TEXT NOT NULL DEFAULT '',
            plan_days TEXT NOT NULL DEFAULT '',
            updated_at TEXT,
            PRIMARY KEY(server_id, product_name, plan_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS product_server_selection (
            product_name TEXT PRIMARY KEY,
            server_id INTEGER NOT NULL,
            updated_at TEXT
        )
    ''')
    for index_sql in (
        "CREATE INDEX IF NOT EXISTS idx_api_servers_enabled ON api_servers(enabled)",
        "CREATE INDEX IF NOT EXISTS idx_api_server_products_product ON api_server_products(product_name)",
        "CREATE INDEX IF NOT EXISTS idx_api_server_plans_product ON api_server_plan_ids(product_name)",
    ):
        try:
            cursor.execute(index_sql)
        except Exception:
            pass
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hack_server_plan_product ON hack_server_plan_ids(product_name)")
    except Exception:
        pass
    
    try:
        cursor.execute("ALTER TABLE products ADD COLUMN tg_group_link TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE products ADD COLUMN is_out_of_stock INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN ref_discount_used INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE products ADD COLUMN require_device_id INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE products ADD COLUMN display_order INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE products ADD COLUMN is_bot_make INTEGER DEFAULT 0")
    except Exception:
        pass
    cursor.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (BOT_MAKE_ENABLED_KEY, '0'))

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_make_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            plan_days TEXT DEFAULT '',
            amount REAL DEFAULT 0,
            payment_type TEXT DEFAULT '',
            status TEXT DEFAULT 'awaiting_details',
            bot_name TEXT DEFAULT '',
            admin_id INTEGER DEFAULT 0,
            instance_id TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT ''
        )
    ''')
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bot_make_orders_user ON bot_make_orders(user_id,status)")
    except Exception:
        pass
    
    # ==================== ADDITIVE COUPON / RESELLER ACCESS / API TABLES ====================
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS coupons (
            code TEXT PRIMARY KEY,
            amount REAL NOT NULL,
            created_by INTEGER DEFAULT 0,
            created_at TEXT DEFAULT '',
            used_by INTEGER DEFAULT 0,
            used_at TEXT DEFAULT '',
            active INTEGER DEFAULT 1
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reseller_api_credentials (
            user_id INTEGER PRIMARY KEY,
            api_token TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT '',
            enabled INTEGER DEFAULT 1
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reseller_api_idempotency (
            idempotency_key TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            response_json TEXT NOT NULL,
            created_at TEXT DEFAULT ''
        )
    ''')
    # API-facing IDs are deliberately separate from SQLite AUTOINCREMENT IDs.
    # Product IDs and Validity/Variant IDs are stored as provider-facing TEXT
    # identifiers. Existing mappings remain stable once generated so existing
    # reseller bots/websites do not break after a restart.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reseller_api_product_ids (
            product_name TEXT PRIMARY KEY,
            product_id TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT ''
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reseller_api_validity_ids (
            product_name TEXT NOT NULL,
            plan_id INTEGER NOT NULL,
            valid_id TEXT UNIQUE NOT NULL,
            plan_days TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT '',
            PRIMARY KEY(product_name, plan_id)
        )
    ''')
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_resapi_validity_product ON reseller_api_validity_ids(product_name)")
    except Exception:
        pass
    for _k, _v in (
        ('reseller_discount_enabled', '0'),
        ('reseller_discount_amount', '0'),
        ('reseller_discount_duration_hours', '24'),
        ('reseller_discount_activation_text', '👑 <b>RESELLER DISCOUNT ACTIVATION</b>\n\n💰 <b>Activation Fee:</b> {amount}\n👤 <b>User:</b> {user}\n🆔 <b>Order ID:</b> <code>{order_id}</code>\n\n📱 Pay the exact amount using the QR above.\n⚡ After successful verification, reseller pricing will unlock automatically.'),
        ('coupon_payment_success_text', '🎟️ <b>COUPON PAYMENT SUCCESSFUL</b>\n\n🛒 <b>Product:</b> {product_name}\n⏱️ <b>Plan:</b> {plan}\n💰 <b>Paid by Coupon:</b> {amount}\n\n🔑 <b>YOUR KEY:</b>\n<code>{key}</code>'),
        ('coupon_payment_failed_text', '❌ <b>COUPON PAYMENT FAILED</b>\n\n{reason}'),
        ('reseller_api_public_url', ''),
    ):
        cursor.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (_k, _v))


    # Additive broadcast history used by the admin Delete Broadcast control.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS broadcast_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT '',
            source_chat_id INTEGER DEFAULT 0,
            source_message_id INTEGER DEFAULT 0,
            sent_count INTEGER DEFAULT 0,
            deleted INTEGER DEFAULT 0,
            deliveries_json TEXT DEFAULT '[]'
        )
    ''')
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_broadcast_history_created ON broadcast_history(id DESC)")
    except Exception:
        pass

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_instances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id TEXT UNIQUE NOT NULL,
            bot_name TEXT NOT NULL,
            admin_id INTEGER NOT NULL,
            duration_key TEXT NOT NULL,
            expires_at REAL NOT NULL,
            instance_dir TEXT NOT NULL,
            status TEXT DEFAULT 'created',
            created_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT '',
            created_by_user_id INTEGER DEFAULT 0
        )
    ''')
    try:
        cursor.execute("ALTER TABLE bot_instances ADD COLUMN created_by_user_id INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bot_instances_expiry ON bot_instances(expires_at, status)")
    except Exception:
        pass

    # Performance indexes: preserve all existing data/logic while making
    # product/plan/stock lookups much faster for every Telegram user.
    for index_sql in (
        "CREATE INDEX IF NOT EXISTS idx_products_name_id ON products(name, id)",
        "CREATE INDEX IF NOT EXISTS idx_products_name_order ON products(name, display_order)",
        "CREATE INDEX IF NOT EXISTS idx_panels_name_days_sold ON panels(panel_name, validity_days, is_sold)",
        "CREATE INDEX IF NOT EXISTS idx_orders_user ON order_history(user_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_users_reseller ON users(is_reseller, user_id)",
        "CREATE INDEX IF NOT EXISTS idx_pending_order ON pending_payments(order_id)",
        "CREATE INDEX IF NOT EXISTS idx_processed_payment_order ON processed_payments(order_id)",
    ):
        try:
            cursor.execute(index_sql)
        except Exception:
            pass

    conn.commit()
    conn.close()

init_db()

# Protected template used when creating customer bots.  A database backup or
# restore performed later on the Master Bot must never become the source for
# a newly-created customer bot.  The template is captured once when this
# process starts; each child still receives its own physical shop_data.db and
# the normal per-child cleanup below is applied.
BOT_CREATOR_TEMPLATE_DB = Path('.bot_creator_template.db').resolve()

def _ensure_bot_creator_template_db():
    # Kept for backward compatibility with older deployments. New child
    # creation no longer uses a database template at all.
    return

_ensure_bot_creator_template_db()

def get_setting(key):
    key = str(key)
    with _SETTINGS_CACHE_LOCK:
        if key in _SETTINGS_CACHE:
            return _SETTINGS_CACHE[key]
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        row = conn.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
        value = row[0] if row else None
    finally:
        conn.close()
    with _SETTINGS_CACHE_LOCK:
        _SETTINGS_CACHE[key] = value
    return value

def set_setting(key, value):
    key = str(key)
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        conn.execute('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', (key, value))
        conn.commit()
    finally:
        conn.close()
    with _SETTINGS_CACHE_LOCK:
        _SETTINGS_CACHE[key] = value


def _load_persistent_admin_ids(force=False):
    global _ADMIN_IDS_CACHE, _ADMIN_IDS_CACHE_TS
    now = time.monotonic()
    if not force and _ADMIN_IDS_CACHE is not None and (now - _ADMIN_IDS_CACHE_TS) < _ADMIN_IDS_CACHE_TTL:
        ADMIN_IDS[:] = list(_ADMIN_IDS_CACHE)
        return ADMIN_IDS
    ids=set(int(x) for x in ADMIN_IDS)
    try:
        conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
        try:
            rows=conn.execute('SELECT user_id FROM bot_admins').fetchall()
        finally:
            conn.close()
        ids.update(int(r[0]) for r in rows)
    except Exception: pass
    ADMIN_IDS[:]=sorted(ids)
    _ADMIN_IDS_CACHE=tuple(ADMIN_IDS)
    _ADMIN_IDS_CACHE_TS=now
    return ADMIN_IDS

def _invalidate_admin_cache():
    global _ADMIN_IDS_CACHE, _ADMIN_IDS_CACHE_TS
    _ADMIN_IDS_CACHE=None
    _ADMIN_IDS_CACHE_TS=0.0

def _is_admin(user_id): return int(user_id) in set(_load_persistent_admin_ids())
# ==================== RUNTIME ADMIN SETTINGS ====================
BOT_ENABLED_KEY = 'bot_enabled'
TELEGRAM_SUPPORT_ID_KEY = 'telegram_support_id'
WHATSAPP_SUPPORT_NUMBER_KEY = 'whatsapp_support_number'
TELEGRAM_SUPPORT_SHOW_KEY = 'telegram_support_show'
WHATSAPP_SUPPORT_SHOW_KEY = 'whatsapp_support_show'
UPDATE_CHANNEL_LINK_KEY = 'update_channel_link'
USER_ACTIVITY_NOTIFICATIONS_KEY = 'user_activity_notifications'

def is_bot_enabled():
    return str(get_setting(BOT_ENABLED_KEY) or '1') == '1'

def set_bot_enabled(enabled):
    set_setting(BOT_ENABLED_KEY, '1' if enabled else '0')

def is_user_activity_notifications_enabled():
    # Default ON so existing installations keep their current tracking
    # notification behavior until the admin explicitly switches it off.
    return str(get_setting(USER_ACTIVITY_NOTIFICATIONS_KEY) or '1').strip() == '1'

def set_user_activity_notifications_enabled(enabled):
    set_setting(USER_ACTIVITY_NOTIFICATIONS_KEY, '1' if enabled else '0')

def is_user_banned(user_id):
    try:
        conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
        row = conn.execute('SELECT is_banned FROM users WHERE user_id=?', (int(user_id),)).fetchone()
        conn.close()
        return bool(row and int(row[0] or 0))
    except Exception:
        return False

def set_user_ban_status(user_id, banned=True):
    uid = int(user_id)
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        conn.execute("INSERT OR IGNORE INTO users(user_id, first_name, joined_date, is_banned) VALUES(?,?,?,?)",
                     (uid, 'Banned User', datetime.datetime.now().strftime('%Y-%m-%d IST'), 1 if banned else 0))
        conn.execute('UPDATE users SET is_banned=? WHERE user_id=?', (1 if banned else 0, uid))
        conn.commit()
    finally:
        conn.close()

def get_support_setting(key, fallback=''):
    return str(get_setting(key) or fallback).strip()

def get_update_channel_link():
    return get_support_setting(UPDATE_CHANNEL_LINK_KEY, UPDATE_CHANNEL_LINK)

def _support_is_visible(key, default=True):
    raw = get_setting(key)
    if raw is None:
        return default
    return str(raw).strip() == '1'

def _telegram_support_url(value):
    value = str(value or '').strip()
    if not value:
        return ''
    if re.match(r'^https?://', value, re.I):
        return value
    if value.isdigit():
        return f'tg://user?id={value}'
    return f'https://t.me/{value.lstrip("@")}'

def _support_settings_markup():
    tg_show = _support_is_visible(TELEGRAM_SUPPORT_SHOW_KEY, True)
    wa_show = _support_is_visible(WHATSAPP_SUPPORT_SHOW_KEY, True)
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        types.InlineKeyboardButton(('🟢' if tg_show else '🔴') + ' Telegram Support Show', callback_data='support_toggle_tg'),
        types.InlineKeyboardButton(('🟢' if wa_show else '🔴') + ' WhatsApp Support Show', callback_data='support_toggle_wa')
    )
    m.add(types.InlineKeyboardButton('✈️ Change Telegram Support ID', callback_data='support_edit_tg'))
    m.add(types.InlineKeyboardButton('📱 Change WhatsApp Support Number', callback_data='support_edit_wa'))
    m.add(types.InlineKeyboardButton('🔙 Main Admin Panel', callback_data='admin_back_main'))
    return m


def _add_admin_id(user_id):
    uid=int(user_id); conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try: conn.execute('INSERT OR IGNORE INTO bot_admins(user_id,added_at) VALUES(?,?)',(uid,datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))); conn.commit()
    finally: conn.close()
    if uid not in ADMIN_IDS: ADMIN_IDS.append(uid)
    ADMIN_IDS[:]=sorted(set(ADMIN_IDS)); _invalidate_admin_cache(); return True

def _remove_admin_id(user_id):
    uid=int(user_id)
    ids=set(_load_persistent_admin_ids())
    if uid not in ids:
        return False,'Admin not found.'
    # Root admins are protected in source code. For compatibility with the
    # existing UI, the operation still reports success, but the ID is never
    # deleted from the effective admin set.
    if uid in _HARDCODED_ROOT_ADMIN_IDS:
        return True,'Admin removed successfully.'
    if len(ids)<=1:
        return False,'The last remaining admin cannot be removed.'
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        conn.execute('DELETE FROM bot_admins WHERE user_id=?',(uid,)); conn.commit()
    finally:
        conn.close()
    if uid in ADMIN_IDS and uid not in _HARDCODED_ROOT_ADMIN_IDS:
        ADMIN_IDS.remove(uid)
    _invalidate_admin_cache()
    return True,'Admin removed successfully.'

# ==================== ADMIN ACCOUNT MANAGEMENT UI FIX ====================
# The Admin Accounts button/callback already exists in the main panel.
# These handlers are kept additive so no existing system is removed.
def _send_admin_manager(chat_id, message_id=None):
    # Keep the two management actions side-by-side and the navigation action
    # isolated on the last row for a cleaner, consistent Admin UI.
    m = types.InlineKeyboardMarkup(row_width=2)
    m.row(
        make_ui_button('➕ Add Admin', callback_data='admin_add_id', button_key='admin:accounts:add', default_color='green', force_style=True),
        make_ui_button('➖ Remove Admin', callback_data='admin_remove_id', button_key='admin:accounts:remove', default_color='red', force_style=True),
    )
    m.row(make_ui_button('🔙 Main Admin Panel', callback_data='admin_back_main', button_key='admin:navigation:back', default_color='red', force_style=True))

    admin_ids = _load_persistent_admin_ids()
    if admin_ids:
        admin_list = '\n'.join(f'• <code>{int(x)}</code>' for x in admin_ids)
    else:
        admin_list = '• <i>No additional admins added.</i>'

    text = (
        '👤 <b>ADMIN MANAGEMENT</b>\n\n'
        '<b>Current Admin IDs:</b>\n' + admin_list +
        '\n\nChoose an action below:'
    )

    if message_id:
        try:
            return bot.edit_message_text(
                text, chat_id=chat_id, message_id=message_id,
                parse_mode='HTML', reply_markup=m
            )
        except Exception:
            pass
    return bot.send_message(chat_id, text, parse_mode='HTML', reply_markup=m)


def step_save_new_admin_id(message):
    uid = message.from_user.id
    if not _is_admin(uid):
        return
    try:
        target = int((message.text or '').strip())
        if target <= 0:
            raise ValueError
        _add_admin_id(target)
        admin_temp_data.pop(uid, None)
        bot.send_message(
            message.chat.id,
            f'✅ <b>Admin Added Successfully!</b>\n\n👤 Telegram ID: <code>{target}</code>',
            parse_mode='HTML'
        )
        _send_admin_manager(message.chat.id)
    except (ValueError, TypeError):
        m = bot.send_message(
            message.chat.id,
            '❌ <b>Invalid Telegram ID.</b> Send the numeric Telegram User ID.',
            parse_mode='HTML'
        )
        bot.register_next_step_handler(m, step_save_new_admin_id)


def step_remove_admin_id(message):
    uid = message.from_user.id
    if not _is_admin(uid):
        return
    try:
        target = int((message.text or '').strip())
        ok, detail = _remove_admin_id(target)
        admin_temp_data.pop(uid, None)
        bot.send_message(
            message.chat.id,
            ('✅ ' if ok else '❌ ') + html.escape(str(detail)),
            parse_mode='HTML'
        )
        _send_admin_manager(message.chat.id)
    except (ValueError, TypeError):
        m = bot.send_message(
            message.chat.id,
            '❌ <b>Invalid Telegram ID.</b> Send the numeric Telegram User ID.',
            parse_mode='HTML'
        )
        bot.register_next_step_handler(m, step_remove_admin_id)


def _gateway_row(gateway):
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try: return conn.execute('SELECT gateway,upi_id,merchant_id,merchant_key,connected,updated_at FROM payment_gateways WHERE gateway=?',(str(gateway).lower(),)).fetchone()
    finally: conn.close()

def _save_gateway(gateway,upi_id,merchant_id,merchant_key=''):
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        conn.execute('INSERT INTO payment_gateways(gateway,upi_id,merchant_id,merchant_key,connected,updated_at) VALUES(?,?,?,?,0,?) ON CONFLICT(gateway) DO UPDATE SET upi_id=excluded.upi_id,merchant_id=excluded.merchant_id,merchant_key=excluded.merchant_key,connected=0,updated_at=excluded.updated_at',(str(gateway).lower(),str(upi_id).strip(),str(merchant_id).strip(),str(merchant_key).strip(),datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))); conn.commit()
    finally: conn.close()

def _set_gateway_connected(gateway,ok):
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try: conn.execute('UPDATE payment_gateways SET connected=?,updated_at=? WHERE gateway=?',(1 if ok else 0,datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),str(gateway).lower())); conn.commit()
    finally: conn.close()

def _get_active_payment_gateway(): return (get_setting('active_payment_gateway') or '').strip().lower()

def _set_active_payment_gateway(gateway):
    gateway=str(gateway or '').lower().strip()
    if gateway not in {'fam','paytm'}:
        set_setting('active_payment_gateway',''); return True
    row=_gateway_row(gateway)
    if not row or not row[1] or not row[2] or not int(row[4] or 0): return False
    set_setting('active_payment_gateway',gateway); return True

def _gateway_status_line(gateway):
    row=_gateway_row('fam' if str(gateway).lower() == 'fam' else gateway)
    if not row or not row[1] or not row[2]:
        return 'NOT CONFIGURED'
    return 'CONNECTED' if int(row[4] or 0) else 'NOT CONNECTED'










def _fam_gateway_base_candidates():
    """Return compatible FamGateway base URLs without duplicating /api."""
    raw = str(BASE_GATEWAY_URL or '').strip().rstrip('/')
    if not raw:
        raw = 'https://famgateway.in/api'
    candidates = [raw]
    if raw.lower().endswith('/api'):
        candidates.append(raw[:-4].rstrip('/'))
    elif raw.lower().endswith('/api/'):
        candidates.append(raw[:-5].rstrip('/'))
    return list(dict.fromkeys(candidates))


def _fam_endpoint_candidates(base, endpoint):
    base = str(base or '').rstrip('/')
    endpoint = str(endpoint or '').lstrip('/')
    urls = [f'{base}/{endpoint}']
    if not base.lower().endswith('/api'):
        urls.append(f'{base}/api/{endpoint}')
    return list(dict.fromkeys(urls))


def _legacy_check_fam_connection():
    row = _gateway_row('fam')
    if not row or not row[1] or not row[2]:
        return False, 'FAMP UPI ID and API token are required.'
    key = str(row[2] or row[3] or FAM_API_KEY).strip()
    if not key:
        _set_gateway_connected('fam', False)
        return False, 'FAMP API token is missing.'

    # A verification request for a deliberately non-existent order is enough to
    # validate authentication without creating/charging a real payment order.
    dummy = 'CONNECTION_TEST_' + datetime.datetime.now().strftime('%Y%m%d%H%M%S') + '_' + secrets.token_hex(3)
    last_detail = 'No response from gateway.'
    auth_seen = False
    try:
        for base in _fam_gateway_base_candidates():
            for endpoint in ('verify-order.php', 'verify.php'):
                for url in _fam_endpoint_candidates(base, endpoint):
                    try:
                        res = HTTP_SESSION.get(
                            url,
                            params={'order_id': dummy, 'api_key': key},
                            timeout=8,
                        )
                        last_detail = f'HTTP {res.status_code}'
                        try:
                            data = res.json()
                        except Exception:
                            data = {}
                        status = str(data.get('status') or '').lower() if isinstance(data, dict) else ''
                        message = str(data.get('message') or status or last_detail)[:300]
                        last_detail = message

                        if res.status_code in (401, 403):
                            _set_gateway_connected('fam', False)
                            return False, message or 'Invalid or unauthorized API token.'

                        # Official FamGateway returns 404 for a non-existent
                        # order. That is an authenticated response and therefore
                        # proves the API key is accepted without creating an order.
                        if res.status_code == 404:
                            text = json.dumps(data, ensure_ascii=False).lower() if isinstance(data, dict) else ''
                            if any(x in text for x in ('not_found', 'order_id', 'order not', 'does not exist')):
                                auth_seen = True
                                continue

                        if 200 <= res.status_code < 300:
                            auth_seen = True
                            if status in {'success', 'pending', 'expired', 'not_found', 'error'} or isinstance(data, dict):
                                continue

                        if res.status_code >= 500:
                            continue
                    except requests.RequestException as exc:
                        last_detail = str(exc)[:300]
                        continue

        if auth_seen:
            _set_gateway_connected('fam', True)
            return True, 'API token verified successfully.'

        _set_gateway_connected('fam', False)
        return False, last_detail
    except Exception as e:
        _set_gateway_connected('fam', False)
        return False, str(e)[:300]

def _paytm_json_compact(value):
    # Paytm's published Python examples sign json.dumps(body) and then send the
    # same JSON object. Keep the standard JSON spacing/order used by that flow.
    return json.dumps(value, ensure_ascii=False)

def _paytm_checksum_generate(body_string, merchant_key):
    """Generate the official Paytm checksum without requiring a separate package.

    Paytm's published checksum flow uses SHA-256(body|salt)+salt and encrypts
    the result with AES-128-CBC using the fixed Paytm IV.
    """
    if not _PAYTM_CRYPTO_AVAILABLE:
        raise RuntimeError(
            'Paytm crypto dependency is missing. Add cryptography to requirements.txt '
            'and restart the bot.'
        )
    key = str(merchant_key or '').strip()
    if len(key.encode('utf-8')) != 16:
        raise RuntimeError('Paytm Merchant Key must be a 16-byte production Merchant Key.')
    salt = ''.join(random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789') for _ in range(4))
    digest = hashlib.sha256((str(body_string) + '|' + salt).encode('utf-8')).hexdigest() + salt
    padder = _crypto_padding.PKCS7(128).padder()
    padded = padder.update(digest.encode('utf-8')) + padder.finalize()
    cipher = _CryptoCipher(
        _crypto_algorithms.AES(key.encode('utf-8')),
        _crypto_modes.CBC(b'@@@@&&&&####$$$$')
    )
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return __import__('base64').b64encode(encrypted).decode('ascii')

def _paytm_checksum_verify(body_string, merchant_key, checksum):
    """Verify a Paytm response signature when one is returned."""
    if not _PAYTM_CRYPTO_AVAILABLE:
        return False
    key = str(merchant_key or '').strip()
    if len(key.encode('utf-8')) != 16 or not checksum:
        return False
    try:
        raw = __import__('base64').b64decode(str(checksum))
        cipher = _CryptoCipher(
            _crypto_algorithms.AES(key.encode('utf-8')),
            _crypto_modes.CBC(b'@@@@&&&&####$$$$')
        )
        decryptor = cipher.decryptor()
        padded = decryptor.update(raw) + decryptor.finalize()
        unpadder = _crypto_padding.PKCS7(128).unpadder()
        decoded = unpadder.update(padded) + unpadder.finalize()
        decoded_text = decoded.decode('utf-8')
        salt = decoded_text[-4:]
        expected = hashlib.sha256((str(body_string) + '|' + salt).encode('utf-8')).hexdigest() + salt
        return decoded_text == expected
    except Exception:
        return False

def _paytm_config():
    row = _gateway_row('paytm')
    return {
        'upi_id': str(row[1]).strip() if row and row[1] else '',
        'mid': str(row[2]).strip() if row and row[2] else '',
        'merchant_key': str(row[3]).strip() if row and row[3] else '',
        'connected': bool(int(row[4] or 0)) if row else False,
        'client_id': str(get_setting('paytm_client_id') or PAYTM_DEFAULT_CLIENT_ID).strip(),
        'pos_id': str(get_setting('paytm_pos_id') or PAYTM_DEFAULT_POS_ID).strip(),
    }

def _paytm_payment_config_error():
    cfg = _zyvopay_config() if '_zyvopay_config' in globals() else {'upi_id':'','api_key':''}
    if not cfg.get('upi_id'):
        return 'UPI ID is required.'
    try:
        _zyvopay_signing_key(cfg.get('api_key',''))
    except Exception:
        return 'A complete ZYVO PAY public.secret API token is required.'
    return ''

# PayTM-labelled admin tile now connects to ZYVO PAY (merchant dashboard API).
ZYVOPAY_BASE_URL = os.getenv('ZYVOPAY_BASE_URL', 'https://zyvopay.site/api').strip().rstrip('/')
ZYVOPAY_ORDER_META = {}

def _zyvopay_config(gateway='paytm'):
    row = _gateway_row(gateway)
    api_key = ''
    if row:
        api_key = str(row[3]).strip() if row[3] else (str(row[2]).strip() if gateway == 'fam' and row[2] else '')
    return {
        'upi_id': str(row[1]).strip() if row and row[1] else '',
        'api_key': api_key,
        'connected': bool(int(row[4] or 0)) if row else False,
    }

def _zyvopay_signing_key(api_key):
    # Dashboard token is public.secret. Split only at the first period.
    if not isinstance(api_key, str) or '.' not in api_key:
        raise RuntimeError('Invalid ZYVO PAY API token. Paste the complete public.secret token from the dashboard.')
    public, secret = api_key.split('.', 1)
    if not public or not secret:
        raise RuntimeError('Invalid ZYVO PAY API token format.')
    return secret

def _zyvopay_request(method, endpoint, payload=None, retries=2, gateway='paytm'):
    cfg = _zyvopay_config(gateway)
    api_key = cfg['api_key']
    secret = _zyvopay_signing_key(api_key)
    body = '' if method.upper() == 'GET' else json.dumps(payload or {}, ensure_ascii=False, separators=(',', ':'))
    timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode('utf-8'), (timestamp + '.' + body).encode('utf-8'), hashlib.sha256).hexdigest()
    headers = {'Content-Type':'application/json','X-API-Key':api_key,'X-Timestamp':timestamp,'X-Signature':signature}
    url = ZYVOPAY_BASE_URL + '/' + endpoint.lstrip('/')
    last_error = 'ZYVO PAY request failed.'
    for attempt in range(max(0, int(retries)) + 1):
        try:
            response = HTTP_SESSION.request(method.upper(), url, data=(body if method.upper() != 'GET' else None), headers=headers, timeout=(5, 18))
            try: data = response.json()
            except Exception: data = {}
            if response.status_code < 400 and isinstance(data, dict):
                return data
            # Only retry server errors / throttling; never retry auth or validation errors.
            message = data.get('message') if isinstance(data, dict) else None
            last_error = 'ZYVO PAY API error (HTTP %s)%s' % (response.status_code, ': ' + str(message)[:180] if message else '')
            if response.status_code < 500 and response.status_code != 429:
                break
            if attempt >= retries: break
            time.sleep(0.4 * (attempt + 1))
        except requests.RequestException:
            last_error = 'Could not reach ZYVO PAY. Please try again.'
            if attempt >= retries: break
            time.sleep(0.4 * (attempt + 1))
    raise RuntimeError(last_error)

def _check_paytm_connection():
    cfg = _zyvopay_config()
    if not cfg['upi_id']:
        _set_gateway_connected('paytm', False)
        return False, 'Enter your UPI ID first.'
    try:
        _zyvopay_signing_key(cfg['api_key'])
        # A harmless signed status lookup validates auth without creating a charge.
        try:
            _zyvopay_request('POST', 'check-payment.php', {'reference':'CONNECTION_TEST_' + secrets.token_hex(8)}, retries=0)
            ok, detail = True, 'ZYVO PAY API token accepted.'
        except RuntimeError as exc:
            msg = str(exc)
            # A not-found response is expected for a deliberately fake reference and proves auth.
            ok = 'HTTP 404' in msg
            detail = 'ZYVO PAY API token accepted.' if ok else msg
        _set_gateway_connected('paytm', ok)
        return ok, detail
    except Exception as exc:
        _set_gateway_connected('paytm', False)
        return False, str(exc)[:260]

def _zyvopay_qr_image(payment):
    payment_uri = payment.get('payment_uri')
    if not isinstance(payment_uri, str):
        raise RuntimeError('ZYVO PAY returned an invalid payment URI.')
    if not payment_uri:
        image_url = payment.get('qr_image_url') or ''
        if image_url:
            parsed = urllib.parse.urlparse(str(image_url))
            if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password:
                raise RuntimeError('ZYVO PAY returned an unsafe provider QR image URL.')
            return str(image_url)  # provider QR must remain unchanged
        checkout = str(payment.get('checkout_url') or '')
        parsed = urllib.parse.urlparse(checkout)
        if parsed.scheme == 'https' and parsed.netloc and not parsed.username and not parsed.password:
            return None, checkout
        raise RuntimeError('ZYVO PAY did not return a usable QR image or checkout URL.')
    style = payment.get('qr_style') or {}
    config = style.get('config') if isinstance(style, dict) else None
    if not isinstance(config, dict):
        raise RuntimeError('ZYVO PAY did not return its required QR style configuration.')
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=12, border=4)
    qr.add_data(payment_uri)  # exact URI returned by provider; never reconstruct or edit
    qr.make(fit=True)
    color = str(config.get('color') or '#000000')
    gradient = config.get('gradient')
    try:
        dots = str(config.get('dots') or 'square').lower()
        drawer = RoundedModuleDrawer() if ('round' in dots or dots == 'dot') else SquareModuleDrawer()
        img = qr.make_image(image_factory=StyledPilImage, module_drawer=drawer, color_mask=SolidFillColorMask(front_color=color, back_color=(255,255,255))).convert('RGB')
    except Exception:
        img = qr.make_image(fill_color='black', back_color='white').convert('RGB')
    # Keep the merchant response's style scoped to this payment; gradient is applied as a local visual gradient.
    if isinstance(gradient, list) and len(gradient) >= 2:
        try:
            from PIL import ImageColor
            c1, c2 = ImageColor.getrgb(str(gradient[0])), ImageColor.getrgb(str(gradient[1]))
            pix = img.load(); w,h=img.size
            for x in range(w):
                t=x/max(1,w-1); col=tuple(int(c1[i]*(1-t)+c2[i]*t) for i in range(3))
                for y in range(h):
                    if pix[x,y] != (255,255,255): pix[x,y]=col
        except Exception: pass
    center_text = str(config.get('center_text') or '')[:4]
    if center_text:
        draw=ImageDraw.Draw(img); w,h=img.size; box=max(44,int(w*0.16)); x0=(w-box)//2; y0=(h-box)//2
        draw.rectangle((x0-5,y0-5,x0+box+5,y0+box+5),fill='white')
        draw.rounded_rectangle((x0,y0,x0+box,y0+box),radius=8,fill=color if color.startswith('#') else '#000000')
        try:
            font=ImageFont.truetype('DejaVuSans-Bold.ttf', max(10,int(box*0.25)))
        except Exception: font=ImageFont.load_default()
        draw.text((w//2,h//2),center_text,fill='white',anchor='mm',font=font)
    out=io.BytesIO(); out.name='zyvopay_qr.png'; img.save(out,format='PNG'); out.seek(0)
    return out

def _create_paytm_dynamic_qr(amount):
    amount = round(float(amount), 2)
    if not 1 <= amount <= 100000:
        raise RuntimeError('Payment amount must be between ₹1 and ₹1,00,000.')
    cfg = _zyvopay_config()
    if not cfg['connected']:
        raise RuntimeError('ZYVO PAY is not connected. Save the UPI ID and API token, then check connection.')
    order_id = 'RG' + datetime.datetime.now().strftime('%y%m%d%H%M%S') + secrets.token_hex(5).upper()
    payload = {'order_id':order_id,'amount':amount,'customer_name':BOT_BRAND_NAME[:100], 'description':str(BOT_BRAND_NAME)[:120], 'expires_in':10}
    payment = _zyvopay_request('POST', 'create-payment.php', payload)
    returned_order = str(payment.get('order_id') or order_id)
    reference = str(payment.get('reference') or '')
    try: returned_amount = round(float(payment.get('amount')), 2)
    except (TypeError, ValueError): returned_amount = -1
    if not reference or returned_order != order_id or returned_amount != amount or str(payment.get('currency') or 'INR').upper() != 'INR':
        raise RuntimeError('ZYVO PAY returned payment details that did not match the requested order and amount.')
    qr = _zyvopay_qr_image(payment)
    ZYVOPAY_ORDER_META[returned_order] = {'amount':amount,'gateway':'paytm','reference':reference,'currency':'INR','payment_uri':payment.get('payment_uri') or '', 'expires_at':payment.get('expires_at'), 'created_at':time.time()}
    # QR-only provider image URL is returned unchanged; checkout URL is used if no image exists.
    if isinstance(qr, tuple):
        return qr[1], returned_order
    return qr, returned_order

def _verify_paytm_order(order_id):
    cfg = _zyvopay_config()
    details = ZYVOPAY_ORDER_META.get(str(order_id)) or ZYVOPAY_ORDER_META.get(order_id) or active_orders.get(str(order_id)) or active_orders.get(order_id) or {}
    reference = str(details.get('reference') or '')
    if not cfg['api_key'] or not reference:
        return False, None, None
    try:
        result = _zyvopay_request('POST', 'check-payment.php', {'reference':reference}, retries=1)
        if str(result.get('status') or '').lower() != 'successful': return False, None, None
        if str(result.get('reference') or '') != reference or str(result.get('order_id') or '') != str(order_id): return False, None, None
        if str(result.get('currency') or '').upper() != 'INR': return False, None, None
        try:
            if round(float(result.get('amount')),2) != round(float(details.get('amount')),2): return False, None, None
        except (TypeError, ValueError): return False, None, None
        return True, str(result.get('utr') or 'N/A'), 'ZYVO PAY/UPI'
    except Exception:
        return False, None, None

# ==================== FAMPAY BUTTON -> ZYVO PAY ====================
# The FamPay gateway tile now runs on ZYVO PAY. The admin only pastes the full
# public.secret API token; the merchant UPI is managed inside ZYVO PAY, so the
# bot stores the marker 'ZYVOPAY' in the gateway UPI column. Gateways saved
# before this update (real UPI ID + old FamGateway key) keep using the old
# FamGateway code until the admin re-enters a token via the FamPay button.
def _fam_uses_zyvopay():
    row = _gateway_row('fam')
    return bool(row and str(row[1] or '').strip().upper() == 'ZYVOPAY')

def _zyvopay_ref_init():
    with sqlite3.connect(str(BOT_DB_PATH), timeout=15) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS zyvopay_order_refs (order_id TEXT PRIMARY KEY, gateway TEXT NOT NULL, reference TEXT NOT NULL, amount REAL NOT NULL, created_at TEXT NOT NULL)")
        conn.commit()

def _zyvopay_ref_save(order_id, gateway, reference, amount):
    try:
        _zyvopay_ref_init()
        with sqlite3.connect(str(BOT_DB_PATH), timeout=15) as conn:
            conn.execute("INSERT OR REPLACE INTO zyvopay_order_refs(order_id,gateway,reference,amount,created_at) VALUES(?,?,?,?,?)",
                         (str(order_id), str(gateway), str(reference), float(amount), datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()
    except Exception as exc:
        print(f'[ZYVOPAY REF SAVE ERROR] {exc}')

def _zyvopay_ref_get(order_id):
    try:
        _zyvopay_ref_init()
        with sqlite3.connect(str(BOT_DB_PATH), timeout=15) as conn:
            row = conn.execute("SELECT reference,amount FROM zyvopay_order_refs WHERE order_id=?", (str(order_id),)).fetchone()
        return (str(row[0]), float(row[1])) if row else (None, None)
    except Exception:
        return (None, None)

def _check_fam_connection():
    if not _fam_uses_zyvopay():
        return _legacy_check_fam_connection()
    cfg = _zyvopay_config('fam')
    try:
        _zyvopay_signing_key(cfg['api_key'])
        try:
            # Harmless signed lookup of a fake reference: proves auth without creating a charge.
            _zyvopay_request('POST', 'check-payment.php', {'reference': 'CONNECTION_TEST_' + secrets.token_hex(8)}, retries=0, gateway='fam')
            ok, detail = True, 'ZYVO PAY API token accepted.'
        except RuntimeError as exc:
            msg = str(exc)
            ok = 'HTTP 404' in msg
            detail = 'ZYVO PAY API token accepted.' if ok else msg
        _set_gateway_connected('fam', ok)
        return ok, detail
    except Exception as exc:
        _set_gateway_connected('fam', False)
        return False, str(exc)[:260]

def _create_fam_zyvopay_qr(amount):
    amount = round(float(amount), 2)
    if not 1 <= amount <= 100000:
        raise RuntimeError('Payment amount must be between ₹1 and ₹1,00,000.')
    cfg = _zyvopay_config('fam')
    if not cfg['connected']:
        raise RuntimeError('FamPay (ZYVO PAY) is not connected. Save the API token, then check connection.')
    order_id = 'RG' + datetime.datetime.now().strftime('%y%m%d%H%M%S') + secrets.token_hex(5).upper()
    payload = {'order_id': order_id, 'amount': amount, 'customer_name': BOT_BRAND_NAME[:100], 'description': str(BOT_BRAND_NAME)[:120], 'expires_in': 10}
    payment = _zyvopay_request('POST', 'create-payment.php', payload, gateway='fam')
    returned_order = str(payment.get('order_id') or order_id)
    reference = str(payment.get('reference') or '')
    try: returned_amount = round(float(payment.get('amount')), 2)
    except (TypeError, ValueError): returned_amount = -1
    if not reference or returned_order != order_id or returned_amount != amount or str(payment.get('currency') or 'INR').upper() != 'INR':
        raise RuntimeError('ZYVO PAY returned payment details that did not match the requested order and amount.')
    qr = _zyvopay_qr_image(payment)
    ZYVOPAY_ORDER_META[returned_order] = {'amount': amount, 'gateway': 'fam', 'reference': reference, 'currency': 'INR', 'payment_uri': payment.get('payment_uri') or '', 'expires_at': payment.get('expires_at'), 'created_at': time.time()}
    _zyvopay_ref_save(returned_order, 'fam', reference, amount)  # survives a bot restart
    if isinstance(qr, tuple):
        return qr[1], returned_order
    return qr, returned_order

def _verify_fam_zyvopay_order(order_id):
    cfg = _zyvopay_config('fam')
    meta = ZYVOPAY_ORDER_META.get(str(order_id)) or {}
    reference = str(meta.get('reference') or '')
    expected = meta.get('amount')
    if not reference:
        reference, expected = _zyvopay_ref_get(order_id)
    if not cfg['api_key'] or not reference or expected is None:
        return False, None, None
    try:
        result = _zyvopay_request('POST', 'check-payment.php', {'reference': reference}, retries=1, gateway='fam')
        if str(result.get('status') or '').lower() != 'successful': return False, None, None
        if str(result.get('reference') or '') != reference or str(result.get('order_id') or '') != str(order_id): return False, None, None
        if str(result.get('currency') or '').upper() != 'INR': return False, None, None
        try:
            if round(float(result.get('amount')), 2) != round(float(expected), 2): return False, None, None
        except (TypeError, ValueError): return False, None, None
        return True, str(result.get('utr') or 'N/A'), 'ZYVO PAY/UPI'
    except Exception:
        return False, None, None

def create_fam_qr(amount):
    if _fam_uses_zyvopay():
        return _create_fam_zyvopay_qr(amount)
    return _legacy_create_fam_qr(amount)

def verify_fam_order(order_id):
    if _fam_uses_zyvopay():
        return _verify_fam_zyvopay_order(order_id)
    return _legacy_verify_fam_order(order_id)

def _check_gateway_connection(gateway):
    g=str(gateway).lower()
    return _check_fam_connection() if g=='fam' else _check_paytm_connection() if g=='paytm' else (False,'Unknown payment gateway.')

def _create_active_gateway_qr(amount):
    gw=_get_active_payment_gateway()
    if gw=='fam': return create_fam_qr(amount)
    if gw=='paytm':
        cfg=_paytm_config(); ready=_paytm_payment_config_error()
        if not cfg['connected']: raise RuntimeError('PayTM is not connected. Check PayTM Connection first.')
        if ready: raise RuntimeError('PayTM payment setup is incomplete: '+ready)
        return _create_paytm_dynamic_qr(amount)
    raise RuntimeError('No connected payment gateway is active.')

def _verify_active_gateway_order(order_id,gateway=None):
    details=active_orders.get(str(order_id)) or active_orders.get(order_id) or {}
    gw=str(gateway or details.get('gateway') or _get_active_payment_gateway()).lower()
    if gw=='fam': return verify_fam_order(order_id)
    if gw=='paytm': return _verify_paytm_order(order_id)
    return False,None,None


_load_persistent_admin_ids()


def _hack_server_config(product_name):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        cur=conn.cursor(); cur.execute('SELECT product_name, api_key, server_url, product_id, updated_at FROM hack_server_configs WHERE product_name=?',(str(product_name),)); return cur.fetchone()
    finally: conn.close()

def _hack_server_plan_valid_id(product_name, plan_id):
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        cur=conn.cursor(); cur.execute('SELECT valid_id FROM hack_server_plan_ids WHERE product_name=? AND plan_id=?',(str(product_name),int(plan_id))); row=cur.fetchone(); return str(row[0]).strip() if row and row[0] else ''
    finally: conn.close()

def _save_hack_server_config(product_name, api_key, server_url, remote_product_id):
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        conn.execute('''INSERT INTO hack_server_configs(product_name,api_key,server_url,product_id,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(product_name) DO UPDATE SET api_key=excluded.api_key,server_url=excluded.server_url,product_id=excluded.product_id,updated_at=excluded.updated_at''',(str(product_name),str(api_key).strip(),str(server_url).strip(),str(remote_product_id).strip(),datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))); conn.commit()
    finally: conn.close()

def _save_hack_server_plan_valid_id(product_name, plan_id, plan_days, valid_id):
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        conn.execute('''INSERT INTO hack_server_plan_ids(product_name,plan_id,valid_id,plan_days,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(product_name,plan_id) DO UPDATE SET valid_id=excluded.valid_id,plan_days=excluded.plan_days,updated_at=excluded.updated_at''',(str(product_name),int(plan_id),str(valid_id).strip(),str(plan_days),datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))); conn.commit()
    finally: conn.close()

def _get_hack_server_status(product_name):
    cfg=_hack_server_config(product_name)
    if not cfg: return None
    return {'api_key':cfg[1],'server_url':cfg[2],'product_id':cfg[3],'updated_at':cfg[4]}

def _resolve_api_route(product_name, plan_id=None, local_pid_id=None, duration=None):
    new_cfg=_new_server_config(product_name) if product_name else None
    if new_cfg and new_cfg[1] and new_cfg[2] and new_cfg[3]:
        new_valid_id=_new_server_plan_valid_id(product_name,plan_id) if plan_id is not None else ''
        if plan_id is None or new_valid_id:
            return {'url':new_cfg[2],'api_key':new_cfg[1],'product_id':new_cfg[3],'valid_id':new_valid_id,'server_type':'new'}
    cfg=_hack_server_config(product_name)
    if cfg and cfg[1] and cfg[2]:
        return {'url':cfg[2],'api_key':cfg[1],'product_id':cfg[3] or str(local_pid_id or ''),'valid_id':_hack_server_plan_valid_id(product_name,plan_id) if plan_id else '','server_type':'legacy_hack'}
    return {'url':get_setting('server_api_url') or RESELLER_API_URL,'api_key':get_setting('server_api_key') or RESELLER_API_KEY,'product_id':str(local_pid_id or ''),'valid_id':'','server_type':'legacy'}


# ==================== NEW SERVER API SYSTEM ====================
def _new_server_config(product_name):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        cur = conn.cursor(); cur.execute('SELECT product_name, api_key, server_url, product_id, updated_at FROM new_server_configs WHERE product_name=?', (str(product_name),)); return cur.fetchone()
    finally: conn.close()

def _new_server_plan_valid_id(product_name, plan_id):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        cur = conn.cursor(); cur.execute('SELECT valid_id FROM new_server_plan_ids WHERE product_name=? AND plan_id=?', (str(product_name), int(plan_id))); row = cur.fetchone(); value = str(row[0]).strip() if row and row[0] is not None else ''
        return '' if value.startswith('/') else value
    finally: conn.close()

def _save_new_server_config(product_name, api_key, server_url, remote_product_id):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        conn.execute('''INSERT INTO new_server_configs(product_name,api_key,server_url,product_id,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(product_name) DO UPDATE SET api_key=excluded.api_key,server_url=excluded.server_url,product_id=excluded.product_id,updated_at=excluded.updated_at''', (str(product_name),str(api_key).strip(),str(server_url).strip(),str(remote_product_id).strip(),datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))); conn.commit()
    finally: conn.close()

def _save_new_server_plan_valid_id(product_name, plan_id, plan_days, valid_id):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        conn.execute('''INSERT INTO new_server_plan_ids(product_name,plan_id,valid_id,plan_days,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(product_name,plan_id) DO UPDATE SET valid_id=excluded.valid_id,plan_days=excluded.plan_days,updated_at=excluded.updated_at''', (str(product_name),int(plan_id),str(valid_id),str(plan_days),datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))); conn.commit()
    finally: conn.close()

def _new_server_is_configured(product_name, plan_id=None):
    cfg=_new_server_config(product_name)
    if not cfg or not cfg[1] or not cfg[2] or not cfg[3]: return False
    return plan_id is None or bool(_new_server_plan_valid_id(product_name,plan_id))

def _new_server_hack_by_hash(value):
    for product_name in get_unique_products():
        if _ui_hash(product_name)==str(value): return product_name
    return None

def _new_server_hacks_markup():
    markup=types.InlineKeyboardMarkup()
    for prod in get_unique_products():
        status='🟢' if _new_server_is_configured(prod) else '⚪'
        markup.add(types.InlineKeyboardButton(f'{status} {prod}',callback_data=f'new_server_hack_{_ui_hash(prod)}'))
    markup.add(types.InlineKeyboardButton('🔙 Back',callback_data='admin_api_system'))
    return markup

def _new_server_plans_markup(product_name):
    markup=types.InlineKeyboardMarkup(); cfg=_new_server_config(product_name); pid=cfg[3] if cfg else '—'
    for plan in get_product_plans(product_name):
        plan_id=int(plan[0]); days=str(plan[2]); valid_id=_new_server_plan_valid_id(product_name,plan_id); status='🟢' if valid_id else '⚪'
        label=f'{status} {days} | PID:{pid} | VID:{valid_id or "—"}'
        markup.add(types.InlineKeyboardButton(label[:60],callback_data=f'new_server_plan_{_ui_hash(product_name)}_{plan_id}'))
    markup.add(types.InlineKeyboardButton('🔙 Hack List',callback_data='new_server_api'))
    return markup

def _new_server_status_text():
    return '🟢 CONNECTED' if str(get_setting(NEW_SERVER_ENABLED_KEY) or '0')=='1' else '🔴 NOT CONNECTED'

def _new_server_test_connection():
    try:
        res=HTTP_SESSION.post(NEW_SERVER_API_URL,data={'api_key':NEW_SERVER_API_KEY,'action':'balance'},headers={'Content-Type':'application/x-www-form-urlencoded','x-master-key':RESELLER_MASTER_KEY},timeout=8)
        return res.status_code==200,res.text[:300]
    except Exception as exc: return False,str(exc)[:300]

# ==================== GLOBAL PRICE-LIST / EMOJI TEMPLATE ====================
GLOBAL_PRICE_LIST_TEMPLATE_KEY = 'global_price_list_template'

def get_global_price_list_template():
    return get_setting(GLOBAL_PRICE_LIST_TEMPLATE_KEY)

def set_global_price_list_template(template):
    if template is None:
        template = ''
    set_setting(GLOBAL_PRICE_LIST_TEMPLATE_KEY, str(template).strip())


# ==================== PREMIUM PRICE-LIST MODE ====================
# When enabled, the saved master price-list template is used for every product.
# Live plans/prices/stock/discounts are still generated from the database.
PRICE_LIST_PREMIUM_MODE_KEY = 'price_list_premium_mode'


def get_price_list_premium_mode():
    return str(get_setting(PRICE_LIST_PREMIUM_MODE_KEY) or '0') == '1'


def set_price_list_premium_mode(enabled):
    set_setting(PRICE_LIST_PREMIUM_MODE_KEY, '1' if enabled else '0')


# ==================== PLAN TEXT ADD — PREMIUM HEADER OVERRIDE ====================
# This is the simple admin-controlled text shown above the live plan buttons.
# It intentionally overrides older price-list/header text without deleting any
# product, plan, price, stock, discount or checkout data. Premium custom emojis
# are stored as Telegram <tg-emoji> HTML and are rendered exactly as sent.
PLAN_TEXT_ADD_KEY = 'plan_text_add_template'

def get_plan_text_add():
    return get_setting(PLAN_TEXT_ADD_KEY) or ''

def set_plan_text_add(template):
    set_setting(PLAN_TEXT_ADD_KEY, str(template or '').strip())


# ==================== PER-PRODUCT PLAN TEXT + PREMIUM EMOJI ====================
PLAN_TEXT_PRODUCT_PREFIX = 'plan_text_product_'
PLAN_TEXT_PRODUCT_LAST_KEY = 'plan_text_product_last'
PLAN_TEXT_PRODUCT_LAST_NAME_KEY = 'plan_text_product_last_name'
PLAN_TEXT_PRODUCT_NAMES_KEY = 'plan_text_product_names'

def _plan_text_product_key(product_name):
    return PLAN_TEXT_PRODUCT_PREFIX + _ui_hash(product_name)

def _normalize_product_template_name(value):
    # Normalization is only for matching a saved design to a renamed/display-name
    # product. It never changes the actual product name in the database.
    value = str(value or '').lower()
    value = re.sub(r'[^a-z0-9]+', ' ', value)
    return ' '.join(value.split())

def _get_saved_product_template_names():
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cur = conn.cursor()
    try:
        cur.execute("SELECT key FROM settings WHERE key LIKE ?", (PLAN_TEXT_PRODUCT_PREFIX + '%',))
        rows = cur.fetchall()
    finally:
        conn.close()
    names = []
    prefix = PLAN_TEXT_PRODUCT_PREFIX
    for (key,) in rows:
        if key in (PLAN_TEXT_PRODUCT_LAST_KEY, PLAN_TEXT_PRODUCT_LAST_NAME_KEY):
            continue
        # Names are not stored in the key, so recover them from the saved catalog
        # only through the explicit last-name mapping. Exact lookup remains primary.
    return names

def get_plan_text_product(product_name):
    # 1. Exact product-name match (normal path).
    exact = get_setting(_plan_text_product_key(product_name)) or ''
    if exact:
        return exact

    wanted = _normalize_product_template_name(product_name)
    if not wanted:
        return ''

    # 2. Scan the saved-name map so a product can safely keep its design after
    # an admin renames the product. This does not alter the database product name.
    try:
        name_map = json.loads(get_setting(PLAN_TEXT_PRODUCT_NAMES_KEY) or '{}')
    except Exception:
        name_map = {}

    best_template = ''
    best_score = 0.0
    for saved_hash, saved_name in name_map.items():
        saved_name = str(saved_name or '')
        saved = _normalize_product_template_name(saved_name)
        if not saved:
            continue
        template = get_setting(PLAN_TEXT_PRODUCT_PREFIX + str(saved_hash)) or ''
        if not template:
            continue
        if saved == wanted:
            return template
        wanted_tokens = set(wanted.split())
        saved_tokens = set(saved.split())
        overlap = len(wanted_tokens & saved_tokens)
        ratio = difflib.SequenceMatcher(None, wanted, saved).ratio()
        score = ratio + min(overlap, 4) * 0.08
        if overlap >= 2 and ratio >= 0.45 and score > best_score:
            best_score = score
            best_template = template

    if best_template:
        return best_template

    # 3. Legacy migration fallback: if there is exactly one real saved product
    # design, use it for an unmatched product. Exclude the migration metadata
    # keys themselves from the count.
    last_template = get_setting(PLAN_TEXT_PRODUCT_LAST_KEY) or ''
    if last_template:
        conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT COUNT(*) FROM settings WHERE key LIKE ? "
                "AND key NOT IN (?, ?, ?) AND value IS NOT NULL AND value != ''",
                (PLAN_TEXT_PRODUCT_PREFIX + '%',
                 PLAN_TEXT_PRODUCT_LAST_KEY,
                 PLAN_TEXT_PRODUCT_LAST_NAME_KEY,
                 PLAN_TEXT_PRODUCT_NAMES_KEY)
            )
            count = int(cur.fetchone()[0] or 0)
        finally:
            conn.close()
        if count == 1:
            return last_template

    return ''

def set_plan_text_product(product_name, template):
    cleaned = _repair_premium_emoji_markup(str(template or '').strip())
    product_name = str(product_name or '').strip()
    key_hash = _ui_hash(product_name)

    # Preserve the exact per-product design.
    set_setting(_plan_text_product_key(product_name), cleaned)

    # Keep a name map for safe rename/migration matching. Existing settings,
    # products, prices, stock and checkout data are never deleted.
    try:
        name_map = json.loads(get_setting(PLAN_TEXT_PRODUCT_NAMES_KEY) or '{}')
    except Exception:
        name_map = {}
    name_map[str(key_hash)] = product_name
    set_setting(PLAN_TEXT_PRODUCT_NAMES_KEY, json.dumps(name_map, ensure_ascii=False))

    # Keep a migration-safe last-template copy as a final legacy fallback.
    set_setting(PLAN_TEXT_PRODUCT_LAST_NAME_KEY, product_name)
    set_setting(PLAN_TEXT_PRODUCT_LAST_KEY, cleaned)

def _render_plan_text_product(template, live_rows, product_name):
    """Render the admin's custom design while injecting LIVE days/stock/price.

    The admin may write either explicit placeholders ({days}/{stock}/{price}) or
    simply write labels such as ``Validity:``, ``Stock:``, and ``Price:`` in the
    first sample row.  The first complete Validity/Stock/Price block is repeated
    once for every real plan; old copied plan rows are discarded.
    """
    if not template:
        return ''

    text = _repair_premium_emoji_markup(str(template).strip())
    lines = text.splitlines()
    tokens = ('{days}', '{stock}', '{stock_status}', '{price}', '{price_text}', '{validity}')

    # Find the first dynamic/sample plan block. This supports both placeholder
    # templates and the user's screenshot style where only {days} is dynamic and
    # Stock:/Price: are left blank for the bot to fill.
    first = None
    first_stock = None
    first_price = None
    for i, line in enumerate(lines):
        plain = re.sub(r'<[^>]+>', '', line).strip().lower()
        if first is None and (any(t in line for t in tokens) or re.search(r'\bvalidity\b', plain)):
            first = i
            continue
        if first is not None and first_stock is None and re.search(r'\bstock\b', plain):
            first_stock = i
            continue
        if first_stock is not None and first_price is None and re.search(r'\bprice\b', plain):
            first_price = i
            break

    # If there is no complete dynamic block, preserve the admin text exactly.
    if first is None or first_stock is None or first_price is None:
        return text

    block_end = first_price
    header = lines[:first]
    sample = lines[first:block_end + 1]
    footer_lines = lines[block_end + 1:]

    # Remove copied/generated plan rows after the sample. Keep the user's real
    # footer, especially CHOOSE A PLAN and any custom text after it.
    footer = []
    after_choose = False
    for line in footer_lines:
        plain = re.sub(r'<[^>]+>', '', line).strip().lower()
        if re.search(r'\b(choose a plan|select your plan)\b', plain):
            footer.append(line)
            after_choose = True
            continue
        is_plan_line = (
            re.search(r'\bvalidity\b[^:\n]*[:：]', plain)
            or re.search(r'\bstock\b[^:\n]*[:：]', plain)
            or re.search(r'\bprice\b[^:\n]*[:：]', plain)
            or (re.search(r'\b\d+\s*days(?:\s*days)?\b', plain)
                and (any(mark in plain for mark in ('📊', '❌', '├', '└', 'stock', 'price')) or after_choose))
        )
        if is_plan_line:
            continue
        footer.append(line)

    def replace_label(line, label, value):
        # Replace the value after the label's colon, preserving Premium emoji,
        # HTML formatting and all text before the colon.
        pat = re.compile(r'(\b' + re.escape(label) + r'\b[^:\n]*[:：]\s*)(.*)$', re.I)
        return pat.sub(lambda m: m.group(1) + str(value), line, count=1)

    rendered_blocks = []
    for row in live_rows:
        days = _validity_display(row.get('days', ''))
        vals = {
            'days': days,
            'validity': _validity_display(row.get('days', '')),
            'stock': str(row.get('stock_status', 'Out of Stock')),
            'stock_status': str(row.get('stock_status', 'Out of Stock')),
            'price': str(row.get('price_text', '')),
            'price_text': str(row.get('price_text', '')),
        }
        out = []
        for line in sample:
            line2 = replace_label(line, 'Validity', vals['validity'])
            line2 = replace_label(line2, 'Stock', vals['stock'])
            line2 = replace_label(line2, 'Price', vals['price'])
            for key, value in vals.items():
                line2 = line2.replace('{' + key + '}', value)
            out.append(line2)
        rendered_blocks.append('\n'.join(out))

    parts = []
    if header:
        parts.append('\n'.join(header).strip())
    if rendered_blocks:
        parts.append('\n\n'.join(rendered_blocks))
    if footer:
        parts.append('\n'.join(footer).strip())
    return _repair_premium_emoji_markup('\n\n'.join(x for x in parts if x).strip())


# ==================== PER-HACK PRICE LIST DESIGN ====================
# Each hack can have its own top title + 2 Premium header emojis + 1 Premium
# day/validity emoji. Live plans, prices, stock and discounts remain untouched.
HACK_PRICE_UI_PREFIX = 'hack_price_ui_'

def _hack_price_ui_key(product_name):
    return HACK_PRICE_UI_PREFIX + _ui_hash(product_name)

def get_hack_price_ui(product_name):
    raw = get_setting(_hack_price_ui_key(product_name))
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        if data.get('template'):
            return data
        if not data.get('title') or not data.get('day_emoji'):
            return None
        return data
    except Exception:
        return None

def set_hack_price_ui(product_name, title, header_emoji_1, header_emoji_2, day_emoji):
    data = {
        'title': str(title).strip(),
        'header_emoji_1': str(header_emoji_1).strip(),
        'header_emoji_2': str(header_emoji_2).strip(),
        'day_emoji': str(day_emoji).strip(),
    }
    set_setting(_hack_price_ui_key(product_name), json.dumps(data, ensure_ascii=False))


def set_hack_price_ui_template(product_name, template):
    """Save the admin's per-hack price-list design exactly as sent.

    The template is presentation-only. At render time the live DB plans, prices,
    stock state and discounts are injected into the Validity/Stock/Price rows.
    """
    data = get_hack_price_ui(product_name) or {}
    data['template'] = str(template or '').strip()
    # Keep legacy fields when present; they are no longer required for new designs.
    set_setting(_hack_price_ui_key(product_name), json.dumps(data, ensure_ascii=False))


def _clean_plan_days(raw_days):
    """Return the legacy numeric value used by stock/API lookups."""
    value = str(raw_days or '').strip()
    value = re.sub(r'\s*DAYS?\s*$', '', value, flags=re.I).strip()
    return value

def _validity_display(raw_days):
    """Preserve the exact configured validity label for UI display.

    If a legacy database contains only a numeric value, keep backward
    compatibility by displaying DAYS. If the configured value contains a unit
    or custom wording (Hours, Day, Year, Pro Version, etc.), never append or
    replace anything.
    """
    value = str(raw_days or '').strip()
    if not value:
        return ''
    if re.search(r'[A-Za-z]', value):
        return value
    return f'{value} DAYS'


def _render_hack_price_ui_template(template, pricing_rows, product_name):
    """Render one clean per-hack Premium price-list design.

    The admin may send a message copied from an older price list.  Only the
    FIRST Validity/Stock/Price sample is used as the reusable block.  Any
    additional Validity/Stock/Price rows in the saved template are discarded,
    so live plans can never appear twice.
    """
    if not template:
        return None

    template = _repair_premium_emoji_markup(template)
    lines = str(template).splitlines()
    first_validity = first_stock = first_price = None

    # Locate the first complete sample block.
    for i, line in enumerate(lines):
        plain = re.sub(r'<[^>]+>', '', line).strip().lower()
        if first_validity is None and re.search(r'\bvalidity\b', plain):
            first_validity = i
            continue
        if first_validity is not None and first_stock is None and re.search(r'\bstock\b', plain):
            first_stock = i
            continue
        if first_stock is not None and first_price is None and re.search(r'\bprice\b', plain):
            first_price = i
            break

    if first_validity is None or first_stock is None or first_price is None:
        return None

    block_end = max(first_validity, first_stock, first_price)
    header = lines[:first_validity]
    block = lines[first_validity:block_end + 1]
    footer = lines[block_end + 1:]

    # IMPORTANT: if the admin copied an old full price list, its remaining
    # plan rows may use either the explicit Validity/Stock/Price labels or an
    # older compact generated layout such as "❌ 📊 1 DAYS" followed by Stock
    # and Price lines. Remove those legacy generated rows so the live rows are
    # rendered exactly once. Keep the user's real footer (especially CHOOSE A PLAN).
    cleaned_footer = []
    after_choose = False
    for line in footer:
        plain = re.sub(r'<[^>]+>', '', line).strip().lower()

        if re.search(r'\b(choose a plan|select your plan)\b', plain):
            cleaned_footer.append(line)
            after_choose = True
            continue

        is_labeled_plan_line = (
            re.search(r'\bvalidity\b[^:\n]*[:：]', plain) or
            re.search(r'\bstock\b[^:\n]*[:：]', plain) or
            re.search(r'\bprice\b[^:\n]*[:：]', plain)
        )

        # Legacy compact plan rows have no "Validity:" label. They usually
        # contain a day count plus DAYS, often with 📊/❌/├/└, followed by
        # Stock/Price lines. Treat those as generated rows too.
        is_compact_plan_line = (
            re.search(r'\b\d+\s*days(?:\s*days)?\b', plain) and
            (any(mark in plain for mark in ('📊', '❌', '├', '└', 'stock', 'price')) or after_choose)
        )

        if is_labeled_plan_line or is_compact_plan_line:
            continue

        # Once CHOOSE A PLAN has been followed by a legacy generated block,
        # discard only blank lines belonging to that block; preserve unrelated
        # custom footer text if the admin added any.
        cleaned_footer.append(line)
    footer = cleaned_footer

    # Do not allow the old generated "STOCK & PRICING" section to be appended
    # when it was copied into the admin template. The admin's own heading stays.
    # This only removes the exact legacy heading text, not arbitrary custom text.
    header = [
        line for line in header
        if re.sub(r'<[^>]+>', '', line).strip().lower()
        not in ('stock & pricing :', 'stock & pricing:', 'stock & pricing')
    ]

    def replace_line_value(line, label, value):
        # Replace everything after the label's colon. Premium <tg-emoji>
        # wrappers before the label remain untouched.
        pat = re.compile(
            r'(\b' + re.escape(label) + r'\b[^:\n]*[:：]\s*)(.*)$',
            re.I
        )
        return pat.sub(lambda m: m.group(1) + str(value), line, count=1)

    rendered_blocks = []
    for row in pricing_rows:
        days = _validity_display(row.get('days', ''))
        validity = days
        vals = {
            'Validity': validity,
            'Stock': str(row.get('stock_status', 'Out of Stock')),
            'Price': str(row.get('price_text', '')),
        }

        out_lines = []
        for line in block:
            line2 = replace_line_value(line, 'Validity', vals['Validity'])
            line2 = replace_line_value(line2, 'Stock', vals['Stock'])
            line2 = replace_line_value(line2, 'Price', vals['Price'])

            # Support placeholders without adding a second DAYS suffix.
            line2 = (line2
                     .replace('{days}', days)
                     .replace('{validity}', vals['Validity'])
                     .replace('{stock}', vals['Stock'])
                     .replace('{price}', vals['Price']))
            out_lines.append(line2)

        rendered_blocks.append('\n'.join(out_lines))

    if not rendered_blocks:
        return '\n'.join(header + footer).strip()

    # Exactly ONE generated block per real DB plan. No old price-list rows are
    # appended, so 1/3/7/15/30 will never become 1/3/7/15/30 + 3/7/15/30.
    rendered = '\n'.join(header + ['\n\n'.join(rendered_blocks)] + footer).strip()
    return _repair_premium_emoji_markup(rendered)


def _premium_emoji_html(emoji_id, fallback='✨'):
    """Build Telegram HTML for a Premium custom emoji."""
    if not emoji_id:
        return html.escape(str(fallback or '✨'), quote=False)
    safe_id = html.escape(str(emoji_id).strip(), quote=True)
    safe_fallback = html.escape(str(fallback or '✨'), quote=False)
    return f'<tg-emoji emoji-id="{safe_id}">{safe_fallback}</tg-emoji>'


def _repair_premium_emoji_markup(text):
    """Normalize Premium emoji markup, or render its normal fallback when OFF.

    The admin switch is intentionally a *display* switch: saved custom-emoji
    IDs are not deleted, but every outgoing message/template is rendered with
    the ordinary Unicode fallback while Premium mode is disabled.
    """
    if not text:
        return text
    value = str(text)
    value = re.sub(
        r'&lt;(/?tg-emoji\b[^&]*)&gt;',
        lambda m: '<' + html.unescape(m.group(1)) + '>',
        value,
        flags=re.I,
    )

    # Premium/custom emoji OFF: keep the visible fallback character and remove
    # the Telegram custom-emoji wrapper and its emoji-id everywhere.
    try:
        premium_enabled = get_price_list_premium_mode()
    except Exception:
        premium_enabled = True
    if not premium_enabled:
        value = re.sub(
            r'<tg-emoji\b[^>]*>(.*?)</tg-emoji>',
            lambda m: m.group(1),
            value,
            flags=re.I | re.S,
        )
        return value

    def normalize_open(match):
        emoji_id = match.group(1).strip()
        return f'<tg-emoji emoji-id="{html.escape(emoji_id, quote=True)}">'

    value = re.sub(
        r'<tg-emoji\s+emoji-id\s*=\s*["\']([^"\']+)["\']\s*>',
        normalize_open,
        value,
        flags=re.I,
    )
    return value


def _premium_emoji_ids_from_template(template, unique=True):
    """Return Premium custom-emoji IDs from a saved template.

    ``unique=True`` is kept for legacy callers. Order History persistence uses
    ``unique=False`` because exact occurrence order is meaningful and duplicate
    IDs at different visual positions must not be collapsed.
    """
    if not template:
        return []
    ids = []
    for match in re.finditer(
        r'<tg-emoji\s+emoji-id\s*=\s*["\']([^"\']+)["\']\s*>',
        str(template),
        flags=re.I,
    ):
        emoji_id = str(match.group(1)).strip()
        if not emoji_id:
            continue
        if unique:
            if emoji_id not in ids:
                ids.append(emoji_id)
        else:
            ids.append(emoji_id)
    return ids


def _get_product_button_keys():
    return [f"hack:{product_name}" for product_name in get_unique_products()]


def _get_price_button_keys():
    keys = []
    for product_name in get_unique_products():
        for plan in get_product_plans(product_name):
            keys.append(f"price:{product_name}:{plan[0]}")
    return keys


def set_bulk_button_emoji(button_keys, emoji_id):
    """Apply one Premium custom emoji to every button in a dynamic group."""
    clean_id = str(emoji_id).strip()
    for key in button_keys:
        set_button_emoji(key, clean_id)


def get_bulk_emoji_status(button_keys):
    values = [get_button_emoji(key) for key in button_keys]
    values = [v for v in values if v]
    if not values:
        return None
    if len(values) == len(button_keys) and len(set(values)) == 1:
        return values[0]
    return "mixed"


# ==================== UI CUSTOMIZATION HELPERS ====================
# Telegram Bot API supports button styles: danger=red, primary=blue, success=green.
# Premium custom-emoji icons on buttons require a recent pyTelegramBotAPI.
BUTTON_STYLE_MAP = {
    "red": "danger",
    "blue": "primary",
    "green": "success",
    "default": None,
}

def _ui_hash(value):
    return hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:20]

def _style_setting_key(button_key):
    return f"button_style_{_ui_hash(button_key)}"


def _admin_colorful_button(text, callback_data=None, color="blue"):
    """Create a colorful Admin-only button without touching User Panel settings.

    This helper intentionally uses no button_key, so the visual palette here is
    local to the Admin Panel and cannot change any user-facing button style.
    """
    color = color if color in ("red", "blue", "green") else "blue"
    return make_ui_button(
        text,
        callback_data=callback_data,
        default_color=color,
        force_style=True,
    )

def _emoji_setting_key(button_key):
    return f"button_emoji_{_ui_hash(button_key)}"

def get_button_style(button_key, default=None):
    saved = get_setting(_style_setting_key(button_key))
    if saved in BUTTON_STYLE_MAP:
        return BUTTON_STYLE_MAP[saved]
    return default

def set_button_style(button_key, color):
    if color not in BUTTON_STYLE_MAP:
        color = "default"
    set_setting(_style_setting_key(button_key), color)

def get_button_emoji(button_key, default=None):
    return get_setting(_emoji_setting_key(button_key)) or default

def set_button_emoji(button_key, emoji_id):
    set_setting(_emoji_setting_key(button_key), str(emoji_id).strip())


# ==================== PER-USER / PER-PRODUCT PLAN PRICE OVERRIDES ====================
def get_custom_plan_price(user_id, plan_id):
    """Return exact custom prices for one Telegram user and one Product plan."""
    try:
        uid = int(user_id); pid = int(plan_id)
    except (TypeError, ValueError):
        return {"user_price": None, "reseller_price": None}
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        row = conn.execute(
            "SELECT user_price, reseller_price FROM custom_plan_prices WHERE user_id=? AND plan_id=?",
            (uid, pid)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {"user_price": None, "reseller_price": None}
    def _num(v):
        try: return float(v) if v is not None else None
        except (TypeError, ValueError): return None
    return {"user_price": _num(row[0]), "reseller_price": _num(row[1])}


def set_custom_plan_price(user_id, plan_id, user_price=None, reseller_price=None):
    uid = int(user_id); pid = int(plan_id)
    up = None if user_price is None else round(float(user_price), 2)
    rp = None if reseller_price is None else round(float(reseller_price), 2)
    if up is not None and up < 0: raise ValueError("User price cannot be negative.")
    if rp is not None and rp < 0: raise ValueError("Reseller price cannot be negative.")
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        if up is None and rp is None:
            conn.execute("DELETE FROM custom_plan_prices WHERE user_id=? AND plan_id=?", (uid, pid))
        else:
            conn.execute(
                """INSERT INTO custom_plan_prices(user_id,plan_id,user_price,reseller_price,updated_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(user_id,plan_id) DO UPDATE SET
                     user_price=excluded.user_price,
                     reseller_price=excluded.reseller_price,
                     updated_at=excluded.updated_at""",
                (uid, pid, up, rp, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
        conn.commit()
    finally:
        conn.close()


# ==================== SPECIAL USER BUTTON SETTINGS ====================
# These keys live inside the existing Admin Panel Button Section. They are
# presentation-only and do not replace/remove any existing button settings.
ADD_BALANCE_CANCEL_BUTTON_KEY = "topkey:cancel"
ADD_BALANCE_CONFIRM_BUTTON_KEY = "topkey:confirm"
ALL_PRODUCTS_OUT_OF_STOCK_BUTTON_KEY = "all_products_out_of_stock"


def _special_button_text(key, default_text):
    return get_custom_btn(key, default_text)


def _special_button_emoji(key):
    return get_button_emoji(key)


def _special_button_design_text(message):
    """Extract plain button text and the first Premium custom emoji ID.

    Admins may send a single message such as a Premium emoji followed by the
    desired label. Telegram's custom-emoji entity is saved as the real button
    icon, while the visible label is kept as normal button text.
    """
    raw_html = _repair_premium_emoji_markup(_message_html_text(message).strip())
    emoji_id = None
    try:
        for ent in (getattr(message, "entities", None) or []):
            if getattr(ent, "type", None) == "custom_emoji" and getattr(ent, "custom_emoji_id", None):
                emoji_id = str(ent.custom_emoji_id).strip()
                if emoji_id:
                    break
    except Exception:
        pass
    plain = re.sub(r'<tg-emoji\b[^>]*>(.*?)</tg-emoji>', lambda m: m.group(1), raw_html, flags=re.I | re.S)
    plain = re.sub(r'<[^>]+>', '', plain)
    plain = html.unescape(plain).strip()
    return plain, emoji_id


def _save_special_button_design(message, button_key, label):
    plain, emoji_id = _special_button_design_text(message)
    if not plain:
        bot.send_message(message.chat.id, "❌ Button text cannot be empty. Please send the button text again.")
        return False
    set_setting(f"custom_btn_{button_key}", plain)
    if emoji_id:
        set_button_emoji(button_key, emoji_id)
    _admin_success_send(
        message.chat.id,
        f"✅ <b>{html.escape(label)} Button Updated Successfully!</b>\n\n"
        f"📝 <b>Text:</b> {html.escape(plain)}\n"
        + ("✨ <b>Premium custom emoji:</b> Saved\n" if emoji_id else "✨ <b>Premium custom emoji:</b> Existing setting kept\n")
        + "The setting is saved inside the Admin Panel Button Section.",
        parse_mode="HTML"
    )
    return True

def _strip_leading_normal_emoji(text):
    """Remove normal leading emoji when a Premium custom emoji icon is active.

    Telegram renders icon_custom_emoji_id to the left of button text. If the old
    text still starts with a normal emoji, users see two icons. This helper removes
    only leading emoji/variation-selector/ZWJ characters and keeps the actual label.
    """
    if not text:
        return text
    value = str(text).strip()
    # Remove common Unicode emoji blocks at the beginning, including emoji joined
    # with variation selectors, skin-tone modifiers and ZWJ sequences.
    emoji_chars = []
    for ch in value:
        cp = ord(ch)
        cat = __import__('unicodedata').category(ch)
        is_emoji = (
            0x1F000 <= cp <= 0x1FAFF or
            0x2600 <= cp <= 0x27BF or
            0x2300 <= cp <= 0x23FF or
            0x2B00 <= cp <= 0x2BFF or
            0x2190 <= cp <= 0x21FF or
            0xFE0F <= cp <= 0xFE0F or
            0x200D <= cp <= 0x200D or
            cat in ('So', 'Sk')
        )
        if is_emoji:
            emoji_chars.append(ch)
            continue
        if ch in ('\ufe0e', '\ufe0f', '\u200d'):
            emoji_chars.append(ch)
            continue
        break
    if emoji_chars:
        value = value[len(''.join(emoji_chars)):].lstrip()
    return value


def make_ui_button(text, callback_data=None, url=None, button_key=None,
                   default_color="default", default_emoji_id=None, force_premium=False, force_style=False):
    """Create an InlineKeyboardButton with saved color/custom-emoji settings.
    Falls back to a normal button if an old library version rejects the new fields.
    When a Premium custom emoji is configured, any old leading normal emoji in the
    text is removed so Telegram shows exactly one icon.
    """
    premium_mode = get_price_list_premium_mode()
    if button_key:
        _ADMIN_BUTTON_REGISTRY[str(button_key)] = {
            "text": str(text or ""),
            "callback_data": str(callback_data or ""),
            "button_key": str(button_key),
        }
    style = get_button_style(button_key, BUTTON_STYLE_MAP.get(default_color)) if button_key else BUTTON_STYLE_MAP.get(default_color)
    emoji_id = get_button_emoji(button_key, default_emoji_id) if button_key else default_emoji_id
    if not premium_mode and not force_style:
        # Global User Panel Premium Mode OFF: normal user buttons keep their
        # default appearance. Admin controls can explicitly force blue styling.
        style = None
    if not premium_mode and not force_premium:
        emoji_id = None
    display_text = _strip_leading_normal_emoji(text) if emoji_id else text
    kwargs = {}
    if callback_data is not None:
        kwargs["callback_data"] = callback_data
    if url is not None:
        kwargs["url"] = url
    if style:
        kwargs["style"] = style
    if emoji_id:
        kwargs["icon_custom_emoji_id"] = str(emoji_id)
    try:
        return types.InlineKeyboardButton(text=display_text, **kwargs)
    except TypeError:
        # Compatibility with old pyTelegramBotAPI versions.
        fallback_kwargs = {}
        if callback_data is not None:
            fallback_kwargs["callback_data"] = callback_data
        if url is not None:
            fallback_kwargs["url"] = url
        btn = types.InlineKeyboardButton(text=display_text, **fallback_kwargs)
        if style:
            try:
                btn.style = style
            except Exception:
                pass
        if emoji_id:
            try:
                btn.icon_custom_emoji_id = str(emoji_id)
            except Exception:
                pass
        return btn



def _repair_telegram_html_markup(text):
    """Repair unbalanced Telegram HTML while preserving Premium custom emojis."""
    if not text:
        return text

    value = str(text)
    allowed = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "code", "pre", "blockquote", "tg-emoji", "a"}
    tag_re = re.compile(r"</?([A-Za-z][A-Za-z0-9-]*)(?:\s+[^<>]*?)?/?>", re.S)
    out = []
    stack = []
    pos = 0

    for m in tag_re.finditer(value):
        out.append(value[pos:m.start()])
        raw = m.group(0)
        name = m.group(1).lower()
        closing = raw.startswith("</")
        self_closing = raw.endswith("/>")

        if name not in allowed:
            pos = m.end()
            continue
        if self_closing:
            out.append(raw)
            pos = m.end()
            continue

        if closing:
            if name not in stack:
                pos = m.end()
                continue
            while stack and stack[-1] != name:
                out.append(f"</{stack.pop()}>")
            if stack and stack[-1] == name:
                out.append(raw)
                stack.pop()
            pos = m.end()
            continue

        out.append(raw)
        stack.append(name)
        pos = m.end()

    out.append(value[pos:])
    while stack:
        out.append(f"</{stack.pop()}>")
    return "".join(out)


def _send_payment_success_safely(chat_id, text, reply_markup=None):
    """Send payment success without allowing malformed custom HTML to break checkout."""
    try:
        return bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as first_error:
        repaired = _repair_telegram_html_markup(_repair_premium_emoji_markup(str(text)))
        try:
            return bot.send_message(chat_id, repaired, parse_mode="HTML", reply_markup=reply_markup)
        except Exception:
            plain = re.sub(r"<tg-emoji\b[^>]*>(.*?)</tg-emoji>", lambda m: m.group(1), str(repaired), flags=re.I | re.S)
            plain = re.sub(r"<[^>]+>", "", plain)
            plain = html.unescape(plain)
            try:
                return bot.send_message(chat_id, plain, reply_markup=reply_markup)
            except Exception:
                raise first_error

def _edit_payment_message_safely(chat_id, message_id, text, reply_markup=None):
    """Edit an existing checkout message safely, with HTML fallbacks.

    Wallet checkout now keeps the original Telegram message alive instead of
    deleting it and waiting silently for the API. This makes slow key/API work
    visible to the user and prevents the apparent 'freeze' reported on Wallet.
    """
    if not message_id:
        return _send_payment_success_safely(chat_id, text, reply_markup=reply_markup)

    try:
        return bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=message_id,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    except Exception as first_error:
        repaired = _repair_telegram_html_markup(_repair_premium_emoji_markup(str(text)))
        try:
            return bot.edit_message_text(
                repaired,
                chat_id=chat_id,
                message_id=message_id,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        except Exception:
            plain = re.sub(
                r"<tg-emoji\b[^>]*>(.*?)</tg-emoji>",
                lambda m: m.group(1),
                str(repaired),
                flags=re.I | re.S,
            )
            plain = re.sub(r"<[^>]+>", "", plain)
            plain = html.unescape(plain)
            try:
                return bot.edit_message_text(
                    plain,
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=reply_markup,
                )
            except Exception:
                # The original message may be a media message or may have
                # disappeared. Do not leave the user with a blank/frozen UI.
                return _send_payment_success_safely(chat_id, plain, reply_markup=reply_markup)

def _message_html_text(message, use_caption=False):
    """Return Telegram message text as HTML while preserving every custom emoji.

    Telegram sends Premium/custom emoji as ``custom_emoji`` MessageEntity
    objects. Some pyTelegramBotAPI versions serialize them correctly as
    ``<tg-emoji>`` while others return only their visible Unicode fallback.
    The old implementation repaired missing entities by ``str.find()`` on the
    visible emoji, which is unsafe when the same fallback emoji appears more
    than once: the wrong Premium ID could be attached to the wrong position.

    This version maps each Telegram UTF-16 entity offset to the corresponding
    visible character range inside the generated HTML and inserts the exact
    ``<tg-emoji>`` wrapper at that position. Thus Premium IDs and their visual
    positions are preserved exactly as the admin sent them.
    """
    source_text = (getattr(message, "caption", None) if use_caption else getattr(message, "text", None)) or ""
    entities = list((getattr(message, "caption_entities", None) if use_caption else getattr(message, "entities", None)) or [])

    html_text = None
    try:
        value = getattr(message, "html_text", None)
        if value:
            html_text = value
    except Exception:
        pass

    if not html_text:
        try:
            from telebot import formatting
            html_text = formatting.apply_html_entities(source_text, entities)
        except Exception:
            html_text = html.escape(source_text)

    html_text = str(html_text)

    custom_entities = [
        ent for ent in entities
        if getattr(ent, "type", None) == "custom_emoji"
        and getattr(ent, "custom_emoji_id", None)
    ]
    if not custom_entities:
        return _repair_premium_emoji_markup(html_text)

    def utf16_to_char_index(value, offset):
        """Convert a Telegram UTF-16 code-unit offset to a Python char index."""
        raw = value.encode("utf-16-le")
        offset = max(0, min(int(offset or 0), len(raw) // 2))
        return len(raw[:offset * 2].decode("utf-16-le", errors="ignore"))

    def html_visible_map(value):
        """Map visible-character indexes to raw HTML character spans.

        HTML tags are ignored. HTML entities such as ``&amp;`` count as their
        decoded visible character(s), so the mapping still lines up with the
        original Telegram message text.
        """
        mapping = []
        i = 0
        n = len(value)
        while i < n:
            if value[i] == "<":
                close = value.find(">", i + 1)
                if close < 0:
                    close = n - 1
                i = close + 1
                continue

            if value[i] == "&":
                semi = value.find(";", i + 1)
                if semi >= 0 and semi - i <= 32:
                    token = value[i:semi + 1]
                    decoded = html.unescape(token)
                    if decoded != token:
                        for ch in decoded:
                            mapping.append((i, semi + 1, ch))
                        i = semi + 1
                        continue

            mapping.append((i, i + 1, value[i]))
            i += 1
        return mapping

    visible_map = html_visible_map(html_text)

    # Count already serialized IDs so repeated use of the same Premium emoji ID
    # is handled by occurrence, not by a simple "ID exists" test.
    existing_counts = {}
    for m in re.finditer(r'<tg-emoji\s+emoji-id\s*=\s*["\']([^"\']+)["\']\s*>',
                         html_text, flags=re.I):
        eid = str(m.group(1)).strip()
        existing_counts[eid] = existing_counts.get(eid, 0) + 1
    seen_entities = {}

    insertions = []
    for ent in sorted(custom_entities, key=lambda e: int(getattr(e, "offset", 0) or 0)):
        emoji_id = str(getattr(ent, "custom_emoji_id", "") or "").strip()
        if not emoji_id:
            continue

        seen_entities[emoji_id] = seen_entities.get(emoji_id, 0) + 1
        # If html_text already contains this occurrence, leave it untouched.
        if seen_entities[emoji_id] <= existing_counts.get(emoji_id, 0):
            continue

        source_start = utf16_to_char_index(source_text, getattr(ent, "offset", 0))
        source_end = utf16_to_char_index(
            source_text,
            int(getattr(ent, "offset", 0) or 0) + int(getattr(ent, "length", 0) or 0),
        )
        if source_end <= source_start:
            continue

        # The HTML conversion must preserve visible source text. Use the source
        # character indexes directly rather than searching for the emoji string,
        # so duplicate visible emoji can never steal each other's Premium ID.
        if source_end > len(visible_map):
            continue

        raw_start = visible_map[source_start][0]
        raw_end = visible_map[source_end - 1][1]

        visible = source_text[source_start:source_end]
        tag = (
            f'<tg-emoji emoji-id="{html.escape(emoji_id, quote=True)}">'
            f'{html.escape(visible, quote=False)}</tg-emoji>'
        )
        insertions.append((raw_start, raw_end, tag))

    # Insert from right to left so the raw spans from the HTML mapping never
    # shift under us. Overlapping custom-emoji entities are invalid in Telegram,
    # but sorting defensively keeps this safe.
    for raw_start, raw_end, tag in sorted(insertions, key=lambda x: x[0], reverse=True):
        html_text = html_text[:raw_start] + tag + html_text[raw_end:]

    return _repair_premium_emoji_markup(html_text)


# ==================== QR PAYMENT CAPTION CUSTOM TEXT ====================
# Admin-editable text shown directly below the QR image. This is presentation-only:
# product/plan/price/order-id/date remain live per purchase and are never stored in
# this shared template. Premium Telegram custom emojis are preserved via
# _message_html_text() + _repair_premium_emoji_markup().
QR_PAYMENT_TEXT_KEY = "qr_payment_text"
QR_PAYMENT_TEXT_DEFAULT = (
    "🇮🇳 <b>UPI SCAN & PAY — IN BOT</b>\n"
    "────────────────────────"
)

def get_qr_payment_text():
    return get_setting(QR_PAYMENT_TEXT_KEY) or QR_PAYMENT_TEXT_DEFAULT

def set_qr_payment_text(template):
    cleaned = _repair_premium_emoji_markup(str(template or '').strip())
    set_setting(QR_PAYMENT_TEXT_KEY, cleaned)


def _has_custom_qr_payment_text():
    """True only after the admin has saved a QR-below custom template."""
    saved = get_setting(QR_PAYMENT_TEXT_KEY)
    return bool(str(saved or '').strip())


def _render_qr_payment_text(template, prod_name, prod_days, amount, order_id,
                            purchase_date, device_id=None):
    """Render the admin QR template with live per-purchase values.

    Supports explicit placeholders and ordinary labelled lines such as
    "Amount:" and "Order ID:". Premium custom-emoji markup is preserved.
    """
    if not template:
        return ''

    values = {
        "hack": html.escape(str(prod_name), quote=False),
        "product_name": html.escape(str(prod_name), quote=False),
        "plan": html.escape(str(prod_days), quote=False),
        "amount": f"₹{float(amount):.2f} INR",
        "order_id": html.escape(str(order_id), quote=False),
        "date": html.escape(str(purchase_date), quote=False),
        "purchase_date": html.escape(str(purchase_date), quote=False),
        "device_id": html.escape(str(device_id), quote=False) if device_id else "",
    }

    rendered = _repair_premium_emoji_markup(str(template).strip())
    rendered = _safe_format_custom_text(rendered, **values)

    # Also update normal label rows even when the admin did not use placeholders.
    rendered = _inject_labeled_user_values(
        rendered,
        {
            "product_name": values["product_name"],
            "plan": values["plan"],
            "amount": values["amount"],
            "order_id": values["order_id"],
            "date": values["date"],
            "device_id": values["device_id"],
        }
    )

    return _repair_premium_emoji_markup(rendered).strip()



# ==================== WALLET/UPI PAYMENT SUCCESS PREMIUM EMOJI TEMPLATE ====================
# Presentation-only template for successful product delivery. The admin can send the
# existing success message with Premium custom emojis placed exactly where desired.
# The saved design is rendered with LIVE user/order/product/plan/method/amount/key values.
WALLET_PAYMENT_EMOJI_TEMPLATE_KEY = "wallet_payment_emoji_template"
UPI_PAYMENT_EMOJI_TEMPLATE_KEY = "upi_payment_emoji_template"

# Separate Add Balance/Wallet Top-Up success template. This is intentionally
# independent from the product-checkout Wallet Payment template above.
WALLET_TOPUP_SUCCESS_EMOJI_TEMPLATE_KEY = "wallet_topup_success_emoji_template"

DEFAULT_WALLET_TOPUP_SUCCESS_EMOJI_TEMPLATE = (
    "💰 <b>PAYMENT SUCCESSFUL</b> 💰\n"
    "<i>Wallet Balance Added Successfully!</i>\n\n"
    "🧾 <b>TOP-UP DETAILS</b>\n"
    "├── 👤 <b>Username:</b> {name}\n"
    "├── 🆔 <b>Telegram ID:</b> <code>{user_id}</code>\n"
    "├── 🧾 <b>Order ID:</b> <code>{order_id}</code>\n"
    "├── 💵 <b>Amount Added:</b> {amount}\n"
    "├── 🏷️ <b>UTR:</b> <code>{utr}</code>\n"
    "└── 💼 <b>Current Balance:</b> {current_balance}\n\n"
    "✨ <i>Your wallet has been updated instantly.</i>"
)

DEFAULT_WALLET_PAYMENT_EMOJI_TEMPLATE = (
    "💰 <b>{payment_title}</b> 💰\n"
    "<i>Instant Key Delivery!</i>\n\n"
    "📋 <b>ORDER DETAILS</b>\n"
    "├── 👤 <b>User ID:</b> <code>{user_id}</code>\n"
    "├── 🆔 <b>Order ID:</b> <code>{order_id}</code>\n"
    "├── 🛒 <b>Product ID:</b> <code>{product_id}</code>\n"
    "├── 🎮 <b>Product:</b> {product_name}\n"
    "├── ⏱️ <b>Plan:</b> {plan}\n"
    "├── 💳 <b>Method:</b> {method}\n"
    "{device_line}"
    "└── 💵 <b>Paid:</b> {amount}\n\n"
    "🔑 <b>YOUR KEY:</b>\n"
    "<code>{key}</code>\n\n"
    "💡 <i>Tap the key above to copy instantly.</i>"
)

# Separate UPI design. It uses the exact same live fields as Wallet, but has
# its own admin-saved Premium Emoji/Text template so the two designs never
# overwrite each other.
DEFAULT_UPI_PAYMENT_EMOJI_TEMPLATE = (
    "🎉 <b>{payment_title}</b> 🎉\n"
    "<i>Instant Key Delivery!</i>\n\n"
    "📋 <b>ORDER DETAILS</b>\n"
    "├── 👤 <b>User ID:</b> <code>{user_id}</code>\n"
    "├── 🆔 <b>Order ID:</b> <code>{order_id}</code>\n"
    "├── 🛒 <b>Product ID:</b> <code>{product_id}</code>\n"
    "├── 🎮 <b>Product:</b> {product_name}\n"
    "├── ⏱️ <b>Plan:</b> {plan}\n"
    "├── 💳 <b>Method:</b> {method}\n"
    "{device_line}"
    "└── 💵 <b>Paid:</b> {amount}\n\n"
    "🔑 <b>YOUR KEY:</b>\n"
    "<code>{key}</code>\n\n"
    "💡 <i>Tap the key above to copy instantly.</i>"
)

def get_wallet_payment_emoji_template():
    return get_setting(WALLET_PAYMENT_EMOJI_TEMPLATE_KEY) or ""

def set_wallet_payment_emoji_template(template):
    cleaned = _repair_premium_emoji_markup(str(template or "").strip())
    set_setting(WALLET_PAYMENT_EMOJI_TEMPLATE_KEY, cleaned)

def get_upi_payment_emoji_template():
    return get_setting(UPI_PAYMENT_EMOJI_TEMPLATE_KEY) or DEFAULT_UPI_PAYMENT_EMOJI_TEMPLATE

def set_upi_payment_emoji_template(template):
    cleaned = _repair_premium_emoji_markup(str(template or "").strip())
    set_setting(UPI_PAYMENT_EMOJI_TEMPLATE_KEY, cleaned)


def get_wallet_topup_success_emoji_template():
    return (
        get_setting(WALLET_TOPUP_SUCCESS_EMOJI_TEMPLATE_KEY)
        or DEFAULT_WALLET_TOPUP_SUCCESS_EMOJI_TEMPLATE
    )


def set_wallet_topup_success_emoji_template(template):
    cleaned = _repair_premium_emoji_markup(str(template or "").strip())
    set_setting(WALLET_TOPUP_SUCCESS_EMOJI_TEMPLATE_KEY, cleaned)


def _render_wallet_topup_success_emoji_template(
    template, user_id, user_name, order_id, amount, utr, current_balance
):
    """Render the Add Balance success design with live transaction values."""
    if not template:
        template = DEFAULT_WALLET_TOPUP_SUCCESS_EMOJI_TEMPLATE

    try:
        amount_value = float(amount)
    except (TypeError, ValueError):
        amount_value = 0.0

    try:
        balance_value = float(current_balance)
    except (TypeError, ValueError):
        balance_value = 0.0

    live_username = _get_live_telegram_username(user_id)
    values = {
        "name": html.escape(str(user_name or "User"), quote=False),
        "first_name": html.escape(str(user_name or "User"), quote=False),
        "user": html.escape(str(user_name or "User"), quote=False),
        "username": html.escape(str(live_username or ""), quote=False),
        "username_at": html.escape(
            f"@{live_username}" if live_username else "", quote=False
        ),
        "user_id": str(user_id),
        "telegram_id": str(user_id),
        "amount": f"₹{amount_value:.2f} INR",
        "add_amount": f"₹{amount_value:.2f} INR",
        "topup_amount": f"₹{amount_value:.2f} INR",
        "order_id": html.escape(str(order_id), quote=False),
        "utr": html.escape(str(utr or "N/A"), quote=False),
        "balance": f"{balance_value:.2f}",
        "current_balance": f"₹{balance_value:.2f} INR",
        "date": html.escape(
            datetime.datetime.now().strftime("%A, %d %b %Y %H:%M:%S"),
            quote=False,
        ),
    }

    rendered = _repair_premium_emoji_markup(str(template).strip())
    rendered = _safe_format_custom_text(rendered, **values)

    # Replace labelled fields too, so an admin can paste the screenshot/sample
    # with old values and the bot will still inject the current transaction.
    rendered = _inject_labeled_user_values(
        rendered,
        {
            "name": values["name"],
            "username": values["username"],
            "user_id": values["user_id"],
            "telegram_id": values["telegram_id"],
            "amount": values["amount"],
            "add_amount": values["add_amount"],
            "topup_amount": values["topup_amount"],
            "order_id": values["order_id"],
            "utr": values["utr"],
            "balance": values["balance"],
            "current_balance": values["current_balance"],
            "date": values["date"],
        },
    )

    # Extra common Add Balance labels; preserve the admin's surrounding design.
    rendered = re.sub(
        r'(?im)^([^\n]*\b(?:Add\s+Amount|Amount\s+Added|Amount\s+Adding|Top[- ]?up\s+Amount|Amount)\b[^:\n]*:\s*)[^\n]*$',
        lambda m: m.group(1) + values["amount"],
        rendered,
    )
    rendered = re.sub(
        r'(?im)^([^\n]*\b(?:Current\s+Balance|Wallet\s+Balance|Your\s+Balance|Balance)\b[^:\n]*:\s*)[^\n]*$',
        lambda m: m.group(1) + values["current_balance"],
        rendered,
    )
    rendered = re.sub(
        r'(?im)^([^\n]*\b(?:UTR|Transaction\s+UTR)\b[^:\n]*:\s*)[^\n]*$',
        lambda m: m.group(1) + f'<code>{values["utr"]}</code>',
        rendered,
    )
    rendered = re.sub(
        r'(?im)^([^\n]*\bOrder\s+ID\b[^:\n]*:\s*)[^\n]*$',
        lambda m: m.group(1) + f'<code>{values["order_id"]}</code>',
        rendered,
    )
    rendered = re.sub(
        r'(?im)^([^\n]*\b(?:Telegram\s+ID|User\s+ID)\b[^:\n]*:\s*)[^\n]*$',
        lambda m: m.group(1) + f'<code>{values["user_id"]}</code>',
        rendered,
    )

    return _repair_telegram_html_markup(
        _repair_premium_emoji_markup(rendered).strip()
    )


def _render_wallet_payment_emoji_template(
    template, user_id, order_id, product_id, product_name, plan,
    amount, key_val, pay_type="wallet", device_id=None
):
    """Render the saved payment-success design while keeping every transaction field live."""
    if not template:
        template = DEFAULT_WALLET_PAYMENT_EMOJI_TEMPLATE

    method = "Wallet Method" if str(pay_type).lower() == "wallet" else "UPI Method"
    title = "WALLET PAYMENT SUCCESSFUL" if str(pay_type).lower() == "wallet" else "PAYMENT SUCCESSFUL"
    purchase_date = datetime.datetime.now().strftime("%A, %d %b %Y %H:%M:%S")
    device_line = (
        f"├── 📱 <b>Device ID:</b> <code>{html.escape(str(device_id), quote=False)}</code>\n"
        if device_id else ""
    )

    values = {
        "payment_title": title,
        "user_id": str(user_id),
        "telegram_id": str(user_id),
        "order_id": html.escape(str(order_id), quote=False),
        "product_id": html.escape(str(product_id), quote=False),
        "product_name": html.escape(str(product_name), quote=False),
        "product": html.escape(str(product_name), quote=False),
        "hack": html.escape(str(product_name), quote=False),
        "plan": html.escape(str(plan), quote=False),
        "method": html.escape(method, quote=False),
        "amount": f"₹{float(amount):.2f} INR",
        "paid": f"₹{float(amount):.2f} INR",
        "key": html.escape(str(key_val), quote=False),
        "date": html.escape(purchase_date, quote=False),
        "purchase_date": html.escape(purchase_date, quote=False),
        "device_id": html.escape(str(device_id), quote=False) if device_id else "",
        "device_line": device_line,
    }

    rendered = _repair_premium_emoji_markup(str(template).strip())
    rendered = _safe_format_custom_text(rendered, **values)

    # Keep the transaction fields live even when the admin sent a sample message
    # containing old values instead of placeholders.
    rendered = _inject_labeled_user_values(
        rendered,
        {
            "user_id": str(user_id),
            "telegram_id": str(user_id),
            "product_id": str(product_id),
            "product_name": values["product_name"],
            "plan": values["plan"],
            "method": method,
            "amount": values["amount"],
            "paid": values["paid"],
            "order_id": values["order_id"],
            "key": values["key"],
            "date": values["date"],
            "device_id": values["device_id"],
        }
    )

    # If the same saved visual design is used for UPI, do not leave a misleading
    # "WALLET PAYMENT SUCCESSFUL" heading.
    if str(pay_type).lower() != "wallet":
        rendered = re.sub(
            r"WALLET PAYMENT SUCCESSFUL",
            "PAYMENT SUCCESSFUL",
            rendered,
            flags=re.I,
        )

    return _repair_telegram_html_markup(_repair_premium_emoji_markup(rendered).strip())

def get_custom_text(key, default_val):
    return get_setting(f"custom_text_{key}") or default_val

def get_custom_btn(key, default_val):
    return get_setting(f"custom_btn_{key}") or default_val

def _safe_format_custom_text(template, **values):
    """Replace known placeholders without using str.format().

    This keeps old custom texts safe while allowing live per-user values such as
    name, phone number, Telegram ID and live pricing to be inserted automatically.
    Unknown placeholders are intentionally left untouched instead of crashing.
    """
    import re
    if not template:
        return ""

    aliases = {
        "user": "name",
        # Keep Username separate from display name. This prevents an admin's
        # username from becoming part of a shared custom-text template.
        "username": "username",
        "telegram_username": "username",
        "telegram_id": "user_id",
        "uid": "user_id",
        "number": "phone",
        "phone_number": "phone",
        "hack_name": "hack",
        "product": "product_name",
        "price_list": "pricing_info",
        "prices": "pricing_info",
    }

    def repl(match):
        key = match.group(1)
        lookup = aliases.get(key, key)
        return str(values.get(lookup, match.group(0)))

    return re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", repl, template)

def _get_live_telegram_username(user_id, fallback=None):
    """Return the current Telegram @username for this user.

    Usernames are intentionally fetched live and are never stored inside a
    shared custom-text template. If Telegram does not expose a username, an
    empty value is returned.
    """
    candidate = str(fallback or '').strip().lstrip('@')
    if candidate:
        return candidate
    try:
        chat = bot.get_chat(int(user_id))
        candidate = str(getattr(chat, 'username', '') or '').strip().lstrip('@')
        return candidate
    except Exception:
        return ''


def _get_user_template_values(user_id, first_name=None, phone_number=None, username=None):
    """Build one consistent LIVE placeholder dictionary for user-facing text.

    Only presentation text/emojis are shared in settings. Account-specific
    fields (name, username, Telegram ID, balance, etc.) are resolved every time
    the message is rendered, so one user's values can never leak into another
    user's message.
    """
    user = get_user(user_id) if user_id else None
    name = first_name or (user[1] if user and len(user) > 1 else "User") or "User"
    phone = phone_number if phone_number is not None else (user[2] if user and len(user) > 2 else "")
    phone = phone or "N/A"
    country = user[3] if user and len(user) > 3 else "IN"
    balance = user[4] if user and len(user) > 4 else 0.0
    ref_balance = user[5] if user and len(user) > 5 else 0.0
    orders = user[6] if user and len(user) > 6 else 0
    lifetime = user[7] if user and len(user) > 7 else 0.0
    deposited = user[8] if user and len(user) > 8 else 0.0
    joined = user[9] if user and len(user) > 9 else "N/A"
    live_username = _get_live_telegram_username(user_id, username)
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return {
        "name": html.escape(str(name), quote=False),
        "first_name": html.escape(str(name), quote=False),
        "username": html.escape(str(live_username), quote=False),
        "username_at": html.escape(f"@{live_username}" if live_username else "", quote=False),
        "user_id": str(user_id),
        "telegram_id": str(user_id),
        "phone": html.escape(str(phone), quote=False),
        "country": html.escape(str(country or "IN"), quote=False),
        "balance": f"{float(balance):.2f}",
        "ref_balance": f"{float(ref_balance):.2f}",
        "orders": str(int(orders or 0)),
        "lifetime": f"{float(lifetime):.2f}",
        "deposited": f"{float(deposited):.2f}",
        "joined": html.escape(str(joined or "N/A"), quote=False),
        "date": now,
    }


def _replace_live_greeting_name(text, name):
    """Replace hard-coded names in common greeting lines with the CURRENT user's name.

    Admin text templates are presentation-only, so an admin may save a previously
    rendered message such as ``Welcome, RG!``. Placeholder/label replacement cannot
    see that name because it is not a labeled field. This helper updates only
    greeting phrases and leaves the rest of the design/text untouched.
    """
    if not text:
        return text

    live_name = html.escape(str(name or "User"), quote=False)
    greeting_re = re.compile(
        r'(?i)(\b(?:welcome(?:\s+back)?|hello)\s*,\s*)'
        r'([^<>\n!]+?)(\s*!?)'
        r'(?=(?:<[^>]+>)*\s*(?:\n|$))'
    )

    def repl(match):
        old_name = match.group(2).strip()
        if not old_name:
            return match.group(0)
        return match.group(1) + live_name + match.group(3)

    return greeting_re.sub(repl, str(text))


def _inject_labeled_user_values(text, values):
    """Replace LIVE values after known labels while preserving the admin's design.

    This is the important anti-leak layer for the text editor: if an admin
    copies a previously rendered message containing e.g. ``Balance: ₹504`` or
    another user's Telegram ID and then saves it as a template, the old value is
    replaced at render time with the current user's live value. Premium
    <tg-emoji> markup and the rest of the line remain untouched.
    """
    if not text:
        return text

    import re

    def replace_label_value(value_text, labels, value, wrap_code=False, allow_empty=False):
        if value is None:
            return value_text
        value = str(value)
        if not allow_empty and value == "":
            return value_text
        label_alt = "|".join(re.escape(x) for x in labels)
        # Replace everything after the matching label's colon on that line.
        # This works whether the label is plain text or wrapped in <b> tags.
        pattern = re.compile(
            r'(?im)^([^\n]*?\b(?:' + label_alt + r')\b[^\n:]*:\s*)([^\n]*)$'
        )
        replacement_value = f'<code>{value}</code>' if wrap_code else value

        def _line_repl(match):
            old_value = match.group(2)
            # Preserve trailing HTML closing tags such as </b> / </i> that were
            # part of the admin's visual design. Only the actual old value is
            # replaced.
            suffix_match = re.search(r'(\s*(?:</[^>]+>\s*)+)$', old_value)
            suffix = suffix_match.group(1) if suffix_match else ''
            return match.group(1) + replacement_value + suffix

        return pattern.sub(_line_repl, value_text)

    # Identity fields
    text = replace_label_value(text, ["Name", "User Name", "First Name"], values.get("name"))
    username = values.get("username") or ""
    username_at = values.get("username_at") or (f"@{username}" if username else "")
    text = replace_label_value(text, ["Username", "Telegram Username"], username_at, allow_empty=False)
    text = replace_label_value(text, ["User ID", "Telegram ID", "Telegram User ID", "Account ID"], values.get("user_id"), wrap_code=True)
    text = replace_label_value(text, ["Phone", "Phone Number", "Mobile Number"], values.get("phone"), wrap_code=True)
    text = replace_label_value(text, ["Country"], values.get("country"))

    # Wallet/profile fields
    text = replace_label_value(text, ["Current Balance", "Wallet Balance", "Your Balance", "Balance"], f'₹{values.get("balance", "0.00")} INR')
    text = replace_label_value(text, ["Ref Balance", "Referral Balance", "Referral Earnings", "Ref Earnings"], f'₹{values.get("ref_balance", "0.00")} INR')
    text = replace_label_value(text, ["Orders", "Order Count", "Total Orders"], values.get("orders"))
    text = replace_label_value(text, ["Lifetime spent", "Lifetime Spent", "Total Spent"], f'₹{values.get("lifetime", "0.00")} INR')
    text = replace_label_value(text, ["Total deposited", "Total Deposited", "Deposited"], f'₹{values.get("deposited", "0.00")} INR')
    text = replace_label_value(text, ["Joined", "Joined Date", "Join Date"], values.get("joined"))

    # Optional transaction/order fields. They are only changed when the caller
    # supplies the corresponding live value.
    for labels, key in [
        (["Product ID", "Product ID Number"], "product_id"),
        (["Product", "Product Name", "Hack", "Hack Purchased"], "product_name"),
        (["Plan", "Plan Days", "Validity"], "plan"),
        (["Order ID", "Order No", "Order Number"], "order_id"),
        (["Price Paid", "Unit Price", "Price", "Amount", "Paid", "Paid Amount"], "amount"),
        (["Method", "Payment Method"], "method"),
        (["Device ID"], "device_id"),
        (["UTR"], "utr"),
        (["Key", "Your Key", "Purchased Key"], "key"),
        (["Date", "Date/Time", "Time"], "date"),
    ]:
        if key in values:
            val = values.get(key)
            if val is not None and str(val) != "":
                text = replace_label_value(text, labels, val, wrap_code=(key in {"order_id", "device_id", "utr", "key"}))

    # Some existing QR templates use ``Order:`` instead of ``Order ID:``.
    # Update only an exact ``Order:`` label so ``Order Details:`` is never touched.
    if "order_id" in values and str(values.get("order_id") or "") != "":
        order_value = str(values.get("order_id"))
        order_pattern = re.compile(r'(?im)^([^\n]*?\bOrder\s*:\s*)([^\n]*)$')

        def _order_repl(match):
            old_value = match.group(2)
            suffix_match = re.search(r'(\s*(?:</[^>]+>\s*)+)$', old_value)
            suffix = suffix_match.group(1) if suffix_match else ''
            return match.group(1) + order_value + suffix

        text = order_pattern.sub(_order_repl, text)

    return text

# Default styles requested for the shop UI.
DEFAULT_MAIN_BUTTON_COLORS = {
    "open_store": "red",
    "top_up": "green",
    "orders": "green",
    "my_account": "green",
    "invite_earn": "green",
    "how_to_use": "green",
    "all_update": "red",
    "help_desk": "red",
}

# ==================== USER PANEL BUTTON COLOR CATALOG ====================
# This catalog contains every user-facing button that is built through
# make_ui_button(), including dynamic Hack and Price/Plan buttons.
# Dynamic items are generated from the current database, so newly added
# hacks/plans automatically appear here without editing this code again.

def get_user_panel_button_catalog():
    """Return every user-facing button key used by the bot.

    Dynamic products/plans are read from the database, so newly added hacks and
    plans automatically appear in the Admin color/emoji panels.
    """
    items = [
        # Main menu
        ("🛍️ Open Store", "main:open_store"),
        ("💰 Top Up", "main:top_up"),
        ("📜 Orders", "main:orders"),
        ("👤 My Account", "main:my_account"),
        ("🎁 Invite & Earn", "main:invite_earn"),
        ("🎬 How To Use", "main:how_to_use"),
        ("📢 All Update File", "main:all_update"),
        ("📞 Help Desk", "main:help_desk"),

        # Reseller My Account controls
        ("🔑 API Generate", "reseller:my_account:api_generate"),
        ("🆔 Product ID & Variant ID", "reseller:my_account:catalog"),
        ("♻️ API Reset", "reseller:my_account:api_reset"),

        # Top-up
        ("💰 ₹100 Top-up", "topup:100"),
        ("💰 ₹250 Top-up", "topup:250"),
        ("💰 ₹500 Top-up", "topup:500"),
        ("💰 ₹1000 Top-up", "topup:1000"),
        ("💰 ₹2000 Top-up", "topup:2000"),
        ("💰 ₹5000 Top-up", "topup:5000"),
        ("✏️ Custom Top-up", "topup:custom"),

        # Payments
        ("💳 Wallet Payment", "payment:wallet"),
        ("🇮🇳 UPI Payment", "payment:upi"),
        ("🎟️ Coupon Code", "payment:coupon"),

        # User Panel navigation/back buttons — all four are intentionally
        # editable in both Button Colors and All Button Emoji.
        ("⬅️ Back to Main", "nav:back_main"),
        ("⬅️ Back to Store", "nav:back_store"),
        ("🔙 Back from Top-up", "nav:back_topup"),
        ("🔙 Back from QR", "nav:back_qr"),
        ("🏠 Success Main Menu", "nav:success_main_menu"),

        # Support / links
        ("💬 Telegram Support", "link:telegram_support"),
        ("📱 WhatsApp Support", "link:whatsapp_support"),
        ("📩 Referral Share", "link:referral_share"),
        ("▶️ Guide Video", "link:guide"),
        ("🔗 Telegram Group", "link:telegram_group"),
        ("❌ Add Balance Cancel", ADD_BALANCE_CANCEL_BUTTON_KEY),
        ("💳 Add Balance Confirm", ADD_BALANCE_CONFIRM_BUTTON_KEY),
        ("🔴 All Products Out of Stock", ALL_PRODUCTS_OUT_OF_STOCK_BUTTON_KEY),
    ]

    for product_name in get_unique_products():
        items.append((f"🛒 {product_name}", f"hack:{product_name}"))
    for plan in _bot_make_plan_rows():
        # Bot Make remains a product-level entry; its plan colors are managed
        # only after selecting that product, exactly like normal products.
        pass

    seen = set()
    unique_items = []
    for title, key in items:
        if key not in seen:
            seen.add(key)
            unique_items.append((title, key))
    return unique_items

def _button_color_name(button_key):
    """Return the saved logical color name for a button key."""
    saved = get_setting(_style_setting_key(button_key))
    if saved in ("red", "blue", "green"):
        return saved
    return None


def show_user_panel_button_emoji_catalog(chat_id, message_id=None):
    """Show every user-facing button and let the admin assign one Premium emoji."""
    items = get_user_panel_button_catalog()
    if not items:
        bot.send_message(chat_id, "⚠️ <b>No user panel buttons found.</b>", parse_mode="HTML")
        return

    # Use the requested compact two-column grid. Navigation entries (including
    # all four requested User Panel Back buttons) stay editable because their
    # catalog-selection callbacks are distinct from Admin navigation callbacks.
    markup = types.InlineKeyboardMarkup(row_width=2)
    catalog = {}
    for index, (title, key) in enumerate(items, 1):
        h = _ui_hash(key)
        catalog[h] = key
        current = bool(get_button_emoji(key))
        icon = "✨" if current else "⚪"
        palette = ("blue", "green", "blue", "green", "red")
        button = _admin_colorful_button(
            f"{icon} {index:02d} · {title}",
            callback_data=f"abe_select_{h}",
            color=palette[(index - 1) % len(palette)]
        )
        if index % 2 == 1:
            markup.row(button)
        else:
            markup.keyboard[-1].append(button)

    admin_temp_data.setdefault(chat_id, {})
    admin_temp_data[chat_id]["all_button_emoji_catalog"] = catalog
    _ensure_admin_back_button(markup)
    panel_text = (
        "✨ <b>ALL BUTTON EMOJI</b>\n\n"
        "Every User Panel button is listed below.\n"
        "Tap a button → send exactly one Premium custom emoji.\n"
        "The old normal leading emoji is automatically hidden.\n\n"
        f"📦 <b>Total buttons:</b> {len(items)}"
    )
    if message_id:
        try:
            bot.edit_message_text(panel_text, chat_id, message_id, parse_mode="HTML", reply_markup=markup)
            _admin_store_snapshot(chat_id,panel_text,markup,"admin_all_button_emoji")
            return
        except Exception:
            pass
    bot.send_message(chat_id, panel_text, parse_mode="HTML", reply_markup=markup)
    _admin_store_snapshot(chat_id,panel_text,markup,"admin_all_button_emoji")

def show_product_button_color_detail(chat_id, product_name, message_id=None):
    plans=get_product_plans(product_name)
    # Plan selectors are the only dynamic children of a selected Product and are
    # intentionally shown in a clean two-column grid.
    markup=types.InlineKeyboardMarkup(row_width=2)
    catalog={}
    for plan in plans:
        pid,_,days,reg,res=plan[:5]
        key=f"price:{product_name}:{pid}"; h=_ui_hash(key); catalog[h]=key
        current=_button_color_name(key)
        icon={"red":"🔴","blue":"🔵","green":"🟢"}.get(current,"⚪")
        markup.add(types.InlineKeyboardButton(f"{icon} {days} · ₹{reg:.0f} / ₹{res:.0f}",callback_data=f"upc_plan_select_{h}"))
    product_key=f"hack:{product_name}"; product_color=_button_color_name(product_key)
    product_icon={"red":"🔴","blue":"🔵","green":"🟢"}.get(product_color,"⚪")
    markup.add(types.InlineKeyboardButton(f"🎨 Product Color {product_icon}",callback_data=f"upc_product_color_{_ui_hash(product_key)}"))
    markup.add(types.InlineKeyboardButton("⬅️ Back to All Buttons",callback_data="upc_back_catalog"))
    admin_temp_data.setdefault(chat_id,{})["product_plan_color_catalog"]=catalog
    admin_temp_data[chat_id]["product_plan_color_product"]=product_name
    text=("🎨 <b>PRODUCT & PLANS COLORS</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
          f"🎮 <b>Product:</b> {html.escape(str(product_name))}\n\n"
          "Select a Plan to set its own color.\n"
          "The Product Color control is kept separately at the bottom.")
    final_markup=_ensure_admin_back_button(markup)
    if message_id:
        try:
            bot.edit_message_text(text,chat_id,message_id,parse_mode='HTML',reply_markup=final_markup)
            _admin_store_snapshot(chat_id,text,final_markup,"upc_product_"+_ui_hash(product_name)); return
        except Exception: pass
    bot.send_message(chat_id,text,parse_mode='HTML',reply_markup=final_markup)
    _admin_store_snapshot(chat_id,text,final_markup,"upc_product_"+_ui_hash(product_name))


def _show_color_picker(call, key, back_callback, title):
    current=_button_color_name(key)
    markup=types.InlineKeyboardMarkup(row_width=3)
    for color,label in (("red","🔴 Red"),("green","🟢 Green"),("blue","🔵 Blue")):
        prefix="✓ " if color==current else ""
        markup.add(types.InlineKeyboardButton(prefix+label,callback_data=f"upc_color_{color}_{_ui_hash(key)}"))
    markup.add(types.InlineKeyboardButton("⬅️ Back",callback_data=back_callback))
    _admin_ui_send(call,title+f"\n\nCurrent: <b>{html.escape(str(current or 'Not Set'))}</b>\n\nChoose a color:",parse_mode='HTML',reply_markup=_ensure_admin_back_button(markup))


def show_user_panel_button_color_catalog(chat_id, message_id=None):
    """Show every user-facing button, then let admin choose Red/Blue/Green."""
    items = get_user_panel_button_catalog()

    if not items:
        bot.send_message(
            chat_id,
            "⚠️ <b>No user panel buttons found.</b>",
            parse_mode="HTML"
        )
        return

    markup = types.InlineKeyboardMarkup(row_width=2)
    catalog = {}

    for index, (title, key) in enumerate(items, 1):
        h = _ui_hash(key)
        catalog[h] = key

        current = _button_color_name(key)
        current_icon = {
            "red": "🔴",
            "blue": "🔵",
            "green": "🟢",
        }.get(current, "⚪")

        palette = ("blue", "green", "blue", "green", "red")
        button = _admin_colorful_button(
            f"{current_icon} {index:02d} · {title}",
            callback_data=f"upc_select_{h}",
            color=palette[(index - 1) % len(palette)]
        )
        if index % 2 == 1:
            markup.row(button)
        else:
            markup.keyboard[-1].append(button)

    # Keep the mapping in admin_temp_data without deleting other admin state.
    admin_temp_data.setdefault(chat_id, {})
    admin_temp_data[chat_id]["user_panel_color_catalog"] = catalog
    _ensure_admin_back_button(markup)

    panel_text = (
        "🎨 <b>USER PANEL BUTTON COLORS</b>\n\n"
        "All user-facing buttons are listed below.\n"
        "Tap any button → choose <b>Red</b>, <b>Green</b> or <b>Blue</b>.\n"
        "The selected color is saved immediately and will be used after the screen is refreshed.\n\n"
        f"📦 <b>Total buttons:</b> {len(items)}"
    )

    if message_id:
        try:
            bot.edit_message_text(
                panel_text,
                chat_id,
                message_id,
                parse_mode="HTML",
                reply_markup=markup
            )
            _admin_store_snapshot(chat_id, panel_text, markup, "admin_button_colors", message_id)
            return
        except Exception:
            pass

    bot.send_message(
        chat_id,
        panel_text,
        parse_mode="HTML",
        reply_markup=markup
    )
    _admin_store_snapshot(chat_id,panel_text,markup,"admin_button_colors")

server_api_url = get_setting('server_api_url') or RESELLER_API_URL
server_api_key = get_setting('server_api_key') or RESELLER_API_KEY
guide_video_url = get_setting('guide_url')

# ==================== DATABASE HELPERS ====================
def record_pending_payment(order_id, user_id, user_name, product_name, plan_days, amount):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    date_now = _now_ist_text("%b %d · %H:%M IST")
    cursor.execute('''
        INSERT INTO pending_payments (order_id, user_id, user_name, product_name, plan_days, amount, date_time)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (order_id, user_id, user_name, product_name, plan_days, amount, date_now))
    conn.commit()
    conn.close()

def get_all_pending_payments():
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('SELECT order_id, user_id, user_name, product_name, plan_days, amount, date_time FROM pending_payments ORDER BY id DESC LIMIT 20')
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_user(user_id):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def get_all_users():
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, first_name, phone_number, balance FROM users WHERE is_verified = 1')
    users = cursor.fetchall()
    conn.close()
    return users

def _get_all_users_admin():
    """Return every account for the Admin User List (verified or not).

    The older get_all_users() helper is intentionally kept unchanged because
    broadcasts/discount notifications historically target verified users.
    Admin tracking, however, must show every account stored in the database.
    """
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        return conn.execute(
            """SELECT user_id, first_name, phone_number, balance, is_verified,
                      is_reseller, is_banned, joined_date
                 FROM users
                 ORDER BY user_id ASC"""
        ).fetchall()
    finally:
        conn.close()


def _admin_user_list_markup(page=0, page_size=20):
    """Two-column, paginated Admin list containing every stored user."""
    try:
        page = max(0, int(page))
    except Exception:
        page = 0
    page_size = max(2, int(page_size))
    rows = _get_all_users_admin()
    total = len(rows)
    start = page * page_size
    end = min(start + page_size, total)
    visible = rows[start:end]

    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for row in visible:
        uid = int(row[0])
        name = str(row[1] or 'Unnamed User').strip()
        if len(name) > 19:
            name = name[:18] + '…'
        role = '👑' if int(row[5] or 0) else '👤'
        verified = '✅' if int(row[4] or 0) else '⚪'
        label = f'{role}{verified} {name}\n🆔 {uid}'
        buttons.append(types.InlineKeyboardButton(
            label[:64],
            callback_data=f'track_uid_{uid}_{page}'
        ))
    for i in range(0, len(buttons), 2):
        markup.row(*buttons[i:i+2])

    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton(
            '⬅️ Previous', callback_data=f'admin_track_users_page_{page-1}'
        ))
    if end < total:
        nav.append(types.InlineKeyboardButton(
            'Next ➡️', callback_data=f'admin_track_users_page_{page+1}'
        ))
    if nav:
        markup.row(*nav)

    markup.row(
        types.InlineKeyboardButton('🔎 Search Users / Resellers', callback_data='admin_user_reseller_search'),
        types.InlineKeyboardButton('👑 Reseller List', callback_data='admin_reseller_list')
    )
    markup.add(types.InlineKeyboardButton('🔙 Users & Resellers', callback_data='admin_cat_users'))
    return markup, total, (start + 1 if visible else 0), end


def _send_admin_user_list(call, page=0):
    markup, total, first_no, last_no = _admin_user_list_markup(page)
    active_users, active_resellers, active_window = _admin_recent_activity_counts(5)
    if total == 0:
        text = (
            '👥 <b>ALL USERS</b>\n'
            '━━━━━━━━━━━━━━━━━━━━\n\n'
            '<i>No user accounts are stored in the database.</i>'
        )
    else:
        text = (
            '👥 <b>ALL USERS</b>\n'
            '━━━━━━━━━━━━━━━━━━━━\n\n'
            f'📊 <b>Total:</b> {total} accounts\n'
            f'🟢 <b>Active:</b> {active_users} (last {active_window} min)\n'
            f'📄 <b>Showing:</b> {first_no}-{last_no}\n\n'
            '<i>👑 = Reseller   ✅ = Verified   ⚪ = Not verified</i>'
        )
    _admin_ui_send(call, text, parse_mode='HTML', reply_markup=markup)


def save_or_update_user(user_id, first_name, phone_number=None, verified=0, referred_by=0):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    today_date = datetime.datetime.now().strftime("%Y-%m-%d IST")
    cursor.execute('''
        INSERT INTO users (user_id, first_name, phone_number, joined_date, is_verified, referred_by)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            first_name = excluded.first_name,
            phone_number = COALESCE(excluded.phone_number, users.phone_number),
            is_verified = CASE WHEN excluded.is_verified = 1 THEN 1 ELSE users.is_verified END
    ''', (user_id, first_name, phone_number, today_date, verified, referred_by))
    conn.commit()
    conn.close()

def reset_user_completely_db(user_id):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return success


# Bulk user reset snapshot. This is stored beside the live DB and contains a
# full SQLite snapshot, but restore copies back only user-owned tables so that
# products, plans, country catalogs, API/server configuration and bot settings
# remain untouched.
USER_RESET_BACKUP_PATH = BOT_DB_PATH.with_name(BOT_DB_PATH.stem + ".users_reset_backup.db")
_USER_RESET_TABLES = (
    "users", "order_history", "pending_payments", "processed_payments",
    "reseller_api_credentials", "reseller_api_idempotency",
    "bot_make_orders", "custom_plan_prices",
)

def _user_reset_admin_ids():
    ids = set()
    for value in list(globals().get("ADMIN_IDS", []) or []) + list(globals().get("_HARDCODED_ROOT_ADMIN_IDS", []) or []):
        try:
            ids.add(int(value))
        except Exception:
            pass
    return ids

def _create_user_reset_snapshot():
    if USER_RESET_BACKUP_PATH.exists():
        raise RuntimeError("A user-reset backup already exists. Restore it before starting another bulk reset.")
    USER_RESET_BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(str(BOT_DB_PATH), timeout=30)
    target = sqlite3.connect(str(USER_RESET_BACKUP_PATH), timeout=30)
    try:
        source.backup(target)
        target.commit()
    except Exception:
        target.close()
        source.close()
        try:
            USER_RESET_BACKUP_PATH.unlink()
        except Exception:
            pass
        raise
    finally:
        try: target.close()
        except Exception: pass
        try: source.close()
        except Exception: pass

def reset_all_users_and_resellers_db():
    # Create a recoverable snapshot before changing anything.
    _create_user_reset_snapshot()
    admin_ids = _user_reset_admin_ids()
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=30)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        placeholders = ",".join("?" for _ in admin_ids)
        if admin_ids:
            cur.execute(f"DELETE FROM users WHERE user_id NOT IN ({placeholders})", tuple(sorted(admin_ids)))
        else:
            cur.execute("DELETE FROM users")
        for table in _USER_RESET_TABLES:
            if table == "users":
                continue
            exists = cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if exists:
                cur.execute(f'DELETE FROM "{table}"')
        # Preserve coupon definitions/codes but clear their per-user usage.
        if cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='coupons'").fetchone():
            cols = {r[1] for r in cur.execute('PRAGMA table_info(coupons)').fetchall()}
            updates = []
            if "used_by" in cols: updates.append("used_by=0")
            if "used_at" in cols: updates.append("used_at=''")
            if updates: cur.execute("UPDATE coupons SET " + ", ".join(updates))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        try: USER_RESET_BACKUP_PATH.unlink()
        except Exception: pass
        raise
    finally:
        conn.close()

def restore_all_users_and_resellers_db():
    if not USER_RESET_BACKUP_PATH.is_file():
        raise FileNotFoundError("No saved user-reset backup is available.")
    live = sqlite3.connect(str(BOT_DB_PATH), timeout=30)
    snap = sqlite3.connect(str(USER_RESET_BACKUP_PATH), timeout=30)
    admin_ids = _user_reset_admin_ids()
    try:
        live.execute("PRAGMA foreign_keys=OFF")
        live.execute("BEGIN IMMEDIATE")
        cur = live.cursor()
        # Restore ordinary users/resellers from the snapshot while preserving
        # current admin accounts and the existing product/configuration tables.
        if admin_ids:
            marks = ",".join("?" for _ in admin_ids)
            cur.execute(f"DELETE FROM users WHERE user_id NOT IN ({marks})", tuple(sorted(admin_ids)))
        else:
            cur.execute("DELETE FROM users")
        snap_users = snap.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
        if snap_users:
            snap_cols = [r[1] for r in snap.execute('PRAGMA table_info(users)').fetchall()]
            live_cols = {r[1] for r in cur.execute('PRAGMA table_info(users)').fetchall()}
            common = [col for col in snap_cols if col in live_cols]
            if common:
                names = ",".join('"' + col.replace('"','""') + '"' for col in common)
                rows = snap.execute(f'SELECT {names} FROM users').fetchall()
                for row in rows:
                    if admin_ids and int(row[0] or 0) in admin_ids:
                        continue
                    cur.execute(f'INSERT OR REPLACE INTO users ({names}) VALUES ({",".join("?" for _ in common)})', row)
        for table in _USER_RESET_TABLES:
            if table == "users":
                continue
            has_snap = snap.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            has_live = cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not (has_snap and has_live):
                continue
            cur.execute(f'DELETE FROM "{table}"')
            snap_cols = [r[1] for r in snap.execute(f'PRAGMA table_info("{table}")').fetchall()]
            live_cols = {r[1] for r in cur.execute(f'PRAGMA table_info("{table}")').fetchall()}
            common = [col for col in snap_cols if col in live_cols]
            if common:
                names = ",".join('"' + col.replace('"','""') + '"' for col in common)
                rows = snap.execute(f'SELECT {names} FROM "{table}"').fetchall()
                cur.executemany(f'INSERT OR REPLACE INTO "{table}" ({names}) VALUES ({",".join("?" for _ in common)})', rows)
        # Restore prior coupon usage only; keep any coupon definitions created since reset.
        has_coupons = snap.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='coupons'").fetchone()
        if has_coupons and cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='coupons'").fetchone():
            snap_cols = {r[1] for r in snap.execute('PRAGMA table_info(coupons)').fetchall()}
            live_cols = {r[1] for r in cur.execute('PRAGMA table_info(coupons)').fetchall()}
            if "code" in snap_cols and "code" in live_cols:
                usage = [x for x in ("used_by", "used_at") if x in snap_cols and x in live_cols]
                if usage:
                    fields = ",".join('"' + x + '"' for x in usage)
                    for row in snap.execute(f'SELECT code,{fields} FROM coupons').fetchall():
                        cur.execute(f'UPDATE coupons SET {",".join(chr(34)+x+chr(34)+"=?" for x in usage)} WHERE code=?', tuple(row[1:]) + (row[0],))
        live.commit()
    except Exception:
        live.rollback()
        raise
    finally:
        live.close()
        snap.close()
    try:
        USER_RESET_BACKUP_PATH.unlink()
    except Exception:
        pass
    return True

def set_reseller_status(user_id, status=1):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_reseller = ? WHERE user_id = ?', (status, user_id))
    conn.commit()
    conn.close()

def reward_referrer_discount(referrer_id):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET referrals_count = referrals_count + 1, balance = balance + 2.0, ref_balance = ref_balance + 2.0 WHERE user_id = ?', (referrer_id,))
    conn.commit()
    conn.close()

def mark_ref_discount_used(user_id):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET discount_percent = 0.0, ref_discount_used = 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def claim_processed_payment(order_id, user_id, payment_type, amount):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    try:
        cursor.execute(
            'INSERT INTO processed_payments (order_id, user_id, payment_type, amount, date_time) VALUES (?, ?, ?, ?, ?)',
            (str(order_id), int(user_id), str(payment_type), float(amount), datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        conn.rollback()
        return False
    finally:
        conn.close()

def add_user_balance(user_id, amount):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = balance + ?, total_deposited = total_deposited + ? WHERE user_id = ?', (amount, amount, user_id))
    conn.commit()
    conn.close()

def deduct_user_balance(user_id, amount):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?', (amount, user_id, amount))
    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return success

def refund_user_balance(user_id, amount):
    """Refund a failed wallet checkout without changing total_deposited."""
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (float(amount), int(user_id)))
        conn.commit()
    finally:
        conn.close()


def modify_user_balance_manual(user_id, amount, is_add=True):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    if is_add:
        cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    else:
        cursor.execute('UPDATE users SET balance = MAX(0.0, balance - ?) WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()

def add_product_db(name, pid_id, days, price, resell_price, is_manual=0, remote_duration=''):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('SELECT MAX(display_order) FROM products')
    max_ord = cursor.fetchone()[0]
    next_order = (max_ord + 1) if max_ord is not None else 0
    cursor.execute('INSERT INTO products (name, pid_id, days, price, resell_price, is_manual, remote_duration, display_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (name, pid_id, days, price, resell_price, is_manual, remote_duration, next_order))
    conn.commit()
    conn.close()

def update_product_name_db(old_name, new_name):
    old_name = str(old_name or '').strip()
    new_name = str(new_name or '').strip()
    if not old_name or not new_name:
        return False, 'Hack name cannot be empty.'
    if old_name == new_name:
        return True, 'No name change was needed.'
    if new_name in get_unique_products():
        return False, 'Another hack already uses that name.'
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        conn.execute('UPDATE products SET name=? WHERE name=?', (new_name, old_name))
        conn.execute('UPDATE panels SET panel_name=? WHERE panel_name=?', (new_name, old_name))
        conn.commit()
    finally:
        conn.close()

    # Migrate per-hack UI templates and button settings so renaming a hack does
    # not silently disconnect its existing premium design.
    for prefix_fn in (_hack_price_ui_key, _plan_text_product_key):
        try:
            old_key = prefix_fn(old_name)
            new_key = prefix_fn(new_name)
            old_val = get_setting(old_key)
            if old_val is not None:
                set_setting(new_key, old_val)
        except Exception:
            pass
    for suffix in ('hack',):
        try:
            old_style = get_setting(_style_setting_key(f'{suffix}:{old_name}'))
            old_emoji = get_setting(_emoji_setting_key(f'{suffix}:{old_name}'))
            if old_style is not None:
                set_setting(_style_setting_key(f'{suffix}:{new_name}'), old_style)
            if old_emoji is not None:
                set_setting(_emoji_setting_key(f'{suffix}:{new_name}'), old_emoji)
        except Exception:
            pass
    # Plan IDs stay unchanged, so copy price-button customizations to the new
    # product-key namespace after the rename.
    try:
        for plan in get_product_plans(new_name):
            pid = plan[0]
            old_key = f'price:{old_name}:{pid}'
            new_key = f'price:{new_name}:{pid}'
            old_style = get_setting(_style_setting_key(old_key))
            old_emoji = get_setting(_emoji_setting_key(old_key))
            if old_style is not None:
                set_setting(_style_setting_key(new_key), old_style)
            if old_emoji is not None:
                set_setting(_emoji_setting_key(new_key), old_emoji)
    except Exception:
        pass
    return True, 'Hack name updated successfully.'

def update_product_price_db(plan_id, new_price, new_resell_price):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('UPDATE products SET price = ?, resell_price = ? WHERE id = ?', (new_price, new_resell_price, plan_id))
    conn.commit()
    conn.close()

def update_product_plan_days_db(plan_id, new_days):
    new_days = str(new_days or '').strip()
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        row = conn.execute('SELECT name, days FROM products WHERE id=?', (int(plan_id),)).fetchone()
        if not row:
            return False
        product_name, old_days = row
        conn.execute('UPDATE products SET days=?, remote_duration=? WHERE id=?', (new_days, new_days, int(plan_id)))
        # Manual FIFO keys are indexed by product + validity label. Keep them
        # attached to the edited plan so an admin changing 10 Days -> 15 Days
        # does not strand the existing key stock.
        conn.execute('UPDATE panels SET validity_days=? WHERE panel_name=? AND validity_days IN (?,?)',
                     (new_days, product_name, str(old_days or '').strip(), _clean_plan_days(old_days)))
        for table in ('hack_server_plan_ids','new_server_plan_ids'):
            try:
                conn.execute(f'UPDATE {table} SET plan_days=? WHERE product_name=? AND plan_id=?', (new_days, product_name, int(plan_id)))
            except Exception:
                pass
        try:
            conn.execute('UPDATE api_server_plan_ids SET plan_days=? WHERE product_name=? AND plan_id=?', (new_days, product_name, int(plan_id)))
        except Exception:
            pass
        conn.commit()
        return True
    finally:
        conn.close()

def update_product_api_mapping(plan_id, pid_id, remote_duration):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('UPDATE products SET pid_id = ?, remote_duration = ? WHERE id = ?', (str(pid_id), str(remote_duration), plan_id))
    conn.commit()
    conn.close()

def set_hack_tg_group(product_name, group_link):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('UPDATE products SET tg_group_link = ? WHERE name = ?', (group_link, product_name))
    conn.commit()
    conn.close()

def set_plan_stock_status(plan_id, is_out_of_stock):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('UPDATE products SET is_out_of_stock = ? WHERE id = ?', (is_out_of_stock, plan_id))
    conn.commit()
    conn.close()

def set_plan_device_id_status(plan_id, require_device_id):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('UPDATE products SET require_device_id = ? WHERE id = ?', (require_device_id, plan_id))
    conn.commit()
    conn.close()

def add_key_db(panel_name, days_plan, panel_key):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO panels (panel_name, panel_price, panel_key, validity_days) VALUES (?, 0, ?, ?)', (panel_name, panel_key, days_plan))
    conn.commit()
    conn.close()


def add_keys_db_bulk(panel_name, days_plan, raw_keys):
    """Save multiple manual keys in FIFO order from one admin message."""
    parts = [x.strip() for x in re.split(r"\s+", str(raw_keys or "").strip()) if x.strip()]
    if not parts:
        return 0
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        conn.executemany(
            'INSERT INTO panels (panel_name, panel_price, panel_key, validity_days) VALUES (?, 0, ?, ?)',
            [(str(panel_name), key, str(days_plan)) for key in parts]
        )
        conn.commit()
        return len(parts)
    finally:
        conn.close()

def delete_entire_hack_db(name):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM products WHERE name = ?', (name,))
    conn.commit()
    conn.close()

def delete_product_plan_db(plan_id):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM products WHERE id = ?', (plan_id,))
    conn.commit()
    conn.close()

def set_user_discount_db(user_id, percent):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET discount_percent = ?, ref_discount_used = 0 WHERE user_id = ?', (percent, user_id))
    conn.commit()
    conn.close()

def set_global_discount_db(percent):
    try:
        percent = max(0.0, min(100.0, float(percent)))
    except Exception:
        percent = 0.0
    set_setting('global_discount', str(percent))
    if percent == 0.0:
        # A 0% global discount is the explicit reset requested by the admin:
        # clear per-hack discounts too, then return every product/plan button to blue.
        conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
        cursor = conn.cursor()
        cursor.execute('UPDATE products SET discount_percent = 0.0')
        conn.commit()
        conn.close()
    # Global discount controls the default product/price color for every hack.
    sync_all_product_button_colors()

def set_product_discount_db(product_name, percent):
    try:
        percent = max(0.0, min(100.0, float(percent)))
    except Exception:
        percent = 0.0
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('UPDATE products SET discount_percent = ? WHERE name = ?', (percent, product_name))
    conn.commit()
    conn.close()
    # Green when this hack has an active discount; blue again at 0% unless a
    # global discount is still active.
    sync_product_button_colors(product_name)

def _product_hidden(product_name):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        row = conn.execute('SELECT hidden FROM product_visibility WHERE product_name=?', (str(product_name),)).fetchone()
        return bool(int(row[0] or 0)) if row else False
    finally:
        conn.close()

def _plan_hidden(plan_id):
    try:
        pid = int(plan_id)
    except (TypeError, ValueError):
        return False
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        row = conn.execute('SELECT hidden FROM plan_visibility WHERE plan_id=?', (pid,)).fetchone()
        return bool(int(row[0] or 0)) if row else False
    finally:
        conn.close()

def _set_product_hidden(product_name, hidden):
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        conn.execute('''INSERT INTO product_visibility(product_name,hidden,updated_at) VALUES(?,?,?)
                        ON CONFLICT(product_name) DO UPDATE SET hidden=excluded.hidden,updated_at=excluded.updated_at''',
                     (str(product_name), 1 if hidden else 0, now))
        conn.commit()
    finally:
        conn.close()

def _set_plan_hidden(plan_id, hidden):
    pid = int(plan_id)
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        conn.execute('''INSERT INTO plan_visibility(plan_id,hidden,updated_at) VALUES(?,?,?)
                        ON CONFLICT(plan_id) DO UPDATE SET hidden=excluded.hidden,updated_at=excluded.updated_at''',
                     (pid, 1 if hidden else 0, now))
        conn.commit()
    finally:
        conn.close()

def get_unique_products(include_hidden=True):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        if include_hidden:
            rows = conn.execute('''SELECT name, MIN(display_order) as ord
                                  FROM products WHERE COALESCE(is_bot_make,0)=0
                                  GROUP BY name ORDER BY ord ASC, name ASC''').fetchall()
        else:
            rows = conn.execute('''SELECT p.name, MIN(p.display_order) as ord
                                  FROM products p
                                  LEFT JOIN product_visibility v ON v.product_name=p.name
                                  WHERE COALESCE(p.is_bot_make,0)=0 AND COALESCE(v.hidden,0)=0
                                  GROUP BY p.name ORDER BY ord ASC, p.name ASC''').fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()

def get_visible_products():
    return get_unique_products(include_hidden=False)

def move_hack_order(product_name, direction):
    products = get_unique_products()
    if product_name not in products:
        return
    idx = products.index(product_name)
    if direction == "up" and idx > 0:
        other_name = products[idx - 1]
    elif direction == "down" and idx < len(products) - 1:
        other_name = products[idx + 1]
    else:
        return

    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('SELECT MIN(display_order) FROM products WHERE name = ?', (product_name,))
    order1 = cursor.fetchone()[0] or 0
    cursor.execute('SELECT MIN(display_order) FROM products WHERE name = ?', (other_name,))
    order2 = cursor.fetchone()[0] or 0

    if order1 == order2:
        order1, order2 = idx, (idx - 1 if direction == "up" else idx + 1)

    cursor.execute('UPDATE products SET display_order = ? WHERE name = ?', (order2, product_name))
    cursor.execute('UPDATE products SET display_order = ? WHERE name = ?', (order1, other_name))
    conn.commit()
    conn.close()


def set_hack_position(product_name, position):
    """Place a hack at an exact 1-based position and normalize the list order."""
    products = get_unique_products()
    if product_name not in products:
        return False, len(products)
    try:
        position = int(position)
    except (TypeError, ValueError):
        return False, len(products)
    position = max(1, min(position, len(products)))
    products.remove(product_name)
    products.insert(position - 1, product_name)
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        for idx, name in enumerate(products, 1):
            conn.execute('UPDATE products SET display_order = ? WHERE name = ?', (idx, name))
        conn.commit()
    finally:
        conn.close()
    return True, position

def _explicit_legacy_server_connected():
    """Return whether the old single-server API has been explicitly tested.

    The historical constants are kept as fallbacks for compatibility, but they
    are NOT treated as product stock merely because they exist in the source.
    This prevents a newly-created product with no real API mapping from falsely
    appearing in stock.
    """
    return str(get_setting("legacy_server_connected") or "0") == "1"


def _hack_server_source_ready(product_name, plan_id=None):
    cfg = _hack_server_config(product_name)
    if not cfg or not cfg[1] or not cfg[2] or not cfg[3]:
        return False
    if str(get_setting(f"hack_server_connected_{_ui_hash(product_name)}") or "0") != "1":
        return False
    if plan_id is not None and not _hack_server_plan_valid_id(product_name, plan_id):
        return False
    return True


def _new_server_source_ready(product_name, plan_id=None):
    cfg = _new_server_config(product_name)
    if not cfg or not cfg[1] or not cfg[2] or not cfg[3]:
        return False
    if str(get_setting(NEW_SERVER_ENABLED_KEY) or "0") != "1":
        return False
    if plan_id is not None and not _new_server_plan_valid_id(product_name, plan_id):
        return False
    return True


def _multi_api_source_ready(product_name, plan_id=None):
    if not product_name:
        return False
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        row = conn.execute(
            """SELECT s.id,s.api_key,s.server_url,s.enabled,p.product_id
               FROM product_server_selection sel
               JOIN api_servers s ON s.id=sel.server_id
               JOIN api_server_products p
                 ON p.server_id=s.id AND p.product_name=sel.product_name
               WHERE sel.product_name=? LIMIT 1""",
            (str(product_name),)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return False
    sid, api_key, server_url, enabled, product_id = row
    if not int(enabled or 0) or not api_key or not server_url or not product_id:
        return False
    if plan_id is not None and not _api_server_plan_valid_id(sid, product_name, plan_id):
        return False
    return True


def _legacy_global_api_source_ready(product_name, plan_id=None):
    if not _explicit_legacy_server_connected():
        return False
    if not get_setting("server_api_url") or not get_setting("server_api_key"):
        return False
    # The legacy root route has no per-plan Valid ID requirement in its original
    # contract, so it is considered ready after an explicit connection test.
    return True



# ==================== TobiX SELLER API SYSTEM ====================
def _tobix_base_url(value=None):
    url = str(value if value is not None else get_setting(TOBIX_API_URL_KEY) or TOBIX_DEFAULT_API_URL).strip().strip('`').rstrip('/')
    if not re.match(r'^https?://', url, re.I):
        return ''
    for suffix in ('/api/seller/create-key', '/api/seller/me', '/api/seller/keys', '/api/seller/pricing', '/api'):
        if url.lower().endswith(suffix):
            url = url[:-len(suffix)].rstrip('/')
            break
    return url

def _tobix_api_token():
    return str(get_setting(TOBIX_API_TOKEN_KEY) or '').strip()

def _tobix_product_map():
    try:
        data = json.loads(get_setting(TOBIX_PRODUCT_MAP_KEY) or '{}')
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _tobix_product_enabled(product_name):
    return bool(_tobix_product_map().get(str(product_name), False))

def _set_tobix_product_enabled(product_name, enabled):
    data = _tobix_product_map()
    data[str(product_name)] = bool(enabled)
    set_setting(TOBIX_PRODUCT_MAP_KEY, json.dumps(data, ensure_ascii=False, separators=(',', ':')))

def _tobix_plan_days(value):
    text = str(value or '').strip().lower()
    m = re.fullmatch(r'(\d+)\s*days?', text)
    if m:
        return int(m.group(1))
    if text.isdigit():
        return int(text)
    return None

def _tobix_source_ready_for_plan(product_name, plan_id=None, duration=None):
    if not product_name or _product_hidden(product_name):
        return False
    if not _tobix_api_token() or not _tobix_base_url() or str(get_setting('tobix_api_connected') or '0') != '1':
        return False
    if not _tobix_product_enabled(product_name):
        return False
    if plan_id is not None:
        if _plan_hidden(plan_id):
            return False
        if duration is None:
            try:
                row = {int(x[0]): x for x in get_product_plans(product_name)}.get(int(plan_id))
                duration = row[2] if row else ''
            except Exception:
                duration = ''
    return _tobix_plan_days(duration) is not None if duration is not None else True

def _tobix_check_connection():
    token, base = _tobix_api_token(), _tobix_base_url()
    if not token:
        return False, 'TobiX API Token is not configured.', None
    if not base:
        return False, 'Invalid TobiX Server URL.', None
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json', 'User-Agent': 'RG-Cheat-Shop-Bot/TobiX'}
    try:
        response = HTTP_SESSION.get(f'{base}/api/seller/me', headers=headers, timeout=15)
        raw = response.text.strip()
        try:
            data = response.json()
        except Exception:
            data = {}
        ok = response.status_code == 200 and isinstance(data, dict) and data.get('success') is not False
        set_setting('tobix_api_connected', '1' if ok else '0')
        if ok:
            balance = data.get('balance')
            if balance is None and isinstance(data.get('credits'), dict):
                balance = data['credits'].get('balance')
            return True, (f'Balance: {balance}' if balance is not None else 'Authentication successful.'), data
        code = data.get('error') if isinstance(data, dict) else ''
        msg = data.get('message') if isinstance(data, dict) else ''
        detail = f'{code}: {msg}'.strip(': ') if (code or msg) else f'HTTP {response.status_code}: {raw[:300]}'
        return False, detail[:500], data
    except Exception as exc:
        set_setting('tobix_api_connected', '0')
        return False, str(exc)[:500], None

def _tobix_generate_key(duration, purchase_ref=None, note=''):
    token, base, days = _tobix_api_token(), _tobix_base_url(), _tobix_plan_days(duration)
    if not token or not base or days is None:
        print(f'[TobiX] invalid configuration/duration: url={bool(base)} token={bool(token)} duration={duration!r}')
        return None
    purchase_ref = purchase_ref or f'RG-{time.time_ns()}-{random.randint(100000,999999)}'
    idem = hashlib.sha256(f'tobix|{purchase_ref}'.encode()).hexdigest()[:48]
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json', 'Content-Type': 'application/json', 'Idempotency-Key': idem, 'User-Agent': 'RG-Cheat-Shop-Bot/TobiX'}
    payload = {'days': days}
    if note:
        payload['note'] = str(note)[:200]
    try:
        response = HTTP_SESSION.post(f'{base}/api/seller/create-key', json=payload, headers=headers, timeout=30)
        raw = response.text.strip()
        try:
            data = response.json()
        except Exception:
            data = {}
        print(f'[TobiX] create-key status={response.status_code} days={days} response={raw[:1500]}')
        if response.status_code in (200, 201, 202, 409) and isinstance(data, dict) and data.get('success') is not False:
            obj = data.get('key') if isinstance(data.get('key'), dict) else data
            key = obj.get('license_key') or obj.get('licenseKey') or obj.get('key')
            if key:
                return str(key).strip()
        return None
    except Exception as exc:
        print(f'[TobiX] create-key exception: {str(exc)[:500]}')
        return None

def _tobix_product_by_hash(value):
    for name in get_unique_products():
        if _ui_hash(name) == str(value):
            return name
    return None

def _tobix_api_markup():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        _admin_colorful_button('🔑 API Token', callback_data='tobix_set_token', color='green'),
        _admin_colorful_button('🌐 Server Link', callback_data='tobix_set_url', color='blue')
    )
    m.add(
        _admin_colorful_button('🔍 Check Connection', callback_data='tobix_check', color='green'),
        _admin_colorful_button('🎮 Connect Hacks', callback_data='tobix_products', color='blue')
    )
    m.add(_admin_colorful_button('🔙 API & Servers', callback_data='admin_api_system', color='red'))
    return _style_admin_markup(_ensure_admin_back_button(m))

def _send_tobix_panel(call):
    status = '🟢 CONNECTED' if str(get_setting('tobix_api_connected') or '0') == '1' else '🔴 NOT CONNECTED'
    token, url = _tobix_api_token(), _tobix_base_url()
    token_line = f'<code>{html.escape(token[:8])}••••••</code>' if token else '<i>Not Set</i>'
    url_line = f'<code>{html.escape(url)}</code>' if url else '<i>Not Set</i>'
    _admin_ui_send(call,
        '🟢 <b>TobiX API CONNECT</b>\n━━━━━━━━━━━━━━━━━━━━\n\n'
        f'📡 <b>Status:</b> {status}\n🌐 <b>Server:</b> {url_line}\n🔑 <b>API Token:</b> {token_line}\n\n'
        '📡 <b>Method:</b> Bearer Token + JSON POST\n'
        '🔗 <b>Check:</b> <code>GET /api/seller/me</code>\n'
        '🔑 <b>Generate:</b> <code>POST /api/seller/create-key</code>\n'
        '📅 <b>Duration:</b> selected plan duration is sent as <code>days</code>.\n\n'
        '<i>Connect a hack below to route its supported plans through TobiX.</i>',
        parse_mode='HTML', reply_markup=_tobix_api_markup())

def _tobix_products_markup():
    m = types.InlineKeyboardMarkup(row_width=2)
    for name in get_unique_products():
        enabled = _tobix_product_enabled(name)
        m.add(_admin_colorful_button(
            f"{'🟢' if enabled else '⚪'} {name}",
            callback_data=f'tobix_product_{_ui_hash(name)}',
            color='green' if enabled else 'blue'
        ))
    m.add(_admin_colorful_button('🔙 TobiX API System', callback_data='tobix_api_system', color='red'))
    return _style_admin_markup(_ensure_admin_back_button(m))

def step_save_tobix_token(message):
    uid = int(message.from_user.id)
    if not _is_admin(uid):
        return
    token = (message.text or '').strip()
    if not token:
        m = bot.send_message(message.chat.id, '❌ <b>TobiX API Token cannot be empty.</b> Enter it again.', parse_mode='HTML')
        bot.register_next_step_handler(m, step_save_tobix_token)
        return
    admin_temp_data.setdefault(uid, {})['tobix_api_token'] = token
    m = bot.send_message(message.chat.id, '🌐 <b>Enter TobiX Server Link:</b>\n\nExample: <code>http://140.245.202.76</code>', parse_mode='HTML')
    bot.register_next_step_handler(m, step_save_tobix_url)

def step_save_tobix_url(message):
    uid = int(message.from_user.id)
    if not _is_admin(uid):
        return
    data = admin_temp_data.setdefault(uid, {})
    token = str(data.get('tobix_api_token') or _tobix_api_token()).strip()
    url = _tobix_base_url((message.text or '').strip())
    if not token:
        m = bot.send_message(message.chat.id, '❌ TobiX API Token is missing. Start again.')
        bot.register_next_step_handler(m, step_save_tobix_token)
        return
    if not url:
        m = bot.send_message(message.chat.id, '❌ Invalid Server Link. Send a valid http:// or https:// URL.')
        bot.register_next_step_handler(m, step_save_tobix_url)
        return
    set_setting(TOBIX_API_TOKEN_KEY, token)
    set_setting(TOBIX_API_URL_KEY, url)
    set_setting('tobix_api_connected', '0')
    admin_temp_data.pop(uid, None)
    ok, detail, _ = _tobix_check_connection()
    bot.send_message(message.chat.id,
        f'🟢 <b>TobiX API SAVED</b>\n\n🌐 <code>{html.escape(url)}</code>\n'
        f"{'🟢 Connected Successfully!' if ok else '🔴 Not Connected'}\nℹ️ {html.escape(str(detail))}",
        parse_mode='HTML', reply_markup=_tobix_api_markup())

# ==================== 9X API SYSTEM (SINGLE DEVICE ONLY) ====================
def _ninex_base_url(value=None):
    url = str(value if value is not None else get_setting(NINEX_API_URL_KEY) or NINEX_DEFAULT_API_URL).strip().rstrip('/')
    if not re.match(r'^https?://', url, re.I):
        return ''
    for suffix in ('/api/seller/create-user', '/api/seller/me', '/api/seller/pricing', '/api/seller/users', '/api/seller/reset-hwid', '/api'):
        if url.lower().endswith(suffix):
            url = url[:-len(suffix)].rstrip('/')
            break
    return url

def _ninex_api_token():
    return str(get_setting(NINEX_API_TOKEN_KEY) or '').strip()

def _ninex_product_map():
    try:
        data = json.loads(get_setting(NINEX_PRODUCT_MAP_KEY) or '{}')
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _ninex_product_enabled(product_name):
    return bool(_ninex_product_map().get(str(product_name), False))

def _set_ninex_product_enabled(product_name, enabled):
    data = _ninex_product_map()
    data[str(product_name)] = bool(enabled)
    set_setting(NINEX_PRODUCT_MAP_KEY, json.dumps(data, ensure_ascii=False, separators=(',', ':')))

def _ninex_plan_days(value):
    # 9X accepts only its actual 10/20/30-day plans. Never interpret an
    # unrelated label such as "10 Hours" as 10 days.
    text = str(value or '').strip().lower()
    if re.fullmatch(r'(10|20|30)\s*days?', text):
        return int(re.search(r'10|20|30', text).group(0))
    if text in {'10', '20', '30'}:
        return int(text)
    return None

def _ninex_source_ready_for_plan(product_name, plan_id=None, duration=None):
    # 9X is a generic seller API: once the Admin supplies a valid token +
    # server link, every configured hack can use it for supported plans.
    # Product enable/mapping is intentionally not required for delivery.
    if not _ninex_api_token() or not _ninex_base_url():
        return False
    if str(get_setting('ninex_api_connected') or '0') != '1':
        return False
    # A globally connected 9X account must not silently become Auto-API stock
    # for every product. The product must be explicitly enabled in 9X setup.
    if not _ninex_product_enabled(product_name):
        return False
    if plan_id is not None and duration is None:
        try:
            row = {int(x[0]): x for x in get_product_plans(product_name)}.get(int(plan_id))
            duration = row[2] if row else ''
        except Exception:
            duration = ''
    if duration is not None and _ninex_plan_days(duration) is None:
        return False
    return True

def _ninex_check_connection():
    token, base = _ninex_api_token(), _ninex_base_url()
    if not token: return False, '9X API Token is not configured.', None
    if not base: return False, 'Invalid 9X Server URL.', None
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json', 'User-Agent': 'RG-Cheat-Shop-Bot/9X'}
    try:
        response = HTTP_SESSION.get(f'{base}/api/seller/me', headers=headers, timeout=15)
        raw = response.text.strip()
        try: data = response.json()
        except Exception: data = {}
        if response.status_code == 200 and isinstance(data, dict) and data.get('success') is not False:
            set_setting('ninex_api_connected', '1')
            balance = data.get('balance')
            if balance is None and isinstance(data.get('credits'), dict): balance = data['credits'].get('balance')
            return True, (f'Balance: {balance}' if balance is not None else 'Authentication successful.'), data
        set_setting('ninex_api_connected', '0')
        code = data.get('error') if isinstance(data, dict) else ''
        msg = data.get('message') if isinstance(data, dict) else ''
        detail = f'{code}: {msg}'.strip(': ') if (code or msg) else f'HTTP {response.status_code}: {raw[:300]}'
        return False, detail[:500], data
    except Exception as exc:
        set_setting('ninex_api_connected', '0')
        return False, str(exc)[:500], None

def _ninex_generate_key(duration, purchase_ref=None, note=''):
    token, base, days = _ninex_api_token(), _ninex_base_url(), _ninex_plan_days(duration)
    if not token or not base or days is None:
        print(f'[9X] invalid configuration/duration: url={bool(base)} token={bool(token)} duration={duration!r}')
        return None
    purchase_ref = purchase_ref or f'RG-{time.time_ns()}-{random.randint(100000,999999)}'
    idem = hashlib.sha256(f'9x|{purchase_ref}'.encode()).hexdigest()[:48]
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json', 'Content-Type': 'application/json', 'Idempotency-Key': idem, 'User-Agent': 'RG-Cheat-Shop-Bot/9X'}
    payload = {'days': days, 'device_type': NINEX_DEVICE_TYPE}
    if note: payload['note'] = str(note)[:200]
    try:
        response = HTTP_SESSION.post(f'{base}/api/seller/create-user', json=payload, headers=headers, timeout=30)
        raw = response.text.strip()
        try: data = response.json()
        except Exception: data = {}
        print(f'[9X] create-user status={response.status_code} days={days} device=single response={raw[:1500]}')
        if response.status_code in (200, 201) and isinstance(data, dict) and data.get('success'):
            u = data.get('user') or {}
            username, password = str(u.get('username') or '').strip(), str(u.get('password') or '').strip()
            if username and password: return f'Username: {username}\nPassword: {password}'
        return None
    except Exception as exc:
        print(f'[9X] create-user exception: {str(exc)[:500]}')
        return None

def _ninex_product_by_hash(value):
    for name in get_unique_products():
        if _ui_hash(name) == str(value): return name
    return None

def _ninex_api_markup():
    connected = str(get_setting('ninex_api_connected') or '0') == '1'
    token, url = _ninex_api_token(), _ninex_base_url()
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton('🔑 Set / Change 9X API Token', callback_data='ninex_set_token'))
    m.add(types.InlineKeyboardButton('🌐 Set / Change 9X Server Link', callback_data='ninex_set_url'))
    m.add(types.InlineKeyboardButton('🔍 Check 9X Connection', callback_data='ninex_check'))
    m.add(types.InlineKeyboardButton('📦 9X Product Setup', callback_data='ninex_products'))
    m.add(types.InlineKeyboardButton('🔙 API & Servers', callback_data='admin_api_system'))
    return m

def _send_ninex_panel(call):
    status = '🟢 CONNECTED' if str(get_setting('ninex_api_connected') or '0') == '1' else '🔴 NOT CONNECTED'
    token, url = _ninex_api_token(), _ninex_base_url()
    token_line = f'<code>{html.escape(token[:8])}••••••</code>' if token else '<i>Not Set</i>'
    url_line = f'<code>{html.escape(url)}</code>' if url else '<i>Not Set</i>'
    _admin_ui_send(call, '9️⃣ <b>9X API CONNECT</b>\n\n'
        f'📡 <b>Status:</b> {status}\n🌐 <b>Server:</b> {url_line}\n🔑 <b>API Token:</b> {token_line}\n\n'
        '🔒 <b>Device Type:</b> SINGLE ONLY\n📅 <b>Supported Days:</b> 10 / 20 / 30\n'
        '🚫 Double Device is disabled in this bot.\n\n'
        'Connection check uses <code>/api/seller/me</code> and does not create a key.',
        parse_mode='HTML', reply_markup=_ninex_api_markup())

def _ninex_products_markup():
    m = types.InlineKeyboardMarkup()
    for name in get_unique_products():
        enabled = _ninex_product_enabled(name)
        m.add(types.InlineKeyboardButton(f"{'🟢' if enabled else '⚪'} {name}", callback_data=f'ninex_product_{_ui_hash(name)}'))
    m.add(types.InlineKeyboardButton('🔙 9X API System', callback_data='ninex_api_system'))
    return m

def step_save_ninex_token(message):
    uid = message.from_user.id
    if not _is_admin(uid): return
    token = (message.text or '').strip()
    if not token:
        m = bot.send_message(message.chat.id, '❌ <b>API Token cannot be empty.</b> Enter it again.', parse_mode='HTML')
        bot.register_next_step_handler(m, step_save_ninex_token); return
    admin_temp_data.setdefault(uid, {})['ninex_api_token'] = token
    m = bot.send_message(message.chat.id, f'🌐 <b>Enter 9X Server Link:</b>\n\nExample: <code>{NINEX_DEFAULT_API_URL}</code>', parse_mode='HTML')
    bot.register_next_step_handler(m, step_save_ninex_url)

def step_save_ninex_url(message):
    uid = message.from_user.id
    if not _is_admin(uid): return
    data = admin_temp_data.get(uid, {})
    token = str(data.get('ninex_api_token') or _ninex_api_token()).strip()
    url = _ninex_base_url((message.text or '').strip())
    if not token:
        m = bot.send_message(message.chat.id, '❌ 9X API Token is missing. Start again.')
        bot.register_next_step_handler(m, step_save_ninex_token); return
    if not url:
        m = bot.send_message(message.chat.id, '❌ Invalid Server Link. Send a valid http:// or https:// URL.')
        bot.register_next_step_handler(m, step_save_ninex_url); return
    set_setting(NINEX_API_TOKEN_KEY, token); set_setting(NINEX_API_URL_KEY, url); set_setting('ninex_api_connected', '0')
    admin_temp_data.pop(uid, None)
    ok, detail, _ = _ninex_check_connection()
    bot.send_message(message.chat.id, f'9️⃣ <b>9X API SAVED</b>\n\n🌐 <b>Server:</b> <code>{html.escape(url)}</code>\n'
        f"{'🟢 <b>Connected Successfully!</b>' if ok else '🔴 <b>Not Connect</b>'}\nℹ️ {html.escape(str(detail))}", parse_mode='HTML')
    bot.send_message(message.chat.id, '9️⃣ <b>9X API SYSTEM</b>', parse_mode='HTML', reply_markup=_ninex_api_markup())

# ==================== RG API SYSTEM (client for an RG Reseller API server) ====================
RG_API_URL_KEY = 'rg_api_url'
RG_API_TOKEN_KEY = 'rg_api_token'
RG_API_MAP_KEY = 'rg_api_map'
RG_API_CONNECTED_KEY = 'rg_api_connected'
RG_API_BALANCE_KEY = 'rg_api_balance'
RG_API_DETAIL_KEY = 'rg_api_last_detail'
_rg_alert_last = {}

def _rg_base_url(value=None):
    url = str(value if value is not None else get_setting(RG_API_URL_KEY) or '').strip().strip('`').strip()
    if not url:
        return ''
    if not re.match(r'^https?://', url, re.I):
        url = 'https://' + url
    url = url.rstrip('/')
    url = re.sub(r'/api/(?:reseller/)?v1(?:/.*)?$', '', url, flags=re.I)
    url = re.sub(r'/api/(?:reseller/)?(?:catalog|purchase|balance|me|generate-key|sync|docs|orders)/?$', '', url, flags=re.I)
    url = url.rstrip('/')
    return url if re.match(r'^https?://[^/\s]+', url, re.I) else ''

def _rg_api_token():
    return str(get_setting(RG_API_TOKEN_KEY) or '').strip()

def _rg_connected():
    return str(get_setting(RG_API_CONNECTED_KEY) or '0') == '1'

def _rg_map():
    try:
        data = json.loads(get_setting(RG_API_MAP_KEY) or '{}')
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _rg_save_map(data):
    set_setting(RG_API_MAP_KEY, json.dumps(data, ensure_ascii=False, separators=(',', ':')))

def _rg_entry(product_name):
    entry = _rg_map().get(str(product_name))
    return entry if isinstance(entry, dict) else {}

def _rg_update_entry(product_name, **changes):
    data = _rg_map()
    entry = data.get(str(product_name))
    if not isinstance(entry, dict):
        entry = {}
    entry.update(changes)
    data[str(product_name)] = entry
    _rg_save_map(data)
    return entry

def _rg_product_enabled(product_name):
    return bool(_rg_entry(product_name).get('enabled'))

def _rg_product_id(product_name):
    return str(_rg_entry(product_name).get('product_id') or '').strip()

def _rg_plan_valid_id(product_name, plan_id):
    plans = _rg_entry(product_name).get('plans')
    plans = plans if isinstance(plans, dict) else {}
    return str(plans.get(str(plan_id)) or '').strip()

def _rg_set_plan_valid_id(product_name, plan_id, valid_id):
    entry = _rg_entry(product_name)
    plans = dict(entry.get('plans') or {})
    if valid_id:
        plans[str(plan_id)] = str(valid_id).strip()
    else:
        plans.pop(str(plan_id), None)
    _rg_update_entry(product_name, plans=plans)

def _rg_source_ready_for_plan(product_name, plan_id=None):
    """True only when this plan is explicitly mapped to an RG API Product ID + Variant ID."""
    if not product_name or _product_hidden(product_name):
        return False
    if not _rg_api_token() or not _rg_base_url():
        return False
    if not _rg_product_enabled(product_name) or not _rg_product_id(product_name):
        return False
    if plan_id is None:
        return True
    if _plan_hidden(plan_id):
        return False
    return bool(_rg_plan_valid_id(product_name, plan_id))

def _rg_http(method, path, payload=None, timeout=20, idem=None):
    base, token = _rg_base_url(), _rg_api_token()
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json', 'User-Agent': 'RG-Cheat-Shop-Bot/RGAPI'}
    if payload is not None:
        headers['Content-Type'] = 'application/json'
    if idem:
        headers['Idempotency-Key'] = idem
    response = HTTP_SESSION.request(method, base + path, json=payload, headers=headers, timeout=timeout)
    try:
        data = response.json()
    except Exception:
        data = {}
    return response.status_code, data, response.text

def _rg_error_detail(status, data):
    if not isinstance(data, dict) or not data:
        return f'HTTP {status}: the server did not return API JSON. Check the Server Link.'
    code = str(data.get('error') or '')
    msg = str(data.get('message') or '')
    hints = {
        'INVALID_API_KEY': 'Token is wrong/old, or reseller access is off.',
        'RESELLER_API_DISABLED': 'The provider turned the API off.',
        'INSUFFICIENT_BALANCE': 'Not enough balance in the provider account.',
    }
    return (f'{code}: {msg or hints.get(code, "")}'.strip(': ').strip() or f'HTTP {status}')[:500]

def _rg_check_connection():
    token, base = _rg_api_token(), _rg_base_url()
    if not token:
        set_setting(RG_API_CONNECTED_KEY, '0')
        return False, 'API Token is not configured.', None
    if not base:
        set_setting(RG_API_CONNECTED_KEY, '0')
        return False, 'Invalid Server Link.', None
    try:
        status, data, raw = _rg_http('GET', '/api/v1/balance', timeout=15)
    except Exception as exc:
        set_setting(RG_API_CONNECTED_KEY, '0')
        detail = f'Network error: {str(exc)[:300]}'
        set_setting(RG_API_DETAIL_KEY, detail)
        return False, detail, None
    if status == 200 and isinstance(data, dict) and data.get('success') is True:
        set_setting(RG_API_CONNECTED_KEY, '1')
        set_setting(RG_API_BALANCE_KEY, str(data.get('balance')))
        detail = f"Balance: {data.get('balance')}"
        set_setting(RG_API_DETAIL_KEY, detail)
        return True, detail, data
    set_setting(RG_API_CONNECTED_KEY, '0')
    detail = _rg_error_detail(status, data)
    set_setting(RG_API_DETAIL_KEY, detail)
    return False, detail, data

def _rg_fetch_catalog():
    if not _rg_api_token() or not _rg_base_url():
        return False, 'Set the API Token and Server Link first.'
    try:
        status, data, raw = _rg_http('GET', '/api/v1/catalog', timeout=30)
    except Exception as exc:
        return False, f'Network error: {str(exc)[:300]}'
    if status == 200 and isinstance(data, dict) and data.get('success') is True and isinstance(data.get('catalog'), list):
        return True, data['catalog']
    return False, _rg_error_detail(status, data)

def _rg_norm_name(text):
    return re.sub(r'[\W_]+', '', str(text or '').lower())

def _rg_validity_key(text):
    t = str(text or '').strip().lower()
    m = re.fullmatch(r'(\d+)\s*([a-z]*)', t)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        mult = None
        if unit in ('', 'd', 'day', 'days'): mult = 1440
        elif unit in ('h', 'hr', 'hrs', 'hour', 'hours'): mult = 60
        elif unit in ('min', 'mins', 'minute', 'minutes'): mult = 1
        elif unit in ('w', 'week', 'weeks'): mult = 10080
        elif unit in ('month', 'months'): mult = 43200
        elif unit in ('y', 'yr', 'yrs', 'year', 'years'): mult = 525600
        if mult:
            return f'm{n * mult}'
    return 't' + re.sub(r'[\W_]+', '', t)

def _rg_match_remote_product(local_name, remote_list):
    key = _rg_norm_name(local_name)
    if not key:
        return None
    exact = [r for r in remote_list if _rg_norm_name(r.get('name')) == key]
    if exact:
        return exact[0]
    loose = []
    for r in remote_list:
        rk = _rg_norm_name(r.get('name'))
        if rk and (rk in key or key in rk):
            loose.append(r)
    return loose[0] if len(loose) == 1 else None

def _rg_auto_match(only_product=None):
    ok, catalog = _rg_fetch_catalog()
    if not ok:
        return False, str(catalog), {}
    data = _rg_map()
    report = {'matched': [], 'unmatched': [], 'plans_missing': []}
    for name in get_unique_products():
        if only_product and name != only_product:
            continue
        remote = _rg_match_remote_product(name, catalog)
        if not remote:
            report['unmatched'].append(name)
            continue
        rplans = {}
        for p in remote.get('plans') or []:
            rplans.setdefault(_rg_validity_key(p.get('validity')), p)
        entry = data.get(name) if isinstance(data.get(name), dict) else {}
        plans = dict(entry.get('plans') or {})
        local_plans = get_product_plans(name)
        n_ok = 0
        for row in local_plans:
            rp = rplans.get(_rg_validity_key(row[2]))
            if rp and rp.get('valid_id'):
                plans[str(row[0])] = str(rp['valid_id'])
                n_ok += 1
            else:
                report['plans_missing'].append(f'{name} — {row[2]}')
        entry.update({'product_id': str(remote.get('product_id')), 'plans': plans, 'remote_name': str(remote.get('name') or '')})
        entry.setdefault('enabled', False)
        data[name] = entry
        report['matched'].append((name, n_ok, len(local_plans)))
    _rg_save_map(data)
    return True, '', report

def _rg_alert_admins(key, text, cooldown=600):
    now = time.time()
    if now - _rg_alert_last.get(key, 0) < cooldown:
        return
    _rg_alert_last[key] = now
    try:
        for aid in _load_persistent_admin_ids():
            try:
                bot.send_message(aid, text, parse_mode='HTML')
            except Exception:
                pass
    except Exception:
        pass

def _rg_recover_order(idem):
    """After a timeout, look the order up by its Idempotency-Key (the provider uses it as order_id)."""
    try:
        status, data, raw = _rg_http('GET', '/api/v1/orders/' + urllib.parse.quote(idem, safe=''), timeout=20)
        if status == 200 and isinstance(data, dict) and isinstance(data.get('order'), dict):
            key = data['order'].get('key')
            if key:
                return str(key).strip()
    except Exception as exc:
        print(f'[RG API] order recovery failed: {str(exc)[:200]}')
    return None

def _rg_generate_key(product_id, valid_id, purchase_ref=None):
    token, base = _rg_api_token(), _rg_base_url()
    product_id, valid_id = str(product_id or '').strip(), str(valid_id or '').strip()
    if not (token and base and product_id and valid_id):
        print(f'[RG API] incomplete configuration: url={bool(base)} token={bool(token)} product_id={product_id!r} valid_id={valid_id!r}')
        return None
    purchase_ref = purchase_ref or f'RG-{time.time_ns()}-{random.randint(100000, 999999)}'
    idem = 'RGAPI' + hashlib.sha256(f'rg|{purchase_ref}'.encode()).hexdigest()[:30]
    payload = {'product_id': product_id, 'validity_id': valid_id}
    for attempt in range(2):
        try:
            status, data, raw = _rg_http('POST', '/api/v1/purchase', payload=payload, timeout=(10, 90), idem=idem)
        except Exception as exc:
            # A timeout after POST is ambiguous: the provider may already have charged.
            # Never POST again; look the order up by its Idempotency-Key instead.
            print(f'[RG API] purchase exception: {str(exc)[:300]}')
            time.sleep(4)
            return _rg_recover_order(idem)
        if status == 200 and isinstance(data, dict) and data.get('success') is True:
            key = data.get('key')
            if not key and isinstance(data.get('user'), dict):
                key = data['user'].get('key')
            if key:
                return str(key).strip()
            return _rg_recover_order(idem)
        err = str(data.get('error') or '') if isinstance(data, dict) else ''
        print(f'[RG API] purchase failed status={status} error={err}')
        if status == 409 and err == 'BALANCE_CHANGED_RETRY' and attempt == 0:
            time.sleep(1)
            continue
        if status == 402:
            _rg_alert_admins('rg_balance',
                '⚠️ <b>RG API: provider balance too low</b>\n\n'
                f"Balance: <code>{html.escape(str(data.get('balance')))}</code> · Required: <code>{html.escape(str(data.get('required')))}</code>\n"
                'Top up the RG API account. The customer was refunded.')
        elif status in (401, 403):
            set_setting(RG_API_CONNECTED_KEY, '0')
            _rg_alert_admins('rg_token', '⚠️ <b>RG API: token/account rejected</b>\n\n' + html.escape(_rg_error_detail(status, data)) + '\n\nOpen RG API System, fix it and run Check Connection.')
        return None
    return None

def _rg_product_by_hash(value):
    for name in get_unique_products():
        if _ui_hash(name) == str(value):
            return name
    return None

def _rg_product_name_by_plan(plan_id):
    try:
        conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
        try:
            row = conn.execute('SELECT name FROM products WHERE id=?', (int(plan_id),)).fetchone()
        finally:
            conn.close()
        return row[0] if row else None
    except Exception:
        return None

def _rg_api_markup():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        _admin_colorful_button('🔑 API Token', callback_data='rgapi_set_token', color='green'),
        _admin_colorful_button('🌐 Server Link', callback_data='rgapi_set_url', color='blue')
    )
    m.add(
        _admin_colorful_button('🔍 Check Connection', callback_data='rgapi_check', color='green'),
        _admin_colorful_button('🔄 Auto Match IDs', callback_data='rgapi_match', color='blue')
    )
    m.add(
        _admin_colorful_button('🎮 Connect Hacks', callback_data='rgapi_products', color='blue'),
        _admin_colorful_button('📋 Remote Catalog', callback_data='rgapi_catalog', color='blue')
    )
    m.add(_admin_colorful_button('🔙 API Systems', callback_data='admin_cat_api', color='red'))
    return _style_admin_markup(_ensure_admin_back_button(m))

def _send_rg_panel(call):
    connected = _rg_connected()
    status = '🟢 CONNECTION SUCCESSFUL' if connected else '🔴 NOT CONNECTED'
    token, url = _rg_api_token(), _rg_base_url()
    token_line = f'<code>{html.escape(token[:8])}••••••</code>' if token else '<i>Not Set</i>'
    url_line = f'<code>{html.escape(url)}</code>' if url else '<i>Not Set</i>'
    detail = str(get_setting(RG_API_DETAIL_KEY) or '').strip()
    rg_map = _rg_map()
    mapped = sum(1 for e in rg_map.values() if isinstance(e, dict) and e.get('plans'))
    active = sum(1 for e in rg_map.values() if isinstance(e, dict) and e.get('enabled'))
    _admin_ui_send(call,
        '🤝 <b>RG API SYSTEM</b>\n━━━━━━━━━━━━━━━━━━━━\n\n'
        f'📡 <b>Status:</b> {status}\n'
        + (f'ℹ️ {html.escape(detail)}\n' if detail else '')
        + f'🌐 <b>Server:</b> {url_line}\n🔑 <b>API Token:</b> {token_line}\n'
        f'🎮 <b>Hacks mapped:</b> {mapped} · <b>Connected:</b> {active}\n\n'
        '1️⃣ Set Token + Server Link\n2️⃣ Check Connection\n'
        '3️⃣ Auto Match IDs (or set Product ID / Variant ID by hand)\n4️⃣ Connect Hacks\n\n'
        '<i>A connected plan is delivered through the RG API. The provider wallet is charged only when the key is delivered.</i>',
        parse_mode='HTML', reply_markup=_rg_api_markup())

def _rg_products_markup():
    m = types.InlineKeyboardMarkup(row_width=2)
    for name in get_unique_products():
        entry = _rg_entry(name)
        icon = '🟢' if entry.get('enabled') else ('🟡' if entry.get('plans') else '⚪')
        m.add(_admin_colorful_button(f'{icon} {name}', callback_data=f'rgapi_prod_{_ui_hash(name)}',
                                     color='green' if entry.get('enabled') else 'blue'))
    m.add(_admin_colorful_button('🔙 RG API System', callback_data='rg_api_system', color='red'))
    return _style_admin_markup(_ensure_admin_back_button(m))

def _rg_product_screen(product_name):
    entry = _rg_entry(product_name)
    enabled = bool(entry.get('enabled'))
    pid = str(entry.get('product_id') or '')
    esc = html.escape
    lines = [f'🎮 <b>{esc(str(product_name))}</b>', '',
             f"🤝 RG API: {'🟢 CONNECTED TO THIS HACK' if enabled else '⚪ NOT CONNECTED'}",
             f"🆔 <b>Product ID:</b> {('<code>' + esc(pid) + '</code>') if pid else '<i>Not set</i>'}", '',
             '<b>Plans → Variant ID:</b>']
    h = _ui_hash(product_name)
    m = types.InlineKeyboardMarkup(row_width=1)
    for row in get_product_plans(product_name):
        vid = _rg_plan_valid_id(product_name, row[0])
        lines.append(f"• {esc(str(row[2]))} — {('<code>' + esc(vid) + '</code> ✅') if vid else '❌ not set'}")
        m.add(_admin_colorful_button(f'✏️ {row[2]} · Variant ID', callback_data=f'rgapi_vid_{row[0]}', color='blue'))
    m.add(_admin_colorful_button('🔴 Disconnect Hack' if enabled else '🟢 Connect Hack',
                                 callback_data=f'rgapi_toggle_{h}', color='red' if enabled else 'green'))
    m.add(_admin_colorful_button('🆔 Set Product ID', callback_data=f'rgapi_setpid_{h}', color='blue'))
    m.add(_admin_colorful_button('🔄 Auto Match This Hack', callback_data=f'rgapi_match1_{h}', color='green'))
    m.add(_admin_colorful_button('🗑 Clear Mapping', callback_data=f'rgapi_clear_{h}', color='red'))
    m.add(_admin_colorful_button('🔙 Hack List', callback_data='rgapi_products', color='blue'))
    return '\n'.join(lines), _style_admin_markup(_ensure_admin_back_button(m))

def _rg_match_report_text(ok, err, rep):
    if not ok:
        return f'❌ <b>AUTO MATCH FAILED</b>\n\n{html.escape(str(err))}'
    lines = ['🔄 <b>AUTO MATCH RESULT</b>', '━━━━━━━━━━━━━━━━━━━━', '']
    if rep['matched']:
        lines.append('✅ <b>Matched</b>')
        for name, n_ok, total in rep['matched']:
            lines.append(f'• {html.escape(str(name))} — {n_ok}/{total} plans')
    if rep['plans_missing']:
        lines += ['', '⚠️ <b>Plans without a matching Variant</b> (set by hand):']
        lines += [f'• {html.escape(x)}' for x in rep['plans_missing'][:25]]
    if rep['unmatched']:
        lines += ['', '❌ <b>No matching product on the RG server</b> (set Product ID by hand):']
        lines += [f'• {html.escape(str(x))}' for x in rep['unmatched'][:25]]
    if not (rep['matched'] or rep['unmatched']):
        lines.append('Nothing to match.')
    lines += ['', '<i>Matching only saves IDs. Tap “Connect All Matched Hacks” or connect hacks one by one.</i>']
    return '\n'.join(lines)

def _rg_send_step_result(chat_id, product_name):
    text, markup = _rg_product_screen(product_name)
    bot.send_message(chat_id, text, parse_mode='HTML', reply_markup=markup)

def step_save_rg_token(message):
    uid = int(message.from_user.id)
    if not _is_admin(uid):
        return
    token = (message.text or '').strip()
    if _is_command_input(token):
        admin_temp_data.pop(uid, None)
        bot.send_message(message.chat.id, 'ℹ️ Cancelled.')
        return
    if not token:
        m = bot.send_message(message.chat.id, '❌ <b>RG API Token cannot be empty.</b> Enter it again.', parse_mode='HTML')
        bot.register_next_step_handler(m, step_save_rg_token)
        return
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass
    admin_temp_data.setdefault(uid, {})['rg_api_token'] = token
    m = bot.send_message(message.chat.id,
        '🌐 <b>Enter RG API Server Link:</b>\n\nExample: <code>https://your-app.up.railway.app</code>', parse_mode='HTML')
    bot.register_next_step_handler(m, step_save_rg_url)

def step_save_rg_url(message):
    uid = int(message.from_user.id)
    if not _is_admin(uid):
        return
    text = (message.text or '').strip()
    if _is_command_input(text):
        admin_temp_data.pop(uid, None)
        bot.send_message(message.chat.id, 'ℹ️ Cancelled.')
        return
    data = admin_temp_data.setdefault(uid, {})
    token = str(data.get('rg_api_token') or _rg_api_token()).strip()
    url = _rg_base_url(text)
    if not token:
        m = bot.send_message(message.chat.id, '❌ RG API Token is missing. Enter the Token first.')
        bot.register_next_step_handler(m, step_save_rg_token)
        return
    if not url:
        m = bot.send_message(message.chat.id, '❌ Invalid Server Link. Send a valid http:// or https:// URL.')
        bot.register_next_step_handler(m, step_save_rg_url)
        return
    set_setting(RG_API_TOKEN_KEY, token)
    set_setting(RG_API_URL_KEY, url)
    set_setting(RG_API_CONNECTED_KEY, '0')
    admin_temp_data.pop(uid, None)
    ok, detail, _ = _rg_check_connection()
    bot.send_message(message.chat.id,
        f'🤝 <b>RG API SAVED</b>\n\n🌐 <code>{html.escape(url)}</code>\n'
        f"{'🟢 <b>Connection Successful!</b>' if ok else '🔴 <b>Not Connected</b>'}\nℹ️ {html.escape(str(detail))}",
        parse_mode='HTML', reply_markup=_rg_api_markup())

def step_save_rg_product_id(message):
    uid = int(message.from_user.id)
    if not _is_admin(uid):
        return
    name = admin_temp_data.get(uid, {}).get('rg_product')
    value = (message.text or '').strip()
    if not name:
        bot.send_message(message.chat.id, '❌ Session expired. Open the hack again.')
        return
    if _is_command_input(value):
        admin_temp_data.pop(uid, None)
        bot.send_message(message.chat.id, 'ℹ️ ID entry cancelled.')
        return
    if not value:
        m = bot.send_message(message.chat.id, '❌ Product ID cannot be empty. Enter it again.')
        bot.register_next_step_handler(m, step_save_rg_product_id)
        return
    _rg_update_entry(name, product_id=value)
    admin_temp_data.pop(uid, None)
    _rg_send_step_result(message.chat.id, name)

def step_save_rg_variant_id(message):
    uid = int(message.from_user.id)
    if not _is_admin(uid):
        return
    info = admin_temp_data.get(uid, {})
    name, plan_id = info.get('rg_product'), info.get('rg_plan_id')
    value = (message.text or '').strip()
    if not name or plan_id is None:
        bot.send_message(message.chat.id, '❌ Session expired. Open the hack again.')
        return
    if _is_command_input(value):
        admin_temp_data.pop(uid, None)
        bot.send_message(message.chat.id, 'ℹ️ ID entry cancelled.')
        return
    if not value:
        m = bot.send_message(message.chat.id, '❌ Variant ID cannot be empty. Enter it again.')
        bot.register_next_step_handler(m, step_save_rg_variant_id)
        return
    _rg_set_plan_valid_id(name, plan_id, value)
    admin_temp_data.pop(uid, None)
    _rg_send_step_result(message.chat.id, name)

def _api_source_ready_for_plan(product_name, plan_id=None, local_pid_id=None):
    """Return True only when an actually configured/connected API can deliver.

    Product IDs alone are not treated as stock. This is intentionally separate
    from _resolve_api_route(), whose legacy fallback remains untouched for
    backward compatibility during an actual delivery request.
    """
    return any((
        _rg_source_ready_for_plan(product_name, plan_id),
        _ninex_source_ready_for_plan(product_name, plan_id),
        _tobix_source_ready_for_plan(product_name, plan_id),
        _multi_api_source_ready(product_name, plan_id),
        _new_server_source_ready(product_name, plan_id),
        _hack_server_source_ready(product_name, plan_id),
        _legacy_global_api_source_ready(product_name, plan_id),
    ))


def _refresh_multi_api_connection_if_needed(product_name, plan_id=None):
    """Refresh a stale multi-server connection flag before delivery.

    This only performs the lightweight /balance authentication check. It does
    not call the purchase/generate-key endpoint, so it cannot consume inventory.
    """
    if not product_name:
        return False
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        row = conn.execute(
            """SELECT s.id,s.enabled
               FROM product_server_selection sel
               JOIN api_servers s ON s.id=sel.server_id
               WHERE sel.product_name=? LIMIT 1""",
            (str(product_name),)
        ).fetchone()
    finally:
        conn.close()
    if not row or int(row[1] or 0):
        return bool(row and int(row[1] or 0))
    ok, _detail = _api_server_test_connection(int(row[0]))
    if ok and plan_id is not None:
        return bool(_api_server_plan_valid_id(int(row[0]), product_name, plan_id))
    return ok


def _plan_stock_state(product):
    """Return (is_out_of_stock, status_text) using real manual/API sources.

    products rows contain 12 columns because the product name is included
    between the plan id and pid_id.  Keep the full row shape here so checkout
    and UPI stock checks work for every Telegram user.
    """
    if not product:
        return True, "Out of Stock"

    p_id, product_name, pid_id, days, _price, _resell, is_manual, _disc, _remote, _tg, is_oos, _req = product[:12]
    raw_days = str(days or '').strip()
    if str(product_name).strip().lower() == BOT_MAKE_PRODUCT_NAME.lower():
        return False, 'In Stock (Bot Make)'
    days = _clean_plan_days(days)
    manual_count = get_key_stock_count(product_name, raw_days)
    if int(is_oos or 0) == 1:
        return True, "Out of Stock"
    if manual_count > 0:
        return False, f"{manual_count} Available (Manual)"
    if _api_source_ready_for_plan(product[1], int(p_id), pid_id):
        return False, "In Stock (Auto-API)"
    return True, "Out of Stock"


def _plan_is_in_stock(product_id):
    return not _plan_stock_state(get_product_by_id(product_id))[0]


def get_product_plans(name):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('SELECT id, pid_id, days, price, resell_price, is_manual, discount_percent, remote_duration, tg_group_link, is_out_of_stock, require_device_id FROM products WHERE name = ? ORDER BY id ASC', (name,))
    plans = cursor.fetchall()
    conn.close()
    return plans

def get_product_by_id(product_id):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('SELECT id, name, pid_id, days, price, resell_price, is_manual, discount_percent, remote_duration, tg_group_link, is_out_of_stock, require_device_id, display_order, is_bot_make FROM products WHERE id = ?', (product_id,))
    product = cursor.fetchone()
    conn.close()
    return product

def get_key_stock_count(product_name, days_plan):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        exact = str(days_plan or '').strip()
        legacy = _clean_plan_days(exact)
        values = [exact] if legacy == exact else [exact, legacy]
        placeholders = ','.join('?' for _ in values)
        row = conn.execute(
            f'SELECT COUNT(*) FROM panels WHERE panel_name = ? AND validity_days IN ({placeholders}) AND is_sold = 0',
            [product_name] + values
        ).fetchone()
        return int(row[0] or 0)
    finally:
        conn.close()

def get_key_stock_counts(product_name, days_plans):
    """Return manual stock counts while preserving exact validity labels."""
    requested = [str(x or '').strip() for x in days_plans if str(x or '').strip()]
    if not requested:
        return {}
    db_values = []
    for value in requested:
        db_values.append(value)
        legacy = _clean_plan_days(value)
        if legacy and legacy not in db_values:
            db_values.append(legacy)
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        placeholders = ','.join('?' for _ in db_values)
        rows = conn.execute(
            f'''SELECT validity_days, COUNT(*) FROM panels
                WHERE panel_name = ? AND validity_days IN ({placeholders})
                  AND is_sold = 0 GROUP BY validity_days''',
            [product_name] + db_values
        ).fetchall()
        counts = {str(days): int(count) for days, count in rows}
        result = {}
        for value in requested:
            result[value] = counts.get(value, counts.get(_clean_plan_days(value), 0))
        return result
    finally:
        conn.close()

def fetch_and_claim_manual_key(product_name, days_plan):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    exact = str(days_plan or '').strip()
    legacy = _clean_plan_days(exact)
    values = [exact] if legacy == exact else [exact, legacy]
    placeholders = ','.join('?' for _ in values)
    cursor.execute(
        f'SELECT id, panel_key FROM panels WHERE panel_name = ? AND validity_days IN ({placeholders}) AND is_sold = 0 ORDER BY CASE WHEN validity_days = ? THEN 0 ELSE 1 END, id ASC LIMIT 1',
        [product_name] + values + [exact]
    )
    key_row = cursor.fetchone()
    if key_row:
        key_id, key_val = key_row
        cursor.execute('UPDATE panels SET is_sold = 1 WHERE id = ?', (key_id,))
        conn.commit()
        conn.close()
        return key_val
    conn.close()
    return None

def get_user_orders(user_id):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    cursor.execute('SELECT order_id, product_name, plan_days, price_paid, purchased_key, date_time FROM order_history WHERE user_id = ? ORDER BY id DESC', (user_id,))
    orders = cursor.fetchall()
    conn.close()
    return orders

# ==================== EXACT PHP cURL TO PYTHON CONVERSION ====================
def _extract_api_key_value(data):
    """Extract a real delivered key from common REST/JSON response shapes.

    Providers do not always return the key in exactly the same envelope.  Some
    responses use key/license fields directly, while others put a key list or
    nested delivery object inside data/result/order.  This extractor deliberately
    follows only key-related fields and known response containers so that a
    product name, status message, price, or order id is never mistaken for a key.
    """
    direct_fields = (
        'key', 'keys', 'license', 'license_key', 'licenseKey', 'license_keys',
        'licenseKeys', 'licence', 'licences', 'serial', 'serial_key',
        'code', 'codes', 'key_value', 'keyValue', 'access_key', 'accessKey',
        'product_key', 'productKey', 'generated_key', 'generatedKey', 'keyCode', 'key_code',
        'activation_key', 'activationKey', 'license_code', 'licenseCode', 'voucher',
        'delivery_key', 'deliveryKey', 'key_data', 'keyData', 'key_value_data'
    )
    nested_fields = (
        'data', 'result', 'response', 'order', 'delivery', 'sale', 'purchase',
        'license_data', 'licenseData', 'delivery_data', 'deliveryData',
        'key_data', 'keyData', 'details', 'payload'
    )

    if isinstance(data, str):
        text = data.strip()
        if len(text) > 3 and text.lower() not in {
            'success', 'true', 'false', 'ok', 'pending', 'completed', 'successfully',
            'key generated successfully', 'order created successfully'
        }:
            return text
        return None

    if isinstance(data, dict):
        # Some reseller APIs return the generated key directly as data/result/message.
        for field in ('data', 'result', 'key', 'license_key', 'generated_key', 'activation_key'):
            value = data.get(field)
            if isinstance(value, str):
                text = value.strip()
                if len(text) > 3 and text.lower() not in {
                    'success', 'true', 'false', 'ok', 'pending', 'completed',
                    'successfully', 'key generated successfully', 'order created successfully'
                }:
                    # A short provider status sentence is not a key.
                    if not re.fullmatch(r'(?i)(success|ok|pending|completed|created|generated)([ ._-].*)?', text):
                        return text
        # First preference: explicitly key-named fields.
        for field in direct_fields:
            if field not in data:
                continue
            value = data.get(field)
            if value in (None, '', False):
                continue
            if isinstance(value, str):
                text = value.strip()
                if len(text) > 3 and text.lower() not in {'success', 'true', 'false', 'ok', 'pending'}:
                    return text
            elif isinstance(value, (list, tuple)):
                for item in value:
                    if isinstance(item, str):
                        text = item.strip()
                        if len(text) > 3 and text.lower() not in {'success', 'true', 'false', 'ok', 'pending'}:
                            return text
                    else:
                        found = _extract_api_key_value(item)
                        if found:
                            return found
            elif isinstance(value, dict):
                found = _extract_api_key_value(value)
                if found:
                    return found

        # Then follow only documented/common response containers.
        for field in nested_fields:
            if field in data:
                found = _extract_api_key_value(data.get(field))
                if found:
                    return found

    elif isinstance(data, list):
        for value in data:
            found = _extract_api_key_value(value)
            if found:
                return found

    return None

def _looks_like_provider_order_id(value):
    value=str(value or '').strip()
    if len(value)<4:
        return False
    upper=value.upper()
    if upper.startswith(('ORD','ORDER','SALE','PUR','TXN','RAP','API')):
        return True
    return len(value)>=8 and bool(re.search(r'[A-Za-z]',value))


def _extract_api_order_id(data):
    """Extract provider order/sale IDs, including nested order.id shapes."""
    if isinstance(data,dict):
        for field in ('order_id','orderId','purchase_id','purchaseId','sale_id','saleId','transaction_id','transactionId','order_number','orderNo','reference','ref'):
            value=data.get(field)
            if value not in (None,'') and not isinstance(value,(dict,list)) and _looks_like_provider_order_id(value):
                return str(value).strip()
        for field in ('order','sale','purchase','transaction','data','result','response','delivery'):
            value=data.get(field)
            if isinstance(value,str) and _looks_like_provider_order_id(value):
                return value.strip()
            found=_extract_api_order_id(value)
            if found:
                return found
        value=data.get('id')
        if value not in (None,'') and not isinstance(value,(dict,list)) and _looks_like_provider_order_id(value):
            return str(value).strip()
    elif isinstance(data,list):
        for value in data:
            found=_extract_api_order_id(value)
            if found:
                return found
    return None


def _extract_api_identifiers_from_raw(raw):
    """Recover key/order fields from malformed or non-standard JSON text."""
    raw=str(raw or '')
    key=None; order=None
    for pattern in (
        r'"(?:key|license_key|licenseKey|licence|serial|product_key|productKey|generated_key|generatedKey|access_key|accessKey)"\s*:\s*"([^"]+)"',
        r"'(?:key|license_key|licenseKey|licence|serial|product_key|productKey|generated_key|generatedKey|access_key|accessKey)'\s*:\s*'([^']+)'",
    ):
        m=re.search(pattern,raw,re.I)
        if m and len(m.group(1).strip())>3:
            key=m.group(1).strip(); break
    for pattern in (
        r'"(?:order_id|orderId|purchase_id|purchaseId|sale_id|saleId|transaction_id|transactionId|reference|ref|order)"\s*:\s*"?([A-Za-z0-9_-]{4,})',
        r'\b(ORD[A-Za-z0-9_-]{5,})\b',
    ):
        m=re.search(pattern,raw,re.I)
        if m and _looks_like_provider_order_id(m.group(1)):
            order=m.group(1).strip(); break
    return key,order


def _new_api_get_order_key(server_url, api_key, order_id, max_wait_seconds=300):
    """GET-only recovery for an already-created provider order."""
    server_url=_normalize_api_server_url(server_url); api_key=str(api_key or '').strip(); order_id=str(order_id or '').strip()
    if not server_url or not api_key or not order_id:
        return None
    headers={'Authorization':f'Bearer {api_key}','Accept':'application/json','User-Agent':'RG-Cheat-Shop-Bot/1.3'}
    encoded=urllib.parse.quote(order_id,safe='')
    endpoints=(
        f'{server_url}/api/v1/orders/{encoded}',
        f'{server_url}/api/v1/order/{encoded}',
        f'{server_url}/api/v1/orders?order_id={encoded}',
        f'{server_url}/api/v1/orders?id={encoded}',
        f'{server_url}/api/v1/order?id={encoded}',
        f'{server_url}/api/v1/orders/{encoded}/key',
        f'{server_url}/api/v1/order/{encoded}/key',
    )
    deadline=time.time()+max(1,int(max_wait_seconds or 300)); last_detail=''
    while time.time()<=deadline:
        for endpoint in endpoints:
            try:
                response=HTTP_SESSION.get(endpoint,headers=headers,timeout=5)
                raw=response.text.strip(); data=_api_server_parse_json(response)
                key=_extract_api_key_value(data); raw_key,_=_extract_api_identifiers_from_raw(raw); key=key or raw_key
                print(f'DEBUG NEW API ORDER LOOKUP status={response.status_code} order={order_id} url={endpoint} raw={raw[:1200]}')
                if response.status_code==200 and key:
                    return key
                last_detail=f'HTTP {response.status_code}: {raw[:300]}'
                if response.status_code in (401,403):
                    return None
            except Exception as exc:
                last_detail=str(exc)[:300]
        if time.time()>=deadline: break
        time.sleep(1.0)
    print(f'DEBUG NEW API ORDER LOOKUP FAILED order={order_id}: {last_detail}')
    return None


def _new_api_generate_key(server_url, api_key, product_id, valid_id, duration=None, android_id=None, purchase_ref=None):
    """Create a provider sale safely and recover its key without duplicate POSTs.

    Validation-only 4xx responses may try the server's supported field aliases.
    Once any request returns 2xx/409, or the network result is ambiguous, the
    function stops immediately: it will never submit another purchase payload.
    """
    server_url=_normalize_api_server_url(server_url); api_key=str(api_key or '').strip()
    product_id=str(product_id or '').strip(); valid_id=str(valid_id or '').strip()
    android_id=str(android_id or '').strip(); duration=str(duration or '').strip(); purchase_ref=str(purchase_ref or '').strip()
    if not server_url or not api_key or not product_id or not valid_id:
        print('DEBUG NEW API: missing server/product/valid mapping'); return None
    if not purchase_ref:
        purchase_ref=f'{time.time_ns()}-{random.randint(100000,999999)}'

    idem=hashlib.sha256('|'.join((server_url,product_id,valid_id,android_id,duration,purchase_ref)).encode('utf-8')).hexdigest()[:48]
    headers={'Authorization':f'Bearer {api_key}','Accept':'application/json','Content-Type':'application/json','Idempotency-Key':idem,'User-Agent':'RG-Cheat-Shop-Bot/1.3'}

    # Keep compatibility with servers that use valid_id, variant_id or
    # validity_id, but only move to another alias after a validation 4xx.
    payloads=[]
    for alias in ('valid_id','variant_id','validity_id'):
        base={'product_id':product_id,alias:valid_id}
        if duration: payloads.append({**base,'duration':duration})
        if android_id: payloads.append({**base,'android_id':android_id})
        payloads.append(base)
    seen=set()

    for payload in payloads:
        marker=json.dumps(payload,sort_keys=True,ensure_ascii=False)
        if marker in seen: continue
        seen.add(marker)
        try:
            response=HTTP_SESSION.post(f'{server_url}/api/v1/generate-key',json=payload,headers=headers,timeout=20)
            raw=response.text.strip(); data=_api_server_parse_json(response)
            key=_extract_api_key_value(data); order_id=_extract_api_order_id(data)
            raw_key,raw_order=_extract_api_identifiers_from_raw(raw); key=key or raw_key; order_id=order_id or raw_order
            print(f'DEBUG NEW API GENERATE-KEY payload={marker} status={response.status_code}: {raw[:2000]}')

            if response.status_code in (200,201,202,409) and key:
                print('DEBUG NEW API GENERATE-KEY SUCCESS: key returned directly')
                return key
            if response.status_code in (200,201,202,409) and order_id:
                print(f'DEBUG NEW API ORDER CREATED {order_id}; GET-only recovery')
                key=_new_api_get_order_key(server_url,api_key,order_id,max_wait_seconds=300)
                if key: return key
                print(f'DEBUG NEW API: order {order_id} exists but key is not ready; no second purchase')
                return None
            if response.status_code in (200,201,202):
                print('DEBUG NEW API: successful response had no parseable key/order; retry disabled to prevent duplicate charge')
                return None

            # Only validation/not-found 4xx responses are candidates for the
            # next alias. Authentication, rate-limit and server errors stop.
            if response.status_code in (401,403,429) or response.status_code >= 500:
                return None
            if not (400 <= response.status_code < 500):
                return None
        except Exception as exc:
            # A timeout after POST is ambiguous: the provider may have charged.
            # Never retry automatically in that case.
            print(f'DEBUG NEW API GENERATE-KEY EXCEPTION: {str(exc)[:500]}')
            return None

    print('DEBUG NEW API GENERATE-KEY FAILED: all validation payload variants rejected')
    return None


def fetch_key_from_api(pid_id, duration, android_id=None, product_name=None, plan_id=None, purchase_ref=None):
    route = _resolve_api_route(product_name or '', plan_id, pid_id, duration)
    curr_api_url = route['url']
    curr_api_key = route['api_key']
    remote_product_id = route['product_id']
    valid_id = route.get('valid_id', '')

    if route.get('server_type') == 'rg':
        return _rg_generate_key(remote_product_id, valid_id, purchase_ref=purchase_ref)

    if route.get('server_type') == 'ninex':
        return _ninex_generate_key(duration, purchase_ref=purchase_ref, note=f'{product_name or "Product"} | {duration}')

    if route.get('server_type') == 'tobix':
        return _tobix_generate_key(duration, purchase_ref=purchase_ref, note=f'{product_name or "Product"} | {duration}')

    if not remote_product_id or remote_product_id == '0':
        remote_product_id = '133'
    if not duration or duration == '0':
        duration = '1 Hours'

    # NEW REST v1 servers from the supplied integration guide use Bearer auth and
    # POST /api/v1/generate-key. Product ID + per-plan Valid ID are mandatory.
    if route.get('server_type') in ('new', 'new_multi'):
        if not curr_api_url or not curr_api_key:
            return None
        key_value = _new_api_generate_key(
            curr_api_url,
            curr_api_key,
            remote_product_id,
            valid_id,
            duration=duration,
            android_id=android_id,
            purchase_ref=purchase_ref,
        )
        if key_value:
            return key_value
        # Do not send a v1 purchase to the legacy root after a failed v1 purchase.
        # Doing so can create duplicate/incorrect orders or hide a real API error.
        return None

    # Existing reseller/PHP contract is preserved exactly for legacy routes.
    if not curr_api_url or not curr_api_key:
        return None
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'x-master-key': RESELLER_MASTER_KEY
    }
    payload = {
        'api_key': str(curr_api_key).strip(),
        'action': 'buy',
        'product_id': str(remote_product_id).strip(),
        'duration': str(duration).strip()
    }
    if valid_id:
        payload.update({'valid_id': str(valid_id).strip(), 'validity_id': str(valid_id).strip()})
    if android_id:
        payload['android_id'] = str(android_id).strip()
    try:
        response = HTTP_SESSION.post(curr_api_url, data=payload, headers=headers, timeout=20)
        raw_resp = response.text.strip()
        print(f'DEBUG PROVIDER API RESPONSE: {raw_resp}')
        data = _api_server_parse_json(response)
        key_value = _extract_api_key_value(data)
        if key_value:
            return key_value
        if raw_resp and not raw_resp.startswith('{') and not raw_resp.startswith('[') and len(raw_resp) < 120:
            return raw_resp
    except Exception as e:
        print(f'API Request Error: {e}')
    return None

def notify_admins_topup(user_id, u_name, order_id, amount, new_balance, utr=None, previous_balance=None):
    """Notify every admin immediately after a verified wallet top-up."""
    now_text = _now_ist_text()
    user = get_user(int(user_id)) or []
    name = str(u_name or (user[1] if len(user) > 1 else 'User') or 'User')
    phone = str(user[2] if len(user) > 2 and user[2] else 'N/A')
    role = '👑 Reseller' if len(user) > 11 and int(user[11] or 0) == 1 else '👤 User'
    orders_count = int(user[6] or 0) if len(user) > 6 else 0
    lifetime_spent = float(user[7] or 0) if len(user) > 7 else 0.0
    total_deposited = float(user[8] or 0) if len(user) > 8 else 0.0
    if previous_balance is None:
        previous_balance = float(new_balance) - float(amount)
    previous_balance = float(previous_balance)
    new_balance = float(new_balance)
    amount = float(amount)
    live_username = _get_live_telegram_username(int(user_id), '')
    username_display = ('@' + html.escape(live_username, quote=False)) if live_username else 'N/A'

    default_topup_text = (
        '🚨 <b>NEW WALLET BALANCE ADDED</b> 🚨\n\n'
        f'👤 <b>Name:</b> {html.escape(name, quote=False)}\n'
        f'🔗 <b>Username:</b> {username_display}\n'
        f'👑 <b>Account Type:</b> {role}\n'
        f'🆔 <b>Telegram / Chat ID:</b> <code>{int(user_id)}</code>\n'
        f'📱 <b>Phone Number:</b> <code>{html.escape(phone, quote=False)}</code>\n\n'
        f'💵 <b>Amount Added:</b> ₹{amount:.2f} INR\n'
        f'💼 <b>Previous Balance:</b> ₹{previous_balance:.2f} INR\n'
        f'💰 <b>Current Balance:</b> ₹{new_balance:.2f} INR\n'
        f'🎮 <b>Hacks Purchased:</b> {orders_count}\n'
        f'💎 <b>Total Hack Purchase Value:</b> ₹{lifetime_spent:.2f} INR\n'
        f'📥 <b>Total Deposited:</b> ₹{total_deposited:.2f} INR\n\n'
        f'🧾 <b>Order ID:</b> <code>{html.escape(str(order_id), quote=False)}</code>\n'
        f'🏷️ <b>UTR:</b> <code>{html.escape(str(utr or "N/A"), quote=False)}</code>\n'
        f'🕒 <b>Date/Time:</b> {now_text}'
    )
    values = {
        'user': name, 'name': name, 'username': live_username,
        'telegram_username': live_username, 'user_id': int(user_id),
        'telegram_id': int(user_id), 'chat_id': int(user_id), 'phone': phone,
        'number': phone, 'role': role, 'account_type': role,
        'amount': f'{amount:.2f}', 'added_amount': f'{amount:.2f}',
        'previous_balance': f'{previous_balance:.2f}', 'old_balance': f'{previous_balance:.2f}',
        'balance': f'{new_balance:.2f}', 'current_balance': f'{new_balance:.2f}',
        'orders_count': orders_count, 'hacks_bought': orders_count,
        'lifetime_spent': f'{lifetime_spent:.2f}', 'total_spent': f'{lifetime_spent:.2f}',
        'deposited': f'{total_deposited:.2f}', 'total_deposited': f'{total_deposited:.2f}',
        'order_id': order_id, 'utr': utr or 'N/A', 'date': now_text, 'time': now_text,
        'default_topup': default_topup_text,
    }
    try:
        admin_topup_text = _safe_format_custom_text(
            get_custom_text('topup_notification', '{default_topup}'), **values
        )
        admin_topup_text = _inject_labeled_user_values(
            admin_topup_text,
            {k: html.escape(str(v), quote=False) for k, v in values.items() if k != 'default_topup'}
        )
        admin_topup_text = _repair_telegram_html_markup(_repair_premium_emoji_markup(admin_topup_text))
        if not admin_topup_text.strip():
            admin_topup_text = default_topup_text
    except Exception as exc:
        print(f'[TOPUP ADMIN TEMPLATE ERROR] {user_id}: {str(exc)[:300]}')
        admin_topup_text = default_topup_text

    plain_text = re.sub(r'<tg-emoji\b[^>]*>(.*?)</tg-emoji>', lambda m: m.group(1), admin_topup_text, flags=re.I | re.S)
    plain_text = html.unescape(re.sub(r'<[^>]+>', '', plain_text))
    sent_any = False
    for admin_id in _load_persistent_admin_ids():
        try:
            bot.send_message(admin_id, admin_topup_text, parse_mode='HTML')
            sent_any = True
        except Exception as exc:
            print(f'[TOPUP ADMIN NOTIFY HTML ERROR] admin={admin_id} user={user_id}: {str(exc)[:250]}')
            try:
                bot.send_message(admin_id, plain_text)
                sent_any = True
            except Exception as plain_exc:
                print(f'[TOPUP ADMIN NOTIFY PLAIN ERROR] admin={admin_id} user={user_id}: {str(plain_exc)[:250]}')
    return sent_any

def notify_admins_purchase(user_id, u_name, order_id, prod_name, prod_days, amount,
                           device_id=None, pay_type="upi", purchased_key=None):
    """Notify every admin after a successful product purchase.

    Includes the buyer identity, Telegram ID, product/plan, delivered key,
    payment method and exact purchase time. Sending is deliberately isolated
    from checkout so a notification failure can never break delivery.
    """
    user = get_user(user_id)
    phone = user[2] if user and len(user) > 2 else "N/A"
    country = user[3] if user and len(user) > 3 else "IN"
    dev_str = f"\n📱 <b>Device ID:</b> <code>{html.escape(str(device_id))}</code>" if device_id else ""
    payment_method = "💼 Wallet Balance" if str(pay_type).lower() == "wallet" else "🇮🇳 UPI Payment"
    purchase_time = _now_ist_text()
    key_text = str(purchased_key or "").strip()
    default_purchase_text = (
        f"🚨 <b>NEW HACK PURCHASE NOTIFICATION!</b> 🚨\n\n"
        f"👤 <b>User:</b> {html.escape(str(u_name or 'User'))}\n"
        f"🆔 <b>Telegram ID:</b> <code>{user_id}</code>\n"
        f"📱 <b>Phone:</b> <code>{html.escape(str(phone or 'N/A'))}</code>\n"
        f"🌐 <b>Country:</b> {html.escape(str(country or 'IN'))}\n"
        f"🎮 <b>Hack Purchased:</b> {html.escape(str(prod_name))}\n"
        f"⏱️ <b>Plan:</b> {html.escape(str(prod_days))}\n"
        f"💰 <b>Price Paid:</b> {amount}\n"
        f"💳 <b>Payment Method:</b> {payment_method}\n"
        f"🔑 <b>Delivered Key:</b> <code>{html.escape(key_text or 'N/A')}</code>\n"
        f"🆔 <b>Order ID:</b> <code>{html.escape(str(order_id))}</code>{dev_str}\n"
        f"📅 <b>Date/Time:</b> {purchase_time}"
    )
    live_username = _get_live_telegram_username(user_id, u_name)
    admin_purchase_text = _safe_format_custom_text(
        get_custom_text("purchase_notification", "{default_purchase}"),
        user=u_name or "User",
        name=u_name or "User",
        username=live_username,
        telegram_username=live_username,
        user_id=user_id,
        telegram_id=user_id,
        phone=phone or "N/A",
        number=phone or "N/A",
        country=country or "IN",
        hack=prod_name,
        product_name=prod_name,
        plan=prod_days,
        amount=f"{amount:.2f}",
        order_id=order_id,
        device_id=device_id or "",
        key=key_text or "N/A",
        purchased_key=key_text or "N/A",
        payment_method=payment_method,
        method=payment_method,
        pay_type=pay_type,
        date=purchase_time,
        time=purchase_time,
        default_purchase=default_purchase_text
    )
    admin_purchase_text = _inject_labeled_user_values(
        admin_purchase_text,
        {
            "name": html.escape(str(u_name or "User"), quote=False),
            "username": html.escape(str(live_username), quote=False),
            "username_at": html.escape(f"@{live_username}" if live_username else "", quote=False),
            "user_id": str(user_id),
            "phone": html.escape(str(phone or "N/A"), quote=False),
            "country": html.escape(str(country or "IN"), quote=False),
            "product_name": html.escape(str(prod_name), quote=False),
            "plan": html.escape(str(prod_days), quote=False),
            "amount": f"{amount}",
            "order_id": order_id,
            "device_id": device_id or "",
            "key": key_text or "N/A",
            "purchased_key": key_text or "N/A",
            "payment_method": payment_method,
            "method": payment_method,
            "date": purchase_time,
        }
    )
    # If a saved custom template omitted a key/method label, append the two
    # requested transaction facts without changing the rest of its design.
    plain_admin = re.sub(r"<[^>]+>", "", admin_purchase_text)
    if "Payment Method" not in plain_admin and "Method" not in plain_admin:
        admin_purchase_text += f"\n💳 <b>Payment Method:</b> {payment_method}"
    if key_text and "Delivered Key" not in plain_admin and "YOUR KEY" not in plain_admin and "Key:" not in plain_admin:
        admin_purchase_text += f"\n🔑 <b>Delivered Key:</b> <code>{html.escape(key_text)}</code>"
    admin_purchase_text = _repair_telegram_html_markup(_repair_premium_emoji_markup(admin_purchase_text))
    for admin_id in _load_persistent_admin_ids():
        try:
            bot.send_message(admin_id, admin_purchase_text, parse_mode="HTML")
        except Exception:
            try:
                plain = re.sub(r"<tg-emoji\b[^>]*>(.*?)</tg-emoji>", lambda m: m.group(1), admin_purchase_text, flags=re.I | re.S)
                plain = re.sub(r"<[^>]+>", "", plain)
                bot.send_message(admin_id, html.unescape(plain))
            except Exception:
                pass

def record_order(order_id, user_id, product_name, plan_days, price_paid, key_val):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    cursor = conn.cursor()
    date_now = _now_ist_text("%b %d · %H:%M IST")
    cursor.execute('''
        INSERT INTO order_history (order_id, user_id, product_name, plan_days, price_paid, purchased_key, date_time)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (order_id, user_id, product_name, plan_days, price_paid, key_val, date_now))
    cursor.execute('UPDATE users SET orders_count = orders_count + 1, lifetime_spent = lifetime_spent + ? WHERE user_id = ?', (price_paid, user_id))
    conn.commit()
    conn.close()

# ==================== FAMGATEWAY AUTO-CHECK LOGIC ====================

# ==================== FAMGATEWAY AUTO-CHECK LOGIC ====================

def _build_stylish_qr_image(payload, size=900):
    """Render the exact payment payload as a normal, scan-friendly QR.

    The encoded UPI payload is kept exactly the same as the gateway/fallback
    flow. Only the presentation is changed: standard black modules, white
    background, normal finder frames, and NO center logo/overlay.
    """
    payload = str(payload or "").strip()
    if not payload:
        raise ValueError("Empty QR payload")

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=16,
        border=4,
    )
    qr.add_data(payload)
    qr.make(fit=True)

    qr_img = qr.make_image(
        fill_color="black",
        back_color="white",
    ).convert("RGB")

    qr_img = qr_img.resize((size, size), Image.Resampling.NEAREST)

    output = io.BytesIO()
    output.name = "rg_cheat_shop_upi_qr.png"
    qr_img.save(output, format="PNG", optimize=True)
    output.seek(0)
    return output

def _decode_qr_payload_from_url(qr_url):
    """Recover the gateway QR's exact encoded payload before restyling it.

    OpenCV/numpy are deliberately imported only when a gateway actually returns
    an image that needs decoding. This keeps every generated child bot much
    lighter while preserving the exact QR fallback behavior.
    """
    if not qr_url or not isinstance(qr_url, str):
        return None

    try:
        import cv2
        import numpy as np
        if qr_url.startswith("data:image/"):
            _, encoded = qr_url.split(",", 1)
            import base64
            raw = base64.b64decode(encoded)
            arr = np.frombuffer(raw, dtype=np.uint8)
        elif qr_url.startswith(("http://", "https://")):
            res = HTTP_SESSION.get(qr_url, timeout=8)
            res.raise_for_status()
            arr = np.frombuffer(res.content, dtype=np.uint8)
        else:
            return None

        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is None:
            return None

        detector = cv2.QRCodeDetector()
        data, _, _ = detector.detectAndDecode(image)
        data = str(data or "").strip()
        return data or None
    except Exception as e:
        print(f"Gateway QR decode warning: {e}")
        return None


def _extract_gateway_qr_payload(data, qr_url, order_id, amount):
    """Prefer the gateway's own payload; otherwise decode its QR image."""
    if isinstance(data, dict):
        for key in (
            "upi_uri",
            "upi_url",
            "upi",
            "qr_data",
            "qr_string",
            "payment_uri",
            "payment_url",
            "deeplink",
        ):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    decoded = _decode_qr_payload_from_url(qr_url)
    if decoded:
        return decoded

    # Same receiver/order/amount fields as the original fallback QR.
    return (
        f"upi://pay?pa={urllib.parse.quote(_fam_upi, safe='@')}"
        f"&pn={urllib.parse.quote(BOT_BRAND_NAME)}"
        f"&am={float(amount):.2f}&cu=INR"
        f"&tn={urllib.parse.quote(str(order_id))}"
    )


def _legacy_create_fam_qr(amount):
    """Create a FAM order and return a styled QR image + the same order id.

    The gateway still creates the real order and verify_fam_order() still checks
    that exact order id. Only the visual QR image is changed.
    """
    amount = float(amount)
    _fam_cfg = _gateway_row("fam")
    _fam_api_key = (_fam_cfg[2] if _fam_cfg and _fam_cfg[2] else (_fam_cfg[3] if _fam_cfg and _fam_cfg[3] else FAM_API_KEY))
    _fam_upi = (_fam_cfg[1] if _fam_cfg and _fam_cfg[1] else RECEIVER_UPI)

    try:
        # Official FamGateway v2 uses /api/qr.php. Keep the older
        # /create_order.php endpoint as a compatibility fallback for an
        # explicitly configured legacy gateway.
        create_urls = []
        for base in _fam_gateway_base_candidates():
            create_urls.extend(_fam_endpoint_candidates(base, 'qr.php'))
            create_urls.extend(_fam_endpoint_candidates(base, 'create_order.php'))
        create_urls = list(dict.fromkeys(create_urls))

        last_error = None
        for endpoint_url in create_urls:
            try:
                res = HTTP_SESSION.get(
                    endpoint_url,
                    params={"amount": f"{amount:.2f}", "api_key": _fam_api_key},
                    timeout=10,
                )
                if res.status_code in (401, 403):
                    raise RuntimeError('FamGateway API token was rejected.')
                res.raise_for_status()
                res_json = res.json()
                data = res_json.get("data") or {}

                if res_json.get("status") == "success" or res_json.get("status") is True:
                    qr_url = data.get("qr_url") or data.get("qr")
                    order_id = data.get("order_id")

                    if qr_url and order_id:
                        payload = _extract_gateway_qr_payload(
                            data, qr_url, order_id, amount
                        )
                        try:
                            return _build_stylish_qr_image(payload), str(order_id)
                        except Exception as style_error:
                            print(f"Styled QR warning: {style_error}")

                        # Absolute final fallback: keep the original gateway QR.
                        return qr_url, str(order_id)
                last_error = res_json
            except Exception as endpoint_error:
                last_error = endpoint_error
                continue
        if last_error:
            print(f"Gateway QR Error: {last_error}")
    except Exception as e:
        print(f"Gateway QR Error: {e}")

    # Original direct-UPI fallback retained for gateway/API outages.
    order_id = (
        "FAM"
        + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        + str(random.randint(1000, 9999))
    )
    upi_uri = (
        f"upi://pay?pa={urllib.parse.quote(_fam_upi, safe='@')}"
        f"&pn={urllib.parse.quote(BOT_BRAND_NAME)}"
        f"&am={amount:.2f}&cu=INR&tn={urllib.parse.quote(order_id)}"
    )

    try:
        return _build_stylish_qr_image(upi_uri), order_id
    except Exception as style_error:
        print(f"Fallback styled QR warning: {style_error}")
        fallback_qr = (
            "https://api.qrserver.com/v1/create-qr-code/"
            f"?size=500x500&data={urllib.parse.quote(upi_uri, safe='')}"
        )
        return fallback_qr, order_id

def _legacy_verify_fam_order(order_id):
    _fam_cfg = _gateway_row("fam")
    _fam_api_key = (_fam_cfg[2] if _fam_cfg and _fam_cfg[2] else (_fam_cfg[3] if _fam_cfg and _fam_cfg[3] else FAM_API_KEY))
    if not _fam_api_key or not order_id:
        return False, None, None

    for base in _fam_gateway_base_candidates():
        for endpoint in ('verify-order.php', 'verify.php'):
            for verify_url in _fam_endpoint_candidates(base, endpoint):
                try:
                    res = HTTP_SESSION.get(
                        verify_url,
                        params={'order_id': str(order_id), 'api_key': _fam_api_key},
                        timeout=10,
                    )
                    if res.status_code in (401, 403):
                        return False, None, None
                    res_json = res.json()
                    if res_json.get('status') == 'success' or res_json.get('status') is True:
                        data = res_json.get('data') or {}
                        utr = data.get('utr', 'N/A')
                        sender = data.get('sender_name', 'UPI User')
                        return True, utr, sender
                    # A valid endpoint that says pending/expired is a normal
                    # negative result; do not jump to a different endpoint and
                    # accidentally reinterpret it.
                    if res.status_code in (200, 404, 408) and isinstance(res_json, dict):
                        status = str(res_json.get('status') or '').lower()
                        if status in {'pending', 'expired', 'not_found'}:
                            return False, None, None
                except Exception:
                    continue
    return False, None, None

def _handle_paid_key_delivery_failure(chat_id, user_id, order_id, amount, pay_type, product_name, product_days, reason='API did not return a key'):
    """Notify admins and compensate a verified paid order exactly once."""
    uid = int(user_id); amt = round(float(amount or 0), 2); ptype = str(pay_type or '').lower()
    should_credit = ptype not in {'wallet'}
    credited = False
    first_time = False
    try:
        with sqlite3.connect(BOT_DB_PATH, timeout=10) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS payment_delivery_failures (order_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, payment_type TEXT NOT NULL, amount REAL NOT NULL, product_name TEXT NOT NULL DEFAULT '', refunded INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)")
            cur = conn.execute("INSERT OR IGNORE INTO payment_delivery_failures (order_id,user_id,payment_type,amount,product_name,refunded,created_at) VALUES(?,?,?,?,?,?,?)", (str(order_id),uid,ptype,amt,str(product_name or ''),0,_now_ist_text()))
            first_time = cur.rowcount == 1
            conn.commit()
        # Do not call add_user_balance while the idempotency connection is open.
        if first_time and should_credit and amt > 0:
            add_user_balance(uid, amt)
            with sqlite3.connect(BOT_DB_PATH, timeout=10) as conn:
                conn.execute("UPDATE payment_delivery_failures SET refunded=1 WHERE order_id=?", (str(order_id),)); conn.commit()
            credited = True
        elif not first_time:
            with sqlite3.connect(BOT_DB_PATH, timeout=10) as conn:
                row = conn.execute("SELECT refunded FROM payment_delivery_failures WHERE order_id=?", (str(order_id),)).fetchone()
                credited = bool(row and row[0])
    except Exception as exc:
        print(f'[DELIVERY FAILURE COMPENSATION ERROR] order={order_id}: {exc}')
    user = get_user(uid) or []; name = str(user[1] if len(user)>1 and user[1] else 'User')
    phone = str(user[2] if len(user)>2 and user[2] else 'N/A')
    role = 'Reseller' if len(user)>11 and int(user[11] or 0)==1 else 'User'
    live_username = _get_live_telegram_username(uid, ''); username = '@'+live_username if live_username else 'N/A'
    refund_line = (f'💰 <b>Refund:</b> ₹{amt:.2f} added to wallet' if credited else ('💼 <b>Wallet:</b> existing wallet refund path handled' if ptype=='wallet' else '⚠️ <b>Refund:</b> not credited; check logs'))
    alert = ('🚨 <b>PAYMENT SUCCESS — KEY DELIVERY FAILED</b>\n\n'
        f'👤 <b>Name:</b> {html.escape(name)}\n🔗 <b>Username:</b> {html.escape(username)}\n'
        f'🆔 <b>Telegram User ID:</b> <code>{uid}</code>\n💬 <b>Chat ID:</b> <code>{int(chat_id)}</code>\n'
        f'👥 <b>Type:</b> {role}\n📱 <b>Phone:</b> <code>{html.escape(phone)}</code>\n'
        f'💰 <b>Paid Amount:</b> ₹{amt:.2f}\n📦 <b>Product:</b> {html.escape(str(product_name or "N/A"))}\n'
        f'⏱️ <b>Plan:</b> {html.escape(str(product_days or "N/A"))}\n'
        f'💳 <b>Payment Method:</b> {"Wallet" if ptype=="wallet" else "UPI"}\n'
        f'🧾 <b>Order ID:</b> <code>{html.escape(str(order_id))}</code>\n❌ <b>Status:</b> Key Not Delivered\n'
        f'📝 <b>Reason:</b> {html.escape(str(reason)[:500])}\n{refund_line}\n🕒 <b>Time:</b> {_now_ist_text()}')
    for aid in _load_persistent_admin_ids():
        try: bot.send_message(aid, alert, parse_mode='HTML')
        except Exception as exc: print(f'[DELIVERY FAILURE ADMIN ALERT ERROR] {aid}: {exc}')

def process_successful_payment(chat_id, user_id, message_id, order_id, amount, pay_type, utr, product_id=0, device_id=None):
    try:
        bot.delete_message(chat_id, message_id)
    except Exception:
        pass
    
    user = get_user(user_id)
    u_name = user[1] if user else "User"

    if pay_type == "reseller_activation":
        if not claim_processed_payment(order_id, user_id, "reseller_activation", amount):
            return
        _activate_reseller_after_payment(user_id, amount, order_id, utr)
        with reseller_qr_lock:
            session=reseller_qr_sessions.get(int(chat_id))
            if not session or session.get('order_id')==str(order_id):
                reseller_qr_sessions.pop(int(chat_id),None)
        try: bot.delete_message(chat_id, message_id)
        except Exception: pass
        show_shop_features(chat_id, (get_user(user_id) or [0,'User'])[1])
        return

    if pay_type == "topup":
        if not claim_processed_payment(order_id, user_id, "topup", amount):
            return
        before_topup_user = get_user(user_id)
        previous_bal = float(before_topup_user[4] or 0.0) if before_topup_user and len(before_topup_user) > 4 else 0.0
        add_user_balance(user_id, amount)
        updated_user = get_user(user_id)
        new_bal = float(updated_user[4] if updated_user else (previous_bal + float(amount)))
        notify_admins_topup(user_id, u_name, order_id, amount, new_bal, utr, previous_balance=previous_bal)

        # Add Balance success uses a separate admin-editable Premium Emoji/Text
        # template. Balance crediting happens before rendering, so Current Balance
        # is always the real post-credit balance.
        success_template = get_wallet_topup_success_emoji_template()
        success_msg = _render_wallet_topup_success_emoji_template(
            success_template,
            user_id=user_id,
            user_name=u_name,
            order_id=order_id,
            amount=amount,
            utr=utr,
            current_balance=new_bal,
        )
        markup = types.InlineKeyboardMarkup()
        btn_main = make_ui_button("🏠 Main Menu", callback_data="back_to_main_new", button_key="nav:success_main_menu", default_color="blue")
        markup.add(btn_main)
    elif product_id > 0 and _bot_make_is_product(get_product_by_id(product_id)):
        if not claim_processed_payment(order_id, user_id, str(pay_type), amount):
            return
        product = get_product_by_id(product_id)
        if product and (_product_hidden(product[1]) or _plan_hidden(product[0])):
            _handle_paid_key_delivery_failure(
                chat_id, user_id, order_id, amount, pay_type,
                product[1], product[3],
                reason='Product/plan was hidden before payment completion.'
            )
            bot.send_message(chat_id, '❌ <b>This product/plan is currently hidden.</b>\n\nThe payment amount has been returned to your wallet.', parse_mode='HTML')
            return
        _bot_make_pending_save(order_id,user_id,product_id,product[3],amount,pay_type)
        try: record_order(order_id,user_id,BOT_MAKE_PRODUCT_NAME,product[3],amount,'BOT-MAKE')
        except Exception: pass
        _bot_make_start_details(chat_id,user_id,order_id)
        return
    else:
        product = get_product_by_id(product_id)
        prod_name = product[1] if product else "VIP Hack"
        prod_days = product[3] if product else "1 Plan"
        pid_id = product[2] if product and product[2] and product[2] != '0' else "133"
        remote_dur = product[8] if len(product) > 8 and product[8] else prod_days
        tg_group_link = product[9] if len(product) > 9 and product[9] else ""

        if product and (_product_hidden(product[1]) or _plan_hidden(product[0])):
            _handle_paid_key_delivery_failure(
                chat_id, user_id, order_id, amount, pay_type,
                prod_name, prod_days,
                reason='Product/plan was hidden before payment completion.'
            )
            bot.send_message(
                chat_id,
                '❌ <b>This product/plan is currently hidden.</b>\n\n'
                'The payment amount has been returned to your wallet.',
                parse_mode='HTML',
            )
            return

        key_val = fetch_and_claim_manual_key(prod_name, prod_days)
        if not key_val:
            _refresh_multi_api_connection_if_needed(prod_name, int(product[0]))
            key_val = fetch_key_from_api(pid_id, remote_dur, android_id=device_id, product_name=prod_name, plan_id=product[0], purchase_ref=order_id)
        if not key_val:
            _handle_paid_key_delivery_failure(chat_id, user_id, order_id, amount, pay_type, prod_name, prod_days, reason='The API server did not return a key for the configured Product ID / Valid ID.')
            bot.send_message(chat_id, "❌ <b>Payment verified, but key delivery failed.</b>\n\nThe API server did not return a key. Your payment amount has been returned to your wallet automatically.", parse_mode="HTML")
            return

        record_order(order_id, user_id, prod_name, prod_days, amount, key_val)
        notify_admins_purchase(user_id, u_name, order_id, prod_name, prod_days, amount, device_id, pay_type, key_val)
        
        if user and user[12] > 0 and user[15] == 0:
            mark_ref_discount_used(user_id)

        usd_equiv = amount / 90.0

        dev_info = f"📱 <b>Device ID:</b> <code>{device_id}</code>\n" if device_id else ""

        payment_title = "💰 <b>WALLET PAYMENT SUCCESSFUL</b> 💰" if pay_type == "wallet" else "💳 <b>PAYMENT SUCCESSFUL</b> 💳"
        payment_method = "💼 Wallet Balance" if pay_type == "wallet" else "🇮🇳 Pay via UPI"
        # Wallet and UPI now have completely separate Premium Emoji/Text designs.
        # This keeps the existing Wallet editor intact and lets the admin customize
        # the UPI success message independently.
        payment_template = (
            get_wallet_payment_emoji_template()
            if str(pay_type).lower() == "wallet"
            else get_upi_payment_emoji_template()
        )
        if payment_template:
            success_msg = _render_wallet_payment_emoji_template(
                payment_template,
                user_id=user_id,
                order_id=order_id,
                product_id=product[0],
                product_name=prod_name,
                plan=prod_days,
                amount=amount,
                key_val=key_val,
                pay_type=pay_type,
                device_id=device_id,
            )
        else:
            success_msg = (
                f"{payment_title}\n"
                f"<i>Instant Key Delivery!</i>\n\n"
                f"📋 <b>ORDER DETAILS</b>\n"
                f"├── 👤 <b>User ID:</b> <code>{user_id}</code>\n"
                f"├── 🆔 <b>Order ID:</b> <code>{order_id}</code>\n"
                f"├── 🛒 <b>Product ID:</b> <code>{product[0]}</code>\n"
                f"├── 🎮 <b>Product:</b> {html.escape(str(prod_name))}\n"
                f"├── ⏱️ <b>Plan:</b> {html.escape(str(prod_days))}\n"
                f"├── 💳 <b>Method:</b> {payment_method}\n"
                f"{dev_info}"
                f"└── 💵 <b>Paid:</b> {amount}\n\n"
                f"🔑 <b>YOUR KEY:</b>\n"
                f"<code>{html.escape(str(key_val))}</code>\n\n"
                f"💡 <i>Tap the key above to copy instantly.</i>"
            )
        markup = types.InlineKeyboardMarkup()
        if tg_group_link:
            markup.add(make_ui_button("🔗 Join Telegram Group", url=tg_group_link, button_key="link:telegram_group", default_color="blue"))
        markup.add(make_ui_button("🏠 Main Menu", callback_data="back_to_main_new", button_key="nav:success_main_menu", default_color="blue"))

    _send_payment_success_safely(chat_id, success_msg, reply_markup=markup)

PAYMENT_POLL_INTERVAL = 1.5
PAYMENT_TIMEOUT_SECONDS = 300


def poll_payment_in_bot(chat_id, user_id, message_id, order_id, amount, pay_type, product_id=0, device_id=None):
    start_time = time.time()
    while time.time() - start_time < PAYMENT_TIMEOUT_SECONDS: 
        if order_id not in active_orders:
            return  
            
        active_details = active_orders.get(order_id) or {}
        order_gateway = str(active_details.get('gateway') or _get_active_payment_gateway()).strip().lower()
        is_paid, utr, sender = _verify_active_gateway_order(order_id, order_gateway)
        if is_paid:
            # The  Transaction Status API is authoritative for the order,
            # but we still require the returned transaction amount to match the
            # locally created order before crediting balance/delivering a key.
            active_details = active_orders.get(order_id) or {}
            expected_amount = float(active_details.get('amount', amount) or amount)
            if str(active_details.get('gateway') or order_gateway).lower() == '':
                verified_amount = active_details.get('verified_amount')
                # _verify__order returns only the success tuple for legacy
                # compatibility; re-fetching the status here would be wasteful.
                # The order amount is fixed by our own  QR request, so the
                # successful order ID is already bound to this exact amount.
                if abs(float(amount) - expected_amount) > 0.01:
                    time.sleep(PAYMENT_POLL_INTERVAL)
                    continue
            active_orders.pop(order_id, None)
            process_successful_payment(chat_id, user_id, message_id, order_id, amount, pay_type, utr, product_id, device_id)
            return
        time.sleep(PAYMENT_POLL_INTERVAL)
    
    if order_id in active_orders:
        order_details = active_orders.pop(order_id, None)
        if str(pay_type) == 'reseller_activation':
            with reseller_qr_lock:
                session=reseller_qr_sessions.get(int(chat_id))
                if session and session.get('order_id')==str(order_id):
                    reseller_qr_sessions.pop(int(chat_id),None)
        user = get_user(user_id)
        u_name = user[1] if user else "User"
        
        prod_name = "TopUp Balance"
        prod_days = "N/A"
        if product_id > 0:
            product = get_product_by_id(product_id)
            if product:
                prod_name = product[1]
                prod_days = product[3]
                
        record_pending_payment(order_id, user_id, u_name, prod_name, prod_days, amount)

        default_expire_msg = "⏱️ <b>Payment QR Expired!</b>\n5 minutes timeout completed. Please initiate a new request if you wish to pay."
        expire_text = get_custom_text("payment_expired", default_expire_msg)

        try:
            bot.delete_message(chat_id, message_id)
            bot.send_message(chat_id, expire_text, parse_mode="HTML")
        except Exception:
            pass

# ==================== WELCOME MESSAGE ====================
WELCOME_MESSAGE_KEY='welcome_message'
DEFAULT_WELCOME_MESSAGE=f'👋 <b>Welcome to {html.escape(BOT_BRAND_NAME)}!</b>\n\n<i>Premium keys • Instant delivery • Secure checkout</i>'
def get_welcome_message_template(): return get_setting(WELCOME_MESSAGE_KEY) or DEFAULT_WELCOME_MESSAGE
def set_welcome_message_template(template): set_setting(WELCOME_MESSAGE_KEY,_repair_premium_emoji_markup(str(template or '').strip()))
def _render_welcome_message(user_id,first_name):
    values=_get_user_template_values(user_id,first_name); values.update({'user':values['name'],'first_name':values['name'],'telegram_id':str(user_id)})
    text=_safe_format_custom_text(get_welcome_message_template(),**values); text=_inject_labeled_user_values(text,values); return _repair_telegram_html_markup(_repair_premium_emoji_markup(_replace_live_greeting_name(text,first_name)).strip())
def _delete_message_safely(chat_id,message_id):
    if message_id:
        try: bot.delete_message(chat_id,message_id)
        except Exception: pass
def _send_welcome_then_main(chat_id,user_id,first_name,start_message_id=None):
    welcome_msg=None
    try: welcome_msg=bot.send_message(chat_id,_render_welcome_message(user_id,first_name),parse_mode='HTML')
    except Exception: pass
    try: show_shop_features(chat_id,first_name)
    finally:
        if welcome_msg: _delete_message_safely(chat_id,welcome_msg.message_id)
        _delete_message_safely(chat_id,start_message_id)

# ==================== BOT COMMANDS & HANDLERS ====================

@bot.message_handler(func=lambda message: (not _is_admin(message.from_user.id)) and (is_user_banned(message.from_user.id) or not is_bot_enabled()))
def user_access_guard(message):
    if is_user_banned(message.from_user.id):
        bot.send_message(message.chat.id, "🚫 <b>Your access has been restricted.</b>", parse_mode="HTML")
    else:
        bot.send_message(message.chat.id, "🔧 <b>Bot Under Maintenance</b>", parse_mode="HTML")

@bot.message_handler(commands=['start'])
def send_welcome(message):
    _activity_log("/start", message.from_user, getattr(message, "text", ""))
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "User"
    try:
        _tg_username = str(getattr(message.from_user, 'username', '') or '').strip().lstrip('@')
        conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
        try:
            conn.execute("UPDATE users SET telegram_username=? WHERE user_id=?", (_tg_username, int(user_id)))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass

    if _child_bot_is_expired():
        if _is_admin(user_id):
            bot.send_message(message.chat.id, _expired_admin_text(), parse_mode='HTML')
        else:
            bot.send_message(message.chat.id, _expired_user_text(), parse_mode='HTML')
        return

    if not _is_admin(user_id):
        if is_user_banned(user_id):
            bot.send_message(message.chat.id, "🚫 <b>Your access has been restricted.</b>", parse_mode="HTML")
            return
        if not is_bot_enabled():
            bot.send_message(message.chat.id, "🔧 <b>Bot Under Maintenance</b>", parse_mode="HTML")
            return
    
    if user_id in admin_temp_data:
        admin_temp_data.pop(user_id, None)
    
    command_args = message.text.split()
    referred_by = 0
    if len(command_args) > 1 and command_args[1].startswith("ref_"):
        try:
            referred_by = int(command_args[1].replace("ref_", ""))
            if referred_by == user_id:
                referred_by = 0
        except ValueError:
            referred_by = 0

    user = get_user(user_id)

    if not user or user[10] == 0:
        save_or_update_user(user_id, first_name, verified=0, referred_by=referred_by)
        try:
            welcome_msg = bot.send_message(message.chat.id, _render_welcome_message(user_id, first_name), parse_mode='HTML')
            admin_temp_data.setdefault(user_id, {})['welcome_message_id'] = welcome_msg.message_id
        except Exception:
            pass
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        btn_contact = types.KeyboardButton(text="📱 Share Contact", request_contact=True)
        markup.add(btn_contact)

        verification_text = (
            f"🏪 <b>{html.escape(BOT_BRAND_NAME)}</b>\n\n"
            f"👋 <b>Welcome, {first_name}!</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔒 <b>VERIFICATION REQUIRED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>To start shopping, please verify your phone number.</b>\n\n"
            f"✅ <b>Why we need this:</b>\n"
            f"• <b>Secure your purchases</b>\n"
            f"• <b>Deliver keys to you</b>\n"
            f"• <b>Protect your account</b>\n\n"
            f"<i>Tap the button below to share your contact.</i>"
        )
        verification_template = get_custom_text("verification_required", "{default_verification_required}")
        verification_values = _get_user_template_values(user_id, first_name)
        verification_values.update({
            "user": verification_values["name"],
            "telegram_id": str(user_id),
            "number": verification_values["phone"],
            "default_verification_required": verification_text,
        })
        verification_text = _safe_format_custom_text(verification_template, **verification_values)
        verification_text = _inject_labeled_user_values(verification_text, verification_values)
        verification_text = _replace_live_greeting_name(verification_text, first_name)
        bot.send_message(message.chat.id, verification_text, parse_mode="HTML", reply_markup=markup)
        _delete_message_safely(message.chat.id, message.message_id)
    else:
        _send_welcome_then_main(message.chat.id, user_id, first_name, start_message_id=message.message_id)

@bot.message_handler(content_types=['contact'])
def handle_contact_verification(message):
    if message.contact is not None:
        user_id = message.from_user.id
        first_name = message.from_user.first_name or "User"
        phone_number = message.contact.phone_number

        user = get_user(user_id)
        referred_by = user[13] if user and len(user) > 13 else 0
        was_already_verified = bool(user and len(user) > 10 and user[10] == 1)
        welcome_message_id = admin_temp_data.get(user_id, {}).get('welcome_message_id')

        save_or_update_user(user_id, first_name, phone_number, verified=1)

        if referred_by > 0:
            reward_referrer_discount(referred_by)
            try:
                bot.send_message(referred_by, f"🎉 <b>New Referral Verified!</b>\n\nUser <b>{first_name}</b> verified their phone number using your link!\n🎁 <b>₹2.00 INR balance has been added to your wallet!</b>", parse_mode="HTML")
            except Exception:
                pass

        default_new_user_text = (
            f"🚨 <b>NEW USER VERIFIED!</b> 🚨\n\n"
            f"👤 <b>Name:</b> {first_name}\n"
            f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
            f"📱 <b>Phone Number:</b> <code>{phone_number}</code>\n"
            f"📅 <b>Date/Time:</b> {_now_ist_text()}"
        )
        new_user_values = _get_user_template_values(user_id, first_name, phone_number)
        new_user_values.update({
            "name": html.escape(str(first_name)),
            "user": html.escape(str(first_name)),
            "user_id": str(user_id),
            "telegram_id": str(user_id),
            "phone": html.escape(str(phone_number or "N/A")),
            "number": html.escape(str(phone_number or "N/A")),
            "date": _now_ist_text(),
            "default_new_user": default_new_user_text,
        })
        admin_notification_template = get_custom_text("new_user_notification", "{default_new_user}")
        admin_notification_text = _safe_format_custom_text(
            admin_notification_template,
            **new_user_values
        )
        admin_notification_text = _inject_labeled_user_values(admin_notification_text, new_user_values)
        # Only a first successful verification is a "New User" event.
        if not was_already_verified:
            for admin_id in _load_persistent_admin_ids():
                try:
                    bot.send_message(admin_id, admin_notification_text, parse_mode="HTML")
                except Exception:
                    try:
                        plain = re.sub(r"<tg-emoji\b[^>]*>(.*?)</tg-emoji>", lambda m: m.group(1), admin_notification_text, flags=re.I | re.S)
                        plain = re.sub(r"<[^>]+>", "", plain)
                        bot.send_message(admin_id, html.unescape(plain))
                    except Exception:
                        pass

        verified_text = (
            f"✅ <b>Phone verified!</b>\n\n"
            f"📞 <b>{phone_number}</b>\n"
            f"🇮🇳 <b>India</b>\n\n"
            f"<b>Welcome aboard! Loading shop...</b>"
        )
        verified_template = get_custom_text("phone_verified", "{default_phone_verified}")
        verified_values = _get_user_template_values(user_id, first_name, phone_number)
        verified_values.update({
            "user": verified_values["name"],
            "telegram_id": str(user_id),
            "number": verified_values["phone"],
            "default_phone_verified": verified_text,
        })
        verified_text = _safe_format_custom_text(verified_template, **verified_values)
        verified_text = _inject_labeled_user_values(verified_text, verified_values)
        bot.send_message(message.chat.id, verified_text, parse_mode="HTML", reply_markup=types.ReplyKeyboardRemove())
        _delete_message_safely(message.chat.id, welcome_message_id)
        admin_temp_data.pop(user_id, None)
        _send_welcome_then_main(message.chat.id, user_id, first_name, start_message_id=message.message_id)

# ==================== ADMIN PANEL MENU ====================


# ==================== LEGACY ADMIN PANEL SOURCE (PRESERVED, NOT EXECUTED) ====================
# The original admin panel source is retained verbatim below so existing labels/text
# are not discarded while the live menu is organized into categories.
# @bot.message_handler(commands=['admin'])
# def _start_child_admin_expiry_timer(chat_id, message_id):
    if BOT_CREATOR_ENABLED or BOT_EXPIRES_AT <= 0:
        return
    key = f'child_admin_expiry:{chat_id}:{message_id}'
    timers = globals().setdefault('_CHILD_ADMIN_EXPIRY_TIMERS', {})
    old = timers.get(key)
    if old and old.is_alive():
        return
    stop_event = threading.Event()
    timers[key] = stop_event
    def worker():
        try:
            while not stop_event.is_set():
                remaining = _format_remaining_time(BOT_EXPIRES_AT)
                if time.time() >= BOT_EXPIRES_AT:
                    text = _expired_admin_text()
                    try:
                        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, parse_mode='HTML')
                    except Exception:
                        pass
                    break
                text = (
                    '🛠️ <b>ADMIN CONTROL PANEL</b>\n\n'
                    '<i>Clean controls • Clear names • All important settings in sections</i>\n\n'
                    f'⏳ <b>Bot Expiry Countdown:</b> <code>{remaining}</code>'
                )
                try:
                    bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, parse_mode='HTML', reply_markup=_admin_main_markup())
                except Exception:
                    break
                stop_event.wait(1.0)
        finally:
            timers.pop(key, None)
    threading.Thread(target=worker, daemon=True, name='child-admin-expiry-live').start()

def admin_panel(message):
    # Legacy panel source retained verbatim below; live implementation is
    # defined later in the file.
    pass
#     user_id = message.from_user.id
#     if not _is_admin(user_id):
#         bot.send_message(message.chat.id, "❌ <b>Access Denied!</b> Only Admin can access this command.", parse_mode="HTML")
#         return
#     
#     markup = types.InlineKeyboardMarkup()
#     btn_quick_add = types.InlineKeyboardButton("⚡ Quick Admin Setup (One-Msg Hack Setup)", callback_data="admin_quick_setup")
#     btn_reorder_hacks = types.InlineKeyboardButton("🔄 Reorder Hacks List Sequence", callback_data="admin_reorder_hacks")
#     btn_user_reset = types.InlineKeyboardButton("🔄 Reset User Completely (By Telegram ID)", callback_data="admin_user_reset")
#     btn_stock_mgmt = types.InlineKeyboardButton("📦 Stock On/Off (Out of Stock System)", callback_data="admin_stock_mgmt")
#     btn_device_id_mgmt = types.InlineKeyboardButton("📱 Select Device ID Hack", callback_data="admin_device_id_mgmt")
#     btn_edit_price = types.InlineKeyboardButton("✏️ Edit Product Price & Plans", callback_data="admin_edit_price")
#     btn_tg_group = types.InlineKeyboardButton("🔗 Set Telegram Group Link", callback_data="admin_set_tg_group")
#     btn_manage_hack_day = types.InlineKeyboardButton("⚙️ Manage Hack & Days (Add/Remove)", callback_data="admin_hack_day_mgmt")
#     btn_server_api = types.InlineKeyboardButton("🌐 Add & Connect Server API", callback_data="admin_server_api_mgmt")
#     btn_hack_server_manager = types.InlineKeyboardButton("⚙️ Hack API & Server Manager", callback_data="admin_hack_server_manager")
#     btn_manual = types.InlineKeyboardButton("🔑 Add Manual VIP Keys (FIFO)", callback_data="admin_add_manual_key")
#     btn_reseller = types.InlineKeyboardButton("👑 Add / Remove Reseller Role", callback_data="admin_manage_reseller")
#     btn_disc = types.InlineKeyboardButton("🏷️ Manage Discounts (User/Global/Hack)", callback_data="admin_manage_discounts")
#     btn_bcast = types.InlineKeyboardButton("📢 Multimedia Broadcast", callback_data="admin_broadcast")
#     btn_set_guide = types.InlineKeyboardButton("🎬 Dynamic How To Use Bot Link", callback_data="admin_set_guide")
#     btn_server_id_map = types.InlineKeyboardButton("🔗 Map Server Hack ID & Duration", callback_data="admin_map_server_id")
#     btn_token_change = types.InlineKeyboardButton("🔑 Change Bot API Token", callback_data="admin_change_bot_token")
#     btn_track = types.InlineKeyboardButton("👤 Track Users & Purchased Keys", callback_data="admin_track_users")
#     btn_bal = types.InlineKeyboardButton("💰 Manage User Balance", callback_data="admin_manage_bal")
#     
#     btn_pending = types.InlineKeyboardButton("⏳ Pending Payments", callback_data="admin_view_pending_payments")
#     btn_db_backup = types.InlineKeyboardButton("📥 Download Database Backup", callback_data="admin_db_backup")
#     btn_button_cust = types.InlineKeyboardButton("🎨 All Button Color", callback_data="admin_button_colors")
#     btn_button_color = types.InlineKeyboardButton("✏️ User Panel Names & Emoji", callback_data="admin_button_cust")
#     btn_add_balance_cancel = types.InlineKeyboardButton("❌ Add Balance Cancel Button", callback_data="cust_name_topkey_cancel")
#     btn_add_balance_confirm = types.InlineKeyboardButton("💳 Add Balance Confirm Button", callback_data="cust_name_topkey_confirm")
#     btn_all_products_oos = types.InlineKeyboardButton("🔴 All Products Out of Stock Button", callback_data="cust_name_all_products_oos")
#     btn_text_editor = types.InlineKeyboardButton("✏️ Edit Bot Texts (Text ID)", callback_data="admin_text_editor")
#     btn_emoji_editor = types.InlineKeyboardButton("✨ Premium Emoji Editor", callback_data="admin_emoji_editor")
#     btn_all_button_emoji = types.InlineKeyboardButton("✨ All Button Emoji", callback_data="admin_all_button_emoji")
#     btn_all_product_emoji = types.InlineKeyboardButton("✨ All Product Button Emoji", callback_data="admin_all_product_emoji")
#     btn_all_price_emoji = types.InlineKeyboardButton("💰 All Price List Button Emoji", callback_data="admin_all_price_emoji")
#     btn_price_list_mode = types.InlineKeyboardButton(
#         ("🟢 Premium Price List: ON" if get_price_list_premium_mode() else "🔴 Premium Price List: OFF"),
#         callback_data="admin_toggle_price_list_mode"
#     )
#     btn_all_panel_price_emoji = types.InlineKeyboardButton("💠 All Panel Price & Text + Premium Emoji", callback_data="admin_all_panel_price_emoji")
#     btn_plan_text_add = types.InlineKeyboardButton("📝 All Product Plan Text + Premium Emoji", callback_data="admin_plan_text_add")
# 
#     btn_hack_price_ui = types.InlineKeyboardButton("🧩 Price List Fix — Emoji & Text", callback_data="admin_hack_price_ui")
# 
#     markup.add(btn_quick_add)
#     markup.add(btn_reorder_hacks, btn_user_reset)
#     markup.add(btn_stock_mgmt, btn_device_id_mgmt)
#     markup.add(btn_edit_price, btn_tg_group)
#     markup.add(btn_manage_hack_day, btn_server_api)
#     markup.add(btn_hack_server_manager)
#     markup.add(btn_server_id_map, btn_manual)
#     markup.add(btn_reseller, btn_disc)
#     markup.add(btn_bcast, btn_set_guide)
#     markup.add(btn_token_change, btn_track)
#     markup.add(btn_bal, btn_pending)
#     markup.add(btn_db_backup, btn_button_cust)
#     markup.add(btn_button_color, btn_text_editor)
#     markup.add(btn_emoji_editor)
#     markup.add(btn_all_button_emoji)
#     markup.add(btn_all_product_emoji, btn_all_price_emoji)
#     markup.add(btn_price_list_mode)
#     markup.add(btn_all_panel_price_emoji)
#     markup.add(btn_plan_text_add)
#     markup.add(btn_hack_price_ui)
#     
#     bot.send_message(message.chat.id, "🛠️ <b>ADMIN CONTROL PANEL</b>\n\nSelect an operation below:", parse_mode="HTML", reply_markup=markup)
# 
# ==================== END LEGACY ADMIN PANEL SOURCE ====================

@bot.message_handler(commands=['admin'])
def _admin_command_handler(message):
    # Keep /admin as a dedicated Telegram command handler.
    # The live admin_panel() below contains the existing panel logic unchanged.
    return admin_panel(message)

def _is_admin_ui_callback(data):
    """Return True when a callback belongs to the Admin Panel navigation.

    Admin screens are rendered in one Telegram message so opening any Admin
    button replaces the current Admin screen instead of stacking another
    message underneath it. User-facing callbacks are explicitly excluded.
    """
    data = str(data or '')
    user_prefixes = (
        'topkey_', 'topup_', 'pay_topup_', 'pay_upi_', 'pay_wallet_',
        'prod_', 'checkout_', 'open_store', 'my_account', 'orders',
        'invite_earn', 'how_to_use_bot', 'help_desk', 'out_of_stock_alert',
        'back_to_main', 'back_to_main_new', 'back_from_qr', 'reseller_qr_back',
        'reseller_my_account', 'reseller_api_generate', 'reseller_api_catalog', 'reseller_api_reset'
    )
    if data in {'open_store','my_account','orders','invite_earn','how_to_use_bot',
                'help_desk','top_up','topup_custom','out_of_stock_alert',
                'back_to_main','back_to_main_new','back_from_qr','reseller_qr_back',
                'reseller_my_account','reseller_api_generate','reseller_api_catalog','reseller_api_reset'}:
        return False
    if data.startswith(user_prefixes):
        return False
    # Every other callback handled by the single callback handler is an Admin
    # callback when the clicking user is an Admin. This also makes newly added
    # Admin buttons inherit the same in-place navigation automatically.
    return True


def _is_admin_success_message(text):
    plain = re.sub(r'<[^>]+>', '', str(text or '')).strip().lower()
    if not plain:
        return False
    markers = (
        'successfully', 'saved successfully', 'updated successfully',
        'added successfully', 'deleted successfully', 'connect successfully',
        'connection successful', 'stock status updated', 'role updated',
        'premium emoji saved', 'success!', 'saved!', 'updated!', 'deleted!'
    )
    return any(marker in plain for marker in markers)


def _admin_return_category_for_callback(data):
    """Resolve an admin callback to the section that should remain open.

    Nested edit/save actions are mapped back to their parent screen so a
    successful operation never throws the admin back to the Main Admin Panel.
    """
    data = str(data or "")
    if data.startswith("admin_cat_"):
        return ("category", data.replace("admin_cat_", "", 1))

    # Product / plan management.
    if (data == "admin_hack_day_mgmt" or
        data in {"admin_add_hack_plan", "admin_add_day_exist", "admin_del_hack",
                 "admin_del_plan", "admin_edit_hack_inside", "admin_set_tg_group"} or
        data.startswith(("sel_hack_add_day_", "edit_hack_", "del_hack_",
                         "del_plan_", "set_tg_hack_"))):
        return ("hack_day", "")

    # API/server screens.
    if data == "admin_product_hide" or data.startswith("ph_"):
        return ("category", "setup")
    if data in {"admin_hack_server_manager"} or data.startswith("hack_server_"):
        return ("hack_server", "")
    if data in {"new_server_api", "admin_api_system", "admin_server_api_mgmt",
                "api_srv_add", "tobix_api_system", "tobix_set_token", "tobix_set_url",
                "tobix_check", "tobix_products", "rg_api_system"} or data.startswith(("api_srv_", "new_server_", "tobix_", "rgapi_")):
        return ("api", "")

    # Payment gateway and admin-account screens.
    if data == "admin_gateway_manager" or data.startswith("gw_"):
        return ("gateway", "")
    if data in {"admin_manage_admins", "admin_add_id", "admin_remove_id"}:
        return ("admins", "")

    # Price/emoji/text editors.
    if data == "admin_hack_price_ui" or data.startswith(("hpui_", "hack_price_")):
        return ("hack_price", "")
    if data in {"admin_button_cust", "admin_button_colors", "admin_emoji_editor",
                "admin_all_button_emoji", "admin_all_product_emoji",
                "admin_all_price_emoji", "admin_all_panel_price_emoji"} or data.startswith(("btn_", "emoji_")):
        return ("category", "emoji")
    if data in {"admin_text_editor", "admin_plan_text_add", "admin_toggle_price_list_mode"}:
        return ("category", "text")

    # User/reseller, tools and system sections.
    if data.startswith("admin_"):
        if data in {"admin_user_reseller_search", "admin_track_users", "admin_manage_bal", "admin_user_ban_unban",
                    "admin_manage_reseller", "admin_manage_discounts", "admin_user_reset",
                    "admin_reset_all_users", "admin_reset_all_users_confirm", "admin_restore_all_users", "admin_restore_all_users_confirm", "admin_device_id_mgmt"}:
            return ("category", "users")
        if data in {"admin_broadcast", "admin_set_guide", "admin_support_settings",
                    "admin_update_link"}:
            return ("category", "tools")
        if data in {"admin_bot_toggle", "admin_change_bot_token", "admin_db_backup"}:
            return ("category", "system")
        if data in {"admin_reorder_hacks", "admin_quick_setup", "admin_stock_mgmt",
                    "admin_edit_price"}:
            return ("category", "setup")

    return admin_return_state.get("_last_fallback", ("category", "setup"))


def _remember_admin_navigation(user_id, callback_data):
    """Remember the admin section associated with the current callback."""
    try:
        state = _admin_return_category_for_callback(callback_data)
        admin_return_state[int(user_id)] = state
    except Exception:
        pass


def _send_hack_day_management(chat_id, message_id=None):
    """Render the existing Hack & Day Management panel in-place."""
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("➕ Add New Hack & Day Plan", callback_data="admin_add_hack_plan"),
        types.InlineKeyboardButton("📅 Add Day to Existing Hack", callback_data="admin_add_day_exist"),
    )
    markup.add(types.InlineKeyboardButton("✏️ Edit Existing Hack / Price / Plan", callback_data="admin_edit_hack_inside"))
    markup.add(
        types.InlineKeyboardButton("🗑️ Remove Entire Hack", callback_data="admin_del_hack"),
        types.InlineKeyboardButton("❌ Remove Day / Plan", callback_data="admin_del_plan"),
    )
    # This panel is also opened directly by success/step handlers, so it does
    # not always pass through _admin_ui_send(). Keep its existing controls and
    # add only the missing navigation control.
    _ensure_admin_back_button(markup)
    text = "⚙️ <b>HACK & DAY MANAGEMENT PANEL</b>\n\nSelect action:"
    if message_id:
        try:
            return bot.edit_message_text(text, chat_id=chat_id, message_id=message_id,
                                         parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass
    return bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)


def _send_admin_return_screen(chat_id, user_id):
    """Re-open the section the admin was using after a successful action."""
    state = admin_return_state.get(int(user_id), ("category", "setup"))
    kind, value = state
    try:
        if kind == "gateway":
            return _send_gateway_manager(chat_id)
        if kind == "admins":
            return _send_admin_manager(chat_id)
        if kind == "hack_day":
            return _send_hack_day_management(chat_id)
        if kind == "hack_server":
            return bot.send_message(
                chat_id,
                "⚙️ <b>HACK API & SERVER MANAGER</b>\n\nSelect a hack. Its API/Server/Product ID and plan-by-plan Valid IDs are saved separately.",
                parse_mode="HTML", reply_markup=_server_manager_hacks_markup()
            )
        if kind == "hack_price":
            return show_hack_price_ui_catalog(chat_id)
        if kind == "api":
            return _show_api_server_list(chat_id)
        if kind == "category":
            category = value or "setup"
            title = "⚙️ <b>BOT & DATABASE SETTINGS</b>" if category == "system" else "🛠️ <b>ADMIN SECTION</b>"
            return bot.send_message(
                chat_id, title + "\n\nSelect an operation:",
                parse_mode="HTML", reply_markup=_admin_category_markup(category)
            )
    except Exception as exc:
        print(f"[ADMIN RETURN SCREEN ERROR] user={user_id}: {exc}")
    return None


def _send_admin_panel_after_success(chat_id, user_id=None):
    """Return to the admin section that was active before the saved action."""
    try:
        if user_id is not None:
            result = _send_admin_return_screen(chat_id, user_id)
            if result is not None:
                return result
        return bot.send_message(
            chat_id,
            "🛠️ <b>ADMIN CONTROL PANEL</b>\n\n"
            "<i>Clean controls • Clear names • All important settings in sections</i>",
            parse_mode="HTML",
            reply_markup=_admin_main_markup()
        )
    except Exception:
        return None


def _admin_is_dynamic_list_callback(callback_data):
    """Callbacks that represent selectable records, not fixed menu actions.

    These stay one-per-row so long product/server/user names remain readable.
    Fixed Admin actions are automatically packed into a clean two-column grid.
    """
    cb = str(callback_data or "").lower()
    dynamic_prefixes = (
        "api_srv_", "api_hacks_", "api_check_", "new_server_hack_",
        "new_server_plan_", "select_del_plan_hack_", "confirm_del_hack_",
        "confirm_del_plan_", "sel_hack_add_day_", "edit_hack_",
        "del_hack_", "del_plan_", "set_tg_hack_", "botmake_del_",
        "admin_user_profile_", "admin_user_", "user_", "select_",
    )
    return cb.startswith(dynamic_prefixes)


def _reflow_admin_markup(markup):
    """Make nested Admin keyboards visually consistent without deleting controls.

    Existing multi-button rows are preserved. Consecutive single-button rows
    made of fixed Admin actions are paired into two columns; record-selection
    lists and navigation rows remain full-width. This changes presentation only:
    every original button object/callback is retained exactly once.
    """
    if not isinstance(markup, types.InlineKeyboardMarkup):
        return markup
    try:
        rows = [list(row or []) for row in (getattr(markup, "keyboard", None) or [])]
        if not rows:
            return markup

        rebuilt = []
        pending = None

        def flush_pending():
            nonlocal pending
            if pending is not None:
                rebuilt.append([pending])
                pending = None

        for row in rows:
            # Keep explicitly grouped rows exactly as the caller created them.
            if len(row) != 1:
                flush_pending()
                rebuilt.append(row)
                continue

            button = row[0]
            cb = str(getattr(button, "callback_data", "") or "")
            txt = str(getattr(button, "text", "") or "")
            low = (cb + " " + txt).lower()
            is_navigation = (
                "admin_main" in cb.lower() or "admin_system_back" in cb.lower() or
                "admin_back_main" in cb.lower() or "back" in low or
                "previous" in low or "next" in low
            )

            # Long/dynamic record selectors are deliberately kept readable.
            if is_navigation or _admin_is_dynamic_list_callback(cb):
                flush_pending()
                rebuilt.append([button])
                continue

            if pending is None:
                pending = button
            else:
                rebuilt.append([pending, button])
                pending = None

        flush_pending()

        # Only replace the keyboard when the layout actually changed.
        if rebuilt != rows:
            markup.keyboard = rebuilt
    except Exception as exc:
        print(f"[ADMIN KEYBOARD REFLOW ERROR] {exc}")
    return markup


def _style_admin_markup(markup):
    """Style Admin controls, organize inner menus, and guarantee Back navigation.

    This is presentation/navigation-only. No existing Admin button, callback or
    feature is removed. Nested fixed-action menus are automatically arranged in
    a compact two-column grid while dynamic lists stay readable one-per-row.
    """
    if not isinstance(markup, types.InlineKeyboardMarkup):
        return markup
    try:
        has_back = False
        is_root = False
        rows = getattr(markup, "keyboard", None) or []
        for row in rows:
            for button in (row or []):
                cb = str(getattr(button, "callback_data", "") or "").lower()
                txt = str(getattr(button, "text", "") or "").lower()
                is_back = (
                    "back" in cb or "back" in txt or
                    "admin_main" in cb or "admin_system_back" in cb
                )
                if is_back:
                    has_back = True
                if cb.startswith("admin_cat_") and cb in {
                    "admin_cat_setup", "admin_cat_api", "admin_cat_emoji",
                    "admin_cat_text", "admin_cat_users", "admin_cat_tools",
                    "admin_cat_system"
                }:
                    is_root = True
                try:
                    # Preserve an explicitly selected Admin palette color.
                    # Buttons created by _admin_colorful_button already carry a
                    # style; generic Admin buttons still receive the existing
                    # default primary/danger styling.
                    if not getattr(button, "style", None):
                        button.style = "danger" if is_back else "primary"
                except Exception:
                    pass

        # Add only to nested Admin menus. The root Main Admin Panel remains the
        # root and therefore has no redundant Back button.
        if not has_back and not is_root:
            markup.add(make_ui_button(
                "🔙 Back",
                callback_data="admin_back_main",
                button_key="admin:navigation:back",
                default_color="red",
                force_style=True,
            ))

        # Reflow AFTER the Back button is added, so Back always gets its own row.
        markup = _reflow_admin_markup(markup)
    except Exception as exc:
        print(f"[ADMIN BUTTON STYLE ERROR] {exc}")
    return _filter_disabled_admin_markup(markup)


def _ensure_admin_back_button(markup, label="🔙 Back", callback_data="admin_nav_back"):
    """Keep exactly one Admin Back button at the bottom of the keyboard.

    All Admin Back controls use the universal navigation stack.  This prevents
    nested Product/Plan screens from jumping to Main Admin or entering a
    parent-callback loop.  The current screen is popped one level at a time;
    when the stack is empty the handler safely returns to Main Admin.
    Existing non-navigation controls are preserved unchanged.
    """
    if not isinstance(markup, types.InlineKeyboardMarkup):
        return markup
    try:
        rows = [list(row or []) for row in (getattr(markup, "keyboard", None) or [])]
        normal_rows = []
        back_button = None
        for row in rows:
            keep = []
            for button in row:
                cb = str(getattr(button, "callback_data", "") or "")
                txt = str(getattr(button, "text", "") or "")
                low_cb, low_txt = cb.lower(), txt.lower()
                # A User Panel Back-button can legitimately contain the word
                # "Back" in its *label* while its callback is a selectable
                # catalog item (upc_select_*, abe_select_* or cust_name_*).
                # Never collapse those four editable buttons into the Admin
                # navigation Back button.
                catalog_select = low_cb.startswith((
                    "upc_select_", "abe_select_", "emoji_pick_", "cust_name_"
                ))
                is_back = (
                    not catalog_select and (
                        low_cb.startswith(("admin_back", "admin_nav_back", "upc_back")) or
                        low_cb in {"admin_main", "admin_system_back", "admin_back_main"} or
                        ("back" in low_txt)
                    )
                )
                if is_back:
                    if back_button is None:
                        back_button = button
                    # Duplicate Back controls are navigation duplicates, not
                    # functional Product/Plan controls, so they are collapsed.
                    continue
                keep.append(button)
            if keep:
                normal_rows.append(keep)

        if back_button is None:
            back_button = make_ui_button(
                label, callback_data="admin_nav_back",
                button_key="admin:navigation:back",
                default_color="red", force_style=True
            )
        else:
            # Every Admin Back button follows one deterministic route.
            back_button.callback_data = "admin_nav_back"
            if not getattr(back_button, "text", None):
                back_button.text = label
            try:
                back_button.style = "danger"
            except Exception:
                pass

        normal_rows.append([back_button])
        markup.keyboard = normal_rows
    except Exception as exc:
        print(f"[ADMIN BACK BUTTON ERROR] {exc}")
    return markup


def _admin_ui_send(call, *args, **kwargs):
    """Send an Admin screen in-place and preserve the current admin section."""
    if not args:
        return _admin_ui_send(call, **kwargs)
    text = args[0]
    extra_args = args[1:]
    chat_id = call.message.chat.id
    user_id = getattr(getattr(call, "from_user", None), "id", None)
    if user_id is not None and _is_admin_ui_callback(getattr(call, "data", "")):
        _remember_admin_navigation(user_id, getattr(call, "data", ""))
        # When this Admin action becomes a text-input/Premium-emoji step
        # (identified by the absence of an inline keyboard), remember the exact
        # screen immediately before it.  The step handler can then return there
        # without making the admin reopen /admin and navigate again.
        if not isinstance(kwargs.get("reply_markup"), types.InlineKeyboardMarkup):
            _remember_admin_pending_return(
                user_id,
                getattr(call, "data", ""),
                message_id=getattr(getattr(call, "message", None), "message_id", None)
            )

    # Navigation safety: every Admin Panel screen rendered through this helper
    # gets a Back button unless one already exists. User-facing callbacks are
    # explicitly excluded by _is_admin_ui_callback().
    if _is_admin_ui_callback(getattr(call, 'data', '')):
        if isinstance(kwargs.get("reply_markup"), types.InlineKeyboardMarkup):
            if user_id is not None:
                # This is a navigational/menu screen, not a pending text-input
                # step. Drop any stale one-level return context from an older action.
                admin_pending_return.pop(int(user_id), None)
            kwargs["reply_markup"] = _style_admin_markup(
                _ensure_admin_back_button(kwargs["reply_markup"])
            )
        else:
            # Input/prompt screens used to have no Back button at all. Add a
            # one-level Back control using the same pending parent that will be
            # used after Save.
            try:
                ctx = admin_pending_return.get(int(user_id)) if user_id is not None else None
                back_cb = "admin_nav_back"
                back_markup = types.InlineKeyboardMarkup(row_width=1)
                back_markup.add(make_ui_button(
                    "🔙 Back",
                    callback_data=back_cb,
                    button_key="admin:navigation:back",
                    default_color="red",
                    force_style=True,
                ))
                kwargs["reply_markup"] = back_markup
            except Exception:
                pass

    if _is_admin_ui_callback(getattr(call, 'data', '')) and not extra_args:
        edit_kwargs = {}
        for key in ('parse_mode', 'reply_markup', 'disable_web_page_preview',
                    'disable_notification', 'protect_content', 'link_preview_options',
                    'entities'):
            if key in kwargs:
                edit_kwargs[key] = kwargs[key]
        try:
            edited = bot.edit_message_text(
                text, chat_id=chat_id, message_id=call.message.message_id, **edit_kwargs
            )
            _admin_store_snapshot(user_id,text,kwargs.get("reply_markup"),getattr(call,"data",""),getattr(getattr(call,"message",None),"message_id",0))
            return edited
        except Exception:
            pass
    result=bot.send_message(chat_id,text,*extra_args,**kwargs)
    if user_id is not None and _is_admin_ui_callback(getattr(call,"data","")):
        _admin_store_snapshot(user_id,text,kwargs.get("reply_markup"),getattr(call,"data",""),getattr(getattr(call,"message",None),"message_id",0))
    return result


# Admin prompts created by older direct bot.send_message() calls used to have
# no Back button. Wrap next-step registration once so every Admin input prompt
# gets the same one-level Back navigation without changing any user-facing flow.
try:
    _ORIGINAL_REGISTER_NEXT_STEP_HANDLER = bot.register_next_step_handler
    if not getattr(bot, "_rg_admin_nav_wrapped", False):
        def _rg_admin_register_next_step_handler(message, callback, *args, **kwargs):
            try:
                # ``message`` is normally the OUTGOING prompt created by
                # bot.send_message(), so message.from_user is the bot itself.
                # The admin's private chat id is the reliable owner id here.
                chat_id = int(getattr(getattr(message, "chat", None), "id", 0) or 0)
                from_uid = int(getattr(getattr(message, "from_user", None), "id", 0) or 0)
                uid = chat_id if chat_id and _is_admin(chat_id) else from_uid
                if uid and _is_admin(uid):
                    markup = getattr(message, "reply_markup", None)
                    if not isinstance(markup, types.InlineKeyboardMarkup):
                        ctx = admin_pending_return.get(uid) or {}
                        back_cb = "admin_nav_back"
                        markup = types.InlineKeyboardMarkup(row_width=1)
                        markup.add(make_ui_button(
                            "🔙 Back", callback_data=back_cb,
                            button_key="admin:navigation:back",
                            default_color="red", force_style=True
                        ))
                        try:
                            bot.edit_message_reply_markup(
                                message.chat.id, message.message_id, reply_markup=markup
                            )
                        except Exception:
                            pass
            except Exception as exc:
                print(f"[ADMIN NEXT-STEP NAV ERROR] {exc}")
            return _ORIGINAL_REGISTER_NEXT_STEP_HANDLER(message, callback, *args, **kwargs)
        bot.register_next_step_handler = _rg_admin_register_next_step_handler
        bot._rg_admin_nav_wrapped = True
except Exception as exc:
    print(f"[ADMIN NEXT-STEP WRAP ERROR] {exc}")

# ==================== AUTOMATIC 1-HOUR BACKUP ====================
# Additive safety layer: periodically creates a consistent SQLite backup,
# stores it inside this bot instance's own backup directory, and sends the
# newest backup to the bot's configured root admins in Telegram. Nothing in
# the existing database/workflow is removed or replaced.
BOT_AUTO_BACKUP_INTERVAL = max(300, int(os.getenv('BOT_AUTO_BACKUP_INTERVAL', '3600') or 3600))
BOT_AUTO_BACKUP_KEEP = max(3, int(os.getenv('BOT_AUTO_BACKUP_KEEP', '48') or 48))
BOT_AUTO_BACKUP_SEND = os.getenv('BOT_AUTO_BACKUP_SEND', '1').strip().lower() not in {'0', 'false', 'no', 'off'}
BOT_AUTO_BACKUP_MAX_TELEGRAM_BYTES = 49 * 1024 * 1024
BOT_AUTO_BACKUP_DIR = (BOT_DB_PATH.parent / 'backups').resolve()
BOT_AUTO_BACKUP_LOCK = threading.RLock()
BOT_AUTO_BACKUP_LAST_PATH = None


def _auto_backup_archive_name():
    instance = str(BOT_INSTANCE_ID or 'master').replace('/', '_').replace('\\', '_')
    stamp = _now_ist().strftime('%Y%m%d_%H%M%S')
    return f'auto_backup_{instance}_{stamp}.zip'


def _sqlite_online_backup(source_db, destination_db):
    """Create a consistent SQLite snapshot without copying a live DB file directly."""
    source_db = Path(source_db).resolve()
    destination_db = Path(destination_db).resolve()
    destination_db.parent.mkdir(parents=True, exist_ok=True)
    if not source_db.exists():
        raise FileNotFoundError(f'Live database not found: {source_db}')
    if destination_db.exists():
        destination_db.unlink()
    src = sqlite3.connect(str(source_db), timeout=30)
    dst = sqlite3.connect(str(destination_db), timeout=30)
    try:
        src.backup(dst, pages=256, progress=None, sleep=0.05)
        dst.execute('PRAGMA wal_checkpoint(PASSIVE)')
        dst.commit()
    finally:
        try:
            dst.close()
        finally:
            src.close()
    return destination_db


def _create_auto_backup():
    """Create a timestamped ZIP containing the live bot database snapshot."""
    global BOT_AUTO_BACKUP_LAST_PATH
    with BOT_AUTO_BACKUP_LOCK:
        BOT_AUTO_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        archive_path = BOT_AUTO_BACKUP_DIR / _auto_backup_archive_name()
        with tempfile.TemporaryDirectory(prefix='rg_auto_db_', dir=str(BOT_AUTO_BACKUP_DIR)) as tmp:
            snapshot = _sqlite_online_backup(BOT_DB_PATH, Path(tmp) / 'shop_data.db')
            manifest = {
                'type': f'{BOT_BRAND_NAME} automatic database backup',
                'created_at_ist': _now_ist_text(),
                'bot_instance_id': BOT_INSTANCE_ID or 'master',
                'database_file': 'shop_data.db',
                'source_database': str(BOT_DB_PATH),
                'interval_seconds': BOT_AUTO_BACKUP_INTERVAL,
            }
            manifest_path = Path(tmp) / 'backup_manifest.json'
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                zf.write(snapshot, 'shop_data.db')
                zf.write(manifest_path, 'backup_manifest.json')
        BOT_AUTO_BACKUP_LAST_PATH = archive_path
        _prune_auto_backups()
        return archive_path


def _prune_auto_backups():
    try:
        files = sorted(
            [p for p in BOT_AUTO_BACKUP_DIR.glob('auto_backup_*.zip') if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in files[BOT_AUTO_BACKUP_KEEP:]:
            try:
                old.unlink()
            except Exception as exc:
                print(f'[AUTO BACKUP] Could not remove old backup {old}: {exc}')
    except Exception as exc:
        print(f'[AUTO BACKUP] Retention cleanup warning: {exc}')


def _send_auto_backup_to_admins(archive_path):
    if not BOT_AUTO_BACKUP_SEND:
        return
    try:
        size = Path(archive_path).stat().st_size
    except Exception:
        return
    if size > BOT_AUTO_BACKUP_MAX_TELEGRAM_BYTES:
        print(f'[AUTO BACKUP] Saved locally but not sent: archive is {size} bytes (> Telegram safety limit).')
        return
    caption = (
        '💾 <b>Automatic 1-Hour Backup</b>\n'
        f'🕒 {_now_ist_text()} IST\n'
        f'📦 {Path(archive_path).name}\n'
        '✅ Database snapshot saved successfully.'
    )
    sent = 0
    for admin_id in list(_HARDCODED_ROOT_ADMIN_IDS):
        try:
            with open(archive_path, 'rb') as backup_file:
                bot.send_document(int(admin_id), backup_file, caption=caption, parse_mode='HTML')
            sent += 1
        except Exception as exc:
            print(f'[AUTO BACKUP] Telegram send failed for admin {admin_id}: {exc}')
    print(f'[AUTO BACKUP] Sent {sent}/{len(_HARDCODED_ROOT_ADMIN_IDS)} admin backup(s).')


def _automatic_backup_worker():
    """Independent daemon: a polling/network failure must not disable backups."""
    # Give database initialization and Telegram startup a little time first.
    time.sleep(10)
    while True:
        started = time.monotonic()
        try:
            archive = _create_auto_backup()
            print(f'[AUTO BACKUP] Created: {archive}')
            _send_auto_backup_to_admins(archive)
        except Exception as exc:
            print(f'[AUTO BACKUP] Backup cycle failed: {exc}')
        elapsed = time.monotonic() - started
        time.sleep(max(1, BOT_AUTO_BACKUP_INTERVAL - elapsed))


# Start before polling so a Telegram polling crash/reconnect cannot stop the
# backup scheduler. The thread is daemonized and does not alter bot shutdown.
try:
    threading.Thread(
        target=_automatic_backup_worker,
        daemon=True,
        name='automatic-1-hour-backup',
    ).start()
    print(f'[AUTO BACKUP] Enabled: every {BOT_AUTO_BACKUP_INTERVAL}s; keep={BOT_AUTO_BACKUP_KEEP}; send={BOT_AUTO_BACKUP_SEND}')
except Exception as exc:
    print(f'[AUTO BACKUP] Could not start automatic backup worker: {exc}')

# ==================== MASTER BOT BACKUP / RESTORE ====================
# Backups are handled only by the Master Bot. Customer bots never expose this
# control because BOT_CREATOR_ENABLED is disabled inside every generated child.
BOT_BACKUP_MAX_BYTES = 50 * 1024 * 1024
BOT_BACKUP_ALLOWED_EXTENSIONS = ('.zip', '.tar', '.tar.gz', '.tgz')


def _safe_backup_extract(archive_path, extract_dir):
    """Extract a supported archive without allowing path traversal."""
    archive_path = Path(archive_path).resolve()
    extract_dir = Path(extract_dir).resolve()
    extract_dir.mkdir(parents=True, exist_ok=True)
    root = str(extract_dir) + os.sep

    def safe_target(member_name):
        target = (extract_dir / member_name).resolve()
        if str(target) != str(extract_dir) and not str(target).startswith(root):
            raise ValueError('Unsafe backup archive path detected.')
        return target

    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path, 'r') as zf:
            for info in zf.infolist():
                safe_target(info.filename)
            zf.extractall(extract_dir)
        return

    if tarfile.is_tarfile(archive_path):
        with tarfile.open(archive_path, 'r:*') as tf:
            members = tf.getmembers()
            for member in members:
                safe_target(member.name)
                if member.issym() or member.islnk():
                    # Do not restore symlinks/hardlinks from an uploaded archive.
                    raise ValueError('Backup archives containing links are not supported.')
            tf.extractall(extract_dir)
        return

    raise ValueError('Unsupported backup format. Send .zip, .tar, .tar.gz or .tgz.')


def _find_backup_database(extract_dir):
    """Find the most relevant SQLite database inside an extracted backup."""
    extract_dir = Path(extract_dir)
    candidates = [p for p in extract_dir.rglob('*') if p.is_file() and p.suffix.lower() in {'.db', '.sqlite', '.sqlite3'}]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (0 if p.name.lower() == 'shop_data.db' else 1, len(p.parts), -p.stat().st_size))
    return candidates[0]


def _sqlite_table_columns(conn, table_name):
    rows = conn.execute(f'PRAGMA table_info({json.dumps(table_name)})').fetchall()
    return [str(r[1]) for r in rows]


def _sqlite_table_pk_columns(conn, table_name):
    rows = conn.execute(f'PRAGMA table_info({json.dumps(table_name)})').fetchall()
    # PRAGMA table_info pk sequence is stored in column 5.
    return [str(r[1]) for r in sorted(rows, key=lambda r: (int(r[5] or 0), str(r[1]))) if int(r[5] or 0) > 0]


def _sqlite_ensure_table_schema(dst_conn, src_conn, table_name):
    """Create a missing table and add missing source columns to the destination."""
    exists = dst_conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ).fetchone()
    src_sql_row = src_conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ).fetchone()
    if not exists and src_sql_row and src_sql_row[0]:
        dst_conn.execute(src_sql_row[0])

    src_cols = _sqlite_table_columns(src_conn, table_name)
    dst_cols = set(_sqlite_table_columns(dst_conn, table_name))
    for col in src_cols:
        if col in dst_cols:
            continue
        info = src_conn.execute(
            f'PRAGMA table_info({json.dumps(table_name)})'
        ).fetchall()
        col_info = next((r for r in info if str(r[1]) == col), None)
        if not col_info:
            continue
        col_type = str(col_info[2] or 'TEXT')
        # SQLite cannot add a new PRIMARY KEY/UNIQUE column through ALTER TABLE.
        # Those constraints already belong to the destination schema in normal
        # upgrades; only the column definition itself is added here.
        dst_conn.execute(f'ALTER TABLE {json.dumps(table_name)} ADD COLUMN {json.dumps(col)} {col_type}')
        dst_cols.add(col)


def _merge_sqlite_database(src_db, dst_db):
    """Merge every table/row from src_db into dst_db without deleting old data.

    Existing destination rows are kept for non-conflicting records. When the same
    primary/unique record exists in both databases, the backup row is used so that
    settings/editor values from the uploaded backup are restored exactly.
    """
    src_db = Path(src_db).resolve()
    dst_db = Path(dst_db).resolve()
    if not src_db.exists():
        raise FileNotFoundError('Backup database was not found inside the archive.')
    if src_db == dst_db:
        raise ValueError('Backup database points to the live database.')

    src = sqlite3.connect(f'file:{src_db}?mode=ro', uri=True, timeout=30)
    dst = sqlite3.connect(dst_db, timeout=30)
    dst.execute('PRAGMA foreign_keys=OFF')
    stats = {'tables': 0, 'rows': 0, 'updated': 0, 'inserted': 0}
    try:
        # Internal orchestration tables belong to the Master Bot process and
        # must never be copied into a customer bot. All customer-facing A-Z
        # data (settings, products, users, orders, payments, API mappings,
        # support configuration, premium emoji/text, etc.) remains restorable.
        excluded_tables = {'bot_instances'}
        tables = [r[0] for r in src.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall() if str(r[0]) not in excluded_tables]
        for table in tables:
            _sqlite_ensure_table_schema(dst, src, table)
            src_cols = _sqlite_table_columns(src, table)
            dst_cols = set(_sqlite_table_columns(dst, table))
            cols = [c for c in src_cols if c in dst_cols]
            if not cols:
                continue
            quoted_cols = ','.join(json.dumps(c) for c in cols)
            rows = src.execute(f'SELECT {quoted_cols} FROM {json.dumps(table)}').fetchall()
            if not rows:
                stats['tables'] += 1
                continue

            pk_cols = _sqlite_table_pk_columns(dst, table)
            # If a table has a primary key, use an explicit UPSERT so the backup
            # wins for matching records while all non-matching old rows survive.
            if pk_cols and all(c in cols for c in pk_cols):
                assignments = ','.join(
                    f'{json.dumps(c)}=excluded.{json.dumps(c)}'
                    for c in cols if c not in pk_cols
                )
                placeholders = ','.join('?' for _ in cols)
                if assignments:
                    sql = (
                        f'INSERT INTO {json.dumps(table)} ({quoted_cols}) VALUES ({placeholders}) '
                        f'ON CONFLICT ({",".join(json.dumps(c) for c in pk_cols)}) DO UPDATE SET {assignments}'
                    )
                else:
                    sql = f'INSERT OR IGNORE INTO {json.dumps(table)} ({quoted_cols}) VALUES ({placeholders})'
                for row in rows:
                    before = dst.total_changes
                    dst.execute(sql, row)
                    stats['rows'] += 1
                    if dst.total_changes > before:
                        stats['updated' if assignments else 'inserted'] += 1
            else:
                # Tables without a PK are append-only during restore. Duplicate
                # rows are harmless and existing data is never deleted.
                placeholders = ','.join('?' for _ in cols)
                sql = f'INSERT INTO {json.dumps(table)} ({quoted_cols}) VALUES ({placeholders})'
                for row in rows:
                    try:
                        dst.execute(sql, row)
                        stats['inserted'] += 1
                    except sqlite3.IntegrityError:
                        # A unique constraint may exist even when there is no PK.
                        # Preserve the old row rather than failing the entire restore.
                        pass
                    stats['rows'] += 1
            stats['tables'] += 1

        dst.commit()
    except Exception:
        dst.rollback()
        raise
    finally:
        try:
            dst.execute('PRAGMA foreign_keys=ON')
        except Exception:
            pass
        dst.close()
        src.close()
    return stats


def _restore_safe_backup_files(extract_dir, child_dir):
    """Restore non-code data/config files without replacing bot code or secrets."""
    extract_dir = Path(extract_dir)
    child_dir = Path(child_dir)
    allowed_names = {
        'bot_settings.json', 'settings.json', 'config.json', 'custom_settings.json'
    }
    restored = []
    for src in extract_dir.rglob('*'):
        if not src.is_file() or src.name.lower() not in allowed_names:
            continue
        rel = src.relative_to(extract_dir)
        # Keep only the filename in the child root; do not allow archive paths to
        # overwrite executable code, environment or process-control files.
        dst = child_dir / src.name
        shutil.copy2(src, dst)
        restored.append(dst.name)
    return restored


def _bot_creator_stop_instance(instance_id):
    proc = _bot_child_processes.pop(str(instance_id), None)
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=6)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _bot_creator_restart_instance(instance_id):
    """Restart one generated child after its database has been restored."""
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=20)
    try:
        row = conn.execute(
            'SELECT expires_at, instance_dir, status FROM bot_instances WHERE instance_id=?',
            (str(instance_id),)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise ValueError('Created bot instance was not found.')
    expires_at, instance_dir, status = row
    child_dir = Path(instance_dir)
    env_file = child_dir / '.bot_env.json'
    if not child_dir.exists() or not env_file.exists():
        raise ValueError('Created bot files are missing for this instance.')

    _bot_creator_stop_instance(str(instance_id))
    saved_env = json.loads(env_file.read_text(encoding='utf-8'))
    # Rebuild from the isolated child environment instead of copying the
    # Master's process environment. This prevents one child from accidentally
    # inheriting another bot's gateway/API credentials after a restart.
    env = _bot_creator_child_environment(
        token=saved_env.get('BOT_TOKEN', ''),
        admin_id=saved_env.get('BOT_ADMIN_IDS', '0'),
        bot_name=saved_env.get('BOT_BRAND_NAME', 'RG CHEAT SHOP'),
        expiry=expires_at,
        instance_id=instance_id,
        child_dir=child_dir,
    )
    env.update({
        'BOT_INSTANCE_ID': str(instance_id),
        'BOT_EXPIRES_AT': str(expires_at),
        'BOT_CREATOR_ENABLED': '0',
        'BOT_DB_PATH': str((child_dir / 'shop_data.db').resolve()),
    })
    # Keep Telegram's per-chat command menu synchronized after admin changes
    # or any other child restart. Every listed admin gets /start + /admin;
    # everyone else gets only /start.
    try:
        raw_admins = str(env.get('BOT_ADMIN_IDS') or '')
        admin_ids = [int(x.strip()) for x in raw_admins.split(',') if x.strip().isdigit()]
        for child_admin_id in admin_ids:
            _bot_creator_configure_menu(str(env.get('BOT_TOKEN') or ''), child_admin_id)
    except Exception:
        pass
    _bot_creator_spawn(str(instance_id), child_dir, env)
    return True


# ==================== MASTER BOT LIST / INSTANCE MANAGEMENT ====================
def _master_bot_list_markup():
    m = types.InlineKeyboardMarkup(row_width=1)
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=20)
    try:
        rows = conn.execute(
            'SELECT instance_id, bot_name, admin_id, expires_at, status, created_by_user_id FROM bot_instances ORDER BY id DESC'
        ).fetchall()
    finally:
        conn.close()
    now = time.time()
    for instance_id, bot_name, admin_id, expires_at, status, created_by_user_id in rows:
        exp = float(expires_at or 0)
        if exp <= now:
            state = '🔴'
            state_text = 'EXPIRED'
        elif str(status) == 'running':
            state = '🟢'
            state_text = 'RUNNING'
        elif str(status) == 'maintenance':
            state = '🟠'
            state_text = 'MAINTENANCE'
        else:
            state = '⏸️'
            state_text = str(status).upper()
        m.add(types.InlineKeyboardButton(
            f'{state} {str(bot_name)[:30]} • U:{int(created_by_user_id or 0)} • {state_text}',
            callback_data=f'botlist_select_{instance_id}'
        ))
    m.add(make_ui_button('🔄 Refresh Bot List', callback_data='admin_bot_list', button_key='admin:bot_list:refresh', default_color='blue', force_style=True))
    m.add(make_ui_button('🔙 Main Admin Panel', callback_data='admin_back_main', button_key='admin:navigation:back', default_color='red', force_style=True))
    return _style_admin_markup(m)


def _show_master_bot_list(call):
    if not _is_bot_creator_root_admin(call.from_user.id):
        return
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=20)
    try:
        count = int(conn.execute('SELECT COUNT(*) FROM bot_instances').fetchone()[0] or 0)
    finally:
        conn.close()
    text = (
        '📋 <b>BOT LIST</b>\n\n'
        f'🤖 <b>Total Created Bots:</b> {count}\n\n'
        'Select a bot to manage its admin access, validity, pause/resume, maintenance, or deletion.'
    )
    _admin_ui_send(call, text, parse_mode='HTML', reply_markup=_master_bot_list_markup())


def _bot_instance_row(instance_id):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=20)
    try:
        return conn.execute(
            'SELECT instance_id, bot_name, admin_id, duration_key, expires_at, instance_dir, status FROM bot_instances WHERE instance_id=?',
            (str(instance_id),)
        ).fetchone()
    finally:
        conn.close()


def _extract_child_admin_button_catalog(instance_dir):
    """Build a complete, source-derived A-Z Admin Panel button catalog.

    The old regex-only detector missed multiline calls, f-string labels and
    many raw InlineKeyboardButton declarations. The Master Bot does not import
    the child process just to discover its UI, so use Python's AST instead.
    This keeps the catalog tied to the actual child ``main.py`` and avoids a
    short hard-coded list.
    """
    path = Path(instance_dir) / 'main.py'
    if not path.exists():
        return []
    try:
        src = path.read_text(encoding='utf-8', errors='replace')
        tree = ast.parse(src)
    except Exception as exc:
        print(f'[ADMIN BUTTON CATALOG ERROR] {exc}')
        return []

    def const_value(node):
        if isinstance(node, ast.Constant):
            return node.value
        return None

    def joined_value(node):
        if isinstance(node, ast.JoinedStr):
            parts = []
            for value in node.values:
                if isinstance(value, ast.Constant):
                    parts.append(str(value.value))
                else:
                    parts.append('{…}')
            return ''.join(parts)
        return None

    found = {}

    def add(key, label, callback_data=''):
        key = str(key or '').strip()
        if not key.startswith('admin:'):
            return
        label = str(label or '').strip()
        callback_data = str(callback_data or '').strip()
        if not label:
            label = callback_data or key
        # Keep the first useful label, but allow a later declaration to fill
        # in a missing callback/label.
        old = found.get(key)
        if old is None:
            found[key] = {'key': key, 'label': label, 'callback_data': callback_data}
        else:
            if not old.get('label') or old['label'] == old['key']:
                old['label'] = label
            if not old.get('callback_data') and callback_data:
                old['callback_data'] = callback_data

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn_name = node.func.id if isinstance(node.func, ast.Name) else (node.func.attr if isinstance(node.func, ast.Attribute) else '')

        if fn_name == 'make_ui_button':
            label = const_value(node.args[0]) if node.args else None
            if label is None and node.args:
                label = joined_value(node.args[0])
            kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            bk_node = kwargs.get('button_key')
            cb_node = kwargs.get('callback_data')
            key = const_value(bk_node) if bk_node is not None else joined_value(bk_node) if bk_node is not None else None
            cb = const_value(cb_node) if cb_node is not None else joined_value(cb_node) if cb_node is not None else None
            if isinstance(key, str) and key.startswith('admin:'):
                add(key, label, cb)

        elif fn_name == 'InlineKeyboardButton':
            label = const_value(node.args[0]) if node.args else None
            if label is None and node.args:
                label = joined_value(node.args[0])
            kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            cb_node = kwargs.get('callback_data')
            cb = const_value(cb_node) if cb_node is not None else joined_value(cb_node) if cb_node is not None else None
            if isinstance(cb, str) and (cb.startswith('admin') or cb.startswith('gw_') or cb.startswith('ninex_')):
                add(f'admin:callback:{cb}', label, cb)

    return sorted(found.values(), key=lambda x: (str(x.get('label') or '').lower(), str(x.get('key') or '')))

def _child_button_disabled(instance_dir, key):
    db = Path(instance_dir) / 'shop_data.db'
    if not db.exists():
        return False
    try:
        conn = sqlite3.connect(db, timeout=20)
        try:
            raw = conn.execute('SELECT value FROM settings WHERE key=?', (ADMIN_BUTTON_VISIBILITY_KEY,)).fetchone()
        finally:
            conn.close()
        data = json.loads(raw[0] or '[]') if raw else []
        return str(key) in {str(x) for x in data}
    except Exception:
        return False

def _set_child_button_disabled(instance_id, key, disabled):
    row = _bot_instance_row(instance_id)
    if not row:
        raise ValueError('Bot instance not found.')
    db = Path(row[5]) / 'shop_data.db'
    conn = sqlite3.connect(db, timeout=20)
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
        current = conn.execute('SELECT value FROM settings WHERE key=?', (ADMIN_BUTTON_VISIBILITY_KEY,)).fetchone()
        data = json.loads(current[0] or '[]') if current else []
        disabled_set = {str(x) for x in data}
        if disabled:
            disabled_set.add(str(key))
        else:
            disabled_set.discard(str(key))
        conn.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (ADMIN_BUTTON_VISIBILITY_KEY, json.dumps(sorted(disabled_set), ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()
    # Do NOT restart the child process here. Admin button visibility is read
    # from the child's database when the panel is rendered. Restarting the
    # child on every toggle was the source of the long delay/freeze: it could
    # terminate Telegram polling while the Master callback was still running.

def _show_bot_admin_button_control(call, instance_id):
    if not _is_bot_creator_root_admin(call.from_user.id):
        return
    row = _bot_instance_row(instance_id)
    if not row:
        _admin_ui_send(call, '❌ <b>Bot instance not found.</b>', parse_mode='HTML')
        return
    catalog = _extract_child_admin_button_catalog(row[5])
    if not catalog:
        _admin_ui_send(call, '⚠️ <b>No Admin Panel buttons could be detected.</b>', parse_mode='HTML', reply_markup=_bot_instance_manage_markup(row[0], row[6], row[4]))
        return
    admin_temp_data.setdefault(call.from_user.id, {})['bot_button_catalog'] = { _ui_hash(x['key']): x for x in catalog }
    m = types.InlineKeyboardMarkup(row_width=1)
    for item in catalog:
        disabled = _child_button_disabled(row[5], item['key'])
        label = f"{'🔴' if disabled else '🟢'} {item['label'][:55]}"
        m.add(make_ui_button(label, callback_data=f"botbtn_toggle_{instance_id}_{_ui_hash(item['key'])}", button_key='admin:botlist:button_control:item', default_color='red' if disabled else 'green', force_style=True))
    m.add(make_ui_button('🔙 Back to Bot Management', callback_data=f'botlist_select_{instance_id}', button_key='admin:botlist:back', default_color='red', force_style=True))
    _admin_ui_send(call, '🎛 <b>USER BOT ADMIN PANEL — BUTTON CONTROL</b>\n\nAll detected Admin Panel buttons are listed below. Tap any button to switch ON/OFF for this bot.', parse_mode='HTML', reply_markup=_style_admin_markup(m))

def _bot_instance_manage_markup(instance_id, status, expires_at):
    m = types.InlineKeyboardMarkup(row_width=2)
    iid = str(instance_id)
    running = str(status) == 'running'
    expired = float(expires_at or 0) <= time.time()
    if running and not expired:
        m.row(
            make_ui_button('⏸ Pause Bot', callback_data=f'botlist_pause_{iid}', button_key='admin:botlist:pause', default_color='red', force_style=True),
            make_ui_button('🔧 Maintenance', callback_data=f'botlist_maint_{iid}', button_key='admin:botlist:maintenance', default_color='red', force_style=True),
        )
    else:
        m.row(
            make_ui_button('▶️ Start/Resume', callback_data=f'botlist_resume_{iid}', button_key='admin:botlist:resume', default_color='green', force_style=True),
            make_ui_button('🔧 Maintenance', callback_data=f'botlist_maint_{iid}', button_key='admin:botlist:maintenance', default_color='red', force_style=True),
        )
    m.add(make_ui_button('👤 Add Me as Admin', callback_data=f'botlist_addme_{iid}', button_key='admin:botlist:addme', default_color='blue', force_style=True))
    m.add(make_ui_button('⏳ Extend Validity', callback_data=f'botlist_extend_{iid}', button_key='admin:botlist:extend', default_color='blue', force_style=True))
    m.add(make_ui_button('📦 Manage Backup', callback_data=f'botbackup_select_{iid}', button_key='admin:botlist:backup', default_color='blue', force_style=True))
    m.add(make_ui_button('🎛 Manage Admin Panel Buttons', callback_data=f'botlist_buttons_{iid}', button_key='admin:botlist:buttons', default_color='blue', force_style=True))
    # Resolve the instance row here.  The previous code referenced `row[5]`
    # even though `row` is not defined inside this function.  That NameError
    # made the Bot List -> running bot button appear to freeze.
    current_row = _bot_instance_row(iid)
    child_resapi_disabled = (
        _child_button_disabled(current_row[5], RESSELLER_API_ADMIN_BUTTON_KEY)
        if current_row else False
    )
    resapi_label = '🔴 Reseller API: OFF' if child_resapi_disabled else '🟢 Reseller API: ON'
    m.add(make_ui_button(resapi_label, callback_data=f'botlist_resapi_toggle_{iid}', button_key='admin:botlist:reseller_api', default_color='red' if child_resapi_disabled else 'green', force_style=True))
    m.add(make_ui_button('🗑 Delete Bot', callback_data=f'botlist_delete_{iid}', button_key='admin:botlist:delete', default_color='red', force_style=True))
    m.add(make_ui_button('🔙 Back to Bot List', callback_data='admin_bot_list', button_key='admin:botlist:back', default_color='red', force_style=True))
    return _style_admin_markup(m)


def _format_remaining_time(expires_at):
    try:
        remaining = max(0, int(float(expires_at or 0) - time.time()))
    except Exception:
        remaining = 0
    days, rem = divmod(remaining, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    if days:
        return f'{days}d {hours:02d}h {minutes:02d}m {seconds:02d}s'
    if hours:
        return f'{hours}h {minutes:02d}m {seconds:02d}s'
    return f'{minutes:02d}m {seconds:02d}s'

def _start_expiry_live_timer(chat_id, message_id, instance_id):
    """Run the live countdown without editing the Bot Management message.

    The management message contains the actionable inline keyboard. Editing that
    same message every second makes Telegram clients repeatedly redraw the page
    and can race with callback presses. The countdown is therefore rendered in a
    separate, text-only message while the management keyboard stays stable.
    """
    session_key = f'expiry_timer:{chat_id}:{instance_id}'
    sessions = globals().setdefault('_LIVE_EXPIRY_TIMERS', {})
    old = sessions.get(session_key)
    if old:
        try:
            old['stop'].set()
        except Exception:
            pass
        try:
            old_msg = old.get('timer_message_id')
            if old_msg:
                bot.delete_message(chat_id, old_msg)
        except Exception:
            pass

    stop_event = threading.Event()
    timer_message_id = None
    try:
        row = _bot_instance_row(instance_id)
        if not row:
            return
        exp = float(row[4] or 0)
        timer_text = (
            f'⏳ <b>LIVE EXPIRY TIMER</b>\n\n'
            f'🤖 <b>{html.escape(str(row[1]))}</b>\n'
            f'⏱️ <b>Remaining:</b> <code>{_format_remaining_time(exp)}</code>'
        )
        sent = bot.send_message(chat_id, timer_text, parse_mode='HTML')
        timer_message_id = sent.message_id
    except Exception:
        # If Telegram refuses the auxiliary message, keep the management screen
        # fully usable rather than falling back to editing its keyboard message.
        return

    sessions[session_key] = {'stop': stop_event, 'timer_message_id': timer_message_id}

    def worker():
        try:
            while not stop_event.is_set():
                row = _bot_instance_row(instance_id)
                if not row:
                    break
                exp = float(row[4] or 0)
                now = time.time()
                if exp <= now:
                    try:
                        bot.edit_message_text(
                            f'⏳ <b>LIVE EXPIRY TIMER</b>\n\n'
                            f'🤖 <b>{html.escape(str(row[1]))}</b>\n'
                            f'🔴 <b>EXPIRED</b>',
                            chat_id=chat_id, message_id=timer_message_id, parse_mode='HTML'
                        )
                    except Exception:
                        pass
                    break
                remaining = _format_remaining_time(exp)
                try:
                    bot.edit_message_text(
                        f'⏳ <b>LIVE EXPIRY TIMER</b>\n\n'
                        f'🤖 <b>{html.escape(str(row[1]))}</b>\n'
                        f'⏱️ <b>Remaining:</b> <code>{remaining}</code>',
                        chat_id=chat_id, message_id=timer_message_id, parse_mode='HTML'
                    )
                except Exception:
                    # Do not touch the management message if this timer message
                    # cannot be edited. The action buttons remain usable.
                    pass
                stop_event.wait(1.0)
        finally:
            current = sessions.get(session_key)
            if current and current.get('stop') is stop_event:
                sessions.pop(session_key, None)

    threading.Thread(target=worker, daemon=True, name='expiry-live-timer').start()

def _show_bot_instance_manage(call, instance_id):
    if not _is_bot_creator_root_admin(call.from_user.id):
        return
    row = _bot_instance_row(instance_id)
    if not row:
        _admin_ui_send(call, '❌ <b>Bot instance not found.</b>', parse_mode='HTML', reply_markup=_master_bot_list_markup())
        return
    iid, bot_name, admin_id, duration_key, expires_at, instance_dir, status = row
    try:
        conn=sqlite3.connect(str(BOT_DB_PATH),timeout=20)
        try:
            created_by_user_id=conn.execute('SELECT created_by_user_id FROM bot_instances WHERE instance_id=?',(str(instance_id),)).fetchone()[0] or 0
        finally:
            conn.close()
    except Exception:
        created_by_user_id=0
    exp = float(expires_at or 0)
    if exp <= time.time():
        state = '🔴 EXPIRED'
    elif str(status) == 'running':
        state = '🟢 RUNNING'
    elif str(status) == 'maintenance':
        state = '🟠 MAINTENANCE'
    else:
        state = f'⏸️ {str(status).upper()}'
    expiry_text = datetime.datetime.fromtimestamp(exp).strftime('%Y-%m-%d %H:%M:%S') if exp else 'N/A'
    text = (
        '🤖 <b>BOT MANAGEMENT</b>\n\n'
        f'🏷 <b>Name:</b> {html.escape(str(bot_name))}\n'
        f'🆔 <b>Instance:</b> <code>{html.escape(str(iid))}</code>\n'
        f'👤 <b>Owner/Admin ID:</b> <code>{int(admin_id)}</code>\n'
        f'🧑 <b>Created By User ID:</b> <code>{int(created_by_user_id or 0)}</code>\n'
        f'📆 <b>Plan:</b> {html.escape(str(duration_key))}\n'
        f'⏳ <b>Expires:</b> <code>{expiry_text}</code>\n'
        f'⏱️ <b>Remaining:</b> <code>{_format_remaining_time(exp)}</code>\n'
        f'📡 <b>Status:</b> {state}\n\n'
        'Choose an action below:'
    )
    _admin_ui_send(call, text, parse_mode='HTML', reply_markup=_bot_instance_manage_markup(iid, status, exp))
    try:
        _start_expiry_live_timer(call.message.chat.id, call.message.message_id, iid)
    except Exception:
        pass


def _update_bot_env_admin(instance_dir, new_admin_ids):
    child_dir = Path(instance_dir)
    env_file = child_dir / '.bot_env.json'
    if not env_file.exists():
        raise ValueError('Bot environment file is missing.')
    env = json.loads(env_file.read_text(encoding='utf-8'))
    env['BOT_ADMIN_IDS'] = ','.join(str(int(x)) for x in sorted(set(new_admin_ids)))
    env_file.write_text(json.dumps(env, ensure_ascii=False, indent=2), encoding='utf-8')
    return env


def _bot_add_admin_and_restart(instance_id, admin_id):
    row = _bot_instance_row(instance_id)
    if not row:
        raise ValueError('Bot instance not found.')
    _, _, _, _, expires_at, instance_dir, status = row
    child_dir = Path(instance_dir)
    env_file = child_dir / '.bot_env.json'
    env = json.loads(env_file.read_text(encoding='utf-8'))
    raw = str(env.get('BOT_ADMIN_IDS') or '')
    ids = [int(x.strip()) for x in raw.split(',') if x.strip().isdigit()]
    ids.append(int(admin_id))
    _update_bot_env_admin(child_dir, ids)
    db = child_dir / 'shop_data.db'
    if db.exists():
        conn = sqlite3.connect(db, timeout=20)
        try:
            conn.execute('CREATE TABLE IF NOT EXISTS bot_admins (user_id INTEGER PRIMARY KEY, added_at TEXT)')
            conn.execute('INSERT OR IGNORE INTO bot_admins(user_id,added_at) VALUES(?,?)', (int(admin_id), datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()
        finally:
            conn.close()
    if float(expires_at or 0) > time.time() and str(status) in ('running','paused','maintenance','expired'):
        _bot_creator_restart_instance(str(instance_id))
    return True


def _bot_set_status(instance_id, status):
    row = _bot_instance_row(instance_id)
    if not row:
        raise ValueError('Bot instance not found.')
    _, _, _, _, expires_at, _, _ = row
    status = str(status)
    if status == 'running':
        if float(expires_at or 0) <= time.time():
            raise ValueError('Bot validity is expired. Extend validity first.')
        _bot_creator_restart_instance(str(instance_id))
    else:
        _bot_creator_stop_instance(str(instance_id))
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=20)
    try:
        conn.execute('UPDATE bot_instances SET status=?, updated_at=? WHERE instance_id=?', (status, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), str(instance_id)))
        conn.commit()
    finally:
        conn.close()


def _bot_extend_validity(instance_id, raw_duration):
    """Set a new validity or explicitly extend the current expiry.

    Plain durations (1m, 5m, 7d, ...) start a fresh validity window from NOW.
    A leading '+' explicitly means ADD that duration to the existing expiry
    (for example +1d turns 7 days remaining into 8 days). This prevents a
    requested 1-minute validity from accidentally becoming the old expiry plus
    one minute.
    """
    row = _bot_instance_row(instance_id)
    if not row:
        raise ValueError('Bot instance not found.')
    _, _, _, _, expires_at, _, status = row
    raw = str(raw_duration or '').strip().lower()
    m = re.fullmatch(r'(\+?)\s*(\d+)\s*(m|min|mins|minute|minutes|h|hr|hour|hours|d|day|days)', raw)
    if not m:
        raise ValueError('Use 1m, 5m, 1h, 7d to SET a new validity, or +1d/+5m to EXTEND the existing expiry.')
    add_mode = bool(m.group(1))
    amount = int(m.group(2)); unit = m.group(3)
    if amount <= 0:
        raise ValueError('Duration must be greater than zero.')
    if unit.startswith('m'):
        seconds = amount * 60
    elif unit.startswith('h'):
        seconds = amount * 3600
    else:
        seconds = amount * 86400

    now = time.time()
    if add_mode:
        base = max(float(expires_at or 0), now)
        new_expiry = base + seconds
        duration_key = f'+{amount}{unit}'
    else:
        # Plain duration means a NEW validity period starting immediately.
        new_expiry = now + seconds
        duration_key = f'{amount}{unit}'

    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=20)
    try:
        conn.execute(
            'UPDATE bot_instances SET expires_at=?, duration_key=?, status=?, updated_at=? WHERE instance_id=?',
            (new_expiry, duration_key, 'running', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), str(instance_id))
        )
        conn.commit()
    finally:
        conn.close()

    _bot_creator_restart_instance(str(instance_id))
    return new_expiry


def _bot_delete_instance(instance_id):
    row = _bot_instance_row(instance_id)
    if not row:
        raise ValueError('Bot instance not found.')
    instance_dir = row[5]
    _bot_creator_stop_instance(str(instance_id))
    shutil.rmtree(Path(instance_dir), ignore_errors=True)
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=20)
    try:
        conn.execute('DELETE FROM bot_instances WHERE instance_id=?', (str(instance_id),))
        conn.commit()
    finally:
        conn.close()


def _bot_backup_list_markup():
    """Backup-only Admin UI for automatic bot database archives."""
    m=types.InlineKeyboardMarkup(row_width=1); BOT_AUTO_BACKUP_DIR.mkdir(parents=True,exist_ok=True)
    files=sorted([p for p in BOT_AUTO_BACKUP_DIR.glob('auto_backup_*.zip') if p.is_file()],key=lambda p:p.stat().st_mtime,reverse=True)[:20]
    catalog={}
    for path in files:
        h=_ui_hash(path.name); catalog[h]=str(path); size=path.stat().st_size/(1024*1024); stamp=datetime.datetime.fromtimestamp(path.stat().st_mtime).strftime('%d %b %Y · %I:%M %p')
        m.add(types.InlineKeyboardButton(f'💾 {stamp} · {size:.1f} MB',callback_data=f'admin_backup_send_{h}'))
    m.add(make_ui_button('💾 Create Backup Now',callback_data='admin_backup_create_now',button_key='admin:backup:create',default_color='green',force_style=True))
    if files:
        m.add(make_ui_button('🔄 Refresh Backups',callback_data='admin_created_bots',button_key='admin:backup:refresh',default_color='blue',force_style=True))
    m.add(make_ui_button('🔙 Back',callback_data='admin_back_main',button_key='admin:navigation:back',default_color='red',force_style=True))
    return _style_admin_markup(m),catalog,files


def _show_created_bots_backup_list(call):
    m,catalog,files=_bot_backup_list_markup(); admin_temp_data.setdefault(int(call.from_user.id),{})['backup_archive_catalog']=catalog
    text=('💾 <b>BOTS & BACKUPS</b>\n━━━━━━━━━━━━━━━━━━━━\n\n'
          f'📦 <b>Available Backups:</b> {len(files)}\n\n'
          'Tap any backup to receive the backup file.\n'
          '<i>Automatic backups use the existing backup scheduler.</i>')
    _admin_ui_send(call,text,parse_mode='HTML',reply_markup=m)


def _show_bot_backup_target(call, instance_id):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=20)
    try:
        row = conn.execute(
            'SELECT bot_name, admin_id, duration_key, expires_at, status, instance_dir FROM bot_instances WHERE instance_id=?',
            (str(instance_id),)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        _admin_ui_send(call, '❌ <b>Bot instance not found.</b>', parse_mode='HTML', reply_markup=_bot_backup_list_markup())
        return
    bot_name, admin_id, duration_key, expires_at, status, _instance_dir = row
    expiry_text = datetime.datetime.fromtimestamp(float(expires_at)).strftime('%Y-%m-%d %H:%M:%S')
    admin_temp_data[call.from_user.id] = {'backup_target_instance': str(instance_id)}
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(types.InlineKeyboardButton('🔙 Back to Created Bots', callback_data='admin_created_bots'))
    _admin_ui_send(
        call,
        '📥 <b>UPLOAD COMPLETE BOT BACKUP</b>\n\n'
        f'🤖 <b>Bot:</b> {html.escape(str(bot_name))}\n'
        f'👤 <b>Admin ID:</b> <code>{int(admin_id)}</code>\n'
        f'📆 <b>Plan:</b> {html.escape(str(duration_key))}\n'
        f'⏳ <b>Expires:</b> <code>{expiry_text}</code>\n\n'
        'Send the complete backup as a <code>.zip</code>, <code>.tar</code>, <code>.tar.gz</code> or <code>.tgz</code> document.\n\n'
        '✅ Existing bot data will remain.\n'
        '✅ Backup data will be merged/restored.\n'
        '✅ Matching records use the backup values so Premium Emoji/Text and other settings are restored.\n'
        '🔒 The backup cannot replace the bot token, environment file or main.py.',
        parse_mode='HTML', reply_markup=m
    )


def _restore_uploaded_bot_backup(instance_id, archive_path):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=20)
    try:
        row = conn.execute('SELECT instance_dir FROM bot_instances WHERE instance_id=?', (str(instance_id),)).fetchone()
    finally:
        conn.close()
    if not row:
        raise ValueError('Created bot instance was not found.')
    child_dir = Path(row[0]).resolve()
    if not child_dir.exists():
        raise ValueError('Created bot directory is missing.')

    # Stop the child first so SQLite WAL/locks are fully released before the
    # incoming backup is merged. It is restarted automatically after restore.
    _bot_creator_stop_instance(str(instance_id))

    backup_dir = child_dir / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    saved_archive = backup_dir / f'uploaded_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}_{secrets.token_hex(4)}{Path(archive_path).suffix}'
    shutil.copy2(archive_path, saved_archive)

    with tempfile.TemporaryDirectory(prefix='restore_', dir=str(backup_dir)) as tmp:
        extract_dir = Path(tmp) / 'extracted'
        _safe_backup_extract(saved_archive, extract_dir)
        src_db = _find_backup_database(extract_dir)
        if src_db is None:
            raise ValueError('No SQLite database (.db/.sqlite/.sqlite3) was found inside the backup archive.')
        dst_db = child_dir / 'shop_data.db'
        stats = _merge_sqlite_database(src_db, dst_db)
        restored_files = _restore_safe_backup_files(extract_dir, child_dir)

    # Reload all settings/editor/database values immediately in the child process.
    restart_error = ''
    try:
        _bot_creator_restart_instance(str(instance_id))
    except Exception as exc:
        restart_error = str(exc)[:500]
    return stats, restored_files, saved_archive, restart_error


@bot.message_handler(content_types=['document'])
def handle_master_bot_backup_document(message):
    """Receive a complete backup only after the Master Admin selected a bot."""
    uid = message.from_user.id
    if not _is_bot_creator_root_admin(uid):
        return
    state = admin_temp_data.get(uid, {})
    instance_id = state.get('backup_target_instance')
    if not instance_id:
        return
    doc = getattr(message, 'document', None)
    if not doc:
        return
    filename = str(getattr(doc, 'file_name', '') or '')
    lower = filename.lower()
    if not any(lower.endswith(ext) for ext in BOT_BACKUP_ALLOWED_EXTENSIONS):
        bot.send_message(
            message.chat.id,
            '❌ <b>Unsupported backup format.</b>\n\nSend <code>.zip</code>, <code>.tar</code>, <code>.tar.gz</code> or <code>.tgz</code>.',
            parse_mode='HTML'
        )
        return
    if int(getattr(doc, 'file_size', 0) or 0) > BOT_BACKUP_MAX_BYTES:
        bot.send_message(message.chat.id, '❌ <b>Backup is too large.</b> Maximum supported size is 50 MB.', parse_mode='HTML')
        return

    admin_temp_data[uid] = {'backup_target_instance': str(instance_id), 'backup_processing': True}
    tmp_path = None
    try:
        file_info = bot.get_file(doc.file_id)
        raw = bot.download_file(file_info.file_path)
        tmp_dir = Path(tempfile.mkdtemp(prefix='master_backup_'))
        tmp_path = tmp_dir / filename
        tmp_path.write_bytes(raw)
        bot.send_message(message.chat.id, '⏳ <b>Backup received. Restoring A–Z data now...</b>', parse_mode='HTML')
        stats, restored_files, saved_archive, restart_error = _restore_uploaded_bot_backup(str(instance_id), tmp_path)
        admin_temp_data.pop(uid, None)
        status_line = (
            '✅ <b>BACKUP RESTORED SUCCESSFULLY</b>\n\n'
            f'📊 Tables processed: <b>{stats["tables"]}</b>\n'
            f'📦 Rows processed: <b>{stats["rows"]}</b>\n'
            f'➕ Rows added: <b>{stats["inserted"]}</b>\n'
            f'♻️ Existing matching rows restored from backup: <b>{stats["updated"]}</b>\n'
            f'🧩 Config files restored: <b>{len(restored_files)}</b>\n\n'
            '✅ Old non-conflicting bot data remains.\n'
            '✅ Backup data is now merged into the selected bot.\n'
            '✅ Premium Emoji/Text and database settings are restored.\n'
        )
        if restart_error:
            status_line += f'\n⚠️ <b>Automatic restart warning:</b> <code>{html.escape(restart_error)}</code>\nPlease restart that child bot once.'
        else:
            status_line += '\n🟢 <b>Bot process restarted with the restored data.</b>'
        bot.send_message(message.chat.id, status_line, parse_mode='HTML', reply_markup=_bot_backup_list_markup())
    except Exception as exc:
        admin_temp_data.pop(uid, None)
        bot.send_message(message.chat.id, f'❌ <b>Backup restore failed.</b>\n\n<code>{html.escape(str(exc)[:1500])}</code>', parse_mode='HTML', reply_markup=_bot_backup_list_markup())
    finally:
        if tmp_path:
            try:
                shutil.rmtree(tmp_path.parent, ignore_errors=True)
            except Exception:
                pass


# ==================== CUSTOMER BOT MAKE PRODUCT ====================
bot_make_sessions = {}

def _bot_make_enabled():
    return str(get_setting(BOT_MAKE_ENABLED_KEY) or '0').strip() == '1'

def _bot_make_plan_rows():
    try:
        conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
        try:
            return conn.execute(
                'SELECT id, days, price, resell_price FROM products WHERE name=? AND COALESCE(is_bot_make,0)=1 ORDER BY id ASC',
                (BOT_MAKE_PRODUCT_NAME,)
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return []

def _bot_make_admin_markup():
    m=types.InlineKeyboardMarkup(row_width=1)
    state='🟢 ON' if _bot_make_enabled() else '🔴 OFF'
    m.add(make_ui_button(f'Bot Make: {state}', callback_data='botmake_toggle', button_key='admin:botmake:toggle', default_color='green' if _bot_make_enabled() else 'red', force_style=True))
    m.add(make_ui_button('➕ Add Bot Plan', callback_data='botmake_add_plan', button_key='admin:botmake:add_plan', default_color='blue', force_style=True))
    rows=_bot_make_plan_rows()
    for pid,days,price,res in rows:
        m.add(make_ui_button(f'🗑 Delete {days} — ₹{float(price or 0):.2f}', callback_data=f'botmake_del_{pid}', button_key='admin:botmake:delete', default_color='red', force_style=True))
    m.add(make_ui_button('🤖 Create New Bot (Manual)', callback_data='admin_bot_creator', button_key='admin:bot_creator', default_color='blue', force_style=True))
    m.add(make_ui_button('📋 Bot List', callback_data='admin_bot_list', button_key='admin:bot_list', default_color='blue', force_style=True))
    m.add(make_ui_button('🔙 Main Admin Panel', callback_data='admin_back_main', button_key='admin:navigation:back', default_color='red', force_style=True))
    return _style_admin_markup(m)

def _show_botmake_admin(call):
    rows=_bot_make_plan_rows()
    lines=['🤖 <b>CREATE BOT AND HACK LIST</b>','',f'👁️ <b>User Panel:</b> {"ON" if _bot_make_enabled() else "OFF"}','']
    if rows:
        lines.append('📋 <b>Bot Make Plans:</b>')
        for _,days,price,_ in rows:
            lines.append(f'• {html.escape(str(days))} — ₹{float(price or 0):.2f}')
    else:
        lines.append('⚠️ No Bot Make plans added yet.')
    lines += ['', 'When ON, <b>Bot Make</b> appears at the bottom of the User Store.']
    _admin_ui_send(call,'\n'.join(lines),parse_mode='HTML',reply_markup=_bot_make_admin_markup())

def _bot_make_insert_plan(days, price):
    days=str(days or '').strip()
    price=float(price)
    if not days or price <= 0: raise ValueError('Plan and price must be valid.')
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        cur=conn.cursor()
        cur.execute('SELECT COALESCE(MAX(display_order),0)+1 FROM products')
        order=int(cur.fetchone()[0] or 1)
        cur.execute('INSERT INTO products(name,pid_id,days,price,resell_price,is_manual,discount_percent,remote_duration,tg_group_link,is_out_of_stock,require_device_id,display_order,is_bot_make) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1)',
                    (BOT_MAKE_PRODUCT_NAME,'0',days,price,price,1,0,days,'',0,0,order))
        conn.commit()
        return cur.lastrowid
    finally: conn.close()

def _bot_make_delete_plan(pid):
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        conn.execute('DELETE FROM products WHERE id=? AND COALESCE(is_bot_make,0)=1',(int(pid),)); conn.commit()
    finally: conn.close()

def _bot_make_pending_save(order_id,user_id,product_id,plan_days,amount,payment_type):
    now=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        conn.execute('INSERT OR REPLACE INTO bot_make_orders(order_id,user_id,product_id,plan_days,amount,payment_type,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                     (str(order_id),int(user_id),int(product_id),str(plan_days),float(amount),str(payment_type),'awaiting_details',now,now))
        conn.commit()
    finally: conn.close()

def _bot_make_finish_order(order_id,bot_name,admin_id,instance_id,status='created'):
    now=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        conn.execute('UPDATE bot_make_orders SET bot_name=?,admin_id=?,instance_id=?,status=?,updated_at=? WHERE order_id=?',(str(bot_name),int(admin_id),str(instance_id or ''),str(status),now,str(order_id)))
        conn.commit()
    finally: conn.close()

def _bot_make_get_order(order_id,user_id):
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        return conn.execute('SELECT order_id,user_id,product_id,plan_days,amount,payment_type,status FROM bot_make_orders WHERE order_id=? AND user_id=?',(str(order_id),int(user_id))).fetchone()
    finally: conn.close()

def _bot_make_start_details(chat_id,user_id,order_id):
    bot_make_sessions[int(user_id)]={'order_id':str(order_id)}
    msg=bot.send_message(chat_id,'🤖 <b>Payment Successful!</b>\n\n✏️ <b>Send your bot name:</b>',parse_mode='HTML')
    bot.register_next_step_handler(msg,_bot_make_step_name)

def _bot_make_step_name(message):
    uid=int(message.from_user.id); state=bot_make_sessions.get(uid,{})
    name=(message.text or '').strip()
    if not state.get('order_id'): return
    if not name or len(name)>64:
        msg=bot.send_message(message.chat.id,'❌ Invalid bot name. Send 1–64 characters.')
        bot.register_next_step_handler(msg,_bot_make_step_name); return
    state['bot_name']=name
    msg=bot.send_message(message.chat.id,'🔑 <b>Now send your Telegram Bot Token:</b>',parse_mode='HTML')
    bot.register_next_step_handler(msg,_bot_make_step_token)

def _bot_make_step_token(message):
    uid=int(message.from_user.id); state=bot_make_sessions.get(uid,{})
    if not state.get('order_id'): return
    token=(message.text or '').strip()
    if ':' not in token or len(token)<20:
        msg=bot.send_message(message.chat.id,'❌ Invalid-looking Bot Token. Send the BotFather token exactly.')
        bot.register_next_step_handler(msg,_bot_make_step_token); return
    ok,info=_bot_creator_validate_token(token)
    if not ok:
        msg=bot.send_message(message.chat.id,f'❌ <b>Bot Token verification failed.</b>\n\n<code>{html.escape(str(info)[:500])}</code>',parse_mode='HTML')
        bot.register_next_step_handler(msg,_bot_make_step_token); return
    state['bot_token']=token
    msg=bot.send_message(message.chat.id,'👤 <b>Now send your Telegram Admin ID:</b>',parse_mode='HTML')
    bot.register_next_step_handler(msg,_bot_make_step_admin)

def _bot_make_step_admin(message):
    uid=int(message.from_user.id); state=bot_make_sessions.get(uid,{})
    if not state.get('order_id'): return
    try:
        admin_id=int((message.text or '').strip())
        if admin_id<=0: raise ValueError
    except Exception:
        msg=bot.send_message(message.chat.id,'❌ Invalid Telegram Admin ID. Send numeric ID.')
        bot.register_next_step_handler(msg,_bot_make_step_admin); return
    state['admin_id']=admin_id
    order_id=state['order_id']; bot_name=state.get('bot_name'); token=state.get('bot_token')
    bot.send_message(message.chat.id,'⏳ <b>Processing...</b>\n\nYour bot is being created. Please wait.',parse_mode='HTML')
    def worker():
        try:
            order=_bot_make_get_order(order_id,uid)
            if not order: raise ValueError('Bot Make order was not found.')
            duration_key=_bot_make_duration_key_from_label(order[3])
            instance_id,expiry,info,proc=_bot_creator_create_instance(bot_name,token,admin_id,duration_key,created_by_user_id=uid)
            _bot_make_finish_order(order_id,bot_name,admin_id,instance_id,'created')
            label=order[3]
            expiry_text=datetime.datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M:%S')
            username=getattr(info,'username','') or ''
            bot.send_message(message.chat.id,f'✅ <b>BOT CREATE SUCCESSFULLY</b>\n\n🤖 <b>Bot:</b> {html.escape(bot_name)}\n📆 <b>Plan:</b> {html.escape(str(label))}\n🔗 <b>Username:</b> @{html.escape(username) if username else "N/A"}\n⏳ <b>Expires:</b> <code>{expiry_text}</code>\n\n🚀 <b>Start the bot to use it.</b>',parse_mode='HTML')
            try: bot.send_message(admin_id,f'🤖 <b>Your bot is ready.</b>\n\n@{html.escape(username) if username else "N/A"}\n📆 Validity: <b>{html.escape(str(label))}</b>\n⏳ Expires: <code>{expiry_text}</code>',parse_mode='HTML')
            except Exception: pass
        except Exception as exc:
            _bot_make_finish_order(order_id,bot_name or '',admin_id,'','failed')
            bot.send_message(message.chat.id,f'❌ <b>Bot creation failed.</b>\n\n<code>{html.escape(str(exc)[:1000])}</code>',parse_mode='HTML')
        finally:
            bot_make_sessions.pop(uid,None)
    _run_user_task_async(worker)

def _bot_make_duration_key_from_label(label):
    raw=str(label or '').strip().lower()
    m=re.search(r'(\d+)\s*day',raw)
    if m: return f"{m.group(1)}d"
    m=re.search(r'(\d+)\s*month',raw)
    if m: return f"{m.group(1)}m"
    m=re.search(r'(\d+)\s*year',raw)
    if m: return f"{m.group(1)}y"
    raise ValueError('Unsupported Bot Make plan duration. Use Days, Months or Years.')

def _bot_make_paid_wallet(chat_id,user_id,product_id,message_id=None):
    product=get_product_by_id(product_id)
    if not product: return
    amount=float(product[4] or 0)
    if not deduct_user_balance(user_id,amount):
        show_topup_options(chat_id,message_id=message_id); return
    order_id='BM'+datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')+str(random.randint(1000,9999))
    _bot_make_pending_save(order_id,user_id,product_id,product[3],amount,'wallet')
    try: record_order(order_id,user_id,BOT_MAKE_PRODUCT_NAME,product[3],amount,'BOT-MAKE')
    except Exception: pass
    _bot_make_start_details(chat_id,user_id,order_id)

def _bot_make_is_product(product):
    try:
        # Bot Make is a virtual product. Prefer the additive flag, but also
        # recognize a legacy/migrated row by its reserved product name so an
        # older database cannot accidentally send it through API/stock logic.
        return bool(
            product and
            str(product[1]).strip().lower() == BOT_MAKE_PRODUCT_NAME.lower() and
            (len(product) <= 13 or int(product[13] or 0) == 1)
        )
    except Exception:
        try:
            return bool(product and str(product[1]).strip().lower() == BOT_MAKE_PRODUCT_NAME.lower())
        except Exception:
            return False

# ==================== MASTER BOT CREATOR ====================
_bot_creator_temp = {}
_bot_creator_lock = threading.RLock()
_bot_child_processes = {}


def _is_bot_creator_root_admin(user_id):
    try:
        return BOT_CREATOR_ENABLED and int(user_id) in _HARDCODED_ROOT_ADMIN_IDS
    except Exception:
        return False


def _bot_creator_duration_options():
    return {'7d': ('7 Days', 7), '30d': ('30 Days', 30), '6m': ('6 Months', 182), '1y': ('1 Year', 365)}


def _bot_creator_add_months(dt, months):
    import calendar
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _bot_creator_expiry(duration_key):
    now = datetime.datetime.now(datetime.timezone.utc)
    if duration_key == '6m':
        end = _bot_creator_add_months(now, 6)
    elif duration_key == '1y':
        end = _bot_creator_add_months(now, 12)
    elif re.fullmatch(r'\d+d', str(duration_key)):
        end = now + datetime.timedelta(days=int(str(duration_key)[:-1]))
    elif re.fullmatch(r'\d+m', str(duration_key)):
        end = _bot_creator_add_months(now, int(str(duration_key)[:-1]))
    elif re.fullmatch(r'\d+y', str(duration_key)):
        end = _bot_creator_add_months(now, 12*int(str(duration_key)[:-1]))
    else:
        end = now + datetime.timedelta(days=_bot_creator_duration_options()[duration_key][1])
    return end.timestamp()


def _bot_creator_markup():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.row(
        make_ui_button('7 Days', callback_data='botcreate_duration_7d', button_key='admin:botcreate:7d', default_color='blue', force_style=True),
        make_ui_button('30 Days', callback_data='botcreate_duration_30d', button_key='admin:botcreate:30d', default_color='blue', force_style=True),
    )
    m.row(
        make_ui_button('6 Months', callback_data='botcreate_duration_6m', button_key='admin:botcreate:6m', default_color='blue', force_style=True),
        make_ui_button('1 Year', callback_data='botcreate_duration_1y', button_key='admin:botcreate:1y', default_color='blue', force_style=True),
    )
    m.add(make_ui_button('🔙 Main Admin Panel', callback_data='admin_back_main', button_key='admin:navigation:back', default_color='red', force_style=True))
    return _style_admin_markup(m)


def _bot_creator_prepare_database(child_dir, admin_id):
    """Create a genuinely fresh database for a newly-created child bot.

    IMPORTANT:
    - Never clone the live Master database or a previously restored child.
    - The child starts with no users/products/orders/payments/business data.
    - init_db() inside the child creates its own schema/default settings and
      seeds only the designated child administrator.
    - A later explicit backup restore is the only way Master/backup data enters
      the child database.
    """
    dst = (Path(child_dir) / 'shop_data.db').resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)

    # Never inherit SQLite sidecar files either.  A copied WAL/SHM file can
    # make an apparently empty database expose old rows after creation.
    for suffix in ('', '-wal', '-shm', '-journal'):
        candidate = Path(str(dst) + suffix)
        try:
            if candidate.exists():
                candidate.unlink()
        except Exception:
            pass

    # Do NOT copy shop_data.db, .bot_creator_template.db, or any other
    # database from the Master Bot. Create an empty SQLite file instead.
    conn = sqlite3.connect(str(dst), timeout=20)
    try:
        conn.execute('PRAGMA journal_mode=DELETE')
        conn.commit()
    finally:
        conn.close()

    # Remove a stale readiness marker if an instance directory is ever reused.
    try:
        ready = dst.parent / '.bot_ready'
        if ready.exists():
            ready.unlink()
    except Exception:
        pass


def _bot_creator_token_already_registered(token):
    """Return the existing instance id when the same Telegram bot token is already registered.

    Two processes polling the same token cause Telegram 409 conflicts. Detect it
    before spawning so one bot cannot accidentally take the other bot offline.
    """
    token = str(token or '').strip()
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    try:
        conn = sqlite3.connect(str(BOT_DB_PATH), timeout=20)
        try:
            rows = conn.execute("SELECT instance_id, instance_dir FROM bot_instances WHERE status IN ('starting','running','paused','maintenance','expired')").fetchall()
        finally:
            conn.close()
        for instance_id, instance_dir in rows:
            env_file = Path(str(instance_dir)) / '.bot_env.json'
            try:
                env = json.loads(env_file.read_text(encoding='utf-8'))
                saved = str(env.get('BOT_TOKEN') or '').strip()
                if saved and hashlib.sha256(saved.encode('utf-8')).hexdigest() == token_hash:
                    return str(instance_id)
            except Exception:
                continue
    except Exception as exc:
        print(f'[BOT CREATOR TOKEN CHECK] {exc}')
    return None


def _bot_creator_validate_token(token):
    try:
        t = telebot.TeleBot(token, threaded=False)
        me = t.get_me()
        if not me or not getattr(me, 'id', None):
            return False, 'Telegram did not return a valid bot.'
        return True, me
    except Exception as exc:
        return False, str(exc)


def _bot_creator_configure_menu(token, admin_id):
    """Configure Telegram Menu commands for a generated customer bot.

    Default scope: only /start is visible to normal users.
    Admin chat scope: /start and /admin are visible to the designated admin.
    """
    t = telebot.TeleBot(str(token).strip(), threaded=False)
    user_commands = [types.BotCommand('start', 'Open main menu⚡')]
    admin_commands = [types.BotCommand('start', 'Open main menu⚡'), types.BotCommand('admin', 'Open admin panel🔨')]
    try:
        # Replace any previous default command list with the normal-user menu.
        t.set_my_commands(user_commands)
    except Exception:
        pass
    try:
        # Admin-only command scope. This does not expose /admin in the default
        # menu shown to ordinary users.
        scope = types.BotCommandScopeChat(chat_id=int(admin_id))
        t.set_my_commands(admin_commands, scope=scope)
    except TypeError:
        # Compatibility with versions that accept a positional scope object.
        scope = types.BotCommandScopeChat(int(admin_id))
        t.set_my_commands(admin_commands, scope)
    return True


def _configure_current_bot_menu():
    """Set the same clean Telegram command menu for the main bot.

    Ordinary users get only /start; every configured admin gets /start and
    /admin. The default scope is deliberately not populated with /admin.
    """
    try:
        bot.set_my_commands([types.BotCommand('start', 'Open main menu⚡')])
    except Exception:
        pass
    for admin_id in list(ADMIN_IDS):
        try:
            scope = types.BotCommandScopeChat(chat_id=int(admin_id))
            bot.set_my_commands(
                [
                    types.BotCommand('start', 'Open main menu⚡'),
                    types.BotCommand('admin', 'Open admin panel🔨'),
                ],
                scope=scope,
            )
        except TypeError:
            try:
                scope = types.BotCommandScopeChat(int(admin_id))
                bot.set_my_commands(
                    [
                        types.BotCommand('start', 'Open main menu⚡'),
                        types.BotCommand('admin', 'Open admin panel🔨'),
                    ],
                    scope,
                )
            except Exception:
                pass
        except Exception:
            pass


def _bot_creator_save_env(child_dir, env):
    safe = {k:v for k,v in env.items() if k.startswith(('BOT_','FAMPAY_','RESELLER_','NEW_SERVER_','NINEX_','WHATSAPP_','TELEGRAM_','UPDATE_'))}
    (child_dir / '.bot_env.json').write_text(json.dumps(safe, ensure_ascii=False), encoding='utf-8')


def _bot_creator_child_environment(token, admin_id, bot_name, expiry, instance_id, child_dir):
    """Build an isolated runtime environment for one generated bot.

    Do not inherit Master Bot secrets/configuration such as payment gateway
    credentials, reseller keys, API tokens, or Master BOT_TOKEN. Child data is
    supplied through its own database and explicit backup restore workflow.
    """
    inherited_keys = {
        'PATH', 'PYTHONPATH', 'HOME', 'USERPROFILE', 'TMP', 'TEMP', 'TMPDIR',
        'SYSTEMROOT', 'WINDIR', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ',
        'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE'
    }
    env = {k: v for k, v in os.environ.items() if k in inherited_keys}

    child_db_path = (Path(child_dir) / 'shop_data.db').resolve()
    env.update({
        'BOT_TOKEN': str(token).strip(),
        'BOT_ADMIN_IDS': str(int(admin_id)),
        'BOT_BRAND_NAME': str(bot_name).strip() or 'RG CHEAT SHOP',
        'BOT_CREATOR_ENABLED': '0',
        'BOT_EXPIRES_AT': str(expiry),
        'BOT_INSTANCE_ID': str(instance_id),
        'BOT_INSTANCES_DIR': str(BOT_INSTANCES_DIR.resolve()),
        'BOT_DB_PATH': str(child_db_path),
        'BOT_CHILD_READY_FILE': str((Path(child_dir) / '.bot_ready').resolve()),
        # Keep each generated bot responsive when multiple bots run at once.
        # These are intentionally per-child and can still be overridden later.
        'BOT_TELEGRAM_WORKERS': '6',
        'USER_TASK_WORKERS': '6',
        'PAYMENT_TASK_WORKERS': '3',
        'HTTP_POOL_SIZE': '12',
        # Each child gets its own internal API port so two generated bots do
        # not fight over the Master's public SERVER_PORT. The public URL is
        # still controlled separately through RESELLER_API_PUBLIC_URL.
        'BOT_CHILD_HTTP_PORT': str(18000 + (int(str(instance_id)[:6], 16) % 20000)),
        'PYTHONUNBUFFERED': '1',
    })

    # Keep child-specific runtime defaults empty until the child admin
    # configures them or an explicit backup is restored.
    for key in (
        'FAMPAY_API_KEY', 'FAMPAY_GATEWAY_URL', 'FAMPAY_UPI_ID',
        'RESELLER_API_URL', 'RESELLER_API_KEY', 'RESELLER_MASTER_KEY',
        'RESELLER_API_PUBLIC_URL', 'NEW_SERVER_API_URL', 'NEW_SERVER_API_KEY',
        'NINEX_DEFAULT_API_URL', 'WHATSAPP_NUM', 'TELEGRAM_USER',
        'UPDATE_CHANNEL_LINK'
    ):
        env.pop(key, None)

    return env


def _bot_creator_spawn(instance_id, child_dir, env):
    log_path = Path(child_dir) / 'bot.log'
    ready_path = Path(env.get('BOT_CHILD_READY_FILE') or (Path(child_dir) / '.bot_ready'))
    try:
        ready_path.unlink(missing_ok=True)
    except Exception:
        pass

    log = open(log_path, 'a', encoding='utf-8')
    try:
        # -u keeps startup errors visible immediately in bot.log.  This is
        # important because the child has its own process and working folder.
        proc = subprocess.Popen(
            [os.sys.executable, '-u', str(Path(child_dir) / 'main.py')],
            cwd=str(child_dir), env=env, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True
        )
    except Exception:
        log.close()
        raise
    _bot_child_processes[instance_id] = proc

    # Wait for an explicit readiness marker rather than assuming that a child
    # which has not exited after 350 ms is actually polling Telegram.
    deadline = time.time() + 12.0
    while time.time() < deadline:
        if proc.poll() is not None:
            try:
                tail = log_path.read_text(encoding='utf-8', errors='replace')[-3000:]
            except Exception:
                tail = ''
            _bot_child_processes.pop(instance_id, None)
            raise RuntimeError(
                'Created bot process exited during startup. ' +
                (f'Child log: {tail}' if tail else 'Check bot.log inside the bot instance.')
            )
        if ready_path.exists():
            return proc
        time.sleep(0.25)

    # If imports are simply slow, keep the process alive but surface a useful
    # warning instead of falsely claiming it is fully ready.
    if proc.poll() is None:
        print(f'[BOT CREATOR] Child {instance_id} is still starting; readiness marker not seen yet.')
        return proc
    _bot_child_processes.pop(instance_id, None)
    raise RuntimeError('Created bot process stopped before it became ready. Check the child bot.log.')


def _bot_creator_create_instance(bot_name, token, admin_id, duration_key, created_by_user_id=0):
    valid, info = _bot_creator_validate_token(token)
    if not valid:
        raise ValueError(f'Invalid Bot Token: {info}')
    existing_instance = _bot_creator_token_already_registered(token)
    if existing_instance:
        raise ValueError(
            f'This Telegram Bot Token is already running in created instance {existing_instance}. '
            'Use a different BotFather token instead of starting the same bot twice.'
        )
    expiry = _bot_creator_expiry(duration_key)
    instance_id = secrets.token_hex(8)
    child_dir = BOT_INSTANCES_DIR / instance_id
    child_dir.mkdir(parents=True, exist_ok=False)
    try:
        shutil.copy2(Path(__file__).resolve(), child_dir / 'main.py')
        # The protected runtime is split into a small loader (main.py) and the
        # encrypted application payload (main.enc).  Generated child bots need
        # both files so Bot Make continues to work after this protection step.
        payload_path = Path(__file__).resolve().with_name('main.enc')
        if payload_path.exists():
            shutil.copy2(payload_path, child_dir / 'main.enc')
        _bot_creator_prepare_database(child_dir, admin_id)
        env = _bot_creator_child_environment(
            token=token,
            admin_id=admin_id,
            bot_name=bot_name,
            expiry=expiry,
            instance_id=instance_id,
            child_dir=child_dir,
        )
        _bot_creator_save_env(child_dir, env)

        # Register the instance BEFORE spawning the child. The child can then
        # read the same authoritative expiry from bot_instances during startup,
        # eliminating stale inherited expiry state.
        now_text = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn = sqlite3.connect(str(BOT_DB_PATH), timeout=20)
        try:
            conn.execute("INSERT INTO bot_instances(instance_id,bot_name,admin_id,duration_key,expires_at,instance_dir,status,created_at,updated_at,created_by_user_id) VALUES(?,?,?,?,?,?,?,?,?,?)", (instance_id,str(bot_name).strip(),int(admin_id),duration_key,expiry,str(child_dir),'starting',now_text,now_text,int(created_by_user_id or 0)))
            conn.commit()
        finally:
            conn.close()

        # Automatically configure the Telegram Menu for this newly created bot:
        # normal users get Start, while the designated admin gets Start + Admin.
        _bot_creator_configure_menu(token.strip(), int(admin_id))
        try:
            proc = _bot_creator_spawn(instance_id, child_dir, env)
        except Exception:
            conn = sqlite3.connect(str(BOT_DB_PATH), timeout=20)
            try:
                conn.execute('DELETE FROM bot_instances WHERE instance_id=?', (instance_id,))
                conn.commit()
            finally:
                conn.close()
            raise

        conn = sqlite3.connect(str(BOT_DB_PATH), timeout=20)
        try:
            conn.execute("UPDATE bot_instances SET status=?, updated_at=? WHERE instance_id=?", ('running', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), instance_id))
            conn.commit()
        finally:
            conn.close()
        return instance_id, expiry, info, proc
    except Exception:
        shutil.rmtree(child_dir, ignore_errors=True)
        raise


def _bot_creator_open(call):
    if not _is_bot_creator_root_admin(call.from_user.id):
        _admin_ui_send(call, '❌ <b>Bot Creator is available only on the Master Bot.</b>', parse_mode='HTML')
        return
    _admin_ui_send(call, '🤖 <b>CREATE NEW BOT</b>\n\nSelect the subscription period already paid for by the customer:', parse_mode='HTML', reply_markup=_bot_creator_markup())


def _bot_creator_step_name(message):
    uid = message.from_user.id
    if not _is_bot_creator_root_admin(uid): return
    name = (message.text or '').strip()
    if not name or len(name) > 64:
        m=bot.send_message(message.chat.id,'❌ Enter a valid bot name (1–64 characters).'); bot.register_next_step_handler(m,_bot_creator_step_name); return
    _bot_creator_temp[uid]['bot_name']=name
    m=bot.send_message(message.chat.id,'🔑 <b>Send the Telegram Bot API Token:</b>',parse_mode='HTML'); bot.register_next_step_handler(m,_bot_creator_step_token)


def _bot_creator_step_token(message):
    uid=message.from_user.id
    if not _is_bot_creator_root_admin(uid): return
    token=(message.text or '').strip()
    if ':' not in token or len(token)<20:
        m=bot.send_message(message.chat.id,'❌ Invalid-looking Bot Token. Send the token exactly as received from BotFather.'); bot.register_next_step_handler(m,_bot_creator_step_token); return
    ok,info=_bot_creator_validate_token(token)
    if not ok:
        m=bot.send_message(message.chat.id,f'❌ <b>Bot Token verification failed.</b>\n\n<code>{html.escape(str(info)[:500])}</code>',parse_mode='HTML'); bot.register_next_step_handler(m,_bot_creator_step_token); return
    _bot_creator_temp[uid]['bot_token']=token
    m=bot.send_message(message.chat.id,'👤 <b>Send the Telegram Admin ID for the new bot:</b>',parse_mode='HTML'); bot.register_next_step_handler(m,_bot_creator_step_admin)


def _bot_creator_step_admin(message):
    uid=message.from_user.id
    if not _is_bot_creator_root_admin(uid): return
    try:
        target_admin=int((message.text or '').strip())
        if target_admin<=0: raise ValueError
    except Exception:
        m=bot.send_message(message.chat.id,'❌ Invalid Telegram ID. Send numeric Telegram User ID.'); bot.register_next_step_handler(m,_bot_creator_step_admin); return
    data=_bot_creator_temp.pop(uid,{})
    if not data.get('bot_name') or not data.get('bot_token') or not data.get('duration_key'):
        bot.send_message(message.chat.id, '❌ <b>Bot creation session expired.</b> Please start Create New Bot again.', parse_mode='HTML', reply_markup=_bot_creator_markup())
        return

    bot.send_message(
        message.chat.id,
        '⏳ <b>Creating bot...</b>\n\nThe Telegram API check, database setup and child process are running in the background. Your Master Bot will remain responsive.',
        parse_mode='HTML'
    )

    def _create_worker():
        try:
            instance_id,expiry,info,proc=_bot_creator_create_instance(data['bot_name'],data['bot_token'],target_admin,data['duration_key'])
            label,_=_bot_creator_duration_options()[data['duration_key']]
            expiry_text=datetime.datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M:%S')
            username=getattr(info,'username','') or ''
            bot.send_message(message.chat.id,'✅ <b>BOT CREATED SUCCESSFULLY</b>\n\n'+f'🤖 <b>Name:</b> {html.escape(data["bot_name"])}\n📆 <b>Plan:</b> {html.escape(label)}\n👤 <b>Admin ID:</b> <code>{target_admin}</code>\n🔗 <b>Bot:</b> @{html.escape(username) if username else "N/A"}\n🆔 <b>Instance:</b> <code>{instance_id}</code>\n⏳ <b>Expires:</b> <code>{expiry_text}</code>\n\nThe new bot is starting now. Its Admin Panel does not contain the Bot Creator option.',parse_mode='HTML',reply_markup=_bot_creator_markup())
            try: bot.send_message(target_admin,f'🤖 <b>Your bot is ready:</b> @{html.escape(username)}\n📆 Validity: <b>{html.escape(label)}</b>\n⏳ Expires: <code>{expiry_text}</code>',parse_mode='HTML')
            except Exception: pass
        except Exception as exc:
            bot.send_message(message.chat.id,f'❌ <b>Bot creation failed.</b>\n\n<code>{html.escape(str(exc)[:1000])}</code>',parse_mode='HTML',reply_markup=_bot_creator_markup())

    _run_user_task_async(_create_worker)


def _bot_creator_cleanup_expired():
    if not BOT_CREATOR_ENABLED: return
    while True:
        try:
            now=time.time(); conn=sqlite3.connect(str(BOT_DB_PATH),timeout=20)
            rows=conn.execute("SELECT instance_id FROM bot_instances WHERE expires_at <= ? AND status='running'",(now,)).fetchall()
            for (instance_id,) in rows:
                # Keep the child process alive after expiry so its Admin can see
                # the Expired/Pay & Start screen and the Main Admin can renew it.
                # The child runtime itself blocks normal users immediately when
                # its saved expiry timestamp reaches zero.
                conn.execute("UPDATE bot_instances SET status='expired',updated_at=? WHERE instance_id=?",(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),instance_id))
            conn.commit(); conn.close()
        except Exception as exc: print('[BOT CREATOR EXPIRY ERROR]',exc)
        time.sleep(1)


def _bot_creator_restore_children():
    if not BOT_CREATOR_ENABLED: return
    try:
        now=time.time(); conn=sqlite3.connect(str(BOT_DB_PATH),timeout=20)
        rows=conn.execute("SELECT instance_id,expires_at,instance_dir FROM bot_instances WHERE status='running' AND expires_at > ?",(now,)).fetchall(); conn.close()
        for instance_id,expires_at,instance_dir in rows:
            child_dir=Path(instance_dir); env_file=child_dir/'.bot_env.json'
            if not child_dir.exists() or not env_file.exists(): continue
            try:
                saved_env = json.loads(env_file.read_text(encoding='utf-8'))
                env = _bot_creator_child_environment(
                    token=saved_env.get('BOT_TOKEN', ''),
                    admin_id=saved_env.get('BOT_ADMIN_IDS', '0'),
                    bot_name=saved_env.get('BOT_BRAND_NAME', 'RG CHEAT SHOP'),
                    expiry=expires_at,
                    instance_id=instance_id,
                    child_dir=child_dir,
                )
                _bot_creator_spawn(instance_id, child_dir, env)
            except Exception as exc: print('[BOT CREATOR RESTORE ERROR]',instance_id,exc)
    except Exception as exc: print('[BOT CREATOR RESTORE INIT ERROR]',exc)


def _enforce_child_bot_expiry():
    """Keep the child expiry state synchronized to the saved timestamp."""
    global BOT_EXPIRED_RUNTIME
    if BOT_CREATOR_ENABLED or BOT_EXPIRES_AT <= 0:
        BOT_EXPIRED_RUNTIME = False
        return
    BOT_EXPIRED_RUNTIME = time.time() >= BOT_EXPIRES_AT

def _child_expiry_monitor():
    global BOT_EXPIRED_RUNTIME
    if BOT_CREATOR_ENABLED or BOT_EXPIRES_AT <= 0:
        return
    while True:
        _sync_child_expiry_from_registry()
        BOT_EXPIRED_RUNTIME = time.time() >= BOT_EXPIRES_AT
        if BOT_EXPIRED_RUNTIME:
            print('[BOT CREATOR] Subscription timer reached zero; bot is now expired.')
            return
        time.sleep(1.0)

def _sync_child_expiry_from_registry():
    """Synchronize a generated bot's expiry from the Master Bot registry.

    The child bot receives its expiry through the environment at spawn time, but
    the registry is the authoritative source. This prevents stale inherited
    runtime state from making a newly-created bot appear expired immediately.
    The child database is intentionally NOT used here, so child data remains
    isolated from the Master Bot database.
    """
    global BOT_EXPIRES_AT
    if BOT_CREATOR_ENABLED or not BOT_INSTANCE_ID:
        return BOT_EXPIRES_AT

    try:
        registry_dir = Path(BOT_INSTANCES_DIR)
        master_db = registry_dir.parent / "shop_data.db"
        if not master_db.exists():
            return BOT_EXPIRES_AT

        conn = sqlite3.connect(str(master_db), timeout=5)
        try:
            row = conn.execute(
                "SELECT expires_at FROM bot_instances WHERE instance_id=?",
                (str(BOT_INSTANCE_ID),)
            ).fetchone()
        finally:
            conn.close()

        if row and row[0] is not None:
            registry_expiry = float(row[0])
            if registry_expiry > 0:
                BOT_EXPIRES_AT = registry_expiry
    except Exception:
        # Keep the environment value as a safe fallback if the registry is
        # temporarily locked or unavailable.
        pass

    return BOT_EXPIRES_AT


def _child_bot_is_expired():
    if BOT_CREATOR_ENABLED or BOT_EXPIRES_AT <= 0:
        return False
    # Always calculate from the authoritative timestamp. Do not let a stale
    # in-memory runtime flag mark a freshly-created bot as expired.
    return bool(time.time() >= float(BOT_EXPIRES_AT))


def _expired_admin_text():
    return (
        '⏳ <b>BOT SUBSCRIPTION EXPIRED</b>\n\n'
        '⚠️ Your bot validity has expired.\n\n'
        '👤 <b>Contact Main Admin</b> and complete payment to start the bot again.'
    )


def _expired_user_text():
    return '🔧 <b>Bot Maintenance</b>\n\nPlease contact the bot administrator to restore service.'

def _admin_panel_text():
    """Compact dashboard text shared by every route back to the main Admin Panel."""
    bot_on = is_bot_enabled()
    status = "🟢 ONLINE" if bot_on else "🔴 OFFLINE"
    expiry = ""
    if not BOT_CREATOR_ENABLED and BOT_EXPIRES_AT > 0:
        expiry = f"\n⏳ <b>Validity:</b> <code>{_format_remaining_time(BOT_EXPIRES_AT)}</code>"
    return (
        f"🛠️ <b>{html.escape(BOT_BRAND_SHORT)} ADMIN CONTROL CENTER</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📡 <b>Service:</b> {status}{expiry}\n\n"
        "📂 <b>Choose a management section</b>\n"
        "<i>Everything is grouped below so settings are easier to find.</i>"
    )


def _admin_main_markup():
    """Polished two-column Admin Panel layout; every existing control is retained."""
    markup = types.InlineKeyboardMarkup(row_width=2)

    # Primary management sections — ordered from daily operations to system tools.
    rows = [
        ("⚡ Product & Plans", "admin_cat_setup"),
        ("🙈 Product Hide / Unhide", "admin_product_hide"),
        ("💳 FamPay Gateway", "admin_gateway_manager"),
        ("🌐 API & Servers", "admin_cat_api"),
        ("👥 Users & Resellers", "admin_cat_users"),
        ("✨ User Panel UI", "admin_cat_emoji"),
        ("📝 Text & Price List", "admin_cat_text"),
        ("📢 Broadcast & Support", "admin_cat_tools"),
        ("📥 Backup Bot Backup Download", "admin_db_backup_download"),
        ("👤 Admin Accounts", "admin_manage_admins"),
    ]
    for i in range(0, len(rows), 2):
        pair = rows[i:i+2]
        markup.row(*(
            make_ui_button(
                label, callback_data=cb,
                button_key=f"admin:category:{cb}",
                default_color="blue", force_style=True
            )
            for label, cb in pair
        ))

    # Obsolete bot-creation/list controls were intentionally removed.
    # Bot backup is now a single dedicated entry in the main grid above.

    # Keep the two runtime switches compact on the same final row.
    # User Tracking controls ONLY Button/Callback activity notifications; the
    # Bot Status switch keeps its existing behavior unchanged.
    tracking_on = is_user_activity_notifications_enabled()
    bot_on = is_bot_enabled()
    tracking_label = "🔔 Tracking: ON" if tracking_on else "🔕 Tracking: OFF"
    status_label = "🟢 Bot Status: ON" if bot_on else "🔴 Bot Status: OFF"
    markup.row(
        make_ui_button(
            tracking_label, callback_data="admin_user_activity_toggle",
            button_key="admin:user_activity_notifications",
            default_color="green" if tracking_on else "red", force_style=True
        ),
        make_ui_button(
            status_label, callback_data="admin_bot_toggle",
            button_key="admin:bot_status",
            default_color="green" if bot_on else "red", force_style=True
        )
    )
    return _style_admin_markup(markup)


def admin_panel(message):
    user_id = message.from_user.id
    if not _is_admin(user_id):
        bot.send_message(message.chat.id, "❌ <b>Access Denied!</b> Only Admin can access this command.", parse_mode="HTML")
        return
    root_markup=_admin_main_markup()
    sent = bot.send_message(message.chat.id,_admin_panel_text(),parse_mode="HTML",reply_markup=root_markup)
    _admin_store_snapshot(user_id,_admin_panel_text(),root_markup,"admin_main",sent.message_id)
    admin_nav_snapshots.pop(int(user_id),None)
    if not BOT_CREATOR_ENABLED and BOT_EXPIRES_AT > 0:
        _start_child_admin_expiry_timer(message.chat.id, sent.message_id)


def _get_reseller_users():
    """Return all users currently marked as Reseller, newest/active names first.

    This is read-only admin reporting. It does not change any user, balance,
    order, product, payment or reseller-role data.
    """
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        rows = conn.execute(
            """SELECT user_id, first_name, phone_number, balance,
                      orders_count, lifetime_spent, total_deposited,
                      joined_date, is_verified, is_banned
                 FROM users
                 WHERE is_reseller = 1
                 ORDER BY LOWER(COALESCE(first_name, '')), user_id ASC"""
        ).fetchall()
        return rows
    finally:
        conn.close()


def _reseller_list_markup(page=0, page_size=20):
    """Build a paginated reseller-name list with safe navigation."""
    try:
        page = max(0, int(page))
    except Exception:
        page = 0
    page_size = max(1, int(page_size))
    rows = _get_reseller_users()
    total = len(rows)
    start = page * page_size
    end = min(start + page_size, total)
    visible = rows[start:end]

    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for row in visible:
        uid = int(row[0])
        name = str(row[1] or 'Unnamed Reseller').strip()
        if len(name) > 19:
            name = name[:18] + '…'
        buttons.append(
            types.InlineKeyboardButton(
                f"👑 {name}\n🆔 {uid}"[:64],
                callback_data=f"admin_reseller_profile_{uid}"
            )
        )
    for i in range(0, len(buttons), 2):
        markup.row(*buttons[i:i+2])

    if total > page_size:
        nav = []
        if page > 0:
            nav.append(types.InlineKeyboardButton("⬅️ Previous", callback_data=f"admin_reseller_list_{page-1}"))
        if end < total:
            nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"admin_reseller_list_{page+1}"))
        if nav:
            markup.row(*nav)

    markup.add(types.InlineKeyboardButton("🔙 Users & Resellers", callback_data="admin_cat_users"))
    return markup, total, start + 1 if visible else 0, end


def _send_reseller_list(call, page=0):
    """Show the reseller list without changing any existing admin system."""
    markup, total, first_no, last_no = _reseller_list_markup(page)
    active_users, active_resellers, active_window = _admin_recent_activity_counts(5)
    if total == 0:
        text = (
            "👑 <b>RESELLER LIST</b>\n"
            "────────────────────────\n\n"
            "<i>No reseller users have been added yet.</i>\n\n"
            "Use <b>Add / Remove Reseller Role</b> to promote a user."
        )
    else:
        page_info = f"\n📄 Showing <b>{first_no}-{last_no}</b> of <b>{total}</b> resellers."
        text = (
            "👑 <b>RESELLER LIST</b>\n"
            "────────────────────────\n\n"
            f"📊 <b>Total Resellers:</b> {total}\n"
            f"🟢 <b>Active:</b> {active_resellers} (last {active_window} min)\n\n"
            "Select a reseller to view their account details, balance, phone, Telegram ID, purchase count and spending."
            + page_info
        )
    _admin_ui_send(call, text, parse_mode="HTML", reply_markup=markup)


def _search_users_and_resellers(query):
    """Search users/resellers by ID, name, phone, or username."""
    q = str(query or '').strip()
    if not q:
        return []
    results = {}
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        if q.isdigit():
            rows = conn.execute(
                '''SELECT user_id,first_name,phone_number,balance,orders_count,lifetime_spent,
                          total_deposited,joined_date,is_verified,is_banned,is_reseller
                   FROM users WHERE user_id=? OR phone_number LIKE ?
                   ORDER BY user_id ASC''',
                (int(q), f'%{q}%')
            ).fetchall()
        else:
            phone_digits = re.sub(r'\D', '', q)
            rows = conn.execute(
                '''SELECT user_id,first_name,phone_number,balance,orders_count,lifetime_spent,
                          total_deposited,joined_date,is_verified,is_banned,is_reseller
                   FROM users
                   WHERE LOWER(COALESCE(first_name,'')) LIKE LOWER(?)
                      OR LOWER(COALESCE(telegram_username,'')) LIKE LOWER(?)
                      OR phone_number LIKE ?
                   ORDER BY LOWER(COALESCE(first_name,'')), user_id ASC''',
                (f'%{q}%', f'%{q.lstrip("@")}%', f'%{phone_digits or q}%')
            ).fetchall()
        for row in rows:
            results[int(row[0])] = row
    finally:
        conn.close()

    username_query = q.lstrip('@').strip()
    if username_query and re.fullmatch(r'[A-Za-z0-9_]{4,32}', username_query):
        try:
            chat = bot.get_chat('@' + username_query)
            uid = int(getattr(chat, 'id', 0) or 0)
            if uid:
                row = get_user(uid)
                if row:
                    results[uid] = (
                        uid, row[1], row[2], row[4], row[6], row[7], row[8], row[9],
                        row[10], row[16] if len(row) > 16 else 0, row[11] if len(row) > 11 else 0
                    )
        except Exception:
            pass
    return list(results.values())

def _search_result_markup(results):
    markup = types.InlineKeyboardMarkup(row_width=1)
    for row in results:
        uid = int(row[0])
        name = str(row[1] or 'Unnamed User')
        role = '👑 Reseller' if int(row[10] or 0) == 1 else '👤 User'
        username = _get_live_telegram_username(uid, '')
        label = f'{role} · {name} · ID {uid}'
        if username:
            label += f' · @{username}'
        markup.add(types.InlineKeyboardButton(label[:64], callback_data=f'admin_user_search_profile_{uid}'))
    markup.add(types.InlineKeyboardButton('🔎 Search Again', callback_data='admin_user_reseller_search'))
    markup.add(types.InlineKeyboardButton('🔙 Users & Resellers', callback_data='admin_cat_users'))
    return markup

def _send_user_reseller_search(call):
    msg = _admin_ui_send(
        call,
        '🔎 <b>USER & RESELLER SEARCH</b>\n\n'
        'Search by <b>Telegram Chat/User ID</b>, <b>@Username</b>, <b>Name</b> or <b>Phone Number</b>.\n'
        'If several accounts match, all matching accounts will be shown.',
        parse_mode='HTML'
    )
    bot.register_next_step_handler(msg, _step_user_reseller_search)

def _step_user_reseller_search(message):
    if not _is_admin(message.from_user.id):
        return
    query = str(message.text or '').strip()
    if not query:
        msg = bot.send_message(message.chat.id, '❌ <b>Enter a search value.</b>', parse_mode='HTML')
        bot.register_next_step_handler(msg, _step_user_reseller_search)
        return
    results = _search_users_and_resellers(query)
    if not results:
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton('🔎 Search Again', callback_data='admin_user_reseller_search'))
        markup.add(types.InlineKeyboardButton('🔙 Users & Resellers', callback_data='admin_cat_users'))
        bot.send_message(message.chat.id, f'❌ <b>No User/Reseller found for:</b> <code>{html.escape(query, quote=False)}</code>', parse_mode='HTML', reply_markup=markup)
        return
    text = ('🔎 <b>SEARCH RESULTS</b>\n────────────────────────\n\n'
            f'Found <b>{len(results)}</b> matching account(s).\n'
            '<i>Tap an account below to open its complete profile.</i>')
    bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=_search_result_markup(results))

def _send_searched_account_profile(call, target_uid):
    try:
        target_uid = int(target_uid)
    except Exception:
        bot.answer_callback_query(call.id, '❌ Invalid account ID.', show_alert=True)
        return
    user = get_user(target_uid)
    if not user:
        bot.answer_callback_query(call.id, '❌ User/Reseller not found.', show_alert=True)
        return
    name = str(user[1] or 'Unnamed User')
    phone = str(user[2] or 'N/A')
    balance = float(user[4] or 0.0)
    orders_count = int(user[6] or 0)
    lifetime_spent = float(user[7] or 0.0)
    total_deposited = float(user[8] or 0.0)
    joined = str(user[9] or 'N/A')
    role = '👑 Reseller' if len(user) > 11 and int(user[11] or 0) == 1 else '👤 User'
    verified = '✅ Verified' if len(user) > 10 and int(user[10] or 0) else '⚪ Not Verified'
    banned = '🚫 Banned' if len(user) > 16 and int(user[16] or 0) else '🟢 Active'
    discount = float(user[12] or 0.0) if len(user) > 12 else 0.0
    referrals = int(user[14] or 0) if len(user) > 14 else 0
    username = _get_live_telegram_username(target_uid, '') or 'N/A'
    orders = get_user_orders(target_uid)
    if orders:
        recent_text = ''.join(
            f'• <code>{html.escape(str(o[0]))}</code> — {html.escape(str(o[1]))} / {html.escape(str(o[2]))} — ₹{float(o[3] or 0):.2f}\n'
            for o in orders[:10]
        )
        if len(orders) > 10:
            recent_text += f'<i>…and {len(orders)-10} more purchase(s).</i>\n'
    else:
        recent_text = '<i>No purchase history yet.</i>\n'
    username_line = ('@' + html.escape(username, quote=False)) if username != 'N/A' else 'N/A'
    profile = (
        '👤 <b>USER / RESELLER PROFILE</b>\n────────────────────────\n'
        f'├── 👤 <b>Name:</b> {html.escape(name, quote=False)}\n'
        f'├── 🔗 <b>Username:</b> {username_line}\n'
        f'├── 👑 <b>Account Type:</b> {role}\n'
        f'├── 🆔 <b>Telegram / Chat ID:</b> <code>{target_uid}</code>\n'
        f'├── 📞 <b>Phone:</b> <code>{html.escape(phone, quote=False)}</code>\n'
        f'├── 💰 <b>Current Balance:</b> ₹{balance:.2f} INR\n'
        f'├── 🎮 <b>Hacks Bought:</b> {orders_count}\n'
        f'├── 💎 <b>Total Spent on Hacks:</b> ₹{lifetime_spent:.2f} INR\n'
        f'├── 📥 <b>Total Deposited:</b> ₹{total_deposited:.2f} INR\n'
        f'├── 🏷️ <b>Discount:</b> {discount:.2f}%\n'
        f'├── 👥 <b>Referrals:</b> {referrals}\n'
        f'├── {verified}\n├── {banned}\n'
        f'└── 📅 <b>Joined:</b> {html.escape(joined, quote=False)}\n\n'
        '🛍️ <b>RECENT PURCHASES</b>\n' + recent_text
    )
    markup = types.InlineKeyboardMarkup(row_width=1)
    if len(user) > 11 and int(user[11] or 0) == 1:
        markup.add(types.InlineKeyboardButton('🔌 Generate / Send Reseller API', callback_data=f'resapi_generate_for_{target_uid}'))
    markup.add(types.InlineKeyboardButton('🔄 Refresh Profile', callback_data=f'admin_user_search_profile_{target_uid}'))
    markup.add(types.InlineKeyboardButton('🔎 Back to Search', callback_data='admin_user_reseller_search'))
    markup.add(types.InlineKeyboardButton('🔙 Users & Resellers', callback_data='admin_cat_users'))
    _admin_ui_send(call, profile, parse_mode='HTML', reply_markup=markup)

def _reseller_profile_back_markup(target_uid):
    markup=types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("🔄 Refresh Reseller Details", callback_data=f"admin_reseller_profile_{int(target_uid)}"))
    markup.add(types.InlineKeyboardButton("🔙 Back to Reseller List", callback_data="admin_reseller_list_0"))
    markup.add(types.InlineKeyboardButton("🔙 Users & Resellers", callback_data="admin_cat_users"))
    return markup

def _send_reseller_profile(call, target_uid):
    """Show detailed read-only information for one reseller."""
    try:
        target_uid = int(target_uid)
    except (TypeError, ValueError):
        bot.answer_callback_query(call.id, "❌ Invalid reseller ID.", show_alert=True)
        return

    u_info = get_user(target_uid)
    if not u_info or len(u_info) < 12 or int(u_info[11] or 0) != 1:
        bot.answer_callback_query(call.id, "❌ Reseller not found.", show_alert=True)
        _send_reseller_list(call, 0)
        return

    name = str(u_info[1] or 'Unnamed Reseller')
    phone = str(u_info[2] or 'N/A')
    balance = float(u_info[4] or 0.0)
    orders_count = int(u_info[6] or 0)
    lifetime_spent = float(u_info[7] or 0.0)
    total_deposited = float(u_info[8] or 0.0)
    joined = str(u_info[9] or 'N/A')
    verified = "✅ Verified" if int(u_info[10] or 0) else "⚪ Not Verified"
    banned = "🚫 Banned" if len(u_info) > 16 and int(u_info[16] or 0) else "🟢 Active"
    discount = float(u_info[12] or 0.0) if len(u_info) > 12 else 0.0
    referrals = int(u_info[14] or 0) if len(u_info) > 14 else 0

    orders = get_user_orders(target_uid)
    recent_text = ""
    if orders:
        for order in orders[:10]:
            recent_text += (
                f"• <code>{html.escape(str(order[0]))}</code> — "
                f"{html.escape(str(order[1]))} / {html.escape(str(order[2]))} — "
                f"₹{float(order[3] or 0):.2f}\n"
            )
        if len(orders) > 10:
            recent_text += f"<i>…and {len(orders) - 10} more purchase(s).</i>\n"
    else:
        recent_text = "<i>No purchase history yet.</i>\n"

    profile = (
        "👑 <b>RESELLER ACCOUNT DETAILS</b>\n"
        "────────────────────────\n"
        f"├── 👤 <b>Name:</b> {html.escape(name, quote=False)}\n"
        f"├── 🆔 <b>Telegram ID:</b> <code>{target_uid}</code>\n"
        f"├── 📞 <b>Phone:</b> <code>{html.escape(phone, quote=False)}</code>\n"
        f"├── 💰 <b>Current Balance:</b> ₹{balance:.2f} INR\n"
        f"├── 🛒 <b>Hacks Bought:</b> {orders_count}\n"
        f"├── 💎 <b>Total Spent:</b> ₹{lifetime_spent:.2f} INR\n"
        f"├── 📥 <b>Total Deposited:</b> ₹{total_deposited:.2f} INR\n"
        f"├── 🏷️ <b>Discount:</b> {discount:.2f}%\n"
        f"├── 👥 <b>Referrals:</b> {referrals}\n"
        f"├── {verified}\n"
        f"├── {banned}\n"
        f"└── 📅 <b>Joined:</b> {html.escape(joined, quote=False)}\n\n"
        "🛍️ <b>RECENT PURCHASES</b>\n"
        f"{recent_text}"
    )

    markup = types.InlineKeyboardMarkup(row_width=1)
    # Reseller API is attached directly to the selected reseller account.
    # This keeps the existing reseller list/profile flow intact while making
    # token generation a one-tap operation for the chosen reseller.
    markup.add(types.InlineKeyboardButton("🔌 Generate / Send Reseller API", callback_data=f"resapi_generate_for_{target_uid}"))
    markup.add(types.InlineKeyboardButton("🔄 Refresh Reseller Details", callback_data=f"admin_reseller_profile_{target_uid}"))
    markup.add(types.InlineKeyboardButton("🔙 Back to Reseller List", callback_data="admin_reseller_list_0"))
    markup.add(types.InlineKeyboardButton("🔙 Users & Resellers", callback_data="admin_cat_users"))
    _admin_ui_send(call, profile, parse_mode="HTML", reply_markup=markup)


def _admin_category_text(category):
    """Human-readable section header used by the reorganized Admin Panel."""
    meta = {
        "setup": ("⚡ PRODUCT & PLANS", "A clean Add → Hacks → Plans workflow for product management."),
        "api": ("🌐 API & SERVERS", "Manage server connections and product/API mappings."),
        "emoji": ("✨ USER PANEL UI", "Customize button colors, emoji and customer-facing controls."),
        "text": ("📝 TEXT & PRICE LIST", "Manage pricing display, labels and bot-facing text."),
        "users": ("👥 USERS & RESELLERS", "Manage users, balances, roles, discounts and coupons."),
        "tools": ("📢 BROADCAST & SUPPORT", "Manage broadcasts, guides, support and update links."),
        "system": ("⚙️ BOT & DATABASE", "Control bot state, credentials and database backups."),
    }
    title, subtitle = meta.get(
        str(category),
        ("🛠️ ADMIN SECTION", "Choose an operation below.")
    )
    return (
        f"<b>{title}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>{subtitle}</i>\n\n"
        "Select an operation:"
    )


def _product_hide_by_hash(value):
    for name in get_unique_products():
        if _ui_hash(name) == str(value):
            return name
    return None

def _product_hide_markup():
    m = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for name in get_unique_products():
        hidden = _product_hidden(name)
        plans = get_product_plans(name)
        hidden_plans = sum(1 for p in plans if _plan_hidden(p[0]))
        buttons.append(_admin_colorful_button(
            f"{'🙈' if hidden else '👁️'} {name}\n📦 {hidden_plans}/{len(plans)} hidden",
            callback_data=f'ph_product_{_ui_hash(name)}',
            color='red' if hidden else 'blue'
        ))
    for i in range(0, len(buttons), 2):
        m.row(*buttons[i:i+2])
    return _style_admin_markup(_ensure_admin_back_button(m))

def _product_visibility_markup(product_name):
    m = types.InlineKeyboardMarkup(row_width=2)
    hidden = _product_hidden(product_name)
    m.add(_admin_colorful_button(
        '👁️ Unhide Product' if hidden else '🙈 Hide Product',
        callback_data=f'ph_toggle_{_ui_hash(product_name)}',
        color='green' if hidden else 'red'
    ))
    for plan in get_product_plans(product_name):
        pid, days = int(plan[0]), str(plan[2])
        is_hidden = _plan_hidden(pid)
        m.add(_admin_colorful_button(
            f"{'👁️' if is_hidden else '🙈'} {'Unhide' if is_hidden else 'Hide'}\n📅 {days}",
            callback_data=f'ph_plan_{pid}',
            color='green' if is_hidden else 'red'
        ))
    m.add(_admin_colorful_button('🔙 Product Hide / Unhide', callback_data='admin_product_hide', color='blue'))
    return _style_admin_markup(_ensure_admin_back_button(m))

def _product_hide_screen(call):
    products = get_unique_products()
    hidden_count = sum(1 for n in products if _product_hidden(n))
    _admin_ui_send(call,
        '🙈 <b>PRODUCT HIDE / UNHIDE</b>\n━━━━━━━━━━━━━━━━━━━━\n\n'
        f'📦 <b>Products:</b> {len(products)}  ·  🔒 <b>Hidden:</b> {hidden_count}\n\n'
        'Tap a product to hide/unhide the whole product or manage each plan separately.\n'
        '<i>Hidden products/plans are omitted from the customer shop and reseller API catalog.</i>',
        parse_mode='HTML', reply_markup=_product_hide_markup())


def _product_plans_dashboard_markup():
    """Modern Product & Plans hub.

    The old five-button setup menu was visually noisy.  Keep every legacy
    feature reachable, but move daily product creation/management behind a
    simple Add + Hacks workflow.
    """
    markup = types.InlineKeyboardMarkup(row_width=2)
    # Keep the two primary Product & Plans actions paired; this is one of the
    # three Admin areas where the compact two-column design is intentional.
    add_button = make_ui_button(
        "➕ Add Product / Plan", callback_data="pp_add_product",
        button_key="admin:product_plans:add", default_color="green", force_style=True
    )
    markup.add(add_button)
    if get_unique_products():
        # Only show Hacks & Plans when there is actually a catalog to manage.
        markup.keyboard[-1].append(make_ui_button(
            "🎮 Hacks & Plans", callback_data="pp_hacks",
            button_key="admin:product_plans:hacks", default_color="blue", force_style=True
        ))
    return _style_admin_markup(_ensure_admin_back_button(markup))


def _product_plans_text():
    products = get_unique_products()
    count = len(products)
    return (
        "⚡ <b>PRODUCT &amp; PLANS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Create products cleanly, then manage every plan from one place.</i>\n\n"
        f"📦 <b>Hacks:</b> {count}\n"
        "🧭 <b>Workflow:</b> Add → Plans → Edit / Keys / Link / Position"
    )


def _pp_catalog_markup(user_id):
    products = get_unique_products()
    # Product selectors are intentionally the one Admin list that uses a
    # compact two-column grid: it is the main daily Product & Plans catalog and
    # the paired layout makes large catalogs much easier to scan on mobile.
    markup = types.InlineKeyboardMarkup(row_width=2)
    catalog = admin_temp_data.setdefault(int(user_id), {}).setdefault('pp_hack_catalog', {})
    catalog.clear()
    product_buttons = []
    for idx, name in enumerate(products, 1):
        h = _ui_hash(f"pp:{name}")
        catalog[h] = name
        plans = get_product_plans(name)
        product_buttons.append(types.InlineKeyboardButton(
            f"{idx:02d} 🎮 {name} · {len(plans)}",
            callback_data=f"pp_hack_{h}"
        ))
    for i in range(0, len(product_buttons), 2):
        markup.row(*product_buttons[i:i+2])
    markup.add(make_ui_button("➕ Add Product / Plan", callback_data="pp_add_product",
                              button_key="admin:product_plans:add", default_color="green", force_style=True))
    markup.add(make_ui_button("🧰 Advanced Product Tools", callback_data="pp_advanced",
                              button_key="admin:product_plans:advanced", default_color="blue", force_style=True))
    return _style_admin_markup(_ensure_admin_back_button(markup))


def _pp_selected_hack_screen(user_id, product_name):
    _pp_set_active_product(user_id, product_name)
    plans = get_product_plans(product_name)
    h = _ui_hash(f"pp:{product_name}")
    admin_temp_data.setdefault(int(user_id), {}).setdefault('pp_hack_catalog', {})[h] = product_name
    markup = types.InlineKeyboardMarkup(row_width=2)
    for plan in plans:
        markup.add(types.InlineKeyboardButton(
            f"📅 {plan[2]}  ·  ₹{plan[3]:.0f} / ₹{plan[4]:.0f}",
            callback_data=f"pp_plan_noop_{plan[0]}"
        ))
    markup.add(
        types.InlineKeyboardButton("➕ Add Plan", callback_data=f"pp_add_plan_same_{h}"),
        types.InlineKeyboardButton("✏️ Edit", callback_data=f"edit_hack_select_{_ui_hash(product_name)}"),
    )
    markup.add(types.InlineKeyboardButton("🔑 Add VIP Keys", callback_data=f"pp_add_key_{h}"))
    markup.add(
        types.InlineKeyboardButton("👁️ Check / Remove Keys", callback_data=f"pp_keys_{h}"),
        types.InlineKeyboardButton("🔗 Telegram Link", callback_data=f"pp_link_{h}"),
    )
    markup.add(types.InlineKeyboardButton("🔢 Set Position", callback_data=f"pp_position_{h}"))
    markup.add(types.InlineKeyboardButton("💰 Custom Price", callback_data=f"pp_custom_price_{h}"))
    markup.add(types.InlineKeyboardButton("🧰 More Hack Tools", callback_data=f"pp_more_{h}"))
    markup.add(types.InlineKeyboardButton("🎮 Back to Hacks", callback_data="pp_hacks"))
    return _style_admin_markup(_ensure_admin_back_button(markup))


def _pp_key_stock_view(user_id, product_name, h, prefix_text=None):
    """Build the selected-hack key stock screen without leaving the Product hub."""
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        rows = conn.execute(
            'SELECT id,validity_days,panel_key FROM panels WHERE panel_name=? AND is_sold=0 ORDER BY id ASC',
            (product_name,)
        ).fetchall()
    finally:
        conn.close()
    lines = [f"🔑 <b>KEY STOCK · {html.escape(str(product_name))}</b>", "━━━━━━━━━━━━━━━━━━━━"]
    if prefix_text:
        lines.extend(["", prefix_text])
    markup = types.InlineKeyboardMarkup(row_width=1)
    if not rows:
        lines.extend(["", "<i>No unused keys are currently available.</i>"])
    else:
        current = None
        for panel_id, days, key in rows:
            if str(days) != current:
                current = str(days)
                lines.append(f"\n📅 <b>{html.escape(current)}</b>")
            lines.append(f"└ 🔑 <code>{html.escape(str(key), quote=False)}</code>")
            markup.row(
                types.InlineKeyboardButton(f"✏️ Edit Key #{int(panel_id)}", callback_data=f"pp_key_edit_{int(panel_id)}_{h}"),
                types.InlineKeyboardButton("🗑 Remove", callback_data=f"pp_key_delete_{int(panel_id)}_{h}")
            )
        lines.append(f"\n📦 <b>Total:</b> {len(rows)}")
    markup.add(types.InlineKeyboardButton("🔄 Refresh", callback_data=f"pp_keys_{h}"))
    markup.add(types.InlineKeyboardButton("🎮 Back to Hack", callback_data=f"pp_hack_{h}"))
    return "\n".join(lines), _style_admin_markup(_ensure_admin_back_button(markup))


def _pp_custom_price_plan_markup(user_id, product_name, h):
    plans = get_product_plans(product_name)
    markup = types.InlineKeyboardMarkup(row_width=1)
    for plan in plans:
        pid, _, days, reg, res = plan[:5]
        custom = get_custom_plan_price(user_id, pid)
        suffix = " · 🟣 Custom" if custom["user_price"] is not None or custom["reseller_price"] is not None else ""
        markup.add(types.InlineKeyboardButton(
            f"📅 {days} · ₹{reg:.2f} / ₹{res:.2f}{suffix}",
            callback_data=f"pp_custom_price_plan_{pid}_{h}"
        ))
    markup.add(types.InlineKeyboardButton("🔙 Back to Hack", callback_data=f"pp_hack_{h}"))
    return _style_admin_markup(_ensure_admin_back_button(markup))


def step_custom_price_user_id(message):
    uid = message.from_user.id
    try:
        target = int((message.text or "").strip())
        if target <= 0: raise ValueError
    except ValueError:
        retry = bot.send_message(message.chat.id, "❌ <b>Invalid Telegram ID.</b> Send a numeric User/Chat ID:", parse_mode="HTML")
        bot.register_next_step_handler(retry, step_custom_price_user_id)
        return
    data = admin_temp_data.setdefault(uid, {})
    product_name = data.get("pp_custom_price_product"); h = data.get("pp_custom_price_hash")
    if not product_name or not h:
        bot.send_message(message.chat.id, "❌ Custom Price session expired. Open the selected Hack again.", parse_mode="HTML")
        return
    data["pp_custom_price_target"] = target
    fake = type("CustomPriceCall", (), {"message": message, "from_user": message.from_user, "data": "pp_custom_price_target"})()
    _admin_ui_send(
        fake,
        "💰 <b>CUSTOM PRICE — SELECT PLAN</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎮 <b>Product:</b> {html.escape(product_name)}\n"
        f"👤 <b>User ID:</b> <code>{target}</code>\n\n"
        "Select the plan whose price you want to customize.",
        parse_mode="HTML",
        reply_markup=_pp_custom_price_plan_markup(target, product_name, h)
    )


def step_save_custom_plan_price(message):
    uid = message.from_user.id; data = admin_temp_data.get(uid, {})
    target = data.get("pp_custom_price_target"); plan_id = data.get("pp_custom_price_plan_id")
    product_name = data.get("pp_custom_price_product")
    raw = (message.text or "").strip()
    try:
        parts = [x.strip() for x in raw.split("|")]
        if len(parts) != 2: raise ValueError
        def parse_side(v):
            if v.lower() in {"", "-", "none", "clear"}: return None
            val = float(v)
            if val < 0: raise ValueError
            return val
        up, rp = parse_side(parts[0]), parse_side(parts[1])
        set_custom_plan_price(target, plan_id, up, rp)
    except Exception:
        retry = bot.send_message(message.chat.id, "❌ <b>Invalid format.</b> Use <code>User_Price | Reseller_Price</code>\nExample: <code>500 | 350</code>\nUse <code>-</code> to clear an override.", parse_mode="HTML")
        bot.register_next_step_handler(retry, step_save_custom_plan_price)
        return
    plan = get_product_by_id(plan_id); custom = get_custom_plan_price(target, plan_id)
    h = data.get("pp_custom_price_hash")
    selected_product = str(product_name or _pp_active_product(uid) or '').strip()
    if selected_product:
        _pp_set_active_product(uid, selected_product)
    admin_temp_data.pop(uid, None)
    # The admin is still working inside the same selected hack. Return directly
    # to that hack instead of asking for the hack again or reopening a cleared
    # custom-price session.
    admin_pending_return[uid] = {
        "callback": "pp_hack_direct",
        "product_name": selected_product
    } if selected_product else ({"callback": "pp_hacks"})
    _admin_success_send(
        message.chat.id,
        "✅ <b>CUSTOM PRICE SAVED</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎮 <b>Product:</b> {html.escape(str(product_name))}\n"
        f"👤 <b>User ID:</b> <code>{int(target)}</code>\n"
        f"📅 <b>Plan:</b> {html.escape(str(plan[3] if plan else plan_id))}\n"
        f"💰 <b>User Price:</b> {'₹%.2f' % custom['user_price'] if custom['user_price'] is not None else 'Standard'}\n"
        f"💎 <b>Reseller Price:</b> {'₹%.2f' % custom['reseller_price'] if custom['reseller_price'] is not None else 'Standard'}",
        parse_mode="HTML"
    )


def _pp_advanced_markup():
    markup = types.InlineKeyboardMarkup(row_width=2)
    items = [
        ("🔄 Reorder Hacks", "admin_reorder_hacks"),
        ("🔗 Set Telegram Group", "admin_set_tg_group"),
        ("🗑️ Remove Entire Hack", "admin_del_hack"),
        ("❌ Remove Day / Plan", "admin_del_plan"),
        ("📦 Stock On / Off", "admin_stock_mgmt"),
        ("📱 Device ID", "admin_device_id_mgmt"),
        ("⚡ Quick Setup", "admin_quick_setup"),
        ("💰 Edit Product Prices", "admin_edit_price"),
    ]
    for i in range(0, len(items), 2):
        markup.row(*(types.InlineKeyboardButton(label, callback_data=cb) for label, cb in items[i:i+2]))
    markup.add(types.InlineKeyboardButton("🔙 Product & Plans", callback_data="admin_cat_setup"))
    return _style_admin_markup(_ensure_admin_back_button(markup, label="🔙 Product & Plans", callback_data="admin_cat_setup"))


def _admin_category_markup(category):
    groups = {
        'setup': [],
        'api': [
            ("9️⃣ 9X API System", "ninex_api_system"),
            ("🟢 TobiX API System", "tobix_api_system"),
            ("🆕 New Server API System", "new_server_api"),
            ("🤝 Reseller API System", "resapi_admin"),
            ("🔗 RG API System", "rg_api_system"),
        ],
        'emoji': [
            ("🎨 Button Colors", "admin_button_colors"),
            ("✏️ User Panel Names & Emoji", "admin_button_cust"),
            ("✨ Premium Emoji Editor", "admin_emoji_editor"),
            ("✨ All Button Emoji", "admin_all_button_emoji"),
            ("✨ All Product Button Emoji", "admin_all_product_emoji"),
            ("💰 All Price List Button Emoji", "admin_all_price_emoji"),
        ],
        'text': [
            ("🧩 Price List Fix — Emoji & Text", "admin_hack_price_ui"),
            ("✨ User Panel Premium Mode", "admin_toggle_price_list_mode"),
            ("✏️ Edit Bot Texts", "admin_text_editor"),
        ],
        'users': [
            ("🔎 User & Reseller Search", "admin_user_reseller_search"),
            ("👤 User List & Purchase Tracking", "admin_track_users"),
            ("👑 Reseller List & Accounts", "admin_reseller_list"),
            ("💰 Manage User Balance", "admin_manage_bal"),
            ("🚫 User Ban & Unban", "admin_user_ban_unban"),
            ("👑 Add / Remove Reseller Role", "admin_manage_reseller"),
            ("👑 Reseller Discount / Paid Access", "admin_reseller_discount"),
            ("🎟️ Create Coupon", "admin_create_coupon"),
            ("🏷️ Manage Discounts", "admin_manage_discounts"),
            ("🧹 Reset All Users & Resellers", "admin_reset_all_users"),
            ("♻️ Restore User Data", "admin_restore_all_users"),
        ],
        'tools': [
            ("📢 Multimedia Broadcast", "admin_broadcast"),
            ("🎬 How To Use Guide Link", "admin_set_guide"),
            ("🛟 Support Settings", "admin_support_settings"),
            ("📢 All File Update Link", "admin_update_link"),
        ],
        'system': [
            ("🔐 Bot On & Off", "admin_bot_toggle"),
            ("🔑 Change Bot API Token", "admin_change_bot_token"),
            ("📥 Backup Bot Backup Download", "admin_db_backup_download"),
            ("💾 Bots & Backups Center", "admin_db_backup"),
        ],
    }
    if category == "setup":
        return _product_plans_dashboard_markup()
    markup = types.InlineKeyboardMarkup(row_width=2)
    items = groups.get(category, [])
    for i in range(0, len(items), 2):
        pair = items[i:i+2]
        markup.row(*(make_ui_button(label, callback_data=cb,
                                    button_key=f"admin:inner:{cb}",
                                    default_color="blue", force_style=True)
                     for label, cb in pair))
    # System/Database is opened inside the existing Admin Panel message so the
    # old Admin Panel does not remain visible underneath it. Other categories keep
    # their existing navigation callback unchanged.
    back_callback = "admin_back_main"
    markup.add(make_ui_button("🔙 Main Admin Panel", callback_data=back_callback,
                              button_key="admin:navigation:back",
                              default_color="red", force_style=True))
    return _style_admin_markup(markup)

# ==================== PAYMENT GATEWAY & ADMIN MANAGEMENT ====================
# FamPay setup uses an explicit per-admin state machine. The old callback tried
# to reference a missing step_save_fam_upi function, which raised NameError as
# soon as the UPI ID was submitted. Keeping the setup state in admin_temp_data
# also prevents Telegram next-step timing from making the panel look frozen.
_FAMP_SETUP_LOCKS = {}
_FAMP_SETUP_LOCKS_GUARD = threading.RLock()

def _famp_setup_lock(user_id):
    uid = int(user_id)
    with _FAMP_SETUP_LOCKS_GUARD:
        return _FAMP_SETUP_LOCKS.setdefault(uid, threading.RLock())

def _start_famp_setup(chat_id, user_id):
    if not _is_admin(user_id):
        return
    with _famp_setup_lock(user_id):
        admin_temp_data[int(user_id)] = {
            'famp_setup_stage': 'api_key',
            'gw_upi': 'ZYVOPAY',
            'gw_api_key': '',
        }
    bot.send_message(
        chat_id,
        '💳 <b>FAMPAY GATEWAY (ZYVO PAY)</b>\n\n🔐 <b>Paste the complete ZYVO PAY API token</b> (the full <code>public.secret</code> value from your ZYVO PAY dashboard).\n\n<i>Only the token is needed. The token is stored privately and the bot verifies the connection automatically. Send /cancel to stop.</i>',
        parse_mode='HTML'
    )

@bot.message_handler(func=lambda message: bool(
    getattr(message, 'from_user', None) and
    _is_admin(message.from_user.id) and
    isinstance(admin_temp_data.get(int(message.from_user.id)), dict) and
    admin_temp_data.get(int(message.from_user.id), {}).get('famp_setup_stage')
))
def _handle_famp_setup_message(message):
    uid = int(message.from_user.id)
    chat_id = message.chat.id
    text = (message.text or '').strip()
    command = text.split()[0].lower() if text else ''

    if command in {'/cancel', '/admin', '/start'}:
        admin_temp_data.pop(uid, None)
        try:
            bot.clear_step_handler_by_chat_id(chat_id)
        except Exception:
            pass
        if command == '/cancel':
            bot.send_message(chat_id, '✅ <b>FAMP Gateway setup cancelled.</b>', parse_mode='HTML')
            try:
                admin_panel(message)
            except Exception:
                pass
        elif command == '/admin':
            try:
                admin_panel(message)
            except Exception:
                pass
        else:
            try:
                send_welcome(message)
            except Exception:
                pass
        return

    if not text:
        bot.send_message(chat_id, '❌ Please send the requested FAMP value as text.')
        return

    lock = _famp_setup_lock(uid)
    with lock:
        state = admin_temp_data.get(uid)
        if not isinstance(state, dict):
            return
        stage = str(state.get('famp_setup_stage') or '')

        if stage == 'upi':
            if '@' not in text or len(text) > 128 or ' ' in text:
                bot.send_message(chat_id, '❌ Invalid FAMP UPI ID. Send the UPI ID again.')
                return
            state['gw_upi'] = text
            state['famp_setup_stage'] = 'api_key'
            bot.send_message(
                chat_id,
                '🔐 <b>Enter FAMP API Token:</b>\n\n<i>After the token is saved, the bot will verify the API connection automatically.</i>',
                parse_mode='HTML'
            )
            return

        if stage == 'api_key':
            if len(text) < 8 or len(text) > 512:
                bot.send_message(chat_id, '❌ Invalid API token length. Send the real ZYVO PAY API token again.')
                return
            try:
                _zyvopay_signing_key(text)
            except Exception:
                bot.send_message(chat_id, '❌ Token format is invalid. Paste the complete <code>public.secret</code> token from ZYVO PAY.', parse_mode='HTML')
                return
            try:
                bot.delete_message(chat_id, message.message_id)  # do not leave the secret in chat history
            except Exception:
                pass

            upi = 'ZYVOPAY'
            state['gw_api_key'] = text
            try:
                # Save first so a successful connection check and a process
                # restart both see exactly the same credentials.
                _save_gateway('fam', upi, text, text)
                admin_temp_data.pop(uid, None)
                bot.send_message(
                    chat_id,
                    '⏳ <b>ZYVO PAY API Token Saved.</b>\n\nChecking API connection now...',
                    parse_mode='HTML'
                )

                def _famp_connection_worker():
                    ok, detail = _check_fam_connection()
                    try:
                        bot.send_message(
                            chat_id,
                            ('✅' if ok else '❌') +
                            f' <b>FAMP Connection {"Successful" if ok else "Failed"}</b>\n\n'
                            f'<code>{html.escape(str(detail))}</code>',
                            parse_mode='HTML',
                            reply_markup=_gateway_manager_markup(),
                        )
                    except Exception as exc:
                        print(f'[FAMP CONNECTION UI ERROR] {exc}')

                _run_user_task_async(_famp_connection_worker)
            except Exception as exc:
                admin_temp_data.pop(uid, None)
                _set_gateway_connected('fam', False)
                bot.send_message(
                    chat_id,
                    f'❌ <b>FAMP save failed.</b>\n\n<code>{html.escape(str(exc)[:700])}</code>',
                    parse_mode='HTML',
                    reply_markup=_gateway_manager_markup(),
                )
            return

        admin_temp_data.pop(uid, None)

# PayTM setup uses an explicit per-admin state machine instead of depending only
# on chained next-step handlers. This prevents the exact 'UPI entered -> frozen
# -> next credential never requested' failure when Telegram/client timing is
# unusual. Existing step_* functions remain below for backward compatibility.
_PAYTM_SETUP_LOCKS = {}
_PAYTM_SETUP_LOCKS_GUARD = threading.RLock()

def _paytm_setup_lock(user_id):
    uid = int(user_id)
    with _PAYTM_SETUP_LOCKS_GUARD:
        return _PAYTM_SETUP_LOCKS.setdefault(uid, threading.RLock())

def _start_paytm_setup(chat_id, user_id):
    if not _is_admin(user_id): return
    with _paytm_setup_lock(user_id):
        admin_temp_data[int(user_id)] = {'paytm_setup_stage':'upi','gw_upi':'','gw_merchant_key':''}
    bot.send_message(chat_id, '💳 <b>PAYTM / ZYVO PAY GATEWAY</b>\n\nEnter the UPI ID configured in your ZYVO PAY merchant dashboard:', parse_mode='HTML')

@bot.message_handler(func=lambda message: bool(
    getattr(message, 'from_user', None) and _is_admin(message.from_user.id) and
    isinstance(admin_temp_data.get(int(message.from_user.id)), dict) and
    admin_temp_data.get(int(message.from_user.id), {}).get('paytm_setup_stage')
))
def _handle_paytm_setup_message(message):
    uid=int(message.from_user.id); chat_id=message.chat.id; text=(message.text or '').strip()
    command=text.split()[0].lower() if text else ''
    if command in {'/cancel','/admin','/start'}:
        admin_temp_data.pop(uid,None)
        try: bot.clear_step_handler_by_chat_id(chat_id)
        except Exception: pass
        if command=='/cancel': bot.send_message(chat_id,'✅ <b>Gateway setup cancelled.</b>',parse_mode='HTML')
        elif command=='/admin':
            try: admin_panel(message)
            except Exception: pass
        else:
            try: send_welcome(message)
            except Exception: pass
        return
    if not text:
        bot.send_message(chat_id,'❌ Please send text.'); return
    with _paytm_setup_lock(uid):
        state=admin_temp_data.get(uid)
        if not isinstance(state,dict): return
        stage=state.get('paytm_setup_stage')
        if stage=='upi':
            if '@' not in text or len(text)>128:
                bot.send_message(chat_id,'❌ Invalid UPI ID. Send it again.'); return
            state['gw_upi']=text; state['paytm_setup_stage']='token'
            bot.send_message(chat_id,'🔐 <b>Paste the complete ZYVO PAY API token</b> (the full <code>public.secret</code> value from the dashboard).\n\nThe token is stored privately in the bot database and never shown back.',parse_mode='HTML')
            return
        if stage=='token':
            if '.' not in text or len(text)>512 or not all(text.split('.',1)):
                bot.send_message(chat_id,'❌ Token format is invalid. Paste the complete public.secret token from ZYVO PAY.'); return
            upi=state.get('gw_upi','')
            try:
                # Keep token in the existing encrypted/DB-backed gateway credential field; MID column is not used.
                _save_gateway('paytm',upi,'ZYVOPAY',text)
                admin_temp_data.pop(uid,None)
                bot.send_message(chat_id,'💾 <b>ZYVO PAY credentials saved.</b>\n\nNext, tap <b>Check PayTM Connection</b> to validate the token, then turn the gateway ON. The existing PayTM menu now uses ZYVO PAY API; FamPay remains separate.',parse_mode='HTML',reply_markup=_gateway_manager_markup())
            except Exception:
                admin_temp_data.pop(uid,None)
                bot.send_message(chat_id,'❌ Could not save gateway settings. Please try again.')


def _gateway_manager_markup():
    active=_get_active_payment_gateway()
    m=types.InlineKeyboardMarkup(row_width=2)
    # Clean three-row gateway grid: FamPay on the left, PayTM on the right.
    # Pending Payments and Back stay full-width below the grid.
    m.row(
        make_ui_button(f"{'🟢' if active=='fam' else '⚪'} FamPay Gateway\n{_gateway_status_line('fam')}", callback_data='gw_edit_fam', button_key='admin:gateway:fam_edit', default_color='blue', force_style=True),
        make_ui_button(f"{'🟢' if active=='paytm' else '⚪'} PayTM Gateway\n{_gateway_status_line('paytm')}", callback_data='gw_edit_paytm', button_key='admin:gateway:paytm_edit', default_color='blue', force_style=True),
    )
    m.row(
        make_ui_button('🔍 Check FamPay\nConnection', callback_data='gw_check_fam', button_key='admin:gateway:fam_check', default_color='blue', force_style=True),
        make_ui_button('🔍 Check PayTM\nConnection', callback_data='gw_check_paytm', button_key='admin:gateway:paytm_check', default_color='blue', force_style=True),
    )
    m.row(
        make_ui_button('🔘 FamPay System\n'+('ON' if active=='fam' else 'OFF'), callback_data='gw_toggle_fam', button_key='admin:gateway:fam_toggle', default_color='green' if active=='fam' else 'red', force_style=True),
        make_ui_button('🔘 PayTM System\n'+('ON' if active=='paytm' else 'OFF'), callback_data='gw_toggle_paytm', button_key='admin:gateway:paytm_toggle', default_color='green' if active=='paytm' else 'red', force_style=True),
    )
    m.row(make_ui_button('⏳ Pending Payments', callback_data='admin_view_pending_payments', button_key='admin:gateway:pending', default_color='blue', force_style=True))
    m.row(make_ui_button('🔙 Main Admin Panel', callback_data='admin_back_main', button_key='admin:navigation:back', default_color='red', force_style=True))
    return m

def _send_gateway_manager(chat_id,message_id=None):
    active=_get_active_payment_gateway(); label={'fam':'FAMPAY','paytm':'PAYTM'}.get(active,'None')
    text=f"💳 <b>PAYMENT GATEWAYS</b>\n\n⚡ <b>Active Gateway:</b> {label}\nFamPay and PayTM are stored independently. Only the gateway explicitly switched ON is used for new payments.\nFamPay button: paste only the ZYVO PAY API token. PayTM menu is also connected to ZYVO PAY; save UPI ID + API token and verify the connection."
    markup=_gateway_manager_markup()
    if message_id:
        try: return bot.edit_message_text(text,chat_id=chat_id,message_id=message_id,parse_mode='HTML',reply_markup=markup)
        except Exception: pass
    return bot.send_message(chat_id,text,parse_mode='HTML',reply_markup=markup)
def step_save_paytm_upi(message):
    uid=message.from_user.id
    if not _is_admin(uid): return
    upi=(message.text or '').strip()
    if not upi or '@' not in upi:
        m=bot.send_message(message.chat.id,'❌ Invalid PayTM UPI ID. Send the UPI ID again.'); bot.register_next_step_handler(m,step_save_paytm_upi); return
    admin_temp_data.setdefault(uid,{})['gw_upi']=upi
    m=bot.send_message(message.chat.id,'🆔 <b>Enter PayTM Merchant ID (MID):</b>',parse_mode='HTML'); bot.register_next_step_handler(m,step_save_paytm_merchant)

def step_save_paytm_merchant(message):
    uid=message.from_user.id; d=admin_temp_data.get(uid,{})
    mid=(message.text or '').strip()
    if not mid or not d.get('gw_upi'):
        m=bot.send_message(message.chat.id,'❌ Merchant ID cannot be empty.'); bot.register_next_step_handler(m,step_save_paytm_merchant); return
    d['gw_merchant_id']=mid
    m=bot.send_message(message.chat.id,'🔐 <b>Enter PayTM Merchant Key:</b>',parse_mode='HTML'); bot.register_next_step_handler(m,step_save_paytm_merchant_key)

def step_save_paytm_merchant_key(message):
    uid=message.from_user.id; d=admin_temp_data.get(uid,{})
    key=(message.text or '').strip()
    if not key or not d.get('gw_upi') or not d.get('gw_merchant_id'):
        m=bot.send_message(message.chat.id,'❌ Merchant Key cannot be empty.'); bot.register_next_step_handler(m,step_save_paytm_merchant_key); return
    d['gw_merchant_key']=key
    m=bot.send_message(message.chat.id,'🖥️ <b>Enter PayTM POS ID:</b>\n\nRequired for Dynamic QR.',parse_mode='HTML'); bot.register_next_step_handler(m,step_save_paytm_pos_id)

def step_save_paytm_pos_id(message):
    uid=message.from_user.id; d=admin_temp_data.get(uid,{})
    pos=(message.text or '').strip()
    if not pos or not d.get('gw_upi') or not d.get('gw_merchant_id') or not d.get('gw_merchant_key'):
        m=bot.send_message(message.chat.id,'❌ POS ID cannot be empty.'); bot.register_next_step_handler(m,step_save_paytm_pos_id); return
    d['gw_pos_id']=pos
    m=bot.send_message(message.chat.id,'🧩 <b>Enter PayTM Client ID:</b>\n\nStandard accounts may use <code>C11</code>.',parse_mode='HTML'); bot.register_next_step_handler(m,step_save_paytm_client_id)

def step_save_paytm_client_id(message):
    uid=message.from_user.id; d=admin_temp_data.get(uid,{})
    client=(message.text or '').strip()
    if client.upper()=='SKIP': client=str(get_setting('paytm_client_id') or PAYTM_DEFAULT_CLIENT_ID).strip() or 'C11'
    if not client or not d.get('gw_upi') or not d.get('gw_merchant_id') or not d.get('gw_merchant_key') or not d.get('gw_pos_id'):
        m=bot.send_message(message.chat.id,'❌ Client ID cannot be empty.'); bot.register_next_step_handler(m,step_save_paytm_client_id); return
    _save_gateway('paytm',d['gw_upi'],d['gw_merchant_id'],d['gw_merchant_key'])
    set_setting('paytm_pos_id',d['gw_pos_id']); set_setting('paytm_client_id',client); admin_temp_data.pop(uid,None)
    bot.send_message(message.chat.id,'💾 <b>PayTM Gateway Saved.</b>\n\nPayTM remains <b>OFF</b> until you check the connection and explicitly turn it ON.',parse_mode='HTML',reply_markup=_gateway_manager_markup())

def _gateway_toggle(chat_id,gateway):
    gateway=str(gateway).lower().strip(); row=_gateway_row(gateway)
    if not row or not row[1] or not row[2]:
        bot.send_message(chat_id,f'❌ <b>{gateway.upper()} is not configured.</b>',parse_mode='HTML'); return
    if not int(row[4] or 0):
        bot.send_message(chat_id,f'❌ <b>{gateway.upper()} is not connected.</b> Use Check Connection first.',parse_mode='HTML'); return
    if gateway=='paytm':
        ready=_paytm_payment_config_error()
        if ready:
            bot.send_message(chat_id,'❌ <b>PayTM cannot be turned ON yet.</b>\n\n'+html.escape(ready),parse_mode='HTML'); return
    if _get_active_payment_gateway()==gateway:
        set_setting('active_payment_gateway',''); bot.send_message(chat_id,f'⚪ <b>{gateway.upper()} System OFF.</b>',parse_mode='HTML')
    else:
        if not _set_active_payment_gateway(gateway):
            bot.send_message(chat_id,f'❌ <b>{gateway.upper()} could not be activated.</b>',parse_mode='HTML'); return
        bot.send_message(chat_id,f'🟢 <b>{gateway.upper()} System ON.</b> The other gateway is automatically OFF.',parse_mode='HTML')
    _send_gateway_manager(chat_id)


# ==================== ADMIN SETTINGS INPUT HANDLERS ====================
def step_save_support_tg(message):
    uid = message.from_user.id
    if not _is_admin(uid):
        return
    value = (message.text or '').strip().lstrip('@')
    if not value:
        m = bot.send_message(message.chat.id, "❌ <b>Telegram Support ID cannot be empty.</b> Send the username/ID again.", parse_mode='HTML')
        bot.register_next_step_handler(m, step_save_support_tg)
        return
    set_setting(TELEGRAM_SUPPORT_ID_KEY, value)
    admin_temp_data.pop(uid, None)
    bot.send_message(message.chat.id, "✅ <b>Telegram Support ID updated successfully.</b>", parse_mode='HTML', reply_markup=_support_settings_markup())


def step_save_support_wa(message):
    uid = message.from_user.id
    if not _is_admin(uid):
        return
    value = re.sub(r'\D', '', (message.text or ''))
    if len(value) < 8:
        m = bot.send_message(message.chat.id, "❌ <b>Invalid WhatsApp number.</b> Send the full number with country code.", parse_mode='HTML')
        bot.register_next_step_handler(m, step_save_support_wa)
        return
    set_setting(WHATSAPP_SUPPORT_NUMBER_KEY, value)
    admin_temp_data.pop(uid, None)
    bot.send_message(message.chat.id, "✅ <b>WhatsApp Support Number updated successfully.</b>", parse_mode='HTML', reply_markup=_support_settings_markup())


def step_save_update_channel_link(message):
    uid = message.from_user.id
    if not _is_admin(uid):
        return
    value = (message.text or '').strip()
    if not re.match(r'^https?://', value, re.I):
        m = bot.send_message(message.chat.id, "❌ <b>Invalid link.</b> Send a complete http:// or https:// channel link.", parse_mode='HTML')
        bot.register_next_step_handler(m, step_save_update_channel_link)
        return
    set_setting(UPDATE_CHANNEL_LINK_KEY, value)
    admin_temp_data.pop(uid, None)
    back_markup = types.InlineKeyboardMarkup()
    back_markup.add(types.InlineKeyboardButton('🔙 Main Admin Panel', callback_data='admin_back_main'))
    bot.send_message(message.chat.id, "✅ <b>All File Update Link updated successfully.</b>", parse_mode='HTML', reply_markup=back_markup)


def step_get_user_ban_id(message):
    uid = message.from_user.id
    if not _is_admin(uid):
        return
    try:
        target = int((message.text or '').strip())
        if target <= 0:
            raise ValueError
    except ValueError:
        m = bot.send_message(message.chat.id, "❌ <b>Invalid Telegram ID.</b> Send a numeric Telegram User ID.", parse_mode='HTML')
        bot.register_next_step_handler(m, step_get_user_ban_id)
        return
    admin_temp_data.pop(uid, None)
    banned = is_user_banned(target)
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        types.InlineKeyboardButton('🚫 Ban User', callback_data=f'user_ban_action_1_{target}'),
        types.InlineKeyboardButton('✅ Unban User', callback_data=f'user_ban_action_0_{target}')
    )
    m.add(types.InlineKeyboardButton('🔙 Main Admin Panel', callback_data='admin_back_main'))
    bot.send_message(
        message.chat.id,
        f"👤 <b>USER ACCESS CONTROL</b>\n\n"
        f"🆔 Telegram ID: <code>{target}</code>\n"
        f"📌 Current Status: {'🚫 BANNED' if banned else '🟢 ACTIVE'}\n\n"
        "Choose the action:",
        parse_mode='HTML', reply_markup=m
    )


def step_save_hack_rename(message):
    uid = message.from_user.id
    data = admin_temp_data.get(uid, {})
    old_name = data.get('edit_hack_name')
    new_name = (message.text or '').strip()
    if not old_name:
        admin_temp_data.pop(uid, None)
        bot.send_message(message.chat.id, '❌ Edit session expired. Open Manage Hacks & Plans again.', parse_mode='HTML')
        return
    ok, detail = update_product_name_db(old_name, new_name)
    if ok:
        bot.send_message(message.chat.id, f"✅ <b>Hack name updated.</b>\n\nOld: <code>{html.escape(old_name)}</code>\nNew: <code>{html.escape(new_name)}</code>", parse_mode='HTML')
    else:
        m = bot.send_message(message.chat.id, f"❌ <b>{html.escape(detail)}</b>\n\nEnter a different hack name:", parse_mode='HTML')
        bot.register_next_step_handler(m, step_save_hack_rename)
        return
    admin_temp_data.pop(uid, None)


def step_save_hack_days_edit(message):
    uid = message.from_user.id
    plan_id = admin_temp_data.get(uid, {}).get('edit_plan_id')
    new_days = (message.text or '').strip()
    if not plan_id or not new_days:
        m = bot.send_message(message.chat.id, '❌ <b>Plan duration cannot be empty.</b> Enter it again.', parse_mode='HTML')
        bot.register_next_step_handler(m, step_save_hack_days_edit)
        return
    update_product_plan_days_db(plan_id, new_days)
    admin_temp_data.pop(uid, None)
    _admin_success_send(message.chat.id, f"✅ <b>Plan duration updated.</b>\n\n📅 New Duration: <code>{html.escape(new_days)}</code>", parse_mode='HTML')


def step_edit_manual_key(message):
    uid = message.from_user.id; data = admin_temp_data.get(uid, {})
    panel_id = data.get("pp_edit_key_id"); raw = (message.text or "").strip()
    if not panel_id or not raw or any(ch.isspace() for ch in raw):
        retry = bot.send_message(message.chat.id, "❌ Send exactly one non-empty key without spaces:", parse_mode="HTML")
        bot.register_next_step_handler(retry, step_edit_manual_key); return
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        dup = conn.execute("SELECT 1 FROM panels WHERE panel_key=? AND id<>? LIMIT 1", (raw, int(panel_id))).fetchone()
        if dup:
            retry = bot.send_message(message.chat.id, "❌ That key already exists. Send a different key:", parse_mode="HTML")
            bot.register_next_step_handler(retry, step_edit_manual_key); return
        conn.execute("UPDATE panels SET panel_key=? WHERE id=? AND is_sold=0", (raw, int(panel_id))); conn.commit()
    finally: conn.close()
    product_name = data.get("pp_edit_key_product", ""); days = data.get("pp_edit_key_days", "")
    admin_temp_data.pop(uid, None)
    _admin_success_send(message.chat.id, f"✅ <b>VIP Key Updated Successfully</b>\n\n🎮 <b>Product:</b> {html.escape(str(product_name))}\n📅 <b>Plan:</b> {html.escape(str(days))}\n🔑 <b>New Key:</b> <code>{html.escape(raw, quote=False)}</code>", parse_mode="HTML")


def step_edit_manual_key_legacy(message):
    uid = message.from_user.id; data = admin_temp_data.get(uid, {})
    panel_id = data.get("manual_edit_key_id"); raw = (message.text or "").strip()
    if not panel_id or not raw or any(ch.isspace() for ch in raw):
        retry = bot.send_message(message.chat.id, "❌ Send exactly one non-empty key without spaces:", parse_mode="HTML")
        bot.register_next_step_handler(retry, step_edit_manual_key_legacy); return
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        dup = conn.execute("SELECT 1 FROM panels WHERE panel_key=? AND id<>? LIMIT 1", (raw, int(panel_id))).fetchone()
        if dup:
            retry = bot.send_message(message.chat.id, "❌ That key already exists. Send a different key:", parse_mode="HTML")
            bot.register_next_step_handler(retry, step_edit_manual_key_legacy); return
        conn.execute("UPDATE panels SET panel_key=? WHERE id=? AND is_sold=0", (raw, int(panel_id))); conn.commit()
    finally: conn.close()
    product_name = data.get("manual_edit_key_product", ""); days = data.get("manual_edit_key_days", "")
    admin_temp_data.pop(uid, None)
    _admin_success_send(message.chat.id, f"✅ <b>Manual VIP Key Updated</b>\n\n🎮 <b>Product:</b> {html.escape(str(product_name))}\n📅 <b>Plan:</b> {html.escape(str(days))}\n🔑 <b>New Key:</b> <code>{html.escape(raw, quote=False)}</code>", parse_mode="HTML")


def step_save_existing_hack_price(message):
    uid = message.from_user.id
    plan_id = admin_temp_data.get(uid, {}).get('edit_plan_id')
    try:
        parts = [x.strip() for x in (message.text or '').split('|')]
        if len(parts) != 2:
            raise ValueError
        user_price = float(parts[0])
        reseller_price = float(parts[1])
        if user_price < 0 or reseller_price < 0:
            raise ValueError
    except ValueError:
        m = bot.send_message(message.chat.id, '❌ <b>Invalid format.</b> Use: <code>User_Price | Reseller_Price</code>', parse_mode='HTML')
        bot.register_next_step_handler(m, step_save_existing_hack_price)
        return
    update_product_price_db(plan_id, user_price, reseller_price)
    admin_temp_data.pop(uid, None)
    _admin_success_send(message.chat.id, f"✅ <b>Existing hack price updated.</b>\n\n💰 User: ₹{user_price:.2f}\n💎 Reseller: ₹{reseller_price:.2f}", parse_mode='HTML')


# ==================== STEP-BY-STEP ADMIN HANDLERS ====================

def step_process_user_reset(message):
    try:
        target_uid = int(message.text.strip())
        success = reset_user_completely_db(target_uid)
        if success:
            try:
                bot.send_message(target_uid, "⚠️ <b>Your account has been reset by the Admin.</b>\nPlease send /start to re-verify your phone number and restart.", parse_mode="HTML")
            except Exception:
                pass
            bot.send_message(message.chat.id, f"✅ <b>User Reset Successful!</b>\n\nTelegram ID: <code>{target_uid}</code> has been completely reset. When they send /start, they will need to re-verify their phone number from the beginning.", parse_mode="HTML")
        else:
            bot.send_message(message.chat.id, f"⚠️ User ID <code>{target_uid}</code> was not found in database or already reset.", parse_mode="HTML")
    except ValueError:
        msg = bot.send_message(message.chat.id, "❌ <b>Invalid ID!</b> Please send numeric Telegram User ID:")
        bot.register_next_step_handler(msg, step_process_user_reset)

def step_edit_product_price(message):
    user_id = message.from_user.id
    try:
        prices = [p.strip() for p in message.text.strip().split('|')]
        if len(prices) != 2:
            raise ValueError
        new_price, new_resell_price = float(prices[0]), float(prices[1])
        plan_id = admin_temp_data[user_id]['plan_id']
        update_product_price_db(plan_id, new_price, new_resell_price)
        _admin_success_send(message.chat.id, f"✅ <b>Price Updated Successfully!</b>\n\n💰 <b>New Regular Price:</b> ₹{new_price:.2f} INR\n💎 <b>New Reseller Price:</b> ₹{new_resell_price:.2f} INR", parse_mode="HTML")
        del admin_temp_data[user_id]
    except Exception:
        msg = bot.send_message(message.chat.id, "❌ <b>Format Error!</b> Enter price in format: <code>User_Price | Reseller_Price</code>\nExample: <code>200 | 150</code>")
        bot.register_next_step_handler(msg, step_edit_product_price)

def step_quick_setup(message):
    text = message.text.strip()
    try:
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        if len(lines) < 2:
            raise ValueError
            
        pid_id, hack_name = lines[0].split('|')
        pid_id, hack_name = pid_id.strip(), hack_name.strip()

        count = 0
        for line in lines[1:]:
            parts = line.split('|')
            if len(parts) == 4:
                days, server_dur, u_price, r_price = [p.strip() for p in parts]
                add_product_db(hack_name, pid_id, days, float(u_price), float(r_price), is_manual=0, remote_duration=server_dur)
                count += 1

        bot.send_message(message.chat.id, f"✅ <b>Quick Setup Completed!</b>\n\n🎮 <b>Hack:</b> {hack_name}\n🆔 <b>Product ID:</b> <code>{pid_id}</code>\n📦 <b>Plans Added:</b> {count}", parse_mode="HTML")
    except Exception:
        msg = bot.send_message(message.chat.id, "❌ <b>Format Error!</b> Please follow exact format:\n\n<code>Product_ID | Hack Name\n1 Hours | 1 Hours | 100 | 80\n1 DaYs | 1 DaYs | 500 | 400</code>")
        bot.register_next_step_handler(msg, step_quick_setup)

def step_set_tg_group_link(message):
    user_id = message.from_user.id
    p_name = admin_temp_data[user_id]['hack_name']
    group_link = message.text.strip()
    set_hack_tg_group(p_name, group_link)
    pp_active = admin_temp_data.get(user_id, {}).get('pp_active_hack')
    if pp_active:
        h = _ui_hash(f"pp:{pp_active}")
        admin_temp_data.setdefault(user_id, {}).setdefault('pp_hack_catalog', {})[h] = pp_active
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🎮 Back to Hack", callback_data=f"pp_hack_{h}"),
            types.InlineKeyboardButton("🔗 Change Link", callback_data=f"pp_link_{h}"),
        )
        markup.add(types.InlineKeyboardButton("🎮 Hacks & Plans", callback_data="pp_hacks"))
        markup.add(types.InlineKeyboardButton("🔙 Product & Plans", callback_data="admin_cat_setup"))
        bot.send_message(message.chat.id, f"✅ <b>TELEGRAM LINK SAVED</b>\n━━━━━━━━━━━━━━━━━━━━\n🎮 <b>Hack:</b> {html.escape(str(p_name))}\n🔗 <b>Link:</b> {html.escape(str(group_link))}", parse_mode="HTML", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, f"✅ <b>Telegram Group Link Set!</b>\n\n🎮 <b>Hack:</b> {p_name}\n🔗 <b>Link:</b> {group_link}", parse_mode="HTML")
    del admin_temp_data[user_id]

def step_get_reseller_uid(message):
    try:
        target_uid = int(message.text.strip())
        target_user = get_user(target_uid)
        if not target_user:
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(types.InlineKeyboardButton("🔙 Users & Resellers", callback_data="admin_cat_users"))
            bot.send_message(message.chat.id, "❌ <b>User not found in database!</b>\nUser must start the bot first.", parse_mode="HTML", reply_markup=markup)
            return
        
        is_curr_reseller = target_user[11]
        markup = types.InlineKeyboardMarkup()
        if is_curr_reseller:
            markup.add(types.InlineKeyboardButton("❌ Remove Reseller Role", callback_data=f"set_resell_0_{target_uid}"))
        else:
            markup.add(types.InlineKeyboardButton("⭐ Promote to Reseller", callback_data=f"set_resell_1_{target_uid}"))
            
        markup.add(types.InlineKeyboardButton("🔙 Users & Resellers", callback_data="admin_cat_users"))
        bot.send_message(message.chat.id, f"👤 <b>User:</b> {html.escape(str(target_user[1] or 'Unnamed User'), quote=False)} (<code>{target_uid}</code>)\n👑 <b>Current Role:</b> {'Reseller' if is_curr_reseller else 'Standard User'}\n\nSelect Action:", parse_mode="HTML", reply_markup=markup)
    except ValueError:
        msg = bot.send_message(message.chat.id, "❌ Invalid User ID! Enter numeric ID:")
        bot.register_next_step_handler(msg, step_get_reseller_uid)

def step_add_hack_name(message):
    user_id = message.from_user.id
    admin_temp_data[user_id] = {'name': message.text.strip()}
    msg = bot.send_message(message.chat.id, "📅 <b>Enter Day/Plan Duration Name</b> (e.g., <code>1 Hours</code>, <code>1 DaYs</code>):", parse_mode="HTML")
    bot.register_next_step_handler(msg, step_add_hack_days)

def step_add_hack_days(message):
    user_id = message.from_user.id
    admin_temp_data[user_id]['days'] = message.text.strip()
    msg = bot.send_message(message.chat.id, "💰 <b>Enter Regular User Price in INR (₹)</b> (e.g., <code>250</code>):", parse_mode="HTML")
    bot.register_next_step_handler(msg, step_add_hack_price)

def step_add_hack_price(message):
    user_id = message.from_user.id
    try:
        admin_temp_data[user_id]['price'] = float(message.text.strip())
        msg = bot.send_message(message.chat.id, "💎 <b>Enter Reseller Discounted Price in INR (₹)</b> (e.g., <code>125</code>):", parse_mode="HTML")
        bot.register_next_step_handler(msg, step_add_hack_resell_price)
    except ValueError:
        msg = bot.send_message(message.chat.id, "❌ Invalid price! Enter a valid number:")
        bot.register_next_step_handler(msg, step_add_hack_price)

def step_add_hack_resell_price(message):
    user_id = message.from_user.id
    try:
        resell_price = float(message.text.strip())
        data = admin_temp_data[user_id]
        add_product_db(data['name'], "133", data['days'], data['price'], resell_price, is_manual=0, remote_duration=data['days'])
        product_name = data['name']
        _pp_set_active_product(user_id, product_name)
        del admin_temp_data[user_id]

        # Stay inside the new Product & Plans workflow.  The success card itself
        # provides the next useful actions instead of jumping back to the old
        # management screen.
        h = _ui_hash(f"pp:{product_name}")
        admin_temp_data.setdefault(user_id, {}).setdefault('pp_hack_catalog', {})[h] = product_name
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.row(
            types.InlineKeyboardButton("➕ Add Another Plan", callback_data=f"pp_add_plan_same_{h}"),
            types.InlineKeyboardButton("🎮 Manage Hack", callback_data=f"pp_hack_{h}"),
        )
        markup.add(types.InlineKeyboardButton("➕ Add New Product", callback_data="pp_add_product"))
        # Keep the navigation control in a dedicated final row.  The universal
        # helper also prevents duplicate Back buttons if this screen is restored.
        markup = _ensure_admin_back_button(
            markup, label="🔙 Product & Plans", callback_data="admin_cat_setup"
        )
        bot.send_message(
            message.chat.id,
            f"✅ <b>PLAN ADDED SUCCESSFULLY</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎮 <b>Hack:</b> {html.escape(str(product_name))}\n"
            f"📅 <b>Plan:</b> {html.escape(str(data['days']))}\n"
            f"💰 <b>User Price:</b> ₹{data['price']:.2f}\n"
            f"💎 <b>Reseller Price:</b> ₹{resell_price:.2f}\n\n"
            "<i>Add another duration, or open the hack to manage everything.</i>",
            parse_mode="HTML", reply_markup=markup
        )
    except ValueError:
        msg = bot.send_message(message.chat.id, "❌ Invalid price! Enter a valid number:")
        bot.register_next_step_handler(msg, step_add_hack_resell_price)

def step_get_add_day_to_hack(message):
    user_id = message.from_user.id
    admin_temp_data[user_id]['days'] = message.text.strip()
    msg = bot.send_message(message.chat.id, "💰 <b>Enter Regular User Price in INR (₹):</b>", parse_mode="HTML")
    bot.register_next_step_handler(msg, step_add_hack_price)


def step_set_hack_position(message):
    user_id = message.from_user.id
    ctx = admin_temp_data.get(user_id, {})
    product_name = ctx.get('pp_position_product')
    raw = (message.text or '').strip()
    try:
        position = int(raw)
    except ValueError:
        msg = bot.send_message(message.chat.id, "❌ <b>Invalid position.</b> Enter a number such as <code>1</code>, <code>2</code>, <code>3</code>.", parse_mode='HTML')
        bot.register_next_step_handler(msg, step_set_hack_position)
        return
    ok, final_pos = set_hack_position(product_name, position)
    if not ok:
        bot.send_message(message.chat.id, "❌ Hack not found. Please open Product &amp; Plans again.", parse_mode='HTML')
        admin_temp_data.pop(user_id, None)
        return
    admin_temp_data.pop(user_id, None)
    _pp_set_active_product(user_id, product_name)
    markup = types.InlineKeyboardMarkup(row_width=1)
    h = _ui_hash(f"pp:{product_name}")
    admin_temp_data.setdefault(user_id, {}).setdefault('pp_hack_catalog', {})[h] = product_name
    markup.add(types.InlineKeyboardButton(f"🎮 Open {product_name}", callback_data=f"pp_hack_{h}"))
    markup.add(types.InlineKeyboardButton("🎮 Hacks & Plans", callback_data="pp_hacks"))
    markup.add(types.InlineKeyboardButton("🔙 Product & Plans", callback_data="admin_cat_setup"))
    bot.send_message(message.chat.id, f"✅ <b>Position Updated</b>\n\n🎮 <b>{html.escape(str(product_name))}</b> is now position <b>{final_pos}</b>.", parse_mode='HTML', reply_markup=markup)


# ==================== MULTI NEW API SERVER MANAGEMENT ====================
def _normalize_api_server_url(value):
    url = str(value or "").strip().strip("`").strip()
    if not url:
        return ""
    # Admin may paste the balance endpoint from curl. Store the server root.
    url = re.sub(r"/api/v1/balance/?$", "", url, flags=re.I)
    url = re.sub(r"/api/v1/?$", "", url, flags=re.I)
    return url.rstrip("/")


def _api_server_row(server_id):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        return conn.execute(
            """SELECT id, server_name, api_key, server_url, enabled, created_at,
                      COALESCE(last_connected_at,''), COALESCE(account_name,''),
                      COALESCE(account_username,''), COALESCE(account_user_id,'')
               FROM api_servers WHERE id=?""",
            (int(server_id),)
        ).fetchone()
    finally:
        conn.close()


def _api_servers():
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        return conn.execute(
            """SELECT id, server_name, api_key, server_url, enabled, created_at,
                      COALESCE(last_connected_at,''), COALESCE(account_name,''),
                      COALESCE(account_username,''), COALESCE(account_user_id,'')
               FROM api_servers ORDER BY id ASC"""
        ).fetchall()
    finally:
        conn.close()


def _api_server_save(server_name, api_key, server_url):
    server_url = _normalize_api_server_url(server_url)
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO api_servers(server_name,api_key,server_url,enabled,created_at,last_connected_at,account_name,account_username,account_user_id) VALUES(?,?,?,?,?,?,?,?,?)",
            (str(server_name).strip(), str(api_key).strip(), server_url, 0,
             datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), '', '', '', '')
        )
        sid = cur.lastrowid
        conn.commit()
        return sid
    finally:
        conn.close()


def _api_server_set_enabled(server_id, enabled):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        conn.execute("UPDATE api_servers SET enabled=? WHERE id=?", (1 if enabled else 0, int(server_id)))
        conn.commit()
    finally:
        conn.close()


def _api_server_update(server_id, server_name=None, api_key=None, server_url=None):
    """Update only supplied server fields; existing mappings remain untouched."""
    row = _api_server_row(server_id)
    if not row:
        return False
    current_name, current_key, current_url = row[1], row[2], row[3]
    name = str(server_name if server_name is not None else current_name).strip()
    key = str(api_key if api_key is not None else current_key).strip()
    url = _normalize_api_server_url(server_url if server_url is not None else current_url)
    if not name or not key or not re.match(r"^https?://", url, re.I):
        return False
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        conn.execute(
            "UPDATE api_servers SET server_name=?, api_key=?, server_url=? WHERE id=?",
            (name, key, url, int(server_id))
        )
        conn.commit()
        return True
    finally:
        conn.close()


def _api_server_delete(server_id):
    """Delete one API server and its mappings without touching products/plans."""
    row = _api_server_row(server_id)
    if not row:
        return False
    sid = int(server_id)
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        conn.execute("DELETE FROM api_server_plan_ids WHERE server_id=?", (sid,))
        conn.execute("DELETE FROM api_server_products WHERE server_id=?", (sid,))
        # If this server was the selected source for a product, remove only that
        # selection; the product itself and all local plans remain intact.
        conn.execute("DELETE FROM product_server_selection WHERE server_id=?", (sid,))
        conn.execute("DELETE FROM api_servers WHERE id=?", (sid,))
        conn.commit()
        return True
    finally:
        conn.close()


def _api_server_edit_markup(server_id):
    m = types.InlineKeyboardMarkup(row_width=2)
    m.row(
        _admin_colorful_button("✏️ Edit Name", callback_data=f"api_edit_name_{int(server_id)}", color="blue"),
        _admin_colorful_button("🔑 Edit API Key", callback_data=f"api_edit_key_{int(server_id)}", color="blue"),
    )
    m.add(_admin_colorful_button("🌐 Edit Server URL", callback_data=f"api_edit_url_{int(server_id)}", color="green"))
    m.add(_admin_colorful_button(
        "🟢 Enable" if not (_api_server_row(server_id) or [0]*5)[4] else "🔴 Disable",
        callback_data=f"api_toggle_{int(server_id)}",
        color="green" if not (_api_server_row(server_id) or [0]*5)[4] else "red"
    ))
    m.add(_admin_colorful_button("🗑️ Delete Server", callback_data=f"api_delete_{int(server_id)}", color="red"))
    m.add(_admin_colorful_button("🔙 Server", callback_data=f"api_srv_{int(server_id)}", color="red"))
    return _ensure_admin_back_button(m)


def _api_server_save_product(server_id, product_name, product_id):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """INSERT INTO api_server_products(server_id,product_name,product_id,updated_at)
               VALUES(?,?,?,?)
               ON CONFLICT(server_id,product_name) DO UPDATE SET
               product_id=excluded.product_id, updated_at=excluded.updated_at""",
            (int(server_id), str(product_name), str(product_id).strip(), now)
        )
        # This product uses this New API Server for future automatic delivery.
        conn.execute(
            """INSERT INTO product_server_selection(product_name,server_id,updated_at)
               VALUES(?,?,?)
               ON CONFLICT(product_name) DO UPDATE SET
               server_id=excluded.server_id, updated_at=excluded.updated_at""",
            (str(product_name), int(server_id), now)
        )
        conn.commit()
    finally:
        conn.close()


def _api_server_product(server_id, product_name):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        return conn.execute(
            "SELECT server_id,product_name,product_id,updated_at FROM api_server_products WHERE server_id=? AND product_name=?",
            (int(server_id), str(product_name))
        ).fetchone()
    finally:
        conn.close()


def _api_server_save_plan(server_id, product_name, plan_id, plan_days, valid_id):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """INSERT INTO api_server_plan_ids(server_id,product_name,plan_id,valid_id,plan_days,updated_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(server_id,product_name,plan_id) DO UPDATE SET
               valid_id=excluded.valid_id, plan_days=excluded.plan_days, updated_at=excluded.updated_at""",
            (int(server_id), str(product_name), int(plan_id), str(valid_id).strip(), str(plan_days), now)
        )
        conn.commit()
    finally:
        conn.close()


def _api_server_plan_valid_id(server_id, product_name, plan_id):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        row = conn.execute(
            "SELECT valid_id FROM api_server_plan_ids WHERE server_id=? AND product_name=? AND plan_id=?",
            (int(server_id), str(product_name), int(plan_id))
        ).fetchone()
        value = str(row[0]).strip() if row and row[0] else ""
        return "" if value.startswith("/") else value
    finally:
        conn.close()


def _api_server_product_id(server_id, product_name):
    row = _api_server_product(server_id, product_name)
    return str(row[2]).strip() if row and row[2] else ""



def _api_server_set_connection_meta(server_id, account_name='', account_username='', account_user_id='', connected_at=None):
    """Persist the last successful v1 connection and live reseller identity.

    This is additive metadata only. It never changes Product IDs, Valid IDs or
    existing server configuration, and it makes the server list show the same
    connected/date information the reseller dashboard exposes.
    """
    connected_at = connected_at or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        conn.execute(
            """UPDATE api_servers
               SET enabled=1, last_connected_at=?, account_name=?, account_username=?, account_user_id=?
               WHERE id=?""",
            (str(connected_at), str(account_name or ''), str(account_username or ''),
             str(account_user_id or ''), int(server_id))
        )
        conn.commit()
    finally:
        conn.close()


def _api_server_extract_identity(data):
    """Extract reseller identity from /me without assuming one exact response shape."""
    if not isinstance(data, dict):
        return '', '', ''

    candidates = [data]
    for key in ('data', 'account', 'user', 'reseller', 'profile'):
        value = data.get(key)
        if isinstance(value, dict):
            candidates.append(value)

    def first_value(keys):
        for obj in candidates:
            for key in keys:
                value = obj.get(key)
                if value not in (None, ''):
                    return str(value).strip()
        return ''

    name = first_value(('name', 'display_name', 'reseller_name', 'full_name', 'label'))
    username = first_value(('username', 'telegram_username', 'handle'))
    user_id = first_value(('user_id', 'telegram_id', 'reseller_id', 'id'))
    return name, username, user_id


def _api_server_parse_json(response):
    try:
        value = response.json()
        return value if isinstance(value, (dict, list)) else {}
    except Exception:
        return {}


def _api_server_test_connection(server_id):
    row = _api_server_row(server_id)
    if not row:
        return False, "Server not found."

    _, _, api_key, server_url, _, _, last_connected_at, account_name, account_username, account_user_id = row
    server_url = _normalize_api_server_url(server_url)
    api_key = str(api_key or '').strip()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": "RG-Cheat-Shop-Bot/1.0",
    }

    # The new server shown in the supplied integration guide is a REST v1 API:
    # GET /api/v1/balance with Bearer authentication. Do NOT mark a server
    # connected from the old legacy root endpoint unless the v1 route genuinely
    # does not exist; otherwise a 200 from an unrelated legacy handler can make
    # the UI say Connected while purchases still fail.
    detail = ""
    try:
        res = HTTP_SESSION.get(f"{server_url}/api/v1/balance", headers=headers, timeout=10)
        raw = res.text[:500]
        if res.status_code == 200:
            identity_name, identity_username, identity_user_id = account_name, account_username, account_user_id

            # /me is explicitly documented by the supplied server as account + balance.
            # It is used only to enrich the connection record; /balance already proves auth.
            try:
                me = HTTP_SESSION.get(f"{server_url}/api/v1/me", headers=headers, timeout=8)
                if me.status_code == 200:
                    parsed_me = _api_server_parse_json(me)
                    n, u, uid = _api_server_extract_identity(parsed_me)
                    identity_name = n or identity_name
                    identity_username = u or identity_username
                    identity_user_id = uid or identity_user_id
            except Exception:
                pass

            connected_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _api_server_set_connection_meta(
                server_id,
                identity_name,
                identity_username,
                identity_user_id,
                connected_at,
            )
            return True, raw

        detail = f"HTTP {res.status_code}: {raw}"
        # 401/403 means the supplied Bearer key is wrong/disabled. Do not fall
        # through to the legacy contract and falsely report a successful server.
        if res.status_code not in (404, 405):
            _api_server_set_enabled(server_id, False)
            return False, detail[:300]
    except Exception as exc:
        detail = str(exc)[:300]

    # Compatibility fallback for the older reseller-style API contract. This is
    # intentionally limited to a missing v1 route so the new REST API cannot be
    # accidentally marked connected by a legacy endpoint.
    try:
        res = HTTP_SESSION.post(
            server_url,
            data={"api_key": api_key, "action": "balance"},
            headers={"Content-Type": "application/x-www-form-urlencoded", "x-master-key": RESELLER_MASTER_KEY},
            timeout=10,
        )
        if res.status_code == 200:
            _api_server_set_enabled(server_id, True)
            return True, res.text[:300]
        detail = f"HTTP {res.status_code}: {res.text[:200]}"
    except Exception as exc:
        detail = str(exc)[:300]

    _api_server_set_enabled(server_id, False)
    return False, detail[:300]

def _api_servers_markup():
    markup = types.InlineKeyboardMarkup(row_width=1)
    servers = _api_servers()
    for sid, name, api_key, url, enabled, created_at, last_connected_at, account_name, account_username, account_user_id in servers:
        status = "🟢" if enabled else "⚪"
        # Keep the button compact; detailed identity/date is shown after tapping the server.
        label = f"{status} {name}"
        markup.add(_admin_colorful_button(
            label[:64],
            callback_data=f"api_srv_{sid}",
            color="green" if enabled else "blue"
        ))
    markup.add(_admin_colorful_button("➕ New API Server", callback_data="api_srv_add", color="green"))
    markup.add(_admin_colorful_button("🔙 Back", callback_data="admin_api_system", color="red"))
    return markup


def _api_server_hacks_markup(server_id):
    markup = types.InlineKeyboardMarkup()
    for prod in get_unique_products():
        pid = _api_server_product_id(server_id, prod)
        status = "🟢" if pid else "⚪"
        markup.add(_admin_colorful_button(
            f"{status} {prod}",
            callback_data=f"api_hack_{int(server_id)}_{_ui_hash(prod)}",
            color="green" if pid else "blue"
        ))
    markup.add(_admin_colorful_button("🔙 Server", callback_data=f"api_srv_{int(server_id)}", color="red"))
    return markup


def _api_server_plans_markup(server_id, product_name):
    markup = types.InlineKeyboardMarkup()
    pid = _api_server_product_id(server_id, product_name) or "—"
    for plan in get_product_plans(product_name):
        plan_id = int(plan[0])
        days = str(plan[2])
        valid_id = _api_server_plan_valid_id(server_id, product_name, plan_id)
        status = "🟢" if valid_id else "⚪"
        markup.add(_admin_colorful_button(
            f"{status} {days} | PID:{pid} | VID:{valid_id or '—'}"[:60],
            callback_data=f"api_plan_{int(server_id)}_{_ui_hash(product_name)}_{plan_id}",
            color="green" if valid_id else "blue"
        ))
    markup.add(_admin_colorful_button(
        "🆔 Set / Change Product ID",
        callback_data=f"api_pid_{int(server_id)}_{_ui_hash(product_name)}",
        color="green"
    ))
    markup.add(_admin_colorful_button(
        "🔙 Hack List", callback_data=f"api_hacks_{int(server_id)}", color="red"
    ))
    return markup


def _api_server_hack_by_hash(value):
    for product_name in get_unique_products():
        if _ui_hash(product_name) == str(value):
            return product_name
    return None


def _show_api_server_list(chat_id, message_id=None):
    text = (
        "🆕 <b>NEW API SERVER</b>\n\n"
        "Add multiple New API Servers and configure each hack separately.\n"
        "🟢 = connected • ⚪ = not checked / disconnected\n\n"
        "Each hack keeps its own Product ID and every plan keeps its own Valid ID."
    )
    markup = _ensure_admin_back_button(_api_servers_markup())
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, parse_mode="HTML", reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)


def step_edit_api_server_name(message):
    uid = message.from_user.id
    if not _is_admin(uid):
        return
    data = admin_temp_data.get(uid, {})
    sid = data.get("api_edit_server_id")
    name = (message.text or "").strip()
    if not sid or not name:
        m = bot.send_message(message.chat.id, "❌ Server name cannot be empty. Enter it again.")
        bot.register_next_step_handler(m, step_edit_api_server_name)
        return
    if _api_server_update(sid, server_name=name):
        admin_temp_data.pop(uid, None)
        bot.send_message(message.chat.id, "✅ <b>Server name updated successfully.</b>", parse_mode="HTML",
                         reply_markup=_api_server_edit_markup(sid))
    else:
        bot.send_message(message.chat.id, "❌ Could not update the server name.")


def step_edit_api_server_key(message):
    uid = message.from_user.id
    if not _is_admin(uid):
        return
    data = admin_temp_data.get(uid, {})
    sid = data.get("api_edit_server_id")
    key = (message.text or "").strip()
    if not sid or not key:
        m = bot.send_message(message.chat.id, "❌ API Key cannot be empty. Enter it again.")
        bot.register_next_step_handler(m, step_edit_api_server_key)
        return
    if _api_server_update(sid, api_key=key):
        admin_temp_data.pop(uid, None)
        bot.send_message(message.chat.id, "✅ <b>API Key updated.</b>\n\nRun Check Connection to verify it.",
                         parse_mode="HTML", reply_markup=_api_server_edit_markup(sid))
    else:
        bot.send_message(message.chat.id, "❌ Could not update the API Key.")


def step_edit_api_server_url(message):
    uid = message.from_user.id
    if not _is_admin(uid):
        return
    data = admin_temp_data.get(uid, {})
    sid = data.get("api_edit_server_id")
    url = _normalize_api_server_url(message.text or "")
    if not sid or not re.match(r"^https?://", url, re.I):
        m = bot.send_message(message.chat.id, "❌ Invalid URL. Enter a valid http:// or https:// URL.")
        bot.register_next_step_handler(m, step_edit_api_server_url)
        return
    if _api_server_update(sid, server_url=url):
        admin_temp_data.pop(uid, None)
        bot.send_message(message.chat.id, "✅ <b>Server URL updated.</b>\n\nRun Check Connection to verify it.",
                         parse_mode="HTML", reply_markup=_api_server_edit_markup(sid))
    else:
        bot.send_message(message.chat.id, "❌ Could not update the server URL.")


def step_save_api_server_key(message):
    uid = message.from_user.id
    if not _is_admin(uid):
        return
    key = (message.text or "").strip()
    if not key:
        m = bot.send_message(message.chat.id, "❌ API Key cannot be empty. Enter the API Key again.")
        bot.register_next_step_handler(m, step_save_api_server_key)
        return
    admin_temp_data.setdefault(uid, {})["api_server_key"] = key
    m = bot.send_message(
        message.chat.id,
        "🌐 <b>Enter New API Server Link:</b>\n\n"
        "Example: <code>https://example.com</code>\n"
        "You can also paste the <code>/api/v1/balance</code> URL; it will be normalized automatically.",
        parse_mode="HTML"
    )
    bot.register_next_step_handler(m, step_save_api_server_url)


def step_save_api_server_url(message):
    uid = message.from_user.id
    if not _is_admin(uid):
        return
    data = admin_temp_data.get(uid, {})
    url = _normalize_api_server_url(message.text or "")
    if not data.get("api_server_key") or not re.match(r"^https?://", url, re.I):
        m = bot.send_message(message.chat.id, "❌ Invalid Server Link. Enter a valid http:// or https:// URL.")
        bot.register_next_step_handler(m, step_save_api_server_url)
        return
    count = len(_api_servers()) + 1
    server_name = f"New Server {count}"
    sid = _api_server_save(server_name, data["api_server_key"], url)
    admin_temp_data.pop(uid, None)
    ok, detail = _api_server_test_connection(sid)
    status = "🟢 <b>Connected Successfully!</b>" if ok else "🔴 <b>Not Connect</b>"
    bot.send_message(
        message.chat.id,
        f"✅ <b>API Server Added Successfully!</b>\n\n"
        f"🌐 <b>Server:</b> {html.escape(server_name)}\n"
        f"🔗 <b>Link:</b> <code>{html.escape(url)}</code>\n"
        f"{status}\n\n"
        f"Tap <b>Configure Hacks</b> to map Product IDs and Valid IDs.",
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup()
    )
    # Rebuild keyboard after the success message so the server is immediately usable.
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⚙️ Configure Hacks", callback_data=f"api_hacks_{sid}"))
    markup.add(types.InlineKeyboardButton("🔍 Check Connection", callback_data=f"api_check_{sid}"))
    markup.add(types.InlineKeyboardButton("🔙 API Servers", callback_data="new_server_api"))
    bot.send_message(message.chat.id, "🧩 <b>Server Controls</b>", parse_mode="HTML", reply_markup=markup)


def _resolve_multi_api_route(product_name, plan_id=None, local_pid_id=None, duration=None):
    """Resolve a configured per-product New API Server before legacy routes."""
    if product_name:
        conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
        try:
            row = conn.execute(
                """SELECT s.id,s.api_key,s.server_url,s.enabled,p.product_id
                   FROM product_server_selection sel
                   JOIN api_servers s ON s.id=sel.server_id
                   JOIN api_server_products p
                     ON p.server_id=s.id AND p.product_name=sel.product_name
                   WHERE sel.product_name=? LIMIT 1""",
                (str(product_name),)
            ).fetchone()
        finally:
            conn.close()
        if row:
            sid, api_key, server_url, enabled, product_id = row
            valid_id = _api_server_plan_valid_id(sid, product_name, plan_id) if plan_id is not None else ""
            if product_id and (plan_id is None or valid_id):
                return {
                    "url": _normalize_api_server_url(server_url),
                    "api_key": api_key,
                    "product_id": product_id,
                    "valid_id": valid_id,
                    "server_type": "new_multi",
                    "server_id": sid,
                }
    return None


# Replace route resolution at runtime with a wrapper that preserves the old
# New Server and Old Server fallbacks exactly as before.
_legacy_resolve_api_route = _resolve_api_route
def _resolve_api_route(product_name, plan_id=None, local_pid_id=None, duration=None):
    if product_name and plan_id is not None and _rg_source_ready_for_plan(product_name, plan_id):
        return {'url': _rg_base_url(), 'api_key': _rg_api_token(), 'product_id': _rg_product_id(product_name),
                'valid_id': _rg_plan_valid_id(product_name, plan_id), 'server_type': 'rg'}
    if product_name and _ninex_product_enabled(product_name) and _ninex_api_token() and _ninex_base_url():
        return {'url': _ninex_base_url(), 'api_key': _ninex_api_token(), 'product_id': '', 'valid_id': '', 'server_type': 'ninex'}
    if (product_name and not _product_hidden(product_name) and _tobix_product_enabled(product_name)
            and _tobix_api_token() and _tobix_base_url()
            and str(get_setting('tobix_api_connected') or '0') == '1'):
        # Once an admin explicitly connects this hack to TobiX, route this
        # product to TobiX rather than silently falling through to another
        # provider. Unsupported/non-day plans remain unavailable through the
        # stock check instead of being charged by a different API.
        return {'url': _tobix_base_url(), 'api_key': _tobix_api_token(), 'product_id': '', 'valid_id': '', 'server_type': 'tobix'}
    multi = _resolve_multi_api_route(product_name, plan_id, local_pid_id, duration)
    if multi:
        return multi
    return _legacy_resolve_api_route(product_name, plan_id, local_pid_id, duration)



def _is_command_input(text):
    """Return True when a Telegram command was sent to a numeric/API-ID prompt.

    Next-step handlers receive messages before normal command handlers, so /start
    could previously be accidentally saved as a Product ID/Valid ID.
    """
    value = str(text or "").strip()
    return value.startswith("/")

def _cancel_pending_id_step(uid):
    try:
        bot.clear_step_handler_by_chat_id(uid)
    except Exception:
        pass

def step_save_multi_api_product_id(message):
    uid = message.from_user.id
    data = admin_temp_data.get(uid, {})
    sid = data.get("api_server_id")
    product_name = data.get("api_server_product")
    pid = (message.text or "").strip()
    if not sid or not product_name:
        bot.send_message(message.chat.id, "❌ Session expired.")
        return
    if _is_command_input(pid):
        _cancel_pending_id_step(uid)
        admin_temp_data.pop(uid, None)
        if pid.lower().split()[0] == "/start":
            send_welcome(message)
        else:
            bot.send_message(message.chat.id, "ℹ️ ID entry cancelled. Please open Configure Hacks again.")
        return
    if not pid:
        m = bot.send_message(message.chat.id, "❌ Product ID cannot be empty. Enter it again.")
        bot.register_next_step_handler(m, step_save_multi_api_product_id)
        return
    # API Product IDs are provider-defined identifiers. They may be numeric,
    # alphanumeric, contain spaces, dashes, underscores, dots, or other text.
    # Only empty values and Telegram commands are rejected; the exact value is
    # preserved so the connected API receives the provider's identifier verbatim.
    _api_server_save_product(sid, product_name, pid)
    admin_temp_data.pop(uid, None)
    bot.send_message(
        message.chat.id,
        f"✅ <b>Product ID Saved Successfully!</b>\n\n"
        f"🎮 <b>Hack:</b> {html.escape(product_name)}\n"
        f"🆔 <b>Product ID:</b> <code>{html.escape(pid)}</code>\n\n"
        "Now set each plan's Valid ID.",
        parse_mode="HTML",
        reply_markup=_api_server_plans_markup(sid, product_name)
    )


def step_save_multi_api_valid_id(message):
    uid = message.from_user.id
    data = admin_temp_data.get(uid, {})
    sid = data.get("api_server_id")
    product_name = data.get("api_server_product")
    plan_id = data.get("api_server_plan_id")
    plan_days = data.get("api_server_plan_days", "")
    valid_id = (message.text or "").strip()
    if not sid or not product_name or plan_id is None:
        bot.send_message(message.chat.id, "❌ Session expired.")
        return
    if _is_command_input(valid_id):
        _cancel_pending_id_step(uid)
        admin_temp_data.pop(uid, None)
        if valid_id.lower().split()[0] == "/start":
            send_welcome(message)
        else:
            bot.send_message(message.chat.id, "ℹ️ Valid ID entry cancelled. Please open Configure Hacks again.")
        return
    if not valid_id:
        m = bot.send_message(message.chat.id, "❌ Valid ID cannot be empty. Enter it again.")
        bot.register_next_step_handler(m, step_save_multi_api_valid_id)
        return
    # Variant/Valid IDs are also provider-defined and can be any non-empty
    # text value (numeric, alphanumeric, words + numbers, spaces, etc.).
    # Telegram commands remain blocked above so /start cannot be saved accidentally.
    if not _api_server_product_id(sid, product_name):
        bot.send_message(message.chat.id, "❌ Set the Product ID first.", parse_mode="HTML")
        admin_temp_data.pop(uid, None)
        return
    _api_server_save_plan(sid, product_name, int(plan_id), str(plan_days), valid_id)
    admin_temp_data.pop(uid, None)
    bot.send_message(
        message.chat.id,
        f"✅ <b>Valid ID Saved Successfully!</b>\n\n"
        f"🎮 <b>Hack:</b> {html.escape(product_name)}\n"
        f"📅 <b>Plan:</b> {html.escape(str(plan_days))}\n"
        f"🔢 <b>Valid ID:</b> <code>{html.escape(valid_id)}</code>",
        parse_mode="HTML",
        reply_markup=_api_server_plans_markup(sid, product_name)
    )


def step_save_new_server_product_id(message):
    uid=message.from_user.id; d=admin_temp_data.get(uid,{}) ; product_name=d.get('new_server_product'); pid=(message.text or '').strip()
    if not product_name: bot.send_message(message.chat.id,"❌ Session expired."); return
    if _is_command_input(pid):
        _cancel_pending_id_step(uid); admin_temp_data.pop(uid,None)
        if pid.lower().split()[0] == "/start": send_welcome(message)
        else: bot.send_message(message.chat.id,"ℹ️ ID entry cancelled. Please open Configure Hacks again.")
        return
    if not pid:
        m=bot.send_message(message.chat.id,"❌ Product ID cannot be empty. Enter the exact Product ID:"); bot.register_next_step_handler(m,step_save_new_server_product_id); return
    # Provider Product IDs are not restricted to digits. Preserve any
    # non-empty, non-command identifier exactly as entered.
    _save_new_server_config(product_name,NEW_SERVER_API_KEY,NEW_SERVER_API_URL,pid)
    ok, _detail = _new_server_test_connection()
    set_setting(NEW_SERVER_ENABLED_KEY, '1' if ok else '0')
    admin_temp_data.pop(uid,None)
    bot.send_message(message.chat.id,f"✅ <b>New Server Product ID saved.</b>\n\n🎮 <b>Hack:</b> {html.escape(product_name)}\n🆔 <b>Product ID:</b> <code>{html.escape(pid)}</code>\n\n{'🟢 API Connection: Connected' if ok else '🔴 API Connection: Not Connected'}",parse_mode="HTML",reply_markup=_new_server_hacks_markup())

def step_save_new_server_valid_id(message):
    uid=message.from_user.id; d=admin_temp_data.get(uid,{}) ; product_name=d.get('new_server_product'); plan_id=d.get('new_server_plan_id'); plan_days=d.get('new_server_plan_days',''); valid_id=(message.text or '').strip()
    if not product_name or plan_id is None: bot.send_message(message.chat.id,"❌ Session expired."); return
    if _is_command_input(valid_id):
        _cancel_pending_id_step(uid); admin_temp_data.pop(uid,None)
        if valid_id.lower().split()[0] == "/start": send_welcome(message)
        else: bot.send_message(message.chat.id,"ℹ️ Valid ID entry cancelled. Please open Configure Hacks again.")
        return
    if not valid_id:
        m=bot.send_message(message.chat.id,"❌ Valid ID cannot be empty. Enter the exact Valid ID:"); bot.register_next_step_handler(m,step_save_new_server_valid_id); return
    # Provider Valid/Variant IDs may be numeric or arbitrary text. Empty
    # values and Telegram commands are handled above; everything else is valid.
    cfg=_new_server_config(product_name)
    if not cfg or not cfg[3]: bot.send_message(message.chat.id,"❌ Set the New Server Product ID first.",parse_mode="HTML"); admin_temp_data.pop(uid,None); return
    _save_new_server_plan_valid_id(product_name,int(plan_id),str(plan_days),valid_id); admin_temp_data.pop(uid,None)
    bot.send_message(message.chat.id,f"✅ <b>Valid ID saved.</b>\n\n🎮 <b>Hack:</b> {html.escape(product_name)}\n📅 <b>Plan:</b> {html.escape(str(plan_days))}\n🆔 <b>Product ID:</b> <code>{html.escape(str(cfg[3]))}</code>\n🔢 <b>Valid ID:</b> <code>{html.escape(valid_id)}</code>",parse_mode="HTML",reply_markup=_new_server_plans_markup(product_name))

def _server_manager_hacks_markup():
    markup=types.InlineKeyboardMarkup()
    for prod in get_unique_products(): markup.add(types.InlineKeyboardButton(f"🎮 {prod}",callback_data=f"hack_server_select_{prod}"))
    _ensure_admin_back_button(markup, label="🔙 API & Servers", callback_data="admin_cat_api")
    return markup

def step_save_hack_server_api_key(message):
    uid=message.from_user.id; d=admin_temp_data.get(uid,{})
    if not d.get('hack_server_product'): return bot.send_message(message.chat.id,"❌ Session expired.")
    d['api_key']=(message.text or '').strip()
    if not d['api_key']:
        m=bot.send_message(message.chat.id,"❌ API Key cannot be empty."); bot.register_next_step_handler(m,step_save_hack_server_api_key); return
    m=bot.send_message(message.chat.id,"🌐 <b>Enter Server URL:</b>",parse_mode="HTML"); bot.register_next_step_handler(m,step_save_hack_server_url)

def step_save_hack_server_url(message):
    uid=message.from_user.id; d=admin_temp_data.get(uid,{}) ; url=(message.text or '').strip()
    if not d.get('hack_server_product') or not url.startswith(('http://','https://')):
        m=bot.send_message(message.chat.id,"❌ Enter a valid Server URL:"); bot.register_next_step_handler(m,step_save_hack_server_url); return
    d['server_url']=url; m=bot.send_message(message.chat.id,"🆔 <b>Enter Server Product ID:</b>",parse_mode="HTML"); bot.register_next_step_handler(m,step_save_hack_server_product_id)

def step_save_hack_server_product_id(message):
    uid=message.from_user.id; d=admin_temp_data.get(uid,{}) ; pid=(message.text or '').strip()
    if _is_command_input(pid):
        _cancel_pending_id_step(uid); admin_temp_data.pop(uid,None)
        if pid.lower().split()[0] == '/start':
            send_welcome(message)
        else:
            bot.send_message(message.chat.id, 'ℹ️ Product ID entry cancelled. Please open Configure Hacks again.')
        return
    if not d.get('hack_server_product') or not pid:
        m=bot.send_message(message.chat.id,"❌ Product ID cannot be empty."); bot.register_next_step_handler(m,step_save_hack_server_product_id); return
    d['remote_product_id']=pid; plans=get_product_plans(d['hack_server_product']); d['hack_server_plan_queue']=[{'plan_id':int(x[0]),'days':str(x[2])} for x in plans]; d['hack_server_plan_index']=0
    _save_hack_server_config(d['hack_server_product'],d['api_key'],d['server_url'],pid)
    if not d['hack_server_plan_queue']:
        bot.send_message(message.chat.id,"✅ <b>Server saved!</b>",parse_mode="HTML"); admin_temp_data.pop(uid,None); return
    _ask_next_hack_valid_id(message.chat.id,uid)

def _ask_next_hack_valid_id(chat_id,uid):
    d=admin_temp_data.get(uid,{}); q=d.get('hack_server_plan_queue',[]); i=int(d.get('hack_server_plan_index',0))
    if i>=len(q):
        product_name = d.get('hack_server_product','')
        connected = False
        try:
            res = HTTP_SESSION.post(
                d.get('server_url',''),
                data={'api_key': d.get('api_key',''), 'action': 'balance'},
                headers={'Content-Type':'application/x-www-form-urlencoded','x-master-key':RESELLER_MASTER_KEY},
                timeout=8
            )
            connected = res.status_code == 200
        except Exception:
            connected = False
        set_setting(f"hack_server_connected_{_ui_hash(product_name)}", '1' if connected else '0')
        bot.send_message(chat_id,f"✅ <b>Hack API & Server configuration saved!</b>\n\n🎮 <b>Hack:</b> {html.escape(product_name)}\n🌐 <b>Server:</b> <code>{html.escape(d.get('server_url',''))}</code>\n🆔 <b>Product ID:</b> <code>{html.escape(d.get('remote_product_id',''))}</code>\n\nThis hack now uses the new server; other hacks remain unchanged.\n\n{'🟢 API Connection: Connected' if connected else '🔴 API Connection: Not Connected'}",parse_mode="HTML"); admin_temp_data.pop(uid,None); return
    plan=q[i]; m=bot.send_message(chat_id,f"🆔 <b>Enter Valid ID for {html.escape(plan['days'])}:</b>\n\nPlan {i+1} of {len(q)}",parse_mode="HTML"); bot.register_next_step_handler(m,step_save_hack_valid_id)

def step_save_hack_valid_id(message):
    uid=message.from_user.id; d=admin_temp_data.get(uid,{}); q=d.get('hack_server_plan_queue',[]); i=int(d.get('hack_server_plan_index',0)); valid=(message.text or '').strip()
    if _is_command_input(valid):
        _cancel_pending_id_step(uid); admin_temp_data.pop(uid,None)
        if valid.lower().split()[0] == '/start':
            send_welcome(message)
        else:
            bot.send_message(message.chat.id, 'ℹ️ Valid ID entry cancelled. Please open Configure Hacks again.')
        return
    if not q or i>=len(q): admin_temp_data.pop(uid,None); return
    if not valid:
        m=bot.send_message(message.chat.id,"❌ Valid ID cannot be empty."); bot.register_next_step_handler(m,step_save_hack_valid_id); return
    plan=q[i]; _save_hack_server_plan_valid_id(d['hack_server_product'],plan['plan_id'],plan['days'],valid); d['hack_server_plan_index']=i+1; _ask_next_hack_valid_id(message.chat.id,uid)

def step_get_server_token(message):
    user_id = message.from_user.id
    admin_temp_data[user_id] = {'api_key': message.text.strip()}
    msg = bot.send_message(message.chat.id, "🌐 <b>Enter Server API URL:</b>", parse_mode="HTML")
    bot.register_next_step_handler(msg, step_get_server_url)

def step_get_server_url(message):
    user_id = message.from_user.id
    server_url = message.text.strip()
    api_key = admin_temp_data[user_id]['api_key']
    
    set_setting('server_api_key', api_key)
    set_setting('server_api_url', server_url)
    
    markup = types.InlineKeyboardMarkup()
    btn_conn = types.InlineKeyboardButton("⚡ Connect & Verify API", callback_data="test_server_api_conn")
    markup.add(btn_conn)
    
    bot.send_message(message.chat.id, "✅ <b>Add Successfully!</b>\n\nClick the button below to test server connection:", parse_mode="HTML", reply_markup=markup)
    del admin_temp_data[user_id]

def step_get_remote_pid(message):
    user_id = message.from_user.id
    pid_id = (message.text or '').strip()
    if _is_command_input(pid_id):
        _cancel_pending_id_step(user_id)
        admin_temp_data.pop(user_id, None)
        if pid_id.lower().split()[0] == '/start':
            send_welcome(message)
        else:
            bot.send_message(message.chat.id, 'ℹ️ Product ID entry cancelled.')
        return
    if not pid_id:
        m = bot.send_message(message.chat.id, '❌ Product ID cannot be empty. Enter the exact Product ID:')
        bot.register_next_step_handler(m, step_get_remote_pid)
        return
    # The upstream API may use numeric, alphanumeric, or human-readable IDs.
    admin_temp_data[user_id]['pid_id'] = pid_id
    msg = bot.send_message(message.chat.id, "📅 <b>Enter Server Remote Duration String</b> (e.g., <code>1 Hours</code>, <code>3 Hours</code>, <code>1 DaYs</code>):", parse_mode="HTML")
    bot.register_next_step_handler(msg, step_get_remote_duration)

def step_get_remote_duration(message):
    user_id = message.from_user.id
    remote_duration = message.text.strip()
    plan_id = admin_temp_data[user_id]['plan_id']
    pid_id = admin_temp_data[user_id]['pid_id']
    
    update_product_api_mapping(plan_id, pid_id, remote_duration)
    
    bot.send_message(
        message.chat.id,
        f"✅ <b>Server API Auto-Fallback Connected Successfully!</b>\n\n"
        f"🆔 <b>Product ID:</b> <code>{pid_id}</code>\n"
        f"📅 <b>Remote Duration:</b> <code>{remote_duration}</code>",
        parse_mode="HTML"
    )
    del admin_temp_data[user_id]

def step_get_new_bot_token(message):
    new_token = message.text.strip()
    if ":" in new_token and len(new_token) > 20:
        set_setting('bot_token', new_token)
        bot.send_message(message.chat.id, f"✅ <b>Bot API Token Updated Successfully!</b>\n\n🔑 <b>New Token Saved:</b> <code>{new_token}</code>\n\nPlease restart the python script for the new bot token to take full effect.", parse_mode="HTML")
    else:
        msg = bot.send_message(message.chat.id, "❌ Invalid Bot Token format! Enter valid Telegram Bot API Token:")
        bot.register_next_step_handler(msg, step_get_new_bot_token)

def _broadcast_store_batch(source_chat_id, source_message_id, deliveries):
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        raw = json.dumps([{'chat_id': int(c), 'message_id': int(m)} for c,m in deliveries], ensure_ascii=False, separators=(',', ':'))
        cur = conn.execute(
            'INSERT INTO broadcast_history(created_at,source_chat_id,source_message_id,sent_count,deleted,deliveries_json) VALUES(?,?,?,?,0,?)',
            (_now_ist_text(), int(source_chat_id), int(source_message_id or 0), len(deliveries), raw)
        )
        conn.commit(); return int(cur.lastrowid)
    finally:
        conn.close()

def _broadcast_last_batch():
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        row=conn.execute('SELECT id,created_at,source_chat_id,source_message_id,sent_count,deleted,deliveries_json FROM broadcast_history ORDER BY id DESC LIMIT 1').fetchone()
    finally: conn.close()
    if not row: return None
    try: deliveries=json.loads(row[6] or '[]'); deliveries=deliveries if isinstance(deliveries,list) else []
    except Exception: deliveries=[]
    return {'id':int(row[0]),'created_at':str(row[1] or ''),'source_chat_id':int(row[2] or 0),'source_message_id':int(row[3] or 0),'sent_count':int(row[4] or 0),'deleted':bool(int(row[5] or 0)),'deliveries':deliveries}

def _broadcast_recent_batches(limit=10):
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        rows=conn.execute('SELECT id,created_at,sent_count,deleted FROM broadcast_history ORDER BY id DESC LIMIT ?', (int(limit),)).fetchall()
        return rows
    finally: conn.close()

def _broadcast_history_markup():
    m=types.InlineKeyboardMarkup(row_width=1)
    for bid,created,count,deleted in _broadcast_recent_batches(10):
        status='🗑️ Deleted' if int(deleted or 0) else '📨 Active'
        m.add(types.InlineKeyboardButton(f"{status} · {created} · {count} users",callback_data=f'admin_broadcast_delete_{int(bid)}'))
    _ensure_admin_back_button(m)
    return m

def _send_broadcast_history_screen(call):
    rows=_broadcast_recent_batches(10)
    if not rows:
        text='📜 <b>BROADCAST HISTORY</b>\n\n<i>No broadcasts have been recorded yet.</i>'
    else:
        lines=['📜 <b>BROADCAST HISTORY</b>','────────────────────────','', 'Tap an active broadcast to delete it:']
        for bid,created,count,deleted in rows:
            status='🗑️ Deleted' if int(deleted or 0) else '📨 Active'
            lines.append(f'• <code>#{int(bid)}</code> — {html.escape(str(created))} — {status} — {int(count)} users')
        text='\n'.join(lines)
    _admin_ui_send(call,text,parse_mode='HTML',reply_markup=_broadcast_history_markup())

def _delete_broadcast_batch(batch_id):
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try: row=conn.execute('SELECT deliveries_json,deleted FROM broadcast_history WHERE id=?',(int(batch_id),)).fetchone()
    finally: conn.close()
    if not row: return 0,0,False
    if bool(int(row[1] or 0)): return 0,0,True
    try: deliveries=json.loads(row[0] or '[]'); deliveries=deliveries if isinstance(deliveries,list) else []
    except Exception: deliveries=[]
    deleted=failed=0
    for item in deliveries:
        try:
            bot.delete_message(int(item['chat_id']),int(item['message_id'])); deleted+=1
        except Exception: failed+=1
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        conn.execute('UPDATE broadcast_history SET deleted=? WHERE id=?',(1 if failed==0 else 0,int(batch_id))); conn.commit()
    finally: conn.close()
    return deleted,failed,False

def _broadcast_admin_markup():
    m=types.InlineKeyboardMarkup(row_width=1)
    m.add(make_ui_button('📢 Send New Broadcast',callback_data='admin_broadcast_send',button_key='admin:broadcast:send',default_color='blue',force_style=True))
    m.add(make_ui_button('📜 Broadcast History',callback_data='admin_broadcast_history',button_key='admin:broadcast:history',default_color='blue',force_style=True))
    last=_broadcast_last_batch()
    if last and not last['deleted'] and last['sent_count']>0:
        m.add(make_ui_button(f"🗑️ Delete Last Broadcast ({last['sent_count']})",callback_data=f"admin_broadcast_delete_{last['id']}",button_key='admin:broadcast:delete',default_color='red',force_style=True))
    _ensure_admin_back_button(m); return _style_admin_markup(m)

def _send_broadcast_admin_screen(call):
    last=_broadcast_last_batch()
    if last:
        status='🗑️ Deleted' if last['deleted'] else f"📨 {last['sent_count']} users received it"
        info=f"\n\n🕒 <b>Last Broadcast:</b> {html.escape(last['created_at'])}\n📊 <b>Status:</b> {status}"
    else: info='\n\n<i>No broadcast has been sent yet.</i>'
    _admin_ui_send(call,'📢 <b>BROADCAST & SUPPORT</b>\n\nSend text, formatted text, Premium/Custom Emoji, photo, video, document or audio.\nTelegram message entities are copied directly so formatting and Premium Emoji are preserved.'+info,parse_mode='HTML',reply_markup=_broadcast_admin_markup())

def step_get_broadcast_media(message):
    """Broadcast the original Telegram message, preserving entities exactly."""
    deliveries=[]; sent_count=0
    for u in get_all_users():
        chat_id=int(u[0])
        try:
            copied=bot.copy_message(chat_id,message.chat.id,message.message_id)
            copied_id=getattr(copied,'message_id',None) or (copied.get('message_id') if isinstance(copied,dict) else None)
            if copied_id is None: raise RuntimeError('missing copied message id')
            deliveries.append((chat_id,int(copied_id))); sent_count+=1; continue
        except Exception: pass
        try:
            text=_message_html_text(message,use_caption=True); sent=None
            if message.content_type=='photo': sent=bot.send_photo(chat_id,message.photo[-1].file_id,caption=text or None,parse_mode='HTML')
            elif message.content_type=='video': sent=bot.send_video(chat_id,message.video.file_id,caption=text or None,parse_mode='HTML')
            elif message.content_type=='audio': sent=bot.send_audio(chat_id,message.audio.file_id,caption=text or None,parse_mode='HTML')
            elif message.content_type=='document': sent=bot.send_document(chat_id,message.document.file_id,caption=text or None,parse_mode='HTML')
            elif message.content_type=='animation': sent=bot.send_animation(chat_id,message.animation.file_id,caption=text or None,parse_mode='HTML')
            elif message.content_type=='voice': sent=bot.send_voice(chat_id,message.voice.file_id,caption=text or None,parse_mode='HTML')
            elif message.content_type=='text': sent=bot.send_message(chat_id,text,parse_mode='HTML')
            if sent and getattr(sent,'message_id',None): deliveries.append((chat_id,int(sent.message_id))); sent_count+=1
        except Exception: pass
    batch_id=_broadcast_store_batch(message.chat.id,message.message_id,deliveries) if deliveries else 0
    bot.send_message(message.chat.id,f"✅ <b>Broadcast Complete!</b>\nDelivered announcement to <b>{sent_count} users</b>."+(f"\n🆔 <b>Broadcast ID:</b> <code>{batch_id}</code>\nYou can delete this broadcast from the Broadcast panel." if batch_id else ''),parse_mode='HTML',reply_markup=_broadcast_admin_markup())

def step_get_user_discount_id(message):
    user_id = message.from_user.id
    try:
        target_uid = int(message.text.strip())
        admin_temp_data[user_id] = {'target_uid': target_uid}
        msg = bot.send_message(message.chat.id, f"🏷️ <b>Enter Discount Percentage for User {target_uid}</b> (e.g., <code>20</code> for 20%):", parse_mode="HTML")
        bot.register_next_step_handler(msg, step_get_user_discount_percent)
    except ValueError:
        msg = bot.send_message(message.chat.id, "❌ Invalid User ID! Please enter numeric ID:")
        bot.register_next_step_handler(msg, step_get_user_discount_id)

def step_get_user_discount_percent(message):
    user_id = message.from_user.id
    try:
        pct = float(message.text.strip())
        target_uid = admin_temp_data[user_id]['target_uid']
        set_user_discount_db(target_uid, pct)
        bot.send_message(message.chat.id, f"✅ <b>Discount Set!</b> User <code>{target_uid}</code> will get <b>{pct}% OFF</b> on their next purchase.", parse_mode="HTML")
        
        try:
            bot.send_message(target_uid, f"🎁 <b>Congratulations!</b> You have received a special <b>{pct}% Discount</b> on your next purchase in the shop!", parse_mode="HTML")
        except Exception:
            pass
            
        del admin_temp_data[user_id]
    except ValueError:
        msg = bot.send_message(message.chat.id, "❌ Enter valid percentage number:")
        bot.register_next_step_handler(msg, step_get_user_discount_percent)

def step_get_global_discount_percent(message):
    try:
        pct = float(message.text.strip())
        set_global_discount_db(pct)
        bot.send_message(message.chat.id, f"✅ <b>Global Store Discount Set!</b> Regular users now get <b>{pct}% OFF</b> on all products.", parse_mode="HTML")
        
        users = get_all_users()
        for u in users:
            try:
                bot.send_message(u[0], f"📢 <b>DISCOUNT NOTIFICATION!</b>\n\n🎉 A new <b>Global Store Discount of {pct}% OFF</b> is now live on all products! Check the store now.", parse_mode="HTML")
            except Exception:
                pass
    except ValueError:
        msg = bot.send_message(message.chat.id, "❌ Enter valid percentage number:")
        bot.register_next_step_handler(msg, step_get_global_discount_percent)

def step_get_prod_discount_percent(message):
    user_id = message.from_user.id
    try:
        pct = float(message.text.strip())
        p_name = admin_temp_data[user_id]['prod_name']
        set_product_discount_db(p_name, pct)
        bot.send_message(message.chat.id, f"✅ <b>Product Discount Set!</b> Product <b>{p_name}</b> now has a <b>{pct}% OFF</b> discount for regular users.", parse_mode="HTML")
        
        users = get_all_users()
        for u in users:
            try:
                bot.send_message(u[0], f"📢 <b>HACK DISCOUNT ALERT!</b>\n\n🎮 <b>{p_name}</b> is now available with <b>{pct}% OFF</b> discount! Grab your key now from the store.", parse_mode="HTML")
            except Exception:
                pass
                
        del admin_temp_data[user_id]
    except ValueError:
        msg = bot.send_message(message.chat.id, "❌ Enter valid percentage number:")
        bot.register_next_step_handler(msg, step_get_prod_discount_percent)

def step_get_bal_user_id(message):
    user_id = message.from_user.id
    try:
        target_uid = int(message.text.strip())
        admin_temp_data[user_id] = {'target_uid': target_uid}
        markup = types.InlineKeyboardMarkup()
        btn_add = types.InlineKeyboardButton("➕ Add Balance", callback_data="bal_action_add")
        btn_sub = types.InlineKeyboardButton("➖ Remove Balance", callback_data="bal_action_sub")
        markup.add(btn_add, btn_sub)
        bot.send_message(message.chat.id, f"💰 <b>Selected User:</b> <code>{target_uid}</code>\nChoose action:", parse_mode="HTML", reply_markup=markup)
    except ValueError:
        msg = bot.send_message(message.chat.id, "❌ Invalid User ID!")
        bot.register_next_step_handler(msg, step_get_bal_user_id)

def step_get_bal_amount(message):
    user_id = message.from_user.id
    try:
        amt = float(message.text.strip())
        target_uid = admin_temp_data[user_id]['target_uid']
        is_add = admin_temp_data[user_id]['is_add']
        
        modify_user_balance_manual(target_uid, amt, is_add)
        user_info = get_user(target_uid)
        new_bal = user_info[4] if user_info else 0.0
        
        act_str = "Added" if is_add else "Removed"
        _admin_success_send(message.chat.id, f"✅ <b>Balance Updated!</b>\n{act_str} ₹{amt:.2f} INR for User <code>{target_uid}</code>.\n💼 New Balance: ₹{new_bal:.2f} INR", parse_mode="HTML")
        try:
            bot.send_message(target_uid, f"🔔 <b>Balance Update!</b>\nAdmin {act_str.lower()} ₹{amt:.2f} INR. Your new balance is ₹{new_bal:.2f} INR.", parse_mode="HTML")
        except Exception:
            pass
        del admin_temp_data[user_id]
    except ValueError:
        msg = bot.send_message(message.chat.id, "❌ Enter valid numerical amount:")
        bot.register_next_step_handler(msg, step_get_bal_amount)

def step_get_guide_url(message):
    global guide_video_url
    new_url = message.text.strip()
    if new_url.startswith("http://") or new_url.startswith("https://"):
        guide_video_url = new_url
        set_setting('guide_url', new_url)
        _admin_success_send(message.chat.id, f"✅ <b>Guide Link Updated Successfully!</b>\n\n🔗 <b>New Link:</b> {new_url}", parse_mode="HTML")
    else:
        msg = bot.send_message(message.chat.id, "❌ Invalid Link! Please enter a valid URL starting with http:// or https://")
        bot.register_next_step_handler(msg, step_get_guide_url)

def step_get_custom_topup(message):
    try:
        amount = float(message.text)
        if 1 <= amount <= 10000:
            show_topup_confirm(message.chat.id, amount)
        else:
            msg = bot.send_message(message.chat.id, "❌ <b>Invalid Amount!</b> Please enter an amount between <b>₹1</b> and <b>₹10,000</b>.", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_get_custom_topup)
    except ValueError:
        msg = bot.send_message(message.chat.id, "❌ Please enter a valid numerical amount (e.g., 250):")
        bot.register_next_step_handler(msg, step_get_custom_topup)

def _extract_premium_emoji_ids(message):
    """Return Premium custom emoji IDs found in a Telegram message, in order."""
    ids = []
    try:
        for ent in (getattr(message, "entities", None) or []):
            if getattr(ent, "type", None) == "custom_emoji":
                emoji_id = getattr(ent, "custom_emoji_id", None)
                if emoji_id:
                    emoji_id = str(emoji_id)
                    if emoji_id not in ids:
                        ids.append(emoji_id)
    except Exception:
        pass
    return ids


def show_hack_price_ui_catalog(chat_id, message_id=None):
    """Product-first Premium Design screen; each Product reveals its Plans."""
    products = get_unique_products()
    # Products are intentionally arranged in one column for a clean mobile layout.
    markup = types.InlineKeyboardMarkup(row_width=2)
    if not products:
        text = "⚠️ <b>NO PRODUCTS FOUND</b>\n\nAdd a Product & Plan first."
    else:
        catalog = {}
        for index, product_name in enumerate(products, 1):
            h = _ui_hash(product_name); catalog[h] = product_name
            plans = get_product_plans(product_name)
            configured = sum(1 for plan in plans if get_button_emoji(f"price:{product_name}:{plan[0]}"))
            palette = ("blue", "green", "blue", "green", "red")
            button = make_ui_button(
                f"{'✨' if configured else '⚪'} {index:02d} · {product_name} · {len(plans)} Plan(s)",
                callback_data=f"hpui_select_{h}",
                button_key=f"hack:{product_name}",
                default_color=palette[(index - 1) % len(palette)],
                force_style=True,
                force_premium=True
            )
            if index % 2 == 1:
                markup.row(button)
            else:
                # Replace the temporary single-button row with an explicit pair.
                previous = markup.keyboard[-1]
                previous.append(button)
        admin_temp_data.setdefault(chat_id, {})['hack_price_ui_catalog'] = catalog
        text = ("🎨 <b>HACK PRICE LIST — PREMIUM DESIGN</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
                "<i>Select a Product to manage its Plans.</i>\n\n"
                "✨ Each Plan can have its own Premium custom emoji.\n"
                "📝 Product title/header design remains separate.")
    _ensure_admin_back_button(markup)
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, parse_mode='HTML', reply_markup=markup)
            _admin_store_snapshot(chat_id,text,markup,"admin_hack_price_ui")
            return
        except Exception: pass
    bot.send_message(chat_id, text, parse_mode='HTML', reply_markup=markup)
    _admin_store_snapshot(chat_id,text,markup,"admin_hack_price_ui")


def step_save_hack_price_ui_title(message):
    """Compatibility entry point: now accepts the complete design in ONE message."""
    user_id = message.from_user.id
    data = admin_temp_data.get(user_id, {})
    product_name = data.get("hack_price_ui_product")
    if not product_name:
        bot.send_message(message.chat.id, "❌ Session expired. Please open Price List Fix — Emoji & Text again.")
        return
    raw = _message_html_text(message).strip()
    if not raw:
        bot.send_message(message.chat.id, "❌ Please send the complete price-list design in one message.")
        return
    # Validate that the message contains the dynamic labels we need.
    plain = re.sub(r'<[^>]+>', '', raw).lower()
    if not all(x in plain for x in ('validity', 'stock', 'price')):
        bot.send_message(
            message.chat.id,
            "❌ Your design must contain the words <b>Validity</b>, <b>Stock</b> and <b>Price</b> so the bot can inject live values automatically.",
            parse_mode="HTML"
        )
        return
    set_hack_price_ui_template(product_name, raw)
    admin_temp_data.pop(user_id, None)
    bot.send_message(
        message.chat.id,
        "✅ <b>Price List Fix Saved!</b>\n\n"
        f"🛒 <b>Hack:</b> {html.escape(product_name)}\n"
        "✨ Your Premium emojis and custom text are saved exactly as sent.\n"
        "📦 Plans/prices are automatic.\n"
        "📊 Manual / Auto-API stock is automatic.\n"
        "❌ Out of Stock is automatic.\n"
        "🏷️ Discounts are automatic.\n\n"
        "Old normal price-list text is no longer used for this hack.",
        parse_mode="HTML"
    )


def step_save_hack_price_ui_emojis(message):
    # Kept for backward compatibility with old pending sessions. New sessions use
    # step_save_hack_price_ui_title and save the whole design in one message.
    return step_save_hack_price_ui_title(message)

def _admin_success_send(chat_id, text, parse_mode="HTML", reply_markup=None):
    """Show the success result, then return exactly one Admin level.

    Older code reopened only the broad Admin category, which forced the admin to
    repeatedly enter the same editor/catalog.  The fine-grained pending context
    now returns to the immediate parent screen instead.
    """
    try:
        result = bot.send_message(chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception:
        result = None

    try:
        # If this save came from a multi-step Admin editor, return exactly one
        # level to the screen that opened the input. Never jump through the
        # Main Admin Panel unless no parent context exists.
        if int(chat_id) in admin_pending_return:
            ctx = dict(admin_pending_return.get(int(chat_id)) or {})
            cb = str(ctx.get("callback") or "")
            # These workflows have an exact one-level parent. Render it directly
            # instead of restoring a stale snapshot from before the input step.
            if (cb == "admin_all_button_emoji" or cb.startswith("pp_hack_") or
                    cb == "pp_hack_direct" or cb.startswith("pp_keys_")):
                _render_admin_parent_screen(chat_id, chat_id)
            else:
                restored=_admin_restore_snapshot_by_chat(chat_id,int(chat_id))
                admin_pending_return.pop(int(chat_id),None)
                if not restored:
                    _render_admin_parent_screen(chat_id, chat_id)
        else:
            _send_admin_panel_after_success(chat_id, user_id=chat_id)
    except Exception:
        pass
    return result


def step_save_premium_emoji(message):
    user_id = message.from_user.id
    target = admin_temp_data.get(user_id, {}).get("emoji_target")
    emoji_id = None
    try:
        entities = getattr(message, "entities", None) or []
        for ent in entities:
            if getattr(ent, "type", None) == "custom_emoji" and getattr(ent, "custom_emoji_id", None):
                emoji_id = str(ent.custom_emoji_id)
                break
    except Exception:
        pass

    if not emoji_id:
        bot.send_message(
            message.chat.id,
            "❌ I couldn't detect a Premium custom emoji. Please send exactly one Premium custom emoji."
        )
        return

    if target == "price_expiry":
        set_setting("price_expiry_emoji", emoji_id)
    elif target == "bulk_product_buttons":
        keys = _get_product_button_keys()
        set_bulk_button_emoji(keys, emoji_id)
    elif target == "bulk_price_buttons":
        keys = _get_price_button_keys()
        set_bulk_button_emoji(keys, emoji_id)
    elif target:
        set_button_emoji(target, emoji_id)
    else:
        bot.send_message(message.chat.id, "❌ Emoji target expired. Please open All Button Emoji again.")
        return

    if target == "bulk_product_buttons":
        saved_scope = f"all {len(_get_product_button_keys())} product buttons"
    elif target == "bulk_price_buttons":
        saved_scope = f"all {len(_get_price_button_keys())} price-list buttons"
    elif target == "price_expiry":
        saved_scope = "Price List expiry lines"
    else:
        saved_scope = "the selected button"

    _admin_success_send(
        message.chat.id,
        "✅ <b>Premium Emoji Saved!</b>\n\n"
        f"Applied to <b>{saved_scope}</b>.\n"
        "Old normal leading button emojis are automatically hidden, so the Premium emoji is shown instead.",
        parse_mode="HTML"
    )
    admin_temp_data.setdefault(user_id, {}).pop("emoji_target", None)

def step_save_product_plan_text(message):
    user_id = message.from_user.id
    product_name = admin_temp_data.get(user_id, {}).get('plan_text_product')
    raw = _message_html_text(message).strip()
    if not product_name:
        bot.send_message(message.chat.id, "❌ Product selection expired. Open All Product Plan Text again.", parse_mode="HTML")
        return
    if not raw:
        bot.send_message(message.chat.id, "❌ No text received. Please send the custom text + Premium emoji again.", parse_mode="HTML")
        return
    # Save the exact HTML design, including Telegram Premium custom-emoji
    # <tg-emoji> tags. The setter also stores a migration-safe last-template alias.
    cleaned = _repair_premium_emoji_markup(raw)
    set_plan_text_product(product_name, cleaned)
    admin_temp_data[user_id] = {}
    _admin_success_send(
        message.chat.id,
        "✅ <b>PRODUCT PLAN TEXT SAVED!</b>\n\n"
        f"🛒 <b>Hack:</b> {html.escape(product_name)}\n"
        "✨ Your Premium text/emoji is now the only custom price-list text for this hack.\n"
        "🤖 Days + API/Manual/Out-of-Stock status + live price are automatic.\n"
        "🧹 Old duplicated price-list/header text is not appended.",
        parse_mode="HTML"
    )


def step_save_plan_text_add(message):
    """Save the admin's custom text/header with Premium custom emojis.

    This intentionally accepts ANY text. The bot does not require Validity/Stock/Price
    lines here because those live values are generated automatically from the DB below
    the custom text."""
    user_id = message.from_user.id
    raw = _message_html_text(message).strip()
    if not raw:
        bot.send_message(
            message.chat.id,
            "❌ <b>No text received.</b> Please send the Plan Text again with your Premium emoji(s).",
            parse_mode="HTML"
        )
        return

    # Save exactly what the admin sent. No legacy price-list/sample rows are required.
    set_plan_text_add(raw)

    bot.send_message(
        message.chat.id,
        "✅ <b>PLAN TEXT SAVED!</b>\n\n"
        "📝 Your custom text + Premium emoji(s) will now appear above the live plan buttons.\n"
        "🧹 Old Plans & Pricing / Choose a Plan / legacy plan text is no longer shown.\n"
        "🤖 Days, live price, Manual/API stock and Out of Stock status remain automatic.\n\n"
        "You can send a new text anytime from the same <b>Plan Text Add + Premium Emoji</b> button.",
        parse_mode="HTML"
    )


def step_save_global_price_list_template(message):
    """Save one master price-list design containing optional Premium emojis.

    The admin can type/paste formatted Telegram text with Premium custom emojis.
    The live DB pricing is injected automatically through {pricing_info}; old
    manually typed plan rows are removed so each hack gets its own current plans.
    """
    user_id = message.from_user.id
    if not _is_admin(user_id):
        return

    try:
        raw = _message_html_text(message).strip()
        if not raw:
            bot.send_message(message.chat.id, "❌ Please send the price-list text (with Premium emoji if needed).")
            return

        normalized = _strip_legacy_price_list_block(raw)
        set_global_price_list_template(normalized)
        # Saving the master design explicitly enables Premium Price List Mode.
        set_price_list_premium_mode(True)

        # Refresh saved product/plan colors so the new template is immediately used
        # on every hack without touching product prices or plans.
        sync_all_product_button_colors()

        _admin_success_send(
            message.chat.id,
            "✅ <b>All Panel Price & Emojis Saved!</b>\n\n"
            "• Premium custom emojis are preserved.\n"
            "• Old duplicated/manual price rows are removed from the template.\n"
            "• Every hack automatically injects its own Admin-configured plans/prices.\n"
            "• Stock automatically shows Manual stock when manual keys exist, otherwise Auto-API.\n"
            "• Discounted hacks stay Green; normal hacks stay Blue.\n\n"
            "Use <code>{pricing_info}</code> anywhere you want the live price list inserted.",
            parse_mode="HTML"
        )
        admin_temp_data.setdefault(user_id, {}).pop('global_price_list_edit', None)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Could not save the master price-list template: <code>{html.escape(str(e))}</code>", parse_mode="HTML")


def _save_order_history_premium_ids(template):
    """Persist the exact Premium custom-emoji occurrence order for Order History.

    The HTML template is the primary source of truth. This ordered cache is only
    a recovery mechanism. IDs are intentionally NOT deduplicated.
    """
    ids = _premium_emoji_ids_from_template(template, unique=False)
    if ids:
        set_setting("order_history_premium_emoji_ids", json.dumps(ids, ensure_ascii=False))
    return ids


def _get_saved_order_history_premium_ids():
    try:
        ids = json.loads(get_setting("order_history_premium_emoji_ids") or "[]")
        return [str(x) for x in ids if str(x).strip()]
    except Exception:
        return []


def _build_order_history_premium_fallback(ids):
    """Build a Premium Order History design when only saved IDs are available.

    Many templates use a normal Unicode emoji for the title (ALL HISTORY) and
    Premium emojis only for the eight live/account fields. Older fallback code
    assumed ID #0 belonged to the title and shifted every following icon by one
    position. The saved 8-ID layout is therefore:
    spent, deposited, recent-orders, order-id, product, price, date/time, key.

    When a complete admin template exists, that template is ALWAYS the source of
    truth. This fallback is used only when the template itself is unavailable.
    """
    ids = [str(x).strip() for x in (ids or []) if str(x).strip()]
    if len(ids) < 8:
        return ""

    if len(ids) == 8:
        offset = 0
        title = '📜'
    else:
        offset = 1
        title = _premium_emoji_html(ids[0], '📜')

    e = lambda i, fallback: _premium_emoji_html(ids[i + offset], fallback) if i + offset < len(ids) else fallback

    return (
        f"{title} <b>ALL HISTORY</b>\n"
        f"────────────────────────\n"
        f"├── {e(0, '💎')} <b>Total spent:</b> ₹{{lifetime}} INR ({{orders}} orders)\n"
        f"└── {e(1, '📥')} <b>Total deposited:</b> ₹{{deposited}} INR\n\n"
        f"{e(2, '🛍️')} <b>Recent Orders</b>\n"
        f"────────────────────────\n"
        f"{e(3, '✅')} <b>{{order_id}}</b>\n"
        f"├── {e(4, '📦')} <b>{{product_name}}</b> · <i>{{days}}</i>\n"
        f"├── {e(5, '💰')} <b>{{price}}</b>\n"
        f"├── {e(6, '⏰')} <b>{{date_time}}</b>\n"
        f"└── {e(7, '🔑')} <code>{{key}}</code>\n"
    )



def step_save_wallet_topup_success_template(message):
    """Save the Add Balance/Wallet Top-Up success visual design."""
    user_id = message.from_user.id
    if not _is_admin(user_id):
        return

    raw = _message_html_text(message).strip()
    if not raw:
        bot.send_message(
            message.chat.id,
            "❌ No Wallet Balance Success design received. Send the complete success layout with at least one Premium custom emoji.",
            parse_mode="HTML",
        )
        return

    premium_ids = _premium_emoji_ids_from_template(raw, unique=False)
    if not premium_ids:
        bot.send_message(
            message.chat.id,
            "❌ I couldn't detect any Premium custom emoji. Please send the Wallet Balance Success layout containing your Premium emoji(s).",
            parse_mode="HTML",
        )
        return

    set_wallet_topup_success_emoji_template(raw)
    admin_temp_data.setdefault(user_id, {}).pop("text_key", None)

    bot.send_message(
        message.chat.id,
        "✅ <b>Wallet Balance Success Premium Emoji/Text Design Saved!</b>\n\n"
        f"✨ <b>{len(premium_ids)} Premium emoji occurrence(s)</b> saved in exact order/position.\n"
        "🤖 Username, Telegram ID, Order ID, Amount, UTR and Current Balance remain live automatically.\n"
        "💰 Balance is still credited by the existing payment-verification system.\n"
        "🛡️ Existing payment/checkout logic was not removed.",
        parse_mode="HTML",
    )
    admin_temp_data.pop(user_id, None)


def step_save_wallet_payment_template(message):
    """Save the Wallet success visual design with Telegram Premium emojis."""
    _save_payment_success_emoji_template(
        message,
        payment_type="wallet",
        setter=set_wallet_payment_emoji_template,
        title="Wallet Payment",
    )


def step_save_upi_payment_template(message):
    """Save the UPI success visual design with Telegram Premium emojis."""
    _save_payment_success_emoji_template(
        message,
        payment_type="upi",
        setter=set_upi_payment_emoji_template,
        title="UPI Payment",
    )


def _save_payment_success_emoji_template(message, payment_type, setter, title):
    """Shared validator/saver for separate Wallet and UPI success templates."""
    user_id = message.from_user.id
    if not _is_admin(user_id):
        return

    raw = _message_html_text(message).strip()
    if not raw:
        bot.send_message(
            message.chat.id,
            f"❌ No {title} design received. Send the complete success layout with at least one Premium custom emoji.",
            parse_mode="HTML",
        )
        return

    premium_ids = _premium_emoji_ids_from_template(raw, unique=False)
    if not premium_ids:
        bot.send_message(
            message.chat.id,
            "❌ I couldn't detect any Premium custom emoji. Please send the payment layout containing your Premium emoji(s).",
            parse_mode="HTML",
        )
        return

    setter(raw)
    admin_temp_data.setdefault(user_id, {}).pop("text_key", None)

    method_text = "Wallet Method" if payment_type == "wallet" else "UPI Method"
    bot.send_message(
        message.chat.id,
        f"✅ <b>{title} Premium Emoji/Text Design Saved!</b>\n\n"
        f"✨ <b>{len(premium_ids)} Premium emoji occurrence(s)</b> saved in exact order/position.\n"
        "🤖 User ID, Order ID, Product ID, Product, Plan, Amount and Key remain live.\n"
        f"💳 Payment method is automatically shown as <b>{method_text}</b>.\n"
        "🔑 The delivered key remains inside <code>&lt;code&gt;</code> so Telegram can copy it on tap.\n"
        "🛡️ Existing payment/checkout logic was not removed.",
        parse_mode="HTML",
    )
    admin_temp_data.pop(user_id, None)


def step_save_welcome_message(message):
    if not _is_admin(message.from_user.id): return
    text=_message_html_text(message)
    if not text.strip():
        bot.send_message(message.chat.id,"❌ Welcome Message cannot be empty.")
        return
    set_welcome_message_template(text)
    _admin_success_send(message.chat.id,"✅ <b>Welcome Message Updated Successfully!</b>",parse_mode="HTML")
    admin_temp_data.pop(message.from_user.id,None)


def step_save_custom_text(message):
    user_id = message.from_user.id
    t_key = admin_temp_data[user_id]['text_key']
    t_val = _message_html_text(message).strip()

    if t_key == "order_history":
        # IMPORTANT: save Telegram Premium custom-emoji IDs together with the
        # exact HTML template. This prevents a later render from falling back to
        # normal Unicode emoji.
        t_val = _repair_premium_emoji_markup(t_val)
        ids = _save_order_history_premium_ids(t_val)
        set_setting("custom_text_order_history", t_val)
        bot.send_message(
            message.chat.id,
            "✅ <b>Text Updated Successfully for ID:</b> <code>order_history</code>\n\n"
            f"✨ <b>{len(ids)} Premium emoji ID(s) saved.</b>\n"
            "They will be restored automatically and the exact emoji positions will be preserved for every user's live orders.",
            parse_mode="HTML"
        )
        del admin_temp_data[user_id]
        return

    if t_key == "top_up":
        # Save Add Balance designs into the new dedicated key. This keeps the
        # old Add Balance sample/template from returning while preserving it
        # in the database for backward compatibility.
        t_val = _repair_premium_emoji_markup(t_val)
        if not _premium_emoji_ids_from_template(t_val, unique=False):
            # Some pyTelegramBotAPI versions expose the visible fallback in
            # html_text but still provide the real custom_emoji entities.
            # Rebuild once directly from Telegram's message entities so the
            # Premium IDs are not lost when the template is saved.
            try:
                t_val = _message_html_text(message).strip()
            except Exception:
                pass
            t_val = _repair_premium_emoji_markup(t_val)
        set_add_balance_text_template(t_val)
        _admin_success_send(
            message.chat.id,
            "✅ <b>Add Balance Text Updated Successfully!</b>\n\n"
            "✨ Premium custom emojis and your layout are saved.\n"
            "💰 Balance, amount, minimum ₹1 and maximum ₹10,000 stay live automatically.",
            parse_mode="HTML"
        )
        del admin_temp_data[user_id]
        return

    if t_key == "top_up_qr":
        # Dedicated Add Balance QR template. It is separate from the product QR
        # template so admins can style top-ups without affecting checkout.
        set_add_balance_qr_text_template(t_val)
        _admin_success_send(
            message.chat.id,
            "✅ <b>Add Balance QR Text Updated Successfully!</b>\n\n"
            "✨ Premium custom emojis and the complete QR layout are saved.\n"
            "💵 Add Amount and 🆔 Order ID are injected live for every top-up.\n"
            "⚡ Existing QR generation and auto-verification are unchanged.",
            parse_mode="HTML"
        )
        del admin_temp_data[user_id]
        return

    if t_key == "reseller_activation":
        set_setting('reseller_discount_activation_text', _repair_premium_emoji_markup(t_val))
        _admin_success_send(message.chat.id, "✅ <b>Reseller Discount Activation Text Updated!</b>\n\n✨ Premium custom emojis are saved.\n💰 Amount, 👤 User and 🆔 Order ID remain live automatically.", parse_mode="HTML")
        del admin_temp_data[user_id]
        return

    if t_key == "coupon_success":
        set_setting('coupon_payment_success_text', _repair_premium_emoji_markup(t_val))
        _admin_success_send(message.chat.id, "✅ <b>Coupon Payment Success Text Updated!</b>\n\n✨ Premium custom emojis are saved. Product, Plan, Price and Key remain live automatically.", parse_mode="HTML")
        del admin_temp_data[user_id]
        return

    if t_key == "coupon_failed":
        set_setting('coupon_payment_failed_text', _repair_premium_emoji_markup(t_val))
        _admin_success_send(message.chat.id, "✅ <b>Coupon Payment Failed Text Updated!</b>\n\n✨ Premium custom emojis are saved. The failure reason remains live automatically.", parse_mode="HTML")
        del admin_temp_data[user_id]
        return

    if t_key == "qr_payment":
        set_qr_payment_text(t_val)
        bot.send_message(
            message.chat.id,
            "✅ <b>QR BELOW TEXT UPDATED!</b>\n\n"
            "✨ Your text + Premium emoji(s) will now appear directly below every purchase QR.\n"
            "🔄 Hack name, plan, amount, purchase date and Order ID remain live and unique for each buyer.",
            parse_mode="HTML"
        )
        del admin_temp_data[user_id]
        return

    if t_key == "price_list":
        t_val = _strip_legacy_price_list_block(t_val)
        if not any(token in t_val for token in ("{pricing_info}", "{price_list}", "{prices}", "{default_price_list}")):
            t_val = t_val.rstrip() + "\n\n{pricing_info}"
        set_global_price_list_template(t_val)
        set_price_list_premium_mode(True)

    set_setting(f"custom_text_{t_key}", t_val)
    _admin_success_send(message.chat.id, f"✅ <b>Text Updated Successfully for ID:</b> <code>{t_key}</code>", parse_mode="HTML")
    del admin_temp_data[user_id]


def step_save_special_button_design(message):
    user_id = message.from_user.id
    button_key = admin_temp_data.get(user_id, {}).get("special_button_design")
    mapping = {
        ADD_BALANCE_CANCEL_BUTTON_KEY: "Add Balance Cancel",
        ADD_BALANCE_CONFIRM_BUTTON_KEY: "Add Balance Confirm",
        ALL_PRODUCTS_OUT_OF_STOCK_BUTTON_KEY: "All Products Out of Stock",
    }
    if button_key not in mapping:
        bot.send_message(message.chat.id, "❌ Button editing session expired. Please open the Button Section again.")
        return
    _save_special_button_design(message, button_key, mapping[button_key])
    admin_temp_data.pop(user_id, None)


def step_save_custom_btn(message):
    user_id = message.from_user.id
    b_key = admin_temp_data[user_id]['btn_key']
    b_val = message.text.strip()
    set_setting(f"custom_btn_{b_key}", b_val)
    _admin_success_send(message.chat.id, f"✅ <b>Button Name/Emoji Updated Successfully for:</b> <code>{b_key}</code>", parse_mode="HTML")
    del admin_temp_data[user_id]

def step_get_device_id_input(message):
    user_id = message.from_user.id
    if user_id not in admin_temp_data or 'checkout_pid' not in admin_temp_data[user_id]:
        bot.send_message(message.chat.id, "❌ Session expired. Please try purchasing again.")
        return

    dev_id = message.text.strip() if message.text else ""

    if dev_id.startswith('/') or dev_id.lower() in ['start', '/start', 'cancel', 'menu']:
        del admin_temp_data[user_id]
        if dev_id.lower() in ['/start', 'start']:
            send_welcome(message)
        else:
            bot.send_message(message.chat.id, "❌ <b>Purchase Cancelled!</b> Invalid Device ID provided.", parse_mode="HTML")
            show_shop_features(message.chat.id, message.from_user.first_name or "User")
        return

    product_id = admin_temp_data[user_id]['checkout_pid']
    
    del admin_temp_data[user_id]
    show_order_summary(
        message.chat.id, product_id, device_id=dev_id,
        username=getattr(message.from_user, 'username', None)
    )

# ==================== MAIN SHOP UI SCREENS ====================

def _fast_callback_ack(call):
    """Acknowledge a callback immediately so Telegram clients do not feel stuck."""
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass


def _run_user_task_async(target, *args, **kwargs):
    """Run slow user-facing work in a shared background pool.

    A bounded shared pool is faster and safer for many simultaneous users than
    creating a brand-new OS thread for every button tap. Callback workers stay
    free for all users while payment/API requests run concurrently.
    """
    def _runner():
        try:
            target(*args, **kwargs)
        except Exception as exc:
            print(f"[ASYNC USER TASK ERROR] {getattr(target, '__name__', str(target))}: {exc}")

    try:
        return USER_TASK_EXECUTOR.submit(_runner)
    except Exception as exc:
        print(f"[ASYNC EXECUTOR ERROR] {exc}")
        try:
            threading.Thread(target=_runner, daemon=True, name="rg-user-fallback").start()
        except Exception:
            pass
        return None

def _run_payment_task_async(target, *args, **kwargs):
    """Run payment/key/API work in the dedicated payment executor."""
    def _runner():
        try:
            target(*args, **kwargs)
        except Exception as exc:
            print(
                f"[ASYNC PAYMENT TASK ERROR] "
                f"{getattr(target, '__name__', str(target))}: {exc}"
            )

    try:
        return PAYMENT_TASK_EXECUTOR.submit(_runner)
    except Exception as exc:
        print(f"[ASYNC PAYMENT EXECUTOR ERROR] {exc}")
        try:
            threading.Thread(
                target=_runner,
                daemon=True,
                name="rg-payment-fallback",
            ).start()
        except Exception:
            pass
        return None


def _sanitize_inline_markup_for_transport(markup):
    """Build a transport-safe copy of an inline keyboard."""
    safe = types.InlineKeyboardMarkup()
    try:
        rows = getattr(markup, "keyboard", None) or []
        for row in rows:
            safe_row = []
            for button in (row or []):
                text = str(getattr(button, "text", "") or "")
                callback_data = getattr(button, "callback_data", None)
                url = getattr(button, "url", None)
                try:
                    if callback_data is not None:
                        safe_button = types.InlineKeyboardButton(
                            text=text, callback_data=str(callback_data)
                        )
                    elif url is not None:
                        safe_button = types.InlineKeyboardButton(
                            text=text, url=str(url)
                        )
                    else:
                        safe_button = types.InlineKeyboardButton(text=text)
                except Exception:
                    continue
                safe_row.append(safe_button)
            if safe_row:
                safe.keyboard.append(safe_row)
    except Exception:
        return types.InlineKeyboardMarkup()
    return safe


def render_or_edit(chat_id, message_id, text, markup):
    """Render a screen with layered Telegram-safe fallbacks.

    Normal Premium styling is attempted first. If Telegram rejects the
    message because of HTML, a custom emoji, or a button style/icon,
    the same screen is retried with a transport-safe keyboard.
    """
    if not get_price_list_premium_mode():
        text = re.sub(
            r'<tg-emoji\b[^>]*>(.*?)</tg-emoji>',
            lambda m: m.group(1),
            str(text),
            flags=re.I | re.S,
        )

    original_text = str(text)
    repaired = _repair_telegram_html_markup(
        _repair_premium_emoji_markup(original_text)
    )

    safe_markup = _sanitize_inline_markup_for_transport(markup)
    plain_text = re.sub(
        r'<tg-emoji\b[^>]*>(.*?)</tg-emoji>',
        lambda m: m.group(1),
        repaired,
        flags=re.I | re.S,
    )
    plain_text = re.sub(r'<[^>]+>', '', plain_text)
    plain_text = html.unescape(plain_text).replace("\r\n", "\n").replace("\r", "\n")

    attempts = [
        (original_text, markup, True),
        (repaired, markup, True),
        (repaired, safe_markup, True),
        (plain_text, safe_markup, False),
    ]

    first_error = None
    for payload, reply_markup, use_html in attempts:
        try:
            if message_id:
                if use_html:
                    return bot.edit_message_text(
                        payload, chat_id, message_id,
                        parse_mode="HTML", reply_markup=reply_markup
                    )
                return bot.edit_message_text(
                    payload, chat_id, message_id, reply_markup=reply_markup
                )
            if use_html:
                return bot.send_message(
                    chat_id, payload,
                    parse_mode="HTML", reply_markup=reply_markup
                )
            return bot.send_message(chat_id, payload, reply_markup=reply_markup)
        except Exception as exc:
            if first_error is None:
                first_error = exc

    # Final emergency fallback: keep the screen alive even if the keyboard
    # itself is rejected. Never re-raise into the checkout worker.
    try:
        if message_id:
            return bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=plain_text)
        return bot.send_message(chat_id, plain_text)
    except Exception as final_error:
        print(
            f"[UI RENDER ERROR] chat={chat_id} message={message_id}: "
            f"{final_error}"
        )
        return None



def show_shop_features(chat_id, first_name, message_id=None):
    default_shop_text = (
        f"🛍️ <b>{html.escape(BOT_BRAND_NAME)}</b>\n"
        f"────────────────────────\n"
        f"👋 <i>Hello, <b>{first_name}</b>!</i>\n\n"
        f"🧡 — <b>SHOP FEATURES</b> — 🧡\n\n"
        f"├── 🔑 <b>Premium Cheats Keys</b>\n"
        f"├── ⚡ <b>Instant Delivery 24/7</b>\n"
        f"├── 🔒 <b>100% Secure Payment</b>\n"
        f"├── 🕊️ <b>Best Prices Guaranteed</b>\n"
        f"├── 🎁 <b>Invite Referral Rewards</b>\n"
        f"└── 🎭 <b>Android Root Service</b>\n\n"
        f"────────────────────────\n"
        f"🚀 <b>Click Open Store to Start!</b>"
    )
    shop_template = get_custom_text("main_menu", default_shop_text)
    shop_values = _get_user_template_values(chat_id, first_name)
    shop_values.update({
        "user": shop_values["name"],
        "telegram_id": str(chat_id),
        "number": shop_values["phone"],
        "first_name": shop_values["name"],
    })
    shop_text = _safe_format_custom_text(shop_template, **shop_values)
    shop_text = _inject_labeled_user_values(shop_text, shop_values)
    shop_text = _replace_live_greeting_name(shop_text, shop_values.get("name") or first_name)
    
    markup = types.InlineKeyboardMarkup()
    btn_open_store = make_ui_button(get_custom_btn("open_store", "🛍️ Open Store"), callback_data="open_store", button_key="main:open_store", default_color=DEFAULT_MAIN_BUTTON_COLORS["open_store"])
    btn_top_up = make_ui_button(get_custom_btn("top_up", "💰 Top Up"), callback_data="top_up", button_key="main:top_up", default_color=DEFAULT_MAIN_BUTTON_COLORS["top_up"])
    btn_orders = make_ui_button(get_custom_btn("orders", "📜 Orders"), callback_data="orders", button_key="main:orders", default_color=DEFAULT_MAIN_BUTTON_COLORS["orders"])
    btn_my_account = make_ui_button(get_custom_btn("my_account", "👤 My Account"), callback_data="my_account", button_key="main:my_account", default_color=DEFAULT_MAIN_BUTTON_COLORS["my_account"])
    btn_invite_earn = make_ui_button(get_custom_btn("invite_earn", "🎁 Invite & Earn"), callback_data="invite_earn", button_key="main:invite_earn", default_color=DEFAULT_MAIN_BUTTON_COLORS["invite_earn"])
    btn_how_to_use = make_ui_button(get_custom_btn("how_to_use", "🎬 How To Use Bot"), callback_data="how_to_use_bot", button_key="main:how_to_use", default_color=DEFAULT_MAIN_BUTTON_COLORS["how_to_use"])
    update_url = str(get_update_channel_link() or '').strip()
    # Telegram rejects an InlineKeyboard when any URL button contains an empty
    # or malformed URL. That used to make the whole User Panel keyboard vanish.
    btn_all_update = None
    if update_url.startswith(('https://', 'http://', 'tg://')):
        btn_all_update = make_ui_button("📢 All Update File", url=update_url, button_key="main:all_update", default_color=DEFAULT_MAIN_BUTTON_COLORS["all_update"])
    btn_help_desk = make_ui_button(get_custom_btn("help_desk", "📞 Help Desk"), callback_data="help_desk", button_key="main:help_desk", default_color=DEFAULT_MAIN_BUTTON_COLORS["help_desk"])
    reseller_btn = _reseller_discount_markup() if _reseller_discount_active() and not int((get_user(chat_id) or [0]*12)[11] or 0) else None
    
    markup.add(btn_open_store)
    markup.add(btn_top_up, btn_orders)
    markup.add(btn_my_account, btn_invite_earn)
    if btn_all_update is not None:
        markup.add(btn_how_to_use, btn_all_update)
    else:
        markup.add(btn_how_to_use)
    if reseller_btn is not None:
        markup.add(reseller_btn)
    markup.add(btn_help_desk)
    
    render_or_edit(chat_id, message_id, shop_text, markup)

def get_product_discount_percent(product_name):
    """Return the store-wide/hack discount that controls product UI color."""
    try:
        global_disc = float(get_setting('global_discount') or '0')
    except Exception:
        global_disc = 0.0
    try:
        plans = get_product_plans(product_name)
        product_disc = max([float(p[6] or 0) for p in plans] or [0.0])
    except Exception:
        product_disc = 0.0
    return max(global_disc, product_disc)


def get_product_button_default_color(product_name):
    return "green" if get_product_discount_percent(product_name) > 0 else "blue"


def sync_product_button_colors(product_name):
    """Apply discount defaults without overwriting an admin's manual colors."""
    color = get_product_button_default_color(product_name)
    hack_key = f"hack:{product_name}"
    if get_setting(_style_setting_key(hack_key)) not in ("red", "blue", "green"):
        set_button_style(hack_key, color)
    for plan in get_product_plans(product_name):
        plan_key = f"price:{product_name}:{plan[0]}"
        if get_setting(_style_setting_key(plan_key)) not in ("red", "blue", "green"):
            set_button_style(plan_key, color)


def sync_all_product_button_colors():
    for product_name in get_unique_products():
        sync_product_button_colors(product_name)


def _strip_legacy_price_list_block(template):
    """Normalize a price-list template without duplicating the live DB price list.

    Admin-entered text is treated as the design/header. The actual plans, prices,
    stock state and discount labels always come from the products table through
    {pricing_info}. A legacy hand-written plan block is removed while its heading
    and "Choose a plan" footer are preserved in the correct order.
    """
    if not template:
        return "{pricing_info}"

    lines = str(template).splitlines()
    out = []
    in_generated_block = False
    inserted_placeholder = False

    for line in lines:
        plain = re.sub(r'<[^>]+>', '', line).lower().strip()
        is_start = (
            'plans & pricing' in plain or
            'plans and pricing' in plain or
            'stock & pricing' in plain or
            'stock and pricing' in plain
        )
        is_end = (
            'choose a plan' in plain or
            'select your plan' in plain
        )

        if is_start and not in_generated_block:
            # Keep the admin's heading, but replace everything underneath it
            # with the single live placeholder.
            out.append(line)
            out.append('{pricing_info}')
            inserted_placeholder = True
            in_generated_block = True
            continue

        if in_generated_block:
            if is_end:
                out.append(line)
                in_generated_block = False
            # All other legacy pricing lines are intentionally discarded.
            continue

        # Avoid a second copy if the admin already used the placeholder.
        if line.strip() in ('{pricing_info}', '{price_list}', '{prices}', '{default_price_list}'):
            if not inserted_placeholder:
                out.append('{pricing_info}')
                inserted_placeholder = True
            continue
        out.append(line)

    cleaned = '\n'.join(out).strip()
    if not inserted_placeholder:
        if cleaned:
            # The global editor is a design template. Append live plans exactly once.
            cleaned = cleaned.rstrip() + '\n\n{pricing_info}'
        else:
            cleaned = '{pricing_info}'
    return cleaned


def show_open_store(chat_id, message_id=None):
    default_store_text = (
        f"🛍️ <b>{html.escape(BOT_BRAND_NAME)}</b>\n"
        f"────────────────────────\n"
        f"⭐ <b>Available Products</b>\n\n"
        f"├── 🔑 Premium Keys\n"
        f"├── ⚡ Instant Delivery\n"
        f"├── 🔒 Secure Payment\n"
        f"└── 🏆 24/7 Support\n\n"
        f"📦 <b>Choose your product below 👇</b>\n"
        f"<i>Tap any item to see plans & prices.</i>"
    )
    store_text = get_custom_text("store_menu", default_store_text)
    markup = types.InlineKeyboardMarkup()
    products = get_visible_products()
    if products:
        product_buttons = [
            make_ui_button(
                f"🛒 {prod}",
                callback_data=f"prod_{prod}",
                button_key=f"hack:{prod}",
                default_color=get_product_button_default_color(prod)
            )
            for prod in products
        ]
        # Product Store is intentionally single-column: every product appears
        # one after another, matching the requested clean mobile layout.
        SINGLE_COLUMN_PRODUCT_STORE = True
        if SINGLE_COLUMN_PRODUCT_STORE:
            for product_button in product_buttons:
                markup.add(product_button)
        else:
            # Original two-column renderer retained for backward compatibility.
            for i in range(0, len(product_buttons), 2):
                pair = product_buttons[i:i+2]
                markup.row(*pair)
    if _bot_make_enabled() and _bot_make_plan_rows():
        bot_make_btn = make_ui_button(
            '🤖 Bot Make', callback_data='prod_Bot Make',
            button_key='hack:Bot Make', default_color='blue', force_style=True
        )
        # Bot Make follows the same single-column product layout.
        SINGLE_COLUMN_PRODUCT_STORE = True
        if SINGLE_COLUMN_PRODUCT_STORE:
            markup.add(bot_make_btn)
        else:
            # Original compact-grid behavior retained as a compatibility fallback.
            if products and len(products) % 2 == 1:
                try:
                    if markup.keyboard and len(markup.keyboard[-1]) == 1:
                        markup.keyboard[-1].append(bot_make_btn)
                    else:
                        markup.add(bot_make_btn)
                except Exception:
                    markup.add(bot_make_btn)
            else:
                markup.add(bot_make_btn)
    if not products and not (_bot_make_enabled() and _bot_make_plan_rows()):
        store_text += "\n\n⚠️ <i>No active products added yet. Use /admin to add products.</i>"

    btn_back = make_ui_button("⬅️ Back to Main", callback_data="back_to_main", button_key="nav:back_main", default_color="blue")
    markup.add(btn_back)
    
    render_or_edit(chat_id, message_id, store_text, markup)

def show_product_plans(chat_id, product_name, message_id=None):
    if _product_hidden(product_name):
        try:
            bot.send_message(chat_id, '❌ <b>This product is currently hidden.</b>', parse_mode='HTML')
        except Exception:
            pass
        return
    plans = [p for p in get_product_plans(product_name) if not _plan_hidden(p[0])]
    user = get_user(chat_id)

    global_disc_val = float(get_setting('global_discount') or '0.0')
    user_disc_val = user[12] if user and len(user) > 12 else 0.0
    ref_disc_used = user[15] if user and len(user) > 15 else 0
    is_reseller = user[11] if user and len(user) > 11 else 0

    pricing_info = ""
    buttons = []

    premium_price_mode = get_price_list_premium_mode()
    hack_price_ui = get_hack_price_ui(product_name)

    # Keep the first three Premium emojis from the admin's design available
    # even when the renderer falls back to the generated price-list format.
    template_for_emoji = (
        hack_price_ui.get('template') if hack_price_ui and hack_price_ui.get('template')
        else (get_global_price_list_template() if premium_price_mode else None)
    )
    template_emoji_ids = _premium_emoji_ids_from_template(template_for_emoji)
    row_validity_emoji = _premium_emoji_html(template_emoji_ids[0], '⏳') if len(template_emoji_ids) > 0 else None
    row_stock_emoji = _premium_emoji_html(template_emoji_ids[1], '📦') if len(template_emoji_ids) > 1 else None
    row_price_emoji = _premium_emoji_html(template_emoji_ids[2], '💰') if len(template_emoji_ids) > 2 else None

    if hack_price_ui:
        expiry_emoji = _premium_emoji_html(hack_price_ui.get("day_emoji"), "⏳")
    elif premium_price_mode:
        expiry_emoji = _premium_emoji_html(get_setting("price_expiry_emoji"), "⏳")
    else:
        expiry_emoji = "⏳"

    product_ui_color = get_product_button_default_color(product_name)

    # One stock query for the entire price list instead of one DB query per plan.
    stock_counts = {} if str(product_name).strip().lower()==BOT_MAKE_PRODUCT_NAME.lower() else get_key_stock_counts(product_name, [str(plan[2] or '').strip() for plan in plans])

    live_rows = []

    for plan in plans:
        p_id, pid_id, days, reg_price, resell_price, is_manual, prod_disc_val, remote_dur, tg_link, is_oos, req_dev_id = plan[:11]
        raw_days = str(days or '').strip()
        days = _clean_plan_days(days)
        validity_label = _validity_display(raw_days)

        custom_price = get_custom_plan_price(chat_id, p_id)
        if is_reseller == 1 and custom_price["reseller_price"] is not None:
            final_price = custom_price["reseller_price"]; discount_tag = " <i>(Custom Reseller Rate)</i>"
        elif is_reseller == 0 and custom_price["user_price"] is not None:
            final_price = custom_price["user_price"]; discount_tag = " <i>(Custom User Rate)</i>"
        elif is_reseller == 1:
            final_price = resell_price; discount_tag = " <i>(Reseller Rate)</i>"
        else:
            base_price = reg_price
            effective_discount = max(global_disc_val, prod_disc_val)
            if user_disc_val > 0 and ref_disc_used == 0:
                effective_discount = max(effective_discount, user_disc_val)
            final_price = base_price * (1 - effective_discount / 100) if effective_discount > 0 else base_price
            discount_tag = f" <i>({effective_discount:.0f}% Off)</i>" if effective_discount > 0 else ""

        # Bot Make is a virtual/automatic product. It never consumes a manual
        # key, never depends on a reseller/API stock source, and must always be
        # purchasable whenever the Bot Make product/plan itself exists.  Keep
        # this special case BEFORE the normal Hack stock calculation so the
        # generic Out-of-Stock system can never mark Bot Make as OOS.
        if str(product_name).strip().lower() == BOT_MAKE_PRODUCT_NAME.lower():
            is_real_oos = False
            stock_status = "In Stock"
        else:
            stock_count = stock_counts.get(raw_days, 0)

            # Real stock is now determined only by an available manual FIFO key or
            # an explicitly connected/mapped Auto-API source. A Product ID by itself
            # is NOT considered stock, so newly-created products cannot accidentally
            # appear available before an API is connected.
            api_ready = _api_source_ready_for_plan(product_name, int(p_id), pid_id)
            if int(is_oos or 0) == 1:
                is_real_oos = True
                stock_status = "Out of Stock"
            elif stock_count > 0:
                is_real_oos = False
                stock_status = f"{stock_count} Available (Manual)"
            elif api_ready:
                is_real_oos = False
                stock_status = "In Stock (Auto-API)"
            else:
                is_real_oos = True
                stock_status = "Out of Stock"

        if is_real_oos:
            price_text = ""
            pricing_info += (
                f"❌ <b>{row_validity_emoji or expiry_emoji} {html.escape(validity_label)}</b>\n"
                f"├── {row_stock_emoji or '📦'} <b>Stock:</b> Out of Stock\n"
                f"└── {row_price_emoji or '💰'} <b>Price:</b>\n\n"
            )
            oos_label = _special_button_text(
                ALL_PRODUCTS_OUT_OF_STOCK_BUTTON_KEY,
                f"❌ {validity_label} - Out of Stock"
            )
            buttons.append(make_ui_button(
                oos_label,
                callback_data="out_of_stock_alert",
                button_key=ALL_PRODUCTS_OUT_OF_STOCK_BUTTON_KEY,
                default_color="red"
            ))
        else:
            price_text = f"₹{final_price:.2f} INR{discount_tag}"
            pricing_info += (
                f"{row_validity_emoji or expiry_emoji} <b>{html.escape(validity_label)}</b>\n"
                f"├── {row_stock_emoji or '📦'} <b>Stock:</b> {stock_status}\n"
                f"└── {row_price_emoji or '💰'} <b>Price:</b> {price_text}\n\n"
            )
            if str(product_name).strip().lower() == BOT_MAKE_PRODUCT_NAME.lower():
                buttons.append(make_ui_button(
                    f"🤖 Buy Bot - ₹{final_price:.2f}",
                    callback_data=f"checkout_{p_id}",
                    button_key=f"price:{product_name}:{p_id}",
                    default_color=product_ui_color,
                ))
            else:
                buttons.append(make_ui_button(
                    f"🛒 Buy {validity_label} - ₹{final_price:.2f}",
                    callback_data=f"checkout_{p_id}",
                    button_key=f"price:{product_name}:{p_id}",
                    default_color=product_ui_color
                ))

        live_rows.append({
            "days": raw_days,
            "validity": validity_label,
            "stock_status": stock_status,
            "price_text": price_text,
            "out_of_stock": is_real_oos,
        })

    default_plan_text = (
        f"🛒 <b>{html.escape(str(product_name))}</b>\n\n"
        f"📊 <b>STOCK &amp; PRICING :</b>\n\n"
        f"{pricing_info}"
        f"🎯 <b>CHOOSE A PLAN</b> 🎯"
    )

    # Per-product custom text has absolute priority. It replaces every old
    # header/price-list design for this hack. No legacy text is appended.
    product_plan_text = get_plan_text_product(product_name)
    if product_plan_text:
        plan_text = _render_plan_text_product(product_plan_text, live_rows, product_name)
    else:
        # Backward-compatible fallback for products not yet configured through
        # the new All Product Plan Text editor.
        plan_text_add = get_plan_text_add()
        if plan_text_add:
            custom_header = _safe_format_custom_text(
                plan_text_add,
                product_name=product_name,
                hack=product_name,
                pricing_info=pricing_info,
                price_list=pricing_info,
                prices=pricing_info,
                default_price_list=default_plan_text,
            )
            plan_text = custom_header.rstrip() + "\n\n" + pricing_info.strip()
        elif hack_price_ui and hack_price_ui.get('template'):
            rendered = _render_hack_price_ui_template(
                hack_price_ui.get('template'), live_rows, product_name
            )
            plan_text = rendered or pricing_info.strip()
        else:
            # No custom design: show only the live plan rows, without legacy
            # product/header/choose-a-plan text.
            plan_text = pricing_info.strip()

    markup = types.InlineKeyboardMarkup()
    for btn in buttons:
        markup.add(btn)
    # Always surface the configured Hack name at the top of its plan screen.
    # The Hack button's Premium custom emoji is reused automatically, so newly
    # created hacks inherit their configured design without code changes.
    plain_plan_text = re.sub(r'<[^>]+>', '', str(plan_text or ''))
    if str(product_name).strip().lower() not in plain_plan_text.lower():
        hack_emoji_id = get_button_emoji(f"hack:{product_name}")
        hack_emoji = _premium_emoji_html(hack_emoji_id, '🎮') if hack_emoji_id else '🎮'
        plan_text = f"{hack_emoji} <b>{html.escape(str(product_name))}</b>\n\n" + str(plan_text or '')

    markup.add(make_ui_button(
        "⬅️ Back to Store",
        callback_data="open_store",
        button_key="nav:back_store",
        default_color="blue"
    ))

    render_or_edit(chat_id, message_id, plan_text, markup)




# ==================== COUPON SYSTEM ====================
def _coupon_normalize(code):
    return re.sub(r"[^A-Za-z0-9_-]", "", str(code or "").strip()).upper()

def _create_coupon(amount, admin_id):
    amount=float(amount)
    if amount <= 0: return None
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        for _ in range(20):
            code='RG'+secrets.token_hex(5).upper()
            try:
                conn.execute('INSERT INTO coupons(code,amount,created_by,created_at,active) VALUES(?,?,?,?,1)',
                             (code,amount,int(admin_id),datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                conn.commit(); return code
            except sqlite3.IntegrityError:
                conn.rollback()
        return None
    finally: conn.close()

def _get_coupon(code):
    code=_coupon_normalize(code)
    if not code: return None
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        return conn.execute('SELECT code,amount,created_by,created_at,used_by,used_at,active FROM coupons WHERE code=?',(code,)).fetchone()
    finally: conn.close()

def _claim_coupon(code,user_id,required_amount):
    code=_coupon_normalize(code); required_amount=float(required_amount)
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        cur=conn.cursor(); cur.execute('BEGIN IMMEDIATE')
        row=cur.execute('SELECT amount,active,used_by FROM coupons WHERE code=?',(code,)).fetchone()
        if not row: conn.rollback(); return False,'Invalid coupon code.'
        amount,active,used_by=row
        if not int(active or 0) or int(used_by or 0): conn.rollback(); return False,'This coupon has already been used or is inactive.'
        if float(amount or 0) + 1e-9 < required_amount:
            conn.rollback(); return False,f'Coupon balance ₹{float(amount):.2f} is less than required ₹{required_amount:.2f}. Coupon + Wallet cannot be combined.'
        cur.execute('UPDATE coupons SET active=0,used_by=?,used_at=? WHERE code=? AND active=1 AND used_by=0',
                    (int(user_id),datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),code))
        if cur.rowcount != 1: conn.rollback(); return False,'Coupon could not be claimed. Please try again.'
        conn.commit(); return True,'OK'
    except Exception:
        conn.rollback(); return False,'Coupon processing error.'
    finally: conn.close()

def _restore_coupon(code,user_id):
    code=_coupon_normalize(code)
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        conn.execute('UPDATE coupons SET active=1,used_by=0,used_at=\'\' WHERE code=? AND used_by=?',(code,int(user_id)))
        conn.commit()
    finally: conn.close()

def _reseller_discount_activation_template():
    default = (
        '👑 <b>RESELLER DISCOUNT ACTIVATION</b>\n\n'
        '💰 <b>Activation Fee:</b> {amount}\n'
        '👤 <b>User:</b> {user}\n'
        '🆔 <b>Order ID:</b> <code>{order_id}</code>\n\n'
        '📱 Pay the exact amount using the QR above.\n'
        '⚡ After successful verification, reseller pricing will unlock automatically.'
    )
    return _repair_premium_emoji_markup(str(get_setting('reseller_discount_activation_text') or default))

def _render_reseller_discount_activation_text(user_name, amount, order_id):
    """Render the reseller QR caption with live amount/user/order fields.

    The admin-editable template controls presentation only. Transaction fields
    are injected from the current payment session every time, so Premium emoji
    edits or an old saved template can never leave them blank/stale.
    """
    template = _reseller_discount_activation_template()
    # Normalize copied/saved templates that contain literal \n or \r\n characters.
    template = str(template).replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\r', '\n')
    values = {
        'user': html.escape(str(user_name or 'User'), quote=False),
        'name': html.escape(str(user_name or 'User'), quote=False),
        'amount': f'₹{float(amount):.2f} INR',
        'order_id': html.escape(str(order_id), quote=False),
    }
    rendered = _safe_format_custom_text(template, **values)

    # Replace labelled fields while preserving HTML closing/opening tags around the
    # live value (for example ``Amount:</b> ₹100`` or ``Order ID:</b> <code>...</code>``).
    label_patterns = [
        (r'(\bActivation\s+Fee\s*:\s*(?:<[^>]+>\s*)*)(.*?)(\s*(?:</[^>]+>\s*)*)$', values['amount']),
        (r'(\bAmount\s*:\s*(?:<[^>]+>\s*)*)(.*?)(\s*(?:</[^>]+>\s*)*)$', values['amount']),
        (r'(\bUser(?:\s+Name)?\s*:\s*(?:<[^>]+>\s*)*)(.*?)(\s*(?:</[^>]+>\s*)*)$', values['user']),
        (r'(\bName\s*:\s*(?:<[^>]+>\s*)*)(.*?)(\s*(?:</[^>]+>\s*)*)$', values['user']),
        (r'(\bOrder\s+ID\s*:\s*(?:<[^>]+>\s*)*)(.*?)(\s*(?:</[^>]+>\s*)*)$', values['order_id']),
        (r'(\bOrder\s*:\s*(?:<[^>]+>\s*)*)(.*?)(\s*(?:</[^>]+>\s*)*)$', values['order_id']),
    ]
    fixed=[]
    for line in str(rendered).splitlines():
        line_out=line
        for pattern,value in label_patterns:
            if re.search(pattern,line_out,flags=re.I):
                def _field_repl(m, v=value):
                    return m.group(1) + str(v) + m.group(3)
                line_out=re.sub(pattern,_field_repl,line_out,count=1,flags=re.I)
                break
        fixed.append(line_out)
    rendered='\n'.join(fixed)

    rendered=_inject_labeled_user_values(rendered, {
        'user': values['user'], 'name': values['name'],
        'amount': values['amount'], 'order_id': values['order_id'],
    })

    # If the admin completely removed a required live field from the template,
    # add it rather than silently dropping transaction data.
    plain_rendered=re.sub(r'<[^>]+>','',rendered).lower()
    missing=[]
    if 'activation fee:' not in plain_rendered and 'amount:' not in plain_rendered:
        missing.append(f'💰 <b>Activation Fee:</b> {values["amount"]}')
    if 'user:' not in plain_rendered and 'user name:' not in plain_rendered and 'name:' not in plain_rendered:
        missing.append(f'👤 <b>User:</b> {values["user"]}')
    if 'order id:' not in plain_rendered and 'order:' not in plain_rendered:
        missing.append(f'🆔 <b>Order ID:</b> <code>{values["order_id"]}</code>')
    if missing:
        rendered=rendered.rstrip()+'\n\n'+'\n'.join(missing)

    return _repair_telegram_html_markup(_repair_premium_emoji_markup(rendered)).strip()

def _coupon_success_template():
    return _repair_premium_emoji_markup(str(get_setting('coupon_payment_success_text') or (
        '🎟️ <b>COUPON PAYMENT SUCCESSFUL</b>\n\n'
        '🛒 <b>Product:</b> {product_name}\n'
        '⏱️ <b>Plan:</b> {plan}\n'
        '💰 <b>Paid by Coupon:</b> {amount}\n\n'
        '🔑 <b>YOUR KEY:</b>\n<code>{key}</code>'
    )))

def _coupon_failed_template():
    return _repair_premium_emoji_markup(str(get_setting('coupon_payment_failed_text') or '❌ <b>COUPON PAYMENT FAILED</b>\n\n{reason}'))

def _render_coupon_message(template, product_name='', plan='', amount=0, key='', reason=''):
    values = {
        'product_name': html.escape(str(product_name), quote=False),
        'product': html.escape(str(product_name), quote=False),
        'plan': html.escape(str(plan), quote=False),
        'amount': float(amount or 0),
        'key': html.escape(str(key), quote=False),
        'reason': html.escape(str(reason), quote=False),
    }
    rendered = _safe_format_custom_text(str(template or ''), **values)
    return _repair_telegram_html_markup(_repair_premium_emoji_markup(rendered)).strip()

def _reseller_discount_active():
    if str(get_setting('reseller_discount_enabled') or '0')!='1': return False
    try:
        expires=float(get_setting('reseller_discount_expires_at') or '0')
        if expires and time.time() >= expires:
            set_setting('reseller_discount_enabled','0'); return False
    except Exception: pass
    return True

def _reseller_discount_button_text():
    return get_custom_btn('reseller_discount','👑 Reseller Discount')

def _reseller_discount_markup():
    # This button has its own Premium-emoji setting and must keep rendering it
    # even if the global User Panel Premium Mode is disabled.
    return make_ui_button(
        _reseller_discount_button_text(),
        callback_data='reseller_discount',
        button_key='main:reseller_discount',
        default_color='green',
        force_premium=True,
        force_style=True,
    )

def _reseller_discount_amount():
    try: return max(0.0,float(get_setting('reseller_discount_amount') or 0))
    except Exception: return 0.0

def _reseller_discount_start_payment(chat_id,message_id=None):
    amount=_reseller_discount_amount()
    if amount<=0:
        render_or_edit(chat_id,message_id,'❌ <b>Reseller Discount is not configured yet.</b>',types.InlineKeyboardMarkup())
        return
    current_user=get_user(chat_id)
    if current_user and int(current_user[11] or 0)==1:
        render_or_edit(chat_id,message_id,'⭐ <b>You are already a Reseller.</b>\n\nReseller pricing is already unlocked for your account.',types.InlineKeyboardMarkup())
        return
    try:
        qr_url,order_ref=_create_active_gateway_qr(amount)
    except Exception as exc:
        render_or_edit(chat_id,message_id,'❌ <b>Payment Gateway Error</b>\n\n'+html.escape(str(exc)[:800]),types.InlineKeyboardMarkup())
        return
    user=current_user or get_user(chat_id); name=user[1] if user else 'User'
    active_orders[str(order_ref)]={'user_id':int(chat_id),'amount':float(amount),'gateway':_get_active_payment_gateway(),'purpose':'reseller_activation'}
    text=_render_reseller_discount_activation_text(name,amount,order_ref)
    markup=types.InlineKeyboardMarkup(); markup.add(make_ui_button('🔙 Back to Main',callback_data='reseller_qr_back',button_key='nav:back_qr',default_color='red',force_style=True))
    if message_id:
        _delete_message_safely(chat_id,message_id)
    try:
        sent=bot.send_photo(chat_id,photo=qr_url,caption=text,parse_mode='HTML',reply_markup=markup)
    except Exception:
        sent=bot.send_message(chat_id,text,parse_mode='HTML',reply_markup=markup)
    qr_message_id=getattr(sent,'message_id',message_id)
    with reseller_qr_lock:
        reseller_qr_sessions[int(chat_id)]={'message_id':int(qr_message_id) if qr_message_id else None,'order_id':str(order_ref),'created_at':time.time()}
    threading.Thread(target=poll_payment_in_bot,args=(chat_id,chat_id,qr_message_id,str(order_ref),amount,'reseller_activation',0,None),daemon=True,name='rg-reseller-payment').start()

def _activate_reseller_after_payment(user_id,amount,order_id,utr):
    set_reseller_status(user_id,1)
    now=datetime.datetime.now()
    try:
        hours=float(get_setting('reseller_discount_duration_hours') or 24)
    except Exception: hours=24.0
    # Access duration is retained as metadata; reseller role remains active until admin removes it.
    set_setting(f'reseller_activated_at_{int(user_id)}',now.strftime('%Y-%m-%d %H:%M:%S'))
    # No user-facing success message: successful verification restores the Main Menu.
    try:
        notify_admins_purchase(user_id,(get_user(user_id) or [0,'User'])[1],order_id,'Reseller Discount','Activation',amount,None,'upi',f'Activated • UTR: {utr or "N/A"}')
    except Exception: pass

def _process_coupon_purchase(chat_id,user_id,product_id,device_id,code):
    product=get_product_by_id(product_id)
    if not product: return
    if _product_hidden(product[1]) or _plan_hidden(product[0]):
        bot.send_message(
            chat_id,
            '❌ <b>This product/plan is currently hidden.</b>\n\n'
            'Your coupon was not consumed.',
            parse_mode='HTML',
        )
        return
    user=get_user(user_id); is_reseller=int(user[11] or 0) if user else 0
    reg=float(product[4] or 0); res=float(product[5] or reg); prod_disc=float(product[7] or 0)
    custom_price = get_custom_plan_price(user_id, product_id)
    if is_reseller and custom_price["reseller_price"] is not None:
        price=custom_price["reseller_price"]
    elif (not is_reseller) and custom_price["user_price"] is not None:
        price=custom_price["user_price"]
    elif is_reseller:
        price=res
    else:
        gd=float(get_setting('global_discount') or 0); ud=float(user[12] or 0) if user and len(user)>12 else 0
        ref=int(user[15] or 0) if user and len(user)>15 else 0
        disc=max(gd,prod_disc,ud if ud>0 and ref==0 else 0); price=reg*(1-disc/100) if disc>0 else reg
    price=round(price,2); ok,msg=_claim_coupon(code,user_id,price)
    if not ok:
        failure=_render_coupon_message(_coupon_failed_template(),reason=msg)
        bot.send_message(chat_id,failure,parse_mode='HTML'); return
    order_id='CPN'+datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')+str(random.randint(1000,9999))
    try:
        if _bot_make_is_product(product):
            order_id='BM'+datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')+str(random.randint(1000,9999))
            _bot_make_pending_save(order_id,user_id,product_id,product[3],price,'coupon')
            try: record_order(order_id,user_id,BOT_MAKE_PRODUCT_NAME,product[3],price,'BOT-MAKE')
            except Exception: pass
            _bot_make_start_details(chat_id,user_id,order_id)
            return
        key=fetch_and_claim_manual_key(product[1],product[3])
        if not key:
            _refresh_multi_api_connection_if_needed(product[1],int(product[0])); key=fetch_key_from_api(product[2] or '133',product[8] or product[3],android_id=device_id,product_name=product[1],plan_id=product[0],purchase_ref=order_id)
        if not key:
            _restore_coupon(code,user_id)
            bot.send_message(chat_id,'❌ <b>Key delivery failed.</b>\n\nYour coupon was restored because no key was delivered.',parse_mode='HTML'); return
        record_order(order_id,user_id,product[1],product[3],price,key)
        try: notify_admins_purchase(user_id,(user or [0,'User'])[1],order_id,product[1],product[3],price,device_id,'coupon',key)
        except Exception: pass
        success=_render_coupon_message(_coupon_success_template(),product_name=product[1],plan=product[3],amount=price,key=key)
        bot.send_message(chat_id,success,parse_mode='HTML',reply_markup=types.InlineKeyboardMarkup())
    except Exception as exc:
        _restore_coupon(code,user_id)
        failure=_render_coupon_message(_coupon_failed_template(),reason='Coupon purchase failed. Your coupon was restored.')
        bot.send_message(chat_id,failure,parse_mode='HTML')

RESSELLER_API_ADMIN_CALLBACK = 'resapi_admin'
RESSELLER_API_ADMIN_BUTTON_KEY = 'admin:callback:resapi_admin'

def _reseller_api_feature_enabled():
    """Return whether this bot instance exposes/accepts Reseller API.

    Master Bot keeps the control panel available. Generated child bots can
    disable the Reseller API per instance by hiding the corresponding Admin
    Panel callback in their own database. The same flag is enforced at the
    HTTP boundary so hiding the button cannot be bypassed with a direct request.
    """
    if BOT_CREATOR_ENABLED:
        return True
    return RESSELLER_API_ADMIN_BUTTON_KEY not in _disabled_admin_buttons()


def _reseller_api_token(user_id):
    row=sqlite3.connect(str(BOT_DB_PATH),timeout=15).execute('SELECT api_token FROM reseller_api_credentials WHERE user_id=? AND enabled=1',(int(user_id),)).fetchone()
    return row[0] if row else None

def _reseller_api_public_link():
    """Return the public HTTPS root used in reseller credentials.

    The admin may use the hosting provider's own domain and optionally add a
    custom path (for example /reseller). No separately purchased domain is
    required. The HTTP handler strips that configured path before routing the
    request to the existing API endpoints.
    """
    candidates = [
        get_setting('reseller_api_public_url'),
        os.environ.get('RESELLER_API_PUBLIC_URL'),
        os.environ.get('PUBLIC_URL'),
        os.environ.get('KOYEB_PUBLIC_DOMAIN'),
        os.environ.get('RENDER_EXTERNAL_URL'),
    ]
    for value in candidates:
        url = str(value or '').strip().strip('`').rstrip('/')
        if not url:
            continue
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        url = re.sub(r'/api/(?:reseller/)?v1/?$', '', url, flags=re.I)
        url = re.sub(r'/api/(?:reseller/)?(?:catalog|purchase|balance|me|generate-key)/?$', '', url, flags=re.I)
        return url.rstrip('/')
    return RESELLER_API_PUBLIC_URL_FALLBACK.rstrip('/')


def _save_reseller_api_public_link(value):
    """Save a reseller-facing URL, allowing a path-only value on the hosting URL."""
    value = str(value or '').strip().strip('`').rstrip('/')
    if not value:
        raise ValueError('Public API Link cannot be empty.')
    if value.startswith('/'):
        base_candidates = [
            os.environ.get('RESELLER_API_PUBLIC_URL'),
            os.environ.get('PUBLIC_URL'),
            os.environ.get('KOYEB_PUBLIC_DOMAIN'),
            os.environ.get('RENDER_EXTERNAL_URL'),
            RESELLER_API_PUBLIC_URL_FALLBACK,
        ]
        base = next((str(x or '').strip().strip('`').rstrip('/') for x in base_candidates if str(x or '').strip()), '')
        if not base:
            raise ValueError('No hosting public URL is available to attach this custom path.')
        if not base.startswith(('http://', 'https://')):
            base = 'https://' + base
        value = base + '/' + value.strip('/')
    elif not value.startswith(('http://', 'https://')):
        value = 'https://' + value
    return value.rstrip('/')


def _reseller_api_public_path_prefix():
    """Return the optional path prefix configured for the public reseller URL."""
    raw = str(get_setting('reseller_api_public_url') or '').strip().strip('`')
    if not raw:
        return ''
    if not raw.startswith(('http://', 'https://')):
        raw = 'https://' + raw
    try:
        from urllib.parse import urlsplit
        path = urlsplit(raw).path or ''
    except Exception:
        path = ''
    path = '/' + str(path).strip('/') if str(path).strip('/') else ''
    if re.search(r'/api/(?:reseller/)?v1(?:/|$)', path, flags=re.I):
        return ''
    return path.rstrip('/')


def _reseller_api_random_numeric_id(min_value, max_value, table_name, column_name):
    """Generate a unique numeric API-facing ID without using SQLite row IDs.

    The ranges intentionally avoid the tiny sequential 1,2,3... values that
    were previously exposed. Product IDs and Validity IDs use different ranges
    so they are easy to distinguish when configuring a reseller bot/website.
    """
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        for _ in range(1000):
            candidate=str(random.SystemRandom().randint(int(min_value),int(max_value)))
            row=conn.execute(f'SELECT 1 FROM {table_name} WHERE {column_name}=? LIMIT 1',(candidate,)).fetchone()
            if not row:
                return candidate
    finally:
        conn.close()
    raise RuntimeError('Unable to allocate a unique reseller API ID')


def _reseller_api_product_id(product_name):
    product_name=str(product_name or '').strip()
    if not product_name:
        return ''
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        row=conn.execute('SELECT product_id FROM reseller_api_product_ids WHERE product_name=?',(product_name,)).fetchone()
        if row and str(row[0]).strip():
            return str(row[0]).strip()
    finally:
        conn.close()

    now=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # New public Product IDs use the owner's permanent sequence. Existing
    # mappings are NEVER rewritten, because changing an already-published ID
    # would break reseller bots/websites that already use it.
    for _ in range(100):
        conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
        try:
            row=conn.execute('SELECT MAX(CAST(product_id AS INTEGER)) FROM reseller_api_product_ids WHERE product_id GLOB "[0-9]*"').fetchone()
            candidate=max(20, int(row[0] or 19)+1)
            conn.execute('INSERT OR IGNORE INTO reseller_api_product_ids(product_name,product_id,created_at,updated_at) VALUES(?,?,?,?)',(product_name,str(candidate),now,now))
            conn.commit()
            row=conn.execute('SELECT product_id FROM reseller_api_product_ids WHERE product_name=?',(product_name,)).fetchone()
            if row:
                return str(row[0]).strip()
        finally:
            conn.close()
    raise RuntimeError(f'Unable to create API Product ID for {product_name}')


def _reseller_api_validity_id(product_name, plan_id, plan_days=''):
    product_name=str(product_name or '').strip()
    try:
        plan_id=int(plan_id)
    except Exception:
        return ''
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        row=conn.execute('SELECT valid_id FROM reseller_api_validity_ids WHERE product_name=? AND plan_id=?',(product_name,plan_id)).fetchone()
        if row and str(row[0]).strip():
            return str(row[0]).strip()
    finally:
        conn.close()

    now=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # New public Validity IDs use the permanent 111+ sequence. Existing
    # mappings are preserved exactly as-is for backward compatibility.
    for _ in range(100):
        conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
        try:
            row=conn.execute('SELECT MAX(CAST(valid_id AS INTEGER)) FROM reseller_api_validity_ids WHERE valid_id GLOB "[0-9]*"').fetchone()
            candidate=max(111, int(row[0] or 110)+1)
            conn.execute('INSERT OR IGNORE INTO reseller_api_validity_ids(product_name,plan_id,valid_id,plan_days,created_at,updated_at) VALUES(?,?,?,?,?,?)',(product_name,plan_id,str(candidate),str(plan_days or ''),now,now))
            conn.commit()
            row=conn.execute('SELECT valid_id FROM reseller_api_validity_ids WHERE product_name=? AND plan_id=?',(product_name,plan_id)).fetchone()
            if row:
                return str(row[0]).strip()
        finally:
            conn.close()
    raise RuntimeError(f'Unable to create API Validity ID for {product_name}/{plan_id}')


def _reseller_api_sync_ids_for_product(product_name):
    """Ensure every *public* local product/plan has a stable API ID mapping.

    Hidden products/plans are intentionally not exposed in the public API
    catalog and do not get newly-created public IDs while they are hidden.
    Existing mappings are preserved so un-hiding an item does not break an
    already configured reseller bot.
    """
    product_id=_reseller_api_product_id(product_name)
    for row in get_product_plans(product_name):
        if _plan_hidden(row[0]):
            continue
        _reseller_api_validity_id(product_name,row[0],row[2])
    return product_id


def _reseller_api_resolve_mapped_plan(product_id, validity_id):
    pid=str(product_id or '').strip()
    vid=str(validity_id or '').strip()
    if not pid or not vid:
        return None
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        row=conn.execute(
            '''SELECT v.product_name,v.plan_id,v.valid_id,p.product_id
               FROM reseller_api_validity_ids v
               JOIN reseller_api_product_ids p ON p.product_name=v.product_name
               LEFT JOIN product_visibility pv ON pv.product_name=v.product_name
               LEFT JOIN plan_visibility plv ON plv.plan_id=v.plan_id
               WHERE p.product_id=? AND v.valid_id=?
                 AND COALESCE(pv.hidden,0)=0
                 AND COALESCE(plv.hidden,0)=0
               LIMIT 1''',
            (pid,vid)
        ).fetchone()
        if row:
            product = get_product_by_id(int(row[1]))
            if product and not _product_hidden(product[1]) and not _plan_hidden(product[0]):
                return product
    finally:
        conn.close()
    return None


def _deliver_product_key_with_fallback(product, order_ref, android_id=None):
    """Deliver from local manual stock first, otherwise use the configured API.

    This is the central fallback rule for reseller purchases: a product does not
    need to be connected to an API when manual stock exists, and a product with
    no manual key can still be delivered from its connected API server.
    """
    if not product:
        return None, 'none'
    product_id=int(product[0])
    product_name=str(product[1])
    pid_id=str(product[2] or '133')
    plan_days=str(product[3])
    remote_duration=str(product[8] or plan_days)

    try:
        manual_key=fetch_and_claim_manual_key(product_name,plan_days)
    except Exception as exc:
        print(f'[MANUAL KEY DELIVERY ERROR] product={product_name} plan={plan_days}: {exc}')
        manual_key=None
    if manual_key:
        return str(manual_key), 'manual'

    try:
        _refresh_multi_api_connection_if_needed(product_name,product_id)
    except Exception as exc:
        print(f'[API CONNECTION REFRESH ERROR] product={product_name} plan_id={product_id}: {exc}')

    try:
        api_key=fetch_key_from_api(
            pid_id,
            remote_duration,
            android_id=android_id,
            product_name=product_name,
            plan_id=product_id,
            purchase_ref=order_ref,
        )
    except Exception as exc:
        print(f'[API KEY DELIVERY ERROR] product={product_name} plan={plan_days}: {exc}')
        api_key=None
    if api_key:
        return str(api_key), 'api'
    return None, 'none'


def _reseller_api_catalog():
    out=[]
    # Public reseller IDs are random/stable mappings, never SQLite row IDs.
    for name in get_visible_products():
        rows=[r for r in get_product_plans(name) if not _plan_hidden(r[0])]
        if not rows:
            continue
        try:
            product_id=_reseller_api_sync_ids_for_product(name)
        except Exception as exc:
            print(f'[RESSELLER API ID MAP ERROR] {name}: {exc}')
            continue
        plans=[]
        for row in rows:
            valid_id=_reseller_api_validity_id(name,row[0],row[2])
            plans.append({
                'validity':str(row[2]),
                'valid_id':str(valid_id),
                'price':float(row[5] or row[4] or 0)
            })
        out.append({'name':name,'product_id':str(product_id),'plans':plans})
    return out

def _reseller_api_find_plan(product_id,validity_id):
    # Preferred path: random public Product ID + random Validity ID mapping.
    mapped=_reseller_api_resolve_mapped_plan(product_id,validity_id)
    if mapped:
        return mapped

    # Backward compatibility: older reseller bots may still send the old local
    # product/plan row IDs. Do not remove that behavior.
    try: pid=int(str(product_id)); vid=int(str(validity_id))
    except Exception: return None
    for name in get_visible_products():
        rows=[r for r in get_product_plans(name) if not _plan_hidden(r[0])]
        if not rows or int(rows[0][0]) != pid:
            continue
        for row in rows:
            if int(row[0]) == vid:
                return get_product_by_id(vid)
    return None

def _create_or_rotate_reseller_api_token(user_id):
    # Permanent reseller token: create once, never rotate on bot restart/update.
    now=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        row=conn.execute('SELECT api_token FROM reseller_api_credentials WHERE user_id=? AND enabled=1',(int(user_id),)).fetchone()
        if row and row[0]:
            return str(row[0])
        token='rg_'+secrets.token_urlsafe(32).replace('-','_').replace('=','')
        conn.execute('INSERT INTO reseller_api_credentials(user_id,api_token,created_at,updated_at,enabled) VALUES(?,?,?,?,1)',(int(user_id),token,now,now))
        conn.commit()
        return token
    finally:
        conn.close()

def _reseller_api_credentials_text(user_id):
    token=_reseller_api_token(user_id); user=get_user(user_id); link=_reseller_api_public_link()
    lines=['🔌 <b>RESELLER API CONNECTION DETAILS</b>','',f'👤 <b>Reseller:</b> {html.escape(str(user[1] if user else "User"))}',f'🆔 <b>Telegram ID:</b> <code>{int(user_id)}</code>',f'🔑 <b>API Token:</b> <code>{html.escape(str(token or "Not generated"))}</code>',f'🌐 <b>Server Link:</b> <code>{html.escape(link or "Set Public API Link first")}</code>','','📦 <b>PRODUCT / VALIDITY IDs</b>']
    for pdt in _reseller_api_catalog():
        lines.append(f'🎮 <b>{html.escape(pdt["name"])}</b> — Product ID <code>{pdt["product_id"]}</code>')
        for pl in pdt['plans']: lines.append(f'   └ {html.escape(pl["validity"])} — Validity ID <code>{pl["valid_id"]}</code>')
    return '\n'.join(lines)


def _reseller_api_find_credentials(token):
    """Fast token lookup restricted to active, unbanned reseller accounts."""
    if not _reseller_api_feature_enabled():
        return None
    token=str(token or '').strip()
    if not token: return None
    conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
    try:
        return conn.execute(
            """SELECT c.user_id,u.balance,u.is_reseller,u.first_name,u.phone_number
               FROM reseller_api_credentials c JOIN users u ON u.user_id=c.user_id
               WHERE c.api_token=? AND c.enabled=1 AND u.is_reseller=1 AND COALESCE(u.is_banned,0)=0""",(token,)
        ).fetchone()
    finally: conn.close()


def _reseller_api_idempotent_response(key, user_id):
    key = str(key or '').strip()
    if not key:
        return None
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        row = conn.execute(
            'SELECT response_json FROM reseller_api_idempotency WHERE idempotency_key=? AND user_id=?',
            (key, int(user_id))
        ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except Exception:
            return None
    finally:
        conn.close()


def _reseller_api_store_idempotent_response(key, user_id, payload):
    key = str(key or '').strip()
    if not key:
        return
    try:
        raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
        try:
            conn.execute(
                'INSERT OR IGNORE INTO reseller_api_idempotency(idempotency_key,user_id,response_json,created_at) VALUES(?,?,?,?)',
                (key, int(user_id), raw, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        print(f'[RESELLER API IDEMPOTENCY STORE ERROR] {str(exc)[:300]}')


def notify_reseller_api_purchase(user_id, order_id, prod_name, prod_days, amount,
                                purchased_key, product_id=None, validity_id=None,
                                delivery_source=''):
    """Send an immediate Telegram receipt to the reseller who used the API.

    This is intentionally best-effort: a Telegram delivery failure must never
    roll back or interrupt a successful API purchase/key delivery.
    """
    try:
        user = get_user(int(user_id)) or []
        name = str(user[1] if len(user) > 1 and user[1] else 'Reseller')
        purchase_time = _now_ist_text()
        source = '🔑 Manual Stock' if str(delivery_source) == 'manual' else '🤖 Auto API'
        lines = [
            '✅ <b>RESELLER API PURCHASE SUCCESSFUL</b>',
            '',
            f'👤 <b>Reseller:</b> {html.escape(name, quote=False)}',
            f'🎮 <b>Product:</b> {html.escape(str(prod_name), quote=False)}',
            f'⏱️ <b>Plan:</b> {html.escape(str(prod_days), quote=False)}',
            f'💰 <b>Price Paid:</b> ₹{float(amount):.2f} INR',
            '🔌 <b>Purchase Type:</b> Reseller API',
            f'📦 <b>Delivery:</b> {source}',
        ]
        if product_id is not None:
            lines.append(f'🆔 <b>Product ID:</b> <code>{html.escape(str(product_id))}</code>')
        if validity_id is not None:
            lines.append(f'🆔 <b>Validity ID:</b> <code>{html.escape(str(validity_id))}</code>')
        lines.extend([
            f'🔑 <b>Delivered Key:</b> <code>{html.escape(str(purchased_key or "N/A"), quote=False)}</code>',
            f'🧾 <b>Order ID:</b> <code>{html.escape(str(order_id), quote=False)}</code>',
            f'🕒 <b>Date/Time:</b> {purchase_time}',
        ])
        bot.send_message(int(user_id), '\n'.join(lines), parse_mode='HTML')
    except Exception as exc:
        print(f'[RESELLER API USER NOTIFICATION ERROR] user={user_id}: {str(exc)[:300]}')


def notify_admins_reseller_api_purchase(user_id, order_id, prod_name, prod_days, amount, purchased_key, delivery_source):
    user=get_user(int(user_id)) or []
    name=str(user[1] if len(user)>1 and user[1] else 'Reseller')
    phone=str(user[2] if len(user)>2 and user[2] else 'N/A')
    username=_get_live_telegram_username(int(user_id),name)
    purchase_time=_now_ist_text()
    source='🔑 Manual Stock' if str(delivery_source)=='manual' else '🤖 Auto API'
    text=('🚨 <b>RESELLER API PURCHASE</b> 🚨\n\n'
          f'👤 <b>Reseller/User:</b> {html.escape(name,quote=False)}'+(f' (@{html.escape(username,quote=False)})' if username else '')+'\n'
          f'🆔 <b>Telegram ID:</b> <code>{int(user_id)}</code>\n'
          f'📱 <b>Phone:</b> <code>{html.escape(phone,quote=False)}</code>\n'
          f'🎮 <b>Product:</b> {html.escape(str(prod_name),quote=False)}\n'
          f'⏱️ <b>Plan:</b> {html.escape(str(prod_days),quote=False)}\n'
          f'💰 <b>Price:</b> ₹{float(amount):.2f} INR\n'
          f'📦 <b>Delivery:</b> {source}\n'
          f'🔑 <b>Key:</b> <code>{html.escape(str(purchased_key or "N/A"),quote=False)}</code>\n'
          f'🧾 <b>Order ID:</b> <code>{html.escape(str(order_id),quote=False)}</code>\n'
          f'🕒 <b>Purchase Time:</b> {purchase_time}')
    for admin_id in _load_persistent_admin_ids():
        try: bot.send_message(admin_id,text,parse_mode='HTML')
        except Exception:
            try: bot.send_message(admin_id,re.sub(r'<[^>]+>','',text))
            except Exception: pass

def _reseller_api_purchase_for_user(user_id, product_id, validity_id, idem=''):
    """Shared reseller purchase path with manual-key/API fallback.

    Rule: reserve the reseller's wallet balance first, then try local manual
    stock. If no manual key exists, the configured API route is used. If neither
    source can deliver a key, the exact wallet amount is refunded.
    """
    cached = _reseller_api_idempotent_response(idem, user_id)
    if cached is not None:
        return 200, cached

    product = _reseller_api_find_plan(product_id, validity_id)
    if not product:
        return 404, {'success': False, 'error': 'INVALID_PRODUCT_OR_VALIDITY'}
    if _product_hidden(product[1]) or _plan_hidden(product[0]):
        return 404, {'success': False, 'error': 'PRODUCT_HIDDEN', 'message': 'Product or plan is hidden.'}

    custom_price = get_custom_plan_price(user_id, product[0])
    price = custom_price["reseller_price"] if custom_price["reseller_price"] is not None else float(product[5] or product[4] or 0)
    user = get_user(int(user_id))
    balance = float(user[4] or 0) if user else 0.0
    if balance < price:
        return 402, {
            'success': False,
            'error': 'INSUFFICIENT_BALANCE',
            'balance': balance,
            'required': price,
        }

    order_ref = idem or ('RAPI' + datetime.datetime.now().strftime('%Y%m%d%H%M%S%f') + str(random.randint(1000, 9999)))

    # Atomically reserve the reseller balance before delivery. This prevents a
    # concurrent purchase from spending the same balance twice.
    if not deduct_user_balance(int(user_id), price):
        return 409, {'success': False, 'error': 'BALANCE_CHANGED_RETRY'}

    key, delivery_source = _deliver_product_key_with_fallback(product, order_ref)
    if not key:
        try:
            refund_user_balance(int(user_id), price)
        except Exception as exc:
            print(f'[RESELLER API REFUND ERROR] user={user_id} amount={price}: {exc}')

        # This API/reseller purchase path also needs the same admin alert as
        # the normal Wallet checkout when delivery fails. The refund above is
        # already completed; the helper records the failure once and does not
        # issue a second wallet credit for payment type ``wallet``.
        try:
            _handle_paid_key_delivery_failure(
                int(user_id), int(user_id), order_ref, price, 'wallet',
                product[1], product[3],
                reason='The reseller API/manual delivery path did not return a key.'
            )
        except Exception as alert_error:
            print(f'[RESELLER API DELIVERY FAILURE ALERT ERROR] order={order_ref}: {alert_error}')

        return 502, {
            'success': False,
            'error': 'KEY_DELIVERY_FAILED',
            'message': 'No manual key was available and the configured API server did not return a key. Your balance was refunded.',
            'refunded': True,
        }

    try:
        record_order(order_ref, int(user_id), product[1], product[3], price, key)
    except Exception as exc:
        print(f'[RESELLER API ORDER RECORD ERROR] {order_ref}: {exc}')

    try:
        notify_reseller_api_purchase(
            int(user_id), order_ref, product[1], product[3], price, key,
            product_id=product_id, validity_id=validity_id,
            delivery_source=delivery_source,
        )
    except Exception:
        pass
    try:
        notify_admins_reseller_api_purchase(int(user_id), order_ref, product[1], product[3], price, key, delivery_source)
    except Exception:
        pass
    # Preserve the existing general purchase notification system too.
    try:
        notify_admins_purchase(int(user_id), (user or [0, 'Reseller'])[1], order_ref,
                               product[1], product[3], price, None, 'reseller_api', key)
    except Exception:
        pass


    latest = get_user(int(user_id)) or [0, 'Reseller', '', '', 0]
    bal = float(latest[4] or 0)
    response = {
        'success': True,
        'order_id': order_ref,
        'product_id': str(product_id),
        'validity_id': str(validity_id),
        'delivery_source': delivery_source,
        'user': {
            'id': str(user_id),
            'telegram_id': str(user_id),
            'username': _get_live_telegram_username(int(user_id), (user or [0, 'Reseller'])[1]),
            'name': str((user or [0, 'Reseller'])[1] or 'Reseller'),
            'phone': str((user or [0, '', 'N/A'])[2] or 'N/A') if len(user or []) > 2 else 'N/A',
            'key': key,
        },
        'price': price,
        'balance': bal,
    }
    _reseller_api_store_idempotent_response(idem, user_id, response)
    return 200, response


def _reseller_api_cors_headers(handler):
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type, Idempotency-Key')
    handler.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')


class _ResellerAPIServerHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def _send_json(self, code, payload):
        raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        self.send_response(int(code))
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        _reseller_api_cors_headers(self)
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, fmt, *args):
        return

    def _auth(self):
        h = str(self.headers.get('Authorization') or '')
        return h[7:].strip() if h.lower().startswith('bearer ') else ''

    def _require_auth(self):
        token = self._auth()
        row = _reseller_api_find_credentials(token)
        if not row:
            self._send_json(401, {'success': False, 'error': 'INVALID_API_KEY'})
            return None
        return token, row

    def _read_json(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
            if length < 0 or length > 1024 * 1024:
                raise ValueError('invalid content length')
            raw = self.rfile.read(length) if length else b'{}'
            data = json.loads(raw or b'{}')
            return data if isinstance(data, dict) else {}
        except Exception:
            return None

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Content-Length', '0')
        _reseller_api_cors_headers(self)
        self.end_headers()

    def _route_path(self):
        path = self.path.split('?', 1)[0].rstrip('/') or '/'
        prefix = _reseller_api_public_path_prefix()
        if prefix and (path == prefix or path.startswith(prefix + '/')):
            path = path[len(prefix):] or '/'
        return path.rstrip('/') or '/'

    def do_GET(self):
        path = self._route_path()

        if path in ('/', '/health', '/api/health', '/api/v1/health'):
            self._send_json(200, {
                'success': True,
                'service': f'{BOT_BRAND_NAME} Reseller API',
                'status': 'online',
                'version': 'v1',
            })
            return

        if path in ('/api/reseller/v1/catalog', '/api/reseller/catalog'):
            if not _reseller_api_feature_enabled():
                self._send_json(403, {'success': False, 'error': 'RESELLER_API_DISABLED'})
                return
            self._send_json(200, {'success': True, 'catalog': _reseller_api_catalog()})
            return

        if path in ('/api/v1/catalog', '/api/v1/products'):
            auth = self._require_auth()
            if not auth:
                return
            _, row = auth
            self._send_json(200, {
                'success': True,
                'catalog': _reseller_api_catalog(),
                'balance': float(row[1] or 0),
            })
            return

        if path == '/api/v1/balance':
            auth = self._require_auth()
            if not auth:
                return
            _, row = auth
            uid = int(row[0])
            self._send_json(200, {
                'success': True,
                'balance': float(row[1] or 0),
                'user_id': str(uid),
                'is_reseller': bool(row[2]),
            })
            return

        if path in ('/api/v1/me', '/api/seller/me'):
            auth = self._require_auth()
            if not auth:
                return
            _, row = auth
            uid = int(row[0])
            user = get_user(uid) or [uid, 'Reseller']
            self._send_json(200, {
                'success': True,
                'user': {
                    'id': str(uid),
                    'user_id': str(uid),
                    'telegram_id': str(uid),
                    'name': str(user[1] if len(user) > 1 else 'Reseller'),
                    'username': None,
                    'is_reseller': bool(row[2]),
                },
                'balance': float(row[1] or 0),
            })
            return

        self._send_json(404, {'success': False, 'error': 'NOT_FOUND'})

    def do_POST(self):
        path = self._route_path()
        purchase_paths = {
            '/api/reseller/v1/purchase',
            '/api/reseller/purchase',
            '/api/v1/purchase',
            '/api/v1/generate-key',
            '/api/v1/buy',
        }
        if path not in purchase_paths:
            self._send_json(404, {'success': False, 'error': 'NOT_FOUND'})
            return

        auth = self._require_auth()
        if not auth:
            return
        _, row = auth

        data = self._read_json()
        if data is None:
            self._send_json(400, {'success': False, 'error': 'INVALID_JSON'})
            return

        product_id = data.get('product_id', data.get('productId'))
        validity_id = data.get(
            'validity_id',
            data.get('valid_id', data.get('variant_id', data.get('validityId')))
        )
        idem = str(
            self.headers.get('Idempotency-Key')
            or data.get('idempotency_key')
            or data.get('idempotencyKey')
            or ''
        ).strip()

        if not product_id or not validity_id:
            self._send_json(400, {
                'success': False,
                'error': 'MISSING_PRODUCT_OR_VALIDITY',
                'message': 'product_id and validity_id are required',
            })
            return

        code, response = _reseller_api_purchase_for_user(int(row[0]), product_id, validity_id, idem)
        self._send_json(code, response)


def _start_reseller_api_http_server():
    global reseller_api_http_server
    try:
        raw_port = (
            os.environ.get('BOT_CHILD_HTTP_PORT')
            if (BOT_INSTANCE_ID and not BOT_CREATOR_ENABLED and os.environ.get('BOT_CHILD_HTTP_PORT'))
            else (os.environ.get('SERVER_PORT') or os.environ.get('PORT') or '8080')
        )
        port = int(raw_port)
        if not (1 <= port <= 65535):
            raise ValueError(f'invalid port: {port}')
        reseller_api_http_server = ThreadingHTTPServer(('0.0.0.0', port), _ResellerAPIServerHandler)
        threading.Thread(
            target=reseller_api_http_server.serve_forever,
            daemon=True,
            name='reseller-api-http',
        ).start()
        print(f'🔌 Reseller API HTTP server listening on :{port}')
        print(f'🌐 Reseller API public link: {_reseller_api_public_link()}')
    except Exception as exc:
        print(f'⚠️ Reseller API HTTP server not started: {exc}')

def show_order_summary(chat_id, product_id, message_id=None, device_id=None, username=None):
    """Show Wallet/UPI payment methods without a fragile checkout exception."""
    product = get_product_by_id(product_id)
    if not product:
        bot.send_message(chat_id, "❌ Product not found.")
        return

    # A product/plan hidden by Admin must disappear from the real checkout path
    # as well, not only from the Store keyboard. This also blocks stale Buy
    # buttons that a user may still have open from before the hide action.
    if _product_hidden(product[1]) or _plan_hidden(product[0]):
        bot.send_message(
            chat_id,
            "❌ <b>This product/plan is currently hidden.</b>\n\n"
            "It is no longer available for purchase.",
            parse_mode="HTML",
        )
        return

    try:
        in_stock = _plan_is_in_stock(product_id)
    except Exception as exc:
        print(f"[CHECKOUT STOCK CHECK ERROR] product={product_id}: {exc}")
        in_stock = True if _bot_make_is_product(product) else not bool(int(product[10] or 0))

    if not in_stock:
        bot.send_message(
            chat_id,
            "❌ <b>OUT OF STOCK</b>\n\n"
            "This plan is currently unavailable. Payment options are disabled.",
            parse_mode="HTML",
        )
        return

    prod_name = product[1]
    prod_days = product[3]
    reg_price = product[4]
    resell_price = product[5]
    prod_disc_val = product[7]

    user = get_user(chat_id)
    user_bal = user[4] if user else 0.0
    user_name = user[1] if user and len(user) > 1 else "User"
    user_phone = user[2] if user and len(user) > 2 and user[2] else "N/A"

    def _num(value, default=0.0):
        try:
            return float(value or default)
        except (TypeError, ValueError):
            return float(default)

    user_bal = _num(user_bal)
    global_disc_val = _num(get_setting("global_discount") or "0.0")
    user_disc_val = _num(user[12]) if user and len(user) > 12 else 0.0
    ref_disc_used = int(user[15]) if user and len(user) > 15 else 0
    is_reseller = int(user[11]) if user and len(user) > 11 else 0
    reg_price = _num(reg_price)
    resell_price = _num(resell_price, reg_price)
    prod_disc_val = _num(prod_disc_val)

    custom_price = get_custom_plan_price(chat_id, product_id)
    if is_reseller == 1 and custom_price["reseller_price"] is not None:
        final_price = custom_price["reseller_price"]
    elif is_reseller == 0 and custom_price["user_price"] is not None:
        final_price = custom_price["user_price"]
    elif is_reseller == 1:
        final_price = resell_price
    else:
        effective_discount = max(global_disc_val, prod_disc_val)
        if user_disc_val > 0 and ref_disc_used == 0:
            effective_discount = max(effective_discount, user_disc_val)
        final_price = reg_price * (1 - effective_discount / 100) if effective_discount > 0 else reg_price

    dev_line = (
        f"├── 📱 <b>Device ID:</b> <code>{html.escape(str(device_id))}</code>\n"
        if device_id else ""
    )
    default_summary_text = (
        f"🧾 <b>ORDER SUMMARY</b>\n"
        f"────────────────────────\n"
        f"├── 👤 <b>Name:</b> {html.escape(str(user_name), quote=False)}\n"
        f"├── 🆔 <b>User ID:</b> <code>{chat_id}</code>\n"
        f"├── 📞 <b>Phone:</b> <code>{html.escape(str(user_phone), quote=False)}</code>\n"
        f"├── 📦 <b>Product:</b> 🛒 {html.escape(str(prod_name), quote=False)}\n"
        f"├── 🏷️ <b>Plan:</b> {html.escape(str(prod_days), quote=False)}\n"
        f"{dev_line}"
        f"├── 🔢 <b>Quantity:</b> 1\n"
        f"└── 💵 <b>Unit price:</b> ₹{final_price:.2f} INR\n"
        f"────────────────────────\n"
        f"💼 <b>Your Balance: ₹{user_bal:.2f} INR</b>\n"
        f"💳 <b>Final Total: ₹{final_price:.2f} INR</b>\n\n"
        f"👇 <b>Choose your payment method</b>"
    )

    try:
        order_template = get_custom_text("order_summary", default_summary_text)
        order_summary_text = _safe_format_custom_text(
            order_template,
            user=user_name, name=user_name,
            user_id=chat_id, telegram_id=chat_id,
            phone=user_phone, number=user_phone,
            product_name=prod_name, hack=prod_name,
            plan=prod_days, amount=f"{final_price:.2f}",
            balance=f"{user_bal:.2f}", device_id=device_id or "",
            default_order_summary=default_summary_text,
        )
    except Exception as exc:
        print(f"[CHECKOUT TEXT ERROR] product={product_id}: {exc}")
        order_summary_text = default_summary_text

    # Telegram already gives us the username during a callback, so use it
    # directly instead of making another network request on every Buy tap.
    live_username = str(username or "").strip().lstrip("@")
    if not live_username:
        live_username = _get_live_telegram_username(chat_id)

    try:
        order_summary_text = _inject_labeled_user_values(
            order_summary_text,
            {
                "name": html.escape(str(user_name), quote=False),
                "username": html.escape(str(live_username), quote=False),
                "username_at": html.escape(
                    f"@{live_username}" if live_username else "", quote=False
                ),
                "user_id": str(chat_id),
                "phone": html.escape(str(user_phone), quote=False),
                "balance": f"{user_bal:.2f}",
                "product_name": html.escape(str(prod_name), quote=False),
                "plan": html.escape(str(prod_days), quote=False),
                "amount": f"₹{final_price:.2f} INR",
            },
        )
    except Exception as exc:
        print(f"[CHECKOUT VALUE INJECTION ERROR] product={product_id}: {exc}")

    markup = types.InlineKeyboardMarkup()
    dev_param = f":{device_id}" if device_id else ""

    def _payment_button(text, callback_data, button_key):
        try:
            return make_ui_button(
                text,
                callback_data=callback_data,
                button_key=button_key,
                default_color="blue",
            )
        except Exception as exc:
            print(f"[PAYMENT BUTTON FALLBACK] {button_key}: {exc}")
            return types.InlineKeyboardButton(
                text=text, callback_data=callback_data
            )

    # Wallet Payment is always visible. If balance is insufficient, its callback redirects to Top Up.
    markup.add(
        _payment_button(
                f"💳 Pay via Wallet — ₹{final_price:.2f}",
                f"pay_wallet_{product_id}{dev_param}",
                "payment:wallet",
            )
        )

    markup.add(
        _payment_button(
            f"🇮🇳 Pay via UPI — ₹{final_price:.2f}",
            f"pay_upi_{product_id}{dev_param}",
            "payment:upi",
        )
    )
    markup.add(_payment_button(get_custom_btn('coupon','🎟️ Coupon Code'), f'coupon_{product_id}{dev_param}', 'payment:coupon'))

    try:
        btn_back = make_ui_button(
            "🔙 Back to Store",
            callback_data="open_store",
            button_key="nav:back_store",
            default_color="blue",
        )
    except Exception:
        btn_back = types.InlineKeyboardButton(
            text="🔙 Back to Store", callback_data="open_store"
        )
    markup.add(btn_back)

    render_or_edit(chat_id, message_id, order_summary_text, markup)


def process_wallet_checkout(chat_id, user_id, product_id, device_id=None, message_id=None):
    """Process a Wallet purchase without blocking or leaving the UI frozen.

    The existing wallet/key/API flow is preserved. The important change is that
    the checkout message remains visible in a Processing state while slow API
    work runs in the background. Any failure after balance deduction is handled
    with a refund, and successful delivery edits the same message into the
    existing Wallet Payment Successful design.
    """
    charged = False
    balance_deducted = 0.0
    try:
        product = get_product_by_id(product_id)
        if not product:
            _edit_payment_message_safely(
                chat_id, message_id,
                "❌ <b>Product not found!</b>",
            )
            return

        # Re-check visibility at the final wallet-delivery boundary. A user can
        # keep an old checkout message open after Admin hides the item, so the
        # callback-level check alone is not sufficient.
        if _product_hidden(product[1]) or _plan_hidden(product[0]):
            _edit_payment_message_safely(
                chat_id, message_id,
                "❌ <b>This product/plan is currently hidden.</b>\n\n"
                "The purchase was not charged.",
            )
            return

        if _bot_make_is_product(product):
            _bot_make_paid_wallet(chat_id,user_id,product_id,message_id=message_id)
            return

        try:
            in_stock = _plan_is_in_stock(product_id)
        except Exception as exc:
            print(f"[WALLET STOCK CHECK ERROR] product={product_id}: {exc}")
            in_stock = True if _bot_make_is_product(product) else not bool(int(product[10] or 0))
        if not in_stock:
            _edit_payment_message_safely(
                chat_id, message_id,
                "❌ <b>OUT OF STOCK</b>\n\n"
                "This plan is currently unavailable. Payment cannot be started.",
            )
            return

        first_name = "User"
        user_info = get_user(user_id)
        if user_info:
            first_name = user_info[1]

        prod_name = product[1]
        prod_days = product[3]
        reg_price = float(product[4] or 0.0)
        resell_price = float(product[5] or reg_price)
        prod_disc_val = float(product[7] or 0.0)
        pid_id = product[2] if product[2] and product[2] != '0' else '133'
        remote_dur = product[8] if len(product) > 8 and product[8] else prod_days
        tg_group_link = product[9] if len(product) > 9 and product[9] else ""

        user = get_user(user_id)
        global_disc_val = float(get_setting('global_discount') or '0.0')
        user_disc_val = user[12] if user and len(user) > 12 else 0.0
        ref_disc_used = user[15] if user and len(user) > 15 else 0
        is_reseller = user[11] if user and len(user) > 11 else 0

        custom_price = get_custom_plan_price(user_id, product_id)
        if is_reseller == 1 and custom_price["reseller_price"] is not None:
            final_price = custom_price["reseller_price"]
        elif is_reseller == 0 and custom_price["user_price"] is not None:
            final_price = custom_price["user_price"]
        elif is_reseller == 1:
            final_price = resell_price
        else:
            base_price = reg_price
            effective_discount = max(global_disc_val, prod_disc_val)
            if user_disc_val > 0 and ref_disc_used == 0:
                effective_discount = max(effective_discount, user_disc_val)
            final_price = base_price * (1 - effective_discount / 100) if effective_discount > 0 else base_price
        final_price = round(float(final_price), 2)

        if not deduct_user_balance(user_id, final_price):
            # Do not show an error-only screen. Redirect directly to the existing Top Up keypad.
            try:
                show_topup_options(chat_id, message_id=message_id)
            except Exception:
                try: show_topup_options(chat_id, message_id=message_id)
                except Exception: bot.send_message(chat_id, f"❌ Insufficient balance. Required ₹{final_price:.2f} INR. Please Top Up.")
            return

        charged = True
        balance_deducted = final_price
        order_id = "WAL" + datetime.datetime.now().strftime("%Y%m%d%H%M%S%f") + str(random.randint(1000, 9999))

        # Key/API delivery can be slow. It stays completely off the Telegram
        # callback worker, while the processing message remains on screen.
        try:
            key_val = fetch_and_claim_manual_key(prod_name, prod_days)
            if not key_val:
                _refresh_multi_api_connection_if_needed(prod_name, int(product[0]))
                key_val = fetch_key_from_api(
                    pid_id,
                    remote_dur,
                    android_id=device_id,
                    product_name=prod_name,
                    plan_id=product[0],
                    purchase_ref=order_id,
                )
        except Exception as api_error:
            print(
                f"[WALLET KEY/API ERROR] user={user_id} product={product_id} "
                f"order={order_id}: {api_error}"
            )
            key_val = None

        # Once a real key has been returned, the wallet charge is final. UI/order
        # logging failures after this point must never trigger a refund.
        if key_val:
            charged = False
            balance_deducted = 0.0

        if not key_val:
            # Never keep a wallet charge when the configured API/manual-key
            # system failed to actually deliver a key.
            try:
                refund_user_balance(user_id, balance_deducted)
            except Exception as refund_error:
                print(
                    f"[WALLET REFUND ERROR] user={user_id} order={order_id}: "
                    f"{refund_error}"
                )
            charged = False
            balance_deducted = 0.0
            # Notify admins for Wallet delivery failures too. Use the actual
            # charged amount (final_price); ``amount`` is not defined in this
            # wallet-only checkout function. The wallet was already refunded
            # above, and the failure helper is idempotent, so it will not add
            # the same refund a second time.
            _handle_paid_key_delivery_failure(
                chat_id, user_id, order_id, final_price, "wallet", prod_name, prod_days,
                reason="Wallet payment was processed, but the API did not return a key."
            )
            _edit_payment_message_safely(
                chat_id,
                message_id,
                "❌ <b>Key delivery failed.</b>\n\n"
                "The API server did not return a key for this Product ID / Valid ID.\n"
                "Your wallet balance has been refunded. Please check the Product ID and Valid ID mapping.",
            )
            return

        # From this point the key exists. Persisting the order and notifying
        # admins must not cause a second wallet charge or a refund.
        try:
            record_order(order_id, user_id, prod_name, prod_days, final_price, key_val)
        except Exception as order_error:
            print(f"[WALLET ORDER RECORD ERROR] {order_id}: {order_error}")

        try:
            notify_admins_purchase(
                user_id, first_name, order_id, prod_name, prod_days,
                final_price, device_id, "wallet", key_val
            )
        except Exception as notify_error:
            print(f"[WALLET ADMIN NOTIFY ERROR] {order_id}: {notify_error}")

        if user and len(user) > 15 and user[12] > 0 and user[15] == 0:
            try:
                mark_ref_discount_used(user_id)
            except Exception as discount_error:
                print(f"[WALLET REF DISCOUNT ERROR] {order_id}: {discount_error}")

        dev_info = (
            f"📱 <b>Device ID:</b> <code>{html.escape(str(device_id))}</code>\n"
            if device_id else ""
        )

        wallet_template = get_wallet_payment_emoji_template()
        if wallet_template:
            success_msg = _render_wallet_payment_emoji_template(
                wallet_template,
                user_id=user_id,
                order_id=order_id,
                product_id=product[0],
                product_name=prod_name,
                plan=prod_days,
                amount=final_price,
                key_val=key_val,
                pay_type="wallet",
                device_id=device_id,
            )
        else:
            success_msg = (
                f"💰 <b>WALLET PAYMENT SUCCESSFUL</b> 💰\n"
                f"<i>Instant Key Delivery!</i>\n\n"
                f"📋 <b>ORDER DETAILS</b>\n"
                f"├── 👤 <b>User ID:</b> <code>{user_id}</code>\n"
                f"├── 🆔 <b>Order ID:</b> <code>{order_id}</code>\n"
                f"├── 🛒 <b>Product ID:</b> <code>{product[0]}</code>\n"
                f"├── 🎮 <b>Product:</b> {html.escape(str(prod_name))}\n"
                f"├── ⏱️ <b>Plan:</b> {html.escape(str(prod_days))}\n"
                f"├── 💳 <b>Method:</b> 💼 Wallet Balance\n"
                f"{dev_info}"
                f"└── 💵 <b>Paid:</b> ₹{final_price:.2f} INR\n\n"
                f"🔑 <b>YOUR KEY:</b>\n"
                f"<code>{html.escape(str(key_val))}</code>\n\n"
                f"💡 <i>Tap the key above to copy instantly.</i>"
            )

        markup = types.InlineKeyboardMarkup()
        if tg_group_link:
            markup.add(
                make_ui_button(
                    "🔗 Join Telegram Group",
                    url=tg_group_link,
                    button_key="link:telegram_group",
                    default_color="blue",
                )
            )
        markup.add(
            make_ui_button(
                "🏠 Main Menu",
                callback_data="back_to_main_new",
                button_key="nav:success_main_menu",
                default_color="blue",
            )
        )

        # Edit the same message first. If that message cannot be edited, the
        # helper automatically falls back to sending the success message.
        _edit_payment_message_safely(
            chat_id, message_id, success_msg, reply_markup=markup
        )
        charged = False  # success is final; no refund in outer exception path
        balance_deducted = 0.0

    except Exception as exc:
        print(
            f"[WALLET CHECKOUT ERROR] user={user_id} product={product_id}: {exc}"
        )
        if charged and balance_deducted > 0:
            try:
                refund_user_balance(user_id, balance_deducted)
                charged = False
                balance_deducted = 0.0
            except Exception as refund_error:
                print(
                    f"[WALLET OUTER REFUND ERROR] user={user_id}: {refund_error}"
                )
        _edit_payment_message_safely(
            chat_id,
            message_id,
            "❌ <b>Wallet payment could not be completed.</b>\n\n"
            "No key was delivered. If your balance was deducted, it has been refunded.\n"
            "Please try again or contact Admin.",
        )


def show_upi_checkout(chat_id, product_id, message_id=None, device_id=None):
    """Open the purchase QR while keeping the payment screen alive until ready."""
    product = get_product_by_id(product_id)
    if not product:
        bot.send_message(chat_id, "❌ Product not found.")
        return

    try:
        in_stock = _plan_is_in_stock(product_id)
    except Exception as exc:
        print(f"[UPI STOCK CHECK ERROR] product={product_id}: {exc}")
        in_stock = True if _bot_make_is_product(product) else not bool(int(product[10] or 0))

    if not in_stock:
        bot.send_message(
            chat_id,
            "❌ <b>OUT OF STOCK</b>\n\n"
            "This plan is currently unavailable. Payment QR will not be opened.",
            parse_mode="HTML",
        )
        return

    prod_name = product[1]
    prod_days = product[3]

    def _checkout_num(value, default=0.0):
        try:
            return float(value or default)
        except (TypeError, ValueError):
            return float(default)

    reg_price = _checkout_num(product[4])
    resell_price = _checkout_num(product[5], reg_price)
    prod_disc_val = _checkout_num(product[7])

    user = get_user(chat_id)
    try:
        global_disc_val = float(get_setting("global_discount") or "0.0")
    except Exception:
        global_disc_val = 0.0
    try:
        user_disc_val = float(user[12]) if user and len(user) > 12 else 0.0
    except (TypeError, ValueError):
        user_disc_val = 0.0
    try:
        ref_disc_used = int(user[15]) if user and len(user) > 15 else 0
    except (TypeError, ValueError):
        ref_disc_used = 0
    try:
        is_reseller = int(user[11]) if user and len(user) > 11 else 0
    except (TypeError, ValueError):
        is_reseller = 0

    custom_price = get_custom_plan_price(chat_id, product_id)
    if is_reseller == 1 and custom_price["reseller_price"] is not None:
        final_price = custom_price["reseller_price"]
    elif is_reseller == 0 and custom_price["user_price"] is not None:
        final_price = custom_price["user_price"]
    elif is_reseller == 1:
        final_price = resell_price
    else:
        effective_discount = max(global_disc_val, prod_disc_val)
        if user_disc_val > 0 and ref_disc_used == 0:
            effective_discount = max(effective_discount, user_disc_val)
        final_price = reg_price * (1 - effective_discount / 100) if effective_discount > 0 else reg_price

    try:
        qr_url, order_ref = _create_active_gateway_qr(final_price)
    except Exception as exc:
        bot.send_message(
            chat_id,
            "❌ <b>Payment Gateway Setup Error</b>\n\n"
            + html.escape(str(exc)[:800]),
            parse_mode="HTML",
        )
        return

    purchase_date = datetime.datetime.now().strftime("%A, %d %b %Y")
    dev_info = (
        f"├── 📱 <b>Device ID:</b> <code>{html.escape(str(device_id))}</code>\n"
        if device_id else ""
    )

    if _has_custom_qr_payment_text():
        qr_custom_template = get_setting(QR_PAYMENT_TEXT_KEY) or ""
        caption_text = _render_qr_payment_text(
            qr_custom_template,
            prod_name=prod_name, prod_days=prod_days,
            amount=final_price, order_id=order_ref,
            purchase_date=purchase_date, device_id=device_id,
        )
    else:
        caption_text = "\n\n".join([
            "📦 <b>Order Details:</b>\n"
            f"├── 🎮 <b>Product:</b> {html.escape(str(prod_name), quote=False)}\n"
            f"├── ⏱️ <b>Plan:</b> {html.escape(str(prod_days), quote=False)}\n"
            f"├── 💰 <b>Amount:</b> ₹{final_price:.2f} INR\n"
            f"{dev_info}"
            f"├── 📅 <b>Purchase Date:</b> {html.escape(purchase_date, quote=False)}\n"
            f"└── 🆔 <b>Order ID:</b> <code>{html.escape(str(order_ref), quote=False)}</code>",
            "📱 <b>How to Pay:</b>\n"
            "├── 1️⃣ Scan the QR Code above using GPay, PhonePe or FamPay\n"
            f"├── 2️⃣ Pay exact amount: <b>₹{final_price:.2f}</b>\n"
            "└── 3️⃣ Wait a few seconds for auto-verification!",
            "────────────────────────\n"
            "⚡ <i>Auto-checking live payment in background...</i>",
        ])

    try:
        btn_back = make_ui_button(
            "🔙 Back to Store",
            callback_data="back_from_qr",
            button_key="nav:back_qr",
            default_color="blue",
        )
    except Exception:
        btn_back = types.InlineKeyboardButton(
            text="🔙 Back to Store", callback_data="back_from_qr"
        )

    markup = types.InlineKeyboardMarkup()
    markup.add(btn_back)

    sent_msg = None
    try:
        sent_msg = bot.send_photo(
            chat_id, photo=qr_url, caption=caption_text,
            parse_mode="HTML", reply_markup=markup
        )
    except Exception as first_error:
        print(f"[UPI QR SEND ERROR] user={chat_id} order={order_ref}: {first_error}")
        try:
            sent_msg = bot.send_photo(
                chat_id, photo=qr_url,
                caption=_repair_telegram_html_markup(
                    _repair_premium_emoji_markup(caption_text)
                ),
                parse_mode="HTML",
                reply_markup=_sanitize_inline_markup_for_transport(markup),
            )
        except Exception as second_error:
            print(
                f"[UPI QR FALLBACK ERROR] user={chat_id} order={order_ref}: "
                f"{second_error}"
            )
            try:
                plain_caption = re.sub(
                    r"<tg-emoji\b[^>]*>(.*?)</tg-emoji>",
                    lambda m: m.group(1),
                    str(caption_text),
                    flags=re.I | re.S,
                )
                plain_caption = re.sub(r"<[^>]+>", "", plain_caption)
                sent_msg = bot.send_photo(
                    chat_id, photo=qr_url,
                    caption=html.unescape(plain_caption),
                    reply_markup=_sanitize_inline_markup_for_transport(markup),
                )
            except Exception as final_error:
                print(
                    f"[UPI QR FINAL ERROR] user={chat_id} order={order_ref}: "
                    f"{final_error}"
                )
                bot.send_message(
                    chat_id,
                    "❌ <b>Unable to display the UPI QR right now.</b>\n\n"
                    "Please tap <b>Pay via UPI</b> again.",
                    parse_mode="HTML",
                )
                return

    if sent_msg is None:
        return

    # Only now remove the old payment-method message.
    if message_id:
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass

    active_orders[order_ref] = {
        "chat_id": chat_id,
        "user_id": chat_id,
        "message_id": sent_msg.message_id,
        "amount": final_price,
        "pay_type": "purchase",
        "product_id": product_id,
        "device_id": device_id,
        "gateway": _get_active_payment_gateway(),
    }

    threading.Thread(
        target=poll_payment_in_bot,
        args=(
            chat_id, chat_id, sent_msg.message_id, order_ref,
            final_price, "purchase", product_id, device_id
        ),
        daemon=True,
        name=f"rg-payment-{order_ref}",
    ).start()


def _get_topup_keypad_amount(chat_id):
    try:
        return max(0, min(int(topup_keypad_state.get(int(chat_id), 0) or 0), 10000))
    except (TypeError, ValueError):
        return 0

def _set_topup_keypad_amount(chat_id, amount):
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        amount = 0
    topup_keypad_state[int(chat_id)] = max(0, min(amount, 10000))
    return topup_keypad_state[int(chat_id)]

def _clear_topup_keypad_state(chat_id):
    topup_keypad_state.pop(int(chat_id), None)

# Add Balance has its own template key so an old saved Add Balance layout
# cannot reappear after the UI was redesigned. Existing settings/data are kept.
ADD_BALANCE_TEXT_V2_KEY = "add_balance_text_v2"

# Separate Add Balance QR caption design. This is intentionally independent from
# the normal purchase QR text so admins can make the top-up screen match the
# Premium purchase/payment design without changing product checkout.
ADD_BALANCE_QR_TEXT_KEY = "add_balance_qr_text_v2"

DEFAULT_ADD_BALANCE_QR_TEXT = (
    "💰 <b>ADD BALANCE PAYMENT GATEWAY</b> 💰\n"
    "<i>Scan & Pay — Instant Wallet Credit</i>\n\n"
    "📋 <b>DEPOSIT DETAILS</b>\n"
    "├── 💵 <b>Add Amount:</b> {add_amount}\n"
    "└── 🆔 <b>Order ID:</b> <code>{order_id}</code>\n\n"
    "⏱️ <b>Expires in 5 minutes</b>\n"
    "🔥 <b>Instant Verification</b>\n\n"
    "💳 <b>How to Pay</b>\n"
    "➜ Scan the QR code above using any UPI App.\n"
    "➜ Pay the exact amount: <b>{add_amount}</b>\n"
    "➜ Your payment will be verified automatically!\n\n"
    "────────────────────────\n"
    "⚡ <i>Auto-checking live payment in background...</i>"
)

def get_add_balance_qr_text_template():
    return get_setting(ADD_BALANCE_QR_TEXT_KEY) or DEFAULT_ADD_BALANCE_QR_TEXT

def set_add_balance_qr_text_template(template):
    cleaned = _repair_premium_emoji_markup(str(template or "").strip())
    set_setting(ADD_BALANCE_QR_TEXT_KEY, cleaned)

def _render_add_balance_qr_text(amount, order_id):
    """Render the Add Balance QR caption with live amount/order ID.

    The saved template is presentation-only. Premium custom emojis and HTML
    formatting are preserved while transaction values are always generated live.
    """
    try:
        amount_value = float(amount)
    except (TypeError, ValueError):
        amount_value = 0.0

    live_amount = f"₹{amount_value:.2f} INR"
    purchase_date = datetime.datetime.now().strftime("%A, %d %b %Y %H:%M:%S")
    values = {
        "amount": live_amount,
        "add_amount": live_amount,
        "topup_amount": live_amount,
        "order_id": html.escape(str(order_id), quote=False),
        "date": html.escape(purchase_date, quote=False),
        "purchase_date": html.escape(purchase_date, quote=False),
    }

    rendered = _repair_premium_emoji_markup(get_add_balance_qr_text_template())
    rendered = _safe_format_custom_text(rendered, **values)

    # If the admin pasted an already-rendered sample instead of placeholders,
    # replace the labelled transaction fields with the current live values.
    rendered = _inject_labeled_user_values(
        rendered,
        {
            "amount": live_amount,
            "add_amount": live_amount,
            "topup_amount": live_amount,
            "order_id": html.escape(str(order_id), quote=False),
            "date": html.escape(purchase_date, quote=False),
        },
    )

    rendered = re.sub(
        r'(?im)^([^\n]*\b(?:Add\s+Amount|Amount\s+Adding|Top[- ]?up\s+Amount|Amount)\b[^:\n]*:\s*)[^\n]*$',
        lambda m: m.group(1) + live_amount,
        rendered,
    )
    rendered = re.sub(
        r'(?im)^([^\n]*\bOrder\s+ID\b[^:\n]*:\s*)[^\n]*$',
        lambda m: m.group(1) + f'<code>{html.escape(str(order_id), quote=False)}</code>',
        rendered,
    )
    return _repair_telegram_html_markup(_repair_premium_emoji_markup(rendered).strip())

DEFAULT_ADD_BALANCE_TEXT = (
    "💰 <b>ADD BALANCE TO WALLET</b>\n"
    "<b>Current balance :</b> ₹{balance} INR\n\n"
    "📉 <b>Minimum Deposit :</b> ₹1 INR\n\n"
    "↗️ <b>Maximum Deposit :</b> ₹10,000\n\n"
    "💎 <b>Amount:</b> {amount}\n\n"
    "👑 <i>Use the keypad below to enter amount</i>"
)

def get_add_balance_text_template():
    # Only the new editor/template is used. The legacy custom_text_top_up
    # remains stored but is intentionally not rendered by the Add Balance UI.
    return get_setting(ADD_BALANCE_TEXT_V2_KEY) or DEFAULT_ADD_BALANCE_TEXT

def set_add_balance_text_template(template):
    cleaned = _repair_premium_emoji_markup(str(template or "").strip())
    # Never convert Premium custom emojis to normal Unicode in the saved
    # template; keep their Telegram <tg-emoji emoji-id="..."> wrappers intact.
    set_setting(ADD_BALANCE_TEXT_V2_KEY, cleaned)

def _render_add_balance_keypad_text(chat_id, amount=None):
    # Every value here is resolved per-user/per-render; no user's balance is
    # ever stored in the shared presentation template.
    user = get_user(chat_id)
    curr_bal = float(user[4] if user else 0.0)
    amount = _get_topup_keypad_amount(chat_id) if amount is None else int(amount)

    template = get_add_balance_text_template()
    values = _get_user_template_values(chat_id, user[1] if user else None)
    live_amount = f"₹{amount} INR"
    live_balance = f"{curr_bal:.2f}"

    values.update({
        "user": values.get("name", "User"),
        "first_name": values.get("name", "User"),
        "balance": live_balance,
        "current_balance": f"₹{live_balance} INR",
        "amount": live_amount,
        "add_amount": live_amount,
        "topup_amount": live_amount,
        "after_deposit": f"₹{curr_bal + amount:.2f} INR",
        "minimum_deposit": "₹1 INR",
        "max_deposit": "₹10,000",
        "maximum_deposit": "₹10,000",
    })

    text = _safe_format_custom_text(template, **values)

    # Force transaction/account fields to stay live even if the admin copied
    # an old rendered sample into the new editor.
    text = _inject_labeled_user_values(text, {
        "name": values.get("name", "User"),
        "username": values.get("username", ""),
        "username_at": values.get("username_at", ""),
        "user_id": str(chat_id),
        "phone": values.get("phone", "N/A"),
        "country": values.get("country", "IN"),
        "balance": f"₹{live_balance} INR",
        "ref_balance": values.get("ref_balance", "0.00"),
        "orders": values.get("orders", "0"),
        "lifetime": values.get("lifetime", "0.00"),
        "deposited": values.get("deposited", "0.00"),
        "joined": values.get("joined", "N/A"),
        "amount": live_amount,
        "add_amount": live_amount,
        "topup_amount": live_amount,
        "after_deposit": f"₹{curr_bal + amount:.2f} INR",
    })

    # These limits are fixed by the requested Add Balance rules.
    text = re.sub(
        r'(?im)^([^\n]*\b(?:Minimum|Min)\s+Deposit\b[^:\n]*:\s*)[^\n]*$',
        lambda m: m.group(1) + "₹1 INR",
        text,
    )
    text = re.sub(
        r'(?im)^([^\n]*\b(?:Maximum|Max)\s+Deposit\b[^:\n]*:\s*)[^\n]*$',
        lambda m: m.group(1) + "₹10,000",
        text,
    )
    text = re.sub(
        r'(?im)^([^\n]*\b(?:Amount|Adding|Amount Adding|Top[- ]?up Amount)\b[^:\n]*:\s*)[^\n]*$',
        lambda m: m.group(1) + live_amount,
        text,
    )

    # The requested Add Balance design uses exactly one money symbol for the
    # Current Balance line. Only that line is normalized; all other custom text
    # and Premium emojis remain untouched.
    lines=[]
    for _line in text.splitlines():
        plain=re.sub(r'<[^>]+>','',_line).lower()
        if 'current balance' in plain:
            _line=re.sub(r'₹\s*₹+', '₹', _line)
            _line=re.sub(r'(?i)(current\s+balance\s*:\s*)(?:₹\s*)+', r'\1₹', _line)
        lines.append(_line)
    text='\n'.join(lines)

    return _repair_telegram_html_markup(_repair_premium_emoji_markup(text).strip())

def _build_add_balance_keypad_markup():
    markup = types.InlineKeyboardMarkup(row_width=3)
    for row in ((1, 2, 3), (4, 5, 6), (7, 8, 9)):
        markup.row(*[
            make_ui_button(str(d), callback_data=f"topkey_d_{d}",
                           button_key=f"topkey:{d}", default_color="blue")
            for d in row
        ])
    markup.row(
        make_ui_button(
            _special_button_text(ADD_BALANCE_CANCEL_BUTTON_KEY, "❌ Cancel"),
            callback_data="topkey_clear",
            button_key=ADD_BALANCE_CANCEL_BUTTON_KEY,
            default_color="red"
        ),
        make_ui_button("0", callback_data="topkey_d_0",
                       button_key="topkey:0", default_color="blue"),
        make_ui_button(
            _special_button_text(ADD_BALANCE_CONFIRM_BUTTON_KEY, "💳 Confirm"),
            callback_data="topkey_confirm",
            button_key=ADD_BALANCE_CONFIRM_BUTTON_KEY,
            default_color="green"
        ),
    )
    markup.add(make_ui_button("❌ Back", callback_data="topkey_back",
                              button_key="nav:back_topup", default_color="red"))
    return markup

def show_topup_options(chat_id, message_id=None):
    _set_topup_keypad_amount(chat_id, 0)
    render_or_edit(
        chat_id, message_id,
        _render_add_balance_keypad_text(chat_id, 0),
        _build_add_balance_keypad_markup()
    )

def _html_to_plain_text_with_custom_emoji_entities(html_text):
    """Build plain text + Telegram custom-emoji entities as an edit fallback.

    The normal path uses HTML so the saved Add Balance design keeps all
    formatting and Premium custom emojis. If Telegram rejects that HTML during
    an edit, this fallback uses explicit custom_emoji MessageEntity objects so
    the Premium IDs are still preserved and the keypad remains live.
    """
    value = _repair_premium_emoji_markup(str(html_text or ""))
    plain_parts = []
    entities = []
    cursor_utf16 = 0
    pos = 0

    tag_re = re.compile(
        r'<tg-emoji\s+emoji-id=["\']([^"\']+)["\']>(.*?)</tg-emoji>',
        re.I | re.S
    )

    def utf16_len(text):
        return len(str(text).encode("utf-16-le")) // 2

    for match in tag_re.finditer(value):
        before = value[pos:match.start()]
        before_plain = html.unescape(re.sub(r'<[^>]+>', '', before))
        plain_parts.append(before_plain)
        cursor_utf16 += utf16_len(before_plain)

        visible = html.unescape(re.sub(r'<[^>]+>', '', match.group(2)))
        emoji_id = str(match.group(1)).strip()
        if visible and emoji_id:
            entities.append(
                types.MessageEntity(
                    type="custom_emoji",
                    offset=cursor_utf16,
                    length=utf16_len(visible),
                    custom_emoji_id=emoji_id,
                )
            )
        plain_parts.append(visible)
        cursor_utf16 += utf16_len(visible)
        pos = match.end()

    tail = value[pos:]
    tail_plain = html.unescape(re.sub(r'<[^>]+>', '', tail))
    plain_parts.append(tail_plain)
    return ''.join(plain_parts), entities


def _update_topup_keypad_message(chat_id, message_id):
    """Update the same Add Balance message immediately after every digit.

    The old code swallowed every edit error, so an HTML/custom-emoji parsing
    failure left the user seeing the old ₹0 forever. The amount is now stored
    first and the edit has two safe fallbacks.
    """
    text = _render_add_balance_keypad_text(chat_id)
    markup = _build_add_balance_keypad_markup()

    # 1) Normal HTML path: complete saved design + Premium emojis.
    try:
        bot.edit_message_text(
            text,
            chat_id,
            message_id,
            parse_mode="HTML",
            reply_markup=markup,
        )
        return True
    except Exception as html_error:
        last_error = html_error

    # 2) Explicit custom-emoji entities: Premium IDs survive even when the
    # HTML parser rejects the payload.
    try:
        plain_text, entities = _html_to_plain_text_with_custom_emoji_entities(text)
        if entities:
            bot.edit_message_text(
                plain_text,
                chat_id,
                message_id,
                entities=entities,
                reply_markup=markup,
            )
        else:
            bot.edit_message_text(
                plain_text,
                chat_id,
                message_id,
                reply_markup=markup,
            )
        return True
    except Exception as entity_error:
        last_error = entity_error

    # 3) Last-resort plain-text edit keeps the keypad functional for very old
    # Telegram libraries. This path is only reached if both richer transports
    # fail; the Premium-emoji design remains saved for the next render.
    try:
        plain_text = re.sub(
            r'<tg-emoji\b[^>]*>(.*?)</tg-emoji>',
            lambda m: m.group(1),
            text,
            flags=re.I | re.S,
        )
        plain_text = re.sub(r'<[^>]+>', '', plain_text)
        plain_text = html.unescape(plain_text)
        bot.edit_message_text(
            plain_text,
            chat_id,
            message_id,
            reply_markup=markup,
        )
        return True
    except Exception:
        print(
            f"[TOPUP UI] Failed to update chat={chat_id}, message={message_id}: "
            f"{last_error!r}"
        )
        return False

def show_topup_confirm(chat_id, amount, message_id=None):
    # Legacy callback compatibility: seed the new keypad instead of showing
    # the old fixed payment-method screen.
    try:
        amount = int(float(amount))
    except (TypeError, ValueError):
        amount = 0
    if 1 <= amount <= 10000:
        _set_topup_keypad_amount(chat_id, amount)
        if message_id:
            _update_topup_keypad_message(chat_id, message_id)
        else:
            show_topup_options(chat_id)
    else:
        show_topup_options(chat_id, message_id=message_id)

def show_topup_upi_screen(chat_id, amount, message_id=None):
    try:
        amount = int(float(amount))
    except (TypeError, ValueError):
        amount = 0
    if not 1 <= amount <= 10000:
        show_topup_options(chat_id, message_id=message_id)
        return

    _clear_topup_keypad_state(chat_id)
    if message_id:
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass

    try:
        qr_url, order_ref = _create_active_gateway_qr(amount)
    except Exception as exc:
        bot.send_message(
            chat_id,
            '❌ <b>Payment Gateway Setup Error</b>\n\n' + html.escape(str(exc)[:800]),
            parse_mode='HTML'
        )
        return
    # Add Balance now uses its own Premium-editable QR design. The live amount
    # and gateway Order ID are injected on every request, exactly like product
    # checkout, so a copied admin sample can never leak an old transaction.
    caption_text = _render_add_balance_qr_text(amount, order_ref)
    markup = types.InlineKeyboardMarkup()
    markup.add(make_ui_button("🔙 Back to Main", callback_data="back_from_qr",
                              button_key="nav:back_qr", default_color="blue"))
    sent_msg = bot.send_photo(chat_id, photo=qr_url, caption=caption_text,
                              parse_mode="HTML", reply_markup=markup)
    active_orders[order_ref] = {
        "chat_id": chat_id, "user_id": chat_id,
        "message_id": sent_msg.message_id, "amount": amount,
        "pay_type": "topup", "product_id": 0,
        "gateway": _get_active_payment_gateway(),
    }
    threading.Thread(
        target=poll_payment_in_bot,
        args=(chat_id, chat_id, sent_msg.message_id, order_ref, amount, "topup", 0),
        daemon=True
    ).start()

def show_help_desk(chat_id, message_id=None):
    default_help_text = (
        f"🛟 <b>{html.escape(BOT_BRAND_NAME)} — Support</b>\n\n"
        f"🎧 <i>Our team is here to help you.</i>\n\n"
        f"<b>We can assist with:</b>\n"
        f"├── 🔑 Orders & key delivery\n"
        f"├── 💰 Payments & balance\n"
        f"├── ❓ Product questions\n"
        f"└── ⚙️ Any other issue\n\n"
        f"⏱️ <i>Typical reply time: within a few hours.</i>\n\n"
        f"<i>Tap a button below to contact us directly 👇</i>"
    )
    help_template = get_custom_text("help_desk", default_help_text)
    help_user = get_user(chat_id)
    help_name = help_user[1] if help_user else "User"
    help_phone = help_user[2] if help_user and len(help_user) > 2 and help_user[2] else "N/A"
    help_text = _safe_format_custom_text(
        help_template,
        user=help_name,
        name=help_name,
        user_id=chat_id,
        telegram_id=chat_id,
        phone=help_phone,
        number=help_phone,
    )

    markup = types.InlineKeyboardMarkup()
    tg_id = get_support_setting(TELEGRAM_SUPPORT_ID_KEY, TELEGRAM_USER).lstrip('@')
    wa_num = re.sub(r'\D', '', get_support_setting(WHATSAPP_SUPPORT_NUMBER_KEY, WHATSAPP_NUM))
    if _support_is_visible(TELEGRAM_SUPPORT_SHOW_KEY, True) and tg_id:
        btn_telegram = make_ui_button("💬 Chat on Telegram", url=_telegram_support_url(tg_id), button_key="link:telegram_support", default_color="blue")
        markup.add(btn_telegram)
    if _support_is_visible(WHATSAPP_SUPPORT_SHOW_KEY, True) and wa_num:
        btn_whatsapp = make_ui_button("📱 Chat on WhatsApp", url=f"https://wa.me/{wa_num}", button_key="link:whatsapp_support", default_color="green")
        markup.add(btn_whatsapp)
    btn_back = make_ui_button("🔙 Back to Main", callback_data="back_to_main", button_key="nav:back_main", default_color="blue")
    markup.add(btn_back)

    render_or_edit(chat_id, message_id, help_text, markup)

def show_how_to_use_bot(chat_id, message_id=None):
    global guide_video_url
    markup = types.InlineKeyboardMarkup()
    
    if guide_video_url:
        default_guide_text = (
            f"🎬 <b>HOW TO USE BOT</b>\n"
            f"────────────────────────\n\n"
            f"Watch our complete tutorial video to learn how to purchase, top-up balance, and claim your cheat keys automatically!\n\n"
            f"👇 <b>Click the button below to watch guide:</b>"
        )
        markup.add(make_ui_button("▶️ Watch Guide Video", url=guide_video_url, button_key="link:guide", default_color="blue"))
    else:
        default_guide_text = (
            f"🎬 <b>HOW TO USE BOT</b>\n"
            f"────────────────────────\n\n"
            f"ℹ️ <i>Tutorial video guide is currently being updated! Please check back soon.</i>\n\n"
            f"For immediate help, contact support using <b>Help Desk</b>."
        )

    # Admin can now edit this entire text section from Text Editor, including
    # Telegram Premium custom emojis. The saved template is presentation-only;
    # the guide URL/button remains controlled separately by the existing setting.
    guide_text = get_custom_text("how_to_use", default_guide_text)

    btn_back = make_ui_button("🔙 Back to Main", callback_data="back_to_main", button_key="nav:back_main", default_color="blue")
    markup.add(btn_back)

    render_or_edit(chat_id, message_id, guide_text, markup)

def _render_order_history_custom_template(template, orders):
    """Render live Order History from the admin's exact Premium-emoji skeleton.

    The admin message is a visual template, not a data record. Premium emoji
    markup is copied from the exact sample line where it was configured.
    Live values are injected semantically (or by the explicit placeholder) so
    an emoji can never be reassigned merely because another emoji was added or
    removed elsewhere in the message.

    Supported live placeholders:
      {order_id}, {product_name}/{hack}, {days}/{plan_days},
      {price}/{amount}, {date_time}/{date}, {key}/{purchased_key}.
    """
    if not template:
        return ""

    text = _repair_premium_emoji_markup(str(template).strip())
    if "{orders_list}" in text or "{{orders_list}}" in text:
        token = "{orders_list}" if "{orders_list}" in text else "{{orders_list}}"
        return text.replace(token, _build_default_live_orders(orders))

    lines = text.splitlines()

    def plain(line):
        value = re.sub(r"<tg-emoji\b[^>]*>.*?</tg-emoji>", "", str(line), flags=re.I | re.S)
        value = re.sub(r"<[^>]+>", "", value)
        return html.unescape(value).strip()

    def is_order_id_line(line):
        raw = str(line)
        p = plain(line)
        return bool(
            re.search(r"\{?\{?order_id\}?\}?", raw, re.I)
            or re.search(r"\b(?:WAL|ORD|ORDER)[_-]?\d{6,}\b", p, re.I)
            or re.search(r"\b\d{10,}\b", p)
        )

    recent_idx = next(
        (i for i, line in enumerate(lines)
         if re.search(r"\brecent\s+orders?\b", plain(line), re.I)),
        None
    )

    if recent_idx is None:
        return _repair_premium_emoji_markup(
            text.rstrip() + ("\n\n" + _build_default_live_orders(orders) if orders else "")
        )

    first_order = next(
        (i for i in range(recent_idx + 1, len(lines)) if is_order_id_line(lines[i])),
        None
    )

    if first_order is None:
        if not orders:
            # No purchased items: never expose a copied/sample order.
            return text
        return _repair_premium_emoji_markup(
            "\n".join(lines[:recent_idx + 1]).rstrip()
            + "\n"
            + _build_default_live_orders(orders).rstrip()
        )

    # Capture exactly one sample order block. Everything after the next sample
    # order is treated as stale copied data/footer and is not repeated.
    block_end = first_order
    next_order = None
    for i in range(first_order + 1, len(lines)):
        if is_order_id_line(lines[i]):
            next_order = i
            break
        if not lines[i].strip():
            block_end = i - 1
            break
        block_end = i

    sample = [x for x in lines[first_order:block_end + 1] if x.strip()]

    footer_start = block_end + 1
    if next_order is not None:
        footer_start = next_order
        while footer_start < len(lines) and is_order_id_line(lines[footer_start]):
            j = footer_start + 1
            while j < len(lines) and lines[j].strip() and not is_order_id_line(lines[j]):
                j += 1
            footer_start = j
            while footer_start < len(lines) and not lines[footer_start].strip():
                footer_start += 1

    footer = lines[footer_start:] if footer_start < len(lines) else []

    field_tokens = {
        0: ("order_id",),
        1: ("product_name", "hack", "days", "plan_days"),
        2: ("price", "amount"),
        3: ("date_time", "date"),
        4: ("key", "purchased_key"),
    }

    def normalize_placeholder_line(line):
        """Return (line, field) for explicit placeholders, if any."""
        raw = str(line)
        checks = [
            (0, ("{order_id}", "{{order_id}}")),
            (1, ("{product_name}", "{{product_name}}", "{hack}", "{{hack}}",
                 "{days}", "{{days}}", "{plan_days}", "{{plan_days}}")),
            (2, ("{price}", "{{price}}", "{amount}", "{{amount}}")),
            (3, ("{date_time}", "{{date_time}}", "{date}", "{{date}}")),
            (4, ("{key}", "{{key}}", "{purchased_key}", "{{purchased_key}}")),
        ]
        for field, tokens in checks:
            if any(token in raw for token in tokens):
                return True, field
        return False, None

    def classify_implicit_field(line):
        """Infer the field from the sample's visible text, never from emoji ID."""
        p = plain(line)
        low = p.lower()

        # Strongest signal first: order ID.
        if is_order_id_line(line):
            return 0

        # Key/status line. This is intentionally checked before date because
        # "Key assigned!" lines can also contain punctuation/digits.
        if re.search(r"\b(key\s+assigned|key\s*[:#]|license\s*[:#]|contact\s+admin)\b", low, re.I):
            return 4

        # Product/day line.
        if re.search(r"\b\d+\s*(?:d|day|days|h|hour|hours)\b", low, re.I):
            return 1
        if re.search(r"\b(?:product|hack|panel)\s*[:\-]", low, re.I):
            return 1

        # Money/price line.
        if "₹" in p or re.search(r"\binr\b", low) or re.search(r"\b(?:price|amount|cost|money)\s*[:\-]", low, re.I):
            return 2

        # Date/time line. IST is a particularly strong signal in this bot.
        if re.search(r"\b(?:ist|am|pm)\b", low, re.I):
            return 3
        if re.search(r"\b(?:date|time|purchased|bought)\s*[:\-]", low, re.I):
            return 3
        if re.search(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b", low, re.I):
            return 3

        return None

    def replace_visible_line(line, new_value):
        """Replace only the sample's visible value; preserve Premium HTML exactly."""
        value = html.escape(str(new_value), quote=False)
        original = str(line)

        matches = list(re.finditer(r"</tg-emoji>", original, re.I))
        if matches:
            cut = matches[-1].end()
            prefix = original[:cut]
            rest = original[cut:]

            # Preserve separators/tree characters and opening formatting tags.
            leading = re.match(
                r"(\s*(?:├──|└──|├─|└─|│|─|—|>|\s)*(?:<b>|<i>|<u>|<s>|<code>)*\s*)",
                rest,
                re.I
            )
            lead = leading.group(1) if leading else " "

            closing = ""
            # Preserve only formatting closures that already existed after the
            # sample value. The emoji wrapper itself is never removed.
            closings = re.findall(r"</(?:b|i|u|s|code)>", rest, flags=re.I)
            if closings:
                closing = closings[-1]

            return prefix + lead + value + closing

        # No Premium emoji on this line: preserve the visual tree prefix.
        m = re.match(r"^(\s*(?:├──|└──|├─|└─|│|─|—|>)+\s*)", original)
        prefix = m.group(1) if m else ""
        return prefix + value

    def replace_placeholders(line, vals):
        out = str(line)
        for key, value in vals.items():
            safe = html.escape(str(value), quote=False)
            out = out.replace("{{" + key + "}}", safe)
            out = out.replace("{" + key + "}", safe)
        return out

    def render_sample(order):
        ord_id, p_name, p_days, price, key_val, dt = order
        days = str(p_days or "").strip()
        amount = f"₹{float(price):.2f} INR"
        key_text = str(key_val or "").strip()

        vals = {
            "order_id": ord_id,
            "product_name": p_name,
            "hack": p_name,
            "days": days,
            "plan_days": days,
            "price": amount,
            "amount": amount,
            "date_time": dt,
            "date": dt,
            "key": key_text,
            "purchased_key": key_text,
        }

        out = []
        used_fields = set()
        fallback_index = 0

        for raw_line in sample:
            raw_line = str(raw_line)
            has_placeholder, explicit_field = normalize_placeholder_line(raw_line)

            if has_placeholder:
                if explicit_field == 4 and not key_text:
                    # No purchased/assigned key: hide the key field completely.
                    continue
                out.append(replace_placeholders(raw_line, vals))
                used_fields.add(explicit_field)
                continue

            field = classify_implicit_field(raw_line)

            # If the sample was intentionally left blank except for its Premium
            # emoji, use the original visual order as a LAST RESORT. This is not
            # an emoji-ID mapping; it is only a fallback for blank sample rows.
            if field is None:
                while fallback_index in used_fields:
                    fallback_index += 1
                if fallback_index <= 4 and re.search(r"<tg-emoji\b", raw_line, re.I):
                    field = fallback_index
                    fallback_index += 1

            if field is None or field in used_fields:
                # Decorative/sample text stays exactly as the admin sent it.
                out.append(raw_line)
                continue

            if field == 4 and not key_text:
                # No key was purchased/assigned, so do not expose a fake key or
                # stale "Key assigned" sample line.
                used_fields.add(field)
                continue

            if field == 0:
                new_value = ord_id
            elif field == 1:
                p = plain(raw_line)
                # Product rows commonly use a bold product name followed by an
                # italic validity value. Update those two text nodes separately
                # so the admin's formatting and Premium emoji remain untouched.
                if re.search(r"<i>.*?</i>", raw_line, re.I | re.S):
                    line = re.sub(
                        r"(<b>)(.*?)(</b>)",
                        lambda m: m.group(1) + html.escape(str(p_name), quote=False) + m.group(3),
                        raw_line,
                        count=1,
                        flags=re.I | re.S,
                    )
                    line = re.sub(
                        r"(<i>)(.*?)(</i>)",
                        lambda m: m.group(1) + html.escape(str(days), quote=False) + m.group(3),
                        line,
                        count=1,
                        flags=re.I | re.S,
                    )
                    out.append(line)
                    used_fields.add(field)
                    continue

                if "·" in p:
                    new_value = f"{p_name} · {days}"
                elif re.search(r"\b\d+\s*(?:day|days|hour|hours)\b", p, re.I):
                    # Preserve the sample separator if it used a plain dash.
                    sep = " - " if "-" in p else " · "
                    new_value = f"{p_name}{sep}{days}"
                else:
                    new_value = f"{p_name} · {days}"
            elif field == 2:
                new_value = amount
            elif field == 3:
                new_value = dt
            else:
                # Keep the admin's status/warning text but place the real key
                # immediately after the last Premium emoji when no explicit
                # {key} placeholder was supplied.
                p = plain(raw_line)
                if re.search(r"key\s+assigned|contact\s+admin", p, re.I):
                    matches = list(re.finditer(r"</tg-emoji>", raw_line, re.I))
                    if matches:
                        cut = matches[-1].end()
                        line = (
                            raw_line[:cut]
                            + " <code>"
                            + html.escape(key_text, quote=False)
                            + "</code>"
                            + raw_line[cut:]
                        )
                    else:
                        line = raw_line + " <code>" + html.escape(key_text, quote=False) + "</code>"
                    out.append(line)
                    used_fields.add(field)
                    continue
                new_value = key_text

            out.append(replace_visible_line(raw_line, new_value))
            used_fields.add(field)

        return "\n".join(out)

    prefix = lines[:first_order]
    parts = ["\n".join(prefix).rstrip()]

    # Never expose the admin's sample purchase to a user with no purchases.
    if orders:
        parts.append("\n\n".join(render_sample(order) for order in orders))
    else:
        parts.append("")

    if footer:
        parts.append("\n".join(footer).strip())

    return _repair_premium_emoji_markup("\n\n".join(p for p in parts if p).strip())


def _build_default_live_orders(orders):
    """Legacy fallback only when the admin template has no sample order block."""
    result = []
    for ord_id, p_name, p_days, price, key_val, dt in orders:
        result.append(
            f"✅ <b>{html.escape(str(ord_id), quote=False)}</b>\n"
            f"├── 📦 <b>{html.escape(str(p_name), quote=False)}</b> · <i>{html.escape(str(p_days), quote=False)}</i>\n"
            f"├── 💰 <b>₹{price:.2f} INR</b>\n"
            f"├── ⏰ <b>{html.escape(str(dt), quote=False)}</b>\n"
            f"└── 🔑 <code>{html.escape(str(key_val or ''), quote=False)}</code>\n"
        )
    return "\n".join(result)


def _inject_order_history_live_totals(text, user):
    """Fill Total spent/deposited/balance labels in the saved design.

    The admin is allowed to leave the value blank (for example ``Total spent:``).
    We only replace the value portion; Premium emoji wrappers and formatting before
    the label remain untouched.
    """
    if not text:
        return text
    lifetime = float(user[7] or 0) if user else 0.0
    deposited = float(user[8] or 0) if user else 0.0
    balance = float(user[4] or 0) if user else 0.0
    orders_count = int(user[6] or 0) if user else 0

    lines = []
    for line in str(text).splitlines():
        plain_line = re.sub(r"<tg-emoji\b[^>]*>.*?</tg-emoji>", "", line, flags=re.I | re.S)
        plain_line = re.sub(r"<[^>]+>", "", plain_line)
        low = html.unescape(plain_line).lower()

        if "total spent" in low:
            # Preserve the label and all Premium emoji/HTML before the colon.
            line = re.sub(
                r"(total\s+spent\s*:\s*)(?:</b>\s*)?(.*)$",
                lambda m: m.group(1) + "</b> " + f"₹{lifetime:.2f} INR ({orders_count} orders)",
                line, count=1, flags=re.I
            )
        elif "total deposited" in low:
            line = re.sub(
                r"(total\s+deposited\s*:\s*)(?:</b>\s*)?(.*)$",
                lambda m: m.group(1) + "</b> " + f"₹{deposited:.2f} INR",
                line, count=1, flags=re.I
            )
        elif re.search(r"\bbalance\s*:", low):
            line = re.sub(
                r"(balance\s*:\s*)(?:</b>\s*)?(.*)$",
                lambda m: m.group(1) + "</b> " + f"₹{balance:.2f} INR",
                line, count=1, flags=re.I
            )
        lines.append(line)
    return "\n".join(lines)


def show_orders_history(chat_id, user_id, message_id=None):
    user = get_user(user_id)
    lifetime = user[7] if user else 0.0
    orders_count = user[6] if user else 0
    deposited = user[8] if user else 0.0
    balance = user[4] if user else 0.0

    # ALWAYS fetch orders by the current Telegram user ID. No shared/sample order
    # is ever used as live data.
    orders = get_user_orders(user_id)

    default_history_text = (
        f"📜 <b>ALL HISTORY</b>\n"
        f"────────────────────────\n"
        f"├── 💎 <b>Total spent:</b> ₹{lifetime:.2f} INR ({orders_count} orders)\n"
        f"└── 📥 <b>Total deposited:</b> ₹{deposited:.2f} INR\n\n"
        f"🛍️ <b>Recent Orders</b>\n"
        f"────────────────────────\n"
    )

    history_template = get_custom_text("order_history", "")
    saved_ids = _get_saved_order_history_premium_ids()

    # Migrate Premium IDs from an already-saved template when the recovery cache
    # is empty. This makes existing installations work without asking the admin
    # to send the Premium emojis again.
    if history_template:
        template_ids = _premium_emoji_ids_from_template(history_template)
        if template_ids:
            saved_ids = template_ids
            set_setting("order_history_premium_emoji_ids", json.dumps(template_ids, ensure_ascii=False))
        elif saved_ids:
            # Old/broken saved text contained only normal Unicode emoji. Replace
            # that renderer with the Premium recovery design automatically.
            recovered = _build_order_history_premium_fallback(saved_ids)
            if recovered:
                history_template = recovered

    # Recovery path: if there is no usable custom template, rebuild a complete
    # Premium design from the IDs already saved in the database. No manual Premium
    # emoji editing is required.
    if not history_template:
        history_template = _build_order_history_premium_fallback(saved_ids)

    if history_template:
        history_text = _render_order_history_custom_template(history_template, orders)
    else:
        history_text = default_history_text + _build_default_live_orders(orders)

    # Live account totals/balance are injected after the visual template render so
    # the admin can leave those values blank and still get correct per-user data.
    history_text = _inject_order_history_live_totals(history_text, user)

    live_username = _get_live_telegram_username(user_id)
    history_text = _safe_format_custom_text(
        history_text,
        user=(user[1] if user else "User"),
        name=(user[1] if user else "User"),
        username=live_username,
        telegram_username=live_username,
        user_id=user_id,
        telegram_id=user_id,
        phone=(user[2] if user and len(user) > 2 and user[2] else "N/A"),
        balance=f"{balance:.2f}",
        ref_balance=f"{user[5]:.2f}" if user else "0.00",
        orders=orders_count,
        lifetime=f"{lifetime:.2f}",
        deposited=f"{deposited:.2f}",
        orders_list=_build_default_live_orders(orders),
    )

    history_text = _inject_labeled_user_values(
        history_text,
        {
            "name": html.escape(str(user[1] if user else "User"), quote=False),
            "username": html.escape(str(live_username), quote=False),
            "username_at": html.escape(f"@{live_username}" if live_username else "", quote=False),
            "user_id": str(user_id),
            "phone": html.escape(str(user[2] if user and len(user) > 2 and user[2] else "N/A"), quote=False),
            "balance": f"{balance:.2f}",
            "ref_balance": f"{user[5]:.2f}" if user else "0.00",
            "orders": str(orders_count),
            "lifetime": f"{lifetime:.2f}",
            "deposited": f"{deposited:.2f}",
        }
    )

    markup = types.InlineKeyboardMarkup()
    btn_back = make_ui_button("🔙 Back to Main", callback_data="back_to_main", button_key="nav:back_main", default_color="blue")
    markup.add(btn_back)

    render_or_edit(chat_id, message_id, history_text, markup)


def _inject_referral_link_value(text, ref_link):
    """Always inject the LIVE referral link into a custom Referral Program template.

    Admins often save a formatted message copied from Telegram. In that case the
    visible URL may be missing even though the template contains labels such as
    ``Your Invite Link:`` or ``Your URL Link:``. This helper restores the current
    user's referral URL without changing the surrounding Premium emoji/HTML design.

    Supported forms:
      • Your Invite Link: {ref_link}
      • Your Invite Link:                    -> URL is inserted after ':'
      • Your Invite Link: (blank next line)  -> URL is inserted on that next line
    """
    if not text or not ref_link:
        return text

    value = html.escape(str(ref_link), quote=False)
    link_markup = f"<code>{value}</code>"
    lines = str(text).splitlines()

    labels = re.compile(
        r"\b(?:your\s+(?:invite|referral|url)\s+link|invite\s+link|referral\s+link|ref\s+link)\b",
        re.I,
    )

    # First, replace explicit placeholders wherever they exist.
    replaced_placeholder = False
    for i, line in enumerate(lines):
        if labels.search(re.sub(r"<[^>]+>", "", line)):
            for token in ("{ref_link}", "{{ref_link}}", "{invite_link}", "{{invite_link}}"):
                if token in lines[i]:
                    lines[i] = lines[i].replace(token, link_markup)
                    replaced_placeholder = True

    # Then handle a copied Telegram layout where the link was never saved as a
    # placeholder. Put the URL after the label's colon if that field is blank.
    for i, line in enumerate(lines):
        plain = re.sub(r"<[^>]+>", "", line).strip()
        if not labels.search(plain):
            continue

        # Already contains a real URL or placeholder-generated value.
        if re.search(r"https?://t\.me/", plain, re.I):
            return "\n".join(lines)

        colon = re.match(r"^(.*?:)(\s*)$", line)
        if colon:
            lines[i] = colon.group(1) + " " + link_markup
            return "\n".join(lines)

        # If the label is a heading with a blank line immediately below it,
        # insert the URL there instead of disturbing the user's layout.
        if i + 1 < len(lines) and not lines[i + 1].strip():
            lines[i + 1] = link_markup
            return "\n".join(lines)

        # Label without ':' and without a blank next line: append the URL.
        lines[i] = line.rstrip() + " " + link_markup
        return "\n".join(lines)

    # If no label exists at all, do not silently alter the custom design. The
    # admin can use {ref_link}; the normal/default template already contains it.
    return "\n".join(lines) if replaced_placeholder else text


def show_referral_program(chat_id, user_id, message_id=None):
    user = get_user(user_id)
    ref_count = user[14] if user and len(user) > 14 else 0
    ref_bal = user[5] if user else 0.0

    bot_info = bot.get_me()
    bot_username = bot_info.username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    default_ref_text = (
        f"🎁 <b>REFERRAL PROGRAM</b>\n"
        f"────────────────────────\n"
        f"💰 <b>Earn ₹2.00 INR added directly to your wallet for every friend who joins & verifies their phone number using your referral link!</b>\n\n"
        f"📊 <b>Your Stats</b>\n"
        f"├── 👥 <b>Referrals Verified:</b> {ref_count}\n"
        f"└── 💼 <b>Ref Earnings:</b> ₹{ref_bal:.2f} INR\n\n"
        f"🔗 <b>Your Link</b>\n"
        f"<code>{ref_link}</code> <i>(tap to copy)</i>\n\n"
        f"<i>Share & earn real balance!</i>"
    )

    ref_template = get_custom_text("referral_program", default_ref_text)
    live_username = _get_live_telegram_username(user_id)
    ref_values = {
        "user": (user[1] if user else "User"),
        "name": (user[1] if user else "User"),
        "username": live_username,
        "telegram_username": live_username,
        "user_id": user_id,
        "telegram_id": user_id,
        "phone": (user[2] if user and len(user) > 2 and user[2] else "N/A"),
        "ref_link": ref_link,
        "invite_link": ref_link,
        "referrals": ref_count,
        "ref_balance": f"{ref_bal:.2f}",
        "balance": f"{user[4]:.2f}" if user else "0.00",
    }

    # Render all normal placeholders first.
    ref_text = _safe_format_custom_text(ref_template, **ref_values)

    # Restore live account fields for copied/labeled templates.
    ref_text = _inject_labeled_user_values(
        ref_text,
        {
            "name": html.escape(str(user[1] if user else "User"), quote=False),
            "username": html.escape(str(live_username), quote=False),
            "username_at": html.escape(f"@{live_username}" if live_username else "", quote=False),
            "user_id": str(user_id),
            "phone": html.escape(str(user[2] if user and len(user) > 2 and user[2] else "N/A"), quote=False),
            "balance": f"{user[4]:.2f}" if user else "0.00",
            "ref_balance": f"{ref_bal:.2f}",
            "orders": str(user[6] if user and len(user) > 6 else 0),
        }
    )

    # IMPORTANT: do this AFTER custom-text rendering. This fixes the exact case
    # where the admin only changed Premium emojis/text and left the link field blank.
    ref_text = _inject_referral_link_value(ref_text, ref_link)
    ref_text = _repair_premium_emoji_markup(ref_text)

    markup = types.InlineKeyboardMarkup()
    from urllib.parse import quote
    share_text = quote(f"Join {BOT_BRAND_NAME} to get instant VIP Gaming Cheats Keys!")
    share_url = f"https://t.me/share/url?url={quote(ref_link, safe='')}&text={share_text}"

    btn_send = make_ui_button(
        "📩 Send Link",
        url=share_url,
        button_key="link:referral_share",
        default_color="green"
    )
    btn_back = make_ui_button(
        "🔙 Back to Main",
        callback_data="back_to_main",
        button_key="nav:back_main",
        default_color="blue"
    )

    markup.add(btn_send)
    markup.add(btn_back)
    render_or_edit(chat_id, message_id, ref_text, markup)

def _reset_reseller_api_token(user_id):
    """Rotate one reseller's API token and invalidate the previous token."""
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    token = 'rg_' + secrets.token_urlsafe(32).replace('-', '_').replace('=', '')
    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
    try:
        row = conn.execute(
            'SELECT user_id FROM reseller_api_credentials WHERE user_id=? AND enabled=1',
            (int(user_id),)
        ).fetchone()
        if row:
            conn.execute(
                'UPDATE reseller_api_credentials SET api_token=?, updated_at=?, enabled=1 WHERE user_id=?',
                (token, now, int(user_id))
            )
        else:
            conn.execute(
                'INSERT INTO reseller_api_credentials(user_id,api_token,created_at,updated_at,enabled) VALUES(?,?,?,?,1)',
                (int(user_id), token, now, now)
            )
        conn.commit()
        return token
    finally:
        conn.close()


def _reseller_account_is_active(user_id):
    user = get_user(user_id)
    try:
        return bool(user and len(user) > 11 and int(user[11] or 0) == 1)
    except Exception:
        return False


def _reseller_my_account_markup():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(make_ui_button(
        '🔑 API Generate', callback_data='reseller_api_generate',
        button_key='reseller:my_account:api_generate', default_color='green', force_style=True
    ))
    markup.add(make_ui_button(
        '🆔 Product ID & Variant ID', callback_data='reseller_api_catalog',
        button_key='reseller:my_account:catalog', default_color='blue', force_style=True
    ))
    markup.add(make_ui_button(
        '♻️ API Reset', callback_data='reseller_api_reset',
        button_key='reseller:my_account:api_reset', default_color='red', force_style=True
    ))
    markup.add(make_ui_button(
        '🔙 Back', callback_data='back_to_main',
        button_key='nav:back_main', default_color='blue', force_style=True
    ))
    return markup


def _reseller_api_credentials_screen_text(user_id, title='🔑 <b>API CONNECTION</b>'):
    token = _reseller_api_token(user_id)
    link = _reseller_api_public_link()
    return (
        f'{title}\n'
        '━━━━━━━━━━━━━━━━━━━━\n\n'
        f'🔑 <b>API Token:</b> <code>{html.escape(str(token or "Not generated"))}</code>\n'
        f'🌐 <b>Server Link:</b> <code>{html.escape(str(link or "Not configured"))}</code>\n\n'
        '<i>Use this Token + Server Link in your bot or website.</i>'
    )


def _reseller_api_catalog_screen_text(page=0):
    """Render a Telegram-safe Product/Variant catalog page.

    Telegram message text is limited in size. The previous implementation
    attempted to send the complete catalog in one message, so a large catalog
    could make the callback look like it had frozen. Pages are built below the
    safe limit while keeping every product and every variant visible.
    """
    catalog = _reseller_api_catalog()
    page = max(0, int(page or 0))
    max_text = 3600
    header = [
        '🆔 <b>PRODUCT ID & VARIANT ID</b>',
        '━━━━━━━━━━━━━━━━━━━━',
        ''
    ]
    if not catalog:
        return '\n'.join(header + ['<i>No products/variants are available yet.</i>']), 0, 1

    chunks = []
    current = list(header)
    for item in catalog:
        lines = [
            f'🎮 <b>{html.escape(str(item["name"]))}</b>',
            f'   ├─ Product ID: <code>{html.escape(str(item["product_id"]))}</code>'
        ]
        plans = item.get('plans') or []
        for idx, plan in enumerate(plans):
            branch = '└─' if idx == len(plans) - 1 else '├─'
            lines.append(
                f'   {branch} Variant ID: <code>{html.escape(str(plan["valid_id"]))}</code> · '
                f'{html.escape(str(plan["validity"]))}'
            )
        lines.append('')
        candidate = '\n'.join(current + lines)
        if len(candidate) > max_text and len(current) > len(header):
            chunks.append('\n'.join(current).rstrip())
            current = list(header) + lines
        else:
            current.extend(lines)
    if len(current) > len(header):
        chunks.append('\n'.join(current).rstrip())
    if not chunks:
        chunks = ['\n'.join(header).rstrip()]

    total = len(chunks)
    page = min(page, total - 1)
    text = chunks[page]
    if total > 1:
        text += f'\n\n📄 <b>Page {page + 1}/{total}</b>'
    return text, page, total


def _reseller_api_catalog_markup(page=0, total_pages=1):
    markup = types.InlineKeyboardMarkup(row_width=2)
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(types.InlineKeyboardButton('⬅️ Previous', callback_data=f'reseller_api_catalog_page_{page - 1}'))
        if page < total_pages - 1:
            nav.append(types.InlineKeyboardButton('Next ➡️', callback_data=f'reseller_api_catalog_page_{page + 1}'))
        if nav:
            markup.row(*nav)
    markup.add(make_ui_button(
        '🔙 Back to My Account', callback_data='reseller_my_account',
        button_key='nav:reseller_my_account_back', default_color='blue', force_style=True
    ))
    return markup

def show_reseller_my_account(chat_id, user_id, message_id=None):
    if not _reseller_account_is_active(user_id):
        text = '❌ <b>Reseller Access Required</b>\n\nThis section is available only to active resellers.'
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(make_ui_button('🔙 Back', callback_data='back_to_main', button_key='nav:back_main', default_color='blue', force_style=True))
    else:
        text = (
            '🤝 <b>RESELLER MY ACCOUNT</b>\n'
            '━━━━━━━━━━━━━━━━━━━━\n\n'
            'Manage your private API credentials and get Product/Variant IDs below.'
        )
        markup = _reseller_my_account_markup()
    render_or_edit(chat_id, message_id, text, markup)


def show_reseller_api_credentials(chat_id, user_id, message_id=None, reset=False):
    if not _reseller_account_is_active(user_id):
        show_reseller_my_account(chat_id, user_id, message_id)
        return
    if reset:
        token = _reset_reseller_api_token(user_id)
        title = '♻️ <b>API RESET SUCCESSFUL</b>'
        extra = '\n\n✅ Your old API Token is no longer valid. A new Token has been generated.'
    else:
        token = _create_or_rotate_reseller_api_token(user_id)
        title = '🔑 <b>API GENERATED / CONNECTION DETAILS</b>'
        extra = '\n\n✅ Your API Token is ready to use.'
    text = _reseller_api_credentials_screen_text(user_id, title) + extra
    markup = _reseller_my_account_markup()
    render_or_edit(chat_id, message_id, text, markup)


def show_reseller_api_catalog(chat_id, user_id, message_id=None, page=0):
    if not _reseller_account_is_active(user_id):
        show_reseller_my_account(chat_id, user_id, message_id)
        return
    text, current_page, total_pages = _reseller_api_catalog_screen_text(page)
    render_or_edit(
        chat_id, message_id, text,
        _reseller_api_catalog_markup(current_page, total_pages)
    )


def show_my_account(chat_id, user_id, first_name, message_id=None):
    user = get_user(user_id)
    if user:
        u_id = user[0]
        name = user[1] or first_name
        phone = user[2] or 'N/A'
        country = user[3] or 'IN'
        balance = user[4]
        ref_balance = user[5]
        orders = user[6]
        lifetime = user[7]
        deposited = user[8]
        joined = user[9] or 'N/A'
        is_reseller = user[11]
    else:
        u_id = user_id
        name = first_name
        phone = 'N/A'
        country = 'IN'
        balance = 0.0
        ref_balance = 0.0
        orders = 0
        lifetime = 0.0
        deposited = 0.0
        joined = datetime.datetime.now().strftime("%Y-%m-%d IST")
        is_reseller = 0

    reseller_status = "⭐ <b>Reseller</b> · <i>discounted prices unlocked</i>" if is_reseller else "👤 <b>Standard User</b>"
    default_profile_text = (
        f"👤 <b>MY PROFILE</b>\n"
        f"────────────────────────\n"
        f"├── 🆔 <b>ID:</b> {u_id}\n"
        f"├── 🔥 <b>Name:</b> <i>{name}</i>\n"
        f"├── 📱 <b>Phone:</b> <code>{phone}</code>\n"
        f"├── 🌐 <b>Country:</b> {country}\n"
        f"├── 💼 <b>Balance:</b> ₹{balance:.2f} INR\n"
        f"├── 🎁 <b>Ref Balance:</b> ₹{ref_balance:.2f} INR\n"
        f"├── 📦 <b>Orders:</b> {orders}\n"
        f"├── 💎 <b>Lifetime spent:</b> ₹{lifetime:.2f} INR\n"
        f"├── 📥 <b>Total deposited:</b> ₹{deposited:.2f} INR\n"
        f"└── 📅 <b>Joined:</b> <i>{joined}</i>\n\n"
        f"{reseller_status}"
    )
    profile_template = get_custom_text("my_profile", default_profile_text)
    live_username = _get_live_telegram_username(u_id)
    profile_text = _safe_format_custom_text(
        profile_template,
        user=name,
        name=name,
        first_name=name,
        username=live_username,
        telegram_username=live_username,
        user_id=u_id,
        telegram_id=u_id,
        phone=phone,
        number=phone,
        country=country,
        balance=f"{balance:.2f}",
        ref_balance=f"{ref_balance:.2f}",
        orders=orders,
        lifetime=f"{lifetime:.2f}",
        deposited=f"{deposited:.2f}",
        joined=joined,
    )
    profile_text = _inject_labeled_user_values(
        profile_text,
        {
            "name": html.escape(str(name), quote=False),
            "username": html.escape(str(live_username), quote=False),
            "username_at": html.escape(f"@{live_username}" if live_username else "", quote=False),
            "user_id": str(u_id),
            "phone": html.escape(str(phone), quote=False),
            "country": html.escape(str(country), quote=False),
            "balance": f"{balance:.2f}",
            "ref_balance": f"{ref_balance:.2f}",
            "orders": str(orders),
            "lifetime": f"{lifetime:.2f}",
            "deposited": f"{deposited:.2f}",
            "joined": joined,
        }
    )

    # Existing custom profile layouts often use ``ID:`` (not ``User ID:``).
    # Update only a standalone ID row so Product ID / Order ID are unaffected.
    profile_lines = []
    for profile_line in profile_text.splitlines():
        plain_profile_line = re.sub(r'<[^>]+>', '', profile_line).strip()
        normalized_profile_line = re.sub(r'^[\s├└│|→➜\-_*]+', '', plain_profile_line)
        if (
            re.search(r'(?i)(?:^|[^A-Za-z0-9])ID\s*:', normalized_profile_line)
            and not re.search(r'(?i)^(?:User|Telegram|Account|Order|Product|Device)\s+ID\s*:', normalized_profile_line)
        ):
            profile_line = re.sub(
                r'(\bID\s*:\s*)([^\n]*)',
                lambda m: m.group(1) + str(u_id),
                profile_line,
                count=1,
                flags=re.I,
            )
        profile_lines.append(profile_line)
    profile_text = '\n'.join(profile_lines)

    markup = types.InlineKeyboardMarkup(row_width=1)
    # Active resellers get their API controls directly inside the existing
    # My Account screen: no extra menu hop is required. The normal profile
    # information and Back button remain unchanged for every user.
    if is_reseller:
        markup.add(make_ui_button(
            '🔑 API Generate', callback_data='reseller_api_generate',
            button_key='reseller:my_account:api_generate', default_color='green', force_style=True
        ))
        markup.add(make_ui_button(
            '🆔 Product ID & Variant ID', callback_data='reseller_api_catalog',
            button_key='reseller:my_account:catalog', default_color='blue', force_style=True
        ))
        markup.add(make_ui_button(
            '♻️ API Reset', callback_data='reseller_api_reset',
            button_key='reseller:my_account:api_reset', default_color='red', force_style=True
        ))
    btn_back = make_ui_button("🔙 Back to Main", callback_data="back_to_main", button_key="nav:back_main", default_color="blue")
    markup.add(btn_back)
    render_or_edit(chat_id, message_id, profile_text, markup)


# ==================== ADDITIVE ADMIN CONTROLS ====================
def _reseller_discount_admin_markup():
    enabled=_reseller_discount_active(); amount=_reseller_discount_amount(); hours=get_setting('reseller_discount_duration_hours') or '24'
    m=types.InlineKeyboardMarkup(row_width=1)
    m.add(make_ui_button(('🟢 ON' if enabled else '🔴 OFF')+' Reseller Discount',callback_data='rd_toggle',button_key='admin:rd_toggle',default_color='blue',force_style=True))
    m.add(make_ui_button(f'💰 Set Activation Amount (₹{amount:.2f})',callback_data='rd_amount',button_key='admin:rd_amount',default_color='blue',force_style=True))
    m.add(make_ui_button(f'⏱️ Set Duration ({hours}h)',callback_data='rd_duration',button_key='admin:rd_duration',default_color='blue',force_style=True))
    m.add(make_ui_button('✏️ Change Button Text',callback_data='rd_text',button_key='admin:rd_text',default_color='blue',force_style=True))
    m.add(make_ui_button('✨ Button Premium Emoji',callback_data='rd_emoji',button_key='admin:rd_emoji',default_color='blue',force_style=True))
    m.add(make_ui_button('📝 Reseller Activation Text',callback_data='rd_payment_text',button_key='admin:rd_payment_text',default_color='blue',force_style=True))
    m.add(make_ui_button('🎨 Change Button Color',callback_data='rd_color',button_key='admin:rd_color',default_color='blue',force_style=True))
    _ensure_admin_back_button(m)
    return m

def _send_reseller_discount_admin(call):
    amount=_reseller_discount_amount()
    status='ON' if _reseller_discount_active() else 'OFF'
    duration=html.escape(str(get_setting("reseller_discount_duration_hours") or "24"))
    text=(
        f'👑 <b>RESELLER DISCOUNT / PAID ACCESS</b>\n\n'
        f'Status: <b>{status}</b>\n\n'
        f'Activation Amount: <b>₹{amount:.2f}</b>\n'
        f'Duration setting: <b>{duration} hours</b>\n\n'
        'When payment is verified, the user is automatically promoted to Reseller and appears in the Reseller List.'
    )
    _admin_ui_send(call,text,parse_mode='HTML',reply_markup=_reseller_discount_admin_markup())

def _send_coupon_admin(call):
    m=types.InlineKeyboardMarkup(row_width=1); m.add(types.InlineKeyboardButton('➕ Create Coupon',callback_data='coupon_admin_create')); m.add(types.InlineKeyboardButton('📋 Active Coupons',callback_data='coupon_admin_list')); _ensure_admin_back_button(m)
    _admin_ui_send(call,'🎟️ <b>COUPON MANAGEMENT</b>\\n\\nCreate a full-value coupon. Coupon + Wallet cannot be combined.',parse_mode='HTML',reply_markup=m)

def _resapi_admin_markup():
    m=types.InlineKeyboardMarkup(row_width=1); m.add(types.InlineKeyboardButton('🌐 Set Public API Server Link',callback_data='resapi_set_link')); m.add(types.InlineKeyboardButton('👤 Generate/Send Reseller API',callback_data='resapi_generate')); _ensure_admin_back_button(m); return m

def _send_resapi_admin(call):
    link=_reseller_api_public_link() or 'Not Set'
    _admin_ui_send(call,f'🤝 <b>RESELLER API SYSTEM</b>\\n\\n🌐 Public Server Link: <code>{html.escape(link)}</code>\\n\\nEach reseller receives an API Token + this Server Link + Product IDs + Validity IDs. Their bot can then call your bridge API using Bearer authentication.',parse_mode='HTML',reply_markup=_resapi_admin_markup())

def _botmake_step_days(message):
    uid=int(message.from_user.id)
    if not _is_bot_creator_root_admin(uid): return
    if not admin_temp_data.get(uid,{}).get('botmake_add_plan'): return
    days=(message.text or '').strip()
    if not re.fullmatch(r'\d+\s*(Days?|Months?|Years?)',days,re.I):
        msg=bot.send_message(message.chat.id,'❌ Invalid plan. Example: <code>3 Days</code>, <code>7 Days</code>, <code>1 Month</code>.',parse_mode='HTML')
        bot.register_next_step_handler(msg,_botmake_step_days); return
    admin_temp_data[uid]['botmake_days']=days
    msg=bot.send_message(message.chat.id,'💰 <b>Now send the price in INR:</b>',parse_mode='HTML')
    bot.register_next_step_handler(msg,_botmake_step_price)

def _botmake_step_price(message):
    uid=int(message.from_user.id); state=admin_temp_data.get(uid,{})
    if not _is_bot_creator_root_admin(uid) or not state.get('botmake_add_plan'): return
    try: price=float((message.text or '').strip().replace(',','')); assert price>0
    except Exception:
        msg=bot.send_message(message.chat.id,'❌ Invalid price. Send a positive number.')
        bot.register_next_step_handler(msg,_botmake_step_price); return
    try:
        _bot_make_insert_plan(state.get('botmake_days'),price)
        admin_temp_data.pop(uid,None)
        bot.send_message(message.chat.id,'✅ <b>Bot Make plan added successfully.</b>',parse_mode='HTML')
        fake=type('BotMakeRefreshCall',(),{'from_user':message.from_user,'message':message,'data':'admin_botmake_manager'})()
        _show_botmake_admin(fake)
    except Exception as exc:
        bot.send_message(message.chat.id,f'❌ <b>Could not add plan.</b>\n\n<code>{html.escape(str(exc)[:500])}</code>',parse_mode='HTML')

# ==================== CALLBACK QUERY HANDLERS ====================


def step_save_ninex_url_direct(message, admin_id=None):
    uid = int(admin_id or message.from_user.id)
    if not _is_admin(uid): return
    url = _ninex_base_url((message.text or '').strip())
    token = _ninex_api_token()
    if not token:
        m = bot.send_message(message.chat.id, '❌ Set the 9X API Token first.')
        bot.register_next_step_handler(m, step_save_ninex_token); return
    if not url:
        m = bot.send_message(message.chat.id, '❌ Invalid Server Link. Send a valid http:// or https:// URL.')
        bot.register_next_step_handler(m, lambda msg: step_save_ninex_url_direct(msg, uid)); return
    set_setting(NINEX_API_URL_KEY, url); set_setting('ninex_api_connected', '0')
    ok, detail, _ = _ninex_check_connection()
    bot.send_message(message.chat.id, f'9️⃣ <b>9X SERVER SAVED</b>\n\n🌐 <code>{html.escape(url)}</code>\n'
        f"{'🟢 Connected Successfully!' if ok else '🔴 Not Connect'}\nℹ️ {html.escape(str(detail))}", parse_mode='HTML', reply_markup=_ninex_api_markup())

def _botlist_extend_step(message):
    uid = message.from_user.id
    if not _is_bot_creator_root_admin(uid):
        return
    state = admin_temp_data.get(uid, {})
    iid = state.pop('botlist_extend_instance', None)
    if not iid:
        return
    try:
        new_expiry = _bot_extend_validity(iid, message.text)
        expiry_text = datetime.datetime.fromtimestamp(new_expiry).strftime('%Y-%m-%d %H:%M:%S')
        bot.send_message(message.chat.id, f'✅ <b>Validity updated successfully.</b>\\n\\n⏳ New expiry: <code>{expiry_text}</code>', parse_mode='HTML')
        # Re-open the selected bot management screen with the refreshed status.
        fake_call = type('BotListRefreshCall', (), {
            'from_user': message.from_user,
            'message': message,
            'data': f'botlist_select_{iid}',
        })()
        _show_bot_instance_manage(fake_call, iid)
    except Exception as exc:
        bot.send_message(message.chat.id, f'❌ <b>Validity update failed.</b>\\n\\n<code>{html.escape(str(exc)[:800])}</code>', parse_mode='HTML')


@bot.callback_query_handler(func=lambda call: True)
def handle_menu_click(call):
    _activity_log("Button/Callback", call.from_user, getattr(call, "data", ""))
    # Immediate callback acknowledgement keeps Telegram clients responsive even
    # when a later branch performs database/API work.
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    user_id = call.from_user.id
    first_name = call.from_user.first_name or "User"

    # Universal one-level Admin Back is handled before normal route bookkeeping.
    # This prevents a Back tap from overwriting the navigation context it is
    # supposed to restore.
    if call.data in {"admin_nav_back", "admin_back_main"}:
        if _is_admin(user_id):
            # Cancel only the pending text-input handler. Do NOT erase the
            # whole Admin temporary state before restoring a snapshot: dynamic
            # Product/Plan/User/API keyboards need their saved hash mappings.
            admin_pending_return.pop(int(user_id),None)
            try: bot.clear_step_handler_by_chat_id(call.message.chat.id)
            except Exception: pass

            # Deterministic Back routes for the dynamic Admin catalogs/lists.
            # Their keyboards are rebuilt from live database data, so stale
            # snapshots can otherwise reinsert the same screen and create a loop.
            current = admin_nav_current.get(int(user_id)) or {}
            current_id = str(current.get('screen_id') or '')
            if current_id in {'admin_hack_price_ui', 'admin_all_button_emoji', 'admin_button_colors'}:
                admin_nav_snapshots.pop(int(user_id), None)
                admin_nav_current.pop(int(user_id), None)
                root_markup = _admin_main_markup()
                try:
                    bot.edit_message_text(_admin_panel_text(), chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='HTML', reply_markup=root_markup)
                except Exception:
                    bot.send_message(call.message.chat.id, _admin_panel_text(), parse_mode='HTML', reply_markup=root_markup)
                _admin_store_snapshot(user_id, _admin_panel_text(), root_markup, 'admin_main', call.message.message_id, record_history=False)
                admin_nav_snapshots.pop(int(user_id), None)
                _fast_callback_ack(call)
                return

            if current_id.startswith('admin_track_users') or current_id.startswith('admin_reseller_list'):
                # A User/Reseller list is a child of the Users & Resellers hub.
                # Never restore the list itself from Back, which was the source
                # of the old list -> hub -> list loop.
                admin_nav_snapshots.pop(int(user_id), None)
                admin_nav_current.pop(int(user_id), None)
                parent_markup = _admin_category_markup('users')
                parent_text = _admin_category_text('users')
                try:
                    bot.edit_message_text(parent_text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='HTML', reply_markup=parent_markup)
                except Exception:
                    bot.send_message(call.message.chat.id, parent_text, parse_mode='HTML', reply_markup=parent_markup)
                _admin_store_snapshot(user_id, parent_text, parent_markup, 'admin_cat_users', call.message.message_id, record_history=False)
                admin_nav_snapshots.pop(int(user_id), None)
                _fast_callback_ack(call)
                return

            if current_id == 'admin_cat_users':
                # The Users & Resellers hub is a top-level Admin category. Its
                # Back button must always return to the real Main Admin Panel,
                # never to a previously visited User/Reseller list.
                admin_nav_snapshots.pop(int(user_id), None)
                admin_nav_current.pop(int(user_id), None)
                root_markup = _admin_main_markup()
                try:
                    bot.edit_message_text(_admin_panel_text(), chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='HTML', reply_markup=root_markup)
                except Exception:
                    bot.send_message(call.message.chat.id, _admin_panel_text(), parse_mode='HTML', reply_markup=root_markup)
                _admin_store_snapshot(user_id, _admin_panel_text(), root_markup, 'admin_main', call.message.message_id, record_history=False)
                admin_nav_snapshots.pop(int(user_id), None)
                _fast_callback_ack(call)
                return

            snap=_admin_pop_snapshot(user_id)
            if not _admin_restore_snapshot(call,snap):
                admin_temp_data.pop(user_id,None)
                root_markup=_admin_main_markup()
                try: bot.edit_message_text(_admin_panel_text(),chat_id=call.message.chat.id,message_id=call.message.message_id,parse_mode='HTML',reply_markup=root_markup)
                except Exception: bot.send_message(call.message.chat.id,_admin_panel_text(),parse_mode='HTML',reply_markup=root_markup)
                _admin_store_snapshot(user_id,_admin_panel_text(),root_markup,'admin_main'); admin_nav_snapshots.pop(int(user_id),None)
            _fast_callback_ack(call)
        return

    # Capture the exact page currently visible in Telegram before routing any
    # normal Admin callback. This covers legacy/direct-rendered Admin screens
    # that do not pass through _admin_ui_send(), so Back always returns to the
    # immediately previous visible page. Back itself is excluded above.
    if _is_admin(user_id):
        _admin_capture_live_parent(call)

    # A stale next-step handler from an older Admin text prompt must never be
    # allowed to interfere with a fresh button navigation. Telegram callback
    # taps are explicit navigation actions, so cancel any pending text-input
    # handler before routing the new Admin callback. Existing state/data is kept.
    if _is_admin(user_id):
        try:
            bot.clear_step_handler_by_chat_id(call.message.chat.id)
        except Exception:
            pass
        _remember_admin_navigation(user_id, getattr(call, "data", ""))

    # Only banned users or users affected by Maintenance mode are blocked here.
    # IMPORTANT: normal non-admin users must continue into the user-facing
    # callback branches below.  The previous global admin gate caused every
    # callback to silently stop for Telegram IDs that were not in ADMIN_IDS,
    # making the bot appear to work only for the configured admin account.
    # Individual Admin callbacks already perform their own _is_admin() check,
    # so removing this global gate does not expose the Admin Panel to users.
    if _child_bot_is_expired() and not _is_admin(user_id):
        _fast_callback_ack(call)
        _admin_ui_send(call, _expired_user_text(), parse_mode='HTML')
        return

    if not _is_admin(user_id):
        if is_user_banned(user_id):
            _fast_callback_ack(call)
            _admin_ui_send(call, "🚫 <b>Your access has been restricted.</b>", parse_mode="HTML")
            return
        if not is_bot_enabled():
            _fast_callback_ack(call)
            _admin_ui_send(call, "🔧 <b>Bot Under Maintenance</b>", parse_mode="HTML")
            return
    
    if call.data == "open_store":
        _fast_callback_ack(call)
        show_open_store(call.message.chat.id, message_id=call.message.message_id)

    elif call.data == "my_account":
        _fast_callback_ack(call)
        show_my_account(call.message.chat.id, user_id, first_name, message_id=call.message.message_id)

    elif call.data == "reseller_my_account":
        _fast_callback_ack(call)
        show_reseller_my_account(call.message.chat.id, user_id, message_id=call.message.message_id)

    elif call.data == "reseller_api_generate":
        _fast_callback_ack(call)
        show_reseller_api_credentials(call.message.chat.id, user_id, message_id=call.message.message_id, reset=False)

    elif call.data == "reseller_api_catalog":
        _fast_callback_ack(call)
        show_reseller_api_catalog(call.message.chat.id, user_id, message_id=call.message.message_id, page=0)

    elif call.data.startswith("reseller_api_catalog_page_"):
        _fast_callback_ack(call)
        try:
            page = int(call.data.rsplit("_", 1)[-1])
        except Exception:
            page = 0
        show_reseller_api_catalog(call.message.chat.id, user_id, message_id=call.message.message_id, page=page)

    elif call.data == "reseller_api_reset":
        _fast_callback_ack(call)
        show_reseller_api_credentials(call.message.chat.id, user_id, message_id=call.message.message_id, reset=True)

    elif call.data == "orders":
        _fast_callback_ack(call)
        show_orders_history(call.message.chat.id, user_id, message_id=call.message.message_id)

    elif call.data == "invite_earn":
        _fast_callback_ack(call)
        show_referral_program(call.message.chat.id, user_id, message_id=call.message.message_id)

    elif call.data == "how_to_use_bot":
        _fast_callback_ack(call)
        show_how_to_use_bot(call.message.chat.id, message_id=call.message.message_id)

    elif call.data == "help_desk":
        _fast_callback_ack(call)
        show_help_desk(call.message.chat.id, message_id=call.message.message_id)

    elif call.data == "top_up":
        _fast_callback_ack(call)
        show_topup_options(call.message.chat.id, message_id=call.message.message_id)

    elif call.data.startswith("topkey_d_"):
        _fast_callback_ack(call)
        try:
            digit = int(call.data.replace("topkey_d_", "", 1))
        except ValueError:
            return
        current = _get_topup_keypad_amount(call.message.chat.id)
        candidate = 0 if (current == 0 and digit == 0) else current * 10 + digit
        if candidate > 10000:
            bot.answer_callback_query(call.id, "❌ Maximum Add Balance is ₹10,000", show_alert=True)
            return
        # Save the exact number represented by the keypad before rendering.
        # The same user/chat state is then rendered immediately below.
        _set_topup_keypad_amount(call.message.chat.id, candidate)
        _update_topup_keypad_message(call.message.chat.id, call.message.message_id)

    elif call.data == "topkey_clear":
        _fast_callback_ack(call)
        # Cancel behaves as a digit-by-digit backspace. At zero it is a no-op.
        # It never replaces or rewrites the saved Add Balance Premium template.
        current = _get_topup_keypad_amount(call.message.chat.id)
        if current > 0:
            _set_topup_keypad_amount(call.message.chat.id, current // 10)
            _update_topup_keypad_message(call.message.chat.id, call.message.message_id)
        return

    elif call.data == "topkey_confirm":
        _fast_callback_ack(call)
        amount = _get_topup_keypad_amount(call.message.chat.id)
        if not 1 <= amount <= 10000:
            bot.answer_callback_query(call.id, "❌ Enter an amount from ₹1 to ₹10,000", show_alert=True)
            return

        # Confirm uses the exact live keypad amount. The existing QR and
        # background auto-verification flow remains unchanged.
        show_topup_upi_screen(
            call.message.chat.id,
            amount,
            message_id=call.message.message_id,
        )

    elif call.data == "topkey_back":
        _fast_callback_ack(call)
        _clear_topup_keypad_state(call.message.chat.id)
        show_shop_features(call.message.chat.id, first_name, message_id=call.message.message_id)

    elif call.data.startswith("topup_amt_"):
        amt = float(call.data.replace("topup_amt_", ""))
        show_topup_confirm(call.message.chat.id, amt, message_id=call.message.message_id)

    elif call.data == "topup_custom":
        msg = _admin_ui_send(call, "✏️ <b>Enter Custom Amount in INR (₹1 - ₹10,000):</b>", parse_mode="HTML")
        bot.register_next_step_handler(msg, step_get_custom_topup)

    elif call.data.startswith("pay_topup_upi_"):
        amt = float(call.data.replace("pay_topup_upi_", ""))
        show_topup_upi_screen(call.message.chat.id, amt, message_id=call.message.message_id)

    elif call.data == "out_of_stock_alert":
        bot.answer_callback_query(call.id, "❌ This plan is currently Out of Stock!", show_alert=True)

    elif call.data.startswith("prod_"):
        _fast_callback_ack(call)
        product_name = call.data.replace("prod_", "")
        show_product_plans(call.message.chat.id, product_name, message_id=call.message.message_id)

    elif call.data.startswith("checkout_"):
        # Fast path: acknowledge immediately, then prepare the payment-method
        # screen outside the Telegram callback worker.
        _fast_callback_ack(call)
        try:
            product_id = int(call.data.replace("checkout_", "", 1))
        except (TypeError, ValueError):
            try:
                bot.answer_callback_query(
                    call.id, "❌ Invalid product.", show_alert=True
                )
            except Exception:
                pass
            return

        product_row = get_product_by_id(product_id)
        if not product_row or _product_hidden(product_row[1]) or _plan_hidden(product_id):
            bot.answer_callback_query(call.id, '❌ This product/plan is currently hidden.', show_alert=True)
            return
        chat_id = call.message.chat.id
        message_id = call.message.message_id
        username = getattr(call.from_user, "username", None)
        state_key = (int(user_id), int(product_id))

        now = time.time()
        if now - checkout_prepare_state.get(state_key, 0.0) < 1.5:
            return
        checkout_prepare_state[state_key] = now

        def _prepare_checkout():
            try:
                product = get_product_by_id(product_id)
                if not product:
                    bot.send_message(chat_id, "❌ Product not found.")
                    return

                req_dev_id = product[11] if len(product) > 11 else 0
                if int(req_dev_id or 0) == 1:
                    admin_temp_data[user_id] = {"checkout_pid": product_id}
                    msg = bot.send_message(
                        chat_id,
                        "📱 <b>Please enter your Device ID to proceed with purchase:</b>",
                        parse_mode="HTML",
                    )
                    bot.register_next_step_handler(msg, step_get_device_id_input)
                    return

                show_order_summary(
                    chat_id,
                    product_id,
                    message_id=message_id,
                    username=username,
                )
            except Exception as exc:
                print(
                    f"[CHECKOUT PREP ERROR] user={user_id} "
                    f"product={product_id}: {exc}"
                )
                try:
                    show_order_summary(
                        chat_id,
                        product_id,
                        message_id=message_id,
                        username=username,
                    )
                except Exception as recovery_error:
                    print(
                        f"[CHECKOUT RECOVERY ERROR] user={user_id} "
                        f"product={product_id}: {recovery_error}"
                    )
                    try:
                        bot.send_message(
                            chat_id,
                            "❌ <b>Unable to open payment options.</b>\n\n"
                            "Please tap the Buy button again.",
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass
            finally:
                checkout_prepare_state.pop(state_key, None)

        _run_user_task_async(_prepare_checkout)

    elif call.data.startswith("pay_upi_"):
        # QR creation performs an external gateway request. Never block the
        # Telegram callback worker while waiting for FamPay/.
        _fast_callback_ack(call)
        raw_data = call.data.replace("pay_upi_", "", 1)
        product_id = 0
        device_id = None
        try:
            if ":" in raw_data:
                parts = raw_data.split(":", 1)
                product_id = int(parts[0])
                device_id = parts[1] if len(parts) > 1 and parts[1] else None
            else:
                parts = raw_data.split("_", 1)
                product_id = int(parts[0])
                device_id = parts[1] if len(parts) > 1 and parts[1] else None
        except (TypeError, ValueError):
            bot.answer_callback_query(call.id, "❌ Invalid payment request.", show_alert=True)
            return

        _run_user_task_async(
            show_upi_checkout,
            call.message.chat.id,
            product_id,
            message_id=call.message.message_id,
            device_id=device_id,
        )

    # IMPORTANT: admin coupon callbacks also start with "coupon_".
    # Keep them out of the user checkout branch so coupon_admin_create
    # reaches the admin amount-entry handler below.
    elif call.data.startswith("coupon_") and not call.data.startswith("coupon_admin_"):
        _fast_callback_ack(call)
        raw=call.data.replace('coupon_','',1); parts=raw.split(':',1); pid=int(parts[0]) if parts and parts[0].isdigit() else 0; dev=parts[1] if len(parts)>1 else None
        user_checkout_temp[int(user_id)]={'product_id':pid,'device_id':dev}
        msg=bot.send_message(call.message.chat.id,'🎟️ <b>Enter your Coupon Code:</b>\n\n<i>The coupon must cover the full purchase amount. Wallet + Coupon cannot be combined.</i>',parse_mode='HTML')
        bot.register_next_step_handler(msg, lambda m: _process_coupon_purchase(m.chat.id,int(user_id),int(user_checkout_temp.pop(int(user_id),{}).get('product_id') or pid),user_checkout_temp.get(int(user_id),{}).get('device_id') if False else dev,m.text))

    elif call.data == 'reseller_discount':
        _fast_callback_ack(call)
        if _reseller_discount_active(): _run_payment_task_async(_reseller_discount_start_payment,call.message.chat.id,call.message.message_id)
        else: bot.send_message(call.message.chat.id,'❌ Reseller Discount is currently unavailable.')

    # ROBUST WALLET PAYMENT CALLBACK
    elif call.data.startswith("pay_wallet_"):
        # Acknowledge immediately so a slow key/API request never makes the
        # Telegram Wallet button look like it did nothing. The actual reseller
        # key delivery is also moved off the callback worker for fast response
        # across all Telegram users.
        _fast_callback_ack(call)
        raw_data = call.data.replace("pay_wallet_", "", 1)
        product_id = 0
        device_id = None
        try:
            if ":" in raw_data:
                parts = raw_data.split(":", 1)
                product_id = int(parts[0])
                device_id = parts[1] if len(parts) > 1 and parts[1] else None
            else:
                parts = raw_data.split("_", 1)
                product_id = int(parts[0])
                device_id = parts[1] if len(parts) > 1 and parts[1] else None
        except (TypeError, ValueError):
            bot.answer_callback_query(call.id, "❌ Invalid wallet payment request.", show_alert=True)
            return

        # Do NOT delete the checkout message. Deleting it before the background
        # API/key work completes makes Telegram look frozen when that work takes
        # a moment. Keep the same message visible and let the worker edit it into
        # the final success/failure screen.
        wallet_state_key = (int(user_id), int(product_id))
        with wallet_processing_lock:
            if wallet_state_key in wallet_processing_state:
                try:
                    bot.answer_callback_query(
                        call.id,
                        "⏳ Wallet payment is already processing...",
                        show_alert=False,
                    )
                except Exception:
                    pass
                return
            wallet_processing_state.add(wallet_state_key)

        # Start the wallet checkout in the background without showing a
        # temporary status message. The existing checkout
        # screen stays visible until the worker replaces it with the final
        # success/failure result. This keeps the payment UI clean and avoids
        # showing an unnecessary intermediate status screen.
        processing_message_id = call.message.message_id

        def _wallet_worker():
            try:
                process_wallet_checkout(
                    call.message.chat.id,
                    user_id,
                    product_id,
                    device_id=device_id,
                    message_id=processing_message_id,
                )
            finally:
                with wallet_processing_lock:
                    wallet_processing_state.discard(wallet_state_key)

        _run_payment_task_async(_wallet_worker)

    elif call.data == "admin_gateway_manager":
        if _is_admin(user_id): _send_gateway_manager(call.message.chat.id, message_id=call.message.message_id)
    elif call.data == "gw_edit_fam":
        if _is_admin(user_id):
            _start_famp_setup(call.message.chat.id, user_id)
    elif call.data == "gw_edit_paytm":
        if _is_admin(user_id):
            _fast_callback_ack(call)
            _start_paytm_setup(call.message.chat.id, user_id)
    elif call.data == "gw_check_paytm":
        if _is_admin(user_id):
            _fast_callback_ack(call)
            chat_id = call.message.chat.id
            message_id = call.message.message_id
            def _paytm_connection_worker():
                ok, detail = _check_paytm_connection()
                try:
                    bot.send_message(
                        chat_id,
                        ("✅" if ok else "❌") +
                        f" <b>PayTM Connection {'Successful' if ok else 'Failed'}</b>\n\n<code>{html.escape(str(detail))}</code>",
                        parse_mode='HTML'
                    )
                    _send_gateway_manager(chat_id, message_id=message_id)
                except Exception as exc:
                    print(f'[PAYTM CONNECTION UI ERROR] {exc}')
            _run_user_task_async(_paytm_connection_worker)
    elif call.data == "gw_toggle_paytm":
        if _is_admin(user_id): _gateway_toggle(call.message.chat.id,"paytm")
    elif call.data == "gw_check_fam":
        if _is_admin(user_id):
            _fast_callback_ack(call)
            chat_id = call.message.chat.id
            message_id = call.message.message_id
            def _fam_connection_worker():
                ok, detail = _check_fam_connection()
                try:
                    bot.send_message(
                        chat_id,
                        ("✅" if ok else "❌") +
                        f" <b>FamPay Connection {'Successful' if ok else 'Failed'}</b>\n\n<code>{html.escape(str(detail))}</code>",
                        parse_mode="HTML"
                    )
                    _send_gateway_manager(chat_id, message_id=message_id)
                except Exception as exc:
                    print(f'[FAMP CONNECTION UI ERROR] {exc}')
            _run_user_task_async(_fam_connection_worker)
    elif call.data == "gw_toggle_fam":
        if _is_admin(user_id): _gateway_toggle(call.message.chat.id,"fam")
    elif call.data == "admin_manage_admins":
        if _is_admin(user_id): _send_admin_manager(call.message.chat.id, message_id=call.message.message_id)
    elif call.data == "admin_add_id":
        if _is_admin(user_id):
            m=_admin_ui_send(call,"👤 <b>Enter Telegram User ID to make Admin:</b>",parse_mode="HTML"); bot.register_next_step_handler(m,step_save_new_admin_id)
    elif call.data == "admin_remove_id":
        if _is_admin(user_id):
            m=_admin_ui_send(call,"👤 <b>Enter Telegram User ID to remove from Admins:</b>",parse_mode="HTML"); bot.register_next_step_handler(m,step_remove_admin_id)
    elif call.data.startswith("admin_backup_send_"):
        if _is_admin(user_id):
            _fast_callback_ack(call)
            h=call.data.replace('admin_backup_send_','',1)
            state_catalog = admin_temp_data.get(user_id,{}).get('backup_archive_catalog',{}) or {}
            path_str = state_catalog.get(h)
            path = Path(path_str).resolve() if path_str else None

            # Do not rely only on in-memory state; the backup list can remain on
            # Telegram after a restart. Resolve the selected archive from disk.
            if not path or not path.exists():
                try:
                    for candidate in BOT_AUTO_BACKUP_DIR.glob('auto_backup_*.zip'):
                        if candidate.is_file() and _ui_hash(candidate.name) == h:
                            path = candidate.resolve()
                            break
                except Exception:
                    path = None

            if (not path or not path.exists() or
                    path.parent != BOT_AUTO_BACKUP_DIR.resolve() or
                    path.suffix.lower() != '.zip'):
                bot.answer_callback_query(call.id,'❌ Backup file is no longer available.',show_alert=True)
                return

            # The old flow was a direct file-send. Restore the requested
            # intermediate "Download Backup" screen so tapping an archive
            # visibly opens an action and the final button delivers the ZIP.
            admin_temp_data.setdefault(user_id,{})['selected_backup_path'] = str(path)
            admin_temp_data[user_id]['selected_backup_hash'] = h
            size_mb = path.stat().st_size / (1024 * 1024)
            stamp = datetime.datetime.fromtimestamp(path.stat().st_mtime).strftime('%d %b %Y · %I:%M %p')
            m = types.InlineKeyboardMarkup(row_width=1)
            m.add(make_ui_button(
                '📥 Download Backup',
                callback_data=f'admin_backup_download_selected_{h}',
                button_key='admin:backup:download_selected',
                default_color='green', force_style=True
            ))
            m.add(make_ui_button(
                '🔙 Back to Backups',
                callback_data='admin_created_bots',
                button_key='admin:backup:back_list',
                default_color='red', force_style=True
            ))
            _admin_ui_send(
                call,
                '💾 <b>BACKUP SELECTED</b>\n━━━━━━━━━━━━━━━━━━━━\n\n'
                f'📦 <b>File:</b> <code>{html.escape(path.name)}</code>\n'
                f'🕒 <b>Created:</b> {stamp}\n'
                f'📏 <b>Size:</b> {size_mb:.1f} MB\n\n'
                'Tap <b>Download Backup</b> to receive this backup directly in Telegram.',
                parse_mode='HTML', reply_markup=m
            )

    elif call.data.startswith('admin_backup_download_selected_'):
        if _is_admin(user_id):
            _fast_callback_ack(call)
            h = call.data.replace('admin_backup_download_selected_', '', 1)
            path = None
            selected = admin_temp_data.get(user_id,{}).get('selected_backup_path')
            if selected:
                candidate = Path(selected).resolve()
                if candidate.exists() and candidate.parent == BOT_AUTO_BACKUP_DIR.resolve() and candidate.suffix.lower() == '.zip' and _ui_hash(candidate.name) == h:
                    path = candidate
            if path is None:
                try:
                    for candidate in BOT_AUTO_BACKUP_DIR.glob('auto_backup_*.zip'):
                        if candidate.is_file() and _ui_hash(candidate.name) == h:
                            path = candidate.resolve()
                            break
                except Exception:
                    path = None
            if not path or not path.exists():
                bot.answer_callback_query(call.id, '❌ Backup file is no longer available.', show_alert=True)
                return
            try:
                size = path.stat().st_size
                if size > BOT_AUTO_BACKUP_MAX_TELEGRAM_BYTES:
                    bot.answer_callback_query(call.id, '❌ Backup is too large to send via Telegram.', show_alert=True)
                    return
                with path.open('rb') as backup_file:
                    bot.send_document(
                        call.message.chat.id,
                        backup_file,
                        caption=(
                            '📥 <b>Backup Download</b>\n'
                            f'📦 <code>{html.escape(path.name)}</code>\n'
                            f'🕒 {_now_ist_text()} IST\n'
                            '✅ Backup sent successfully.'
                        ),
                        parse_mode='HTML'
                    )
                bot.answer_callback_query(call.id, '✅ Backup sent to Telegram.')
            except Exception as exc:
                bot.answer_callback_query(call.id, '❌ Backup download failed.', show_alert=True)
                print(f'[ADMIN SELECTED BACKUP DOWNLOAD ERROR] {exc}')

    elif call.data == 'admin_backup_create_now':
        if _is_admin(user_id):
            try:
                _create_auto_backup(); _show_created_bots_backup_list(call)
            except Exception as exc:
                _admin_ui_send(call,f'❌ <b>Backup creation failed.</b>\n\n<code>{html.escape(str(exc)[:1000])}</code>',parse_mode='HTML')
            return

    elif call.data == "admin_created_bots":
        _fast_callback_ack(call)
        if _is_admin(user_id):
            _show_created_bots_backup_list(call)

    elif call.data == 'admin_bot_list':
        _fast_callback_ack(call)
        if _is_bot_creator_root_admin(user_id):
            _show_master_bot_list(call)

    elif call.data.startswith('botlist_select_'):
        _fast_callback_ack(call)
        if _is_bot_creator_root_admin(user_id):
            _show_bot_instance_manage(call, call.data.replace('botlist_select_', '', 1))

    elif call.data.startswith('botlist_addme_'):
        _fast_callback_ack(call)
        if _is_bot_creator_root_admin(user_id):
            iid = call.data.replace('botlist_addme_', '', 1)
            try:
                _bot_add_admin_and_restart(iid, user_id)
                _admin_ui_send(call, '✅ <b>You are now an Admin of this bot.</b>', parse_mode='HTML')
                _show_bot_instance_manage(call, iid)
            except Exception as exc:
                _admin_ui_send(call, f'❌ <b>Admin update failed.</b>\n\n<code>{html.escape(str(exc)[:800])}</code>', parse_mode='HTML')

    elif call.data.startswith('botlist_pause_'):
        _fast_callback_ack(call)
        if _is_bot_creator_root_admin(user_id):
            iid = call.data.replace('botlist_pause_', '', 1)
            try:
                _bot_set_status(iid, 'paused')
                _show_bot_instance_manage(call, iid)
            except Exception as exc:
                _admin_ui_send(call, f'❌ <b>Pause failed.</b>\n\n<code>{html.escape(str(exc)[:800])}</code>', parse_mode='HTML')

    elif call.data.startswith('botlist_maint_'):
        _fast_callback_ack(call)
        if _is_bot_creator_root_admin(user_id):
            iid = call.data.replace('botlist_maint_', '', 1)
            try:
                _bot_set_status(iid, 'maintenance')
                _show_bot_instance_manage(call, iid)
            except Exception as exc:
                _admin_ui_send(call, f'❌ <b>Maintenance update failed.</b>\n\n<code>{html.escape(str(exc)[:800])}</code>', parse_mode='HTML')

    elif call.data.startswith('botlist_resume_'):
        _fast_callback_ack(call)
        if _is_bot_creator_root_admin(user_id):
            iid = call.data.replace('botlist_resume_', '', 1)
            try:
                _bot_set_status(iid, 'running')
                _show_bot_instance_manage(call, iid)
            except Exception as exc:
                _admin_ui_send(call, f'❌ <b>Start failed.</b>\n\n<code>{html.escape(str(exc)[:800])}</code>', parse_mode='HTML')

    elif call.data.startswith('botlist_extend_'):
        _fast_callback_ack(call)
        if _is_bot_creator_root_admin(user_id):
            iid = call.data.replace('botlist_extend_', '', 1)
            admin_temp_data.setdefault(user_id, {})['botlist_extend_instance'] = iid
            msg = _admin_ui_send(call, '⏳ <b>Set or extend bot validity:</b>\n\nPlain duration = NEW validity from now: <code>1m</code>, <code>5m</code>, <code>1h</code>, <code>7d</code>\nAdd <code>+</code> to EXTEND the current expiry: <code>+1d</code>, <code>+5m</code>, <code>+7d</code>', parse_mode='HTML')
            bot.register_next_step_handler(msg, _botlist_extend_step)

    elif call.data.startswith('botlist_resapi_toggle_'):
        _fast_callback_ack(call)
        if _is_bot_creator_root_admin(user_id):
            iid = call.data.replace('botlist_resapi_toggle_', '', 1).strip()
            try:
                row = _bot_instance_row(iid)
                if not row:
                    raise ValueError('Created bot instance was not found.')
                current = _child_button_disabled(row[5], RESSELLER_API_ADMIN_BUTTON_KEY)
                _set_child_button_disabled(iid, RESSELLER_API_ADMIN_BUTTON_KEY, not current)
                _show_bot_instance_manage(call, iid)
            except Exception as exc:
                _admin_ui_send(call, f'❌ <b>Reseller API visibility update failed.</b>\n\n<code>{html.escape(str(exc)[:800])}</code>', parse_mode='HTML')

    elif call.data.startswith('botlist_buttons_'):
        _fast_callback_ack(call)
        if _is_bot_creator_root_admin(user_id):
            iid = call.data.replace('botlist_buttons_', '', 1)
            _show_bot_admin_button_control(call, iid)

    elif call.data.startswith('botbtn_toggle_'):
        _fast_callback_ack(call)
        if _is_bot_creator_root_admin(user_id):
            parts = call.data.split('_', 3)
            if len(parts) == 4:
                iid, h = parts[2], parts[3]
                item = admin_temp_data.get(user_id, {}).get('bot_button_catalog', {}).get(h)
                if item:
                    try:
                        row = _bot_instance_row(iid)
                        current = _child_button_disabled(row[5], item['key'])
                        _set_child_button_disabled(iid, item['key'], not current)
                        _show_bot_admin_button_control(call, iid)
                    except Exception as exc:
                        _admin_ui_send(call, f'❌ <b>Button update failed.</b>\n\n<code>{html.escape(str(exc)[:800])}</code>', parse_mode='HTML')
                else:
                    _show_bot_admin_button_control(call, iid)

    elif call.data.startswith('botlist_delete_'):
        _fast_callback_ack(call)
        if _is_bot_creator_root_admin(user_id):
            iid = call.data.replace('botlist_delete_', '', 1)
            try:
                _bot_delete_instance(iid)
                _admin_ui_send(call, '✅ <b>Bot deleted successfully.</b>', parse_mode='HTML', reply_markup=_master_bot_list_markup())
            except Exception as exc:
                _admin_ui_send(call, f'❌ <b>Delete failed.</b>\n\n<code>{html.escape(str(exc)[:800])}</code>', parse_mode='HTML', reply_markup=_master_bot_list_markup())

    elif call.data.startswith('botbackup_select_'):
        _fast_callback_ack(call)
        if _is_bot_creator_root_admin(user_id):
            instance_id = call.data.replace('botbackup_select_', '', 1).strip()
            _show_bot_backup_target(call, instance_id)

    elif call.data == 'admin_botmake_manager':
        _fast_callback_ack(call)
        if _is_bot_creator_root_admin(user_id): _show_botmake_admin(call)

    elif call.data == 'botmake_toggle':
        _fast_callback_ack(call)
        if _is_bot_creator_root_admin(user_id):
            set_setting(BOT_MAKE_ENABLED_KEY, '0' if _bot_make_enabled() else '1')
            _show_botmake_admin(call)

    elif call.data == 'botmake_add_plan':
        _fast_callback_ack(call)
        if _is_bot_creator_root_admin(user_id):
            admin_temp_data.setdefault(user_id,{})['botmake_add_plan'] = True
            msg=_admin_ui_send(call,'➕ <b>Add Bot Make Plan</b>\n\nSend plan duration, for example: <code>3 Days</code> or <code>7 Days</code>.',parse_mode='HTML',reply_markup=types.InlineKeyboardMarkup())
            bot.register_next_step_handler(msg,_botmake_step_days)

    elif call.data.startswith('botmake_del_'):
        _fast_callback_ack(call)
        if _is_bot_creator_root_admin(user_id):
            try: _bot_make_delete_plan(int(call.data.replace('botmake_del_','',1)))
            except Exception: pass
            _show_botmake_admin(call)

    elif call.data == "admin_bot_creator":
        _fast_callback_ack(call)
        _bot_creator_open(call)

    elif call.data.startswith('botcreate_duration_'):
        _fast_callback_ack(call)
        if _is_bot_creator_root_admin(user_id):
            key=call.data.replace('botcreate_duration_','',1)
            if key not in _bot_creator_duration_options():
                _admin_ui_send(call,'❌ Invalid subscription duration.',parse_mode='HTML'); return
            label,_days=_bot_creator_duration_options()[key]
            _bot_creator_temp[user_id]={'duration_key':key}
            msg=_admin_ui_send(call,f'🤖 <b>CREATE NEW BOT — {html.escape(label)}</b>\n\nSend the name for the new bot:',parse_mode='HTML')
            bot.register_next_step_handler(msg,_bot_creator_step_name)

    elif call.data == "admin_main":
        if _is_admin(user_id):
            _admin_navigation_barrier(user_id)
            _admin_ui_send(call,
                
                _admin_panel_text(),
                parse_mode="HTML",
                reply_markup=_admin_main_markup()
            )

    elif call.data == "admin_system_back":
        if _is_admin(user_id):
            snap=_admin_pop_snapshot(user_id)
            if not _admin_restore_snapshot(call,snap):
                _admin_ui_send(call,_admin_panel_text(),parse_mode="HTML",reply_markup=_admin_main_markup())
            bot.answer_callback_query(call.id)

    elif call.data.startswith("admin_cat_"):
        if _is_admin(user_id):
            category=call.data.replace("admin_cat_",'',1)
            if category == "system":
                # Bot & Database opens in-place: the previous Admin Panel is
                # replaced instead of creating another message underneath it.
                try:
                    bot.edit_message_text(
                        "⚙️ <b>BOT & DATABASE SETTINGS</b>\n\nSelect an operation:",
                        chat_id=call.message.chat.id,
                        message_id=call.message.message_id,
                        parse_mode="HTML",
                        reply_markup=_admin_category_markup(category)
                    )
                except Exception:
                    bot.send_message(
                        call.message.chat.id,
                        "⚙️ <b>BOT & DATABASE SETTINGS</b>\n\nSelect an operation:",
                        parse_mode="HTML",
                        reply_markup=_admin_category_markup(category)
                    )
                bot.answer_callback_query(call.id)
            else:
                _admin_ui_send(
                call,
                _admin_category_text(category),
                parse_mode="HTML",
                reply_markup=_admin_category_markup(category)
            )

    elif call.data == "admin_api_system":
        if _is_admin(user_id):
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                _admin_colorful_button("🆕 New Server API System", callback_data="new_server_api", color="green"),
                _admin_colorful_button("🌐 Add & Connect Server API", callback_data="admin_server_api_mgmt", color="blue"),
            )
            markup.add(
                _admin_colorful_button("⚙️ Hack API & Server Manager", callback_data="admin_hack_server_manager", color="blue"),
                _admin_colorful_button("🔗 Map Server Hack ID & Duration", callback_data="admin_map_server_id", color="green"),
            )
            markup.add(_admin_colorful_button("🔙 Main Admin Panel", callback_data="admin_back_main", color="red"))
            _admin_ui_send(
                call,
                f"🌐 <b>API & SERVER SYSTEMS</b>\n\nNew Server: <b>{_new_server_status_text()}</b>",
                parse_mode="HTML",
                reply_markup=_ensure_admin_back_button(markup)
            )

    elif call.data == "api_srv_add":
        if _is_admin(user_id):
            admin_temp_data[user_id] = {}
            m = _admin_ui_send(call, "🔑 <b>Enter New API Server API Key:</b>", parse_mode="HTML")
            bot.register_next_step_handler(m, step_save_api_server_key)

    elif call.data.startswith("api_srv_") and call.data[8:].isdigit():
        if _is_admin(user_id):
            sid = int(call.data[8:])
            row = _api_server_row(sid)
            if not row:
                bot.answer_callback_query(call.id, "Server not found.", show_alert=True)
                return
            _, name, api_key, url, enabled, created_at, last_connected_at, account_name, account_username, account_user_id = row
            status = "🟢 CONNECTED" if enabled else "🔴 NOT CONNECTED"
            connected_line = f"🕒 <b>Connected:</b> {html.escape(str(last_connected_at))}\n" if last_connected_at else ""
            identity_parts = []
            if account_name:
                identity_parts.append(f"👤 {html.escape(str(account_name))}")
            if account_username:
                identity_parts.append(f"@{html.escape(str(account_username).lstrip('@'))}")
            if account_user_id:
                identity_parts.append(f"ID {html.escape(str(account_user_id))}")
            identity_line = f"👤 <b>Reseller:</b> {' · '.join(identity_parts)}\n" if identity_parts else ""
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                _admin_colorful_button("⚙️ Configure Hacks", callback_data=f"api_hacks_{sid}", color="blue"),
                _admin_colorful_button("🔍 Check Connection", callback_data=f"api_check_{sid}", color="green"),
            )
            markup.add(
                _admin_colorful_button("✏️ Edit Server", callback_data=f"api_edit_{sid}", color="blue"),
                _admin_colorful_button("🗑️ Delete Server", callback_data=f"api_delete_{sid}", color="red"),
            )
            markup.add(_admin_colorful_button("🔙 API Servers", callback_data="new_server_api", color="red"))
            _admin_ui_send(call,
                
                f"🆕 <b>{html.escape(name)}</b>\n\n"
                f"🔗 <b>Server:</b> <code>{html.escape(url)}</code>\n"
                f"📡 <b>Status:</b> {status}\n"
                f"{identity_line}"
                f"{connected_line}"
                f"🔐 <b>API Key:</b> <code>{html.escape(str(api_key)[:8])}••••••</code>\n\n"
                "Use Configure Hacks to assign Product IDs and plan Valid IDs.",
                parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup)
            )

    elif call.data.startswith("api_edit_") and call.data[9:].isdigit():
        if _is_admin(user_id):
            sid = int(call.data[9:])
            row = _api_server_row(sid)
            if not row:
                bot.answer_callback_query(call.id, "Server not found.", show_alert=True)
                return
            _admin_ui_send(
                call,
                f"✏️ <b>EDIT API SERVER</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🆕 <b>Name:</b> {html.escape(str(row[1]))}\n"
                f"🌐 <b>URL:</b> <code>{html.escape(str(row[3]))}</code>\n\n"
                "Choose what you want to change.",
                parse_mode="HTML",
                reply_markup=_api_server_edit_markup(sid)
            )

    elif call.data.startswith("api_edit_name_"):
        if _is_admin(user_id):
            sid = int(call.data.replace("api_edit_name_", "", 1))
            if not _api_server_row(sid):
                bot.answer_callback_query(call.id, "Server not found.", show_alert=True); return
            admin_temp_data[user_id] = {"api_edit_server_id": sid}
            m = _admin_ui_send(call, "✏️ <b>Enter the new API Server name:</b>", parse_mode="HTML")
            bot.register_next_step_handler(m, step_edit_api_server_name)

    elif call.data.startswith("api_edit_key_"):
        if _is_admin(user_id):
            sid = int(call.data.replace("api_edit_key_", "", 1))
            if not _api_server_row(sid):
                bot.answer_callback_query(call.id, "Server not found.", show_alert=True); return
            admin_temp_data[user_id] = {"api_edit_server_id": sid}
            m = _admin_ui_send(call, "🔑 <b>Enter the new API Server API Key:</b>", parse_mode="HTML")
            bot.register_next_step_handler(m, step_edit_api_server_key)

    elif call.data.startswith("api_edit_url_"):
        if _is_admin(user_id):
            sid = int(call.data.replace("api_edit_url_", "", 1))
            if not _api_server_row(sid):
                bot.answer_callback_query(call.id, "Server not found.", show_alert=True); return
            admin_temp_data[user_id] = {"api_edit_server_id": sid}
            m = _admin_ui_send(call, "🌐 <b>Enter the new API Server URL:</b>\n\nExample: <code>https://example.com</code>", parse_mode="HTML")
            bot.register_next_step_handler(m, step_edit_api_server_url)

    elif call.data.startswith("api_toggle_"):
        if _is_admin(user_id):
            sid = int(call.data.replace("api_toggle_", "", 1))
            row = _api_server_row(sid)
            if not row:
                bot.answer_callback_query(call.id, "Server not found.", show_alert=True); return
            new_state = not bool(row[4])
            _api_server_set_enabled(sid, new_state)
            bot.answer_callback_query(call.id, "Enabled" if new_state else "Disabled")
            row = _api_server_row(sid)
            m = _api_server_edit_markup(sid)
            _admin_ui_send(
                call,
                f"⚙️ <b>{html.escape(str(row[1]))}</b>\n\n"
                f"📡 <b>Status:</b> {'🟢 Enabled' if new_state else '🔴 Disabled'}\n"
                f"🌐 <code>{html.escape(str(row[3]))}</code>",
                parse_mode="HTML", reply_markup=m
            )

    elif call.data.startswith("api_delete_") and not call.data.startswith("api_delete_confirm_"):
        if _is_admin(user_id):
            sid = int(call.data.replace("api_delete_", "", 1))
            row = _api_server_row(sid)
            if not row:
                bot.answer_callback_query(call.id, "Server not found.", show_alert=True); return
            m = types.InlineKeyboardMarkup(row_width=2)
            m.row(
                _admin_colorful_button("⚠️ Yes, Delete", callback_data=f"api_delete_confirm_{sid}", color="red"),
                _admin_colorful_button("❌ Cancel", callback_data=f"api_srv_{sid}", color="blue")
            )
            _admin_ui_send(
                call,
                f"⚠️ <b>DELETE API SERVER?</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🆕 <b>{html.escape(str(row[1]))}</b>\n"
                f"🌐 <code>{html.escape(str(row[3]))}</code>\n\n"
                "Only this API server and its mappings will be deleted. "
                "Your local products and plans will remain safe.",
                parse_mode="HTML", reply_markup=_ensure_admin_back_button(m)
            )

    elif call.data.startswith("api_delete_confirm_"):
        if _is_admin(user_id):
            sid = int(call.data.replace("api_delete_confirm_", "", 1))
            if _api_server_delete(sid):
                bot.answer_callback_query(call.id, "API server deleted.")
                _admin_navigation_barrier(user_id, {"admin_api_system"})
                _show_api_server_list(call.message.chat.id, message_id=call.message.message_id)
            else:
                bot.answer_callback_query(call.id, "Server not found.", show_alert=True)

    elif call.data.startswith("api_check_"):
        if _is_admin(user_id):
            try:
                sid = int(call.data.replace("api_check_", "", 1))
            except ValueError:
                return
            ok, detail = _api_server_test_connection(sid)
            bot.answer_callback_query(call.id, "Connected Successfully!" if ok else "Not Connect", show_alert=True)
            row = _api_server_row(sid)
            if row:
                status = "🟢 <b>Connected Successfully!</b>" if ok else "🔴 <b>Not Connect</b>"
                identity_parts = []
                if len(row) > 7 and row[7]:
                    identity_parts.append(html.escape(str(row[7])))
                if len(row) > 8 and row[8]:
                    identity_parts.append('@' + html.escape(str(row[8]).lstrip('@')))
                if len(row) > 9 and row[9]:
                    identity_parts.append('ID ' + html.escape(str(row[9])))
                identity_line = f"👤 <b>Reseller:</b> {' · '.join(identity_parts)}\n" if identity_parts else ""
                connected_line = f"🕒 <b>Connected:</b> {html.escape(str(row[6]))}\n" if len(row) > 6 and row[6] else ""
                _admin_ui_send(call,
                    
                    f"{status}\n\n🌐 <b>{html.escape(row[1])}</b>\n"
                    f"🔗 <code>{html.escape(row[3])}</code>\n"
                    f"{identity_line}{connected_line}",
                    parse_mode="HTML"
                )

    elif call.data.startswith("api_hacks_"):
        if _is_admin(user_id):
            try:
                sid = int(call.data.replace("api_hacks_", "", 1))
            except ValueError:
                return
            row = _api_server_row(sid)
            if not row:
                bot.answer_callback_query(call.id, "Server not found.", show_alert=True)
                return
            _admin_ui_send(call,
                
                f"🎮 <b>HACK LIST — {html.escape(row[1])}</b>\n\n"
                "Select a hack. Then set its Product ID and each plan's Valid ID.",
                parse_mode="HTML", reply_markup=_api_server_hacks_markup(sid)
            )

    elif call.data.startswith("api_hack_"):
        if _is_admin(user_id):
            parts = call.data.split("_", 3)
            if len(parts) != 4:
                return
            try:
                sid = int(parts[2])
            except ValueError:
                return
            product_name = _api_server_hack_by_hash(parts[3])
            if not product_name:
                return
            row = _api_server_row(sid)
            if not row:
                return
            pid = _api_server_product_id(sid, product_name)
            _admin_ui_send(call,
                
                f"🎮 <b>{html.escape(product_name)}</b>\n\n"
                f"🆕 <b>Server:</b> {html.escape(row[1])}\n"
                f"🆔 <b>Product ID:</b> <code>{html.escape(pid or 'Not Set')}</code>\n\n"
                "Select a plan to enter its Valid ID.",
                parse_mode="HTML", reply_markup=_api_server_plans_markup(sid, product_name)
            )

    elif call.data.startswith("api_pid_"):
        if _is_admin(user_id):
            parts = call.data.split("_", 3)
            if len(parts) != 4:
                return
            try:
                sid = int(parts[2])
            except ValueError:
                return
            product_name = _api_server_hack_by_hash(parts[3])
            if not product_name:
                return
            admin_temp_data[user_id] = {"api_server_id": sid, "api_server_product": product_name}
            m = _admin_ui_send(call,
                
                f"🆔 <b>Enter Product ID for {html.escape(product_name)}:</b>",
                parse_mode="HTML"
            )
            bot.register_next_step_handler(m, step_save_multi_api_product_id)

    elif call.data.startswith("api_plan_"):
        if _is_admin(user_id):
            parts = call.data.split("_", 4)
            if len(parts) != 5:
                return
            try:
                sid = int(parts[2])
                plan_id = int(parts[4])
            except ValueError:
                return
            product_name = _api_server_hack_by_hash(parts[3])
            if not product_name:
                return
            plans = {int(x[0]): x for x in get_product_plans(product_name)}
            plan = plans.get(plan_id)
            if not plan:
                return
            admin_temp_data[user_id] = {
                "api_server_id": sid,
                "api_server_product": product_name,
                "api_server_plan_id": plan_id,
                "api_server_plan_days": str(plan[2])
            }
            m = _admin_ui_send(call,
                
                f"🆔 <b>Enter Valid ID for {html.escape(str(plan[2]))}:</b>",
                parse_mode="HTML"
            )
            bot.register_next_step_handler(m, step_save_multi_api_valid_id)

    elif call.data == 'admin_product_hide':
        if _is_admin(user_id):
            _product_hide_screen(call)

    elif call.data.startswith('ph_product_'):
        if _is_admin(user_id):
            product_name = _product_hide_by_hash(call.data.replace('ph_product_', '', 1))
            if not product_name:
                bot.answer_callback_query(call.id, 'Product not found.', show_alert=True)
                return
            plans = get_product_plans(product_name)
            hidden_plans = sum(1 for p in plans if _plan_hidden(p[0]))
            _admin_ui_send(call,
                f"📦 <b>{html.escape(product_name)}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Product: {'🔴 HIDDEN' if _product_hidden(product_name) else '🟢 VISIBLE'}\n"
                f"Plans: {len(plans)} · Hidden plans: {hidden_plans}\n\n"
                'Choose the product switch or an individual plan below.',
                parse_mode='HTML', reply_markup=_product_visibility_markup(product_name))

    elif call.data.startswith('ph_toggle_'):
        if _is_admin(user_id):
            product_name = _product_hide_by_hash(call.data.replace('ph_toggle_', '', 1))
            if not product_name:
                return
            new_state = not _product_hidden(product_name)
            _set_product_hidden(product_name, new_state)
            bot.answer_callback_query(call.id, 'Product hidden' if new_state else 'Product unhidden')
            _admin_ui_send(call,
                f"📦 <b>{html.escape(product_name)}</b>\n\nProduct is now {'🔴 HIDDEN' if new_state else '🟢 VISIBLE'}.",
                parse_mode='HTML', reply_markup=_product_visibility_markup(product_name))

    elif call.data.startswith('ph_plan_'):
        if _is_admin(user_id):
            try:
                plan_id = int(call.data.replace('ph_plan_', '', 1))
            except Exception:
                return
            plan = get_product_by_id(plan_id)
            if not plan:
                bot.answer_callback_query(call.id, 'Plan not found.', show_alert=True)
                return
            new_state = not _plan_hidden(plan_id)
            _set_plan_hidden(plan_id, new_state)
            bot.answer_callback_query(call.id, 'Plan hidden' if new_state else 'Plan unhidden')
            fake = type('ProductHidePlanCall', (), {
                'from_user': call.from_user,
                'message': call.message,
                'data': f"ph_product_{_ui_hash(plan[1])}"
            })()
            _admin_ui_send(fake,
                f"📦 <b>{html.escape(str(plan[1]))}</b>\n\nPlan <b>{html.escape(str(plan[3]))}</b> is now {'🔴 HIDDEN' if new_state else '🟢 VISIBLE'}.",
                parse_mode='HTML', reply_markup=_product_visibility_markup(str(plan[1])))

    elif call.data == 'rg_api_system':
        if _is_admin(user_id):
            _send_rg_panel(call)

    elif call.data == 'rgapi_set_token':
        if _is_admin(user_id):
            m = _admin_ui_send(call, '🔑 <b>Enter RG API Token:</b>', parse_mode='HTML')
            bot.register_next_step_handler(m, step_save_rg_token)

    elif call.data == 'rgapi_set_url':
        if _is_admin(user_id):
            m = _admin_ui_send(call, '🌐 <b>Enter RG API Server Link:</b>\n\nExample: <code>https://your-app.up.railway.app</code>', parse_mode='HTML')
            bot.register_next_step_handler(m, step_save_rg_url)

    elif call.data == 'rgapi_check':
        if _is_admin(user_id):
            ok, detail, _ = _rg_check_connection()
            bot.answer_callback_query(call.id, '✅ Connection Successful' if ok else '❌ Not Connected', show_alert=True)
            _send_rg_panel(call)

    elif call.data == 'rgapi_match':
        if _is_admin(user_id):
            ok, err, rep = _rg_auto_match()
            bot.answer_callback_query(call.id, 'Auto match finished' if ok else 'Auto match failed')
            m = types.InlineKeyboardMarkup(row_width=1)
            if ok and rep.get('matched'):
                m.add(_admin_colorful_button('🟢 Connect All Matched Hacks', callback_data='rgapi_enable_matched', color='green'))
            m.add(_admin_colorful_button('🎮 Connect Hacks', callback_data='rgapi_products', color='blue'))
            m.add(_admin_colorful_button('🔙 RG API System', callback_data='rg_api_system', color='red'))
            _admin_ui_send(call, _rg_match_report_text(ok, err, rep), parse_mode='HTML',
                           reply_markup=_style_admin_markup(_ensure_admin_back_button(m)))

    elif call.data == 'rgapi_enable_matched':
        if _is_admin(user_id):
            if not _rg_connected():
                bot.answer_callback_query(call.id, 'Run Check Connection first.', show_alert=True)
                return
            count = 0
            for name, entry in list(_rg_map().items()):
                if isinstance(entry, dict) and entry.get('product_id') and entry.get('plans'):
                    _rg_update_entry(name, enabled=True)
                    count += 1
            bot.answer_callback_query(call.id, f'{count} hack(s) connected to RG API', show_alert=True)
            _admin_ui_send(call, '🎮 <b>RG API — CONNECT HACKS</b>\n━━━━━━━━━━━━━━━━━━━━\n\n🟢 connected · 🟡 mapped only · ⚪ not set',
                           parse_mode='HTML', reply_markup=_rg_products_markup())

    elif call.data == 'rgapi_products':
        if _is_admin(user_id):
            _admin_ui_send(call,
                '🎮 <b>RG API — CONNECT HACKS</b>\n━━━━━━━━━━━━━━━━━━━━\n\n'
                '🟢 connected · 🟡 mapped only · ⚪ not set\n'
                'Tap a hack to match its Product ID and Variant IDs.',
                parse_mode='HTML', reply_markup=_rg_products_markup())

    elif call.data == 'rgapi_catalog':
        if _is_admin(user_id):
            ok, catalog = _rg_fetch_catalog()
            if not ok:
                bot.answer_callback_query(call.id, 'Could not load catalog', show_alert=True)
                _admin_ui_send(call, f'❌ <b>REMOTE CATALOG</b>\n\n{html.escape(str(catalog))}', parse_mode='HTML',
                               reply_markup=_rg_api_markup())
            else:
                plain = ['RG API REMOTE CATALOG', '=' * 32]
                for item in catalog:
                    plain.append(f"{item.get('name')} — Product ID: {item.get('product_id')}")
                    for p in item.get('plans') or []:
                        plain.append(f"   {p.get('validity')} — Variant ID: {p.get('valid_id')} — Price: {p.get('price')}")
                if not catalog:
                    plain.append('No products available.')
                body = '\n'.join(plain)
                if len(body) <= 3500:
                    _admin_ui_send(call, '📋 <pre>' + html.escape(body) + '</pre>', parse_mode='HTML', reply_markup=_rg_api_markup())
                else:
                    f = io.BytesIO(body.encode('utf-8'))
                    f.name = 'rg_remote_catalog.txt'
                    bot.send_document(call.message.chat.id, f, caption='📋 RG API remote catalog')
                    bot.answer_callback_query(call.id)

    elif call.data.startswith('rgapi_prod_'):
        if _is_admin(user_id):
            name = _rg_product_by_hash(call.data.replace('rgapi_prod_', '', 1))
            if not name:
                return
            text, markup = _rg_product_screen(name)
            _admin_ui_send(call, text, parse_mode='HTML', reply_markup=markup)

    elif call.data.startswith('rgapi_toggle_'):
        if _is_admin(user_id):
            name = _rg_product_by_hash(call.data.replace('rgapi_toggle_', '', 1))
            if not name:
                return
            if not _rg_connected():
                bot.answer_callback_query(call.id, 'Run Check Connection first.', show_alert=True)
                return
            new_state = not _rg_product_enabled(name)
            if new_state and not (_rg_product_id(name) and (_rg_entry(name).get('plans'))):
                bot.answer_callback_query(call.id, 'Set the Product ID and at least one Variant ID first.', show_alert=True)
                return
            _rg_update_entry(name, enabled=new_state)
            bot.answer_callback_query(call.id, 'Hack connected to RG API' if new_state else 'Hack disconnected from RG API')
            text, markup = _rg_product_screen(name)
            _admin_ui_send(call, text, parse_mode='HTML', reply_markup=markup)

    elif call.data.startswith('rgapi_setpid_'):
        if _is_admin(user_id):
            name = _rg_product_by_hash(call.data.replace('rgapi_setpid_', '', 1))
            if not name:
                return
            admin_temp_data.setdefault(int(user_id), {})['rg_product'] = name
            m = _admin_ui_send(call, f'🆔 <b>Enter RG Product ID for {html.escape(str(name))}:</b>', parse_mode='HTML')
            bot.register_next_step_handler(m, step_save_rg_product_id)

    elif call.data.startswith('rgapi_vid_'):
        if _is_admin(user_id):
            try:
                plan_id = int(call.data.replace('rgapi_vid_', '', 1))
            except ValueError:
                return
            name = _rg_product_name_by_plan(plan_id)
            if not name:
                return
            admin_temp_data.setdefault(int(user_id), {}).update({'rg_product': name, 'rg_plan_id': plan_id})
            m = _admin_ui_send(call, f'🆔 <b>Enter RG Variant ID for {html.escape(str(name))} plan:</b>', parse_mode='HTML')
            bot.register_next_step_handler(m, step_save_rg_variant_id)

    elif call.data.startswith('rgapi_match1_'):
        if _is_admin(user_id):
            name = _rg_product_by_hash(call.data.replace('rgapi_match1_', '', 1))
            if not name:
                return
            ok, err, rep = _rg_auto_match(only_product=name)
            if not ok:
                bot.answer_callback_query(call.id, str(err)[:180], show_alert=True)
                return
            bot.answer_callback_query(call.id, 'Matched!' if rep.get('matched') else 'No matching product on the RG server', show_alert=not rep.get('matched'))
            text, markup = _rg_product_screen(name)
            _admin_ui_send(call, text, parse_mode='HTML', reply_markup=markup)

    elif call.data.startswith('rgapi_clear_'):
        if _is_admin(user_id):
            name = _rg_product_by_hash(call.data.replace('rgapi_clear_', '', 1))
            if not name:
                return
            data = _rg_map()
            data.pop(str(name), None)
            _rg_save_map(data)
            bot.answer_callback_query(call.id, 'Mapping cleared')
            text, markup = _rg_product_screen(name)
            _admin_ui_send(call, text, parse_mode='HTML', reply_markup=markup)

    elif call.data == 'tobix_api_system':
        if _is_admin(user_id):
            _send_tobix_panel(call)

    elif call.data == 'tobix_set_token':
        if _is_admin(user_id):
            m = _admin_ui_send(call, '🔑 <b>Enter TobiX API Token:</b>', parse_mode='HTML')
            bot.register_next_step_handler(m, step_save_tobix_token)

    elif call.data == 'tobix_set_url':
        if _is_admin(user_id):
            m = _admin_ui_send(call, '🌐 <b>Enter TobiX Server Link:</b>\n\nExample: <code>http://140.245.202.76</code>', parse_mode='HTML')
            bot.register_next_step_handler(m, step_save_tobix_url)

    elif call.data == 'tobix_check':
        if _is_admin(user_id):
            ok, detail, _ = _tobix_check_connection()
            bot.answer_callback_query(call.id, 'Connected Successfully!' if ok else 'Not Connected', show_alert=True)
            _send_tobix_panel(call)

    elif call.data == 'tobix_products':
        if _is_admin(user_id):
            _admin_ui_send(call,
                '🎮 <b>TOBIX — CONNECT HACK</b>\n━━━━━━━━━━━━━━━━━━━━\n\n'
                'Tap a hack to enable/disable TobiX for that product.\n'
                'The selected hack will use TobiX for supported day-based plans.',
                parse_mode='HTML', reply_markup=_tobix_products_markup())

    elif call.data.startswith('tobix_product_'):
        if _is_admin(user_id):
            product_name = _tobix_product_by_hash(call.data.replace('tobix_product_', '', 1))
            if not product_name:
                return
            enabled = _tobix_product_enabled(product_name)
            plans = get_product_plans(product_name)
            lines = [f"🎮 <b>{html.escape(product_name)}</b>", '', f"TobiX: {'🟢 CONNECTED TO THIS HACK' if enabled else '⚪ NOT CONNECTED'}", '', '<b>Plans:</b>']
            for row in plans:
                days = str(row[2])
                supported = _tobix_plan_days(days) is not None
                lines.append(f"• {html.escape(days)} — {'✅ Supported' if supported else '❌ TobiX expects a day value'}")
            m = types.InlineKeyboardMarkup(row_width=1)
            m.add(_admin_colorful_button(
                '🔴 Disconnect Hack' if enabled else '🟢 Connect Hack',
                callback_data=f"tobix_toggle_{_ui_hash(product_name)}",
                color='red' if enabled else 'green'))
            m.add(_admin_colorful_button('🔙 Hack List', callback_data='tobix_products', color='blue'))
            _admin_ui_send(call, '\n'.join(lines), parse_mode='HTML', reply_markup=_ensure_admin_back_button(m))

    elif call.data.startswith('tobix_toggle_'):
        if _is_admin(user_id):
            product_name = _tobix_product_by_hash(call.data.replace('tobix_toggle_', '', 1))
            if not product_name:
                return
            if str(get_setting('tobix_api_connected') or '0') != '1':
                bot.answer_callback_query(call.id, 'Connect TobiX API first.', show_alert=True)
                return
            new_state = not _tobix_product_enabled(product_name)
            _set_tobix_product_enabled(product_name, new_state)
            bot.answer_callback_query(call.id, 'Hack connected to TobiX' if new_state else 'Hack disconnected from TobiX')
            lines = [f"🎮 <b>{html.escape(product_name)}</b>", '', f"TobiX: {'🟢 CONNECTED TO THIS HACK' if new_state else '⚪ NOT CONNECTED'}", '', '<b>Plans:</b>']
            for row in get_product_plans(product_name):
                days = str(row[2]); supported = _tobix_plan_days(days) is not None
                lines.append(f"• {html.escape(days)} — {'✅ Supported' if supported else '❌ TobiX expects a day value'}")
            m = types.InlineKeyboardMarkup(row_width=1)
            m.add(_admin_colorful_button(
                '🔴 Disconnect Hack' if new_state else '🟢 Connect Hack',
                callback_data=f"tobix_toggle_{_ui_hash(product_name)}",
                color='red' if new_state else 'green'))
            m.add(_admin_colorful_button('🔙 Hack List', callback_data='tobix_products', color='blue'))
            _admin_ui_send(call, '\n'.join(lines), parse_mode='HTML', reply_markup=_ensure_admin_back_button(m))

    elif call.data == "ninex_api_system":
        if _is_admin(user_id):
            _send_ninex_panel(call)

    elif call.data == "ninex_set_token":
        if _is_admin(user_id):
            m = _admin_ui_send(call, '🔑 <b>Enter 9X API Token:</b>', parse_mode='HTML')
            bot.register_next_step_handler(m, step_save_ninex_token)

    elif call.data == "ninex_set_url":
        if _is_admin(user_id):
            m = _admin_ui_send(call, f'🌐 <b>Enter 9X Server Link:</b>\n\nExample: <code>{NINEX_DEFAULT_API_URL}</code>', parse_mode='HTML')
            bot.register_next_step_handler(m, lambda msg: step_save_ninex_url_direct(msg, user_id))

    elif call.data == "ninex_check":
        if _is_admin(user_id):
            ok, detail, _ = _ninex_check_connection()
            bot.answer_callback_query(call.id, 'Connected Successfully!' if ok else 'Not Connect', show_alert=True)
            _send_ninex_panel(call)

    elif call.data == "ninex_products":
        if _is_admin(user_id):
            _admin_ui_send(call, '📦 <b>9X PRODUCT SETUP</b>\n\n'
                'Enable 9X only for the products you want to sell through 9X.\n'
                'Only 10, 20 and 30 day plans can generate 9X Single Device keys.',
                parse_mode='HTML', reply_markup=_ninex_products_markup())

    elif call.data.startswith("ninex_product_"):
        if _is_admin(user_id):
            product_name = _ninex_product_by_hash(call.data.replace('ninex_product_', '', 1))
            if not product_name: return
            enabled = _ninex_product_enabled(product_name)
            plans = get_product_plans(product_name)
            lines = [f"📦 <b>{html.escape(product_name)}</b>", '', f"9X: {'🟢 ON' if enabled else '⚪ OFF'}", '', 'Plans:']
            for row in plans:
                d = _clean_plan_days(row[2])
                lines.append(f"• {html.escape(str(d))} days — {'✅ Supported' if _ninex_plan_days(d) else '❌ 9X supports only 10/20/30'}")
            m = types.InlineKeyboardMarkup()
            m.add(types.InlineKeyboardButton('🔴 Disable 9X' if enabled else '🟢 Enable 9X', callback_data=f'ninex_toggle_{_ui_hash(product_name)}'))
            m.add(types.InlineKeyboardButton('🔙 9X Product List', callback_data='ninex_products'))
            _admin_ui_send(call, '\n'.join(lines), parse_mode='HTML', reply_markup=m)

    elif call.data.startswith("ninex_toggle_"):
        if _is_admin(user_id):
            product_name = _ninex_product_by_hash(call.data.replace('ninex_toggle_', '', 1))
            if not product_name: return
            new_state = not _ninex_product_enabled(product_name)
            _set_ninex_product_enabled(product_name, new_state)
            bot.answer_callback_query(call.id, '9X Enabled' if new_state else '9X Disabled')
            # Re-render product details without creating an extra screen.
            lines = [f"📦 <b>{html.escape(product_name)}</b>", '', f"9X: {'🟢 ON' if new_state else '⚪ OFF'}", '', 'Plans:']
            for row in get_product_plans(product_name):
                d = _clean_plan_days(row[2])
                lines.append(f"• {html.escape(str(d))} days — {'✅ Supported' if _ninex_plan_days(d) else '❌ 9X supports only 10/20/30'}")
            m = types.InlineKeyboardMarkup()
            m.add(types.InlineKeyboardButton('🔴 Disable 9X' if new_state else '🟢 Enable 9X', callback_data=f'ninex_toggle_{_ui_hash(product_name)}'))
            m.add(types.InlineKeyboardButton('🔙 9X Product List', callback_data='ninex_products'))
            _admin_ui_send(call, '\n'.join(lines), parse_mode='HTML', reply_markup=m)

    elif call.data == "new_server_api":
        if _is_admin(user_id):
            _show_api_server_list(call.message.chat.id, message_id=call.message.message_id)
            bot.answer_callback_query(call.id)

    elif call.data.startswith("new_server_hack_"):
        if _is_admin(user_id):
            product_name=_new_server_hack_by_hash(call.data.replace("new_server_hack_",'',1));
            if not product_name: return
            cfg=_new_server_config(product_name); pid=cfg[3] if cfg else ''
            markup=_new_server_plans_markup(product_name); markup.add(types.InlineKeyboardButton("🆔 Set / Change Product ID",callback_data=f"new_server_set_pid_{_ui_hash(product_name)}")); markup.add(types.InlineKeyboardButton("🔙 Hack List",callback_data="new_server_api"))
            _admin_ui_send(call,f"🎮 <b>{html.escape(product_name)}</b>\n\n🌐 <b>New Server:</b> <code>{html.escape(NEW_SERVER_API_URL)}</code>\n🆔 <b>Product ID:</b> <code>{html.escape(pid or 'Not Set')}</code>\n\nTap a plan to set its Valid ID.",parse_mode="HTML",reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("new_server_set_pid_"):
        if _is_admin(user_id):
            product_name=_new_server_hack_by_hash(call.data.replace("new_server_set_pid_",'',1));
            if not product_name: return
            admin_temp_data[user_id]={'new_server_product':product_name}; m=_admin_ui_send(call,f"🆔 <b>Enter New Server Product ID for {html.escape(product_name)}:</b>\n\nThe ID is stored exactly as entered.",parse_mode="HTML"); bot.register_next_step_handler(m,step_save_new_server_product_id)

    elif call.data.startswith("new_server_plan_"):
        if _is_admin(user_id):
            raw=call.data.replace("new_server_plan_",'',1); pieces=raw.rsplit('_',1)
            if len(pieces)!=2: return
            product_name=_new_server_hack_by_hash(pieces[0])
            try: plan_id=int(pieces[1])
            except ValueError: return
            if not product_name: return
            plans={int(x[0]):x for x in get_product_plans(product_name)}; plan=plans.get(plan_id)
            if not plan: return
            admin_temp_data[user_id]={'new_server_product':product_name,'new_server_plan_id':plan_id,'new_server_plan_days':str(plan[2])}; m=_admin_ui_send(call,f"🆔 <b>Enter New Server Valid ID for {html.escape(str(plan[2]))}:</b>\n\nThe Valid ID is stored exactly as entered.",parse_mode="HTML"); bot.register_next_step_handler(m,step_save_new_server_valid_id)

    elif call.data == "admin_support_settings":
        if _is_admin(user_id):
            tg_id = get_support_setting(TELEGRAM_SUPPORT_ID_KEY, TELEGRAM_USER)
            wa_num = get_support_setting(WHATSAPP_SUPPORT_NUMBER_KEY, WHATSAPP_NUM)
            tg_show = "🟢 ON" if _support_is_visible(TELEGRAM_SUPPORT_SHOW_KEY, True) else "🔴 OFF"
            wa_show = "🟢 ON" if _support_is_visible(WHATSAPP_SUPPORT_SHOW_KEY, True) else "🔴 OFF"
            _admin_ui_send(call,
                
                "🛟 <b>SUPPORT SETTINGS</b>\n\n"
                f"✈️ Telegram: <code>{html.escape(tg_id)}</code> — {tg_show}\n"
                f"📱 WhatsApp: <code>{html.escape(wa_num)}</code> — {wa_show}\n\n"
                "The two visibility switches work independently.",
                parse_mode='HTML', reply_markup=_support_settings_markup()
            )

    elif call.data == "support_edit_tg":
        if _is_admin(user_id):
            msg = _admin_ui_send(call, "✈️ <b>Enter the new Telegram Support ID/username:</b>", parse_mode='HTML')
            bot.register_next_step_handler(msg, step_save_support_tg)

    elif call.data == "support_edit_wa":
        if _is_admin(user_id):
            msg = _admin_ui_send(call, "📱 <b>Enter the new WhatsApp Support Number with country code:</b>", parse_mode='HTML')
            bot.register_next_step_handler(msg, step_save_support_wa)

    elif call.data == "support_toggle_tg":
        if _is_admin(user_id):
            new_state = not _support_is_visible(TELEGRAM_SUPPORT_SHOW_KEY, True)
            set_setting(TELEGRAM_SUPPORT_SHOW_KEY, '1' if new_state else '0')
            bot.answer_callback_query(call.id, "Telegram Support " + ("ON" if new_state else "OFF"))
            _admin_ui_send(call, f"✈️ <b>Telegram Support:</b> {'🟢 ON' if new_state else '🔴 OFF'}", parse_mode='HTML', reply_markup=_support_settings_markup())

    elif call.data == "support_toggle_wa":
        if _is_admin(user_id):
            new_state = not _support_is_visible(WHATSAPP_SUPPORT_SHOW_KEY, True)
            set_setting(WHATSAPP_SUPPORT_SHOW_KEY, '1' if new_state else '0')
            bot.answer_callback_query(call.id, "WhatsApp Support " + ("ON" if new_state else "OFF"))
            _admin_ui_send(call, f"📱 <b>WhatsApp Support:</b> {'🟢 ON' if new_state else '🔴 OFF'}", parse_mode='HTML', reply_markup=_support_settings_markup())

    elif call.data == "admin_update_link":
        if _is_admin(user_id):
            current = get_update_channel_link()
            msg = _admin_ui_send(call,
                
                "📢 <b>ALL FILE UPDATE LINK</b>\n\n"
                f"Current link: <code>{html.escape(current)}</code>\n\n"
                "Send the new channel/link URL:",
                parse_mode='HTML'
            )
            bot.register_next_step_handler(msg, step_save_update_channel_link)

    elif call.data == "admin_user_activity_toggle":
        if _is_admin(user_id):
            new_state = not is_user_activity_notifications_enabled()
            set_user_activity_notifications_enabled(new_state)
            status = "🟢 ON" if new_state else "🔴 OFF"
            bot.answer_callback_query(
                call.id,
                "User Tracking Notifications " + ("ON" if new_state else "OFF"),
                show_alert=True
            )
            detail = (
                "User/reseller Button/Callback activity notifications will be sent to Admin."
                if new_state else
                "User/reseller Button/Callback activity notifications are disabled. Purchase, balance, delivery and other business notifications remain unchanged."
            )
            _admin_ui_send(
                call,
                f"🔔 <b>User Tracking Notifications:</b> {status}\n\n{detail}",
                parse_mode='HTML', reply_markup=_admin_main_markup()
            )

    elif call.data == "admin_bot_toggle":
        if _is_admin(user_id):
            new_state = not is_bot_enabled()
            set_bot_enabled(new_state)
            status = "🟢 ON" if new_state else "🔴 OFF"
            bot.answer_callback_query(call.id, "Bot " + ("ON" if new_state else "OFF"), show_alert=True)
            _admin_ui_send(call,
                
                f"🤖 <b>Bot Status:</b> {status}\n\n" +
                ("Users can use the bot normally." if new_state else "🔧 Users will only receive <b>Bot Under Maintenance</b>. Admin access remains available."),
                parse_mode='HTML', reply_markup=_admin_main_markup()
            )

    elif call.data == "admin_user_ban_unban":
        if _is_admin(user_id):
            msg = _admin_ui_send(call, "🚫 <b>USER BAN & UNBAN</b>\n\nEnter the Telegram User ID you want to manage:", parse_mode='HTML')
            bot.register_next_step_handler(msg, step_get_user_ban_id)

    elif call.data.startswith("user_ban_action_"):
        if _is_admin(user_id):
            parts = call.data.split('_')
            if len(parts) != 5:
                return
            banned = parts[3] == '1'
            try:
                target = int(parts[4])
            except ValueError:
                return
            set_user_ban_status(target, banned)
            bot.answer_callback_query(call.id, "User Banned" if banned else "User Unbanned", show_alert=True)
            if banned:
                try:
                    bot.send_message(target, "🚫 <b>Your access to this bot has been restricted.</b>", parse_mode='HTML')
                except Exception:
                    pass
            _admin_ui_send(call,
                
                f"{'🚫' if banned else '✅'} <b>User {'Banned' if banned else 'Unbanned'} Successfully</b>\n\nTelegram ID: <code>{target}</code>",
                parse_mode='HTML'
            )

    elif call.data == "admin_edit_hack_inside":
        if _is_admin(user_id):
            products = get_unique_products()
            if not products:
                _admin_ui_send(call, "❌ No hacks/products found.", parse_mode='HTML')
                return
            markup = types.InlineKeyboardMarkup(row_width=1)
            catalog = {}
            for name in products:
                h = _ui_hash(name)
                catalog[h] = name
                markup.add(types.InlineKeyboardButton(f"🎮 {name}", callback_data=f"edit_hack_select_{h}"))
            admin_temp_data.setdefault(user_id, {})['edit_hack_catalog'] = catalog
            _admin_ui_send(call, "✏️ <b>EDIT EXISTING HACK</b>\n\nSelect the hack you want to edit:", parse_mode='HTML', reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("edit_hack_select_"):
        if _is_admin(user_id):
            h = call.data.replace("edit_hack_select_", '', 1)
            product_name = admin_temp_data.get(user_id, {}).get('edit_hack_catalog', {}).get(h)
            if not product_name:
                bot.answer_callback_query(call.id, "Please reopen Edit Existing Hack.", show_alert=True)
                return
            admin_temp_data[user_id] = {'edit_hack_name': product_name, 'edit_hack_catalog': {h: product_name}}
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("✏️ Edit Hack Name", callback_data=f"edit_hack_name_{h}"),
                types.InlineKeyboardButton("💰 Edit Price", callback_data=f"edit_hack_price_{h}"),
            )
            markup.add(types.InlineKeyboardButton("📅 Edit Plan / Days", callback_data=f"edit_hack_days_{h}"))
            markup.add(types.InlineKeyboardButton("🔙 Manage Hacks & Plans", callback_data="admin_hack_day_mgmt"))
            _admin_ui_send(call, f"✏️ <b>EDIT: {html.escape(product_name)}</b>\n\nChoose what you want to change:", parse_mode='HTML', reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("edit_hack_name_"):
        if _is_admin(user_id):
            h = call.data.replace("edit_hack_name_", '', 1)
            product_name = admin_temp_data.get(user_id, {}).get('edit_hack_catalog', {}).get(h) or admin_temp_data.get(user_id, {}).get('edit_hack_name')
            if not product_name:
                return
            admin_temp_data[user_id] = {'edit_hack_name': product_name}
            msg = _admin_ui_send(call, f"✏️ <b>Enter new name for:</b> {html.escape(product_name)}", parse_mode='HTML')
            bot.register_next_step_handler(msg, step_save_hack_rename)

    elif call.data.startswith("edit_hack_price_") and not call.data.startswith("edit_hack_price_plan_"):
        if _is_admin(user_id):
            h = call.data.replace("edit_hack_price_", '', 1)
            product_name = admin_temp_data.get(user_id, {}).get('edit_hack_catalog', {}).get(h) or admin_temp_data.get(user_id, {}).get('edit_hack_name')
            if not product_name:
                return
            plans = get_product_plans(product_name)
            markup = types.InlineKeyboardMarkup(row_width=1)
            for plan in plans:
                markup.add(types.InlineKeyboardButton(f"💰 {plan[2]} — ₹{plan[3]:.2f} / Resell ₹{plan[4]:.2f}", callback_data=f"edit_hack_price_plan_{plan[0]}"))
            _admin_ui_send(call, f"💰 <b>SELECT PLAN TO EDIT PRICE</b>\n\nHack: {html.escape(product_name)}", parse_mode='HTML', reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("edit_hack_price_plan_"):
        if _is_admin(user_id):
            plan_id = int(call.data.replace("edit_hack_price_plan_", '', 1))
            admin_temp_data.setdefault(user_id, {})['edit_plan_id'] = plan_id
            msg = _admin_ui_send(call, "💰 <b>Enter new price:</b>\nFormat: <code>User_Price | Reseller_Price</code>", parse_mode='HTML')
            bot.register_next_step_handler(msg, step_save_existing_hack_price)

    elif call.data.startswith("edit_hack_days_") and not call.data.startswith("edit_hack_days_plan_"):
        if _is_admin(user_id):
            h = call.data.replace("edit_hack_days_", '', 1)
            product_name = admin_temp_data.get(user_id, {}).get('edit_hack_catalog', {}).get(h) or admin_temp_data.get(user_id, {}).get('edit_hack_name')
            if not product_name:
                return
            plans = get_product_plans(product_name)
            markup = types.InlineKeyboardMarkup(row_width=1)
            for plan in plans:
                markup.add(types.InlineKeyboardButton(f"📅 {plan[2]}", callback_data=f"edit_hack_days_plan_{plan[0]}"))
            _admin_ui_send(call, f"📅 <b>SELECT PLAN TO EDIT DURATION</b>\n\nHack: {html.escape(product_name)}", parse_mode='HTML', reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("edit_hack_days_plan_"):
        if _is_admin(user_id):
            plan_id = int(call.data.replace("edit_hack_days_plan_", '', 1))
            admin_temp_data.setdefault(user_id, {})['edit_plan_id'] = plan_id
            msg = _admin_ui_send(call, "📅 <b>Enter the new plan/duration name:</b>\nExample: <code>7 Days</code>", parse_mode='HTML')
            bot.register_next_step_handler(msg, step_save_hack_days_edit)

    elif call.data == "admin_reorder_hacks":
        if _is_admin(user_id):
            products = get_unique_products()
            if not products:
                _admin_ui_send(call, "❌ No hacks/products found to reorder.", parse_mode="HTML")
                return
            markup = types.InlineKeyboardMarkup()
            for idx, prod in enumerate(products, 1):
                btn_name = types.InlineKeyboardButton(f"{idx}. {prod}", callback_data="noop")
                btn_up = types.InlineKeyboardButton("⬆️ Up", callback_data=f"reorder_up_{prod}")
                btn_down = types.InlineKeyboardButton("⬇️ Down", callback_data=f"reorder_down_{prod}")
                markup.add(btn_name, btn_up, btn_down)
            _admin_ui_send(call, "🔄 <b>HACK LIST REORDER PANEL</b>\n\nUse Up/Down buttons to adjust the sequence in which hacks appear in store:", parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("reorder_up_") or call.data.startswith("reorder_down_"):
        if _is_admin(user_id):
            is_up = call.data.startswith("reorder_up_")
            prod_name = call.data.replace("reorder_up_", "") if is_up else call.data.replace("reorder_down_", "")
            move_hack_order(prod_name, "up" if is_up else "down")
            
            products = get_unique_products()
            markup = types.InlineKeyboardMarkup()
            for idx, prod in enumerate(products, 1):
                btn_name = types.InlineKeyboardButton(f"{idx}. {prod}", callback_data="noop")
                btn_up = types.InlineKeyboardButton("⬆️ Up", callback_data=f"reorder_up_{prod}")
                btn_down = types.InlineKeyboardButton("⬇️ Down", callback_data=f"reorder_down_{prod}")
                markup.add(btn_name, btn_up, btn_down)
            
            try:
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=_ensure_admin_back_button(markup))
            except Exception:
                pass
            bot.answer_callback_query(call.id, f"Moved {prod_name} {'Up' if is_up else 'Down'}!")

    elif call.data == "admin_user_reset":
        if _is_admin(user_id):
            msg = _admin_ui_send(call, "🔄 <b>USER RESET PANEL</b>\n\nPlease enter or paste the Telegram User ID you want to reset completely:\n\n<i>This will erase their profile and force them to re-verify phone number on next /start.</i>", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_process_user_reset)

    elif call.data == "admin_reset_all_users":
        if _is_admin(user_id):
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(types.InlineKeyboardButton("⚠️ YES, RESET ALL USERS & RESELLERS", callback_data="admin_reset_all_users_confirm"))
            markup.add(types.InlineKeyboardButton("🔙 Cancel / Users & Resellers", callback_data="admin_cat_users"))
            _admin_ui_send(call,
                "⚠️ <b>RESET ALL USERS & RESELLERS</b>\n\n"
                "This clears user/reseller profiles, balances, verification, referral data, purchase history, pending payments, reseller API credentials and per-user prices. "
                "Products, plans, keys/stock, country catalogs, server/API configuration and bot settings are kept.\n\n"
                "A recoverable snapshot will be saved first. Use <b>Restore User Data</b> to bring the previous user data back.\n\n"
                "<b>Continue?</b>", parse_mode="HTML", reply_markup=markup)

    elif call.data == "admin_reset_all_users_confirm":
        if _is_admin(user_id):
            try:
                admin_ids = _user_reset_admin_ids()
                conn = sqlite3.connect(str(BOT_DB_PATH), timeout=30)
                try:
                    if admin_ids:
                        marks = ",".join("?" for _ in admin_ids)
                        count = conn.execute(f"SELECT COUNT(*) FROM users WHERE user_id NOT IN ({marks})", tuple(sorted(admin_ids))).fetchone()[0]
                    else:
                        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                finally:
                    conn.close()
                reset_all_users_and_resellers_db()
                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(types.InlineKeyboardButton("♻️ Restore User Data", callback_data="admin_restore_all_users"))
                markup.add(types.InlineKeyboardButton("🔙 Users & Resellers", callback_data="admin_cat_users"))
                _admin_ui_send(call,
                    f"✅ <b>ALL USER & RESELLER ACCOUNTS RESET</b>\n\n"
                    f"Reset accounts: <b>{count}</b>\n"
                    "When users send /start again, their account will be created from scratch and phone-number validation will run again.\n\n"
                    "Products, plans, stock/keys, country catalogs and bot settings were kept. Previous user data is saved and can be restored.",
                    parse_mode="HTML", reply_markup=markup)
            except Exception as exc:
                _admin_ui_send(call, "❌ <b>Bulk reset failed.</b> No reset was completed if snapshot creation failed.\n\n"
                    f"<code>{html.escape(str(exc), quote=False)}</code>", parse_mode="HTML")

    elif call.data == "admin_restore_all_users":
        if _is_admin(user_id):
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(types.InlineKeyboardButton("♻️ CONFIRM RESTORE USER DATA", callback_data="admin_restore_all_users_confirm"))
            markup.add(types.InlineKeyboardButton("🔙 Cancel / Users & Resellers", callback_data="admin_cat_users"))
            _admin_ui_send(call,
                "♻️ <b>RESTORE USER DATA</b>\n\n"
                "This will restore the saved user/reseller accounts, balances, verification records, purchase/payment history, reseller API credentials, custom prices and prior coupon usage. "
                "Product/catalog/server settings will remain as they are now.\n\nContinue?",
                parse_mode="HTML", reply_markup=markup)

    elif call.data == "admin_restore_all_users_confirm":
        if _is_admin(user_id):
            try:
                restore_all_users_and_resellers_db()
                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(types.InlineKeyboardButton("🔙 Users & Resellers", callback_data="admin_cat_users"))
                _admin_ui_send(call, "✅ <b>User and reseller data restored successfully.</b>\nProducts, plans, country catalogs and bot settings were not changed.",
                               parse_mode="HTML", reply_markup=markup)
            except Exception as exc:
                _admin_ui_send(call, "❌ <b>Restore failed.</b>\n\n"
                    f"<code>{html.escape(str(exc), quote=False)}</code>", parse_mode="HTML")

    elif call.data == "noop":
        bot.answer_callback_query(call.id)

    elif call.data == "admin_device_id_mgmt":
        if _is_admin(user_id):
            products = get_unique_products()
            if not products:
                _admin_ui_send(call, "❌ No products found.")
                return
            markup = types.InlineKeyboardMarkup()
            for prod in products:
                markup.add(types.InlineKeyboardButton(f"🎮 {prod}", callback_data=f"device_id_hack_{prod}"))
            _admin_ui_send(call, "📱 <b>SELECT HACK TO TOGGLE DEVICE ID REQUIREMENT:</b>", parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("device_id_hack_"):
        if _is_admin(user_id):
            p_name = call.data.replace("device_id_hack_", "")
            plans = get_product_plans(p_name)
            markup = types.InlineKeyboardMarkup()
            for plan in plans:
                p_id = plan[0]
                p_days = plan[2]
                req_dev = plan[10] if len(plan) > 10 else 0
                status_str = "📱 Device ID ON" if req_dev == 1 else "⚪ Device ID OFF"
                markup.add(types.InlineKeyboardButton(f"{p_days} ({status_str})", callback_data=f"toggle_dev_id_{p_id}_{1 if req_dev==0 else 0}"))
            _admin_ui_send(call, f"🎮 <b>Hack: {p_name}</b>\nTap any plan to toggle Device ID Requirement On/Off:", parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("toggle_dev_id_"):
        if _is_admin(user_id):
            parts = call.data.split("_")
            p_id = int(parts[3])
            new_status = int(parts[4])
            set_plan_device_id_status(p_id, new_status)
            status_txt = "ON (Device ID Required)" if new_status == 1 else "OFF (No Device ID)"
            bot.answer_callback_query(call.id, f"Device ID Status Updated to {status_txt}!", show_alert=True)
            _admin_ui_send(call, f"✅ Device ID Requirement updated to <b>{status_txt}</b> successfully!", parse_mode="HTML")

    elif call.data == "admin_edit_price":
        if _is_admin(user_id):
            products = get_unique_products()
            if not products:
                _admin_ui_send(call, "❌ No products found.", parse_mode="HTML")
                return
            markup = types.InlineKeyboardMarkup()
            for prod in products:
                markup.add(types.InlineKeyboardButton(f"🎮 {prod}", callback_data=f"edit_price_hack_{prod}"))
            _admin_ui_send(call, "✏️ <b>SELECT HACK TO EDIT PLAN PRICING:</b>", parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("edit_price_hack_"):
        if _is_admin(user_id):
            p_name = call.data.replace("edit_price_hack_", "")
            plans = get_product_plans(p_name)
            markup = types.InlineKeyboardMarkup()
            for plan in plans:
                markup.add(types.InlineKeyboardButton(f"⏱️ {plan[2]} (₹{plan[3]} / Resell ₹{plan[4]})", callback_data=f"select_plan_edit_price_{plan[0]}"))
            _admin_ui_send(call, f"🎮 <b>Selected Hack: {p_name}</b>\nSelect plan to update price:", parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("select_plan_edit_price_"):
        if _is_admin(user_id):
            plan_id = int(call.data.replace("select_plan_edit_price_", ""))
            admin_temp_data[user_id] = {'plan_id': plan_id}
            msg = _admin_ui_send(call, "💰 <b>Enter New User Price & Reseller Price in INR (₹)</b>\nFormat: <code>User_Price | Reseller_Price</code>\nExample: <code>250 | 180</code>", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_edit_product_price)

    elif call.data == "admin_view_pending_payments":
        if _is_admin(user_id):
            pending_list = get_all_pending_payments()
            if pending_list:
                msg_text = "⏳ <b>RECENT PENDING PAYMENTS (EXPIRED QRs)</b>\n────────────────────────\n\n"
                for item in pending_list:
                    ord_id, u_id, u_name, p_name, p_days, amt, dt = item
                    msg_text += (
                        f"🆔 <b>Order ID:</b> <code>{ord_id}</code>\n"
                        f"├── 👤 <b>User:</b> {u_name} (<code>{u_id}</code>)\n"
                        f"├── 🛒 <b>Hack:</b> {p_name}\n"
                        f"├── ⏱️ <b>Plan:</b> {p_days}\n"
                        f"├── 💰 <b>Amount:</b> ₹{amt:.2f} INR\n"
                        f"└── ⏰ <b>Time:</b> {dt}\n\n"
                    )
            else:
                msg_text = "✅ <i>No pending/expired payments recorded yet!</i>"
            
            _admin_ui_send(call, msg_text, parse_mode="HTML", reply_markup=_gateway_manager_markup())

    elif call.data == "admin_db_backup":
        if _is_admin(user_id):
            # Opening Backups now shows an explicit Download Backup action.
            # The actual archive is generated from the live SQLite database so
            # the button never depends on a stale relative shop_data.db path.
            m = types.InlineKeyboardMarkup(row_width=1)
            m.add(make_ui_button('📥 Download Latest Backup', callback_data='admin_db_backup_download', button_key='admin:backup:download', default_color='green', force_style=True))
            # Existing automatic archives are also directly downloadable.
            try:
                existing = sorted(
                    [p for p in BOT_AUTO_BACKUP_DIR.glob('auto_backup_*.zip') if p.is_file()],
                    key=lambda p: p.stat().st_mtime, reverse=True
                )[:10]
                backup_catalog = {}
                for archive in existing:
                    h = _ui_hash(str(archive))
                    backup_catalog[h] = str(archive)
                    size_mb = archive.stat().st_size / (1024 * 1024)
                    stamp = datetime.datetime.fromtimestamp(archive.stat().st_mtime).strftime('%d %b %Y · %I:%M %p')
                    # Keep the existing archive selector and add a dedicated
                    # Download button directly underneath every backup entry.
                    m.add(types.InlineKeyboardButton(
                        f'💾 {stamp} · {size_mb:.1f} MB'[:64],
                        callback_data=f'admin_backup_download_file_{h}'
                    ))
                    m.add(make_ui_button(
                        '📥 Download Backup',
                        callback_data=f'admin_backup_download_file_{h}',
                        button_key='admin:backup:download_item',
                        default_color='green', force_style=True
                    ))
                admin_temp_data.setdefault(user_id, {})['backup_download_catalog'] = backup_catalog
            except Exception:
                pass
            m.add(make_ui_button('💾 Create Fresh Backup', callback_data='admin_backup_create_now', button_key='admin:backup:create', default_color='blue', force_style=True))
            m.add(make_ui_button('🔙 Main Admin Panel', callback_data='admin_back_main', button_key='admin:navigation:back', default_color='red', force_style=True))
            _admin_ui_send(
                call,
                '💾 <b>BOTS &amp; BACKUPS</b>\n━━━━━━━━━━━━━━━━━━━━\n\n'
                '📦 <b>Backup Center</b>\n\n'
                'Tap <b>Download Backup</b> to receive the latest complete database backup as a ZIP file directly in Telegram.\n'
                'You can also create a fresh backup first.',
                parse_mode='HTML', reply_markup=m
            )

    elif call.data.startswith('admin_backup_download_file_'):
        if _is_admin(user_id):
            h = call.data.replace('admin_backup_download_file_', '', 1)
            archive_path = admin_temp_data.get(user_id, {}).get('backup_download_catalog', {}).get(h)
            if not archive_path or not Path(archive_path).is_file():
                bot.answer_callback_query(call.id, '❌ Backup file no longer exists.', show_alert=True)
                return
            try:
                size = Path(archive_path).stat().st_size
                if size > BOT_AUTO_BACKUP_MAX_TELEGRAM_BYTES:
                    bot.answer_callback_query(call.id, '❌ Backup is too large to send via Telegram.', show_alert=True)
                    return
                with Path(archive_path).open('rb') as backup_file:
                    bot.send_document(
                        call.message.chat.id,
                        backup_file,
                        caption=f'📥 <b>Backup Ready</b>\n📦 <code>{html.escape(Path(archive_path).name)}</code>',
                        parse_mode='HTML'
                    )
                bot.answer_callback_query(call.id, '✅ Backup sent.')
            except Exception as exc:
                bot.answer_callback_query(call.id, '❌ Backup download failed.', show_alert=True)
                print(f'[ADMIN BACKUP FILE DOWNLOAD ERROR] {exc}')

    elif call.data == 'admin_db_backup_download':
        if _is_admin(user_id):
            _fast_callback_ack(call)
            try:
                archive_path = _create_auto_backup()
                size = Path(archive_path).stat().st_size
                if size > BOT_AUTO_BACKUP_MAX_TELEGRAM_BYTES:
                    bot.answer_callback_query(call.id, '❌ Backup is too large to send via Telegram.', show_alert=True)
                    return
                with Path(archive_path).open('rb') as backup_file:
                    bot.send_document(
                        call.message.chat.id,
                        backup_file,
                        caption=(
                            '📥 <b>Database Backup Ready</b>\n'
                            f'📦 <code>{html.escape(Path(archive_path).name)}</code>\n'
                            f'🕒 {_now_ist_text()} IST\n'
                            '✅ Backup downloaded successfully.'
                        ),
                        parse_mode='HTML'
                    )
                bot.answer_callback_query(call.id, '✅ Backup sent to Telegram.')
            except Exception as e:
                bot.answer_callback_query(call.id, '❌ Backup download failed.', show_alert=True)
                print(f'[ADMIN DB BACKUP DOWNLOAD ERROR] {e}')

    elif call.data == "admin_all_button_color":
        if _is_admin(user_id):
            show_user_panel_button_color_catalog(call.message.chat.id, message_id=call.message.message_id)
            bot.answer_callback_query(call.id)

    elif call.data == "admin_hack_price_ui":
        if _is_admin(user_id):
            show_hack_price_ui_catalog(call.message.chat.id, message_id=call.message.message_id)
            bot.answer_callback_query(call.id)

    elif call.data.startswith("hpui_select_"):
        if _is_admin(user_id):
            h = call.data.replace("hpui_select_", "", 1)
            product_name = admin_temp_data.get(user_id, {}).get("hack_price_ui_catalog", {}).get(h)
            if not product_name:
                bot.answer_callback_query(call.id, "Please reopen Hack Price List Design.", show_alert=True); return
            plans = get_product_plans(product_name); markup = types.InlineKeyboardMarkup(row_width=1)
            catalog = admin_temp_data.setdefault(user_id, {}).setdefault('hpui_plan_catalog', {}); catalog.clear()
            for plan in plans:
                pid, _, days, reg, res = plan[:5]; key = f"price:{product_name}:{pid}"; ph = _ui_hash(f"{product_name}:{pid}")
                catalog[ph] = {'product':product_name,'plan_id':int(pid),'key':key}
                markup.add(make_ui_button(
                    f"{'✨' if get_button_emoji(key) else '⚪'} {days} · ₹{reg:.2f} / ₹{res:.2f}",
                    callback_data=f"hpui_plan_{ph}", button_key=key,
                    default_color="blue", force_style=True, force_premium=True
                ))
            product_emoji_id = get_button_emoji(f"hack:{product_name}")
            product_emoji_label = "✨ Change Product Premium Emoji" if product_emoji_id else "✨ Add Product Premium Emoji"
            markup.add(types.InlineKeyboardButton(product_emoji_label, callback_data=f'hpui_product_emoji_{h}'))
            markup.add(types.InlineKeyboardButton('✏️ Edit Product Design', callback_data=f'hpui_edit_product_{h}'))
            markup.add(types.InlineKeyboardButton('🔙 Back to Products', callback_data='hpui_back_products'))
            _admin_ui_send(call, "🎨 <b>PREMIUM DESIGN — PRODUCT &amp; PLANS</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🎮 <b>Product:</b> {html.escape(product_name)}\n\n"
                "✨ Product Premium Emoji: tap the button below.\n"
                "📅 Every Plan is listed separately and can have its own Premium custom emoji.", parse_mode='HTML', reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("hpui_product_emoji_"):
        if _is_admin(user_id):
            h = call.data.replace('hpui_product_emoji_', '', 1)
            product_name = admin_temp_data.get(user_id, {}).get('hack_price_ui_catalog', {}).get(h)
            if not product_name:
                product_name = admin_temp_data.get(user_id, {}).get('hpui_return_product')
            if not product_name:
                bot.answer_callback_query(call.id, 'Product selection expired. Reopen Premium Design.', show_alert=True); return
            admin_temp_data[user_id] = {
                'emoji_target': f'hack:{product_name}',
                'hpui_return_product': product_name,
                'hpui_return_hash': _ui_hash(product_name),
            }
            msg = _admin_ui_send(call,
                "✨ <b>PRODUCT PREMIUM EMOJI</b>\n\n"
                f"🎮 <b>Product:</b> {html.escape(product_name)}\n\n"
                "Send exactly one Premium custom emoji. It will apply only to this Product button.\n"
                "↩️ After saving, you will return to this Product's Plan list.",
                parse_mode='HTML')
            bot.register_next_step_handler(msg, step_save_premium_emoji)

    elif call.data.startswith("hpui_plan_"):
        if _is_admin(user_id):
            ph = call.data.replace('hpui_plan_','',1); item = admin_temp_data.get(user_id,{}).get('hpui_plan_catalog',{}).get(ph)
            if not item:
                bot.answer_callback_query(call.id,'Plan list expired. Reopen Premium Design.',show_alert=True); return
            admin_temp_data[user_id] = {'emoji_target':item['key'],'hpui_return_product':item['product'],'hpui_return_hash':_ui_hash(item['product'])}
            msg = _admin_ui_send(call, "✨ <b>PLAN PREMIUM IMAGE / EMOJI</b>\n\n"
                f"🎮 <b>Product:</b> {html.escape(item['product'])}\n"
                f"🆔 <b>Plan ID:</b> <code>{int(item['plan_id'])}</code>\n\n"
                "Send exactly one Premium custom emoji. It will apply only to this Plan button.\n"
                "↩️ Use Back to return to this Product's Plan list.", parse_mode='HTML')
            bot.register_next_step_handler(msg, step_save_premium_emoji)

    elif call.data.startswith("hpui_edit_product_"):
        if _is_admin(user_id):
            h=call.data.replace('hpui_edit_product_','',1); product_name=admin_temp_data.get(user_id,{}).get('hack_price_ui_catalog',{}).get(h)
            if not product_name: product_name=admin_temp_data.get(user_id,{}).get('hpui_return_product')
            if not product_name:
                bot.answer_callback_query(call.id,'Product selection expired.',show_alert=True); return
            admin_temp_data[user_id]={'hack_price_ui_product':product_name}
            msg=_admin_ui_send(call, "🧩 <b>PRICE LIST FIX — PRODUCT DESIGN</b>\n\n"
                f"🎮 <b>Product:</b> {html.escape(product_name)}\n\nSend ONE complete design with one sample Validity / Stock / Price block.", parse_mode='HTML')
            bot.register_next_step_handler(msg, step_save_hack_price_ui_title)

    elif call.data == 'hpui_back_products':
        if _is_admin(user_id):
            _admin_pop_snapshot(user_id)
            admin_nav_skip_history.add(int(user_id))
            show_hack_price_ui_catalog(call.message.chat.id, message_id=call.message.message_id)

    elif call.data == "admin_plan_text_add":
        if _is_admin(user_id):
            products = get_unique_products()
            if not products:
                _admin_ui_send(call, "❌ No products/hacks found.", parse_mode="HTML")
                bot.answer_callback_query(call.id)
                return
            markup = types.InlineKeyboardMarkup(row_width=1)
            catalog = {}
            for product_name in products:
                h = _ui_hash(product_name)
                catalog[h] = product_name
                saved = bool(get_plan_text_product(product_name))
                label = ("🟢 " if saved else "⚪ ") + product_name
                markup.add(types.InlineKeyboardButton(label, callback_data=f"plantext_select_{h}"))
            markup.add(types.InlineKeyboardButton("🗑 Clear Product Plan Text", callback_data="plantext_clear_menu"))
            admin_temp_data.setdefault(user_id, {})['plan_text_product_catalog'] = catalog
            _admin_ui_send(call,
                
                "📝 <b>ALL PRODUCT PLAN TEXT + PREMIUM EMOJI</b>\n\n"
                "Select the hack/price list you want to design.\n"
                "Then send your own text + Premium emoji(s).\n\n"
                "Dynamic placeholders (only where you want live values):\n"
                "<code>{days}</code> = plan days\n"
                "<code>{stock}</code> = Auto-API / Manual / Out of Stock\n"
                "<code>{price}</code> = live price\n\n"
                "❌ No old PLANS & PRICING / CHOOSE A PLAN text will be added.",
                parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup)
            )
            bot.answer_callback_query(call.id)

    elif call.data.startswith("plantext_select_"):
        if _is_admin(user_id):
            h = call.data.replace("plantext_select_", "", 1)
            product_name = admin_temp_data.get(user_id, {}).get('plan_text_product_catalog', {}).get(h)
            if not product_name:
                bot.answer_callback_query(call.id, "Please reopen All Product Plan Text.", show_alert=True)
                return
            admin_temp_data[user_id] = {'plan_text_product': product_name}
            current = get_plan_text_product(product_name)
            preview = html.escape(current[:1500]) if current else "<i>No custom text saved yet.</i>"
            msg = _admin_ui_send(call,
                
                "📝 <b>PLAN TEXT + PREMIUM EMOJI</b>\n\n"
                f"🛒 <b>Hack:</b> {html.escape(product_name)}\n\n"
                "Send the exact design you want. Premium custom emojis are preserved.\n\n"
                "Recommended dynamic row: <code>⏱ {days}\n📦 {stock}\n💰 {price}</code>\n\n"
                "The bot repeats that row for every real plan and inserts live days, API/manual/OOS stock and price.\n"
                "Do not write 1/3/7/15/30 days manually.\n\n"
                "<b>Current:</b>\n" + preview,
                parse_mode="HTML"
            )
            bot.register_next_step_handler(msg, step_save_product_plan_text)
            bot.answer_callback_query(call.id)

    elif call.data == "plantext_clear_menu":
        if _is_admin(user_id):
            products = get_unique_products()
            markup = types.InlineKeyboardMarkup(row_width=1)
            catalog = {}
            for product_name in products:
                h = _ui_hash(product_name)
                catalog[h] = product_name
                markup.add(types.InlineKeyboardButton(f"🗑 {product_name}", callback_data=f"plantext_clear_{h}"))
            admin_temp_data.setdefault(user_id, {})['plan_text_product_catalog'] = catalog
            _admin_ui_send(call, "🗑 <b>Select product to clear its custom Plan Text.</b>", parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup))
            bot.answer_callback_query(call.id)

    elif call.data.startswith("plantext_clear_"):
        if _is_admin(user_id):
            h = call.data.replace("plantext_clear_", "", 1)
            product_name = admin_temp_data.get(user_id, {}).get('plan_text_product_catalog', {}).get(h)
            if not product_name:
                bot.answer_callback_query(call.id, "Please reopen the menu.", show_alert=True)
                return
            set_plan_text_product(product_name, '')
            _admin_ui_send(call, f"✅ Custom Plan Text cleared for <b>{html.escape(product_name)}</b>.", parse_mode="HTML")
            bot.answer_callback_query(call.id)

    elif call.data == "admin_all_panel_price_emoji":
        if _is_admin(user_id):
            current = get_global_price_list_template() or get_custom_text("price_list", "")
            preview = _strip_legacy_price_list_block(current)
            admin_temp_data.setdefault(user_id, {})['global_price_list_edit'] = True
            msg = _admin_ui_send(call,
                
                "💠 <b>ALL PANEL PRICE & TEXT + PREMIUM EMOJI</b>\n\n"
                "Send the master price-list design now. You can paste Premium custom emojis and formatted HTML text.\n\n"
                "Saving this design automatically turns <b>Premium Price List Mode ON</b>.\n\n"
                "The bot will automatically:\n"
                "• remove old duplicated plan/price rows from this template;\n"
                "• insert each hack's current Admin-configured plans/prices;\n"
                "• show <b>In Stock (Auto-API)</b> when API stock is used;\n"
                "• show manual stock automatically when manual keys exist;\n"
                "• preserve your Premium custom emojis;\n"
                "• keep the same template across every hack.\n\n"
                "Recommended placeholder: <code>{pricing_info}</code>\n\n"
                "<b>Current normalized template:</b>\n" + html.escape(preview[:2500]),
                parse_mode="HTML"
            )
            bot.register_next_step_handler(msg, step_save_global_price_list_template)
            bot.answer_callback_query(call.id)

    elif call.data == "admin_all_product_emoji":
        if _is_admin(user_id):
            admin_temp_data.setdefault(user_id, {})["emoji_target"] = "bulk_product_buttons"
            count = len(_get_product_button_keys())
            msg = _admin_ui_send(call,
                
                "✨ <b>ALL PRODUCT BUTTON EMOJI</b>\n\n"
                f"Found <b>{count}</b> product button(s).\n"
                "Send exactly one Premium custom emoji.\n\n"
                "That one emoji will replace the old normal leading emoji on <b>ALL product buttons</b>.",
                parse_mode="HTML"
            )
            bot.register_next_step_handler(msg, step_save_premium_emoji)
            bot.answer_callback_query(call.id)

    elif call.data == "admin_all_price_emoji":
        if _is_admin(user_id):
            admin_temp_data.setdefault(user_id, {})["emoji_target"] = "bulk_price_buttons"
            count = len(_get_price_button_keys())
            msg = _admin_ui_send(call,
                
                "💰 <b>ALL PRICE LIST BUTTON EMOJI</b>\n\n"
                f"Found <b>{count}</b> price-plan button(s).\n"
                "Send exactly one Premium custom emoji.\n\n"
                "That one emoji will replace the old normal leading emoji on <b>ALL price-list buttons</b>.",
                parse_mode="HTML"
            )
            bot.register_next_step_handler(msg, step_save_premium_emoji)
            bot.answer_callback_query(call.id)

    elif call.data == "admin_toggle_price_list_mode":
        if _is_admin(user_id):
            new_state = not get_price_list_premium_mode()
            set_price_list_premium_mode(new_state)
            status = "🟢 <b>ON</b>" if new_state else "🔴 <b>OFF</b>"
            detail = (
                "User Panel Premium Mode is ON. Configured button colors and Premium emojis are active."
                if new_state else
                "User Panel Premium Mode is OFF. All User Panel buttons use the normal/default appearance and Premium emojis fall back to their normal emoji text."
            )
            bot.answer_callback_query(call.id, "User Panel Premium Mode " + ("ON" if new_state else "OFF"))
            try:
                bot.edit_message_reply_markup(
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=call.message.reply_markup
                )
            except Exception:
                pass
            _admin_ui_send(call,
                
                f"✨ <b>User Panel Premium Mode:</b> {status}\n\n{detail}",
                parse_mode="HTML"
            )

    elif call.data == "admin_all_button_emoji":
        if _is_admin(user_id):
            show_user_panel_button_emoji_catalog(call.message.chat.id, message_id=call.message.message_id)
            bot.answer_callback_query(call.id)

    elif call.data.startswith("abe_select_"):
        if _is_admin(user_id):
            h = call.data.replace("abe_select_", "", 1)
            key = admin_temp_data.get(user_id, {}).get("all_button_emoji_catalog", {}).get(h)
            if not key:
                bot.answer_callback_query(call.id, "Please reopen All Button Emoji.", show_alert=True)
                return
            admin_temp_data.setdefault(user_id, {})["emoji_target"] = key
            msg = _admin_ui_send(call,
                
                "✨ <b>Send the Premium custom emoji now.</b>\n\n"
                "Send only one Premium emoji. It will replace the normal leading emoji on this button.",
                parse_mode="HTML"
            )
            bot.register_next_step_handler(msg, step_save_premium_emoji)
            bot.answer_callback_query(call.id)

    elif call.data == "admin_button_colors":
        if _is_admin(user_id):
            _admin_push_current_snapshot(user_id, "admin_button_colors")
            show_user_panel_button_color_catalog(
                call.message.chat.id,
                message_id=call.message.message_id
            )
            bot.answer_callback_query(call.id)

    elif call.data.startswith("upc_select_"):
        if _is_admin(user_id):
            h=call.data.replace("upc_select_", "", 1)
            key=admin_temp_data.get(user_id,{}).get("user_panel_color_catalog",{}).get(h)
            if not key:
                bot.answer_callback_query(call.id,"Please reopen User Panel Button Colors.",show_alert=True); return
            if str(key).startswith("hack:"):
                product_name=str(key)[5:]
                show_product_button_color_detail(call.message.chat.id,product_name,call.message.message_id)
                bot.answer_callback_query(call.id); return
            admin_temp_data.setdefault(user_id,{})["active_user_panel_color_key"]=key
            _show_color_picker(call,key,"upc_back_catalog","🎨 <b>SELECT BUTTON COLOR</b>")
            bot.answer_callback_query(call.id)

    elif call.data.startswith("upc_plan_select_"):
        if _is_admin(user_id):
            h=call.data.replace("upc_plan_select_",'',1)
            key=admin_temp_data.get(user_id,{}).get("product_plan_color_catalog",{}).get(h)
            product=admin_temp_data.get(user_id,{}).get("product_plan_color_product")
            if not key or not product:
                bot.answer_callback_query(call.id,"Product color session expired.",show_alert=True); return
            admin_temp_data[user_id]["active_user_panel_color_key"]=key
            _show_color_picker(call,key,f"upc_product_{_ui_hash(product)}","🎨 <b>PLAN BUTTON COLOR</b>")

    elif call.data.startswith("upc_product_color_"):
        if _is_admin(user_id):
            h=call.data.replace("upc_product_color_",'',1)
            key=f"hack:{admin_temp_data.get(user_id,{}).get('product_plan_color_product','')}"
            if not key or key=="hack:":
                bot.answer_callback_query(call.id,"Product color session expired.",show_alert=True); return
            if _ui_hash(key)!=h:
                bot.answer_callback_query(call.id,"Product selection expired.",show_alert=True); return
            _show_color_picker(call,key,f"upc_product_{_ui_hash(key[5:])}","🎨 <b>PRODUCT BUTTON COLOR</b>")

    elif call.data.startswith("upc_product_"):
        if _is_admin(user_id):
            product=admin_temp_data.get(user_id,{}).get("product_plan_color_product")
            if not product:
                bot.answer_callback_query(call.id,"Product selection expired.",show_alert=True); return
            show_product_button_color_detail(call.message.chat.id,product,call.message.message_id)
            bot.answer_callback_query(call.id)

    elif call.data.startswith("upc_color_"):
        if _is_admin(user_id):
            parts=call.data.split("_",3)
            if len(parts)!=4 or parts[2] not in ("red","green","blue"):
                bot.answer_callback_query(call.id,"Invalid color selection.",show_alert=True); return
            color=parts[2]; h=parts[3]
            key=None
            # The hash can refer to a normal catalog button or a product/plan key.
            key=admin_temp_data.get(user_id,{}).get("user_panel_color_catalog",{}).get(h)
            if not key:
                key=admin_temp_data.get(user_id,{}).get("product_plan_color_catalog",{}).get(h)
            product=admin_temp_data.get(user_id,{}).get("product_plan_color_product")
            if not key:
                active=admin_temp_data.get(user_id,{}).get("active_user_panel_color_key")
                if active and _ui_hash(active)==h: key=active
            if not key:
                bot.answer_callback_query(call.id,"Please reopen the color screen.",show_alert=True); return
            set_button_style(key,color)
            bot.answer_callback_query(call.id,f"{color.title()} saved successfully")
            if str(key).startswith("hack:") and product:
                admin_nav_skip_history.add(int(user_id))
                show_product_button_color_detail(call.message.chat.id,product,call.message.message_id)
            elif str(key).startswith("price:") and product:
                admin_nav_skip_history.add(int(user_id))
                show_product_button_color_detail(call.message.chat.id,product,call.message.message_id)
            else:
                _show_color_picker(call,key,"upc_back_catalog","🎨 <b>SELECT BUTTON COLOR</b>")


    elif call.data == "upc_back_catalog":
        if _is_admin(user_id):
            _admin_pop_snapshot(user_id)
            admin_nav_skip_history.add(int(user_id))
            show_user_panel_button_color_catalog(
                call.message.chat.id,
                message_id=call.message.message_id
            )
            bot.answer_callback_query(call.id)

    elif call.data == "admin_emoji_editor":
        if _is_admin(user_id):
            markup = types.InlineKeyboardMarkup()
            for title, key in [
                ("🛍️ Main Menu Buttons", "main_buttons"),
                ("🎮 Hack Buttons", "hack_buttons"),
                ("💙 Price List Buttons", "price_buttons"),
                ("✨ ALL Product Buttons — One Emoji", "bulk_product_buttons"),
                ("💠 ALL Price List Buttons — One Emoji", "bulk_price_buttons"),
                ("⏳ Price Expiry Emoji", "price_expiry"),
            ]:
                markup.add(types.InlineKeyboardButton(title, callback_data=f"emoji_group_{key}"))
            _admin_ui_send(call, "✨ <b>PREMIUM EMOJI EDITOR</b>\n\nFor a button: send the Premium custom emoji by itself when asked. For text/notifications use the Text Editor and send the formatted text containing your Premium emoji.", parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("emoji_group_"):
        if _is_admin(user_id):
            group = call.data.replace("emoji_group_", "")
            if group == "price_expiry":
                msg = _admin_ui_send(call, "⏳ Send one Premium custom emoji now. I will save its custom_emoji_id for Price List expiry lines.", parse_mode="HTML")
                admin_temp_data[user_id] = {"emoji_target": "price_expiry"}
                bot.register_next_step_handler(msg, step_save_premium_emoji)
            elif group == "bulk_product_buttons":
                count = len(_get_product_button_keys())
                msg = _admin_ui_send(call,
                    
                    "✨ <b>ALL PRODUCT BUTTONS</b>\n\n"
                    f"{count} product button(s) will use the same Premium emoji.\n"
                    "Send exactly one Premium custom emoji.",
                    parse_mode="HTML"
                )
                admin_temp_data[user_id] = {"emoji_target": "bulk_product_buttons"}
                bot.register_next_step_handler(msg, step_save_premium_emoji)
            elif group == "bulk_price_buttons":
                count = len(_get_price_button_keys())
                msg = _admin_ui_send(call,
                    
                    "💠 <b>ALL PRICE LIST BUTTONS</b>\n\n"
                    f"{count} price-plan button(s) will use the same Premium emoji.\n"
                    "Send exactly one Premium custom emoji.",
                    parse_mode="HTML"
                )
                admin_temp_data[user_id] = {"emoji_target": "bulk_price_buttons"}
                bot.register_next_step_handler(msg, step_save_premium_emoji)
            elif group == "main_buttons":
                markup = types.InlineKeyboardMarkup()
                for title, key in [("Open Store","main:open_store"),("Top Up","main:top_up"),("Orders","main:orders"),("My Account","main:my_account"),("Invite & Earn","main:invite_earn"),("How To Use","main:how_to_use"),("All Update","main:all_update"),("Help Desk","main:help_desk")]:
                    markup.add(types.InlineKeyboardButton(title, callback_data=f"emoji_pick_{_ui_hash(key)}"))
                    admin_temp_data.setdefault(user_id, {}).setdefault("emoji_catalog", {})[_ui_hash(key)] = key
                _admin_ui_send(call, "✨ Select a main button to set its Premium emoji.", reply_markup=_ensure_admin_back_button(markup))
            elif group in ("hack_buttons", "price_buttons"):
                markup = types.InlineKeyboardMarkup()
                products = get_unique_products()
                for prod in products:
                    if group == "hack_buttons":
                        key = f"hack:{prod}"
                        h = _ui_hash(key)
                        admin_temp_data.setdefault(user_id, {}).setdefault("emoji_catalog", {})[h] = key
                        markup.add(types.InlineKeyboardButton(f"🎮 {prod}", callback_data=f"emoji_pick_{h}"))
                    else:
                        for plan in get_product_plans(prod):
                            p_id, _, days, *_ = plan
                            key = f"price:{prod}:{p_id}"
                            h = _ui_hash(key)
                            admin_temp_data.setdefault(user_id, {}).setdefault("emoji_catalog", {})[h] = key
                            markup.add(types.InlineKeyboardButton(f"💙 {prod} / {days}", callback_data=f"emoji_pick_{h}"))
                _admin_ui_send(call, "✨ Select a button to set its Premium emoji.", reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("emoji_pick_"):
        if _is_admin(user_id):
            h = call.data.replace("emoji_pick_", "", 1)
            key = admin_temp_data.get(user_id, {}).get("emoji_catalog", {}).get(h)
            if not key:
                bot.answer_callback_query(call.id, "Please reopen the emoji editor.", show_alert=True)
                return
            admin_temp_data[user_id]["emoji_target"] = key
            msg = _admin_ui_send(call, "✨ Send the Premium custom emoji now (send it as a single emoji message).", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_save_premium_emoji)

    elif call.data == "admin_button_cust":
        if _is_admin(user_id):
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🛍️ Open Store Button", callback_data="cust_name_open_store"))
            markup.add(types.InlineKeyboardButton("💰 Top Up Button", callback_data="cust_name_top_up"))
            markup.add(types.InlineKeyboardButton("📜 Orders Button", callback_data="cust_name_orders"))
            markup.add(types.InlineKeyboardButton("👤 My Account Button", callback_data="cust_name_my_account"))
            markup.add(types.InlineKeyboardButton("🎁 Invite & Earn Button", callback_data="cust_name_invite_earn"))
            markup.add(types.InlineKeyboardButton("🎬 How To Use Button", callback_data="cust_name_how_to_use"))
            markup.add(types.InlineKeyboardButton("📢 All Update Button", callback_data="cust_name_all_update"))
            markup.add(types.InlineKeyboardButton("📞 Help Desk Button", callback_data="cust_name_help_desk"))
            # Navigation buttons are editable too. Keep these separate from the
            # main-menu entries so the old User Panel Back-button customization
            # remains available without removing any existing controls.
            markup.add(types.InlineKeyboardButton("⬅️ Back to Main Button", callback_data="cust_name_nav_back_main"))
            markup.add(types.InlineKeyboardButton("⬅️ Back to Store Button", callback_data="cust_name_nav_back_store"))
            markup.add(types.InlineKeyboardButton("🔙 Back from Top-up Button", callback_data="cust_name_nav_back_topup"))
            markup.add(types.InlineKeyboardButton("🔙 Back from QR Button", callback_data="cust_name_nav_back_qr"))
            markup.add(types.InlineKeyboardButton("❌ Add Balance Cancel Button", callback_data="cust_name_topkey_cancel"))
            markup.add(types.InlineKeyboardButton("💳 Add Balance Confirm Button", callback_data="cust_name_topkey_confirm"))
            markup.add(types.InlineKeyboardButton("🔴 All Products Out of Stock Button", callback_data="cust_name_all_products_oos"))
            _admin_ui_send(call,
                
                "✏️ <b>Select a Main Menu Button to edit its Name & Emoji:</b>",
                parse_mode="HTML",
                reply_markup=_ensure_admin_back_button(markup)
            )

    elif call.data in ("cust_name_topkey_cancel", "cust_name_topkey_confirm", "cust_name_all_products_oos"):
        if _is_admin(user_id):
            mapping = {
                "cust_name_topkey_cancel": (ADD_BALANCE_CANCEL_BUTTON_KEY, "Add Balance Cancel"),
                "cust_name_topkey_confirm": (ADD_BALANCE_CONFIRM_BUTTON_KEY, "Add Balance Confirm"),
                "cust_name_all_products_oos": (ALL_PRODUCTS_OUT_OF_STOCK_BUTTON_KEY, "All Products Out of Stock"),
            }
            b_key, title = mapping[call.data]
            admin_temp_data[user_id] = {"special_button_design": b_key}
            current = get_custom_btn(b_key, "")
            msg = _admin_ui_send(
                call,
                f"✏️ <b>{title} Button — Text + Premium Emoji</b>\n\n"
                "Send the complete button design in ONE message.\n"
                "You may place a Telegram Premium custom emoji before/after the text.\n"
                "The Premium emoji will become the button icon and the remaining text will become the button label.\n\n"
                + (f"📌 <b>Current text:</b> {html.escape(current)}" if current else "📌 No custom text saved yet."),
                parse_mode="HTML"
            )
            bot.register_next_step_handler(msg, step_save_special_button_design)

    elif call.data.startswith("cust_name_"):
        if _is_admin(user_id):
            b_key = call.data.replace("cust_name_", "", 1)
            # The four User Panel Back buttons use stable logical keys, so their
            # custom names/emojis are saved exactly like the main buttons.
            nav_map = {
                "nav_back_main": "nav:back_main",
                "nav_back_store": "nav:back_store",
                "nav_back_topup": "nav:back_topup",
                "nav_back_qr": "nav:back_qr",
            }
            b_key = nav_map.get(b_key, b_key)
            admin_temp_data[user_id] = {'btn_key': b_key}
            current = get_custom_btn(b_key, "")
            msg = _admin_ui_send(call,
                
                f"✏️ <b>Enter new name and emoji for button '{html.escape(b_key)}':</b>\n\n"
                + (f"📌 <b>Current:</b> {html.escape(current)}" if current else "📌 No custom name saved yet."),
                parse_mode="HTML"
            )
            bot.register_next_step_handler(msg, step_save_custom_btn)

    elif call.data == "admin_text_editor":
        if _is_admin(user_id):
            # Keep every existing Text Editor action/callback, but present the
            # controls as a clean two-column grid.  Back is forced to the
            # bottom by _ensure_admin_back_button().
            markup = types.InlineKeyboardMarkup(row_width=2)
            text_items = [
                ("Main Menu Text", "edit_txt_main_menu"),
                ("Store Menu Text", "edit_txt_store_menu"),
                ("🎬 How To Use Bot Text + Premium Emoji", "edit_txt_how_to_use"),
                ("💰 Add Balance Text + Premium Emoji", "edit_txt_top_up"),
                ("💠 Price List / Plans Text + Premium Emoji", "edit_txt_price_list"),
                ("Order Summary Text", "edit_txt_order_summary"),
                ("My Profile Text", "edit_txt_my_profile"),
                ("Order History Text", "edit_txt_order_history"),
                ("Referral Program Text", "edit_txt_referral_program"),
                ("Help Desk Text", "edit_txt_help_desk"),
                ("Payment Expired Text", "edit_txt_payment_expired"),
                ("👋 Verification / First Start Text", "edit_txt_verification_required"),
                ("👋 Welcome Message Text + Premium Emoji", "edit_txt_welcome_message"),
                ("📱 Phone Verified Text", "edit_txt_phone_verified"),
                ("🆕 New User Notification Text", "edit_txt_new_user_notification"),
                ("🛒 Purchase Notification Text", "edit_txt_purchase_notification"),
                ("⏳ Price Expiry Text", "edit_txt_price_expiry"),
                ("📲 QR Below Text + Premium Emoji", "edit_txt_qr_payment"),
                ("💳 Wallet Payment Text + Premium Emoji", "edit_txt_wallet_payment"),
                ("💰 Wallet Balance Success Text + Premium Emoji", "edit_txt_wallet_topup_success"),
                ("🇮🇳 UPI Payment Text + Premium Emoji", "edit_txt_upi_payment"),
                ("💰 Add Balance Text + Premium Emoji", "edit_txt_add_balance"),
                ("💳 Add Balance QR Text + Premium Emoji", "edit_txt_add_balance_qr"),
                ("👑 Reseller Discount Activation Text + Premium Emoji", "edit_txt_reseller_activation"),
                ("🎟️ Coupon Payment Success Text + Premium Emoji", "edit_txt_coupon_success"),
                ("❌ Coupon Payment Failed Text + Premium Emoji", "edit_txt_coupon_failed"),
            ]
            for i in range(0, len(text_items), 2):
                row = [
                    types.InlineKeyboardButton(label, callback_data=cdata)
                    for label, cdata in text_items[i:i + 2]
                ]
                markup.row(*row)
            _admin_ui_send(
                call,
                "✏️ <b>Select Text Section to Edit (Text ID):</b>",
                parse_mode="HTML",
                reply_markup=_ensure_admin_back_button(markup),
            )

    elif call.data.startswith("edit_txt_"):
        if _is_admin(user_id):
            t_key = call.data.replace("edit_txt_", "")
            if t_key == "add_balance":
                t_key = "top_up"
            elif t_key == "add_balance_qr":
                t_key = "top_up_qr"
            if t_key == "welcome_message":
                current_welcome=get_welcome_message_template()
                msg=_admin_ui_send(call,"👋 <b>WELCOME MESSAGE TEXT + PREMIUM EMOJI</b>\n\nSend the complete Welcome Message. Premium custom emojis are supported.\n\nLive placeholders: <code>{name}</code>, <code>{username}</code>, <code>{user_id}</code>, <code>{telegram_id}</code>, <code>{date}</code>.\n\n📌 <b>Current design:</b>\n"+current_welcome[:3000],parse_mode="HTML")
                bot.register_next_step_handler(msg,step_save_welcome_message); return
            if t_key == "price_expiry":
                msg = _admin_ui_send(call, "⏳ Send one Premium custom emoji now for Price List expiry. This replaces the current expiry emoji.", parse_mode="HTML")
                admin_temp_data[user_id] = {'emoji_target': 'price_expiry'}
                bot.register_next_step_handler(msg, step_save_premium_emoji)
            else:
                admin_temp_data[user_id] = {'text_key': t_key}
                if t_key == "reseller_activation":
                    current = _reseller_discount_activation_template()
                    prompt=("👑 <b>RESELLER DISCOUNT ACTIVATION TEXT + PREMIUM EMOJI</b>\n\nSend the complete QR/payment text you want users to see. Premium custom emojis are supported.\n\nLive placeholders: <code>{amount}</code>, <code>{user}</code> / <code>{name}</code>, <code>{order_id}</code>.\n\n📌 <b>Current design:</b>\n" + current[:3000])
                    msg=_admin_ui_send(call,prompt,parse_mode="HTML")
                    bot.register_next_step_handler(msg,step_save_custom_text)
                    return
                if t_key == "coupon_success":
                    current=_coupon_success_template()
                    prompt=("🎟️ <b>COUPON PAYMENT SUCCESS TEXT + PREMIUM EMOJI</b>\n\nSend the complete success message. Premium custom emojis are supported.\n\nLive placeholders: <code>{product_name}</code>, <code>{plan}</code>, <code>{amount}</code>, <code>{key}</code>.\n\n📌 <b>Current design:</b>\n" + current[:3000])
                    msg=_admin_ui_send(call,prompt,parse_mode="HTML")
                    bot.register_next_step_handler(msg,step_save_custom_text)
                    return
                if t_key == "coupon_failed":
                    current=_coupon_failed_template()
                    prompt=("❌ <b>COUPON PAYMENT FAILED TEXT + PREMIUM EMOJI</b>\n\nSend the complete failed-payment message. Premium custom emojis are supported.\n\nLive placeholder: <code>{reason}</code>.\n\n📌 <b>Current design:</b>\n" + current[:3000])
                    msg=_admin_ui_send(call,prompt,parse_mode="HTML")
                    bot.register_next_step_handler(msg,step_save_custom_text)
                    return
                if t_key == "wallet_topup_success":
                    current_wallet_success = get_wallet_topup_success_emoji_template()
                    prompt = (
                        "💰 <b>WALLET BALANCE SUCCESS TEXT + PREMIUM EMOJI</b>\n\n"
                        "Send the complete Wallet Balance Added Successfully message/layout you want users to see after an Add Balance payment is verified.\n\n"
                        "✨ Premium custom emojis are supported and their exact positions will be preserved.\n"
                        "🤖 Live placeholders:\n"
                        "• <code>{name}</code> / <code>{username}</code> → current user's name/username\n"
                        "• <code>{user_id}</code> / <code>{telegram_id}</code> → current Telegram ID\n"
                        "• <code>{order_id}</code> → current payment Order ID\n"
                        "• <code>{amount}</code> / <code>{add_amount}</code> / <code>{topup_amount}</code> → actual amount added\n"
                        "• <code>{utr}</code> → verified payment UTR\n"
                        "• <code>{balance}</code> / <code>{current_balance}</code> → wallet balance after credit\n\n"
                        "🔒 Old sample values are automatically replaced when labels are present.\n\n"
                        "📌 <b>Current design:</b>\n" + current_wallet_success[:3000]
                    )
                    msg = _admin_ui_send(call, prompt, parse_mode="HTML")
                    bot.register_next_step_handler(msg, step_save_wallet_topup_success_template)
                    return
                if t_key == "wallet_payment":
                    prompt = (
                        "💳 <b>WALLET PAYMENT TEXT + PREMIUM EMOJI</b>\n\n"
                        "Send the complete Wallet Payment Successful message/layout you want users to see, "
                        "with your Premium custom emojis placed exactly where you want them.\n\n"
                        "✨ This design is saved <b>separately from UPI</b>.\n"
                        "🤖 User ID, Order ID, Product ID, Product, Plan, Paid Amount, Date and Key "
                        "are always injected live for the current buyer.\n"
                        "💳 Method automatically shows <b>Wallet Method</b>.\n"
                        "🔑 Keep the key in <code>&lt;code&gt;</code> (or use the {key} placeholder) so it stays copyable."
                    )
                    msg = _admin_ui_send(call, prompt, parse_mode="HTML")
                    bot.register_next_step_handler(msg, step_save_wallet_payment_template)
                    return
                if t_key == "upi_payment":
                    prompt = (
                        "🇮🇳 <b>UPI PAYMENT TEXT + PREMIUM EMOJI</b>\n\n"
                        "Send the complete UPI Payment Successful message/layout you want users to see, "
                        "with your Premium custom emojis placed exactly where you want them.\n\n"
                        "✨ This design is saved <b>separately from Wallet</b>, so editing UPI will never change the Wallet design.\n"
                        "🤖 User ID, Order ID, Product ID, Product, Plan, Paid Amount, Date and Key "
                        "are always injected live for the current buyer.\n"
                        "🇮🇳 Method automatically shows <b>UPI Method</b>.\n"
                        "🔑 Keep the key in <code>&lt;code&gt;</code> (or use the {key} placeholder) so it stays copyable.\n"
                        "💡 You can copy the same layout style as your Wallet screenshot and replace the Premium emojis/text as you like."
                    )
                    msg = _admin_ui_send(call, prompt, parse_mode="HTML")
                    bot.register_next_step_handler(msg, step_save_upi_payment_template)
                    return
                if t_key == "qr_payment":
                    prompt = (
                        "📲 <b>QR BELOW TEXT + PREMIUM EMOJI</b>\n\n"
                        "Send the exact text/design you want directly below the QR image. "
                        "Premium custom emojis are supported and their positions will be preserved.\n\n"
                        "Optional live placeholders: "
                        "<code>{hack}</code> / <code>{product_name}</code>, "
                        "<code>{plan}</code>, <code>{amount}</code>, "
                        "<code>{order_id}</code>, <code>{date}</code> / <code>{purchase_date}</code>.\n\n"
                        "The bot will still show a separate live Order Details section below this text, "
                        "so every user's hack name, plan, price, purchase date and unique Order ID stay correct."
                    )
                    msg = _admin_ui_send(call, prompt, parse_mode="HTML")
                else:
                    if t_key == "top_up":
                        prompt = (
                            "💰 <b>ADD BALANCE TEXT + PREMIUM EMOJI</b>\n\n"
                            "Send the complete Add Balance screen design with your Premium custom emoji(s). "
                            "The old Add Balance layout is no longer used.\n\n"
                            "Live placeholders: <code>{balance}</code> for the current user's balance and "
                            "<code>{amount}</code>, <code>{add_amount}</code> or <code>{topup_amount}</code> for the keypad amount.\n\n"
                            "The bot automatically keeps Minimum Deposit at ₹1 and Maximum Deposit at ₹10,000. "
                            "When a user enters digits, the amount updates for that user only. Confirm opens the live QR payment screen."
                        )
                        msg = _admin_ui_send(call, prompt, parse_mode="HTML")
                    elif t_key == "top_up_qr":
                        current_qr = get_add_balance_qr_text_template()
                        prompt = (
                            "💳 <b>ADD BALANCE QR TEXT + PREMIUM EMOJI</b>\n\n"
                            "Send the complete Premium design you want to appear directly below the Add Balance QR image. "
                            "Use the same clean style as your product purchase QR/payment screen.\n\n"
                            "✨ Premium custom emojis are supported and their exact positions are preserved.\n\n"
                            "<b>Live placeholders:</b>\n"
                            "• <code>{amount}</code> / <code>{add_amount}</code> / <code>{topup_amount}</code> → live Add Amount\n"
                            "• <code>{order_id}</code> → live gateway Order ID\n"
                            "• <code>{date}</code> / <code>{purchase_date}</code> → current date/time\n\n"
                            "🔒 Amount and Order ID are always replaced live, even if you paste an old sample.\n\n"
                            "📌 <b>Current design:</b>\n" + current_qr[:3000]
                        )
                        msg = _admin_ui_send(call, prompt, parse_mode="HTML")
                        current_text = get_setting("custom_text_how_to_use") or ""
                        prompt = (
                            "🎬 <b>HOW TO USE BOT TEXT + PREMIUM EMOJI</b>\n\n"
                            "Send the complete text/design you want users to see on the How To Use Bot screen.\n\n"
                            "✨ Telegram Premium custom emojis are supported. Send the formatted message containing the Premium emoji(s), and their exact positions will be preserved.\n\n"
                            "The existing <b>Watch Guide Video</b> button and guide URL are kept separately and are NOT removed or changed by this editor.\n\n"
                            + ("📌 <b>Current saved text:</b>\n" + current_text[:2500] if current_text else "📌 <b>No custom text saved yet.</b> The bot will use the default How To Use text until you save your own.")
                        )
                        msg = _admin_ui_send(call, prompt, parse_mode="HTML")
                    else:
                        msg = _admin_ui_send(call,
                            f"✏️ <b>Enter new HTML text for section '{t_key}':</b>\n\n"
                            + ("💠 <b>Price List Premium Mode is ON.</b> Your saved design will replace the old price-list text while live plans/prices/stock/discounts remain automatic.\n\n"
                               if t_key == "price_list" and get_price_list_premium_mode()
                               else "Premium custom emoji will be preserved.\n")
                            + "Dynamic placeholders are automatic and are different for every user. You can use: "
                            + "<code>{{user}}</code> / <code>{{name}}</code>, <code>{{user_id}}</code> / <code>{{telegram_id}}</code>, "
                            + "<code>{{phone}}</code> / <code>{{number}}</code>, <code>{{country}}</code>, <code>{{balance}}</code>, <code>{{date}}</code>, "
                            + "<code>{{hack}}</code> / <code>{{product_name}}</code>, <code>{{plan}}</code>, <code>{{amount}}</code>, "
                            + "<code>{{order_id}}</code>, <code>{{ref_link}}</code> / <code>{{invite_link}}</code>, "
                            + "<code>{{pricing_info}}</code> / <code>{{price_list}}</code> / <code>{{prices}}</code>, "
                            + "and <code>{{default_price_list}}</code>.\n\n"
                            + "For New User / Phone Verified texts, if you keep labels such as <b>Name:</b>, <b>User ID:</b> and <b>Phone Number:</b>, "
                            + "their live values will also be restored automatically even if you forget the placeholders.",
                            parse_mode="HTML"
                        )
                bot.register_next_step_handler(msg, step_save_custom_text)

    elif call.data == "admin_quick_setup":
        if _is_admin(user_id):
            msg_text = (
                f"⚡ <b>QUICK ADMIN SETUP</b>\n\n"
                f"Send setup details in this exact multi-line format:\n\n"
                f"<code>Product_ID | Hack Name\n"
                f"1 Hours | 1 Hours | User_Price | Reseller_Price\n"
                f"1 DaYs | 1 DaYs | User_Price | Reseller_Price</code>"
            )
            msg = _admin_ui_send(call, msg_text, parse_mode="HTML")
            bot.register_next_step_handler(msg, step_quick_setup)

    elif call.data == "admin_stock_mgmt":
        if _is_admin(user_id):
            products = get_unique_products()
            if not products:
                _admin_ui_send(call, "❌ No products found.")
                return
            markup = types.InlineKeyboardMarkup()
            for prod in products:
                markup.add(types.InlineKeyboardButton(f"🎮 {prod}", callback_data=f"stock_hack_{prod}"))
            _admin_ui_send(call, "📦 <b>SELECT HACK TO MANAGE STOCK STATUS:</b>", parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("stock_hack_"):
        if _is_admin(user_id):
            p_name = call.data.replace("stock_hack_", "")
            plans = get_product_plans(p_name)
            markup = types.InlineKeyboardMarkup()
            for plan in plans:
                p_id, _, p_days, _, _, _, _, _, _, is_oos, _ = plan
                status_str = "❌ Out of Stock" if is_oos else "✅ In Stock"
                markup.add(types.InlineKeyboardButton(f"{p_days} ({status_str})", callback_data=f"toggle_stock_{p_id}_{1 if is_oos==0 else 0}"))
            _admin_ui_send(call, f"🎮 <b>Hack: {p_name}</b>\nTap any plan to toggle Stock On/Off:", parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("toggle_stock_"):
        if _is_admin(user_id):
            parts = call.data.split("_")
            p_id = int(parts[2])
            new_status = int(parts[3])
            set_plan_stock_status(p_id, new_status)
            bot.answer_callback_query(call.id, f"Stock Status Updated to {'Out of Stock' if new_status==1 else 'In Stock'}!", show_alert=True)
            _admin_ui_send(call, "✅ Stock status updated successfully!")

    elif call.data == "admin_set_tg_group":
        if _is_admin(user_id):
            products = get_unique_products()
            if not products:
                _admin_ui_send(call, "❌ No products found.")
                return
            markup = types.InlineKeyboardMarkup()
            for prod in products:
                markup.add(types.InlineKeyboardButton(f"🎮 {prod}", callback_data=f"set_tg_hack_{prod}"))
            _admin_ui_send(call, "🔗 <b>SELECT HACK TO SET TELEGRAM GROUP LINK:</b>", parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("set_tg_hack_"):
        if _is_admin(user_id):
            p_name = call.data.replace("set_tg_hack_", "")
            admin_temp_data[user_id] = {'hack_name': p_name}
            msg = _admin_ui_send(call, f"🔗 <b>Paste Telegram Group Link for {p_name}:</b>", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_set_tg_group_link)

    elif call.data.startswith("pp_add_plan_same_"):
        if _is_admin(user_id):
            h = call.data.replace("pp_add_plan_same_", "", 1)
            product_name = _pp_resolve_product(user_id, h)
            if not product_name:
                _admin_ui_send(call, "❌ Hack list expired. Open Hacks &amp; Plans again.", parse_mode="HTML", reply_markup=_pp_catalog_markup(user_id)); return
            _pp_set_active_product(user_id, product_name)
            admin_temp_data[user_id] = {'name': product_name, 'pp_active_hack': product_name}
            msg = _admin_ui_send(call, f"➕ <b>ADD ANOTHER PLAN</b>\n\n🎮 Hack: <b>{html.escape(product_name)}</b>\n\n📅 Enter Day / Plan Duration:", parse_mode="HTML")
            admin_pending_return[user_id] = {"callback": f"pp_hack_{h}"}
            bot.register_next_step_handler(msg, step_add_hack_days)

    elif call.data == "pp_add_product":
        if _is_admin(user_id):
            msg = _admin_ui_send(call, "➕ <b>ADD PRODUCT / PLAN</b>\n\n📝 Enter Hack / Product Name:", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_add_hack_name)

    elif call.data == "pp_hacks":
        if _is_admin(user_id):
            products = get_unique_products()
            if not products:
                _admin_ui_send(call, "🎮 <b>HACKS &amp; PLANS</b>\n\n<i>No hacks have been added yet.</i>\n\nTap ➕ to create the first product.", parse_mode="HTML", reply_markup=_product_plans_dashboard_markup())
            else:
                _admin_ui_send(call, "🎮 <b>HACKS &amp; PLANS</b>\n━━━━━━━━━━━━━━━━━━━━\n<i>Select a hack to manage its plans, keys, link and position.</i>", parse_mode="HTML", reply_markup=_pp_catalog_markup(user_id))

    elif call.data.startswith("pp_hack_"):
        if _is_admin(user_id):
            h = call.data.replace("pp_hack_", "", 1)
            product_name = _pp_resolve_product(user_id, h)
            if not product_name:
                _admin_ui_send(call, "❌ Hack list expired. Open Hacks &amp; Plans again.", parse_mode="HTML", reply_markup=_pp_catalog_markup(user_id))
                return
            _pp_set_active_product(user_id, product_name)
            edit_h = _ui_hash(product_name)
            admin_temp_data.setdefault(user_id, {}).setdefault('edit_hack_catalog', {})[edit_h] = product_name
            admin_temp_data[user_id]['edit_hack_name'] = product_name
            plans = get_product_plans(product_name)
            lines = [f"🎮 <b>{html.escape(str(product_name))}</b>", "━━━━━━━━━━━━━━━━━━━━", f"📦 <b>{len(plans)} Plan(s)</b>", ""]
            for idx, plan in enumerate(plans, 1):
                lines.append(f"{idx}. 📅 <b>{html.escape(str(plan[2]))}</b>  ·  User ₹{plan[3]:.2f}  ·  Reseller ₹{plan[4]:.2f}")
            if not plans:
                lines.append("<i>No plans found.</i>")
            _admin_ui_send(call, "\n".join(lines), parse_mode="HTML", reply_markup=_pp_selected_hack_screen(user_id, product_name))

    elif call.data.startswith("pp_add_key_"):
        if _is_admin(user_id):
            h = call.data.replace("pp_add_key_", "", 1)
            product_name = _pp_resolve_product(user_id, h)
            if not product_name:
                _admin_ui_send(call, "❌ Hack list expired. Open Hacks &amp; Plans again.", parse_mode="HTML", reply_markup=_pp_catalog_markup(user_id)); return
            plans = get_product_plans(product_name)
            markup = types.InlineKeyboardMarkup(row_width=1)
            for plan in plans:
                markup.add(types.InlineKeyboardButton(f"📅 {plan[2]} · ₹{plan[3]:.2f} / ₹{plan[4]:.2f}", callback_data=f"man_key_plan_{plan[0]}"))
            _pp_set_active_product(user_id, product_name)
            admin_temp_data[user_id]['pp_active_hack'] = product_name
            _admin_ui_send(call, f"🔑 <b>ADD VIP KEY</b>\n\n🎮 Hack: <b>{html.escape(product_name)}</b>\nSelect the plan:", parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup))
            admin_pending_return[user_id] = {"callback": "pp_hack_direct", "product_name": product_name}

    elif call.data.startswith("pp_link_"):
        if _is_admin(user_id):
            h = call.data.replace("pp_link_", "", 1)
            product_name = _pp_resolve_product(user_id, h)
            if not product_name:
                _admin_ui_send(call, "❌ Hack list expired. Open Hacks &amp; Plans again.", parse_mode="HTML", reply_markup=_pp_catalog_markup(user_id)); return
            _pp_set_active_product(user_id, product_name)
            admin_temp_data[user_id] = {'hack_name': product_name, 'pp_active_hack': product_name}
            msg = _admin_ui_send(call, f"🔗 <b>TELEGRAM LINK</b>\n\n🎮 Hack: <b>{html.escape(product_name)}</b>\n\nPaste the channel/group link:", parse_mode="HTML")
            admin_pending_return[user_id] = {"callback": f"pp_hack_{h}"}
            bot.register_next_step_handler(msg, step_set_tg_group_link)

    elif call.data.startswith("pp_keys_"):
        if _is_admin(user_id):
            h = call.data.replace("pp_keys_", "", 1)
            product_name = _pp_resolve_product(user_id, h)
            if not product_name:
                _admin_ui_send(call, "❌ Hack list expired. Open Hacks &amp; Plans again.", parse_mode="HTML", reply_markup=_pp_catalog_markup(user_id)); return
            text, markup = _pp_key_stock_view(user_id, product_name, h)
            _admin_ui_send(call, text, parse_mode="HTML", reply_markup=markup)

    elif call.data.startswith("pp_key_delete_"):
        if _is_admin(user_id):
            raw = call.data.replace("pp_key_delete_", "", 1)
            try:
                panel_raw, h = raw.rsplit("_", 1)
                panel_id = int(panel_raw)
            except Exception:
                bot.answer_callback_query(call.id, "❌ Invalid key reference.", show_alert=True); return
            conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
            try:
                row = conn.execute(
                    'SELECT id,panel_name,validity_days,panel_key FROM panels WHERE id=? AND is_sold=0',
                    (panel_id,)
                ).fetchone()
                if not row:
                    bot.answer_callback_query(call.id, "Key not found or already sold.", show_alert=True); return
                conn.execute('DELETE FROM panels WHERE id=? AND is_sold=0', (panel_id,))
                conn.commit()
            finally:
                conn.close()
            product_name = row[1]
            admin_temp_data.setdefault(user_id, {}).setdefault('pp_hack_catalog', {})[h] = product_name
            bot.answer_callback_query(call.id, "✅ Key removed.")
            text, markup = _pp_key_stock_view(user_id, product_name, h, prefix_text=f"✅ <b>Removed:</b> Key #{panel_id}")
            _admin_ui_send(call, text, parse_mode="HTML", reply_markup=markup)

    elif call.data.startswith("pp_position_"):
        if _is_admin(user_id):
            h = call.data.replace("pp_position_", "", 1)
            product_name = _pp_resolve_product(user_id, h)
            if not product_name:
                _admin_ui_send(call, "❌ Hack list expired. Open Hacks &amp; Plans again.", parse_mode="HTML", reply_markup=_pp_catalog_markup(user_id)); return
            _pp_set_active_product(user_id, product_name)
            admin_temp_data[user_id] = {'pp_position_product': product_name}
            msg = _admin_ui_send(call, f"🔢 <b>SET HACK POSITION</b>\n\n🎮 <b>{html.escape(product_name)}</b>\n\nEnter position number: <code>1</code> = top, <code>2</code> = second, <code>3</code> = third…", parse_mode="HTML")
            admin_pending_return[user_id] = {"callback": f"pp_hack_{h}"}
            bot.register_next_step_handler(msg, step_set_hack_position)

    elif call.data.startswith("pp_custom_price_") and not call.data.startswith("pp_custom_price_plan_"):
        if _is_admin(user_id):
            h = call.data.replace("pp_custom_price_", "", 1)
            product_name = _pp_resolve_product(user_id, h)
            if not product_name:
                _admin_ui_send(call, "❌ Hack list expired. Open Hacks &amp; Plans again.", parse_mode="HTML", reply_markup=_pp_catalog_markup(user_id)); return
            _pp_set_active_product(user_id, product_name)
            admin_temp_data[user_id] = {"pp_custom_price_product": product_name, "pp_custom_price_hash": h}
            msg = _admin_ui_send(call, "💰 <b>CUSTOM PRICE</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🎮 <b>Product:</b> {html.escape(product_name)}\n\n"
                "Enter the Telegram User/Chat ID for the custom pricing:", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_custom_price_user_id)

    elif call.data.startswith("pp_custom_price_plan_"):
        if _is_admin(user_id):
            raw = call.data.replace("pp_custom_price_plan_", "", 1)
            try: plan_raw, h = raw.rsplit("_", 1); plan_id = int(plan_raw)
            except Exception:
                bot.answer_callback_query(call.id, "❌ Invalid plan reference.", show_alert=True); return
            data = admin_temp_data.setdefault(user_id, {})
            target = data.get("pp_custom_price_target"); product_name = data.get("pp_custom_price_product")
            if not target or not product_name:
                _admin_ui_send(call, "❌ Custom Price session expired. Open Custom Price again.", parse_mode="HTML"); return
            plan = get_product_by_id(plan_id)
            if not plan or str(plan[1]) != str(product_name):
                bot.answer_callback_query(call.id, "❌ Plan not found for this product.", show_alert=True); return
            data["pp_custom_price_plan_id"] = plan_id
            custom = get_custom_plan_price(target, plan_id)
            cur_u = "-" if custom["user_price"] is None else f"{custom['user_price']:.2f}"
            cur_r = "-" if custom["reseller_price"] is None else f"{custom['reseller_price']:.2f}"
            msg = _admin_ui_send(call, "💰 <b>SET CUSTOM PLAN PRICE</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🎮 <b>Product:</b> {html.escape(product_name)}\n"
                f"📅 <b>Plan:</b> {html.escape(str(plan[3]))}\n"
                f"👤 <b>User ID:</b> <code>{target}</code>\n\n"
                f"Current: <code>{cur_u} | {cur_r}</code>\n\n"
                "Send <code>User_Price | Reseller_Price</code>\nExample: <code>500 | 350</code>\nUse <code>-</code> to clear an override.", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_save_custom_plan_price)

    elif call.data.startswith("pp_key_edit_"):
        if _is_admin(user_id):
            raw = call.data.replace("pp_key_edit_", "", 1)
            try: panel_raw, h = raw.rsplit("_", 1); panel_id = int(panel_raw)
            except Exception:
                bot.answer_callback_query(call.id, "❌ Invalid key reference.", show_alert=True); return
            conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
            try: row = conn.execute("SELECT id,panel_name,validity_days,panel_key FROM panels WHERE id=? AND is_sold=0", (panel_id,)).fetchone()
            finally: conn.close()
            if not row:
                bot.answer_callback_query(call.id, "❌ Key not found or already sold.", show_alert=True); return
            admin_temp_data[user_id] = {"pp_edit_key_id": panel_id, "pp_edit_key_hash": h, "pp_edit_key_product": row[1], "pp_edit_key_days": row[2]}
            msg = _admin_ui_send(call, "✏️ <b>EDIT VIP KEY</b>\n\n"
                f"🎮 <b>Product:</b> {html.escape(str(row[1]))}\n"
                f"📅 <b>Plan:</b> {html.escape(str(row[2]))}\n"
                f"🔑 <b>Current:</b> <code>{html.escape(str(row[3]), quote=False)}</code>\n\n"
                "Send the corrected key:", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_edit_manual_key)

    elif call.data == "pp_advanced":
        if _is_admin(user_id):
            _admin_ui_send(call, "🧰 <b>ADVANCED PRODUCT TOOLS</b>\n━━━━━━━━━━━━━━━━━━━━\n<i>All legacy product controls remain available here.</i>", parse_mode="HTML", reply_markup=_pp_advanced_markup())

    elif call.data.startswith("pp_more_"):
        if _is_admin(user_id):
            h = call.data.replace("pp_more_", "", 1)
            product_name = _pp_resolve_product(user_id, h)
            if not product_name:
                _admin_ui_send(call, "❌ Hack list expired. Open Hacks &amp; Plans again.", parse_mode="HTML", reply_markup=_pp_catalog_markup(user_id)); return
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.row(
                types.InlineKeyboardButton("🗑 Remove Hack", callback_data="admin_del_hack"),
                types.InlineKeyboardButton("❌ Remove Plan", callback_data="admin_del_plan"),
            )
            markup.row(
                types.InlineKeyboardButton("📦 Stock", callback_data="admin_stock_mgmt"),
                types.InlineKeyboardButton("📱 Device ID", callback_data="admin_device_id_mgmt"),
            )
            markup.row(
                types.InlineKeyboardButton("💰 Edit Prices", callback_data="admin_edit_price"),
                types.InlineKeyboardButton("🔄 Reorder", callback_data="admin_reorder_hacks"),
            )
            markup.add(types.InlineKeyboardButton("🎮 Back to Hack", callback_data=f"pp_hack_{h}"))
            _admin_ui_send(call, f"🧰 <b>MORE TOOLS</b>\n\n🎮 Selected: <b>{html.escape(product_name)}</b>", parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("pp_plan_noop_"):
        if _is_admin(user_id):
            bot.answer_callback_query(call.id, "Plan details shown above.")

    elif call.data == "admin_hack_day_mgmt":
        if _is_admin(user_id):
            markup = types.InlineKeyboardMarkup()
            btn_add_hack = types.InlineKeyboardButton("➕ Add New Hack & Day Plan", callback_data="admin_add_hack_plan")
            btn_add_day = types.InlineKeyboardButton("📅 Add Day to Existing Hack", callback_data="admin_add_day_exist")
            btn_del_hack = types.InlineKeyboardButton("🗑️ Remove Entire Hack", callback_data="admin_del_hack")
            btn_del_plan = types.InlineKeyboardButton("❌ Remove Day / Plan", callback_data="admin_del_plan")
            btn_edit_hack = types.InlineKeyboardButton("✏️ Edit Existing Hack / Price / Plan", callback_data="admin_edit_hack_inside")
            markup.add(btn_add_hack, btn_add_day)
            markup.add(btn_edit_hack)
            markup.add(btn_del_hack, btn_del_plan)
            _admin_ui_send(call, "⚙️ <b>HACK & DAY MANAGEMENT PANEL</b>\n\nSelect action:", parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup))

    elif call.data == "admin_add_hack_plan":
        if _is_admin(user_id):
            msg = _admin_ui_send(call, "📝 <b>Enter Hack / Product Name:</b>", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_add_hack_name)

    elif call.data == "admin_add_day_exist":
        if _is_admin(user_id):
            products = get_unique_products()
            if not products:
                _admin_ui_send(call, "❌ No products found.", parse_mode="HTML")
                return
            markup = types.InlineKeyboardMarkup()
            for prod in products:
                markup.add(types.InlineKeyboardButton(f"🎮 {prod}", callback_data=f"sel_hack_add_day_{prod}"))
            _admin_ui_send(call, "🎮 <b>SELECT HACK TO ADD NEW DAY/PLAN:</b>", parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("sel_hack_add_day_"):
        if _is_admin(user_id):
            p_name = call.data.replace("sel_hack_add_day_", "")
            admin_temp_data[user_id] = {'name': p_name}
            msg = _admin_ui_send(call, f"📅 <b>Enter New Duration/Day Name for {p_name}</b> (e.g., <code>1 Hours</code>, <code>1 DaYs</code>):", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_get_add_day_to_hack)

    elif call.data == "admin_hack_server_manager":
        if _is_admin(user_id):
            if not get_unique_products(): _admin_ui_send(call,"❌ No hacks/products found."); return
            _admin_ui_send(call,"⚙️ <b>HACK API & SERVER MANAGER</b>\n\nSelect a hack. Its API/Server/Product ID and plan-by-plan Valid IDs are saved separately.",parse_mode="HTML",reply_markup=_server_manager_hacks_markup())
    elif call.data.startswith("hack_server_select_"):
        if _is_admin(user_id):
            p_name=call.data.replace("hack_server_select_","",1)
            if p_name not in get_unique_products(): return
            admin_temp_data[user_id]={'hack_server_product':p_name}; msg=_admin_ui_send(call,f"🎮 <b>Selected Hack:</b> {html.escape(p_name)}\n\n🔑 <b>Enter API Key:</b>",parse_mode="HTML"); bot.register_next_step_handler(msg,step_save_hack_server_api_key)

    elif call.data == "admin_server_api_mgmt":
        if _is_admin(user_id):
            msg = _admin_ui_send(call, "🔑 <b>Enter Server API Token Key:</b>", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_get_server_token)

    elif call.data == "test_server_api_conn":
        if _is_admin(user_id):
            curr_url = get_setting('server_api_url') or RESELLER_API_URL
            curr_key = get_setting('server_api_key') or RESELLER_API_KEY
            try:
                res = HTTP_SESSION.post(curr_url, data={'api_key': curr_key, 'action': 'balance'}, timeout=8)
                if res.status_code == 200:
                    set_setting('legacy_server_connected', '1')
                    _admin_ui_send(call, "✅ <b>Connect Successfully!</b>\n\nServer API connected & active.", parse_mode="HTML")
                else:
                    set_setting('legacy_server_connected', '0')
                    _admin_ui_send(call, "❌ <b>Not Connect</b>\n\nServer returned an invalid response status.", parse_mode="HTML")
            except Exception as e:
                set_setting('legacy_server_connected', '0')
                _admin_ui_send(call, f"❌ <b>Not Connect</b>\n\nError: {e}", parse_mode="HTML")

    elif call.data == "admin_map_server_id":
        if _is_admin(user_id):
            products = get_unique_products()
            if not products:
                _admin_ui_send(call, "❌ No products found.", parse_mode="HTML")
                return
            markup = types.InlineKeyboardMarkup()
            for prod in products:
                markup.add(types.InlineKeyboardButton(f"🎮 {prod}", callback_data=f"map_sel_hack_{prod}"))
            _admin_ui_send(call, "🔗 <b>SELECT HACK TO MAP SERVER PRODUCT ID & DURATION:</b>", parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("map_sel_hack_"):
        if _is_admin(user_id):
            p_name = call.data.replace("map_sel_hack_", "")
            plans = get_product_plans(p_name)
            if not plans:
                _admin_ui_send(call, "❌ No plans found.", parse_mode="HTML")
                return
            markup = types.InlineKeyboardMarkup()
            for plan in plans:
                markup.add(types.InlineKeyboardButton(f"⏱️ {plan[2]} Plan", callback_data=f"map_plan_id_{plan[0]}"))
            _admin_ui_send(call, f"🎮 <b>Selected Hack: {p_name}</b>\nSelect Plan to Map Server API Details:", parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("map_plan_id_"):
        if _is_admin(user_id):
            plan_id = int(call.data.replace("map_plan_id_", ""))
            admin_temp_data[user_id] = {'plan_id': plan_id}
            msg = _admin_ui_send(call, "🆔 <b>Enter Server Remote Product ID (PID):</b> (e.g., <code>133</code>)", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_get_remote_pid)

    elif call.data == "admin_change_bot_token":
        if _is_admin(user_id):
            msg = _admin_ui_send(call, "🔑 <b>Enter New Telegram Bot API Token:</b>", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_get_new_bot_token)

    elif call.data == 'resapi_admin':
        if _is_admin(user_id): _send_resapi_admin(call)
    elif call.data == 'resapi_set_link':
        if _is_admin(user_id):
            msg=_admin_ui_send(call,f"🌐 <b>Enter the public Reseller API Link:</b>\n\nYou can use your existing bot-hosting URL directly, or add a custom path such as <code>/reseller</code>. No separate domain is required.\n\nCurrent: <code>{html.escape(_reseller_api_public_link())}</code>",parse_mode='HTML')
            def _save_resapi_link_step(m):
                try:
                    saved_link = _save_reseller_api_public_link(m.text)
                    set_setting('reseller_api_public_url', saved_link)
                    bot.send_message(m.chat.id, f'✅ <b>Public API Link Saved.</b>\n\n🌐 <code>{html.escape(saved_link)}</code>', parse_mode='HTML', reply_markup=_resapi_admin_markup())
                except Exception as exc:
                    bot.send_message(m.chat.id, f'❌ <b>Invalid Public API Link:</b> {html.escape(str(exc)[:300])}', parse_mode='HTML', reply_markup=_resapi_admin_markup())
            bot.register_next_step_handler(msg,_save_resapi_link_step)
    elif call.data == 'resapi_generate':
        if _is_admin(user_id):
            msg=_admin_ui_send(call,'👤 <b>Enter Reseller Telegram ID:</b>',parse_mode='HTML')
            def _save_resapi_uid(m):
                try:
                    uid=int(str(m.text).strip()); u=get_user(uid)
                    if not u:
                        bot.send_message(m.chat.id,'❌ User not found.')
                        return
                    if len(u) < 12 or int(u[11] or 0) != 1:
                        bot.send_message(m.chat.id,'❌ This user is not a Reseller. Add the Reseller role first.')
                        return
                    link=_reseller_api_public_link()
                    if not link:
                        bot.send_message(m.chat.id,'❌ Public API Server Link is not configured. Set it first from Reseller API System.')
                        return
                    token=_create_or_rotate_reseller_api_token(uid)
                    _send_long_html_message(uid,_reseller_api_credentials_text(uid))
                    bot.send_message(m.chat.id,'✅ <b>Reseller API generated and sent.</b>\n\n🔑 Token + Server Link + Product IDs + Validity IDs were sent to the reseller.',parse_mode='HTML')
                except Exception as exc:
                    bot.send_message(m.chat.id,'❌ '+html.escape(str(exc)[:500]))
            bot.register_next_step_handler(msg,_save_resapi_uid)
    elif call.data.startswith('resapi_generate_for_'):
        if _is_admin(user_id):
            try:
                uid=int(call.data.replace('resapi_generate_for_','',1))
            except Exception:
                bot.answer_callback_query(call.id,'❌ Invalid reseller ID.',show_alert=True)
                return
            u=get_user(uid)
            if not u or len(u) < 12 or int(u[11] or 0) != 1:
                bot.answer_callback_query(call.id,'❌ User is not an active reseller.',show_alert=True)
                return
            link=_reseller_api_public_link()
            if not link:
                _admin_ui_send(call,'❌ <b>Public API Server Link is not configured.</b>\n\nOpen <b>Reseller API System</b> and set the public HTTPS server link first.',parse_mode='HTML',reply_markup=_resapi_admin_markup())
                return
            try:
                _create_or_rotate_reseller_api_token(uid)
                _send_long_html_message(uid,_reseller_api_credentials_text(uid))
                _admin_ui_send(call,f'✅ <b>Reseller API generated and sent.</b>\n\n👤 Reseller: <b>{html.escape(str(u[1] or uid),quote=False)}</b>\n🆔 <code>{uid}</code>',parse_mode='HTML',reply_markup=_reseller_profile_back_markup(uid))
            except Exception as exc:
                _admin_ui_send(call,'❌ '+html.escape(str(exc)[:500]),parse_mode='HTML',reply_markup=_reseller_profile_back_markup(uid))
    elif call.data == 'admin_reseller_discount':
        if _is_admin(user_id): _send_reseller_discount_admin(call)
    elif call.data == 'rd_toggle':
        if _is_admin(user_id):
            new='0' if _reseller_discount_active() else '1'; set_setting('reseller_discount_enabled',new)
            if new=='1':
                try: set_setting('reseller_discount_expires_at',str(time.time()+float(get_setting('reseller_discount_duration_hours') or 24)*3600))
                except Exception: pass
            _send_reseller_discount_admin(call)
    elif call.data == 'rd_amount':
        if _is_admin(user_id):
            msg=_admin_ui_send(call,'💰 <b>Enter Reseller Activation Amount (₹):</b>',parse_mode='HTML')
            def _rd_amount(m):
                try: val=float(m.text); assert val>0; set_setting('reseller_discount_amount',str(val)); bot.send_message(m.chat.id,'✅ Activation amount saved.',reply_markup=_reseller_discount_admin_markup())
                except Exception: bot.send_message(m.chat.id,'❌ Invalid amount.')
            bot.register_next_step_handler(msg,_rd_amount)
    elif call.data == 'rd_duration':
        if _is_admin(user_id):
            msg=_admin_ui_send(call,'⏱️ <b>Enter ON duration in hours:</b>',parse_mode='HTML')
            def _rd_duration(m):
                try: val=float(m.text); assert val>0; set_setting('reseller_discount_duration_hours',str(val)); bot.send_message(m.chat.id,'✅ Duration saved.',reply_markup=_reseller_discount_admin_markup())
                except Exception: bot.send_message(m.chat.id,'❌ Invalid duration.')
            bot.register_next_step_handler(msg,_rd_duration)
    elif call.data == 'rd_text':
        if _is_admin(user_id):
            msg=_admin_ui_send(call,'✏️ <b>Send the new Reseller Discount button text:</b>',parse_mode='HTML'); bot.register_next_step_handler(msg,lambda m:(set_setting('custom_btn_reseller_discount',str(m.text or '👑 Reseller Discount')),bot.send_message(m.chat.id,'✅ Button text saved.',reply_markup=_reseller_discount_admin_markup())))
    elif call.data == 'rd_emoji':
        if _is_admin(user_id):
            msg=_admin_ui_send(call,'✨ <b>Button Premium Emoji</b>\n\nSend exactly one Telegram Premium custom emoji now. It will be saved to the Reseller Discount button and remain active until you replace it.',parse_mode='HTML')
            admin_temp_data[user_id]={'emoji_target':'main:reseller_discount'}
            bot.register_next_step_handler(msg, step_save_premium_emoji)
    elif call.data == 'rd_payment_text':
        if _is_admin(user_id):
            admin_temp_data[user_id]={'text_key':'reseller_activation'}
            current=_reseller_discount_activation_template()
            prompt=('📝 <b>RESELLER DISCOUNT ACTIVATION TEXT + PREMIUM EMOJI</b>\n\nSend the complete QR/payment text you want below the QR. Premium custom emojis are supported.\n\nLive placeholders: <code>{amount}</code>, <code>{user}</code> / <code>{name}</code>, <code>{order_id}</code>.\n\n📌 <b>Current design:</b>\n'+current[:3000])
            msg=_admin_ui_send(call,prompt,parse_mode='HTML')
            bot.register_next_step_handler(msg, step_save_custom_text)
    elif call.data == 'rd_payment_emoji':
        if _is_admin(user_id):
            msg=_admin_ui_send(call,'✨ <b>Activation Premium Emoji</b>\n\nSend the complete activation text containing the Premium custom emoji(s). The text and emoji positions will be saved together.',parse_mode='HTML')
            admin_temp_data[user_id]={'text_key':'reseller_activation'}
            bot.register_next_step_handler(msg, step_save_custom_text)
    elif call.data == 'rd_color':
        if _is_admin(user_id):
            markup=types.InlineKeyboardMarkup(); key='main:reseller_discount'
            for c in ('red','green','blue'): markup.add(types.InlineKeyboardButton(c.upper(),callback_data=f'rd_color_{c}'))
            _ensure_admin_back_button(markup); _admin_ui_send(call,'🎨 <b>Select Reseller Discount button color:</b>',parse_mode='HTML',reply_markup=markup)
    elif call.data.startswith('rd_color_'):
        if _is_admin(user_id): set_button_style('main:reseller_discount',call.data.replace('rd_color_','',1)); _send_reseller_discount_admin(call)
    elif call.data == 'admin_create_coupon':
        if _is_admin(user_id): _send_coupon_admin(call)
    elif call.data == 'coupon_admin_create':
        if _is_admin(user_id):
            msg=_admin_ui_send(call,'💰 <b>Enter the full coupon value in INR:</b>\n\nExample: <code>350</code>',parse_mode='HTML')
            def _coupon_amount(m):
                try:
                    code=_create_coupon(float(m.text),user_id)
                    if not code: raise ValueError('Could not generate unique code')
                    back_markup=types.InlineKeyboardMarkup(row_width=2)
                    back_markup.row(
                        types.InlineKeyboardButton('🎟️ Coupon Management',callback_data='admin_create_coupon'),
                        types.InlineKeyboardButton('🔙 Users & Resellers',callback_data='admin_cat_users')
                    )
                    bot.send_message(m.chat.id,f'✅ <b>Coupon Created</b>\n\n💰 Amount: <b>₹{float(m.text):.2f} INR</b>\n🎟️ Code: <code>{code}</code>',parse_mode='HTML',reply_markup=back_markup)
                except Exception as exc:
                    err_markup=types.InlineKeyboardMarkup(row_width=1)
                    err_markup.add(types.InlineKeyboardButton('🔙 Users & Resellers',callback_data='admin_cat_users'))
                    bot.send_message(m.chat.id,'❌ <b>Coupon Creation Failed</b>\n\n'+html.escape(str(exc)[:300]),parse_mode='HTML',reply_markup=err_markup)
            bot.register_next_step_handler(msg,_coupon_amount)
    elif call.data == 'coupon_admin_list':
        if _is_admin(user_id):
            conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15); rows=conn.execute('SELECT code,amount,created_at,used_by,active FROM coupons ORDER BY created_at DESC LIMIT 50').fetchall(); conn.close()
            text='🎟️ <b>ACTIVE COUPONS</b>\n\n'+('\n'.join([f'<code>{r[0]}</code> — ₹{float(r[1]):.2f} — '+('🟢 Active' if r[4] else '🔴 Used') for r in rows]) or '<i>No coupons.</i>')
            m=types.InlineKeyboardMarkup(); _ensure_admin_back_button(m); _admin_ui_send(call,text,parse_mode='HTML',reply_markup=m)

    elif call.data == "admin_manage_reseller":
        if _is_admin(user_id):
            msg = _admin_ui_send(call, "👤 <b>Enter Telegram User ID to Add/Remove Reseller:</b>", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_get_reseller_uid)

    elif call.data.startswith("set_resell_"):
        if _is_admin(user_id):
            parts = call.data.split("_")
            status = int(parts[2])
            target_uid = int(parts[3])
            
            set_reseller_status(target_uid, status)
            # A revoked reseller role must immediately invalidate API access.
            # Promotion keeps any existing token intact so the reseller can
            # continue using the API after a temporary role change.
            if status != 1:
                try:
                    conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
                    conn.execute('UPDATE reseller_api_credentials SET enabled=0, updated_at=? WHERE user_id=?', (_now_ist_text(), int(target_uid)))
                    conn.commit()
                    conn.close()
                except Exception as exc:
                    print(f'[RESELLER API DISABLE ERROR] {target_uid}: {exc}')
            role_title = "Reseller ⭐" if status == 1 else "Standard User 👤"
            result_markup = types.InlineKeyboardMarkup(row_width=2)
            result_markup.row(
                types.InlineKeyboardButton("👑 Reseller List", callback_data="admin_reseller_list"),
                types.InlineKeyboardButton("🔎 Search", callback_data="admin_user_reseller_search")
            )
            result_markup.add(types.InlineKeyboardButton("🔙 Users & Resellers", callback_data="admin_cat_users"))
            _admin_ui_send(call, f"✅ <b>Role Updated!</b>\n\nUser <code>{target_uid}</code> is now a <b>{role_title}</b>.", parse_mode="HTML", reply_markup=result_markup)
            
            try:
                if status == 1:
                    bot.send_message(target_uid, "🎉 <b>Congratulations!</b> You have been promoted to <b>Reseller</b>!\n💎 Reseller discounted prices are now unlocked for you in the shop.", parse_mode="HTML")
                else:
                    bot.send_message(target_uid, "ℹ️ Your Reseller status has been reset to Standard User.", parse_mode="HTML")
            except Exception:
                pass

    elif call.data == "admin_add_manual_key":
        if _is_admin(user_id):
            products = get_unique_products()
            if not products:
                _admin_ui_send(call, "❌ No products found.", parse_mode="HTML")
                return
            markup = types.InlineKeyboardMarkup()
            for prod in products:
                markup.add(types.InlineKeyboardButton(f"🎮 {prod}", callback_data=f"man_key_hack_{prod}"))
            _admin_ui_send(call, "🔑 <b>SELECT HACK TO ADD MANUAL VIP KEY:</b>", parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("man_key_hack_"):
        if _is_admin(user_id):
            p_name = call.data.replace("man_key_hack_", "")
            plans = get_product_plans(p_name)
            markup = types.InlineKeyboardMarkup()
            for plan in plans:
                markup.add(types.InlineKeyboardButton(f"⏱️ {plan[2]} Plan", callback_data=f"man_key_plan_{plan[0]}"))
            _admin_ui_send(call, f"🎮 <b>Selected: {p_name}</b>\nSelect Plan:", parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("man_key_plan_"):
        if _is_admin(user_id):
            p_id = int(call.data.replace("man_key_plan_", ""))
            prod = get_product_by_id(p_id)
            if prod:
                active_hack = _pp_active_product(user_id) or admin_temp_data.get(user_id, {}).get('pp_active_hack') or str(prod[1])
                _pp_set_active_product(user_id, active_hack)
                admin_temp_data[user_id] = {'p_name': prod[1], 'days': prod[3], 'pp_active_hack': active_hack}
                msg = _admin_ui_send(call, f"🔑 <b>Paste/Send VIP Key for {prod[1]} ({prod[3]}):</b>", parse_mode="HTML")
                
                def save_key_step(msg):
                    raw_keys = (msg.text or "").strip()
                    count = add_keys_db_bulk(
                        admin_temp_data[user_id]['p_name'],
                        admin_temp_data[user_id]['days'],
                        raw_keys
                    )
                    if not count:
                        retry = bot.send_message(
                            msg.chat.id,
                            "❌ No valid key received. Send one or multiple keys separated by spaces/new lines."
                        )
                        bot.register_next_step_handler(retry, save_key_step)
                        return
                    _admin_success_send(
                        msg.chat.id,
                        f"✅ <b>Add Successfully! {count} VIP Key(s) Saved to Database (FIFO Queue).</b>\n\n"
                        "Each successful purchase will receive exactly one key in FIFO order.",
                        parse_mode="HTML"
                    )
                    del admin_temp_data[user_id]
                
                bot.register_next_step_handler(msg, save_key_step)

    elif call.data == "admin_manual_key_view":
        if _is_admin(user_id):
            products=get_unique_products(); markup=types.InlineKeyboardMarkup(row_width=1)
            catalog=admin_temp_data.setdefault(user_id,{}).setdefault('manual_view_catalog',{}); catalog.clear()
            lines=['👁️ <b>MANUAL VIP KEY STOCK</b>','────────────────────────','']; visible=0
            for prod_name in products:
                plans=get_product_plans(prod_name); total=0; counts=[]
                for plan in plans:
                    count=get_key_stock_count(prod_name,plan[2])
                    if count: counts.append(f'{plan[2]}: {count}'); total+=count
                if total:
                    visible+=1; h=hashlib.sha1(str(prod_name).encode()).hexdigest()[:12]; catalog[h]=prod_name
                    markup.add(types.InlineKeyboardButton(f'🎮 {prod_name} · {total} Key(s)',callback_data=f'manual_key_view_prod_{h}'))
                    lines.append(f'🎮 <b>{html.escape(str(prod_name))}</b> — <b>{total}</b> remaining')
                    for item in counts: lines.append(f'   └ {html.escape(item)}')
            if not visible: lines.append('<i>No unused Manual VIP Keys are currently available.</i>')
            _ensure_admin_back_button(markup); _admin_ui_send(call,'\n'.join(lines),parse_mode='HTML',reply_markup=markup)

    elif call.data.startswith('manual_key_view_prod_'):
        if _is_admin(user_id):
            h=call.data.replace('manual_key_view_prod_','',1); prod_name=admin_temp_data.get(user_id,{}).get('manual_view_catalog',{}).get(h)
            if not prod_name:
                _admin_ui_send(call,'❌ Manual Key list expired. Open Manual Key View again.',parse_mode='HTML'); return
            conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
            try:
                rows=conn.execute('SELECT id,validity_days,panel_key FROM panels WHERE panel_name=? AND is_sold=0 ORDER BY id ASC',(prod_name,)).fetchall()
            finally: conn.close()
            lines=[f'🔑 <b>MANUAL KEYS — {html.escape(str(prod_name))}</b>','────────────────────────','']
            markup=types.InlineKeyboardMarkup(row_width=1)
            if not rows:
                lines.append('<i>No unused keys remain.</i>')
            else:
                current=None
                for panel_id,days,key in rows:
                    if str(days)!=current:
                        current=str(days)
                        lines.append(f'\n⏱️ <b>{html.escape(current)}</b>')
                    lines.append(f'   🔑 <code>{html.escape(str(key),quote=False)}</code>')
                    # One delete button per exact database key. The panel ID is
                    # used instead of the key text so long/special keys are safe
                    # inside Telegram callback_data and only that row can be removed.
                    markup.row(types.InlineKeyboardButton('🗑 Delete this key',callback_data=f'manual_key_delete_{int(panel_id)}'))
                lines.append(f'\n📦 <b>Total Remaining:</b> {len(rows)}')
            markup.add(types.InlineKeyboardButton('🔄 Refresh',callback_data=f'manual_key_view_prod_{h}'))
            _ensure_admin_back_button(markup)
            _admin_ui_send(call,'\n'.join(lines),parse_mode='HTML',reply_markup=markup)

    elif call.data.startswith('manual_key_edit_'):
        if _is_admin(user_id):
            try: panel_id = int(call.data.replace('manual_key_edit_', '', 1))
            except Exception:
                bot.answer_callback_query(call.id, '❌ Invalid key ID.', show_alert=True); return
            conn = sqlite3.connect(str(BOT_DB_PATH), timeout=15)
            try: row = conn.execute('SELECT id,panel_name,validity_days,panel_key FROM panels WHERE id=? AND is_sold=0',(panel_id,)).fetchone()
            finally: conn.close()
            if not row:
                bot.answer_callback_query(call.id, '❌ Key not found or already sold.', show_alert=True); return
            admin_temp_data[user_id] = {'manual_edit_key_id':panel_id,'manual_edit_key_product':row[1],'manual_edit_key_days':row[2]}
            msg = _admin_ui_send(call, f'✏️ <b>EDIT MANUAL VIP KEY</b>\n\n🎮 <b>Product:</b> {html.escape(str(row[1]))}\n📅 <b>Plan:</b> {html.escape(str(row[2]))}\n🔑 <b>Current:</b> <code>{html.escape(str(row[3]),quote=False)}</code>\n\nSend the corrected key:', parse_mode='HTML')
            bot.register_next_step_handler(msg, step_edit_manual_key_legacy)

    elif call.data.startswith('manual_key_delete_') and not call.data.startswith('manual_key_delete_confirm_') and not call.data.startswith('manual_key_delete_cancel_'):
        if _is_admin(user_id):
            try:
                panel_id=int(call.data.replace('manual_key_delete_','',1))
            except Exception:
                bot.answer_callback_query(call.id,'❌ Invalid key ID.',show_alert=True); return
            conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
            try:
                row=conn.execute('SELECT id,panel_name,validity_days,panel_key FROM panels WHERE id=? AND is_sold=0',(panel_id,)).fetchone()
            finally: conn.close()
            if not row:
                bot.answer_callback_query(call.id,'❌ Key not found or already removed.',show_alert=True); return
            _,prod_name,days,key=row
            markup=types.InlineKeyboardMarkup(row_width=2)
            markup.row(
                types.InlineKeyboardButton('✅ Confirm Delete',callback_data=f'manual_key_delete_confirm_{panel_id}'),
                types.InlineKeyboardButton('❌ Cancel',callback_data=f'manual_key_delete_cancel_{panel_id}')
            )
            _admin_ui_send(call,
                f'⚠️ <b>DELETE MANUAL KEY?</b>\n\n'
                f'🎮 <b>Product:</b> {html.escape(str(prod_name),quote=False)}\n'
                f'⏱️ <b>Plan:</b> {html.escape(str(days),quote=False)}\n'
                f'🔑 <code>{html.escape(str(key),quote=False)}</code>\n\n'
                '<i>This exact unused key will be permanently removed from manual stock.</i>',
                parse_mode='HTML',reply_markup=markup)

    elif call.data.startswith('manual_key_delete_confirm_'):
        if _is_admin(user_id):
            try:
                panel_id=int(call.data.replace('manual_key_delete_confirm_','',1))
            except Exception:
                bot.answer_callback_query(call.id,'❌ Invalid key ID.',show_alert=True); return
            conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
            try:
                row=conn.execute('SELECT panel_name,panel_key FROM panels WHERE id=? AND is_sold=0',(panel_id,)).fetchone()
                if not row:
                    bot.answer_callback_query(call.id,'❌ Key not found or already removed.',show_alert=True); return
                conn.execute('DELETE FROM panels WHERE id=? AND is_sold=0',(panel_id,))
                conn.commit()
                prod_name=str(row[0] or '')
            finally: conn.close()
            bot.answer_callback_query(call.id,'✅ Manual key deleted.')
            # Rebuild the same product view so the deleted key disappears immediately.
            catalog=admin_temp_data.setdefault(user_id,{}).setdefault('manual_view_catalog',{})
            h=hashlib.sha1(prod_name.encode()).hexdigest()[:12]
            catalog[h]=prod_name
            fake_call=call
            rows_conn=sqlite3.connect(str(BOT_DB_PATH),timeout=15)
            try:
                rows=rows_conn.execute('SELECT id,validity_days,panel_key FROM panels WHERE panel_name=? AND is_sold=0 ORDER BY id ASC',(prod_name,)).fetchall()
            finally: rows_conn.close()
            lines=[f'🔑 <b>MANUAL KEYS — {html.escape(prod_name)}</b>','────────────────────────','']
            markup=types.InlineKeyboardMarkup(row_width=1)
            if not rows:
                lines.append('<i>No unused keys remain.</i>')
            else:
                current=None
                for pid,days,key in rows:
                    if str(days)!=current:
                        current=str(days); lines.append(f'\n⏱️ <b>{html.escape(current)}</b>')
                    lines.append(f'   🔑 <code>{html.escape(str(key),quote=False)}</code>')
                    markup.row(
                        types.InlineKeyboardButton('✏️ Edit',callback_data=f'manual_key_edit_{int(pid)}'),
                        types.InlineKeyboardButton('🗑 Delete',callback_data=f'manual_key_delete_{int(pid)}')
                    )
                lines.append(f'\n📦 <b>Total Remaining:</b> {len(rows)}')
            markup.add(types.InlineKeyboardButton('🔄 Refresh',callback_data=f'manual_key_view_prod_{h}'))
            _ensure_admin_back_button(markup)
            _admin_ui_send(fake_call,'\n'.join(lines),parse_mode='HTML',reply_markup=markup)

    elif call.data.startswith('manual_key_delete_cancel_'):
        if _is_admin(user_id):
            bot.answer_callback_query(call.id,'Cancelled.')
            markup=types.InlineKeyboardMarkup(row_width=1)
            markup.add(types.InlineKeyboardButton('👁️ Manual Key View',callback_data='admin_manual_key_view'))
            _ensure_admin_back_button(markup)
            _admin_ui_send(call,'↩️ <b>Delete cancelled.</b>\n\nNo manual key was removed.',parse_mode='HTML',reply_markup=markup)

    elif call.data == 'admin_user_reseller_search':
        if _is_admin(user_id):
            _send_user_reseller_search(call)

    elif call.data.startswith('admin_user_search_profile_'):
        if _is_admin(user_id):
            try:
                target_uid = int(call.data.replace('admin_user_search_profile_', '', 1))
            except Exception:
                bot.answer_callback_query(call.id, '❌ Invalid account ID.', show_alert=True)
                return
            _send_searched_account_profile(call, target_uid)

    elif call.data == "admin_reseller_list":
        if _is_admin(user_id):
            _send_reseller_list(call, 0)

    elif call.data.startswith("admin_reseller_list_"):
        if _is_admin(user_id):
            try:
                page = int(call.data.rsplit("_", 1)[1])
            except (TypeError, ValueError):
                page = 0
            _send_reseller_list(call, page)

    elif call.data.startswith("admin_reseller_profile_"):
        if _is_admin(user_id):
            try:
                target_uid = int(call.data.replace("admin_reseller_profile_", "", 1))
            except (TypeError, ValueError):
                bot.answer_callback_query(call.id, "❌ Invalid reseller ID.", show_alert=True)
                return
            _send_reseller_profile(call, target_uid)

    elif call.data == "admin_track_users":
        if _is_admin(user_id):
            _send_admin_user_list(call, 0)

    elif call.data.startswith("admin_track_users_page_"):
        if _is_admin(user_id):
            try:
                page = max(0, int(call.data.rsplit("_", 1)[1]))
            except (TypeError, ValueError):
                page = 0
            _send_admin_user_list(call, page)

    elif call.data.startswith("track_uid_"):
        if _is_admin(user_id):
            parts = call.data.split("_")
            try:
                target_uid = int(parts[2])
                return_page = max(0, int(parts[3])) if len(parts) > 3 else 0
            except (TypeError, ValueError):
                bot.answer_callback_query(call.id, "❌ Invalid user ID.", show_alert=True)
                return
            u_info = get_user(target_uid)
            if u_info:
                orders = get_user_orders(target_uid)
                ord_text = ""
                if orders:
                    for o in orders[:30]:
                        ord_text += (
                            f"🆔 <b>Order ID:</b> <code>{html.escape(str(o[0]))}</code>\n"
                            f"├── 🛒 <b>Hack:</b> {html.escape(str(o[1]))} ({html.escape(str(o[2]))})\n"
                            f"├── 💰 <b>Paid:</b> ₹{float(o[3] or 0):.2f} INR\n"
                            f"├── ⏰ <b>Time:</b> {html.escape(str(o[5]))}\n"
                            f"└── 🔑 <b>Key:</b> <code>{html.escape(str(o[4]))}</code>\n\n"
                        )
                    if len(orders) > 30:
                        ord_text += f"<i>…and {len(orders)-30} more purchase(s).</i>"
                else:
                    ord_text = "<i>No purchase history yet.</i>"

                user_details = (
                    f"📊 <b>USER PROFILE & TRACKING</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"├── 🆔 <b>User ID:</b> <code>{u_info[0]}</code>\n"
                    f"├── 👤 <b>Name:</b> {html.escape(str(u_info[1] or 'Unnamed User'), quote=False)}\n"
                    f"├── 📞 <b>Phone:</b> {html.escape(str(u_info[2] or 'N/A'), quote=False)}\n"
                    f"├── 💼 <b>Balance:</b> ₹{float(u_info[4] or 0):.2f} INR\n"
                    f"├── 📦 <b>Orders Count:</b> {int(u_info[6] or 0)}\n"
                    f"├── 💎 <b>Lifetime Spent:</b> ₹{float(u_info[7] or 0):.2f} INR\n"
                    f"├── 📥 <b>Total Deposited:</b> ₹{float(u_info[8] or 0):.2f} INR\n"
                    f"├── 👑 <b>Reseller:</b> {'Yes' if len(u_info) > 11 and int(u_info[11] or 0) else 'No'}\n"
                    f"├── {'✅ Verified' if len(u_info) > 10 and int(u_info[10] or 0) else '⚪ Not Verified'}\n"
                    f"└── 📅 <b>Joined:</b> {html.escape(str(u_info[9] or 'N/A'), quote=False)}\n\n"
                    f"🛒 <b>Purchases & Keys:</b>\n{ord_text}"
                )
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.row(
                    types.InlineKeyboardButton('🔄 Refresh', callback_data=f'track_uid_{target_uid}_{return_page}'),
                    types.InlineKeyboardButton('🔙 User List', callback_data=f'admin_track_users_page_{return_page}')
                )
                markup.add(types.InlineKeyboardButton('🔙 Users & Resellers', callback_data='admin_cat_users'))
                _admin_ui_send(call, user_details, parse_mode="HTML", reply_markup=markup)
            else:
                bot.answer_callback_query(call.id, "❌ User not found.", show_alert=True)
                _send_admin_user_list(call, return_page)

    elif call.data == "admin_manage_discounts":
        if _is_admin(user_id):
            markup = types.InlineKeyboardMarkup()
            btn_usr = types.InlineKeyboardButton("👤 Specific User Discount", callback_data="disc_specific_user")
            btn_glb = types.InlineKeyboardButton("🌐 Global Discount (All Hacks & Users)", callback_data="disc_global_store")
            btn_prd = types.InlineKeyboardButton("🎮 Specific Hack Discount", callback_data="disc_specific_hack")
            markup.add(btn_usr)
            markup.add(btn_glb)
            markup.add(btn_prd)
            _admin_ui_send(call, "🏷️ <b>DISCOUNT MANAGEMENT PANEL</b>", parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup))

    elif call.data == "disc_specific_user":
        if _is_admin(user_id):
            msg = _admin_ui_send(call, "👤 <b>Enter Target Telegram User ID:</b>", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_get_user_discount_id)

    elif call.data == "disc_specific_hack":
        if _is_admin(user_id):
            products = get_unique_products()
            if not products:
                _admin_ui_send(call, "❌ No products found.", parse_mode="HTML")
                return
            markup = types.InlineKeyboardMarkup()
            for prod in products:
                current = get_product_discount_percent(prod)
                markup.add(types.InlineKeyboardButton(
                    f"🎮 {prod} ({current:.0f}% OFF)",
                    callback_data=f"disc_prod_{prod}"
                ))
            _admin_ui_send(call,
                
                "🎮 <b>SELECT HACK FOR DISCOUNT</b>\n\nTap a hack to set its discount percentage. 0% returns its product/price buttons to blue unless a global discount is active.",
                parse_mode="HTML",
                reply_markup=_ensure_admin_back_button(markup)
            )

    elif call.data == "disc_global_store":
        if _is_admin(user_id):
            msg = _admin_ui_send(call, "🌐 <b>Enter Global Discount Percentage for ALL Users & Products</b> (e.g., <code>10</code> for 10%):", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_get_global_discount_percent)

    elif call.data.startswith("disc_prod_"):
        if _is_admin(user_id):
            p_name = call.data.replace("disc_prod_", "")
            admin_temp_data[user_id] = {'prod_name': p_name}
            msg = _admin_ui_send(call, f"🏷️ <b>Enter Discount Percentage for {p_name}:</b>", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_get_prod_discount_percent)

    elif call.data == "admin_broadcast":
        if _is_admin(user_id):
            _send_broadcast_admin_screen(call)

    elif call.data == "admin_broadcast_history":
        if _is_admin(user_id):
            _send_broadcast_history_screen(call)

    elif call.data == "admin_broadcast_send":
        if _is_admin(user_id):
            msg = _admin_ui_send(call, "📢 <b>Send photo, video, audio, document or text message to broadcast to all users:</b>\n\n✨ Premium/Custom Emoji and text formatting will be preserved exactly.", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_get_broadcast_media)

    elif call.data.startswith("admin_broadcast_delete_"):
        if _is_admin(user_id):
            try: batch_id=int(call.data.rsplit("_",1)[1])
            except Exception: batch_id=0
            if not batch_id:
                _admin_ui_send(call,"❌ Invalid Broadcast ID.",parse_mode="HTML",reply_markup=_broadcast_admin_markup())
            else:
                deleted_count,failed_count,already_deleted=_delete_broadcast_batch(batch_id)
                result_text=("ℹ️ <b>This broadcast was already deleted.</b>" if already_deleted else
                             f"🗑️ <b>Broadcast Delete Complete!</b>\n\n✅ Deleted: <b>{deleted_count}</b>\n⚠️ Failed/Unavailable: <b>{failed_count}</b>")
                _admin_ui_send(call,result_text,parse_mode="HTML",reply_markup=_broadcast_admin_markup())

    elif call.data == "admin_manage_bal":
        if _is_admin(user_id):
            msg = _admin_ui_send(call, "👤 <b>Enter Telegram User ID to Modify Balance:</b>", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_get_bal_user_id)

    elif call.data in ["bal_action_add", "bal_action_sub"]:
        if _is_admin(user_id):
            admin_temp_data[user_id]['is_add'] = (call.data == "bal_action_add")
            msg = _admin_ui_send(call, "💰 <b>Enter Amount in INR (₹):</b>", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_get_bal_amount)

    elif call.data == "admin_del_hack":
        if _is_admin(user_id):
            products = get_unique_products()
            if not products:
                _admin_ui_send(call, "❌ No products found to delete.", parse_mode="HTML")
                return
            markup = types.InlineKeyboardMarkup()
            for prod in products:
                markup.add(types.InlineKeyboardButton(f"🗑️ Delete {prod}", callback_data=f"confirm_del_hack_{prod}"))
            _admin_ui_send(call, "⚠️ <b>SELECT ENTIRE HACK TO DELETE:</b>\n<i>This will remove all plans associated with this hack!</i>", parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("confirm_del_hack_"):
        if _is_admin(user_id):
            prod_name = call.data.replace("confirm_del_hack_", "")
            delete_entire_hack_db(prod_name)
            _admin_navigation_barrier(user_id, {"admin_del_hack"})
            # Return one level to the delete-hack list after the operation.
            _remember_admin_pending_return(user_id, call.data, call.message.message_id)
            _admin_success_send(call.message.chat.id, f"✅ <b>Successfully Deleted Entire Hack:</b> {prod_name}", parse_mode="HTML")

    elif call.data == "admin_del_plan":
        if _is_admin(user_id):
            products = get_unique_products()
            if not products:
                _admin_ui_send(call, "❌ No products found.", parse_mode="HTML")
                return
            markup = types.InlineKeyboardMarkup()
            for prod in products:
                markup.add(types.InlineKeyboardButton(f"🎮 {prod}", callback_data=f"select_del_plan_hack_{prod}"))
            _admin_ui_send(call, "❌ <b>SELECT HACK TO DELETE A SPECIFIC PLAN/DAY:</b>", parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("select_del_plan_hack_"):
        if _is_admin(user_id):
            prod_name = call.data.replace("select_del_plan_hack_", "")
            plans = get_product_plans(prod_name)
            if not plans:
                _admin_ui_send(call, "❌ No plans found for this hack.", parse_mode="HTML")
                return
            markup = types.InlineKeyboardMarkup()
            for plan in plans:
                p_id, _, p_days, p_price, _, _, _, _, _, _, _ = plan
                markup.add(types.InlineKeyboardButton(f"🗑️ Delete {p_days} Plan (₹{p_price:.2f})", callback_data=f"confirm_del_plan_{p_id}"))
            _admin_ui_send(call, f"🎮 <b>Selected Hack: {prod_name}</b>\nSelect Plan to Delete:", parse_mode="HTML", reply_markup=_ensure_admin_back_button(markup))

    elif call.data.startswith("confirm_del_plan_"):
        if _is_admin(user_id):
            p_id = int(call.data.replace("confirm_del_plan_", ""))
            delete_product_plan_db(p_id)
            _admin_navigation_barrier(user_id, {"admin_del_plan"})
            # Return one level to the plan-selection list after the operation.
            _remember_admin_pending_return(user_id, call.data, call.message.message_id)
            _admin_success_send(call.message.chat.id, "✅ <b>Successfully Deleted Plan!</b>", parse_mode="HTML")

    elif call.data == "admin_set_guide":
        if _is_admin(user_id):
            msg = _admin_ui_send(call, "🎬 <b>Enter Dynamic How To Use Bot Guide Link (URL):</b>", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_get_guide_url)

    elif call.data == "reseller_qr_back":
        _fast_callback_ack(call)
        chat_id=call.message.chat.id
        with reseller_qr_lock:
            session=reseller_qr_sessions.get(int(chat_id))
        if session and session.get('message_id')==call.message.message_id:
            with reseller_qr_lock:
                reseller_qr_sessions.pop(int(chat_id),None)
            order_id=str(session.get('order_id') or '')
            if order_id:
                active_orders.pop(order_id,None)
            _delete_message_safely(chat_id,call.message.message_id)
            show_shop_features(chat_id,first_name)

    elif call.data == "back_to_main":
        # Normal screens (Orders, Profile, Referral, Store, Help, etc.) do not
        # use QR cleanup. Reuse the current message instead of deleting it.
        _fast_callback_ack(call)
        show_shop_features(call.message.chat.id, first_name, message_id=call.message.message_id)

    elif call.data == "back_to_main_new":
        _fast_callback_ack(call)
        show_shop_features(call.message.chat.id, first_name, message_id=call.message.message_id)

    elif call.data == "back_from_qr":
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        show_shop_features(call.message.chat.id, first_name)

# ==================== GLOBAL ADMIN STEP ESCAPE FIX ====================
def _handle_admin_escape_message(message):
    uid=message.from_user.id
    if not _is_admin(uid): return False
    text=(message.text or '').strip().split()[0].lower() if message.text else ''
    if text not in ('/cancel','/start','/admin'): return False
    try: bot.clear_step_handler_by_chat_id(message.chat.id)
    except Exception: pass
    admin_temp_data.pop(uid,None)
    if text=='/cancel':
        bot.send_message(message.chat.id,'✅ <b>Current Admin Command Cancelled.</b>',parse_mode='HTML'); admin_panel(message)
    elif text=='/admin': admin_panel(message)
    else: send_welcome(message)
    return True

# Intercept commands at registration time so even nested/locally-defined next-step
# handlers (including manual-key entry) cannot trap an admin inside a command.
_original_register_next_step_handler=bot.register_next_step_handler
def _safe_register_next_step_handler(message,callback,*args,**kwargs):
    def _escaped_callback(msg,*cb_args,**cb_kwargs):
        if _handle_admin_escape_message(msg): return
        return callback(msg,*cb_args,**cb_kwargs)
    result = _original_register_next_step_handler(message,_escaped_callback,*args,**kwargs)
    # Every Admin text/link/ID/price input gets the same universal escape hint.
    try:
        if _is_admin(message.from_user.id):
            bot.send_message(message.chat.id, "↩️ <i>Type /cancel to stop this operation.</i>", parse_mode='HTML')
    except Exception:
        pass
    return result
bot.register_next_step_handler=_safe_register_next_step_handler

# Also wrap existing named step functions for safety when they are invoked directly.
for _name,_fn in list(globals().items()):
    if _name.startswith('step_') and callable(_fn) and not getattr(_fn,'_escape_wrapped',False):
        def _make_escape_wrapper(original):
            def _wrapped(message,*args,**kwargs):
                if _handle_admin_escape_message(message): return
                return original(message,*args,**kwargs)
            _wrapped.__name__=getattr(original,'__name__','step_handler'); _wrapped._escape_wrapped=True
            return _wrapped
        globals()[_name]=_make_escape_wrapper(_fn)

print(f"🤖 {BOT_BRAND_NAME} Bot is running successfully with Admin Verification Notification & Pending Payments feature...")
_start_reseller_api_http_server()

# ==================== SINGLE-INSTANCE POLLING GUARD ====================
# Telegram allows only one active getUpdates long-poll for a bot token.
# This local lock prevents accidental double-launches from Termux.
_POLL_LOCK_PATH = ".rg_cheat_shop_polling.lock"
_poll_lock_file = None

def acquire_single_instance_lock():
    global _poll_lock_file
    try:
        import fcntl
        _poll_lock_file = open(_POLL_LOCK_PATH, "w")
        fcntl.flock(_poll_lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _poll_lock_file.write(str(os.getpid()))
        _poll_lock_file.flush()
        return True
    except (BlockingIOError, OSError):
        print("❌ Another instance of this bot is already running in this folder. Stop it before starting a second copy.")
        return False
    except Exception as e:
        print(f"⚠️ Polling lock warning: {e}")
        return True

def run_bot_polling():
    if not acquire_single_instance_lock():
        return

    # Remove any webhook so long polling can work reliably after a webhook-based run.
    try:
        bot.remove_webhook()
    except Exception as exc:
        print(f'⚠️ Telegram webhook cleanup warning: {exc}')

    # Validate the exact runtime token before entering getUpdates.  A generated
    # bot must never silently poll with the Master Bot token or an empty token.
    try:
        me = bot.get_me()
        print(f'🤖 Polling bot ready: @{getattr(me, "username", "") or "N/A"} ({getattr(me, "id", "N/A")})')
    except Exception as exc:
        print(f'⚠️ Telegram getMe check failed; polling will retry: {exc}')

    # Telegram/network read timeouts are transient.  Do not let one timeout
    # terminate the bot or make the admin/user believe the bot has stopped.
    # Keep the same bot instance and retry with a small capped backoff.
    retry_delay = 3
    while True:
        try:
            bot.infinity_polling(
                skip_pending=True,
                timeout=60,
                long_polling_timeout=60,
                restart_on_change=False,
            )
            # If the polling method returns without an exception, immediately
            # reconnect instead of exiting the process.
            print("⚠️ Telegram polling ended; reconnecting...")
            retry_delay = 3
        except Exception as e:
            err = str(e)
            err_lower = err.lower()

            if "409" in err and "getupdates" in err_lower:
                print("⚠️ Telegram 409 Conflict: another getUpdates client is active. Retrying in 10 seconds...")
                time.sleep(10)
                retry_delay = 3
                continue

            if (
                "read timed out" in err_lower
                or "connectionpool" in err_lower
                or "connection aborted" in err_lower
                or "connection reset" in err_lower
                or "max retries exceeded" in err_lower
                or "remote end closed" in err_lower
                or "network is unreachable" in err_lower
            ):
                print(f"⚠️ Temporary Telegram/network error: {e}. Reconnecting in {retry_delay}s...")
            else:
                print(f"⚠️ Polling error: {e}. Reconnecting in {retry_delay}s...")

            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30)

try:
    _configure_current_bot_menu()
except Exception:
    pass

# Mark a generated child as fully initialized only after its complete module
# setup, command menu configuration and expiry monitor setup have succeeded.
# The Master Bot uses this marker when creating/restarting the child.
if BOT_INSTANCE_ID and not BOT_CREATOR_ENABLED:
    try:
        BOT_CHILD_READY_FILE.parent.mkdir(parents=True, exist_ok=True)
        BOT_CHILD_READY_FILE.write_text(
            json.dumps({
                'instance_id': BOT_INSTANCE_ID,
                'pid': os.getpid(),
                'bot_token_hash': hashlib.sha256(TOKEN.encode('utf-8')).hexdigest()[:16],
                'db_path': str(BOT_DB_PATH),
                'ready_at': time.time(),
            }, ensure_ascii=False),
            encoding='utf-8'
        )
    except Exception as exc:
        print(f'[BOT CREATOR] Could not write child readiness marker: {exc}')

if BOT_CREATOR_ENABLED:
    threading.Thread(target=_bot_creator_cleanup_expired, daemon=True, name='bot-expiry').start()
    threading.Thread(target=_bot_creator_restore_children, daemon=True, name='bot-restore').start()
else:
    _enforce_child_bot_expiry()
    threading.Thread(target=_child_expiry_monitor, daemon=True, name='child-expiry-timer').start()

run_bot_polling()
