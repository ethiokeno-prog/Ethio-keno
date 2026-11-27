# -*- coding: utf-8 -*-
import base64
import hashlib
import json
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
    os.environ.get("TELEBIRR_ACCOUNT") or "0944123180"
).strip()
TELEBIRR_NAME = (
    os.environ.get("TELEBIRR_NAME") or "Enyachew Amerga"
).strip()
CBE_ACCOUNT = (
    os.environ.get("CBE_ACCOUNT") or "1000682528641"
).strip()
CBE_NAME = (
    os.environ.get("CBE_NAME") or "Enyachew Amerga"
).strip()


def split_account_and_name(raw_val, default_name):
  val = (raw_val or "").strip()
  if " - " in val:
    num_part, name_part = val.split(" - ", 1)
    return num_part.strip(), (name_part.strip() or default_name)
  return val, default_name
WEBAPP_URL = (os.environ.get("WEBAPP_URL") or "https://ethio-keno-exlm.onrender.com").strip().rstrip("/")

EAT = timezone(timedelta(hours=3))
STATE_FILE = os.environ.get("STATE_FILE") or "/tmp/ethio_keno_state.json"
USERS, USED_TX, WITHDRAWALS = {}, set(), {}
CLAIMED_BONUS_USERS = set()
REFERRED_USERS = {}
LIVE_TICKETS = []


def load_persistent_state():
  global USERS, USED_TX, WITHDRAWALS, CLAIMED_BONUS_USERS, REFERRED_USERS
  try:
    if os.path.exists(STATE_FILE):
      with open(STATE_FILE, "r", encoding="utf-8") as fh:
        data = json.load(fh)
      if isinstance(data.get("users"), dict):
        USERS.update(data["users"])
      if isinstance(data.get("used_tx"), list):
        USED_TX.update(str(x) for x in data["used_tx"])
      if isinstance(data.get("withdrawals"), dict):
        WITHDRAWALS.update(data["withdrawals"])
      if isinstance(data.get("claimed_bonus_users"), list):
        CLAIMED_BONUS_USERS.update(str(x) for x in data["claimed_bonus_users"])
      if isinstance(data.get("referred_users"), dict):
        REFERRED_USERS.update(data["referred_users"])
      global HOUSE_TOTAL_STAKE, HOUSE_TOTAL_PAID
      HOUSE_TOTAL_STAKE = float(data.get("house_total_stake", 0.0) or 0.0)
      HOUSE_TOTAL_PAID = float(data.get("house_total_paid", 0.0) or 0.0)
  except Exception:
    pass


def save_persistent_state():
  try:
    tmp_path = STATE_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
      json.dump({
          "users": USERS,
          "used_tx": list(USED_TX),
          "withdrawals": WITHDRAWALS,
          "claimed_bonus_users": list(CLAIMED_BONUS_USERS),
          "referred_users": REFERRED_USERS,
          "house_total_stake": HOUSE_TOTAL_STAKE,
          "house_total_paid": HOUSE_TOTAL_PAID,
      }, fh, ensure_ascii=False)
    os.replace(tmp_path, STATE_FILE)
  except Exception:
    pass


load_persistent_state()

PAYTABLE = {
    1: {1: 3.5},
    2: {2: 10},
    3: {2: 1.5, 3: 30},
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


ROUND_DURATION_SEC = 60
DRAW_STEP_SEC = 2
DRAW_COUNT = 20
RESULT_HOLD_SEC = 5
DRAW_PHASE_SEC = DRAW_COUNT * DRAW_STEP_SEC + RESULT_HOLD_SEC  # 45s after 01:00 hits 00:00
CYCLE_TOTAL_SEC = ROUND_DURATION_SEC + DRAW_PHASE_SEC  # 105s full cycle: 60s betting + 45s draw & result

ROUND_BETS = {}  # round_num -> list of dicts
SETTLED_ROUNDS = set()
DRAWN_CACHE = {}  # round_num -> list of 20 ints


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
        "invalid_shots": 0,
    }
  return USERS[uid]


