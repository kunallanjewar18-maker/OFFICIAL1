
from markupsafe import Markup
_P = {
 "key":'<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6"/><path d="m15.5 7.5 3 3L22 7l-3-3"/>',
 "user":'<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
 "lock":'<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
 "eye":'<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
 "eyeoff":'<path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/><path d="M6.61 6.61A13.5 13.5 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/><line x1="2" x2="22" y1="2" y2="22"/>',
 "arrow":'<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
 "menu":'<line x1="4" x2="20" y1="12" y2="12"/><line x1="4" x2="20" y1="6" y2="6"/><line x1="4" x2="20" y1="18" y2="18"/>',
 "crown":'<path d="m2 4 3 12h14l3-12-6 7-4-7-4 7-6-7zm3 16h14"/>',
 "wallet":'<path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1"/><path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"/>',
 "cal":'<path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/>',
 "chart":'<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
 "dollar":'<line x1="12" x2="12" y1="2" y2="22"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
 "box":'<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
 "dash":'<rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/>',
 "history":'<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
 "code":'<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
 "logout":'<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" x2="9" y1="12" y2="12"/>',
 "prev":'<polygon points="19 20 9 12 19 4 19 20"/><line x1="5" x2="5" y1="19" y2="5"/>',
 "next":'<polygon points="5 4 15 12 5 20 5 4"/><line x1="19" x2="19" y1="5" y2="19"/>',
 "play":'<polygon points="6 3 20 12 6 21 6 3"/>',
 "pause":'<rect x="14" y="4" width="4" height="16" rx="1"/><rect x="6" y="4" width="4" height="16" rx="1"/>',
 "copy":'<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
 "check":'<path d="M20 6 9 17l-5-5"/>',
 "shield":'<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.5 3.8 17 5 19 5a1 1 0 0 1 1 1z"/>',
 "plus":'<path d="M5 12h14"/><path d="M12 5v14"/>',
 "save":'<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/>',
 "x":'<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
 "back":'<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
 "music":'<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
 "tool":'<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94z"/>',
}
def ic(name, size=18):
    return Markup('<svg class="ic" width="%d" height="%d" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">%s</svg>' % (size, size, _P[name]))

