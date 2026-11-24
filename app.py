import os
import re
import random
import uuid
from datetime import datetime, timezone, timedelta
import requests
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "").strip()
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "enyachew_19").strip()
TELEBIRR_ACCOUNT = os.environ.get("TELEBIRR_ACCOUNT", "0944123180 - Enyachew Amerga").strip()
CBE_ACCOUNT = os.environ.get("CBE_ACCOUNT", "1000682528641 - Enyachew Amerga").strip()
WEBAPP_URL = os.environ.get("WEBAPP_URL", "").strip()

EAT = timezone(timedelta(hours=3))
USERS = {}
USED_TX = set()
WITHDRAWALS = {}

PAYTABLE = {
    1: {1: 3.5}, 2: {1: 1.0, 2: 9.0}, 3: {2: 2.5, 3: 25.0},
    4: {2: 1.5, 3: 5.0, 4: 60.0}, 5: {3: 2.0, 4: 12.0, 5: 150.0},
    6: {3: 1.5, 4: 5.0, 5: 25.0, 6: 300.0},
    7: {3: 1.0, 4: 3.0, 5: 12.0, 6: 80.0, 7: 500.0},
    8: {4: 2.0, 5: 8.0, 6: 30.0, 7: 150.0, 8: 1000.0},
    9: {4: 1.5, 5: 5.0, 6: 20.0, 7: 75.0, 8: 300.0, 9: 1500.0},
    10: {5: 3.0, 6: 15.0, 7: 50.0, 8: 200.0, 9: 800.0, 10: 2500.0},
}


def is_withdraw_hours():
    # ዊዝድሮ ብቻ ከጠዋት 2:00 (08:00) እስከ ማታ 3:00 (21:00) በኢትዮጵያ ሰዓት
    now_eat = datetime.now(EAT)
    return 8 <= now_eat.hour < 21


def get_user(uid: str):
    is_new = uid not in USERS
    if is_new:
        USERS[uid] = {"balance": 10.0, "bonus_given": True, "withdrawals": [], "bets": []}
    return USERS[uid], is_new


def tg_send(chat_id: str, text: str, reply_markup=None):
    if not BOT_TOKEN or not chat_id:
        return False
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload, timeout=8)
        return r.ok
    except Exception:
        return False


def verify_tx_reference(method: str, tx_code: str) -> bool:
    code = tx_code.strip().upper()
    if len(code) < 6 or code in USED_TX:
        return False
    if method == "CBE":
        return bool(re.match(r"^FT[A-Z0-9]{6,18}$", code))
    return bool(re.match(r"^[A-Z0-9]{6,20}$", code))


