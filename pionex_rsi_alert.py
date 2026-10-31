#!/usr/bin/env python3
"""
Alertas RSI(14) para perpetuos de Pionex -> aviso por Telegram.
Solo usa la librería estándar de Python (no hay que instalar nada).

Uso:
  python pionex_rsi_alert.py              # alertas de 1H (se corre cada hora)
  python pionex_rsi_alert.py --diario     # alertas diarias (se corre 1 vez por día)
  python pionex_rsi_alert.py --test       # mensaje de prueba a Telegram
  python pionex_rsi_alert.py --estado     # muestra el RSI actual de todo, sin avisar
  python pionex_rsi_alert.py --buscar PEPE   # busca símbolos en Pionex
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------- CONFIGURACIÓN ----------------
PERIODO_RSI = 14

# --- Alertas de 1 HORA: avisa cuando el RSI cruza hacia ABAJO de este nivel ---
SIMBOLOS = [
    "HYPE_USDT_PERP",
    "SOL_USDT_PERP",
    "XRP_USDT_PERP",
    "BTC_USDT_PERP",
    "ETH_USDT_PERP",
    "MUX_USDT_PERP",     # Micron tokenizado
    "METAX_USDT_PERP",   # Meta tokenizado
    "WTI_USDT_PERP",
]
NIVEL_SOBREVENTA = 30
AVISAR_SOBRECOMPRA = True   # True = también avisa al cruzar hacia arriba de 70
NIVEL_SOBRECOMPRA = 70

# --- Alertas DIARIAS: cada una con su propio nivel ---
ALERTAS_DIARIAS = [
    {"simbolo": "BTC_USDT_PERP", "nivel": 38},
]
# ------------------------------------------------

BASE = "https://api.pionex.com"
TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# milisegundos que dura cada vela (para descartar la que todavía no cerró)
DURACION_MS = {"60M": 3_600_000, "1D": 86_400_000}


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


def velas_cerradas(simbolo, intervalo):
    j = get("/api/v1/market/klines", {"symbol": simbolo, "interval": intervalo, "limit": 300})
    if not j.get("result", True):
        raise RuntimeError(j.get("message") or j.get("code") or str(j))
    klines = sorted(j["data"]["klines"], key=lambda k: int(k["time"]))
    ahora_ms = int(time.time() * 1000)
    # descarta la vela en curso (todavía no cerró)
    if klines and int(klines[-1]["time"]) + DURACION_MS[intervalo] > ahora_ms:
        klines = klines[:-1]
    return [float(k["close"]) for k in klines]


def buscar(terminos):
    j = get("/api/v1/common/symbols", {"type": "PERP"})
    symbols = j["data"]["symbols"]
    for t in terminos:
        t = t.upper()
        res = [s["symbol"] for s in symbols if t in s["symbol"].upper()]
        print(f"{t}: {', '.join(res) if res else 'sin resultados'}")


def chequear(simbolo, intervalo, etiqueta, nivel_abajo, solo_estado, nivel_arriba=None, mensaje_extra=""):
    try:
        cierres = velas_cerradas(simbolo, intervalo)
        r = rsi_wilder(cierres, PERIODO_RSI)
        if len(r) < 2:
            print(f"{simbolo} [{etiqueta}]: pocos datos")
            return
        prev, last = r[-2], r[-1]
        print(f"{simbolo} [{etiqueta}]: RSI anterior {prev:.1f} -> actual {last:.1f} (cierre {cierres[-1]})")
        if solo_estado:
            return
        if prev >= nivel_abajo > last:
            telegram(f"🔻 {simbolo}: RSI(14) {etiqueta} cruzó por debajo de {nivel_abajo}. "
                     f"RSI {last:.1f} | cierre {cierres[-1]}{mensaje_extra}")
        elif nivel_arriba is not None and prev <= nivel_arriba < last:
            telegram(f"🔺 {simbolo}: RSI(14) {etiqueta} cruzó por encima de {nivel_arriba}. "
                     f"RSI {last:.1f} | cierre {cierres[-1]}")
    except Exception as e:
        print(f"{simbolo} [{etiqueta}]: ERROR -> {e}")


def revisar_1h(solo_estado=False):
    arriba = NIVEL_SOBRECOMPRA if AVISAR_SOBRECOMPRA else None
    for s in SIMBOLOS:
        chequear(s, "60M", "1H", NIVEL_SOBREVENTA, solo_estado, nivel_arriba=arriba)
        time.sleep(0.3)


def revisar_diario(solo_estado=False):
    for a in ALERTAS_DIARIAS:
        chequear(a["simbolo"], "1D", "DIARIO", a["nivel"], solo_estado)
        time.sleep(0.3)


if __name__ == "__main__":
    args = sys.argv[1:]
    modo = args[0] if args else ""
    if modo == "--test":
        telegram("✅ Bot de RSI funcionando")
    elif modo == "--buscar":
        buscar(args[1:] or ["BTC"])
    elif modo == "--estado":
        revisar_1h(solo_estado=True)
        revisar_diario(solo_estado=True)
    elif modo == "--diario":
        revisar_diario()
    else:
        revisar_1h()
