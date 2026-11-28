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


WEBAPP_URL = (
    os.environ.get("WEBAPP_URL") or "https://ethio-keno-exlm.onrender.com"
).strip().rstrip("/")

EAT = timezone(timedelta(hours=3))
def _resolve_state_file():
  if os.environ.get("STATE_FILE"):
    return os.environ["STATE_FILE"].strip()
  for candidate_dir in ["/var/data", "/opt/render/project/src/data", "."]:
    try:
      if candidate_dir != "." and not os.path.isdir(candidate_dir):
        os.makedirs(candidate_dir, exist_ok=True)
      test_path = os.path.join(candidate_dir, ".write_test")
      with open(test_path, "w", encoding="utf-8") as tf:
        tf.write("ok")
      os.remove(test_path)
      return os.path.join(candidate_dir, "ethio_keno_state.json")
    except Exception:
      continue
  return "/tmp/ethio_keno_state.json"

STATE_FILE = _resolve_state_file()
USERS, USED_TX, WITHDRAWALS = {}, set(), {}
CLAIMED_BONUS_USERS = set()
REFERRED_USERS = {}
LIVE_TICKETS = []
GAME_HISTORY = []  # list of dicts: {"round": int, "cycle": int, "drawn": [20 ints], "ts": int}
BASE_CYCLE_OFFSET = None

HOUSE_TOTAL_STAKE = 0.0
HOUSE_TOTAL_PAID = 0.0
HOUSE_TOTAL_DEPOSITS = 0.0
HOUSE_TOTAL_WITHDRAWALS = 0.0
TOP_WINNERS = []  # list of dicts: {"player": str, "amount": float, "round": int, "ts": int}