HTML_PAGE = f"""<!DOCTYPE html>
<html lang="am">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FAST KENO</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
*{{box-sizing:border-box}}body{{margin:0;font-family:Arial,sans-serif;background:#111317;color:#f3f4f6;padding-bottom:65px}}
.top{{display:flex;justify-content:space-between;align-items:center;padding:10px 12px;background:#191c22;border-bottom:1px solid #2b303b}}
.pill{{background:#242934;padding:5px 10px;border-radius:99px;font-size:12px;font-weight:700;color:#4ade80}}
.sub{{display:flex;justify-content:space-between;padding:7px 12px;background:#15181e;font-size:12px;color:#9ca3af}}
.timer{{background:#22c55e;color:#061209;font-weight:800;padding:3px 9px;border-radius:7px}}
.grid{{display:grid;grid-template-columns:repeat(10,1fr);gap:4px;padding:8px 12px}}
.t{{height:35px;border:1px solid #2d3340;border-radius:6px;background:#1f242d;color:#fff;font-weight:700;font-size:12px}}
.t.sel{{background:#16a34a;border-color:#4ade80}}.t.hit{{background:#eab308;color:#111}}.t.miss{{background:#2563eb}}
.ctrl{{padding:8px 12px}}.row{{display:grid;grid-template-columns:42px 1fr 42px 50px 60px;gap:6px;margin-bottom:8px}}
.btn{{background:#262c37;color:#fff;border:1px solid #374151;border-radius:8px;height:36px;font-weight:700}}
.val{{background:#181b21;border:1px solid #374151;border-radius:8px;display:flex;align-items:center;justify-content:center;font-weight:800}}
.betbtn{{width:100%;height:42px;border:none;border-radius:9px;background:#22c55e;color:#061209;font-weight:900;font-size:15px}}
.box{{margin:8px 12px;padding:10px;border-radius:10px;background:#1a1e26;border:1px solid #2b313d;font-size:12px;line-height:1.45}}
.panel{{display:none;padding:10px}}.panel.active{{display:block}}
input,select{{width:100%;padding:9px;margin:5px 0 9px;border-radius:8px;border:1px solid #374151;background:#111317;color:#fff}}
.act{{width:100%;padding:10px;border:none;border-radius:8px;font-weight:800;color:#fff;background:#16a34a}}
.amb{{background:#d97706}}.appb{{background:#2563eb;color:#fff;border:none;padding:5px 9px;border-radius:6px;margin-top:5px}}
.nav{{position:fixed;bottom:0;left:0;right:0;height:54px;background:#181b21;border-top:1px solid #2b303b;display:grid;grid-template-columns:repeat(3,1fr)}}
.nb{{background:none;border:none;color:#9ca3af;font-weight:700;font-size:11px}}.nb.active{{color:#4ade80}}
</style>
</head>
<body>
<div class="top"><strong style="color:#4ade80">⚡ FAST KENO</strong><div class="pill">ባላንስ: <span id="bal">10.00</span> ETB</div></div>
<div class="sub"><div>ምርጫ: <strong id="cnt">0</strong>/10 | ቦነስ: 10 ETB</div><div class="timer" id="tm">00:30</div></div>

<div id="p-game" class="panel active">
  <div class="box" style="display:flex;justify-content:space-between"><span>Possible win: <strong id="mwin" style="color:#4ade80">0 ETB</strong></span><button class="btn" style="height:26px;padding:0 8px;font-size:11px" onclick="qpick()">Quick Pick</button></div>
  <div class="grid" id="grid"></div>
  <div class="ctrl">
    <div class="row">
      <button class="btn" onclick="sbet(-10)">-</button><div class="val" id="bval">10</div><button class="btn" onclick="sbet(10)">+</button>
      <button class="btn" onclick="sbet(bet)">X2</button><button class="btn" onclick="bet=Math.max(10,Math.floor(bal));ui()">MAX</button>
    </div>
    <button class="betbtn" onclick="play()">BET</button>
  </div>
  <div class="box" id="gmsg">ከ 1-10 ቁጥሮች እና መደብ (ቢያንስ 10 ETB) መርጠው BET ይጫኑ።</div>
</div>

<div id="p-wallet" class="panel">
  <div class="box">
    <strong>💳 Deposit (24 ሰዓት ክፍት ነው)</strong><br>
    Telebirr: <b>{TELEBIRR_ACCOUNT}</b><br>CBE: <b>{CBE_ACCOUNT}</b><br>
    <span style="color:#4ade80">ወደ አድሚን አይሄድም፤ ቦቱ FT/Transaction ኮዱን አረጋግጦ ወደ ባላንስ ይጨምራል።</span>
    <select id="dm"><option value="Telebirr">Telebirr</option><option value="CBE">CBE</option></select>
    <input type="number" id="da" placeholder="የብር መጠን (ቢያንስ 10)" value="50">
    <input type="text" id="dt" placeholder="FT / Transaction ኮድ ያስገቡ (ለምሳሌ FT26328XXXX)">
    <button class="act" onclick="dep()">ገቢ አረጋግጥ</button>
    <div id="dmsg" style="margin-top:6px;color:#93c5fd"></div>
  </div>
  <div class="box">
    <strong>💸 Withdraw (ከጠዋት 2:00 - ማታ 3:00 ብቻ)</strong><br>
    <input type="number" id="wa" placeholder="መጀመሪያ የሚወጣውን Amount ይጻፉ" value="10">
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
const uid=tg&&tg.initDataUnsafe&&tg.initDataUnsafe.user?String(tg.initDataUnsafe.user.id):"895515150";
const PT={{1:{{1:3.5}},2:{{1:1,2:9}},3:{{2:2.5,3:25}},4:{{2:1.5,3:5,4:60}},5:{{3:2,4:12,5:150}},6:{{3:1.5,4:5,5:25,6:300}},7:{{3:1,4:3,5:12,6:80,7:500}},8:{{4:2,5:8,6:30,7:150,8:1000}},9:{{4:1.5,5:5,6:20,7:75,8:300,9:1500}},10:{{5:3,6:15,7:50,8:200,9:800,10:2500}}}};
let bal=10,bet=10; const picks=new Set();
const g=document.getElementById("grid");
for(let i=1;i<=80;i++){{const b=document.createElement("button");b.className="t";b.dataset.n=i;b.textContent=i;
b.onclick=()=>{{if(picks.has(i)){{picks.delete(i);b.classList.remove("sel")}}else{{if(picks.size>=10)return alert("ከ10 በላይ አይቻልም");picks.add(i);b.classList.add("sel")}}ui()}};g.appendChild(b)}}
function ui(){{document.getElementById("cnt").textContent=picks.size;document.getElementById("bval").textContent=bet;
const t=PT[picks.size]||{{}};const mx=Math.max(0,...Object.values(t));document.getElementById("mwin").textContent=(bet*mx).toFixed(2)+" ETB"}}
function sbet(d){{bet=Math.max(10,bet+d);ui()}}
function qpick(){{picks.clear();document.querySelectorAll(".t").forEach(x=>x.classList.remove("sel","hit","miss"));
const a=Array.from({{length:80}},(_,i)=>i+1).sort(()=>Math.random()-0.5).slice(0,10);
a.forEach(n=>{{picks.add(n);document.querySelector(`.t[data-n="${{n}}"]`).classList.add("sel")}});ui()}}
function tab(k){{["game","wallet","hist"].forEach(x=>{{document.getElementById("p-"+x).classList.toggle("active",x===k);document.getElementById("n-"+x).classList.toggle("active",x===k)}});load()}}
async function load(){{const r=await fetch(`/api/state?uid=${{uid}}`);const d=await r.json();bal=d.balance;document.getElementById("bal").textContent=bal.toFixed(2);
document.getElementById("hlist").innerHTML=d.bets.length?d.bets.slice().reverse().map(x=>`<div>Bet:${{x.bet}} | Hits:${{x.matches}} | Win:${{x.payout}} ETB</div>`).join(""):"ምንም ታሪክ የለም።";
document.getElementById("wlist").innerHTML=d.wds.length?d.wds.slice().reverse().map(w=>`<div style="padding:5px 0;border-bottom:1px solid #2b303b">${{w.id}} | ${{w.method}} (${{w.dest}}) | ${{w.amount}} ETB | <b>${{w.status}}</b>${{d.is_admin&&w.status==="Pending"?`<br><button class="appb" onclick="appw('${{w.id}}')">Approve (Completed)</button>`:""}}</div>`).join(""):"ምንም ጥያቄ የለም።"}}
async function play(){{if(!picks.size)return alert("ቢያንስ 1 ቁጥር ምረጥ");document.querySelectorAll(".t").forEach(x=>x.classList.remove("hit","miss"));
const r=await fetch("/api/play",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{uid,picks:Array.from(picks),bet}})}});
const d=await r.json();if(!d.ok)return document.getElementById("gmsg").textContent="❌ "+d.msg;
bal=d.balance;document.getElementById("bal").textContent=bal.toFixed(2);
d.drawn.forEach(n=>{{const el=document.querySelector(`.t[data-n="${{n}}"]`);el.classList.add(picks.has(n)?"hit":"miss")}});
document.getElementById("gmsg").innerHTML=`<b>Drawn:</b> ${{d.drawn.join(", ")}}<br><b>Matches (${{d.matches}}):</b> ${{d.hits.join(", ")||"0"}} | <b>Win:</b> ${{d.payout}} ETB`}}
async function dep(){{const r=await fetch("/api/deposit",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{uid,method:document.getElementById("dm").value,amount:document.getElementById("da").value,tx:document.getElementById("dt").value}})}});
const d=await r.json();document.getElementById("dmsg").textContent=d.msg;if(d.ok){{document.getElementById("dt").value="";load()}}}}
async function wdr(){{const r=await fetch("/api/withdraw",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{uid,amount:document.getElementById("wa").value,method:document.getElementById("wm").value,dest:document.getElementById("wd").value}})}});
const d=await r.json();document.getElementById("wmsg").textContent=d.msg;if(d.ok){{document.getElementById("wd").value="";load()}}}}
async function appw(id){{const r=await fetch("/api/approve",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{uid,id}})}});const d=await r.json();alert(d.msg);load()}}
let s=30;setInterval(()=>{{s=s<=1?30:s-1;document.getElementById("tm").textContent="00:"+String(s).padStart(2,"0")}},1000);ui();load();
</script>
</body>
</html>"""