CSS = """
:root{--bg:#04040a;--card:rgba(17,17,30,.72);--bd:rgba(139,92,246,.25);--tx:#eef0ff;--mu:#8b8fa8;--ac:#8b5cf6;--ac2:#22d3ee;--ok:#10b981;--er:#f43f5e;--gl:0 0 22px rgba(139,92,246,.45)}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;min-height:100vh;color:var(--tx);font:15px/1.5 'Inter',system-ui,Segoe UI,Arial,sans-serif;background:var(--bg);
background-image:radial-gradient(60% 50% at 15% 0%,rgba(139,92,246,.18),transparent 70%),radial-gradient(50% 45% at 100% 20%,rgba(34,211,238,.12),transparent 70%),linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px);
background-size:auto,auto,44px 44px,44px 44px;background-attachment:fixed}
body::before,body::after{content:"";position:fixed;width:340px;height:340px;border-radius:50%;filter:blur(110px);opacity:.28;z-index:-1;animation:fl 14s ease-in-out infinite alternate}
body::before{background:#8b5cf6;left:-90px;bottom:-60px}body::after{background:#22d3ee;right:-100px;top:35%;animation-delay:-6s}
@keyframes fl{to{transform:translate(70px,-60px) scale(1.2)}}
a{color:var(--ac2);text-decoration:none}h1,h2,h3{margin:.3em 0;letter-spacing:-.01em}
h2{font-size:24px;background:linear-gradient(90deg,#fff,#c4b5fd 60%,#67e8f9);-webkit-background-clip:text;background-clip:text;color:transparent}
.wrap{max-width:1020px;margin:0 auto;padding:16px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:16px;padding:18px;margin:14px 0;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);box-shadow:0 8px 30px rgba(0,0,0,.45);transition:.25s}
.card:hover{border-color:rgba(139,92,246,.5);box-shadow:0 8px 34px rgba(0,0,0,.5),0 0 26px rgba(139,92,246,.18)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:14px}
.stat{position:relative;overflow:hidden;background:var(--card);border:1px solid var(--bd);border-radius:16px;padding:16px;backdrop-filter:blur(14px);transition:.25s}
.stat:hover{transform:translateY(-3px);box-shadow:var(--gl)}
.stat::after{content:"";position:absolute;inset:auto -20% -60% auto;width:90px;height:90px;background:var(--ac);filter:blur(45px);opacity:.35}
.stat b{display:block;font-size:28px;margin-top:4px;background:linear-gradient(90deg,#fff,#a5f3fc);-webkit-background-clip:text;background-clip:text;color:transparent}
.mu{color:var(--mu);font-size:13px}
input,select,button,textarea{font:inherit;padding:10px 13px;border-radius:10px;border:1px solid rgba(139,92,246,.28);background:rgba(6,6,14,.8);color:var(--tx);max-width:100%;outline:0;transition:.2s}
input:focus,select:focus,textarea:focus{border-color:var(--ac);box-shadow:0 0 0 3px rgba(139,92,246,.22),0 0 16px rgba(139,92,246,.3)}
textarea{width:100%;min-height:120px;font-family:ui-monospace,Consolas,monospace;font-size:13px}
button,.btn{background:linear-gradient(135deg,#8b5cf6,#6366f1 55%,#22d3ee);border:0;color:#fff;cursor:pointer;display:inline-block;padding:10px 18px;border-radius:10px;font-weight:600;box-shadow:0 4px 18px rgba(139,92,246,.45);transition:.2s}
button:hover,.btn:hover{transform:translateY(-1px);box-shadow:0 6px 26px rgba(139,92,246,.7);filter:brightness(1.08)}
button:disabled{opacity:.4;cursor:not-allowed;transform:none;box-shadow:none}
button.g{background:linear-gradient(135deg,#059669,#10b981);box-shadow:0 4px 16px rgba(16,185,129,.4)}
button.r{background:linear-gradient(135deg,#e11d48,#f43f5e);box-shadow:0 4px 16px rgba(244,63,94,.4)}
button.o{background:transparent;border:1px solid var(--bd);box-shadow:none}
form.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
table{width:100%;border-collapse:collapse}th,td{padding:10px 8px;border-bottom:1px solid rgba(139,92,246,.14);text-align:left;font-size:14px}
th{color:var(--mu);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.06em}tr:hover td{background:rgba(139,92,246,.05)}
.tw{overflow-x:auto}.flash{padding:12px 16px;border-radius:12px;margin:10px 0;word-break:break-all;backdrop-filter:blur(10px)}
.flash.ok{background:rgba(16,185,129,.12);border:1px solid var(--ok);box-shadow:0 0 18px rgba(16,185,129,.25)}
.flash.err{background:rgba(244,63,94,.12);border:1px solid var(--er);box-shadow:0 0 18px rgba(244,63,94,.25)}
.top{display:flex;align-items:center;gap:12px;padding:11px 16px;background:rgba(8,8,18,.75);backdrop-filter:blur(16px);border-bottom:1px solid var(--bd);position:sticky;top:0;z-index:20}
.logo{font-weight:800;letter-spacing:.04em;background:linear-gradient(90deg,#c4b5fd,#22d3ee);-webkit-background-clip:text;background-clip:text;color:transparent;text-shadow:0 0 24px rgba(139,92,246,.6)}
.burger{background:none!important;box-shadow:none!important;border:0;padding:4px 8px;font-size:26px;line-height:1;color:var(--tx)}
.side{position:fixed;top:0;left:-280px;width:270px;height:100%;background:rgba(8,8,18,.96);border-right:1px solid var(--bd);padding:20px;transition:.28s;z-index:30;box-shadow:12px 0 40px rgba(0,0,0,.6)}
.side.open{left:0}.side a{display:block;padding:12px 14px;border-radius:10px;color:var(--tx);margin:3px 0;transition:.2s}
.side a.on,.side a:hover{background:linear-gradient(90deg,rgba(139,92,246,.28),rgba(34,211,238,.1));box-shadow:inset 3px 0 0 var(--ac)}
.shade{display:none;position:fixed;inset:0;background:#000a;z-index:25;backdrop-filter:blur(3px)}.shade.open{display:block}
.player{display:flex;align-items:center;gap:6px;background:rgba(6,6,14,.8);border:1px solid var(--bd);border-radius:30px;padding:3px 10px;margin-left:auto;max-width:60%}
.player button{background:none;border:0;box-shadow:none;padding:4px 7px;font-size:17px;color:var(--tx)}.player span{font-size:12px;color:var(--mu);overflow:hidden;white-space:nowrap;text-overflow:ellipsis;max-width:130px}
pre,code{background:rgba(6,6,14,.85);border:1px solid var(--bd);border-radius:8px;padding:2px 7px;word-break:break-all;color:#c4b5fd}pre{padding:12px;overflow-x:auto;white-space:pre-wrap;margin:6px 0}
.pill{padding:3px 10px;border-radius:20px;font-size:12px;font-weight:600}.pill.a{background:rgba(16,185,129,.15);color:#34d399;box-shadow:0 0 10px rgba(16,185,129,.3)}.pill.e{background:rgba(244,63,94,.15);color:#fb7185}.pill.p{background:rgba(139,92,246,.18);color:#c4b5fd}.pill.c{background:rgba(34,211,238,.14);color:#67e8f9}
.nav{display:flex;gap:6px;flex-wrap:wrap;align-items:center;padding:11px 16px;background:rgba(8,8,18,.75);backdrop-filter:blur(16px);border-bottom:1px solid var(--bd);position:sticky;top:0;z-index:20}
.nav a{padding:8px 14px;border-radius:10px;color:var(--tx);transition:.2s}.nav a:hover{background:rgba(139,92,246,.15)}.nav a.on{background:linear-gradient(135deg,#8b5cf6,#6366f1);box-shadow:var(--gl)}
.center{max-width:400px;margin:13vh auto;padding:14px}.center input{width:100%;margin:7px 0}
.center .card{box-shadow:0 0 60px rgba(139,92,246,.3),0 10px 40px rgba(0,0,0,.6);border-color:rgba(139,92,246,.45)}
.big{font-size:30px;text-align:center;margin-bottom:4px}.hero{background:linear-gradient(135deg,rgba(139,92,246,.22),rgba(34,211,238,.1));text-align:center;padding:26px}
.ic{flex:none;vertical-align:-3px;color:#a78bfa;-webkit-text-fill-color:currentColor}
h2,h3{display:flex;align-items:center;gap:9px}
h2 .ic{color:#c4b5fd}
.btn .ic,button .ic{color:inherit;vertical-align:-4px;margin-right:6px}
.top{padding:12px 14px}
.iconbtn{display:inline-flex;align-items:center;justify-content:center;width:46px;height:46px;padding:0;border-radius:14px;background:rgba(139,92,246,.12)!important;border:1px solid var(--bd)!important;box-shadow:none!important;color:#c4b5fd}
.iconbtn .ic{margin:0;color:#c4b5fd}
.brand{font-weight:800;letter-spacing:.06em;font-size:15px;white-space:nowrap}
.player{background:rgba(139,92,246,.1);border:1px solid rgba(139,92,246,.35);padding:4px 8px;gap:2px}
.player button{padding:6px;border-radius:50%;display:inline-flex}.player button .ic{margin:0;color:#c4b5fd}
.player #pp{background:linear-gradient(135deg,#8b5cf6,#22d3ee);box-shadow:none}.player #pp .ic{color:#fff}
.side a{display:flex;align-items:center;gap:12px}.side a .ic{color:#a78bfa}.side a.on .ic{color:#67e8f9}
.sidehd{display:flex;align-items:center;gap:10px;margin-bottom:6px}
.tile{width:46px;height:46px;border-radius:14px;display:inline-flex;align-items:center;justify-content:center;background:rgba(139,92,246,.18);border:1px solid rgba(139,92,246,.3);flex:none}
.tile .ic{color:#c4b5fd}
.welcome{position:relative;overflow:hidden;padding:20px;border-radius:22px;border:1px solid rgba(139,92,246,.5);background:linear-gradient(135deg,rgba(139,92,246,.55),rgba(79,70,229,.35) 55%,rgba(34,211,238,.3));box-shadow:0 10px 40px rgba(139,92,246,.25)}
.welcome .who{display:flex;align-items:center;gap:14px}
.welcome .tile{width:56px;height:56px;border-radius:16px;background:rgba(255,255,255,.14);border-color:rgba(255,255,255,.3)}.welcome .tile .ic{color:#fff}
.welcome small{display:block;font-size:12px;font-weight:700;letter-spacing:.18em;color:rgba(255,255,255,.75)}
.welcome h1{margin:2px 0 0;font-size:26px;font-weight:800;color:#fff}
.balrow{margin-top:16px;display:flex;align-items:center;gap:12px;padding:14px;border-radius:16px;background:rgba(4,4,12,.38);border:1px solid rgba(255,255,255,.1)}
.balrow .tile{width:40px;height:40px;border-radius:12px;background:rgba(16,185,129,.18);border-color:rgba(16,185,129,.35)}.balrow .tile .ic{color:#34d399}
.balrow span{font-weight:700;letter-spacing:.1em;font-size:13px;color:rgba(255,255,255,.85)}
.balrow b{margin-left:auto;font-size:30px;font-weight:800;color:#34d399;text-shadow:0 0 22px rgba(16,185,129,.45)}
.gen{display:flex;align-items:center;justify-content:center;width:100%;margin-top:14px;padding:13px;border-radius:14px;font-size:16px;background:rgba(255,255,255,.95);color:#4c1d95;box-shadow:0 6px 24px rgba(0,0,0,.3)}
.gen .ic{color:#6d28d9}
.g4{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:14px 0}
.kpi{display:flex;flex-direction:column;align-items:center;text-align:center;padding:18px 10px;border-radius:18px;background:var(--card);border:1px solid var(--bd);box-shadow:0 8px 26px rgba(0,0,0,.4)}
.kpi .tile{margin-bottom:10px}.kpi b{font-size:32px;line-height:1.1;font-weight:800}.kpi span{margin-top:6px;font-size:12px;font-weight:700;letter-spacing:.14em;color:var(--mu)}
.wide{padding:20px 12px}.wide b{font-size:34px;color:#34d399;text-shadow:0 0 22px rgba(16,185,129,.35)}.wide .sub{margin-top:4px;color:var(--mu);font-size:14px}.wide.pk b{color:#c4b5fd;text-shadow:0 0 22px rgba(139,92,246,.45)}
.sec{display:flex;align-items:center;justify-content:space-between;margin:22px 2px 10px}.sec h3{margin:0;font-size:18px}.sec a{font-weight:700;color:#67e8f9;display:inline-flex;align-items:center;gap:6px}
.klist{border-radius:18px;overflow:hidden;background:var(--card);border:1px solid var(--bd)}
.krow{display:flex;align-items:center;gap:12px;padding:13px 14px;border-bottom:1px solid rgba(139,92,246,.15)}.krow:last-child{border-bottom:0}
.krow .tile{width:42px;height:42px;border-radius:12px}
.krow .m{flex:1;min-width:0}.krow .m b{display:block;font-size:15px}.krow .m code{display:inline-block;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;border:0;background:none;padding:0;color:var(--mu);font-size:13px}
.krow .d{font-size:13px;color:var(--mu);white-space:nowrap}
.cp{padding:6px!important;border-radius:9px!important;background:rgba(139,92,246,.14)!important;box-shadow:none!important;border:1px solid var(--bd)!important;color:#c4b5fd}.cp .ic{margin:0}
.foot{margin:26px 0 8px;padding-top:14px;border-top:1px solid rgba(139,92,246,.2);text-align:center;color:var(--mu);font-size:13px}
/* login */
.lg{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:18px}
.lg .box{width:100%;max-width:420px;padding:28px 22px 22px;border-radius:30px;background:rgba(10,10,24,.78);border:1.5px solid rgba(139,92,246,.55);box-shadow:0 0 60px rgba(139,92,246,.25),0 20px 50px rgba(0,0,0,.6);backdrop-filter:blur(16px)}
.lg .logo-t{width:68px;height:68px;margin:0 auto 14px;border-radius:20px;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#8b5cf6,#22d3ee);box-shadow:0 0 34px rgba(139,92,246,.6)}.lg .logo-t .ic{color:#fff}
.lg h1{margin:0;text-align:center;font-size:28px;font-weight:800;letter-spacing:.01em}
.lg .dv{display:flex;align-items:center;gap:12px;margin:14px 6px}.lg .dv i{flex:1;height:1px;background:linear-gradient(90deg,transparent,rgba(139,92,246,.7),transparent)}.lg .dv u{width:9px;height:9px;border-radius:50%;background:#8b5cf6;box-shadow:0 0 12px #8b5cf6}
.lg .tag{display:flex;width:max-content;max-width:100%;margin:0 auto 22px;align-items:center;gap:8px;padding:9px 16px;border-radius:14px;font-weight:600;font-size:14px;color:#a5b4fc;border:1px solid rgba(139,92,246,.5);background:rgba(139,92,246,.08)}.lg .tag .ic{color:#a5b4fc}
.lg label{display:block;margin:14px 0 8px;font-weight:700;font-size:15px}
.lg .fld{display:flex;align-items:center;gap:10px;padding:0 14px;border-radius:14px;background:rgba(18,18,40,.9);border:1px solid rgba(139,92,246,.45);transition:.2s}
.lg .fld:focus-within{border-color:#22d3ee;box-shadow:0 0 0 3px rgba(34,211,238,.18)}
.lg .fld input{flex:1;min-width:0;width:100%;border:0;background:none;box-shadow:none!important;padding:15px 0;font-size:16px}
.lg .fld .ic{color:#94a3b8}.lg .eye{background:none!important;box-shadow:none!important;border:0!important;padding:4px!important;color:#94a3b8;display:inline-flex}.lg .eye .ic{margin:0}
.lg .sess{display:flex;align-items:center;gap:8px;margin:14px 0 18px;color:#a5b4fc;font-size:14px}
.lg .go{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;padding:15px;border-radius:14px;font-size:16px;font-weight:800;letter-spacing:.14em;background:linear-gradient(90deg,#8b5cf6,#6366f1 50%,#22d3ee);box-shadow:0 8px 30px rgba(99,102,241,.5)}.lg .go .ic{margin:0;color:#fff}
.lg .copy{margin-top:18px;text-align:center;color:var(--mu);font-size:13px}
.lg .flash{margin:0 0 4px}
/* admin products */
.plans td{vertical-align:middle}.plans input,.plans select{padding:8px 10px}
.hint{font-size:12px;color:var(--mu);margin:8px 0 0}
@media(max-width:480px){.balrow b{font-size:26px}.welcome h1{font-size:22px}}

"""

