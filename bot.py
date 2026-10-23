#!/usr/bin/env python3
"""WIF Tipbot — $WIF tipping on Robinhood Chain via Telegram.

Every user gets their own Robinhood Chain wallet. Tips are real ERC-20
transfers of $WIF (0x5173b8eA6923c2d40267890D45C46a3480954773) on chain 4663.
The bot funds each new wallet with a tiny ETH gas grant (RH chain fees are
~0.02 gwei, so a transfer costs well under a cent).

Commands:
  /start            register, get your wallet
  /deposit          your deposit address + QR-ish info
  /balance          WIF + ETH balance
  /tip @user 100    send 100 WIF onchain to another user
  /withdraw ADDR 100  send WIF to any external address
  /leaderboard      top tippers
  /help
"""
import asyncio
import json
import logging
import os
import sqlite3
import time
from pathlib import Path

import requests
from eth_account import Account
from eth_account.messages import encode_defunct

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
BASE = Path(__file__).parent
TOKEN = os.environ.get("TGBOT_TOKEN", "")
RPC = "https://rpc.mainnet.chain.robinhood.com"
CHAIN_ID = 4663
WIF = "0x5173b8eA6923c2d40267890D45C46a3480954773"
WIF_DECIMALS = 18
GAS_GRANT = int(0.00001 * 1e18)          # 0.00001 ETH per new user (gas)
TREASURY = json.loads((BASE / "treasury.json").read_text())["private_key"]
TREASURY_ADDR = Account.from_key(TREASURY).address
MIN_TIP = int(1_000 * 10**WIF_DECIMALS)  # 1,000 WIF floor (~$1.4)
MAX_TIP = int(1_000_000 * 10**WIF_DECIMALS)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wif-tipbot")


# ----------------------------------------------------------------------------
# DB
# ----------------------------------------------------------------------------
def db():
    con = sqlite3.connect(BASE / "tipbot.db")
    con.row_factory = sqlite3.Row
    con.execute(
        """CREATE TABLE IF NOT EXISTS users (
            tg_id INTEGER PRIMARY KEY,
            tg_username TEXT,
            address TEXT UNIQUE,
            privkey TEXT,
            created_at INTEGER
        )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS tips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_tg INTEGER, to_tg INTEGER, amount REAL, tx TEXT,
            created_at INTEGER
        )"""
    )
    return con


