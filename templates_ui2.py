from templates_ui import _P, ic, CSS, HEAD, FLASH, T as _T

_P.update({
 "bolt": '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
 "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
 "palette": '<circle cx="13.5" cy="6.5" r=".5"/><circle cx="17.5" cy="10.5" r=".5"/><circle cx="8.5" cy="7.5" r=".5"/><circle cx="6.5" cy="12.5" r=".5"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.93 0 1.65-.75 1.65-1.69 0-.44-.18-.83-.44-1.12-.29-.29-.44-.65-.44-1.13a1.64 1.64 0 0 1 1.67-1.67h2c3.05 0 5.55-2.5 5.55-5.55C21.97 6.01 17.46 2 12 2z"/>',
 "qr": '<rect width="5" height="5" x="3" y="3" rx="1"/><rect width="5" height="5" x="16" y="3" rx="1"/><rect width="5" height="5" x="3" y="16" rx="1"/><path d="M21 16h-3a2 2 0 0 0-2 2v3"/><path d="M21 21v.01"/><path d="M12 7v3a2 2 0 0 1-2 2H7"/><path d="M3 12h.01"/><path d="M12 3h.01"/><path d="M12 16v.01"/><path d="M16 12h1"/><path d="M21 12v.01"/><path d="M12 21v-1"/>',
 "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
 "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
 "minus": '<path d="M5 12h14"/>',
 "trash": '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
 "hourglass": '<path d="M5 22h14"/><path d="M5 2h14"/><path d="M17 22v-4.17a2 2 0 0 0-.59-1.41L12 12l-4.41 4.42A2 2 0 0 0 7 17.83V22"/><path d="M7 2v4.17a2 2 0 0 0 .59 1.41L12 12l4.41-4.42A2 2 0 0 0 17 6.17V2"/>',
 "shield2": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.5 3.8 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
 "phone": '<rect width="14" height="20" x="5" y="2" rx="2"/><path d="M12 18h.01"/>',
 "send": '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
})

# ---- theme: recolour the old violet CSS through variables so ONE colour setting re-skins everything
_end = CSS.index("}") + 1
_body = CSS[_end:]
for a, b in (("139,92,246", "var(--acrgb)"), ("34,211,238", "var(--ac2rgb)"), ("#8b5cf6", "var(--ac)"),
             ("#22d3ee", "var(--ac2)"), ("#6366f1", "var(--ac3)"), ("#c4b5fd", "var(--acl)"), ("#a78bfa", "var(--acl)"),
             ("#a5b4fc", "var(--acl)"), ("#67e8f9", "var(--acl2)"), ("#6d28d9", "var(--ac)"), ("#4c1d95", "var(--acd)"),
             ("#04040a", "var(--bg)"), ("rgba(79,70,229,.35)", "rgba(var(--acrgb),.3)")):
    _body = _body.replace(a, b)
ROOT = (":root{--bg:#050a14;--card:rgba(13,22,40,.74);--bd:rgba(var(--acrgb),.28);--tx:#eef2ff;--mu:#8fa0bf;--ok:#10b981;--er:#f43f5e;"
        "--gl:0 0 22px rgba(var(--acrgb),.45);--acrgb:59,130,246;--ac2rgb:34,211,238;--ac:#3b82f6;--ac2:#22d3ee;--ac3:#4f6ef5;"
        "--acl:#93c5fd;--acl2:#67e8f9;--acd:#1e3a8a}")
EXTRA = """
.gcard{border-radius:28px;border:1px solid var(--bd);background:var(--card);overflow:hidden;box-shadow:0 0 40px rgba(var(--acrgb),.14);margin-top:14px}
.gh{display:flex;align-items:center;justify-content:center;gap:12px;padding:22px 12px;font-size:23px;font-weight:800;letter-spacing:.2em;text-transform:uppercase}
.gh .ic{color:var(--ac)}
.gs{text-align:center;padding:16px 10px;color:var(--ac2);background:rgba(var(--acrgb),.09);border-top:1px solid var(--bd);border-bottom:1px solid var(--bd)}
.gb{padding:18px}.gb .l{display:flex;align-items:center;gap:10px;margin:16px 0 10px;font-weight:800;letter-spacing:.08em;font-size:16px;text-transform:uppercase}
.gb .l .ic{color:var(--ac)}
.gb select,.gb .qi{width:100%;padding:16px 16px;border-radius:18px;font-size:18px;border:1.5px solid var(--bd);background:rgba(4,8,18,.88)}
.qty{display:flex;gap:10px;align-items:center}.qty .qi{text-align:center;flex:1;min-width:0}
.sq{width:60px;height:58px;flex:none;border-radius:16px;font-size:28px;padding:0;display:inline-flex;align-items:center;justify-content:center}
.genb{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;padding:17px;border-radius:18px;font-size:18px;font-weight:800;letter-spacing:.16em;margin-top:20px}
.genb .ic{margin:0}
.hd{display:flex;align-items:center;justify-content:center;gap:12px;padding:16px;border-radius:20px;border:1px solid var(--bd);background:var(--card);font-size:24px;font-weight:800;margin-top:14px}
.hd .ic{color:var(--ac)}
.tbl{max-height:62vh;overflow:auto;border-radius:16px;border:1px solid var(--bd);margin-top:12px}
.tbl table{min-width:560px}.tbl th{position:sticky;top:0;background:#101a30;z-index:1;text-align:center;padding:14px 8px}
.tbl td{padding:12px 8px;white-space:nowrap}.tbl td code{border:0;background:none;padding:0;color:var(--acl);display:inline-block;max-width:150px;overflow:hidden;text-overflow:ellipsis;vertical-align:middle}
.pn{display:inline-block;max-width:120px;overflow:hidden;text-overflow:ellipsis;vertical-align:middle;font-weight:700}
.src{display:inline-block;padding:5px 14px;border-radius:9px;border:1.5px solid var(--bd);font-weight:800;font-size:13px;color:var(--acl);background:rgba(var(--acrgb),.16)}
.vd{font-weight:800;color:var(--ac);font-size:13px}
.sbox{position:relative;margin-top:12px}.sbox .ic{position:absolute;left:14px;top:50%;margin-top:-10px;color:var(--ac)}.sbox input{width:100%;padding:15px 14px 15px 46px;border-radius:14px}
.plain{border-radius:22px;border:1px solid var(--bd);padding:16px;margin-top:16px;background:rgba(var(--acrgb),.05)}
.plain h3{font-size:18px}.plain select,.plain input.f{width:100%;margin:6px 0;padding:14px;border-radius:14px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}.two button{display:flex;justify-content:center;align-items:center;padding:14px}
.bal{padding:20px;border-radius:22px;background:linear-gradient(135deg,rgba(var(--acrgb),.75),rgba(var(--ac2rgb),.4));border:1px solid var(--bd);margin:14px 0}
.bal small{letter-spacing:.2em;color:rgba(255,255,255,.8);font-weight:700}.bal b{display:block;font-size:34px;margin:4px 0;color:#fff}
.amts{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:12px 0}
.amt{padding:16px 4px;border-radius:14px;font-size:18px;font-weight:800;background:rgba(var(--acrgb),.12);border:1.5px solid var(--bd);box-shadow:none;color:var(--tx)}
.amt.on{background:linear-gradient(135deg,var(--ac),var(--ac2));color:#fff;box-shadow:0 0 22px rgba(var(--acrgb),.5)}
.qrbox{background:#fff;border-radius:18px;padding:16px;max-width:300px;margin:14px auto}.qrbox img{width:100%;display:block}
.cd{font-size:30px;font-weight:800;text-align:center;color:var(--ac2);letter-spacing:.06em}
.badge{margin-left:auto;background:var(--er);color:#fff;border-radius:20px;padding:1px 9px;font-size:12px;font-weight:800}
.notice{padding:14px;border-radius:14px;border:1px solid var(--bd);background:rgba(var(--acrgb),.1);margin:10px 0;display:block;color:var(--tx)}
.nt{border-radius:16px;border:1px solid var(--bd);background:var(--card);padding:14px;margin:10px 0}.nt.new{border-color:var(--ac2);box-shadow:0 0 18px rgba(var(--ac2rgb),.3)}
.nt b{font-size:16px}.nt p{margin:8px 0 0;white-space:pre-wrap;word-break:break-word}
.modal{display:none;position:fixed;inset:0;background:#000b;z-index:50;align-items:center;justify-content:center;padding:18px}.modal.open{display:flex}
.modal .bx{width:100%;max-width:360px;border-radius:22px;background:#0b1428;border:1px solid var(--bd);padding:20px}
.sw{display:flex;flex-wrap:wrap;gap:12px;margin:14px 0}.sw button{width:42px;height:42px;border-radius:50%;padding:0;border:2px solid rgba(255,255,255,.35);box-shadow:none}
.sw input[type=color]{width:100%;height:46px;padding:2px;border-radius:12px}
"""
SLIM = """
body{font-size:14px}
button,.btn{padding:8px 14px;font-size:14px;border-radius:9px}
input,select,textarea{padding:8px 11px;font-size:14px;border-radius:9px}
.iconbtn{width:40px;height:40px;border-radius:12px}
.tile{width:40px;height:40px;border-radius:12px}
.welcome{padding:16px;border-radius:20px}.welcome .tile{width:48px;height:48px;border-radius:14px}.welcome h1{font-size:22px}
.balrow{padding:11px;margin-top:12px}.balrow b{font-size:26px}.balrow .tile{width:36px;height:36px}
.gen{padding:11px;font-size:14px;border-radius:12px;margin-top:12px}
.kpi{padding:13px 8px;border-radius:15px}.kpi b{font-size:26px}.kpi .tile{width:36px;height:36px;margin-bottom:7px}.kpi span{font-size:11px}
.wide{padding:14px 8px}.wide b{font-size:28px}
.krow{padding:10px 12px}.krow .tile{width:38px;height:38px}
.sec h3{font-size:16px}
.gh{font-size:19px;padding:16px 10px;letter-spacing:.16em}
.gcard{border-radius:22px}.gs{padding:11px 10px;font-size:13px}.gb{padding:14px}
.gb .l{font-size:13px;margin:13px 0 8px}
.gb select,.gb .qi{padding:11px 14px;font-size:15px;border-radius:13px}
.sq{width:46px;height:44px;font-size:22px;border-radius:12px}
.genb{padding:12px;font-size:15px;border-radius:13px;letter-spacing:.1em;margin-top:16px}
.hd{font-size:19px;padding:12px;border-radius:16px}
.sbox input{padding:10px 12px 10px 42px}
.tbl th{padding:10px 8px}.tbl td{padding:9px 8px}
.plain{padding:13px;border-radius:18px}.plain select,.plain input.f{padding:10px;border-radius:11px}
.two button{padding:10px}
.amt{padding:11px 4px;font-size:15px;border-radius:12px}
.bal{padding:15px;border-radius:18px}.bal b{font-size:28px}
.side{padding:16px}.side a{padding:9px 12px;font-size:14px;border-radius:9px}
.top{padding:9px 12px}.player{padding:2px 6px}
.cp{padding:5px!important}
.lg .box{padding:24px 20px 20px;border-radius:26px}.lg .logo-t{width:56px;height:56px;border-radius:16px;margin-bottom:10px}
.lg h1{font-size:24px}.lg .tag{padding:7px 14px;font-size:13px;margin-bottom:16px}
.lg label{font-size:14px;margin:11px 0 6px}.lg .fld{border-radius:12px}.lg .fld input{padding:11px 0;font-size:15px}
.lg .go{padding:12px;font-size:14px;border-radius:12px}
.card{padding:15px;border-radius:14px}
h2{font-size:21px}
"""
CSS2 = ROOT + _body + EXTRA + SLIM