FLASH = """{% with m=get_flashed_messages(with_categories=true) %}{% for c,t in m %}<div class="flash {{c}}">{{t}}</div>{% endfor %}{% endwith %}"""
HEAD = """<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><meta name=theme-color content="#04040a"><link rel=preconnect href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel=stylesheet><title>"""
T = {}
T["login.html"] = HEAD + """{{BRAND}} - {{title}}</title><style>""" + CSS + """</style></head><body>
<div class="lg"><div class="box">
<div class="logo-t">{{ic('key',34)}}</div><h1>{{BRAND}}</h1>
<div class="dv"><i></i><u></u><i></i></div>
<div class="tag">{{ic('lock',18)}} {{title}}</div>""" + FLASH + """
<form method=post action="{{action}}" autocomplete=on>
<label for=u>Username</label><div class="fld">{{ic('user',20)}}<input id=u name=username placeholder="Enter your username" required autofocus autocomplete=username autocapitalize=off></div>
<label for=pw>Password</label><div class="fld">{{ic('lock',20)}}<input id=pw name=password type=password placeholder="Enter your password" required autocomplete=current-password><button type=button class=eye id=eye aria-label="Show password">{{ic('eye',20)}}</button></div>
<div class="sess">{{ic('lock',16)}} Secure session</div>
<button class="go">LOGIN {{ic('arrow',20)}}</button></form>
<div class="copy">&copy; {{year}} {{BRAND}}</div></div></div>
<script>const E=document.getElementById('eye'),P=document.getElementById('pw'),I='{{ic('eye',20)|e}}',O='{{ic('eyeoff',20)|e}}';
E.onclick=()=>{const h=P.type==='password';P.type=h?'text':'password';E.innerHTML=h?O:I};</script></body></html>"""

