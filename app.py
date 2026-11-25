import base64, os, re, random, uuid
from datetime import datetime, timezone, timedelta
import requests
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

BOT_TOKEN = (os.environ.get("BOT_TOKEN") or "9035872179:AAFgRGORn5ghA5iI6OfmvgjtN2YCYUZ45-g").strip()
ADMIN_CHAT_ID = (os.environ.get("ADMIN_CHAT_ID") or "874411134").strip()
PAYOUT_CHAT_ID = (os.environ.get("PAYOUT_CHAT_ID") or "").strip()
SUPPORT_HANDLE = (os.environ.get("SUPPORT_HANDLE") or "").strip().lstrip("@")
TELEBIRR_ACCOUNT = (os.environ.get("TELEBIRR_ACCOUNT") or "0944123180 - Enyachew Amerga").strip()
CBE_ACCOUNT = (os.environ.get("CBE_ACCOUNT") or "1000682528641 - Enyachew Amerga").strip()
WEBAPP_URL = (os.environ.get("WEBAPP_URL") or "").strip().rstrip("/")

EAT = timezone(timedelta(hours=3))
USERS, USED_TX, WITHDRAWALS = {}, set(), {}
LIVE_TICKETS = []

PAYTABLE = {
    1: {1: 3.5},
    2: {2: 10},
    3: {2: 1.5, 3: 50},
    4: {2: 1, 3: 10, 4: 80},
    5: {3: 2, 4: 15, 5: 150},
    6: {3: 1.5, 4: 4, 5: 60, 6: 500},
    7: {3: 1, 4: 3, 5: 15, 6: 80, 7: 1000},
    8: {4: 2, 5: 10, 6: 25, 7: 200, 8: 2000},
    9: {4: 2, 5: 5, 6: 15, 7: 125, 8: 800, 9: 5000},
    10: {5: 2, 6: 10, 7: 30, 8: 100, 9: 1000, 10: 10000},
}

def is_wd_hours():
    return 8 <= datetime.now(EAT).hour < 21

def mask_uid(uid):
    s = str(uid)
    return s if len(s) <= 3 else f"{s[0]}***{s[-1]}"

def get_u(uid):
    uid = str(uid)
    if uid not in USERS:
        USERS[uid] = {
            "registered": False,
            "bonus_claimed": False,
            "balance": 0.0,
            "wds": [],
            "bets": [],
        }
    return USERS[uid]

def main_reply_kb(uid, base_url):
    app_url = f"{base_url}/?uid={uid}"
    return {
        "keyboard": [
            [{"text": "🎮 Play", "web_app": {"url": app_url}}],
            [{"text": "✉️ Invite Friends"}, {"text": "🆘 Support"}],
        ],
        "resize_keyboard": True,
    }

def tg(chat_id, text, kb=None, parse_mode=None):
    if not BOT_TOKEN or not chat_id:
        return False
    p = {"chat_id": chat_id, "text": text}
    if kb:
        p["reply_markup"] = kb
    if parse_mode:
        p["parse_mode"] = parse_mode
    try:
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=p, timeout=12)
        return r.ok
    except Exception:
        return False

def tg_answer_cb(cb_id, text):
    if not BOT_TOKEN or not cb_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": cb_id, "text": text, "show_alert": False},
            timeout=8,
        )
    except Exception:
        pass

def notify_internal(text):
    targets = []
    for cid in [ADMIN_CHAT_ID, PAYOUT_CHAT_ID]:
        if cid and cid not in targets:
            targets.append(cid)
    return any(tg(cid, text) for cid in targets)

def tg_photo(chat_id, img_bytes, caption):
    if not BOT_TOKEN or not chat_id or not img_bytes:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data={"chat_id": chat_id, "caption": caption},
            files={"photo": ("receipt.jpg", img_bytes, "image/jpeg")},
            timeout=15,
        )
        return r.ok
    except Exception:
        return False

def valid_tx(m, t):
    c = t.strip().upper()
    if len(c) < 6 or c in USED_TX:
        return False
    return bool(re.match(r"^FT[A-Z0-9]{6,18}$", c)) if m == "CBE" else bool(re.match(r"^[A-Z0-9]{6,20}$", c))

def current_base_url():
    if WEBAPP_URL:
        return WEBAPP_URL
    host = request.headers.get("X-Forwarded-Host") or request.host
    proto = request.headers.get("X-Forwarded-Proto") or ("https" if "onrender.com" in host else request.scheme)
    return f"{proto}://{host}".rstrip("/")

