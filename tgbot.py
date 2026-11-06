"""
RG CHEAT - Telegram bot (runs INSIDE the website, no separate hosting needed).

What it does
  * Sends login codes (6 digit) to resellers
  * Sends "NEW PURCHASE ALERT", "LOW BALANCE ALERT", "BALANCE ADDED" to resellers
  * Sends "NEW DEVICE LOGIN REQUEST" to the admin with [Accept] / [Reject] buttons
  * /start  -> shows the user's own Chat ID (reseller gives this ID to the admin)
  * remembers everybody who pressed /start (admin can link them with one click)
  * keeps a delivery log (last 40 sends / errors) so a missing message is never a mystery

It only needs the 'requests' package. Every message is sent from its own short-lived thread (max 4 at once), so a burst of
purchases never hits Telegram's rate limit (429 is retried automatically).
"""
import collections
import html
import re
import socket
import threading
import time

import requests
import urllib3.util.connection as _u3c

# Some hosts (Render free) have a broken IPv6 route to Telegram -> requests hang. Use IPv4 only.
_u3c.allowed_gai_family = lambda: socket.AF_INET

API = "https://api.telegram.org/bot%s/%s"


def _post(url, payload, connect, read):
    """requests.post with a HARD deadline (covers DNS / stuck sockets that 'timeout=' does not). Never hangs."""
    box = {}

    def work():
        try:
            box["r"] = requests.post(url, json=payload, timeout=(connect, read))
        except Exception as ex:
            box["e"] = ex
    t = threading.Thread(target=work, daemon=True, name="tg-http")
    t.start()
    t.join(connect + read + 3)
    if "r" in box:
        return box["r"]
    if "e" in box:
        raise box["e"]
    raise TimeoutError("no answer from Telegram")


def nice_error(err):
    """Turn a raw Telegram error into a sentence the admin can act on."""
    e = str(err or "")
    low = e.lower()
    if "chat not found" in low:
        return "Chat ID is wrong, or that person never pressed START in the bot (%s)" % e
    if "blocked by the user" in low:
        return "That person blocked the bot (%s)" % e
    if "deactivated" in low:
        return "That Telegram account is deactivated (%s)" % e
    if "unauthorized" in low or "not found" == low.strip():
        return "Bot token is wrong - Telegram rejected it (%s)" % e
    if "conflict" in low:
        return "Another copy of this bot is running somewhere else with the same token (%s)" % e
    if low.startswith("network"):
        return "Server could not reach Telegram (%s)" % e
    return e


def _norm(e):
    """emoji key: ignore the invisible variation selector so  \u2705  and  \u2705\ufe0f  match."""
    return (e or "").replace("\ufe0f", "")