T["rbase.html"] = HEAD + """Reseller Panel</title><style>""" + CSS + """</style></head><body>
<div class="shade" id=shade></div>
<div class="side" id=side><div class=sidehd><span class=tile>{{ic('crown',22)}}</span><div><b class=logo>{{BRAND}}</b><div class=mu>{{r.username}}</div></div></div>
<div class=mu style="margin:8px 0 0">Balance: <b style="color:#34d399">{{r.balance|cur}}</b></div><hr style="border:0;border-top:1px solid rgba(139,92,246,.25);margin:14px 0">
<a href="/dashboard" class="{{'on' if page=='dashboard'}}">{{ic('dash')}} Dashboard</a>
<a href="/generate" class="{{'on' if page=='generate'}}">{{ic('key')}} Generate Key</a>
<a href="/history" class="{{'on' if page=='history'}}">{{ic('history')}} History</a>
<a href="/api-docs" class="{{'on' if page=='api'}}">{{ic('code')}} API &amp; Docs</a>
<a href="/logout">{{ic('logout')}} Logout</a></div>
<div class="top"><button class="iconbtn" id=bg aria-label="Menu">{{ic('menu',22)}}</button>
<div class="player" id=pl><button id=pv aria-label="Previous">{{ic('prev',16)}}</button><button id=pp aria-label="Play">{{ic('play',16)}}</button><button id=nx aria-label="Next">{{ic('next',16)}}</button><span id=ttl>…</span><audio id=au preload=auto></audio></div></div>
<div class="wrap">""" + FLASH + """{% block c %}{% endblock %}</div>
<script>
const PLAY='{{ic('play',16)|e}}',PAUSE='{{ic('pause',16)|e}}';
const S=document.getElementById('side'),H=document.getElementById('shade');
function tg(){S.classList.toggle('open');H.classList.toggle('open')}bg.onclick=tg;H.onclick=tg;
document.querySelectorAll('[data-copy]').forEach(b=>b.onclick=()=>{navigator.clipboard&&navigator.clipboard.writeText(b.dataset.copy);b.style.color='#34d399';setTimeout(()=>b.style.color='',900)});
(async()=>{let L=[];try{L=await(await fetch('/music.json')).json()}catch(e){}
if(!L.length){pl.style.display='none';return}
let i=+localStorage.mi||0;if(i>=L.length)i=0;
function load(n,seek){i=(n+L.length)%L.length;au.src=L[i].url;ttl.textContent=L[i].title;localStorage.mi=i;
 if(seek)au.addEventListener('loadedmetadata',()=>{au.currentTime=seek},{once:true})}
function play(){au.play().then(()=>{pp.innerHTML=PAUSE;localStorage.mp=1}).catch(()=>{pp.innerHTML=PLAY})}
function pause(){au.pause();pp.innerHTML=PLAY;localStorage.mp=0}
load(i,+localStorage.mt||0);
pp.onclick=()=>au.paused?play():pause();
nx.onclick=()=>{load(i+1);play()};pv.onclick=()=>{load(i-1);play()};
au.onended=()=>{load(i+1);play()};
setInterval(()=>{if(!au.paused)localStorage.mt=au.currentTime},1000);
if(localStorage.mp!=='0'){play();document.addEventListener('click',()=>{if(au.paused&&localStorage.mp!=='0')play()},{once:true})}
})();
</script></body></html>"""