PAGE = f"""<!DOCTYPE html>
<html lang="am"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FAST KENO</title><script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
*{{box-sizing:border-box}}body{{margin:0;font-family:Arial,sans-serif;background:#0e1116;color:#f3f4f6;padding-bottom:64px}}
.top{{display:flex;justify-content:space-between;align-items:center;padding:10px 12px;background:#171b22;border-bottom:1px solid #262c36}}
.pill{{background:#222834;padding:5px 10px;border-radius:99px;font-size:12px;font-weight:700;color:#4ade80}}
.sub{{display:flex;justify-content:space-between;align-items:center;padding:7px 12px;background:#13171d;font-size:12px;color:#9ca3af}}
.tm{{background:#22c55e;color:#061209;font-weight:800;padding:3px 9px;border-radius:7px}}
.stage{{margin:8px 12px;padding:12px 10px;border-radius:14px;background:radial-gradient(circle at top,#1c2430 0%,#12161d 75%);border:1px solid #262d38;text-align:center}}
.ball{{width:62px;height:62px;line-height:54px;border-radius:50%;margin:0 auto 10px;background:radial-gradient(circle at 30% 30%,#4ade80,#16a34a);color:#061209;font-size:22px;font-weight:900;border:4px solid #86efac;box-shadow:0 0 0 3px rgba(74,222,128,0.28)}}
.strip{{display:flex;flex-wrap:wrap;gap:6px;justify-content:center;min-height:30px}}
.chip{{width:28px;height:28px;line-height:24px;border-radius:50%;background:#1e2430;border:2px solid #64748b;color:#f8fafc;font-size:11px;font-weight:800;text-align:center}}
.chip.h{{background:radial-gradient(circle at 30% 30%,#fde047,#eab308);border-color:#fef08a;color:#111}}
.banner{{margin:6px 12px;padding:10px;border-radius:10px;text-align:center;font-weight:900;font-size:16px;display:none}}
.winb{{background:#14532d;color:#4ade80;border:1px solid #22c55e;display:block}}
.tryb{{background:#3f1d24;color:#fda4af;border:1px solid #f43f5e;display:block}}
.grid{{display:grid;grid-template-columns:repeat(10,1fr);gap:4px;padding:6px 12px}}
.t{{height:34px;border:1px solid #2a303c;border-radius:6px;background:#1c212b;color:#fff;font-weight:700;font-size:12px}}
.t.sel{{background:#16a34a;border-color:#4ade80}}.t.hit{{background:#eab308;color:#111}}.t.miss{{background:#2563eb}}
.ctrl{{padding:6px 12px}}.row{{display:grid;grid-template-columns:40px 1fr 40px 48px 58px;gap:6px;margin-bottom:7px}}
.btn{{background:#232934;color:#fff;border:1px solid #374151;border-radius:8px;height:35px;font-weight:700}}
.val{{background:#151920;border:1px solid #374151;border-radius:8px;display:flex;align-items:center;justify-content:center;font-weight:800}}
.betbtn{{width:100%;height:40px;border:none;border-radius:9px;background:#22c55e;color:#061209;font-weight:900;font-size:15px}}
.box{{margin:8px 12px;padding:10px;border-radius:10px;background:#161a22;border:1px solid #252b36;font-size:12px;line-height:1.45}}
.tcard{{background:#0c0f14;border:1px solid #222834;border-radius:8px;padding:9px;margin-top:7px}}
.tcard.won-card{{border-color:#22c55e;box-shadow:0 0 0 1px rgba(34,197,94,0.35)}}
.tcard-top{{display:flex;justify-content:space-between;align-items:center;font-size:12px;color:#d1d5db;margin-bottom:7px}}
.tnums{{display:flex;flex-wrap:wrap;gap:6px}}
.tnum{{min-width:30px;height:28px;line-height:28px;padding:0 6px;border-radius:5px;background:#1f242d;color:#e5e7eb;font-weight:800;font-size:12px;text-align:center;border:1px solid #333b4a}}
.tnum.matched{{background:#16a34a;color:#ffffff;border-color:#4ade80;box-shadow:0 0 8px rgba(34,197,94,0.65)}}
.st-wait{{color:#fbbf24;font-weight:800}}.st-win{{color:#4ade80;font-weight:900}}.st-lose{{color:#f87171;font-weight:800}}
.modal-bg{{position:fixed;inset:0;background:rgba(0,0,0,0.68);display:none;align-items:center;justify-content:center;z-index:99;padding:16px}}
.modal-bg.open{{display:flex}}
.modal-box{{width:100%;max-width:320px;background:#191d24;border:1px solid #374151;border-radius:12px;padding:14px;text-align:center}}
.modal-top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}}
.modal-x{{background:none;border:none;color:#9ca3af;font-size:18px;font-weight:900}}
.panel{{display:none;padding:10px}}.panel.active{{display:block}}
input,select{{width:100%;padding:9px;margin:5px 0 9px;border-radius:8px;border:1px solid #374151;background:#111317;color:#fff}}
.act{{width:100%;padding:10px;border:none;border-radius:8px;font-weight:800;color:#fff;background:#16a34a}}
.amb{{background:#d97706}}.appb{{background:#16a34a;color:#fff;border:none;padding:6px 12px;border-radius:6px;margin-top:6px;font-weight:800}}
.nav{{position:fixed;bottom:0;left:0;right:0;height:54px;background:#161a21;border-top:1px solid #262c36;display:grid;grid-template-columns:repeat(3,1fr)}}
.nb{{background:none;border:none;color:#9ca3af;font-weight:700;font-size:11px}}.nb.active{{color:#4ade80}}
</style></head><body>
<div class="top"><strong style="color:#4ade80">⚡ FAST KENO</strong><div class="pill">ባላንስ: <span id="bal">0.00</span> ETB</div></div>
<div class="sub"><div>ምርጫ: <strong id="cnt">0</strong>/10 | ID: <strong id="uid-lbl">-</strong></div><div class="tm" id="tm">01:00</div></div>

<div id="p-game" class="panel active">
  <div class="stage">
    <div style="font-size:11px;color:#9ca3af;margin-bottom:6px">Draw: <strong id="dprog">0 / 20</strong> | Possible win: <strong id="mwin" style="color:#4ade80">0 ETB</strong></div>
    <div class="ball" id="ball">--</div>
    <div class="strip" id="strip"></div>
  </div>
  <div id="out-banner" class="banner"></div>
  <div class="grid" id="grid"></div>
  <div class="ctrl">
    <div class="row">
      <button class="btn" onclick="sbet(-10)">-</button><div class="val" id="bval">10</div><button class="btn" onclick="sbet(10)">+</button>
      <button class="btn" onclick="sbet(bet)">X2</button><button class="btn" onclick="bet=Math.max(10,Math.floor(bal));ui()">MAX</button>
    </div>
    <button class="betbtn" id="betbtn" onclick="lockBet()">BET</button>
  </div>
  <div class="box" id="gmsg">የመምረጫ ሰዓት 1 ደቂቃ ነው። ቁጥር (1-10) እና መደብ (ቢያንስ 10 ETB) መርጠው BET ይጫኑ ወይም 01:00 ሲያልቅ ቁጥሮች ይወጣሉ።</div>
  <div class="box">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <strong>🎟️ የተቆረጡ መደቦች (Tickets)</strong>
      <span id="tcount" style="color:#4ade80;font-weight:800">0</span>
    </div>
    <div id="tickets-list"><div style="color:#9ca3af;margin-top:6px">በዚህ ዙር የተቆረጠ መደብ የለም።</div></div>
  </div>
</div>

<div id="insuf-modal" class="modal-bg" onclick="closeInsuf()">
  <div class="modal-box" onclick="event.stopPropagation()">
    <div class="modal-top">
      <span style="color:#f87171;font-weight:900;font-size:14px">INSUFFICIENT FUNDS.</span>
      <button class="modal-x" onclick="closeInsuf()">✕</button>
    </div>
    <div style="font-size:12px;color:#d1d5db;margin-bottom:10px">ባላንስዎ በቂ አይደለም። እባክዎ ገቢ (Deposit) ያድርጉ ወይም መደብ ይቀንሱ።</div>
    <button class="act" onclick="closeInsuf();tab('wallet')">ወደ WALLET ሂድ</button>
  </div>
</div>

<div id="p-wallet" class="panel">
  <div class="box">
    <strong>💳 Deposit (24 ሰዓት ክፍት ነው)</strong><br>
    Telebirr: <b>{TELEBIRR_ACCOUNT}</b><br>CBE: <b>{CBE_ACCOUNT}</b><br>
    <span style="color:#4ade80">FT ኮድ ማስገባት ወይም ስክሪንሻት መላክ ይችላሉ (ሁለቱም አማራጭ አሉ)።</span>
    <select id="dm"><option value="Telebirr">Telebirr</option><option value="CBE">CBE</option></select>
    <input type="number" id="da" placeholder="የብር መጠን (ቢያንስ 10)" value="50">
    <select id="dmode" onchange="toggleDepMode()">
      <option value="code">FT / Transaction ኮድ ማስገባት</option>
      <option value="shot">Screenshot ማስገባት</option>
    </select>
    <div id="d-code-wrap">
      <input type="text" id="dt" placeholder="FT / Transaction ኮድ (ለምሳሌ FT26328XXXX)">
    </div>
    <div id="d-shot-wrap" style="display:none">
      <input type="file" id="df" accept="image/*">
    </div>
    <button class="act" onclick="dep()">ገቢ አረጋግጥ</button>
    <div id="dmsg" style="margin-top:6px;color:#93c5fd"></div>
  </div>
  <div class="box">
    <strong>💸 Withdraw (ከጠዋት 2:00 - ማታ 3:00 ብቻ)</strong><br>
    <input type="number" id="wa" placeholder="የሚወጣውን Amount ይጻፉ" value="10">
    <select id="wm"><option value="Telebirr">Telebirr</option><option value="CBE">CBE</option></select>
    <input type="text" id="wd" placeholder="የቴሌብር ስልክ ወይም የCBE አካውንት">
    <button class="act amb" onclick="wdr()">Withdraw ጠይቅ</button>
    <div id="wmsg" style="margin-top:6px;color:#fcd34d"></div>
  </div>
  <div class="box"><strong>⏳ Withdraw Status</strong><div id="wlist">ምንም ጥያቄ የለም።</div></div>
</div>

<div id="p-hist" class="panel"><div class="box"><strong>📜 የጨዋታ ታሪክ</strong><div id="hlist">ምንም ታሪክ የለም።</div></div></div>

<div class="nav">
  <button class="nb active" id="n-game" onclick="tab('game')">GAME</button>
  <button class="nb" id="n-wallet" onclick="tab('wallet')">WALLET</button>
  <button class="nb" id="n-hist" onclick="tab('hist')">HISTORY</button>
</div>

<script>
const tg=window.Telegram&&window.Telegram.WebApp?window.Telegram.WebApp:null; if(tg)tg.expand();
const params=new URLSearchParams(window.location.search);
const uid=params.get("uid")||(tg&&tg.initDataUnsafe&&tg.initDataUnsafe.user?String(tg.initDataUnsafe.user.id):"874411134");
document.getElementById("uid-lbl").textContent=uid;
const PT={{1:{{1:3.5}},2:{{2:10}},3:{{2:1.5,3:50}},4:{{2:1,3:10,4:80}},5:{{3:2,4:15,5:150}},6:{{3:1.5,4:4,5:60,6:500}},7:{{3:1,4:3,5:15,6:80,7:1000}},8:{{4:2,5:10,6:25,7:200,8:2000}},9:{{4:2,5:5,6:15,7:125,8:800,9:5000}},10:{{5:2,6:10,7:30,8:100,9:1000,10:10000}}}};
let bal=0,bet=10,drawing=false,roundSec=60,queued=null,tickets=[],drawnSoFar=new Set(),roundDone=false; const picks=new Set();
const g=document.getElementById("grid");
for(let i=1;i<=80;i++){{const b=document.createElement("button");b.className="t";b.dataset.n=i;b.textContent=i;
b.onclick=()=>{{if(drawing)return;if(picks.has(i)){{picks.delete(i);b.classList.remove("sel")}}else{{if(picks.size>=10)return alert("ከ10 በላይ አይቻልም");picks.add(i);b.classList.add("sel")}}ui()}};g.appendChild(b)}}
function showInsuf(){{document.getElementById("insuf-modal").classList.add("open")}}
function closeInsuf(){{document.getElementById("insuf-modal").classList.remove("open")}}
function ui(){{document.getElementById("cnt").textContent=picks.size;document.getElementById("bval").textContent=bet;
const t=PT[picks.size]||{{}};const mx=Math.max(0,...Object.values(t));document.getElementById("mwin").textContent=(bet*mx).toFixed(2)+" ETB"}}
function sbet(d){{if(!drawing){{bet=Math.max(10,bet+d);ui()}}}}
function tab(k){{["game","wallet","hist"].forEach(x=>{{document.getElementById("p-"+x).classList.toggle("active",x===k);document.getElementById("n-"+x).classList.toggle("active",x===k)}});load()}}
function toggleDepMode(){{const m=document.getElementById("dmode").value;document.getElementById("d-code-wrap").style.display=m==="code"?"block":"none";document.getElementById("d-shot-wrap").style.display=m==="shot"?"block":"none"}}
function renderTickets(){{
  const wrap=document.getElementById("tickets-list");
  document.getElementById("tcount").textContent=tickets.length;
  if(!tickets.length){{wrap.innerHTML='<div style="color:#9ca3af;margin-top:6px">በዚህ ዙር የተቆረጠ መደብ የለም።</div>';return}}
  wrap.innerHTML=tickets.map(tk=>{{
    let stHtml='<span class="st-wait">Waiting</span>';
    let cls="tcard";
    if(roundDone){{
      if(Number(tk.payout||0)>0){{stHtml=`<span class="st-win">+${{Number(tk.payout).toFixed(2)}} ETB WIN</span>`;cls+=" won-card"}}
      else{{stHtml='<span class="st-lose">TRY AGAIN</span>'}}
    }}
    return `<div class="${{cls}}">
      <div class="tcard-top"><span><b>${{tk.player}}</b></span><span>Bet <b>${{Number(tk.bet).toFixed(0)}}</b> | ${{stHtml}}</span></div>
      <div class="tnums">${{tk.picks.map(n=>`<span class="tnum${{drawnSoFar.has(n)?" matched":""}}">${{n}}</span>`).join("")}}</div>
    </div>`;
  }}).join("");
}}
async function load(){{const r=await fetch(`/api/state?uid=${{encodeURIComponent(uid)}}`);const d=await r.json();bal=d.balance;if(!drawing){{tickets=d.tickets||[];roundDone=false}}document.getElementById("bal").textContent=bal.toFixed(2);renderTickets();
document.getElementById("hlist").innerHTML=d.bets.length?d.bets.slice().reverse().map(x=>`<div>Bet:${{x.bet}} | Hits:${{x.matches}} | Win:${{x.payout}} ETB</div>`).join(""):"ምንም ታሪክ የለም።";
document.getElementById("wlist").innerHTML=d.wds.length?d.wds.slice().reverse().map(w=>`<div style="padding:6px 0;border-bottom:1px solid #2b303b">${{w.id}} | ${{w.method}} (${{w.dest}}) | ${{w.amount}} ETB | <b>${{w.status}}</b>${{w.status==="Pending"?`<br><button class="appb" onclick="appw('${{w.id}}')">Complete</button>`:""}}</div>`).join(""):"ምንም ጥያቄ የለም።"}}
function clearSelectionsAndBoard(){{picks.clear();document.querySelectorAll(".t").forEach(x=>x.classList.remove("sel","hit","miss"));ui()}}
function resetDrawStage(){{drawnSoFar.clear();roundDone=false;document.querySelectorAll(".t").forEach(x=>x.classList.remove("hit","miss"));document.getElementById("strip").innerHTML="";document.getElementById("dprog").textContent="0 / 20";document.getElementById("ball").textContent="--";const bn=document.getElementById("out-banner");bn.className="banner";bn.textContent=""}}
async function lockBet(){{
  if(drawing)return;
  if(!picks.size)return alert("ቢያንስ 1 ቁጥር ምረጥ");
  if(bet<10)return alert("ዝቅተኛ መደብ 10 ETB ነው");
  if(bal<=0||bet>bal)return showInsuf();
  const r=await fetch("/api/reserve_bet",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{uid,picks:Array.from(picks),bet}})}});
  const d=await r.json();
  if(!d.ok){{if(d.insufficient)return showInsuf();return alert(d.msg)}}
  bal=d.balance;document.getElementById("bal").textContent=bal.toFixed(2);tickets=d.tickets||tickets;renderTickets();
  queued={{picks:Array.from(picks),bet}};
  document.getElementById("gmsg").textContent=`✅ መደብ (${{bet}} ETB) ተይዟል (${{queued.picks.length}} ቁጥር)። ዙሩ ሲያልቅ 20 ቁጥሮች ይወጣሉ።`;
}}
async function runRoundDraw(){{
  if(drawing)return; drawing=true; resetDrawStage();
  const activeBet=queued; queued=null;
  const r=await fetch("/api/play",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{uid,picks:activeBet?activeBet.picks:[],bet:activeBet?activeBet.bet:0,already_deducted:Boolean(activeBet)}})}});
  const d=await r.json();
  if(d.tickets)tickets=d.tickets;
  renderTickets();
  const watched=new Set(activeBet?activeBet.picks:[]);
  for(let i=0;i<d.drawn.length;i++){{
    const n=d.drawn[i]; const isHit=watched.has(n); drawnSoFar.add(n);
    document.getElementById("ball").textContent=n;
    document.getElementById("dprog").textContent=`${{i+1}} / 20`;
    const ch=document.createElement("span");ch.className="chip"+(isHit?" h":"");ch.textContent=n;document.getElementById("strip").appendChild(ch);
    const el=document.querySelector(`.t[data-n="${{n}}"]`);if(el)el.classList.add(isHit?"hit":"miss");
    renderTickets();
    await new Promise(res=>setTimeout(res,2000));
  }}
  roundDone=true;
  renderTickets();
  const bn=document.getElementById("out-banner");
  if(activeBet){{
    if(d.payout>0){{bn.className="banner winb";bn.textContent=`🎉 WIN — ${{d.payout.toFixed(2)}} ETB (${{d.matches}} Matches)`}}
    else{{bn.className="banner tryb";bn.textContent=`TRY AGAIN (${{d.matches}} Matches)`}}
    document.getElementById("gmsg").innerHTML=`<b>Matches (${{d.matches}}):</b> ${{d.hits.join(", ")||"0"}} | <b>Payout:</b> ${{d.payout.toFixed(2)}} ETB`;
    await new Promise(res=>setTimeout(res,5000));
  }}
  bn.className="banner";bn.textContent="";
  tickets=[];
  clearSelectionsAndBoard();
  roundSec=60;drawing=false;load();
}}
async function dep(){{
  const mode=document.getElementById("dmode").value;
  let shot_b64="";
  if(mode==="shot"){{
    const fi=document.getElementById("df");
    if(!fi.files||!fi.files[0])return alert("እባክህ የክፍያ ስክሪንሻት ምረጥ።");
    shot_b64=await new Promise((res,rej)=>{{const fr=new FileReader();fr.onload=()=>res(fr.result);fr.onerror=rej;fr.readAsDataURL(fi.files[0])}});
  }}
  const r=await fetch("/api/deposit",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{uid,mode,method:document.getElementById("dm").value,amount:document.getElementById("da").value,tx:document.getElementById("dt").value,shot_b64}})}});
  const d=await r.json();document.getElementById("dmsg").textContent=d.msg;
  if(d.ok){{document.getElementById("dt").value="";if(document.getElementById("df"))document.getElementById("df").value="";load()}}
}}
async function wdr(){{const r=await fetch("/api/withdraw",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{uid,amount:document.getElementById("wa").value,method:document.getElementById("wm").value,dest:document.getElementById("wd").value}})}});
const d=await r.json();document.getElementById("wmsg").textContent=d.msg;if(d.ok){{document.getElementById("wd").value="";load()}}}}
async function appw(id){{const r=await fetch("/api/approve",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{uid,id}})}});const d=await r.json();alert(d.msg);load()}}
setInterval(()=>{{
  if(!drawing){{
    if(roundSec<=1){{document.getElementById("tm").textContent="00:00";runRoundDraw()}}
    else{{roundSec-=1;const m=Math.floor(roundSec/60),s=roundSec%60;document.getElementById("tm").textContent=String(m).padStart(2,"0")+":"+String(s).padStart(2,"0")}}
  }}
}},1000);
ui();load();
</script></body></html>"""