THEME_JS = r"""
(function(){function h2r(h){h=h.replace('#','');return[0,2,4].map(function(i){return parseInt(h.substr(i,2),16)})}
function toHsl(r,g,b){r/=255;g/=255;b/=255;var M=Math.max(r,g,b),m=Math.min(r,g,b),l=(M+m)/2,s=0,h=0;if(M!=m){var d=M-m;s=l>.5?d/(2-M-m):d/(M+m);h=M==r?(g-b)/d+(g<b?6:0):M==g?(b-r)/d+2:(r-g)/d+4;h*=60}return[h,s,l]}
function fromHsl(h,s,l){h=((h%360)+360)%360;var a=s*Math.min(l,1-l);function f(n){var k=(n+h/30)%12;return Math.round(255*(l-a*Math.max(-1,Math.min(k-3,9-k,1))))}return[f(0),f(8),f(4)]}
function hex(c){return'#'+c.map(function(x){return('0'+x.toString(16)).slice(-2)}).join('')}
function ck(){var m=document.cookie.match(/(?:^|; )rg_theme=([0-9a-fA-F]{6})/);return m?'#'+m[1]:''}
window.applyTheme=function(c){if(!/^#[0-9a-f]{6}$/i.test(c||''))return false;var r=h2r(c),H=toHsl(r[0],r[1],r[2]),s=document.documentElement.style,S=Math.max(H[1],.55);
var a2=fromHsl(H[0]+40,S,.6),a3=fromHsl(H[0]+15,S,.58);
s.setProperty('--acrgb',r.join(','));s.setProperty('--ac',c);s.setProperty('--ac2',hex(a2));s.setProperty('--ac2rgb',a2.join(','));s.setProperty('--ac3',hex(a3));
s.setProperty('--acl',hex(fromHsl(H[0],S,.8)));s.setProperty('--acl2',hex(fromHsl(H[0]+40,S,.8)));s.setProperty('--acd',hex(fromHsl(H[0],S,.25)));return true};
window.saveTheme=function(c){try{localStorage.rgtheme=c}catch(e){}document.cookie='rg_theme='+c.slice(1)+';path=/;max-age=31536000;SameSite=Lax'};
window.initTheme=function(server){var c=server||ck()||(function(){try{return localStorage.rgtheme}catch(e){return ''}})();if(applyTheme(c))saveTheme(c)};
})();
"""

T = dict(_T)
for k in ("login.html", "rbase.html", "abase.html"):
    T[k] = T[k].replace(CSS, CSS2)
T["login.html"] = T["login.html"].replace("</style></head>", "</style><script>" + THEME_JS + "initTheme('');try{['mu','mt','mp','ts'].forEach(function(k){sessionStorage.removeItem(k)})}catch(e){}</script></head>", 1)

# ---------------------------------------------------------------- reseller base
T["rbase.html"] = HEAD + """Reseller Panel</title><style>""" + CSS2 + """</style><script>""" + THEME_JS + """initTheme({{(r.theme or '')|tojson}});</script></head><body>
<div class="shade" id=shade></div>
<div class="side" id=side><div class=sidehd><span class=tile>{{ic('crown',22)}}</span><div><b class=logo>{{BRAND}}</b><div class=mu>{{r.username}}</div></div></div>
<div class=mu style="margin:8px 0 0">Balance: <b style="color:#34d399" id=sbal>{{r.balance|cur}}</b></div><hr style="border:0;border-top:1px solid var(--bd);margin:14px 0">
<a href="/dashboard" class="{{'on' if page=='dashboard'}}">{{ic('dash')}} Dashboard</a>
<a href="/generate" class="{{'on' if page=='generate'}}">{{ic('bolt')}} Generate Key</a>
<a href="/history" class="{{'on' if page=='history'}}">{{ic('history')}} Key History</a>
<a href="/wallet" class="{{'on' if page=='wallet'}}">{{ic('wallet')}} Add Balance</a>
<a href="/security" class="{{'on' if page=='security'}}">{{ic('shield2')}} Security</a>
<a href="/broadcast" class="{{'on' if page=='broadcast'}}">{{ic('bell')}} Broadcast{% if unread and page!='broadcast' %}<span class=badge>{{unread}}</span>{% endif %}</a>
<a href="/api-docs" class="{{'on' if page=='api'}}">{{ic('code')}} API &amp; Docs</a>
<a href="/logout">{{ic('logout')}} Logout</a></div>
<div class="top"><button class="iconbtn" id=bg aria-label="Menu">{{ic('menu',22)}}</button>
<div class="player" id=pl><button id=pv aria-label="Previous">{{ic('prev',16)}}</button><button id=pp aria-label="Play">{{ic('play',16)}}</button><button id=nx aria-label="Next">{{ic('next',16)}}</button><span id=ttl>…</span><audio id=au preload=auto></audio></div>
<button class="iconbtn" id=pal aria-label="Colour" style="margin-left:auto">{{ic('palette',22)}}</button></div>
<div class="modal" id=mod><div class=bx><h3>{{ic('palette',20)}} Portal colour</h3><div class=mu>Your colour is saved and used on the login page too.</div>
<div class="sw" id=sw></div><input type=color id=cc value="#3b82f6" style="width:100%;height:46px;padding:2px;border-radius:12px"><button class="o" id=mx style="margin-top:14px;width:100%">Close</button></div></div>
<div class="wrap">""" + FLASH + """{% if unread and page!='broadcast' %}<a class=notice href="/broadcast">{{ic('bell',18)}} You have {{unread}} new notice{{'s' if unread>1}} from admin &rarr;</a>{% endif %}{% block c %}{% endblock %}</div>
<script>
const PLAY='{{ic('play',16)|e}}',PAUSE='{{ic('pause',16)|e}}';
const S=document.getElementById('side'),H=document.getElementById('shade');
function tg(){S.classList.toggle('open');H.classList.toggle('open')}bg.onclick=tg;H.onclick=tg;
document.addEventListener('click',e=>{const b=e.target.closest('[data-copy]');if(!b)return;navigator.clipboard&&navigator.clipboard.writeText(b.dataset.copy);b.style.color='#34d399';setTimeout(()=>b.style.color='',900)});
const COLS=['#3b82f6','#06b6d4','#10b981','#8b5cf6','#ec4899','#f43f5e','#f97316','#eab308'];
COLS.forEach(c=>{const b=document.createElement('button');b.style.background=c;b.onclick=()=>pick(c);sw.appendChild(b)});
function pick(c){applyTheme(c);saveTheme(c);cc.value=c;const f=new FormData();f.append('color',c);fetch('/theme',{method:'POST',body:f})}
cc.onchange=()=>pick(cc.value);pal.onclick=()=>mod.classList.add('open');mx.onclick=()=>mod.classList.remove('open');mod.onclick=e=>{if(e.target===mod)mod.classList.remove('open')};
(async()=>{let L=[];try{L=await(await fetch('/music.json')).json()}catch(e){}
if(!L.length){pl.style.display='none';return}
const ss=sessionStorage;let i=0;
if(ss.mu){const k=L.findIndex(x=>x.url===ss.mu);i=k>=0?k:0}else{i=+localStorage.mi||0;if(i>=L.length)i=0}
let leaving=false;
function save(){try{ss.mu=L[i].url;ss.mt=au.currentTime||0;if(!au.paused)ss.ts=Date.now()}catch(e){}}
function load(n,seek){i=(n+L.length)%L.length;au.src=L[i].url;ttl.textContent=L[i].title;localStorage.mi=i;
 return new Promise(res=>{au.addEventListener('loadedmetadata',()=>{if(seek>0){try{au.currentTime=seek}catch(e){}}res()},{once:true})})}
function play(){return au.play().catch(()=>{pp.innerHTML=PLAY;arm()})}
function arm(){['pointerdown','keydown','touchstart'].forEach(ev=>document.addEventListener(ev,()=>{if(au.paused&&ss.mp!=='0')play()},{once:true}))}
au.onplay=()=>{pp.innerHTML=PAUSE;ss.mp=1};au.onpause=()=>{pp.innerHTML=PLAY;if(!au.ended&&!leaving)ss.mp=0};
au.ontimeupdate=save;
['pagehide','beforeunload'].forEach(ev=>addEventListener(ev,()=>{leaving=true;save()}));
pp.onclick=()=>au.paused?play():au.pause();
nx.onclick=async()=>{await load(i+1,0);play()};pv.onclick=async()=>{await load(i-1,0);play()};
au.onended=async()=>{await load(i+1,0);play()};
let t=+ss.mt||0;if(ss.mp==='1'&&ss.ts){const d=(Date.now()-ss.ts)/1000;if(d<8)t+=d}
await load(i,t);
if(ss.mp!=='0')play();else pp.innerHTML=PLAY;
})();
</script></body></html>"""

# ---------------------------------------------------------------- key generator
T["generate.html"] = r"""{% extends 'rbase.html' %}{% block c %}
<div class=gcard><div class=gh>{{ic('bolt',28)}} Key Generator</div><div class=gs>Generate licence keys for your customers</div>
<div class=gb>
<div class=l>{{ic('box',22)}} Product type</div><select id=sp></select>
<div class=l>{{ic('hourglass',22)}} Validity</div><select id=sl></select>
<div class=l>{{ic('user',22)}} Quantity</div>
<div class=qty><button type=button class=sq id=qm>{{ic('minus',20)}}</button><input class=qi id=qn type=number inputmode=numeric min=1 max=500 value=1><button type=button class=sq id=qp>{{ic('plus',20)}}</button></div>
<div class=mu style="margin-top:12px;text-align:center">Total <b id=tot></b> &middot; Balance <b id=bl style="color:#34d399">{{r.balance|cur}}</b> &middot; <a href="/wallet">Add balance</a></div>
<button class="genb" id=go>{{ic('bolt',22)}} GENERATE KEYS</button></div></div>
<div class="plain" id=res hidden><h3>{{ic('key',20)}} Generated keys</h3><div class=mu id=st></div>
<textarea id=out readonly style="min-height:130px;margin-top:8px"></textarea>
<div class=two><button id=cpall>{{ic('copy',18)}} Copy all</button><a class="btn o" href="/history" style="text-align:center;border:1px solid var(--bd);background:none;box-shadow:none">{{ic('history',18)}} History</a></div></div>
<script>
const C={{cat|tojson}},CU='{{CURRENCY}}',$=i=>document.getElementById(i);let bal={{r.balance}};
const sp=$('sp'),sl=$('sl'),qn=$('qn');
C.forEach((p,i)=>sp.add(new Option(p.name,i)));
function plan(){const p=C[sp.value];return p&&p.plans.find(x=>x.id==sl.value)}
function qty(){return Math.max(1,Math.min(500,parseInt(qn.value)||1))}
function upd(){const x=plan();$('tot').textContent=x?CU+(Math.round(x.price*qty()*100)/100):'-'}
function fill(){sl.innerHTML='';const p=C[sp.value];if(!p)return;let first=-1;p.plans.forEach((x,i)=>{const out=x.mode==='stock'&&x.stock==0;const o=new Option(x.name.toUpperCase()+' - '+CU+x.price+(out?' (out of stock)':''),x.id);o.disabled=out;sl.add(o);if(!out&&first<0)first=i});if(first>=0)sl.selectedIndex=first;upd()}
sp.onchange=fill;sl.onchange=upd;qn.oninput=upd;
$('qm').onclick=()=>{qn.value=Math.max(1,qty()-1);upd()};$('qp').onclick=()=>{qn.value=Math.min(500,qty()+1);upd()};
function setBal(b){bal=b;$('bl').textContent=CU+(Math.round(b*100)/100);const s=$('sbal');if(s)s.textContent=CU+(Math.round(b*100)/100)}
$('cpall').onclick=()=>{navigator.clipboard&&navigator.clipboard.writeText($('out').value)};
$('go').onclick=async()=>{const x=plan(),n=qty();if(!x)return;
 if(n>=10&&!confirm('Generate '+n+' keys for '+CU+(Math.round(x.price*n*100)/100)+'?'))return;
 const go=$('go');go.disabled=true;$('res').hidden=false;$('out').value='';let ok=0,err='';
 for(let k=0;k<n;k++){$('st').textContent='Generating '+(k+1)+' / '+n+' …';
  try{const f=new FormData();f.append('plan_id',x.id);const j=await(await fetch('/generate/one',{method:'POST',body:f})).json();
   if(!j.ok){err=j.error;break}$('out').value+=($('out').value?'\n':'')+j.key;ok++;setBal(j.balance)}catch(e){err='Network error';break}}
 $('st').textContent=ok+' key'+(ok==1?'':'s')+' generated'+(err?' — stopped: '+err:'')+' · '+x.name;go.disabled=false};
fill();
</script>{% endblock %}"""

