# -*- coding: utf-8 -*-
"""
PiXeL Music  -  AI STUDIO PIXEL
Музыкальная соцсеть: один файл, только стандартная библиотека Python.

Запуск: открой файл и нажми ▶, затем открой в браузере адрес из консоли (http://127.0.0.1:8080).
Друзья из твоей Wi-Fi сети заходят по адресу вида http://192.168.x.x:8080
Все данные лежат рядом со скриптом в папке pixel_data (db.json + files).

Админ: пользователь с ником из ADMINS (по умолчанию kagaram). Ник админа можно создать только
с устройства, на котором запущен сервер (или задать пароль админа переменной PIXEL_ADMIN_PASSWORD).

Настройки можно менять без правки кода:
  - переменные окружения: PORT, PIXEL_DATA, PIXEL_ADMINS, PIXEL_PUBLIC_URL, NGROK_TOKEN,
    PIXEL_ADMIN_PASSWORD, PIXEL_TRUST_PROXY (подробности в README.md);
  - файл config_local.py рядом со скриптом (в Git не попадает), удобно для Pydroid.
"""
import json, os, re, time, uuid, hashlib, secrets, socket, threading, mimetypes, atexit, traceback
import urllib.request, urllib.error, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote

# ============================== НАСТРОЙКИ ==============================
def _env(name, default=""):
    return os.environ.get(name, default)


try:
    PORT = int(_env("PORT", "8080") or 8080)
except ValueError:
    PORT = 8080
ADMINS = {n.strip().lower() for n in (_env("PIXEL_ADMINS") or "kagaram").split(",") if n.strip()}   # ники администраторов
ADMIN_PASSWORD = _env("PIXEL_ADMIN_PASSWORD")   # если задан: админ создаётся при первом запуске (для хостинга)
TRUST_PROXY = _env("PIXEL_TRUST_PROXY").lower() in ("1", "true", "yes")   # сайт стоит за прокси/хостингом (берём IP из X-Forwarded-For)

# --- ДЛЯ ТЕСТА С ДРУЗЬЯМИ (необязательно, при релизе блок можно оставить пустым) ---
PUBLIC_URL = _env("PIXEL_PUBLIC_URL")   # адрес, по которому сайт открывают другие (свой домен). Пусто = текущий адрес
NGROK_TOKEN = _env("NGROK_TOKEN")   # бесплатный токен с ngrok.com: сайт получит публичную ссылку. Нужен: pip install pyngrok
# -------------------------------------------------------------------------------

MAX_AUDIO = 300 * 1024 * 1024   # 300 МБ на трек
MAX_IMAGE = 10 * 1024 * 1024    # 10 МБ на картинку
REG_PER_IP_DAY = 3              # аккаунтов с одного IP за сутки
REG_PER_DEVICE = 2              # аккаунтов на одно устройство
REG_COOLDOWN = 30               # пауза между регистрациями с одного IP, сек
MSG_PER_MIN = 20                # сообщений в минуту от одного пользователя
# =========================================================================

try:
    BASE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    BASE = os.getcwd()
# необязательный локальный файл настроек (в Git не попадает): config_local.py
_cfg_path = os.path.join(BASE, "config_local.py")
if os.path.exists(_cfg_path):
    try:
        _ns = {}
        with open(_cfg_path, encoding="utf-8") as _f:
            exec(compile(_f.read(), _cfg_path, "exec"), _ns)
        for _k in ("PORT", "PUBLIC_URL", "NGROK_TOKEN", "ADMIN_PASSWORD", "TRUST_PROXY"):
            if _k in _ns:
                globals()[_k] = _ns[_k]
        if "ADMINS" in _ns:
            ADMINS = {str(n).strip().lower() for n in _ns["ADMINS"]}
        if _ns.get("DATA_DIR"):
            os.environ["PIXEL_DATA"] = str(_ns["DATA_DIR"])
    except Exception as _e:
        print("config_local.py не прочитан:", _e)
DATA = _env("PIXEL_DATA") or os.path.join(BASE, "pixel_data")
FILES = os.path.join(DATA, "files")
DBF = os.path.join(DATA, "db.json")
os.makedirs(FILES, exist_ok=True)

for _e, _t in ((".mp3", "audio/mpeg"), (".m4a", "audio/mp4"), (".mp4", "video/mp4"), (".aac", "audio/aac"),
               (".flac", "audio/flac"), (".ogg", "audio/ogg"), (".wav", "audio/wav")):
    mimetypes.add_type(_t, _e)

AUDIO_EXT = {"mp3", "mp4", "m4a", "wav", "ogg", "aac", "flac", "webm"}
IMAGE_EXT = {"jpg", "jpeg", "png", "webp", "gif"}
IMG_URL = re.compile(r"^/files/[0-9a-f]{32}\.(jpg|jpeg|png|webp|gif)$")
FILE_NAME = re.compile(r"^[0-9a-f]{32}\.[a-z0-9]{2,5}$")

HTML = r'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#06080f">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" href="/icon-192.png">
<link rel="apple-touch-icon" href="/icon-192.png">
<title>Music GitHub PiXeL</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Exo+2:ital,wght@0,500;0,700;0,800;0,900;1,800;1,900&display=swap">
<style>
:root{--acc:#3d7bff;--acc2:#2a56b3;--accrgb:61,123,255;--bg:#06080f;--s1:#0c1220;--s2:#131b30;--line:#1d2846;--on:#fff;--txt:#eef1fb;--mut:#8a94b0;--red:#ff5d6c;
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;min-height:100%;background:var(--bg);color:var(--txt);font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;font-size:15px}
body{background-image:radial-gradient(700px 420px at 50% -140px,rgba(var(--accrgb),.20),transparent 70%);background-repeat:no-repeat;background-attachment:fixed}
.app{max-width:720px;margin:0 auto;padding:calc(14px + env(safe-area-inset-top)) 14px 220px}
.ic{width:22px;height:22px;display:block;flex:none}
header.top{display:flex;align-items:center;gap:11px;padding:4px 4px 16px}
.wm{font-weight:900;font-size:18px;letter-spacing:-.2px;font-style:italic;text-transform:uppercase}.wm b{color:var(--acc)}
.lab{font-size:12px;font-weight:800;letter-spacing:1.4px;text-transform:uppercase;color:var(--mut)}
h2,h3{margin:0 0 10px;letter-spacing:-.2px}
h3.lab{margin:20px 4px 8px}
.mut,small{color:var(--mut)}
.center{text-align:center}
.hint{font-size:13px;color:var(--mut);margin:8px 0}
.card{background:var(--s1);border:1px solid var(--line);border-radius:26px;padding:18px;margin:12px 0}
input:not([type=range]):not([type=checkbox]):not([type=color]),textarea,select{width:100%;padding:14px 16px;border-radius:18px;border:1px solid var(--line);background:rgba(0,0,0,.35);color:var(--txt);font:inherit;outline:none;margin:6px 0;appearance:none;-webkit-appearance:none}
input:focus,textarea:focus,select:focus{border-color:var(--acc)}
textarea{min-height:90px;resize:vertical}
select option{background:var(--s1)}
label.l{display:block;margin-top:12px}
.btn{display:flex;align-items:center;justify-content:center;gap:9px;width:100%;padding:14px 18px;border:1px solid transparent;border-radius:999px;background:linear-gradient(135deg,var(--acc),var(--acc2));color:var(--on);font:inherit;font-weight:800;font-size:14px;letter-spacing:.6px;text-transform:uppercase;cursor:pointer;margin:8px 0;text-decoration:none;box-shadow:0 8px 24px rgba(var(--accrgb),.30)}
.btn.sec{background:rgba(255,255,255,.04);border-color:var(--line);color:var(--txt);box-shadow:none}
.btn.red{background:transparent;border-color:var(--red);color:var(--red);box-shadow:none}
.btn.sm{width:auto;padding:11px 18px;margin:0}
.btn[disabled]{opacity:.4;pointer-events:none}
.btn:active{transform:scale(.98)}
.btns{display:flex;gap:8px;flex-wrap:wrap}.btns .btn{flex:1;min-width:120px}
.diagw{position:relative;display:block;width:84%;margin:26px auto 12px;transform:skewX(-12deg);text-decoration:none;color:var(--on)}
.diagw::before{content:"";position:absolute;inset:0;border:1.5px solid var(--acc);border-radius:12px;transform:translate(7px,7px);opacity:.8}
.diagw .in{position:relative;display:flex;align-items:center;justify-content:center;gap:12px;padding:17px 18px;border-radius:12px;background:linear-gradient(135deg,var(--acc),var(--acc2));font-weight:900;font-style:italic;text-transform:uppercase;letter-spacing:1.4px;font-size:14px;box-shadow:0 12px 30px rgba(var(--accrgb),.4)}
.diagw .in>*{transform:skewX(12deg)}
.diagw svg{width:24px;height:24px;fill:currentColor}
.seg{display:flex;gap:4px;padding:5px;border-radius:999px;background:var(--s1);border:1px solid var(--line);margin:14px 0 8px}
.seg button{flex:1;padding:11px 6px;border:0;border-radius:999px;background:transparent;color:var(--mut);font:inherit;font-weight:800;font-size:12px;letter-spacing:1px;text-transform:uppercase;cursor:pointer}
.seg button.on{background:linear-gradient(135deg,var(--acc),var(--acc2));color:var(--on)}
.row{display:flex;align-items:center;gap:12px;padding:8px 8px 8px 8px;border-radius:20px;cursor:pointer;margin:3px 0;border:1px solid transparent}
.row:active{background:var(--s2)}
.row.on{background:var(--s2);border-color:rgba(var(--accrgb),.5)}
.row.on .meta b{color:var(--acc)}
.cv{width:50px;height:50px;border-radius:14px;overflow:hidden;flex:none;background:var(--s2)}
.cv img{width:100%;height:100%;object-fit:cover;display:block}
.meta{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px}
.meta b,.meta small{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ib{border:0;background:transparent;color:var(--mut);width:40px;height:40px;border-radius:50%;cursor:pointer;display:grid;place-items:center;flex:none}
.ib:active{background:var(--s2)}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}
.chip{padding:9px 14px;border-radius:999px;border:1px solid var(--line);background:transparent;color:var(--txt);font:inherit;font-size:14px;font-weight:600;cursor:pointer}
.chip.on{background:linear-gradient(135deg,var(--acc),var(--acc2));border-color:transparent;color:var(--on)}
.sws{display:flex;flex-wrap:wrap;gap:10px;margin:10px 0;align-items:center}
.sw{width:38px;height:38px;border-radius:50%;border:2px solid transparent;cursor:pointer;padding:0;outline:2px solid transparent;outline-offset:2px}
.sw.on{outline-color:var(--txt)}
.sw.none{background:repeating-linear-gradient(45deg,#333 0 4px,#222 4px 8px)}
input[type=color]{width:38px;height:38px;border:0;border-radius:50%;padding:0;background:none;cursor:pointer}
/* профиль в стиле игровой карточки */
.pcard{position:relative;border-radius:32px;overflow:hidden;padding:20px 18px 18px;background:var(--s2) center/cover;border:1px solid var(--line);isolation:isolate;margin:12px 0}
.pcard::before{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.30),rgba(0,0,0,.74));z-index:-1}
.pcard.nb::before{background:radial-gradient(420px 260px at 20% 0%,rgba(var(--accrgb),.35),rgba(0,0,0,.6))}
.phead{display:flex;gap:16px;align-items:center}
.ava{width:118px;height:118px;border-radius:50%;padding:6px;flex:none;background:conic-gradient(var(--acc) 0 14%,rgba(255,255,255,.16) 14% 100%)}
.ava .ai{width:100%;height:100%;border-radius:50%;overflow:hidden;background:var(--s2);display:grid;place-items:center;font-size:44px;font-weight:900;color:var(--acc)}
.ava img{width:100%;height:100%;object-fit:cover;display:block}
.pinfo{min-width:0;flex:1}
.pst{font-size:13px;font-weight:700;color:rgba(255,255,255,.65);display:flex;align-items:center;gap:7px}
.pname{font-size:32px;font-weight:900;font-style:italic;letter-spacing:-.5px;text-transform:uppercase;line-height:1.02;text-shadow:0 2px 14px rgba(0,0,0,.8);overflow-wrap:anywhere;margin:2px 0}
.pid{color:rgba(255,255,255,.55);font-weight:700;font-size:13px;margin:2px 0 9px}
.pills{display:flex;flex-wrap:wrap;gap:7px}
.pill{display:inline-flex;align-items:center;gap:6px;padding:7px 13px;border-radius:999px;font-size:11px;font-weight:900;letter-spacing:1.2px;text-transform:uppercase;border:1px solid rgba(var(--accrgb),.7);background:rgba(var(--accrgb),.14);color:var(--acc)}
.pill.f{background:linear-gradient(135deg,var(--acc),var(--acc2));color:var(--on);border-color:transparent;box-shadow:0 4px 16px rgba(var(--accrgb),.4)}
.pill.g{border-color:rgba(52,211,153,.6);background:rgba(52,211,153,.12);color:#34d399}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:#34d399;box-shadow:0 0 8px #34d399}
.dot.off{background:#56607a;box-shadow:none}
.ptrack{display:flex;align-items:center;gap:12px;margin-top:16px;padding:10px;border-radius:26px;background:rgba(0,0,0,.5);border:1px solid rgba(var(--accrgb),.6);box-shadow:0 0 24px rgba(var(--accrgb),.2);cursor:pointer}
.ptrack .cv{width:58px;height:58px;border-radius:16px}
.ptrack .meta b{font-size:16px;font-weight:800}
.pb{width:50px;height:50px;border-radius:50%;border:0;background:linear-gradient(135deg,var(--acc),var(--acc2));color:var(--on);display:grid;place-items:center;cursor:pointer;flex:none;box-shadow:0 6px 18px rgba(var(--accrgb),.4)}
.about p{white-space:pre-wrap;margin:6px 0 0;color:#c9d0e4;line-height:1.45}
.rowh{display:flex;align-items:center;justify-content:space-between;gap:10px}
.rowh h3{margin:0}
.err{color:var(--red);font-size:14px;min-height:20px}
#tabs{position:fixed;left:10px;right:10px;max-width:700px;margin:0 auto;bottom:calc(10px + env(safe-area-inset-bottom));z-index:30;display:flex;gap:2px;padding:6px;border-radius:34px;background:rgba(12,14,22,.9);border:1px solid var(--line);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px)}
#tabs button{flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;padding:9px 2px 7px;border:1.5px solid transparent;border-radius:28px;background:transparent;color:var(--mut);font:inherit;font-size:10px;font-weight:800;letter-spacing:.8px;text-transform:uppercase;cursor:pointer}
#tabs button .ic{margin:0 auto}
#tabs button.on{color:var(--txt);border-color:var(--acc);box-shadow:0 0 18px rgba(var(--accrgb),.4),inset 0 0 12px rgba(var(--accrgb),.15)}
#tabs button.on .ic{color:var(--acc)}
#mini{position:fixed;left:10px;right:10px;max-width:700px;margin:0 auto;bottom:calc(88px + env(safe-area-inset-bottom));z-index:29;display:none;background:rgba(19,22,34,.94);border:1px solid rgba(var(--accrgb),.55);border-radius:28px;overflow:hidden;box-shadow:0 0 26px rgba(var(--accrgb),.22);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px)}
#mini.show{display:block}
.mrow{display:flex;align-items:center;gap:10px;padding:8px 8px 8px 8px;cursor:pointer}
.mrow .cv{width:46px;height:46px;border-radius:14px}
#mprog{height:3px;background:var(--acc);width:0;box-shadow:0 0 8px var(--acc)}
.foot{text-align:center;font-family:var(--mono);font-size:10px;letter-spacing:4px;color:var(--mut);opacity:.7;margin:30px 0 0}
.up{height:5px;background:var(--line);border-radius:5px;overflow:hidden;margin:10px 0 4px;display:none}.up i{display:block;height:100%;width:0;background:var(--acc)}
.pick{display:flex;align-items:center;gap:10px;padding:8px 12px 8px 10px;border-radius:18px;margin:4px 0;background:rgba(0,0,0,.3);border:1px solid var(--line);cursor:pointer}
.pick input{width:20px;height:20px;margin:0;accent-color:var(--acc)}
#toast{position:fixed;top:calc(12px + env(safe-area-inset-top));left:50%;transform:translateX(-50%);padding:12px 18px;border-radius:999px;z-index:300;display:none;max-width:90%;background:var(--s2);border:1px solid var(--acc);font-size:14px;font-weight:600}
/* auth */
#auth{min-height:76vh;display:flex;flex-direction:column;justify-content:center}
.hero{text-align:center;margin-bottom:10px}
.hero .wm{font-size:28px;margin-top:14px}
.tagl{font-size:12px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:var(--mut);margin:8px 0 0}
.atg{display:flex;align-items:center;border:1px solid var(--line);border-radius:18px;background:rgba(0,0,0,.35);margin:8px 0}
.atg span{padding-left:16px;color:var(--acc);font-weight:800}
.atg input{border:0!important;margin:0!important;background:transparent!important}
.code{text-align:center;font-family:var(--mono);font-size:30px!important;letter-spacing:12px;padding-left:24px!important}
.step{display:flex;gap:6px;margin:0 0 14px}.step i{flex:1;height:4px;border-radius:2px;background:var(--line)}.step i.on{background:var(--acc)}
.bot{display:flex;align-items:center;gap:10px;padding:14px;border:1px dashed var(--line);border-radius:18px;margin:10px 0;font-size:14px}
/* полноэкранный плеер */
#sheet{position:fixed;inset:0;z-index:60;background:var(--bg);display:none;overflow:hidden}
#sheet.open{display:block}
#sbg{position:absolute;inset:-60px;background:center/cover;filter:blur(55px) saturate(1.4);opacity:.5;transform:scale(1.15)}
.sin{position:relative;height:100%;max-width:520px;margin:0 auto;padding:calc(12px + env(safe-area-inset-top)) 22px calc(18px + env(safe-area-inset-bottom));display:flex;flex-direction:column;overflow-y:auto}
.shead{display:flex;align-items:center;justify-content:space-between}
.bigcov{width:min(100%,340px);aspect-ratio:1;margin:16px auto 14px;border-radius:28px;overflow:hidden;box-shadow:0 26px 60px rgba(0,0,0,.6),0 0 40px rgba(var(--accrgb),.25);transition:transform .35s;transform:scale(.88);background:var(--s2);flex:none}
.playing .bigcov{transform:scale(1)}
.bigcov img{width:100%;height:100%;object-fit:cover;display:block}
.sti{display:flex;flex-direction:column;gap:3px;margin:4px 0 0}
.sti b{font-size:22px;font-weight:900;letter-spacing:-.3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sti span{color:var(--mut);font-weight:600}
.eq{display:flex;gap:3px;align-items:flex-end;height:22px;margin:12px 0 4px}
.eq i{width:3px;height:100%;border-radius:2px;background:var(--acc);transform-origin:bottom;transform:scaleY(.12);animation:eq 1s ease-in-out infinite;animation-play-state:paused}
.playing .eq i{animation-play-state:running}
@keyframes eq{0%,100%{transform:scaleY(.12)}50%{transform:scaleY(1)}}
.times{display:flex;justify-content:space-between;font-family:var(--mono);font-size:11px;color:var(--mut);margin-top:8px}
.ctl{display:flex;align-items:center;justify-content:space-between;margin:12px 0 6px}
.cb{width:50px;height:50px;border:0;background:transparent;color:var(--txt);display:grid;place-items:center;cursor:pointer;border-radius:50%}
.cb .ic{width:26px;height:26px}
.cb.sm{color:var(--mut)}.cb.sm.on{color:var(--acc)}
.cb.big{width:76px;height:76px;background:linear-gradient(135deg,var(--acc),var(--acc2));color:var(--on);box-shadow:0 10px 30px rgba(var(--accrgb),.45)}.cb.big .ic{width:32px;height:32px}
.srow{display:flex;align-items:center;gap:12px;margin:10px 0}
.sq{flex:1}
.lite #sbg{filter:none;opacity:.2}
.lite .eq i,.lite .bigcov{animation:none;transition:none}
.lite #tabs,.lite #mini{-webkit-backdrop-filter:none;backdrop-filter:none}
/* загрузка */
#splash{position:fixed;inset:0;z-index:500;background:var(--bg);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;transition:opacity .5s}
#splash.out{opacity:0;pointer-events:none}
.sp-logo svg{width:96px;height:96px;border-radius:24px;filter:drop-shadow(0 0 26px rgba(var(--accrgb),.6))}
.sp-logo rect.c{animation:pxl 1.4s ease-in-out infinite}
@keyframes pxl{0%,100%{opacity:.2}50%{opacity:1}}
.sp-t{font-size:32px;font-weight:900;font-style:italic;letter-spacing:-.5px;text-transform:uppercase}.sp-t b{color:var(--acc)}
.sp-s{font-size:14px;font-weight:700;letter-spacing:2px;color:var(--mut)}
.sp-s::after{content:"";animation:dots 1.6s steps(1) infinite}
@keyframes dots{0%{content:""}20%{content:"."}40%{content:".."}60%{content:"..."}80%{content:"...."}}
.sp-bar{width:170px;height:4px;background:var(--line);border-radius:4px;overflow:hidden}
.sp-bar i{display:block;height:100%;width:40%;border-radius:4px;background:var(--acc);animation:spbar 1.2s ease-in-out infinite}
@keyframes spbar{0%{transform:translateX(-100%)}100%{transform:translateX(260%)}}
#modal{position:fixed;inset:0;z-index:250;display:none;background:rgba(0,0,0,.65);align-items:center;justify-content:center;padding:20px}
#modal.open{display:flex}
.mbox{background:var(--s1);border:1px solid var(--line);border-radius:28px;padding:22px;max-width:420px;width:100%}
.mbox ol{padding-left:20px;line-height:1.6;color:#c9d0e4}
.ni{display:grid;place-items:center;width:100%;height:100%;color:var(--acc);background:rgba(var(--accrgb),.12)}
.ni .ic{width:48%;height:48%;opacity:.85}
.dur{font-family:var(--mono);font-size:12px;color:var(--mut);padding:0 4px;flex:none}
#sbg.nc{background-image:radial-gradient(circle at 30% 20%,rgba(var(--accrgb),.6),transparent 65%)!important}
#tabs button{font-size:9.5px;letter-spacing:.3px}
.st-flat .btn,.st-flat .pb,.st-flat .cb.big,.st-flat .diagw .in,.st-flat .pill.f{box-shadow:none}
.st-flat #tabs button.on,.st-flat #mini,.st-flat .ptrack,.st-flat .bigcov{box-shadow:none}
.st-flat body,body.st-flat{background-image:none}
.st-glass .card,.st-glass .row.on,.st-glass .seg{background:rgba(255,255,255,.05);-webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px)}
.st-glass{background-image:radial-gradient(700px 420px at 50% -140px,rgba(var(--accrgb),.28),transparent 70%),radial-gradient(500px 400px at 100% 60%,rgba(var(--accrgb),.12),transparent 70%)}
.lite *{-webkit-backdrop-filter:none!important;backdrop-filter:none!important}
button,.row,.chip,.sw,.seg button,#tabs button,.cb,.pb,.ib{touch-action:manipulation;user-select:none;-webkit-user-select:none}
.row{content-visibility:auto;contain-intrinsic-size:auto 66px}
.cv{position:relative}
.eqm{position:absolute;inset:0;display:none;align-items:flex-end;justify-content:center;gap:3px;padding-bottom:13px;background:rgba(0,0,0,.5)}
.row.on .eqm{display:flex}
.eqm i{width:4px;height:55%;background:var(--acc);border-radius:2px;transform-origin:bottom;animation:eq .8s ease-in-out infinite}
.eqm i:nth-child(2){animation-delay:-.3s;animation-duration:.65s}.eqm i:nth-child(3){animation-delay:-.55s;animation-duration:.95s}
.ppaused .eqm i{animation-play-state:paused}
.btn:active,.row:active,.chip:active,.sw:active{transform:scale(.97);transition:transform .06s}
.buf .mrow .cv,.buf .bigcov{animation:bufp 1s ease-in-out infinite}
@keyframes bufp{50%{opacity:.55}}
.skel{height:62px;border-radius:20px;margin:10px 0;background:linear-gradient(90deg,var(--s1),var(--s2),var(--s1));background-size:200% 100%;animation:shim 1.2s linear infinite}
@keyframes shim{to{background-position:-200% 0}}
.lite .skel{animation:none}
/* ===== v6: ползунки (исправлена ошибка громкости), навигация, чат, импорт, фон ===== */
input[type=range]{-webkit-appearance:none;appearance:none;background:transparent;width:100%;height:28px;margin:0;padding:0;outline:none;--pn:0}
input[type=range]::-webkit-slider-runnable-track{height:5px;border-radius:3px;background:linear-gradient(90deg,var(--acc) calc(9px + (100% - 18px)*var(--pn)),var(--line) calc(9px + (100% - 18px)*var(--pn)))}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:18px;height:18px;border-radius:50%;background:#fff;margin-top:-6.5px;box-shadow:0 0 0 4px rgba(var(--accrgb),.35)}
input[type=range]::-moz-range-track{height:5px;border-radius:3px;background:var(--line)}
input[type=range]::-moz-range-progress{height:5px;border-radius:3px;background:var(--acc)}
input[type=range]::-moz-range-thumb{width:18px;height:18px;border:0;border-radius:50%;background:#fff}
.app{position:relative;z-index:1}
#view.vin{animation:vin .32s cubic-bezier(.2,.9,.3,1)}
@keyframes vin{from{opacity:0;transform:translateY(10px)}}
.lite #view.vin{animation:none}
/* навигация: только иконки, чат по центру */
#tabs{padding:5px;gap:0;border-radius:36px}
#tabs button{position:relative;z-index:1;height:50px;padding:0;gap:0;justify-content:center;border:0;background:transparent;color:var(--mut);transition:color .25s}
#tabs button.on{color:var(--txt);border:0;box-shadow:none}
#tabs button .ic{width:24px;height:24px;transition:transform .35s cubic-bezier(.3,1.5,.4,1),color .25s}
#tabs button.on .ic{color:var(--acc);transform:scale(1.14)}
#tabs button[data-tab=chats] .ic{width:28px;height:28px}
.tind{position:absolute;top:5px;bottom:5px;left:0;width:0;border-radius:30px;border:1.5px solid var(--acc);background:rgba(var(--accrgb),.12);box-shadow:0 0 18px rgba(var(--accrgb),.4);transition:transform .45s cubic-bezier(.3,1.25,.4,1),width .45s cubic-bezier(.3,1.25,.4,1);pointer-events:none}
#tabs button.pop .ic{animation:tpop .5s}
@keyframes tpop{30%{transform:scale(.7)}60%{transform:scale(1.28)}}
.tbdg{position:absolute;top:2px;left:calc(50% + 7px);min-width:19px;height:19px;padding:0 5px;border-radius:10px;background:var(--red);color:#fff;font-size:11px;font-weight:900;display:none;align-items:center;justify-content:center;box-shadow:0 0 0 2px var(--s1)}
#mini{bottom:calc(78px + env(safe-area-inset-bottom))}
.chip,.seg button{transition:background-color .22s,color .22s,border-color .22s,transform .12s}
.chip.on,.seg button.on{background:var(--acc);background-image:none}
/* переключатель */
.trow{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:12px 2px;cursor:pointer;border-bottom:1px solid var(--line)}
.trow:last-of-type{border-bottom:0}
.tt{display:flex;flex-direction:column;gap:2px;min-width:0}.tt small{color:var(--mut)}
.sw2{width:54px;height:32px;border-radius:32px;background:var(--line);position:relative;flex:none;transition:background-color .3s}
.sw2 i{position:absolute;top:3px;left:3px;width:26px;height:26px;border-radius:50%;background:#fff;transition:transform .34s cubic-bezier(.3,1.5,.4,1);box-shadow:0 2px 6px rgba(0,0,0,.4)}
.sw2.on{background:var(--acc)}.sw2.on i{transform:translateX(22px)}
.info{margin-top:12px;padding:14px;border-radius:18px;background:rgba(0,0,0,.28);border:1px dashed var(--line);font-size:14px;line-height:1.45;color:#c9d0e4}
.info ul{margin:8px 0 0;padding-left:18px}.info li{margin:5px 0}.info em{color:var(--acc);font-style:normal;font-weight:800}
/* аватарки, значки */
.av{width:48px;height:48px;border-radius:50%;overflow:hidden;background:#fff;flex:none;position:relative}
.av img,.av svg{width:100%;height:100%;object-fit:cover;display:block}
.av.lg{width:58px;height:58px}.av.xs{width:22px;height:22px}
.av .pd,.pbub .pd{position:absolute;right:1px;bottom:1px;border:2px solid var(--s1);width:14px;height:14px}
.bdg{min-width:22px;height:22px;padding:0 6px;border-radius:11px;background:var(--acc);color:var(--on);font-size:12px;font-weight:900;display:inline-flex;align-items:center;justify-content:center;box-shadow:0 0 12px rgba(var(--accrgb),.5)}
.cmt{display:flex;flex-direction:column;align-items:flex-end;gap:6px;flex:none}
.empty{text-align:center;padding:34px 16px;color:var(--mut)}
.empty .ic{width:46px;height:46px;margin:0 auto 10px;opacity:.6;color:var(--acc)}
.empty p{margin:0 0 4px;color:var(--txt);font-weight:800;font-size:17px}
.sbox{display:flex;align-items:center;gap:10px;padding:2px 16px;color:var(--mut)}
.sbox input,.sbox2 input{border:0!important;background:transparent!important;margin:0!important;padding:14px 0!important}
.sbox2{display:flex;align-items:center;gap:10px;padding:0 14px;border:1px solid var(--line);border-radius:18px;background:rgba(0,0,0,.35);margin:10px 0;color:var(--mut)}
.people{display:flex;gap:14px;overflow-x:auto;padding:4px 2px 10px;scrollbar-width:none}
.people::-webkit-scrollbar{display:none}
.pbub{display:flex;flex-direction:column;align-items:center;gap:6px;width:64px;flex:none;cursor:pointer;position:relative}
.pbub small{font-size:12px;font-weight:700;max-width:64px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pbub .av{border:2px solid var(--acc);padding:2px;background:var(--s1)}
.pbub .av svg,.pbub .av img{border-radius:50%}
/* карточка пользователя в поиске */
.ucard{position:relative;border-radius:24px;overflow:hidden;border:1px solid var(--line);background:var(--s2);margin:10px 0;cursor:pointer}
.ucard:active{transform:scale(.985)}
.ub{height:56px;background:linear-gradient(135deg,rgba(var(--accrgb),.55),rgba(var(--accrgb),.12)) center/cover}
.uin{display:flex;align-items:center;gap:12px;padding:0 12px 12px;margin-top:-26px}
.uin .av{border:3px solid var(--s2);width:60px;height:60px}
.uin .meta{padding-top:26px}
.msgb{margin-top:22px;background:rgba(var(--accrgb),.18)!important;color:var(--acc)!important;width:44px;height:44px}
.pills.tiny{margin-top:4px}.pills.tiny .pill{padding:3px 9px;font-size:10px}
.pill{--pc:var(--acc);--pcr:var(--accrgb);--pt:var(--on);border:1px solid rgba(var(--pcr),.7);background:rgba(var(--pcr),.14);color:var(--pc)}
.pill.f{background:linear-gradient(135deg,var(--pc),rgba(var(--pcr),.7));color:var(--pt);border-color:transparent;box-shadow:0 4px 16px rgba(var(--pcr),.4)}
.pill .ic{width:13px;height:13px}
.seen{color:rgba(255,255,255,.5);font-weight:600}
.lockc{display:flex;gap:14px;align-items:center;color:var(--mut)}.lockc .ic{width:30px;height:30px;color:var(--acc);flex:none}
.lockc b{display:block;color:var(--txt)}
.offc{display:flex;gap:14px;align-items:center;border-color:var(--red)}.offc .ic{width:32px;height:32px;color:var(--red);flex:none}
.offc b{display:block}.offc small{color:var(--mut)}
/* плейлисты */
.cv.big{width:96px;height:96px;border-radius:22px;flex:none}
.plhead{display:flex;gap:14px;align-items:center}
.plcov{display:flex;gap:14px;align-items:center;margin-bottom:6px}
.owner{display:flex;align-items:center;gap:8px;margin:6px 0 4px;cursor:pointer}
.owner small{color:var(--mut)}
.addb{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;background:rgba(255,255,255,.07);color:var(--mut);flex:none;transition:background-color .2s,color .2s,transform .2s}
.addb.on{background:var(--acc);color:var(--on);transform:scale(1.08)}
.mlist{max-height:46vh;overflow:auto;margin:6px 0 10px}
.row.ghost{opacity:.62}.gb{display:inline-flex;vertical-align:-3px;margin-right:5px}
.chip .ic{width:16px;height:16px;display:inline-block;vertical-align:-3px;margin-right:4px}
.chip.on .ic{fill:currentColor}
.srow.wrap .chips{margin:0}
.srow.wrap{flex-wrap:wrap}
/* чат */
#chat{position:fixed;left:0;right:0;top:0;height:100%;z-index:70;display:none;flex-direction:column;background:var(--bg)}
#chat.open{display:flex}
.chead{display:flex;align-items:center;gap:12px;padding:calc(10px + env(safe-area-inset-top)) 12px 10px;border-bottom:1px solid var(--line);background:var(--s1)}
.rbtn{width:46px;height:46px;border-radius:50%;border:0;background:rgba(255,255,255,.07);color:var(--txt);display:grid;place-items:center;cursor:pointer;flex:none}
.rbtn:active{transform:scale(.92)}
.chead .av{width:46px;height:46px}
.cmeta{flex:1;min-width:0;cursor:pointer}
.cmeta b{display:block;font-size:17px;font-weight:900;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cmeta small{color:var(--mut);font-weight:600}.cmeta small.on{color:#34d399}
#cmsgs{flex:1;overflow-y:auto;padding:14px 12px;display:flex;flex-direction:column;gap:6px;overscroll-behavior:contain}
.dsep{align-self:center;margin:10px 0 6px}
.dsep span{display:inline-block;padding:6px 16px;border-radius:999px;background:rgba(255,255,255,.07);font-size:13px;font-weight:800;color:var(--mut)}
.msg{max-width:80%;padding:10px 14px 7px;border-radius:22px;word-break:break-word}
.msg .mx{white-space:pre-wrap;font-size:16px;line-height:1.35;font-weight:600}
.msg .mt{display:flex;justify-content:flex-end;align-items:center;gap:5px;margin-top:3px;font-size:12px;font-weight:700;color:rgba(255,255,255,.62)}
.msg .tk{display:inline-flex}.msg .tk .ic{width:18px;height:18px}.msg .tk.rd{color:#fff}
.msg.out{align-self:flex-end;background:linear-gradient(160deg,rgba(var(--accrgb),.58),rgba(var(--accrgb),.22));border:1px solid rgba(var(--accrgb),.75);border-bottom-right-radius:8px;box-shadow:0 4px 18px rgba(var(--accrgb),.2)}
.msg.in{align-self:flex-start;background:var(--s2);border:1px solid var(--line);border-bottom-left-radius:8px}
.msg.pop{animation:msgpop .34s cubic-bezier(.2,1.25,.4,1)}
.msg.out.pop{transform-origin:100% 100%}.msg.in.pop{transform-origin:0 100%}
@keyframes msgpop{from{opacity:0;transform:translateY(16px) scale(.9)}}
.lite .msg.pop{animation:none}
.chatempty{margin:auto}
.cin{display:flex;align-items:flex-end;gap:10px;padding:10px 12px calc(12px + env(safe-area-inset-bottom));border-top:1px solid var(--line);background:var(--s1)}
#cinp{flex:1;resize:none;max-height:110px;min-height:48px;margin:0;padding:13px 18px;border-radius:26px;overflow-y:auto}
.cin .pb{width:50px;height:50px}
#cnote{display:none;text-align:center;color:var(--mut);padding:16px 18px calc(18px + env(safe-area-inset-bottom));border-top:1px solid var(--line);background:var(--s1);font-weight:600}
/* уведомление о сообщении */
#nbanner{position:fixed;left:10px;right:10px;max-width:700px;margin:0 auto;top:calc(8px + env(safe-area-inset-top));z-index:350;display:flex;align-items:center;gap:12px;padding:12px 16px 12px 12px;border-radius:32px;background:rgba(14,16,24,.97);border:1px solid var(--line);box-shadow:0 14px 40px rgba(0,0,0,.55);transform:translateY(-160%);opacity:0;transition:transform .55s cubic-bezier(.2,1.15,.3,1),opacity .3s;cursor:pointer}
#nbanner.show{transform:none;opacity:1}
#nbanner .av{width:56px;height:56px;border:2px solid var(--line)}
.nbt{flex:1;min-width:0}
.nbl{display:flex;align-items:center;gap:7px;font-size:12px;font-weight:900;letter-spacing:1.4px;color:var(--mut);text-transform:uppercase}
.nbl .ic{width:18px;height:18px}.nbl em{margin-left:auto;font-style:normal;letter-spacing:0;text-transform:none;font-size:13px;font-weight:700}
#nbn{display:block;font-size:20px;font-weight:900;margin-top:3px}
#nbm{display:block;color:var(--mut);font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* статистика */
.stats,.stats3{display:grid;gap:10px;margin:8px 0}
.stats{grid-template-columns:repeat(3,1fr)}.stats3{grid-template-columns:repeat(3,1fr)}
.stile{padding:14px 8px;border-radius:20px;background:var(--s1);border:1px solid var(--line);text-align:center}
.stats3 .stile{background:rgba(0,0,0,.28)}
.stile b{display:block;font-size:24px;font-weight:900;color:var(--acc)}.stile small{color:var(--mut);font-weight:700;font-size:12px}
.lab.sub{margin:18px 2px 8px}
.trk{display:flex;align-items:center;gap:12px;padding:8px 4px;cursor:pointer}
.rk{width:26px;height:26px;border-radius:9px;background:rgba(var(--accrgb),.18);color:var(--acc);display:grid;place-items:center;font-weight:900;font-size:13px;flex:none}
.bar{height:5px;border-radius:3px;background:var(--line);margin-top:6px;overflow:hidden}.bar i{display:block;height:100%;border-radius:3px;background:var(--acc)}
.cnt{font-weight:900;color:var(--mut);flex:none}
/* админка */
.arow{border-radius:20px;margin:6px 0;border:1px solid transparent}
.arow.open{background:var(--s2);border-color:var(--line)}
.adet{padding:4px 12px 14px}
.pill.rm{cursor:pointer}.pill.rm .ic{width:12px;height:12px}
.adet .atg{padding-right:6px}.adet .atg input{padding:12px 4px!important}
.rep{margin:6px 0;border-radius:18px;border:1px solid var(--line);overflow:hidden}
.rtext{margin:0;padding:12px;font:11px/1.45 var(--mono);white-space:pre-wrap;word-break:break-all;color:#c9d0e4;background:rgba(0,0,0,.35);max-height:300px;overflow:auto}
.lk{display:inline-block;padding:2px 8px;border-radius:7px;font:800 10px var(--mono);letter-spacing:.8px;text-transform:uppercase;background:rgba(255,255,255,.1);margin-right:4px}
.k-js,.k-server{background:rgba(255,93,108,.2);color:var(--red)}.k-api,.k-net{background:rgba(245,184,28,.2);color:#f5b81c}.k-promise{background:rgba(139,92,246,.22);color:#b69cff}.k-client{background:rgba(var(--accrgb),.2);color:var(--acc)}
/* импорт плейлистов */
.svcrow{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:12px 0}
.svc{display:flex;flex-direction:column;align-items:center;gap:6px;padding:10px 4px;border-radius:18px;border:1px solid var(--line);background:rgba(0,0,0,.25);opacity:.9;transition:transform .3s cubic-bezier(.3,1.4,.4,1),opacity .25s,border-color .25s}
.svc small{font-size:10.5px;font-weight:800;text-align:center;color:var(--mut);line-height:1.15}
.svcrow.has .svc{opacity:.3}.svcrow.has .svc.on{opacity:1;transform:translateY(-3px) scale(1.06);border-color:var(--acc);box-shadow:0 8px 24px rgba(var(--accrgb),.3)}
.svcrow.has .svc.on small{color:var(--txt)}
.imph{display:flex;gap:14px;align-items:center}
.svcb{display:flex;align-items:center;gap:7px;font-size:12px;font-weight:900;letter-spacing:1px;text-transform:uppercase;color:var(--mut)}
.row.noh{cursor:default}
/* фон приложения */
#bgm{position:fixed;inset:0;z-index:0;overflow:hidden;background:#000}
#bgm img,#bgm video{width:100%;height:100%;object-fit:cover;display:block}
#bgm::after{content:"";position:absolute;inset:0;background:rgba(0,0,0,var(--bgdim,.55))}
#bgm.blur img,#bgm.blur video{filter:blur(14px);transform:scale(1.1)}
html.has-bg,.has-bg body{background:#000!important;background-image:none!important}
.has-bg .card,.has-bg .ucard,.has-bg .stile{background:rgba(14,18,30,.62);-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px)}
.has-bg .row.on{background:rgba(255,255,255,.1)}
.bgnow{display:flex;align-items:center;gap:8px;margin:12px 0 0;color:var(--acc);font-weight:800}.bgnow .ic{width:18px;height:18px}
.lite.has-bg .card{-webkit-backdrop-filter:none;backdrop-filter:none}
/* журнал ошибок */
#logbar{position:fixed;left:10px;right:10px;max-width:700px;margin:0 auto;bottom:calc(150px + env(safe-area-inset-bottom));z-index:80;display:none;align-items:center;gap:10px;padding:8px 8px 8px 18px;border-radius:999px;background:#2a0f14;border:1px solid var(--red);color:#ffd4d9;font-weight:700;font-size:14px;box-shadow:0 10px 30px rgba(0,0,0,.5)}
#logbar.show{display:flex;animation:vin .3s}
#logbar span{flex:1}
#logbar .btn{width:auto;margin:0;padding:10px 16px;background:var(--red);border-color:var(--red);color:#fff;box-shadow:none}
#logwin{position:fixed;inset:0;z-index:400;display:none;flex-direction:column;background:var(--bg)}
#logwin.open{display:flex}
.lhead{display:flex;align-items:center;justify-content:space-between;padding:calc(12px + env(safe-area-inset-top)) 16px 10px;border-bottom:1px solid var(--line);background:var(--s1);font-size:18px}
#logbody{flex:1;overflow:auto;padding:12px 14px}
.linfo{margin:0 0 12px;padding:12px;border-radius:16px;background:rgba(0,0,0,.35);border:1px solid var(--line);font:11.5px/1.5 var(--mono);white-space:pre-wrap;word-break:break-word;color:#9fb0d6}
.le{padding:12px;border-radius:16px;background:var(--s1);border:1px solid var(--line);margin:8px 0}
.le .lh{display:flex;align-items:center;gap:8px;margin-bottom:6px}.le small{color:var(--mut)}
.le b{display:block;word-break:break-word}
.le pre{margin:8px 0 0;font:11px/1.45 var(--mono);white-space:pre-wrap;word-break:break-all;color:#9fb0d6;max-height:160px;overflow:auto}
.lfoot{padding:10px 14px calc(12px + env(safe-area-inset-bottom));border-top:1px solid var(--line);background:var(--s1)}
.lfoot textarea{min-height:64px;margin:0 0 6px}
.lfoot .btn{margin:6px 0 0}
#ytbox{position:fixed;z-index:66;display:none;background:#000;overflow:hidden;box-shadow:0 20px 50px rgba(0,0,0,.55)}
#ytbox iframe{width:100%;height:100%;border:0;display:block}
#sheet.yt .bigcov{transform:none}
.row.ghost{opacity:1}
.upseg{margin:10px 0 6px}.upseg button{display:flex;align-items:center;justify-content:center;gap:7px}.upseg .ic{width:17px;height:17px}
.vtag{display:inline-block;padding:1px 9px;border-radius:999px;background:rgba(var(--accrgb),.16);color:var(--acc);font-size:11px;font-weight:800;cursor:pointer}
.vtag.pv{background:rgba(255,255,255,.1);color:var(--mut)}
#nbx{flex:none;align-self:flex-start;margin:-6px -8px 0 0;color:var(--mut)}
#impbar{position:fixed;left:0;right:0;top:0;z-index:340;display:none;align-items:center;justify-content:space-between;gap:10px;padding:calc(6px + env(safe-area-inset-top)) 12px 6px;background:#3b1d00;border-bottom:1px solid #f5b81c;color:#ffd98a;font-weight:700;font-size:14px}
#impbar.show{display:flex}
#impbar .btn{width:auto;margin:0;padding:8px 14px;background:#f5b81c;border-color:#f5b81c;color:#1a1204;box-shadow:none}
body.imp .app{padding-top:calc(58px + env(safe-area-inset-top))}
.edet{margin:8px 0 0;padding:10px;border-radius:12px;background:rgba(0,0,0,.4);font:11px/1.4 var(--mono);white-space:pre-wrap;word-break:break-word;color:#9fb0d6}
.spin{display:inline-block;width:16px;height:16px;border-radius:50%;border:2.5px solid rgba(255,255,255,.35);border-top-color:#fff;animation:spn .7s linear infinite}
@keyframes spn{to{transform:rotate(360deg)}}
.btn.sending{opacity:.85;pointer-events:none}.btn.sent{background:#16a34a;border-color:#16a34a;color:#fff;box-shadow:none}.btn.fail{background:var(--red);border-color:var(--red);color:#fff;box-shadow:none}
#logok{position:fixed;inset:0;z-index:420;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;background:rgba(0,0,0,.55);opacity:0;pointer-events:none;transition:opacity .25s}
#logok.show{opacity:1}
.okc{width:104px;height:104px;border-radius:50%;background:#16a34a;color:#fff;display:grid;place-items:center;transform:scale(.3);box-shadow:0 0 0 0 rgba(34,197,94,.6)}
#logok.show .okc{animation:okpop .6s cubic-bezier(.2,1.4,.4,1) forwards}
.okc svg{width:58px;height:58px;stroke-width:3}.okc path{stroke-dasharray:30;stroke-dashoffset:30}
#logok.show .okc path{animation:drawc .45s .25s ease forwards}
#logok b{font-size:20px;color:#fff;opacity:0;transform:translateY(10px)}
#logok.show b{animation:okt .4s .3s forwards}
@keyframes okpop{to{transform:scale(1);box-shadow:0 0 0 24px rgba(34,197,94,0)}}
@keyframes drawc{to{stroke-dashoffset:0}}
@keyframes okt{to{opacity:1;transform:none}}
.sl{display:flex;align-items:center;gap:8px;min-width:0}.sl small{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.sl .vtag{flex:none}
.dev{display:flex;gap:14px;align-items:center;padding:14px;border-radius:24px;background:var(--s1);border:1px solid var(--line);margin:10px 0}
.dev.cur{border-color:var(--acc);box-shadow:0 0 24px rgba(var(--accrgb),.18)}
.dic{width:54px;height:54px;border-radius:18px;display:grid;place-items:center;background:rgba(var(--accrgb),.14);color:var(--acc);flex:none}
.dic .ic{width:28px;height:28px}
.dev .meta{gap:3px}.dev .meta b{display:flex;align-items:center;gap:8px;flex-wrap:wrap;white-space:normal}
.dev .meta small{white-space:normal}
.curb{padding:2px 9px;border-radius:999px;background:rgba(52,211,153,.16);color:#34d399;font-size:11px;font-weight:800}
.dl{display:flex;align-items:center;gap:6px}.dl .dot{width:8px;height:8px;margin:0}
.note{display:block;margin-top:4px;color:var(--acc)}
.has-bg .dev{background:rgba(14,18,30,.62)}
/* ===== v7: меню настроек и настройки мини-плеера ===== */
.subt{margin:16px 4px 6px;font-size:28px;font-weight:900;letter-spacing:-.5px}
.mgrp{background:linear-gradient(180deg,rgba(255,255,255,.075),rgba(255,255,255,.02)),var(--s1);border:1px solid var(--line);border-radius:30px;margin:6px 0 16px;overflow:hidden;box-shadow:0 10px 30px rgba(0,0,0,.25)}
.mi{position:relative;display:flex;align-items:center;gap:16px;padding:18px 20px 18px 18px;cursor:pointer;transition:background-color .15s;user-select:none;-webkit-user-select:none}
.mi+.mi::before{content:"";position:absolute;top:0;left:58px;right:18px;height:1px;background:var(--line);opacity:.8}
.mi:active{background:rgba(255,255,255,.06)}
.mi>.ic{color:var(--mut);width:24px;height:24px}
.mi b{flex:1;min-width:0;font-size:17px;font-weight:600;letter-spacing:-.1px}
.mi .val{color:var(--mut);font-size:15px;font-weight:600}
.mi .chev{display:flex}.mi .chev .ic{width:18px;height:18px;color:var(--mut);opacity:.8}
.mi.red b,.mi.red>.ic{color:var(--red)}
.has-bg .mgrp{background:rgba(14,18,30,.62);-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px)}
.lite .mgrp{-webkit-backdrop-filter:none;backdrop-filter:none}
.aboutc{padding:26px 18px}.aboutc svg{margin:0 auto;display:block;border-radius:16px}
.shr{display:flex;gap:2px}
body.no-eq .eq{display:none}
/* экран настройки плеера */
#pset{position:fixed;inset:0;z-index:80;background:var(--bg);display:none;overflow-y:auto;-webkit-overflow-scrolling:touch}
#pset.open{display:block}
.psin{max-width:720px;margin:0 auto;padding:calc(12px + env(safe-area-inset-top)) 14px calc(40px + env(safe-area-inset-bottom))}
.pshead{display:flex;align-items:center;gap:14px;padding:4px 0 8px}
.pshead b{font-size:20px;font-weight:900;letter-spacing:-.3px}
.mpstage{padding:26px 12px;border-radius:22px;margin:8px 0 12px;background:radial-gradient(120% 120% at 20% 0%,rgba(var(--accrgb),.35),transparent 60%),linear-gradient(135deg,rgba(255,255,255,.05),rgba(0,0,0,.35)),var(--bg);border:1px dashed var(--line)}
/* мини-плеер: общие правила для настоящего и для предпросмотра */
.mp{position:relative}
#mini.mp{background:transparent}
.mpprev{display:block;border:1px solid rgba(var(--accrgb),.55);border-radius:28px;overflow:hidden;box-shadow:0 0 26px rgba(var(--accrgb),.22);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px)}
.mpprev .mpg{height:3px;background:var(--acc);box-shadow:0 0 8px var(--acc)}
.mp .mbgl{position:absolute;inset:0;z-index:0;pointer-events:none;background:rgb(19,22,34);opacity:var(--mop,.94);transition:opacity .25s}
.mp .mrow,.mp .mpg{position:relative;z-index:1}
#mini[data-sz=s] .mrow,.mpprev[data-sz=s] .mrow{padding:5px 8px 5px 5px;gap:8px}
#mini[data-sz=s] .mrow .cv,.mpprev[data-sz=s] .mrow .cv{width:34px;height:34px;border-radius:10px}
#mini[data-sz=s] .meta b,.mpprev[data-sz=s] .meta b{font-size:13px}
#mini[data-sz=s] .meta small,.mpprev[data-sz=s] .meta small{font-size:11px}
#mini[data-sz=s] .pb,.mpprev[data-sz=s] .pb{width:34px;height:34px}
#mini[data-sz=s] .pb .ic,.mpprev[data-sz=s] .pb .ic{width:16px;height:16px}
#mini[data-sz=s] .ib,.mpprev[data-sz=s] .ib{width:30px;height:30px}
#mini[data-sz=s] .ib .ic,.mpprev[data-sz=s] .ib .ic{width:18px;height:18px}
#mini[data-sz=l] .mrow,.mpprev[data-sz=l] .mrow{padding:10px 12px 10px 10px;gap:14px}
#mini[data-sz=l] .mrow .cv,.mpprev[data-sz=l] .mrow .cv{width:66px;height:66px;border-radius:18px}
#mini[data-sz=l] .meta b,.mpprev[data-sz=l] .meta b{font-size:17px}
#mini[data-sz=l] .meta small,.mpprev[data-sz=l] .meta small{font-size:13px}
#mini[data-sz=l] .pb,.mpprev[data-sz=l] .pb{width:58px;height:58px}
#mini[data-sz=l] .pb .ic,.mpprev[data-sz=l] .pb .ic{width:26px;height:26px}
#mini[data-sz=l] .ib,.mpprev[data-sz=l] .ib{width:44px;height:44px}
#mini[data-sz=l] .ib .ic,.mpprev[data-sz=l] .ib .ic{width:26px;height:26px}
#mini[data-sh=soft],.mpprev[data-sh=soft]{border-radius:18px}
#mini[data-sh=sq],.mpprev[data-sh=sq]{border-radius:8px}
#mini[data-bg=solid] .mbgl,.mpprev[data-bg=solid] .mbgl{background:var(--s1)}
#mini[data-bg=solid],.mpprev[data-bg=solid]{-webkit-backdrop-filter:none;backdrop-filter:none}
#mini[data-bg=cover] .mbgl,.mpprev[data-bg=cover] .mbgl{inset:-24px;background-image:var(--mcov,none),linear-gradient(135deg,rgba(var(--accrgb),.55),rgba(var(--accrgb),.12));background-size:cover;background-position:center;filter:blur(22px) saturate(1.5) brightness(.55)}
#mini[data-bg=grad] .mbgl,.mpprev[data-bg=grad] .mbgl{background:linear-gradient(120deg,rgba(var(--accrgb),.6),rgba(var(--accrgb),.08)),var(--s1)}
#mini[data-bg=cover] .meta b,.mpprev[data-bg=cover] .meta b{text-shadow:0 1px 8px rgba(0,0,0,.6)}
#mini[data-bg=none] .mbgl,.mpprev[data-bg=none] .mbgl{display:none}
#mini[data-bg=none],.mpprev[data-bg=none]{border-color:transparent;box-shadow:none;-webkit-backdrop-filter:none;backdrop-filter:none}
#mini[data-bg=none] .meta b,.mpprev[data-bg=none] .meta b{text-shadow:0 1px 10px rgba(0,0,0,.9)}
#mini[data-bg=none] .meta small,.mpprev[data-bg=none] .meta small{text-shadow:0 1px 8px rgba(0,0,0,.9);color:#d4d9ea}
#mini.m-np .mpg,.mpprev.m-np .mpg{display:none}
#mini.m-nc .mrow .cv,.mpprev.m-nc .mrow .cv{display:none}
#mini.m-nk .mrow .ib.nx,.mpprev.m-nk .mrow .ib.nx{display:none}

/* ===== v8: лента, комментарии, меню сообщений, тосты ===== */
#toast{top:calc(10px + env(safe-area-inset-top));left:12px;right:12px;max-width:560px;margin:0 auto;transform:none;padding:0;border-radius:14px;border:1px solid var(--line);border-left:4px solid var(--acc);background:rgba(12,14,22,.97);box-shadow:0 12px 32px rgba(0,0,0,.5);overflow:hidden;font-size:15px;font-weight:600}
#toast.show{animation:tin .26s cubic-bezier(.2,.9,.3,1)}
@keyframes tin{from{opacity:0;transform:translateY(-16px)}}
#toast .tin{display:flex;align-items:center;gap:12px;padding:12px 16px 12px 12px}
#toast .tic{width:30px;height:30px;border-radius:9px;display:grid;place-items:center;flex:none;background:rgba(var(--accrgb),.18);color:var(--acc)}
#toast .tic .ic{width:18px;height:18px}
#toast .ttx{flex:1;min-width:0;line-height:1.3;word-break:break-word}
#toast .tbar{height:2px;background:var(--acc);transform-origin:left;animation:tbar 2.8s linear forwards}
#toast .tbar.ld{width:38%;animation:tld 1.1s ease-in-out infinite}
@keyframes tbar{from{transform:scaleX(1)}to{transform:scaleX(0)}}
@keyframes tld{0%{transform:translateX(-100%)}100%{transform:translateX(270%)}}
#toast.err{border-left-color:var(--red)}
#toast.err .tic{background:rgba(255,93,108,.16);color:var(--red)}
#toast.err .tbar{background:var(--red)}
.spin{width:16px;height:16px;border-radius:50%;border:2.5px solid rgba(var(--accrgb),.3);border-top-color:var(--acc);animation:spn .8s linear infinite;display:block}
@keyframes spn{to{transform:rotate(360deg)}}
/* посты ленты */
.fx{padding:14px 14px 12px}
.fx-head{display:flex;align-items:center;gap:11px;margin-bottom:10px}
.fx-head .av{width:42px;height:42px;cursor:pointer;flex:none}
.fx-head .meta{min-width:0;flex:1}
.fx-head .meta b{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.anonav{display:grid;place-items:center;background:rgba(var(--accrgb),.16)!important;color:var(--acc);cursor:default!important}
.anonav .ic{width:22px;height:22px}
.fx-tag{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:800;background:rgba(var(--accrgb),.16);color:var(--acc)}
.fx-tag .ic{width:12px;height:12px}
.fx .row{background:rgba(0,0,0,.22);border:1px solid var(--line);margin:0}
.fx-cap{margin:10px 2px 2px;font-size:15.5px;line-height:1.45;white-space:pre-wrap;word-break:break-word;color:#dfe5f7}
.fx-pre{margin-top:8px;font-size:14px;color:#c9d0e4}
.fx-pre div{margin:3px 2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fx-pre b{color:var(--txt);margin-right:6px}
.fx-foot{margin-top:10px}.fx-foot .btn{margin:0}
.fx-op{padding:1px 8px;border-radius:999px;font-size:10px;font-weight:900;text-transform:uppercase;letter-spacing:.5px;background:var(--acc);color:var(--on)}
.cmr{display:flex;gap:10px;align-items:flex-start;padding:10px 0}
.cmr+.cmr{border-top:1px solid var(--line)}
.cmr .av{width:38px;height:38px;cursor:pointer;flex:none}
.cmr .cmb{flex:1;min-width:0}
.cmr .cmh{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.cmr .cmh b{cursor:pointer}
.cmr .cmh small{color:var(--mut);font-weight:700}
.cmr .cmx{white-space:pre-wrap;word-break:break-word;line-height:1.4;margin-top:2px;color:#dfe5f7}
.npck{display:flex;color:var(--acc)}.npck .ic{width:22px;height:22px}
/* сообщения: реакции, правка, меню */
.msg{-webkit-touch-callout:none;-webkit-user-select:none;user-select:none}
.msg .rxs{display:flex;flex-wrap:wrap;gap:4px}.msg .rxs:not(:empty){margin-top:6px}
.rx{display:inline-flex;align-items:center;gap:4px;padding:2px 9px;border-radius:13px;background:rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.14);font-size:14px;font-weight:800;cursor:pointer}
.rx.me{border-color:var(--acc);background:rgba(var(--accrgb),.3)}
.msg .ed{opacity:.8;font-style:italic}
#cedbar{display:none;align-items:center;gap:12px;padding:8px 14px;border-top:1px solid var(--line);background:var(--s1)}
#cedbar.on{display:flex}
#cedbar .ctt{flex:1;min-width:0;border-left:3px solid var(--acc);padding-left:10px}
#cedbar .ctt b{display:block;color:var(--acc);font-size:13px}
#cedbar .ctt span{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--mut);font-size:14px}
#cedbar>.ic,#cedi .ic{width:22px;height:22px;color:var(--acc)}
#mctx{position:fixed;inset:0;z-index:120;display:none;background:rgba(0,0,0,.45);-webkit-backdrop-filter:blur(3px);backdrop-filter:blur(3px)}
#mctx.open{display:block}
#mxbox{position:absolute;width:min(290px,calc(100vw - 24px));display:flex;flex-direction:column;gap:8px;animation:mxin .18s ease-out}
@keyframes mxin{from{opacity:0;transform:scale(.92)}}
.mx-rx{display:flex;justify-content:space-between;padding:5px 6px;border-radius:28px;background:var(--s2);border:1px solid var(--line);box-shadow:0 12px 30px rgba(0,0,0,.5)}
.mx-rx button{border:0;background:transparent;font-size:24px;width:34px;height:40px;border-radius:50%;cursor:pointer;padding:0;transition:transform .12s}
.mx-rx button.on{background:rgba(var(--accrgb),.35)}.mx-rx button:active{transform:scale(1.35)}
.mx-menu{border-radius:20px;background:var(--s2);border:1px solid var(--line);overflow:hidden;box-shadow:0 12px 30px rgba(0,0,0,.5)}
.mx-it{display:flex;align-items:center;gap:14px;padding:14px 18px;font-size:16px;font-weight:600;cursor:pointer}
.mx-it+.mx-it{border-top:1px solid var(--line)}.mx-it:active{background:rgba(255,255,255,.07)}
.mx-it .ic{width:21px;height:21px;color:var(--mut)}
.mx-it.red,.mx-it.red .ic{color:var(--red)}
#toast.err .ttx{color:var(--txt)}
.ib.heartb{transition:color .2s,transform .28s cubic-bezier(.3,1.6,.4,1)}
.ib.heartb.liked{color:#ff4d6d;transform:scale(1.15)}
.ib.heartb.liked svg{fill:currentColor}
/* ===== v9: новый дизайн, плейлисты, соцсети, блокировка, мини-плеер ===== */
:root{--disp:"Exo 2",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wm,h2,.lab,.btn,.seg button,#tabs button,.pill,.pname,.subt,.stile b,.mbox h3,.fx-tag,.soc,.plt,.pltitle,.plkind{font-family:var(--disp)}
.lab{letter-spacing:2px}
body:not(.st-flat){background-image:linear-gradient(rgba(var(--accrgb),.05) 1px,transparent 1px),linear-gradient(90deg,rgba(var(--accrgb),.05) 1px,transparent 1px),radial-gradient(700px 420px at 50% -140px,rgba(var(--accrgb),.24),transparent 70%);background-size:38px 38px,38px 38px,auto;background-repeat:repeat,repeat,no-repeat;background-attachment:fixed}
body:not(.st-flat) .card{border-color:rgba(var(--accrgb),.26);background:linear-gradient(155deg,rgba(var(--accrgb),.09),rgba(255,255,255,.015) 45%),var(--s1);border-radius:30px;box-shadow:0 10px 34px rgba(0,0,0,.35),inset 0 1px 0 rgba(255,255,255,.04)}
body.st-glass:not(.st-flat) .card{background:rgba(255,255,255,.05)}
input:not([type=range]):not([type=checkbox]):not([type=color]):not([type=file]),select{border-radius:999px;padding:14px 20px;border-color:rgba(var(--accrgb),.32)}
textarea{border-radius:26px;padding:14px 20px;border-color:rgba(var(--accrgb),.32)}
input:focus,textarea:focus,select:focus{box-shadow:0 0 0 3px rgba(var(--accrgb),.16),0 0 26px rgba(var(--accrgb),.2)}
.btn{font-weight:900;letter-spacing:1.4px;box-shadow:0 10px 30px rgba(var(--accrgb),.38),inset 0 1px 0 rgba(255,255,255,.28),inset 0 -3px 0 rgba(0,0,0,.18)}
.btn.sec,.btn.red{box-shadow:none}
.st-flat .btn{box-shadow:none}
.seg{border-color:rgba(var(--accrgb),.3)}
.mbox{border-radius:34px;border-color:rgba(var(--accrgb),.38);background:linear-gradient(160deg,rgba(var(--accrgb),.13),transparent 45%),var(--s1);box-shadow:0 0 60px rgba(var(--accrgb),.18)}
.mbox h3,.mtitle{font-style:italic;font-weight:900;font-size:26px;letter-spacing:-.3px;margin:0 0 4px}
.mbox .btns{margin-top:14px}
.mgrp{border-color:rgba(var(--accrgb),.24)}
.pcard{border-color:rgba(var(--accrgb),.4);box-shadow:0 0 34px rgba(var(--accrgb),.14)}
.sqs{margin:2px 0 10px}
/* карточки плейлистов */
.plc{position:relative;display:flex;align-items:center;gap:16px;padding:14px 16px 14px 14px;margin:12px 0;border-radius:30px;border:1px solid rgba(var(--accrgb),.34);background:linear-gradient(155deg,rgba(var(--accrgb),.12),rgba(255,255,255,.015) 50%),var(--s1);cursor:pointer;box-shadow:0 8px 26px rgba(0,0,0,.3);transition:transform .15s}
.plc:active{transform:scale(.985)}
.plm{width:96px;height:96px;border-radius:22px;overflow:hidden;flex:none;background:var(--s2);display:grid;place-items:center}
.plm img{width:100%;height:100%;object-fit:cover;display:block}
.plm .mos{display:grid;grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr;width:100%;height:100%}
.plm .ni{display:grid;place-items:center;color:var(--acc);width:100%;height:100%}.plm .ni .ic{width:40%;height:40%}
.plm.big{width:min(62vw,230px);height:min(62vw,230px);border-radius:34px;margin:0 auto;box-shadow:0 18px 50px rgba(0,0,0,.55),0 0 0 1px rgba(255,255,255,.07)}
.plb{flex:1;min-width:0}
.plt{display:block;font-size:19px;font-weight:900;line-height:1.15;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.plb small{display:block;color:var(--mut);font-weight:700;margin:3px 0 9px;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pls{display:flex;align-items:center;gap:16px;font-weight:800;font-size:15px;color:var(--mut);flex-wrap:wrap}
.pls span{display:inline-flex;align-items:center;gap:6px}
.pls .ic{width:18px;height:18px}
.pls .st,.pls .st b{color:#f5b82e}.pls .st b{font-size:16px}.pls .st i{font-style:normal;color:var(--mut);font-weight:700}
.pls .st.off{color:var(--mut)}.pls .st .ic path,.rs .ic path{fill:currentColor}
.plc .chev{color:var(--mut);display:flex}.plc .chev .ic{width:20px;height:20px}
.plhero{text-align:center;padding:26px 18px 20px;overflow:hidden;position:relative}
.plhero::before{content:"";position:absolute;inset:0;background:radial-gradient(420px 260px at 50% 0%,rgba(var(--accrgb),.3),transparent 70%);pointer-events:none}
.plhero>*{position:relative}
.plkind{margin-top:20px;font-weight:800;letter-spacing:3px;text-transform:uppercase;font-size:15px;color:var(--mut)}
.pltitle{font-size:30px;font-weight:900;line-height:1.1;margin:6px 0 12px;white-space:normal;word-break:break-word}
.plown{display:inline-flex;align-items:center;gap:10px;padding:7px 18px 7px 8px;border-radius:999px;background:rgba(255,255,255,.07);border:1px solid var(--line);cursor:pointer;font-weight:800}
.plown .av{width:34px;height:34px;padding:0}
.pls.big{justify-content:center;margin:16px 0 4px;font-size:17px}
.pldesc{white-space:pre-wrap;color:#c9d0e4;margin:12px 4px 0;font-size:14px}
.plbtns{display:flex;gap:12px;margin:16px 0 8px}.plbtns .btn{margin:0;padding:18px;font-size:17px;flex:1}.plbtns .rnd{flex:none;width:70px;padding:0}
.rstars{display:flex;justify-content:center;gap:6px;margin:10px 0 4px}
.rs{border:0;background:transparent;color:#4b5270;padding:4px;cursor:pointer;transition:transform .15s}.rs:active{transform:scale(1.25)}
.rs .ic{width:38px;height:38px}.rs.on{color:#f5b82e}
.rbig{text-align:center;font-size:28px;font-weight:900;color:#f5b82e;margin-top:8px}.rbig small{font-size:15px;color:var(--mut)}
/* соцсети */
.socs{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:14px;padding-top:14px;border-top:1px solid var(--line)}
.soc{display:inline-flex;align-items:center;gap:8px;padding:9px 14px 9px 12px;border-radius:999px;border:1px solid rgba(var(--accrgb),.42);background:rgba(var(--accrgb),.1);color:var(--txt);font-weight:800;font-size:14px;text-decoration:none}
.soc .ic{width:20px;height:20px;color:var(--acc)}.soc .ic:last-child{width:14px;height:14px;opacity:.6;color:var(--txt)}
.socs-empty{justify-content:space-between}.socs-empty small{flex:1;min-width:150px}
/* меню чата и блокировка */
#cmenu{position:absolute;inset:0;z-index:6;display:none}#cmenu.open{display:block}
#cmenu .cmbg{position:absolute;inset:0;background:rgba(0,0,0,.35)}
#cmenu .cmbox{position:absolute;top:calc(64px + env(safe-area-inset-top));right:12px;width:min(260px,calc(100vw - 24px));border-radius:22px;background:var(--s2);border:1px solid rgba(var(--accrgb),.3);box-shadow:0 14px 40px rgba(0,0,0,.55);overflow:hidden;animation:mxin .16s ease-out;transform-origin:top right}
#cunb{display:none;padding:12px 14px calc(12px + env(safe-area-inset-bottom));border-top:1px solid var(--line);background:var(--s1)}#cunb .btn{margin:0}
/* редактирование трека */
.ettools{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:14px 0 2px}
.et{display:flex;align-items:center;gap:8px;padding:11px 14px;border-radius:999px;border:1px solid var(--line);background:rgba(255,255,255,.04);color:var(--txt);font:inherit;font-weight:700;font-size:13px;cursor:pointer}
.et .ic{width:18px;height:18px;color:var(--acc);flex:none}
.et.red{color:var(--red);border-color:rgba(255,93,108,.5)}.et.red .ic{color:var(--red)}
/* мини-плеер: читаемые шрифты */
.mp .meta{gap:1px}
.mp .meta b{font-size:16px;font-weight:700;letter-spacing:0;text-transform:none;font-style:normal;line-height:1.2}
.mp .meta small{font-size:13.5px;font-weight:500;color:var(--mut)}
.mp .meta{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
#mini[data-ft=sys] .meta,.mpprev[data-ft=sys] .meta{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
#mini[data-ft=round] .meta,.mpprev[data-ft=round] .meta{font-family:ui-rounded,"SF Pro Rounded",Nunito,"Varela Round",system-ui,sans-serif}
#mini[data-ft=site] .meta,.mpprev[data-ft=site] .meta{font-family:var(--disp)}
#mini[data-ft=mono] .meta,.mpprev[data-ft=mono] .meta{font-family:var(--mono)}
#mini[data-bt=plain] .pb,.mpprev[data-bt=plain] .pb{background:transparent;box-shadow:none;color:var(--txt)}
#mini[data-bt=plain] .ib,.mpprev[data-bt=plain] .ib{color:var(--txt)}
#mini[data-bt=plain][data-sz=m] .pb,.mpprev[data-bt=plain][data-sz=m] .pb{width:46px;height:46px}
#mini[data-bt=plain][data-sz=m] .pb .ic,.mpprev[data-bt=plain][data-sz=m] .pb .ic{width:32px;height:32px}
#mini[data-bt=plain][data-sz=m] .ib .ic,.mpprev[data-bt=plain][data-sz=m] .ib .ic{width:28px;height:28px}
#mini[data-bt=plain][data-sz=s] .pb,.mpprev[data-bt=plain][data-sz=s] .pb{width:36px;height:36px}
#mini[data-bt=plain][data-sz=s] .pb .ic,.mpprev[data-bt=plain][data-sz=s] .pb .ic{width:24px;height:24px}
#mini[data-bt=plain][data-sz=s] .ib .ic,.mpprev[data-bt=plain][data-sz=s] .ib .ic{width:22px;height:22px}
#mini[data-bt=plain][data-sz=l] .pb,.mpprev[data-bt=plain][data-sz=l] .pb{width:60px;height:60px}
#mini[data-bt=plain][data-sz=l] .pb .ic,.mpprev[data-bt=plain][data-sz=l] .pb .ic{width:40px;height:40px}
#mini[data-bt=plain][data-sz=l] .ib .ic,.mpprev[data-bt=plain][data-sz=l] .ib .ic{width:34px;height:34px}
#mini[data-bp=bottom] .mpg,.mpprev[data-bp=bottom] .mpg{position:absolute;left:0;bottom:0;z-index:2}
#mini.m-npv .mrow .ib.pv,.mpprev.m-npv .mrow .ib.pv{display:none}
</style>
</head>
<body>
<div id="splash">
  <div class="sp-logo"><svg viewBox="0 0 64 64"><rect width="64" height="64" rx="16" fill="var(--acc)"/><g fill="var(--on)" shape-rendering="crispEdges"><rect class="c" style="animation-delay:0s" x="17" y="11" width="6" height="42"/><rect class="c" style="animation-delay:.2s" x="23" y="11" width="18" height="6"/><rect class="c" style="animation-delay:.4s" x="41" y="17" width="6" height="12"/><rect class="c" style="animation-delay:.6s" x="23" y="29" width="18" height="6"/></g></svg></div>
  <div class="sp-t">PiXeL <b>Music</b></div>
  <div class="sp-s">ЗАГРУЖАЕТСЯ</div>
  <div class="sp-bar"><i></i></div>
</div>
<div id="modal"><div class="mbox"></div></div>
<div id="bgm" style="display:none"></div>
<div class="app">
  <header class="top" id="top"></header>
  <div id="view"></div>
  <div class="foot">AI STUDIO PIXEL</div>
</div>

<div id="mini" class="mp">
  <div class="mbgl"></div>
  <div id="mprog" class="mpg"></div>
  <div class="mrow" data-act="opensheet">
    <div class="cv" id="mcov"></div>
    <div class="meta"><b id="mtitle"></b><small id="mart"></small></div>
    <button class="ib pv" data-act="prev"></button>
    <button class="pb" id="mpp" data-act="toggle"></button>
    <button class="ib nx" data-act="next"></button>
  </div>
</div>

<nav id="tabs"></nav>

<div id="sheet">
  <div id="sbg"></div>
  <div class="sin">
    <div class="shead">
      <button class="ib" data-act="closesheet" id="sdown"></button>
      <span class="lab">Сейчас играет</span>
      <span class="shr"><button class="ib" data-act="psetopen" id="spsb" aria-label="Настройка плеера"></button><button class="ib" data-act="queue" id="sqb"></button></span>
    </div>
    <div id="smain">
      <div class="bigcov" id="bigcov"></div>
      <div class="sti"><b id="stitle"></b><span id="sart"></span></div>
      <div class="eq" id="eq"></div>
      <input type="range" id="seek" min="0" max="1000" value="0">
      <div class="times"><span id="tcur">0:00</span><span id="tdur">0:00</span></div>
      <div class="ctl">
        <button class="cb sm" id="bshuf" data-act="shuffle"></button>
        <button class="cb" data-act="prev" id="bprev"></button>
        <button class="cb big" id="spp" data-act="toggle"></button>
        <button class="cb" data-act="next" id="bnext"></button>
        <button class="cb sm" id="brep" data-act="repeat"></button>
      </div>
      <div class="srow"><span class="lab">Громк.</span><input type="range" id="vol2" min="0" max="100" value="80"></div>
      <div class="srow wrap"><button class="chip" id="bfav" data-act="favtoggle"></button><button class="chip" id="boff" data-act="offtoggle">Скачать офлайн</button><button class="chip" data-act="addtopl">+ В плейлист</button></div>
      <div class="srow"><span class="lab" id="slab">Таймер сна</span>
        <div class="chips" style="margin:0"><button class="chip" data-act="sleep" data-v="15">15</button><button class="chip" data-act="sleep" data-v="30">30</button><button class="chip" data-act="sleep" data-v="60">60</button><button class="chip" data-act="sleep" data-v="0">выкл</button></div></div>
    </div>
    <div class="sq" id="sq" style="display:none"></div>
  </div>
</div>

<div id="pset"><div class="psin"><div class="pshead"><button class="rbtn" id="psb" data-act="psetclose" aria-label="Назад"></button><b>Настройка плеера</b></div><div id="psbody"></div></div></div>

<input type="file" id="fAudio" accept="audio/*,video/mp4,.mp3,.mp4,.m4a,.wav,.ogg,.aac,.flac" multiple hidden>
<input type="file" id="fTrCover" accept="image/*" hidden>
<input type="file" id="fAva" accept="image/*" hidden>
<input type="file" id="fBan" accept="image/*" hidden>
<div id="ytbox"><div id="ytp"></div></div>
<div id="chat"><div class="chead"><button class="rbtn" id="cback" data-act="chatback"></button><div class="av" id="cav"></div><div class="cmeta" data-act="chatprofile"><b id="cname"></b><small id="cst"></small></div><button class="rbtn" id="cmore" data-act="chatmenu"></button></div><div id="cmsgs"></div><div id="cedbar"><span id="cedi"></span><div class="ctt"><b>Редактирование</b><span id="cedtxt"></span></div><button class="ib" id="cedx" data-act="cedcancel" aria-label="Отмена"></button></div><div class="cin" id="cbar"><textarea id="cinp" rows="1" maxlength="1000" placeholder="Сообщение"></textarea><button class="pb" id="csendb" data-act="csend"></button></div><div id="cunb"><button class="btn" data-act="chatunblock">Разблокировать</button></div><div id="cnote"></div><div id="cmenu"><div class="cmbg" data-act="cmenuclose"></div><div class="cmbox"><div class="mx-it" id="cmprof" data-act="chatprofile"></div><div class="mx-it red" id="cmblock" data-act="chatblock"></div></div></div></div>
<div id="nbanner"><div class="av" id="nbav"></div><div class="nbt"><div class="nbl"><span id="nbi"></span>Сообщения<em>сейчас</em></div><b id="nbn"></b><span id="nbm"></span></div><button class="ib" id="nbx" aria-label="Закрыть"></button></div>
<div id="impbar"><span id="impt"></span><button class="btn sm" data-act="impback">Вернуться</button></div>
<div id="logok"><div class="okc" id="logokc"></div><b>Отчёт отправлен</b></div>
<div id="logbar"><span>Произошла ошибка</span><button class="btn" data-act="logopen">Показать лог</button><button class="ib" data-act="logbarx">×</button></div>
<div id="logwin"><div class="lhead"><b>Журнал ошибок</b><button class="rbtn" id="logx" data-act="logclose"></button></div><div id="logbody"></div><div class="lfoot"><textarea id="lognote" placeholder="Что ты делал, когда это случилось? (по желанию)"></textarea><div class="btns"><button class="btn sec" data-act="logcopy">Скопировать</button><button class="btn" id="logsendb" data-act="logsend">Отправить разработчику</button></div><button class="btn red" data-act="logclear">Очистить журнал</button></div></div>
<input type="file" id="fPl" accept="image/*" hidden>
<input type="file" id="fBg" accept="image/*,video/*" hidden>
<div id="mctx"><div id="mxbox"><div class="mx-rx" id="mxrx"></div><div class="mx-menu" id="mxmenu"></div></div></div>
<div id="toast"></div>

<script>
"use strict";
/* ---------- журнал ошибок: показывает, что сломалось, прямо в приложении ---------- */
var LOG=[];try{LOG=JSON.parse(localStorage.getItem("px_log")||"[]")}catch(e){LOG=[]}
var logT=0,QUIET={net:1,import:1,resolve:1};
function logErr(kind,msg,stack){
  try{
    msg=String(msg==null?"":msg).slice(0,400);
    if(/ResizeObserver|^Script error\.?$/.test(msg))return;
    LOG.push({t:Date.now(),kind:kind,msg:msg,stack:String(stack||"").slice(0,1500),where:(typeof S!=="undefined"&&S)?String((S.page?S.page.t:S.tab)||""):""});
    if(LOG.length>40)LOG.shift();
    try{localStorage.setItem("px_log",JSON.stringify(LOG))}catch(e){}
    var now=Date.now();if(!QUIET[kind]&&now-logT>7000){logT=now;var b=document.getElementById("logbar");if(b){b.classList.add("show");clearTimeout(logErr.t);logErr.t=setTimeout(function(){b.classList.remove("show")},9000)}}
  }catch(e){}
}
window.addEventListener("error",function(ev){if(ev.target&&ev.target!==window)return;logErr("js",ev.message,(ev.error&&ev.error.stack)||(ev.filename+":"+ev.lineno+":"+ev.colno))});
window.addEventListener("unhandledrejection",function(ev){var r=ev.reason;logErr("promise",r&&r.message?r.message:r,r&&r.stack)});

var EDIT="https://mr6597266-rgb.github.io/PiXeLAIStudio/";
var $=function(s){return document.querySelector(s)};
var esc=function(s){return String(s==null?"":s).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]})};
var enc=encodeURIComponent;

/* ---------- иконки ---------- */
var ICONS={
 music:'<path d="M9 18V6l11-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',
 search:'<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
 user:'<circle cx="12" cy="8" r="4"/><path d="M4 20c1.5-4 4.5-6 8-6s6.5 2 8 6"/>',
 play:'<path d="M7 4.5v15l13-7.5z" fill="currentColor"/>',
 pause:'<rect x="6" y="4.5" width="4" height="15" rx="1" fill="currentColor"/><rect x="14" y="4.5" width="4" height="15" rx="1" fill="currentColor"/>',
 next:'<path d="M5 5v14l10-7z" fill="currentColor"/><path d="M19 5v14"/>',
 prev:'<path d="M19 5v14L9 12z" fill="currentColor"/><path d="M5 5v14"/>',
 shuffle:'<polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/>',
 repeat:'<polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>',
 repeat1:'<polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/><path d="M11 10l1.6-1v6"/>',
 trash:'<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
 edit:'<path d="M4 20h4L19 9l-4-4L4 16z"/>',
 down:'<path d="M6 9l6 6 6-6"/>',
 queue:'<path d="M4 6h16M4 12h16M4 18h9"/>',
 back:'<path d="M15 5l-7 7 7 7"/>',
 link:'<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
 bookmark:'<path d="M6 4h12v17l-6-4-6 4z"/>',
 send:'<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
 out:'<path d="M9 4H5v16h4M16 8l4 4-4 4M20 12H9"/>',
 globe:'<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/>',
 img:'<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="M4 18l5-5 4 4 3-3 4 4"/>',
 upload:'<path d="M12 16V4M7 9l5-5 5 5M4 20h16"/>',
 download:'<path d="M12 4v12M7 11l5 5 5-5M4 20h16"/>',
 feed:'<path d="M5 5a14 14 0 0 1 14 14M5 11a8 8 0 0 1 8 8"/><circle cx="6" cy="18" r="1.4"/>',
 gear:'<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/>'
};
Object.assign(ICONS,{
 chat:'<path d="M4 5h16v11H9l-5 4z"/>',
 chatplus:'<path d="M4 5h16v11H9l-5 4z"/><path d="M12 8v5M9.5 10.5h5"/>',
 check:'<path d="M5 12.5l4.5 4.5L19 7"/>',
 checks:'<path d="M2 12.5l4.5 4.5L15 8M10 16l1.5 1.5L21 7"/>',
 dots:'<circle cx="5" cy="12" r="1.6" fill="currentColor"/><circle cx="12" cy="12" r="1.6" fill="currentColor"/><circle cx="19" cy="12" r="1.6" fill="currentColor"/>',
 shield:'<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
 lock:'<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
 x:'<path d="M6 6l12 12M18 6L6 18"/>',
 eye:'<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
 eyeoff:'<path d="M3 3l18 18M10.6 6.2A9.6 9.6 0 0 1 12 6c6 0 10 6 10 6a17 17 0 0 1-3.2 3.8M6.1 7.6A16 16 0 0 0 2 12s4 7 10 7c1.5 0 2.9-.4 4.1-1M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
 cloud:'<path d="M7 18a4 4 0 0 1-.5-8A6 6 0 0 1 18 9a4.5 4.5 0 0 1-.5 9z"/>',
 heart:'<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/>',
 video:'<rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 10l5-3v10l-5-3z"/>',
 clip:'<rect x="6" y="5" width="12" height="16" rx="2"/><path d="M9 5V4h6v1M9 11h6M9 15h4"/>',
 bug:'<path d="M9 9a3 3 0 0 1 6 0v1H9zM7 11h10v4a5 5 0 0 1-10 0zM3 12h4M17 12h4M4 18l3-2M20 18l-3-2M4 6l3 2M20 6l-3 2"/>',
 addlist:'<path d="M4 6h11M4 12h8M4 18h8M18 12v8M14 16h8"/>',
 import:'<path d="M4 6h12M4 11h8M4 16h6M17 11v8M13 15l4 4 4-4"/>',
 chart:'<rect x="4" y="12" width="4" height="8" rx="1"/><rect x="10" y="4" width="4" height="16" rx="1"/><rect x="16" y="9" width="4" height="11" rx="1"/>',
 bell:'<path d="M6 16v-5a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 21a2 2 0 0 0 4 0"/>',
 vol:'<path d="M4 9.5v5h3.5l4.5 4v-13l-4.5 4z"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a8 8 0 0 1 0 11"/>',
 db:'<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/>',
 info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
 palette:'<path d="M12 3a9 9 0 1 0 0 18c1.5 0 2-1 1.5-2-.6-1.2.2-2.5 1.6-2.5H17a4 4 0 0 0 4-4c0-5-4-9.5-9-9.5z"/><circle cx="8" cy="11" r="1"/><circle cx="12" cy="7.5" r="1"/><circle cx="16" cy="11" r="1"/>',
 chev:'<path d="M9 5l7 7-7 7"/>',
 mpl:'<rect x="3" y="12" width="18" height="8" rx="4"/><path d="M7.5 16h5M17 14.4v3.2l2-1.6z"/>',
 copy:'<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
 alert:'<circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16.5v.5"/>',
 star:'<path d="M12 3.2l2.7 5.6 6.1.8-4.5 4.3 1.1 6.1L12 17l-5.4 3 1.1-6.1L3.2 9.6l6.1-.8z"/>',
 ext:'<path d="M7 17L17 7M9 7h8v8"/>',
 tiktok:'<path d="M14 4v10.5a3.5 3.5 0 1 1-3.5-3.5"/><path d="M14 4c.4 2.4 2 4 4.5 4.2"/>',
 youtube:'<rect x="3" y="6" width="18" height="12" rx="4"/><path d="M10.5 9.5v5l4.2-2.5z"/>',
 telegram:'<path d="M21 4L3 11l6 2.2L11.5 20l3-4 4.5 3.3z"/><path d="M9 13.2l9.5-7"/>',
 instagram:'<rect x="4" y="4" width="16" height="16" rx="5"/><circle cx="12" cy="12" r="3.6"/><circle cx="17" cy="7" r=".6"/>',
 vk:'<path d="M3 8h3c.8 4 2.5 6 4.5 6.5V8h3v3.5c1.7-.4 3-2.2 3.6-3.5H20c-.5 2-2 3.6-3.2 4.3C18.2 13 19.5 14.2 20.5 16h-3.2c-.7-1.2-1.8-2.1-3.3-2.4V16h-.8C8 16 4 13 3 8z"/>'
});
function I(n){return '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'+ICONS[n]+'</svg>'}
var GH='<svg viewBox="0 0 24 24"><path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.58.1.79-.25.79-.56v-2c-3.2.7-3.87-1.37-3.87-1.37-.52-1.33-1.28-1.69-1.28-1.69-1.05-.72.08-.7.08-.7 1.15.08 1.76 1.19 1.76 1.19 1.03 1.76 2.69 1.25 3.35.96.1-.75.4-1.25.73-1.54-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.28 1.19-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.78 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.83 1.19 3.09 0 4.42-2.69 5.39-5.25 5.68.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5Z"/></svg>';
function logoOld(w){return '<svg width="'+w+'" height="'+w+'" viewBox="0 0 11 11" shape-rendering="crispEdges"><g fill="var(--acc)" fill-opacity=".28"><rect width="3" height="3"/><rect x="8" width="3" height="3"/><rect y="8" width="3" height="3"/><rect x="8" y="8" width="3" height="3"/></g><g fill="var(--acc)"><rect x="4" width="3" height="3"/><rect y="4" width="3" height="3"/><rect x="8" y="4" width="3" height="3"/><rect x="4" y="8" width="3" height="3"/></g><rect x="4" y="4" width="3" height="3" fill="#fff"/></svg>'}

function logo(w){return '<svg width="'+w+'" height="'+w+'" viewBox="0 0 64 64"><rect width="64" height="64" rx="16" fill="var(--acc)"/><g fill="var(--on)" shape-rendering="crispEdges"><rect x="17" y="11" width="6" height="42"/><rect x="23" y="11" width="18" height="6"/><rect x="23" y="29" width="18" height="6"/><rect x="41" y="17" width="6" height="12"/></g></svg>'}
/* ---------- обложки: если обложки нет, ничего не рисуем, только тихая иконка ---------- */
function cov(url){return url?'<img src="'+esc(url)+'" alt="" loading="lazy">':'<span class="ni">'+I("music")+"</span>"}
function cimg(url){return cov(url)}
document.addEventListener("error",function(e){var t=e.target;if(t&&t.tagName==="IMG"){var p=t.parentNode;if(p&&p.classList&&(p.classList.contains("cv")||p.classList.contains("bigcov")))p.innerHTML='<span class="ni">'+I("music")+"</span>"}},true);

/* ---------- состояние и настройки ---------- */
var S={me:null,tab:"feed",sub:"tracks",page:null,edit:false,d:null,pacc:""};
var T={};
var DMP={mpsize:"m",mpbg:"glass",mpshape:"pill",mpop:94,mpprog:true,mpcov:true,mpskip:true,sbgm:"cover",seq:true,notif:true,xfade:true,xfadet:4,mpfont:"sys",mpbt:"plain",mpbp:"bottom",mpprev:false};
var SET=Object.assign({acc:"#3d7bff",style:"game",perf:"auto",auto:true,vol:80,bgdim:55,bgblur:false},DMP);
try{Object.assign(SET,JSON.parse(localStorage.getItem("px_set")||"{}"))}catch(e){}
(function(){var m={blue:"#3d7bff",night:"#e8e8f0",violet:"#8b5cf6",mint:"#22d3a0"};if(SET.theme){if(m[SET.theme])SET.acc=m[SET.theme];delete SET.theme}})();
var STAT=["Слушаю музыку","Кодю","Играю","Отдыхаю","Занят","Не беспокоить","Ем"];

/* ---------- цвета и темы: всё строится от одного акцентного цвета ---------- */
var PRESETS=[["#3d7bff","Синий"],["#ff3b4e","Красный"],["#f5b81c","Золото"],["#ff7a1a","Оранжевый"],["#ff4fa3","Розовый"],["#8b5cf6","Фиолетовый"],["#19c8e6","Циан"],["#22d3a0","Мята"],["#84cc16","Лайм"],["#e8e8f0","Моно"]];
function okHex(h,d){return /^#[0-9a-fA-F]{6}$/.test(h||"")?h:(d===undefined?"#3d7bff":d)}
function hexRgb(h){h=h.replace("#","");return [parseInt(h.substr(0,2),16),parseInt(h.substr(2,2),16),parseInt(h.substr(4,2),16)]}
function mixc(a,b,t){return [0,1,2].map(function(i){return Math.round(a[i]*(1-t)+b[i]*t)})}
function rgbs(c){return "rgb("+c.join(",")+")"}
function themeVars(hex){
  var a=hexRgb(hex),k=[0,0,0],lum=(0.299*a[0]+0.587*a[1]+0.114*a[2])/255;
  return {"--acc":hex,"--acc2":rgbs(mixc(a,k,.32)),"--accrgb":a.join(","),"--bg":rgbs(mixc(k,a,.055)),"--s1":rgbs(mixc(k,a,.10)),"--s2":rgbs(mixc(k,a,.16)),"--line":rgbs(mixc(k,a,.25)),"--on":lum>.6?"#1a1204":"#fff"};
}
function varStr(v){return Object.keys(v).map(function(k){return k+":"+v[k]}).join(";")}
function swatches(act,cur,withNone,colId){
  var h='<div class="sws" data-grp="'+act+'">';
  if(withNone)h+='<button class="sw none'+(!cur?" on":"")+'" data-act="'+act+'" data-v="" title="Как в приложении"></button>';
  PRESETS.forEach(function(p){h+='<button class="sw'+(cur===p[0]?" on":"")+'" style="background:'+p[0]+'" data-act="'+act+'" data-v="'+p[0]+'" title="'+p[1]+'"></button>'});
  return h+'<input type="color" id="'+colId+'" value="'+okHex(cur,"#3d7bff")+'" title="Свой цвет"></div>';
}

/* ---------- установка как приложение ---------- */
var DEF=null;
window.addEventListener("beforeinstallprompt",function(e){e.preventDefault();DEF=e});
window.addEventListener("appinstalled",function(){DEF=null;toast("Приложение установлено")});
function isApp(){return (window.matchMedia&&matchMedia("(display-mode: standalone)").matches)||window.navigator.standalone===true}
function showModal(h){$("#modal .mbox").innerHTML=h;$("#modal").classList.add("open")}
function copyText(t){
  if(navigator.clipboard&&window.isSecureContext)return navigator.clipboard.writeText(t);
  return new Promise(function(res){var ta=document.createElement("textarea");ta.value=t;ta.style.cssText="position:fixed;opacity:0;top:0";document.body.appendChild(ta);ta.select();try{document.execCommand("copy")}catch(e){}ta.remove();res()});
}
function envInfo(){
  var ua=navigator.userAgent||"",ios=/iPad|iPhone|iPod/.test(ua)||(navigator.platform==="MacIntel"&&navigator.maxTouchPoints>1);
  var android=/Android/i.test(ua),inapp=/FBAN|FBAV|Instagram|Telegram|VKontakte|VK\/|Line\/|; wv\)/i.test(ua);
  var br=/YaBrowser/i.test(ua)?"yandex":/SamsungBrowser/i.test(ua)?"samsung":/Firefox|FxiOS/i.test(ua)?"firefox":/EdgA|EdgiOS|Edg\//i.test(ua)?"edge":/CriOS|OPiOS/.test(ua)?"other-ios":/Chrome/i.test(ua)?"chrome":/Safari/i.test(ua)?"safari":"other";
  if(ios&&br==="yandex")br="other-ios";
  if(ios&&(br==="chrome"||br==="edge"||br==="firefox"))br="other-ios";
  return {ios:ios,android:android,inapp:inapp,br:br};
}
function installSteps(){
  var e=envInfo(),h="",note="";
  if(e.inapp)h='<ol><li>Ты открыл сайт внутри другого приложения (Telegram, Instagram и т. п.). Отсюда добавить на экран нельзя.</li><li>Нажми <b>⋮</b> или <b>«Поделиться»</b> и выбери <b>«Открыть в браузере»</b>.</li><li>В браузере нажми «Добавить на главный экран» ещё раз.</li></ol>';
  else if(e.ios){
    if(e.br==="safari")h='<ol><li>Нажми кнопку <b>«Поделиться»</b> (квадрат со стрелкой вверх) внизу экрана.</li><li>Прокрути список вниз и выбери <b>«На экран „Домой“»</b>.</li><li>Нажми <b>«Добавить»</b>. Иконка PiXeL Music появится на экране.</li></ol>';
    else h='<ol><li>На iPhone и iPad сайт можно добавить на экран только из <b>Safari</b>.</li><li>Скопируй ссылку кнопкой ниже и открой её в Safari.</li><li>Там нажми «Поделиться» → <b>«На экран „Домой“»</b>.</li></ol>';
  }
  else if(e.android){
    if(e.br==="firefox")h='<ol><li>Открой меню <b>⋮</b>.</li><li>Выбери <b>«Установить»</b> или <b>«Добавить на главный экран»</b>.</li></ol>';
    else if(e.br==="samsung")h='<ol><li>Нажми значок меню <b>≡</b> внизу справа.</li><li>Выбери <b>«Добавить страницу на»</b> → <b>«Главный экран»</b>.</li></ol>';
    else h='<ol><li>Открой меню браузера <b>⋮</b>.</li><li>Выбери <b>«Установить приложение»</b> или <b>«Добавить на главный экран»</b>.</li><li>Подтверди. Иконка появится на экране.</li></ol>';
  }
  else h='<ol><li>В Chrome или Edge нажми значок установки справа в адресной строке (или меню <b>⋮</b> → «Установить PiXeL Music»).</li><li>В Safari на Mac: «Файл» → «Добавить в Dock».</li></ol>';
  if(!window.isSecureContext)note='<p class="hint">Адрес сайта без https, поэтому браузер добавит его как <b>ярлык-вкладку</b>: сайт откроется с иконки на экране. Полноценное приложение без адресной строки появится, когда сайт откроют по https-ссылке (например, через ngrok).</p>';
  return h+note;
}
async function installApp(){
  if(isApp()){toast("Ты уже в приложении");return}
  if(DEF){DEF.prompt();try{await DEF.userChoice}catch(e){}DEF=null;return}
  showModal('<h3>Добавить на главный экран</h3>'+installSteps()+'<button class="btn" data-act="copysite">'+I("link")+' Скопировать ссылку</button><button class="btn sec" data-act="closemodal">Понятно</button>');
}
/* ---------- плавный переход между треками ---------- */
function hasNext(){return Q.length>0&&((SHUF&&Q.length>1)||qi+1<Q.length||REP===1)}
function applyVol(){A.volume=Math.max(0,Math.min(1,SET.vol/100*FADE))}
function fadeStep(){
  var f=1;
  if(SET.xfade!==false){
    if(!A.paused){
      var d=A.duration,c=A.currentTime||0,fs=Math.max(2,Math.min(10,SET.xfadet||4));
      if(!isFinite(d)){if(FADEIN)f=0}
      else if(d>fs*2+1){
        var sm=function(x){x=Math.max(0,Math.min(1,x));return x*x*(3-2*x)};
        if(FADEIN){if(c<fs)f=Math.min(f,sm(c/fs));else FADEIN=0}
        var left=d-c;
        if(left<fs&&SET.auto&&REP!==2&&hasNext())f=Math.min(f,sm(left/fs));
      }else FADEIN=0;
    }else if(FADEIN)f=0;
  }else FADEIN=0;
  if(Math.abs(f-FADE)>.003){FADE=f;applyVol()}
}
if("serviceWorker" in navigator&&window.isSecureContext)navigator.serviceWorker.register("/sw.js").catch(function(){});

/* ---------- экран загрузки ---------- */
var t0=Date.now();
function splashDone(){
  var w=Math.max(0,1300-(Date.now()-t0));
  setTimeout(function(){var s=$("#splash");if(!s)return;s.classList.add("out");setTimeout(function(){if(s.parentNode)s.parentNode.removeChild(s)},650)},w);
}
setTimeout(splashDone,9000);
var TOASTI={ok:"check",err:"alert",load:"download",info:"info"};
function toast(m,o){
  o=o||{};m=String(m==null?"":m);
  var ty=o.type||(/не удалось|ошибка|нельзя|слишком|не найден|нет соединения|недоступн|лимит/i.test(m)?"err":/^(выбери|напиши|введи|вставь)/i.test(m)?"info":"ok");
  var t=$("#toast");clearTimeout(toast.t);
  t.className="";t.style.display="block";
  t.innerHTML='<div class="tin"><span class="tic">'+(ty==="load"?'<i class="spin"></i>':I(TOASTI[ty]||"check"))+'</span><span class="ttx">'+esc(m)+'</span></div><div class="tbar'+(o.sticky?" ld":"")+'"></div>';
  void t.offsetWidth;t.className="show"+(ty==="err"?" err":"");
  toast.t=setTimeout(function(){t.style.display="none";t.className=""},o.sticky?30000:(o.ms||2800));
}

/* ---------- API ---------- */
var DEV=(function(){try{var d=localStorage.getItem("px_dev");if(!d){d=Array.prototype.map.call(crypto.getRandomValues(new Uint8Array(16)),function(b){return ("0"+b.toString(16)).slice(-2)}).join("");localStorage.setItem("px_dev",d)}return d}catch(e){return ""}})();
async function api(path,opt){
  opt=opt||{};var h={"X-Dev":DEV};var tk=localStorage.getItem("px_token");if(tk)h["X-Token"]=tk;
  var body=opt.body;if(body&&!(body instanceof Blob)){h["Content-Type"]="application/json";body=JSON.stringify(body)}
  var mth=opt.method||(body?"POST":"GET");
  if(mth!=="GET"&&!/^\/api\/(now|ping|tg\/status)/.test(path))VC={};
  var r;
  try{r=await fetch(path,{method:mth,headers:h,body:body})}
  catch(e0){var ne=new Error("Нет соединения с сервером");ne.status=0;if(!OFFLINE){OFFLINE=true;logErr("net",path.split("?")[0]+": "+e0.message,"");if(localStorage.getItem("px_token")){try{render()}catch(e1){}}}throw ne}
  var j={};try{j=await r.json()}catch(e){}
  if(!r.ok){if(r.status===500)logErr("api",path.split("?")[0]+" → "+(j.error||r.status),"");var er=new Error(j.error||("Ошибка "+r.status));er.status=r.status;er.banned=!!j.banned;er.detail=j.detail||"";throw er}
  if(j&&j.fav_ids){FAVS={};j.fav_ids.forEach(function(i){FAVS[i]=1})}
  if(path.indexOf("/api/me")===0&&j&&j.user&&j.user.name)ensureAccount(j.user);
  return j;
}
function upload(url,file,onp){
  return new Promise(function(res,rej){
    var x=new XMLHttpRequest();x.open("POST",url);x.setRequestHeader("X-Token",localStorage.getItem("px_token")||"");
    x.upload.onprogress=function(e){if(e.lengthComputable&&onp)onp(e.loaded/e.total)};
    x.onload=function(){VC={};var j={};try{j=JSON.parse(x.responseText)}catch(e){}x.status<300?res(j):rej(new Error(j.error||("Ошибка "+x.status)))};
    x.onerror=function(){rej(new Error("Нет связи с сервером"))};x.send(file);
  });
}
function shrink(file,max,q){return new Promise(function(res,rej){
  var im=new Image(),u=URL.createObjectURL(file);
  im.onload=function(){var k=Math.min(1,max/Math.max(im.width,im.height));var w=Math.max(1,Math.round(im.width*k)),h=Math.max(1,Math.round(im.height*k));
    var c=document.createElement("canvas");c.width=w;c.height=h;var g=c.getContext("2d");g.fillStyle="#0e1424";g.fillRect(0,0,w,h);g.drawImage(im,0,0,w,h);
    c.toBlob(function(b){URL.revokeObjectURL(u);b?res(b):rej(new Error("Не удалось обработать картинку"))},"image/jpeg",q)};
  im.onerror=function(){URL.revokeObjectURL(u);rej(new Error("Это не картинка"))};im.src=u})}

/* ---------- чтение тегов и обложек из mp3 / m4a / mp4 ---------- */
function readBuf(f,s,n){return f.slice(s,s+n).arrayBuffer()}
function decTxt(b,e){
  try{
    if(e===1){if(b[0]===255&&b[1]===254)return new TextDecoder("utf-16le").decode(b.subarray(2));if(b[0]===254&&b[1]===255)return new TextDecoder("utf-16be").decode(b.subarray(2));return new TextDecoder("utf-16le").decode(b)}
    if(e===2)return new TextDecoder("utf-16be").decode(b);
    if(e===3)return new TextDecoder("utf-8").decode(b);
    return new TextDecoder("windows-1252").decode(b);
  }catch(x){return ""}
}
function cleanTxt(s){return String(s||"").replace(/\0+/g,"").trim()}
function syn(b,o){return (b[o]&127)<<21|(b[o+1]&127)<<14|(b[o+2]&127)<<7|(b[o+3]&127)}
function imgBlob(p){var t="image/jpeg";if(p[0]===0x89&&p[1]===0x50)t="image/png";else if(p[0]===0x47&&p[1]===0x49)t="image/gif";else if(p[0]===0x52&&p[1]===0x49)t="image/webp";return new Blob([p],{type:t})}
async function readID3(file){
  var head=new Uint8Array(await readBuf(file,0,10));
  var ver=head[3],size=syn(head,6);if(size>20*1048576)size=20*1048576;
  var b=new Uint8Array(await readBuf(file,10,size)),o=0,res={};
  if(head[5]&0x40&&ver>2){o=ver===4?syn(b,0):(((b[0]<<24)|(b[1]<<16)|(b[2]<<8)|b[3])>>>0)+4}
  var il=ver===2?3:4,hl=ver===2?6:10;
  while(o+hl<=b.length){
    var id="";for(var k=0;k<il;k++)id+=String.fromCharCode(b[o+k]);
    if(!/^[A-Z0-9]+$/.test(id))break;
    var fs=ver===2?((b[o+3]<<16)|(b[o+4]<<8)|b[o+5]):ver===4?syn(b,o+4):(((b[o+4]<<24)|(b[o+5]<<16)|(b[o+6]<<8)|b[o+7])>>>0);
    var d=b.subarray(o+hl,o+hl+fs);o+=hl+fs;if(!d.length)continue;
    if(id==="TIT2"||id==="TT2")res.title=cleanTxt(decTxt(d.subarray(1),d[0]));
    else if(id==="TPE1"||id==="TP1")res.artist=cleanTxt(decTxt(d.subarray(1),d[0]));
    else if((id==="APIC"||id==="PIC")&&!res.cover){
      var e=d[0],p=1;
      if(id==="APIC"){while(p<d.length&&d[p]!==0)p++;p++}else p=4;
      p++; // тип картинки
      if(e===1||e===2){while(p+1<d.length&&!(d[p]===0&&d[p+1]===0))p+=2;p+=2}else{while(p<d.length&&d[p]!==0)p++;p++}
      if(p<d.length)res.cover=imgBlob(d.subarray(p));
    }
  }
  return res;
}
function boxes(b,s,e,cb){var o=s;while(o+8<=e){var sz=((b[o]<<24)|(b[o+1]<<16)|(b[o+2]<<8)|b[o+3])>>>0;var t=String.fromCharCode(b[o+4],b[o+5],b[o+6],b[o+7]);if(sz<8||o+sz>e)break;cb(t,o+8,o+sz);o+=sz}}
function parseMoov(b){
  var res={};
  function walk(s,e){boxes(b,s,e,function(t,ds,de){
    if(t==="udta"||t==="moov")walk(ds,de);
    else if(t==="meta")walk(ds+4,de);
    else if(t==="ilst")boxes(b,ds,de,function(t2,ds2,de2){boxes(b,ds2,de2,function(t3,ds3,de3){
      if(t3!=="data")return;var p=b.subarray(ds3+8,de3);
      if(t2==="\u00a9nam")res.title=cleanTxt(new TextDecoder("utf-8").decode(p));
      else if(t2==="\u00a9ART")res.artist=cleanTxt(new TextDecoder("utf-8").decode(p));
      else if(t2==="covr"&&!res.cover)res.cover=imgBlob(p);
    })});
  })}
  walk(0,b.length);return res;
}
async function readMP4(file){
  var pos=0,size=file.size;
  while(pos+8<=size){
    var h=new DataView(await readBuf(file,pos,16));var sz=h.getUint32(0);var t=String.fromCharCode(h.getUint8(4),h.getUint8(5),h.getUint8(6),h.getUint8(7)),hdr=8;
    if(sz===1){sz=h.getUint32(8)*4294967296+h.getUint32(12);hdr=16}else if(sz===0)sz=size-pos;
    if(sz<hdr)break;
    if(t==="moov"){if(sz>60*1048576)return {};return parseMoov(new Uint8Array(await readBuf(file,pos+hdr,sz-hdr)))}
    pos+=sz;
  }
  return {};
}
async function extractMeta(file){
  try{
    var h=new Uint8Array(await readBuf(file,0,12));
    if(h[0]===73&&h[1]===68&&h[2]===51)return await readID3(file);
    if(h[4]===102&&h[5]===116&&h[6]===121&&h[7]===112)return await readMP4(file);
  }catch(e){}
  return {};
}

/* ---------- плеер ---------- */
var AUDIO=new Audio(),A=AUDIO;AUDIO.preload="metadata";
var Q=[],qi=-1,dragging=false,SHUF=false,REP=0,lastId=null,sleepT=null,sleepEnd=0,WANT=false,raf=0;
var FADE=1,FADEIN=0;
function fmt(s){if(!isFinite(s)||s<0)return "0:00";s=Math.floor(s);return Math.floor(s/60)+":"+String(s%60).padStart(2,"0")}
function artOf(t){return t.artist||"Неизвестный исполнитель"}
function playQ(ids,i){var cur=ids[i];Q=ids.filter(function(id){return T[id]&&(T[id].url||T[id].ghost)});if(!Q.length){toast("В этом списке нечего слушать");return}qi=Q.indexOf(cur);if(qi<0)qi=0;loadCur(true)}
function next(auto){
  if(!Q.length)return;
  if(SHUF&&Q.length>1){var n;do{n=Math.floor(Math.random()*Q.length)}while(n===qi);qi=n}
  else if(qi+1>=Q.length){if(REP===0&&auto){A.pause();A.currentTime=0;syncUI();return}qi=0}
  else qi++;
  loadCur();
}
function prev(){if(!Q.length)return;if(A.currentTime>3){A.currentTime=0;return}qi=(qi-1+Q.length)%Q.length;loadCur()}
function toggle(){if(!A.src||!Q.length)return;if(A.paused){WANT=true;A.play().then(syncUI,function(){WANT=false;syncUI()});syncUI()}else{WANT=false;A.pause();syncUI()}}
function markRows(){var cur=Q[qi];document.querySelectorAll(".row[data-list]").forEach(function(r){var ids=(r.dataset.list||"").split(",");r.classList.toggle("on",ids[+r.dataset.i]===cur)})}
function setRange(el,pct){el.style.setProperty("--pn",String(Math.max(0,Math.min(100,pct))/100))}
function syncUI(){
  syncPlBtn();var t=T[Q[qi]];$("#mini").classList.toggle("show",!!t);if(!t)return;
  if(lastId!==t.id){
    lastId=t.id;
    $("#mcov").innerHTML=cov(t.cover);$("#bigcov").innerHTML=cov(t.cover);
    sbgApply(t);$("#mini").style.setProperty("--mcov",t.cover?'url("'+t.cover+'")':"none");
    $("#seek").value=0;setRange($("#seek"),0);
  }
  $("#mtitle").textContent=t.title;$("#mart").textContent=artOf(t);$("#stitle").textContent=t.title;$("#sart").textContent=artOf(t)+(t.owner?" · @"+t.owner:"");
  var pl=!A.paused||WANT;document.body.classList.toggle("ppaused",!pl);var ic=pl?I("pause"):I("play");$("#mpp").innerHTML=ic;$("#spp").innerHTML=ic;
  $("#sheet").classList.toggle("playing",pl);
  $("#bshuf").classList.toggle("on",SHUF);$("#brep").classList.toggle("on",REP>0);$("#brep").innerHTML=I(REP===2?"repeat1":"repeat");syncOffBtn();syncFavBtn();placeYt();
}
function tickP(){updProg();if(!A.paused)raf=requestAnimationFrame(tickP)}
A.onplay=function(){WANT=false;syncUI();cancelAnimationFrame(raf);raf=requestAnimationFrame(tickP)};
A.onpause=function(){WANT=false;syncUI()};
A.onwaiting=function(){$("#mini").classList.add("buf");$("#sheet").classList.add("buf")};
A.onplaying=A.oncanplay=function(){$("#mini").classList.remove("buf");$("#sheet").classList.remove("buf")};
A.onended=function(){ltFlush();if(REP===2){var rt=T[Q[qi]];if(rt)ltStart(rt);A.currentTime=0;A.play().catch(function(){});return}if(SET.auto){if(SET.xfade!==false&&hasNext())FADEIN=1;next(true)}else syncUI()};
A.onerror=function(){WANT=false;syncUI();if(A.getAttribute("src"))toast("Не удалось воспроизвести этот файл")};
function updProg(){ltStep();fadeStep();
  var p=A.duration?A.currentTime/A.duration*100:0;
  $("#mprog").style.width=p+"%";$("#tcur").textContent=fmt(A.currentTime);$("#tdur").textContent=fmt(A.duration);
  if(!dragging){$("#seek").value=Math.round(p*10);setRange($("#seek"),p)}
}
A.ontimeupdate=updProg;
/* ---------- импортированные треки играют через встроенный плеер YouTube (официальный embed) ---------- */
var LOADID=0;
function ytApi(cb){
  if(window.YT&&YT.Player){cb();return}
  YA._cbs=YA._cbs||[];YA._cbs.push(cb);
  if(YA._loading)return;
  YA._loading=true;
  var s=document.createElement("script");s.src="https://www.youtube.com/iframe_api";
  s.onerror=function(){YA._loading=false;YA._cbs=[];WANT=false;syncUI();toast("Не удалось загрузить плеер YouTube. Нужен интернет")};
  window.onYouTubeIframeAPIReady=function(){YA._cbs.forEach(function(f){f()});YA._cbs=[]};
  document.head.appendChild(s);
}
var YA={
  paused:true,duration:0,src:"",_t:0,_v:1,_p:null,_ready:false,_want:"",_iv:0,
  get currentTime(){return this._t},
  set currentTime(v){this._t=v;if(this._p&&this._ready&&this._p.seekTo){try{this._p.seekTo(v,true)}catch(e){}}},
  get volume(){return this._v},
  set volume(v){this._v=v;if(this._p&&this._ready&&this._p.setVolume){try{this._p.setVolume(v*100)}catch(e){}}},
  getAttribute:function(){return this.src||null},
  removeAttribute:function(){this.src="";this.paused=true;clearInterval(this._iv);try{if(this._p&&this._ready)this._p.stopVideo()}catch(e){}placeYt()},
  load:function(id){
    var self=this;self.src="yt:"+id;self._want=id;self.paused=true;self._t=0;self.duration=0;
    ytApi(function(){
      if(self._want!==id)return;
      if(self._p&&self._ready){try{self._p.loadVideoById(id);self._p.setVolume(self._v*100)}catch(e){}return}
      if(self._p)return;
      self._p=new YT.Player("ytp",{width:"100%",height:"100%",videoId:id,
        playerVars:{autoplay:1,controls:0,playsinline:1,rel:0,modestbranding:1,fs:0,iv_load_policy:3},
        events:{
          onReady:function(){self._ready=true;try{self._p.setVolume(self._v*100);if(self._want!==id)self._p.loadVideoById(self._want);else self._p.playVideo()}catch(e){}},
          onStateChange:function(e){self._state(e.data)},
          onError:function(){ytFail()}
        }});
    });
    placeYt();
  },
  play:function(){if(this._p&&this._ready){try{this._p.playVideo()}catch(e){}}return Promise.resolve()},
  pause:function(){if(this._p&&this._ready){try{this._p.pauseVideo()}catch(e){}}this.paused=true},
  _state:function(s){
    if(s===1){this.paused=false;this._poll();if(this.onplaying)this.onplaying();if(this.onplay)this.onplay()}
    else if(s===2){this.paused=true;if(this.onpause)this.onpause()}
    else if(s===0){this.paused=true;if(this.onpause)this.onpause();if(this.onended)this.onended()}
    else if(s===3){if(this.onwaiting)this.onwaiting()}
  },
  _poll:function(){
    var self=this;clearInterval(self._iv);
    self._iv=setInterval(function(){
      try{self._t=self._p.getCurrentTime()||0;var d=self._p.getDuration();if(d)self.duration=d}catch(e){}
      if(self.ontimeupdate)self.ontimeupdate();
      if(self.paused)clearInterval(self._iv);
    },300);
  }
};
["onplay","onpause","onwaiting","onplaying","oncanplay","onended","onerror","ontimeupdate"].forEach(function(k){YA[k]=AUDIO[k]});
function placeYt(){
  var b=document.getElementById("ytbox"),sh=$("#sheet");
  if(!b)return;
  if(A!==YA||!YA.src){b.style.display="none";sh.classList.remove("yt");return}
  var open=sh.classList.contains("open"),big=$("#bigcov"),src=(open&&big&&big.offsetWidth>10)?big:$("#mcov"),r=src.getBoundingClientRect();
  sh.classList.add("yt");
  b.style.display="block";b.style.left=r.left+"px";b.style.top=r.top+"px";b.style.width=r.width+"px";b.style.height=r.height+"px";
  b.style.borderRadius=src===big?"28px":"14px";b.style.pointerEvents=src===big?"auto":"none";
}
function useEngine(yt){
  var want=yt?YA:AUDIO;
  if(A!==want){try{A.pause()}catch(e){}A=want}
  applyVol();
  if(!yt){YA.src="";YA.paused=true;clearInterval(YA._iv)}
  placeYt();
}
function resolveGhost(t,bad){
  if(t.yt&&!bad)return Promise.resolve(t);
  if(!localStorage.getItem("px_token"))return Promise.reject(new Error("Войди в аккаунт, чтобы слушать импортированные треки"));
  var body=t.tmp?{title:t.title,artist:t.artist||"",dur:t.dur||0}:{id:t.id};
  if(bad)body.bad=bad;
  return api("/api/resolve",{body:body}).then(function(r){
    if(r.track)Object.assign(t,r.track,{id:t.id});
    if(r.yt)t.yt=r.yt;
    if(r.cover&&!t.cover)t.cover=r.cover;
    return t;
  });
}
function ghostReady(t,my,user){
  lastId=null;
  if(t.url){useEngine(false);A.src=t.url;WANT=true;A.play().then(syncUI,function(){WANT=false;syncUI()});syncUI();placeYt()}
  else{startYt(t,my,user);syncUI()}
}
function ytFail(){
  var t=T[Q[qi]],my=LOADID;
  if(!t||A!==YA)return;
  YA._retry=(YA._retry||0)+1;
  if(YA._retry>4){WANT=false;YA.paused=true;syncUI();toast("Этот трек недоступен во встроенном плеере. Привяжи файл: кнопка со ссылкой у трека в плейлисте");return}
  toast("Ищу другую версию трека…",{type:"load"});
  resolveGhost(t,t.yt).then(function(){if(my===LOADID)ghostReady(t,my,false)}).catch(function(e){if(my!==LOADID)return;WANT=false;YA.paused=true;syncUI();logErr("resolve",e.message,e.detail||"");toast(e.message||"Трек недоступен")});
}
function startYt(t,my,user){
  useEngine(true);YA.load(t.yt);
  if(user&&!$("#sheet").classList.contains("open"))openSheet();
  placeYt();clearTimeout(YA._hint);
  YA._hint=setTimeout(function(){if(my===LOADID&&A===YA&&A.paused)toast("Если музыка не пошла, нажми на видео")},4500);
}
function loadCur(user){
  var t=T[Q[qi]];if(!t)return;
  var my=++LOADID;ltFlush();ltStart(t);if(!t.url)FADEIN=0;else if(SET.xfade!==false&&FADE<.95)FADEIN=1;
  if(t.url){useEngine(false);A.src=t.url;WANT=true;A.play().then(syncUI,function(){WANT=false;syncUI()})}
  else{
    try{A.pause()}catch(e){}
    WANT=true;
    YA._retry=0;
    if(t.yt)startYt(t,my,user);
    else{toast("Ищу трек…",{type:"load"});resolveGhost(t).then(function(){if(my===LOADID)ghostReady(t,my,user)}).catch(function(e){if(my!==LOADID)return;WANT=false;syncUI();logErr("resolve",e.message,e.detail||"");toast(e.message||"Не удалось найти этот трек")})}
  }
  api("/api/now",{body:{id:t.id,title:t.title}}).catch(function(){});
  if("mediaSession" in navigator){try{
    var art=t.cover&&t.cover.charAt(0)==="/"?[{src:location.origin+t.cover,sizes:"512x512",type:"image/jpeg"}]:[];
    navigator.mediaSession.metadata=new MediaMetadata({title:t.title,artist:artOf(t),album:"PiXeL Music",artwork:art});
    navigator.mediaSession.setActionHandler("nexttrack",function(){next(false)});navigator.mediaSession.setActionHandler("previoustrack",prev);
    navigator.mediaSession.setActionHandler("play",function(){A.play()});navigator.mediaSession.setActionHandler("pause",function(){A.pause()});
  }catch(e){}}
  syncUI();markRows();renderQueue();
}

$("#seek").addEventListener("input",function(){dragging=true;var p=this.value/10;setRange(this,p);$("#tcur").textContent=fmt(this.value/1000*(A.duration||0))});
$("#seek").addEventListener("change",function(){if(A.duration)A.currentTime=this.value/1000*A.duration;dragging=false});
function renderQueue(){
  var h='<div class="lab" style="margin:16px 0 8px">Очередь · '+Q.length+'</div>';
  Q.forEach(function(id,i){var t=T[id];if(!t)return;h+='<div class="row'+(i===qi?" on":"")+'" data-act="qjump" data-i="'+i+'"><div class="cv">'+cimg(t.cover,t.id)+'</div><div class="meta"><b>'+esc(t.title)+'</b><small>'+esc(artOf(t))+'</small></div></div>'});
  $("#sq").innerHTML=h;
}
function setSleep(m){
  clearTimeout(sleepT);sleepT=null;sleepEnd=0;
  if(m>0){sleepEnd=Date.now()+m*60000;sleepT=setTimeout(function(){A.pause();sleepEnd=0;$("#slab").textContent="Таймер сна";toast("Таймер сна: пауза")},m*60000);$("#slab").textContent="Сон через "+m+" мин"}
  else $("#slab").textContent="Таймер сна";
}
(function(){var e="";for(var i=0;i<28;i++)e+='<i style="animation-duration:'+(0.55+Math.random()*0.9).toFixed(2)+'s;animation-delay:-'+(Math.random()).toFixed(2)+'s"></i>';$("#eq").innerHTML=e})();

/* ---------- настройки ---------- */
function applySet(){
  var tv=themeVars(okHex(SET.acc));Object.keys(tv).forEach(function(k){document.documentElement.style.setProperty(k,tv[k])});document.body.classList.toggle("st-flat",SET.style==="flat");document.body.classList.toggle("st-glass",SET.style==="glass");var tm=document.querySelector("meta[name=theme-color]");if(tm)tm.setAttribute("content",tv["--bg"]);
  var weak=(navigator.hardwareConcurrency||8)<=4||(navigator.deviceMemory||4)<=2||(window.matchMedia&&matchMedia("(prefers-reduced-motion: reduce)").matches);
  document.body.classList.toggle("lite",SET.perf==="lite"||(SET.perf==="auto"&&weak));
  applyVol();$("#vol2").value=SET.vol;setRange($("#vol2"),SET.vol);var v1=$("#vol");if(v1){v1.value=SET.vol;setRange(v1,SET.vol)}
  document.documentElement.style.setProperty("--bgdim",String(SET.bgdim/100));var bm=$("#bgm");if(bm)bm.classList.toggle("blur",!!SET.bgblur);
  applyMini();
  try{localStorage.setItem("px_set",JSON.stringify(SET))}catch(e){}
  if(ACC&&!PQ)schedPrefs();
}

/* ---------- куски интерфейса ---------- */
function fdur(s){s=Math.round(s||0);return s>0?Math.floor(s/60)+":"+String(s%60).padStart(2,"0"):""}
function seenTxt(sec){sec=sec||0;if(sec<60)return "только что";if(sec<3600)return Math.floor(sec/60)+" мин назад";if(sec<86400)return Math.floor(sec/3600)+" ч назад";return Math.floor(sec/86400)+" дн назад"}
function ago(ts){return seenTxt(Math.max(0,Date.now()/1000-(ts||0)))}
function p2(x){return String(x).padStart(2,"0")}
function hhmm(t){var d=new Date(t*1000),n=new Date();return d.toDateString()===n.toDateString()?p2(d.getHours())+":"+p2(d.getMinutes()):p2(d.getDate())+"."+p2(d.getMonth()+1)}
function audioDur(f){return new Promise(function(res){var u=URL.createObjectURL(f),a=new Audio(),done=false;function fin(v){if(done)return;done=true;URL.revokeObjectURL(u);res(isFinite(v)?Math.round(v):0)}a.preload="metadata";a.onloadedmetadata=function(){fin(a.duration)};a.onerror=function(){fin(0)};setTimeout(function(){fin(0)},5000);a.src=u})}
function defAva(){return '<svg viewBox="0 0 64 64" width="100%" height="100%"><rect width="64" height="64" fill="#fff"/><path fill-rule="evenodd" fill="var(--acc)" d="M19 10h17c10 0 16 6 16 15s-6 15-16 15h-7v14H19zM29 19v13h6c4 0 7-2.7 7-6.5S39 19 35 19z"/><rect x="47" y="49" width="6" height="6" fill="var(--acc)" opacity=".35"/></svg>'}
function avaInner(u){return u&&u.avatar?'<img src="'+esc(u.avatar)+'" alt="">':defAva()}
function backBtn(act){return '<button class="btn sec" data-act="'+(act||"back")+'">'+I("back")+" Назад</button>"}
function trow(t,ids,i,mode){
  T[t.id]=t;
  var own=mode==="own"||mode==="plmine",sub=esc(artOf(t));
  if(mode!=="own"&&mode!=="u")sub+=" · @"+esc(t.owner);
  if(mode==="feed")sub+=" · "+ago(t.created);
  var vt="";if(mode==="own")vt='<span class="vtag'+(t.private?" pv":"")+'" data-act="tvis" data-id="'+esc(t.id)+'" data-v="'+(t.private?"0":"1")+'">'+(t.private?"для себя":"в ленте")+"</span>";
  if(t.ghost)sub='<span class="gb">'+svcLogo(t.src,14)+"</span>"+sub;
  var btns="";
  if(mode==="own")btns=(t.private||t.ghost?"":'<button class="ib" data-act="newpost" data-id="'+esc(t.id)+'">'+I("feed")+"</button>")+'<button class="ib" data-act="edittrack" data-id="'+esc(t.id)+'">'+I("edit")+'</button><button class="ib" data-act="deltrack" data-id="'+esc(t.id)+'">'+I("trash")+"</button>";
  else if(mode==="plmine")btns=(t.ghost?'<button class="ib" data-act="attach" data-id="'+esc(t.id)+'" aria-label="Привязать файл">'+I("link")+"</button>":"")+'<button class="ib" data-act="plremove" data-id="'+esc(t.id)+'">'+I("x")+"</button>";
  else if(mode==="off")btns='<button class="ib" data-act="offdel" data-id="'+esc(t.id)+'">'+I("trash")+"</button>";
  return '<div class="row'+(t.ghost?" ghost":"")+'" data-act="play" data-list="'+esc(ids.join(","))+'" data-i="'+i+'"><div class="cv">'+cov(t.cover)+'<span class="eqm"><i></i><i></i><i></i></span></div><div class="meta"><b>'+esc(t.title)+"</b><div class=\"sl\"><small>"+sub+"</small>"+vt+"</div></div>"+
  (t.dur?'<span class="dur">'+fdur(t.dur)+"</span>":"")+btns+"</div>";
}
function tlist(tr,mode){if(mode===true)mode="own";if(!tr.length)return '<p class="hint center">Пока пусто</p>';var ids=tr.map(function(t){return t.id});return tr.map(function(t,i){return trow(t,ids,i,mode)}).join("")}
/* ---------- соцсети в профиле ---------- */
var SOC={tiktok:["TikTok","https://www.tiktok.com/@","@nickname"],youtube:["YouTube","https://www.youtube.com/@","@channel"],telegram:["Telegram","https://t.me/","@username"],instagram:["Instagram","https://instagram.com/","@username"],vk:["VK","https://vk.com/","ник или id"]};
function socUrl(k,v){return k==="youtube"&&/^(channel|c|user)\//i.test(v)?"https://www.youtube.com/"+v:SOC[k][1]+v}
function socRow(u){
  var s=u.socials||{},ks=Object.keys(SOC).filter(function(k){return s[k]});
  if(!ks.length)return "";
  return '<div class="socs">'+ks.map(function(k){return '<a class="soc" href="'+esc(socUrl(k,s[k]))+'" target="_blank" rel="noopener noreferrer">'+I(k)+"<span>"+SOC[k][0]+"</span>"+I("ext")+"</a>"}).join("")+"</div>";
}
function socBlock(u,mine){
  var r=socRow(u);if(r)return r;
  return mine?'<div class="socs socs-empty"><small>Добавь TikTok, YouTube или Telegram: кнопки появятся здесь</small><button class="btn sec sm" data-act="edit">'+I("plus")+" Соцсети</button></div>":"";
}
function socVals(){var o={};Object.keys(SOC).forEach(function(k){var e=$("#eSoc_"+k);o[k]=e?e.value:""});return o}
function socForm(u){
  return '<h3 class="lab" style="margin-top:20px">Соцсети</h3><p class="hint" style="margin-top:0">Впиши ник или ссылку. В профиле появятся кнопки, по ним тебя найдут.</p>'+
  Object.keys(SOC).map(function(k){return '<label class="l lab">'+SOC[k][0]+'</label><input id="eSoc_'+k+'" maxlength="80" placeholder="'+SOC[k][2]+'" value="'+esc((u.socials||{})[k]||"")+'" autocapitalize="off" autocomplete="off" spellcheck="false">'}).join("");
}
/* ---------- блокировка пользователей ---------- */
function cmenuToggle(open){
  var m=$("#cmenu"),on=open===undefined?!m.classList.contains("open"):open;
  m.classList.toggle("open",on);
  if(on)$("#cmblock").innerHTML=I(CH.iblock?"check":"lock")+(CH.iblock?"Разблокировать":"Заблокировать");
}
async function doBlock(name,on){
  if(!name)return;
  try{await api("/api/block",{body:{name:name,on:on}});toast(on?"Пользователь заблокирован":"Пользователь разблокирован");CH.busy=false;loadChat(false)}
  catch(e){toast(e.message)}
}
/* ---------- плейлисты: карточки, оценки, комментарии ---------- */
function fr(n){return String(n).replace(".",",")}
function plMosaic(p,cls){
  var inner;
  if(p.fav)inner='<span class="ni">'+I("heart")+"</span>";
  else if(p.mosaic&&p.covers&&p.covers.length>=2){
    var cs=p.covers.slice(0,4);while(cs.length<4)cs.push(cs[cs.length%p.covers.length]);
    inner='<div class="mos">'+cs.map(function(c){return '<img src="'+esc(c)+'" alt="" loading="lazy">'}).join("")+"</div>";
  }else inner=cov(p.cover);
  return '<div class="plm'+(cls?" "+cls:"")+'">'+inner+"</div>";
}
function plStats(p,big){
  if(p.fav)return "";
  return '<div class="pls'+(big?" big":"")+'">'+(big?"<span>"+p.count+" "+trk(p.count)+"</span>":"")+'<span class="st'+(p.nrate?"":" off")+'">'+I("star")+(p.nrate?"<b>"+fr(p.rating)+"</b><i>("+p.nrate+")</i>":"<i>нет оценок</i>")+"</span><span>"+I("play")+p.plays+"</span>"+(big?"":"<span>"+I("chat")+p.ncom+"</span>")+"</div>";
}
function plcard(p){
  return '<div class="plc" data-act="openpl" data-id="'+esc(p.id)+'">'+plMosaic(p)+'<div class="plb"><b class="plt">'+esc(p.name)+"</b><small>"+(p.fav?"":esc(p.owner_display||p.owner)+" · ")+p.count+" "+trk(p.count)+"</small>"+plStats(p)+'</div><span class="chev">'+I("chev")+"</span></div>";
}
function plCmt(p,c){
  var who=' data-act="openuser" data-id="'+esc(c.user)+'"';
  return '<div class="cmr"><div class="av"'+who+">"+avaInner(c)+'</div><div class="cmb"><div class="cmh"><b'+who+">"+esc(c.display)+"</b>"+(c.op?'<span class="fx-op">автор</span>':"")+"<small>"+ago(c.t)+'</small></div><div class="cmx">'+esc(c.text)+"</div></div>"+(c.can_del?'<button class="ib" data-act="plcmtdel" data-id="'+esc(p.id)+'" data-v="'+esc(c.id)+'">'+I("x")+"</button>":"")+"</div>";
}
function plExtra(d,p,mine,guest){
  if(p.fav)return "";
  var h='<div class="card plrate"><div class="lab" style="margin:0">'+(mine?"Оценка слушателей":"Оцени плейлист")+"</div>";
  if(mine||guest)h+='<div class="rbig">'+(p.nrate?"★ "+fr(p.rating)+" <small>("+p.nrate+")</small>":"<small>Пока никто не оценил</small>")+"</div>";
  else{
    var my=p.my_rate||0;
    h+='<div class="rstars">'+[1,2,3,4,5].map(function(i){return '<button class="rs'+(i<=my?" on":"")+'" data-act="plrate" data-id="'+esc(p.id)+'" data-v="'+i+'" data-my="'+my+'" aria-label="Оценка '+i+'">'+I("star")+"</button>"}).join("")+'</div><p class="hint center" style="margin:4px 0 0">'+(my?"Твоя оценка: "+my+". Нажми ту же звезду, чтобы убрать":"Нажми на звезду")+"</p>";
  }
  h+="</div>";
  h+='<h3 class="lab">Комментарии · '+p.ncom+'</h3><div class="card">'+(d.comments.length?d.comments.map(function(c){return plCmt(p,c)}).join(""):'<p class="hint center" style="margin:6px 0">Пока никто не написал. Начни первым</p>')+"</div>";
  if(!guest)h+='<div class="card"><textarea id="plcIn" maxlength="300" rows="2" placeholder="Что думаешь о плейлисте?"></textarea><button class="btn" data-act="plcmtsend" data-id="'+esc(p.id)+'" style="margin-bottom:0">'+I("send")+" Отправить</button></div>";
  return h;
}
function isListQ(list){
  var f=list.filter(function(i){return T[i]&&(T[i].url||T[i].ghost)});
  return f.length>0&&Q.length===f.length&&f.every(function(x,k){return Q[k]===x});
}
function syncPlBtn(){
  var b=$("#plplaybtn");if(!b)return;
  var l=(b.dataset.list||"").split(",").filter(Boolean),on=isListQ(l)&&(!A.paused||WANT);
  b.innerHTML=I(on?"pause":"play")+(on?" Пауза":" Слушать");
}
/* ---------- редактирование трека ---------- */
function editTrackHtml(t){
  return '<h3 class="mtitle">Переименовать трек</h3><label class="l lab">Название</label><input id="etTitle" maxlength="80" value="'+esc(t.title||"")+'" autocomplete="off"><label class="l lab">Исполнитель</label><input id="etArtist" maxlength="60" value="'+esc(t.artist||"")+'" placeholder="Можно оставить пустым" autocomplete="off">'+
  '<div class="ettools"><button class="et" data-act="etcover" data-id="'+esc(t.id)+'">'+I("img")+"<span>Обложка</span></button>"+
  (t.ghost?"":'<button class="et" data-act="etvis" data-id="'+esc(t.id)+'">'+I(t.private?"globe":"lock")+"<span>"+(t.private?"В ленту":"Для себя")+"</span></button>")+
  (t.ghost||t.private?"":'<button class="et" data-act="etpost" data-id="'+esc(t.id)+'">'+I("feed")+"<span>Поделиться</span></button>")+
  '<button class="et red" data-act="etdel" data-id="'+esc(t.id)+'">'+I("trash")+"<span>Удалить</span></button></div>"+
  '<div class="btns"><button class="btn sec" data-act="closemodal">Отмена</button><button class="btn" data-act="etsave" data-id="'+esc(t.id)+'">Сохранить</button></div>';
}
function pllist(a){return a.length?a.map(plcard).join(""):'<p class="hint center">Пока пусто</p>'}
function allBtn(tr){return tr.length?'<button class="btn" data-act="playall" data-list="'+esc(tr.map(function(t){return t.id}).join(","))+'">'+I("play")+" Слушать всё</button>":""}
function recentCard(tr,title){
  if(!tr.length)return "";
  var ids=tr.map(function(t){return t.id}).join(",");
  return '<div class="card"><div class="rowh"><h3 class="lab" style="margin:0">'+title+'</h3><button class="btn sm" data-act="playall" data-list="'+esc(ids)+'">'+I("play")+" Слушать</button></div>"+tlist(tr,"")+"</div>";
}
var TAGC={"Владелец":"#f5b81c","Разработчик":"#19c8e6","Модератор":"#22d3a0","VIP":"#ff4fa3","Тестер":"#8b5cf6"};
function tagPill(t,i,extra){
  var c=TAGC[t],st="";
  if(c){var rgb=hexRgb(c),lum=(0.299*rgb[0]+0.587*rgb[1]+0.114*rgb[2])/255;st=' style="--pc:'+c+";--pcr:"+rgb.join(",")+";--pt:"+(lum>.6?"#1a1204":"#fff")+'"'}
  return '<span class="pill'+(i===0?" f":"")+'"'+st+(extra||"")+">"+esc(t)+(extra?" "+I("x"):"")+"</span>";
}
function profCard(u,mine,withChat){
  var ah=u.accent?okHex(u.accent,""):"";
  var st=ah?varStr(themeVars(ah)):"";
  var pin=u.locked?null:u.pin;if(pin)T[pin.id]=pin;
  var self=mine||(S.me&&S.me.name===u.name);
  var h='<div class="pscope"'+(st?' style="'+st+'"':"")+'>';
  h+='<div class="pcard'+(u.banner?"":" nb")+'"'+(u.banner?' style="background-image:url(\''+esc(u.banner)+'\')"':"")+'>';
  h+='<div class="phead"><div class="ava"><div class="ai">'+avaInner(u)+'</div></div><div class="pinfo">';
  h+='<div class="pst"><span class="dot'+(u.online?"":" off")+'"></span>'+esc(u.status||(u.online?"В сети":"Не в сети"))+(u.online?"":'<span class="seen"> · '+seenTxt(u.seen)+"</span>")+"</div>";
  h+='<div class="pname">'+esc(u.display||u.name)+'</div><div class="pid">@'+esc(u.name)+'</div><div class="pills">';
  (u.tags||[]).forEach(function(t,i){h+=tagPill(t,i)});
  if(u.locked||(mine&&u.private))h+='<span class="pill">'+I("lock")+" Закрытый</span>";
  if(u.now&&!u.locked)h+='<span class="pill">♪ '+esc(u.now)+"</span>";
  h+="</div></div></div>";
  if(pin)h+='<div class="ptrack" data-act="playpin" data-id="'+esc(pin.id)+'"><div class="cv">'+cov(pin.cover)+'</div><div class="meta"><b>'+esc(pin.title)+"</b><small>"+esc(artOf(pin))+'</small></div><button class="pb" tabindex="-1">'+I("play")+"</button></div>";
  h+="</div>";
  if(withChat&&!self&&S.me)h+='<button class="btn" data-act="openchat" data-id="'+esc(u.name)+'">'+I("chatplus")+" Написать</button>";
  if(u.locked)h+='<div class="card lockc">'+I("lock")+'<div><b>Профиль закрыт</b><small>Пользователь скрыл информацию о себе, свои треки и плейлисты.</small></div></div>';
  else h+='<div class="card about"><div class="rowh"><h3 class="lab" style="margin:0">О себе</h3>'+(mine?'<button class="btn sm" data-act="edit">'+I("edit")+" Изменить</button>":"")+"</div><p>"+
    (u.bio?esc(u.bio):'<span class="mut">'+(mine?"Расскажи о себе: что умеешь, что слушаешь и чего хочешь. Тебя увидят другие.":"Пока ничего не написано о себе")+"</span>")+"</p>"+(u.locked?"":socBlock(u,mine))+"</div>";
  return h+"</div>";
}
function chips(k,opts,cur){return '<div class="chips">'+opts.map(function(o){return '<button class="chip'+(String(cur)===String(o[0])?" on":"")+'" data-act="set" data-k="'+k+'" data-v="'+o[0]+'">'+o[1]+"</button>"}).join("")+"</div>"}
function tgl(k,on,label,desc){return '<div class="trow" data-act="tgl" data-k="'+k+'"><div class="tt"><b>'+label+"</b>"+(desc?"<small>"+desc+"</small>":"")+'</div><span class="sw2'+(on?" on":"")+'"><i></i></span></div>'}

/* ---------- экраны ---------- */
var V={};
function offList(){
  var tr=Object.keys(OFF).map(function(i){return OFF[i]});
  if(!tr.length)return '<div class="empty">'+I("cloud")+'<p>Здесь будут скачанные треки</p><small>Открой трек и нажми «Скачать для офлайна». Он будет играть и без интернета.</small></div>';
  return '<div class="rowh"><span class="lab">Скачано: '+tr.length+"</span></div>"+allBtn(tr)+tlist(tr,"off");
}
V.music=async function(){
  var d=await api("/api/me");S.me=d.user;S.d=d;
  var h='<a class="diagw" href="'+EDIT+'" target="_blank" rel="noopener"><span class="in">'+GH+"<span>Редактор · GitHub</span></span></a>";
  h+='<p class="hint center">Нужно отредактировать или обрезать музыку? Жми кнопку</p>';
  h+='<div class="seg">'+[["tracks","Мои треки"],["pls","Плейлисты"],["off","Офлайн"]].map(function(x){return '<button class="'+(S.sub===x[0]?"on":"")+'" data-act="sub" data-v="'+x[0]+'">'+x[1]+"</button>"}).join("")+"</div>";
  if(S.sub==="pls"){
    h+='<div class="btns"><button class="btn" data-act="newpl">'+I("plus")+' Создать</button><button class="btn sec" data-act="openimport">'+I("import")+" Импорт</button></div>"+'<h3 class="lab">Мои плейлисты</h3>'+pllist(d.playlists)+'<h3 class="lab">Сохранённые</h3>'+pllist(d.saved);
  }else if(S.sub==="off"){
    h+=offList();
  }else{
    h+='<div class="seg upseg"><button class="'+(S.upPub?"on":"")+'" data-act="uppub" data-v="1">'+I("globe")+' В ленту</button><button class="'+(S.upPub?"":"on")+'" data-act="uppub" data-v="0">'+I("lock")+' Для себя</button></div><button class="btn" data-act="pickaudio">'+I("upload")+' Добавить аудио (mp3 / mp4)</button><div class="up" id="upbar"><i></i></div><div class="hint" id="uptxt">'+upHint()+'</div><div class="err" id="uperr"></div>'+tlist(d.tracks,"own");
  }
  return h;
};
V.chats=async function(){
  var d=await api("/api/chats");
  var h='<button class="btn" data-act="newchat">'+I("chatplus")+" Новое сообщение</button>";
  if(!d.chats.length)return h+'<div class="empty">'+I("chat")+"<p>Пока нет сообщений</p><small>Найди друга и напиши первым</small></div>";
  return h+d.chats.map(function(c){var u=c.user;
    return '<div class="row crow" data-act="openchat" data-id="'+esc(u.name)+'"><div class="av">'+avaInner(u)+'<span class="dot pd'+(u.online?"":" off")+'"></span></div><div class="meta"><b>'+esc(u.display||u.name)+"</b><small>"+(c.last.mine?"Ты: ":"")+esc(c.last.text)+'</small></div><div class="cmt"><small>'+hhmm(c.last.t)+"</small>"+(c.unread?'<span class="bdg">'+c.unread+"</span>":"")+"</div></div>"}).join("");
};
V.find=async function(){
  return backBtn("chatsback")+'<div class="card"><h2>Кому написать?</h2><div class="sbox2">'+I("search")+'<input id="q" placeholder="Ник друга" autocomplete="off" autocapitalize="off"></div><div id="sres"><p class="hint">Начни вводить ник</p></div></div>';
};
V.create=async function(){
  return backBtn()+'<div class="card"><h2>Новый плейлист</h2>'+
  '<div class="plcov"><div class="cv big" id="plcp">'+cov(S.plCover)+'</div><div><button class="btn sec sm" data-act="pickplcover">'+I("img")+' Обложка</button><small class="hint" style="display:block;margin-top:6px">Необязательно</small></div></div>'+
  '<label class="l lab">Название</label><input id="plName" maxlength="60" placeholder="Например: Ночной драйв">'+
  '<label class="l lab">Описание</label><textarea id="plDesc" maxlength="300" placeholder="О чём этот плейлист"></textarea>'+
  '<label class="l lab">Ссылка (по желанию)</label><input id="plLink" placeholder="https://...">'+
  '<div class="err" id="cerr"></div><button class="btn" data-act="mkpl">Создать и добавить треки</button></div>';
};
V.pladd=async function(id){
  var d=await api("/api/playlist?id="+enc(id));S.plIn={};d.tracks.forEach(function(t){S.plIn[t.id]=1});
  var tr=await api("/api/tracks?q=");
  return '<div class="card"><h2>Добавить в «'+esc(d.playlist.name)+'»</h2><div class="sbox2">'+I("search")+'<input id="ptq" placeholder="Найти трек, исполнителя или автора" autocomplete="off"></div></div><div id="plres">'+pickRows(tr.tracks)+'</div><button class="btn" data-act="plopen" data-id="'+esc(id)+'" style="position:sticky;bottom:96px">Готово</button>';
};
function pickRows(tr){
  if(!tr.length)return '<p class="hint center">Ничего не найдено</p>';
  return tr.map(function(t){T[t.id]=t;var on=!!S.plIn[t.id];return '<div class="row" data-act="pltoggle" data-id="'+esc(t.id)+'"><div class="cv">'+cov(t.cover)+'</div><div class="meta"><b>'+esc(t.title)+"</b><small>"+esc(artOf(t))+" · @"+esc(t.owner)+'</small></div><span class="addb'+(on?" on":"")+'">'+I(on?"check":"plus")+"</span></div>"}).join("");
}
V.profile=async function(){
  var d=await api("/api/me");S.me=d.user;S.d=d;var u=d.user;var h=profCard(u,true);
  if(S.edit){
    h+='<div class="card"><h3 class="lab" style="margin-top:0">Редактирование</h3><div class="btns"><button class="btn sec" data-act="pickava">'+I("img")+' Аватарка</button><button class="btn sec" data-act="pickban">'+I("img")+' Баннер</button></div>'+
    '<label class="l lab">Имя</label><input id="eName" maxlength="30" value="'+esc(u.display||"")+'">'+
    '<label class="l lab">О себе</label><textarea id="eBio" maxlength="400" placeholder="Что умеешь, что любишь, чего хочешь">'+esc(u.bio||"")+"</textarea>"+
    '<label class="l lab">Статус</label><div class="chips">'+STAT.map(function(s){return '<button class="chip'+(u.status===s?" on":"")+'" data-act="stat" data-v="'+esc(s)+'">'+esc(s)+"</button>"}).join("")+"</div>"+
    '<input id="eStat" maxlength="40" placeholder="Или свой статус" value="'+esc(u.status||"")+'">'+
    '<label class="l lab">Любимый трек в профиле</label><select id="ePin"><option value="">— не выбран —</option>'+d.tracks.map(function(t){return '<option value="'+esc(t.id)+'"'+((u.pin&&u.pin.id===t.id)?" selected":"")+">"+esc(t.title)+"</option>"}).join("")+"</select>"+
    '<label class="l lab">Цвет твоего профиля (его увидят другие)</label>'+swatches("pacc",S.pacc,true,"pcol")+
    socForm(u)+'<div class="btns"><button class="btn" data-act="saveprof">Сохранить</button><button class="btn sec" data-act="canceledit">Отмена</button></div></div>';
  }
  h+=recentCard(d.recent,"Недавно слушал");
  h+='<div class="card"><h3 class="lab" style="margin-top:0">Мои плейлисты</h3>'+pllist(d.playlists)+"</div>";
  return h;
};
var ADM={},ADM_TAGS=["Владелец","Разработчик","Модератор","VIP","Тестер"];
function admRow(u){
  ADM[u.name.toLowerCase()]=u;
  var sel=S.asel===u.name.toLowerCase();
  var h='<div class="arow'+(sel?" open":"")+'"><div class="row" data-act="admsel" data-id="'+esc(u.name)+'"><div class="av">'+avaInner(u)+'</div><div class="meta"><b>'+esc(u.display)+(u.admin?" ★":"")+"</b><small>@"+esc(u.name)+" · "+u.tracks+" тр."+(u.private?" · закрытый":"")+(u.banned?" · ЗАБЛОКИРОВАН":"")+'</small></div><span class="dot'+(u.online?"":" off")+'"></span></div>';
  if(sel){
    h+='<div class="adet"><div class="lab">Бейджи</div><div class="pills">'+(u.tags.length?u.tags.map(function(t,i){return tagPill(t,i,' data-act="admtagdel" data-id="'+esc(u.name)+'" data-v="'+esc(t)+'"')}).join(""):'<small class="mut">Пока нет</small>')+"</div>"+
    '<div class="chips">'+ADM_TAGS.filter(function(t){return u.tags.indexOf(t)<0}).map(function(t){return '<button class="chip" data-act="admtagadd" data-id="'+esc(u.name)+'" data-v="'+esc(t)+'">+ '+esc(t)+"</button>"}).join("")+"</div>"+
    '<div class="atg"><input id="atag" maxlength="20" placeholder="Свой бейдж (до 20 символов)"><button class="btn sm" data-act="admtagcustom" data-id="'+esc(u.name)+'">Выдать</button></div>'+
    '<div class="btns"><button class="btn sec" data-act="openuser" data-id="'+esc(u.name)+'">Профиль</button>'+(u.admin?"":'<button class="btn sec" data-act="admimp" data-id="'+esc(u.name)+'">Войти как</button><button class="btn '+(u.banned?"sec":"red")+'" data-act="admban" data-id="'+esc(u.name)+'" data-v="'+(u.banned?"0":"1")+'">'+(u.banned?"Разблокировать":"Заблокировать")+"</button>")+"</div></div>";
  }
  return h+"</div>";
}
async function userView(name){
  var d=await api("/api/user?name="+enc(name));var u=d.user;
  var h=backBtn()+profCard(u,false,true);
  if(!u.locked){
    h+=recentCard(d.recent,"Недавно слушает");
    h+='<div class="card"><h3 class="lab" style="margin-top:0">Плейлисты</h3>'+pllist(d.playlists)+'<h3 class="lab">Треки</h3>'+tlist(d.tracks,"u")+"</div>";
  }
  return h;
}
async function plView(id,guest){
  var d=await api("/api/playlist?id="+enc(id));var p=d.playlist;var mine=!!(S.me&&p.owner===S.me.name);
  var ids=d.tracks.map(function(t){return t.id});
  var h=guest?"":backBtn();
  if(mine&&S.pledit){
    if(S.plInit!==p.id){S.plInit=p.id;S.plCover=p.own_cover?p.cover:""}
    return h+'<div class="card"><h2>Изменить плейлист</h2><div class="plcov"><div class="cv big" id="plcp">'+cov(S.plCover)+'</div><div><button class="btn sec sm" data-act="pickplcover">'+I("img")+' Обложка</button>'+(S.plCover?'<button class="btn sec sm" data-act="clrplcover" style="margin-top:8px">Убрать</button>':"")+"</div></div>"+
    '<label class="l lab">Название</label><input id="plName" maxlength="60" value="'+esc(p.name)+'">'+
    '<label class="l lab">Описание</label><textarea id="plDesc" maxlength="300">'+esc(p.desc)+"</textarea>"+
    '<label class="l lab">Ссылка</label><input id="plLink" placeholder="https://..." value="'+esc(p.link)+'">'+
    '<div class="err" id="cerr"></div><div class="btns"><button class="btn" data-act="plsave" data-id="'+esc(p.id)+'">Сохранить</button><button class="btn sec" data-act="plcancel">Отмена</button></div></div>';
  }
  h+='<div class="card plhero">'+plMosaic(p,"big")+'<div class="plkind">Плейлист</div><h2 class="pltitle">'+esc(p.name)+"</h2>"+
  (p.fav?"":'<div class="plown" data-act="openuser" data-id="'+esc(p.owner)+'"><div class="av xs">'+avaInner({avatar:p.owner_avatar})+"</div><b>"+esc(p.owner_display)+"</b></div>")+
  plStats(p,true)+(p.desc?'<p class="pldesc">'+esc(p.desc)+"</p>":"")+
  '<div class="plbtns"><button class="btn" id="plplaybtn" data-act="plplay" data-id="'+esc(p.id)+'" data-list="'+esc(ids.join(","))+'">'+I("play")+' Слушать</button><button class="btn sec rnd" data-act="plshuf" data-id="'+esc(p.id)+'" data-list="'+esc(ids.join(","))+'" aria-label="Вперемешку">'+I("shuffle")+"</button></div>"+
  (p.fav?"":'<button class="btn sec" data-act="copylink" data-id="'+esc(p.id)+'">'+I("link")+" Скопировать ссылку</button>");
  if(mine&&p.fav)h+="";else if(mine)h+='<div class="btns"><button class="btn sec" data-act="pledit">'+I("edit")+' Изменить</button><button class="btn sec" data-act="pladdopen" data-id="'+esc(p.id)+'">'+I("plus")+' Треки</button><button class="btn red" data-act="delpl" data-id="'+esc(p.id)+'">'+I("trash")+"</button></div>";
  else if(guest)h+='<button class="btn sec" data-act="gologin">Войти, чтобы сохранить</button>';
  else h+='<div class="btns"><button class="btn sec" data-act="savepl" data-id="'+esc(p.id)+'">'+I("bookmark")+(d.saved?" Убрать из моих":" Сохранить себе")+"</button>"+(canOff?'<button class="btn sec" data-act="offpl" data-list="'+esc(ids.join(","))+'">'+I("cloud")+" Офлайн</button>":"")+"</div>";
  if(mine&&canOff)h+='<button class="btn sec" data-act="offpl" data-list="'+esc(ids.join(","))+'">'+I("cloud")+" Скачать для офлайна</button>";
  if(p.link&&/^https?:\/\//i.test(p.link))h+='<a class="btn sec" href="'+esc(p.link)+'" target="_blank" rel="noopener">'+I("globe")+" Ссылка плейлиста</a>";
  h+='</div><div class="card">'+(ids.length?tlist(d.tracks,mine?"plmine":""):'<p class="hint center">В плейлисте пока нет музыки'+(mine?'. Нажми «Треки», чтобы добавить.':"")+"</p>")+"</div>";
  h+=plExtra(d,p,mine,guest);
  return h;
}


function ucard(u,act,showMsg){
  return '<div class="ucard" data-act="'+act+'" data-id="'+esc(u.name)+'"><div class="ub"'+(u.banner?' style="background-image:url(\''+esc(u.banner)+'\')"':"")+'></div><div class="uin"><div class="av lg">'+avaInner(u)+'<span class="dot pd'+(u.online?"":" off")+'"></span></div><div class="meta"><b>'+esc(u.display||u.name)+"</b><small>@"+esc(u.name)+(u.status?" · "+esc(u.status):"")+"</small>"+
  ((u.tags&&u.tags.length)?'<div class="pills tiny">'+u.tags.slice(0,2).map(function(t,i){return tagPill(t,i)}).join("")+"</div>":"")+"</div>"+
  (showMsg?'<button class="ib msgb" data-act="openchat" data-id="'+esc(u.name)+'">'+I("chatplus")+"</button>":"")+"</div></div>";
}
function userRows(users,act){
  return users.length?users.map(function(u){return ucard(u,act,act==="openuser")}).join(""):'<div class="empty">'+I("search")+"<p>Никого не нашли</p><small>Проверь ник: ищем по нику и имени</small></div>";
}
function peopleStrip(users){
  if(!users.length)return "";
  return '<h3 class="lab" style="margin:4px 4px 2px">Люди</h3><div class="people">'+users.map(function(u){return '<div class="pbub" data-act="openuser" data-id="'+esc(u.name)+'"><div class="av lg">'+avaInner(u)+'<span class="dot pd'+(u.online?"":" off")+'"></span></div><small>'+esc(u.display||u.name)+"</small></div>"}).join("")+"</div>";
}
/* ---------- лента: посты и комментарии ---------- */
function fxAva(au,cls){return au?'<div class="av '+(cls||"")+'" data-act="openuser" data-id="'+esc(au.name)+'">'+avaInner(au)+"</div>":'<div class="av anonav '+(cls||"")+'">'+I("eyeoff")+"</div>"}
function postCard(p,full,ids,i){
  var t=p.track,au=p.author;
  var h='<div class="card fx"><div class="fx-head">'+fxAva(au)+'<div class="meta"><b>'+(au?esc(au.display):"Аноним")+(au&&p.anon?' <span class="fx-tag">'+I("eyeoff")+"для других аноним</span>":"")+"</b><small>"+(au?"@"+esc(au.name)+" · ":"")+ago(p.created)+"</small></div>"+(p.can_del?'<button class="ib" data-act="postdel" data-id="'+esc(p.id)+'">'+I("trash")+"</button>":"")+"</div>";
  h+=trow(t,ids||[t.id],i||0,"u");
  if(p.text)h+='<p class="fx-cap">'+esc(p.text)+"</p>";
  if(!full){
    if(p.comments.length)h+='<div class="fx-pre">'+p.comments.map(function(c){return "<div><b>"+esc(c.display)+"</b>"+esc(c.text)+"</div>"}).join("")+"</div>";
    h+='<div class="fx-foot"><button class="btn sec sm" data-act="openpost" data-id="'+esc(p.id)+'">'+I("chat")+" "+(p.ncom?"Комментарии · "+p.ncom:"Написать комментарий")+"</button></div>";
  }
  return h+"</div>";
}
function cmtRow(p,c){
  var who=c.user?' data-act="openuser" data-id="'+esc(c.user)+'"':"";
  return '<div class="cmr"><div class="av"'+who+">"+avaInner(c)+'</div><div class="cmb"><div class="cmh"><b'+who+">"+esc(c.display)+"</b>"+(c.op?'<span class="fx-op">автор</span>':"")+"<small>"+ago(c.t)+'</small></div><div class="cmx">'+esc(c.text)+"</div></div>"+(c.can_del?'<button class="ib" data-act="cmtdel" data-id="'+esc(p.id)+'" data-v="'+esc(c.id)+'">'+I("x")+"</button>":"")+"</div>";
}
V.feed=async function(){
  var pl=S.sq==="pls";
  var r=await Promise.all([api("/api/feed"),api("/api/search?q="),pl?api("/api/playlists?q="):null]),d=r[0];
  var ids=d.posts.map(function(p){return p.track.id});
  var h='<div class="seg sqs">'+[["people","Люди"],["pls","Плейлисты"]].map(function(x){return '<button class="'+((pl?"pls":"people")===x[0]?"on":"")+'" data-act="sq" data-v="'+x[0]+'">'+x[1]+"</button>"}).join("")+'</div><div class="card sbox">'+I("search")+'<input id="q" placeholder="'+(pl?"Найти плейлист или автора":"Найти друга по нику")+'" autocomplete="off" autocapitalize="off"></div>';
  if(pl)return h+'<div id="sres"><h3 class="lab" style="margin:4px 4px 6px">Популярные плейлисты</h3>'+pllist(r[2].playlists)+'</div><div id="pplbox"></div>';
  return h+'<div id="sres"></div><div id="pplbox">'+peopleStrip(r[1].users)+"</div>"+
  '<button class="btn" data-act="newpost">'+I("plus")+" Поделиться треком</button>"+
  '<h3 class="lab" style="margin-top:6px">Лента</h3>'+
  (d.posts.length?d.posts.map(function(p,i){return postCard(p,false,ids,i)}).join(""):'<div class="empty">'+I("feed")+"<p>В ленте пока тихо</p><small>Поделись треком и напиши, что о нём думаешь</small></div>")+
  (d.tracks.length?'<h3 class="lab">Новые треки</h3>'+allBtn(d.tracks)+tlist(d.tracks,"feed"):"")+
  '<h3 class="lab">Новые плейлисты</h3>'+pllist(d.playlists);
};
V.post=async function(id){
  var d=await api("/api/post?id="+enc(id)),p=d.post;
  return backBtn()+postCard(p,true)+'<h3 class="lab">Комментарии · '+p.ncom+'</h3><div class="card">'+(p.comments.length?p.comments.map(function(c){return cmtRow(p,c)}).join(""):'<p class="hint center" style="margin:6px 0">Пока никто не написал. Начни первым</p>')+"</div>"+
  '<div class="card"><textarea id="cmtIn" maxlength="300" rows="2" placeholder="Написать комментарий…"></textarea><button class="btn" data-act="cmtsend" data-id="'+esc(p.id)+'" style="margin-bottom:0">'+I("send")+" Отправить</button></div>";
};
function npInfo(an){return an?"<b>Анонимно.</b> В ленте вместо ника будет «Аноним» и скрытая аватарка. Пока пост в ленте, этот трек не показывается в твоём профиле и в поиске. Комментировать смогут все, а ты в комментариях будешь отмечен как «Автор» без имени.":"<b>С именем.</b> В посте будут твоя аватарка и ник: по ним люди откроют твой профиль, познакомятся и смогут написать тебе."}
V.newpost=async function(){
  var d=await api("/api/me"),tr=d.tracks.filter(function(t){return !t.private&&!t.ghost}),np=S.np||(S.np={track:"",anon:false,text:""});
  var h=backBtn()+'<h2 class="subt">Поделиться треком</h2>';
  if(!tr.length)return h+'<div class="empty">'+I("music")+"<p>Нет подходящих треков</p><small>Загрузи трек во вкладке «Музыка» (не «для себя»), и его можно будет добавить в ленту</small></div>";
  h+='<div class="card"><label class="l lab" style="margin-top:0">Трек</label><div class="mlist">'+tr.map(function(t){var on=np.track===t.id;return '<div class="row'+(on?" on":"")+'" data-act="npsel" data-id="'+esc(t.id)+'"><div class="cv">'+cov(t.cover)+'</div><div class="meta"><b>'+esc(t.title)+"</b><small>"+esc(artOf(t))+'</small></div><span class="npck">'+(on?I("check"):"")+"</span></div>"}).join("")+"</div>"+
  '<label class="l lab">Твоё мнение о треке</label><textarea id="npText" maxlength="500" placeholder="Что думаешь? Почему стоит послушать?">'+esc(np.text||"")+"</textarea>"+
  '<label class="l lab">Как показать автора</label><div class="chips"><button class="chip'+(np.anon?"":" on")+'" data-act="npanon" data-v="0">Показать моё имя</button><button class="chip'+(np.anon?" on":"")+'" data-act="npanon" data-v="1">Анонимно</button></div><div class="info" id="npinfo" style="margin-top:12px">'+npInfo(np.anon)+"</div>"+
  '<button class="btn" data-act="npgo" style="margin:14px 0 0">'+I("send")+" Опубликовать в ленте</button></div>";
  return h;
};
/* ---------- админ-панель ---------- */
function admPost(p){var t=p.track,au=p.author;return '<div class="row noh"><div class="cv">'+cov(t.cover)+'</div><div class="meta"><b>'+esc(t.title)+"</b><small>"+(au?"@"+esc(au.name):"")+(p.anon?" · аноним":"")+" · комм.: "+p.ncom+'</small></div><button class="ib" data-act="admpostdel" data-id="'+esc(p.id)+'">'+I("x")+'</button><button class="ib" data-act="admtrackdel" data-id="'+esc(t.id)+'">'+I("trash")+"</button></div>"}
function admTrack(t){return '<div class="row noh"><div class="cv">'+cov(t.cover)+'</div><div class="meta"><b>'+esc(t.title)+"</b><small>@"+esc(t.owner)+(t.private?" · для себя":"")+(t.posted?" · в ленте":"")+'</small></div><button class="ib" data-act="admtrackdel" data-id="'+esc(t.id)+'">'+I("trash")+"</button></div>"}
var WIPE={posts:["Убрать все посты из ленты","Все посты пропадут из ленты. Сами треки останутся у авторов."],tracks:["Удалить все треки","Удалятся все треки, посты ленты и аудиофайлы. Плейлисты останутся пустыми."],chats:["Удалить все сообщения","Удалятся все переписки у всех пользователей."],reports:["Очистить баг-репорты","Все баг-репорты будут удалены."],users:["Удалить всех пользователей","Удалятся все аккаунты кроме твоего, вместе с их треками, плейлистами, постами и перепиской."],all:["Очистить всё (чистый старт)","Останется только твой админ-аккаунт. Пользователи, треки, посты, плейлисты, сообщения, репорты и файлы будут удалены."]};
V.admin=async function(){
  var r=await Promise.all([api("/api/admin/stats"),api("/api/admin/users?q="+enc(S.aq||"")),api("/api/admin/reports"),api("/api/admin/posts"),api("/api/admin/tracks?q="+enc(S.atq||""))]),st=r[0],us=r[1],rp=r[2],po=r[3],tk=r[4];
  var tiles=[["Пользователей",st.users],["Сейчас онлайн",st.online],["Треков",st.tracks],["Постов в ленте",st.posts],["Плейлистов",st.playlists],["Сообщений",st.messages],["Баг-репортов",rp.total]];
  var h=backBtn()+'<h3 class="lab" style="margin-top:12px">Админ-панель</h3><div class="stats">'+tiles.map(function(t){return '<div class="stile"><b>'+t[1]+"</b><small>"+t[0]+"</small></div>"}).join("")+'</div><div class="card sbox">'+I("search")+'<input id="aq" placeholder="Найти пользователя" value="'+esc(S.aq||"")+'" autocomplete="off"></div><div id="alist">'+us.users.map(admRow).join("")+"</div>";
  h+='<h3 class="lab" style="margin-top:18px">Лента · посты</h3>'+(po.posts.length?'<div class="card">'+po.posts.map(admPost).join("")+"</div>":'<div class="empty">'+I("feed")+"<p>В ленте нет постов</p></div>");
  h+='<h3 class="lab" style="margin-top:18px">Все треки</h3><div class="card sbox">'+I("search")+'<input id="atq" placeholder="Найти трек или автора" value="'+esc(S.atq||"")+'" autocomplete="off"></div><div id="atlist">'+(tk.tracks.length?tk.tracks.map(admTrack).join(""):'<p class="hint center">Треков нет</p>')+"</div>";
  h+='<div class="rowh" style="margin-top:18px"><h3 class="lab" style="margin:0">Баг-репорты</h3>'+(rp.total?'<button class="btn red sm" data-act="repclear">Очистить</button>':"")+'</div><div id="replist">'+(rp.reports.length?rp.reports.map(repRow).join(""):'<div class="empty">'+I("check")+"<p>Репортов нет</p><small>Ошибки пользователей появятся здесь</small></div>")+"</div>";
  h+='<h3 class="lab" style="margin-top:18px">Очистка базы данных</h3><div class="card"><p class="hint" style="margin-top:0">Чтобы начать с чистого листа (например, перед загрузкой на GitHub). Твой админ-аккаунт остаётся всегда. Каждое действие подтверждается словом УДАЛИТЬ и необратимо.</p>'+Object.keys(WIPE).map(function(k,i,a){return '<button class="btn red" data-act="admwipe" data-v="'+k+'"'+(i===a.length-1?' style="margin-bottom:0"':"")+">"+WIPE[k][0]+"</button>"}).join("")+"</div>";
  return h;
};
function statsCard(st){
  var up=Q.slice(qi+1,qi+7).map(function(id){return T[id]}).filter(Boolean),mx=st.top.length?st.top[0].count:1;
  var h='<h3 class="lab">Статистика</h3><div class="card"><div class="stats3"><div class="stile"><b>'+st.plays+"</b><small>прослушиваний</small></div><div class=\"stile\"><b>"+st.minutes+"</b><small>минут музыки</small></div><div class=\"stile\"><b>"+st.uniq+"</b><small>разных треков</small></div></div><p class='hint' style='margin:4px 0 0'>Прослушивание засчитывается, когда трек реально играл около 25 секунд. Минуты считаются по факту.</p>";
  if(st.top.length)h+='<div class="lab sub">Чаще всего слушаешь</div>'+st.top.map(function(x,i){T[x.track.id]=x.track;return '<div class="trk" data-act="playpin" data-id="'+esc(x.track.id)+'"><span class="rk">'+(i+1)+'</span><div class="meta"><b>'+esc(x.track.title)+"</b><small>"+esc(artOf(x.track))+'</small><div class="bar"><i style="width:'+Math.max(6,Math.round(x.count/mx*100))+'%"></i></div></div><span class="cnt">'+x.count+"×</span></div>"}).join("");
  else h+='<p class="hint">Включай треки: здесь появится твоя статистика.</p>';
  if(st.artists.length)h+='<div class="lab sub">Любимые исполнители</div><div class="chips">'+st.artists.map(function(a){return '<span class="chip">'+esc(a.name)+" · "+a.count+"</span>"}).join("")+"</div>";
  h+='<div class="lab sub">Дальше в очереди</div>';
  h+=up.length?up.map(function(t,k){return '<div class="row" data-act="qjump" data-i="'+(qi+1+k)+'"><div class="cv" style="width:42px;height:42px;border-radius:12px">'+cov(t.cover)+'</div><div class="meta"><b>'+esc(t.title)+"</b><small>"+esc(artOf(t))+"</small></div></div>"}).join(""):'<p class="hint" style="margin:0">Запусти плейлист: здесь появится, что зазвучит дальше.</p>';
  return h+"</div>";
}
function bgCard(){
  var has=!!BG.kind;
  return '<h3 class="lab">Фон приложения</h3><div class="card"><p class="hint" style="margin-top:0">Поставь своё фото или видео на фон. Фон хранится только на этом устройстве.</p>'+
  '<div class="btns"><button class="btn sec" data-act="pickbg" data-v="image">'+I("img")+' Фото</button><button class="btn sec" data-act="pickbg" data-v="video">'+I("video")+" Видео</button></div>"+
  (has?'<div class="bgnow">'+I("check")+" Сейчас: "+(BG.kind==="video"?"видео":"фото")+'</div><label class="l lab">Затемнение</label><input type="range" id="bgdim" min="0" max="90" value="'+SET.bgdim+'">'+tgl("bgblur",!!SET.bgblur,"Размытие фона","Текст читается легче")+'<button class="btn red" data-act="bgremove" style="margin-bottom:0">Убрать фон</button>':"")+"</div>";
}
/* ---------- меню настроек (разделы как в iOS) ---------- */
var APPV="v6.2";
var LOCT={auto:1,bgblur:1,mpprog:1,mpcov:1,mpskip:1,seq:1,notif:1,xfade:1,mpprev:1};
function chev(){return '<span class="chev">'+I("chev")+"</span>"}
function smi(ic,label,v,val,act){return '<div class="mi" data-act="'+(act||"mnu")+'"'+(v?' data-v="'+v+'"':"")+">"+I(ic)+"<b>"+label+"</b>"+(val?'<span class="val">'+val+"</span>":"")+chev()+"</div>"}
function rng(k,mn,mx,val){return '<input type="range" data-sk="'+k+'" min="'+mn+'" max="'+mx+'" value="'+val+'" style="--pn:'+((val-mn)/(mx-mn)).toFixed(3)+'">'}
function mpPrev(){
  var t=T[Q[qi]],pl=!A.paused||WANT;
  var cv=t?cov(t.cover):'<span class="ni">'+I("music")+"</span>";
  var cvar=t&&t.cover?"url('"+esc(t.cover)+"')":"none";
  var at=' data-sz="'+(SET.mpsize||"m")+'" data-bg="'+(SET.mpbg||"glass")+'" data-sh="'+(SET.mpshape||"pill")+'" data-ft="'+(SET.mpfont||"sys")+'" data-bt="'+(SET.mpbt||"plain")+'" data-bp="'+(SET.mpbp||"bottom")+'"';
  var cl="mp mpprev"+(SET.mpprog===false?" m-np":"")+(SET.mpcov===false?" m-nc":"")+(SET.mpskip===false?" m-nk":"")+(SET.mpprev!==true?" m-npv":"");
  return '<div class="mpstage"><div class="'+cl+'"'+at+' style="--mcov:'+cvar+";--mop:"+((SET.mpop==null?94:SET.mpop)/100)+'"><div class="mbgl"></div><div class="mpg" style="width:42%"></div><div class="mrow"><div class="cv">'+cv+'</div><div class="meta"><b>'+esc(t?t.title:"Название трека")+"</b><small>"+esc(t?artOf(t):"Исполнитель")+'</small></div><button class="ib pv">'+I("prev")+'</button><button class="pb">'+I(pl?"pause":"play")+'</button><button class="ib nx">'+I("next")+"</button></div></div></div>";
}
function playerSet(){
  var h='<div class="card"><label class="l lab" style="margin-top:0">Предпросмотр</label>'+mpPrev()+'<p class="hint" style="margin:0">Так мини-плеер выглядит внизу экрана. Меняй настройки ниже: предпросмотр обновляется сразу.</p></div>';
  h+='<h3 class="lab">Размер</h3><div class="card">'+chips("mpsize",[["s","Компактный"],["m","Обычный"],["l","Крупный"]],SET.mpsize)+"</div>";
  h+='<h3 class="lab">Шрифт названия</h3><div class="card">'+chips("mpfont",[["sys","Чёткий"],["round","Мягкий"],["site","Фирменный"],["mono","Моно"]],SET.mpfont||"sys")+'<p class="hint" style="margin:0">«Чёткий» — обычный системный шрифт, он лучше всего читается на маленьком экране.</p></div>';
  h+='<h3 class="lab">Кнопки и полоска</h3><div class="card"><label class="l lab" style="margin-top:0">Вид кнопок</label>'+chips("mpbt",[["plain","Значки"],["circle","Круглые"]],SET.mpbt||"plain")+'<label class="l lab">Полоска прогресса</label>'+chips("mpbp",[["bottom","Снизу"],["top","Сверху"]],SET.mpbp||"bottom")+"</div>";
  h+='<h3 class="lab">Фон мини-плеера</h3><div class="card">'+chips("mpbg",[["glass","Стекло"],["solid","Сплошной"],["cover","Из обложки"],["grad","Градиент"],["none","Без фона"]],SET.mpbg)+
  '<label class="l lab">Прозрачность</label>'+rng("mpop",30,100,SET.mpop)+'<label class="l lab">Форма</label>'+chips("mpshape",[["pill","Круглая"],["soft","Мягкая"],["sq","Строгая"]],SET.mpshape)+"</div>";
  h+='<h3 class="lab">Что показывать</h3><div class="card">'+tgl("mpcov",SET.mpcov!==false,"Обложка","Картинка трека слева")+tgl("mpprev",SET.mpprev===true,"Кнопка «назад»","Перед кнопкой паузы")+tgl("mpskip",SET.mpskip!==false,"Кнопка «вперёд»","После кнопки паузы")+tgl("mpprog",SET.mpprog!==false,"Полоска прогресса","Показывает, сколько трека прослушано")+"</div>";
  h+='<h3 class="lab">Большой плеер</h3><div class="card"><label class="l lab" style="margin-top:0">Фон</label>'+chips("sbgm",[["cover","Размытая обложка"],["accent","Цвет темы"]],SET.sbgm)+tgl("seq",SET.seq!==false,"Эквалайзер","Анимированные столбики под названием")+"</div>";
  h+='<button class="btn sec" data-act="mpreset">Сбросить настройки плеера</button>';
  return h;
}
function blockedCard(us){
  return '<h3 class="lab">Заблокированные</h3><div class="card">'+(us.length?us.map(function(u){return '<div class="row noh"><div class="av">'+avaInner(u)+'</div><div class="meta"><b>'+esc(u.display||u.name)+"</b><small>@"+esc(u.name)+'</small></div><button class="btn sec sm" data-act="unblock" data-id="'+esc(u.name)+'">Разблокировать</button></div>'}).join(""):'<p class="hint center" style="margin:6px 0">Никого нет. Заблокировать можно в чате: «⋯» → «Заблокировать»</p>')+"</div>";
}
V.settings=async function(){
  var d=await api("/api/me");S.me=d.user;var u=d.user,nOff=Object.keys(OFF).length;
  var SZ={s:"Компактный",m:"Обычный",l:"Крупный"};
  var h='<h3 class="lab" style="margin-top:4px">Аккаунт</h3><div class="mgrp">'+smi("chart","Статистика","stats")+smi("lock","Безопасность","security")+smi("shield","Приватность","privacy")+(u.admin?smi("shield","Админ-панель","","","openadmin"):"")+"</div>";
  h+='<h3 class="lab">Приложение</h3><div class="mgrp">'+smi("palette","Оформление","look")+smi("gear","Основные","general")+smi("vol","Аудио","audio")+smi("mpl","Плеер","player",SZ[SET.mpsize]||"")+smi("db","Кэш","cache",nOff?String(nOff):"")+
  '<div class="mi" data-act="tgl" data-k="notif">'+I("bell")+"<b>Уведомления</b>"+'<span class="sw2'+(SET.notif!==false?" on":"")+'"><i></i></span></div>'+smi("info","Версия","about",APPV)+"</div>";
  h+='<div class="mgrp"><div class="mi red" data-act="logout">'+I("out")+"<b>Выйти</b></div></div>";
  h+='<p class="hint center">Ты вошёл как <b>@'+esc(u.name)+"</b></p>";
  return h;
};
V.sset=async function(id){
  if(BGREADY)await BGREADY;
  var TT={security:"Безопасность",privacy:"Приватность",look:"Оформление",general:"Основные",audio:"Аудио",player:"Плеер",cache:"Кэш",about:"Версия"};
  var d=await api("/api/me"),u=d.user;S.me=u;
  var h=backBtn();
  if(id!=="stats")h+='<h2 class="subt">'+(TT[id]||"Настройки")+"</h2>";
  if(id==="stats"){h+=statsCard(await api("/api/stats"))}
  else if(id==="security"){
    h+='<div class="card"><label class="l lab" style="margin-top:0">Старый пароль</label><input id="pwOld" type="password" autocomplete="current-password"><label class="l lab">Новый пароль</label><input id="pwNew" type="password" autocomplete="new-password" placeholder="минимум 6 символов"><div class="err" id="pwErr"></div><button class="btn" data-act="chpw" style="margin-bottom:0">Сменить пароль</button></div>';
    h+='<h3 class="lab">Сессии</h3><div class="mgrp">'+smi("phone","Мои устройства","","","opendevices")+'</div><p class="hint">Смотри, где открыт твой аккаунт, и закрывай чужие сессии.</p>';
  }
  else if(id==="privacy"){var bl=(await api("/api/blocks")).users;
    h+='<div class="card">'+tgl("show",u.show_listen!==false,"Показывать, что я слушаю","«Слушает сейчас» и «Недавно слушал» в профиле")+tgl("private",!!u.private,"Приватный профиль","Скрывает профиль от посторонних")+
    '<div class="info"><b>Что делает приватный профиль</b><ul><li><em>Скрывается:</em> «О себе», твои треки и плейлисты, любимый трек, что ты слушаешь. Твои треки пропадают из общей ленты.</li><li><em>Остаётся видно:</em> ник, аватарка, баннер, статус и «в сети».</li><li><em>Плюс:</em> писать тебе смогут только те, кому ты уже отвечал. Меньше спама.</li><li>Ссылки на плейлисты, которыми ты сам поделился, продолжают открываться.</li></ul></div></div>'+blockedCard(bl);
  }
  else if(id==="look"){
    h+='<div class="card"><label class="l lab" style="margin-top:0">Цветовая гамма</label>'+swatches("acc",SET.acc,false,"ccol")+
    '<p class="hint" style="margin-top:0">Выбери готовую тему или нажми на последний круг, чтобы задать свой цвет.</p>'+
    '<label class="l lab">Стиль оформления</label>'+chips("style",[["game","Неон"],["flat","Минимал"],["glass","Стекло"]],SET.style)+"</div>"+bgCard();
  }
  else if(id==="general"){
    h+='<h3 class="lab" style="margin-top:4px">Производительность</h3><div class="card">'+chips("perf",[["auto","Авто"],["full","Красота"],["lite","Лёгкий режим"]],SET.perf)+'<p class="hint" style="margin:0">Лёгкий режим отключает размытие и анимации. Нужен слабым телефонам.</p></div>';
    h+='<h3 class="lab">Приложение</h3><div class="card"><p class="hint" style="margin-top:0">Установи PiXeL Music на экран телефона: своя иконка, полноэкранный режим и быстрый запуск.</p><button class="btn" data-act="installapp" style="margin-bottom:0">'+I("download")+" "+(isApp()?"Приложение установлено":"Скачать приложение")+"</button></div>";
    h+='<h3 class="lab">Сброс</h3><div class="card"><p class="hint" style="margin-top:0">Вернёт цвета, стиль, звук и плеер к значениям по умолчанию. Аккаунт и треки не затронутся.</p><button class="btn red" data-act="setreset" style="margin-bottom:0">Сбросить настройки</button></div>';
  }
  else if(id==="audio"){
    h+='<div class="card">'+tgl("auto",SET.auto,"Автопереход","Сам включать следующий трек")+'<label class="l lab">Громкость</label><input type="range" id="vol" min="0" max="100" value="'+SET.vol+'"><p class="hint" style="margin:6px 0 0">Таймер сна находится в большом плеере, под кнопками управления.</p></div>';
    h+='<h3 class="lab">Плавный переход</h3><div class="card">'+tgl("xfade",SET.xfade!==false,"Плавное переключение","Конец трека тихо затихает, следующий так же тихо набирает громкость")+'<label class="l lab">Длительность: <span id="xfv">'+SET.xfadet+' сек</span></label>'+rng("xfadet",2,10,SET.xfadet)+'<p class="hint" style="margin:6px 0 0">Работает вместе с «Автопереходом» на обычных треках. Для треков из YouTube-импорта не действует.</p></div>';
  }
  else if(id==="player"){h+=playerSet()}
  else if(id==="cache"){
    var tr=Object.keys(OFF).map(function(k){return OFF[k]}),est=null;
    try{if(navigator.storage&&navigator.storage.estimate)est=await navigator.storage.estimate()}catch(e){}
    var used=est&&est.usage?est.usage/1048576:0;
    h+='<div class="card"><div class="stats3"><div class="stile"><b>'+tr.length+"</b><small>скачано треков</small></div><div class=\"stile\"><b>"+(used>=10?Math.round(used):used.toFixed(1))+"</b><small>МБ занято</small></div><div class=\"stile\"><b>"+(BG.kind?"1":"0")+"</b><small>свой фон</small></div></div><p class=\"hint\" style=\"margin:8px 0 0\">Скачанные треки играют без интернета. Фон приложения хранится только на этом устройстве.</p></div>";
    h+='<h3 class="lab">Скачанная музыка</h3>';
    if(tr.length)h+='<div class="card">'+tr.map(function(t){return '<div class="row noh"><div class="cv">'+cov(t.cover)+'</div><div class="meta"><b>'+esc(t.title)+"</b><small>"+esc(artOf(t))+'</small></div><button class="ib" data-act="offrm" data-id="'+esc(t.id)+'">'+I("trash")+"</button></div>"}).join("")+'<button class="btn red" data-act="offclear" style="margin-bottom:0">Удалить всю скачанную музыку</button></div>';
    else h+='<div class="empty">'+I("cloud")+"<p>Ничего не скачано</p><small>Открой трек в плеере и нажми «Скачать для офлайна»</small></div>";
    if(BG.kind)h+='<h3 class="lab">Фон</h3><div class="card"><button class="btn red" data-act="bgremove" style="margin:0">Убрать фон приложения</button></div>';
  }
  else if(id==="about"){
    h+='<div class="card center aboutc">'+logo(64)+'<div class="wm" style="margin-top:12px">PiXeL <b>Music</b></div><p class="hint" style="margin:6px 0 0">Версия '+APPV+'</p><p class="tagl">AI STUDIO PIXEL</p></div>';
    h+='<div class="card"><h3 class="lab" style="margin:0 0 6px">Добавить на экран</h3><p class="hint" style="margin-top:0">Сделай из сайта отдельную вкладку-приложение с иконкой на главном экране. Работает на любом телефоне и компьютере, подскажем шаги именно для твоего браузера.</p><button class="btn" data-act="installapp" style="margin-bottom:0">'+I("download")+" "+(isApp()?"Приложение установлено":"Добавить на главный экран")+'</button></div><div class="mgrp">'+smi("bug","Журнал ошибок","",LOG.length?String(LOG.length):"","logopen")+'</div><p class="hint">Что-то работает не так? В журнале видно, что сломалось, и можно отправить отчёт разработчику.</p>';
  }
  return h;
};
function sbgApply(t){var sb=$("#sbg");if(t.cover&&SET.sbgm!=="accent"){sb.classList.remove("nc");sb.style.backgroundImage='url("'+t.cover+'")'}else{sb.classList.add("nc");sb.style.backgroundImage="none"}}
function applyMini(){
  var list=[$("#mini")].concat([].slice.call(document.querySelectorAll(".mpprev")));
  list.forEach(function(m){
    if(!m)return;
    m.dataset.sz=SET.mpsize||"m";m.dataset.bg=SET.mpbg||"glass";m.dataset.sh=SET.mpshape||"pill";
    m.dataset.ft=SET.mpfont||"sys";m.dataset.bt=SET.mpbt||"plain";m.dataset.bp=SET.mpbp||"bottom";
    m.classList.toggle("m-np",SET.mpprog===false);m.classList.toggle("m-nc",SET.mpcov===false);m.classList.toggle("m-nk",SET.mpskip===false);m.classList.toggle("m-npv",SET.mpprev!==true);
    m.style.setProperty("--mop",String((SET.mpop==null?94:SET.mpop)/100));
  });
  document.body.classList.toggle("no-eq",SET.seq===false);
  var tt=T[Q[qi]];if(tt)sbgApply(tt);
}
function repRow(r){
  var open=S.arep===r.id,lines=r.text.trim().split("\n").filter(Boolean),last=lines[lines.length-1]||"";
  return '<div class="rep"><div class="row" data-act="repopen" data-id="'+esc(r.id)+'"><div class="meta"><b><span class="lk k-'+esc(r.kind)+'">'+esc(r.kind)+"</span>"+esc(last.slice(0,90))+"</b><small>"+(r.user?"@"+esc(r.user)+" · ":"")+ago(r.t)+"</small></div></div>"+
  (open?'<pre class="rtext">'+esc(r.text)+'</pre><button class="btn red sm" style="margin:8px" data-act="repdel" data-id="'+esc(r.id)+'">Удалить</button>':"")+"</div>";
}
async function refreshAdm(){var us=await api("/api/admin/users?q="+enc(S.aq||""));var b=$("#alist");if(b)b.innerHTML=us.users.map(admRow).join("");VC={}}
async function refreshRep(){var rp=await api("/api/admin/reports");var b=$("#replist");if(b)b.innerHTML=rp.reports.length?rp.reports.map(repRow).join(""):'<div class="empty">'+I("check")+"<p>Репортов нет</p></div>";VC={}}

/* ---------- импорт плейлистов из других сервисов ---------- */
var SVC={spotify:{n:"Spotify",re:/spotify\.(com|link)/i},soundcloud:{n:"SoundCloud",re:/soundcloud\.com/i},yandex:{n:"Яндекс Музыка",re:/music\.yandex\./i},ytm:{n:"YouTube Music",re:/youtube\.com|youtu\.be/i}};
function svcOf(u){for(var k in SVC)if(SVC[k].re.test(u))return k;return ""}
function svcLogo(k,px){
  px=px||40;var s='<svg width="'+px+'" height="'+px+'" viewBox="0 0 48 48">';
  if(k==="spotify")return s+'<circle cx="24" cy="24" r="22" fill="#1db954"/><g fill="none" stroke="#04140a" stroke-linecap="round"><path d="M12 18c8-3 17-2 24 2" stroke-width="3.4"/><path d="M13.5 25.5c7-2.2 14-1.6 20 1.6" stroke-width="3"/><path d="M15 32c6-1.6 11-1.2 16 1.3" stroke-width="2.6"/></g></svg>';
  if(k==="soundcloud")return s+'<rect width="48" height="48" rx="12" fill="#ff5500"/><g fill="#fff"><rect x="8" y="23" width="2.6" height="9" rx="1.3"/><rect x="13" y="20" width="2.6" height="12" rx="1.3"/><rect x="18" y="18" width="2.6" height="14" rx="1.3"/><path d="M23 32V19c2-1.6 4.4-2.3 7-2 4 .5 6.8 3.5 7 7.3 2.2-.2 4 1.3 4 3.3 0 2-1.7 3.4-3.7 3.4z"/></g></svg>';
  if(k==="yandex")return s+'<circle cx="24" cy="24" r="22" fill="#ffcc00"/><path d="M20 13v16.2a4.2 4.2 0 1 0 2.6 3.8V19l9-2v8.2a4.2 4.2 0 1 0 2.6 3.8V12z" fill="#111"/></svg>';
  if(k==="ytm")return s+'<circle cx="24" cy="24" r="22" fill="#ff0033"/><circle cx="24" cy="24" r="12" fill="none" stroke="#fff" stroke-width="2.6"/><path d="M21 18.5v11l9-5.5z" fill="#fff"/></svg>';
  return s+'<rect width="48" height="48" rx="12" fill="#3d7bff"/></svg>';
}
var IMP={d:null,sel:[],busy:false,liked:{},seq:0};
V.import=async function(){
  return backBtn()+'<div class="card"><h2>Импорт плейлиста</h2><p class="hint" style="margin-top:0">Вставь ссылку на публичный плейлист, и я покажу все треки из него.</p><div class="svcrow" id="svcrow">'+
  Object.keys(SVC).map(function(k){return '<div class="svc" data-k="'+k+'">'+svcLogo(k,44)+"<small>"+SVC[k].n+"</small></div>"}).join("")+"</div>"+
  '<div class="atg"><input id="impU" placeholder="Вставь ссылку на плейлист" autocomplete="off" autocapitalize="off" spellcheck="false"><button class="ib" data-act="imppaste" type="button">'+I("clip")+'</button></div><div class="err" id="impE"></div><button class="btn" data-act="impgo">'+I("search")+' Найти плейлист</button></div><div id="impres"></div>';
};
function svcHi(u){var k=svcOf(u),row=$("#svcrow");if(!row)return;row.classList.toggle("has",!!k);row.querySelectorAll(".svc").forEach(function(el){el.classList.toggle("on",el.dataset.k===k)})}
async function attSearch(){
  var q=($("#attq")&&$("#attq").value||"").trim(),b=$("#attres");if(!b)return;
  try{
    var d=await api("/api/tracks?q="+enc(q)),tr=d.tracks.filter(function(x){return x.url&&!x.private});
    b.innerHTML=tr.length?tr.map(function(x){T[x.id]=x;return '<div class="row" data-act="attpick" data-id="'+esc(x.id)+'"><div class="cv">'+cov(x.cover)+'</div><div class="meta"><b>'+esc(x.title)+"</b><small>"+esc(artOf(x))+" · @"+esc(x.owner)+"</small></div></div>"}).join(""):'<p class="hint center">В библиотеке такого трека пока нет. Загрузи свой файл на вкладке «Музыка» с пометкой «В ленту», потом привяжи его.</p>';
  }catch(e){b.innerHTML='<div class="err">'+esc(e.message)+"</div>"}
}
function attachModal(id){
  var t=T[id]||{};S.attId=id;
  showModal('<h3>Файл для трека</h3><p class="hint" style="margin-top:0">Выбери файл из библиотеки: он заменит онлайн-версию, будет играть в фоне и скачиваться для офлайна.</p><div class="sbox2">'+I("search")+'<input id="attq" value="'+esc(t.title||"")+'" autocomplete="off"></div><div class="mlist" id="attres"></div><button class="btn sec" data-act="closemodal">Закрыть</button>');
  attSearch();
}
function impImg(u){return u?'<img src="'+esc(u)+'" alt="" loading="lazy" referrerpolicy="no-referrer">':'<span class="ni">'+I("music")+"</span>"}
function impShow(d,keep){
  if(!keep){IMP.liked={};IMP.seq++}
  IMP.d=d;
  var tids=d.tracks.map(function(t,i){
    var id="tmp"+IMP.seq+"_"+i;
    T[id]={id:id,tmp:true,ghost:true,title:t.title,artist:t.artist||"",cover:t.cover||d.cover||"",dur:t.dur||0,src:d.service,yt:t.yt||"",owner:(S.me&&S.me.name)||"",created:0};
    return id;
  });
  var h='<div class="card"><div class="imph"><div class="cv big">'+impImg(d.cover)+'</div><div class="meta"><div class="svcb">'+svcLogo(d.service,22)+"<span>"+SVC[d.service].n+'</span></div><h2 style="margin:4px 0;white-space:normal">'+esc(d.title)+"</h2><small>"+(d.owner?esc(d.owner)+" · ":"")+d.tracks.length+" треков"+(d.skipped?" (ещё "+d.skipped+" не удалось прочитать)":"")+"</small>"+(d.note?'<small class="note">'+esc(d.note)+"</small>":"")+"</div></div>"+
  '<div class="btns" style="margin-top:12px"><button class="btn" data-act="impall">'+I("addlist")+' Добавить в плейлист</button><button class="btn sec" data-act="impfav">'+I("heart")+" В любимое</button></div></div>";
  h+='<div class="card">'+d.tracks.map(function(t,i){
    return '<div class="row" data-act="play" data-list="'+tids.join(",")+'" data-i="'+i+'"><div class="cv">'+impImg(t.cover||d.cover)+'<span class="eqm"><i></i><i></i><i></i></span></div><div class="meta"><b>'+esc(t.title)+"</b><small>"+esc(t.artist||"Неизвестный исполнитель")+"</small></div>"+(t.dur?'<span class="dur">'+fdur(t.dur)+"</span>":"")+'<button class="ib" data-act="impone" data-i="'+i+'" aria-label="В плейлист">'+I("addlist")+'</button><button class="ib heartb'+(IMP.liked[i]?" liked":"")+'" data-act="impfav1" data-i="'+i+'" aria-label="В любимое">'+I("heart")+"</button></div>"}).join("")+"</div>";
  $("#impres").innerHTML=h;markRows();
}
async function impGo(){
  var u=($("#impU").value||"").trim(),er=$("#impE");
  if(!u){er.textContent="Вставь ссылку на плейлист";return}
  if(IMP.busy)return;IMP.busy=true;er.textContent="";$("#impres").innerHTML=SKEL;
  try{impShow(await api("/api/import?url="+enc(u)))}catch(e){$("#impres").innerHTML="";er.innerHTML=esc(e.message)+(e.detail?'<pre class="edet">'+esc(e.detail)+"</pre>":"");logErr("import",e.message,e.detail||"")}
  IMP.busy=false;
}
async function impDest(list){
  IMP.sel=list;var d=await api("/api/me");
  var h='<h3>Куда добавить: '+list.length+(list.length===1?" трек":" треков")+'?</h3><div class="mlist"><div class="row" data-act="impto" data-v="new"><div class="cv"><span class="ni">'+I("plus")+'</span></div><div class="meta"><b>Новый плейлист</b><small>«'+esc(IMP.d.title)+'»</small></div></div><div class="row" data-act="impto" data-v="fav"><div class="cv"><span class="ni">'+I("heart")+'</span></div><div class="meta"><b>Любимое</b></div></div>';
  d.playlists.filter(function(p){return !p.fav}).forEach(function(p){h+='<div class="row" data-act="impto" data-v="'+esc(p.id)+'"><div class="cv">'+cov(p.cover)+'</div><div class="meta"><b>'+esc(p.name)+"</b><small>"+p.count+" треков</small></div></div>"});
  showModal(h+'</div><button class="btn sec" data-act="closemodal">Закрыть</button>');
}
async function impHeart(i,el){
  var t=IMP.d.tracks[i];
  if(IMP.liked[i]){
    var id=IMP.liked[i];el.classList.remove("liked");delete IMP.liked[i];
    try{var fr=await api("/api/fav",{body:{track:id}});if(fr.fav){IMP.liked[i]=id;el.classList.add("liked")}else toast("Трек убран")}
    catch(e){IMP.liked[i]=id;el.classList.add("liked");toast(e.message)}
    return;
  }
  el.classList.add("liked");
  try{var r=await api("/api/import/save",{body:{service:IMP.d.service,tracks:[t],to:"fav",name:IMP.d.title,cover:IMP.d.cover}});if(r.ids&&r.ids[0])IMP.liked[i]=r.ids[0];toast("Добавлено в любимое")}
  catch(e){el.classList.remove("liked");toast(e.message)}
}
async function impBulkFav(){
  var idx=[],arr=[];IMP.d.tracks.forEach(function(t,i){if(!IMP.liked[i]){idx.push(i);arr.push(t)}});
  if(!arr.length){toast("Всё уже в любимом");return}
  try{
    var r=await api("/api/import/save",{body:{service:IMP.d.service,tracks:arr,to:"fav",name:IMP.d.title,cover:IMP.d.cover}});
    (r.ids||[]).forEach(function(id,k){if(id)IMP.liked[idx[k]]=id});impShow(IMP.d,true);toast("В любимое добавлено: "+r.added);
  }catch(e){toast(e.message)}
}
async function impSave(to){
  $("#modal").classList.remove("open");
  try{
    var r=await api("/api/import/save",{body:{service:IMP.d.service,tracks:IMP.sel,to:to,name:IMP.d.title,cover:IMP.d.cover}});
    toast("Добавлено треков: "+r.added);
    if(to==="fav"&&r.ids){IMP.sel.forEach(function(tr,k){var i=IMP.d.tracks.indexOf(tr);if(i>=0&&r.ids[k])IMP.liked[i]=r.ids[k]});if(S.page&&S.page.t==="import")impShow(IMP.d,true)}
    if(to==="new"){S.page={t:"pl",id:r.playlist.id};render()}
  }catch(e){toast(e.message)}
}

function trk(n){n=Math.abs(n)%100;var d=n%10;return n>10&&n<20?'треков':d===1?'трек':d>=2&&d<=4?'трека':'треков'}

/* ---------- вход и регистрация ---------- */
var AU={mode:"login",msg:"",skipGuest:false,chk:null};
async function showAuth(){
  $("#tabs").style.display="none";$("#top").style.display="none";$("#mini").classList.remove("show");
  drawAuth();
}
function pwScore(p){var s=0;if(p.length>=6)s++;if(p.length>=10)s++;if(/[a-zA-Zа-яА-Я]/.test(p)&&/\d/.test(p))s++;if(/[^a-zA-Z0-9]/.test(p)||(/[a-z]/.test(p)&&/[A-Z]/.test(p)))s++;return s}
function drawAuth(){
  var reg=AU.mode==="reg",last=reg?"":(localStorage.getItem("px_nick")||"");
  var h='<div id="auth"><div class="hero">'+logo(76)+'<div class="wm">PiXeL <b>Music</b></div><p class="tagl">слушай · делись · чиль</p></div><div class="card">'+
  '<div class="seg" style="margin-top:0"><button class="'+(!reg?"on":"")+'" data-act="amode" data-v="login">Вход</button><button class="'+(reg?"on":"")+'" data-act="amode" data-v="reg">Регистрация</button></div>'+
  '<label class="l lab">Ник</label><div class="atg"><span>@</span><input id="aU" placeholder="например: chester" maxlength="24" autocapitalize="off" autocomplete="username" spellcheck="false" value="'+esc(last)+'"><i class="okm" id="aOk"></i></div>'+
  (reg?'<div class="hint nm" id="aNickMsg">3–24 символа: латиница, цифры, _ и .</div>':"")+
  '<label class="l lab">Пароль</label><div class="atg"><input id="aP" type="password" placeholder="'+(reg?"минимум 6 символов":"твой пароль")+'" autocomplete="'+(reg?"new-password":"current-password")+'"><button class="ib" data-act="eye" type="button">'+I("eye")+"</button></div>"+
  (reg?'<div class="pws"><i></i><i></i><i></i><i></i></div><div class="hint nm" id="aPwMsg">Придумай пароль</div><label class="l lab">Повтори пароль</label><div class="atg"><input id="aP2" type="password" placeholder="ещё раз" autocomplete="new-password"></div>':"")+
  '<div class="err" id="aE">'+esc(AU.msg||"")+'</div><button class="btn" data-act="'+(reg?"reg":"login")+'">'+(reg?"Создать аккаунт":"Войти")+"</button>"+
  (reg?'<p class="hint center" style="margin:6px 0 0">Один ник на человека. Для защиты от спама на устройство действует лимит аккаунтов.</p>':"")+
  "</div></div>";
  AU.msg="";
  $("#view").innerHTML=h;
}
function aErr(m){var e=$("#aE");if(e)e.textContent=m||""}
function authDone(r){
  localStorage.setItem("px_token",r.token);try{localStorage.setItem("px_nick",r.user.name)}catch(e){}
  S.me=r.user;VC={};POLL.mid=-1;
  $("#tabs").style.display="flex";$("#top").style.display="";S.tab="feed";S.page=null;S.edit=false;
  if(/^#p=/.test(location.hash))openHash();else go("feed");
  setTimeout(pollNow,600);
}
async function doAuth(kind){
  var u=($("#aU").value||"").trim(),p=$("#aP").value;
  if(!u||!p){aErr("Введи ник и пароль");return}
  if(kind==="register"){
    if(p!==$("#aP2").value){aErr("Пароли не совпадают");return}
  }
  try{authDone(await api("/api/"+kind,{body:{username:u,password:p}}))}catch(e){aErr(e.message)}
}
function checkNick(){
  var n=($("#aU").value||"").trim(),m=$("#aNickMsg"),ok=$("#aOk");if(!m)return;
  clearTimeout(AU.chk);
  if(!n){m.textContent="3–24 символа: латиница, цифры, _ и .";m.className="hint nm";ok.className="okm";return}
  AU.chk=setTimeout(async function(){
    try{var r=await api("/api/nick?n="+enc(n));m.textContent=r.msg;m.className="hint nm "+(r.ok?"good":"bad");ok.className="okm "+(r.ok?"good":"bad");ok.innerHTML=r.ok?I("check"):I("x")}catch(e){}
  },350);
}
function checkPw(){
  var p=$("#aP").value,bars=document.querySelectorAll(".pws i"),m=$("#aPwMsg");if(!m)return;
  var s=p?pwScore(p):0,names=["Придумай пароль","Слабый","Средний","Хороший","Отличный"];
  bars.forEach(function(b,i){b.className=i<s?"on s"+s:""});
  m.textContent=names[s];
  var p2=$("#aP2");if(p2&&p2.value&&p2.value!==p){m.textContent="Пароли пока не совпадают"}
}


/* ---------- офлайн-режим: скачанная музыка и работа без сети ---------- */
var OFF={};try{OFF=JSON.parse(localStorage.getItem("px_off")||"{}")}catch(e){OFF={}}
var canOff=("caches" in window);
var OFFLINE=false;
function offMeta(){try{localStorage.setItem("px_off",JSON.stringify(OFF))}catch(e){}}
async function offAdd(t){
  if(!canOff){toast("Скачивание недоступно в этом браузере");return false}
  if(!t.url){toast("Импортированные треки нельзя скачать для офлайна");return false}
  try{
    var c=await caches.open("pixel-audio"),r=await fetch(t.url);
    if(!r.ok)throw new Error("x");
    await c.put(t.url,r);
    if(t.cover){try{var r2=await fetch(t.cover);if(r2.ok)await c.put(t.cover,r2)}catch(e){}}
    OFF[t.id]={id:t.id,title:t.title,artist:t.artist,owner:t.owner,url:t.url,cover:t.cover,dur:t.dur,created:t.created};offMeta();return true;
  }catch(e){toast("Не удалось скачать трек");return false}
}
async function offDel(id){
  var t=OFF[id];if(!t)return;
  try{var c=await caches.open("pixel-audio");await c.delete(t.url);if(t.cover)await c.delete(t.cover)}catch(e){}
  delete OFF[id];offMeta();
}
function offlineView(){
  var tr=Object.keys(OFF).map(function(i){return OFF[i]});
  return '<div class="card offc">'+I("cloud")+'<div><b>Нет подключения</b><small>Доступна только скачанная музыка. Лента, сообщения и профиль вернутся, когда появится интернет.</small></div></div><h3 class="lab">Скачанная музыка</h3>'+
  (tr.length?allBtn(tr)+tlist(tr,"off"):'<div class="empty">'+I("cloud")+"<p>Пока ничего не скачано</p><small>Когда интернет будет, открой трек и нажми «Скачать для офлайна».</small></div>");
}
function setOnline(){if(!OFFLINE)return;OFFLINE=false;VC={};toast("Соединение восстановлено");render();pollNow()}
setInterval(function(){if(OFFLINE)fetch("/api/config",{cache:"no-store"}).then(function(r){if(r.ok)setOnline()}).catch(function(){})},5000);
window.addEventListener("online",function(){if(OFFLINE)fetch("/api/config",{cache:"no-store"}).then(function(r){if(r.ok)setOnline()}).catch(function(){})});

/* ---------- отрисовка ---------- */
var VC={},RID=0;
function vkey(){return S.page?S.page.t+":"+(S.page.id||"")+(S.pledit?":e":""):"tab:"+S.tab+":"+S.sub+(S.edit?":e":"")}
function typingIn(v){var a=document.activeElement;return !!(a&&v.contains(a)&&/^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName))}
var SKEL='<div class="skel"></div><div class="skel"></div><div class="skel"></div><div class="skel"></div>';
var GUESTCTA='<div class="card"><h3>Хочешь больше?</h3><p class="hint" style="margin-top:0">Войди или создай аккаунт: сохраняй плейлисты, добавляй музыку и общайся с друзьями.</p><button class="btn" data-act="gologin" style="margin-bottom:0">Войти или зарегистрироваться</button></div>';
function moveInd(first){
  var b=document.querySelector("#tabs button.on"),i=document.querySelector("#tabs .tind");if(!b||!i||!b.offsetWidth)return;
  if(first)i.style.transition="none";
  i.style.width=b.offsetWidth+"px";i.style.transform="translateX("+b.offsetLeft+"px)";
  if(first){void i.offsetWidth;i.style.transition=""}
}
async function render(){
  var rid=++RID,v=$("#view");
  if(!localStorage.getItem("px_token")){
    var gm=/^#p=([0-9a-f]+)$/.exec(location.hash);
    if(gm&&!AU.skipGuest){
      $("#tabs").style.display="none";$("#top").style.display="";
      try{var gh=await plView(gm[1],true);if(rid!==RID)return;v.innerHTML=gh+GUESTCTA;v.dataset.k="guest";return}catch(e){}
    }
    S.me=null;await showAuth();return;
  }
  var firstTabs=$("#tabs").style.display==="none";
  $("#tabs").style.display="flex";$("#top").style.display="";
  document.querySelectorAll("#tabs button").forEach(function(b){b.classList.toggle("on",b.dataset.tab===S.tab)});
  moveInd(firstTabs);
  var key=vkey();
  if(OFFLINE){v.innerHTML=offlineView();v.dataset.k="off";markRows();return}
  var cached=VC[key],changed=v.dataset.k!==key;
  if(changed){v.classList.remove("vin");void v.offsetWidth;v.classList.add("vin")}
  if(cached!==undefined){v.innerHTML=cached;v.dataset.k=key;markRows()}
  else if(changed){v.innerHTML=SKEL;v.dataset.k=key}
  try{
    var html;
    if(!ACC){var m0=await api("/api/me");S.me=m0.user}
    if(S.page){
      if(!S.me){var m=await api("/api/me");S.me=m.user}
      var t=S.page.t;
      html=t==="user"?await userView(S.page.id):t==="create"?await V.create():t==="find"?await V.find():t==="admin"?await V.admin():t==="pladd"?await V.pladd(S.page.id):t==="import"?await V.import():t==="devices"?await V.devices():t==="sset"?await V.sset(S.page.id):t==="post"?await V.post(S.page.id):t==="newpost"?await V.newpost():await plView(S.page.id);
    }else html=await V[S.tab]();
    if(rid!==RID)return;
    VC[key]=html;
    if(html!==cached&&(cached===undefined||!typingIn(v))){v.innerHTML=html;v.dataset.k=key}
    markRows();var v1=$("#vol");if(v1){v1.value=SET.vol;setRange(v1,SET.vol)}
  }catch(e){
    if(rid!==RID)return;
    if(e.status===0){return render()}
    if(e.status===401||e.banned){localStorage.removeItem("px_token");leaveAccount();VC={};AU.msg=e.banned?e.message:"";showAuth();return}
    v.innerHTML='<div class="card err">'+esc(e.message)+"</div>";v.dataset.k="";
  }
}
function go(tab){S.tab=tab;S.page=null;S.edit=false;S.pledit=false;render();window.scrollTo(0,0)}

/* ---------- сообщения ---------- */
var CH={with:null,last:0,ru:0,timer:null,day:"",busy:false,can:true,edit:null};
function dayLabel(d){var n=new Date(),y=new Date(Date.now()-86400000);if(d.toDateString()===n.toDateString())return "Сегодня";if(d.toDateString()===y.toDateString())return "Вчера";return p2(d.getDate())+"."+p2(d.getMonth()+1)+"."+d.getFullYear()}
function fitChat(){
  var c=$("#chat");
  if(window.visualViewport){c.style.height=window.visualViewport.height+"px";c.style.top=window.visualViewport.offsetTop+"px"}
  else{c.style.height="100%";c.style.top="0"}
  var b=$("#cmsgs");if(c.classList.contains("open"))b.scrollTop=b.scrollHeight;
}
if(window.visualViewport){visualViewport.addEventListener("resize",fitChat);visualViewport.addEventListener("scroll",fitChat)}
function paintChatHead(u){
  $("#cav").innerHTML=avaInner(u);$("#cname").textContent=u.display||u.name;
  var st=$("#cst");st.textContent=u.online?"в сети":"был(а) "+seenTxt(u.seen);st.classList.toggle("on",!!u.online);
}
var RXL=["❤️","👍","👎","😂","😮","😢","🔥","🎉"],MX=null,MXT=0;
function msgSig(m){return JSON.stringify([m.text,!!m.edited,m.rx||[],m.my||""])}
function rxHtml(m){return (m.rx||[]).map(function(r){return '<span class="rx'+(m.my===r.e?" me":"")+'" data-act="rxtoggle" data-v="'+r.e+'">'+r.e+(r.n>1?" "+r.n:"")+"</span>"}).join("")}
function paintMsg(el,m){
  el.querySelector(".mx").textContent=m.text;el.querySelector(".rxs").innerHTML=rxHtml(m);
  var ed=el.querySelector(".ed");if(ed)ed.style.display=m.edited?"":"none";
  el.dataset.my=m.my||"";el.dataset.sig=msgSig(m);
}
function appendMsg(m,anim){
  var box=$("#cmsgs");if(box.querySelector('[data-id="'+m.id+'"]'))return;
  var d=new Date(m.t*1000),day=d.toDateString();
  if(day!==CH.day){CH.day=day;box.insertAdjacentHTML("beforeend",'<div class="dsep"><span>'+dayLabel(d)+"</span></div>")}
  var rd=m.read||m.id<=CH.ru;
  var tick=m.mine?'<span class="tk'+(rd?" rd":"")+'">'+I(rd?"checks":"check")+"</span>":"";
  box.insertAdjacentHTML("beforeend",'<div class="msg '+(m.mine?"out":"in")+(anim?" pop":"")+'" data-id="'+m.id+'" data-my="'+esc(m.my||"")+'" data-sig="'+esc(msgSig(m))+'"><div class="mx">'+esc(m.text)+'</div><div class="rxs">'+rxHtml(m)+'</div><div class="mt"><span class="ed"'+(m.edited?"":' style="display:none"')+'>изм.</span><span>'+p2(d.getHours())+":"+p2(d.getMinutes())+"</span>"+tick+"</div></div>");
}
function syncMsgs(list,mid){
  if(!list)return;
  var box=$("#cmsgs"),ids={},min=list.length?list[0].id:0;
  list.forEach(function(m){ids[m.id]=1;var el=box.querySelector('.msg[data-id="'+m.id+'"]');if(el&&el.dataset.sig!==msgSig(m))paintMsg(el,m)});
  box.querySelectorAll(".msg").forEach(function(el){var id=+el.dataset.id;if(id>=min&&id<=mid&&!ids[id])el.remove()});
}
function closeMx(){$("#mctx").classList.remove("open");MX=null}
function openMsgMenu(el){
  if(!CH.with)return;
  var mine=el.classList.contains("out");
  MX={id:+el.dataset.id,mine:mine,text:el.querySelector(".mx").textContent,my:el.dataset.my||""};
  $("#mxrx").innerHTML=RXL.map(function(e){return '<button data-act="mxrx" data-v="'+e+'"'+(MX.my===e?' class="on"':"")+">"+e+"</button>"}).join("");
  var it='<div class="mx-it" data-act="mxcopy">'+I("copy")+"Копировать</div>";
  if(mine)it+='<div class="mx-it" data-act="mxedit">'+I("edit")+'Редактировать</div><div class="mx-it red" data-act="mxdel">'+I("trash")+"Удалить</div>";
  $("#mxmenu").innerHTML=it;
  $("#mctx").classList.add("open");MXT=Date.now();
  var bx=$("#mxbox"),r=el.getBoundingClientRect(),bw=bx.offsetWidth,bh=bx.offsetHeight,vw=window.innerWidth,vh=window.innerHeight;
  var left=mine?r.right-bw:r.left;left=Math.max(12,Math.min(vw-bw-12,left));
  var top=r.bottom+8;if(top+bh>vh-12)top=r.top-bh-8;top=Math.max(12,Math.min(vh-bh-12,top));
  bx.style.left=left+"px";bx.style.top=top+"px";
}
function startEdit(id,text){CH.edit=id;$("#cedbar").classList.add("on");$("#cedtxt").textContent=text.slice(0,90);var i=$("#cinp");i.value=text;autoGrow();i.focus()}
function cancelEdit(){CH.edit=null;var b=$("#cedbar");if(b)b.classList.remove("on");var i=$("#cinp");if(i){i.value="";autoGrow()}}
(function(){
  var tm=0,sx=0,sy=0,box=$("#cmsgs");
  function cancel(){clearTimeout(tm);tm=0}
  box.addEventListener("touchstart",function(e){
    var el=e.target.closest&&e.target.closest(".msg");if(!el||e.target.closest(".rx"))return;
    var t=e.touches[0];sx=t.clientX;sy=t.clientY;clearTimeout(tm);
    tm=setTimeout(function(){tm=0;if(navigator.vibrate){try{navigator.vibrate(18)}catch(x){}}openMsgMenu(el)},430);
  },{passive:true});
  box.addEventListener("touchmove",function(e){if(!tm)return;var t=e.touches[0];if(Math.abs(t.clientX-sx)>10||Math.abs(t.clientY-sy)>10)cancel()},{passive:true});
  box.addEventListener("touchend",cancel);box.addEventListener("touchcancel",cancel);
  box.addEventListener("contextmenu",function(e){var el=e.target.closest&&e.target.closest(".msg");if(!el)return;e.preventDefault();if(!$("#mctx").classList.contains("open")&&Date.now()-MXT>600)openMsgMenu(el)});
})();
function markRead(){
  document.querySelectorAll("#cmsgs .msg.out").forEach(function(el){
    if(+el.dataset.id<=CH.ru){var tk=el.querySelector(".tk");if(tk&&!tk.classList.contains("rd")){tk.classList.add("rd");tk.innerHTML=I("checks")}}
  });
}
async function loadChat(first){
  if(!CH.with||CH.busy)return;CH.busy=true;var w=CH.with;
  try{
    var d=await api("/api/chat?with="+enc(w)+"&after="+CH.last);
    if(w!==CH.with)return;
    paintChatHead(d.peer);CH.can=d.canSend;
    CH.iblock=!!d.iblock;
    $("#cbar").style.display=d.canSend?"flex":"none";
    $("#cunb").style.display=d.iblock?"block":"none";
    var note=$("#cnote");note.style.display=(d.canSend||d.iblock)?"none":"block";note.textContent=d.why||"";
    var box=$("#cmsgs"),near=first||box.scrollHeight-box.scrollTop-box.clientHeight<140;
    if(d.ru>CH.ru)CH.ru=d.ru;
    d.msgs.forEach(function(m){appendMsg(m,!first)});
    syncMsgs(d.sync,d.mid);
    markRead();
    if(d.msgs.length)CH.last=Math.max(CH.last,d.msgs[d.msgs.length-1].id);
    if(first&&!d.msgs.length&&d.canSend)box.insertAdjacentHTML("beforeend",'<div class="empty chatempty">'+I("chat")+"<p>Напиши первое сообщение</p></div>");
    if(d.msgs.length){var ce=box.querySelector(".chatempty");if(ce)ce.remove()}
    if(near)box.scrollTop=box.scrollHeight;
  }catch(e){if(e.status===404){toast("Пользователь не найден");closeChat()}}
  finally{CH.busy=false}
}
function openChat(nick){
  closeBanner();
  CH.with=nick;CH.last=0;CH.ru=0;CH.day="";CH.can=true;
  $("#cmsgs").innerHTML="";$("#cname").textContent=nick;$("#cst").textContent="";$("#cav").innerHTML=defAva();
  $("#cbar").style.display="flex";$("#cunb").style.display="none";$("#cnote").style.display="none";CH.iblock=false;$("#cinp").value="";autoGrow();
  $("#chat").classList.add("open");document.body.style.overflow="hidden";fitChat();
  clearInterval(CH.timer);loadChat(true);CH.timer=setInterval(function(){loadChat(false)},2500);
}
function closeChat(){
  clearInterval(CH.timer);CH.timer=null;CH.with=null;cancelEdit();closeMx();cmenuToggle(false);
  $("#chat").classList.remove("open");document.body.style.overflow=$("#sheet").classList.contains("open")?"hidden":"";
  if(S.tab==="chats"&&!S.page){VC={};render()}
  pollNow();
}
function autoGrow(){var i=$("#cinp");i.style.height="auto";i.style.height=Math.min(i.scrollHeight,110)+"px"}
async function sendMsg(){
  var inp=$("#cinp"),txt=inp.value.trim();
  if(!txt||!CH.with||!CH.can)return;
  if(CH.edit){var eid=CH.edit;try{var er=await api("/api/chat/edit",{body:{id:eid,text:txt}});var eel=$('#cmsgs .msg[data-id="'+eid+'"]');if(eel)paintMsg(eel,er.msg);cancelEdit()}catch(ee){toast(ee.message)}return}
  inp.value="";autoGrow();
  try{
    var r=await api("/api/chat/send",{body:{to:CH.with,text:txt}});
    var ce=$("#cmsgs .chatempty");if(ce)ce.remove();
    appendMsg(r.msg,true);CH.last=Math.max(CH.last,r.msg.id);
    var box=$("#cmsgs");box.scrollTop=box.scrollHeight;
  }catch(e){inp.value=txt;autoGrow();toast(e.message)}
}
/* уведомление о новом сообщении (выезжает сверху) */
var POLL={mid:-1,n:0},bannerT=null,bannerNick="";
function closeBanner(){clearTimeout(bannerT);$("#nbanner").classList.remove("show")}
function showBanner(m){
  if(SET.notif===false)return;
  bannerNick=m.from;$("#nbav").innerHTML=avaInner({avatar:m.avatar});$("#nbn").textContent=m.display||m.from;$("#nbm").textContent=m.text;
  var b=$("#nbanner");b.classList.remove("show");void b.offsetWidth;b.classList.add("show");
  clearTimeout(bannerT);bannerT=setTimeout(closeBanner,4800);
}
function setBadge(n){var b=$("#tbdg");if(!b)return;b.textContent=n>99?"99+":String(n);b.style.display=n>0?"flex":"none"}
async function pollNow(){
  if(!localStorage.getItem("px_token")||OFFLINE)return;
  try{
    var d=await api("/api/poll?after="+POLL.mid);
    var prev=POLL.mid;POLL.mid=d.mid;setBadge(d.unread);
    var fresh=d.msgs.filter(function(m){return !(CH.with&&CH.with.toLowerCase()===m.from.toLowerCase())});
    if(prev>=0&&fresh.length)showBanner(fresh[fresh.length-1]);
    if(prev>=0&&d.msgs.length&&S.tab==="chats"&&!S.page&&!CH.with){VC={};render()}
  }catch(e){}
}
setInterval(function(){if(document.hidden&&(++POLL.n%5))return;pollNow()},4000);
document.addEventListener("visibilitychange",function(){if(!document.hidden)pollNow()});

/* ---------- мои устройства ---------- */
Object.assign(ICONS,{
 phone:'<rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M11 18.5h2"/>',
 desktop:'<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>'
});
function fmtDate(t){var d=new Date(t*1000);return d.toLocaleDateString("ru-RU",{day:"numeric",month:"long"})+", "+p2(d.getHours())+":"+p2(d.getMinutes())}
function devCard(x){
  return '<div class="dev'+(x.current?" cur":"")+'"><div class="dic">'+I(x.kind==="desktop"?"desktop":"phone")+'</div><div class="meta"><b>'+esc(x.model||x.os)+(x.current?'<span class="curb">это устройство</span>':"")+"</b><small>"+esc(x.browser)+" · "+esc(x.os)+'</small><small class="dl">'+(x.online?'<i class="dot"></i>онлайн':"был(а) "+seenTxt(x.seen))+(x.ip?" · IP "+esc(x.ip):"")+"</small><small>Вход: "+fmtDate(x.t)+"</small></div>"+
  (x.current?"":'<button class="ib" data-act="devout" data-id="'+esc(x.sid)+'" aria-label="Выйти">'+I("out")+"</button>")+"</div>";
}
V.devices=async function(){
  var d=await api("/api/devices"),cur=d.devices.filter(function(x){return x.current}),others=d.devices.filter(function(x){return !x.current});
  var h=backBtn()+'<h3 class="lab" style="margin-top:12px">Мои устройства</h3><p class="hint" style="margin-top:0">Здесь все устройства, где открыт твой аккаунт. Если видишь незнакомое, закрой сессию и смени пароль в настройках.</p>';
  h+='<div class="lab sub">Это устройство</div>'+(cur.length?cur.map(devCard).join(""):'<p class="hint">Не удалось определить</p>');
  if(others.length)h+='<div class="lab sub">Другие устройства · '+others.length+"</div>"+others.map(devCard).join("")+'<button class="btn red" data-act="devall">'+I("out")+" Выйти на всех других</button>";
  else h+='<div class="empty">'+I("shield")+"<p>Других устройств нет</p><small>Твой аккаунт открыт только здесь</small></div>";
  return h;
};

/* ---------- фон приложения (фото или видео) ---------- */
var BG={kind:""},BGREADY=null;
/* ---------- настройки и фон привязаны к аккаунту ---------- */
var ACC="",PQ=false,prefT=null;
var DEFSET=Object.assign({acc:"#3d7bff",style:"game",perf:"auto",auto:true,vol:80,bgdim:55,bgblur:false},DMP);
function bgKey(){return "bg:"+ACC}
function schedPrefs(){
  clearTimeout(prefT);
  prefT=setTimeout(function(){
    if(!ACC||localStorage.getItem("px_admin_token"))return;
    api("/api/prefs",{body:{prefs:{acc:SET.acc,style:SET.style,perf:SET.perf,auto:SET.auto,vol:SET.vol,bgdim:SET.bgdim,bgblur:SET.bgblur,mpsize:SET.mpsize,mpbg:SET.mpbg,mpshape:SET.mpshape,mpop:SET.mpop,mpprog:SET.mpprog,mpcov:SET.mpcov,mpskip:SET.mpskip,sbgm:SET.sbgm,seq:SET.seq,notif:SET.notif,xfade:SET.xfade,xfadet:SET.xfadet,mpfont:SET.mpfont,mpbt:SET.mpbt,mpbp:SET.mpbp,mpprev:SET.mpprev}}}).catch(function(){});
  },900);
}
function ensureAccount(u){
  if(!u||ACC===u.name)return;
  ACC=u.name;
  Object.keys(DEFSET).forEach(function(k){SET[k]=(u.prefs&&u.prefs[k]!==undefined)?u.prefs[k]:(u.prefs?DEFSET[k]:SET[k])});
  if(!u.prefs)schedPrefs();
  PQ=true;applySet();PQ=false;
  BGREADY=bgLoad();
}
function leaveAccount(){
  ACC="";Object.keys(DEFSET).forEach(function(k){SET[k]=DEFSET[k]});
  PQ=true;applySet();PQ=false;bgClear();BGREADY=null;
}
function showImpBar(){
  var on=!!localStorage.getItem("px_admin_token"),b=$("#impbar");if(!b)return;
  b.classList.toggle("show",on);document.body.classList.toggle("imp",on);
  if(on)$("#impt").textContent="Ты в аккаунте @"+(localStorage.getItem("px_imp_name")||"?");
}
/* ---------- видимость новых треков ---------- */
S.upPub=localStorage.getItem("px_uppub")!=="0";
function upHint(){return S.upPub?"Новые треки увидят все в ленте":"Новые треки увидишь только ты"}
/* ---------- честная статистика прослушиваний ---------- */
var LT={id:null,dur:0,acc:0,lastT:0,counted:false,sent:0};
function ltNeed(){return LT.dur>0?Math.max(2,Math.min(25,Math.floor(LT.dur*.45))):25}
function ltStart(t){LT={id:t.id,dur:t.dur||0,acc:0,lastT:0,counted:false,sent:0}}
function ltSend(count){
  if(!LT.id||!localStorage.getItem("px_token")||localStorage.getItem("px_admin_token"))return;
  var sec=Math.floor(LT.acc-LT.sent);
  if(count)LT.counted=true;
  if(sec<=0&&!count)return;
  LT.sent+=sec;
  api("/api/listen",{body:{id:LT.id,sec:sec,count:!!count}}).catch(function(){});
}
function ltStep(){
  if(!LT.id||A.paused)return;
  var c=A.currentTime||0,d=c-LT.lastT;LT.lastT=c;
  if(d>0&&d<1.5)LT.acc+=d;
  if(!LT.counted&&LT.acc>=ltNeed())ltSend(true);
  else if(LT.acc-LT.sent>=60)ltSend(false);
}
function ltFlush(){
  if(!LT.id)return;
  if(!LT.counted&&LT.acc>=ltNeed())ltSend(true);else if(LT.acc-LT.sent>=3)ltSend(false);
}
document.addEventListener("visibilitychange",function(){if(document.hidden)ltFlush()});

function idbOpen(){return new Promise(function(res,rej){var r=indexedDB.open("pixel",1);r.onupgradeneeded=function(){r.result.createObjectStore("kv")};r.onsuccess=function(){res(r.result)};r.onerror=function(){rej(r.error)}})}
async function idbGet(k){try{var db=await idbOpen();return await new Promise(function(res){var q=db.transaction("kv").objectStore("kv").get(k);q.onsuccess=function(){res(q.result)};q.onerror=function(){res(null)}})}catch(e){return null}}
async function idbSet(k,v){var db=await idbOpen();return new Promise(function(res,rej){var t=db.transaction("kv","readwrite");t.objectStore("kv").put(v,k);t.oncomplete=function(){res()};t.onerror=function(){rej(t.error)}})}
async function idbDel(k){try{var db=await idbOpen();return await new Promise(function(res){var t=db.transaction("kv","readwrite");t.objectStore("kv").delete(k);t.oncomplete=function(){res()};t.onerror=function(){res()}})}catch(e){}}
function bgClear(){var m=$("#bgm");if(m){if(m.dataset.u)URL.revokeObjectURL(m.dataset.u);m.innerHTML="";m.dataset.u="";m.style.display="none"}document.documentElement.classList.remove("has-bg");BG.kind=""}
async function bgLoad(){
  var rec=await idbGet(bgKey());
  if(!rec||!rec.blob){bgClear();return}
  bgClear();var m=$("#bgm"),u=URL.createObjectURL(rec.blob);m.dataset.u=u;m.style.display="block";BG.kind=rec.kind;
  if(rec.kind==="video"){var v=document.createElement("video");v.src=u;v.muted=true;v.loop=true;v.playsInline=true;v.setAttribute("playsinline","");v.preload="auto";if(!document.body.classList.contains("lite")){v.autoplay=true;v.play().catch(function(){})}m.appendChild(v)}
  else{var i=new Image();i.src=u;i.alt="";m.appendChild(i)}
  document.documentElement.classList.add("has-bg");
}
async function bgSet(file){
  try{
    if(file.type.indexOf("video/")===0){
      if(file.size>60*1048576){toast("Видео слишком большое (максимум 60 МБ)");return}
      await idbSet(bgKey(),{kind:"video",blob:file});
    }else if(file.type.indexOf("image/")===0){
      await idbSet(bgKey(),{kind:"image",blob:await shrink(file,1600,.86)});
    }else{toast("Выбери фото или видео");return}
    await bgLoad();toast("Фон установлен");if(S.tab==="settings"&&(!S.page||S.page.t==="sset")){VC={};render()}
  }catch(e){toast("Не удалось сохранить фон")}
}
async function bgRemove(){await idbDel(bgKey());bgClear();toast("Фон убран");if(S.tab==="settings"&&(!S.page||S.page.t==="sset")){VC={};render()}}

/* ---------- избранное ---------- */
var FAVS={};
function syncFavBtn(){var t=T[Q[qi]],b=$("#bfav");if(!b||!t)return;b.classList.toggle("on",!!FAVS[t.id])}

/* ---------- окно журнала ошибок ---------- */
function logInfo(){return "PiXeL Music · "+new Date().toLocaleString("ru-RU")+"\nПользователь: "+(S.me?"@"+S.me.name:"гость")+"\nЭкран: "+(S.page?S.page.t:S.tab)+"\nСервер: "+(OFFLINE?"нет связи":"ок")+"\nБраузер: "+navigator.userAgent}
function logText(){return logInfo()+"\n\n"+(LOG.length?LOG.map(function(e){return "["+new Date(e.t).toLocaleTimeString("ru-RU")+"] "+e.kind.toUpperCase()+" ("+e.where+"): "+e.msg+(e.stack?"\n"+e.stack:"")}).join("\n\n"):"Ошибок нет")}
function renderLog(){
  var h='<pre class="linfo">'+esc(logInfo())+"</pre>";
  h+=LOG.length?LOG.slice().reverse().map(function(e){return '<div class="le"><div class="lh"><span class="lk k-'+esc(e.kind)+'">'+esc(e.kind)+"</span><small>"+new Date(e.t).toLocaleTimeString("ru-RU")+" · "+esc(e.where)+"</small></div><b>"+esc(e.msg)+"</b>"+(e.stack?"<pre>"+esc(e.stack)+"</pre>":"")+"</div>"}).join(""):'<div class="empty">'+I("check")+"<p>Ошибок нет</p><small>Если что-то работает не так, опиши проблему ниже и отправь отчёт.</small></div>";
  $("#logbody").innerHTML=h;
}
function openLog(){renderLog();$("#logwin").classList.add("open");document.body.style.overflow="hidden";$("#logbar").classList.remove("show")}
function closeLog(){$("#logwin").classList.remove("open");document.body.style.overflow=($("#sheet").classList.contains("open")||$("#chat").classList.contains("open"))?"hidden":""}
async function sendLog(){
  var b=$("#logsendb");if(!b||b.dataset.busy)return;
  b.dataset.busy="1";b.className="btn sending";b.innerHTML='<span class="spin"></span> Отправляю…';
  var ok=false;
  try{
    await api("/api/report",{body:{text:logText()+"\n\nКомментарий пользователя: "+($("#lognote").value.trim()||"—")}});
    ok=true;$("#lognote").value="";b.className="btn sent";b.innerHTML=I("check")+" Отправлено";
    var k=$("#logok");k.classList.remove("show");void k.offsetWidth;k.classList.add("show");setTimeout(function(){k.classList.remove("show")},1900);
  }catch(e){b.className="btn fail";b.innerHTML=I("x")+" Не отправилось";toast("Не получилось отправить: "+e.message)}
  setTimeout(function(){delete b.dataset.busy;b.className="btn";b.innerHTML="Отправить разработчику"},ok?2400:2200);
}

/* ---------- действия ---------- */
var uploading=false;
async function pickUpload(files){
  if(uploading)return;uploading=true;
  var err=$("#uperr");if(err)err.textContent="";
  for(var i=0;i<files.length;i++){
    var f=files[i],bar=$("#upbar"),tx=$("#uptxt");
    if(f.size>300*1048576){if(err)err.textContent=f.name+": файл больше 300 МБ";continue}
    if(tx)tx.textContent="Читаю теги: "+f.name+" ("+(i+1)+"/"+files.length+")";
    var meta=await extractMeta(f);
    var title=meta.title||f.name.replace(/\.[^.]+$/,""),artist=meta.artist||"";
    var dur=await audioDur(f);
    bar=$("#upbar");if(bar){bar.style.display="block";bar.firstChild.style.width="0"}
    try{
      var r=await upload("/api/upload?kind=audio&name="+enc(f.name)+"&title="+enc(title)+"&artist="+enc(artist)+"&dur="+dur+"&pub="+(S.upPub?1:0),f,function(p){var b=$("#upbar");if(b)b.firstChild.style.width=Math.round(p*100)+"%";var t2=$("#uptxt");if(t2)t2.textContent="Загружаю "+(i+1)+"/"+files.length+": "+Math.round(p*100)+"%"});
      if(meta.cover){try{var cb=await shrink(meta.cover,520,.86);var ur=await upload("/api/upload?kind=image&name=c.jpg",cb);await api("/api/track/cover",{body:{id:r.track.id,url:ur.url}})}catch(e){}}
    }catch(e){var er=$("#uperr");if(er)er.textContent=f.name+": "+e.message;else toast(e.message)}
  }
  uploading=false;if(S.tab==="music"&&!S.page)render();
}
async function pickImage(file,field){
  try{
    var b=await shrink(file,field==="avatar"?420:1400,.86);
    var r=await upload("/api/upload?kind=image&name=x.jpg",b);var o={};o[field]=r.url;
    await api("/api/profile",{body:o});toast("Готово");render();
  }catch(e){toast(e.message)}
}
async function copyText(t){try{await navigator.clipboard.writeText(t);toast("Ссылка скопирована")}catch(e){window.prompt("Скопируй ссылку:",t)}}
function openSheet(){$("#sheet").classList.add("open");document.body.style.overflow="hidden";setTimeout(placeYt,30)}
function closeSheet(){$("#sheet").classList.remove("open");document.body.style.overflow="";placeYt()}


var plPick=null;
async function uploadPlCover(file){
  try{
    var b=await shrink(file,900,.86),r=await upload("/api/upload?kind=image&name=pl.jpg",b);
    S.plCover=r.url;var p=$("#plcp");if(p)p.innerHTML=cov(r.url);
  }catch(e){toast(e.message)}
}
async function addToPlaylistModal(){
  var t=T[Q[qi]];if(!t)return;
  var d=await api("/api/me");
  var h='<h3>Добавить в плейлист</h3>';
  if(!d.playlists.length)h+='<p class="hint">У тебя пока нет плейлистов.</p><button class="btn" data-act="closemodal" id="mkfirst">Создать плейлист</button>';
  else h+='<div class="mlist">'+d.playlists.map(function(p){return '<div class="row" data-act="addtopl1" data-id="'+esc(p.id)+'"><div class="cv">'+cov(p.cover)+'</div><div class="meta"><b>'+esc(p.name)+"</b><small>"+p.count+" треков</small></div></div>"}).join("")+"</div>"+'<button class="btn sec" data-act="closemodal">Закрыть</button>';
  showModal(h);
}
function syncOffBtn(){var t=T[Q[qi]],b=$("#boff");if(!b||!t)return;b.classList.toggle("on",!!OFF[t.id]);b.textContent=OFF[t.id]?"Скачано ✓":"Скачать для офлайна";b.style.display=canOff?"":"none"}
$("#fTrCover").addEventListener("change",async function(e){
  var f=e.target.files[0];e.target.value="";if(!f||!S.etId)return;
  try{toast("Загружаю обложку…",{type:"load",sticky:true});var cb=await shrink(f,520,.86),ur=await upload("/api/upload?kind=image&name=c.jpg",cb);await api("/api/track/cover",{body:{id:S.etId,url:ur.url}});toast("Обложка обновлена");$("#modal").classList.remove("open");lastId=null;render().then(function(){syncUI()})}
  catch(er){toast(er.message||"Не удалось загрузить обложку")}
});
document.addEventListener("click",async function(e){
  if(e.target.id==="modal"){$("#modal").classList.remove("open");return}
  if(e.target.id==="mctx"){if(Date.now()-MXT>350)closeMx();return}
  var tb=e.target.closest("[data-tab]");
  if(tb){tb.classList.remove("pop");void tb.offsetWidth;tb.classList.add("pop");go(tb.dataset.tab);return}
  if(e.target.closest("#nbx")){closeBanner();return}
  if(e.target.closest("#nbanner")){var bn=bannerNick;closeBanner();if(bn)openChat(bn);return}
  var el=e.target.closest("[data-act]");if(!el)return;
  var a=el.dataset.act,id=el.dataset.id,v=el.dataset.v;
  try{
  if(a==="login")return doAuth("login");
  if(a==="reg")return doAuth("register");
  if(a==="amode"){AU.mode=v;drawAuth()}
  else if(a==="eye"){var pi=$("#aP"),show=pi.type==="password";pi.type=show?"text":"password";var p2i=$("#aP2");if(p2i)p2i.type=pi.type;el.innerHTML=I(show?"eyeoff":"eye")}
  else if(a==="gologin"){AU.skipGuest=true;S.me=null;showAuth()}
  else if(a==="play")playQ((el.dataset.list||"").split(","),+el.dataset.i);
  else if(a==="playall")playQ((el.dataset.list||"").split(","),0);
  else if(a==="toggle")toggle();else if(a==="next")next(false);else if(a==="prev")prev();
  else if(a==="shuffle"){SHUF=!SHUF;syncUI()}
  else if(a==="repeat"){REP=(REP+1)%3;syncUI()}
  else if(a==="opensheet"){if(Q.length)openSheet()}
  else if(a==="closesheet")closeSheet();
  else if(a==="queue"){var q=$("#sq"),m=$("#smain"),open=q.style.display==="none";q.style.display=open?"block":"none";m.style.display=open?"none":"block";if(open)renderQueue()}
  else if(a==="qjump"){qi=+el.dataset.i;loadCur()}
  else if(a==="sleep")setSleep(+v);
  else if(a==="sub"){S.sub=v;render()}
  else if(a==="pickaudio")$("#fAudio").click();
  else if(a==="pickava")$("#fAva").click();
  else if(a==="pickban")$("#fBan").click();
  else if(a==="deltrack"){if(confirm("Удалить трек?")){await api("/api/track/delete",{body:{id:id}});await offDel(id);if(Q[qi]===id){A.pause();A.removeAttribute("src");Q=[];qi=-1;lastId=null;syncUI();closeSheet()}render()}}
  else if(a==="openpl"){S.page={t:"pl",id:id};S.pledit=false;render();window.scrollTo(0,0)}
  else if(a==="plopen"){S.page={t:"pl",id:id};S.pledit=false;render();window.scrollTo(0,0)}
  else if(a==="openuser"){if(CH.with){closeChat()}S.page={t:"user",id:id};S.pledit=false;render();window.scrollTo(0,0)}
  else if(a==="back"){if(S.page&&S.page.t==="pladd")S.page={t:"pl",id:S.page.id};else S.page=null;S.pledit=false;S.plInit="";render()}
  else if(a==="chatsback"){S.page=null;render()}
  else if(a==="copylink"){copyText((CFG.public_url||location.origin).replace(/\/$/,"")+"/#p="+id).then(function(){toast("Ссылка скопирована")}).catch(function(){toast("Не удалось скопировать ссылку")})}
  else if(a==="savepl"){var r=await api("/api/playlist/save",{body:{id:id}});toast(r.saved?"Сохранено в твои плейлисты":"Убрано");render()}
  else if(a==="delpl"){if(confirm("Удалить плейлист?")){await api("/api/playlist/delete",{body:{id:id}});S.page=null;S.tab="music";S.sub="pls";render()}}
  else if(a==="newpl"){S.sub="pls";S.plCover="";S.page={t:"create"};render();window.scrollTo(0,0)}
  else if(a==="pickplcover")$("#fPl").click();
  else if(a==="clrplcover"){S.plCover="";var cp=$("#plcp");if(cp)cp.innerHTML=cov("")}
  else if(a==="mkpl"){
    try{var r2=await api("/api/playlist",{body:{name:$("#plName").value,desc:$("#plDesc").value,link:$("#plLink").value,cover:S.plCover||"",tracks:[]}});S.plCover="";S.page={t:"pladd",id:r2.id};render();toast("Плейлист создан. Добавь музыку")}catch(er){$("#cerr").textContent=er.message}
  }
  else if(a==="pledit"){S.pledit=true;S.plInit="";render()}
  else if(a==="plcancel"){S.pledit=false;S.plInit="";render()}
  else if(a==="plsave"){
    try{await api("/api/playlist/edit",{body:{id:id,name:$("#plName").value,desc:$("#plDesc").value,link:$("#plLink").value,cover:S.plCover||""}});S.pledit=false;S.plInit="";toast("Плейлист обновлён");render()}catch(er){$("#cerr").textContent=er.message}
  }
  else if(a==="pladdopen"){S.page={t:"pladd",id:id};render();window.scrollTo(0,0)}
  else if(a==="pltoggle"){
    var on=!S.plIn[id],ab=el.querySelector(".addb");S.plIn[id]=on?1:0;ab.classList.toggle("on",on);ab.innerHTML=I(on?"check":"plus");
    try{await api(on?"/api/playlist/add":"/api/playlist/remove",{body:{id:S.page.id,track:id}})}catch(er){S.plIn[id]=on?0:1;ab.classList.toggle("on",!on);ab.innerHTML=I(on?"plus":"check");toast(er.message)}
  }
  else if(a==="plremove"){try{await api("/api/playlist/remove",{body:{id:S.page.id,track:id}});toast("Трек убран");render()}catch(er){toast(er.message)}}
  else if(a==="edit"){S.pacc=(S.me&&S.me.accent)||"";S.edit=true;render()}
  else if(a==="acc"){SET.acc=v;applySet();VC={};document.querySelectorAll('.sws[data-grp="acc"] .sw').forEach(function(b){b.classList.toggle("on",b.dataset.v===v)})}
  else if(a==="pacc"){S.pacc=v;document.querySelectorAll('.sws[data-grp="pacc"] .sw').forEach(function(b){b.classList.toggle("on",b.dataset.v===v)})}
  else if(a==="installapp")installApp();
  else if(a==="closemodal")$("#modal").classList.remove("open");
  else if(a==="playpin"){if(Q[qi]===id)toggle();else playQ([id],0)}
  else if(a==="canceledit"){S.edit=false;render()}
  else if(a==="stat"){$("#eStat").value=v}
  else if(a==="saveprof"){await api("/api/profile",{body:{display:$("#eName").value,bio:$("#eBio").value,status:$("#eStat").value,accent:S.pacc||"",pin:$("#ePin").value,socials:socVals()}});S.edit=false;toast("Профиль обновлён");render()}
  else if(a==="set"){var k=el.dataset.k;SET[k]=v;applySet();VC={};el.parentNode.querySelectorAll('[data-k="'+k+'"]').forEach(function(b){b.classList.toggle("on",b.dataset.v===v)})}
  else if(a==="tgl"){
    var k2=el.dataset.k,sw=el.querySelector(".sw2"),nv=!sw.classList.contains("on");sw.classList.toggle("on",nv);
    if(LOCT[k2]){SET[k2]=nv;applySet();if(k2==="notif")toast(nv?"Уведомления включены":"Уведомления выключены")}
    else{
      try{await api("/api/profile",{body:k2==="show"?{show_listen:nv}:{private:nv}});VC={};if(S.me){if(k2==="show")S.me.show_listen=nv;else S.me.private=nv}toast(k2==="private"?(nv?"Профиль закрыт":"Профиль открыт"):"Сохранено")}
      catch(er){sw.classList.toggle("on",!nv);toast(er.message)}
    }
  }
  else if(a==="logout"){ltFlush();try{await api("/api/logout",{body:{}})}catch(er){}localStorage.removeItem("px_token");localStorage.removeItem("px_admin_token");localStorage.removeItem("px_imp_name");leaveAccount();showImpBar();A.pause();A.removeAttribute("src");Q=[];qi=-1;lastId=null;syncUI();closeSheet();if(CH.with)closeChat();closeBanner();setBadge(0);POLL.mid=-1;VC={};S.me=null;S.page=null;AU.mode="login";AU.skipGuest=false;render()}
  /* сообщения */
  else if(a==="openchat"){openChat(id)}
  else if(a==="newchat"){S.page={t:"find"};render();window.scrollTo(0,0)}
  else if(a==="chatback")closeChat();
  else if(a==="chpw"){try{await api("/api/password",{body:{old:$("#pwOld").value,new:$("#pwNew").value}});$("#pwOld").value="";$("#pwNew").value="";$("#pwErr").textContent="";toast("Пароль изменён")}catch(er){$("#pwErr").textContent=er.message}}
  else if(a==="chatprofile"){cmenuToggle(false);var w=CH.with;if(w){closeChat();S.page={t:"user",id:w};render();window.scrollTo(0,0)}}
  else if(a==="csend")sendMsg();
  /* офлайн */
  else if(a==="offtoggle"){var tt=T[Q[qi]];if(!tt)return;if(OFF[tt.id]){await offDel(tt.id);toast("Удалено из загрузок")}else{toast("Скачиваю трек…",{type:"load",sticky:true});if(await offAdd(tt))toast("Скачано. Трек играет без интернета");else{var te=$("#toast");if(te&&te.querySelector(".spin"))te.style.display="none"}}syncOffBtn();if(S.tab==="music"&&S.sub==="off"){VC={};render()}}
  else if(a==="offpl"){var ids=(el.dataset.list||"").split(",").filter(Boolean),okc=0;for(var oi=0;oi<ids.length;oi++){var ot=T[ids[oi]];if(!ot)continue;if(OFF[ot.id]){okc++;continue}toast("Скачиваю "+(oi+1)+" из "+ids.length+"…");if(await offAdd(ot))okc++}toast("Скачано треков: "+okc)}
  else if(a==="offdel"){await offDel(id);VC={};render()}
  else if(a==="addtopl"){if(!T[Q[qi]])return;addToPlaylistModal()}
  else if(a==="addtopl1"){var tr1=T[Q[qi]];if(!tr1)return;await api("/api/playlist/add",{body:{id:id,track:tr1.id}});$("#modal").classList.remove("open");toast("Добавлено в плейлист")}
  /* импорт, любимое, фон, журнал ошибок */
  else if(a==="openimport"){S.page={t:"import"};IMP.d=null;render();window.scrollTo(0,0)}
  else if(a==="imppaste"){try{var cl=await navigator.clipboard.readText();$("#impU").value=cl;svcHi(cl)}catch(er){toast("Вставь ссылку вручную: браузер не дал доступ к буферу")}}
  else if(a==="impgo")impGo();
  else if(a==="impall"){if(IMP.d)impDest(IMP.d.tracks)}
  else if(a==="impone"){if(IMP.d)impDest([IMP.d.tracks[+el.dataset.i]])}
  else if(a==="impfav"){if(IMP.d)impBulkFav()}
  else if(a==="attach")attachModal(id);
  else if(a==="attpick"){try{var ar=await api("/api/track/attach",{body:{ghost:S.attId,track:id}});if(T[S.attId])Object.assign(T[S.attId],ar.track);$("#modal").classList.remove("open");toast("Файл привязан");render()}catch(er){toast(er.message)}}
  else if(a==="impfav1"){if(IMP.d)impHeart(+el.dataset.i,el)}
  else if(a==="impto")impSave(v);
  else if(a==="favtoggle"){var ft=T[Q[qi]];if(!ft)return;var fr=await api("/api/fav",{body:{track:ft.id}});if(fr.fav)FAVS[ft.id]=1;else delete FAVS[ft.id];syncFavBtn();toast(fr.fav?"Добавлено в любимое":"Трек убран")}
  else if(a==="pickbg"){var fb=$("#fBg");fb.accept=v==="video"?"video/*":"image/*";fb.click()}
  else if(a==="bgremove")bgRemove();
  else if(a==="logopen")openLog();
  else if(a==="logclose")closeLog();
  else if(a==="logbarx")$("#logbar").classList.remove("show");
  else if(a==="logcopy"){try{await navigator.clipboard.writeText(logText());toast("Лог скопирован")}catch(er){window.prompt("Скопируй лог:",logText())}}
  else if(a==="logsend")sendLog();
  else if(a==="logclear"){LOG=[];try{localStorage.removeItem("px_log")}catch(er){}renderLog();toast("Журнал очищен")}
  else if(a==="repopen"){S.arep=S.arep===id?"":id;refreshRep()}
  else if(a==="repdel"){await api("/api/admin/report/delete",{body:{id:id}});S.arep="";refreshRep()}
  else if(a==="repclear"){if(confirm("Удалить все репорты?")){await api("/api/admin/report/delete",{body:{all:true}});render()}}
  else if(a==="uppub"){S.upPub=v==="1";try{localStorage.setItem("px_uppub",S.upPub?"1":"0")}catch(er){}document.querySelectorAll(".upseg button").forEach(function(b){b.classList.toggle("on",b.dataset.v===v)});var ut=$("#uptxt");if(ut)ut.textContent=upHint()}
  else if(a==="tvis"){var tt2=T[id]||{};await api("/api/track/edit",{body:{id:id,title:tt2.title||"",artist:tt2.artist||"",private:v==="1"}});toast(v==="1"?"Трек теперь только для тебя":"Трек теперь в ленте");render()}
  else if(a==="admimp"){
    if(!confirm("Войти как @"+id+"? Ты увидишь аккаунт глазами этого пользователя. Прослушивания не засчитываются."))return;
    var ir=await api("/api/admin/impersonate",{body:{user:id}});
    if(CH.with)closeChat();closeSheet();A.pause();
    localStorage.setItem("px_admin_token",localStorage.getItem("px_token"));localStorage.setItem("px_imp_name",ir.user.name);localStorage.setItem("px_token",ir.token);
    ACC="";S.me=null;S.page=null;S.tab="feed";POLL.mid=-1;setBadge(0);VC={};showImpBar();render();window.scrollTo(0,0)}
  else if(a==="impback"){
    var adm=localStorage.getItem("px_admin_token");
    try{await api("/api/logout",{body:{}})}catch(er){}
    if(CH.with)closeChat();closeSheet();A.pause();
    localStorage.setItem("px_token",adm);localStorage.removeItem("px_admin_token");localStorage.removeItem("px_imp_name");
    ACC="";S.me=null;S.page=null;S.tab="settings";POLL.mid=-1;VC={};showImpBar();render()}
  else if(a==="edittrack"){showModal(editTrackHtml(T[id]||{}))}
  else if(a==="etsave"){var etn=($("#etTitle").value||"").trim();if(!etn){toast("Введи название трека");return}await api("/api/track/edit",{body:{id:id,title:etn,artist:$("#etArtist").value}});$("#modal").classList.remove("open");toast("Трек обновлён");lastId=null;render().then(function(){syncUI()})}
  else if(a==="etvis"){var etv=T[id]||{};await api("/api/track/edit",{body:{id:id,title:($("#etTitle")?$("#etTitle").value.trim():"")||etv.title||"",artist:$("#etArtist")?$("#etArtist").value:(etv.artist||""),private:!etv.private}});$("#modal").classList.remove("open");toast(etv.private?"Трек теперь в ленте":"Трек теперь только для тебя");render()}
  else if(a==="etpost"){$("#modal").classList.remove("open");S.np={track:id,anon:false,text:""};S.page={t:"newpost"};render();window.scrollTo(0,0)}
  else if(a==="etcover"){S.etId=id;$("#fTrCover").click()}
  else if(a==="etdel"){if(confirm("Удалить трек?")){$("#modal").classList.remove("open");await api("/api/track/delete",{body:{id:id}});await offDel(id);if(Q[qi]===id){A.pause();A.removeAttribute("src");Q=[];qi=-1;lastId=null;syncUI();closeSheet()}toast("Трек удалён");render()}}
  else if(a==="chatmenu"){cmenuToggle()}
  else if(a==="cmenuclose"){cmenuToggle(false)}
  else if(a==="chatblock"){cmenuToggle(false);var bw=CH.with;if(!bw)return;if(CH.iblock){await doBlock(bw,false);return}showModal('<h3 class="mtitle">Заблокировать @'+esc(bw)+'?</h3><p class="hint">Вы оба не сможете писать друг другу, пока ты не разблокируешь. Разблокировать можно кнопкой внизу этого чата или в Настройки → Приватность.</p><button class="btn red" data-act="chatblockgo">Заблокировать</button><button class="btn sec" data-act="closemodal">Отмена</button>')}
  else if(a==="chatblockgo"){$("#modal").classList.remove("open");await doBlock(CH.with,true)}
  else if(a==="chatunblock"){await doBlock(CH.with,false)}
  else if(a==="unblock"){await api("/api/block",{body:{name:id,on:false}});toast("Пользователь разблокирован");render()}
  else if(a==="sq"){S.sq=v;render()}
  else if(a==="plplay"){var pls1=(el.dataset.list||"").split(",").filter(Boolean);if(!pls1.length){toast("В плейлисте пока нет музыки");return}if(isListQ(pls1)){toggle()}else{playQ(pls1,0);api("/api/playlist/play",{body:{id:id}}).catch(function(){})}}
  else if(a==="plshuf"){var pls2=(el.dataset.list||"").split(",").filter(Boolean);if(!pls2.length){toast("В плейлисте пока нет музыки");return}SHUF=true;playQ(pls2,Math.floor(Math.random()*pls2.length));api("/api/playlist/play",{body:{id:id}}).catch(function(){})}
  else if(a==="plrate"){var rmy=+el.dataset.my||0,rnv=(+v===rmy)?0:+v;await api("/api/playlist/rate",{body:{id:id,v:rnv}});toast(rnv?"Оценка сохранена":"Оценка убрана");render()}
  else if(a==="plcmtsend"){var pci=$("#plcIn"),pct=(pci&&pci.value||"").trim();if(!pct){toast("Напиши комментарий");return}await api("/api/playlist/comment",{body:{id:id,text:pct}});pci.value="";toast("Комментарий отправлен");render()}
  else if(a==="plcmtdel"){if(confirm("Удалить комментарий?")){await api("/api/playlist/comment/delete",{body:{id:id,cid:v}});render()}}
  else if(a==="newpost"){S.np={track:id||"",anon:false,text:""};S.page={t:"newpost"};render();window.scrollTo(0,0)}
  else if(a==="npsel"){S.np=S.np||{track:"",anon:false,text:""};S.np.track=id;document.querySelectorAll("#view .row[data-act=npsel]").forEach(function(r){var on=r.dataset.id===id;r.classList.toggle("on",on);var ck=r.querySelector(".npck");if(ck)ck.innerHTML=on?I("check"):""})}
  else if(a==="npanon"){S.np=S.np||{track:"",anon:false,text:""};S.np.anon=v==="1";document.querySelectorAll("[data-act=npanon]").forEach(function(b){b.classList.toggle("on",b.dataset.v===v)});var ni=$("#npinfo");if(ni)ni.innerHTML=npInfo(S.np.anon)}
  else if(a==="npgo"){var np=S.np||{};if(!np.track){toast("Выбери трек из списка");return}var tx=$("#npText");await api("/api/post/create",{body:{track:np.track,text:tx?tx.value:(np.text||""),anon:!!np.anon}});S.np=null;toast("Трек опубликован в ленте");go("feed")}
  else if(a==="openpost"){S.page={t:"post",id:id};render();window.scrollTo(0,0)}
  else if(a==="postdel"){if(confirm("Убрать этот пост из ленты?")){await api("/api/post/delete",{body:{id:id}});if(S.page&&S.page.t==="post")S.page=null;toast("Пост убран из ленты");render()}}
  else if(a==="cmtsend"){var ci=$("#cmtIn"),ct=(ci&&ci.value||"").trim();if(!ct){toast("Напиши комментарий");return}await api("/api/post/comment",{body:{id:id,text:ct}});ci.value="";toast("Комментарий отправлен");render()}
  else if(a==="cmtdel"){if(confirm("Удалить комментарий?")){await api("/api/post/comment/delete",{body:{id:id,cid:v}});render()}}
  else if(a==="copysite"){copyText((CFG&&CFG.public_url)||location.origin).then(function(){toast("Ссылка скопирована")}).catch(function(){toast("Не удалось скопировать ссылку")})}
  else if(a==="mxrx"){var mxid=MX&&MX.id;closeMx();if(!mxid)return;var rr=await api("/api/chat/react",{body:{id:mxid,e:v}});var rel=$('#cmsgs .msg[data-id="'+mxid+'"]');if(rel)paintMsg(rel,rr.msg)}
  else if(a==="mxcopy"){var mxt=MX?MX.text:"";closeMx();copyText(mxt).then(function(){toast("Скопировано")}).catch(function(){toast("Не удалось скопировать")})}
  else if(a==="mxedit"){var mxe=MX;closeMx();if(mxe)startEdit(mxe.id,mxe.text)}
  else if(a==="mxdel"){var mxd=MX;closeMx();if(mxd)showModal('<h3>Удалить сообщение?</h3><p class="hint">Оно пропадёт у вас обоих.</p><button class="btn red" data-act="mxdelgo" data-id="'+mxd.id+'">Удалить</button><button class="btn sec" data-act="closemodal">Отмена</button>')}
  else if(a==="mxdelgo"){$("#modal").classList.remove("open");await api("/api/chat/delete",{body:{id:+id}});var mdel=$('#cmsgs .msg[data-id="'+id+'"]');if(mdel)mdel.remove();toast("Сообщение удалено")}
  else if(a==="rxtoggle"){var mel=el.closest(".msg");if(!mel)return;var rr2=await api("/api/chat/react",{body:{id:+mel.dataset.id,e:v}});paintMsg(mel,rr2.msg)}
  else if(a==="cedcancel"){cancelEdit()}
  else if(a==="admpostdel"){if(confirm("Убрать этот пост из ленты? Трек останется у автора.")){await api("/api/post/delete",{body:{id:id}});toast("Пост убран из ленты");render()}}
  else if(a==="admtrackdel"){if(confirm("Удалить трек навсегда вместе с постом?")){await api("/api/track/delete",{body:{id:id}});await offDel(id);if(Q[qi]===id){A.pause();A.removeAttribute("src");Q=[];qi=-1;lastId=null;syncUI();closeSheet()}toast("Трек удалён");render()}}
  else if(a==="admwipe"){var wi=WIPE[v];if(wi)showModal('<h3>'+esc(wi[0])+'?</h3><p class="hint">'+esc(wi[1])+' Это нельзя отменить.</p><input id="wipeIn" placeholder="Напиши УДАЛИТЬ" autocomplete="off"><div class="err" id="wipeErr"></div><button class="btn red" data-act="admwipego" data-v="'+v+'">Удалить</button><button class="btn sec" data-act="closemodal">Отмена</button>')}
  else if(a==="admwipego"){var wv=($("#wipeIn").value||"").trim().toUpperCase();if(wv!=="УДАЛИТЬ"){$("#wipeErr").textContent="Напиши слово УДАЛИТЬ, чтобы подтвердить";return}var wr=await api("/api/admin/wipe",{body:{what:v,confirm:wv}});$("#modal").classList.remove("open");if(v==="tracks"||v==="users"||v==="all"){A.pause();A.removeAttribute("src");Q=[];qi=-1;lastId=null;syncUI();closeSheet()}VC={};toast("Готово. Удалено файлов: "+wr.files);render()}
  else if(a==="mnu"){S.page={t:"sset",id:v};render();window.scrollTo(0,0)}
  else if(a==="psetopen"){$("#psbody").innerHTML=playerSet();$("#pset").classList.add("open");$("#pset").scrollTop=0}
  else if(a==="psetclose"){$("#pset").classList.remove("open")}
  else if(a==="mpreset"){Object.keys(DMP).forEach(function(k4){SET[k4]=DMP[k4]});applySet();if($("#pset").classList.contains("open"))$("#psbody").innerHTML=playerSet();else{VC={};render()}toast("Настройки плеера сброшены")}
  else if(a==="setreset"){showModal('<h3>Сбросить настройки?</h3><p class="hint">Цвета, стиль, звук и плеер вернутся к значениям по умолчанию. Аккаунт, треки и плейлисты не затронутся.</p><button class="btn red" data-act="setreset2">Сбросить</button><button class="btn sec" data-act="closemodal">Отмена</button>')}
  else if(a==="setreset2"){$("#modal").classList.remove("open");Object.keys(DEFSET).forEach(function(k5){SET[k5]=DEFSET[k5]});applySet();VC={};toast("Настройки сброшены");render()}
  else if(a==="offrm"){await offDel(id);VC={};syncOffBtn();render()}
  else if(a==="offclear"){var offks=Object.keys(OFF);for(var offi=0;offi<offks.length;offi++)await offDel(offks[offi]);VC={};syncOffBtn();toast("Скачанная музыка удалена");render()}
  else if(a==="opendevices"){S.page={t:"devices"};render();window.scrollTo(0,0)}
  else if(a==="devout"){if(confirm("Закрыть сессию на этом устройстве?")){var dr=await api("/api/devices/revoke",{body:{sid:id}});toast(dr.closed?"Сессия закрыта":"Сессия уже закрыта");render()}}
  else if(a==="devall"){if(confirm("Выйти на всех других устройствах?")){var da=await api("/api/devices/revoke",{body:{others:true}});toast("Закрыто сессий: "+da.closed);render()}}
  /* админ */
  else if(a==="openadmin"){S.aq="";S.asel="";S.page={t:"admin"};render();window.scrollTo(0,0)}
  else if(a==="admsel"){var n=id.toLowerCase();S.asel=S.asel===n?"":n;var us=Object.keys(ADM).map(function(k){return ADM[k]});var b=$("#alist");if(b){b.innerHTML=us.filter(function(u){return !S.aq||u.name.toLowerCase().indexOf(S.aq.toLowerCase())>=0||(u.display||"").toLowerCase().indexOf(S.aq.toLowerCase())>=0}).map(admRow).join("")}}
  else if(a==="admtagadd"||a==="admtagcustom"||a==="admtagdel"){
    var au=ADM[id.toLowerCase()];if(!au)return;var tags=au.tags.slice();
    if(a==="admtagadd"){if(tags.indexOf(v)<0)tags.push(v)}
    else if(a==="admtagcustom"){var ct=($("#atag").value||"").trim();if(!ct)return;if(tags.indexOf(ct)<0)tags.push(ct)}
    else tags=tags.filter(function(x){return x!==v});
    await api("/api/admin/tags",{body:{user:au.name,tags:tags}});toast("Бейджи обновлены");await refreshAdm();
  }
  else if(a==="admban"){if(confirm(v==="1"?"Заблокировать пользователя?":"Разблокировать пользователя?")){await api("/api/admin/ban",{body:{user:id,banned:v==="1"}});toast(v==="1"?"Заблокирован":"Разблокирован");await refreshAdm()}}
  }catch(err){toast(err.message)}
});
var searchT=null,admT=null,ptT=null,atT=null;
document.addEventListener("input",function(e){
  var id=e.target.id;
  var sk=e.target.dataset&&e.target.dataset.sk;
  if(sk){var mn=+e.target.min,mx=+e.target.max,vv=+e.target.value;SET[sk]=vv;setRange(e.target,(vv-mn)/(mx-mn)*100);applySet();if(sk==="xfadet"){var xv=$("#xfv");if(xv)xv.textContent=vv+" сек"}return}
  if(id==="npText"){if(S.np)S.np.text=e.target.value;return}
  if(id==="vol"||id==="vol2"){SET.vol=+e.target.value;applySet()}
  else if(id==="cinp")autoGrow();
  else if(id==="bgdim"){SET.bgdim=+e.target.value;applySet()}
  else if(id==="impU")svcHi(e.target.value);
  else if(id==="ccol"){SET.acc=e.target.value;applySet();VC={}}
  else if(id==="pcol"){S.pacc=e.target.value;document.querySelectorAll('.sws[data-grp="pacc"] .sw').forEach(function(b){b.classList.remove("on")})}
  else if(id==="aU"&&AU.mode==="reg")checkNick();
  else if(id==="aP"||id==="aP2"){if(AU.mode==="reg")checkPw()}
  else if(id==="q"){clearTimeout(searchT);var q=e.target.value.trim();var act=(S.page&&S.page.t==="find")?"openchat":"openuser";searchT=setTimeout(async function(){
    var box=$("#sres");if(!box)return;var plm=S.sq==="pls"&&!(S.page&&S.page.t==="find");if(!q&&!plm){box.innerHTML=(S.page&&S.page.t==="find")?'<p class="hint">Начни вводить ник</p>':"";return}
    try{if(plm){var pd=await api("/api/playlists?q="+enc(q));box.innerHTML=(q?"":'<h3 class="lab" style="margin:4px 4px 6px">Популярные плейлисты</h3>')+(pd.playlists.length?pllist(pd.playlists):'<div class="empty">'+I("search")+"<p>Плейлисты не найдены</p><small>Попробуй другое название или ник автора</small></div>")}else{var d=await api("/api/search?q="+enc(q));box.innerHTML=userRows(d.users,act)}}catch(er){box.innerHTML='<div class="err">'+esc(er.message)+"</div>"}},250)}
  else if(id==="atq"){clearTimeout(atT);S.atq=e.target.value.trim();atT=setTimeout(async function(){try{var d=await api("/api/admin/tracks?q="+enc(S.atq));var b=$("#atlist");if(b)b.innerHTML=d.tracks.length?d.tracks.map(admTrack).join(""):'<p class="hint center">Ничего не найдено</p>'}catch(er){toast(er.message)}},300)}
  else if(id==="aq"){clearTimeout(admT);S.aq=e.target.value.trim();admT=setTimeout(function(){refreshAdm().catch(function(er){toast(er.message)})},300)}
  else if(id==="attq"){clearTimeout(window.__attT);window.__attT=setTimeout(attSearch,250)}
  else if(id==="ptq"){clearTimeout(ptT);var tq=e.target.value.trim();ptT=setTimeout(async function(){try{var d=await api("/api/tracks?q="+enc(tq));var b=$("#plres");if(b)b.innerHTML=pickRows(d.tracks)}catch(er){toast(er.message)}},250)}
});
document.addEventListener("keydown",function(e){
  if(e.key!=="Enter")return;
  var id=e.target.id;
  if(id==="aP"&&AU.mode==="login")doAuth("login");
  else if((id==="aP2")&&AU.mode==="reg")doAuth("register");
  else if(id==="cinp"&&!e.shiftKey&&window.matchMedia&&matchMedia("(pointer:fine)").matches){e.preventDefault();sendMsg()}
});
$("#fAudio").addEventListener("change",function(){if(this.files.length)pickUpload([].slice.call(this.files));this.value=""});
$("#fAva").addEventListener("change",function(){if(this.files[0])pickImage(this.files[0],"avatar");this.value=""});
$("#fBan").addEventListener("change",function(){if(this.files[0])pickImage(this.files[0],"banner");this.value=""});
$("#fPl").addEventListener("change",function(){if(this.files[0])uploadPlCover(this.files[0]);this.value=""});
$("#fBg").addEventListener("change",function(){if(this.files[0])bgSet(this.files[0]);this.value=""});
window.addEventListener("resize",placeYt);
(function(){var sn=document.querySelector("#sheet .sin");if(sn)sn.addEventListener("scroll",placeYt)})();
window.addEventListener("hashchange",openHash);
function openHash(){var m=/^#p=([0-9a-f]+)$/.exec(location.hash);if(m&&localStorage.getItem("px_token")){S.page={t:"pl",id:m[1]};S.pledit=false;history.replaceState(null,"",location.pathname);render()}else if(m){render()}}
window.addEventListener("resize",function(){moveInd(false)});

/* ---------- старт ---------- */
$("#top").innerHTML=logo(32)+'<div class="wm">PiXeL <b>Music</b></div>';
$("#tabs").innerHTML='<span class="tind"></span>'+[["feed","feed","Лента"],["music","music","Музыка"],["chats","chat","Чаты"],["profile","user","Профиль"],["settings","gear","Настройки"]].map(function(x){return '<button data-tab="'+x[0]+'" aria-label="'+x[2]+'">'+I(x[1])+(x[0]==="chats"?'<b class="tbdg" id="tbdg"></b>':"")+"</button>"}).join("");
$("#cback").innerHTML=I("back");$("#cmore").innerHTML=I("dots");$("#cmprof").innerHTML=I("user")+"Профиль";$("#csendb").innerHTML=I("send");
["#sdown","#sqb"].forEach(function(s,i){$(s).innerHTML=I(i?"queue":"down")});$("#spsb").innerHTML=I("gear");$("#psb").innerHTML=I("back");$("#cedx").innerHTML=I("x");$("#cedi").innerHTML=I("edit");
$(".mrow .ib[data-act=prev]").innerHTML=I("prev");$(".mrow .ib[data-act=next]").innerHTML=I("next");$("#mpp").innerHTML=I("play");$("#spp").innerHTML=I("play");
$("#bshuf").innerHTML=I("shuffle");$("#brep").innerHTML=I("repeat");$("#bprev").innerHTML=I("prev");$("#bnext").innerHTML=I("next");
$("#nbi").innerHTML=I("chat");$("#nbx").innerHTML=I("x");$("#logokc").innerHTML=I("check");showImpBar();
(function(){var nb=$("#nbanner"),y0=0;nb.addEventListener("touchstart",function(e){y0=e.touches[0].clientY},{passive:true});nb.addEventListener("touchmove",function(e){if(e.touches[0].clientY-y0<-26)closeBanner()},{passive:true})})();$("#bfav").innerHTML=I("heart")+" Любимое";$("#logx").innerHTML=I("x");
var CFG={public_url:""};
api("/api/config").then(function(c){CFG=c}).catch(function(){});
applySet();BGREADY=bgLoad();render().then(splashDone,splashDone);openHash();
setTimeout(pollNow,800);

</script>
</body>
</html>
'''

# ============================== БАЗА ==============================
LOCK = threading.RLock()
WLOCK = threading.Lock()
_DIRTY = False


def load_db():
    base = {"users": {}, "tokens": {}, "tracks": {}, "playlists": {}, "convs": {}, "devs": {}, "reports": [], "imp": {}, "sess": {}, "posts": {}, "mid": 0, "ver": 3}
    if os.path.exists(DBF):
        try:
            with open(DBF, encoding="utf-8") as f:
                d = json.load(f)
            for k, v in base.items():
                d.setdefault(k, v)
            if d.get("ver", 1) < 2:                 # раньше теги ставили все сами, теперь только админ
                for u in d["users"].values():
                    u["tags"] = []
                d["ver"] = 2
            if d.get("ver", 1) < 3:                 # старые счётчики прослушиваний были завышены, начинаем заново
                for u in d["users"].values():
                    u["plays"] = {}
                    u["listen_sec"] = 0
                d["ver"] = 3
            return d
        except Exception:
            try:
                os.replace(DBF, DBF + ".broken")
            except Exception:
                pass
    return base


DB = load_db()


def _write_db():
    global _DIRTY
    with LOCK:
        _DIRTY = False
        data = json.dumps(DB, ensure_ascii=False)
    with WLOCK:
        tmp = DBF + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, DBF)


def save_db(lazy=False):
    """lazy=True: записать фоновым потоком (для частых мелочей)."""
    global _DIRTY
    if lazy:
        _DIRTY = True
    else:
        _write_db()


def _saver():
    while True:
        time.sleep(2)
        if _DIRTY:
            try:
                _write_db()
            except Exception:
                pass


atexit.register(lambda: _DIRTY and _write_db())


# Админ-аккаунт: в коде пароля нет. Варианты:
#  1) локально: открой сайт на том же устройстве (127.0.0.1) и зарегистрируй ник из ADMINS;
#  2) на хостинге: задай переменную PIXEL_ADMIN_PASSWORD (от 8 символов), админ создастся при первом запуске.
def seed_admins():
    if not ADMIN_PASSWORD:
        return
    if len(ADMIN_PASSWORD) < 8:
        print(" ! PIXEL_ADMIN_PASSWORD короче 8 символов, админ не создан")
        return
    nick = sorted(ADMINS)[0]
    if nick in DB["users"]:
        return
    salt = secrets.token_hex(8)
    DB["users"][nick] = {"name": nick, "display": nick, "salt": salt, "hash": hash_pw(ADMIN_PASSWORD, salt), "bio": "",
                         "status": "Слушаю музыку", "avatar": "", "banner": "", "tags": [], "saved": [], "chats": [],
                         "created": time.time(), "last": 0}
    save_db()
    print(" Админ-аккаунт создан: %s" % nick)


def parse_ua(ua):
    ua = ua or ""
    os_, model, kind = "Неизвестная система", "", "desktop"
    m = re.search(r"Android ([\d.]+)", ua)
    if m:
        os_ = "Android " + m.group(1).split(".")[0]
        kind = "phone" if "Mobile" in ua else "tablet"
        mm = re.search(r"Android [\d.]+; ([^;)]+)", ua)
        model = mm.group(1).strip() if mm else ""
        if model in ("K", "Linux") or model.startswith("Build"):
            model = ""
    elif re.search(r"iPhone|iPad|iPod", ua):
        os_ = "iOS"
        kind = "tablet" if "iPad" in ua else "phone"
        model = "iPad" if "iPad" in ua else "iPhone"
    elif "Windows" in ua:
        os_ = "Windows"
    elif "Mac OS X" in ua or "Macintosh" in ua:
        os_ = "macOS"
    elif "CrOS" in ua:
        os_ = "ChromeOS"
    elif "Linux" in ua:
        os_ = "Linux"
    br = "Браузер"
    for pat, name in ((r"YaBrowser/", "Яндекс Браузер"), (r"SamsungBrowser/", "Samsung Internet"), (r"EdgA?/|Edg/", "Edge"),
                      (r"OPR/|Opera", "Opera"), (r"Firefox/|FxiOS", "Firefox"), (r"Chrome/|CriOS", "Chrome"), (r"Safari/", "Safari")):
        if re.search(pat, ua):
            br = name
            break
    return {"browser": br, "os": os_, "model": model, "kind": kind}


def sid_of(tok):
    return hashlib.sha256(("sid" + tok).encode()).hexdigest()[:14]


def hash_pw(pw, salt):
    return hashlib.sha256((salt + pw).encode("utf-8")).hexdigest()


# (посты и чат: функции ниже)
RESERVED = {"admin", "administrator", "root", "support", "moderator", "mod", "system", "pixel", "pixelmusic",
            "owner", "null", "undefined", "bot", "api", "files", "staff", "official", "developer"}
WEAK_PW = {"123456", "1234567", "12345678", "123456789", "qwerty", "qwerty123", "password", "111111", "000000", "abcdef"}


def valid_nick(n):
    return (bool(re.match(r"^[A-Za-z0-9_.]{3,24}$", n)) and not n.startswith(".") and not n.endswith("."))


def is_admin(u):
    return bool(u) and u["name"].lower() in ADMINS


def tags_of(u):
    t = list(u.get("tags", []))
    if is_admin(u) and "Владелец" not in t:
        t.insert(0, "Владелец")
    return t


def pub(u, me=False, viewer=None):
    now = time.time()
    locked = bool(u.get("private")) and not me and not (viewer is not None and (viewer is u or is_admin(viewer)))
    d = {"name": u["name"], "display": u.get("display") or u["name"], "status": u.get("status", ""),
         "avatar": u.get("avatar", ""), "banner": u.get("banner", ""), "accent": u.get("accent", ""),
         "tags": tags_of(u), "online": now - u.get("last", 0) < 120, "seen": int(max(0, now - u.get("last", 0))),
         "private": bool(u.get("private")), "locked": locked}
    if not locked:
        pin = DB["tracks"].get(u.get("pin", ""))
        d["bio"] = u.get("bio", "")
        d["socials"] = dict(u.get("socials") or {})
        d["pin"] = track_pub(pin) if (pin and (me or track_ok(pin, viewer))) else None
        show = u.get("show_listen", True) or me
        d["now"] = u.get("now", "") if (show and now - u.get("now_t", 0) < 360) else ""
    if me:
        d["show_listen"] = u.get("show_listen", True)
        d["admin"] = is_admin(u)
        d["prefs"] = u.get("prefs")
    return d


def track_pub(t):
    d = {"id": t["id"], "title": t["title"], "artist": t.get("artist", ""), "owner": t["owner"],
         "url": t["url"], "cover": t.get("cover", ""), "dur": t.get("dur", 0), "created": t.get("created", 0),
         "ghost": bool(t.get("ghost")), "src": t.get("src", ""), "yt": t.get("yt", ""), "private": bool(t.get("private"))}
    lk = DB["tracks"].get(t.get("link", "")) if t.get("ghost") else None
    if lk and not lk.get("ghost") and lk.get("url") and not lk.get("private"):
        d["url"], d["ghost"], d["linked"] = lk["url"], False, True
        d["cover"] = d["cover"] or lk.get("cover", "")
        d["dur"] = d["dur"] or lk.get("dur", 0)
    return d


def pl_pub(p, viewer=None):
    tr = [i for i in p["tracks"] if i in DB["tracks"]]
    covers = []
    for i in tr:
        c = DB["tracks"][i].get("cover")
        if c and c not in covers:
            covers.append(c)
            if len(covers) >= 4:
                break
    cover = p.get("cover", "") or p.get("ext_cover", "") or (covers[0] if covers else "")
    mosaic = not (p.get("cover") or p.get("ext_cover")) and len(covers) >= 2
    ow = DB["users"].get(p["owner"].lower()) or {}
    rt = p.get("rate") or {}
    return {"id": p["id"], "name": p["name"], "desc": p.get("desc", ""), "owner": p["owner"],
            "owner_display": ow.get("display") or p["owner"], "owner_avatar": ow.get("avatar", ""),
            "link": p.get("link", ""), "count": len(tr), "created": p.get("created", 0), "cover": cover,
            "own_cover": bool(p.get("cover")), "fav": bool(p.get("fav")),
            "covers": covers, "mosaic": mosaic,
            "rating": round(sum(rt.values()) / len(rt), 1) if rt else 0, "nrate": len(rt),
            "plays": int(p.get("plays", 0)), "ncom": len(p.get("comments", [])),
            "my_rate": rt.get(viewer["name"].lower(), 0) if viewer else 0}


def track_ok(t, viewer):
    """личные треки («Для себя») видит только владелец и админ"""
    if t.get("private"):
        return viewer is not None and (viewer["name"] == t["owner"] or is_admin(viewer))
    return True


def visible_owner(owner, viewer):
    """можно ли показывать чужой контент в общих списках"""
    u = DB["users"].get(str(owner).lower())
    if not u or u.get("banned"):
        return False
    if u.get("private") and not (viewer is not None and (viewer is u or is_admin(viewer))):
        return False
    return True


def recent_tracks(u, viewer=None):
    return [track_pub(DB["tracks"][i]) for i in u.get("recent", [])
            if i in DB["tracks"] and (viewer is u or track_ok(DB["tracks"][i], viewer))]


def user_tracks(name, viewer=None):
    anon = anon_ids()
    own = viewer is not None and (viewer["name"] == name or is_admin(viewer))
    ts = [t for t in DB["tracks"].values() if t["owner"] == name and not t.get("ghost") and track_ok(t, viewer) and (own or t["id"] not in anon)]
    ts.sort(key=lambda t: t["created"], reverse=True)
    return [track_pub(t) for t in ts]


def user_pls(name, viewer=None):
    own = viewer is not None and viewer["name"] == name
    ps = [p for p in DB["playlists"].values() if p["owner"] == name and (own or not p.get("fav"))]
    ps.sort(key=lambda p: (not p.get("fav"), -p["created"]))
    return [pl_pub(p) for p in ps]


def saved_pls(u):
    return [pl_pub(DB["playlists"][i]) for i in u.get("saved", []) if i in DB["playlists"]]


def fav_playlist(u, create=True):
    for p in DB["playlists"].values():
        if p["owner"] == u["name"] and p.get("fav"):
            return p
    if not create:
        return None
    pid = uuid.uuid4().hex[:10]
    DB["playlists"][pid] = {"id": pid, "owner": u["name"], "name": "Любимое", "desc": "", "link": "", "cover": "",
                            "tracks": [], "created": time.time() - 10 ** 7, "fav": True}
    return DB["playlists"][pid]


def fav_ids(u):
    p = fav_playlist(u, False)
    return [i for i in p["tracks"] if i in DB["tracks"]] if p else []


def gc_ghosts():
    used = set()
    for p in DB["playlists"].values():
        used.update(p["tracks"])
    for tid in [i for i, t in DB["tracks"].items() if t.get("ghost") and i not in used]:
        del DB["tracks"][tid]


def add_report(kind, user, text, ua=""):
    with LOCK:
        key = text.strip().splitlines()[-1][:160] if text.strip() else ""
        now = time.time()
        for r in DB["reports"][-8:]:
            if r.get("key") == key and now - r["t"] < 60:
                return r["id"]
        rid = uuid.uuid4().hex[:8]
        DB["reports"].append({"id": rid, "t": int(now), "kind": kind, "user": user or "", "text": text[:6000],
                              "ua": ua[:200], "key": key})
        if len(DB["reports"]) > 200:
            del DB["reports"][:len(DB["reports"]) - 200]
        save_db(True)
        return rid


# ============================== ИМПОРТ ПЛЕЙЛИСТОВ ==============================
# Читаем публичные страницы плейлистов. Это «лучшее, что можно без ключей API»: сервисы могут менять
# страницы, поэтому при сбое пользователь видит понятное сообщение, а не поломку.
IMPORT_HOSTS = {"open.spotify.com": "spotify", "spotify.link": "spotify",
                "soundcloud.com": "soundcloud", "www.soundcloud.com": "soundcloud", "m.soundcloud.com": "soundcloud",
                "on.soundcloud.com": "soundcloud",
                "music.yandex.ru": "yandex", "music.yandex.com": "yandex", "music.yandex.by": "yandex", "music.yandex.kz": "yandex",
                "music.youtube.com": "ytm", "www.youtube.com": "ytm", "youtube.com": "ytm", "m.youtube.com": "ytm"}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


FETCH_HOSTS = set(IMPORT_HOSTS) | {"api.music.yandex.net", "api-v2.soundcloud.com"}


class ImportFail(ValueError):
    def __init__(self, msg, detail=""):
        ValueError.__init__(self, msg)
        self.detail = detail


def http_json(url, data=None, headers=None):
    host = urlparse(url).hostname or ""
    if host not in FETCH_HOSTS:
        raise ValueError("Недопустимый адрес")
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded"
    with urllib.request.build_opener(_NoRedirect).open(urllib.request.Request(url, data=body, headers=h), timeout=15) as r:
        return json.loads(r.read(6000000).decode("utf-8", "replace"))


def fetch_text(url, headers=None, max_bytes=3000000):
    for _ in range(4):
        host = urlparse(url).hostname or ""
        if host not in FETCH_HOSTS:
            raise ValueError("Сервис попросил открыть сторонний адрес. Попробуй другую ссылку")
        h = {"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"}
        if host.endswith("youtube.com"):
            h["Cookie"] = "CONSENT=YES+cb.20210328-17-p0.en+FX+667; SOCS=CAI"
        h.update(headers or {})
        try:
            with urllib.request.build_opener(_NoRedirect).open(urllib.request.Request(url, headers=h), timeout=12) as r:
                data = r.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise ValueError("Страница слишком большая")
                return data.decode(r.headers.get_content_charset() or "utf-8", "replace")
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location") if e.headers else None
            if e.code in (301, 302, 303, 307, 308) and loc:
                url = urllib.parse.urljoin(url, loc)
                continue
            raise
    raise ValueError("Слишком много перенаправлений")


def json_after(text, marker, opener="{"):
    """Достаёт JSON, который стоит после `marker =` (не зависит от того, чем заканчивается скрипт)."""
    i = text.find(marker)
    while i != -1:
        j = text.find(opener, i + len(marker))
        if j != -1 and j - i - len(marker) < 12:
            try:
                return json.JSONDecoder().raw_decode(text[j:])[0]
            except ValueError:
                pass
        i = text.find(marker, i + 1)
    return None


def page_info(text):
    m = re.search(r"<title[^>]*>(.*?)</title>", text or "", re.S | re.I)
    flag = " | похоже на страницу согласия/проверки" if re.search(r"consent|captcha|Before you continue|Прежде чем продолжить", text or "", re.I) else ""
    return "страница получена: %d байт, title: %s%s" % (len(text or ""), (m.group(1).strip()[:80] if m else "нет"), flag)


def walk(o, depth=0):
    if depth > 40:
        return
    if isinstance(o, dict):
        yield o
        for v in o.values():
            for x in walk(v, depth + 1):
                yield x
    elif isinstance(o, list):
        for v in o:
            for x in walk(v, depth + 1):
                yield x


def _s(v, n):
    return str(v or "").strip()[:n]


def _https(u):
    u = str(u or "")
    return u if u.startswith("https://") and len(u) < 400 else ""


def imp_spotify(url):
    m = re.search(r"/(playlist|album)/([A-Za-z0-9]{10,30})", urlparse(url).path)
    if not m:
        raise ValueError("Это не ссылка на плейлист Spotify")
    html = fetch_text("https://open.spotify.com/embed/%s/%s" % (m.group(1), m.group(2)))
    m2 = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not m2:
        raise ImportFail("Spotify не отдал данные плейлиста", page_info(html))
    data = json.loads(m2.group(1))
    ent = next((d for d in walk(data) if isinstance(d.get("trackList"), list)), None)
    if not ent:
        raise ValueError("В ответе Spotify нет списка треков")
    cover = ""
    for d in walk(ent.get("coverArt") or ent.get("visualIdentity") or {}):
        if isinstance(d.get("url"), str):
            cover = d["url"]
            break
    tracks = [{"title": _s(t.get("title"), 120), "artist": _s(t.get("subtitle"), 80),
               "dur": int((t.get("duration") or 0) / 1000), "cover": ""} for t in ent["trackList"] if t.get("title")]
    return {"title": _s(ent.get("name") or ent.get("title"), 80), "owner": _s(ent.get("subtitle"), 60),
            "cover": _https(cover), "tracks": tracks, "skipped": 0}


def imp_soundcloud(url):
    html = fetch_text(url)
    arr = json_after(html, "__sc_hydration", "[")
    if not isinstance(arr, list):
        raise ImportFail("SoundCloud не отдал данные плейлиста", page_info(html))
    pl = next((x.get("data") for x in arr if isinstance(x, dict) and x.get("hydratable") == "playlist"), None)
    cid = next((str((x.get("data") or {}).get("id") or "") for x in arr if isinstance(x, dict) and x.get("hydratable") == "apiClient"), "")
    if not isinstance(pl, dict):
        kinds = ",".join(sorted(set(str(x.get("hydratable")) for x in arr if isinstance(x, dict))))[:120]
        raise ImportFail("Это не ссылка на плейлист SoundCloud. Нужна ссылка на плейлист или альбом (…/sets/…)", "в странице: " + kinds)
    raw = [t for t in (pl.get("tracks") or []) if isinstance(t, dict)]
    need = [t["id"] for t in raw if not t.get("title") and t.get("id")]
    full = {}
    if need and cid:                      # SoundCloud присылает полные данные только по первым трекам, остальные докачиваем
        for i in range(0, min(len(need), 300), 30):
            try:
                lst = http_json("https://api-v2.soundcloud.com/tracks?ids=%s&client_id=%s" % (",".join(str(x) for x in need[i:i + 30]), urllib.parse.quote(cid)))
                for t in lst if isinstance(lst, list) else []:
                    if isinstance(t, dict):
                        full[t.get("id")] = t
            except Exception:
                break
    tracks, skipped = [], 0
    for t in raw:
        if not t.get("title"):
            t = full.get(t.get("id")) or t
        if not t.get("title"):
            skipped += 1
            continue
        art = t.get("artwork_url") or (t.get("user") or {}).get("avatar_url") or ""
        tracks.append({"title": _s(t["title"], 120), "artist": _s((t.get("user") or {}).get("username"), 80),
                       "dur": int((t.get("duration") or 0) / 1000), "cover": _https(art.replace("-large", "-t300x300"))})
    cover = (pl.get("artwork_url") or "").replace("-large", "-t500x500")
    return {"title": _s(pl.get("title"), 80), "owner": _s((pl.get("user") or {}).get("username"), 60),
            "cover": _https(cover) or (tracks[0]["cover"] if tracks else ""), "tracks": tracks, "skipped": skipped}


YA_HDR = {"X-Yandex-Music-Client": "YandexMusicAndroid/24023231", "User-Agent": "Yandex-Music-API"}


def _ya_img(uri, size):
    return _https("https://" + str(uri).replace("%%", size)) if uri else ""


def _ya_norm(t):
    return {"title": _s(t.get("title"), 120), "artist": _s(", ".join(a.get("name", "") for a in t.get("artists", []) if isinstance(a, dict)), 80),
            "dur": int((t.get("durationMs") or 0) / 1000), "cover": _ya_img(t.get("coverUri") or (t.get("ogImage") or ""), "200x200")}


def _ya_tracks(res):
    items = res.get("tracks") or []
    rows, need = [], []
    for it in items:
        if not isinstance(it, dict):
            continue
        t = it.get("track") if isinstance(it.get("track"), dict) else it
        if t.get("title"):
            rows.append(("t", t))
        elif it.get("id"):
            key = "%s:%s" % (it["id"], it["albumId"]) if it.get("albumId") else str(it["id"])
            rows.append(("i", key))
            need.append(key)
    found = {}
    for i in range(0, min(len(need), 300), 100):
        part = need[i:i + 100]
        j = http_json("https://api.music.yandex.net/tracks", {"track-ids": ",".join(part)}, YA_HDR)
        for t in (j.get("result") or []):
            if isinstance(t, dict) and t.get("title"):
                found[str(t.get("id"))] = t
                if t.get("albums"):
                    found["%s:%s" % (t.get("id"), t["albums"][0].get("id"))] = t
    out = []
    for kind, v in rows:
        t = v if kind == "t" else found.get(v) or found.get(v.split(":")[0])
        if t:
            out.append(_ya_norm(t))
    return out


def imp_yandex(url):
    pu = urlparse(url)
    path = pu.path
    legacy = re.search(r"/users/([^/]+)/playlists/(\d+)", path)
    uu = re.search(r"/playlists/((?:lk\.)?[0-9a-fA-F-]{16,})", path)
    if not legacy and not uu:
        raise ValueError("Не вижу плейлист в ссылке. Нужна ссылка вида music.yandex.ru/playlists/… или /users/ник/playlists/номер")
    errs = []
    tries = []
    if legacy:
        tries.append(("GET", "https://api.music.yandex.net/users/%s/playlists/%s" % (urllib.parse.quote(legacy.group(1)), legacy.group(2)), None))
    else:
        pid = uu.group(1)
        tries.append(("GET", "https://api.music.yandex.net/playlist/%s" % pid, None))
        tries.append(("POST", "https://api.music.yandex.net/playlists/list", {"playlistIds": pid}))
    res = None
    for method, u, data in tries:
        try:
            j = http_json(u, data, YA_HDR)
            r = j.get("result")
            if isinstance(r, list):
                r = r[0] if r else None
            if isinstance(r, dict) and (r.get("title") or r.get("tracks")):
                res = r
                break
            errs.append("%s %s: пустой ответ" % (method, u.split("net")[-1][:46]))
        except urllib.error.HTTPError as e:
            errs.append("%s %s: HTTP %s" % (method, u.split("net")[-1][:46], e.code))
        except Exception as e:
            errs.append("%s %s: %s %s" % (method, u.split("net")[-1][:46], type(e).__name__, str(e)[:60]))
    if res is None and legacy:                      # старый способ через сайт
        try:
            host = pu.hostname
            api = "https://%s/handlers/playlist.jsx?owner=%s&kinds=%s&lang=ru&external-domain=%s&overembed=false" % (
                host, urllib.parse.quote(legacy.group(1)), legacy.group(2), host)
            res = json.loads(fetch_text(api, {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json", "Referer": url}))["playlist"]
        except Exception as e:
            errs.append("handlers.jsx: %s %s" % (type(e).__name__, str(e)[:60]))
    if res is None:
        liked = bool(uu and uu.group(1).startswith("lk."))
        raise ImportFail("Яндекс не отдал этот плейлист." + (" Ссылка вида lk. это «Мне нравится»: Яндекс отдаёт её только владельцу. Сделай обычный плейлист из любимых треков и пришли ссылку на него." if liked else " Возможно, плейлист закрытый или Яндекс изменил доступ."), "; ".join(errs))
    tracks = _ya_tracks(res)
    cov = res.get("cover") or {}
    cu = cov.get("uri") or ((cov.get("itemsUri") or [""])[0] if isinstance(cov.get("itemsUri"), list) else "")
    own = res.get("owner") or {}
    return {"title": _s(res.get("title"), 80), "owner": _s(own.get("name") or own.get("login"), 60),
            "cover": _ya_img(cu, "400x400") or (tracks[0]["cover"] if tracks else ""), "tracks": tracks, "skipped": 0}


def _yt_rss(lid):
    """запасной вариант: публичная RSS-лента плейлиста (YouTube отдаёт в ней до 15 последних видео)"""
    import html as htmllib
    xml = fetch_text("https://www.youtube.com/feeds/videos.xml?playlist_id=" + lid)
    head = xml.split("<entry>")[0]
    mt = re.search(r"<title>([^<]*)</title>", head)
    tracks = []
    for e in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
        vid = re.search(r"<yt:videoId>([^<]+)</yt:videoId>", e)
        ti = re.search(r"<title>([^<]*)</title>", e)
        au = re.search(r"<name>([^<]*)</name>", e)
        th = re.search(r'<media:thumbnail url="([^"]+)"', e)
        if vid and ti and re.match(r"^[A-Za-z0-9_-]{11}$", vid.group(1)):
            tracks.append({"title": _s(htmllib.unescape(ti.group(1)), 120),
                           "artist": _s(re.sub(r"\s*-\s*Topic$", "", htmllib.unescape(au.group(1) if au else "")), 80),
                           "dur": 0, "cover": _https(th.group(1) if th else ""), "yt": vid.group(1)})
    return {"title": _s(htmllib.unescape(mt.group(1)) if mt else "", 80), "tracks": tracks}


def imp_ytm(url):
    lid = (parse_qs(urlparse(url).query).get("list") or [""])[0]
    if not re.match(r"^[A-Za-z0-9_-]{10,60}$", lid):
        raise ValueError("В ссылке нет плейлиста (нужна ссылка с list=…)")
    html = fetch_text("https://www.youtube.com/playlist?list=" + lid)
    data = json_after(html, "ytInitialData", "{")
    tracks, seen, title, owner, note = [], set(), "", "", ""
    if isinstance(data, dict):
        for d in walk(data):
            x = d.get("playlistVideoRenderer")
            if not isinstance(x, dict) or x.get("videoId") in seen:
                continue
            seen.add(x.get("videoId"))
            ti = "".join(r.get("text", "") for r in (x.get("title") or {}).get("runs", [])) or str((x.get("title") or {}).get("simpleText") or "")
            if not ti:
                continue
            by = "".join(r.get("text", "") for r in (x.get("shortBylineText") or {}).get("runs", []))
            th = (x.get("thumbnail") or {}).get("thumbnails") or [{}]
            vid = str(x.get("videoId") or "")
            tracks.append({"title": _s(ti, 120), "artist": _s(re.sub(r"\s*-\s*Topic$", "", by), 80),
                           "dur": int(x.get("lengthSeconds") or 0), "cover": _https(th[-1].get("url")),
                           "yt": vid if re.match(r"^[A-Za-z0-9_-]{11}$", vid) else ""})
        meta = next((d["playlistMetadataRenderer"] for d in walk(data) if isinstance(d.get("playlistMetadataRenderer"), dict)), {})
        title = _s(meta.get("title"), 80)
        for d in walk(data):
            h = d.get("playlistHeaderRenderer")
            if isinstance(h, dict):
                owner = "".join(r.get("text", "") for r in (h.get("ownerText") or {}).get("runs", []))
                break
    rss_err = ""
    if not tracks:
        try:
            r = _yt_rss(lid)
            tracks, title = r["tracks"], title or r["title"]
            if tracks:
                note = "YouTube отдал только первые %d треков плейлиста" % len(tracks)
        except Exception as e:
            rss_err = "RSS: %s %s" % (type(e).__name__, str(e)[:80])
    if not tracks:
        raise ImportFail("YouTube не отдал данные плейлиста. Он может быть закрытым (должен быть «по ссылке» или «открытый»)", (page_info(html) + (" | " + rss_err if rss_err else "")))
    return {"title": title, "owner": _s(owner, 60), "cover": tracks[0]["cover"], "tracks": tracks[:300], "skipped": 0, "note": note}


IMPORTERS = {"spotify": imp_spotify, "soundcloud": imp_soundcloud, "yandex": imp_yandex, "ytm": imp_ytm}


def _dur(txt):
    sec = 0
    for x in str(txt or "").split(":"):
        if not x.isdigit():
            return 0
        sec = sec * 60 + int(x)
    return sec


def _norm(x):
    x = re.sub(r"\(.*?\)|\[.*?\]", " ", str(x or "").lower())
    x = re.sub(r"\b(official|audio|video|lyrics|hd|hq|remastered|feat|ft)\b", " ", x)
    return " ".join(re.findall(r"\w+", x))


def find_library(meta, viewer):
    """та же песня уже загружена как файл: тогда она играет как обычный трек (в фоне и офлайн)"""
    tt, aa = _norm(meta.get("title")), _norm(str(meta.get("artist") or "").split(",")[0])
    if not tt:
        return None
    for t in DB["tracks"].values():
        if t.get("ghost") or not t.get("url") or not track_ok(t, viewer) or not visible_owner(t["owner"], viewer):
            continue
        if _norm(t["title"]) == tt:
            la = _norm(t.get("artist", ""))
            if not aa or not la or aa in la or la in aa:
                return t
    return None


def yt_candidates(t):
    """Находит на YouTube несколько подходящих видео (лучшее первым). Играют через официальный встроенный плеер."""
    title, artist, dur = t.get("title", ""), (t.get("artist") or ""), int(t.get("dur") or 0)
    q = ("%s %s audio" % (artist, title)).strip()
    html = fetch_text("https://www.youtube.com/results?search_query=" + urllib.parse.quote(q) + "&sp=EgIQAQ%253D%253D")
    data = json_after(html, "ytInitialData", "{")
    if not isinstance(data, dict):
        raise ImportFail("YouTube не отдал результаты поиска", page_info(html))
    cands = []
    for d in walk(data):
        v = d.get("videoRenderer")
        if isinstance(v, dict) and re.match(r"^[A-Za-z0-9_-]{11}$", str(v.get("videoId") or "")):
            vt = "".join(r.get("text", "") for r in (v.get("title") or {}).get("runs", []))
            cands.append((v["videoId"], vt, _dur((v.get("lengthText") or {}).get("simpleText"))))
        if len(cands) >= 10:
            break
    tl, al = title.lower(), artist.lower().split(",")[0].strip()
    scored = []
    for i, (vid, vt, secs) in enumerate(cands):
        if not secs or (secs > 1800 and not dur > 1500):
            continue
        vl, sc = vt.lower(), 0.0
        if tl and tl in vl:
            sc += 3
        if al and al in vl:
            sc += 2
        if dur:
            diff = abs(secs - dur)
            sc += 3 if diff <= max(6, dur * 0.06) else (1 if diff <= max(20, dur * 0.2) else -2)
        if re.search(r"live|концерт|cover|кавер|remix|ремикс|reaction|slowed|nightcore|8d", vl) and not re.search(r"live|remix|cover|slowed|nightcore|8d", tl):
            sc -= 2
        scored.append((sc - i * 0.1, vid))
    scored.sort(reverse=True)
    out = [v for _, v in scored[:6]]
    if not out:
        raise ValueError("Не нашёл этот трек на YouTube")
    return out


def yt_resolve(t):
    return yt_candidates(t)[0]


def run_import(url):
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https") or (u.hostname or "") not in IMPORT_HOSTS:
        raise ValueError("Поддерживаются ссылки Spotify, SoundCloud, Яндекс Музыки и YouTube Music")
    svc = IMPORT_HOSTS[u.hostname]
    if svc in ("spotify", "soundcloud") and u.hostname in ("spotify.link", "on.soundcloud.com"):
        url = fetch_redirect(url)
    d = IMPORTERS[svc](url)
    if not d["tracks"]:
        raise ValueError("Не нашёл треков. Плейлист может быть закрытым или пустым")
    d["service"] = svc
    d["note"] = d.get("note", "")
    d["tracks"] = d["tracks"][:300]
    if not d["title"]:
        d["title"] = "Импортированный плейлист"
    return d


def fetch_redirect(url):
    for _ in range(4):
        host = urlparse(url).hostname or ""
        if host not in IMPORT_HOSTS:
            raise ValueError("Недопустимый адрес")
        try:
            with urllib.request.build_opener(_NoRedirect).open(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=12):
                return url
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location") if e.headers else None
            if e.code in (301, 302, 303, 307, 308) and loc:
                url = urllib.parse.urljoin(url, loc)
                continue
            raise
    raise ValueError("Слишком много перенаправлений")


# ============================== СООБЩЕНИЯ ==============================
def conv_key(a, b):
    return "|".join(sorted([a.lower(), b.lower()]))


SOCIALS = ("tiktok", "youtube", "telegram", "instagram", "vk")
SOC_NAME = {"tiktok": "TikTok", "youtube": "YouTube", "telegram": "Telegram", "instagram": "Instagram", "vk": "VK"}
SOC_DOM = {"tiktok": r"tiktok\.com", "youtube": r"(?:youtube\.com|youtu\.be)", "telegram": r"(?:t\.me|telegram\.me)",
           "instagram": r"instagram\.com", "vk": r"vk\.com"}


def norm_social(key, raw):
    """ник или ссылка -> чистый ник. "" если пусто, None если не распознали"""
    v = str(raw or "").strip()
    if not v:
        return ""
    m = re.match(r"^(?:https?://)?(?:www\.|m\.)?" + SOC_DOM[key] + r"/(.*)$", v, re.I)
    if m:
        path = m.group(1).split("?")[0].split("#")[0].strip("/")
        if key == "youtube" and re.match(r"^(channel|c|user)/[\w.-]{2,60}$", path, re.I):
            return path
        v = path.split("/")[0]
    v = v.lstrip("@")
    if key == "youtube" and re.match(r"^(channel|c|user)/[\w.-]{2,60}$", v, re.I):
        return v
    return v if re.match(r"^[A-Za-z0-9._-]{2,40}$", v) else None


def is_blocked(a, b):
    """a заблокировал b"""
    return b["name"].lower() in (a.get("blocked") or [])


def pl_comment_pub(c, p, viewer):
    u = DB["users"].get(c["user"].lower()) or {}
    adm = viewer is not None and is_admin(viewer)
    return {"id": c["id"], "user": c["user"], "display": u.get("display") or c["user"], "avatar": u.get("avatar", ""),
            "op": c["user"] == p["owner"], "text": c["text"], "t": c["t"],
            "can_del": viewer is not None and (viewer["name"] == c["user"] or viewer["name"] == p["owner"] or adm)}


def can_message(me, other):
    if other.get("banned"):
        return False, "Пользователь недоступен"
    if me["name"].lower() == other["name"].lower():
        return False, "Нельзя писать самому себе"
    if is_blocked(me, other):
        return False, "Ты заблокировал этого пользователя"
    if is_blocked(other, me):
        return False, "Пользователь ограничил переписку с тобой"
    if other.get("private") and not is_admin(me):
        c = DB["convs"].get(conv_key(me["name"], other["name"]))
        if not c or not any(m["from"] == other["name"].lower() for m in c["msgs"]):
            return False, "Профиль закрыт: ему можно писать только после того, как он сам тебе напишет"
    return True, ""


RX_OK = ("❤️", "👍", "👎", "😂", "😮", "😢", "🔥", "🎉")
RX_CANON = {e.replace("\ufe0f", ""): e for e in RX_OK}


def find_msg(me, mid):
    for key in me.get("chats", []):
        c = DB["convs"].get(key)
        if not c:
            continue
        for m in c["msgs"]:
            if m["id"] == mid:
                return c, m
    return None, None


def fmt_msg(m, me_low):
    cnt = {}
    for e in (m.get("rx") or {}).values():
        cnt[e] = cnt.get(e, 0) + 1
    rx = [{"e": e, "n": cnt[e]} for e in RX_OK if e in cnt]
    return {"id": m["id"], "mine": m["from"] == me_low, "text": m["text"], "t": m["t"], "read": m["read"],
            "edited": bool(m.get("edited")), "rx": rx, "my": (m.get("rx") or {}).get(me_low, "")}


# ============================== ЛЕНТА: ПОСТЫ И КОММЕНТАРИИ ==============================
def anon_ids():
    return {p["track"] for p in DB["posts"].values() if p.get("anon")}


def post_visible(p, viewer):
    t = DB["tracks"].get(p["track"])
    if not t or t.get("private") or t.get("ghost"):
        return False
    if viewer is not None and (viewer["name"] == p["owner"] or is_admin(viewer)):
        return True
    return visible_owner(p["owner"], viewer)


def comment_pub(c, p, viewer):
    u = DB["users"].get(c["user"].lower()) or {}
    op = c["user"] == p["owner"]
    privileged = viewer is not None and (viewer["name"] == p["owner"] or is_admin(viewer))
    hide = op and p.get("anon") and not privileged
    return {"id": c["id"], "user": "" if hide else c["user"],
            "display": "Аноним" if hide else (u.get("display") or c["user"]),
            "avatar": "" if hide else u.get("avatar", ""), "op": op, "text": c["text"], "t": c["t"],
            "can_del": viewer is not None and (viewer["name"] == c["user"] or privileged)}


def post_pub(p, viewer, full=False):
    t = DB["tracks"].get(p["track"])
    if not t:
        return None
    anon = bool(p.get("anon"))
    mine = viewer is not None and viewer["name"] == p["owner"]
    show = (not anon) or mine or (viewer is not None and is_admin(viewer))
    tp = track_pub(t)
    author = None
    if show:
        ow = DB["users"].get(p["owner"].lower()) or {}
        author = {"name": p["owner"], "display": ow.get("display") or p["owner"], "avatar": ow.get("avatar", "")}
    else:
        tp["owner"] = ""
    cs = p.get("comments", [])
    return {"id": p["id"], "text": p.get("text", ""), "anon": anon, "mine": mine, "created": p["created"],
            "track": tp, "author": author, "ncom": len(cs),
            "comments": [comment_pub(c, p, viewer) for c in (cs if full else cs[-2:])],
            "can_del": mine or (viewer is not None and is_admin(viewer))}


def purge_files():
    """удаляет файлы, на которые больше нет ссылок в базе"""
    ref = set(re.findall(r"/files/([0-9a-f]{32}\.[a-z0-9]{2,5})", json.dumps(DB, ensure_ascii=False)))
    n = 0
    try:
        names = os.listdir(FILES)
    except OSError:
        return 0
    for fn in names:
        if FILE_NAME.match(fn) and fn not in ref:
            try:
                os.remove(os.path.join(FILES, fn))
                n += 1
            except Exception:
                pass
    return n


def wipe_db(what):
    """чистка базы. Аккаунт администратора остаётся всегда"""
    keep = {n for n, u in DB["users"].items() if is_admin(u)}
    if what in ("users", "all"):
        for n in [n for n in DB["users"] if n not in keep]:
            del DB["users"][n]
        DB["tokens"] = {k: v for k, v in DB["tokens"].items() if v in keep}
        DB["imp"] = {k: v for k, v in DB["imp"].items() if k in DB["tokens"]}
        DB["sess"] = {k: v for k, v in DB["sess"].items() if k in DB["tokens"]}
        DB["devs"] = {}
        DB["tracks"] = {k: t for k, t in DB["tracks"].items() if t["owner"].lower() in keep}
        DB["playlists"] = {k: p for k, p in DB["playlists"].items() if p["owner"].lower() in keep}
        DB["posts"] = {k: p for k, p in DB["posts"].items() if p["owner"].lower() in keep and p["track"] in DB["tracks"]}
        for p in DB["posts"].values():
            p["comments"] = [c for c in p.get("comments", []) if c["user"].lower() in keep]
        for pl_ in DB["playlists"].values():
            pl_["comments"] = [c for c in pl_.get("comments", []) if c["user"].lower() in keep]
            pl_["rate"] = {k: v for k, v in (pl_.get("rate") or {}).items() if k in keep}
        DB["convs"] = {k: c for k, c in DB["convs"].items() if c["a"] in keep and c["b"] in keep}
        for u in DB["users"].values():
            u["chats"] = [k for k in u.get("chats", []) if k in DB["convs"]]
            u["saved"] = [i for i in u.get("saved", []) if i in DB["playlists"]]
    if what in ("tracks", "all"):
        DB["tracks"] = {}
        DB["posts"] = {}
        for p in DB["playlists"].values():
            p["tracks"] = []
        for u in DB["users"].values():
            u["recent"] = []
            u["pin"] = ""
            u["plays"] = {}
            u["listen_sec"] = 0
            u["now"] = ""
    if what == "posts":
        DB["posts"] = {}
    if what in ("chats", "all"):
        DB["convs"] = {}
        for u in DB["users"].values():
            u["chats"] = []
    if what in ("reports", "all"):
        DB["reports"] = []
    if what == "all":
        DB["playlists"] = {}
        for u in DB["users"].values():
            u["saved"] = []


# ============================== ПРИЛОЖЕНИЕ (PWA) ==============================
MANIFEST = {"name": "PiXeL Music", "short_name": "PiXeL Music", "start_url": "/", "scope": "/",
            "display": "standalone", "orientation": "portrait", "background_color": "#3d7bff",
            "theme_color": "#06080f",
            "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
                      {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}]}

SW_JS = r"""
const C = 'pixel-shell-v3', AUDIO = 'pixel-audio';
const SCOPE = self.registration.scope;
self.addEventListener('install', e => { e.waitUntil(caches.open(C).then(c => c.add(SCOPE)).catch(() => {})); self.skipWaiting(); });
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(k => Promise.all(k.filter(x => x !== C && x !== AUDIO).map(x => caches.delete(x)))).then(() => self.clients.claim()));
});
async function fromAudio(req) {
  const c = await caches.open(AUDIO);
  const hit = await c.match(req.url);
  if (!hit) return fetch(req);
  const rng = req.headers.get('range');
  if (!rng) return hit;
  const buf = await hit.arrayBuffer();
  const m = /bytes=(\d*)-(\d*)/.exec(rng);
  let s = 0, e = buf.byteLength - 1;
  if (m) {
    if (m[1] !== '') { s = +m[1]; if (m[2] !== '') e = Math.min(+m[2], e); }
    else if (m[2] !== '') { s = Math.max(0, buf.byteLength - +m[2]); }
  }
  return new Response(buf.slice(s, e + 1), { status: 206, headers: {
    'Content-Type': hit.headers.get('Content-Type') || 'audio/mpeg',
    'Content-Range': 'bytes ' + s + '-' + e + '/' + buf.byteLength,
    'Content-Length': String(e - s + 1), 'Accept-Ranges': 'bytes' } });
}
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== location.origin) return;
  if (u.pathname.startsWith('/api/')) return;
  if (u.pathname.startsWith('/files/')) { e.respondWith(fromAudio(e.request)); return; }
  e.respondWith(fetch(e.request).then(r => { const cp = r.clone(); caches.open(C).then(c => c.put(e.request, cp)).catch(() => {}); return r; })
    .catch(() => caches.match(e.request).then(r => r || caches.match(SCOPE))));
});
"""

_ICONS = {}


def make_icon(size):
    """PNG-иконка приложения: белая буква P на синем фоне (рисуется без библиотек)."""
    if size in _ICONS:
        return _ICONS[size]
    import zlib, struct
    bg = (61, 123, 255)
    wh = (255, 255, 255)
    cells = set([(0, y) for y in range(7)] + [(x, 0) for x in (1, 2, 3)] + [(x, 3) for x in (1, 2, 3)] + [(4, 1), (4, 2)])
    u = size * 0.60 / 7.0
    ox = (size - 5 * u) / 2.0
    oy = (size - 7 * u) / 2.0

    def idx(px, off, n):
        q = (px - off) / u
        if q < 0 or q >= n:
            return None
        return int(q)

    cmap = [idx(x, ox, 5) for x in range(size)]
    rowc = {}
    rows = []
    for y in range(size):
        cy = idx(y, oy, 7)
        if cy not in rowc:
            row = bytearray([0])
            for x in range(size):
                cx = cmap[x]
                row += bytes(wh if (cx is not None and cy is not None and (cx, cy) in cells) else bg)
            rowc[cy] = bytes(row)
        rows.append(rowc[cy])

    def chunk(t, data):
        c = struct.pack(">I", len(data)) + t + data
        return c + struct.pack(">I", zlib.crc32(t + data) & 0xffffffff)

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) +
           chunk(b"IDAT", zlib.compress(b"".join(rows), 6)) + chunk(b"IEND", b""))
    _ICONS[size] = png
    return png


# ============================== ЗАЩИТА ==============================
LOGINF = {}     # неудачные входы: (ip, ник) -> [время]
REGLOG = {}     # регистрации: ip -> [время]
RATE = {}       # лимиты сообщений: ключ -> [время]
YTC = {}        # найденные видео для треков из импорта без записи в базе: (название, исполнитель) -> [id видео]


def rate_ok(key, limit, window):
    now = time.time()
    lst = [t for t in RATE.get(key, []) if now - t < window]
    if len(lst) >= limit:
        RATE[key] = lst
        return False
    lst.append(now)
    RATE[key] = lst
    return True


# ============================== СЕРВЕР ==============================
class H(BaseHTTPRequestHandler):
    server_version = "PiXeL/2.0"

    def log_message(self, *a):
        pass

    # ---- помощники
    def js(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def err(self, msg, code=400, **extra):
        d = {"error": msg}
        d.update(extra)
        self.js(d, code)

    def send_bytes(self, b, ctype, extra=None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-cache")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def is_local(self):
        """запрос с этого же устройства (не через туннель/прокси)"""
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            return False
        for k in ("X-Forwarded-For", "Cf-Connecting-Ip", "X-Real-Ip", "Forwarded"):
            if self.headers.get(k):
                return False
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        return host in ("127.0.0.1", "localhost", "::1", "")

    def ip(self):
        peer = self.client_address[0]
        trusted = TRUST_PROXY or peer in ("127.0.0.1", "::1")
        cf = self.headers.get("Cf-Connecting-Ip", "")
        if trusted and cf:
            return cf.strip()[:64]
        xff = self.headers.get("X-Forwarded-For", "")
        if trusted and xff:
            return xff.split(",")[0].strip()[:64]
        return peer

    def dev(self):
        d = self.headers.get("X-Dev", "")
        return d if re.match(r"^[0-9a-f]{16,64}$", d) else ""

    def me(self):
        t = self.headers.get("X-Token", "")
        with LOCK:
            n = DB["tokens"].get(t)
            u = DB["users"].get(n) if n else None
            if u and t not in DB["imp"]:        # вход админа «как пользователь» не делает его «в сети»
                now = time.time()
                u["last"] = now
                sx = DB["sess"].get(t)
                if sx is None:
                    DB["sess"][t] = {"ua": self.headers.get("User-Agent", "")[:300], "ip": self.ip(), "t": int(now), "last": now}
                elif now - sx.get("last", 0) > 20:
                    sx["last"] = now
                    sx["ip"] = self.ip()
            return u

    def need_user(self):
        u = self.me()
        if not u:
            self.err("Войди в аккаунт (сессия закончилась)", 401)
            return None
        if u.get("banned"):
            self.err("Аккаунт заблокирован администратором", 403, banned=True)
            return None
        return u

    def need_admin(self):
        u = self.need_user()
        if not u:
            return None
        if not is_admin(u):
            self.err("Нет доступа", 403)
            return None
        return u

    def body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > 300000:
            return {}
        try:
            d = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def new_session(self, tok, low):
        now = time.time()
        DB["sess"][tok] = {"ua": self.headers.get("User-Agent", "")[:300], "ip": self.ip(), "t": int(now), "last": now}
        mine = [(v.get("last", 0), k) for k, v in DB["sess"].items() if DB["tokens"].get(k) == low and k not in DB["imp"]]
        for _, k in sorted(mine)[:-15]:           # храним не больше 15 устройств на аккаунт
            DB["sess"].pop(k, None)
            DB["tokens"].pop(k, None)

    def reg_check(self):
        if self.is_local():
            return None
        now = time.time()
        ip = self.ip()
        lst = [t for t in REGLOG.get(ip, []) if now - t < 86400]
        REGLOG[ip] = lst
        if lst and now - lst[-1] < REG_COOLDOWN:
            return "Подожди немного перед следующей регистрацией"
        if len(lst) >= REG_PER_IP_DAY:
            return "С этого устройства уже создано слишком много аккаунтов. Попробуй завтра"
        d = self.dev()
        if d and DB["devs"].get(d, 0) >= REG_PER_DEVICE:
            return "На этом устройстве уже создано максимум аккаунтов"
        return None

    def reg_mark(self):
        if self.is_local():
            return
        REGLOG.setdefault(self.ip(), []).append(time.time())
        d = self.dev()
        if d:
            DB["devs"][d] = DB["devs"].get(d, 0) + 1

    def nick_problem(self, name):
        if not valid_nick(name):
            return "Ник: 3–24 символа, латиница, цифры, _ и . (не в начале и не в конце)"
        low = name.lower()
        if low in DB["users"]:
            return "Этот ник уже занят"
        if low in RESERVED or (low in ADMINS and not self.is_local()):
            return "Этот ник зарезервирован"
        return None

    # ---- файлы с поддержкой Range (нужно для перемотки аудио)
    def serve_file(self, path):
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        start, end, code = 0, size - 1, 200
        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)$", rng.strip())
            if m and (m.group(1) or m.group(2)):
                if m.group(1) == "":
                    start = max(0, size - int(m.group(2)))
                else:
                    start = int(m.group(1))
                    if m.group(2):
                        end = min(int(m.group(2)), size - 1)
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", "bytes */%d" % size)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                code = 206
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "public, max-age=86400")
        if code == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.end_headers()
        left = end - start + 1
        with open(path, "rb") as f:
            f.seek(start)
            while left > 0:
                chunk = f.read(min(65536, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    # ---- маршрутизация
    def do_GET(self):
        self.safe(self.route_get)

    def do_POST(self):
        self.safe(self.route_post)

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def safe(self, fn):
        try:
            fn()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:
            try:
                rid = add_report("server", "", "%s %s\n%s" % (self.command, self.path.split("?")[0], traceback.format_exc()), self.headers.get("User-Agent", ""))
                self.err("Ошибка сервера (%s). Код: %s" % (e, rid), 500, report=rid)
            except Exception:
                pass

    # ============================== GET ==============================
    def route_get(self):
        u = urlparse(self.path)
        p = u.path
        q = {k: v[0] for k, v in parse_qs(u.query).items()}

        if p in ("/", "/index.html"):
            b = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b)
            return
        if p == "/manifest.webmanifest":
            return self.send_bytes(json.dumps(MANIFEST, ensure_ascii=False).encode("utf-8"), "application/manifest+json")
        if p == "/sw.js":
            return self.send_bytes(SW_JS.encode("utf-8"), "text/javascript; charset=utf-8", {"Service-Worker-Allowed": "/"})
        if p in ("/icon-192.png", "/icon-512.png"):
            return self.send_bytes(make_icon(192 if "192" in p else 512), "image/png")
        if p.startswith("/files/"):
            name = unquote(p[7:])
            if not FILE_NAME.match(name):
                return self.err("Не найдено", 404)
            fp = os.path.join(FILES, name)
            if not os.path.isfile(fp):
                return self.err("Не найдено", 404)
            return self.serve_file(fp)

        # ---- публичные
        if p == "/api/config":
            return self.js({"public_url": PUBLIC_URL})
        if p == "/api/nick":
            n = (q.get("n") or "").strip()
            pr = self.nick_problem(n)
            return self.js({"ok": pr is None, "msg": pr or "Ник свободен"})
        if p == "/api/playlist":
            me = self.me()
            with LOCK:
                pl = DB["playlists"].get(q.get("id", ""))
                if not pl or (pl.get("fav") and not (me and me["name"] == pl["owner"])):
                    return self.err("Плейлист не найден", 404)
                tr = [track_pub(DB["tracks"][i]) for i in pl["tracks"] if i in DB["tracks"] and track_ok(DB["tracks"][i], me)]
                return self.js({"playlist": pl_pub(pl, me), "tracks": tr,
                                "saved": bool(me) and pl["id"] in me.get("saved", []),
                                "comments": [pl_comment_pub(c, pl, me) for c in pl.get("comments", [])] if not pl.get("fav") else []})

        # ---- нужен вход
        me = self.need_user()
        if not me:
            return
        low = me["name"].lower()

        if p == "/api/me":
            with LOCK:
                return self.js({"user": pub(me, True), "tracks": user_tracks(me["name"], me),
                                "playlists": user_pls(me["name"], me), "saved": saved_pls(me),
                                "recent": recent_tracks(me, me), "fav_ids": fav_ids(me)})

        if p == "/api/user":
            with LOCK:
                t = DB["users"].get((q.get("name") or "").lower())
                if not t or t.get("banned"):
                    return self.err("Пользователь не найден", 404)
                d = pub(t, viewer=me)
                if d["locked"]:
                    return self.js({"user": d, "tracks": [], "playlists": [], "recent": []})
                return self.js({"user": d, "tracks": user_tracks(t["name"], me), "playlists": user_pls(t["name"], me),
                                "recent": recent_tracks(t, me) if t.get("show_listen", True) else []})

        if p == "/api/search":
            s = (q.get("q") or "").strip().lower().lstrip("@")
            with LOCK:
                res = []
                if not s:      # подсказки: кто сейчас онлайн и новые люди
                    sug = sorted([t for t in DB["users"].values() if not t.get("banned") and t is not me],
                                 key=lambda t: t.get("last", 0), reverse=True)
                    return self.js({"users": [pub(t, viewer=me) for t in sug[:14]]})
                for t in DB["users"].values():
                    if t.get("banned"):
                        continue
                    if s in t["name"].lower() or s in (t.get("display") or "").lower():
                        res.append(pub(t, viewer=me))
                res.sort(key=lambda x: (not x["name"].lower().startswith(s), x["name"]))
                return self.js({"users": res[:30]})

        if p == "/api/feed":
            with LOCK:
                anon = anon_ids()
                ps = [x for x in DB["playlists"].values() if x["owner"] != me["name"] and not x.get("fav") and visible_owner(x["owner"], me)]
                ps.sort(key=lambda x: x["created"], reverse=True)
                ts = [x for x in DB["tracks"].values() if not x.get("ghost") and not x.get("private") and visible_owner(x["owner"], me)
                      and not (x["id"] in anon and x["owner"] != me["name"])]
                ts.sort(key=lambda x: x["created"], reverse=True)
                xs = sorted(DB["posts"].values(), key=lambda x: x["created"], reverse=True)
                posts = [y for y in (post_pub(x, me) for x in xs if post_visible(x, me)) if y][:40]
                return self.js({"posts": posts, "playlists": [pl_pub(x) for x in ps[:20]], "tracks": [track_pub(x) for x in ts[:60]]})

        if p == "/api/post":
            with LOCK:
                x = DB["posts"].get(q.get("id", ""))
                if not x or not post_visible(x, me):
                    return self.err("Пост не найден", 404)
                return self.js({"post": post_pub(x, me, True)})

        if p == "/api/tracks":
            s = (q.get("q") or "").strip().lower()
            with LOCK:
                ts = sorted(DB["tracks"].values(), key=lambda x: x["created"], reverse=True)
                anon = anon_ids()
                out = []
                for t in ts:
                    if t.get("ghost") or not track_ok(t, me) or not visible_owner(t["owner"], me) or (t["id"] in anon and t["owner"] != me["name"] and not is_admin(me)):
                        continue
                    if s and s not in ("%s %s %s" % (t["title"], t.get("artist", ""), t["owner"])).lower():
                        continue
                    out.append(track_pub(t))
                    if len(out) >= 40:
                        break
                return self.js({"tracks": out})

        if p == "/api/blocks":
            with LOCK:
                return self.js({"users": [pub(DB["users"][k], viewer=me) for k in me.get("blocked", []) if k in DB["users"]]})

        if p == "/api/playlists":
            s_ = (q.get("q") or "").strip().lower().lstrip("@")
            with LOCK:
                out = []
                for x in DB["playlists"].values():
                    if x.get("fav") or not visible_owner(x["owner"], me):
                        continue
                    if not [i for i in x["tracks"] if i in DB["tracks"]]:
                        continue
                    ow = DB["users"].get(x["owner"].lower()) or {}
                    if s_ and s_ not in ("%s %s %s %s" % (x["name"], x["owner"], ow.get("display", ""), x.get("desc", ""))).lower():
                        continue
                    out.append(x)

                def score(x):
                    rt = x.get("rate") or {}
                    avg = sum(rt.values()) / len(rt) if rt else 0
                    return int(x.get("plays", 0)) + 3 * len(x.get("comments", [])) + 2 * len(rt) * avg
                out.sort(key=lambda x: (not (s_ and x["name"].lower().startswith(s_)), -score(x)))
                return self.js({"playlists": [pl_pub(x, me) for x in out[:40]]})

        if p == "/api/chats":
            with LOCK:
                out = []
                for key in me.get("chats", []):
                    c = DB["convs"].get(key)
                    if not c or not c["msgs"]:
                        continue
                    other = DB["users"].get(c["a"] if c["b"] == low else c["b"])
                    if not other or other.get("banned"):
                        continue
                    last = c["msgs"][-1]
                    unread = sum(1 for m in c["msgs"] if m["to"] == low and not m["read"])
                    out.append({"user": pub(other, viewer=me), "unread": unread,
                                "last": {"text": last["text"][:120], "t": last["t"], "mine": last["from"] == low}})
                out.sort(key=lambda x: x["last"]["t"], reverse=True)
                return self.js({"chats": out})

        if p == "/api/chat":
            with LOCK:
                other = DB["users"].get((q.get("with") or "").lower())
                if not other or other.get("banned"):
                    return self.err("Пользователь не найден", 404)
                c = DB["convs"].get(conv_key(low, other["name"]))
                try:
                    after = int(q.get("after") or 0)
                except ValueError:
                    after = 0
                msgs, ru, changed, sync = [], 0, False, None
                if c:
                    for m in c["msgs"]:
                        if m["to"] == low and not m["read"]:
                            m["read"] = True
                            changed = True
                    sel = [m for m in c["msgs"] if m["id"] > after] if after > 0 else c["msgs"][-100:]
                    msgs = [fmt_msg(m, low) for m in sel]
                    if after > 0:
                        sync = [fmt_msg(m, low) for m in c["msgs"][-100:]]
                    ru = max([m["id"] for m in c["msgs"] if m["from"] == low and m["read"]] or [0])
                if changed:
                    save_db(True)
                ok, why = can_message(me, other)
                return self.js({"msgs": msgs, "ru": ru, "sync": sync, "mid": DB["mid"], "peer": pub(other, viewer=me), "canSend": ok, "why": why,
                                "iblock": is_blocked(me, other), "blocked_me": is_blocked(other, me)})

        if p == "/api/poll":
            try:
                after = int(q.get("after") or -1)
            except ValueError:
                after = -1
            with LOCK:
                unread, new = 0, []
                for key in me.get("chats", []):
                    c = DB["convs"].get(key)
                    if not c:
                        continue
                    for m in c["msgs"]:
                        if m["to"] == low and not m["read"]:
                            unread += 1
                            if after >= 0 and m["id"] > after:
                                new.append(m)
                new.sort(key=lambda m: m["id"])
                out = []
                for m in new[-5:]:
                    s = DB["users"].get(m["from"]) or {}
                    out.append({"id": m["id"], "from": s.get("name", m["from"]), "display": s.get("display") or s.get("name", ""),
                                "avatar": s.get("avatar", ""), "text": m["text"][:140], "t": m["t"]})
                return self.js({"unread": unread, "msgs": out, "mid": DB["mid"]})

        if p == "/api/devices":
            with LOCK:
                now = time.time()
                cur = self.headers.get("X-Token", "")
                out = []
                for tk, v in DB["tokens"].items():
                    if v != low or tk in DB["imp"]:
                        continue
                    sx = DB["sess"].get(tk) or {"ua": "", "ip": "", "t": int(now), "last": now}
                    d = parse_ua(sx.get("ua", ""))
                    d.update({"sid": sid_of(tk), "ip": sx.get("ip", ""), "t": sx.get("t", 0), "seen": int(max(0, now - sx.get("last", now))),
                              "online": now - sx.get("last", 0) < 120, "current": tk == cur})
                    out.append(d)
                out.sort(key=lambda x: (not x["current"], x["seen"]))
                return self.js({"devices": out})

        if p == "/api/stats":
            with LOCK:
                plays = {i: c for i, c in me.get("plays", {}).items() if i in DB["tracks"]}
                tot = sum(plays.values())
                mins = int(me.get("listen_sec", 0) / 60)
                top = sorted(plays.items(), key=lambda kv: -kv[1])[:5]
                ar = {}
                for i, c in plays.items():
                    a = DB["tracks"][i].get("artist") or ""
                    if a:
                        ar[a] = ar.get(a, 0) + c
                return self.js({"plays": tot, "minutes": mins, "uniq": len(plays),
                                "top": [{"track": track_pub(DB["tracks"][i]), "count": c} for i, c in top],
                                "artists": [{"name": a, "count": c} for a, c in sorted(ar.items(), key=lambda kv: -kv[1])[:5]]})

        if p == "/api/import":
            if not rate_ok("i:" + low, 6, 60):
                return self.err("Подожди минуту: слишком много запросов импорта", 429)
            try:
                return self.js(run_import(q.get("url") or ""))
            except ImportFail as e:
                return self.err(str(e)[:400], 422, detail=e.detail)
            except ValueError as e:
                return self.err(str(e)[:200], 422)
            except urllib.error.HTTPError as e:
                return self.err("Сервис ответил ошибкой %s. Возможно, плейлист закрытый" % e.code, 502, detail="HTTP %s" % e.code)
            except (urllib.error.URLError, socket.timeout, OSError) as e:
                return self.err("Не удалось связаться с сервисом. Проверь интернет на устройстве, где запущен сервер (в некоторых странах сервисы закрыты без VPN)", 502, detail="%s: %s" % (type(e).__name__, str(e)[:120]))
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
                return self.err("Сервис изменил страницу, прочитать плейлист не получилось", 502, detail="%s: %s" % (type(e).__name__, str(e)[:120]))

        if p == "/api/admin/reports":
            if not self.need_admin():
                return
            with LOCK:
                return self.js({"reports": [{k: r[k] for k in ("id", "t", "kind", "user", "text", "ua")} for r in reversed(DB["reports"][-60:])],
                                "total": len(DB["reports"])})

        if p == "/api/admin/stats":
            if not self.need_admin():
                return
            with LOCK:
                now = time.time()
                return self.js({"users": len(DB["users"]), "tracks": len(DB["tracks"]), "posts": len(DB["posts"]), "playlists": len(DB["playlists"]),
                                "messages": sum(len(c["msgs"]) for c in DB["convs"].values()),
                                "online": sum(1 for u in DB["users"].values() if now - u.get("last", 0) < 120)})

        if p == "/api/admin/posts":
            if not self.need_admin():
                return
            with LOCK:
                xs = sorted(DB["posts"].values(), key=lambda x: x["created"], reverse=True)
                return self.js({"posts": [y for y in (post_pub(x, me) for x in xs[:60]) if y], "total": len(DB["posts"])})

        if p == "/api/admin/tracks":
            if not self.need_admin():
                return
            s_ = (q.get("q") or "").strip().lower()
            with LOCK:
                posted = {x["track"] for x in DB["posts"].values()}
                out = []
                for t in sorted(DB["tracks"].values(), key=lambda x: x["created"], reverse=True):
                    if t.get("ghost"):
                        continue
                    if s_ and s_ not in ("%s %s %s" % (t["title"], t.get("artist", ""), t["owner"])).lower():
                        continue
                    out.append({"id": t["id"], "title": t["title"], "artist": t.get("artist", ""), "owner": t["owner"],
                                "private": bool(t.get("private")), "cover": t.get("cover", ""), "posted": t["id"] in posted})
                    if len(out) >= 40:
                        break
                return self.js({"tracks": out, "total": len(DB["tracks"])})

        if p == "/api/admin/users":
            if not self.need_admin():
                return
            s = (q.get("q") or "").strip().lower().lstrip("@")
            with LOCK:
                now = time.time()
                out = []
                for u in sorted(DB["users"].values(), key=lambda x: x.get("created", 0), reverse=True):
                    if s and s not in u["name"].lower() and s not in (u.get("display") or "").lower():
                        continue
                    out.append({"name": u["name"], "display": u.get("display") or u["name"], "avatar": u.get("avatar", ""),
                                "created": int(u.get("created", 0)), "online": now - u.get("last", 0) < 120,
                                "banned": bool(u.get("banned")), "private": bool(u.get("private")),
                                "tags": list(u.get("tags", [])), "admin": is_admin(u),
                                "tracks": sum(1 for t in DB["tracks"].values() if t["owner"] == u["name"])})
                    if len(out) >= 60:
                        break
                return self.js({"users": out})

        self.err("Не найдено", 404)

    # ============================== POST ==============================
    def route_post(self):
        u = urlparse(self.path)
        p = u.path
        q = {k: v[0] for k, v in parse_qs(u.query).items()}

        if p in ("/api/register", "/api/login"):
            d = self.body()
            name = str(d.get("username", "")).strip()
            pw = str(d.get("password", ""))
            with LOCK:
                if p == "/api/register":
                    pr = self.nick_problem(name)
                    if pr:
                        return self.err(pr)
                    if len(pw) < 6:
                        return self.err("Пароль слишком короткий (минимум 6 символов)")
                    if pw.lower() == name.lower() or pw.lower() in WEAK_PW:
                        return self.err("Слишком простой пароль, придумай другой")
                    e = self.reg_check()
                    if e:
                        return self.err(e, 429)
                    salt = secrets.token_hex(8)
                    user = {"name": name, "display": name, "salt": salt, "hash": hash_pw(pw, salt),
                            "bio": "", "status": "Слушаю музыку", "avatar": "", "banner": "", "tags": [],
                            "saved": [], "chats": [], "created": time.time(), "last": time.time()}
                    DB["users"][name.lower()] = user
                    self.reg_mark()
                else:
                    key = (self.ip(), name.lower())
                    now = time.time()
                    fl = [t for t in LOGINF.get(key, []) if now - t < 600]
                    LOGINF[key] = fl
                    if len(fl) >= 6:
                        return self.err("Слишком много неудачных попыток. Подожди %d мин." % ((600 - (now - fl[0])) // 60 + 1), 429)
                    user = DB["users"].get(name.lower())
                    if not user or not user.get("hash") or not secrets.compare_digest(user["hash"], hash_pw(pw, user["salt"])):
                        fl.append(now)
                        return self.err("Неверный ник или пароль")
                    if user.get("banned"):
                        return self.err("Аккаунт заблокирован администратором", 403, banned=True)
                    LOGINF.pop(key, None)
                tok = secrets.token_hex(24)
                DB["tokens"][tok] = user["name"].lower()
                self.new_session(tok, user["name"].lower())
                user["last"] = time.time()
                save_db()
                return self.js({"token": tok, "user": pub(user, True)})

        if p == "/api/report":
            d = self.body()
            text = str(d.get("text", "")).strip()[:6000]
            if not text:
                return self.err("Пустой отчёт")
            if not rate_ok("r:" + self.ip(), 8, 3600):
                return self.err("Слишком много отчётов. Попробуй позже", 429)
            u0 = self.me()
            rid = add_report("client", u0["name"] if u0 else "", text, self.headers.get("User-Agent", ""))
            return self.js({"id": rid})

        me = self.need_user()
        if not me:
            return
        low = me["name"].lower()

        if p == "/api/fav":
            d = self.body()
            with LOCK:
                tid = str(d.get("track", ""))
                t = DB["tracks"].get(tid)
                if not t or not track_ok(t, me) or not (t["owner"] == me["name"] or visible_owner(t["owner"], me)):
                    return self.err("Трек не найден", 404)
                fp = fav_playlist(me)
                if tid in fp["tracks"]:
                    fp["tracks"].remove(tid)
                    gc_ghosts()
                    r = False
                else:
                    if len(fp["tracks"]) >= 500:
                        return self.err("В любимом уже 500 треков")
                    fp["tracks"].append(tid)
                    r = True
                save_db()
                return self.js({"fav": r})

        if p == "/api/resolve":
            d = self.body()
            tid, bad = str(d.get("id", "")), str(d.get("bad", ""))
            with LOCK:
                t = DB["tracks"].get(tid) if tid else None
                if tid and (not t or not t.get("ghost")):
                    return self.err("Трек не найден", 404)
                if t is None:
                    title = _s(d.get("title"), 120)
                    if not title:
                        return self.err("Нет названия трека")
                    try:
                        dur0 = int(d.get("dur") or 0)
                    except (TypeError, ValueError):
                        dur0 = 0
                    meta = {"title": title, "artist": _s(d.get("artist"), 80), "dur": dur0}
                    key = (meta["title"].lower(), meta["artist"].lower())
                else:
                    meta, key = t, None
                if not bad:
                    lib = find_library(meta, me)
                    if lib:
                        if t is not None:
                            t["link"] = lib["id"]
                            save_db(True)
                            return self.js({"track": track_pub(t)})
                        return self.js({"track": {"url": lib["url"], "ghost": False, "linked": True,
                                                  "cover": lib.get("cover", ""), "dur": lib.get("dur", 0)}})
                cands = list((t.get("ytc") if t is not None else YTC.get(key)) or [])
                if t is not None and t.get("yt") and t["yt"] not in cands:
                    cands.insert(0, t["yt"])
            vid = None
            if bad and bad in cands and cands.index(bad) + 1 < len(cands):
                vid = cands[cands.index(bad) + 1]
            elif not bad and cands:
                vid = cands[0]
            if vid is None:
                if not rate_ok("rs:" + low, 15, 60):
                    return self.err("Слишком часто. Подожди несколько секунд", 429)
                try:
                    found = yt_candidates(meta)
                except ImportFail as e:
                    return self.err(str(e)[:200], 422, detail=e.detail)
                except ValueError as e:
                    return self.err(str(e)[:200], 422)
                except urllib.error.HTTPError as e:
                    return self.err("YouTube ответил ошибкой %s" % e.code, 502, detail="HTTP %s" % e.code)
                except (urllib.error.URLError, socket.timeout, OSError) as e:
                    return self.err("Сервер не может открыть YouTube. Если он закрыт в твоей стране, включи VPN на устройстве, где запущен сервер", 502, detail="%s: %s" % (type(e).__name__, str(e)[:120]))
                except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
                    return self.err("YouTube изменил страницу, найти трек не получилось", 502, detail="%s: %s" % (type(e).__name__, str(e)[:120]))
                cands = cands + [x for x in found if x not in cands]
                if bad:
                    nxt = cands.index(bad) + 1 if bad in cands else 0
                    if nxt >= len(cands):
                        return self.err("Для этого трека больше нет вариантов. Привяжи свой файл (кнопка со ссылкой у трека)", 422)
                    vid = cands[nxt]
                else:
                    vid = cands[0]
            cover = "https://i.ytimg.com/vi/%s/hqdefault.jpg" % vid
            with LOCK:
                if t is not None:
                    t["ytc"], t["yt"] = cands[:8], vid
                    if not t.get("cover"):
                        t["cover"] = cover
                    save_db(True)
                else:
                    if len(YTC) > 500:
                        YTC.clear()
                    YTC[key] = cands[:8]
            return self.js({"yt": vid, "cover": cover})

        if p == "/api/track/attach":
            d = self.body()
            with LOCK:
                g = DB["tracks"].get(str(d.get("ghost", "")))
                r = DB["tracks"].get(str(d.get("track", "")))
                if not g or not g.get("ghost") or g["owner"] != me["name"]:
                    return self.err("Нельзя менять этот трек", 403)
                if not r or r.get("ghost") or not r.get("url") or not track_ok(r, me):
                    return self.err("Файл не найден", 404)
                if r.get("private"):
                    return self.err("Этот файл «Для себя». Сначала поставь ему «В ленту»")
                g["link"] = r["id"]
                save_db()
                return self.js({"track": track_pub(g)})

        if p == "/api/password":
            d = self.body()
            old, new = str(d.get("old", "")), str(d.get("new", ""))
            if not rate_ok("pw:" + low, 5, 600):
                return self.err("Слишком много попыток. Подожди несколько минут", 429)
            with LOCK:
                if not me.get("hash") or not secrets.compare_digest(me["hash"], hash_pw(old, me["salt"])):
                    return self.err("Старый пароль неверный")
                if len(new) < 6:
                    return self.err("Новый пароль слишком короткий (минимум 6 символов)")
                if new.lower() == me["name"].lower() or new.lower() in WEAK_PW:
                    return self.err("Слишком простой пароль, придумай другой")
                me["salt"] = secrets.token_hex(8)
                me["hash"] = hash_pw(new, me["salt"])
                cur = self.headers.get("X-Token", "")
                for tk in [k for k, v in DB["tokens"].items() if v == low and k != cur]:
                    del DB["tokens"][tk]
                    DB["sess"].pop(tk, None)
                save_db()
                return self.js({"ok": True})

        if p == "/api/import/save":
            d = self.body()
            svc = str(d.get("service", ""))
            if svc not in IMPORTERS:
                return self.err("Неизвестный сервис")
            raw = d.get("tracks") if isinstance(d.get("tracks"), list) else []
            with LOCK:
                if sum(1 for t in DB["tracks"].values() if t["owner"] == me["name"] and t.get("ghost")) + len(raw) > 1500:
                    return self.err("Слишком много импортированных треков")
                to = str(d.get("to", ""))
                if to == "fav":
                    pl = fav_playlist(me)
                elif to == "new":
                    if sum(1 for x in DB["playlists"].values() if x["owner"] == me["name"]) >= 50:
                        return self.err("Достигнут лимит: 50 плейлистов")
                    pid = uuid.uuid4().hex[:10]
                    cov = _https(d.get("cover"))
                    pl = DB["playlists"][pid] = {"id": pid, "owner": me["name"], "name": _s(d.get("name"), 60) or "Импорт",
                                                 "desc": "Импорт из %s" % {"spotify": "Spotify", "soundcloud": "SoundCloud", "yandex": "Яндекс Музыки", "ytm": "YouTube Music"}[svc],
                                                 "link": "", "cover": "", "tracks": [], "created": time.time(), "ext_cover": cov}
                else:
                    pl = DB["playlists"].get(to)
                    if not pl or pl["owner"] != me["name"]:
                        return self.err("Плейлист не найден", 404)
                added = 0
                ids = []
                for x in raw[:300]:
                    if not isinstance(x, dict) or not str(x.get("title", "")).strip() or len(pl["tracks"]) >= 500:
                        ids.append("")
                        continue
                    tid = uuid.uuid4().hex
                    DB["tracks"][tid] = {"id": tid, "owner": me["name"], "title": _s(x.get("title"), 120), "artist": _s(x.get("artist"), 80),
                                         "cover": _https(x.get("cover")) or _https(d.get("cover")), "dur": max(0, min(int(x.get("dur") or 0), 86400)),
                                         "url": "", "file": "", "created": time.time(), "ghost": True, "src": svc,
                                         "yt": (str(x.get("yt")) if re.match(r"^[A-Za-z0-9_-]{11}$", str(x.get("yt") or "")) else "")}
                    pl["tracks"].append(tid)
                    ids.append(tid)
                    added += 1
                save_db()
                return self.js({"added": added, "ids": ids, "playlist": pl_pub(pl)})

        if p == "/api/listen":
            d = self.body()
            with LOCK:
                t = DB["tracks"].get(str(d.get("id", "")))
                if not t:
                    return self.js({"ok": True})
                try:
                    sec = int(float(d.get("sec") or 0))
                except ValueError:
                    sec = 0
                now = time.time()
                w = me.get("lw") or [now, 0]
                if now - w[0] > 60:
                    w = [now, 0]
                sec = max(0, min(sec, 120, 65 - w[1]))      # нельзя «наслушать» больше, чем идёт время
                w[1] += sec
                me["lw"] = w
                if sec <= 0:
                    return self.js({"ok": True})
                me["listen_sec"] = me.get("listen_sec", 0) + sec
                dur = int(t.get("dur") or 0)
                need = max(2, min(25, int(dur * 0.45))) if dur > 0 else 25
                counted = False
                lc = me.setdefault("lcnt", {})
                if d.get("count") and sec >= need and now - lc.get(t["id"], 0) >= max(3, min(20, int(dur * 0.8))):
                    pl = me.setdefault("plays", {})
                    pl[t["id"]] = pl.get(t["id"], 0) + 1
                    lc[t["id"]] = now
                    counted = True
                save_db(True)
                return self.js({"ok": True, "counted": counted})

        if p == "/api/devices/revoke":
            d = self.body()
            cur = self.headers.get("X-Token", "")
            with LOCK:
                mine = [tk for tk, v in DB["tokens"].items() if v == low and tk not in DB["imp"]]
                if d.get("others"):
                    kill = [tk for tk in mine if tk != cur]
                else:
                    kill = [tk for tk in mine if sid_of(tk) == str(d.get("sid", "")) and tk != cur]
                for tk in kill:
                    DB["tokens"].pop(tk, None)
                    DB["sess"].pop(tk, None)
                save_db()
                return self.js({"closed": len(kill)})

        if p == "/api/prefs":
            d = self.body()
            pr = d.get("prefs") if isinstance(d.get("prefs"), dict) else {}
            out = {}
            if re.match(r"^#[0-9a-fA-F]{6}$", str(pr.get("acc", ""))):
                out["acc"] = str(pr["acc"]).lower()
            if pr.get("style") in ("game", "flat", "glass"):
                out["style"] = pr["style"]
            if pr.get("perf") in ("auto", "full", "lite"):
                out["perf"] = pr["perf"]
            out["auto"] = bool(pr.get("auto", True))
            out["bgblur"] = bool(pr.get("bgblur", False))
            for k, vals, df in (("mpsize", ("s", "m", "l"), "m"), ("mpbg", ("glass", "solid", "cover", "grad", "none"), "glass"),
                                ("mpshape", ("pill", "soft", "sq"), "pill"), ("sbgm", ("cover", "accent"), "cover"),
                                ("mpfont", ("sys", "round", "site", "mono"), "sys"), ("mpbt", ("plain", "circle"), "plain"), ("mpbp", ("top", "bottom"), "bottom")):
                out[k] = pr[k] if pr.get(k) in vals else df
            out["mpprev"] = bool(pr.get("mpprev", False))
            for k in ("mpprog", "mpcov", "mpskip", "seq", "notif", "xfade"):
                out[k] = bool(pr.get(k, True))
            for k, lo, hi, df in (("vol", 0, 100, 80), ("bgdim", 0, 90, 55), ("mpop", 30, 100, 94), ("xfadet", 2, 10, 4)):
                try:
                    out[k] = max(lo, min(hi, int(pr.get(k, df))))
                except (TypeError, ValueError):
                    out[k] = df
            with LOCK:
                me["prefs"] = out
                save_db(True)
            return self.js({"ok": True})

        if p == "/api/logout":
            with LOCK:
                tk0 = self.headers.get("X-Token", "")
                DB["tokens"].pop(tk0, None)
                DB["imp"].pop(tk0, None)
                DB["sess"].pop(tk0, None)
                save_db()
            return self.js({"ok": True})

        if p == "/api/now":
            d = self.body()
            with LOCK:
                me["now"] = str(d.get("title", ""))[:80]
                me["now_t"] = time.time()
                tid = str(d.get("id", ""))
                if tid in DB["tracks"]:
                    rc = [i for i in me.get("recent", []) if i != tid]
                    rc.insert(0, tid)
                    me["recent"] = rc[:15]
                    save_db(True)
            return self.js({"ok": True})

        if p == "/api/profile":
            d = self.body()
            with LOCK:
                if "display" in d:
                    me["display"] = (str(d["display"]).strip()[:30]) or me["name"]
                if "bio" in d:
                    me["bio"] = str(d["bio"])[:400]
                if "status" in d:
                    me["status"] = str(d["status"]).strip()[:40]
                if "accent" in d:
                    v = str(d["accent"]).strip()
                    if v == "" or re.match(r"^#[0-9a-fA-F]{6}$", v):
                        me["accent"] = v.lower()
                if "pin" in d:
                    pid = str(d["pin"])
                    me["pin"] = pid if (pid in DB["tracks"] and DB["tracks"][pid]["owner"] == me["name"]) else ""
                if "show_listen" in d:
                    me["show_listen"] = bool(d["show_listen"])
                if "private" in d:
                    me["private"] = bool(d["private"])
                if isinstance(d.get("socials"), dict):
                    soc = {}
                    for k in SOCIALS:
                        r_ = norm_social(k, d["socials"].get(k, ""))
                        if r_ is None:
                            return self.err("Не получилось распознать %s: впиши @ник или ссылку" % SOC_NAME[k])
                        if r_:
                            soc[k] = r_
                    me["socials"] = soc
                for k in ("avatar", "banner"):
                    if k in d:
                        v = str(d[k])
                        if v == "" or IMG_URL.match(v):
                            me[k] = v
                save_db()
                return self.js({"user": pub(me, True)})

        if p == "/api/upload":
            kind = q.get("kind", "")
            name = q.get("name", "file")
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if kind == "audio":
                allowed, limit = AUDIO_EXT, MAX_AUDIO
            elif kind == "image":
                allowed, limit = IMAGE_EXT, MAX_IMAGE
            else:
                return self.err("Неизвестный тип загрузки")
            if ext not in allowed:
                return self.err("Формат .%s не поддерживается" % (ext or "?"))
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n <= 0:
                return self.err("Пустой файл")
            if n > limit:
                self.close_connection = True
                return self.err("Файл слишком большой (лимит %d МБ)" % (limit // 1048576), 413)
            if kind == "audio" and sum(1 for t in DB["tracks"].values() if t["owner"] == me["name"] and not t.get("ghost")) >= 300:
                return self.err("Достигнут лимит: 300 треков на аккаунт")
            fid = uuid.uuid4().hex
            fn = fid + "." + ext
            fp = os.path.join(FILES, fn)
            left = n
            try:
                with open(fp, "wb") as f:
                    while left > 0:
                        chunk = self.rfile.read(min(262144, left))
                        if not chunk:
                            raise IOError("обрыв загрузки")
                        f.write(chunk)
                        left -= len(chunk)
            except Exception:
                try:
                    os.remove(fp)
                except Exception:
                    pass
                return self.err("Загрузка прервалась")
            url = "/files/" + fn
            if kind == "image":
                return self.js({"url": url})
            title = (q.get("title") or "").strip()[:80] or os.path.splitext(name)[0].strip()[:80] or "Без названия"
            artist = (q.get("artist") or "").strip()[:60]
            try:
                dur = max(0, min(int(float(q.get("dur") or 0)), 86400))
            except ValueError:
                dur = 0
            with LOCK:
                tr = {"id": fid, "owner": me["name"], "title": title, "artist": artist, "cover": "", "dur": dur,
                      "url": url, "file": fn, "created": time.time(), "private": q.get("pub") == "0"}
                DB["tracks"][fid] = tr
                save_db()
            return self.js({"track": track_pub(tr)})

        if p == "/api/track/delete":
            d = self.body()
            with LOCK:
                t = DB["tracks"].get(str(d.get("id", "")))
                if not t or (t["owner"] != me["name"] and not is_admin(me)):
                    return self.err("Нельзя удалить этот трек", 403)
                del DB["tracks"][t["id"]]
                for g in DB["tracks"].values():
                    if g.get("link") == t["id"]:
                        g.pop("link", None)
                for pid in [k for k, x in DB["posts"].items() if x["track"] == t["id"]]:
                    del DB["posts"][pid]
                for pl in DB["playlists"].values():
                    if t["id"] in pl["tracks"]:
                        pl["tracks"].remove(t["id"])
                save_db()
            for fn in (t["file"], os.path.basename(t.get("cover", ""))):
                if fn and FILE_NAME.match(fn):
                    try:
                        os.remove(os.path.join(FILES, fn))
                    except Exception:
                        pass
            return self.js({"ok": True})

        if p == "/api/track/cover":
            d = self.body()
            url = str(d.get("url", ""))
            with LOCK:
                t = DB["tracks"].get(str(d.get("id", "")))
                if not t or t["owner"] != me["name"]:
                    return self.err("Нельзя менять этот трек", 403)
                if not IMG_URL.match(url):
                    return self.err("Неверная обложка")
                t["cover"] = url
                save_db()
                return self.js({"track": track_pub(t)})

        if p == "/api/track/edit":
            d = self.body()
            with LOCK:
                t = DB["tracks"].get(str(d.get("id", "")))
                if not t or t["owner"] != me["name"]:
                    return self.err("Нельзя менять этот трек", 403)
                title = str(d.get("title", "")).strip()[:80]
                if title:
                    t["title"] = title
                t["artist"] = str(d.get("artist", "")).strip()[:60]
                if "private" in d:
                    t["private"] = bool(d["private"])
                    if t["private"]:
                        for g in DB["tracks"].values():
                            if g.get("link") == t["id"] and g["owner"] != t["owner"]:
                                g.pop("link", None)
                save_db()
                return self.js({"track": track_pub(t)})

        # ---- плейлисты
        if p in ("/api/playlist", "/api/playlist/edit"):
            d = self.body()
            name = str(d.get("name", "")).strip()[:60]
            link = str(d.get("link", "")).strip()[:300]
            cover = str(d.get("cover", "")).strip()
            if not name:
                return self.err("Введи название плейлиста")
            if link and not re.match(r"^https?://", link, re.I):
                return self.err("Ссылка должна начинаться с http:// или https://")
            if cover and not IMG_URL.match(cover):
                return self.err("Неверная обложка плейлиста")
            with LOCK:
                if p == "/api/playlist":
                    if sum(1 for x in DB["playlists"].values() if x["owner"] == me["name"]) >= 50:
                        return self.err("Достигнут лимит: 50 плейлистов")
                    ids = [i for i in d.get("tracks", []) if isinstance(i, str) and i in DB["tracks"]][:300]
                    pid = uuid.uuid4().hex[:10]
                    DB["playlists"][pid] = {"id": pid, "owner": me["name"], "name": name, "desc": str(d.get("desc", ""))[:300],
                                            "link": link, "cover": cover, "tracks": ids, "created": time.time()}
                    save_db()
                    return self.js({"id": pid})
                pl = DB["playlists"].get(str(d.get("id", "")))
                if not pl or (pl["owner"] != me["name"] and not is_admin(me)):
                    return self.err("Нельзя менять этот плейлист", 403)
                pl.update({"name": name, "desc": str(d.get("desc", ""))[:300], "link": link, "cover": cover})
                save_db()
                return self.js({"playlist": pl_pub(pl)})

        if p in ("/api/playlist/add", "/api/playlist/remove"):
            d = self.body()
            with LOCK:
                pl = DB["playlists"].get(str(d.get("id", "")))
                if not pl or pl["owner"] != me["name"]:
                    return self.err("Это не твой плейлист", 403)
                ids = d.get("tracks") if isinstance(d.get("tracks"), list) else [d.get("track")]
                ids = [i for i in ids if isinstance(i, str) and i in DB["tracks"]]
                if p == "/api/playlist/add":
                    for i in ids:
                        if i not in pl["tracks"] and len(pl["tracks"]) < 300:
                            pl["tracks"].append(i)
                else:
                    pl["tracks"] = [i for i in pl["tracks"] if i not in ids]
                    gc_ghosts()
                save_db()
                return self.js({"playlist": pl_pub(pl)})

        if p == "/api/playlist/save":
            d = self.body()
            with LOCK:
                pl = DB["playlists"].get(str(d.get("id", "")))
                if not pl:
                    return self.err("Плейлист не найден", 404)
                if pl["owner"] == me["name"] or pl.get("fav"):
                    return self.err("Этот плейлист нельзя сохранить")
                s = me.setdefault("saved", [])
                if pl["id"] in s:
                    s.remove(pl["id"])
                    r = False
                else:
                    s.append(pl["id"])
                    r = True
                save_db()
                return self.js({"saved": r})

        if p == "/api/playlist/delete":
            d = self.body()
            with LOCK:
                pl = DB["playlists"].get(str(d.get("id", "")))
                if not pl or (pl["owner"] != me["name"] and not is_admin(me)):
                    return self.err("Нельзя удалить этот плейлист", 403)
                if pl.get("fav"):
                    return self.err("Любимое удалить нельзя")
                del DB["playlists"][pl["id"]]
                for usr in DB["users"].values():
                    if pl["id"] in usr.get("saved", []):
                        usr["saved"].remove(pl["id"])
                gc_ghosts()
                save_db()
                return self.js({"ok": True})

        # ---- сообщения
        if p == "/api/chat/send":
            d = self.body()
            text = str(d.get("text", "")).replace("\r", "").strip()[:1000]
            if not text:
                return self.err("Пустое сообщение")
            with LOCK:
                other = DB["users"].get(str(d.get("to", "")).lower())
                if not other:
                    return self.err("Пользователь не найден", 404)
                ok, why = can_message(me, other)
                if not ok:
                    return self.err(why, 403)
                if not rate_ok("m:" + low, MSG_PER_MIN, 60):
                    return self.err("Слишком часто. Подожди несколько секунд", 429)
                key = conv_key(low, other["name"])
                c = DB["convs"].get(key)
                if not c:
                    a, b = sorted([low, other["name"].lower()])
                    c = DB["convs"][key] = {"a": a, "b": b, "msgs": []}
                    for usr in (me, other):
                        usr.setdefault("chats", [])
                        if key not in usr["chats"]:
                            usr["chats"].append(key)
                DB["mid"] += 1
                m = {"id": DB["mid"], "from": low, "to": other["name"].lower(), "text": text, "t": int(time.time()), "read": False}
                c["msgs"].append(m)
                if len(c["msgs"]) > 500:
                    del c["msgs"][:len(c["msgs"]) - 500]
                save_db()
                return self.js({"msg": fmt_msg(m, low)})

        # ---- блокировка пользователей
        if p == "/api/block":
            d = self.body()
            with LOCK:
                other = DB["users"].get(str(d.get("name", "")).lower())
                if not other or other is me:
                    return self.err("Пользователь не найден", 404)
                bl = me.setdefault("blocked", [])
                k = other["name"].lower()
                if d.get("on"):
                    if is_admin(other):
                        return self.err("Администратора заблокировать нельзя")
                    if k not in bl:
                        bl.append(k)
                elif k in bl:
                    bl.remove(k)
                save_db()
                return self.js({"ok": True, "blocked": k in bl})

        # ---- плейлисты: оценки, прослушивания, комментарии
        if p == "/api/playlist/rate":
            d = self.body()
            try:
                v = int(d.get("v", 0))
            except (TypeError, ValueError):
                v = 0
            with LOCK:
                x = DB["playlists"].get(str(d.get("id", "")))
                if not x or x.get("fav") or not visible_owner(x["owner"], me):
                    return self.err("Плейлист не найден", 404)
                if x["owner"] == me["name"]:
                    return self.err("Свой плейлист оценить нельзя")
                rt = x.setdefault("rate", {})
                if 1 <= v <= 5:
                    rt[low] = v
                else:
                    rt.pop(low, None)
                save_db()
                return self.js({"playlist": pl_pub(x, me)})

        if p == "/api/playlist/play":
            d = self.body()
            with LOCK:
                x = DB["playlists"].get(str(d.get("id", "")))
                if x and not x.get("fav") and rate_ok("pp:%s:%s" % (low, x["id"]), 1, 900):
                    x["plays"] = int(x.get("plays", 0)) + 1
                    save_db()
                return self.js({"ok": True})

        if p == "/api/playlist/comment":
            d = self.body()
            text = str(d.get("text", "")).replace("\r", "").strip()[:300]
            if not text:
                return self.err("Пустой комментарий")
            with LOCK:
                x = DB["playlists"].get(str(d.get("id", "")))
                if not x or x.get("fav") or not visible_owner(x["owner"], me):
                    return self.err("Плейлист не найден", 404)
                if not rate_ok("c:" + low, 10, 60):
                    return self.err("Слишком часто. Подожди несколько секунд", 429)
                cs = x.setdefault("comments", [])
                if len(cs) >= 500:
                    return self.err("Под этим плейлистом уже 500 комментариев")
                c = {"id": uuid.uuid4().hex[:10], "user": me["name"], "text": text, "t": int(time.time())}
                cs.append(c)
                save_db()
                return self.js({"comment": pl_comment_pub(c, x, me)})

        if p == "/api/playlist/comment/delete":
            d = self.body()
            with LOCK:
                x = DB["playlists"].get(str(d.get("id", "")))
                if not x:
                    return self.err("Плейлист не найден", 404)
                for c in x.get("comments", []):
                    if c["id"] == str(d.get("cid", "")):
                        if c["user"] != me["name"] and x["owner"] != me["name"] and not is_admin(me):
                            return self.err("Нельзя удалить этот комментарий", 403)
                        x["comments"].remove(c)
                        save_db()
                        return self.js({"ok": True})
                return self.err("Комментарий не найден", 404)

        # ---- лента
        if p == "/api/post/create":
            d = self.body()
            text = str(d.get("text", "")).replace("\r", "").strip()[:500]
            with LOCK:
                t = DB["tracks"].get(str(d.get("track", "")))
                if not t or t["owner"] != me["name"] or t.get("ghost"):
                    return self.err("Выбери свой трек", 404)
                if t.get("private"):
                    return self.err("Трек стоит «для себя». Сделай его публичным, чтобы поделиться")
                if any(x["track"] == t["id"] for x in DB["posts"].values()):
                    return self.err("Этот трек уже в ленте. Удали старый пост, если хочешь опубликовать заново")
                if not rate_ok("post:" + low, 6, 3600):
                    return self.err("Слишком много постов. Подожди немного", 429)
                pid = uuid.uuid4().hex[:12]
                x = {"id": pid, "track": t["id"], "owner": me["name"], "text": text, "anon": bool(d.get("anon")),
                     "created": time.time(), "comments": []}
                DB["posts"][pid] = x
                save_db()
                return self.js({"post": post_pub(x, me)})

        if p == "/api/post/delete":
            d = self.body()
            with LOCK:
                x = DB["posts"].get(str(d.get("id", "")))
                if not x or (x["owner"] != me["name"] and not is_admin(me)):
                    return self.err("Нельзя удалить этот пост", 403)
                del DB["posts"][x["id"]]
                save_db()
                return self.js({"ok": True})

        if p == "/api/post/comment":
            d = self.body()
            text = str(d.get("text", "")).replace("\r", "").strip()[:300]
            if not text:
                return self.err("Пустой комментарий")
            with LOCK:
                x = DB["posts"].get(str(d.get("id", "")))
                if not x or not post_visible(x, me):
                    return self.err("Пост не найден", 404)
                if not rate_ok("c:" + low, 10, 60):
                    return self.err("Слишком часто. Подожди несколько секунд", 429)
                cs = x.setdefault("comments", [])
                if len(cs) >= 500:
                    return self.err("В этом посте уже 500 комментариев")
                c = {"id": uuid.uuid4().hex[:10], "user": me["name"], "text": text, "t": int(time.time())}
                cs.append(c)
                save_db()
                return self.js({"comment": comment_pub(c, x, me)})

        if p == "/api/post/comment/delete":
            d = self.body()
            with LOCK:
                x = DB["posts"].get(str(d.get("id", "")))
                if not x:
                    return self.err("Пост не найден", 404)
                for c in x.get("comments", []):
                    if c["id"] == str(d.get("cid", "")):
                        if c["user"] != me["name"] and x["owner"] != me["name"] and not is_admin(me):
                            return self.err("Нельзя удалить этот комментарий", 403)
                        x["comments"].remove(c)
                        save_db()
                        return self.js({"ok": True})
                return self.err("Комментарий не найден", 404)

        # ---- правка, удаление и реакции в чате
        if p in ("/api/chat/edit", "/api/chat/delete", "/api/chat/react"):
            d = self.body()
            try:
                mid = int(d.get("id", 0))
            except (TypeError, ValueError):
                mid = 0
            with LOCK:
                c, m = find_msg(me, mid)
                if not m:
                    return self.err("Сообщение не найдено", 404)
                if p == "/api/chat/react":
                    e = RX_CANON.get(str(d.get("e", "")).replace("\ufe0f", ""))
                    if not e:
                        return self.err("Нет такой реакции")
                    rx = m.setdefault("rx", {})
                    if rx.get(low) == e:
                        del rx[low]
                    else:
                        rx[low] = e
                    if not rx:
                        m.pop("rx", None)
                    save_db()
                    return self.js({"msg": fmt_msg(m, low)})
                if m["from"] != low:
                    return self.err("Можно менять только свои сообщения", 403)
                if p == "/api/chat/delete":
                    c["msgs"].remove(m)
                    save_db()
                    return self.js({"ok": True})
                text = str(d.get("text", "")).replace("\r", "").strip()[:1000]
                if not text:
                    return self.err("Пустое сообщение")
                if m["text"] != text:
                    m["text"] = text
                    m["edited"] = True
                    save_db()
                return self.js({"msg": fmt_msg(m, low)})

        # ---- админ: очистка базы
        if p == "/api/admin/wipe":
            if not self.need_admin():
                return
            d = self.body()
            what = str(d.get("what", ""))
            if what not in ("posts", "tracks", "chats", "users", "reports", "all"):
                return self.err("Неизвестное действие")
            if str(d.get("confirm", "")).strip().upper() != "УДАЛИТЬ":
                return self.err("Нужно ввести слово УДАЛИТЬ")
            with LOCK:
                wipe_db(what)
                save_db()
            return self.js({"ok": True, "files": purge_files()})

        # ---- админ
        if p == "/api/admin/tags":
            if not self.need_admin():
                return
            d = self.body()
            with LOCK:
                t = DB["users"].get(str(d.get("user", "")).lower())
                if not t:
                    return self.err("Пользователь не найден", 404)
                tags = []
                for x in d.get("tags", []) if isinstance(d.get("tags"), list) else []:
                    x = str(x).strip()[:20]
                    if x and x not in tags and x != "Владелец":
                        tags.append(x)
                t["tags"] = tags[:4]
                save_db()
                return self.js({"tags": tags_of(t)})

        if p == "/api/admin/report/delete":
            if not self.need_admin():
                return
            d = self.body()
            with LOCK:
                if d.get("all"):
                    DB["reports"] = []
                else:
                    DB["reports"] = [r for r in DB["reports"] if r["id"] != str(d.get("id", ""))]
                save_db()
                return self.js({"ok": True})

        if p == "/api/admin/impersonate":
            if not self.need_admin():
                return
            d = self.body()
            with LOCK:
                t = DB["users"].get(str(d.get("user", "")).lower())
                if not t:
                    return self.err("Пользователь не найден", 404)
                if is_admin(t):
                    return self.err("Войти как администратор нельзя")
                tok = secrets.token_hex(24)
                DB["tokens"][tok] = t["name"].lower()
                DB["imp"][tok] = me["name"].lower()
                save_db()
                return self.js({"token": tok, "user": pub(t, True)})

        if p == "/api/admin/ban":
            if not self.need_admin():
                return
            d = self.body()
            with LOCK:
                t = DB["users"].get(str(d.get("user", "")).lower())
                if not t:
                    return self.err("Пользователь не найден", 404)
                if is_admin(t):
                    return self.err("Администратора заблокировать нельзя")
                t["banned"] = bool(d.get("banned"))
                save_db()
                return self.js({"banned": t["banned"]})

        self.err("Не найдено", 404)


# ============================== ЗАПУСК ==============================
def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def start_tunnel(port):
    """Необязательно: публичная ссылка через ngrok, чтобы друзья могли зайти и проверить сообщения."""
    global PUBLIC_URL
    if PUBLIC_URL or not NGROK_TOKEN:
        return
    try:
        from pyngrok import ngrok
        ngrok.set_auth_token(NGROK_TOKEN.strip())
        PUBLIC_URL = ngrok.connect(port, bind_tls=True).public_url.replace("http://", "https://")
        print(" Публичная ссылка для друзей: %s" % PUBLIC_URL)
    except Exception as e:
        msg = str(e)
        low = msg.lower()
        print(" Не удалось открыть публичную ссылку через ngrok.")
        print("   Что сказала ошибка: %s" % msg[:300].replace("\n", " "))
        if isinstance(e, ImportError) or "no module named" in low:
            print("   -> Не установлен pyngrok. В Pydroid: меню -> Pip -> pyngrok")
        elif "err_ngrok_105" in low or "authentication failed" in low or "authtoken" in low:
            print("   -> Токен неверный. Скопируй его заново с dashboard.ngrok.com/get-started/your-authtoken (без пробелов и кавычек внутри)")
        elif "err_ngrok_108" in low or "simultaneous" in low or "limited to 1" in low:
            print("   -> Уже открыта другая сессия ngrok. Закрой её на dashboard.ngrok.com/agents или перезапусти телефон")
        elif "permission" in low or "exec format" in low or "no such file" in low or "not found" in low or "errno 13" in low or "errno 8" in low:
            print("   -> ngrok не запускается на этом телефоне. Используй вариант с Termux и cloudflared (инструкция в сообщении от ассистента)")
        else:
            print("   -> Если ошибка не понятна, пришли её текст ассистенту. Запасной вариант: Termux + cloudflared")


def main():
    srv = None
    port = PORT
    for port in range(PORT, PORT + 15):
        try:
            srv = ThreadingHTTPServer(("0.0.0.0", port), H)
            break
        except OSError:
            continue
    if srv is None:
        print("Не удалось занять порт. Перезапусти приложение.")
        return
    srv.daemon_threads = True
    threading.Thread(target=_saver, daemon=True).start()
    seed_admins()
    print("=" * 46)
    print(" PiXeL Music  |  AI STUDIO PIXEL")
    print("=" * 46)
    print(" Открой в браузере:  http://127.0.0.1:%d" % port)
    ip = local_ip()
    if ip:
        print(" Для друзей в Wi-Fi: http://%s:%d" % (ip, port))
    start_tunnel(port)
    print(" Данные: %s" % DATA)
    print(" Остановить: кнопка Stop")
    try:
        import webbrowser
        webbrowser.open("http://127.0.0.1:%d" % port)
    except Exception:
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        if _DIRTY:
            _write_db()


if __name__ == "__main__":
    main()