def get_top_winners_feed():
  # Mix real winners with varied showcase winners (e.g. 8,000, 9,000, 10,000, 12,000 ETB)
  # rotating every ~2 minutes and replacing/complementing real winners so the
  # horizontal stream stays lively and never looks empty or static.
  real_sorted = sorted(
      [w for w in TOP_WINNERS if float(w.get("amount", 0)) > 0],
      key=lambda x: float(x.get("amount", 0)),
      reverse=True,
  )[:6]
  slot_bucket = int(time.time() // 120)
  rng = random.Random(f"ethio-keno-top-winners-{slot_bucket}")
  prefixes = [
      "0920***99", "0936***09", "0979***03", "0978***88",
      "0957***30", "0972***12", "0703***75", "0980***94",
      "0975***72", "0956***39", "0983***30", "0908***61",
  ]
  amounts = [
      10000.0, 12000.0, 9000.0, 8000.0,
      10000.0, 8500.0, 9500.0, 12000.0,
      8000.0, 10000.0, 9000.0, 11000.0,
  ]
  rng.shuffle(prefixes)
  rng.shuffle(amounts)

  merged = []
  # Include up to 2 real winners so real wins appear alongside showcase entries
  for rw in real_sorted[:2]:
    merged.append(rw)

  used_players = {x["player"] for x in merged}
  for p_id, amt in zip(prefixes, amounts):
    if len(merged) >= 8:
      break
    if p_id in used_players:
      continue
    used_players.add(p_id)
    merged.append({
        "player": p_id,
        "amount": amt,
        "round": max(1, cycle_to_round_num(current_cycle_state()["cycle_num"]) - rng.randint(1, 15)),
        "ts": int(time.time()) - rng.randint(30, 900),
    })
  return merged[:8]


def load_persistent_state():
  global USERS, USED_TX, WITHDRAWALS, CLAIMED_BONUS_USERS, REFERRED_USERS, GAME_HISTORY, BASE_CYCLE_OFFSET
  global HOUSE_TOTAL_STAKE, HOUSE_TOTAL_PAID, HOUSE_TOTAL_DEPOSITS, HOUSE_TOTAL_WITHDRAWALS
  try:
    if os.path.exists(STATE_FILE):
      with open(STATE_FILE, "r", encoding="utf-8") as fh:
        data = json.load(fh)
      if isinstance(data.get("users"), dict):
        USERS.update(data["users"])
      if isinstance(data.get("used_tx"), list):
        USED_TX.update(str(x).upper() for x in data["used_tx"])
      if isinstance(data.get("withdrawals"), dict):
        WITHDRAWALS.update(data["withdrawals"])
      if isinstance(data.get("claimed_bonus_users"), list):
        CLAIMED_BONUS_USERS.update(str(x) for x in data["claimed_bonus_users"])
      if isinstance(data.get("referred_users"), dict):
        REFERRED_USERS.update(data["referred_users"])
      if isinstance(data.get("game_history"), list):
        GAME_HISTORY[:] = data["game_history"]
      if isinstance(data.get("top_winners"), list):
        TOP_WINNERS[:] = data["top_winners"]
      if data.get("base_cycle_offset") is not None:
        BASE_CYCLE_OFFSET = int(data["base_cycle_offset"])
      HOUSE_TOTAL_STAKE = float(data.get("house_total_stake", 0.0) or 0.0)
      HOUSE_TOTAL_PAID = float(data.get("house_total_paid", 0.0) or 0.0)
      HOUSE_TOTAL_DEPOSITS = float(data.get("house_total_deposits", 0.0) or 0.0)
      HOUSE_TOTAL_WITHDRAWALS = float(
          data.get("house_total_withdrawals", 0.0) or 0.0
      )
      if isinstance(data.get("pending_deposits"), dict):
        PENDING_DEPOSITS.update(data["pending_deposits"])
      for uid_k, u_val in list(USERS.items()):
        if isinstance(u_val, dict):
          if u_val.get("bonus_claimed") or uid_k in CLAIMED_BONUS_USERS:
            u_val["registered"] = True
            u_val["bonus_claimed"] = True
            CLAIMED_BONUS_USERS.add(str(uid_k))
          u_val["balance"] = round(float(u_val.get("balance", 0.0) or 0.0), 2)
          u_val.setdefault("deposits", [])
          u_val.setdefault("bets", [])
          u_val.setdefault("wds", [])
  except Exception:
    pass


def save_persistent_state():
  try:
    tmp_path = STATE_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
      json.dump(
          {
              "users": USERS,
              "used_tx": sorted(list(USED_TX)),
              "withdrawals": WITHDRAWALS,
              "pending_deposits": PENDING_DEPOSITS,
              "claimed_bonus_users": sorted(list(CLAIMED_BONUS_USERS)),
              "referred_users": REFERRED_USERS,
              "game_history": GAME_HISTORY[-200:],
              "top_winners": TOP_WINNERS[-50:],
              "base_cycle_offset": BASE_CYCLE_OFFSET,
              "house_total_stake": HOUSE_TOTAL_STAKE,
              "house_total_paid": HOUSE_TOTAL_PAID,
              "house_total_deposits": HOUSE_TOTAL_DEPOSITS,
              "house_total_withdrawals": HOUSE_TOTAL_WITHDRAWALS,
          },
          fh,
          ensure_ascii=False,
      )
    os.replace(tmp_path, STATE_FILE)
  except Exception:
    pass


def cycle_to_round_num(cycle_num):
  global BASE_CYCLE_OFFSET
  c_val = int(cycle_num)
  if BASE_CYCLE_OFFSET is None:
    BASE_CYCLE_OFFSET = c_val - 1
    save_persistent_state()
  return max(1, c_val - int(BASE_CYCLE_OFFSET))


def record_game_history(cycle_num, drawn_list):
  c_key = int(cycle_num)
  r_num = cycle_to_round_num(c_key)
  if not any(int(item.get("cycle", -1)) == c_key for item in GAME_HISTORY):
    GAME_HISTORY.append({
        "round": r_num,
        "cycle": c_key,
        "drawn": list(drawn_list[:20]),
        "ts": int(time.time()),
    })
    if len(GAME_HISTORY) > 200:
      GAME_HISTORY[:] = GAME_HISTORY[-200:]
    save_persistent_state()


load_persistent_state()

import threading

def _background_24_7_loop():
  last_settled_c = -1
  last_ping_ts = 0.0
  while True:
    try:
      now_ts = time.time()
      st = current_cycle_state(now_ts)
      c_num = st["cycle_num"]
      # Settle previous cycle if needed
      if c_num - 1 >= 0 and (c_num - 1) != last_settled_c:
        settle_cycle_if_needed(c_num - 1)
        last_settled_c = c_num - 1
      # As soon as drawing phase starts for current cycle, generate & record the 20 numbers 24/7
      if st["phase"] == "drawing":
        settle_cycle_if_needed(c_num)
      # Built-in 24/7 keep-alive ping every 4 minutes (240s) so the server stays awake automatically
      if WEBAPP_URL and (now_ts - last_ping_ts) >= 240:
        last_ping_ts = now_ts
        ping_url = (
            WEBAPP_URL
            if WEBAPP_URL.startswith("https://")
            else "https://" + WEBAPP_URL.lstrip("/")
        ) + "/ping"
        try:
          requests.get(ping_url, timeout=8)
        except Exception:
          pass
    except Exception:
      pass
    time.sleep(1.5)

_bg_thread = threading.Thread(target=_background_24_7_loop, daemon=True)
_bg_thread.start()

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
      uname = (
          ((me.get("result") or {}).get("username") or "").strip().lstrip("@")
      )
      if uname:
        BOT_USERNAME_CACHE = uname
  except Exception:
    pass
  return BOT_USERNAME_CACHE


DEP_START_HOUR_EAT = int(os.environ.get("DEP_START_HOUR_EAT", "7"))
DEP_END_HOUR_EAT = int(os.environ.get("DEP_END_HOUR_EAT", "1"))


def is_deposit_hours(now_dt=None):
  if now_dt is None:
    now_dt = datetime.now(EAT)
  h = now_dt.hour
  start_h = DEP_START_HOUR_EAT % 24
  end_h = DEP_END_HOUR_EAT % 24
  if start_h == end_h:
    return True
  if start_h < end_h:
    return start_h <= h < end_h
  # Wraps past midnight (e.g., 07:00 EAT to 01:00 EAT)
  return h >= start_h or h < end_h


def is_wd_hours():
  return 8 <= datetime.now(EAT).hour < 21


ROUND_DURATION_SEC = 60
DRAW_STEP_SEC = 2
DRAW_COUNT = 20
RESULT_HOLD_SEC = 5
DRAW_PHASE_SEC = DRAW_COUNT * DRAW_STEP_SEC + RESULT_HOLD_SEC
CYCLE_TOTAL_SEC = ROUND_DURATION_SEC + DRAW_PHASE_SEC

ROUND_BETS = {}
SETTLED_ROUNDS = set()
DRAWN_CACHE = {}


def mask_uid(uid):
  s = str(uid)
  return s if len(s) <= 3 else f"{s[0]}***{s[-1]}"


def get_u(uid):
  uid = str(uid)
  if uid not in USERS:
    USERS[uid] = {
        "registered": False,
        "bonus_claimed": False,
        "claimed_10_bonus": False,
        "balance": 0.0,
        "wds": [],
        "bets": [],
        "deposits": [],
        "invalid_shots": 0,
    }
    save_persistent_state()
  u = USERS[uid]
  if u.get("bonus_claimed") or u.get("claimed_10_bonus") or uid in CLAIMED_BONUS_USERS:
    u["registered"] = True
    u["bonus_claimed"] = True
    u["claimed_10_bonus"] = True
    CLAIMED_BONUS_USERS.add(uid)
  u["balance"] = round(float(u.get("balance", 0.0) or 0.0), 2)
  u.setdefault("deposits", [])
  u.setdefault("bets", [])
  u.setdefault("wds", [])
  return u


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


def get_house_balance():
  net_round_margin = round(HOUSE_TOTAL_STAKE - HOUSE_TOTAL_PAID, 2)
  return round(
      HOUSE_TOTAL_DEPOSITS + net_round_margin - HOUSE_TOTAL_WITHDRAWALS, 2
  )


def record_house_financial_event(event_label, delta_amount, detail_note=""):
  global HOUSE_TOTAL_DEPOSITS, HOUSE_TOTAL_WITHDRAWALS
  bal_before = get_house_balance()
  if event_label == "DEPOSIT":
    HOUSE_TOTAL_DEPOSITS = round(HOUSE_TOTAL_DEPOSITS + float(delta_amount), 2)
  elif event_label == "WITHDRAW":
    HOUSE_TOTAL_WITHDRAWALS = round(
        HOUSE_TOTAL_WITHDRAWALS + float(delta_amount), 2
    )
  bal_after = get_house_balance()
  net_profit = round(
      HOUSE_TOTAL_DEPOSITS
      + (HOUSE_TOTAL_STAKE - HOUSE_TOTAL_PAID)
      - HOUSE_TOTAL_WITHDRAWALS,
      2,
  )
  save_persistent_state()
  sign_str = "+" if event_label == "DEPOSIT" else "-"
  notify_internal(
      f"📊 House Ledger Update ({event_label})\n"
      f"Previous Balance: {bal_before:.2f} ETB\n"
      f"Change: {sign_str}{abs(float(delta_amount)):.2f} ETB\n"
      f"Remaining House Balance: {bal_after:.2f} ETB\n"
      f"Total Deposits (CBE+Telebirr): {HOUSE_TOTAL_DEPOSITS:.2f} ETB | Total Withdrawals: {HOUSE_TOTAL_WITHDRAWALS:.2f} ETB\n"
      f"Daily Net Profit / Position: {net_profit:.2f} ETB\n"
      f"{detail_note}"
  )
  return bal_before, bal_after


def _near_miss_bonus(drawn_list, entries):
  """Reward candidates that leave players tantalizingly 1 or 2 numbers short of a hit/jackpot."""
  d_set = set(drawn_list)
  score = 0.0
  for e in entries:
    picks = e["picks"]
    n_picks = len(picks)
    h_cnt = sum(1 for x in picks if x in d_set)
    missing = n_picks - h_cnt
    if missing == 1:
      score += 8.0
    elif missing == 2 and n_picks >= 3:
      score += 5.0
    elif h_cnt >= 1:
      score += 2.0
  return score


def get_round_drawn(cycle_num):
  global HOUSE_TOTAL_STAKE, HOUSE_TOTAL_PAID
  c_key = int(cycle_num)
  if c_key not in DRAWN_CACHE:
    entries = ROUND_BETS.get(c_key) or []
    rng = random.Random(f"ethio-keno-cycle-{c_key}-{len(entries)}")
    best_drawn = rng.sample(range(1, 81), DRAW_COUNT)
    if entries:
      round_stake = sum(float(e["bet"]) for e in entries)
      max_single_bet = max(float(e["bet"]) for e in entries)
      live_house_bal = max(0.0, get_house_balance())
      projected_total_stake = HOUSE_TOTAL_STAKE + round_stake
      # Strictly 50% house profit margin / 50% player payout pool
      target_paid_budget = projected_total_stake * 0.50
      remaining_rtp_budget = max(0.0, target_paid_budget - HOUSE_TOTAL_PAID)
      house_profitable = (HOUSE_TOTAL_STAKE - HOUSE_TOTAL_PAID) >= 0.0
      high_stake_round = max_single_bet >= 500.0
      allow_win_round = (
          house_profitable
          and remaining_rtp_budget >= round_stake * 0.15
          and (c_key % 2 == 0 or remaining_rtp_budget >= round_stake * 0.65)
      )
      cap_factor = (
          0.35 if high_stake_round else (0.85 if allow_win_round else 0.30)
      )
      max_round_payout_cap = (
          min(
              remaining_rtp_budget,
              max(round_stake * cap_factor, live_house_bal * 0.45),
          )
          if remaining_rtp_budget > 0
          else 0.0
      )
      best_score = None
      for _ in range(180):
        cand = rng.sample(range(1, 81), DRAW_COUNT)
        _, t_pay, max_ratio, all_full = _score_drawn_for_entries(cand, entries)
        nm_bonus = _near_miss_bonus(cand, entries)
        if t_pay > max_round_payout_cap:
          penalty = 40000.0 + (t_pay - max_round_payout_cap) * 60.0 - nm_bonus
        elif allow_win_round and 0.0 < t_pay <= max_round_payout_cap:
          desired_pay = min(
              max_round_payout_cap,
              round_stake * (0.30 if high_stake_round else 0.65),
          )
          # Allow occasional full hits when within 50% profit budget
          full_bonus = -4.0 if (all_full and t_pay <= max_round_payout_cap) else 0.0
          penalty = abs(t_pay - desired_pay) - nm_bonus + full_bonus - 3.0
        else:
          # Suspenseful near-miss round (1-2 numbers short) while keeping house profitable
          penalty = t_pay * 20.0 - nm_bonus * 2.5 + abs(max_ratio - 0.65) * 2.0
        if best_score is None or penalty < best_score:
          best_score = penalty
          best_drawn = cand
      _, chosen_pay, _, _ = _score_drawn_for_entries(best_drawn, entries)
      HOUSE_TOTAL_STAKE = round(HOUSE_TOTAL_STAKE + round_stake, 2)
      HOUSE_TOTAL_PAID = round(HOUSE_TOTAL_PAID + chosen_pay, 2)
      save_persistent_state()
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
      payout = round(
          bet_amt * PAYTABLE.get(len(picks), {}).get(len(hits), 0.0), 2
      )
      entry["hits"] = hits
      entry["matches"] = len(hits)
      entry["payout"] = payout
      entry["settled"] = True
      u = get_u(entry["uid"])
      if payout > 0:
        u["balance"] = round(u["balance"] + payout, 2)
        TOP_WINNERS.append({
            "player": mask_uid(entry["uid"]),
            "amount": payout,
            "round": cycle_to_round_num(c_key),
            "ts": int(time.time()),
        })
        TOP_WINNERS.sort(key=lambda x: float(x.get("amount", 0)), reverse=True)
        if len(TOP_WINNERS) > 50:
          TOP_WINNERS[:] = TOP_WINNERS[:50]
      u["bets"].append({
          "round": cycle_to_round_num(c_key),
          "cycle": c_key,
          "picks": picks,
          "bet": bet_amt,
          "matches": len(hits),
          "payout": payout,
      })
    record_game_history(c_key, drawn)
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


ADMIN_USERNAME = (
    (os.environ.get("ADMIN_USERNAME") or "ethio_keno_play_26")
    .strip()
    .lstrip("@")
)
INTERNAL_DEST_HANDLE = ADMIN_USERNAME
INTERNAL_RESOLVED_CHAT_ID = ""
PENDING_DEPOSITS = {}


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


def notify_internal_kb(text, kb=None):
  target = resolve_internal_target()
  if not target:
    return False
  return tg(target, text, kb=kb)


def tg_photo(chat_id, photo_bytes, caption="", kb=None):
  if not BOT_TOKEN or not chat_id or not photo_bytes:
    return False
  data = {"chat_id": str(chat_id)}
  if caption:
    data["caption"] = caption
  if kb:
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


def notify_internal(text):
  primary = resolve_internal_target()
  if primary:
    return tg(primary, text)
  return False


def extract_tx_code(method, raw_text):
  txt = (raw_text or "").strip().upper()
  if not txt:
    return ""
  m_ft = re.search(r"\bFT[A-Z0-9]{6,18}\b", txt)
  if m_ft:
    return m_ft.group(0)
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
  if c in USED_TX or f"TX:{c}" in USED_TX:
    return "duplicate"
  if len(c) < 6:
    return "invalid"
  if m == "CBE":
    return "ok" if re.match(r"^FT[A-Z0-9]{6,18}$", c) else "invalid"
  return "ok" if re.match(r"^[A-Z0-9]{6,20}$", c) else "invalid"


def is_admin_user(uid, username=""):
  u_str = str(uid or "").strip()
  uname = (username or "").strip().lstrip("@").lower()
  resolved = str(resolve_internal_target() or "").strip().lstrip("@").lower()
  if (
      INTERNAL_DEST_HANDLE
      and uname == INTERNAL_DEST_HANDLE.strip().lstrip("@").lower()
  ):
    return True
  if resolved and u_str.lower() == resolved:
    return True
  return False


def announcement_inline_kb(target_uid):
  base_url = current_base_url()
  app_url = f"{base_url}/?uid={target_uid}"
  bot_uname = get_bot_username() or "ethio_keno_play_26_bot"
  channel_handle = (
      SUPPORT_HANDLE or INTERNAL_DEST_HANDLE or "ethio_keno_play_26"
  ).lstrip("@")
  return {
      "inline_keyboard": [
          [{"text": "🎮 Play Now", "web_app": {"url": app_url}}],
          [
              {"text": "🤖 Open Bot", "url": f"https://t.me/{bot_uname}"},
              {"text": "📢 Channel", "url": f"https://t.me/{channel_handle}"},
          ],
      ]
  }


def broadcast_announcement(text="", photo_bytes=None, exclude_uid=""):
  sent_count = 0
  for target_uid in list(USERS.keys()):
    t_str = str(target_uid).strip()
    if not t_str or (exclude_uid and t_str == str(exclude_uid).strip()):
      continue
    kb = announcement_inline_kb(t_str)
    ok = False
    if photo_bytes:
      ok = tg_photo(t_str, photo_bytes, caption=text or "📢 Announcement", kb=kb)
    elif text:
      ok = tg(t_str, text, kb=kb)
    if ok:
      sent_count += 1
  return sent_count


RECEIPT_VERIFY_URL = (os.environ.get("RECEIPT_VERIFY_URL") or "").strip()


def _extract_sms_dates_eat(raw_text):
  found_dates = []
  for y, m, d in re.findall(
      r"\b(20\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])\b",
      raw_text,
  ):
    try:
      found_dates.append(datetime(int(y), int(m), int(d)).date())
    except ValueError:
      pass
  for d, m, y in re.findall(
      r"\b(0?[1-9]|[12]\d|3[01])[-/](0?[1-9]|1[0-2])[-/](20\d{2}|\d{2})\b",
      raw_text,
  ):
    yr = int(y) + 2000 if len(y) == 2 else int(y)
    try:
      found_dates.append(datetime(yr, int(m), int(d)).date())
    except ValueError:
      pass
  month_map = {
      "JAN": 1, "JANUARY": 1, "FEB": 2, "FEBRUARY": 2, "MAR": 3, "MARCH": 3,
      "APR": 4, "APRIL": 4, "MAY": 5, "JUN": 6, "JUNE": 6, "JUL": 7, "JULY": 7,
      "AUG": 8, "AUGUST": 8, "SEP": 9, "SEPT": 9, "SEPTEMBER": 9,
      "OCT": 10, "OCTOBER": 10, "NOV": 11, "NOVEMBER": 11, "DEC": 12, "DECEMBER": 12,
  }
  for m_txt, d_txt, y_txt in re.findall(
      r"\b([A-Za-z]{3,9})\s+(0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?,?\s+(20\d{2})\b",
      raw_text,
  ):
    mo = month_map.get(m_txt.upper())
    if mo:
      try:
        found_dates.append(datetime(int(y_txt), mo, int(d_txt)).date())
      except ValueError:
        pass
  for d_txt, m_txt, y_txt in re.findall(
      r"\b(0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\s+([A-Za-z]{3,9}),?\s+(20\d{2})\b",
      raw_text,
  ):
    mo = month_map.get(m_txt.upper())
    if mo:
      try:
        found_dates.append(datetime(int(y_txt), mo, int(d_txt)).date())
      except ValueError:
        pass
  return found_dates


def _has_time_marker(raw_text):
  return bool(
      re.search(
          r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?:\s*(?:AM|PM))?\b",
          raw_text,
          re.I,
      )
  )