# ---------------------------------------------------------------- key history
T["history.html"] = r"""{% extends 'rbase.html' %}{% block c %}
<div class=hd>{{ic('history',26)}} KEY HISTORY</div>
<div class=sbox>{{ic('search',20)}}<input id=sq placeholder="Search keys, products, dates..." autocomplete=off></div>
<div class=tbl><table><tr><th>KEY</th><th>PRODUCT</th><th>SRC</th><th>VALID</th><th>TIME</th></tr><tbody id=tb>
{% for x in rows %}<tr data-s="{{(x.key~' '~x.product_name~' '~x.plan_name~' '~(x.via or 'panel')~' '~(x.created|dt2))|lower}}">
<td><code>{{x.key}}</code></td><td><span class=pn>{{x.product_name}}</span></td><td><span class=src>{{(x.via or 'panel')|upper}}</span></td>
<td><span class=vd>{{x.plan_name|upper}}</span></td><td>{{x.created|dt2}} <button class=cp data-copy="{{x.key}}" aria-label="Copy key">{{ic('copy',15)}}</button></td></tr>
{% else %}<tr><td colspan=5 class=mu style="text-align:center">No keys generated yet.</td></tr>{% endfor %}</tbody></table></div>
<div class=mu style="text-align:center;margin:12px 0;font-weight:700"><span id=shown>{{rows|length}}</span> of {{total}} keys shown<br><span style="font-weight:400">Search covers your newest {{rows|length}} keys.</span></div>
<div class=plain><h3>{{ic('key',20)}} Plaintext keys</h3>
<input class=f id=pf placeholder="Filter keys (key or product)..." autocomplete=off>
<select id=pn>{% for n in opts %}<option value="{{n}}">Last {{n}}</option>{% endfor %}<option value="0" {{'selected' if not opts}}>All keys ({{total}})</option></select>
<button id=get style="margin-top:8px">{{ic('bolt',18)}} Get</button>
<textarea id=pt readonly placeholder="Your keys appear here — one per line, ready to copy or send." style="min-height:180px;margin-top:10px"></textarea>
<div class=two><button id=ca>{{ic('copy',18)}} Copy all</button><button id=dl>{{ic('download',18)}} Download .txt</button></div></div>
<script>
const sq=document.getElementById('sq');sq.oninput=()=>{const v=sq.value.trim().toLowerCase();let n=0;document.querySelectorAll('#tb tr[data-s]').forEach(r=>{const m=!v||r.dataset.s.includes(v);r.style.display=m?'':'none';if(m)n++});document.getElementById('shown').textContent=n};
const pt=document.getElementById('pt');
document.getElementById('get').onclick=async()=>{const j=await(await fetch('/history/plain?n='+pn.value+'&q='+encodeURIComponent(pf.value))).json();pt.value=j.text;pt.placeholder=j.count?'':'No keys found.'};
document.getElementById('ca').onclick=()=>{if(pt.value)navigator.clipboard&&navigator.clipboard.writeText(pt.value)};
document.getElementById('dl').onclick=async()=>{if(!pt.value)document.getElementById('get').click(),await new Promise(r=>setTimeout(r,700));if(!pt.value)return;
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([pt.value],{type:'text/plain'}));a.download='keys_'+pt.value.split('\n').length+'.txt';a.click()};
</script>{% endblock %}"""

# ---------------------------------------------------------------- wallet
T["wallet.html"] = r"""{% extends 'rbase.html' %}{% block c %}
<h2 style="margin-top:14px">Add balance</h2><div class=mu>Choose an amount, then pay securely by UPI.</div>
<div class=bal><small>AVAILABLE BALANCE</small><b>{{r.balance|cur}}</b><span style="color:rgba(255,255,255,.85)">Successful payments credit automatically after verification.</span></div>
{% if not ready %}<div class="flash err">Payments are not set up yet. Please contact admin.</div>{% endif %}
<form class=card method=post action="/wallet/create"><h3>{{ic('qr',22)}} Select amount</h3>
<div class=amts>{% for a in amts %}<button type=button class="amt {{'on' if a==500}}" data-a="{{a}}">{{CURRENCY}}{{a}}</button>{% endfor %}</div>
<input type=hidden name=amount id=am value=500>
<button class=genb style="font-size:16px;letter-spacing:.06em" {{'disabled' if not ready}}>{{ic('qr',20)}} Continue with UPI</button></form>
<script>document.querySelectorAll('.amt').forEach(b=>b.onclick=()=>{document.querySelectorAll('.amt').forEach(x=>x.classList.remove('on'));b.classList.add('on');document.getElementById('am').value=b.dataset.a})</script>
{% if tops %}<div class=card><h3>{{ic('history',20)}} Recent top-ups</h3><div class=tw><table>
{% for t in tops %}<tr><td>{{t.created|dt}}</td><td><b>{{t.amount|cur}}</b></td><td>{% if t.status=='paid' %}<span class="pill a">Paid</span>{% elif t.status=='pending' %}<a class="pill c" href="/wallet/pay/{{t.id}}">Pending</a>{% else %}<span class="pill e">Expired</span>{% endif %}</td></tr>{% endfor %}</table></div></div>{% endif %}{% endblock %}"""

T["wallet_pay.html"] = r"""{% extends 'rbase.html' %}{% block c %}
<h2 style="margin-top:14px">Add wallet balance</h2><div class=mu>Pay by UPI; balance credits only after secure verification.</div>
<a class="btn o" href="/wallet" style="margin:12px 0;background:none;border:1px solid var(--bd);box-shadow:none">Back to wallet</a>
<div class=card style="text-align:center"><div class=mu style="text-align:left">Pending top-up<br>{{t.order_id}}</div><div style="font-size:38px;font-weight:800;text-align:left">{{CURRENCY}}{{t.amount|money}}</div>
<div id=wait {{'hidden' if t.status!='pending'}}>
<div class=qrbox><img src="{{t.qr_url}}" alt="UPI QR"></div>
<div>Scan and pay <b>{{CURRENCY}}{{t.amount|money}}</b> to add it to your wallet.</div>
{% if t.upi_id %}<div class=mu style="margin-top:6px">UPI ID: <code>{{t.upi_id}}</code></div>{% endif %}
<div class=cd id=cd style="margin:10px 0">--:--</div>
<a class=btn href="/wallet/qr/{{t.id}}" style="margin:6px 0">{{ic('download',18)}} Download QR</a>
<p class=mu>Download the QR to pay from another device. Verification runs automatically for 5 minutes, even after you leave this page.</p></div>
<div id=ok {{'hidden' if t.status!='paid'}}><div style="font-size:54px">✅</div><h3 style="justify-content:center">Payment successful</h3><div class=mu>{{CURRENCY}}{{t.amount|money}} added. New balance: <b id=nb style="color:#34d399">{{r.balance|cur}}</b></div>
<a class=btn href="/generate" style="margin-top:12px">{{ic('bolt',18)}} Generate keys</a></div>
<div id=ex {{'hidden' if t.status!='expired'}}><h3 style="justify-content:center">QR expired</h3><div class=mu>If you already paid, it is still checked for a while. Otherwise create a new QR.</div><a class=btn href="/wallet" style="margin-top:12px">New payment</a></div></div>
<script>
let left={{left}};const $=i=>document.getElementById(i),CU='{{CURRENCY}}';
function show(s,b){if(s==='paid'){$('wait').hidden=true;$('ex').hidden=true;$('ok').hidden=false;$('nb').textContent=CU+(Math.round(b*100)/100);const e=$('sbal');if(e)e.textContent=CU+(Math.round(b*100)/100);clearInterval(T1);clearInterval(T2)}else if(s==='expired'){$('wait').hidden=true;$('ex').hidden=false}}
function tick(){if(left>0)left--;const m=Math.floor(left/60),s=left%60;$('cd').textContent=String(m).padStart(2,'0')+':'+String(s).padStart(2,'0')}
async function poll(){try{const j=await(await fetch('/wallet/status/{{t.id}}')).json();show(j.status,j.balance)}catch(e){}}
let T1,T2;if(!$('wait').hidden){tick();T1=setInterval(tick,1000);T2=setInterval(poll,4000)}
</script>{% endblock %}"""

# ---------------------------------------------------------------- broadcast (reseller)
T["broadcast.html"] = r"""{% extends 'rbase.html' %}{% block c %}<div class=hd>{{ic('bell',26)}} BROADCAST</div>
{% for x in rows %}<div class="nt {{'new' if not x.rd}}"><div style="display:flex;justify-content:space-between;gap:8px"><b>{{x.title or 'Notice'}}</b>{% if not x.rd %}<span class="pill c">NEW</span>{% endif %}</div>
<div class=mu>{{x.created|dt}}{% if x.reseller_id %} &middot; personal{% endif %}</div><p>{{x.body}}</p></div>
{% else %}<div class=card style="text-align:center" ><span class=mu>No notices yet.</span></div>{% endfor %}{% endblock %}"""

# ---------------------------------------------------------------- admin
T["abase.html"] = T["abase.html"].replace('<a href="/admin/music"',
    '<a href="/admin/gateway" class="{{\'on\' if page==\'gateway\'}}">Gateway</a><a href="/admin/broadcast" class="{{\'on\' if page==\'broadcast\'}}">Broadcast</a><a href="/admin/music"', 1)

T["admin_gateway.html"] = r"""{% extends 'abase.html' %}{% block c %}<h2>{{ic('qr',24)}} Payment Gateway</h2>
<div class=card><form method=post><input type=hidden name=action value=save>
<p class=mu>Gateway URL</p><input name=base value="{{base}}" style="width:100%" required>
<p class=mu>UPI ID (your receiving ID, for your reference)</p><input name=upi value="{{upi}}" placeholder="yourid@fam" style="width:100%">
<p class=mu>API Token{% if tail %} &mdash; saved (ends with <code>{{tail}}</code>). Leave empty to keep it.{% endif %}</p>
<input name=token type=password autocomplete=off placeholder="FAM_xxxxxxxx" style="width:100%" {{'' if tail else 'required'}}>
<button class=g style="margin-top:12px">{{ic('save')}} Save</button></form></div>
<div class=card><h3>Test QR</h3><p class=mu>Creates a {{CURRENCY}}1 test order to check that the UPI ID + token work. Nothing is credited.</p>
<form method=post><input type=hidden name=action value=test><button>{{ic('qr')}} Generate test QR</button></form>
{% if test %}{% if test.ok %}<div class="flash ok">QR created successfully. Order {{test.order}}{% if test.upi %} &middot; UPI {{test.upi}}{% endif %}</div><div style="background:#fff;padding:12px;border-radius:12px;max-width:230px"><img src="{{test.qr}}" style="width:100%"></div>
{% else %}<div class="flash err">Failed: {{test.msg}}</div>{% endif %}{% endif %}</div>
<div class="card tw"><h3>Recent top-ups</h3><table><tr><th>Reseller</th><th>Amount</th><th>Status</th><th>UTR</th><th>Time</th></tr>
{% for t in tops %}<tr><td>{{t.username}}</td><td>{{t.amount|cur}}</td><td>{{t.status}}</td><td>{{t.utr or ''}}</td><td>{{t.created|dt}}</td></tr>{% else %}<tr><td colspan=5>None yet</td></tr>{% endfor %}</table></div>{% endblock %}"""

T["admin_broadcast.html"] = r"""{% extends 'abase.html' %}{% block c %}<h2>{{ic('bell',24)}} Broadcast</h2>
<div class=card><form method=post><input type=hidden name=action value=send>
<p class=mu>Send to</p><select name=target><option value=all>All resellers</option>{% for x in rs %}<option value="{{x.id}}">{{x.username}}</option>{% endfor %}</select>
<p class=mu>Title (optional)</p><input name=title style="width:100%"><p class=mu>Message</p><textarea name=body required></textarea>
<button class=g style="margin-top:10px">{{ic('send')}} Broadcast</button></form></div>
<div class="card tw"><h3>Sent</h3><table><tr><th>To</th><th>Message</th><th>Time</th><th></th></tr>
{% for x in rows %}<tr><td>{{x.username or 'ALL'}}</td><td><b>{{x.title}}</b><div class=mu style="white-space:pre-wrap">{{x.body}}</div></td><td>{{x.created|dt}}</td>
<td><form method=post><input type=hidden name=action value=delete><input type=hidden name=id value="{{x.id}}"><button class=r>{{ic('trash',16)}}</button></form></td></tr>{% else %}<tr><td colspan=4>Nothing sent yet</td></tr>{% endfor %}</table></div>{% endblock %}"""

# ================================================================ v6: login verification, devices, security, telegram
LGHEAD = HEAD + """{{BRAND}} - {{title}}</title><style>""" + CSS2 + """</style><script>""" + THEME_JS + """initTheme('');</script></head><body>
<div class="lg"><div class="box">"""
LGFOOT = """<div class="copy">&copy; {{year}} {{BRAND}}</div></div></div>"""

