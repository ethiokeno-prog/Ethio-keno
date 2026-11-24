import os
import random
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

BOT_USERNAME = "ethio_keno_play_26_bot"

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "enyachew_19")
TELEBIRR_ACCOUNT = os.environ.get("TELEBIRR_ACCOUNT", "0944123180 - Enyachew Amerga")
CBE_ACCOUNT = os.environ.get("CBE_ACCOUNT", "1000682528641 - Enyachew Amerga")

USERS = {}
USED_TX_CODES = set()
HISTORY_LOGS = []

PAYTABLE = {
    1: {1: 3.5},
    2: {1: 1.0, 2: 9.0},
    3: {2: 2.5, 3: 25.0},
    4: {2: 1.5, 3: 5.0, 4: 60.0},
    5: {3: 2.0, 4: 12.0, 5: 150.0},
    6: {3: 1.5, 4: 5.0, 5: 25.0, 6: 300.0},
    7: {3: 1.0, 4: 3.0, 5: 12.0, 6: 80.0, 7: 500.0},
    8: {4: 2.0, 5: 8.0, 6: 30.0, 7: 150.0, 8: 1000.0},
    9: {4: 1.5, 5: 5.0, 6: 20.0, 7: 75.0, 8: 300.0, 9: 1500.0},
    10: {5: 3.0, 6: 15.0, 7: 50.0, 8: 200.0, 9: 800.0, 10: 2500.0},
}


def get_user(user_id: str):
    if user_id not in USERS:
        USERS[user_id] = {"balance": 0.0, "withdrawals": [], "my_bets": []}
    return USERS[user_id]


