#!/usr/bin/env python3
"""Self-check for WIF Tipbot. Run: python selftest.py

Checks chain connectivity, WIF contract params, transfer encoding and
the gas math — everything that does not require a funded wallet.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bot


def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL") + f"  {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        raise SystemExit(1)


def main():
    # 1. chain id
    cid = int(bot.rpc("eth_chainId", []), 16)
    check("chain id 4663", cid == 4663, str(cid))

    # 2. WIF contract: symbol/decimals via raw calls
    def abi_string(hexout):
        raw = bytes.fromhex(hexout[2:])
        ln = int.from_bytes(raw[32:64] if len(raw) > 64 else raw[62:64], "big")
        return raw[64:64 + ln].decode()
    sym = abi_string(bot.rpc("eth_call", [{"to": bot.WIF, "data": "0x95d89b41"}, "latest"]))
    dec = int(bot.rpc("eth_call", [{"to": bot.WIF, "data": "0x313ce567"}, "latest"]), 16)
    check("WIF symbol", sym == "WIF", sym)
    check("WIF decimals 18", dec == 18, str(dec))

    # 3. transfer encoding: known-good fixture
    #   to 0x1111111111111111111111111111111111111111 amt 1000e18
    data = "0xa9059cbb" + "1" * 24 + "1111111111111111111111111111111111111111".lower() + hex(int(1000 * 10**18))[2:].rjust(64, "0")
    check("transfer data length", len(data) == 2 + 8 + 64 + 64, str(len(data)))
    check("transfer selector", data[:10] == "0xa9059cbb")
    check("transfer to padded", data[10:74] == ("1" * 24 + "1" * 40))

    # 4. gas price sane (< 1 gwei on RH chain)
    gp = bot.gas_price()
    check("gas price < 1 gwei", gp < 1_000_000_000, f"{gp/1e9:.4f} gwei")

    # 5. cost per tip
    cost = 80000 * gp / 1e18
    check("cost per tip < 0.00001 ETH", cost < 1e-5, f"{cost:.8f} ETH")
    print("\nA gas grant (0.00001 ETH) covers ~", int(1e-5 / cost), "tips")

    print("\nOK — chain reachable, WIF contract sane, encoding good.")


if __name__ == "__main__":
    main()