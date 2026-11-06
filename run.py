import asyncio
import ccxt.pro as ccxtpro
import pandas as pd
import requests

from scalping.config import MEXC_API_KEY, MEXC_SECRET_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, DRY_RUN

# Ubah simbol koin entry menjadi LSK Futures (Swap)
SYMBOL = 'LSK/USDT:USDT'    
TIMEFRAME = '1m'             
LEVERAGE = 15             
MARGIN_PER_TRADE = 1

STOP_LOSS_PCT = 0.003       # 0.3%
TAKE_PROFIT_PCT = 0.006     # 0.6%
TRAILING_TRIGGER = 0.002    # 0.2%

COIN_NAME = SYMBOL.split('/')[0]  # Mengambil nama koin (LSK) untuk notifikasi

def send_telegram_alert(message):
    """Mengirimkan laporan status penting ke Telegram."""
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        prefix = "🧪 [SIMULASI DRY RUN] " if DRY_RUN else "[BOT SCALP LIVE] "
        try:
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": f"{prefix}\n{message}"}, timeout=5)
        except Exception:
            pass

def calculate_indicators(df):
    """Menghitung RSI 14 dan EMA 200 secara native Pandas."""
    df['EMA200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=13, adjust=False).mean()
    avg_loss = loss.ewm(com=13, adjust=False).mean()
    rs = avg_gain / avg_loss
    df['RSI'] = 100 - (100 / (1 + rs))
    return df

async def run_bot():
    """Fungsi utama dengan dukungan mode Dry Run dan Auto-Reconnect."""
    mode_str = "🧪 SIMULASI (DRY RUN)" if DRY_RUN else "🔴 LIVE TRADING RIIL"
    print(f"[INFO] Bot diinisialisasi dalam mode: {mode_str} | Target Symbol: {SYMBOL}")

    while True:
        exchange = ccxtpro.mexc({
            'apiKey': MEXC_API_KEY,
            'secret': MEXC_SECRET_KEY,
            'options': {
                'defaultType': 'swap',
                'adjustForTimeDifference': True,
            },
            'enableRateLimit': True
        })

        try:
            print("[INFO] Terhubung ke WebSocket MEXC...")
            
            if not DRY_RUN:
                try:
                    await exchange.set_leverage(LEVERAGE, SYMBOL)
                    print(f"[INFO] Leverage diatur ke {LEVERAGE}x untuk {SYMBOL}")
                except Exception as e:
                    print(f"[WARN] Gagal set leverage otomatis: {e}")

            in_position = False
            entry_price = 0.0
            position_side = None
            current_sl = 0.0
            current_tp = 0.0

            last_rsi = 50.0
            last_ema = 0.0
            last_candle_time = 0

            print(f"🚀 Bot Scalping Berjalan ({mode_str})...")
            send_telegram_alert(f"Bot Berhasil Dinyalakan untuk {SYMBOL} dalam mode: {mode_str}")

            while True:
                ticker = await exchange.watch_ticker(SYMBOL)
                last_close = ticker['last']

                current_time = ticker['timestamp']
                if current_time - last_candle_time > 10000:
                    try:
                        bars = await exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=250)
                        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                        df = calculate_indicators(df)
                        
                        last_rsi = df['RSI'].iloc[-1]
                        last_ema = df['EMA200'].iloc[-1]
                        last_candle_time = current_time
                    except Exception as err_ohlcv:
                        print(f"[ERROR Fetch OHLCV]: {err_ohlcv}")

                print(f"⚡ [{mode_str}] {COIN_NAME} Harga: ${last_close:.4f} | RSI: {last_rsi:.1f} | EMA200: ${last_ema:.4f}", end='\r')

                # Logika Entri Posisi
                if not in_position:
                    if last_rsi < 30 and last_close > last_ema:
                        entry_price = last_close
                        qty = (MARGIN_PER_TRADE * LEVERAGE) / entry_price
                        current_sl = entry_price * (1 - STOP_LOSS_PCT)
                        current_tp = entry_price * (1 + TAKE_PROFIT_PCT)
                        position_side = 'LONG'

                        if DRY_RUN:
                            print(f"\n🧪 [DRY RUN] SIMULASI OPEN LONG {COIN_NAME} | Price: ${entry_price:.4f} | SL: ${current_sl:.4f} | TP: ${current_tp:.4f}")
                        else:
                            print(f"\n🟢 [LIVE ORDER] OPEN LONG {COIN_NAME} | Price: ${entry_price:.4f} | SL: ${current_sl:.4f} | TP: ${current_tp:.4f}")
                            await exchange.create_limit_buy_order(SYMBOL, qty, entry_price)

                        in_position = True
                        send_telegram_alert(f"🟢 OPEN LONG {COIN_NAME}\nEntry: ${entry_price:.4f}\nTP: ${current_tp:.4f}\nSL: ${current_sl:.4f}")

                    elif last_rsi > 70 and last_close < last_ema:
                        entry_price = last_close
                        qty = (MARGIN_PER_TRADE * LEVERAGE) / entry_price
                        current_sl = entry_price * (1 + STOP_LOSS_PCT)
                        current_tp = entry_price * (1 - TAKE_PROFIT_PCT)
                        position_side = 'SHORT'

                        if DRY_RUN:
                            print(f"\n🧪 [DRY RUN] SIMULASI OPEN SHORT {COIN_NAME} | Price: ${entry_price:.4f} | SL: ${current_sl:.4f} | TP: ${current_tp:.4f}")
                        else:
                            print(f"\n🔴 [LIVE ORDER] OPEN SHORT {COIN_NAME} | Price: ${entry_price:.4f} | SL: ${current_sl:.4f} | TP: ${current_tp:.4f}")
                            await exchange.create_limit_sell_order(SYMBOL, qty, entry_price)

                        in_position = True
                        send_telegram_alert(f"🔴 OPEN SHORT {COIN_NAME}\nEntry: ${entry_price:.4f}\nTP: ${current_tp:.4f}\nSL: ${current_sl:.4f}")

                # Manajemen Posisi Aktif (TP / SL / Trailing Stop)
                else:
                    if position_side == 'LONG':
                        if last_close >= entry_price * (1 + TRAILING_TRIGGER):
                            new_sl = last_close * (1 - STOP_LOSS_PCT)
                            if new_sl > current_sl:
                                current_sl = new_sl
                                print(f"\n📈 Trailing Stop Naik: ${current_sl:.4f}")

                        if last_close >= current_tp or last_close <= current_sl:
                            pnl_pct = ((last_close - entry_price) / entry_price) * LEVERAGE * 100
                            print(f"\n⚡ Posisi LONG {COIN_NAME} Tertutup di Harga: ${last_close:.4f} | Estimasi PnL: {pnl_pct:.2f}%")
                            
                            if not DRY_RUN:
                                try:
                                    close_qty = (MARGIN_PER_TRADE * LEVERAGE) / entry_price
                                    await exchange.create_market_sell_order(SYMBOL, close_qty, params={'reduceOnly': True})
                                    print(f"🔴 [LIVE ORDER] Posisi LONG {COIN_NAME} berhasil ditutup di bursa.")
                                except Exception as err_close:
                                    print(f"[ERROR CLOSE ORDER]: {err_close}")

                            send_telegram_alert(f"⚡ LONG {COIN_NAME} Tertutup di Harga: ${last_close:.4f}\nEstimasi PnL: {pnl_pct:.2f}%")
                            in_position = False

                    elif position_side == 'SHORT':
                        if last_close <= entry_price * (1 - TRAILING_TRIGGER):
                            new_sl = last_close * (1 + STOP_LOSS_PCT)
                            if new_sl < current_sl:
                                current_sl = new_sl
                                print(f"\n📉 Trailing Stop Turun: ${current_sl:.4f}")

                        if last_close <= current_tp or last_close >= current_sl:
                            pnl_pct = ((entry_price - last_close) / entry_price) * LEVERAGE * 100
                            print(f"\n⚡ Posisi SHORT {COIN_NAME} Tertutup di Harga: ${last_close:.4f} | Estimasi PnL: {pnl_pct:.2f}%")
                            
                            if not DRY_RUN:
                                try:
                                    close_qty = (MARGIN_PER_TRADE * LEVERAGE) / entry_price
                                    await exchange.create_market_buy_order(SYMBOL, close_qty, params={'reduceOnly': True})
                                    print(f"🟢 [LIVE ORDER] Posisi SHORT {COIN_NAME} berhasil ditutup di bursa.")
                                except Exception as err_close:
                                    print(f"[ERROR CLOSE ORDER]: {err_close}")

                            send_telegram_alert(f"⚡ SHORT {COIN_NAME} Tertutup di Harga: ${last_close:.4f}\nEstimasi PnL: {pnl_pct:.2f}%")
                            in_position = False

        except (ccxtpro.NetworkError, ccxtpro.ExchangeNotAvailable, asyncio.TimeoutError) as net_err:
            print(f"\n[⚠️ KONEKSI PUTUS]: {net_err}. Menyambung ulang dalam 5 detik...")
            await asyncio.sleep(5)

        except Exception as err:
            print(f"\n[❌ ERROR]: {err}")
            await asyncio.sleep(10)

        finally:
            await exchange.close()

if __name__ == '__main__':
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("\n🛑 Bot dihentikan secara manual.")