FAST_KENO_HTML = f"""
<!DOCTYPE html>
<html lang="am">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>FAST KENO</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, sans-serif;
      background: #121417;
      color: #f3f4f6;
      padding-bottom: 72px;
    }}
    .topbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: #1a1d23;
      padding: 10px 12px;
      border-bottom: 1px solid #2a2f3a;
    }}
    .brand {{
      font-weight: 800;
      letter-spacing: 0.5px;
      font-size: 15px;
      color: #4ade80;
    }}
    .pill {{
      background: #242933;
      padding: 5px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: bold;
    }}
    .timer-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 8px 12px;
      background: #16191f;
      font-size: 12px;
      color: #9ca3af;
    }}
    .timer-box {{
      background: #22c55e;
      color: #09130c;
      font-weight: 800;
      padding: 4px 10px;
      border-radius: 8px;
      font-size: 14px;
    }}
    .payout-strip {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: #1b1f27;
      margin: 8px 12px;
      padding: 8px 10px;
      border-radius: 10px;
      border: 1px solid #2b313d;
      font-size: 12px;
    }}
    .pay-table {{
      display: flex;
      gap: 6px;
      overflow-x: auto;
    }}
    .pay-cell {{
      background: #252b36;
      padding: 4px 7px;
      border-radius: 6px;
      text-align: center;
      min-width: 48px;
    }}
    .choose-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 4px 12px 6px;
    }}
    .badge-num {{
      width: 30px;
      height: 30px;
      border-radius: 50%;
      background: #16a34a;
      color: #fff;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-weight: 800;
      margin-right: 8px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(10, 1fr);
      gap: 4px;
      padding: 0 12px;
    }}
    .tile {{
      position: relative;
      height: 36px;
      border: 1px solid #2d3340;
      border-radius: 6px;
      background: #20252e;
      color: #e5e7eb;
      font-weight: 700;
      font-size: 12px;
      cursor: pointer;
    }}
    .tile.selected {{
      background: #16a34a;
      border-color: #4ade80;
      color: #fff;
    }}
    .tile.drawn-hit {{
      background: #eab308;
      border-color: #fde047;
      color: #111827;
    }}
    .tile.drawn-miss {{
      background: #2563eb;
      border-color: #60a5fa;
      color: #fff;
    }}
    .dot {{
      position: absolute;
      top: 3px;
      right: 3px;
      width: 5px;
      height: 5px;
      border-radius: 50%;
    }}
    .dot.hot {{ background: #ef4444; }}
    .dot.warm {{ background: #22c55e; }}
    .dot.cold {{ background: #38bdf8; }}
    .bet-controls {{
      padding: 10px 12px;
    }}
    .stepper {{
      display: grid;
      grid-template-columns: 44px 1fr 44px 52px 64px;
      gap: 6px;
      margin-bottom: 8px;
    }}
    .ctrl-btn {{
      background: #262c37;
      color: #fff;
      border: 1px solid #374151;
      border-radius: 8px;
      font-weight: 700;
      height: 38px;
      cursor: pointer;
    }}
    .bet-val {{
      background: #181b21;
      border: 1px solid #374151;
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 800;
      font-size: 15px;
    }}
    .bet-main-btn {{
      width: 100%;
      height: 44px;
      border: none;
      border-radius: 10px;
      background: #22c55e;
      color: #07130b;
      font-weight: 900;
      font-size: 16px;
      cursor: pointer;
    }}
    .result-box {{
      margin: 0 12px 10px;
      padding: 10px;
      border-radius: 10px;
      background: #1b2029;
      border: 1px solid #2e3646;
      font-size: 13px;
      line-height: 1.45;
    }}
    .panel {{
      display: none;
      padding: 12px;
    }}
    .panel.active {{
      display: block;
    }}
    .card {{
      background: #1b1f27;
      border: 1px solid #2b313d;
      border-radius: 12px;
      padding: 12px;
      margin-bottom: 12px;
    }}
    input, select {{
      width: 100%;
      padding: 9px;
      margin: 6px 0 10px;
      border-radius: 8px;
      border: 1px solid #374151;
      background: #121417;
      color: #fff;
    }}
    .action-btn {{
      width: 100%;
      padding: 10px;
      border: none;
      border-radius: 8px;
      font-weight: 800;
      cursor: pointer;
      color: #fff;
    }}
    .green-btn {{ background: #16a34a; }}
    .amber-btn {{ background: #d97706; }}
    .bottom-nav {{
      position: fixed;
      bottom: 0;
      left: 0;
      right: 0;
      height: 56px;
      background: #181b21;
      border-top: 1px solid #2a2f3a;
      display: grid;
      grid-template-columns: repeat(4, 1fr);
    }}
    .nav-btn {{
      background: none;
      border: none;
      color: #9ca3af;
      font-size: 11px;
      font-weight: 700;
      cursor: pointer;
    }}
    .nav-btn.active {{
      color: #4ade80;
    }}
  </style>
</head>
<body>
  <div class="topbar">
    <div class="brand">⚡ FAST KENO</div>
    <div class="pill">ባላንስ: <span id="bal">0.00</span> ETB</div>
  </div>

  <div class="timer-row">
    <div>ID: <span id="uid-label">---</span> | ምርጫ: <strong id="pick-count">0</strong>/10</div>
    <div class="timer-box" id="timer">00:30</div>
  </div>

  <div id="panel-game" class="panel active">
    <div class="payout-strip">
      <div>
        <div style="color:#9ca3af;font-size:11px;">Possible win</div>
        <div style="color:#4ade80;font-weight:800;font-size:14px;" id="max-win">0.00 ETB</div>
      </div>
      <div class="pay-table" id="paytable-box">
        <div class="pay-cell"><div>Match</div><div>Pays</div></div>
      </div>
    </div>

    <div class="choose-header">
      <div style="display:flex;align-items:center;">
        <span class="badge-num">1</span>
        <div>
          <div style="font-weight:800;font-size:14px;">Choose 10 numbers</div>
          <div style="font-size:11px;color:#9ca3af;">From 1 to 80 (1-10 ምረጥ)</div>
        </div>
      </div>
      <button class="ctrl-btn" style="height:28px;padding:0 10px;font-size:11px;" onclick="quickPick()">Quick</button>
    </div>

    <div class="grid" id="grid"></div>

    <div class="bet-controls">
      <div class="stepper">
        <button class="ctrl-btn" onclick="stepBet(-10)">-</button>
        <div class="bet-val" id="bet-amount">10</div>
        <button class="ctrl-btn" onclick="stepBet(10)">+</button>
        <button class="ctrl-btn" onclick="multBet(2)">X2</button>
        <button class="ctrl-btn" onclick="setMaxBet()">MAX</button>
      </div>
      <button class="bet-main-btn" onclick="placeBet()">BET</button>
    </div>

    <div class="result-box" id="game-msg">ቁጥሮች (1-10) እና መደብ (ቢያንስ 10 ETB) መርጠው BET ይጫኑ።</div>
  </div>

  <div id="panel-wallet" class="panel">
    <div class="card">
      <h3>💳 Deposit (Telebirr / CBE)</h3>
      <div style="font-size:12px;color:#cbd5e1;line-height:1.5;">
        <strong>Telebirr:</strong> {TELEBIRR_ACCOUNT}<br/>
        <strong>CBE:</strong> {CBE_ACCOUNT}<br/>
        <span style="color:#4ade80;">ገቢ ጥያቄ ወደ አድሚኑ አይሄድም፤ ትክክለኛ የ FT / Transaction ኮድ ሲያስገቡ ባላንስ ይጨምራል።</span>
      </div>
      <label>መንገድ</label>
      <select id="dep-method">
        <option value="Telebirr">Telebirr</option>
        <option value="CBE">CBE</option>
      </select>
      <label>የገባው ብር (ቢያንስ 10)</label>
      <input type="number" id="dep-amt" value="50" min="10" />
      <label>Transaction / FT ኮድ</label>
      <input type="text" id="dep-tx" placeholder="ለምሳሌ FT26328XXXX" />
      <button class="action-btn green-btn" onclick="doDeposit()">ገቢ አረጋግጥ</button>
      <div id="dep-res" style="margin-top:8px;font-size:13px;color:#93c5fd;"></div>
    </div>

    <div class="card">
      <h3>💸 Withdraw (ወደ አድሚን ይላካል)</h3>
      <div style="font-size:12px;color:#cbd5e1;">የወጪ ጥያቄ ወደ አድሚኑ (<strong>@{ADMIN_USERNAME}</strong>) ይላካል።</div>
      <label>መንገድ</label>
      <select id="wd-method">
        <option value="Telebirr">Telebirr</option>
        <option value="CBE">CBE</option>
      </select>
      <label>የሚወጣው ብር (ቢያንስ 10)</label>
      <input type="number" id="wd-amt" value="20" min="10" />
      <label>የቴሌብር ስልክ ወይም የCBE አካውንት</label>
      <input type="text" id="wd-dest" placeholder="09... ወይም 1000..." />
      <button class="action-btn amber-btn" onclick="doWithdraw()">ወደ አድሚን ላክ</button>
      <div id="wd-res" style="margin-top:8px;font-size:13px;color:#fcd34d;"></div>
    </div>
  </div>

  <div id="panel-history" class="panel">
    <div class="card">
      <h3>📜 የእኔ የጨዋታ ታሪክ (History)</h3>
      <div id="my-history" style="font-size:13px;color:#cbd5e1;">ምንም ታሪክ የለም።</div>
    </div>
  </div>

  <div id="panel-results" class="panel">
    <div class="card">
      <h3>🎯 የቅርብ ጊዜ ውጤቶች (Results & Stats)</h3>
      <div id="global-results" style="font-size:13px;color:#cbd5e1;">ገና ውጤት አልተመዘገበም።</div>
    </div>
  </div>

  <div class="bottom-nav">
    <button class="nav-btn active" id="nav-game" onclick="switchTab('game')">GAME</button>
    <button class="nav-btn" id="nav-wallet" onclick="switchTab('wallet')">WALLET</button>
    <button class="nav-btn" id="nav-history" onclick="switchTab('history')">HISTORY</button>
    <button class="nav-btn" id="nav-results" onclick="switchTab('results')">RESULTS</button>
  </div>

  <script>
    const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
    if (tg) tg.expand();
    const tgUser = tg && tg.initDataUnsafe && tg.initDataUnsafe.user ? tg.initDataUnsafe.user : null;
    const userId = tgUser ? String(tgUser.id) : "895515150";
    document.getElementById("uid-label").textContent = userId;

    const PAYTABLE = {{
      1: {{1: 3.5}},
      2: {{1: 1.0, 2: 9.0}},
      3: {{2: 2.5, 3: 25.0}},
      4: {{2: 1.5, 3: 5.0, 4: 60.0}},
      5: {{3: 2.0, 4: 12.0, 5: 150.0}},
      6: {{3: 1.5, 4: 5.0, 5: 25.0, 6: 300.0}},
      7: {{3: 1.0, 4: 3.0, 5: 12.0, 6: 80.0, 7: 500.0}},
      8: {{4: 2.0, 5: 8.0, 6: 30.0, 7: 150.0, 8: 1000.0}},
      9: {{4: 1.5, 5: 5.0, 6: 20.0, 7: 75.0, 8: 300.0, 9: 1500.0}},
      10: {{5: 3.0, 6: 15.0, 7: 50.0, 8: 200.0, 9: 800.0, 10: 2500.0}}
    }};

    let balance = 0;
    let betAmount = 10;
    const picked = new Set();
    const dotPattern = ["hot", "warm", "cold"];

    const gridEl = document.getElementById("grid");
    for (let n = 1; n <= 80; n++) {{
      const btn = document.createElement("button");
      btn.className = "tile";
      btn.dataset.num = n;
      btn.textContent = n;
      if (n % 7 === 0 || n % 13 === 0) {{
        const dot = document.createElement("span");
        dot.className = "dot " + dotPattern[n % 3];
        btn.appendChild(dot);
      }}
      btn.onclick = () => toggleNum(n, btn);
      gridEl.appendChild(btn);
    }}

    function toggleNum(n, btn) {{
      if (picked.has(n)) {{
        picked.delete(n);
        btn.classList.remove("selected");
      }} else {{
        if (picked.size >= 10) {{
          alert("ከ 10 ቁጥር በላይ መምረጥ አይቻልም!");
          return;
        }}
        picked.add(n);
        btn.classList.add("selected");
      }}
      updatePayoutUI();
    }}

    function quickPick() {{
      clearHighlights(true);
      picked.clear();
      const pool = Array.from({{length: 80}}, (_, i) => i + 1);
      for (let i = pool.length - 1; i > 0; i--) {{
        const j = Math.floor(Math.random() * (i + 1));
        [pool[i], pool[j]] = [pool[j], pool[i]];
      }}
      pool.slice(0, 10).forEach(n => {{
        picked.add(n);
        document.querySelector(`.tile[data-num="${{n}}"]`).classList.add("selected");
      }});
      updatePayoutUI();
    }}

    function updatePayoutUI() {{
      document.getElementById("pick-count").textContent = picked.size;
      document.getElementById("bet-amount").textContent = betAmount;
      const box = document.getElementById("paytable-box");
      const table = PAYTABLE[picked.size] || {{}};
      const entries = Object.entries(table);
      let maxMult = 0;
      let html = "";
      entries.forEach(([m, mult]) => {{
        if (mult > maxMult) maxMult = mult;
        html += `<div class="pay-cell"><div style="color:#9ca3af;">M:${{m}}</div><div style="color:#4ade80;font-weight:700;">x${{mult}}</div></div>`;
      }});
      box.innerHTML = html || `<div class="pay-cell"><div>1-10</div><div>ምረጥ</div></div>`;
      document.getElementById("max-win").textContent = `${{(betAmount * maxMult).toFixed(2)}} ETB`;
    }}

    function stepBet(delta) {{
      betAmount = Math.max(10, betAmount + delta);
      updatePayoutUI();
    }}

    function multBet(factor) {{
      betAmount = Math.max(10, betAmount * factor);
      updatePayoutUI();
    }}

    function setMaxBet() {{
      betAmount = Math.max(10, Math.floor(balance));
      updatePayoutUI();
    }}

    function clearHighlights(keepSelected) {{
      document.querySelectorAll(".tile").forEach(el => {{
        el.classList.remove("drawn-hit", "drawn-miss");
        const num = Number(el.dataset.num);
        if (!keepSelected || !picked.has(num)) {{
          el.classList.remove("selected");
        }}
      }});
    }}

    function setBalance(val) {{
      balance = Number(val) || 0;
      document.getElementById("bal").textContent = balance.toFixed(2);
      updatePayoutUI();
    }}

    async function loadState() {{
      const res = await fetch(`/api/state?user_id=${{encodeURIComponent(userId)}}`);
      const data = await res.json();
      setBalance(data.balance);
      renderHistory(data.my_bets || [], data.global_logs || []);
    }}

    async function placeBet() {{
      if (picked.size < 1) {{
        alert("ቢያንስ 1 ቁጥር ምረጥ!");
        return;
      }}
      if (betAmount < 10) {{
        alert("ዝቅተኛ መደብ 10 ETB ነው!");
        return;
      }}
      clearHighlights(true);
      const res = await fetch("/api/play", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{
          user_id: userId,
          picks: Array.from(picked),
          bet: betAmount
        }})
      }});
      const data = await res.json();
      if (!data.ok) {{
        document.getElementById("game-msg").textContent = "❌ " + data.message;
        return;
      }}
      setBalance(data.balance);
      const drawnSet = new Set(data.drawn);
      data.drawn.forEach(n => {{
        const el = document.querySelector(`.tile[data-num="${{n}}"]`);
        if (picked.has(n)) el.classList.add("drawn-hit");
        else el.classList.add("drawn-miss");
      }});
      document.getElementById("game-msg").innerHTML =
        `<div><strong>Draw (20):</strong> ${{data.drawn.join(", ")}}</div>` +
        `<div><strong>Matches (${{data.matches}}):</strong> ${{data.hits.join(", ") || "ምንም"}} | <strong>Win:</strong> ${{data.payout.toFixed(2)}} ETB</div>`;
      renderHistory(data.my_bets || [], data.global_logs || []);
    }}

    async function doDeposit() {{
      const method = document.getElementById("dep-method").value;
      const amount = parseFloat(document.getElementById("dep-amt").value);
      const tx_code = document.getElementById("dep-tx").value.trim();
      const res = await fetch("/api/deposit", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ user_id: userId, method, amount, tx_code }})
      }});
      const data = await res.json();
      document.getElementById("dep-res").textContent = data.message;
      if (data.ok) {{
        setBalance(data.balance);
        document.getElementById("dep-tx").value = "";
      }}
    }}

    async function doWithdraw() {{
      const method = document.getElementById("wd-method").value;
      const amount = parseFloat(document.getElementById("wd-amt").value);
      const destination = document.getElementById("wd-dest").value.trim();
      const res = await fetch("/api/withdraw", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ user_id: userId, method, amount, destination }})
      }});
      const data = await res.json();
      document.getElementById("wd-res").textContent = data.message;
      if (data.ok) {{
        setBalance(data.balance);
        document.getElementById("wd-dest").value = "";
      }}
    }}

    function renderHistory(myBets, globalLogs) {{
      document.getElementById("my-history").innerHTML = myBets.length
        ? myBets.slice().reverse().map(b => `<div style="padding:6px 0;border-bottom:1px solid #2a2f3a;">Bet: ${{b.bet}} ETB | Picks: [${{b.picks.join(",")}}] | Matches: ${{b.matches}} | Win: <strong>${{b.payout.toFixed(2)}} ETB</strong></div>`).join("")
        : "ምንም ታሪክ የለም።";
      document.getElementById("global-results").innerHTML = globalLogs.length
        ? globalLogs.slice().reverse().map(g => `<div style="padding:6px 0;border-bottom:1px solid #2a2f3a;">User ${{g.user_id}} | Matches: ${{g.matches}} | Win: ${{g.payout.toFixed(2)}} ETB<br/><span style="font-size:11px;color:#9ca3af;">Drawn: ${{g.drawn.join(", ")}}</span></div>`).join("")
        : "ገና ውጤት አልተመዘገበም።";
    }}

    function switchTab(tab) {{
      ["game", "wallet", "history", "results"].forEach(t => {{
        document.getElementById("panel-" + t).classList.toggle("active", t === tab);
        document.getElementById("nav-" + t).classList.toggle("active", t === tab);
      }});
    }}

    let sec = 30;
    setInterval(() => {{
      sec = sec <= 1 ? 30 : sec - 1;
      document.getElementById("timer").textContent = `00:${{String(sec).padStart(2, "0")}}`;
    }}, 1000);

    updatePayoutUI();
    loadState();
  </script>
</body>
</html>
"""