T["login_wait.html"] = LGHEAD + """<div class="logo-t">{{ic('hourglass',30)}}</div><h1>Approval needed</h1><div class="dv"><i></i><u></u><i></i></div>
<div class="tag">{{ic('shield2',18)}} New device</div>""" + FLASH + """
<p class=mu style="text-align:center;margin:0 0 14px">Your password is correct. The admin was asked to approve this device.<br>Keep this page open &mdash; you will enter automatically.</p>
<div class="cd" id=st style="font-size:18px">Waiting for admin&hellip;</div>
<a class="btn" href="/login/cancel" style="display:block;text-align:center;margin-top:16px;background:none;border:1px solid var(--bd);box-shadow:none">Cancel</a>
<script>
async function p(){try{const j=await(await fetch('/login/status',{cache:'no-store'})).json();
 if(j.status==='approved'||j.status==='denied'||j.status==='gone'){location.href=j.next;return}
 if(j.status==='expired'){document.getElementById('st').textContent='Request expired. Please login again.';setTimeout(()=>location.href=j.next,2500);return}}catch(e){}
 setTimeout(p,3000)}
p();
</script>""" + LGFOOT + "</body></html>"

T["login_verify.html"] = LGHEAD + """<div class="logo-t">{{ic('shield2',30)}}</div><h1>Verification</h1><div class="dv"><i></i><u></u><i></i></div>
<div class="tag">{{ic('send',18)}} Code sent to Telegram{% if tg_mask %} &middot; ID {{tg_mask}}{% endif %}</div>""" + FLASH + """
<form method=post autocomplete=off>
<label for=cd>Enter the 6-digit code</label>
<div class="fld">{{ic('lock',20)}}<input id=cd name=code inputmode=numeric pattern="[0-9]{6}" maxlength=6 minlength=6 placeholder="000000" required autofocus autocomplete=one-time-code style="letter-spacing:.4em;font-weight:800;font-size:20px"></div>
<div class="sess">{{ic('hourglass',16)}} Code expires in 5 minutes</div>
<div class="sess" id=ds style="color:#fbbf24">Sending the code to Telegram&hellip;</div>
<button class="go">VERIFY {{ic('arrow',20)}}</button></form>
<form method=post style="margin-top:12px"><input type=hidden name=action value=resend>
<button class="o" style="width:100%;background:none;border:1px solid var(--bd);box-shadow:none">Resend code</button></form>
<a href="/login/cancel" style="display:block;text-align:center;margin-top:14px;font-size:13px">&larr; Back to login</a>
<script>
var n=0;async function ps(){var d=document.getElementById('ds');try{var j=await(await fetch('/login/otp_status',{cache:'no-store'})).json();
 if(j.state==='ok'){d.style.color='#34d399';d.textContent='Code delivered to your Telegram';return}
 if(j.state==='fail'){d.style.color='#f87171';d.textContent='Could not send the code: '+j.err+' - press Resend, or tell the admin.';return}
 if(j.state==='gone'){location.href='/login';return}}catch(e){}
 if(++n>25){d.textContent='Telegram is slow... press Resend if the code does not arrive.';return}
 setTimeout(ps,1200)}
ps();
</script>""" + LGFOOT + "</body></html>"

T["blocked.html"] = """<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><meta name=theme-color content="#450a0a"><title>Access blocked</title>
<style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:18px;font:15px/1.5 system-ui,Segoe UI,Arial,sans-serif;color:#fff;
background:radial-gradient(70% 60% at 50% 0%,#7f1d1d,#1c0505 70%)}
.b{width:100%;max-width:400px;text-align:center;padding:30px 22px;border-radius:26px;background:rgba(127,29,29,.35);border:2px solid #ef4444;box-shadow:0 0 60px rgba(239,68,68,.45);animation:p 1.6s ease-in-out infinite}
@keyframes p{50%{box-shadow:0 0 90px rgba(239,68,68,.75)}}
.i{width:74px;height:74px;margin:0 auto 14px;border-radius:50%;background:#ef4444;display:flex;align-items:center;justify-content:center;font-size:40px;font-weight:800}
h1{margin:0 0 8px;font-size:22px;letter-spacing:.06em}p{margin:6px 0;color:#fecaca}.s{margin-top:16px;font-size:12px;color:#fca5a5}</style></head>
<body><div class=b><div class=i>!</div><h1>ACCESS BLOCKED</h1>
<p><b>{{msg or 'This device is not authorised.'}}</b></p>
<p>Login is not available from this device. If this is your own device, contact the admin.</p>
<div class=s>Device ID not recognised &middot; {{BRAND}}</div></div></body></html>"""

T["security.html"] = r"""{% extends 'rbase.html' %}{% block c %}
<div class=hd>{{ic('shield2',24)}} SECURITY</div>

<div class=card><h3>{{ic('send',20)}} Telegram</h3>
{% if tg_mask %}<span class="pill a">Linked</span> <span class=mu>Chat ID {{tg_mask}}</span>
{% else %}<span class="pill e">Not linked</span><div class=mu style="margin-top:6px">Open the bot, press <b>Start</b>, copy your Chat ID and give it to the admin.</div>{% endif %}
{% if not bot_ready %}<div class=hint>The bot is not set up by admin yet.</div>{% endif %}</div>

<div class=card><h3>{{ic('lock',20)}} Login verification code</h3>
<div class=mu>When ON, a 6-digit code is sent to your Telegram after you enter username &amp; password.</div>
<div style="margin:10px 0">{% if r.otp_on %}<span class="pill a">ON</span>{% else %}<span class="pill e">OFF</span>{% endif %}</div>
{% if r.otp_on %}<form method=post class=row onsubmit="return confirm('Turn OFF login verification?')"><input type=hidden name=action value=otp_off>
<input type=password name=password placeholder="Your password to confirm" required style="flex:1;min-width:160px"><button class=r>Turn OFF</button></form>
{% else %}<form method=post><input type=hidden name=action value=otp_on><button class=g {{'disabled' if not tg_mask}}>Turn ON</button></form>{% endif %}</div>

<div class=card><h3>{{ic('bell',20)}} Telegram alerts</h3>
<form method=post><input type=hidden name=action value=alerts>
<label class=mu style="display:flex;gap:8px;align-items:center"><input type=checkbox name=notify value=1 {{'checked' if r.notify}} style="width:auto"> Send me an alert for every purchase / balance added</label>
<p class=mu style="margin:12px 0 4px">Low balance alert when wallet goes below ({{CURRENCY}}) &mdash; 0 = off</p>
<input name=low_bal type=number step=any min=0 value="{{r.low_bal|money}}" style="width:140px">
<div><button class=g style="margin-top:12px">{{ic('save',16)}} Save</button></div></form>
<form method=post style="margin-top:10px"><input type=hidden name=action value=test_alert><button class=o {{'disabled' if not tg_mask}}>{{ic('send',16)}} Send me a test alert</button></form></div>

<div class=card><h3>{{ic('phone',20)}} My devices</h3>
<div class=mu>Only devices approved by admin can open the panel.</div>
<div class=tw><table>{% for d in devs %}<tr><td>{{d.label}}<div class=mu>{{d.ip}}</div></td>
<td>{% if d.status=='approved' %}<span class="pill a">Approved</span>{% elif d.status=='pending' %}<span class="pill c">Pending</span>{% else %}<span class="pill e">Rejected</span>{% endif %}{% if d.dev_id==cur_dev %} <span class="pill p">This device</span>{% endif %}
<div class=mu>{% if d.last_seen %}Last used {{d.last_seen|dt}}{% endif %}</div></td>
<td><form method=post onsubmit="return confirm('Remove this device?')"><input type=hidden name=action value=rm_device><input type=hidden name=id value="{{d.id}}"><button class="r cp" style="color:#fff">{{ic('trash',16)}}</button></form></td></tr>
{% else %}<tr><td class=mu>No devices yet.</td></tr>{% endfor %}</table></div></div>{% endblock %}"""

# ---- admin: Telegram + Devices pages, nav links
T["abase.html"] = T["abase.html"].replace('<a href="/admin/gateway"',
    '<a href="/admin/telegram" class="{{\'on\' if page==\'telegram\'}}">Telegram</a><a href="/admin/devices" class="{{\'on\' if page==\'devices\'}}">Devices</a><a href="/admin/gateway"', 1)

T["admin_telegram.html"] = r"""{% extends 'abase.html' %}{% block c %}<h2>{{ic('send',24)}} Telegram Bot</h2>
<div class=card><h3>Status</h3>
{% if me %}<span class="pill a">Bot connected</span> <b>@{{me.username}}</b>{% elif has_token %}<span class="pill e">Token saved but Telegram rejected it</span>{% else %}<span class="pill e">Not set up</span>{% endif %}
<div style="margin-top:8px">Device approval: {% if active %}<span class="pill a">ACTIVE</span>{% else %}<span class="pill p">OFF</span>{% endif %}
<span class=mu> (active when bot token + your Chat ID are set and the switch below is on)</span></div></div>
<div class=card><form method=post><input type=hidden name=action value=save>
<p class=mu>Bot token (from @BotFather){% if has_token %} &mdash; saved (ends with <code>{{tail}}</code>). Leave empty to keep it.{% endif %}{% if env_tok %} <b>(set inside app.py / env, it wins)</b>{% endif %}</p>
<input name=token type=password autocomplete=off placeholder="123456789:AAH..." style="width:100%">
<p class=mu>Your (admin) Telegram Chat ID &mdash; or simply open the bot and send <code>/admin YOUR_ADMIN_PASSWORD</code> and it fills itself. Device requests come here{% if env_adm %} <b>(set inside app.py / env, it wins)</b>{% endif %}</p>
<input name=admin_id value="{{admin_id}}" placeholder="e.g. 123456789" style="width:100%" inputmode=numeric>
<label class=mu style="display:flex;gap:8px;align-items:center;margin-top:12px"><input type=checkbox name=dev_check value=1 {{'checked' if dev_check}} style="width:auto"> Require admin approval for every new reseller device</label>
<label class=mu style="display:flex;gap:8px;align-items:center;margin-top:12px"><input type=checkbox name=otp_global value=1 {{'checked' if otp_global}} style="width:auto"> <b>Login code (6-digit, Telegram) for resellers</b> &mdash; master switch. Untick = nobody needs a code (direct login) until the bot works.</label>
<label class=mu style="display:flex;gap:8px;align-items:center;margin-top:12px"><input type=checkbox name=prem_on value=1 {{'checked' if prem_on}} style="width:auto"> <b>Premium emoji</b> in bot messages (falls back to normal emoji automatically if Telegram refuses)</label>
<button class=g style="margin-top:12px">{{ic('save')}} Save</button></form></div>
<div class=card><h3>Premium emoji</h3>
<div class=mu>Mode: <b>{{prem.mode}}</b> &middot; {{prem.total}} emoji loaded <span class=mu>(both = text + buttons, text, btn = buttons only, plain = normal emoji)</span></div>
{% for n,i in prem.packs %}<div class=mu style="margin-top:4px">{% if i.ok %}<span class="pill a">OK</span>{% else %}<span class="pill e">FAIL</span>{% endif %} <b>{{n}}</b> &mdash; {% if i.ok %}{{i.count}} emoji{% else %}{{i.err}}{% endif %}</div>{% endfor %}
{% if prem.err %}<p class=hint>Last Telegram refusal: {{prem.err}}</p>{% endif %}
<p class=hint>In the bot (as admin) send <code>/emojis</code> for this status, or send premium emojis / a <code>t.me/addemoji/...</code> link to get their IDs.</p></div>
<div class=card><h3>Test</h3><form method=post><input type=hidden name=action value=test><button>{{ic('send')}} Send test message to me</button></form>
<p class=hint>Open your bot in Telegram and press Start first, otherwise Telegram will not let the bot message you.</p></div>

<div class=card><h3>Resellers &amp; Telegram</h3>
<div class=mu style="margin-bottom:8px">Login code master switch: {% if otp_global %}<span class="pill a">ON</span>{% else %}<span class="pill e">OFF (everyone logs in without a code)</span>{% endif %}</div>
<div class=tw><table><tr><th>Reseller</th><th>Telegram</th><th>Code</th><th></th></tr>
{% for x in rs %}<tr><td><a href="/admin/reseller/{{x.id}}">{{x.username}}</a></td>
<td>{% if x.tg_chat %}<span class="pill a">Linked</span> <span class=mu>{{x.tg_chat}}</span>{% else %}<span class="pill e">Not linked</span>{% endif %}</td>
<td>{% if x.otp_on %}<span class="pill a">ON</span>{% else %}<span class="pill e">OFF</span>{% endif %}</td>
<td>{% if x.tg_chat %}<form method=post><input type=hidden name=action value=test_reseller><input type=hidden name=id value="{{x.id}}"><button class=o>Test</button></form>{% endif %}</td></tr>
{% else %}<tr><td colspan=4>No resellers</td></tr>{% endfor %}</table></div>
{% if seen %}<p class=mu style="margin-top:12px">Pressed /start in the bot but not linked yet (open the reseller &rarr; Manage and tap the name):</p>
{% for s in seen %}<span class="pill p" style="margin:2px">{{s.name or '?'}}{% if s.username %} @{{s.username}}{% endif %} &middot; {{s.chat_id}}</span>{% endfor %}{% endif %}</div>

<div class=card><h3>Delivery log</h3>
<div class=mu>Receiving: {% if poll_err %}<span class="pill e">Problem</span> {{poll_err}}{% else %}<span class="pill a">OK</span>{% endif %} &middot; sent OK <b>{{sent_ok}}</b> &middot; failed <b>{{sent_fail}}</b> (since the server started)</div>
<div class=tw style="margin-top:8px"><table><tr><th>Time</th><th>To</th><th>What</th><th>Result</th></tr>
{% for t,ok,chat,what,err in log %}<tr><td>{{t|dt}}</td><td>{{chat}}</td><td>{{what}}</td><td>{% if ok %}<span class="pill a">Delivered</span>{% else %}<span class="pill e">Failed</span> <span class=mu>{{err}}</span>{% endif %}</td></tr>
{% else %}<tr><td colspan=4>Nothing sent yet</td></tr>{% endfor %}</table></div>
<p class=hint>If a login code never arrives, look here: the exact reason from Telegram is shown for every failed message.</p></div>{% endblock %}"""