# ----------------------------------------------------------------------------
# RPC helpers (no web3 dependency — eth-account + requests)
# ----------------------------------------------------------------------------
def rpc(method, params):
    r = requests.post(
        RPC,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        headers={"content-type": "application/json", "user-agent": "wif-tipbot/1.0"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(data["error"]["message"])
    return data["result"]


def balance_of(address):
    out = rpc(
        "eth_call",
        [{"to": WIF, "data": "0x70a08231" + address[2:].lower().rjust(64, "0")}, "latest"],
    )
    return int(out, 16)


def eth_balance(address):
    return int(rpc("eth_getBalance", [address, "latest"]), 16)


def gas_price():
    return int(rpc("eth_gasPrice", []), 16)


def erc20_transfer(privkey, to, amount, nonce):
    acct = Account.from_key(privkey)
    transfer = (
        "0xa9059cbb"
        + to[2:].lower().rjust(64, "0")
        + hex(amount)[2:].rjust(64, "0")
    )
    tx = {
        "chainId": CHAIN_ID,
        "nonce": nonce,
        "to": WIF,
        "value": 0,
        "gas": 80000,
        "gasPrice": gas_price() * 2,  # headroom
        "data": transfer,
    }
    signed = acct.sign_transaction(tx)
    return rpc("eth_sendRawTransaction", [signed.raw_transaction.hex()])


def send_native(privkey, to, value, nonce):
    acct = Account.from_key(privkey)
    tx = {
        "chainId": CHAIN_ID,
        "nonce": nonce,
        "to": to,
        "value": value,
        "gas": 30000,
        "gasPrice": gas_price() * 2,
        "data": b"",
    }
    signed = acct.sign_transaction(tx)
    return rpc("eth_sendRawTransaction", [signed.raw_transaction.hex()])


def nonce_of(address):
    return int(rpc("eth_getTransactionCount", [address, "latest"]), 16)


def fmt_wif(wei):
    return f"{wei / 10**WIF_DECIMALS:,.0f}"


# ----------------------------------------------------------------------------
# Telegram bot
# ----------------------------------------------------------------------------
def start_bot():
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

    app = ApplicationBuilder().token(TOKEN).build()

    def get_user(tg_id, username):
        con = db()
        row = con.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()
        if row:
            return row
        acct = Account.create()
        con.execute(
            "INSERT INTO users (tg_id, tg_username, address, privkey, created_at) VALUES (?,?,?,?,?)",
            (tg_id, username, acct.address, acct.key.hex(), int(time.time())),
        )
        con.commit()
        # gas grant from treasury so the user can tip immediately
        n = nonce_of(TREASURY_ADDR)
        send_native(TREASURY, acct.address, GAS_GRANT, n)
        return con.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()

    async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        u = update.effective_user
        row = get_user(u.id, u.username or "")
        await update.message.reply_text(
            f"👋 *WIF Tipbot*\n\n"
            f"Your Robinhood Chain wallet:\n`{row['address']}`\n\n"
            f"· /deposit — send $WIF here\n"
            f"· /tip @user 100 — tip anyone onchain\n"
            f"· /withdraw ADDR 100 — cash out\n"
            f"· /balance — check funds\n\n"
            f"Gas for your first tips is funded by the bot 🤝",
            parse_mode="Markdown",
        )

    async def cmd_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
        u = update.effective_user
        row = get_user(u.id, u.username or "")
        await update.message.reply_text(
            f"💸 Send $WIF (or ETH) to:\n\n`{row['address']}`\n\n"
            f"Chain: *Robinhood Chain* (chain id 4663)\n"
            f"Token: `{WIF}`\n\n"
            f"After the tx confirms, /balance shows it onchain.",
            parse_mode="Markdown",
        )

    async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
        u = update.effective_user
        row = get_user(u.id, u.username or "")
        wif = balance_of(row["address"])
        eth = eth_balance(row["address"])
        await update.message.reply_text(
            f"*{fmt_wif(wif)} WIF*\n`{eth/1e18:.6f} ETH` (gas)\n\n"
            f"`{row['address']}`",
            parse_mode="Markdown",
        )

    async def cmd_tip(update: Update, context: ContextTypes.DEFAULT_TYPE):
        u = update.effective_user
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("Usage: /tip @username 100")
            return
        target = args[0].lstrip("@").strip()
        try:
            amount = int(float(args[1]) * 10**WIF_DECIMALS)
        except ValueError:
            await update.message.reply_text("Amount must be a number.")
            return
        if not (MIN_TIP <= amount <= MAX_TIP):
            await update.message.reply_text(
                f"Tip must be between {fmt_wif(MIN_TIP)} and {fmt_wif(MAX_TIP)} WIF."
            )
            return
        con = db()
        sender = con.execute("SELECT * FROM users WHERE tg_id=?", (u.id,)).fetchone()
        if not sender:
            await update.message.reply_text("Run /start first.")
            return
        recv = con.execute(
            "SELECT * FROM users WHERE tg_username=?", (target,)
        ).fetchone()
        if not recv:
            await update.message.reply_text(f"@{target} hasn't registered yet. They need to /start first.")
            return
        if balance_of(sender["address"]) < amount:
            await update.message.reply_text("Not enough WIF. /deposit first.")
            return
        try:
            n = nonce_of(sender["address"])
            tx = erc20_transfer(sender["privkey"], recv["address"], amount, n)
        except Exception as e:
            await update.message.reply_text(f"❌ Transfer failed: {e}")
            return
        con.execute(
            "INSERT INTO tips (from_tg, to_tg, amount, tx, created_at) VALUES (?,?,?,?,?)",
            (u.id, recv["tg_id"], amount / 10**WIF_DECIMALS, tx, int(time.time())),
        )
        con.commit()
        btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("View on explorer", url=f"https://robinhoodchain.blockscout.com/tx/{tx}")]
        ])
        await update.message.reply_text(
            f"✅ Tipped *{fmt_wif(amount)} WIF* to @{target}\n"
            f"`{tx}`",
            parse_mode="Markdown",
            reply_markup=btn,
        )
        await context.bot.send_message(
            recv["tg_id"], f"🎁 You received *{fmt_wif(amount)} WIF* from @{u.username or u.first_name}!"
        )

    async def cmd_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
        u = update.effective_user
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("Usage: /withdraw 0xADDRESS 100")
            return
        to = args[0].strip()
        try:
            amount = int(float(args[1]) * 10**WIF_DECIMALS)
        except ValueError:
            await update.message.reply_text("Amount must be a number.")
            return
        if not to.startswith("0x") or len(to) != 42:
            await update.message.reply_text("Invalid address.")
            return
        con = db()
        sender = con.execute("SELECT * FROM users WHERE tg_id=?", (u.id,)).fetchone()
        if not sender:
            await update.message.reply_text("Run /start first.")
            return
        if balance_of(sender["address"]) < amount:
            await update.message.reply_text("Not enough WIF.")
            return
        try:
            tx = erc20_transfer(sender["privkey"], to, amount, nonce_of(sender["address"]))
        except Exception as e:
            await update.message.reply_text(f"❌ Withdraw failed: {e}")
            return
        await update.message.reply_text(
            f"💸 Withdrew *{fmt_wif(amount)} WIF* to `{to}`\n`{tx}`",
            parse_mode="Markdown",
        )

    async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
        con = db()
        rows = con.execute(
            "SELECT tg_username, SUM(amount) AS total FROM tips GROUP BY tg_username ORDER BY total DESC LIMIT 10"
        ).fetchall()
        if not rows:
            await update.message.reply_text("No tips yet — be the first! /tip")
            return
        lines = ["🏆 *Leaderboard*", ""]
        medals = ["🥇", "🥈", "🥉"]
        for i, r in enumerate(rows):
            mark = medals[i] if i < 3 else f"{i+1}."
            lines.append(f"{mark} @{r['tg_username']} — {r['total']:,.0f} WIF")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🤖 *WIF Tipbot* — tip $WIF on Robinhood Chain right from Telegram.\n\n"
            "/start — get your wallet\n"
            "/deposit — top up\n"
            "/tip @user 100 — send onchain\n"
            "/withdraw ADDR 100 — cash out\n"
            "/balance, /leaderboard, /help\n\n"
            "Every tip is a real onchain ERC-20 transfer. Fees are ~$0.000004.",
            parse_mode="Markdown",
        )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("deposit", cmd_deposit))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("tip", cmd_tip))
    app.add_handler(CommandHandler("withdraw", cmd_withdraw))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("help", cmd_help))
    app.run_polling(allowed_updates=["message"])


# /start as a no-op guard when run standalone without token
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("TGBOT_TOKEN not set. Run: TGBOT_TOKEN=<token> python bot.py")
    start_bot()