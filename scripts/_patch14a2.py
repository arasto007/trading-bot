from pathlib import Path

p = Path(__file__).with_name("phase14a2_pa_no_signal_audit.py")
raw = p.read_bytes()
if raw[:2] == b"\xff\xfe" or (len(raw) > 3 and raw[1] == 0 and raw[3] == 0):
    t = raw.decode("utf-16-le")
else:
    t = raw.decode("utf-8")

t = t.replace(
    "from tradingbot.domain.models import (\n"
    "                                MarketKey,\n"
    "                                SignalDirection,\n"
    "                                TradingSignal,\n"
    "                            )",
    "from tradingbot.domain.enums import SignalDirection\n"
    "                            from tradingbot.domain.models import TradingSignal",
)
t = t.replace(
    'market=MarketKey(symbol="XAUUSD", timeframe="M5"),\n'
    "                                direction=direction,\n"
    "                                confidence=float(setup.confidence),\n"
    '                                strategy_name="priceaction",\n'
    "                                entry=float(setup.entry),\n"
    "                                stop_loss=float(setup.stop_loss),\n"
    "                                take_profit=float(setup.take_profit),\n"
    "                                metadata=dict(setup.metadata or {}),",
    "direction=direction,\n"
    "                                confidence=float(setup.confidence),\n"
    '                                symbol="XAUUSD",\n'
    '                                timeframe="M5",\n'
    '                                strategy_name="priceaction",\n'
    "                                stop_loss=float(setup.stop_loss),\n"
    "                                take_profit=float(setup.take_profit),\n"
    "                                metadata=dict(setup.metadata or {}),\n"
    "                                created_at=ts,",
)
p.write_bytes(t.encode("utf-8"))
print("patched", "MarketKey" not in t)