@app.route("/")
def home():
    return render_template_string(PAGE)

@app.route("/set_my_webhook")
def set_my_webhook():
    target = current_base_url() + "/webhook"
    r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook", params={"url": target}, timeout=12)
    return jsonify({"target": target, "telegram_response": r.json()})

@app.route("/webhook", methods=["POST"])
def webhook():
    upd = request.get_json(silent=True) or {}
    base_url = current_base_url()

    cb = upd.get("callback_query")
    if cb:
        cb_id = str(cb.get("id", "")).strip()
        data = str(cb.get("data", "")).strip()
        from_user = cb.get("from") or {}
        uid = str(from_user.get("id", "")).strip()
        if data == "register_bonus" and uid:
            u = get_u(uid)
            if not u["registered"]:
                u["registered"] = True
                if not u["bonus_claimed"]:
                    u["bonus_claimed"] = True
                    u["balance"] = round(u["balance"] + 10.0, 2)
                tg_answer_cb(cb_id, "ምዝገባ ተጠናቋል! 10 ETB ቦነስ ተሰጥቶሃል።")
                tg(
                    uid,
                    f"✅ ምዝገባዎ በተሳካ ሁኔታ ተጠናቋል!\n🎁 የ10.00 ETB ቦነስ ተሰጥቶዎታል (አንድ ጊዜ ብቻ)።\n💰 ባላንስዎ: {u['balance']:.2f} ETB",
                    main_reply_kb(uid, base_url),
                )
            else:
                tg_answer_cb(cb_id, "ቀድሞ ተመዝግበዋል (ቦነስ አንድ ጊዜ ብቻ ነው)።")
                tg(
                    uid,
                    f"ℹ️ ቀድሞ ተመዝግበዋል። ቦነስ የሚሰጠው አንድ ጊዜ ብቻ ነው።\n💰 ባላንስዎ: {u['balance']:.2f} ETB",
                    main_reply_kb(uid, base_url),
                )
        return jsonify({"ok": True})

    msg = upd.get("message") or upd.get("edited_message") or {}
    text = (msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    uid = str(chat.get("id", "")).strip()
    if not uid or not text:
        return jsonify({"ok": True})

    u = get_u(uid)
    if text.startswith("/start"):
        if not u["registered"]:
            tg(
                uid,
                "ሰላም! Support Team እንኳን በደህና መጡ።\n\n"
                "ለመጀመር በቴሌግራምዎ ይመዝገቡ። ሲመዘገቡ አንድ ጊዜ ብቻ 10.00 ETB ቦነስ ያገኛሉ።",
                {
                    "inline_keyboard": [
                        [{"text": "✅ ተመዝገብ እና 10 ETB ቦነስ ውሰድ", "callback_data": "register_bonus"}]
                    ]
                },
            )
        else:
            tg(
                uid,
                f"ሰላም! Support Team እንኳን በደህና መጡ።\n💰 ባላንስዎ: {u['balance']:.2f} ETB",
                main_reply_kb(uid, base_url),
            )
        return jsonify({"ok": True})

    if text in ("🎮 Play", "Play", "Play Games"):
        if not u["registered"]:
            tg(
                uid,
                "እባክዎ መጀመሪያ ይመዝገቡ።",
                {"inline_keyboard": [[{"text": "✅ ተመዝገብ እና 10 ETB ቦነስ ውሰድ", "callback_data": "register_bonus"}]]},
            )
        else:
            tg(
                uid,
                f"🎮 ለመጫወት ከታች ያለውን Play ቁልፍ ይጫኑ።\n💰 ባላንስዎ: {u['balance']:.2f} ETB",
                main_reply_kb(uid, base_url),
            )
        return jsonify({"ok": True})

    if text in ("✉️ Invite Friends", "Invite Friends"):
        bot_info_user = ""
        try:
            me = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=8).json()
            if me.get("ok"):
                bot_info_user = (me.get("result") or {}).get("username") or ""
        except Exception:
            pass
        ref_link = f"https://t.me/{bot_info_user}?start={uid}" if bot_info_user else f"{base_url}/?ref={uid}"
        tg(
            uid,
            f"👥 ጓደኞችዎን ይጋብዙ!\nየግብዣ ሊንክዎ:\n{ref_link}",
            main_reply_kb(uid, base_url),
        )
        return jsonify({"ok": True})

    if text in ("🆘 Support", "Support"):
        sup_line = f"\nቀጥታ Support: @{SUPPORT_HANDLE}" if SUPPORT_HANDLE else ""
        tg(
            uid,
            f"🆘 Support Team:\nማንኛውንም ጥያቄ ወይም እርዳታ እዚህ መልዕክት ይጻፉ፤ Support Team ይመልስልዎታል።{sup_line}",
            main_reply_kb(uid, base_url),
        )
        return jsonify({"ok": True})

    if u["registered"] and not text.startswith("/"):
        notify_internal(f"💬 Support Message\nCustomer ID: {uid}\nMessage: {text}")
        tg(uid, "✅ መልዕክትዎ ወደ Support Team ደርሷል፤ በቅርቡ ምላሽ ይሰጥዎታል።", main_reply_kb(uid, base_url))

    return jsonify({"ok": True})