T["admin_devices.html"] = r"""{% extends 'abase.html' %}{% block c %}<h2>{{ic('phone',24)}} Devices</h2>
<div class="card tw"><table><tr><th>Reseller</th><th>Device</th><th>Status</th><th>Requested</th><th></th></tr>
{% for d in rows %}<tr><td>{{d.username}}</td><td>{{d.label}}<div class=mu>{{d.ip}}</div></td>
<td>{% if d.status=='approved' %}<span class="pill a">Approved</span>{% elif d.status=='pending' %}<span class="pill c">Pending</span>{% else %}<span class="pill e">Rejected</span>{% endif %}</td>
<td>{{d.created|dt}}{% if d.last_seen %}<div class=mu>used {{d.last_seen|dt}}</div>{% endif %}</td>
<td style="white-space:nowrap"><form method=post style="display:inline"><input type=hidden name=id value="{{d.id}}">
{% if d.status!='approved' %}<button class=g name=action value=approve>Accept</button> {% endif %}{% if d.status!='denied' %}<button class=r name=action value=deny>Reject</button> {% endif %}
<button class=o name=action value=delete onclick="return confirm('Remove this device record? (a rejected device becomes unblocked)')">{{ic('trash',16)}}</button></form></td></tr>
{% else %}<tr><td colspan=5>No devices yet.</td></tr>{% endfor %}</table></div>{% endblock %}"""

# ---- wallet: first listed amount is pre-selected (list is editable by admin)
T["wallet.html"] = T["wallet.html"].replace("""{{'on' if a==500}}""", """{{'on' if loop.first}}""").replace('id=am value=500>', 'id=am value="{{amts[0]}}">')

# ---- admin gateway: editable add-balance amounts
T["admin_gateway.html"] = T["admin_gateway.html"].replace('<p class=mu>API Token',
    '<p class=mu>Add-balance amounts shown to resellers (comma separated, e.g. <code>100, 200, 500, 1000</code>)</p><input name=amounts value="{{amounts}}" style="width:100%" inputmode=numeric>\n<p class=mu>API Token', 1)

# ---- admin resellers: telegram id on create + column
T["admin_resellers.html"] = T["admin_resellers.html"].replace(
    '<input name=credit type=number step=any value=0 placeholder="Starting credit" style="width:140px">',
    '<input name=credit type=number step=any value=0 placeholder="Starting credit" style="width:140px"><input name=tg_chat placeholder="Telegram Chat ID (optional)" inputmode=numeric style="width:210px">', 1
).replace('<th>Keys</th><th>Status</th>', '<th>Keys</th><th>Telegram</th><th>Status</th>', 1
).replace('<td>{{x.kc}}</td>', '<td>{{x.kc}}</td><td>{% if x.tg_chat %}<span class="pill a">Linked</span> <span class=mu>{{x.tg_chat}}</span>{% else %}<span class="pill e">Not linked</span>'
          '<form class=row method=post action="/admin/reseller/{{x.id}}" style="margin-top:6px;flex-wrap:nowrap"><input type=hidden name=action value=tg>'
          '<input name=tg_chat list=seenids placeholder="Chat ID" inputmode=numeric style="width:130px"><button class=g>Link</button></form>{% endif %}</td>', 1
).replace('colspan=5>No resellers', 'colspan=6>No resellers', 1
).replace('</table></div>{% endblock %}', '</table></div>'
          '<datalist id=seenids>{% for s in seen %}<option value="{{s.chat_id}}">{{s.name}} {{s.username}}</option>{% endfor %}</datalist>'
          '{% if seen %}<div class=card><h3>Pressed /start in the bot (not linked yet)</h3>{% for s in seen %}<span class="pill p" style="margin:2px">{{s.name or "?"}}{% if s.username %} @{{s.username}}{% endif %} &middot; {{s.chat_id}}</span>{% endfor %}'
          '<p class=hint>Type or pick the Chat ID in the reseller row above and press Link. A test message is sent to confirm.</p></div>{% endif %}{% endblock %}', 1)

# ---- admin reseller manage: telegram + verification + devices
T["admin_reseller.html"] = T["admin_reseller.html"].replace('<div class=card><h3>Change Password</h3>', r"""<div class=card><h3>{{ic('send',20)}} Telegram &amp; Security</h3>
<form class=row method=post><input type=hidden name=action value=tg><input name=tg_chat value="{{r.tg_chat or ''}}" placeholder="Telegram Chat ID (empty = unlink)" inputmode=numeric style="min-width:220px"><button class=g>Save</button></form>
<form method=post style="display:inline"><input type=hidden name=action value=tg_test><button class=o {{'disabled' if not r.tg_chat}}>Send test message</button></form>
{% if seen %}<p class=mu style="margin:12px 0 4px">Pressed /start in the bot &mdash; tap to link:</p>
{% for s in seen %}<form method=post style="display:inline"><input type=hidden name=action value=tg><input type=hidden name=tg_chat value="{{s.chat_id}}"><button class=o style="margin:2px">{{s.name or '?'}}{% if s.username %} @{{s.username}}{% endif %} &middot; {{s.chat_id}}</button></form>{% endfor %}{% endif %}
<p class=hint>The reseller opens your bot and presses Start (the bot shows his Chat ID). His name appears above, or paste the ID by hand. After saving, a test message is sent so you know it really works.</p>
<div style="margin-top:10px">Login code: {% if r.otp_on %}<span class="pill a">ON</span>{% else %}<span class="pill e">OFF</span>{% endif %}
<form method=post style="display:inline"><input type=hidden name=action value=otp_toggle><button class=o style="margin-left:8px">Switch</button></form></div>
{% if devs %}<div class=tw style="margin-top:10px"><table>{% for d in devs %}<tr><td>{{d.label}} <span class=mu>{{d.ip}}</span></td><td>{{d.status}}</td></tr>{% endfor %}</table></div><a href="/admin/devices">Manage devices &rarr;</a>{% endif %}</div>
<div class=card><h3>Change Password</h3>""", 1)

# ---- admin backup page: music has its own backup
T["admin_backup.html"] = r"""{% extends 'abase.html' %}{% block c %}<h2>{{ic('save',24)}} Backup &amp; Restore</h2>
<div class=card><h3>Download Backup</h3>
<p class=mu>One file with products, plans, prices, resellers (balances, passwords, Telegram IDs, approved devices), keys, stock, settings (Main API, Gateway, Telegram bot). <b>Music is not inside</b> - it has its own backup below. Keep this file private.</p>
<div class=mu>Now: {% for k,v in counts.items() %}{{k}} <b>{{v}}</b>{{ ' &middot; '|safe if not loop.last }}{% endfor %}</div>
<a class=btn href="/admin/backup/download" style="margin-top:12px">{{ic('save')}} Download Backup</a></div>
<div class=card><h3>Upload Backup (Restore)</h3>
<p class=mu>Replaces ALL current data with the file (music is not touched). If the file is wrong, nothing changes.</p>
<form method=post action="/admin/backup/restore" enctype=multipart/form-data onsubmit="return confirm('This will REPLACE all current data with the backup. Continue?')">
<input type=file name=file accept=".json,application/json" required> <button class=r>{{ic('plus')}} Upload &amp; Restore</button></form></div>
<div class=card><h3>{{ic('music',20)}} Music Backup</h3>
<p class=mu>Songs now: <b>{{songs}}</b>{% if msize %} &middot; uploaded audio <b>{{msize}} MB</b>{% endif %}. One <code>.zip</code> with the song list and every uploaded audio file.</p>
<a class=btn href="/admin/music/backup" style="margin-top:6px">{{ic('download')}} Download Music Backup</a></div>
<div class=card><h3>Upload Music Backup (Restore)</h3>
<p class=mu>All songs come back. The current music library is replaced.</p>
<form method=post action="/admin/music/restore" enctype=multipart/form-data onsubmit="return confirm('Replace the current music with the backup?')">
<input type=file name=file accept=".zip,application/zip" required> <button class=r>{{ic('plus')}} Upload &amp; Restore Music</button></form></div>{% endblock %}"""

# music admin page note
T["admin_music.html"] = T["admin_music.html"].replace("Free Render disk resets on redeploy, so direct URLs are safer than uploads.",
    'Free Render disk resets on redeploy &mdash; take a <a href="/admin/backup">Music Backup</a> after adding songs and upload it again after a redeploy.')


# =============================================================== v10: Settings, Sold Keys, API docs
T["rbase.html"] = T["rbase.html"].replace('<a href="/logout">',
    '<a href="/settings" class="{{\'on\' if page==\'settings\'}}">{{ic(\'tool\')}} Settings</a>\n<a href="/logout">', 1)

COPY_JS = r"""
function rgCopy(t){if(navigator.clipboard&&window.isSecureContext)return navigator.clipboard.writeText(t);
 return new Promise(function(res){var a=document.createElement('textarea');a.value=t;a.style.cssText='position:fixed;opacity:0;top:0';document.body.appendChild(a);a.focus();a.select();try{document.execCommand('copy')}catch(e){}a.remove();res()})}
function rgFlash(b,txt){var o=b.dataset.o||b.innerHTML;b.dataset.o=o;b.innerHTML=txt;b.classList.add('done');clearTimeout(b._t);b._t=setTimeout(function(){b.innerHTML=o;b.classList.remove('done')},1200)}
"""

SK_CSS = r"""
.skbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:12px 0}
.skbar .sbox{flex:1;min-width:200px;margin:0}
.chips{display:flex;gap:8px}.chip{padding:8px 14px;border-radius:20px;border:1px solid var(--bd);background:transparent;color:var(--mu);font-weight:700}
.chip.on{background:linear-gradient(135deg,var(--ac),var(--ac2));color:#fff;border-color:transparent}
.skg{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:14px}
.sk{border:1px solid var(--bd);border-radius:18px;background:var(--card);padding:14px;display:flex;flex-direction:column;gap:12px;transition:.2s}
.sk:hover{border-color:var(--ac);box-shadow:0 0 22px rgba(var(--acrgb),.2)}
.sk-h{display:flex;align-items:center;justify-content:space-between;gap:8px}
.sk-r{display:inline-flex;align-items:center;gap:7px;font-weight:800;letter-spacing:.03em}.sk-r .ic{color:var(--ac)}
.sk-key{display:flex;align-items:stretch;gap:8px}
.sk-key code{flex:1;min-width:0;display:flex;align-items:center;padding:12px 14px;border-radius:12px;border:1px dashed var(--bd);background:rgba(var(--acrgb),.08);
 color:var(--acl);font:700 15px/1.35 ui-monospace,Consolas,monospace;letter-spacing:.04em;overflow-wrap:anywhere;word-break:break-all;cursor:pointer;user-select:all}
.sk-cp{display:inline-flex;align-items:center;gap:6px;padding:0 14px;border-radius:12px;font-weight:800;white-space:nowrap}
.sk-cp.done{background:var(--ok);border-color:var(--ok);color:#fff}
.sk-m{display:grid;grid-template-columns:1fr 1fr;gap:10px 14px}
.sk-m small{display:block;color:var(--mu);font-size:11px;font-weight:700;letter-spacing:.12em}
.sk-m b{font-size:14px}.sk-m .pl{color:var(--ac);font-weight:800}
.sk-m .full{grid-column:1/-1}
.sk-empty{padding:30px;text-align:center}
"""

