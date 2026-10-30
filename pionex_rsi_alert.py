#!/usr/bin/env python3
"""
Alerta RSI(14) 1H para perpetuos de Pionex -> aviso por Telegram.
Solo usa la librería estándar de Python (no hay que instalar nada).

Uso:
  python pionex_rsi_alert.py            # revisa los activos y avisa
  python pionex_rsi_alert.py --test     # manda un mensaje de prueba a Telegram
  python pionex_rsi_alert.py --buscar MU META CL   # busca los símbolos reales en Pionex
  python pionex_rsi_alert.py --estado   # muestra el RSI actual de todos (sin avisar)
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------- CONFIGURACIÓN ----------------
# Ajustá los símbolos si alguno no existe. Usá --buscar para encontrarlos.
SIMBOLOS = [
    "HYPE_USDT_PERP",
    "SOL_USDT_PERP",
    "XRP_USDT_PERP",
    "BTC_USDT_PERP",
    "ETH_USDT_PERP",
    "MUX_USDT_PERP",     # Micron tokenizado (MUXUSDT.P)
    "METAX_USDT_PERP",   # Meta tokenizado (METAXUSDT.P)
    "WTI_USDT_PERP",
]
PERIODO_RSI = 14
INTERVALO = "60M"          # 1 hora
NIVEL_SOBREVENTA = 30
AVISAR_SOBRECOMPRA = False # poné True para avisar también al cruzar hacia arriba de 70
NIVEL_SOBRECOMPRA = 70
# ------------------------------------------------

BASE = "https://api.pionex.com"
TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def get(path, params):
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "rsi-alert/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def telegram(texto):
    if not TOKEN or not CHAT_ID:
        print("[sin Telegram configurado] faltan los secretos:", texto)
        return
    data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": texto}).encode()
    try:
        urllib.request.urlopen(
            urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=data),
            timeout=20,
        )
        print("[Telegram] mensaje enviado")
    except urllib.error.HTTPError as e:
        print(f"[ERROR TELEGRAM] {e.code}: {e.read().decode()}")
        print("  -> 403/400: tocá Start en tu bot y revisá TELEGRAM_CHAT_ID (tu número personal)")
        print("  -> 401: el TELEGRAM_TOKEN está mal")
    except Exception as e:
        print(f"[ERROR TELEGRAM] {e}")


def rsi_wilder(cierres, n=14):
    """RSI con suavizado de Wilder (igual que TradingView). Devuelve lista de RSI."""
    if len(cierres) < n + 1:
        return []
    ganancias, perdidas = [], []
    for i in range(1, len(cierres)):
        d = cierres[i] - cierres[i - 1]
        ganancias.append(max(d, 0))
        perdidas.append(max(-d, 0))
    avg_g = sum(ganancias[:n]) / n
    avg_p = sum(perdidas[:n]) / n

    def calc(g, p):
        return 100.0 if p == 0 else 100 - 100 / (1 + g / p)

    out = [calc(avg_g, avg_p)]
    for i in range(n, len(ganancias)):
        avg_g = (avg_g * (n - 1) + ganancias[i]) / n
        avg_p = (avg_p * (n - 1) + perdidas[i]) / n
        out.append(calc(avg_g, avg_p))
    return out


def velas_cerradas(simbolo):
    j = get("/api/v1/market/klines", {"symbol": simbolo, "interval": INTERVALO, "limit": 300})
    if not j.get("result", True):
        raise RuntimeError(j.get("message") or j.get("code") or str(j))
    klines = j["data"]["klines"]
    klines = sorted(klines, key=lambda k: int(k["time"]))
    ahora_ms = int(time.time() * 1000)
    # descarta la vela en curso (todavía no cerró)
    if klines and int(klines[-1]["time"]) + 3600_000 > ahora_ms:
        klines = klines[:-1]
    return [float(k["close"]) for k in klines]


def buscar(terminos):
    j = get("/api/v1/common/symbols", {"type": "PERP"})
    symbols = j["data"]["symbols"]
    for t in terminos:
        t = t.upper()
        res = [s["symbol"] for s in symbols if t in s["symbol"].upper()]
        print(f"{t}: {', '.join(res) if res else 'sin resultados'}")


def revisar(solo_estado=False):
    for s in SIMBOLOS:
        try:
            cierres = velas_cerradas(s)
            r = rsi_wilder(cierres, PERIODO_RSI)
            if len(r) < 2:
                print(f"{s}: pocos datos")
                continue
            prev, last = r[-2], r[-1]
            print(f"{s}: RSI anterior {prev:.1f} -> actual {last:.1f} (cierre {cierres[-1]})")
            if solo_estado:
                continue
            if prev >= NIVEL_SOBREVENTA > last:
                telegram(f"🔻 {s}: RSI(14) 1H cruzó por debajo de {NIVEL_SOBREVENTA} "
                         f"(sobreventa). RSI {last:.1f} | cierre {cierres[-1]}")
            elif AVISAR_SOBRECOMPRA and prev <= NIVEL_SOBRECOMPRA < last:
                telegram(f"🔺 {s}: RSI(14) 1H cruzó por encima de {NIVEL_SOBRECOMPRA} "
                         f"(sobrecompra). RSI {last:.1f} | cierre {cierres[-1]}")
        except Exception as e:
            print(f"{s}: ERROR -> {e}  (revisá el símbolo con --buscar)")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--test":
        telegram("✅ Bot de RSI funcionando")
    elif args and args[0] == "--buscar":
        buscar(args[1:] or ["MUX", "METAX", "CL"])
    elif args and args[0] == "--estado":
        revisar(solo_estado=True)
    else:
        revisar()