T["dashboard.html"] = """{% extends 'rbase.html' %}{% block c %}
<div class="welcome"><div class="who"><span class="tile">{{ic('crown',28)}}</span><div><small>WELCOME BACK</small><h1>{{r.username}}</h1></div></div>
<div class="balrow"><span class="tile">{{ic('wallet',22)}}</span><span>BALANCE</span><b>{{r.balance|cur}}</b></div>
<a class="btn gen" href="/generate">{{ic('key',20)}} Generate New Key</a></div>
<div class="g4">
<div class="kpi"><span class="tile">{{ic('cal',22)}}</span><b>{{st.today}}</b><span>TODAY</span></div>
<div class="kpi"><span class="tile">{{ic('cal',22)}}</span><b>{{st.week}}</b><span>THIS WEEK</span></div>
<div class="kpi"><span class="tile">{{ic('cal',22)}}</span><b>{{st.month}}</b><span>THIS MONTH</span></div>
<div class="kpi"><span class="tile">{{ic('chart',22)}}</span><b>{{st.total}}</b><span>ALL TIME</span></div></div>
<div class="kpi wide"><span class="tile">{{ic('dollar',22)}}</span><span>MONTHLY SPENT</span><b>{{st.month_spent|cur}}</b><div class="sub">{{st.month_name}}</div></div>
<div class="kpi wide pk" style="margin-top:12px"><span class="tile">{{ic('box',22)}}</span><span>ACTIVE PRODUCTS</span><b>{{st.products}}</b></div>
<div class="sec"><h3>{{ic('key',22)}} Recent Generated Keys</h3><a href="/history">View All {{ic('arrow',16)}}</a></div>
<div class="klist">{% for x in recent %}<div class="krow"><span class="tile">{{ic('key',20)}}</span>
<div class="m"><b>{{x.product_name}} {{x.plan_name}}</b><code>Key: {{x.key}}</code></div>
<div class="d">{{x.created|dt|truncate(6,True,'')}}</div><button class="cp" data-copy="{{x.key}}" aria-label="Copy key">{{ic('copy',16)}}</button></div>
{% else %}<div class="krow"><span class="mu">No keys generated yet.</span></div>{% endfor %}</div>
<div class="foot">&copy; {{year}} {{BRAND}}</div>{% endblock %}"""

T["generate.html"] = """{% extends 'rbase.html' %}{% block c %}<h2>{{ic('key',24)}} Generate Key</h2><div class=mu>Balance: <b style="color:#34d399">{{r.balance|cur}}</b></div>
{% for p in cat %}<div class=card><h3>{{p.name}}</h3>{% if not p.plans %}<div class=mu>No plans yet</div>{% endif %}
<div class=tw><table>{% for pl in p.plans %}{% set out = pl.mode=='stock' and pl.stock==0 %}<tr><td>{{pl.name}}<div class=mu>{{pl.days}} day(s){% if pl.mode=='stock' %} · {{pl.stock}} in stock{% endif %}</div></td>
<td><b style="color:#34d399">{{pl.price|cur}}</b>{% if pl.custom %} <span class="pill p">special</span>{% endif %}</td>
<td style="text-align:right"><form method=post onsubmit="return confirm('Purchase {{pl.name}} for {{pl.price|cur}}?')">
<input type=hidden name=plan_id value="{{pl.id}}"><button class=g {{'disabled' if out}}>{{'Out of stock' if out else 'Purchase Now'}}</button></form></td></tr>{% endfor %}</table></div></div>
{% else %}<div class=card>No products available.</div>{% endfor %}{% endblock %}"""

T["history.html"] = """{% extends 'rbase.html' %}{% block c %}<h2>{{ic('history',24)}} History</h2><div class="card tw"><table>
<tr><th>Key</th><th>Product / Plan</th><th>Price</th><th>Created</th><th>Expires</th><th>Status</th></tr>
{% for x in rows %}<tr><td><code>{{x.key}}</code></td><td>{{x.product_name}}<br><span class=mu>{{x.plan_name}}</span></td><td>{{x.price|cur}}</td>
<td>{{x.created|dt}}</td><td>{{x.expires|dt}}</td><td>{% if x.expires>now %}<span class="pill a">Active</span>{% else %}<span class="pill e">Expired</span>{% endif %}</td></tr>
{% else %}<tr><td colspan=6>No keys generated yet.</td></tr>{% endfor %}</table></div>{% endblock %}"""

T["api.html"] = """{% extends 'rbase.html' %}{% block c %}<h2>{{ic('code',24)}} API &amp; Docs</h2>
<div class=card><h3>Your Credentials</h3>
<p class=mu>Server URL</p><pre>{{base}}</pre><p class=mu>API Key</p><pre>{{r.api_key}}</pre>
<form method=post onsubmit="return confirm('Old key will stop working. Continue?')"><button class=r>Regenerate API Key</button></form></div>
<div class=card><h3>Authentication</h3><p>Send your key in every request header:</p><pre>X-API-Key: YOUR_API_KEY</pre></div>
<div class=card><h3>1. Check Balance</h3><pre>GET {{base}}/api/v1/balance</pre>
<pre>curl -H "X-API-Key: {{r.api_key}}" {{base}}/api/v1/balance</pre></div>
<div class=card><h3>2. Products &amp; Plan IDs</h3><p>Prices shown are <b>your</b> prices.</p><pre>GET {{base}}/api/v1/products</pre></div>
<div class=card><h3>3. Purchase (Generate Key)</h3><pre>POST {{base}}/api/v1/purchase
Content-Type: application/json

{"plan_id": 3}</pre>
<pre>{"success": true, "key": "PUBGCH-A1B2-C3D4-E5F6-7890", "product": "PUBG Cheat",
 "plan": "1 Day", "price": 90.0, "expires_at": 1767225600, "balance": 60.0}</pre></div>
<div class=card><h3>4. History</h3><pre>GET {{base}}/api/v1/history</pre><p class=mu>Returns your last 100 keys.</p></div>
<div class=card><h3>Errors</h3><table><tr><th>HTTP</th><th>error</th></tr>
<tr><td>401</td><td>INVALID_API_KEY</td></tr><tr><td>402</td><td>Insufficient balance</td></tr>
<tr><td>400</td><td>plan_id required / Plan not found / Out of stock / Account disabled</td></tr></table></div>
<div class=card><h3>Python Example</h3><pre>import requests
BASE="{{base}}"; H={"X-API-Key":"{{r.api_key}}"}
print(requests.get(BASE+"/api/v1/balance",headers=H).json())
r=requests.post(BASE+"/api/v1/purchase",headers=H,json={"plan_id":3}).json()
print(r.get("key"))</pre></div>{% endblock %}"""

T["abase.html"] = HEAD + """Admin</title><style>""" + CSS + """</style></head><body>
<div class=nav><b class=logo style="padding:7px 10px;display:inline-flex;align-items:center;gap:8px">{{ic('tool')}} ADMIN</b><a href="/admin" class="{{'on' if page=='home'}}">Home</a><a href="/admin/products" class="{{'on' if page=='products'}}">Products</a>
<a href="/admin/keys" class="{{'on' if page=='keys'}}">Sold Keys</a><a href="/admin/resellers" class="{{'on' if page=='resellers'}}">Resellers</a><a href="/admin/main-api" class="{{'on' if page=='mapi'}}">Main API</a><a href="/admin/backup" class="{{'on' if page=='backup'}}">Backup</a><a href="/admin/music" class="{{'on' if page=='music'}}">Music</a><a href="/admin/logout" style="margin-left:auto">Logout</a></div>
<div class=wrap>""" + FLASH + """{% block c %}{% endblock %}</div></body></html>"""

