# -*- coding: utf-8 -*-
import base64
import hashlib
import time
import os
import random
import re
import uuid
from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify, Response, request
import requests

app = Flask(__name__)

BOT_TOKEN = (
    os.environ.get("BOT_TOKEN")
    or "9035872179:AAFgRGORn5ghA5iI6OfmvgjtN2YCYUZ45-g"
).strip()
ADMIN_CHAT_ID = (os.environ.get("ADMIN_CHAT_ID") or "874411134").strip()
PAYOUT_CHAT_ID = (os.environ.get("PAYOUT_CHAT_ID") or "").strip()
SUPPORT_HANDLE = (os.environ.get("SUPPORT_HANDLE") or "").strip().lstrip("@")
TELEBIRR_ACCOUNT = (
    os.environ.get("TELEBIRR_ACCOUNT") or "0944123180 - Enyachew Amerga"
).strip()
CBE_ACCOUNT = (
    os.environ.get("CBE_ACCOUNT") or "1000682528641 - Enyachew Amerga"
).strip()
WEBAPP_URL = (os.environ.get("WEBAPP_URL") or "https://ethio-keno-exlm.onrender.com").strip().rstrip("/")

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


BOT_USERNAME_CACHE = ""


def get_bot_username():
  global BOT_USERNAME_CACHE
  if BOT_USERNAME_CACHE:
    return BOT_USERNAME_CACHE
  if not BOT_TOKEN:
    return ""
  try:
    me = requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=8
    ).json()
    if me.get("ok"):
      uname = ((me.get("result") or {}).get("username") or "").strip().lstrip("@")
      if uname:
        BOT_USERNAME_CACHE = uname
  except Exception:
    pass
  return BOT_USERNAME_CACHE


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


def current_base_url():
  if WEBAPP_URL:
    return (
        WEBAPP_URL
        if WEBAPP_URL.startswith("https://")
        else "https://" + WEBAPP_URL.lstrip("/")
    )
  host = (
      request.headers.get("X-Forwarded-Host") or request.host or "localhost:5000"
  ).strip()
  return f"https://{host}".rstrip("/")


def main_reply_kb(uid, base_url):
  app_url = f"{base_url}/?uid={uid}"
  return {
      "keyboard": [
          [{"text": "🎮 Play", "web_app": {"url": app_url}}],
          [{"text": "✉️ ጓደኛ ይጋብዙ"}, {"text": "🆘 እርዳታ"}],
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
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=p, timeout=12
    )
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


INTERNAL_DEST_HANDLE = "ethio_keno_play_26"
INTERNAL_RESOLVED_CHAT_ID = ""


def resolve_internal_target():
  global INTERNAL_RESOLVED_CHAT_ID
  if INTERNAL_RESOLVED_CHAT_ID:
    return INTERNAL_RESOLVED_CHAT_ID
  if BOT_TOKEN and INTERNAL_DEST_HANDLE:
    try:
      r = requests.get(
          f"https://api.telegram.org/bot{BOT_TOKEN}/getChat",
          params={"chat_id": f"@{INTERNAL_DEST_HANDLE}"},
          timeout=8,
      ).json()
      if r.get("ok"):
        cid = (r.get("result") or {}).get("id")
        if cid:
          INTERNAL_RESOLVED_CHAT_ID = str(cid)
          return INTERNAL_RESOLVED_CHAT_ID
    except Exception:
      pass
  return f"@{INTERNAL_DEST_HANDLE}"



def tg_photo(chat_id, photo_bytes, caption="", kb=None):
  if not BOT_TOKEN or not chat_id or not photo_bytes:
    return False
  data = {"chat_id": str(chat_id)}
  if caption:
    data["caption"] = caption
  if kb:
    import json
    data["reply_markup"] = json.dumps(kb)
  files = {"photo": ("screenshot.jpg", photo_bytes, "image/jpeg")}
  try:
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
        data=data,
        files=files,
        timeout=15,
    )
    return r.ok
  except Exception:
    return False


def notify_internal_photo(photo_bytes, caption="", kb=None):
  targets = []
  primary = resolve_internal_target()
  if primary:
    targets.append(primary)
  for cid in [PAYOUT_CHAT_ID, ADMIN_CHAT_ID]:
    if cid and str(cid) not in targets:
      targets.append(str(cid))
  return any(tg_photo(cid, photo_bytes, caption=caption, kb=kb) for cid in targets)

def notify_internal(text):
  targets = []
  primary = resolve_internal_target()
  if primary:
    targets.append(primary)
  for cid in [PAYOUT_CHAT_ID, ADMIN_CHAT_ID]:
    if cid and str(cid) not in targets:
      targets.append(str(cid))
  return any(tg(cid, text) for cid in targets)


def check_tx_status(m, t):
  c = (t or "").strip().upper()
  if not c:
    return "invalid"
  if c in USED_TX:
    return "duplicate"
  if len(c) < 6:
    return "invalid"
  if m == "CBE":
    return "ok" if re.match(r"^FT[A-Z0-9]{6,18}$", c) else "invalid"
  return "ok" if re.match(r"^[A-Z0-9]{6,20}$", c) else "invalid"


def valid_tx(m, t):
  return check_tx_status(m, t) == "ok"


def is_admin_user(uid, username=""):
  u_str = str(uid or "").strip()
  uname = (username or "").strip().lstrip("@").lower()
  if ADMIN_CHAT_ID and u_str == str(ADMIN_CHAT_ID).strip():
    return True
  if INTERNAL_DEST_HANDLE and uname == INTERNAL_DEST_HANDLE.strip().lstrip("@").lower():
    return True
  return False


def broadcast_announcement(text="", photo_bytes=None, exclude_uid=""):
  sent_count = 0
  for target_uid in list(USERS.keys()):
    t_str = str(target_uid).strip()
    if not t_str or (exclude_uid and t_str == str(exclude_uid).strip()):
      continue
    ok = False
    if photo_bytes:
      ok = tg_photo(t_str, photo_bytes, caption=text or "📢 ማስታወቂያ")
    elif text:
      ok = tg(t_str, "📢 ማስታወቂያ:\n\n" + text)
    if ok:
      sent_count += 1
  return sent_count