@app.route("/")
def home():
    return render_template_string(FAST_KENO_HTML)


@app.route("/api/state")
def api_state():
    uid = request.args.get("user_id", "895515150")
    u = get_user(uid)
    return jsonify({
        "balance": u["balance"],
        "my_bets": u["my_bets"],
        "global_logs": HISTORY_LOGS[-20:]
    })


@app.route("/api/play", methods=["POST"])
def api_play():
    data = request.get_json(force=True)
    uid = str(data.get("user_id", "895515150")).strip()
    picks = data.get("picks", [])
    try:
        bet = float(data.get("bet", 0))
    except (TypeError, ValueError):
        bet = 0.0

    if not isinstance(picks, list) or len(picks) < 1 or len(picks) > 10:
        return jsonify({"ok": False, "message": "ከ 1 እስከ 10 ቁጥሮች መምረጥ አለብህ።"})
    if bet < 10:
        return jsonify({"ok": False, "message": "ዝቅተኛ መደብ 10 ETB ነው።"})

    u = get_user(uid)
    if bet > u["balance"]:
        return jsonify({"ok": False, "message": "በቂ ባላንስ የለህም። እባክህ በመጀመሪያ Deposit አድርግ።"})

    u["balance"] -= bet
    drawn = sorted(random.sample(range(1, 81), 20))
    drawn_set = set(drawn)
    hits = sorted([int(x) for x in picks if int(x) in drawn_set])
    matches = len(hits)

    mult = PAYTABLE.get(len(picks), {}).get(matches, 0.0)
    payout = round(bet * mult, 2)
    u["balance"] = round(u["balance"] + payout, 2)

    record = {
        "user_id": uid,
        "bet": bet,
        "picks": sorted([int(x) for x in picks]),
        "drawn": drawn,
        "hits": hits,
        "matches": matches,
        "payout": payout
    }
    u["my_bets"].append(record)
    HISTORY_LOGS.append(record)

    return jsonify({
        "ok": True,
        "balance": u["balance"],
        "drawn": drawn,
        "hits": hits,
        "matches": matches,
        "payout": payout,
        "my_bets": u["my_bets"],
        "global_logs": HISTORY_LOGS[-20:]
    })