def current_cycle_state(now_ts=None):
  if now_ts is None:
    now_ts = time.time()
  cycle_num = int(now_ts // CYCLE_TOTAL_SEC)
  pos_in_cycle = now_ts % CYCLE_TOTAL_SEC
  if pos_in_cycle < ROUND_DURATION_SEC:
    phase = "betting"
    bet_sec_left = max(1, int(ROUND_DURATION_SEC - int(pos_in_cycle)))
    draw_elapsed_sec = 0.0
  else:
    phase = "drawing"
    bet_sec_left = 0
    draw_elapsed_sec = pos_in_cycle - ROUND_DURATION_SEC
  return {
      "server_now": now_ts,
      "cycle_num": cycle_num,
      "pos_in_cycle": pos_in_cycle,
      "phase": phase,
      "bet_sec_left": bet_sec_left,
      "draw_elapsed_sec": draw_elapsed_sec,
      "cycle_total_sec": CYCLE_TOTAL_SEC,
      "round_duration_sec": ROUND_DURATION_SEC,
      "draw_step_sec": DRAW_STEP_SEC,
      "draw_count": DRAW_COUNT,
      "result_hold_sec": RESULT_HOLD_SEC,
  }


def _score_drawn_for_entries(drawn_list, entries):
  d_set = set(drawn_list)
  total_bet = 0.0
  total_payout = 0.0
  max_hit_ratio = 0.0
  all_full_hit = bool(entries)
  for e in entries:
    picks = e["picks"]
    b_amt = float(e["bet"])
    total_bet += b_amt
    h_cnt = sum(1 for x in picks if x in d_set)
    ratio = (h_cnt / len(picks)) if picks else 0.0
    if ratio > max_hit_ratio:
      max_hit_ratio = ratio
    if h_cnt < len(picks):
      all_full_hit = False
    mult = PAYTABLE.get(len(picks), {}).get(h_cnt, 0.0)
    total_payout += round(b_amt * mult, 2)
  return total_bet, total_payout, max_hit_ratio, all_full_hit


HOUSE_TOTAL_STAKE = 0.0
HOUSE_TOTAL_PAID = 0.0


def get_round_drawn(cycle_num):
  global HOUSE_TOTAL_STAKE, HOUSE_TOTAL_PAID
  c_key = int(cycle_num)
  if c_key not in DRAWN_CACHE:
    entries = ROUND_BETS.get(c_key) or []
    rng = random.Random(f"ethio-keno-cycle-{c_key}-{len(entries)}")
    best_drawn = rng.sample(range(1, 81), DRAW_COUNT)
    if entries:
      # 70% House Profit / 30% Player Return (RTP = 0.30) engine:
      # Tracks cumulative stake vs payouts so ~70% stays with the house while ~30% goes back
      # to players via small/medium wins and partial teaser hits so customers stay engaged.
      round_stake = sum(float(e["bet"]) for e in entries)
      projected_total_stake = HOUSE_TOTAL_STAKE + round_stake
      target_paid_budget = projected_total_stake * 0.30
      remaining_rtp_budget = max(0.0, target_paid_budget - HOUSE_TOTAL_PAID)
      # Allow occasional small/medium wins within the 30% player return budget, plus partial hits (e.g. 1-2 matches)
      allow_win_round = (remaining_rtp_budget >= round_stake * 0.25) and (c_key % 3 != 0)
      best_score = None
      for attempt in range(70):
        cand = rng.sample(range(1, 81), DRAW_COUNT)
        t_bet, t_pay, max_ratio, all_full = _score_drawn_for_entries(cand, entries)
        if all_full and t_pay > remaining_rtp_budget:
          penalty = 200000.0 + t_pay
        elif t_pay > max(remaining_rtp_budget, round_stake * 0.30 if allow_win_round else 0.0):
          penalty = 10000.0 + (t_pay - remaining_rtp_budget) * 20.0
        else:
          if allow_win_round and 0.0 < t_pay <= remaining_rtp_budget:
            # Give a real payout within the 30% player pool so players win & don't lose hope
            penalty = abs(t_pay - min(remaining_rtp_budget, round_stake * 0.85))
          else:
            # Non-payout round: mix 0-match rounds with 1-2 partial teaser matches (where payout is 0)
            want_teaser = (c_key % 2 == 1)
            if want_teaser and 0.0 < max_ratio <= 0.45 and t_pay == 0.0:
              penalty = -2.0
            else:
              penalty = t_pay * 15.0 + max_ratio * 2.0
        if best_score is None or penalty < best_score:
          best_score = penalty
          best_drawn = cand
      _, chosen_pay, _, _ = _score_drawn_for_entries(best_drawn, entries)
      HOUSE_TOTAL_STAKE = round(HOUSE_TOTAL_STAKE + round_stake, 2)
      HOUSE_TOTAL_PAID = round(HOUSE_TOTAL_PAID + chosen_pay, 2)
    DRAWN_CACHE[c_key] = best_drawn
  return list(DRAWN_CACHE[c_key])


def settle_cycle_if_needed(cycle_num):
  c_key = int(cycle_num)
  drawn = get_round_drawn(c_key)
  drawn_set = set(drawn)
  entries = ROUND_BETS.get(c_key) or []
  if c_key not in SETTLED_ROUNDS:
    SETTLED_ROUNDS.add(c_key)
    for entry in entries:
      picks = entry["picks"]
      bet_amt = float(entry["bet"])
      hits = sorted([x for x in picks if x in drawn_set])
      payout = round(bet_amt * PAYTABLE.get(len(picks), {}).get(len(hits), 0.0), 2)
      entry["hits"] = hits
      entry["matches"] = len(hits)
      entry["payout"] = payout
      entry["settled"] = True
      u = get_u(entry["uid"])
      if payout > 0:
        u["balance"] = round(u["balance"] + payout, 2)
      u["bets"].append({
          "cycle": c_key,
          "bet": bet_amt,
          "matches": len(hits),
          "payout": payout,
      })
    save_persistent_state()
  return drawn, entries


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



def extract_tx_code(method, raw_text):
  txt = (raw_text or "").strip().upper()
  if not txt:
    return ""
  # Look for CBE FT codes first (e.g. FT26328XXXX)
  m_ft = re.search(r"\bFT[A-Z0-9]{6,18}\b", txt)
  if m_ft:
    return m_ft.group(0)
  # Look for common alphanumeric transaction IDs (e.g. CE535PPHGP or Telebirr ref)
  if method == "CBE":
    return ""
  tokens = re.findall(r"\b[A-Z0-9]{6,20}\b", txt)
  for tok in tokens:
    if any(ch.isalpha() for ch in tok) and any(ch.isdigit() for ch in tok):
      return tok
  if tokens and re.fullmatch(r"[A-Z0-9]{6,20}", txt):
    return txt
  return ""

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
      ok = tg_photo(t_str, photo_bytes, caption=text or "📢 Announcement")
    elif text:
      ok = tg(t_str, "📢 Announcement:\n\n" + text)
    if ok:
      sent_count += 1
  return sent_count


PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
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
<div class="top"><strong style="color:#4ade80">⚡ ETHIO FAST KENO</strong><div class="pill">Balance: <span id="bal">0.00</span> ETB</div></div>
<div class="sub"><div>Picks: <strong id="cnt">0</strong>/10 | ID: <strong id="uid-lbl">-</strong></div><div class="tm" id="tm">01:00</div></div>

<div id="p-game" class="panel active">
  <div class="stage">
    <div style="font-size:11px;color:#9ca3af;margin-bottom:6px">Drawn Numbers: <strong id="dprog">0 / 20</strong> | Max Win: <strong id="mwin" style="color:#4ade80">0.00 ETB</strong></div>
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
      <button class="btn" onclick="setBetVal(2)">2 ETB</button>
      <button class="btn" onclick="setBetVal(4)">4 ETB</button>
      <button class="btn" onclick="setBetVal(6)">6 ETB</button>
      <button class="btn" onclick="setBetVal(10)">10 ETB</button>
    </div>
    <button class="betbtn" id="betbtn" onclick="lockBet()">PLACE BET</button>
  </div>
  <div class="box" id="gmsg">Betting window is 1 minute. Pick 1 to 10 numbers and a stake (min 2 ETB), then tap Place Bet. When 01:00 ends, 20 numbers are drawn.</div>
  <div class="box">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <strong>🎟️ Active Tickets</strong>
      <span id="tcount" style="color:#4ade80;font-weight:800">0</span>
    </div>
    <div id="tickets-list"><div style="color:#9ca3af;margin-top:6px">No tickets placed in this round yet.</div></div>
  </div>
</div>

<div id="insuf-modal" class="modal-bg" onclick="closeInsuf()">
  <div class="modal-box" onclick="event.stopPropagation()">
    <div class="modal-top">
      <span style="color:#f87171;font-weight:900;font-size:14px">Insufficient Balance</span>
      <button class="modal-x" onclick="closeInsuf()">✕</button>
    </div>
    <div style="font-size:12px;color:#d1d5db;margin-bottom:10px">Your balance is too low. Please deposit funds or lower your bet amount.</div>
    <button class="act" onclick="closeInsuf();tab('wallet')">Go to Wallet</button>
  </div>
</div>

<div id="p-wallet" class="panel">
  <div class="box">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <strong style="font-size:16px">💳 Deposit</strong>
      <span style="background:#1e293b;color:#fbbf24;padding:3px 9px;border-radius:99px;font-size:11px;font-weight:800">● Awaiting payment</span>
    </div>
    <div style="font-size:11px;color:#9ca3af;margin-top:4px">Recharge and enjoy your favorite games</div>
    <div id="dep-step1">
      <select id="dm"><option value="Telebirr">Telebirr</option><option value="CBE">CBE</option></select>
      <input type="number" id="da" placeholder="Enter amount (min 10 ETB)" min="10" step="any">
      <button id="dep-cont-btn" class="act" style="background:#2563eb;margin-top:2px" onclick="showDepositStep2()">Continue</button>
    </div>
    <div id="dep-step2" style="display:none;margin-top:8px">
      <div style="background:#0f131a;border:1px solid #262e3d;border-radius:10px;padding:10px;margin-bottom:8px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
          <div><b id="dep-sum-amt" style="font-size:16px;color:#fff">0 ETB</b> <span id="dep-sum-meta" style="font-size:11px;color:#9ca3af"></span></div>
          <span style="background:#2a220c;color:#fbbf24;padding:3px 8px;border-radius:99px;font-size:10px;font-weight:800">● Awaiting payment</span>
        </div>
        <div style="font-size:12px;font-weight:700;color:#e5e7eb;margin-bottom:6px">1) Send <span id="dep-send-amt">0</span> ETB to this <span id="dep-send-method">Telebirr</span> account</div>
        <div id="dep-tb-card" class="acct-card">
          <div>
            <div style="font-size:10px;color:#9ca3af;font-weight:700">RECEIVER ACCOUNT (TELEBIRR)</div>
            <div id="acc-tb" style="font-size:15px;font-weight:900;color:#fff;letter-spacing:0.3px;margin-top:2px">__TELEBIRR__</div>
            <div style="font-size:11px;color:#9ca3af;margin-top:2px">Name: <b style="color:#e5e7eb">__TELEBIRR_NAME__</b></div>
          </div>
          <button class="copy-btn" onclick="copyById('acc-tb', this)">Copy</button>
        </div>
        <div id="dep-cbe-card" class="acct-card">
          <div>
            <div style="font-size:10px;color:#9ca3af;font-weight:700">RECEIVER ACCOUNT (CBE)</div>
            <div id="acc-cbe" style="font-size:15px;font-weight:900;color:#fff;letter-spacing:0.3px;margin-top:2px">__CBE__</div>
            <div style="font-size:11px;color:#9ca3af;margin-top:2px">Name: <b style="color:#e5e7eb">__CBE_NAME__</b></div>
          </div>
          <button class="copy-btn" onclick="copyById('acc-cbe', this)">Copy</button>
        </div>
      </div>
      <div style="background:#0f131a;border:1px solid #262e3d;border-radius:10px;padding:10px;margin-bottom:8px">
        <div style="font-size:12px;font-weight:700;color:#e5e7eb">2) Paste the confirmation SMS</div>
        <div style="font-size:11px;color:#9ca3af;margin-top:2px">Copy the SMS you received after paying and paste it below.</div>
        <div style="font-size:10px;color:#64748b;margin-top:2px">Example Transaction ID: FT26328XXXX / CE535PPHGP</div>
        <textarea id="dt" rows="3" placeholder="Paste confirmation SMS or Transaction ID here..." style="width:100%;padding:9px;margin:7px 0 4px;border-radius:8px;border:1px solid #374151;background:#111317;color:#fff;font-family:inherit;resize:vertical"></textarea>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
        <button type="button" class="act" style="background:#232934;border:1px solid #374151" onclick="cancelDepositStep2()">Cancel</button>
        <button type="button" id="dep-confirm-btn" class="act" onclick="dep()">✓ Confirm</button>
      </div>
    </div>
    <div id="dmsg" style="margin-top:8px;color:#93c5fd"></div>
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