class Bot:
    def __init__(self, get_token, get_admin, on_device, brand="RG CHEAT", on_claim=None, on_seen=None,
                 packs=None, prem_on=None):
        self.get_token = get_token          # () -> bot token (str)
        self.get_admin = get_admin          # () -> admin chat id (str)
        self.on_device = on_device          # (device_row_id:int, approve:bool) -> text
        self.brand = brand
        self.on_claim = on_claim            # (chat_id, secret) -> bool  ("/admin <password>")
        self.on_seen = on_seen              # (chat_id, name, username) -> None  (someone pressed /start)
        self._sem = threading.Semaphore(4)         # at most 4 messages in flight (Telegram rate limit)
        self._hook_cleared = None
        self._started = False
        self.log = collections.deque(maxlen=40)    # (time, ok, chat_id, what, error)
        self.sent_ok = 0
        self.sent_fail = 0
        self.poll_err = ""                  # last problem while receiving (empty = fine)
        self.poll_ok = 0                    # time of last successful poll
        self._me = None                     # cached getMe result (the admin page never waits for Telegram)
        self._me_ts = 0
        self._me_busy = False
        self.me_err = ""
        # ---- premium (custom) emoji
        self.packs = list(packs or [])              # emoji pack names (t.me/addemoji/<name>)
        self.prem_on = prem_on or (lambda: True)    # admin switch
        self.pack_data = {}                         # pack -> {plain emoji: custom_emoji_id}
        self.pack_info = {}                         # pack -> {"ok": bool, "count": int, "err": str}
        self.emap = {}                              # plain emoji -> custom_emoji_id (first pack wins)
        self._rx = None
        self._mode = "both"                         # both | text | btn | plain  (what Telegram accepted last)
        self._mode_ts = 0
        self.prem_err = ""

    def _note(self, ok, chat_id, what, err=""):
        self.log.appendleft((int(time.time()), ok, str(chat_id), what, err))
        if not ok:
            print("[telegram] FAILED %s to %s: %s" % (what, chat_id, err), flush=True)   # visible in Render > Logs
        if ok:
            self.sent_ok += 1
        else:
            self.sent_fail += 1

    # ------------------------------------------------------------ low level
    def api(self, method, _timeout=20, **params):
        tok = self.get_token()
        if not tok:
            raise RuntimeError("bot token not set")
        try:
            r = _post(API % (tok, method), params, 5, _timeout)
        except (requests.RequestException, TimeoutError) as ex:
            e = RuntimeError("Network error: %s" % type(ex).__name__)
            e.network = True
            raise e
        try:
            j = r.json()
        except ValueError:
            e = RuntimeError("Telegram HTTP %s" % r.status_code)
            e.network = True
            raise e
        if not j.get("ok"):
            e = RuntimeError(str(j.get("description") or "Telegram error")[:150])
            e.retry_after = (j.get("parameters") or {}).get("retry_after")
            raise e
        return j.get("result")

    def _refresh_me(self):
        try:
            self._me = self.api("getMe", _timeout=8)
            self.me_err = ""
        except Exception as e:
            self._me = None
            self.me_err = "Cannot reach Telegram: " + nice_error(e)
        finally:
            self._me_busy = False

    def me_cached(self):
        """Instant. Refreshes in the background at most once a minute."""
        now = time.time()
        if now - self._me_ts > 60 and not self._me_busy:
            self._me_busy, self._me_ts = True, now
            threading.Thread(target=self._refresh_me, daemon=True, name="tg-me").start()
        return self._me

    def me(self):
        try:
            return self.api("getMe", _timeout=10)
        except Exception:
            return None

    # ------------------------------------------------------------ premium emoji
    def _rebuild_map(self):
        m = {}
        for name in self.packs:                     # earlier pack in the list has priority
            for k, v in (self.pack_data.get(name) or {}).items():
                m.setdefault(k, v)
        self.emap = m
        if m:
            keys = sorted(m, key=len, reverse=True)
            self._rx = re.compile("(?:%s)\\ufe0f?" % "|".join(re.escape(k) for k in keys))
        else:
            self._rx = None

    def fetch_pack(self, name):
        """Download one emoji pack from Telegram -> {plain emoji: custom_emoji_id}."""
        st = self.api("getStickerSet", _timeout=20, name=name)
        out = {}
        for sk in st.get("stickers") or []:
            cid, em = sk.get("custom_emoji_id"), sk.get("emoji")
            if cid and em:
                out.setdefault(_norm(em), cid)
        return out

    def _load_packs(self):
        while True:
            if not self.get_token():
                time.sleep(10)
                continue
            todo = [n for n in self.packs if not (self.pack_info.get(n) or {}).get("ok")]
            for name in todo:
                try:
                    d = self.fetch_pack(name)
                    self.pack_data[name] = d
                    self.pack_info[name] = {"ok": True, "count": len(d), "err": ""}
                except Exception as e:
                    self.pack_info[name] = {"ok": False, "count": 0, "err": nice_error(e)}
                self._rebuild_map()
            if not todo or all((self.pack_info.get(n) or {}).get("ok") for n in self.packs):
                return
            time.sleep(60)

    def premium(self, text):
        """Replace normal emoji in an HTML message by their premium version (never touches tags / <code>)."""
        if not self._rx or not text:
            return text
        out, depth = [], 0
        for part in re.split(r"(<[^>]*>)", text):
            if part[:1] == "<" and part[-1:] == ">":
                low = part.lower()
                if re.match(r"<(code|pre|tg-emoji)\b", low):
                    depth += 1
                elif re.match(r"</(code|pre|tg-emoji)\s*>", low):
                    depth = max(depth - 1, 0)
                out.append(part)
            elif depth or not part:
                out.append(part)
            else:
                out.append(self._rx.sub(
                    lambda m: '<tg-emoji emoji-id="%s">%s</tg-emoji>' % (self.emap[_norm(m.group(0))], m.group(0)), part))
        return "".join(out)

    def _btn(self, label, data, icon):
        b = {"text": label, "callback_data": data}
        if icon and self._rx:
            m = self._rx.match(label)
            if m and _norm(m.group(0)) in self.emap:
                b["text"] = label[m.end():].lstrip() or label
                b["icon_custom_emoji_id"] = self.emap[_norm(m.group(0))]
        return b

    def _cur_mode(self):
        if not self.emap or not self.prem_on():
            return "plain"
        if self._mode != "both" and time.time() - self._mode_ts > 1800:   # try the full premium again every 30 min
            self._mode = "both"
        return self._mode

    def status(self):
        return {"mode": self._cur_mode(), "packs": [(n, self.pack_info.get(n) or {"ok": False, "count": 0, "err": "loading..."})
                                                    for n in self.packs], "total": len(self.emap), "err": self.prem_err}

    # ------------------------------------------------------------ sending
    def send(self, chat_id, text, buttons=None, what="alert"):
        """Send in the background (own short-lived thread). Never blocks, never raises."""
        return self.send_many(chat_id, [(text, buttons)], what=what)

    def send_many(self, chat_id, items, what="alert"):
        """Send several messages one after another (keeps their order) in one background thread."""
        chat_id = str(chat_id or "").strip()
        if not chat_id or not self.get_token():
            self._note(False, chat_id or "-", what, "skipped: no Chat ID or bot token")
            return False

        def work():
            with self._sem:
                for text, buttons in items:
                    try:
                        self.send_now(chat_id, text, buttons, what=what)
                    except Exception as e:
                        self._note(False, chat_id, what, "error: %s" % str(e)[:120])
                    time.sleep(0.05)
        threading.Thread(target=work, daemon=True, name="tg-send").start()
        return True

    def send_now(self, chat_id, text, buttons=None, what="message"):
        """Send immediately (waits for Telegram). Returns (ok, readable_error). Retries flood-control / network hiccups."""
        chat_id = str(chat_id or "").strip()
        if not chat_id:
            return False, "No Chat ID"
        if not self.get_token():
            return False, "Bot token is not set"
        err = ""
        for attempt in range(2):
            try:
                self._send(chat_id, text, buttons)
                self._note(True, chat_id, what)
                return True, ""
            except Exception as e:
                err = nice_error(e)
                wait = getattr(e, "retry_after", None)
                if wait and attempt < 1:
                    time.sleep(min(int(wait) + 1, 5))
                elif getattr(e, "network", False) and attempt < 1:
                    time.sleep(1)
                else:
                    break
        self._note(False, chat_id, what, err)
        return False, err

    def _send_once(self, chat_id, text, buttons, mode):
        t = self.premium(text) if mode in ("both", "text") else text
        p = dict(chat_id=chat_id, text=t, parse_mode="HTML", disable_web_page_preview=True)
        if buttons:
            icon = mode in ("both", "btn")
            p["reply_markup"] = {"inline_keyboard": [[self._btn(a, b, icon) for a, b in row] for row in buttons]}
        return self.api("sendMessage", _timeout=8, **p)

    def _send(self, chat_id, text, buttons):
        """Premium emoji first; if Telegram refuses them, quietly fall back to normal emoji (message is never lost)."""
        mode = self._cur_mode()
        order = {"both": ["both", "text", "btn", "plain"], "text": ["text", "plain"],
                 "btn": ["btn", "plain"], "plain": ["plain"]}[mode]
        for i, m in enumerate(order):
            try:
                r = self._send_once(chat_id, text, buttons, m)
                if i > 0 and mode != "plain":
                    self._mode, self._mode_ts = m, time.time()
                return r
            except Exception as e:
                low = str(e).lower()
                if i < len(order) - 1 and any(w in low for w in ("emoji", "entit", "parse", "icon", "button")):
                    self.prem_err = str(e)[:150]
                    continue
                raise

    # ------------------------------------------------------------ receiving
    def _poller(self):
        offset = 0
        while True:
            tok = self.get_token()
            if not tok:
                time.sleep(5)
                continue
            try:
                if self._hook_cleared != tok:          # polling needs the webhook to be off
                    self.api("deleteWebhook", _timeout=10)
                    self._hook_cleared = tok
                ups = self.api("getUpdates", _timeout=40, offset=offset, timeout=25,
                               allowed_updates=["message", "callback_query"]) or []
                self.poll_err = ""
                self.poll_ok = int(time.time())
                for u in ups:
                    offset = u["update_id"] + 1
                    try:
                        self._handle(u)
                    except Exception:
                        pass
            except Exception as e:
                self.poll_err = nice_error(e)
                time.sleep(5)

    def _handle(self, u):
        m = u.get("message")
        if m and m.get("chat", {}).get("type") == "private":
            cid = m["chat"]["id"]
            text = (m.get("text") or "").strip().lower()
            if text.startswith("/admin") and self.on_claim:
                ok = self.on_claim(cid, (m.get("text") or "")[6:])
                try:                                    # remove the message that contains the password
                    self.api("deleteMessage", chat_id=cid, message_id=m["message_id"])
                except Exception:
                    pass
                self.send(cid, "✅ <b>You are the admin now.</b>\nNew-device requests will come to this chat." if ok
                          else "❌ Wrong password (or too many tries).")
                return
            if str(cid) == str(self.get_admin() or "") and self._emoji_tools(cid, m):
                return
            if text.startswith("/start") or text.startswith("/id") or text.startswith("/myid"):
                if self.on_seen:
                    try:
                        frm = m.get("from") or {}
                        nm = " ".join(x for x in (frm.get("first_name"), frm.get("last_name")) if x)
                        self.on_seen(cid, nm, frm.get("username") or "")
                    except Exception:
                        pass
                self.send(cid, "👋 <b>Welcome to %s</b>\n\nYour Telegram Chat ID:\n<code>%s</code>\n\n"
                               "Send this ID to the admin. After he links it you will get login codes "
                               "and purchase alerts here." % (html.escape(self.brand), cid))
            else:
                self.send(cid, "Send /start to see your Chat ID.")
            return
        cb = u.get("callback_query")
        if cb:
            data = cb.get("data") or ""
            who = str((cb.get("from") or {}).get("id"))
            admin = str(self.get_admin() or "")
            if not data.startswith("dv:"):
                self.api("answerCallbackQuery", callback_query_id=cb["id"])
                return
            if not admin or who != admin:              # only the admin may decide
                self.api("answerCallbackQuery", callback_query_id=cb["id"], text="Not allowed", show_alert=True)
                return
            try:
                _, act, did = data.split(":")
                res = self.on_device(int(did), act == "a")
            except Exception:
                res = "Error"
            self.api("answerCallbackQuery", callback_query_id=cb["id"], text=res)
            msg = cb.get("message") or {}
            try:
                self.api("editMessageReplyMarkup", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
                         reply_markup={"inline_keyboard": [[{"text": ("✅ " if act == "a" else "❌ ") + res,
                                                             "callback_data": "noop"}]]})
            except Exception:
                pass

    # ------------------------------------------------------------ admin helper: emoji ids
    def _plain(self, cid, text):
        try:
            self.api("sendMessage", chat_id=cid, text=text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            pass

    def _emoji_tools(self, cid, m):
        """Admin only: send premium emojis or a pack link -> the bot answers with the emoji IDs.  /emojis = status."""
        txt = m.get("text") or ""
        ents = [e for e in (m.get("entities") or []) if e.get("type") == "custom_emoji"]
        names = re.findall(r"t\.me/addemoji/([A-Za-z0-9_]+)", txt)
        low = txt.strip().lower()
        if low.startswith("/emojis") or low.startswith("/emojiid"):
            st = self.status()
            lines = ["<b>Premium emoji</b>  (mode: <b>%s</b>, %d emoji loaded)" % (st["mode"], st["total"])]
            for n, i in st["packs"]:
                lines.append("%s %s - %s" % ("OK" if i["ok"] else "FAIL", html.escape(n),
                                             ("%d emoji" % i["count"]) if i["ok"] else html.escape(i["err"])))
            lines.append("\nSend me premium emojis, or a pack link (t.me/addemoji/...), and I reply with their IDs.")
            self._plain(cid, "\n".join(lines))
            return True
        if not ents and not names:
            return False
        u16 = txt.encode("utf-16-le")
        rows = []
        for e in ents:
            ch = u16[e["offset"] * 2:(e["offset"] + e["length"]) * 2].decode("utf-16-le", "ignore")
            rows.append("%s <code>%s</code>" % (html.escape(ch), e.get("custom_emoji_id")))
        for n in names[:5]:
            try:
                d = self.fetch_pack(n)
                rows.append("<b>%s</b> (%d)" % (html.escape(n), len(d)))
                rows += ["%s <code>%s</code>" % (html.escape(k), v) for k, v in d.items()]
            except Exception as ex:
                rows.append("%s: %s" % (html.escape(n), html.escape(nice_error(ex))))
        buf = ""
        for r in rows:
            if len(buf) + len(r) > 3500:
                self._plain(cid, buf)
                buf = ""
            buf += r + "\n"
        if buf:
            self._plain(cid, buf)
        return True

    # ------------------------------------------------------------ start
    def start(self):
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._poller, daemon=True, name="tg-poll").start()
        if self.packs:
            threading.Thread(target=self._load_packs, daemon=True, name="tg-emoji").start()