@app.route("/")
def home():
    return render_template_string(HTML_PAGE)


@app.route("/webhook", methods=["POST"])
def webhook():
    upd = request.get_json(silent=True) or {}
    msg = upd.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    uid = str(chat.get("id", "")).strip()
    if uid and text.startswith("/start"):
        u, is_new = get_user(uid)
        bonus_txt = "🎁 አዲስ ተመዝጋቢ ስለሆንክ 10.00 ETB ቦነስ ተሰጥቶሃል!\n" if is_new else ""
        base_url = WEBAPP_URL or request.url_root.rstrip("/")
        kb = {"inline_keyboard": [[{"text": "⚡ Play FAST KENO", "web_app": {"url": base_url}}]]}
        tg_send(uid, f"እንኳን ወደ FAST KENO በደህና መጡ!\n{bonus_txt}ባላንስዎ: {u['balance']:.2f} ETB", kb)
    return jsonify({"ok": True})


@app.route("/api/state")
def api_state():
    uid = str(request.args.get("uid", "895515150")).strip()
    u, _ = get_user(uid)
    is_admin = bool(ADMIN_CHAT_ID and uid == ADMIN_CHAT_ID)
    wds = list(WITHDRAWALS.values()) if is_admin else u["withdrawals"]
    return jsonify({"balance": u["balance"], "bets": u["bets"][-20:], "wds": wds, "is_admin": is_admin})


