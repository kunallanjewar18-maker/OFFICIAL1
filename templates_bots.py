"""Pages for Bot Make. install(T, _P) is called from templates_ui2.py before the admin menu is turned into the hamburger drawer."""

BOT_ICON = ('<rect width="18" height="10" x="3" y="11" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/>'
            '<line x1="8" x2="8" y1="16" y2="16"/><line x1="16" x2="16" y1="16" y2="16"/>')

RESELLER_PAGE = r"""{% extends 'rbase.html' %}{% block c %}
<div class=hd>{{ic('bot',24)}} BOT MAKE</div>
{% if mine %}
<div class=card><h3>{{ic('bot',20)}} Your bot</h3>
<table>
<tr><td class=mu>Name</td><td><b>{{mine.bot_name}}</b></td></tr>
<tr><td class=mu>Bot</td><td>{% if mine.bot_username %}<a href="https://t.me/{{mine.bot_username}}" target=_blank rel=noopener>@{{mine.bot_username}}</a>{% else %}-{% endif %}</td></tr>
<tr><td class=mu>Status</td><td>
{% if state=='running' %}<span class="pill a">Running</span>
{% elif state=='starting' %}<span class="pill c">Starting...</span>
{% elif state=='stopped' %}<span class="pill e">Stopped by admin</span>
{% else %}<span class="pill c">Restarting...</span>{% endif %}</td></tr>
<tr><td class=mu>Your admin ID</td><td><code>{{mine.admin_id}}</code></td></tr>
<tr><td class=mu>Created</td><td>{{mine.created|dt}}</td></tr>
</table>
<div class=mu style="margin-top:12px">Open your bot in Telegram and send <b>/admin</b> from the admin account to manage it. To stop, restart or delete your bot, contact the admin.</div>
{% if state in ('starting','down','gaveup') %}<script>setTimeout(function(){location.reload()},6000)</script>{% endif %}
</div>
{% elif full %}
<div class=card><div class=hint>Bot creation is full right now. Please contact the admin.</div></div>
{% else %}
<div class=card><h3>{{ic('plus',20)}} Create your own bot</h3>
<div class=mu>Make a bot in <b>@BotFather</b> first, then fill the 3 boxes. Your bot starts in about 5-10 seconds.</div>
<form method=post id=bmf style="margin-top:12px">
<p class=mu style="margin:14px 0 4px">Bot name <span class=mu>(shown everywhere inside the bot)</span></p>
<input name=name maxlength=40 required placeholder="e.g. My Cheat Shop" style="width:100%" autocomplete=off>
<p class=mu style="margin:14px 0 4px">Bot API token <span class=mu>(from @BotFather)</span></p>
<input name=token required placeholder="123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" style="width:100%" autocomplete=off autocapitalize=off spellcheck=false>
<p class=mu style="margin:14px 0 4px">Admin ID <span class=mu>(your Telegram numeric ID - this account becomes the bot's admin)</span></p>
<input name=admin_id required inputmode=numeric pattern="[0-9]{5,15}" placeholder="e.g. 123456789" style="width:100%" autocomplete=off>
<button class=genb id=bmb style="margin-top:18px">{{ic('bot',20)}} CREATE BOT</button>
</form>
<script>document.getElementById('bmf').onsubmit=function(){var b=document.getElementById('bmb');b.disabled=true;b.textContent='Creating... please wait';return true}</script>
</div>
{% endif %}
{% endblock %}"""