T["admin_home.html"] = """{% extends 'abase.html' %}{% block c %}<h2>Overview</h2><div class=grid>
<div class=stat><span class=mu>Resellers</span><b>{{st.resellers}}</b></div><div class=stat><span class=mu>Products</span><b>{{st.products}}</b></div>
<div class=stat><span class=mu>Keys Sold</span><b>{{st.keys}}</b></div><div class=stat><span class=mu>Revenue</span><b>{{st.revenue|cur}}</b></div>
<div class=stat><span class=mu>Credit Outstanding</span><b>{{st.credit|cur}}</b></div></div>
<div class="card tw"><h3>Recent Sales</h3><table><tr><th>Reseller</th><th>Product</th><th>Plan</th><th>Price</th><th>Time</th></tr>
{% for x in recent %}<tr><td>{{x.username}}</td><td>{{x.product_name}}</td><td>{{x.plan_name}}</td><td>{{x.price|cur}}</td><td>{{x.created|dt}}</td></tr>
{% else %}<tr><td colspan=5>No sales yet</td></tr>{% endfor %}</table></div>{% endblock %}"""

T["admin_products.html"] = """{% extends 'abase.html' %}{% block c %}<h2>Products &amp; Plans</h2>
<div class=card><h3>Add Product</h3><form class=row method=post><input type=hidden name=action value=product><input name=name placeholder="Product name" required><button>Add</button></form></div>
{% if prods %}<div class=card><h3>Add Plan</h3><form class=row method=post><input type=hidden name=action value=plan>
<select name=product_id>{% for x in prods %}<option value="{{x.p.id}}">{{x.p.name}}</option>{% endfor %}</select>
<input name=days type=number min=1 placeholder="Days (e.g. 1)" required style="width:130px">
<input name=price type=number step=any min=0 placeholder="Price" required style="width:120px">
<select name=mode><option value=stock>Manual keys</option><option value=api>External API</option><option value=random>Auto-generate</option></select><button>{{ic('plus')}} Add Plan</button></form><p class=hint>Plan name is made automatically from the days (1 &rarr; "1 Day", 7 &rarr; "7 Days"). Choose how keys are supplied: Manual keys, External API, or Auto-generate.</p></div>{% endif %}
{% for x in prods %}<div class=card><div style="display:flex;justify-content:space-between;align-items:center"><h3>{{x.p.name}}</h3>
<form method=post onsubmit="return confirm('Delete product and all plans?')"><input type=hidden name=action value=del_product><input type=hidden name=product_id value="{{x.p.id}}"><button class=r>Delete</button></form></div>
<div class=tw><table class=plans><tr><th>ID</th><th>Days</th><th>Price</th><th>Key source</th><th></th></tr>
{% for e in x.plans %}{% set pl=e.pl %}<tr><form method=post><input type=hidden name=action value=edit_plan><input type=hidden name=plan_id value="{{pl.id}}">
<td>{{pl.id}}</td><td><input name=days type=number value="{{pl.days}}" style="width:65px"></td>
<td><input name=price type=number step=any value="{{pl.price}}" style="width:90px"></td>
<td><select name=mode>{% for v,l in [('stock','Manual keys'),('api','External API'),('random','Auto-generate')] %}<option value="{{v}}" {{'selected' if (pl.mode or 'random')==v}}>{{l}}</option>{% endfor %}{% if pl.prov_pid %}<option value="provider" {{'selected' if pl.mode=='provider'}}>Main API #{{pl.prov_pid}}</option>{% endif %}</select></td>
<td style="white-space:nowrap"><button class=g>Save</button></form>
{% if (pl.mode or 'random')=='stock' %}<a class=btn href="/admin/stock/{{pl.id}}" style="padding:8px 12px">{{ic('key',16)}}Keys <span class="pill c">{{e.stock}}</span></a>{% elif pl.mode=='api' %}<a class=btn href="/admin/plan-api/{{pl.id}}" style="padding:8px 12px">{{ic('code',16)}}API</a>{% elif pl.mode=='provider' %}<span class="pill c">Main API #{{pl.prov_pid}}</span>{% endif %}
<form method=post style="display:inline" onsubmit="return confirm('Delete plan?')"><input type=hidden name=action value=del_plan><input type=hidden name=plan_id value="{{pl.id}}"><button class=r>{{ic('x',16)}}</button></form></td></tr>
{% else %}<tr><td colspan=5>No plans</td></tr>{% endfor %}</table></div></div>{% endfor %}{% endblock %}"""

T["admin_stock.html"] = """{% extends 'abase.html' %}{% block c %}<a href="/admin/products">{{ic('back',16)}} Back</a><h2>{{ic('key',24)}} {{pl.pname}} — {{pl.name}}</h2>
<div class=mu>Key source: <span class="pill p">{{ {'stock':'Manual keys','api':'External API','random':'Auto-generate','provider':'Main API'}[pl.mode or 'random'] }}</span> (change it on the Products page; keys below are used only in "Manual keys" mode)</div>
<div class=card><h3>Add Keys</h3><form method=post><input type=hidden name=action value=add><textarea name=keys placeholder="One key per line" required></textarea><button class=g style="margin-top:8px">{{ic('plus')}} Add Keys</button></form></div>
<div class="card tw"><div style="display:flex;justify-content:space-between;align-items:center"><h3>All Keys ({{rows|length}})</h3>
<form method=post onsubmit="return confirm('Remove all used keys?')"><input type=hidden name=action value=clear_used><button class="r">Clear used</button></form></div>
<table><tr><th>#</th><th>Key</th><th>Status</th><th></th></tr>
{% for k in rows %}<tr><td>{{k.id}}</td>
<td>{% if k.used %}<code>{{k.key}}</code>{% else %}<form method=post class=row style="flex-wrap:nowrap"><input type=hidden name=action value=edit><input type=hidden name=id value="{{k.id}}"><input name=key value="{{k.key}}" style="min-width:220px"><button class=g style="padding:8px 12px">Save</button></form>{% endif %}</td>
<td>{% if k.used %}<span class="pill e">Sold</span><div class=mu>{{k.used_by}} · {{k.used_at|dt}}</div>{% else %}<span class="pill a">Available</span>{% endif %}</td>
<td><form method=post onsubmit="return confirm('Delete this key?')"><input type=hidden name=action value=delete><input type=hidden name=id value="{{k.id}}"><button class=r>Delete</button></form></td></tr>
{% else %}<tr><td colspan=4>No keys added yet.</td></tr>{% endfor %}</table></div>{% endblock %}"""