def fetch_receipt_link_details(raw_sms):
  m_url = re.search(r"https?://\S+", raw_sms or "", re.I)
  if not m_url:
    return None, ""
  receipt_url = m_url.group(0).strip().rstrip(".,;)")
  try:
    resp = requests.get(
        receipt_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"}
    )
    if not resp.ok or not resp.text:
      return None, f"Receipt link could not be fetched (status {resp.status_code})."
    plain = re.sub(r"<[^>]+>", " ", resp.text)
    plain = re.sub(r"\s+", " ", plain).strip()
    return {"url": receipt_url, "text": plain}, ""
  except Exception as e:
    return None, f"Could not open receipt link online ({str(e)[:80]})."


def verify_sms_strict(method, raw_sms, expected_amt):
  txt = (raw_sms or "").strip()
  up = txt.upper()
  tb_num, tb_owner = split_account_and_name(TELEBIRR_ACCOUNT, TELEBIRR_NAME)
  cbe_num, cbe_owner = split_account_and_name(CBE_ACCOUNT, CBE_NAME)

  target_acc = (tb_num if method == "Telebirr" else cbe_num).strip()
  target_owner = (
      (tb_owner if method == "Telebirr" else cbe_owner).strip().lower()
  )

  scam_markers = [
      "FAKE RECEIPT", "PHISHING", "TEST PAYMENT", "SIMULATED",
      "SCRAMBLER", "FORWARDED", "DEMO", "SAMPLE"
  ]
  if any(s in up for s in scam_markers):
    return "rejected", "Suspicious or spoofed payment text detected."

  has_payment_context = any(
      k in up
      for k in [
          "TELEBIRR", "ETHIO TELECOM", "TRANSACTION NUMBER", "TRANSACTION ID",
          "COMMERCIAL BANK OF ETHIOPIA", "CBE", "DEBITED", "TRANSFERRED",
          "PAID TO", "RECEIVED", "CREDITED", "ETB", "BIRR", "ACCT", "ACCOUNT",
          "APPS.CBE.COM.ET", "RECEIPT", "HTTPS://", "HTTP://",
      ]
  )
  if not has_payment_context:
    return "rejected", "Official confirmation SMS or receipt link is missing."

  is_cbe_text = (
      "CBE" in up
      or "COMMERCIAL BANK OF ETHIOPIA" in up
      or "APPS.CBE.COM.ET" in up
      or re.search(r"\bFT[A-Z0-9]{6,18}\b", up) is not None
  )
  is_tb_text = "TELEBIRR" in up or "ETHIO TELECOM" in up
  if method == "CBE" and is_tb_text and not is_cbe_text:
    return "rejected", "CBE is selected, but the message is from Telebirr."
  if method == "Telebirr" and is_cbe_text and not is_tb_text:
    return "rejected", "Telebirr is selected, but the message is from CBE."

  url_match = re.search(r"https?://\S+", txt, re.I)
  fetched = None
  fetch_err = ""
  if url_match:
    raw_url = url_match.group(0).strip().rstrip(".,;)")
    low_url = raw_url.lower()
    if method == "CBE" and "cbe.com.et" not in low_url:
      return "rejected", "Untrusted or non-CBE receipt link provided."
    if method == "Telebirr" and (
        "ethiotelecom" not in low_url and "telebirr" not in low_url
    ):
      return "rejected", "Untrusted or non-Telebirr receipt link provided."
    fetched, fetch_err = fetch_receipt_link_details(txt)
    if fetched is None:
      return "needs_review", f"Receipt link check required ({fetch_err})."

  combined_text = txt
  if fetched and fetched.get("text"):
    combined_text = f"{txt}\n{fetched['text']}"
  comb_up = combined_text.upper()

  today_eat = datetime.now(EAT).date()
  dates_found = _extract_sms_dates_eat(combined_text)
  if not dates_found:
    return "rejected", "Transaction date is missing from the SMS/receipt. Yesterday's or undated messages are not accepted."
  if any(dt != today_eat for dt in dates_found):
    return "rejected", f"Transaction date does not match today's date ({today_eat.isoformat()} EAT). Old or yesterday's SMS cannot be reused."
  if not _has_time_marker(combined_text):
    return "rejected", "Transaction time is missing from the SMS/receipt."

  acc_digits = re.sub(r"\D", "", target_acc)
  acc_matched = False
  url_suffix_matches = re.findall(r"[?&/]([0-9]{6,13})\b", txt)
  for suf in url_suffix_matches:
    if acc_digits.endswith(suf) or suf.endswith(acc_digits[-8:]):
      acc_matched = True
      break

  body_without_urls = re.sub(r"https?://\S+", " ", combined_text)
  body_digits = re.sub(r"\D", "", body_without_urls)
  if (
      not acc_matched
      and acc_digits
      and len(acc_digits) >= 6
      and acc_digits in body_digits
  ):
    acc_matched = True
  if not acc_matched and len(acc_digits) >= 8:
    if acc_digits[-4:] in body_digits and (
        "*" in body_without_urls or "X" in body_without_urls.upper()
    ):
      acc_matched = True

  owner_matched = False
  if target_owner and len(target_owner) >= 4:
    name_parts = [p for p in re.split(r"\s+", target_owner) if len(p) >= 3]
    if name_parts and all(part in combined_text.lower() for part in name_parts):
      owner_matched = True

  if not (acc_matched and owner_matched):
    return (
        "rejected",
        f"Both receiver account ({target_acc}) and account name ({target_owner.title()}) must match our {method} account.",
    )

  if (
      any(
          k in up
          for k in [
              "PAID TO ",
              "TRANSFERRED TO ",
              "DEBITED WITH ",
              "SENT TO ",
          ]
      )
      and not acc_matched
  ):
    return "rejected", "Outgoing payment does not match our receiving account."

  amt_matches = re.findall(
      r"(?:ETB|BIRR)\s*([0-9,]+(?:\.[0-9]{1,2})?)|([0-9,]+(?:\.[0-9]{1,2})?)\s*(?:ETB|BIRR)",
      comb_up,
  )
  found_amounts = []
  for g1, g2 in amt_matches:
    raw_num = (g1 or g2 or "").replace(",", "").strip()
    if raw_num:
      try:
        found_amounts.append(float(raw_num))
      except ValueError:
        pass
  if not found_amounts:
    return "rejected", f"Amount was not found in the SMS/receipt ({float(expected_amt):.2f} ETB required)."
  if not any(abs(x - float(expected_amt)) < 0.01 for x in found_amounts):
    return "rejected", f"Amount in SMS/receipt does not match requested {float(expected_amt):.2f} ETB."

  return "verified", ""