@app.route("/api/state")
def api_state():
    uid = str(request.args.get("uid", "874411134")).strip()
    u = get_u(uid)
    adm = bool(ADMIN_CHAT_ID and uid == ADMIN_CHAT_ID)
    return jsonify({
        "balance": u["balance"],
        "registered": u["registered"],
        "bets": u["bets"][-20:],
        "tickets": LIVE_TICKETS[-25:],
        "wds": list(WITHDRAWALS.values()) if adm else u["wds"],
        "is_admin": adm,
    })

@app.route("/api/reserve_bet", methods=["POST"])
def api_reserve_bet():
    d = request.get_json(force=True)
    uid = str(d.get("uid", "874411134")).strip()
    picks = sorted(list({int(x) for x in (d.get("picks") or []) if 1 <= int(x) <= 80}))
    bet = float(d.get("bet", 0) or 0)
    u = get_u(uid)
    if not (1 <= len(picks) <= 10) or bet < 10:
        return jsonify({"ok": False, "msg": "ከ1-10 ቁጥር እና ቢያንስ 10 ETB ይምረጡ።"})
    if u["balance"] <= 0 or bet > u["balance"]:
        return jsonify({"ok": False, "insufficient": True, "msg": "INSUFFICIENT FUNDS."})
    u["balance"] = round(u["balance"] - bet, 2)
    LIVE_TICKETS.append({"player": mask_uid(uid), "picks": picks, "bet": bet, "payout": 0.0})
    return jsonify({"ok": True, "balance": u["balance"], "tickets": LIVE_TICKETS[-25:]})