T["admin_keys.html"] = r"""{% extends 'abase.html' %}{% block c %}<style>""" + SK_CSS + r"""</style>
<h2>{{ic('key',24)}} Sold Keys <span class=mu>({{rows|length}})</span></h2>
<div class=skbar>
 <div class=sbox>{{ic('search',20)}}<input id=sq placeholder="Search reseller, key, product..." autocomplete=off></div>
 <div class=chips><button class="chip on" data-f=all>All</button><button class=chip data-f=a>Active</button><button class=chip data-f=e>Expired</button></div>
 <button id=cpall class=sk-cp style="padding:9px 14px">{{ic('copy',16)}} Copy shown keys</button>
</div>
<div class=skg id=skg>
{% for x in rows %}{% set act = x.expires>now %}
<div class=sk data-st="{{'a' if act else 'e'}}" data-k="{{x.key}}" data-s="{{(x.username~' '~x.key~' '~x.product_name~' '~x.plan_name~' '~x.via)|lower}}">
 <div class=sk-h><span class=sk-r>{{ic('user',16)}} {{x.username}}</span>{% if act %}<span class="pill a">Active</span>{% else %}<span class="pill e">Expired</span>{% endif %}</div>
 <div class=sk-key><code title="Tap to copy">{{x.key}}</code><button class=sk-cp data-copy-key="{{x.key}}">{{ic('copy',16)}} Copy</button></div>
 <div class=sk-m>
  <div class=full><small>PRODUCT / PLAN</small><b>{{x.product_name}}</b> <span class=pl>&middot; {{x.plan_name}}</span></div>
  <div><small>PRICE</small><b>{{x.price|cur}}</b></div><div><small>VIA</small><b>{{(x.via or 'panel')|upper}}</b></div>
  <div class=full><small>CREATED</small><b>{{x.created|dt}}</b></div>
 </div>
</div>
{% else %}<div class="card sk-empty mu" style="grid-column:1/-1">No keys sold yet.</div>{% endfor %}
</div>
<script>""" + COPY_JS + r"""
var st='all',cards=[].slice.call(document.querySelectorAll('#skg .sk'));
function apply(){var v=document.getElementById('sq').value.trim().toLowerCase();cards.forEach(function(c){var ok=(st=='all'||c.dataset.st==st)&&(!v||c.dataset.s.indexOf(v)>=0);c.style.display=ok?'':'none'})}
document.getElementById('sq').oninput=apply;
document.querySelectorAll('.chip').forEach(function(b){b.onclick=function(){document.querySelectorAll('.chip').forEach(function(x){x.classList.remove('on')});b.classList.add('on');st=b.dataset.f;apply()}});
document.getElementById('skg').addEventListener('click',function(e){
 var b=e.target.closest('[data-copy-key]'),c=e.target.closest('.sk-key code');
 if(b){rgCopy(b.dataset.copyKey).then(function(){rgFlash(b,'Copied')})}
 else if(c){var bb=c.parentNode.querySelector('.sk-cp');rgCopy(bb.dataset.copyKey).then(function(){rgFlash(bb,'Copied')})}});
document.getElementById('cpall').onclick=function(){var t=cards.filter(function(c){return c.style.display!='none'}).map(function(c){return c.dataset.k}).join('\n');var b=this;rgCopy(t).then(function(){rgFlash(b,'Copied')})};
</script>{% endblock %}"""

T["settings.html"] = r"""{% extends 'rbase.html' %}{% block c %}
<style>.pwrow{position:relative;margin:8px 0}.pwrow input{width:100%;padding-right:46px}.pwrow .eye{position:absolute;right:4px;top:50%;margin-top:-17px;width:38px;height:34px;padding:0;background:none;border:0;box-shadow:none;color:var(--mu);display:flex;align-items:center;justify-content:center}
.sgen{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 12px}.sgen button{display:inline-flex;align-items:center;gap:6px}</style>
<div class=hd>{{ic('tool',24)}} SETTINGS</div>
<div class=card><h3>{{ic('lock',20)}} Change password</h3>
<div class=mu>If your password may have leaked, change it here. After the change every other logged-in browser is logged out. (Even with the password, a new device still needs admin approval.)</div>
<form method=post autocomplete=off style="margin-top:12px"><input type=hidden name=action value=password>
<label class=mu>Current password</label><div class=pwrow><input type=password name=current id=pc required autocomplete=current-password><button type=button class=eye data-t=pc aria-label=Show>{{ic('eye',18)}}</button></div>
<label class=mu>New password (min 6 characters)</label><div class=pwrow><input type=password name=new id=pn minlength=6 required autocomplete=new-password><button type=button class=eye data-t=pn aria-label=Show>{{ic('eye',18)}}</button></div>
<label class=mu>Confirm new password</label><div class=pwrow><input type=password name=confirm id=pf minlength=6 required autocomplete=new-password><button type=button class=eye data-t=pf aria-label=Show>{{ic('eye',18)}}</button></div>
<div class=sgen><button type=button class=o id=gen>{{ic('bolt',16)}} Generate strong password</button><button type=button class=o id=cpw>{{ic('copy',16)}} Copy new password</button></div>
<label class=mu style="display:flex;gap:8px;align-items:center"><input type=checkbox name=newkey value=1 style="width:auto"> Also generate a new API key (old API key stops working)</label>
<div><button class=g style="margin-top:14px">{{ic('save',16)}} Update password</button></div></form></div>
<script>""" + COPY_JS + r"""
document.querySelectorAll('.eye').forEach(function(b){b.onclick=function(){var i=document.getElementById(b.dataset.t);i.type=i.type=='password'?'text':'password'}});
document.getElementById('gen').onclick=function(){var cs='ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789@#$%',a=new Uint32Array(14),o='';crypto.getRandomValues(a);for(var i=0;i<14;i++)o+=cs[a[i]%cs.length];
 ['pn','pf'].forEach(function(id){var e=document.getElementById(id);e.value=o;e.type='text'})};
document.getElementById('cpw').onclick=function(){var v=document.getElementById('pn').value;if(v){var b=this;rgCopy(v).then(function(){rgFlash(b,'Copied')})}};
</script>{% endblock %}"""

API_CSS = r"""
.dk{border:1px solid var(--bd);border-radius:14px;background:rgba(var(--acrgb),.06);padding:12px 14px;margin:8px 0;display:flex;gap:10px;align-items:center}
.dk code,.dk pre{flex:1;min-width:0;margin:0;overflow-wrap:anywhere;word-break:break-all;white-space:pre-wrap;color:var(--acl);background:none;border:0;padding:0;font:600 14px/1.4 ui-monospace,Consolas,monospace}
.dk button{flex:none;display:inline-flex;align-items:center;gap:6px}
.dk button.done{background:var(--ok);border-color:var(--ok);color:#fff}
.cb{position:relative;margin:10px 0}.cb pre{margin:0;padding:14px 14px 14px;border-radius:14px;border:1px solid var(--bd);background:rgba(4,8,18,.85);color:#cfe3ff;overflow:auto;font:13px/1.5 ui-monospace,Consolas,monospace;white-space:pre}
.cb button{position:absolute;top:8px;right:8px;padding:5px 10px;font-size:12px}
.stp{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.stp div{border:1px solid var(--bd);border-radius:14px;padding:12px;background:rgba(var(--acrgb),.06)}
.stp b.n{display:inline-flex;width:26px;height:26px;border-radius:50%;background:linear-gradient(135deg,var(--ac),var(--ac2));color:#fff;align-items:center;justify-content:center;margin-right:6px}
.mth{display:inline-block;padding:3px 9px;border-radius:8px;font-weight:800;font-size:12px;margin-right:6px;background:rgba(16,185,129,.2);color:#34d399}.mth.p{background:rgba(59,130,246,.22);color:#93c5fd}
.res{margin-top:10px;padding:12px 14px;border-radius:14px;font-weight:700;display:none}.res.ok{display:block;background:rgba(16,185,129,.15);border:1px solid #10b981;color:#34d399}.res.no{display:block;background:rgba(244,63,94,.14);border:1px solid #f43f5e;color:#fb7185}
.pp{border:1px solid var(--bd);border-radius:14px;padding:10px 12px;margin:8px 0;background:var(--card)}
.pp label.h{display:flex;align-items:center;gap:8px;font-weight:800;cursor:pointer}.pp input[type=checkbox]{width:auto}
.pp .pls{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 0 26px}.pp .pls span{padding:4px 10px;border-radius:9px;border:1px solid var(--bd);font-size:12px;color:var(--mu)}.pp .pls span b{color:var(--acl)}
.tools{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.tools button{display:inline-flex;align-items:center;gap:6px}
.tl input{width:100%;margin:6px 0 10px}
"""

def _cb(code):
    return '<div class=cb><button class="o" data-cp-next>{{ic(\'copy\',14)}} Copy</button><pre>' + code + '</pre></div>'