@app.route("/api/play", methods=["POST"])
def api_play():
    d = request.get_json(force=True)
    uid = str(d.get("uid", "895515150")).strip()
    picks = d.get("picks", [])
    bet = float(d.get("bet", 0) or 0)
    u, _ = get_user(uid)
    if not (1 <= len(picks) <= 10) or bet < 10:
        return jsonify({"ok": False, "msg": "ከ1-10 ቁጥር እና ቢያንስ 10 ETB ይምረጡ።"})
    if bet > u["balance"]:
        return jsonify({"ok": False, "msg": "በቂ ባላንስ የለህም።"})
    u["balance"] = round(u["balance"] - bet, 2)
    drawn = sorted(random.sample(range(1, 81), 20))
    hits = sorted([int(x) for x in picks if int(x) in set(drawn)])
    payout = round(bet * PAYTABLE.get(len(picks), {}).get(len(hits), 0.0), 2)
    u["balance"] = round(u["balance"] + payout, 2)
    u["bets"].append({"bet": bet, "matches": len(hits), "payout": payout})
    return jsonify({"ok": True, "balance": u["balance"], "drawn": drawn, "hits": hits, "matches": len(hits), "payout": payout})


@app.route("/api/deposit", methods=["POST"])
def api_deposit():
    d = request.get_json(force=True)
    uid = str(d.get("uid", "895515150")).strip()
    method = str(d.get("method", "")).strip()
    tx = str(d.get("tx", "")).strip().upper()
    amount = float(d.get("amount", 0) or 0)
    if amount < 10:
        return jsonify({"ok": False, "msg": "ዝቅተኛ ገቢ 10 ETB ነው።"})
    if not verify_tx_reference(method, tx):
        return jsonify({"ok": False, "msg": "❌ ስህተት ነው፤ ይህ የ FT / Transaction ኮድ የለም ወይም ቀድሞ ተጠቅሟል።"})
    USED_TX.add(tx)
    u, _ = get_user(uid)
    u["balance"] = round(u["balance"] + amount, 2)
    return jsonify({"ok": True, "balance": u["balance"], "msg": f"✅ በ {method} ({tx}) {amount:.2f} ETB ተረጋግጦ ወደ ባላንስህ ተጨምሯል።"})