T["admin_plan_api.html"] = """{% extends 'abase.html' %}{% block c %}<a href="/admin/products">{{ic('back',16)}} Back</a><h2>{{ic('code',24)}} {{pl.pname}} — {{pl.name}} (External API)</h2>
<div class=card><form method=post>
<p class=mu>API URL</p><input name=ext_url value="{{pl.ext_url or ''}}" placeholder="https://provider.com/api/generate" style="width:100%">
<p class=mu>Method</p><select name=ext_method><option {{'selected' if pl.ext_method=='POST'}}>POST</option><option {{'selected' if pl.ext_method=='GET'}}>GET</option></select>
<p class=mu>Headers (JSON)</p><textarea name=ext_headers placeholder='{"X-API-Key": "PROVIDER_KEY"}'>{{pl.ext_headers or ''}}</textarea>
<p class=mu>Body / params (JSON)</p><textarea name=ext_body placeholder='{"duration": "{days}"}'>{{pl.ext_body or ''}}</textarea>
<p class=mu>Key location in the response (e.g. <code>data.key</code>). Empty = whole response text.</p><input name=ext_path value="{{pl.ext_path or ''}}" placeholder="data.key" style="width:100%">
<p class=mu>Placeholders: <code>{days}</code> <code>{plan}</code> <code>{product}</code>. If the provider fails, the reseller's balance is refunded automatically.</p>
<button class=g>{{ic('save')}} Save API Settings</button></form></div>{% endblock %}"""

T["admin_keys.html"] = """{% extends 'abase.html' %}{% block c %}<h2>Sold Keys</h2><div class="card tw"><table>
<tr><th>Reseller</th><th>Key</th><th>Product / Plan</th><th>Price</th><th>Via</th><th>Created</th><th>Status</th></tr>
{% for x in rows %}<tr><td>{{x.username}}</td><td><code>{{x.key}}</code></td><td>{{x.product_name}}<br><span class=mu>{{x.plan_name}}</span></td><td>{{x.price|cur}}</td><td>{{x.via}}</td><td>{{x.created|dt}}</td>
<td>{% if x.expires>now %}<span class="pill a">Active</span>{% else %}<span class="pill e">Expired</span>{% endif %}</td></tr>
{% else %}<tr><td colspan=7>No keys sold yet.</td></tr>{% endfor %}</table></div>{% endblock %}"""

T["admin_resellers.html"] = """{% extends 'abase.html' %}{% block c %}<h2>Resellers</h2>
<div class=card><h3>Create Reseller</h3><form class=row method=post><input name=username placeholder="Username" required><input name=password placeholder="Password" required>
<input name=credit type=number step=any value=0 placeholder="Starting credit" style="width:140px"><button>Create</button></form></div>
<div class="card tw"><table><tr><th>User</th><th>Balance</th><th>Keys</th><th>Status</th><th></th></tr>
{% for x in rows %}<tr><td>{{x.username}}</td><td>{{x.balance|cur}}</td><td>{{x.kc}}</td><td>{% if x.active %}<span class="pill a">Active</span>{% else %}<span class="pill e">Disabled</span>{% endif %}</td>
<td><a class=btn href="/admin/reseller/{{x.id}}">Manage</a></td></tr>{% else %}<tr><td colspan=5>No resellers</td></tr>{% endfor %}</table></div>{% endblock %}"""

T["admin_reseller.html"] = """{% extends 'abase.html' %}{% block c %}<a href="/admin/resellers">{{ic('back',16)}} Back</a><h2>{{r.username}} <span class=mu>Balance: {{r.balance|cur}}</span></h2>
<div class=card><h3>Add / Deduct Credit</h3><form class=row method=post><input type=hidden name=action value=credit><input name=amount type=number step=any placeholder="Amount (negative to deduct)" required><button class=g>Update</button></form></div>
<div class=card><h3>Change Password</h3><form class=row method=post><input type=hidden name=action value=password><input name=password placeholder="New password" required><button>Change</button></form></div>
<div class=card><h3>Custom Prices</h3><p class=mu>Leave empty to use the base price.</p><form method=post><input type=hidden name=action value=prices><div class=tw><table>
<tr><th>Product</th><th>Plan</th><th>Custom Price</th></tr>
{% for p in cat %}{% for pl in p.plans %}<tr><td>{{p.name}}</td><td>{{pl.name}}</td><td><input name="p_{{pl.id}}" type=number step=any value="{{pl.price if pl.custom}}" style="width:120px"></td></tr>{% endfor %}{% endfor %}</table></div>
<button class=g style="margin-top:10px">Save Prices</button></form></div>
<div class=card><form method=post style="display:inline"><input type=hidden name=action value=toggle><button>{{'Disable' if r.active else 'Enable'}} Account</button></form>
<form method=post style="display:inline" onsubmit="return confirm('Delete reseller and history?')"><input type=hidden name=action value=delete><button class=r>Delete Reseller</button></form></div>{% endblock %}"""

T["admin_music.html"] = """{% extends 'abase.html' %}{% block c %}<h2>{{ic('music',24)}} Music ({{rows|length}}/{{mx}})</h2>
<div class=card><form method=post enctype=multipart/form-data class=row><input name=title placeholder="Title (optional)"><input type=file name=file accept="audio/*">
<span class=mu>or</span><input name=url placeholder="Direct audio URL (.mp3)"><button>Add Song</button></form>
<p class=mu>Songs play in order at the top of the reseller panel. Free Render disk resets on redeploy, so direct URLs are safer than uploads.</p></div>
<div class="card tw"><table>{% for m in rows %}<tr><td>{{loop.index}}</td><td>{{m.title}}</td><td><audio controls preload=none src="{{m.url}}" style="height:32px"></audio></td>
<td><form method=post><input type=hidden name=action value=delete><input type=hidden name=id value="{{m.id}}"><button class=r>Delete</button></form></td></tr>
{% else %}<tr><td>No songs</td></tr>{% endfor %}</table></div>{% endblock %}"""

