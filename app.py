import os
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

BOT_USERNAME = "ethio_keno_play_26_bot"

# እነዚህን በራስህ ትክክለኛ መረጃዎች ቀይር (ወይም በ Render Environment Variables አስቀምጥ)
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "your_admin_username")  # ያለ @ ጻፍ፣ ለምሳሌ: enyachew_19
TELEBIRR_ACCOUNT = os.environ.get("TELEBIRR_ACCOUNT", "09XXXXXXXX (ስምህ)")
CBE_ACCOUNT = os.environ.get("CBE_ACCOUNT", "1000XXXXXXXXX (ስምህ)")

# ለሙከራ / ለመጀመሪያ ደረጃ በማህደረ ትውስታ የሚያዝ ቀላል መረጃ (በቀጣይ ወደ Database እናሳድገዋለን)
USERS = {}          # user_id -> {"balance": float, "withdrawals": list}
USED_TX_CODES = set()  # ቀድሞ የተጠቀሙ የ FT / Transaction ኮዶችን ለመከላከል


def get_user(user_id: str):
    if user_id not in USERS:
        USERS[user_id] = {"balance": 0.0, "withdrawals": []}
    return USERS[user_id]


MINI_APP_HTML = f"""
<!DOCTYPE html>
<html lang="am">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Ethio Keno Mini App</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    body {{
      font-family: Arial, sans-serif;
      background: #0f172a;
      color: #f8fafc;
      margin: 0;
      padding: 14px;
    }}
    .card {{
      background: #1e293b;
      border-radius: 12px;
      padding: 14px;
      margin-bottom: 12px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(8, 1fr);
      gap: 6px;
      margin-top: 10px;
    }}
    .num-btn {{
      padding: 10px 0;
      border: none;
      border-radius: 8px;
      background: #334155;
      color: #fff;
      font-weight: bold;
      cursor: pointer;
    }}
    .num-btn.selected {{
      background: #16a34a;
    }}
    .bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 10px;
      gap: 8px;
      flex-wrap: wrap;
    }}
    input, select {{
      width: 100%;
      box-sizing: border-box;
      padding: 9px;
      margin-top: 6px;
      margin-bottom: 10px;
      border-radius: 8px;
      border: 1px solid #475569;
      background: #0f172a;
      color: #fff;
    }}
    button.primary {{
      background: #2563eb;
      color: #fff;
      border: none;
      padding: 10px 14px;
      border-radius: 8px;
      font-weight: bold;
      cursor: pointer;
    }}
    button.green {{
      background: #16a34a;
      color: #fff;
      border: none;
      padding: 10px 14px;
      border-radius: 8px;
      font-weight: bold;
      cursor: pointer;
      width: 100%;
    }}
    button.amber {{
      background: #d97706;
      color: #fff;
      border: none;
      padding: 10px 14px;
      border-radius: 8px;
      font-weight: bold;
      cursor: pointer;
      width: 100%;
    }}
    .msg {{
      margin-top: 8px;
      font-size: 14px;
      color: #93c5fd;
    }}
    .small {{
      font-size: 13px;
      color: #cbd5e1;
      line-height: 1.45;
    }}
  </style>
</head>
<body>
  <div class="card">
    <h2>🎲 Ethio Keno (1 - 80)</h2>
    <div class="small">ከ 1 እስከ 10 ቁጥሮች ምረጥ | ዝቅተኛ መደብ: 10 ብር | 20 Draw ቁጥሮች</div>
    <div style="margin-top: 8px;">ባላንስ: <strong id="balance">0.00</strong> ብር</div>
  </div>

  <div class="card">
    <div>የተመረጡ ቁጥሮች: <span id="picked-count">0</span> / 10</div>
    <div class="grid" id="grid"></div>
    <div class="bar">
      <button class="primary" onclick="clearPicks()">አጽዳ</button>
      <button class="primary" onclick="drawKeno()">20 ቁጥር አውጣ (Test Draw)</button>
    </div>
    <div id="result" class="msg"></div>
  </div>

  <div class="card">
    <h3>💳 ገቢ ማድረግ (Deposit - ራስ-ሰር ማጣሪያ)</h3>
    <div class="small">
      <strong>Telebirr:</strong> {TELEBIRR_ACCOUNT}<br/>
      <strong>CBE:</strong> {CBE_ACCOUNT}<br/>
      <em>ማሳሰቢያ፡ ገቢ ጥያቄ ወደ አድሚኑ አይሄድም፤ ትክክለኛ የ FT / Transaction ኮድ ሲያስገቡ ባላንስ ይጨምራል።</em>
    </div>
    <label>የክፍያ መንገድ</label>
    <select id="dep-method">
      <option value="Telebirr">Telebirr</option>
      <option value="CBE">Commercial Bank of Ethiopia (CBE)</option>
    </select>
    <label>የገባው የብር መጠን (ቢያንስ 10 ብር)</label>
    <input type="number" id="dep-amount" placeholder="ለምሳሌ 50" min="10" />
    <label>Transaction ID / FT ኮድ</label>
    <input type="text" id="dep-tx" placeholder="ለምሳሌ FT26328XXXX" />
    <button class="green" onclick="submitDeposit()">ገቢ አረጋግጥና ወደ ባላንስ አስገባ</button>
    <div id="dep-msg" class="msg"></div>
  </div>

  <div class="card">
    <h3>💸 ወጪ ማድረግ (Withdraw - ወደ አድሚን ይላካል)</h3>
    <div class="small">የወጪ ጥያቄ ለአድሚኑ (<strong>@{ADMIN_USERNAME}</strong>) ይደርሳል እና በአድሚኑ ይጸድቃል።</div>
    <label>የመቀበያ መንገድ</label>
    <select id="wd-method">
      <option value="Telebirr">Telebirr</option>
      <option value="CBE">CBE</option>
    </select>
    <label>የሚወጣው የብር መጠን</label>
    <input type="number" id="wd-amount" placeholder="ለምሳሌ 100" min="10" />
    <label>የቴሌብር ስልክ ቁጥር ወይም የCBE አካውንት</label>
    <input type="text" id="wd-dest" placeholder="09... ወይም 1000..." />
    <button class="amber" onclick="submitWithdraw()">የወጪ ጥያቄ ወደ አድሚን ላክ</button>
    <div id="wd-msg" class="msg"></div>
  </div>

  <script>
    const tg = window.Telegram.WebApp;
    tg.expand();

    const tgUser = tg.initDataUnsafe && tg.initDataUnsafe.user ? tg.initDataUnsafe.user : null;
    const userId = tgUser ? String(tgUser.id) : "guest_demo_user";

    const selected = new Set();
    const gridEl = document.getElementById("grid");

    for (let i = 1; i <= 80; i++) {{
      const btn = document.createElement("button");
      btn.className = "num-btn";
      btn.textContent = i;
      btn.onclick = () => {{
        if (selected.has(i)) {{
          selected.delete(i);
          btn.classList.remove("selected");
        }} else {{
          if (selected.size >= 10) {{
            alert("በአንድ ዙር ከ 10 ቁጥር በላይ መምረጥ አይቻልም!");
            return;
          }}
          selected.add(i);
          btn.classList.add("selected");
        }}
        document.getElementById("picked-count").textContent = selected.size;
      }};
      gridEl.appendChild(btn);
    }}

    function setBalanceUI(val) {{
      document.getElementById("balance").textContent = Number(val).toFixed(2);
    }}

    async function loadUser() {{
      const res = await fetch(`/api/user?user_id=${{encodeURIComponent(userId)}}`);
      const data = await res.json();
      setBalanceUI(data.balance);
    }}

    function clearPicks() {{
      selected.clear();
      document.querySelectorAll(".num-btn").forEach(b => b.classList.remove("selected"));
      document.getElementById("picked-count").textContent = 0;
      document.getElementById("result").textContent = "";
    }}

    function drawKeno() {{
      if (selected.size < 1) {{
        alert("ቢያንስ 1 ቁጥር ምረጥ!");
        return;
      }}
      const pool = Array.from({{ length: 80 }}, (_, idx) => idx + 1);
      for (let i = pool.length - 1; i > 0; i--) {{
        const j = Math.floor(Math.random() * (i + 1));
        [pool[i], pool[j]] = [pool[j], pool[i]];
      }}
      const drawn = pool.slice(0, 20).sort((a, b) => a - b);
      const hits = Array.from(selected).filter(n => drawn.includes(n));
      document.getElementById("result").innerHTML =
        `<div><strong>የወጡ 20 ቁጥሮች:</strong> ${{drawn.join(", ")}}</div>` +
        `<div style="margin-top:4px;"><strong>የተገጣጠሙ (${{hits.length}}):</strong> ${{hits.join(", ") || "ምንም"}}</div>`;
    }}

    async function submitDeposit() {{
      const method = document.getElementById("dep-method").value;
      const amount = parseFloat(document.getElementById("dep-amount").value);
      const txCode = document.getElementById("dep-tx").value.trim();
      const msgEl = document.getElementById("dep-msg");

      if (!amount || amount < 10) {{
        msgEl.textContent = "እባክህ ቢያንስ 10 ብር አስገባ።";
        return;
      }}
      if (!txCode || txCode.length < 5) {{
        msgEl.textContent = "እባክህ ትክክለኛ የ Transaction / FT ኮድ አስገባ።";
        return;
      }}

      const res = await fetch("/api/deposit", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ user_id: userId, method, amount, tx_code: txCode }})
      }});
      const data = await res.json();
      msgEl.textContent = data.message;
      if (data.ok) {{
        setBalanceUI(data.balance);
        document.getElementById("dep-tx").value = "";
      }}
    }}

    async function submitWithdraw() {{
      const method = document.getElementById("wd-method").value;
      const amount = parseFloat(document.getElementById("wd-amount").value);
      const destination = document.getElementById("wd-dest").value.trim();
      const msgEl = document.getElementById("wd-msg");

      if (!amount || amount < 10) {{
        msgEl.textContent = "እባክህ የሚወጣውን የብር መጠን (ቢያንስ 10 ብር) አስገባ።";
        return;
      }}
      if (!destination) {{
        msgEl.textContent = "እባክህ የቴሌብር ቁጥር ወይም የCBE አካውንት አስገባ።";
        return;
      }}

      const res = await fetch("/api/withdraw", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ user_id: userId, method, amount, destination }})
      }});
      const data = await res.json();
      msgEl.textContent = data.message;
      if (data.ok) {{
        setBalanceUI(data.balance);
        document.getElementById("wd-dest").value = "";
      }}
    }}

    loadUser();
  </script>
</body>
</html>
"""