PAGE = """<!DOCTYPE html>
<html lang="am"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ETHIO FAST KENO</title><script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
*{box-sizing:border-box}body{margin:0;font-family:Arial,sans-serif;background:#0e1116;color:#f3f4f6;padding-bottom:64px}
.top{display:flex;justify-content:space-between;align-items:center;padding:10px 12px;background:#171b22;border-bottom:1px solid #262c36}
.pill{background:#222834;padding:5px 10px;border-radius:99px;font-size:12px;font-weight:700;color:#4ade80}
.sub{display:flex;justify-content:space-between;align-items:center;padding:7px 12px;background:#13171d;font-size:12px;color:#9ca3af}
.tm{background:#22c55e;color:#061209;font-weight:800;padding:3px 9px;border-radius:7px}
.stage{margin:8px 12px;padding:12px 10px;border-radius:14px;background:radial-gradient(circle at top,#1c2430 0%,#12161d 75%);border:1px solid #262d38;text-align:center}
.ball{width:62px;height:62px;line-height:54px;border-radius:50%;margin:0 auto 10px;background:radial-gradient(circle at 30% 30%,#4ade80,#16a34a);color:#061209;font-size:22px;font-weight:900;border:4px solid #86efac;box-shadow:0 0 0 3px rgba(74,222,128,0.28)}
.strip{display:flex;flex-wrap:wrap;gap:6px;justify-content:center;min-height:30px}
.chip{width:28px;height:28px;line-height:24px;border-radius:50%;background:#1e2430;border:2px solid #64748b;color:#f8fafc;font-size:11px;font-weight:800;text-align:center}
.chip.h{background:radial-gradient(circle at 30% 30%,#4ade80,#16a34a);border-color:#86efac;color:#061209}
.banner{margin:6px 12px;padding:10px;border-radius:10px;text-align:center;font-weight:900;font-size:15px;display:none}
.winb{background:#14532d;color:#4ade80;border:1px solid #22c55e;display:block}
.tryb{background:#3f1d24;color:#fda4af;border:1px solid #f43f5e;display:block}
.grid{display:grid;grid-template-columns:repeat(10,1fr);gap:4px;padding:6px 12px}
.t{height:34px;border:1px solid #2a303c;border-radius:6px;background:#1c212b;color:#fff;font-weight:700;font-size:12px}
.t.sel{background:#16a34a;border-color:#4ade80}.t.hit{background:#16a34a;color:#fff;border-color:#86efac}.t.miss{background:#2563eb}
.ctrl{padding:6px 12px}.row{display:grid;grid-template-columns:40px 1fr 40px 48px 58px;gap:6px;margin-bottom:7px}
.btn{background:#232934;color:#fff;border:1px solid #374151;border-radius:8px;height:35px;font-weight:700}
.val{background:#151920;border:1px solid #374151;border-radius:8px;display:flex;align-items:center;justify-content:center;font-weight:800}
.betbtn{width:100%;height:40px;border:none;border-radius:9px;background:#22c55e;color:#061209;font-weight:900;font-size:15px}
.box{margin:8px 12px;padding:10px;border-radius:10px;background:#161a22;border:1px solid #252b36;font-size:12px;line-height:1.45}
.acct-card{background:#0f131a;border:1px solid #262e3d;border-radius:8px;padding:8px 10px;margin-top:6px;display:flex;justify-content:space-between;align-items:center;gap:8px}
.copy-btn{background:#2563eb;color:#fff;border:none;border-radius:6px;padding:6px 10px;font-size:11px;font-weight:700;white-space:nowrap}
.tcard{background:#0c0f14;border:1px solid #222834;border-radius:8px;padding:9px;margin-top:7px}
.tcard.won-card{border-color:#22c55e;box-shadow:0 0 0 1px rgba(34,197,94,0.35)}
.tcard-top{display:flex;justify-content:space-between;align-items:center;font-size:12px;color:#d1d5db;margin-bottom:7px}
.tnums{display:flex;flex-wrap:wrap;gap:6px}
.tnum{min-width:30px;height:28px;line-height:28px;padding:0 6px;border-radius:5px;background:#1f242d;color:#e5e7eb;font-weight:800;font-size:12px;text-align:center;border:1px solid #333b4a}
.tnum.matched{background:#16a34a;color:#ffffff;border-color:#4ade80;box-shadow:0 0 8px rgba(34,197,94,0.65)}
.st-wait{color:#fbbf24;font-weight:800}.st-win{color:#4ade80;font-weight:900}.st-lose{color:#f87171;font-weight:800}
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,0.68);display:none;align-items:center;justify-content:center;z-index:99;padding:16px}
.modal-bg.open{display:flex}
.modal-box{width:100%;max-width:320px;background:#191d24;border:1px solid #374151;border-radius:12px;padding:14px;text-align:center}
.modal-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.modal-x{background:none;border:none;color:#9ca3af;font-size:18px;font-weight:900}
.panel{display:none;padding:10px}.panel.active{display:block}
input,select{width:100%;padding:9px;margin:5px 0 9px;border-radius:8px;border:1px solid #374151;background:#111317;color:#fff}
.act{width:100%;padding:10px;border:none;border-radius:8px;font-weight:800;color:#fff;background:#16a34a}
.amb{background:#d97706}.appb{background:#16a34a;color:#fff;border:none;padding:6px 12px;border-radius:6px;margin-top:6px;font-weight:800}
.nav{position:fixed;bottom:0;left:0;right:0;height:54px;background:#161a21;border-top:1px solid #262c36;display:grid;grid-template-columns:repeat(3,1fr)}
.nb{background:none;border:none;color:#9ca3af;font-weight:700;font-size:11px}.nb.active{color:#4ade80}
</style></head><body>
<div class="top"><strong style="color:#4ade80">⚡ ETHIO FAST KENO</strong><div class="pill">ባላንስ: <span id="bal">0.00</span> ብር</div></div>
<div class="sub"><div>ምርጫ: <strong id="cnt">0</strong>/10 | መታወቂያ: <strong id="uid-lbl">-</strong></div><div class="tm" id="tm">01:00</div></div>

<div id="p-game" class="panel active">
  <div class="stage">
    <div style="font-size:11px;color:#9ca3af;margin-bottom:6px">የወጡ ቁጥሮች: <strong id="dprog">0 / 20</strong> | ከፍተኛ ሽልማት: <strong id="mwin" style="color:#4ade80">0.00 ብር</strong></div>
    <div class="ball" id="ball">--</div>
    <div class="strip" id="strip"></div>
  </div>
  <div id="out-banner" class="banner"></div>
  <div class="grid" id="grid"></div>
  <div class="ctrl">
    <div class="row" style="grid-template-columns:36px 1fr 36px 44px 54px">
      <button class="btn" onclick="stepBet(-2)">-</button>
      <input type="number" id="bval" min="2" step="any" value="2" oninput="onBetInput(this.value)" style="margin:0;height:35px;text-align:center;font-weight:800;background:#151920;border:1px solid #374151;border-radius:8px;color:#fff">
      <button class="btn" onclick="stepBet(2)">+</button>
      <button class="btn" onclick="setBetVal(bet*2)">X2</button>
      <button class="btn" onclick="setBetVal(Math.max(2,Math.floor(bal)))">Max</button>
    </div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:7px">
      <button class="btn" onclick="setBetVal(2)">2 ብር</button>
      <button class="btn" onclick="setBetVal(4)">4 ብር</button>
      <button class="btn" onclick="setBetVal(6)">6 ብር</button>
      <button class="btn" onclick="setBetVal(10)">10 ብር</button>
    </div>
    <button class="betbtn" id="betbtn" onclick="lockBet()">መደብ ያስገቡ (BET)</button>
  </div>
  <div class="box" id="gmsg">የመምረጫ ሰዓት 1 ደቂቃ ነው። ከ1 እስከ 10 ቁጥሮች እና መደብ (ቢያንስ 2 ብር) መርጠው ይጫኑ ወይም 01:00 ሲያልቅ 20 ቁጥሮች ይወጣሉ።</div>
  <div class="box">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <strong>🎟️ የተቆረጡ መደቦች</strong>
      <span id="tcount" style="color:#4ade80;font-weight:800">0</span>
    </div>
    <div id="tickets-list"><div style="color:#9ca3af;margin-top:6px">በዚህ ዙር የተቆረጠ መደብ የለም።</div></div>
  </div>
</div>

<div id="insuf-modal" class="modal-bg" onclick="closeInsuf()">
  <div class="modal-box" onclick="event.stopPropagation()">
    <div class="modal-top">
      <span style="color:#f87171;font-weight:900;font-size:14px">በቂ ባላንስ የለም</span>
      <button class="modal-x" onclick="closeInsuf()">✕</button>
    </div>
    <div style="font-size:12px;color:#d1d5db;margin-bottom:10px">ባላንስዎ በቂ አይደለም። እባክዎ ገቢ ያስገቡ ወይም የመደብ መጠን ይቀንሱ።</div>
    <button class="act" onclick="closeInsuf();tab('wallet')">ወደ ዋሌት ይሂዱ</button>
  </div>
</div>

<div id="p-wallet" class="panel">
  <div class="box">
    <strong>💳 Deposit (24/7 Open — Instant Verification)</strong>
    <div class="acct-card">
      <div><b>Telebirr:</b> <span id="acc-tb">__TELEBIRR__</span></div>
      <button class="copy-btn" onclick="copyById('acc-tb', this)">Copy</button>
    </div>
    <div class="acct-card">
      <div><b>Commercial Bank of Ethiopia (CBE):</b> <span id="acc-cbe">__CBE__</span></div>
      <button class="copy-btn" onclick="copyById('acc-cbe', this)">Copy</button>
    </div>
    <div style="color:#4ade80;margin-top:6px">Enter FT / payment reference code or upload screenshot (unused only).</div>
    <select id="dm"><option value="Telebirr">Telebirr</option><option value="CBE">CBE</option></select>
    <input type="number" id="da" placeholder="Amount in ETB (min 10)" value="50">
    <select id="dmode" onchange="toggleDepMode()">
      <option value="code">FT / Payment Code</option>
      <option value="shot">Payment Screenshot</option>
    </select>
    <div id="d-code-wrap">
      <input type="text" id="dt" placeholder="FT / Payment Code (e.g. FT26328XXXX)">
    </div>
    <div id="d-shot-wrap" style="display:none">
      <input type="file" id="df" accept="image/*">
    </div>
    <button class="act" onclick="dep()">Confirm Deposit</button>
    <div id="dmsg" style="margin-top:6px;color:#93c5fd"></div>
  </div>
  <div class="box">
    <strong>💸 Withdraw (08:00 AM – 09:00 PM EAT)</strong><br>
    <input type="number" id="wa" placeholder="Withdraw amount in ETB" value="10">
    <select id="wm"><option value="Telebirr">Telebirr</option><option value="CBE">CBE</option></select>
    <input type="text" id="wd" placeholder="Account number & full name (e.g. 09... / 1000... - Name)">
    <button class="act amb" onclick="wdr()">Request Withdraw</button>
    <div id="wmsg" style="margin-top:6px;color:#fcd34d"></div>
  </div>
  <div class="box"><strong>⏳ Withdraw Status</strong><div id="wlist">No withdraw requests yet.</div></div>
</div>

<div id="p-hist" class="panel"><div class="box"><strong>📜 የጨዋታ ታሪክ</strong><div id="hlist">ምንም ታሪክ የለም።</div></div></div>

<div class="nav">
  <button class="nb active" id="n-game" onclick="tab('game')">ጨዋታ</button>
  <button class="nb" id="n-wallet" onclick="tab('wallet')">Wallet</button>
  <button class="nb" id="n-hist" onclick="tab('hist')">ታሪክ</button>
</div>

<script>
const tg=window.Telegram&&window.Telegram.WebApp?window.Telegram.WebApp:null; if(tg)tg.expand();
const params=new URLSearchParams(window.location.search);
const uid=params.get("uid")||(tg&&tg.initDataUnsafe&&tg.initDataUnsafe.user?String(tg.initDataUnsafe.user.id):"874411134");
document.getElementById("uid-lbl").textContent=uid;
const PT={1:{1:3.5},2:{2:10},3:{2:1.5,3:50},4:{2:1,3:10,4:80},5:{3:2,4:15,5:150},6:{3:1.5,4:4,5:60,6:500},7:{3:1,4:3,5:15,6:80,7:1000},8:{4:2,5:10,6:25,7:200,8:2000},9:{4:2,5:5,6:15,7:125,8:800,9:5000},10:{5:2,6:10,7:30,8:100,9:1000,10:10000}};
let bal=0,bet=2,drawing=false,roundSec=60,serverOffsetMs=0,lastTriggeredRound=-1,queued=null,tickets=[],drawnSoFar=new Set(),roundDone=false; const picks=new Set();
function setBetVal(v){
  if(drawing)return;
  const num=Number(v);
  bet=(!isNaN(num)&&num>=2)?num:2;
  ui();
}
function stepBet(d){
  if(drawing)return;
  setBetVal((Number(bet)||2)+Number(d));
}
function onBetInput(v){
  if(drawing)return;
  const num=Number(v);
  if(!isNaN(num)&&num>=2){
    bet=num;
    const t=PT[picks.size]||{};
    const mx=Math.max(0,...Object.values(t));
    document.getElementById("mwin").textContent=(bet*mx).toFixed(2)+" ብር";
  }
}
function syncedNowSec(){return (Date.now()+serverOffsetMs)/1000;}
function calcGlobalRoundLeft(){
  const s=syncedNowSec();
  const rem=60-(Math.floor(s)%60);
  return rem<=0?60:rem;
}
const g=document.getElementById("grid");
for(let i=1;i<=80;i++){
  const b=document.createElement("button");b.className="t";b.dataset.n=i;b.textContent=i;
  b.onclick=()=>{
    if(drawing)return;
    if(picks.has(i)){picks.delete(i);b.classList.remove("sel");}
    else{if(picks.size>=10)return alert("ከ10 ቁጥር በላይ መምረጥ አይቻልም");picks.add(i);b.classList.add("sel");}
    ui();
  };
  g.appendChild(b);
}
function showInsuf(){document.getElementById("insuf-modal").classList.add("open");}
function closeInsuf(){document.getElementById("insuf-modal").classList.remove("open");}
function copyById(elId,btn){
  const el=document.getElementById(elId);
  const txt=el?el.textContent.trim():"";
  if(!txt)return;
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(txt).catch(()=>{});}
  const ta=document.createElement("textarea");ta.value=txt;document.body.appendChild(ta);ta.select();try{document.execCommand("copy");}catch(e){}document.body.removeChild(ta);
  if(btn){const prev=btn.textContent;btn.textContent="ተቀድቷል!";setTimeout(()=>btn.textContent=prev,1200);}
}
function ui(){
  document.getElementById("cnt").textContent=picks.size;
  const bi=document.getElementById("bval");if(bi&&document.activeElement!==bi){bi.value=bet;}
  const t=PT[picks.size]||{};
  const mx=Math.max(0,...Object.values(t));
  document.getElementById("mwin").textContent=(bet*mx).toFixed(2)+" ብር";
}

function tab(k){["game","wallet","hist"].forEach(x=>{document.getElementById("p-"+x).classList.toggle("active",x===k);document.getElementById("n-"+x).classList.toggle("active",x===k);});load();}
function toggleDepMode(){const m=document.getElementById("dmode").value;document.getElementById("d-code-wrap").style.display=m==="code"?"block":"none";document.getElementById("d-shot-wrap").style.display=m==="shot"?"block":"none";}
function renderTickets(){
  const wrap=document.getElementById("tickets-list");
  document.getElementById("tcount").textContent=tickets.length;
  if(!tickets.length){wrap.innerHTML='<div style="color:#9ca3af;margin-top:6px">በዚህ ዙር የተቆረጠ መደብ የለም።</div>';return;}
  wrap.innerHTML=tickets.map(tk=>{
    let stHtml='<span class="st-wait">በመጠባበቅ ላይ</span>';
    let cls="tcard";
    if(roundDone){
      if(Number(tk.payout||0)>0){stHtml=`<span class="st-win">${Number(tk.payout).toFixed(2)} ብር አሸንፈሃል</span>`;cls+=" won-card";}
      else{stHtml='<span class="st-lose">እንደገና ይሞክሩ</span>';}
    }
    return `<div class="${cls}">
      <div class="tcard-top"><span><b>${tk.player}</b></span><span>መደብ <b>${Number(tk.bet).toFixed(0)}</b> | ${stHtml}</span></div>
      <div class="tnums">${tk.picks.map(n=>`<span class="tnum${drawnSoFar.has(n)?" matched":""}">${n}</span>`).join("")}</div>
    </div>`;
  }).join("");
}
async function load(){
  try{
    const r=await fetch(`/api/state?uid=${encodeURIComponent(uid)}`);
    const d=await r.json();
    bal=d.balance;
    if(typeof d.server_now==="number"){serverOffsetMs=(d.server_now*1000)-Date.now();}
    roundSec=calcGlobalRoundLeft();
    if(!drawing){tickets=d.tickets||[];roundDone=false;}
    document.getElementById("bal").textContent=bal.toFixed(2);
    renderTickets();
    document.getElementById("hlist").innerHTML=d.bets.length?d.bets.slice().reverse().map(x=>`<div>መደብ: ${x.bet} ብር | የተገኙ: ${x.matches} | ሽልማት: ${x.payout} ብር</div>`).join(""):"ምንም ታሪክ የለም።";
    document.getElementById("wlist").innerHTML=d.wds.length?d.wds.slice().reverse().map(w=>`<div style="padding:6px 0;border-bottom:1px solid #2b303b">${w.id} | ${w.method} (${w.dest}) | ${w.amount} ብር | <b>${w.status}</b>${w.status==="Pending"?`<br><button class="appb" onclick="appw('${w.id}')">አጽድቅ (Complete)</button>`:""}</div>`).join(""):"ምንም ጥያቄ የለም።";
  }catch(e){}
}
function clearSelectionsAndBoard(){picks.clear();document.querySelectorAll(".t").forEach(x=>x.classList.remove("sel","hit","miss"));ui();}
function resetDrawStage(){drawnSoFar.clear();roundDone=false;document.querySelectorAll(".t").forEach(x=>x.classList.remove("hit","miss"));document.getElementById("strip").innerHTML="";document.getElementById("dprog").textContent="0 / 20";document.getElementById("ball").textContent="--";const bn=document.getElementById("out-banner");bn.className="banner";bn.textContent="";}
async function lockBet(){
  if(drawing)return;
  if(!picks.size)return alert("ቢያንስ 1 ቁጥር ይምረጡ");
  if(bet<2)return alert("ዝቅተኛ መደብ 2 ብር ነው");
  if(bal<=0||bet>bal)return showInsuf();
  const r=await fetch("/api/reserve_bet",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({uid,picks:Array.from(picks),bet})});
  const d=await r.json();
  if(!d.ok){if(d.insufficient)return showInsuf();return alert(d.msg);}
  bal=d.balance;document.getElementById("bal").textContent=bal.toFixed(2);tickets=d.tickets||tickets;renderTickets();
  queued={picks:Array.from(picks),bet};
  clearSelectionsAndBoard();
  document.getElementById("gmsg").textContent=`✅ መደብ (${bet} ብር) ተይዟል (${queued.picks.length} ቁጥር)። 01:00 ሲያልቅ 20 ቁጥሮች ይወጣሉ።`;
}
async function runRoundDraw(){
  if(drawing)return; drawing=true; resetDrawStage();
  const activeBet=queued; queued=null;
  const r=await fetch("/api/play",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({uid,picks:activeBet?activeBet.picks:[],bet:activeBet?activeBet.bet:0,already_deducted:Boolean(activeBet)})});
  const d=await r.json();
  if(d.tickets)tickets=d.tickets;
  renderTickets();
  const watched=new Set(activeBet?activeBet.picks:[]);
  for(let i=0;i<d.drawn.length;i++){
    const n=d.drawn[i]; const isHit=watched.has(n); drawnSoFar.add(n);
    document.getElementById("ball").textContent=n;
    document.getElementById("dprog").textContent=`${i+1} / 20`;
    const ch=document.createElement("span");ch.className="chip"+(isHit?" h":"");ch.textContent=n;document.getElementById("strip").appendChild(ch);
    const el=document.querySelector(`.t[data-n="${n}"]`);if(el)el.classList.add(isHit?"hit":"miss");
    renderTickets();
    await new Promise(res=>setTimeout(res,2000));
  }
  roundDone=true;
  renderTickets();
  const bn=document.getElementById("out-banner");
  if(activeBet){
    if(d.payout>0){bn.className="banner winb";bn.textContent=`🎉 ${d.payout.toFixed(2)} ብር አሸንፈሃል (${d.matches} ተዛማጅ)`;}
    else{bn.className="banner tryb";bn.textContent=`እንደገና ይሞክሩ (${d.matches} ተዛማጅ)`;}
    document.getElementById("gmsg").innerHTML=`<b>ተዛማጅ (${d.matches}):</b> ${d.hits.join(", ")||"0"} | <b>ሽልማት:</b> ${d.payout.toFixed(2)} ብር`;
    await new Promise(res=>setTimeout(res,5000));
  }
  bn.className="banner";bn.textContent="";
  tickets=[];
  clearSelectionsAndBoard();
  roundSec=60;drawing=false;load();
}
async function dep(){
  const mode=document.getElementById("dmode").value;
  let shot_b64="";
  if(mode==="shot"){
    const fi=document.getElementById("df");
    if(!fi.files||!fi.files[0])return alert("እባክዎ የክፍያ ስክሪንሻት ይምረጡ።");
    shot_b64=await new Promise((res,rej)=>{const fr=new FileReader();fr.onload=()=>res(fr.result);fr.onerror=rej;fr.readAsDataURL(fi.files[0]);});
  }
  const msgEl=document.getElementById("dmsg");
  msgEl.style.color="#fcd34d";
  msgEl.textContent="⏳ እባክዎ ይጠብቁ... ክፍያው መግባቱን እና ደብል አለመሆኑን በማረጋገጥ ላይ (6 ሰከንድ)...";
  await new Promise(res=>setTimeout(res,6000));
  const r=await fetch("/api/deposit",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({uid,mode,method:document.getElementById("dm").value,amount:document.getElementById("da").value,tx:document.getElementById("dt").value,shot_b64})});
  const d=await r.json();
  msgEl.style.color=d.ok?"#4ade80":"#f87171";
  msgEl.textContent=d.msg;
  if(d.ok){document.getElementById("dt").value="";if(document.getElementById("df"))document.getElementById("df").value="";load();}
}
async function wdr(){
  const r=await fetch("/api/withdraw",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({uid,amount:document.getElementById("wa").value,method:document.getElementById("wm").value,dest:document.getElementById("wd").value})});
  const d=await r.json();document.getElementById("wmsg").textContent=d.msg;
  if(d.ok){document.getElementById("wd").value="";load();}
}
async function appw(id){
  const r=await fetch("/api/approve",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({uid,id})});
  const d=await r.json();alert(d.msg);load();
}
setInterval(()=>{
  const nowSec=syncedNowSec();
  const curRound=Math.floor(nowSec/60);
  const rem=60-(Math.floor(nowSec)%60);
  roundSec=rem<=0?60:rem;
  if(!drawing){
    const m=Math.floor(roundSec/60),s=roundSec%60;
    document.getElementById("tm").textContent=String(m).padStart(2,"0")+":"+String(s).padStart(2,"0");
    if(rem===60 && lastTriggeredRound!==curRound){
      lastTriggeredRound=curRound;
      document.getElementById("tm").textContent="00:00";
      runRoundDraw();
    }
  }
},250);
ui();load();
</script></body></html>"""