<div id="p-hist" class="panel"><div class="box"><strong>📜 Bet History</strong><div id="hlist">No bet history yet.</div></div></div>

<div id="p-rules" class="panel">
  <div class="box">
    <strong>📜 Game Rules & Payout Table</strong>
    <p style="margin:6px 0">Payouts follow the multiplier table below. Pick 1 to 10 numbers; your stake is multiplied based on how many of your picks match the 20 drawn numbers (for example, picking 3 numbers and matching 2 pays 1.5x, and <b>matching all 3 pays 30x</b>).</p>
    <div style="overflow-x:auto;margin-top:8px">
      <table style="width:100%;border-collapse:collapse;font-size:11px;text-align:center">
        <thead>
          <tr style="background:#1f242d;color:#4ade80">
            <th style="padding:5px;border:1px solid #2b303b">Picks</th>
            <th style="padding:5px;border:1px solid #2b303b">1</th>
            <th style="padding:5px;border:1px solid #2b303b">2</th>
            <th style="padding:5px;border:1px solid #2b303b">3</th>
            <th style="padding:5px;border:1px solid #2b303b">4</th>
            <th style="padding:5px;border:1px solid #2b303b">5</th>
            <th style="padding:5px;border:1px solid #2b303b">6</th>
            <th style="padding:5px;border:1px solid #2b303b">7</th>
            <th style="padding:5px;border:1px solid #2b303b">8</th>
            <th style="padding:5px;border:1px solid #2b303b">9</th>
            <th style="padding:5px;border:1px solid #2b303b">10</th>
          </tr>
        </thead>
        <tbody>
          <tr><td style="padding:4px;border:1px solid #2b303b"><b>1</b></td><td style="border:1px solid #2b303b">3.5</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
          <tr><td style="padding:4px;border:1px solid #2b303b"><b>2</b></td><td>-</td><td style="border:1px solid #2b303b">10</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
          <tr><td style="padding:4px;border:1px solid #2b303b"><b>3</b></td><td>-</td><td style="border:1px solid #2b303b">1.5</td><td style="border:1px solid #2b303b;color:#4ade80;font-weight:800">30</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
          <tr><td style="padding:4px;border:1px solid #2b303b"><b>4</b></td><td>-</td><td style="border:1px solid #2b303b">1</td><td style="border:1px solid #2b303b">10</td><td style="border:1px solid #2b303b">80</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
          <tr><td style="padding:4px;border:1px solid #2b303b"><b>5</b></td><td>-</td><td>-</td><td style="border:1px solid #2b303b">2</td><td style="border:1px solid #2b303b">15</td><td style="border:1px solid #2b303b">150</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
          <tr><td style="padding:4px;border:1px solid #2b303b"><b>6</b></td><td>-</td><td>-</td><td style="border:1px solid #2b303b">1.5</td><td style="border:1px solid #2b303b">4</td><td style="border:1px solid #2b303b">60</td><td style="border:1px solid #2b303b">500</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
          <tr><td style="padding:4px;border:1px solid #2b303b"><b>7</b></td><td>-</td><td>-</td><td style="border:1px solid #2b303b">1</td><td style="border:1px solid #2b303b">3</td><td style="border:1px solid #2b303b">15</td><td style="border:1px solid #2b303b">80</td><td style="border:1px solid #2b303b">1000</td><td>-</td><td>-</td><td>-</td></tr>
          <tr><td style="padding:4px;border:1px solid #2b303b"><b>8</b></td><td>-</td><td>-</td><td>-</td><td style="border:1px solid #2b303b">2</td><td style="border:1px solid #2b303b">10</td><td style="border:1px solid #2b303b">25</td><td style="border:1px solid #2b303b">200</td><td style="border:1px solid #2b303b">2000</td><td>-</td><td>-</td></tr>
          <tr><td style="padding:4px;border:1px solid #2b303b"><b>9</b></td><td>-</td><td>-</td><td>-</td><td style="border:1px solid #2b303b">2</td><td style="border:1px solid #2b303b">5</td><td style="border:1px solid #2b303b">15</td><td style="border:1px solid #2b303b">125</td><td style="border:1px solid #2b303b">800</td><td style="border:1px solid #2b303b">5000</td><td>-</td></tr>
          <tr><td style="padding:4px;border:1px solid #2b303b"><b>10</b></td><td>-</td><td>-</td><td>-</td><td>-</td><td style="border:1px solid #2b303b">2</td><td style="border:1px solid #2b303b">10</td><td style="border:1px solid #2b303b">30</td><td style="border:1px solid #2b303b">100</td><td style="border:1px solid #2b303b">1000</td><td style="border:1px solid #2b303b">10000</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</div>