SUB = """<div style="display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 4px">
<a class=btn href="/admin/main-api" style="{{'' if page2=='c' else 'background:transparent;border:1px solid var(--bd);box-shadow:none'}}">{{ic('key',16)}}Connection</a>
<a class=btn href="/admin/main-api/products" style="{{'' if page2=='p' else 'background:transparent;border:1px solid var(--bd);box-shadow:none'}}">{{ic('box',16)}}All Products</a></div>"""

T["admin_mapi.html"] = """{% extends 'abase.html' %}{% block c %}{% set page2='c' %}<h2>{{ic('code',24)}} Main API</h2>""" + SUB + """
<div class=card><h3>{{ic('key',20)}} Connection</h3>
<form method=post><input type=hidden name=action value=save>
<p class=mu>Base URL</p><input name=base value="{{base}}" style="width:100%" required>
<p class=mu>API Token{% if tail %} &mdash; saved (ends with <code>{{tail}}</code>). Leave empty to keep it.{% endif %}</p>
<input name=token type=password autocomplete=off placeholder="Paste your API token" style="width:100%" {{'' if tail else 'required'}}>
<button class=g style="margin-top:12px">{{ic('check')}} Save &amp; Connect</button></form></div>
<div class=card><h3>{{ic('wallet',20)}} Status &amp; Balance</h3>
{% if st %}{% if st.ok %}<span class="pill a">Connected</span>
<div style="font-size:30px;font-weight:800;color:#34d399;margin:8px 0">{{st.balance|cur}}{% if st.balance_usd is not none %} <span class=mu>(${{st.balance_usd|money}})</span>{% endif %}</div>
{% else %}<span class="pill e">Not connected</span><div class=mu style="margin:8px 0">{{st.msg}}</div>{% endif %}
<div class=mu>Last checked: {{st.ts|dt}}</div>
{% else %}<div class=mu>Not checked yet. Save your token, then press Check Balance.</div>{% endif %}
<form method=post style="margin-top:12px"><input type=hidden name=action value=check><button>{{ic('wallet')}} Check Balance</button></form></div>
{% endblock %}"""

T["admin_mapi_products.html"] = """{% extends 'abase.html' %}{% block c %}{% set page2='p' %}<h2>{{ic('box',24)}} All Products</h2>""" + SUB + """
{% if not cat %}<div class=card>No catalog yet. Connect the API first (Connection tab), then press Refresh.<br><br><a class=btn href="/admin/main-api/products?refresh=1">Refresh from API</a></div>
{% else %}
<form method=post>
<div class=card><div class=mu>Provider rates are already in INR. Imported plans are bought automatically from the main API when a reseller purchases.</div>
<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:12px">
<label class=mu>Markup % <input name=markup type=number step=any min=0 value=0 style="width:90px"></label>
<label class=mu><input type=checkbox name=overwrite> Also reset prices of already imported plans</label></div>
<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
<button class=g name=scope value=sel>{{ic('plus')}} Import selected</button>
<button name=scope value=all onclick="return confirm('Import ALL products from the main API?')">{{ic('box')}} Import ALL</button>
<a class=btn href="/admin/main-api/products?refresh=1" style="background:transparent;border:1px solid var(--bd);box-shadow:none">Refresh</a>
<label class=mu style="margin-left:auto"><input type=checkbox id=selall> Select all</label></div>
<div class=mu style="margin-top:8px">Catalog fetched: {{cat.ts|dt}} &middot; Edit selling prices later in <a href="/admin/products">Products</a>.</div></div>
{% for g in groups %}<div class=card><div style="display:flex;justify-content:space-between;align-items:center"><h3>{{g.name}}</h3><label class=mu><input type=checkbox class=ga> all</label></div>
<div class=tw><table><tr><th></th><th>Plan</th><th>ID</th><th>Cost</th><th>Status</th></tr>
{% for p in g.plans %}<tr><td><input type=checkbox name=pid value="{{p.pid}}" class=pc></td><td>{{p.dur}}</td><td>{{p.pid}}</td>
<td>{{p.inr|cur}}{% if p.usd is not none %} <span class=mu>${{p.usd|money}}</span>{% endif %}</td>
<td>{% if p.mine is not none %}<span class="pill a">Imported</span> <span class=mu>your price {{p.mine|cur}}</span>{% else %}<span class="pill p">New</span>{% endif %}</td></tr>{% endfor %}</table></div></div>
{% else %}<div class=card>The catalog is empty.</div>{% endfor %}
</form>
<script>
document.querySelectorAll('.ga').forEach(g=>g.onchange=()=>g.closest('.card').querySelectorAll('.pc').forEach(c=>c.checked=g.checked));
document.getElementById('selall').onchange=function(){document.querySelectorAll('.pc,.ga').forEach(c=>c.checked=this.checked)};
</script>
{% endif %}{% endblock %}"""

T["admin_backup.html"] = """{% extends 'abase.html' %}{% block c %}<h2>{{ic('save',24)}} Backup &amp; Restore</h2>
<div class=card><h3>Download Backup</h3>
<p class=mu>One file with everything: products, plans, prices, resellers (balances &amp; passwords), keys, stock, Main API token. Keep it private.</p>
<div class=mu>Now: {% for k,v in counts.items() %}{{k}} <b>{{v}}</b>{{ ' &middot; '|safe if not loop.last }}{% endfor %}</div>
<a class=btn href="/admin/backup/download" style="margin-top:12px">{{ic('save')}} Download Backup</a></div>
<div class=card><h3>Upload Backup (Restore)</h3>
<p class=mu>Replaces ALL current data with the file. If the file is wrong, nothing changes. Uploaded music files are not inside the backup (use music URLs).</p>
<form method=post action="/admin/backup/restore" enctype=multipart/form-data onsubmit="return confirm('This will REPLACE all current data with the backup. Continue?')">
<input type=file name=file accept=".json,application/json" required> <button class=r>{{ic('plus')}} Upload &amp; Restore</button></form></div>
{% endblock %}"""

TEMPLATES = T