T["api.html"] = r"""{% extends 'rbase.html' %}{% block c %}<style>""" + API_CSS + r"""</style>
<h2>{{ic('code',24)}} API &amp; Docs</h2>
<div class=card><h3>{{ic('bolt',20)}} Connect your bot in 4 steps</h3>
<div class=stp>
<div><b class=n>1</b><b>Connect</b><p class=mu>Enter <b>Server URL</b> + <b>API Token</b> (below) in your bot. The bot calls <code>/api/v1/connect</code>. Success shows <b>Connect successful</b>, otherwise <b>Not connected</b>.</p></div>
<div><b class=n>2</b><b>Check balance</b><p class=mu>The bot calls <code>/api/v1/balance</code> and shows the wallet balance of this panel account.</p></div>
<div><b class=n>3</b><b>Select products</b><p class=mu><b>All products</b> or only the ones you tick. Products come with their plans (validity) and <b>your reseller price</b>.</p></div>
<div><b class=n>4</b><b>Sell</b><p class=mu>When your customer buys, the bot calls <code>/api/v1/purchase</code> with the <code>plan_id</code>. The key is returned instantly.</p></div>
</div></div>

<div class=card><h3>Your Credentials</h3>
<p class=mu style="margin:6px 0 0">Server URL (public hosting link)</p><div class=dk><code>{{base}}</code><button class=o data-cp="{{base}}">{{ic('copy',15)}} Copy</button></div>
<p class=mu style="margin:6px 0 0">API Token</p><div class=dk><code id=tok>{{r.api_key}}</code><button class=o data-cp="{{r.api_key}}">{{ic('copy',15)}} Copy</button></div>
<div class=mu>Keep the token private. If it leaks, regenerate it &mdash; the old token stops working at once.</div>
<form method=post onsubmit="return confirm('Old key will stop working. Continue?')" style="margin-top:10px"><button class=r>Regenerate API Key</button></form></div>

<div class="card tl"><h3>{{ic('shield2',20)}} Connection tester</h3>
<div class=mu>Try exactly what your bot will do. Nothing is bought here.</div>
<p class=mu style="margin:10px 0 0">Server URL</p><input id=tu value="{{base}}" autocomplete=off>
<p class=mu style="margin:0">API Token</p><input id=tk value="{{r.api_key}}" autocomplete=off>
<div class=tools><button class=g id=bc>{{ic('check',16)}} Connect</button><button class=o id=bb>{{ic('wallet',16)}} Check balance</button><button class=o id=bp>{{ic('box',16)}} Select products</button></div>
<div class=res id=rs></div>
<div id=pbox style="display:none">
<div class=tools><button class=o id=pa>Select all</button><button class=o id=pn>Clear</button><button class=g id=pg>{{ic('bolt',16)}} Get selected products</button></div>
<div id=plist></div>
<p class=mu id=purl style="word-break:break-all"></p>
<div class=cb style="display:none" id=jb><button class=o id=jc>{{ic('copy',14)}} Copy</button><pre id=jo style="max-height:320px"></pre></div>
</div></div>

<div class=card><h3>Authentication</h3><p>Send the token in <b>any one</b> of these ways:</p>
""" + _cb('X-API-Key: YOUR_API_TOKEN\nAuthorization: Bearer YOUR_API_TOKEN\n?api_key=YOUR_API_TOKEN   (query string)') + r"""
<p class=mu>Wrong / missing token &rarr; HTTP 401 and <code>"connected": false</code>.</p></div>

<div class=card><h3><span class=mth>GET</span>1. Connect</h3><p>Use this when the reseller presses <b>Connect</b> in the bot.</p>
""" + _cb('GET {{base}}/api/v1/connect') + _cb('{"success": true, "connected": true, "message": "Connect successful",\n "username": "RPSHIVA", "balance": 250.0, "currency": "INR", "server": "{{base}}"}') + r"""
<p class=mu>If the token is wrong: <code>{"success": false, "connected": false, "error": "INVALID_API_KEY", "message": "Not connected: ..."}</code></p></div>

<div class=card><h3><span class=mth>GET</span>2. Check Balance</h3>
""" + _cb('GET {{base}}/api/v1/balance\n\n{"success": true, "username": "RPSHIVA", "balance": 250.0, "currency": "INR"}') + r"""</div>

<div class=card><h3><span class=mth>GET</span>3. Products, Plans &amp; Prices</h3>
<p>Prices are <b>your</b> prices (custom price if admin set one). All amounts are INR.</p>
""" + _cb('# all products\nGET {{base}}/api/v1/products\n\n# only selected products (comma separated product_id list)\nGET {{base}}/api/v1/products?ids=1,4,7\n\n# same thing with POST\nPOST {{base}}/api/v1/products\n{"product_ids": [1, 4, 7]}') + _cb('{"success": true, "currency": "INR", "count": 1, "missing_ids": [],\n "products": [{"product_id": 1, "name": "FALCON CHEAT ROOT",\n   "plans": [{"plan_id": 3, "name": "1 Day",  "days": 1, "price": 18.0, "currency": "INR", "available": true},\n             {"plan_id": 4, "name": "7 Days", "days": 7, "price": 50.0, "currency": "INR", "available": true}]}]}') + r"""
<p class=mu><code>available</code> is <code>false</code> when a plan uses your own key stock and the stock is empty. <code>missing_ids</code> lists product ids you asked for that do not exist.<br>
Tip: the bot should store <code>product_id</code> and <code>plan_id</code>. To refresh prices / new products call this endpoint again.</p></div>

<div class=card><h3><span class="mth p">POST</span>4. Purchase (Generate Key)</h3>
""" + _cb('POST {{base}}/api/v1/purchase\nContent-Type: application/json\n\n{"plan_id": 3}') + _cb('{"success": true, "key": "FALCON-A1B2-C3D4-E5F6-7890", "product": "FALCON CHEAT ROOT",\n "plan": "1 Day", "price": 18.0, "expires_at": 1767225600, "balance": 232.0}') + r"""
<p class=mu>The price is cut from your wallet and returned in <code>balance</code>. If the main provider fails the balance is refunded automatically.</p></div>

<div class=card><h3><span class=mth>GET</span>5. History</h3>
""" + _cb('GET {{base}}/api/v1/history') + r"""<p class=mu>Returns your last 100 keys.</p></div>

<div class=card><h3>Errors</h3><div class=tw><table><tr><th>HTTP</th><th>error</th><th>Meaning</th></tr>
<tr><td>401</td><td>INVALID_API_KEY</td><td>Not connected - token wrong or account disabled</td></tr>
<tr><td>402</td><td>Insufficient balance</td><td>Add balance in the panel</td></tr>
<tr><td>400</td><td>plan_id required</td><td>Send <code>plan_id</code> in the body</td></tr>
<tr><td>400</td><td>Plan not found / Out of stock / Account disabled</td><td>Check <code>/products</code></td></tr></table></div></div>

<div class=card><h3>{{ic('code',20)}} Ready-made Python helper (for your bot)</h3>
<p class=mu>Copy this into your bot. It does Connect &rarr; Balance &rarr; Select products &rarr; Buy.</p>
""" + _cb('''import requests

class Panel:
    def __init__(self, server_url, token):
        self.base = server_url.rstrip("/")
        self.h = {"X-API-Key": token.strip()}

    def _get(self, path, **params):
        r = requests.get(self.base + path, headers=self.h, params=params, timeout=30)
        return r.json()

    def connect(self):                      # -> (True/False, text)
        try:
            d = self._get("/api/v1/connect")
        except Exception as e:
            return False, "Not connected: %s" % e
        if d.get("connected"):
            return True, "Connect successful (%s, balance %s INR)" % (d["username"], d["balance"])
        return False, "Not connected: %s" % d.get("message", d.get("error"))

    def balance(self):
        return self._get("/api/v1/balance").get("balance")

    def products(self, ids=None):           # ids=None -> ALL products
        p = {"ids": ",".join(map(str, ids))} if ids else {}
        return self._get("/api/v1/products", **p)["products"]

    def buy(self, plan_id):
        r = requests.post(self.base + "/api/v1/purchase", headers=self.h,
                          json={"plan_id": plan_id}, timeout=90).json()
        if not r.get("success"):
            raise RuntimeError(r.get("error", "failed"))
        return r["key"]

# ---- usage in your bot ----
p = Panel("{{base}}", "YOUR_API_TOKEN")
ok, msg = p.connect()                       # show "Connect successful" or "Not connected"
print(msg)
print("Balance:", p.balance())
for prod in p.products([1, 4]):             # or p.products() for ALL
    for pl in prod["plans"]:
        print(prod["product_id"], prod["name"], pl["plan_id"], pl["name"], pl["price"])
# key = p.buy(3)                            # when your customer pays
''') + r"""</div>

<div class=card><h3>cURL</h3>
""" + _cb('curl -H "X-API-Key: YOUR_API_TOKEN" {{base}}/api/v1/connect\ncurl -H "X-API-Key: YOUR_API_TOKEN" "{{base}}/api/v1/products?ids=1,4"\ncurl -X POST -H "X-API-Key: YOUR_API_TOKEN" -H "Content-Type: application/json" -d \'{"plan_id": 3}\' {{base}}/api/v1/purchase') + r"""</div>

<script>""" + COPY_JS + r"""
document.addEventListener('click',function(e){
 var b=e.target.closest('[data-cp]');if(b){rgCopy(b.dataset.cp).then(function(){rgFlash(b,'Copied')});return}
 b=e.target.closest('[data-cp-next]');if(b){rgCopy(b.nextElementSibling.textContent).then(function(){rgFlash(b,'Copied')})}});
var rs=document.getElementById('rs'),prods=[];
function say(ok,t){rs.className='res '+(ok?'ok':'no');rs.textContent=t}
function api(path){var u=document.getElementById('tu').value.trim().replace(/\/+$/,''),k=document.getElementById('tk').value.trim();
 return fetch(u+path,{headers:{'X-API-Key':k}}).then(function(r){return r.json()})}
function fail(e){say(false,'Not connected: '+(e&&e.message?e.message:'server not reachable'))}
document.getElementById('bc').onclick=function(){api('/api/v1/connect').then(function(d){d.connected?say(true,'\u2705 Connect successful \u2014 '+d.username+' \u00b7 balance \u20b9'+d.balance):say(false,'\u274c Not connected \u2014 '+(d.message||d.error))}).catch(fail)};
document.getElementById('bb').onclick=function(){api('/api/v1/balance').then(function(d){d.success?say(true,'\u2705 Balance: \u20b9'+d.balance+' ('+d.username+')'):say(false,'\u274c '+(d.message||d.error))}).catch(fail)};
document.getElementById('bp').onclick=function(){api('/api/v1/products').then(function(d){
 if(!d.success){say(false,'\u274c '+(d.message||d.error));return}
 prods=d.products;say(true,'\u2705 '+prods.length+' products found. Tick the ones you want.');
 var box=document.getElementById('plist');box.innerHTML='';
 prods.forEach(function(p){var w=document.createElement('div');w.className='pp';
  var l=document.createElement('label');l.className='h';var c=document.createElement('input');c.type='checkbox';c.value=p.product_id;c.checked=true;l.appendChild(c);
  l.appendChild(document.createTextNode(p.name+'  (ID '+p.product_id+')'));w.appendChild(l);
  var s=document.createElement('div');s.className='pls';
  p.plans.forEach(function(x){var i=document.createElement('span');i.innerHTML='<b></b> ';i.firstChild.textContent=x.name;i.appendChild(document.createTextNode('\u20b9'+x.price+' \u00b7 plan '+x.plan_id+(x.available?'':' \u00b7 out of stock')));s.appendChild(i)});
  w.appendChild(s);box.appendChild(w)});
 document.getElementById('pbox').style.display='block'}).catch(fail)};
function sel(v){document.querySelectorAll('#plist input').forEach(function(c){c.checked=v})}
document.getElementById('pa').onclick=function(){sel(true)};document.getElementById('pn').onclick=function(){sel(false)};
document.getElementById('pg').onclick=function(){var ids=[].slice.call(document.querySelectorAll('#plist input:checked')).map(function(c){return c.value});
 if(!ids.length){say(false,'Select at least one product');return}
 var path='/api/v1/products'+(ids.length==prods.length?'':'?ids='+ids.join(','));
 document.getElementById('purl').textContent='Your bot calls: GET '+document.getElementById('tu').value.trim().replace(/\/+$/,'')+path;
 api(path).then(function(d){document.getElementById('jo').textContent=JSON.stringify(d,null,2);document.getElementById('jb').style.display='block';say(true,'\u2705 '+d.count+' product(s) with plans and prices selected')}).catch(fail)};
document.getElementById('jc').onclick=function(){var b=this;rgCopy(document.getElementById('jo').textContent).then(function(){rgFlash(b,'Copied')})};
</script>{% endblock %}"""



# =============================================================== v10.2 fixes
# Admin home: "Keys Sold" showed <built-in method keys of dict> because st.keys is the dict method
T["admin_home.html"] = T["admin_home.html"].replace("{{st.keys}}", "{{st['keys']}}")

# reseller panel: do not download the whole song in the background on every page (it kept connections busy)
T["rbase.html"] = T["rbase.html"].replace("<audio id=au preload=auto>", "<audio id=au preload=metadata>")

# Admin > Reseller: separate Add / Deduct buttons (phones often have no minus key)
T["admin_reseller.html"] = T["admin_reseller.html"].replace(
 '<div class=card><h3>Add / Deduct Credit</h3><form class=row method=post><input type=hidden name=action value=credit><input name=amount type=number step=any placeholder="Amount (negative to deduct)" required><button class=g>Update</button></form></div>',
 '<div class=card><h3>Add / Deduct Balance</h3><div class=mu>Current balance: <b>{{r.balance|cur}}</b></div>'
 '<form class=row method=post style="margin-top:10px"><input type=hidden name=action value=credit>'
 '<input name=amount type=number step=any min=0 inputmode=decimal placeholder="Amount" required style="flex:1;min-width:140px">'
 '<button class=g name=op value=add>{{ic(\'plus\',16)}} Add</button>'
 '<button class=r name=op value=sub onclick="return confirm(\'Deduct this amount from the reseller balance?\')">{{ic(\'minus\',16)}} Deduct</button></form></div>', 1)

# Admin > Telegram: say clearly when the server cannot reach Telegram (instead of "rejected")
T["admin_telegram.html"] = T["admin_telegram.html"].replace(
 '{% elif has_token %}<span class="pill e">Token saved but Telegram rejected it</span>',
 '{% elif has_token %}<span class="pill e">{{ me_err or "Checking Telegram... reload this page in a few seconds" }}</span>', 1)

# Admin > Music: upload with a progress bar (no blank "frozen" page), clear error if it fails
T["admin_music.html"] = T["admin_music.html"].replace(
 '<form method=post enctype=multipart/form-data class=row>',
 '<form method=post enctype=multipart/form-data class=row id=mf>', 1).replace(
 '</form>\n<p class=mu>Songs play', '</form><div id=mp style="display:none;margin-top:10px"><div style="height:10px;border-radius:8px;background:rgba(255,255,255,.1);overflow:hidden"><div id=mb style="height:100%;width:0;background:linear-gradient(90deg,var(--ac),var(--ac2))"></div></div><div class=mu id=mt style="margin-top:6px">Uploading...</div></div>\n<p class=mu>Songs play', 1)
T["admin_music.html"] = T["admin_music.html"].replace("{% endblock %}", r"""<script>
var mf=document.getElementById('mf');
mf.addEventListener('submit',function(e){var f=mf.querySelector('input[type=file]');if(!f.files.length||!window.XMLHttpRequest||!window.FormData)return;
 e.preventDefault();var x=new XMLHttpRequest(),box=document.getElementById('mp'),bar=document.getElementById('mb'),tx=document.getElementById('mt');
 box.style.display='block';mf.querySelectorAll('button').forEach(function(b){b.disabled=true});
 x.upload.onprogress=function(ev){if(ev.lengthComputable){var p=Math.round(ev.loaded*100/ev.total);bar.style.width=p+'%';tx.textContent='Uploading '+p+'%'+(p>=100?' - saving...':'')}};
 x.onload=function(){location.href='/admin/music'};
 x.onerror=function(){tx.textContent='Upload failed (network). Try again or use a direct URL.';mf.querySelectorAll('button').forEach(function(b){b.disabled=false})};
 x.ontimeout=x.onerror;x.timeout=600000;x.open('POST','/admin/music');x.send(new FormData(mf))});
</script>{% endblock %}""", 1)