<div class="nav" style="grid-template-columns:repeat(4,1fr)">
  <button class="nb active" id="n-game" onclick="tab('game')">Game</button>
  <button class="nb" id="n-wallet" onclick="tab('wallet')">Wallet</button>
  <button class="nb" id="n-hist" onclick="tab('hist')">History</button>
  <button class="nb" id="n-rules" onclick="tab('rules')">Rules</button>
</div>

<script>
const tg=window.Telegram&&window.Telegram.WebApp?window.Telegram.WebApp:null; if(tg)tg.expand();
const params=new URLSearchParams(window.location.search);
const uid=params.get("uid")||(tg&&tg.initDataUnsafe&&tg.initDataUnsafe.user?String(tg.initDataUnsafe.user.id):"874411134");
document.getElementById("uid-lbl").textContent=uid;
const PT={1:{1:3.5},2:{2:10},3:{2:1.5,3:30},4:{2:1,3:10,4:80},5:{3:2,4:15,5:150},6:{3:1.5,4:4,5:60,6:500},7:{3:1,4:3,5:15,6:80,7:1000},8:{4:2,5:10,6:25,7:200,8:2000},9:{4:2,5:5,6:15,7:125,8:800,9:5000},10:{5:2,6:10,7:30,8:100,9:1000,10:10000}};
let bal=0,bet=2,drawing=false,roundSec=60,serverOffsetMs=0,lastDrawnCycle=-1,queued=null,tickets=[],drawnSoFar=new Set(),roundDone=false,lastServerPhase="betting",lastServerCycle=-1,syncTiming={roundDurationSec:60,drawStepSec:2,drawCount:20,resultHoldSec:5,cycleTotalSec:105}; const picks=new Set();
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
    document.getElementById("mwin").textContent=(bet*mx).toFixed(2)+" ETB";
  }
}
function syncedNowSec(){return (Date.now()+serverOffsetMs)/1000;}
function calcGlobalCycleInfo(){
  const s=syncedNowSec();
  const cTotal=syncTiming.cycleTotalSec||105;
  const rDur=syncTiming.roundDurationSec||60;
  const cycleNum=Math.floor(s/cTotal);
  const pos=((s%cTotal)+cTotal)%cTotal;
  if(pos<rDur){
    const rem=Math.max(1,rDur-Math.floor(pos));
    return {cycleNum,pos,phase:"betting",betSecLeft:rem,drawElapsedSec:0};
  }
  return {cycleNum,pos,phase:"drawing",betSecLeft:0,drawElapsedSec:pos-rDur};
}
const g=document.getElementById("grid");
for(let i=1;i<=80;i++){
  const b=document.createElement("button");b.className="t";b.dataset.n=i;b.textContent=i;
  b.onclick=()=>{
    if(drawing)return;
    if(picks.has(i)){picks.delete(i);b.classList.remove("sel");}
    else{if(picks.size>=10)return alert("You cannot select more than 10 numbers.");picks.add(i);b.classList.add("sel");}
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
  if(btn){const prev=btn.textContent;btn.textContent="Copied!";setTimeout(()=>btn.textContent=prev,1200);}
}
function ui(){
  document.getElementById("cnt").textContent=picks.size;
  const bi=document.getElementById("bval");if(bi&&document.activeElement!==bi){bi.value=bet;}
  const t=PT[picks.size]||{};
  const mx=Math.max(0,...Object.values(t));
  document.getElementById("mwin").textContent=(bet*mx).toFixed(2)+" ETB";
}

function tab(k){["game","wallet","hist","rules"].forEach(x=>{document.getElementById("p-"+x).classList.toggle("active",x===k);document.getElementById("n-"+x).classList.toggle("active",x===k);});load();}
function showDepositStep2(){
  const amt=Number(document.getElementById("da").value||0);
  if(!amt||amt<10)return alert("Minimum deposit is 10 ETB.");
  const m=document.getElementById("dm").value;
  document.getElementById("dep-sum-amt").textContent=`${amt} ETB`;
  document.getElementById("dep-sum-meta").textContent=`• ${m} • just now`;
  document.getElementById("dep-send-amt").textContent=`${amt}`;
  document.getElementById("dep-send-method").textContent=m;
  document.getElementById("dep-tb-card").style.display=m==="Telebirr"?"flex":"none";
  document.getElementById("dep-cbe-card").style.display=m==="CBE"?"flex":"none";
  document.getElementById("dep-step1").style.display="none";
  document.getElementById("dep-step2").style.display="block";
  document.getElementById("dmsg").style.color="#4ade80";
  document.getElementById("dmsg").textContent="✅ Success! Deposit request sent — awaiting payment confirmation.";
}
function cancelDepositStep2(){
  document.getElementById("dep-step2").style.display="none";
  document.getElementById("dep-step1").style.display="block";
  document.getElementById("dt").value="";
  document.getElementById("dmsg").textContent="";
}
function renderTickets(){
  const wrap=document.getElementById("tickets-list");
  document.getElementById("tcount").textContent=tickets.length;
  if(!tickets.length){wrap.innerHTML='<div style="color:#9ca3af;margin-top:6px">No tickets placed in this round yet.</div>';return;}
  wrap.innerHTML=tickets.map(tk=>{
    let stHtml='<span class="st-wait">Pending</span>';
    let cls="tcard";
    if(roundDone){
      if(Number(tk.payout||0)>0){stHtml=`<span class="st-win">Won ${Number(tk.payout).toFixed(2)} ETB</span>`;cls+=" won-card";}
      else{stHtml='<span class="st-lose">Please try again</span>';}
    }
    return `<div class="${cls}">
      <div class="tcard-top"><span><b>${tk.player}</b></span><span>Bet <b>${Number(tk.bet).toFixed(0)} ETB</b> | ${stHtml}</span></div>
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
    if(typeof d.cycle_total_sec==="number"){
      syncTiming={
        roundDurationSec:d.round_duration_sec||60,
        drawStepSec:d.draw_step_sec||2,
        drawCount:d.draw_count||20,
        resultHoldSec:d.result_hold_sec||5,
        cycleTotalSec:d.cycle_total_sec||105
      };
    }
    const cInfo=calcGlobalCycleInfo();
    roundSec=cInfo.betSecLeft;
    if(!drawing){
      if(cInfo.phase==="drawing" && lastDrawnCycle!==cInfo.cycleNum){
        tickets=d.tickets||[];
        runRoundDraw(cInfo.cycleNum);
      }else{
        tickets=d.tickets||[];
        roundDone=false;
        document.getElementById("bal").textContent=bal.toFixed(2);
      }
    }
    renderTickets();
    document.getElementById("hlist").innerHTML=d.bets.length?d.bets.slice().reverse().map(x=>`<div>Bet: ${x.bet} ETB | Matches: ${x.matches} | Win: ${x.payout} ETB</div>`).join(""):"No bet history yet.";
    document.getElementById("wlist").innerHTML=d.wds.length?d.wds.slice().reverse().map(w=>`<div style="padding:6px 0;border-bottom:1px solid #2b303b">${w.id} | ${w.method} (${w.dest}) | ${w.amount} ETB | <b>${w.status}</b>${w.status==="Pending"?`<br><button class="appb" onclick="appw('${w.id}')">Approve (Complete)</button>`:""}</div>`).join(""):"No withdraw requests yet.";
  }catch(e){}
}
function clearSelectionsAndBoard(){picks.clear();document.querySelectorAll(".t").forEach(x=>x.classList.remove("sel"));ui();}
function resetDrawStage(){drawnSoFar.clear();roundDone=false;document.getElementById("strip").innerHTML="";document.getElementById("dprog").textContent="0 / 20";document.getElementById("ball").textContent="--";const bn=document.getElementById("out-banner");bn.className="banner";bn.textContent="";}
async function lockBet(){
  if(drawing)return;
  if(!picks.size)return alert("Please select at least 1 number.");
  if(bet<2)return alert("Minimum bet is 2 ETB.");
  if(bal<=0||bet>bal)return showInsuf();
  const cInfo=calcGlobalCycleInfo();
  if(cInfo.phase!=="betting")return alert("Betting for this round has closed. Please wait for the next round.");
  const r=await fetch("/api/reserve_bet",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({uid,picks:Array.from(picks),bet})});
  const d=await r.json();
  if(!d.ok){if(d.insufficient)return showInsuf();return alert(d.msg);}
  bal=d.balance;document.getElementById("bal").textContent=bal.toFixed(2);tickets=d.tickets||tickets;renderTickets();
  queued={picks:Array.from(picks),bet,cycleNum:d.cycle_num||cInfo.cycleNum};
  clearSelectionsAndBoard();
  document.getElementById("gmsg").textContent=`✅ Bet locked (${bet} ETB on ${queued.picks.length} numbers). 20 numbers will be drawn when 01:00 ends.`;
}
function appendDrawnChipInstant(n, watchedSet, updateMainBall){
  if(drawnSoFar.has(n))return;
  drawnSoFar.add(n);
  if(updateMainBall){
    document.getElementById("ball").textContent=n;
  }
  document.getElementById("dprog").textContent=`${drawnSoFar.size} / 20`;
  const ch=document.createElement("span");
  ch.className="chip"+(watchedSet.has(n)?" h":"");
  ch.textContent=n;
  document.getElementById("strip").appendChild(ch);
}

async function runRoundDraw(targetCycle){
  if(drawing)return;
  const cNum=(typeof targetCycle==="number")?targetCycle:calcGlobalCycleInfo().cycleNum;
  if(lastDrawnCycle===cNum)return;
  lastDrawnCycle=cNum;
  drawing=true;
  resetDrawStage();
  let activeBet=(queued && queued.cycleNum===cNum)?queued:null;
  if(activeBet)queued=null;

  const r=await fetch("/api/play",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({uid,cycle_num:cNum})});
  const d=await r.json();
  if(!activeBet && d.my_ticket){
    activeBet={picks:d.my_ticket.picks||[],bet:Number(d.my_ticket.bet||0),cycleNum:cNum};
  }
  if(d.tickets)tickets=d.tickets;
  renderTickets();

  const stepSec=syncTiming.drawStepSec||2;
  const drawnArr=d.drawn||[];
  const watched=new Set(activeBet?activeBet.picks:[]);

  // Any numbers already drawn by the server up to this exact moment appear immediately
  // seated in place without fast-forwarding or racing.
  const initInfo=calcGlobalCycleInfo();
  const alreadyCount=(initInfo.cycleNum===cNum && initInfo.phase==="drawing")
    ? Math.min(drawnArr.length, Math.max(0, Math.floor(initInfo.drawElapsedSec / stepSec) + 1))
    : 0;

  if(alreadyCount > 0){
    for(let i=0;i<alreadyCount;i++){
      appendDrawnChipInstant(drawnArr[i], watched, i === alreadyCount - 1);
    }
    renderTickets();
  }

  // Subsequent numbers appear one by one in sync with the server draw timeline
  for(let i=alreadyCount;i<drawnArr.length;i++){
    const cNow=calcGlobalCycleInfo();
    if(cNow.phase==="betting" && cNow.cycleNum!==cNum)break;
    const targetElapsed=i * stepSec;
    while(true){
      const tickNow=calcGlobalCycleInfo();
      if(tickNow.phase==="betting" && tickNow.cycleNum!==cNum)break;
      if(tickNow.cycleNum!==cNum || tickNow.drawElapsedSec >= targetElapsed - 0.05)break;
      const waitMs=Math.min(250, Math.max(50, (targetElapsed - tickNow.drawElapsedSec)*1000));
      await new Promise(res=>setTimeout(res,waitMs));
    }
    const afterWait=calcGlobalCycleInfo();
    if(afterWait.phase==="betting" && afterWait.cycleNum!==cNum)break;
    appendDrawnChipInstant(drawnArr[i], watched, true);
    renderTickets();
  }

  roundDone=true;
  renderTickets();
  const bn=document.getElementById("out-banner");
  const hasPlayed=Boolean(activeBet) || Number(d.my_bet||0)>0;
  if(hasPlayed){
    const pay=Number(d.payout||0);
    const mt=Number(d.matches||0);
    const hList=d.hits||[];
    if(pay>0){
      bn.className="banner winb";
      bn.textContent=`🎉 Congratulations! You won ${pay.toFixed(2)} ETB (${mt} matches)!`;
    }else{
      bn.className="banner tryb";
      bn.textContent=`Please try again — ${mt} matches`;
    }
    document.getElementById("gmsg").innerHTML=`<b>Matches (${mt}):</b> ${hList.join(", ")||"None"} | <b>Win:</b> ${pay.toFixed(2)} ETB`;
    await new Promise(res=>setTimeout(res,4000));
  }else{
    await new Promise(res=>setTimeout(res,2500));
  }
  if(typeof d.balance==="number"){
    bal=d.balance;
    document.getElementById("bal").textContent=bal.toFixed(2);
  }
  bn.className="banner";bn.textContent="";
  tickets=[];
  clearSelectionsAndBoard();
  drawing=false;
  load();
}
async function dep(){
  const rawTxt=(document.getElementById("dt").value||"").trim();
  if(!rawTxt)return alert("Please paste the confirmation SMS or Transaction ID.");
  const msgEl=document.getElementById("dmsg");
  msgEl.textContent="";
  const r=await fetch("/api/deposit",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({uid,mode:"sms",method:document.getElementById("dm").value,amount:document.getElementById("da").value,tx:rawTxt,sms_text:rawTxt})});
  const d=await r.json();
  if(d.ok){
    msgEl.style.color="#4ade80";
    msgEl.textContent=d.msg;
    document.getElementById("dt").value="";
    document.getElementById("da").value="";
    document.getElementById("dep-step2").style.display="none";
    document.getElementById("dep-step1").style.display="block";
    load();
  }else if(d.msg){
    msgEl.style.color="#f87171";
    msgEl.textContent=d.msg;
  }else{
    msgEl.textContent="";
  }
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
  const cInfo=calcGlobalCycleInfo();
  roundSec=cInfo.betSecLeft;
  if(!drawing){
    const m=Math.floor(roundSec/60),s=roundSec%60;
    document.getElementById("tm").textContent=String(m).padStart(2,"0")+":"+String(s).padStart(2,"0");
    if(cInfo.phase==="drawing" && lastDrawnCycle!==cInfo.cycleNum){
      document.getElementById("tm").textContent="00:00";
      runRoundDraw(cInfo.cycleNum);
    }else if(lastServerPhase==="drawing" && cInfo.phase==="betting" && lastServerCycle!==cInfo.cycleNum){
      resetDrawStage();
      tickets=[];
      renderTickets();
      load();
    }
  }
  lastServerPhase=cInfo.phase;
  lastServerCycle=cInfo.cycleNum;
},250);
ui();load();
</script></body></html>"""


@app.route("/ping")
@app.route("/healthz")
def healthz():
  return jsonify({"ok": True, "service": "ethio-fast-keno", "ts": int(time.time())})


@app.route("/")
def home():
  tb_num, tb_owner = split_account_and_name(TELEBIRR_ACCOUNT, TELEBIRR_NAME)
  cbe_num, cbe_owner = split_account_and_name(CBE_ACCOUNT, CBE_NAME)
  html = (
      PAGE.replace("__TELEBIRR__", tb_num)
      .replace("__TELEBIRR_NAME__", tb_owner)
      .replace("__CBE__", cbe_num)
      .replace("__CBE_NAME__", cbe_owner)
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
        json={"menu_button": {"type": "commands"}},
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
      already_claimed = bool(u.get("registered") or u.get("bonus_claimed") or uid in CLAIMED_BONUS_USERS)
      if not already_claimed:
        u["registered"] = True
        u["bonus_claimed"] = True
        CLAIMED_BONUS_USERS.add(uid)
        u["balance"] = round(u["balance"] + 10.0, 2)
        inviter_id = (u.get("referred_by") or REFERRED_USERS.get(uid) or "").strip()
        if (
            inviter_id
            and inviter_id != uid
            and inviter_id in USERS
            and not u.get("ref_rewarded")
        ):
          u["ref_rewarded"] = True
          inv_u = get_u(inviter_id)
          inv_u["balance"] = round(inv_u["balance"] + 10.0, 2)
          inv_u["referrals"] = int(inv_u.get("referrals", 0)) + 1
          tg(
              inviter_id,
              f"🎉 Your friend joined via your referral link and verified their registration!\n🎁 You received a 10.00 ETB referral bonus (one-time only). Total referrals: {inv_u['referrals']} | Balance: {inv_u['balance']:.2f} ETB",
          )
        save_persistent_state()
        tg_answer_cb(cb_id, "Registration complete! 10.00 ETB one-time bonus credited.")
        tg(
            uid,
            f"✅ Registration verified and completed!\n🎁 You received a 10.00 ETB welcome bonus (one-time only).\n💰 Your Balance: {u['balance']:.2f} ETB",
            main_reply_kb(uid, base_url),
        )
      else:
        u["registered"] = True
        u["bonus_claimed"] = True
        CLAIMED_BONUS_USERS.add(uid)
        save_persistent_state()
        tg_answer_cb(cb_id, "Already registered! Welcome bonus is one-time only.")
        tg(
            uid,
            f"ℹ️ You have already registered and claimed your welcome bonus. Bonus can only be claimed once.\n💰 Your Balance: {u['balance']:.2f} ETB",
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
            f"✅ Completed! Your withdrawal request of {w['amount']:.2f} ETB ({wid}) has been sent to {w['dest']}.",
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
        tg(uid, f"📢 Announcement sent to {cnt} users.", main_reply_kb(uid, base_url))
        return jsonify({"ok": True})

      shot_digest = hashlib.sha256(img_bytes).hexdigest()[:16].upper()
      shot_key = f"SHOT_{shot_digest}"
      if shot_key in USED_TX:
        u["invalid_shots"] = int(u.get("invalid_shots", 0)) + 1
        notify_internal_photo(
            img_bytes,
            caption=(
                f"⚠️ Duplicate Screenshot Rejected\n"
                f"Ref: {shot_key}\n"
                f"Customer ID: {uid}\n"
                f"Invalid Count: {u['invalid_shots']}"
            ),
        )
        if u["invalid_shots"] >= 2:
          tg(
              uid,
              "⚠️ Duplicate screenshot rejected. This payment receipt has already been used. Please send a new valid receipt.",
              main_reply_kb(uid, base_url),
          )
        return jsonify({"ok": True})

      amt_match = re.search(r"(\d+(?:\.\d+)?)", caption)
      amt = float(amt_match.group(1)) if amt_match else 0.0
      if amt >= 10:
        USED_TX.add(shot_key)
        u["invalid_shots"] = 0
        u["registered"] = True
        u["balance"] = round(u["balance"] + amt, 2)
        notify_internal_photo(
            img_bytes,
            caption=(
                f"✅ Screenshot Verified & Credited\n"
                f"Ref: {shot_key}\n"
                f"Customer ID: {uid}\n"
                f"Amount: {amt:.2f} ETB\n"
                f"New Balance: {u['balance']:.2f} ETB"
            ),
        )
        tg(
            uid,
            f"✅ Verified & Completed! {amt:.2f} ETB has been added to your balance.\n💰 New Balance: {u['balance']:.2f} ETB",
            main_reply_kb(uid, base_url),
        )
      else:
        u["invalid_shots"] = int(u.get("invalid_shots", 0)) + 1
        notify_internal_photo(
            img_bytes,
            caption=(
                f"🕵️ Internal Screenshot Audit (Unverified / Missing Amount in Caption)\n"
                f"Ref: {shot_key}\n"
                f"Customer ID: {uid}\n"
                f"Caption: {caption or '(none)'}\n"
                f"Invalid Count: {u['invalid_shots']}"
            ),
        )
        if u["invalid_shots"] >= 2:
          tg(
              uid,
              "❌ Payment not verified (valid receipt or amount >= 10 ETB missing in caption). Please send a valid payment receipt only.",
              main_reply_kb(uid, base_url),
          )
    return jsonify({"ok": True})

  if not text:
    return jsonify({"ok": True})

  u = get_u(uid)
  if text.startswith("/start"):
    parts = text.split(maxsplit=1)
    already_claimed = bool(u.get("registered") or u.get("bonus_claimed") or uid in CLAIMED_BONUS_USERS)
    if len(parts) == 2 and parts[1].startswith("ref_"):
      inviter_id = parts[1][4:].strip()
      if (
          not already_claimed
          and inviter_id
          and inviter_id != uid
          and not u.get("referred_by")
          and uid not in REFERRED_USERS
      ):
        u["referred_by"] = inviter_id
        REFERRED_USERS[uid] = inviter_id
        save_persistent_state()
    if not already_claimed:
      tg(
          uid,
          "Welcome to ETHIO FAST KENO!\n\n"
          "Tap below to register with your Telegram account and claim your one-time 10.00 ETB welcome bonus.",
          {
              "inline_keyboard": [[{
                  "text": "✅ Register & Claim 10 ETB Bonus",
                  "callback_data": "register_bonus",
              }]]
          },
      )
    else:
      tg(
          uid,
          f"Welcome back to ETHIO FAST KENO!\n💰 Your Balance: {u['balance']:.2f} ETB",
          main_reply_kb(uid, base_url),
      )
    return jsonify({"ok": True})

  if text in ("🎮 Play", "Play", "Play Games"):
    if not u["registered"]:
      tg(
          uid,
          "Please register first to start playing.",
          {"inline_keyboard": [[{
              "text": "✅ Register & Claim 10 ETB Bonus",
              "callback_data": "register_bonus",
          }]]},
      )
    else:
      tg(
          uid,
          f"🎮 Tap the 'Play' button below to launch the game.\n💰 Your Balance: {u['balance']:.2f} ETB",
          main_reply_kb(uid, base_url),
      )
    return jsonify({"ok": True})

  if text in ("✉️ Invite Friends", "Invite Friends"):
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
            "text": "Join me on ETHIO FAST KENO and play!",
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
        "🚀 Invite your friends! Tap the button below to share your referral link:\n"
        f"{ref_link}",
        share_kb,
    )
    return jsonify({"ok": True})

  if text in ("🆘 Support", "Support"):
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
        f"🆘 Customer Support:\nMessage @{target_handle} directly for help and support.",
        sup_kb,
    )
    return jsonify({"ok": True})

  if is_admin_user(uid, sender_username) and (
      text.lower().startswith("/broadcast ") or text.lower().startswith("/post ")
  ):
    ann_txt = re.sub(r"(?i)^/(broadcast|post)\s+", "", text).strip()
    if ann_txt:
      cnt = broadcast_announcement(text=ann_txt, exclude_uid=uid)
      tg(uid, f"📢 Announcement sent to {cnt} users.", main_reply_kb(uid, base_url))
    else:
      tg(uid, "ℹ️ To send an announcement: type /post followed by your message, or send a photo with caption.", main_reply_kb(uid, base_url))
    return jsonify({"ok": True})

  if u["registered"] and not text.startswith("/"):
    notify_internal(f"💬 Support Message\nCustomer ID: {uid}\nMessage: {text}")
    tg(
        uid,
        "✅ Your message has been sent to Support. We will reply shortly.",
        main_reply_kb(uid, base_url),
    )

  return jsonify({"ok": True})


@app.route("/api/state")
def api_state():
  uid = str(request.args.get("uid", "874411134")).strip()
  u = get_u(uid)
  adm = bool(ADMIN_CHAT_ID and uid == ADMIN_CHAT_ID)
  st = current_cycle_state(time.time())
  c_num = st["cycle_num"]
  drawn = get_round_drawn(c_num)
  entries = ROUND_BETS.get(c_num) or []

  # If we are in or past drawing phase, settle immediately so winners get credited right away
  if st["phase"] == "drawing":
    drawn, entries = settle_cycle_if_needed(c_num)
    elapsed_draw = st["draw_elapsed_sec"]
    shown_cnt = min(DRAW_COUNT, max(0, int(elapsed_draw // DRAW_STEP_SEC) + 1)) if elapsed_draw < DRAW_COUNT * DRAW_STEP_SEC else DRAW_COUNT
    show_result = elapsed_draw >= DRAW_COUNT * DRAW_STEP_SEC
  else:
    shown_cnt = 0
    show_result = False

  public_tickets = [
      {
          "player": e["player"],
          "picks": e["picks"],
          "bet": e["bet"],
          "payout": e["payout"] if show_result else 0.0,
      }
      for e in entries[-25:]
  ]
  my_entry = next((e for e in reversed(entries) if e["uid"] == uid), None)

  return jsonify({
      "balance": u["balance"],
      "registered": u["registered"],
      "bets": u["bets"][-20:],
      "tickets": public_tickets,
      "my_ticket": my_entry,
      "drawn": drawn[:shown_cnt],
      "full_drawn": drawn if show_result else drawn[:shown_cnt],
      "shown_count": shown_cnt,
      "show_result": show_result,
      "wds": list(WITHDRAWALS.values()) if adm else u["wds"],
      "is_admin": adm,
      "server_now": st["server_now"],
      "cycle_num": c_num,
      "phase": st["phase"],
      "bet_sec_left": st["bet_sec_left"],
      "draw_elapsed_sec": st["draw_elapsed_sec"],
      "cycle_total_sec": CYCLE_TOTAL_SEC,
      "round_duration_sec": ROUND_DURATION_SEC,
      "draw_step_sec": DRAW_STEP_SEC,
      "draw_count": DRAW_COUNT,
      "result_hold_sec": RESULT_HOLD_SEC,
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
  st = current_cycle_state(time.time())
  if st["phase"] != "betting":
    return jsonify({"ok": False, "msg": "Betting for this round has closed. Please wait for the next round."})
  if not (1 <= len(picks) <= 10) or bet < 2:
    return jsonify({"ok": False, "msg": "Please pick 1 to 10 numbers and bet at least 2 ETB."})
  if u["balance"] <= 0 or bet > u["balance"]:
    return jsonify(
        {"ok": False, "insufficient": True, "msg": "Insufficient balance."}
    )
  u["balance"] = round(u["balance"] - bet, 2)
  save_persistent_state()
  c_num = st["cycle_num"]
  ROUND_BETS.setdefault(c_num, []).append({
      "uid": uid,
      "player": mask_uid(uid),
      "picks": picks,
      "bet": bet,
      "hits": [],
      "matches": 0,
      "payout": 0.0,
      "settled": False,
  })
  public_tickets = [
      {
          "player": e["player"],
          "picks": e["picks"],
          "bet": e["bet"],
          "payout": 0.0,
      }
      for e in ROUND_BETS[c_num][-25:]
  ]
  return jsonify({
      "ok": True,
      "balance": u["balance"],
      "cycle_num": c_num,
      "tickets": public_tickets,
  })


@app.route("/api/play", methods=["POST"])
def api_play():
  d = request.get_json(force=True)
  uid = str(d.get("uid", "874411134")).strip()
  req_cycle = d.get("cycle_num")
  st = current_cycle_state(time.time())
  c_num = int(req_cycle) if req_cycle is not None else st["cycle_num"]
  drawn, entries = settle_cycle_if_needed(c_num)
  u = get_u(uid)
  my_entry = next((e for e in reversed(entries) if e["uid"] == uid), None)
  public_tickets = [
      {
          "player": e["player"],
          "picks": e["picks"],
          "bet": e["bet"],
          "payout": e["payout"],
      }
      for e in entries[-25:]
  ]
  return jsonify({
      "ok": True,
      "balance": u["balance"],
      "cycle_num": c_num,
      "drawn": drawn,
      "my_ticket": my_entry,
      "my_bet": my_entry["bet"] if my_entry else 0.0,
      "hits": my_entry["hits"] if my_entry else [],
      "matches": my_entry["matches"] if my_entry else 0,
      "payout": my_entry["payout"] if my_entry else 0.0,
      "tickets": public_tickets,
  })


@app.route("/api/deposit", methods=["POST"])
def api_deposit():
  d = request.get_json(force=True)
  uid = str(d.get("uid", "874411134")).strip()
  m = str(d.get("method", "Telebirr")).strip()
  raw_sms = str(d.get("sms_text") or d.get("tx") or "").strip()
  tx = extract_tx_code(m, raw_sms)
  amt = float(d.get("amount", 0) or 0)
  u = get_u(uid)

  if amt < 10:
    u["invalid_shots"] = int(u.get("invalid_shots", 0)) + 1
    msg_txt = "❌ Payment not verified. Minimum deposit is 10 ETB." if u["invalid_shots"] >= 2 else ""
    return jsonify({"ok": False, "silent": not bool(msg_txt), "msg": msg_txt})

  if not tx:
    u["invalid_shots"] = int(u.get("invalid_shots", 0)) + 1
    msg_txt = (
        "❌ Valid Transaction ID / SMS not found. Please paste your confirmation SMS or Transaction ID."
        if u["invalid_shots"] >= 2
        else ""
    )
    return jsonify({"ok": False, "silent": not bool(msg_txt), "msg": msg_txt})

  st = check_tx_status(m, tx)
  if st == "duplicate":
    u["invalid_shots"] = int(u.get("invalid_shots", 0)) + 1
    msg_txt = (
        "⚠️ Duplicate Transaction ID! This payment reference has already been used."
        if u["invalid_shots"] >= 2
        else ""
    )
    return jsonify({"ok": False, "silent": not bool(msg_txt), "msg": msg_txt})
  if st != "ok":
    u["invalid_shots"] = int(u.get("invalid_shots", 0)) + 1
    msg_txt = (
        "❌ Invalid or unverified Transaction ID. Please check and enter a valid confirmation SMS/ID."
        if u["invalid_shots"] >= 2
        else ""
    )
    return jsonify({"ok": False, "silent": not bool(msg_txt), "msg": msg_txt})

  USED_TX.add(tx)
  u["invalid_shots"] = 0
  u["balance"] = round(u["balance"] + amt, 2)
  save_persistent_state()
  notify_internal(
      f"✅ Auto-Credited Deposit\nCustomer ID: {uid}\nMethod: {m}\nRef: {tx}\nAmount: {amt:.2f} ETB"
  )
  return jsonify({
      "ok": True,
      "balance": u["balance"],
      "msg": (
          f"✅ Verified & Completed! {amt:.2f} ETB via {m} ({tx}) has been added to your balance."
      ),
  })


@app.route("/api/withdraw", methods=["POST"])
def api_withdraw():
  if not is_wd_hours():
    return jsonify({
        "ok": False,
        "msg": (
            "⏰ Withdrawals are available daily from 08:00 AM to 09:00 PM EAT. Deposits are open 24/7."
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
    return jsonify({"ok": False, "msg": "Please enter a valid withdrawal amount."})
  if amt > u["balance"]:
    return jsonify({"ok": False, "msg": "Insufficient balance."})
  if not dest:
    return jsonify({"ok": False, "msg": "Please enter your account number and full name."})
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
  save_persistent_state()
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
          f"⏳ Your withdrawal request of {amt:.2f} ETB ({wid}) is Pending and will be processed shortly."
      ),
  })


@app.route("/api/approve", methods=["POST"])
def api_approve():
  d = request.get_json(force=True)
  wid = str(d.get("id", "")).strip()
  w = WITHDRAWALS.get(wid)
  if not w:
    return jsonify({"ok": False, "msg": "Withdrawal request not found."}), 404
  w["status"] = "Completed"
  for item in get_u(w["uid"])["wds"]:
    if item["id"] == wid:
      item["status"] = "Completed"
  save_persistent_state()
  tg(
      w["uid"],
      f"✅ Completed! Your withdrawal of {w['amount']:.2f} ETB ({wid}) has been sent to {w['dest']}.",
  )
  return jsonify(
      {"ok": True, "msg": f"{wid} marked as Completed and customer notified."}
  )


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