@app.route("/api/play", methods=["POST"])
def api_play():
    d = request.get_json(force=True)
    uid = str(d.get("uid", "874411134")).strip()
    picks = [int(x) for x in (d.get("picks") or [])]
    bet = float(d.get("bet", 0) or 0)
    already = bool(d.get("already_deducted"))
    u = get_u(uid)
    drawn = random.sample(range(1, 81), 20)
    drawn_set = set(drawn)
    for tk in LIVE_TICKETS:
        tk_hits = [n for n in tk["picks"] if n in drawn_set]
        tk["payout"] = round(float(tk["bet"]) * PAYTABLE.get(len(tk["picks"]), {}).get(len(tk_hits), 0.0), 2)
    snapshot = list(LIVE_TICKETS[-25:])
    if not picks or bet < 10:
        LIVE_TICKETS.clear()
        return jsonify({"ok": True, "balance": u["balance"], "drawn": drawn, "hits": [], "matches": 0, "payout": 0.0, "tickets": snapshot})
    if not (1 <= len(picks) <= 10):
        return jsonify({"ok": False, "msg": "ምርጫው ከ1-10 መሆን አለበት።"})
    if not already:
        if u["balance"] <= 0 or bet > u["balance"]:
            return jsonify({"ok": False, "insufficient": True, "msg": "INSUFFICIENT FUNDS."})
        u["balance"] = round(u["balance"] - bet, 2)
    hits = sorted([x for x in picks if x in drawn_set])
    payout = round(bet * PAYTABLE.get(len(picks), {}).get(len(hits), 0.0), 2)
    u["balance"] = round(u["balance"] + payout, 2)
    u["bets"].append({"bet": bet, "matches": len(hits), "payout": payout})
    LIVE_TICKETS.clear()
    return jsonify({"ok": True, "balance": u["balance"], "drawn": drawn, "hits": hits, "matches": len(hits), "payout": payout, "tickets": snapshot})