@app.route("/api/deposit", methods=["POST"])
def api_deposit():
    data = request.get_json(force=True)
    uid = str(data.get("user_id", "895515150")).strip()
    method = str(data.get("method", "")).strip()
    tx_code = str(data.get("tx_code", "")).strip().upper()
    try:
        amount = float(data.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0.0

    if amount < 10:
        return jsonify({"ok": False, "message": "ዝቅተኛ ገቢ 10 ETB ነው።"})
    if not tx_code or len(tx_code) < 5:
        return jsonify({"ok": False, "message": "ትክክለኛ የ FT / Transaction ኮድ ያስፈልጋል።"})
    if tx_code in USED_TX_CODES:
        return jsonify({"ok": False, "message": "ይህ ኮድ ቀድሞ ጥቅም ላይ ውሏል (ተደጋግሟል)።"})

    USED_TX_CODES.add(tx_code)
    u = get_user(uid)
    u["balance"] = round(u["balance"] + amount, 2)

    return jsonify({
        "ok": True,
        "balance": u["balance"],
        "message": f"✅ በ {method} ({tx_code}) {amount:.2f} ETB ተረጋግጦ ወደ ባላንስህ ተጨምሯል።"
    })


@app.route("/api/withdraw", methods=["POST"])
def api_withdraw():
    data = request.get_json(force=True)
    uid = str(data.get("user_id", "895515150")).strip()
    method = str(data.get("method", "")).strip()
    destination = str(data.get("destination", "")).strip()
    try:
        amount = float(data.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0.0

    u = get_user(uid)
    if amount < 10:
        return jsonify({"ok": False, "message": "ዝቅተኛ ወጪ 10 ETB ነው።"})
    if amount > u["balance"]:
        return jsonify({"ok": False, "message": "በቂ ባላንስ የለህም።"})
    if not destination:
        return jsonify({"ok": False, "message": "የቴሌብር ስልክ ወይም የCBE አካውንት አስገባ።"})

    u["balance"] = round(u["balance"] - amount, 2)
    u["withdrawals"].append({
        "user_id": uid,
        "method": method,
        "amount": amount,
        "destination": destination,
        "admin": ADMIN_USERNAME,
        "status": "pending_admin_approval"
    })

    return jsonify({
        "ok": True,
        "balance": u["balance"],
        "message": f"📤 የ {amount:.2f} ETB የወጪ ጥያቄ ወደ አድሚኑ (@{ADMIN_USERNAME}) ተልኳል።"
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
