# WIF Tipbot

**Tip $WIF on Robinhood Chain directly from Telegram.**

Every user gets their own onchain wallet. Every tip is a real ERC-20
transfer of [$WIF](https://robinhoodchain.blockscout.com/token/0x5173b8eA6923c2d40267890D45C46a3480954773)
on Robinhood Chain (chain id 4663) — no custody, no IOU ledger, just
Telegram as the frontend for a token transfer.

Built for the [World is Flat Hackathon](https://worldisflat.fun/build)
($10,000 USDG prize).

## Why onchain tips matter

Tipping is the internet's most natural payment gesture, and crypto
payments have the right properties for it: cheap, fast, global, no
merchant account. Robinhood Chain makes it actually practical —
fees are ~0.02 gwei, so a tip costs **~$0.003**. WIF Tipbot removes the
last barrier (wallet management) by generating a wallet per user and
sponsoring the first tips' gas.

## Commands

| Command | What it does |
|---|---|
| `/start` | register, get your personal RH-chain wallet |
| `/deposit` | your deposit address + network details |
| `/tip @user 100` | real onchain WIF transfer to another user |
| `/withdraw 0x… 100` | send WIF to any external address |
| `/balance` | WIF + ETH (gas) balances, read live from chain |
| `/leaderboard` | top tippers |
| `/help` | all commands |

## How it works

```
Telegram user ──/tip @friend 100──▶ WIF Tipbot
                                      │
                                      │ sign + broadcast ERC-20 transfer
                                      ▼
                              Robinhood Chain (4663)
                              $WIF 0x5173b8eA6923c2d40267890D45C46a3480954773
```

- Wallet generation: `eth_account` (BIP-39-less fresh keys), stored
  locally in SQLite (private keys never leave the server).
- Chain reads: raw RPC calls to `rpc.mainnet.chain.robinhood.com`
  (`eth_call`, `eth_getBalance`, `eth_getTransactionCount`, `eth_gasPrice`).
- Transfers: signed with `eth_account`, broadcast via
  `eth_sendRawTransaction`. No web3.py dependency — the whole bot is
  `python-telegram-bot` + `requests` + `eth_account`.
- Gas: the treasury sponsors 0.00001 ETH per new wallet so a user can
  tip immediately; one deposit covers dozens of tips.

## Flywheel

1. **Tip** → creator gets WIF onchain, wants more
2. **Leaderboard** → status competition, more tipping
3. **Community** → creators bring their audiences
4. **Flywheel** → every interaction is a real $WIF transaction, driving
   usage + demand for the token

## Run it

```bash
pip install python-telegram-bot requests eth-account
cat > treasury.json <<'EOF'
{"private_key": "0x…treasury wallet…"}
EOF
TGBOT_TOKEN=<your bot token> python bot.py
```

Fund the treasury once: send a little ETH (gas) and some WIF to the
treasury address. That's the only setup.

## Live

- Bot: [@WIFTipBot](https://t.me/WIFTipBot) (or wherever it's deployed)
- Example tx: (see selftest / demo)
- Contract: `0x5173b8eA6923c2d40267890D45C46a3480954773`
- Chain: Robinhood Chain, id 4663, RPC `rpc.mainnet.chain.robinhood.com`

## License

MIT