@app.route("/api/withdraw", methods=["POST"])
def api_withdraw():
    if not is_withdraw_hours():
        return jsonify({"ok": False, "msg": "⏰ ዊዝድሮ የሚቻለው ከጠዋት 2:00 እስከ ማታ 3:00 ብቻ ነው። ዲፖዚት ግን 24 ሰዓት ይቻላል።"})
    d = request.get_json(force=True)
    uid = str(d.get("uid", "895515150")).strip()
    amount = float(d.get("amount", 0) or 0)
    method = str(d.get("method", "")).strip()
    dest = str(d.get("dest", "")).strip()
    u, _ = get_user(uid)
    if amount <= 0:
        return jsonify({"ok": False, "msg": "ትክክለኛ አማውንት ያስገቡ።"})
    if amount > u["balance"]:
        return jsonify({"ok": False, "msg": "በቂ ባላንስ የለህም።"})
    if not dest:
        return jsonify({"ok": False, "msg": "የቴሌብር ስልክ ወይም የCBE አካውንት ያስገቡ።"})
    u["balance"] = round(u["balance"] - amount, 2)
    wid = "WD-" + uuid.uuid4().hex[:6].upper()
    obj = {"id": wid, "uid": uid, "method": method, "amount": amount, "dest": dest, "status": "Pending"}
    WITHDRAWALS[wid] = obj
    u["withdrawals"].append(obj)
    tg_send(ADMIN_CHAT_ID, f"💸 Withdraw Pending\nID: {wid}\nUser: {uid}\nBank: {method}\nAmount: {amount:.2f} ETB\nAccount: {dest}")
    return jsonify({"ok": True, "balance": u["balance"], "msg": f"⏳ ጥያቄዎ ({wid}) Pending ላይ ነው፤ ቦቱ ወደ አድሚኑ ልኮታል።"})


@app.route("/api/approve", methods=["POST"])
def api_approve():
    d = request.get_json(force=True)
    if not ADMIN_CHAT_ID or str(d.get("uid", "")).strip() != ADMIN_CHAT_ID:
        return jsonify({"ok": False, "msg": "አድሚን ብቻ ነው ማጽደቅ የሚችለው።"}), 403
    wid = str(d.get("id", "")).strip()
    w = WITHDRAWALS.get(wid)
    if not w:
        return jsonify({"ok": False, "msg": "ጥያቄው አልተገኘም።"}), 404
    w["status"] = "Completed"
    for item in get_user(w["uid"])[0]["withdrawals"]:
        if item["id"] == wid:
            item["status"] = "Completed"
    tg_send(w["uid"], f"✅ የ {w['amount']:.2f} ETB የወጪ ጥያቄዎ ({wid}) Completed ሆኗል።")
    return jsonify({"ok": True, "msg": f"{wid} ወደ Completed ተቀይሯል።"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