# ---- v10.7: change the bot token from the panel + premium emoji picker
T["admin_telegram.html"] = T["admin_telegram.html"].replace(
 """<p class=mu>Bot token (from @BotFather){% if has_token %} &mdash; saved (ends with <code>{{tail}}</code>). Leave empty to keep it.{% endif %}{% if env_tok %} <b>(set inside app.py / env, it wins)</b>{% endif %}</p>""",
 """<p class=mu>Bot token (from @BotFather){% if has_token %} &mdash; saved (ends with <code>{{tail}}</code>){% if tok_src=='env' %}, from the Render env variable{% endif %}. Leave empty to keep it.{% endif %}<br>Paste a NEW token here and press Save: it is checked with Telegram and the bot switches to it <b>at once</b> (no redeploy, no code change).</p>""", 1)
T["admin_telegram.html"] = T["admin_telegram.html"].replace(
 """{% if env_adm %} <b>(set inside app.py / env, it wins)</b>{% endif %}""", "", 1)
T["admin_telegram.html"] = T["admin_telegram.html"].replace(
 """<div class=card><h3>Test</h3>""",
 """{% if has_token and tok_src=='panel' %}<div class=card><h3>Token leaked?</h3><p class=hint>1) In @BotFather send <code>/revoke</code> and get the new token. 2) Paste it above and Save. The old token stops working immediately, the website stays online.</p>
<form method=post onsubmit="return confirm('Remove the bot token? The bot goes OFF until you paste a new one.')"><input type=hidden name=action value=clear_token><button class=r>Remove token</button></form></div>{% endif %}
<div class=card><h3>Test</h3>""", 1)
T["admin_telegram.html"] = T["admin_telegram.html"].replace(
 """<p class=hint>Open your bot in Telegram and press Start first""",
 """<form method=post style="margin-top:8px"><input type=hidden name=action value=test_alert><button>{{ic('send')}} Send sample purchase alert (to see the emoji)</button></form>
<p class=hint>Open your bot in Telegram and press Start first""", 1)
T["admin_telegram.html"] = T["admin_telegram.html"].replace(
 """<div class=card><h3>Test</h3>""",
 """<div class=card id=emgr><h3>Emoji ID manager</h3>
<p class=hint>Every emoji the bot uses is listed here. <b>Paste a premium emoji ID</b> in the box and press <b>Save</b> &mdash; it is used in every message at once. Empty the box and Save to go back to automatic.
{% if n_over %}({{n_over}} set by you){% endif %}</p>
<p class=hint><b>How to get an ID:</b> open your bot in Telegram (as admin) and send it any premium emoji (or a <code>t.me/addemoji/...</code> pack link). It replies with the ID of each emoji. You can copy that ID here.</p>
<style>.er{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:8px 10px;margin:6px 0;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.12);border-radius:12px}.er .em{font-size:22px;min-width:28px;text-align:center}.er .lb{min-width:92px;font-size:13px;opacity:.75}.er img{width:30px;height:30px;object-fit:contain}.er input{flex:1;min-width:150px;margin:0}.er button{padding:7px 12px}.er .ms{width:100%;font-size:12px;min-height:14px}</style>
<div id=erows>{% for r in roles %}<div class=er data-r="{{r.em}}"><span class=em>{{r.em}}</span><span class=lb>{{r.label}}</span>&rarr;{% if r.cid %}<img class=ep src="/admin/emoji/thumb/{{r.cid}}" alt="">{% else %}<img class=ep alt="" style="display:none">{% endif %}<input class=eid inputmode=numeric placeholder="Emoji ID" value="{{r.mine}}"><button type=button class=sv>Save</button><span class=ms></span></div>{% endfor %}</div>
<h3 style="margin-top:18px">Add any emoji</h3>
<p class=hint>Type or paste any normal emoji (the one used in the bot message) and the premium emoji ID it should become.</p>
<div class=er id=eadd><input id=enew placeholder="Normal emoji, e.g. &#128293;" style="max-width:150px;flex:0 0 150px;font-size:20px"><span>&rarr;</span><input id=enewid class=eid inputmode=numeric placeholder="Emoji ID"><button type=button id=eaddb>Add</button><span class=ms id=eaddm></span></div>
<div id=eextra>{% for r in extras %}<div class=er data-r="{{r.em}}"><span class=em>{{r.em}}</span><span class=lb>Added by you</span>&rarr;<img class=ep src="/admin/emoji/thumb/{{r.cid}}" alt=""><input class=eid inputmode=numeric value="{{r.cid}}"><button type=button class=sv>Save</button><button type=button class="sv rm r">Remove</button><span class=ms></span></div>{% endfor %}</div>
<details style="margin-top:14px"><summary style="cursor:pointer"><b>Paste many at once</b></summary>
<p class=hint>One per line: the emoji, a space, the ID. (You can paste the bot's reply directly.)</p>
<textarea id=ebulk rows=5 placeholder="&#9989; 5368324170671202286&#10;&#128273; 5314504236132747481" style="width:100%"></textarea>
<button type=button id=ebulkb style="margin-top:6px">Apply all</button> <span class=ms id=ebulkm></span></details>
<details style="margin-top:14px"><summary style="cursor:pointer"><b>Pick from my emoji packs</b> ({{cat|length}} emoji)</summary>
<p class=hint>Tap an emoji below to copy its ID into the box you last touched.</p>
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(52px,1fr));gap:6px;margin-top:10px">{% for pk,ix,cid,em in cat %}<button type=button class=ecell data-c="{{cid}}" title="{{pk}} #{{ix}}" style="padding:4px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:10px"><img loading=lazy src="/admin/emoji/thumb/{{cid}}" width=40 height=40 alt="{{em}}"></button>{% else %}<div class=mu>Packs not loaded yet (bot token must work). Reload in a few seconds.</div>{% endfor %}</div></details>
<form method=post style="margin-top:12px" onsubmit="return confirm('Remove ALL your emoji IDs and go back to automatic?')"><input type=hidden name=action value=reset_emoji><button class=r>Reset to automatic</button></form>
<script>(function(){var last=null;
function J(u,b){return fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}).then(function(r){return r.json().then(function(j){j.status=r.status;return j})})}
function save(row,idv,done){var ms=row.querySelector('.ms');ms.textContent='Saving...';
J('/admin/emoji/set',{role:row.dataset.r,cid:idv}).then(function(j){if(!j.ok){ms.style.color='#ff6b6b';ms.textContent=j.msg||'Could not save';return}
var im=row.querySelector('.ep');if(j.cid){im.src='/admin/emoji/thumb/'+j.cid+'?t='+Date.now();im.style.display=''}else{im.style.display='none'}
ms.style.color=j.found===false?'#ffb020':'#3ddc97';ms.textContent=j.found===false?'Saved, but Telegram does not know this ID - check it':(idv?'Saved. Next messages use it.':'Back to automatic.');if(done)done(j)}).catch(function(){ms.style.color='#ff6b6b';ms.textContent='Could not save, try again'})}
function wire(row){var inp=row.querySelector('.eid');inp.addEventListener('focus',function(){last=inp});
row.querySelector('.sv').addEventListener('click',function(){save(row,inp.value.trim())});
var rm=row.querySelector('.rm');if(rm)rm.addEventListener('click',function(){save(row,'',function(){row.remove()})})}
document.querySelectorAll('#erows .er,#eextra .er').forEach(wire);
document.getElementById('enewid').addEventListener('focus',function(){last=this});
document.getElementById('eaddb').addEventListener('click',function(){var e=document.getElementById('enew').value.trim(),i=document.getElementById('enewid').value.trim(),m=document.getElementById('eaddm');
if(!e||!i){m.textContent='Fill both: the emoji and its ID';return}
var row=document.createElement('div');row.className='er';row.dataset.r=e;row.innerHTML='<span class=em></span><span class=lb>Added by you</span>&rarr;<img class=ep alt="" style="display:none"><input class=eid inputmode=numeric><button type=button class=sv>Save</button><button type=button class="sv rm r">Remove</button><span class=ms></span>';
row.querySelector('.em').textContent=e;row.querySelector('.eid').value=i;
save(row,i,function(){document.getElementById('eextra').prepend(row);wire(row);document.getElementById('enew').value='';document.getElementById('enewid').value='';m.textContent=''});})
document.getElementById('ebulkb').addEventListener('click',function(){var m=document.getElementById('ebulkm');J('/admin/emoji/bulk',{text:document.getElementById('ebulk').value}).then(function(j){m.textContent=j.ok?(j.n+' saved - reloading...'):'No valid lines found';if(j.ok)setTimeout(function(){location.reload()},800)})});
document.querySelectorAll('.ecell').forEach(function(c){c.addEventListener('click',function(){if(!last){alert('First tap an ID box above, then tap the emoji.');return}last.value=c.dataset.c;last.focus()})})})();</script></div>
<div class=card><h3>Test</h3>""", 1)

TEMPLATES = T


# ---- admin top menu -> left three-line (hamburger) drawer. Runs last, so every link added above is included.
import re as _re
_nav = T["abase.html"]
_m = _re.search(r'<div class=nav>(.*?)</div>', _nav, _re.S)
if _m:
    _links = _re.findall(r'<a href="[^"]+"[^>]*>.*?</a>', _m.group(1), _re.S)
    _main = [l for l in _links if '/admin/logout' not in l]
    _out = [l for l in _links if '/admin/logout' in l]
    _new = ('<style>.nav{display:none!important}'
            '.atop{display:flex;align-items:center;gap:12px;padding:11px 16px;background:rgba(8,8,18,.75);backdrop-filter:blur(16px);border-bottom:1px solid var(--bd);position:sticky;top:0;z-index:20}'
            '.aburger{width:46px;height:46px;border-radius:12px;border:1px solid var(--bd);background:var(--card);display:inline-flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;cursor:pointer;padding:0;box-shadow:0 0 18px rgba(139,92,246,.25)}'
            '.aburger i{display:block;width:22px;height:2.5px;border-radius:2px;background:#c4b5fd}'
            '.aov{position:fixed;inset:0;background:rgba(0,0,0,.6);backdrop-filter:blur(3px);opacity:0;pointer-events:none;transition:.25s;z-index:90}'
            '.adr{position:fixed;top:0;left:0;bottom:0;width:290px;max-width:84vw;background:#07070f;border-right:1px solid rgba(139,92,246,.45);box-shadow:0 0 50px rgba(139,92,246,.3);transform:translateX(-105%);transition:.28s;z-index:100;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:6px}'
            'body.aopen .aov{opacity:1;pointer-events:auto}body.aopen .adr{transform:none}'
            '.adr a{display:block;padding:12px 14px;border-radius:12px;color:var(--tx);font-size:16px}.adr a:hover{background:rgba(139,92,246,.15)}'
            '.adr a.on{background:linear-gradient(135deg,#8b5cf6,#6366f1);box-shadow:var(--gl)}'
            '.adr .ax{align-self:flex-end;background:none;border:0;color:#fff;font-size:28px;cursor:pointer;line-height:1;padding:0 6px}'
            '.adr .lo{margin-top:auto;border-top:1px solid var(--bd);padding-top:10px}</style>'
            '<div class=atop><button type=button class=aburger id=aB aria-label="Menu"><i></i><i></i><i></i></button>'
            '<b class=logo style="padding:7px 10px;display:inline-flex;align-items:center;gap:8px">{{ic(\'tool\')}} ADMIN</b></div>'
            '<div class=aov id=aO></div><aside class=adr id=aD><button type=button class=ax id=aX aria-label="Close">&times;</button>'
            + ''.join(_main) + ('<div class=lo>' + ''.join(_out) + '</div>' if _out else '') + '</aside>'
            '<script>(function(){var b=document.body,o=function(v){b.classList.toggle("aopen",v)};'
            'document.getElementById("aB").onclick=function(){o(true)};'
            'document.getElementById("aX").onclick=document.getElementById("aO").onclick=function(){o(false)};'
            'document.addEventListener("keydown",function(e){if(e.key==="Escape")o(false)})})();</script>')
    T["abase.html"] = _nav[:_m.start()] + _new + _nav[_m.end():]
