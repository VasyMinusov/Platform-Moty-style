"""
Secure Keypad — interactive PIN entry with a timing side-channel.

Уязвимость:
    Сравнение PIN идёт посимвольно с `time.sleep` за каждый правильный
    префикс. Значит, время ответа коррелирует с количеством угаданных
    цифр в правильных позициях. Классический timing attack.

Дополнительно:
    Через 100 неудачных попыток в логах появляется подсказка.
    В логах также видно суммарное число попыток (INFO).
"""
import os
import secrets
import time
from collections import deque
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

FLAG = os.environ.get("FLAG", "flag{t1m1ng_4tt4cks_4r3_r34l}")

PIN_LEN = 6
DELAY_PER_DIGIT_MS = 100     # +100 мс за каждую правильную цифру в позиции
MAX_LOG_LINES = 500

app = FastAPI()

# ── Глобальное состояние ────────────────────────────────────────────
# PIN один на весь сервис — не на сессию. Все «играют» один и тот же PIN.
# Так честнее для соревнования: несколько команд могут решать параллельно,
# и это не мешает друг другу.
PIN = os.environ.get("PIN") or "".join(secrets.choice("0123456789")
                                       for _ in range(PIN_LEN))
print(f"[init] PIN generated: {PIN}", flush=True)

STATS = {"total_attempts": 0, "successful": 0}
LOGS: deque[str] = deque(maxlen=MAX_LOG_LINES)


def log(kind: str, msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {kind.ljust(5)} {msg}"
    LOGS.append(line)
    print(line, flush=True)


# ── Модель запроса ──────────────────────────────────────────────────
class CheckRequest(BaseModel):
    pin: str


# ── Endpoint ────────────────────────────────────────────────────────
@app.post("/api/check")
def check(req: CheckRequest, request: Request):
    STATS["total_attempts"] += 1
    submitted = (req.pin or "").strip()
    ip = request.headers.get("x-forwarded-for") or request.client.host

    # Некорректная длина — сразу отказ, без задержки.
    if len(submitted) != PIN_LEN or not submitted.isdigit():
        return {
            "ok": False,
            "message": f"PIN must be {PIN_LEN} digits",
            "attempts_total": STATS["total_attempts"],
        }

    # ── Тайминг-оракул ──────────────────────────────────────────────
    # Сравниваем посимвольно. За каждую совпавшую цифру — пауза
    # DELAY_PER_DIGIT_MS. Как только не совпало — выходим из цикла.
    correct_prefix = 0
    for i in range(PIN_LEN):
        if submitted[i] == PIN[i]:
            correct_prefix += 1
        else:
            break

    # Спим ДО return. Это и есть утечка.
    time.sleep(correct_prefix * DELAY_PER_DIGIT_MS / 1000.0)

    if submitted == PIN:
        STATS["successful"] += 1
        log("INFO", f"SUCCESS from {ip}")
        return {
            "ok": True,
            "flag": FLAG,
            "attempts_total": STATS["total_attempts"],
        }

    log("INFO",
        f"attempt from {ip} pin={submitted[:2]}*** prefix={correct_prefix}")
    _maybe_hint()

    return {
        "ok": False,
        "message": "wrong PIN",
        "attempts_total": STATS["total_attempts"],
    }


def _maybe_hint() -> None:
    """Через 100 попыток пишем в лог подсказку."""
    n = STATS["total_attempts"]
    # Не спамим: пишем на 100-й, 200-й и т.д.
    if n >= 100 and n % 100 == 0:
        log("DEBUG", "hint: response time grows with correct prefix length")
        log("DEBUG", "hint: measure wall-clock, not the response body")


# ── Служебный лог ───────────────────────────────────────────────────
@app.get("/api/logs")
def logs():
    """Последние 500 строк. Полезно при разработке и для подсказки."""
    return {
        "total_attempts": STATS["total_attempts"],
        "successful": STATS["successful"],
        "pin_length": PIN_LEN,
        "logs": list(LOGS),
    }


# ── Frontend ────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def index():
    with open("/app/static/index.html", "r", encoding="utf-8") as f:
        return f.read()