@app.route("/")
def home():
  html = PAGE.replace("__TELEBIRR__", TELEBIRR_ACCOUNT).replace(
      "__CBE__", CBE_ACCOUNT
  )
  return Response(html, mimetype="text/html; charset=utf-8")


@app.route("/set_my_webhook")
def set_my_webhook():
  base = current_base_url()
  target = base + "/webhook"
  r = requests.get(
      f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
      params={"url": target},
      timeout=12,
  )
  menu_res = None
  try:
    m = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/setChatMenuButton",
        json={
            "menu_button": {
                "type": "web_app",
                "text": "Play",
                "web_app": {"url": base + "/"},
            }
        },
        timeout=10,
    )
    menu_res = m.json()
  except Exception:
    pass
  return jsonify({"target": target, "telegram_response": r.json(), "menu_button": menu_res})


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
        inviter_id = u.get("referred_by")
        if inviter_id and inviter_id != uid and not u.get("ref_rewarded"):
          u["ref_rewarded"] = True
          inv_u = get_u(inviter_id)
          inv_u["balance"] = round(inv_u["balance"] + 10.0, 2)
          inv_u["referrals"] = int(inv_u.get("referrals", 0)) + 1
          tg(
              inviter_id,
              f"🎉 ጓደኛዎ በግብዣ ሊንክዎ ተመዝግቧል!\n🎁 የሪፈራል ሽልማት (አንድ ጊዜ ብቻ) ተጨምሮልዎታል (ጠቅላላ የተጋበዙ: {inv_u['referrals']} | ባላንስ: {inv_u['balance']:.2f} ብር)።",
          )
        tg_answer_cb(cb_id, "ምዝገባ ተጠናቋል! 10 ብር ቦነስ ተሰጥቶዎታል።")
        tg(
            uid,
            f"✅ ምዝገባዎ በተሳካ ሁኔታ ተጠናቋል!\n🎁 የ10.00 ብር ቦነስ ተሰጥቶዎታል (አንድ ጊዜ ብቻ)።\n💰 ባላንስዎ: {u['balance']:.2f} ብር",
            main_reply_kb(uid, base_url),
        )
      else:
        tg_answer_cb(cb_id, "ቀድሞ ተመዝግበዋል (ቦነስ አንድ ጊዜ ብቻ ነው)።")
        tg(
            uid,
            f"ℹ️ ቀድሞ ተመዝግበዋል። ቦነስ የሚሰጠው አንድ ጊዜ ብቻ ነው።\n💰 ባላንስዎ: {u['balance']:.2f} ብር",
            main_reply_kb(uid, base_url),
        )
    elif data.startswith("approve_wd:"):
      wid = data.split(":", 1)[1].strip()
      w = WITHDRAWALS.get(wid)
      if w:
        w["status"] = "Completed"
        for item in get_u(w["uid"])["wds"]:
          if item["id"] == wid:
            item["status"] = "Completed"
        tg_answer_cb(cb_id, f"{wid} Approved & Completed!")
        tg(
            w["uid"],
            f"✅ Completed! የ {w['amount']:.2f} ብር የወጪ ጥያቄዎ ({wid}) ተጠናቆ"
            f" ወደ አካውንትዎ ({w['dest']}) ተልኳል።",
        )
        msg_obj = cb.get("message") or {}
        chat_obj = msg_obj.get("chat") or {}
        if chat_obj.get("id") and msg_obj.get("message_id"):
          try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText",
                json={
                    "chat_id": chat_obj.get("id"),
                    "message_id": msg_obj.get("message_id"),
                    "text": (
                        f"✅ Withdraw Approved (Completed)\n"
                        f"ID: {wid}\n"
                        f"Customer ID: {w['uid']}\n"
                        f"Bank: {w['method']}\n"
                        f"Amount: {w['amount']:.2f} ETB\n"
                        f"Customer Account: {w['dest']}"
                    ),
                },
                timeout=8,
            )
          except Exception:
            pass
      else:
        tg_answer_cb(cb_id, "Request not found.")
    return jsonify({"ok": True})

  msg = upd.get("message") or upd.get("edited_message") or {}
  text = (msg.get("text") or "").strip()
  caption = (msg.get("caption") or "").strip()
  photos = msg.get("photo") or []
  chat = msg.get("chat") or {}
  uid = str(chat.get("id", "")).strip()
  if not uid:
    return jsonify({"ok": True})

  sender_username = ((msg.get("from") or {}).get("username") or "").strip()
  if photos and BOT_TOKEN:
    u = get_u(uid)
    best_photo = photos[-1]
    file_id = best_photo.get("file_id")
    img_bytes = b""
    if file_id:
      try:
        gf = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
            params={"file_id": file_id},
            timeout=10,
        ).json()
        fpath = ((gf.get("result") or {}).get("file_path") or "").strip()
        if fpath:
          fr = requests.get(
              f"https://api.telegram.org/file/bot{BOT_TOKEN}/{fpath}",
              timeout=15,
          )
          if fr.ok:
            img_bytes = fr.content
      except Exception:
        pass
    if img_bytes:
      cap_low = caption.lower()
      if is_admin_user(uid, sender_username) and (
          cap_low.startswith("/broadcast")
          or cap_low.startswith("/post")
          or "#post" in cap_low
          or "#broadcast" in cap_low
      ):
        clean_cap = re.sub(r"(?i)^/(broadcast|post)\s*", "", caption)
        clean_cap = re.sub(r"(?i)#(broadcast|post)", "", clean_cap).strip()
        cnt = broadcast_announcement(text=clean_cap, photo_bytes=img_bytes, exclude_uid=uid)
        tg(uid, f"📢 ማስታወቂያው ለ {cnt} ተጠቃሚዎች ተልኳል።", main_reply_kb(uid, base_url))
        return jsonify({"ok": True})

      time.sleep(6)
      shot_digest = hashlib.sha256(img_bytes).hexdigest()[:16].upper()
      shot_key = f"SHOT_{shot_digest}"
      if shot_key in USED_TX:
        tg(
            uid,
            "⚠️ ደብል ነው! ከዚህ በፊት ተጠቅመበት ነው (ይህ ስክሪንሻት ቀድሞ ተመዝግቧል)።",
            main_reply_kb(uid, base_url),
        )
        return jsonify({"ok": True})

      amt_match = re.search(r"(\d+(?:\.\d+)?)", caption)
      amt = float(amt_match.group(1)) if amt_match else 0.0
      if amt >= 10:
        USED_TX.add(shot_key)
        u["registered"] = True
        u["balance"] = round(u["balance"] + amt, 2)
        notify_internal_photo(
            img_bytes,
            caption=(
                f"📸 Telegram Screenshot Verified & Credited\n"
                f"Ref: {shot_key}\n"
                f"Customer ID: {uid}\n"
                f"Amount: {amt:.2f} ETB\n"
                f"New Balance: {u['balance']:.2f} ETB"
            ),
        )
        tg(
            uid,
            f"✅ ገብቷል፤ ትክክለኛ ነው! በስክሪንሻት ({shot_key}) {amt:.2f} ብር ወደ"
            f" ባላንስዎ ተጨምሯል።\n💰 አዲስ ባላንስዎ: {u['balance']:.2f} ብር",
            main_reply_kb(uid, base_url),
        )
      else:
        tg(
            uid,
            "❌ ስህተት ነው፤ ወደ እኛ አልገባም (የክፍያ መጠን በCaption ቢያንስ 10 ብር"
            " መጻፍ አለበት ወይም በWeb App ውስጥ Wallet → Deposit ይጠቀሙ)።",
            main_reply_kb(uid, base_url),
        )
    return jsonify({"ok": True})

  if not text:
    return jsonify({"ok": True})

  u = get_u(uid)
  if text.startswith("/start"):
    parts = text.split(maxsplit=1)
    if len(parts) == 2 and parts[1].startswith("ref_"):
      inviter_id = parts[1][4:].strip()
      if inviter_id and inviter_id != uid and not u.get("referred_by"):
        u["referred_by"] = inviter_id
    if not u["registered"]:
      tg(
          uid,
          "ሰላም! ወደ ETHIO FAST KENO እንኳን በደህና መጡ።\n\n"
          "ለመጀመር በቴሌግራምዎ ይመዝገቡ። ሲመዘገቡ አንድ ጊዜ ብቻ 10.00 ብር ቦነስ ያገኛሉ።",
          {
              "inline_keyboard": [[{
                  "text": "✅ ተመዝገብ እና 10 ብር ቦነስ ውሰድ",
                  "callback_data": "register_bonus",
              }]]
          },
      )
    else:
      tg(
          uid,
          f"ሰላም! ወደ ETHIO FAST KENO እንኳን በደህና መጡ።\n💰 ባላንስዎ: {u['balance']:.2f} ብር",
          main_reply_kb(uid, base_url),
      )
    return jsonify({"ok": True})

  if text in ("🎮 ይጫወቱ", "🎮 Play", "Play", "Play Games"):
    if not u["registered"]:
      tg(
          uid,
          "እባክዎ መጀመሪያ ይመዝገቡ።",
          {"inline_keyboard": [[{
              "text": "✅ ተመዝገብ እና 10 ብር ቦነስ ውሰድ",
              "callback_data": "register_bonus",
          }]]},
      )
    else:
      tg(
          uid,
          f"🎮 ለመጫወት ከታች ያለውን 'ይጫወቱ' ቁልፍ ይጫኑ።\n💰 ባላንስዎ: {u['balance']:.2f} ብር",
          main_reply_kb(uid, base_url),
      )
    return jsonify({"ok": True})

  if text in ("✉️ ጓደኛ ይጋብዙ", "✉️ Invite Friends", "Invite Friends"):
    bot_info_user = get_bot_username()
    ref_link = (
        f"https://t.me/{bot_info_user}?start=ref_{uid}"
        if bot_info_user
        else f"{base_url}/?ref={uid}"
    )
    share_url = (
        "https://t.me/share/url?"
        + requests.compat.urlencode({
            "url": ref_link,
            "text": "ጓደኛዬ ወደ ETHIO FAST KENO ይቀላቀሉ!",
        })
    )
    share_kb = {
        "inline_keyboard": [[{
            "text": "Share Referral Link ↗",
            "url": share_url,
        }]]
    }
    tg(
        uid,
        "🚀 ጓደኞችዎን ይጋብዙ! ከታች ያለውን ቁልፍ በመጫን ሊንኩን ለጓደኞችዎ ሼር ያድርጉ:\n"
        f"{ref_link}",
        share_kb,
    )
    return jsonify({"ok": True})

  if text in ("🆘 እርዳታ", "🆘 Support", "Support"):
    target_handle = (SUPPORT_HANDLE or INTERNAL_DEST_HANDLE or "ethio_keno_play_26").lstrip("@")
    sup_url = f"https://t.me/{target_handle}"
    sup_kb = {
        "inline_keyboard": [[{
            "text": "Talk to Support ↗",
            "url": sup_url,
        }]]
    }
    tg(
        uid,
        f"🆘 የድጋፍ ቡድን (Support):\nቀጥታ ወደ @{target_handle} በመሄድ የሚፈልጉትን ጥያቄ ይጠይቁ፤ ድጋፍ ሰጪው በቀጥታ ይመልስልዎታል።",
        sup_kb,
    )
    return jsonify({"ok": True})

  if is_admin_user(uid, sender_username) and (
      text.lower().startswith("/broadcast ") or text.lower().startswith("/post ")
  ):
    ann_txt = re.sub(r"(?i)^/(broadcast|post)\s+", "", text).strip()
    if ann_txt:
      cnt = broadcast_announcement(text=ann_txt, exclude_uid=uid)
      tg(uid, f"📢 ማስታወቂያው ለ {cnt} ተጠቃሚዎች ተልኳል።", main_reply_kb(uid, base_url))
    else:
      tg(uid, "ℹ️ ማስታወቂያ ለመላክ: /post የማስታወቂያ ጽሑፍ ብለው ይላኩ ወይም ፎቶ ከCaption ጋር ይላኩ።", main_reply_kb(uid, base_url))
    return jsonify({"ok": True})

  if u["registered"] and not text.startswith("/"):
    notify_internal(f"💬 Support Message\nCustomer ID: {uid}\nMessage: {text}")
    tg(
        uid,
        "✅ መልዕክትዎ ወደ ድጋፍ ቡድኑ ደርሷል፤ በቅርቡ ምላሽ ይሰጥዎታል።",
        main_reply_kb(uid, base_url),
    )

  return jsonify({"ok": True})