@app.route("/api/deposit", methods=["POST"])
def api_deposit():
    d = request.get_json(force=True)
    uid = str(d.get("uid", "874411134")).strip()
    m = str(d.get("method", "")).strip()
    mode = str(d.get("mode", "code")).strip()
    tx = str(d.get("tx", "")).strip().upper()
    shot_b64 = str(d.get("shot_b64", "")).strip()
    amt = float(d.get("amount", 0) or 0)
    if amt < 10:
        return jsonify({"ok": False, "msg": "ዝቅተኛ ገቢ 10 ETB ነው።"})
    if mode == "shot":
        if not shot_b64:
            return jsonify({"ok": False, "msg": "ስክሪንሻት አልተመረጠም።"})
        raw_b64 = shot_b64.split(",", 1)[1] if "," in shot_b64 else shot_b64
        try:
            img_bytes = base64.b64decode(raw_b64)
        except Exception:
            return jsonify({"ok": False, "msg": "የስክሪንሻት ፋይል ማንበብ አልተቻለም።"})
        tg_photo(ADMIN_CHAT_ID, img_bytes, f"📸 Deposit Screenshot\nCustomer ID: {uid}\nBank: {m}\nAmount: {amt:.2f} ETB")
        return jsonify({"ok": True, "msg": f"📸 የ {amt:.2f} ETB ({m}) ስክሪንሻት ተልኳል፤ እባክህ አረጋግጥ።"})
    if not valid_tx(m, tx):
        return jsonify({"ok": False, "msg": "❌ ስህተት ነው፤ ይህ የ FT / Transaction ኮድ የለም ወይም ቀድሞ ተጠቅሟል።"})
    USED_TX.add(tx)
    u = get_u(uid)
    u["balance"] = round(u["balance"] + amt, 2)
    return jsonify({"ok": True, "balance": u["balance"], "msg": f"✅ በ {m} ({tx}) {amt:.2f} ETB ተረጋግጦ ወደ ባላንስህ ተጨምሯል።"})