@app.route("/")
def home():
    return render_template_string(MINI_APP_HTML)


@app.route("/api/user")
def api_user():
    user_id = request.args.get("user_id", "guest_demo_user")
    user = get_user(user_id)
    return jsonify({"balance": user["balance"], "admin_username": ADMIN_USERNAME})


@app.route("/api/deposit", methods=["POST"])
def api_deposit():
    data = request.get_json(force=True)
    user_id = str(data.get("user_id", "guest_demo_user")).strip()
    method = str(data.get("method", "")).strip()
    tx_code = str(data.get("tx_code", "")).strip().upper()

    try:
        amount = float(data.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0.0

    if amount < 10:
        return jsonify({"ok": False, "message": "ዝቅተኛ ገቢ 10 ብር ነው።"})

    if not tx_code or len(tx_code) < 5:
        return jsonify({"ok": False, "message": "ትክክለኛ የ FT / Transaction ኮድ ያስፈልጋል።"})

    # ኮዱ ቀድሞ ጥቅም ላይ መዋሉን ማጣራት
    if tx_code in USED_TX_CODES:
        return jsonify({"ok": False, "message": "ይህ Transaction / FT ኮድ ቀድሞ ጥቅም ላይ ውሏል (ተደጋግሟል)።"})

    USED_TX_CODES.add(tx_code)
    user = get_user(user_id)
    user["balance"] += amount

    return jsonify({
        "ok": True,
        "balance": user["balance"],
        "message": f"✅ በ {method} ({tx_code}) {amount:.2f} ብር ተረጋግጦ ወደ ባላንስህ ተጨምሯል።"
    })


@app.route("/api/withdraw", methods=["POST"])
def api_withdraw():
    data = request.get_json(force=True)
    user_id = str(data.get("user_id", "guest_demo_user")).strip()
    method = str(data.get("method", "")).strip()
    destination = str(data.get("destination", "")).strip()

    try:
        amount = float(data.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0.0

    user = get_user(user_id)
    if amount < 10:
        return jsonify({"ok": False, "message": "ዝቅተኛ ወጪ 10 ብር ነው።"})
    if amount > user["balance"]:
        return jsonify({"ok": False, "message": "በቂ ባላንስ የለህም።"})
    if not destination:
        return jsonify({"ok": False, "message": "እባክህ የመቀበያ ስልክ ወይም አካውንት አስገባ።"})

    user["balance"] -= amount
    req_item = {
        "user_id": user_id,
        "method": method,
        "amount": amount,
        "destination": destination,
        "admin": ADMIN_USERNAME,
        "status": "pending_admin_approval"
    }
    user["withdrawals"].append(req_item)

    return jsonify({
        "ok": True,
        "balance": user["balance"],
        "message": f"📤 የ {amount:.2f} ብር የወጪ ጥያቄ ወደ አድሚኑ (@{ADMIN_USERNAME}) ተልኳል፤ ሲጸድቅ በ {method} ({destination}) ይላክልሃል።"
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