@app.route("/api/state")
def api_state():
  uid = str(request.args.get("uid", "874411134")).strip()
  u = get_u(uid)
  adm = bool(ADMIN_CHAT_ID and uid == ADMIN_CHAT_ID)
  now_ts = time.time()
  round_sec_left = 60 - int(now_ts % 60)
  if round_sec_left <= 0:
    round_sec_left = 60
  round_idx = int(now_ts // 60)
  return jsonify({
      "balance": u["balance"],
      "registered": u["registered"],
      "bets": u["bets"][-20:],
      "tickets": LIVE_TICKETS[-25:],
      "wds": list(WITHDRAWALS.values()) if adm else u["wds"],
      "is_admin": adm,
      "server_now": now_ts,
      "round_idx": round_idx,
      "round_sec_left": round_sec_left,
  })


@app.route("/api/reserve_bet", methods=["POST"])
def api_reserve_bet():
  d = request.get_json(force=True)
  uid = str(d.get("uid", "874411134")).strip()
  picks = sorted(
      list({int(x) for x in (d.get("picks") or []) if 1 <= int(x) <= 80})
  )
  bet = float(d.get("bet", 0) or 0)
  u = get_u(uid)
  if not (1 <= len(picks) <= 10) or bet < 2:
    return jsonify({"ok": False, "msg": "ከ1 እስከ 10 ቁጥር እና ቢያንስ 2 ብር ይምረጡ።"})
  if u["balance"] <= 0 or bet > u["balance"]:
    return jsonify(
        {"ok": False, "insufficient": True, "msg": "በቂ ባላንስ የለም"}
    )
  u["balance"] = round(u["balance"] - bet, 2)
  LIVE_TICKETS.append(
      {"player": mask_uid(uid), "picks": picks, "bet": bet, "payout": 0.0}
  )
  return jsonify({
      "ok": True,
      "balance": u["balance"],
      "tickets": LIVE_TICKETS[-25:],
  })


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
    tk["payout"] = round(
        float(tk["bet"])
        * PAYTABLE.get(len(tk["picks"]), {}).get(len(tk_hits), 0.0),
        2,
    )
  snapshot = list(LIVE_TICKETS[-25:])
  if not picks or bet < 2:
    LIVE_TICKETS.clear()
    return jsonify({
        "ok": True,
        "balance": u["balance"],
        "drawn": drawn,
        "hits": [],
        "matches": 0,
        "payout": 0.0,
        "tickets": snapshot,
    })
  if not (1 <= len(picks) <= 10):
    return jsonify({"ok": False, "msg": "ምርጫው ከ1 እስከ 10 መሆን አለበት።"})
  if not already:
    if u["balance"] <= 0 or bet > u["balance"]:
      return jsonify(
          {"ok": False, "insufficient": True, "msg": "በቂ ባላንስ የለም"}
      )
    u["balance"] = round(u["balance"] - bet, 2)
  hits = sorted([x for x in picks if x in drawn_set])
  payout = round(bet * PAYTABLE.get(len(picks), {}).get(len(hits), 0.0), 2)
  u["balance"] = round(u["balance"] + payout, 2)
  u["bets"].append({"bet": bet, "matches": len(hits), "payout": payout})
  LIVE_TICKETS.clear()
  return jsonify({
      "ok": True,
      "balance": u["balance"],
      "drawn": drawn,
      "hits": hits,
      "matches": len(hits),
      "payout": payout,
      "tickets": snapshot,
  })


@app.route("/api/deposit", methods=["POST"])
def api_deposit():
  d = request.get_json(force=True)
  uid = str(d.get("uid", "874411134")).strip()
  m = str(d.get("method", "")).strip()
  mode = str(d.get("mode", "code")).strip()
  tx = str(d.get("tx", "")).strip().upper()
  shot_b64 = str(d.get("shot_b64", "")).strip()
  amt = float(d.get("amount", 0) or 0)
  time.sleep(6)
  if amt < 10:
    return jsonify({"ok": False, "msg": "❌ ስህተት ነው፤ ወደ እኛ አልገባም (ዝቅተኛ ገቢ 10 ብር ነው)።"})

  u = get_u(uid)
  if mode == "shot":
    if not shot_b64:
      return jsonify({"ok": False, "msg": "❌ ስህተት ነው፤ ወደ እኛ አልገባም (ስክሪንሻት አልተመረጠም)።"})
    raw_b64 = shot_b64.split(",", 1)[1] if "," in shot_b64 else shot_b64
    try:
      img_bytes = base64.b64decode(raw_b64)
    except Exception:
      return jsonify({"ok": False, "msg": "❌ ስህተት ነው፤ ወደ እኛ አልገባም (የስክሪንሻት ፋይል ማንበብ አልተቻለም)።"})
    if not img_bytes:
      return jsonify({"ok": False, "msg": "❌ ስህተት ነው፤ ወደ እኛ አልገባም (ባዶ ስክሪንሻት ነው)።"})
    shot_digest = hashlib.sha256(img_bytes).hexdigest()[:16].upper()
    shot_key = f"SHOT_{shot_digest}"
    if shot_key in USED_TX:
      return jsonify({
          "ok": False,
          "msg": "⚠️ ደብል ነው! ከዚህ በፊት ተጠቅመበት ነው (ይህ ስክሪንሻት ቀድሞ ተመዝግቧል)።",
      })
    USED_TX.add(shot_key)
    u["balance"] = round(u["balance"] + amt, 2)
    notify_internal_photo(
        img_bytes,
        caption=(
            f"📸 Deposit Screenshot Verified & Credited\n"
            f"Ref: {shot_key}\n"
            f"Customer ID: {uid}\n"
            f"Method: {m}\n"
            f"Amount: {amt:.2f} ETB\n"
            f"New Balance: {u['balance']:.2f} ETB"
        ),
    )
    return jsonify({
        "ok": True,
        "balance": u["balance"],
        "msg": (
            f"✅ ገብቷል፤ ትክክለኛ ነው! በ {m} ስክሪንሻት ({shot_key}) {amt:.2f} ብር"
            " ተረጋግጦ ወደ ባላንስዎ ተጨምሯል።"
        ),
    })

  st = check_tx_status(m, tx)
  if st == "duplicate":
    return jsonify({
        "ok": False,
        "msg": "⚠️ ደብል ነው! ከዚህ በፊት ተጠቅመበት ነው (ይህ ኮድ ቀድሞ ጥቅም ላይ ውሏል)።",
    })
  if st != "ok":
    return jsonify({
        "ok": False,
        "msg": "❌ ስህተት ነው፤ ወደ እኛ አልገባም (ይህ የክፍያ ኮድ ትክክል አይደለም ወይም አልገባም)።",
    })
  USED_TX.add(tx)
  u["balance"] = round(u["balance"] + amt, 2)
  return jsonify({
      "ok": True,
      "balance": u["balance"],
      "msg": (
          f"✅ ገብቷል፤ ትክክለኛ ነው! በ {m} ({tx}) {amt:.2f} ብር ተረጋግጦ ወደ"
          " ባላንስዎ ተጨምሯል።"
      ),
  })


@app.route("/api/withdraw", methods=["POST"])
def api_withdraw():
  if not is_wd_hours():
    return jsonify({
        "ok": False,
        "msg": (
            "⏰ ገንዘብ ማውጣት የሚቻለው ከጠዋት 2:00 እስከ ማታ 3:00 ብቻ ነው። ገቢ ግን"
            " 24 ሰዓት ይቻላል።"
        ),
    })
  d = request.get_json(force=True)
  uid, amt, m, dest = (
      str(d.get("uid", "874411134")).strip(),
      float(d.get("amount", 0) or 0),
      str(d.get("method", "")).strip(),
      str(d.get("dest", "")).strip(),
  )
  u = get_u(uid)
  if amt <= 0:
    return jsonify({"ok": False, "msg": "ትክክለኛ የብር መጠን ያስገቡ።"})
  if amt > u["balance"]:
    return jsonify({"ok": False, "msg": "በቂ ባላንስ የለዎትም።"})
  if not dest:
    return jsonify({"ok": False, "msg": "የአካውንት ቁጥር እና ሙሉ ስም ያስገቡ።"})
  u["balance"] = round(u["balance"] - amt, 2)
  wid = "WD-" + uuid.uuid4().hex[:6].upper()
  obj = {
      "id": wid,
      "uid": uid,
      "method": m,
      "amount": amt,
      "dest": dest,
      "status": "Pending",
  }
  WITHDRAWALS[wid] = obj
  u["wds"].append(obj)
  wd_text = (
      f"💸 Withdraw Request (Pending)\n"
      f"ID: {wid}\n"
      f"Customer ID: {uid}\n"
      f"Bank: {m}\n"
      f"Amount: {amt:.2f} ETB\n"
      f"Customer Account: {dest}"
  )
  wd_kb = {
      "inline_keyboard": [[{
          "text": f"✅ Approve ({wid})",
          "callback_data": f"approve_wd:{wid}",
      }]]
  }
  targets = []
  primary = resolve_internal_target()
  if primary:
    targets.append(primary)
  for cid in [PAYOUT_CHAT_ID, ADMIN_CHAT_ID]:
    if cid and str(cid) not in targets:
      targets.append(str(cid))
  for cid in targets:
    tg(cid, wd_text, wd_kb)
  return jsonify({
      "ok": True,
      "balance": u["balance"],
      "msg": (
          f"⏳ የ {amt:.2f} ብር የወጪ ጥያቄዎ ({wid}) በመጠባበቅ ላይ (Pending) ነው፤ እስኪደርስዎ በሂደት ላይ ይቆያል።"
      ),
  })


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
      f"✅ ተጠናቋል (Completed)! የ {w['amount']:.2f} ብር የወጪ ጥያቄዎ ({wid}) ተጠናቆ"
      f" ወደ አካውንትዎ ({w['dest']}) ተልኳል።",
  )
  return jsonify(
      {"ok": True, "msg": f"{wid} ተጠናቋል (Completed)፤ ለደንበኛው ተልኳል።"}
  )


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