@app.route("/api/withdraw", methods=["POST"])
def api_withdraw():
    if not is_wd_hours():
        return jsonify({"ok": False, "msg": "⏰ ዊዝድሮ የሚቻለው ከጠዋት 2:00 እስከ ማታ 3:00 ብቻ ነው። ዲፖዚት ግን 24 ሰዓት ይቻላል።"})
    d = request.get_json(force=True)
    uid, amt, m, dest = str(d.get("uid", "874411134")).strip(), float(d.get("amount", 0) or 0), str(d.get("method", "")).strip(), str(d.get("dest", "")).strip()
    u = get_u(uid)
    if amt <= 0:
        return jsonify({"ok": False, "msg": "ትክክለኛ አማውንት ያስገቡ።"})
    if amt > u["balance"]:
        return jsonify({"ok": False, "msg": "በቂ ባላንስ የለህም።"})
    if not dest:
        return jsonify({"ok": False, "msg": "የቴሌብር ስልክ ወይም የCBE አካውንት ያስገቡ።"})
    u["balance"] = round(u["balance"] - amt, 2)
    wid = "WD-" + uuid.uuid4().hex[:6].upper()
    obj = {"id": wid, "uid": uid, "method": m, "amount": amt, "dest": dest, "status": "Pending"}
    WITHDRAWALS[wid] = obj
    u["wds"].append(obj)
    notify_internal(
        f"💸 Withdraw Pending\n"
        f"ID: {wid}\n"
        f"Customer ID: {uid}\n"
        f"Bank: {m}\n"
        f"Amount: {amt:.2f} ETB\n"
        f"Customer Account: {dest}"
    )
    return jsonify({"ok": True, "balance": u["balance"], "msg": f"⏳ የ {amt:.2f} ETB የወጪ ጥያቄዎ ({wid}) Pending ላይ ነው።"})

@app.route("/api/approve", methods=["POST"])
def api_approve():
    d = request.get_json(force=True)
    wid = str(d.get("id", "")).strip()
    w = WITHDRAWALS.get(wid)
    if not w:
        return jsonify({"ok": False, "msg": "ጥያቄው አልተገኘም።"}), 404
    w["status"] = "Completed"
    for item in get_u(w["uid"])["wds"]:
        if item["id"] == wid:
            item["status"] = "Completed"
    tg(
        w["uid"],
        f"✅ የ {w['amount']:.2f} ETB የወጪ ጥያቄዎ ({wid}) Completed ሆኗል፤ ወደ አካውንትዎ ተልኳል።",
    )
    return jsonify({"ok": True, "msg": f"{wid} Completed ሆኗል፤ ለደንበኛው ተልኳል።"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
