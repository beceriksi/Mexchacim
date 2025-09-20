# main.py
# 4 saatlik mumlarda erken hacim akışı taraması:
# - Hacim[t] >= VOL_MULTIPLIER * ortalama_hacim(son VOL_LOOKBACK bar)
# - Fiyat artışı <= PRICE_MAX_CHANGE (fiyat patlamadan önce yakala)
# Sonuçları Telegram'a yollar.

import os, time, ccxt, pandas as pd, requests
from datetime import datetime
import pytz

# ---- Ayarlar (ENV üzerinden değiştirilebilir) ----
EXCHANGE         = os.getenv("EXCHANGE", "mexc")      # binance|mexc|kucoin|bybit|gateio
QUOTE            = os.getenv("QUOTE", "USDT")
TIMEFRAME        = os.getenv("TIMEFRAME", "4h")
LIMIT            = int(os.getenv("LIMIT", "200"))
VOL_LOOKBACK     = int(os.getenv("VOL_LOOKBACK", "10"))
VOL_MULTIPLIER   = float(os.getenv("VOL_MULTIPLIER", "2.0"))
PRICE_MAX_CHANGE = float(os.getenv("PRICE_MAX_CHANGE", "0.03"))
MAX_MARKETS      = int(os.getenv("MAX_MARKETS", "400"))  # taranacak USDT çifti
CSV_OUT          = os.getenv("CSV_OUT", "volume_spike_4h.csv")

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")  # GitHub Secret
CHAT_ID          = os.getenv("CHAT_ID")         # GitHub Secret (string veya int)

def load_exchange(name):
    ex = getattr(ccxt, name)({'enableRateLimit': True})
    ex.load_markets()
    return ex

def pick_symbols(ex, quote="USDT", max_markets=500):
    syms = []
    for s, m in ex.markets.items():
        if m.get("active") and m.get("spot") and m.get("quote") == quote:
            syms.append(s)
    return sorted(set(syms))[:max_markets]

def early_volume_spike(df, idx):
    # Yeterli geçmiş yoksa
    if idx < max(VOL_LOOKBACK, 1):
        return False
    vol_avg = df["volume"].iloc[idx - VOL_LOOKBACK: idx].mean()
    vol_cond = df["volume"].iloc[idx] >= VOL_MULTIPLIER * max(vol_avg, 1e-12)

    close_now = df["close"].iloc[idx]
    close_prev = df["close"].iloc[idx - 1]
    price_change = (close_now - close_prev) / max(close_prev, 1e-12)
    price_cond = price_change <= PRICE_MAX_CHANGE

    return vol_cond and price_cond

def analyze_symbol(ex, symbol):
    try:
        raw = ex.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=LIMIT)
        if not raw:
            return None
        df = pd.DataFrame(raw, columns=["time","open","high","low","close","volume"])
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True).dt.tz_convert("Europe/Istanbul")
        idx = len(df) - 1
        if early_volume_spike(df, idx):
            return {
                "symbol": symbol,
                "bar_time": df["time"].iloc[idx],
                "close": float(df["close"].iloc[idx]),
                "volume": float(df["volume"].iloc[idx]),
            }
    except Exception:
        return None
    return None

def send_to_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram ayarları yok; mesaj gönderilmeyecek.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        r = requests.post(url, data=payload, timeout=20)
        if not r.ok:
            print("Telegram hata:", r.text)
    except Exception as e:
        print("Telegram istisna:", e)

def main():
    ex = load_exchange(EXCHANGE)
    symbols = pick_symbols(ex, QUOTE, MAX_MARKETS)
    print(f"{EXCHANGE.upper()} {QUOTE} pariteleri: {len(symbols)} taranıyor…")

    hits = []
    for i, sym in enumerate(symbols, 1):
        res = analyze_symbol(ex, sym)
        if res:
            hits.append(res)
            print(f"[MATCH] {sym} @ {res['bar_time']} close={res['close']:.6g}")
        if i % 20 == 0:
            time.sleep(0.25)  # API nezaket beklemesi

    df = pd.DataFrame(hits)
    if not df.empty:
        df.sort_values(["bar_time", "symbol"], inplace=True)
        df.to_csv(CSV_OUT, index=False)

        # Telegram mesajı
        lines = ["🔥 4h Erken Hacim Sinyalleri 🔥", ""]
        for _, r in df.iterrows():
            lines.append(f"{r['symbol']} | Close={r['close']:.6g} | Vol={int(r['volume']):,}")
        send_to_telegram("\n".join(lines))
        print(f"\nCSV kaydedildi: {CSV_OUT}")
    else:
        print("Hiç eşleşme yok.")
        send_to_telegram("📭 4h taramasında eşleşme yok.")

if __name__ == "__main__":
    main()
  