ADMIN_PAGE = r"""{% extends 'abase.html' %}{% block c %}<h2>{{ic('bot',24)}} Reseller Bots</h2>
{% if not template_ok %}<div class="flash err">Bot code is missing - upload your bot's main.py below, otherwise no bot can start.</div>{% endif %}
<div class=card><h3>Bot code {% if template_ok %}<span class="pill a">Ready</span>{% else %}<span class="pill e">Missing</span>{% endif %}</h3>
<div class=mu>{% if template_ok %}In use: {{template_info}}. {% endif %}Best: keep <code>bot_main.py</code> next to app.py on GitHub. Or upload main.py here (kept until the next redeploy).</div>
<form method=post action="/admin/bots/code" enctype=multipart/form-data class=row style="margin-top:10px;gap:8px;flex-wrap:wrap"><input type=file name=file accept=".py" required><button class=g>Save bot code</button></form>
<form method=post action="/admin/bots/restart-all" style="margin-top:10px" onsubmit="return confirm('Restart every running bot now?')"><button class=o>Restart all bots (apply new code)</button></form></div>
<div class=card>
<div class=mu>Every bot also gets your admin ID <code>{{owner or 'not set'}}</code> (set in Admin &gt; Telegram) - it is always an admin and cannot be removed inside the bot.</div>
<form method=post class=row style="margin-top:10px"><input type=hidden name=action value=max>
<span class=mu>Max bots allowed:</span><input name=max value="{{maxb}}" inputmode=numeric style="width:90px"><button class=g>Save</button></form>
<div class=row style="margin-top:12px;gap:10px;flex-wrap:wrap">
<a href="/admin/bots/backup"><button type=button class=o>{{ic('save',16)}} Backup all bots (.zip)</button></a>
<form method=post action="/admin/bots/restore" enctype=multipart/form-data class=row style="gap:8px"><input type=file name=file accept=".zip" required><button class=o onclick="return confirm('Restore bots from this backup?')">Restore</button></form></div>
<div class=mu style="margin-top:8px">Render free disk is wiped on every redeploy: download the bots backup after changes and restore it after a redeploy. The backup file contains bot tokens - keep it private.</div>
</div>
{% for b in rows %}{% set s=states[b.instance_id] %}
<div class=card>
<div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center">
<div><b style="font-size:17px">{{b.bot_name}}</b>{% if b.bot_username %} &nbsp;<a href="https://t.me/{{b.bot_username}}" target=_blank rel=noopener>@{{b.bot_username}}</a>{% endif %}
<div class=mu>Reseller: <b>{{b.reseller_name or '-'}}</b> &middot; Admin ID: <code>{{b.admin_id}}</code> &middot; token ...{{b.token_tail}} &middot; made {{b.created|dt}}</div></div>
<div>{% if s=='running' %}<span class="pill a">Running</span>{% elif s=='starting' %}<span class="pill c">Starting</span>{% elif s=='stopped' %}<span class="pill e">Stopped</span>{% elif s=='gaveup' %}<span class="pill e">Crashing</span>{% else %}<span class="pill c">Restarting</span>{% endif %}</div></div>
{% if b.note %}<div class=hint style="margin-top:8px">{{b.note}}</div>{% endif %}
<div class=row style="margin-top:12px;gap:8px;flex-wrap:wrap">
{% if b.desired=='stopped' %}<form method=post action="/admin/bots/{{b.instance_id}}/start"><button class=g>Start</button></form>
{% else %}<form method=post action="/admin/bots/{{b.instance_id}}/stop" onsubmit="return confirm('Stop this bot?')"><button class=r>Stop</button></form>{% endif %}
<form method=post action="/admin/bots/{{b.instance_id}}/restart"><button class=o>Restart</button></form>
<a href="/admin/bots/{{b.instance_id}}/log" target=_blank><button type=button class=o>Log</button></a>
<a href="/admin/bots/{{b.instance_id}}/db.download"><button type=button class=o>{{ic('save',16)}} Database</button></a>
<form method=post action="/admin/bots/{{b.instance_id}}/delete" onsubmit="return confirm('DELETE this bot and its whole database? This cannot be undone.')"><button class=r>{{ic('trash',16)}} Delete</button></form></div>
<form method=post action="/admin/bots/{{b.instance_id}}/db" enctype=multipart/form-data class=row style="margin-top:10px;gap:8px;flex-wrap:wrap" onsubmit="return confirm('Replace this bot database with the uploaded one? The bot restarts. A safety copy of the old database is kept.')">
<span class=mu>Add / restore database (.db or .zip):</span><input type=file name=file accept=".db,.sqlite,.sqlite3,.zip" required><button class=o>Upload</button></form>
</div>
{% else %}<div class=card><span class=mu>No reseller has made a bot yet.</span></div>{% endfor %}
{% endblock %}"""


def install(T, _P):
    _P["bot"] = BOT_ICON
    T["bot_make.html"] = RESELLER_PAGE
    T["admin_bots.html"] = ADMIN_PAGE
    link = '<a href="/bot-make" class="{{\'on\' if page==\'botmake\'}}">{{ic(\'bot\')}} Bot Make</a>\n<a href="/security"'
    assert '<a href="/security"' in T["rbase.html"]
    T["rbase.html"] = T["rbase.html"].replace('<a href="/security"', link, 1)       # directly above Security
    alink = '<a href="/admin/bots" class="{{\'on\' if page==\'bots\'}}">Bots</a><a href="/admin/gateway"'
    assert '<a href="/admin/gateway"' in T["abase.html"]
    T["abase.html"] = T["abase.html"].replace('<a href="/admin/gateway"', alink, 1)