def verify_external_receipt_if_configured(method, tx_code, raw_sms, expected_amt):
  if not RECEIPT_VERIFY_URL:
    return "verified", ""
  try:
    resp = requests.post(
        RECEIPT_VERIFY_URL,
        json={
            "method": method,
            "tx": tx_code,
            "sms_text": raw_sms,
            "expected_amount": float(expected_amt),
            "telebirr_account": TELEBIRR_ACCOUNT,
            "cbe_account": CBE_ACCOUNT,
        },
        timeout=8,
    )
    if resp.ok:
      data = resp.json() if resp.content else {}
      if data.get("verified") is False:
        return (
            "rejected",
            data.get("reason")
            or "External receipt verification rejected this transaction.",
        )
      if "amount" in data and data["amount"] is not None:
        try:
          if abs(float(data["amount"]) - float(expected_amt)) >= 0.01:
            return (
                "rejected",
                f"Receipt verified amount ({float(data['amount']):.2f} ETB) does not match requested deposit ({float(expected_amt):.2f} ETB).",
            )
        except ValueError:
          pass
  except Exception:
    return (
        "needs_review",
        "External receipt check timed out; flagged for admin check.",
    )
  return "verified", ""


PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ETHIO FAST KENO</title><script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}body{margin:0;font-family:Arial,sans-serif;background:#0e1116;color:#f3f4f6;padding-bottom:64px;-webkit-user-select:text;user-select:text;overflow-x:hidden}.box,.acct-card,.tcard,.sub,.top,p,div,span{ -webkit-user-select:text;user-select:text }button,.nb,.t,.btn,.betbtn,.copy-btn,.act,.appb{-webkit-user-select:none;user-select:none;touch-action:manipulation}input,textarea,select{-webkit-user-select:text;user-select:text;touch-action:manipulation}
.top{display:flex;justify-content:space-between;align-items:center;padding:10px 12px;background:#171b22;border-bottom:1px solid #262c36}
.pill{background:#222834;padding:5px 10px;border-radius:99px;font-size:12px;font-weight:700;color:#4ade80}
.sub{display:flex;justify-content:space-between;align-items:center;padding:7px 12px;background:#13171d;font-size:12px;color:#9ca3af}
.wbar{display:flex;align-items:center;gap:8px;padding:7px 10px;background:linear-gradient(90deg,#111827 0%,#0f172a 50%,#111827 100%);border-bottom:1px solid #262e3d;font-size:12px;overflow:hidden;position:relative}
.wbadge{background:linear-gradient(135deg,#f59e0b,#d97706);color:#111827;font-weight:900;padding:5px 9px;border-radius:7px;white-space:nowrap;font-size:11px;z-index:2;flex-shrink:0}
.wmarquee{flex:1;overflow:hidden;white-space:nowrap;position:relative;min-width:0}
.wtrack{display:inline-flex;align-items:center;white-space:nowrap;will-change:transform;animation:wscrollAnim 38s linear infinite}
.wset{display:inline-flex;align-items:center;gap:10px;padding-right:10px;flex-shrink:0}
@keyframes wscrollAnim{0%{transform:translate3d(0,0,0)}100%{transform:translate3d(-50%,0,0)}}
.witem{display:inline-flex;align-items:center;gap:6px;background:#161d29;border:1px solid #2b3548;padding:4px 10px;border-radius:8px;color:#f8fafc;font-size:12px;font-weight:700;flex-shrink:0}
.witem .rk{color:#fbbf24;font-weight:900}.witem .pid{color:#9ca3af;font-weight:700}.witem .amt{color:#4ade80;font-weight:900}
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
.nav{position:fixed;bottom:0;left:0;right:0;height:54px;background:#161a21;border-top:1px solid #262c36;display:grid;grid-template-columns:repeat(4,1fr)}
.nb{background:none;border:none;color:#9ca3af;font-weight:700;font-size:11px}.nb.active{color:#4ade80}
</style></head><body>
<div class="top"><strong style="color:#4ade80">⚡ ETHIO FAST KENO</strong><div class="pill">Balance: <span id="bal">0.00</span> ETB</div></div>
<div class="wbar"><span class="wbadge">🏆 TOP WINNERS</span><div class="wmarquee"><div class="wtrack" id="top-winners-bar"><span class="witem">Loading top winners...</span></div></div></div>
<div class="sub"><div>Picks: <strong id="cnt">0</strong>/10 | ID: <strong id="uid-lbl">-</strong></div><div class="tm" id="tm">01:00</div></div>

<div id="p-game" class="panel active">
  <div class="stage">
    <div style="font-size:11px;color:#9ca3af;margin-bottom:6px">Drawn Numbers: <strong id="dprog">0 / 20</strong> | Max Win: <strong id="mwin" style="color:#4ade80">0.00 ETB</strong></div>
    <div class="ball" id="ball">--</div>
    <div class="strip" id="strip"></div>
  </div>
  <div id="out-banner" class="banner"></div>
  <div id="board-wrap">
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
      <button class="btn" onclick="setBetVal(10)">10 ETB</button>
      <button class="btn" onclick="setBetVal(50)">50 ETB</button>
      <button class="btn" onclick="setBetVal(100)">100 ETB</button>
    </div>
    <button class="betbtn" id="betbtn" onclick="lockBet()">PLACE BET</button>
  </div>
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

<div id="p-hist" class="panel">
  <div class="box"><strong>💳 Deposit History (Last 20)</strong><div id="deplist">No deposits yet.</div></div>
  <div class="box"><strong>💸 Withdraw History (Last 20)</strong><div id="hwlist">No withdraw history yet.</div></div>
  <div class="box"><strong>🎟️ Ticket / Bet History (Last 20)</strong><div id="hlist">No bet history yet.</div></div>
  <div class="box"><strong>🎲 Drawn Numbers History (Last 20 Rounds)</strong><div id="ghlist">No completed rounds yet.</div></div>
</div>

<div id="p-wallet" class="panel">
  <div class="box">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <strong style="font-size:16px">💳 Deposit</strong>
      <span style="background:#1e293b;color:#fbbf24;padding:3px 9px;border-radius:99px;font-size:11px;font-weight:800">● Awaiting payment</span>
    </div>
    <div style="font-size:11px;color:#9ca3af;margin-top:4px">Approval Hours: <b style="color:#4ade80">07:00 AM – 01:00 AM EAT</b> (ጠዋት 1 ሰዓት – ሌሊት 7 ሰዓት). Deposits sent after hours are accepted & approved at <b>07:00 AM EAT (ጠዋት 1 ሰዓት)</b>.</div>
    <div id="dep-step1">
      <select id="dm"><option value="Telebirr">Telebirr</option><option value="CBE">CBE</option></select>
      <input type="number" id="da" placeholder="Enter amount (min 50 ETB)" min="50" step="any">
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
        <div style="font-size:10px;color:#64748b;margin-top:2px">Example Transaction ID: FT26328XXXX / DKK8FX6QR6</div>
        <textarea id="dt" rows="3" placeholder="Copy & paste confirmation SMS or receipt link (text only, no screenshot)..." style="width:100%;padding:9px;margin:7px 0 4px;border-radius:8px;border:1px solid #374151;background:#111317;color:#fff;font-family:inherit;resize:vertical"></textarea>
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
    <input type="number" id="wa" placeholder="Withdraw amount (min 200 ETB)" min="200" value="200">
    <select id="wm"><option value="Telebirr">Telebirr</option><option value="CBE">CBE</option></select>
    <input type="text" id="wd" placeholder="Account number & full name (e.g. 09... / 1000... - Name)">
    <button class="act amb" onclick="wdr()">Request Withdraw</button>
    <div id="wmsg" style="margin-top:6px;color:#fcd34d"></div>
  </div>
  <div class="box"><strong>⏳ Withdraw Status</strong><div id="wlist">No withdraw requests yet.</div></div>
</div>

<div id="p-rules" class="panel">
  <div class="box">
    <strong>📜 Game Rules & Payout Table</strong>
    <p style="margin:6px 0">Payouts follow the multiplier table below. Pick 1 to 10 numbers; your stake is multiplied based on how many of your picks match the 20 drawn numbers.</p>
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

<div class="nav">
  <button type="button" class="nb active" id="n-game" onclick="tab('game')">Game</button>
  <button type="button" class="nb" id="n-hist" onclick="tab('hist')">History</button>
  <button type="button" class="nb" id="n-wallet" onclick="tab('wallet')">Wallet</button>
  <button type="button" class="nb" id="n-rules" onclick="tab('rules')">Rules</button>
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
  const cur=Number(bet)||2;
  if(Number(d)>0){
    if(cur<10)setBetVal(cur+2);
    else if(cur<100)setBetVal(cur+10);
    else setBetVal(cur+100);
  }else{
    if(cur>100)setBetVal(Math.max(100,cur-100));
    else if(cur>10)setBetVal(Math.max(10,cur-10));
    else setBetVal(Math.max(2,cur-2));
  }
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
  const scrollX=window.scrollX,scrollY=window.scrollY;
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(txt).catch(()=>{});}
  const ta=document.createElement("textarea");
  ta.value=txt;
  ta.setAttribute("readonly","");
  ta.style.position="fixed";
  ta.style.left="-9999px";
  ta.style.top="0";
  ta.style.opacity="0";
  document.body.appendChild(ta);
  try{ta.select({preventScroll:true});}catch(e){try{ta.select();}catch(e2){}}
  try{document.execCommand("copy");}catch(e){}
  document.body.removeChild(ta);
  window.scrollTo(scrollX,scrollY);
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
let depositOpenNow=true;
function showDepositStep2(){
  const amt=Number(document.getElementById("da").value||0);
  if(!amt||amt<50)return alert("Minimum deposit is 50 ETB.");
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
function calcTicketMaxWin(tk){
  if(typeof tk.max_win==="number" && tk.max_win>0)return tk.max_win;
  const tbl=PT[(tk.picks||[]).length]||{};
  const mx=Math.max(0,...Object.values(tbl));
  return Number(tk.bet||0)*mx;
}
function renderTickets(){
  const wrap=document.getElementById("tickets-list");
  document.getElementById("tcount").textContent=tickets.length;
  if(!tickets.length){wrap.innerHTML='<div style="color:#9ca3af;margin-top:6px">No tickets placed in this round yet.</div>';return;}
  wrap.innerHTML=tickets.map(tk=>{
    const potWin=calcTicketMaxWin(tk);
    let stHtml=`<span style="color:#4ade80;font-weight:800">Win: ${potWin.toFixed(2)} ETB</span> | <span class="st-wait">Pending</span>`;
    let cls="tcard";
    if(roundDone){
      if(Number(tk.payout||0)>0){stHtml=`<span class="st-win">Won ${Number(tk.payout).toFixed(2)} ETB</span>`;cls+=" won-card";}
      else{stHtml=`<span style="color:#9ca3af">Max: ${potWin.toFixed(2)} ETB</span> | <span class="st-lose">Please try again</span>`;}
    }
    return `<div class="${cls}">
      <div class="tcard-top"><span><b>${tk.player}</b> • Bet <b>${Number(tk.bet).toFixed(0)} ETB</b></span><span>${stHtml}</span></div>
      <div class="tnums">${tk.picks.map(n=>`<span class="tnum${drawnSoFar.has(n)?" matched":""}">${n}</span>`).join("")}</div>
    </div>`;
  }).join("");
}
async function load(){
  try{
    const r=await fetch(`/api/state?uid=${encodeURIComponent(uid)}`);
    const d=await r.json();
    bal=d.balance;
    if(typeof d.deposit_open==="boolean"){depositOpenNow=d.deposit_open;}
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
      if(cInfo.phase==="drawing" && Number(d.cycle_num)===cInfo.cycleNum){
        tickets=d.tickets||[];
        runRoundDraw(cInfo.cycleNum, true);
      }else{
        drawnSoFar.clear();
        roundDone=false;
        tickets=(Number(d.cycle_num)===cInfo.cycleNum && cInfo.phase==="betting")?(d.tickets||[]):[];
        document.getElementById("bal").textContent=bal.toFixed(2);
      }
    }
    renderTickets();
    const twBar=document.getElementById("top-winners-bar");
    if(twBar && Array.isArray(d.top_winners) && d.top_winners.length){
      const singleSet=d.top_winners.map((w,idx)=>`<span class="witem"><span class="rk">#${idx+1}</span> ID <span class="pid">${w.player}</span> won <span class="amt">${Number(w.amount||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})} ETB</span></span>`).join("");
      const newHtml=`<span class="wset">${singleSet}</span><span class="wset">${singleSet}</span>`;
      if(twBar.dataset.rendered!==newHtml){
        twBar.dataset.rendered=newHtml;
        twBar.innerHTML=newHtml;
      }
    }
    const depArr=(d.deposits||[]).slice(-20).reverse();
    document.getElementById("deplist").innerHTML=depArr.length?depArr.map(x=>`<div style="padding:5px 0;border-bottom:1px solid #232934"><b>${Number(x.amount||0).toFixed(2)} ETB</b> | ${x.method} | ${x.tx} | ${x.date_label||""}</div>`).join(""):"No deposits yet.";
    const wdHistArr=(d.wds||[]).slice(-20).reverse();
    const hwEl=document.getElementById("hwlist");
    if(hwEl)hwEl.innerHTML=wdHistArr.length?wdHistArr.map(w=>`<div style="padding:5px 0;border-bottom:1px solid #232934">${w.id} | <b>${Number(w.amount||0).toFixed(2)} ETB</b> | ${w.method} (${w.dest}) | <b>${w.status}</b></div>`).join(""):"No withdraw history yet.";
    const betArr=(d.bets||[]).slice(-20).reverse();
    document.getElementById("hlist").innerHTML=betArr.length?betArr.map(x=>`<div style="padding:6px 0;border-bottom:1px solid #232934"><div>Round #${x.round||x.cycle||"-"} | Bet: <b>${x.bet} ETB</b> | Matches: <b>${x.matches}</b> | Win: <b style="color:#4ade80">${x.payout} ETB</b></div>${(x.picks&&x.picks.length)?`<div style="margin-top:3px;font-size:11px;color:#9ca3af">Picks: ${x.picks.join(", ")}</div>`:""}</div>`).join(""):"No bet history yet.";
    const ghArr=(d.game_history||[]).slice(0,20);
    document.getElementById("ghlist").innerHTML=ghArr.length?ghArr.map(g=>`<div style="padding:7px 0;border-bottom:1px solid #232934"><div style="color:#4ade80;font-weight:800;margin-bottom:4px">Round #${g.round} <span style="color:#9ca3af;font-weight:400">(${(g.drawn||[]).length} numbers)</span></div><div style="display:flex;flex-wrap:wrap;gap:4px">${(g.drawn||[]).map(n=>`<span class="tnum">${n}</span>`).join("")}</div></div>`).join(""):"No completed rounds yet.";
    document.getElementById("wlist").innerHTML=d.wds.length?d.wds.slice().reverse().map(w=>`<div style="padding:6px 0;border-bottom:1px solid #2b303b">${w.id} | ${w.method} (${w.dest}) | ${w.amount} ETB | <b>${w.status}</b>${w.status==="Pending"?`<br><button class="appb" onclick="appw('${w.id}')">Approve (Complete)</button>`:""}</div>`).join(""):"No withdraw requests yet.";
  }catch(e){}
}
function clearSelectionsAndBoard(){picks.clear();document.querySelectorAll(".t").forEach(x=>x.classList.remove("sel"));ui();}
function setBoardVisible(show){const bw=document.getElementById("board-wrap");if(bw)bw.style.display=show?"block":"none";}
function resetDrawStage(){drawnSoFar.clear();roundDone=false;tickets=[];document.getElementById("strip").innerHTML="";document.getElementById("dprog").textContent="0 / 20";document.getElementById("ball").textContent="--";const bn=document.getElementById("out-banner");bn.className="banner";bn.textContent="";renderTickets();}
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

async function runRoundDraw(targetCycle, allowResync){
  if(drawing)return;
  const cNum=(typeof targetCycle==="number")?targetCycle:calcGlobalCycleInfo().cycleNum;
  if(lastDrawnCycle===cNum && !allowResync)return;
  const isResync=(lastDrawnCycle===cNum && Boolean(allowResync));
  lastDrawnCycle=cNum;
  drawing=true;
  setBoardVisible(false);
  if(!isResync){
    resetDrawStage();
  }
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

  for(let i=alreadyCount;i<drawnArr.length;i++){
    const cNow=calcGlobalCycleInfo();
    if(cNow.phase==="betting" && cNow.cycleNum!==cNum)break;
    const targetElapsed=i * stepSec;
    while(true){
      const tickNow=calcGlobalCycleInfo();
      if(tickNow.phase==="betting" && tickNow.cycleNum!==cNum)break;
      if(tickNow.cycleNum!==cNum || tickNow.drawElapsedSec >= targetElapsed - 0.05)break;
      const waitMs=Math.min(200, Math.max(40, (targetElapsed - tickNow.drawElapsedSec)*1000));
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
    const suspMsg = (pay <= 0 && mt > 0)
      ? ` <span style="color:#fbbf24">(So close! ${mt}/${activeBet.picks.length} matched!)</span>`
      : (pay <= 0 ? ` <span style="color:#9ca3af">(Next round could hit!)</span>` : "");
    document.getElementById("gmsg").innerHTML=`<b>Matches (${mt}):</b> ${hList.join(", ")||"None"} | <b>Win:</b> ${pay.toFixed(2)} ETB${suspMsg}`;
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
  setBoardVisible(true);
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
      setBoardVisible(true);
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
      already_claimed = bool(
          u.get("registered")
          or u.get("bonus_claimed")
          or u.get("claimed_10_bonus")
          or uid in CLAIMED_BONUS_USERS
      )
      if not already_claimed:
        u["registered"] = True
        u["bonus_claimed"] = True
        u["claimed_10_bonus"] = True
        CLAIMED_BONUS_USERS.add(uid)
        u["balance"] = round(float(u.get("balance", 0.0) or 0.0) + 10.0, 2)
        inviter_id = (u.get("referred_by") or REFERRED_USERS.get(uid) or "").strip()
        if (
            inviter_id
            and inviter_id != uid
            and not u.get("ref_rewarded")
        ):
          u["ref_rewarded"] = True
          inv_u = get_u(inviter_id)
          inv_u["balance"] = round(inv_u["balance"] + 10.0, 2)
          inv_u["referrals"] = int(inv_u.get("referrals", 0)) + 1
          tg(
              inviter_id,
              f"🎉 Your friend registered for the first time via your referral link!\n🎁 You received a one-time 10.00 ETB referral bonus. Total referrals: {inv_u['referrals']} | Balance: {inv_u['balance']:.2f} ETB",
          )
        save_persistent_state()
        tg_answer_cb(cb_id, "Registration complete! 10.00 ETB one-time bonus credited.")
        ref_status = "Yes (+10.00 ETB credited to inviter)" if (u.get("ref_rewarded")) else "No"
        tg(
            uid,
            "✅ Registration Verified & Completed!\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 User ID: {uid}\n"
            "🎁 Welcome Bonus: +10.00 ETB\n"
            f"🤝 Referral Bonus Applied: {ref_status}\n"
            f"💰 Current Balance: {u['balance']:.2f} ETB\n"
            "🎮 Tap 'Play' below to start playing!",
            main_reply_kb(uid, base_url),
        )
      else:
        u["registered"] = True
        u["bonus_claimed"] = True
        CLAIMED_BONUS_USERS.add(uid)
        u["referred_by"] = ""
        REFERRED_USERS.pop(uid, None)
        save_persistent_state()
        tg_answer_cb(cb_id, "Already registered! No bonus available.")
        tg(
            uid,
            f"ℹ️ You are already registered. No welcome or referral bonus is granted for already-registered accounts.\n💰 Your Balance: {u['balance']:.2f} ETB",
            main_reply_kb(uid, base_url),
        )
    elif data.startswith("approve_dep:"):
      did = data.split(":", 1)[1].strip()
      dep_obj = PENDING_DEPOSITS.get(did)
      if dep_obj and dep_obj.get("status") in ("Pending", "Scheduled (07:00 AM EAT)"):
        dep_obj["status"] = "Approved"
        target_uid = dep_obj["uid"]
        amt = float(dep_obj["amount"])
        tx = dep_obj["tx"]
        m = dep_obj["method"]
        u = get_u(target_uid)
        USED_TX.add(tx)
        USED_TX.add(f"TX:{tx}")
        if dep_obj.get("url_key"):
          USED_TX.add(dep_obj["url_key"])
        u["invalid_shots"] = 0
        u["registered"] = True
        u["balance"] = round(u["balance"] + amt, 2)
        u["deposits"].append({
            "amount": amt,
            "method": m,
            "tx": tx,
            "date_label": datetime.now(EAT).strftime("%Y-%m-%d %H:%M"),
            "status": "Approved",
        })
        record_house_financial_event("DEPOSIT", amt, f"Customer: {target_uid} | Method: {m} | Ref: {tx}")
        tg_answer_cb(cb_id, f"✅ Deposit {did} approved ({amt:.2f} ETB).")
        tg(
            target_uid,
            f"✅ Deposit Approved! {amt:.2f} ETB via {m} ({tx}) has been added to your balance.\n💰 New Balance: {u['balance']:.2f} ETB",
            main_reply_kb(target_uid, base_url),
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
                        f"✅ Deposit Approved by @{INTERNAL_DEST_HANDLE}\n"
                        f"ID: {did}\n"
                        f"Customer ID: {target_uid}\n"
                        f"Method: {m}\n"
                        f"Ref: {tx}\n"
                        f"Amount: {amt:.2f} ETB"
                    ),
                },
                timeout=8,
            )
          except Exception:
            pass
      else:
        tg_answer_cb(cb_id, "Deposit already processed or not found.")
    elif data.startswith("reject_dep:"):
      did = data.split(":", 1)[1].strip()
      dep_obj = PENDING_DEPOSITS.get(did)
      if dep_obj and dep_obj.get("status") in ("Pending", "Scheduled (07:00 AM EAT)"):
        dep_obj["status"] = "Rejected"
        target_uid = dep_obj["uid"]
        amt = float(dep_obj["amount"])
        tx = dep_obj["tx"]
        m = dep_obj["method"]
        tg_answer_cb(cb_id, f"❌ Deposit {did} rejected.")
        tg(
            target_uid,
            f"❌ Deposit Rejected! Your {amt:.2f} ETB ({m} / {tx}) deposit could not be verified by admin.",
            main_reply_kb(target_uid, base_url),
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
                        f"❌ Deposit Rejected by @{INTERNAL_DEST_HANDLE}\n"
                        f"ID: {did}\n"
                        f"Customer ID: {target_uid}\n"
                        f"Method: {m}\n"
                        f"Ref: {tx}\n"
                        f"Amount: {amt:.2f} ETB"
                    ),
                },
                timeout=8,
            )
          except Exception:
            pass
      else:
        tg_answer_cb(cb_id, "Deposit already processed or not found.")
    elif data.startswith("approve_wd:"):
      wid = data.split(":", 1)[1].strip()
      w = WITHDRAWALS.get(wid)
      if w:
        w["status"] = "Completed"
        for item in get_u(w["uid"])["wds"]:
          if item["id"] == wid:
            item["status"] = "Completed"
        save_persistent_state()
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
    cap_low = caption.lower()
    if is_admin_user(uid, sender_username) and (
        cap_low.startswith("/broadcast")
        or cap_low.startswith("/post")
        or "#post" in cap_low
        or "#broadcast" in cap_low
    ):
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
        clean_cap = re.sub(r"(?i)^/(broadcast|post)\s*", "", caption)
        clean_cap = re.sub(r"(?i)#(broadcast|post)", "", clean_cap).strip()
        cnt = broadcast_announcement(text=clean_cap, photo_bytes=img_bytes, exclude_uid=uid)
        tg(uid, f"📢 Announcement sent to {cnt} users.", main_reply_kb(uid, base_url))
      return jsonify({"ok": True})

    tg(
        uid,
        "❌ Screenshots are not accepted. Please copy and paste your official payment SMS or receipt link in Wallet -> Deposit (text only).",
        main_reply_kb(uid, base_url),
    )
    return jsonify({"ok": True})

  if not text:
    return jsonify({"ok": True})

  u = get_u(uid)
  if text.startswith("/start"):
    parts = text.split(maxsplit=1)
    already_registered = bool(
        u.get("registered")
        or u.get("bonus_claimed")
        or u.get("claimed_10_bonus")
        or uid in CLAIMED_BONUS_USERS
    )
    if already_registered:
      u["registered"] = True
      u["bonus_claimed"] = True
      u["claimed_10_bonus"] = True
      CLAIMED_BONUS_USERS.add(uid)
      save_persistent_state()
    elif len(parts) == 2 and parts[1].strip().startswith("ref_"):
      inviter_id = parts[1].strip()[4:].strip()
      if (
          inviter_id
          and inviter_id != uid
          and not u.get("referred_by")
          and uid not in REFERRED_USERS
          and not u.get("ref_rewarded")
      ):
        u["referred_by"] = inviter_id
        REFERRED_USERS[uid] = inviter_id
        save_persistent_state()
    if not already_registered:
      ref_note = (
          "\n🎁 You joined via a referral link! Complete registration below to claim your 10.00 ETB bonus."
          if (u.get("referred_by") or REFERRED_USERS.get(uid))
          else ""
      )
      tg(
          uid,
          "Welcome to ETHIO FAST KENO!\n"
          "━━━━━━━━━━━━━━━━━━━━\n"
          "Please register first to activate your account and claim your one-time 10.00 ETB welcome bonus."
          + ref_note,
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
          "Welcome back to ETHIO FAST KENO!\n"
          "━━━━━━━━━━━━━━━━━━━━\n"
          f"👤 User ID: {uid}\n"
          "✅ Status: Registered\n"
          f"💰 Balance: {u['balance']:.2f} ETB\n"
          "🎮 Tap 'Play' below to open the game.",
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
    bot_info_user = get_bot_username() or "ethio_keno_play_26_bot"
    ref_link = f"https://t.me/{bot_info_user}?start=ref_{uid}"
    share_url = (
        "https://t.me/share/url?"
        + requests.compat.urlencode({
            "url": ref_link,
            "text": "Join ETHIO FAST KENO and register to get a 10 ETB bonus!",
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
        "🚀 Invite your friends!\n\n"
        "When your friend opens this link, taps Start, and completes registration:\n"
        "• Your friend gets a 10.00 ETB welcome bonus\n"
        "• You get a 10.00 ETB referral bonus\n\n"
        f"Your Referral Link:\n{ref_link}",
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
          "max_win": round(
              float(e["bet"]) * max(PAYTABLE.get(len(e["picks"]), {}).values() or [0.0]),
              2,
          ),
          "payout": e["payout"] if show_result else 0.0,
      }
      for e in entries[-25:]
  ]
  my_entry = next((e for e in reversed(entries) if e["uid"] == uid), None)

  prev_cycle = c_num - 1
  if prev_cycle >= 0 and prev_cycle not in SETTLED_ROUNDS:
    settle_cycle_if_needed(prev_cycle)

  return jsonify({
      "balance": u["balance"],
      "registered": u["registered"],
      "round_num": cycle_to_round_num(c_num),
      "deposits": u.get("deposits", [])[-20:],
      "bets": u.get("bets", [])[-20:],
      "game_history": list(reversed(GAME_HISTORY[-20:])),
      "top_winners": get_top_winners_feed(),
      "tickets": public_tickets,
      "my_ticket": my_entry,
      "drawn": drawn[:shown_cnt],
      "full_drawn": drawn if show_result else drawn[:shown_cnt],
      "shown_count": shown_cnt,
      "show_result": show_result,
      "wds": list(WITHDRAWALS.values()) if adm else u["wds"],
      "deposit_open": is_deposit_hours(),
      "deposit_hours_label": "07:00 AM – 01:00 AM EAT (ጠዋት 1 ሰዓት – ሌሊት 7 ሰዓት)",
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
          "max_win": round(
              float(e["bet"]) * max(PAYTABLE.get(len(e["picks"]), {}).values() or [0.0]),
              2,
          ),
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
          "max_win": round(
              float(e["bet"]) * max(PAYTABLE.get(len(e["picks"]), {}).values() or [0.0]),
              2,
          ),
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


RECEIPT_VERIFY_URL = (os.environ.get("RECEIPT_VERIFY_URL") or "").strip()


def verify_external_receipt_if_configured(method, tx_code, raw_sms, expected_amt):
  if not RECEIPT_VERIFY_URL:
    return "verified", ""
  try:
    resp = requests.post(
        RECEIPT_VERIFY_URL,
        json={
            "method": method,
            "tx": tx_code,
            "sms_text": raw_sms,
            "expected_amount": float(expected_amt),
            "telebirr_account": TELEBIRR_ACCOUNT,
            "cbe_account": CBE_ACCOUNT,
        },
        timeout=8,
    )
    if resp.ok:
      data = resp.json() if resp.content else {}
      if data.get("verified") is False:
        return "rejected", data.get("reason") or "External receipt verification rejected this transaction."
      if "amount" in data and data["amount"] is not None:
        try:
          if abs(float(data["amount"]) - float(expected_amt)) >= 0.01:
            return "rejected", f"Receipt verified amount ({float(data['amount']):.2f} ETB) does not match requested deposit ({float(expected_amt):.2f} ETB)."
        except ValueError:
          pass
  except Exception:
    return "needs_review", "External receipt check timed out; flagged for admin check."
  return "verified", ""


def fetch_receipt_link_details(raw_sms):
  m_url = re.search(r"https?://\S+", raw_sms or "", re.I)
  if not m_url:
    return None, ""
  receipt_url = m_url.group(0).strip().rstrip(".,;)")
  try:
    resp = requests.get(receipt_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    if not resp.ok or not resp.text:
      return None, f"Receipt link could not be fetched (status {resp.status_code})."
    plain = re.sub(r"<[^>]+>", " ", resp.text)
    plain = re.sub(r"\s+", " ", plain).strip()
    return {"url": receipt_url, "text": plain}, ""
  except Exception as e:
    return None, f"Could not open receipt link online ({str(e)[:80]})."


def verify_sms_strict(method, raw_sms, expected_amt):
  txt = (raw_sms or "").strip()
  up = txt.upper()
  tb_num, tb_owner = split_account_and_name(TELEBIRR_ACCOUNT, TELEBIRR_NAME)
  cbe_num, cbe_owner = split_account_and_name(CBE_ACCOUNT, CBE_NAME)

  target_acc = (tb_num if method == "Telebirr" else cbe_num).strip()
  target_owner = (tb_owner if method == "Telebirr" else cbe_owner).strip().lower()

  scam_markers = ["FAKE RECEIPT", "PHISHING", "TEST PAYMENT", "SIMULATED", "SCRAMBLER", "FORWARDED", "DEMO", "SAMPLE"]
  if any(s in up for s in scam_markers):
    return "rejected", "Suspicious or spoofed payment text detected."

  has_payment_context = any(k in up for k in [
      "TELEBIRR", "ETHIO TELECOM", "TRANSACTION NUMBER", "TRANSACTION ID",
      "COMMERCIAL BANK OF ETHIOPIA", "CBE", "DEBITED", "TRANSFERRED",
      "PAID TO", "RECEIVED", "CREDITED", "ETB", "BIRR", "ACCT", "ACCOUNT",
      "APPS.CBE.COM.ET", "RECEIPT", "HTTPS://", "HTTP://"
  ])
  if not has_payment_context:
    return "rejected", "Official confirmation SMS or receipt link is missing."

  is_cbe_text = ("CBE" in up or "COMMERCIAL BANK OF ETHIOPIA" in up or "APPS.CBE.COM.ET" in up or re.search(r"\bFT[A-Z0-9]{6,18}\b", up) is not None)
  is_tb_text = ("TELEBIRR" in up or "ETHIO TELECOM" in up)
  if method == "CBE" and is_tb_text and not is_cbe_text:
    return "rejected", "CBE is selected, but the message is from Telebirr."
  if method == "Telebirr" and is_cbe_text and not is_tb_text:
    return "rejected", "Telebirr is selected, but the message is from CBE."

  url_match = re.search(r"https?://\S+", txt, re.I)
  fetched = None
  fetch_err = ""
  if url_match:
    raw_url = url_match.group(0).strip().rstrip(".,;)")
    low_url = raw_url.lower()
    if method == "CBE" and "cbe.com.et" not in low_url:
      return "rejected", "Untrusted or non-CBE receipt link provided."
    if method == "Telebirr" and ("ethiotelecom" not in low_url and "telebirr" not in low_url):
      return "rejected", "Untrusted or non-Telebirr receipt link provided."
    fetched, fetch_err = fetch_receipt_link_details(txt)
    if fetched is None:
      return "needs_review", f"Disputed/unreadable receipt link; sent to admin ({fetch_err})."

  combined_text = txt
  if fetched and fetched.get("text"):
    combined_text = f"{txt}\n{fetched['text']}"
  comb_up = combined_text.upper()

  today_eat = datetime.now(EAT).date()
  dates_found = _extract_sms_dates_eat(combined_text)
  if not dates_found:
    return "rejected", "Transaction date is missing from the SMS/receipt. Yesterday's or undated messages are not accepted."
  if any(dt != today_eat for dt in dates_found):
    return "rejected", f"Transaction date does not match today's date ({today_eat.isoformat()} EAT). Old or yesterday's SMS cannot be reused."
  if not _has_time_marker(combined_text):
    return "rejected", "Transaction time is missing from the SMS/receipt."

  acc_digits = re.sub(r"\D", "", target_acc)
  acc_matched = False
  url_suffix_matches = re.findall(r"[?&/]([0-9]{6,13})\b", txt)
  for suf in url_suffix_matches:
    if acc_digits.endswith(suf) or suf.endswith(acc_digits[-8:]):
      acc_matched = True
      break

  body_without_urls = re.sub(r"https?://\S+", " ", combined_text)
  body_digits = re.sub(r"\D", "", body_without_urls)
  if not acc_matched and acc_digits and len(acc_digits) >= 6 and acc_digits in body_digits:
    acc_matched = True
  if not acc_matched and len(acc_digits) >= 8:
    if acc_digits[-4:] in body_digits and ("*" in body_without_urls or "X" in body_without_urls.upper()):
      acc_matched = True

  owner_matched = False
  if target_owner and len(target_owner) >= 4:
    name_parts = [p for p in re.split(r"\s+", target_owner) if len(p) >= 3]
    if name_parts and all(part in combined_text.lower() for part in name_parts):
      owner_matched = True

  if not (acc_matched and owner_matched):
    return "rejected", f"Both receiver account ({target_acc}) and account name ({target_owner.title()}) must match our {method} account."

  if any(k in up for k in ["PAID TO ", "TRANSFERRED TO ", "DEBITED WITH ", "SENT TO "]) and not acc_matched:
    return "rejected", "Outgoing payment does not match our receiving account."

  amt_matches = re.findall(r"(?:ETB|BIRR)\s*([0-9,]+(?:\.[0-9]{1,2})?)|([0-9,]+(?:\.[0-9]{1,2})?)\s*(?:ETB|BIRR)", comb_up)
  found_amounts = []
  for g1, g2 in amt_matches:
    raw_num = (g1 or g2 or "").replace(",", "").strip()
    if raw_num:
      try:
        found_amounts.append(float(raw_num))
      except ValueError:
        pass
  if not found_amounts:
    return "rejected", f"Amount was not found in the SMS/receipt ({float(expected_amt):.2f} ETB required)."
  if not any(abs(x - float(expected_amt)) < 0.01 for x in found_amounts):
    return "rejected", f"Amount in SMS/receipt does not match requested {float(expected_amt):.2f} ETB."

  return "verified", ""


@app.route("/api/deposit", methods=["POST"])
def api_deposit():
  d = request.get_json(force=True)
  in_dep_hours = is_deposit_hours()
  uid = str(d.get("uid", "874411134")).strip()
  m = str(d.get("method", "Telebirr")).strip()
  raw_sms = str(d.get("sms_text") or d.get("tx") or "").strip()
  tx = extract_tx_code(m, raw_sms).upper()
  amt = float(d.get("amount", 0) or 0)
  u = get_u(uid)

  if amt < 50:
    return jsonify({"ok": False, "msg": "❌ Minimum deposit is 50 ETB."})

  if not tx:
    return jsonify({"ok": False, "msg": "❌ Valid Transaction / FT ID not found. Please paste your confirmation SMS or FT / Transaction ID."})

  url_match = re.search(r"https?://\S+", raw_sms, re.I)
  norm_url = url_match.group(0).strip().upper() if url_match else ""
  tx_key = f"TX:{tx}"
  url_key = f"URL:{norm_url}" if norm_url else ""

  used_upper = {str(x).upper() for x in USED_TX}
  pending_txs = {
      str(p.get("tx", "")).upper()
      for p in PENDING_DEPOSITS.values()
      if p.get("status") == "Pending"
  }
  if tx_key in used_upper or tx in used_upper or tx in pending_txs or (url_key and url_key in used_upper):
    return jsonify({"ok": False, "msg": "⚠️ Duplicate Transaction / FT ID! This payment reference has already been used or is pending."})

  st = check_tx_status(m, tx)
  if st == "duplicate":
    return jsonify({"ok": False, "msg": "⚠️ Duplicate Transaction ID! This payment reference has already been used."})
  if st != "ok":
    return jsonify({"ok": False, "msg": "❌ Invalid Transaction / FT ID format for the selected payment method."})

  # Check SMS / receipt details to attach a helpful verification note for the Admin,
  # then route EVERY valid non-duplicate deposit to Admin for Approve / Reject.
  sms_status, reason = verify_sms_strict(m, raw_sms, amt)
  check_summary = "✅ Auto-check: Format & non-duplicate OK" if sms_status == "verified" else f"⚠️ Note: {reason}"

  did = "DEP-" + uuid.uuid4().hex[:6].upper()
  dep_status_label = "Pending" if in_dep_hours else "Scheduled (07:00 AM EAT)"
  schedule_note = (
      "Immediate approval window (07:00 AM – 01:00 AM EAT)"
      if in_dep_hours
      else "Received outside active approval window — will be approved at 07:00 AM EAT (ጠዋት 1 ሰዓት)"
  )
  PENDING_DEPOSITS[did] = {
      "id": did,
      "uid": uid,
      "method": m,
      "tx": tx,
      "amount": amt,
      "sms_text": raw_sms,
      "url_key": url_key,
      "status": dep_status_label,
      "created_ts": int(time.time()),
      "check_note": check_summary,
      "schedule_note": schedule_note,
  }
  save_persistent_state()

  dep_kb = {
      "inline_keyboard": [[
          {"text": f"✅ Approve ({did})", "callback_data": f"approve_dep:{did}"},
          {"text": f"❌ Reject ({did})", "callback_data": f"reject_dep:{did}"},
      ]]
  }
  notify_internal_kb(
      (
          f"💳 New Deposit Request ({dep_status_label})\n"
          f"ID: {did}\n"
          f"Customer ID: {uid}\n"
          f"Method: {m}\n"
          f"FT / Ref ID: {tx}\n"
          f"Amount: {amt:.2f} ETB\n"
          f"Window: {schedule_note}\n"
          f"{check_summary}\n"
          f"SMS / Details: {raw_sms[:400]}"
      ),
      dep_kb,
  )
  user_msg = (
      f"⏳ Deposit request ({did}) for {amt:.2f} ETB ({m} / {tx}) received and sent to Admin for approval."
      if in_dep_hours
      else f"⏰ Deposit ({did}) for {amt:.2f} ETB ({m} / {tx}) is received! Active deposit & approval hours are 07:00 AM – 01:00 AM EAT (ጠዋት 1 ሰዓት – ሌሊት 7 ሰዓት) — your deposit will be approved at 07:00 AM EAT (ጠዋት 1 ሰዓት)."
  )
  return jsonify({
      "ok": True,
      "pending": True,
      "balance": u["balance"],
      "msg": user_msg,
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
  if amt < 200:
    return jsonify({"ok": False, "msg": "❌ Minimum withdrawal is 200 ETB."})
  if amt > u["balance"]:
    return jsonify({"ok": False, "msg": "Insufficient balance."})
  if not dest:
    return jsonify({"ok": False, "msg": "Please enter your account number and full name."})
  u["balance"] = round(u["balance"] - amt, 2)
  wid = "WD-" + uuid.uuid4().hex[:6].upper()
  bal_before_wd, bal_after_wd = record_house_financial_event("WITHDRAW", amt, f"ID: {wid} | Customer: {uid} | Bank: {m} -> {dest}")
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
      f"Customer Account: {dest}\n"
      f"House Balance Before: {bal_before_wd:.2f} ETB -> After Deduction: {bal_after_wd:.2f} ETB"
  )
  wd_kb = {
      "inline_keyboard": [[{
          "text": f"✅ Approve ({wid})",
          "callback_data": f"approve_wd:{wid}",
      }]]
  }
  primary = resolve_internal_target()
  if primary:
    tg(primary, wd_text, wd_kb)
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
