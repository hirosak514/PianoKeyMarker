@echo off
chcp 65001 >nul
setlocal
title Chopin the Ⅲ 補助プログラム
set "PKM=%LOCALAPPDATA%\PianoKeyMarker"
set "PKM_SELF=%~f0"
if not exist "%PKM%" mkdir "%PKM%"
set "UV=%PKM%\uv.exe"
rem Chopin the Ⅲの画面から自動で起動されたときは --protocol が付く（ウィンドウは最小化で開く）
set "PKM_PROTO="
if /i "%~1"=="--protocol" set "PKM_PROTO=1"

echo.
echo  ==============================================
echo    Chopin the Ⅲ 補助プログラム
echo  ==============================================
echo   このウィンドウは、楽譜を読み取る間は開いたままにしてください。
echo   （最小化しても大丈夫です。閉じると読み取りができなくなります）
echo.

if exist "%UV%" goto haveuv
echo  [準備] 必要な道具をダウンロードしています（初回だけ・1分ほど）...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $env:UV_INSTALL_DIR=(Join-Path $env:LOCALAPPDATA 'PianoKeyMarker'); $env:UV_NO_MODIFY_PATH='1'; irm https://astral.sh/uv/install.ps1 | iex"
if exist "%PKM%\bin\uv.exe" copy /y "%PKM%\bin\uv.exe" "%UV%" >nul
if exist "%UV%" goto haveuv
echo  [準備] 別の方法でダウンロードしています...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $z=Join-Path $env:TEMP 'pkm-uv.zip'; $d=Join-Path $env:TEMP 'pkm-uv'; Invoke-WebRequest -UseBasicParsing 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile $z; Expand-Archive -Force $z $d; Copy-Item (Get-ChildItem $d -Recurse -Filter uv.exe | Select-Object -First 1).FullName (Join-Path $env:LOCALAPPDATA 'PianoKeyMarker\uv.exe') -Force"
if exist "%UV%" goto haveuv
goto fail

:haveuv
rem このファイルの末尾に埋め込んだ補助プログラム本体を取り出す（毎回最新のものに置き換える）
powershell -NoProfile -ExecutionPolicy Bypass -Command "$t=[IO.File]::ReadAllText($env:PKM_SELF,[Text.Encoding]::UTF8); $m='###'+' PKM-HELPER-PY BEGIN '+'###'; $i=$t.LastIndexOf($m); if($i -lt 0){exit 3}; $s=$t.IndexOf([char]10,$i)+1; [IO.File]::WriteAllText((Join-Path $env:LOCALAPPDATA 'PianoKeyMarker\pkm_omr_helper.py'),$t.Substring($s),(New-Object Text.UTF8Encoding $false))"
if errorlevel 1 goto fail
if not exist "%PKM%\pkm_omr_helper.py" goto fail

rem このファイル自体を決まった場所（%LOCALAPPDATA%\PianoKeyMarker\helper.bat）に保存し、
rem Chopin the Ⅲの画面から自動で起動できるように「起動用リンク」を登録する（管理者権限は不要）
if /i not "%~f0"=="%PKM%\helper.bat" copy /y "%~f0" "%PKM%\helper.bat" >nul
reg add "HKCU\Software\Classes\pianokeymarker-helper" /ve /d "URL:PianoKeyMarker Helper" /f >nul
reg add "HKCU\Software\Classes\pianokeymarker-helper" /v "URL Protocol" /d "" /f >nul
reg add "HKCU\Software\Classes\pianokeymarker-helper\shell\open\command" /ve /d "\"%ComSpec%\" /c start \"PianoKeyMarker\" /min \"%PKM%\helper.bat\" --protocol" /f >nul

set "PATH=%PKM%;%PATH%"
echo  補助プログラムを起動します（初回は Python の準備に1〜3分かかります）...
echo.
rem 古い補助プログラムが動いていれば終了させる（新しいものに入れ替えるため。自分自身の PowerShell は除く）
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -like '*pkm_omr_helper.py*' } | ForEach-Object { Invoke-CimMethod -InputObject $_ -MethodName Terminate | Out-Null }" >nul 2>&1
timeout /t 1 /nobreak >nul
rem Chopin the Ⅲの画面（アプリ・ブラウザ）を閉じて3分ほど接続がなければ、自動で終了する
"%UV%" run --no-project --python 3.12 "%PKM%\pkm_omr_helper.py" --no-setup --idle-exit 180
if errorlevel 1 goto crashed
echo.
echo  補助プログラムを終了しました。次回からは、Chopin the Ⅲで「解析する」を押すと自動で起動します。
if defined PKM_PROTO exit /b
timeout /t 8 >nul
exit /b

:crashed
echo.
echo  補助プログラムが止まりました。上に表示された内容を確認してください。
pause
exit /b

:fail
echo.
echo  準備がうまくいきませんでした。
echo  インターネットにつながっているか確認して、もう一度このファイルを開いてください。
echo  何度やってもうまくいかない場合は、Windowsアプリ版（exe）をお使いください（準備は不要です）。
echo.
pause
exit /b

### PKM-HELPER-PY BEGIN ###
#!/usr/bin/env python3
"""
Chopin the Ⅲ 用の補助プログラム
楽譜読み取り専用のソフト（oemer / homr / Audiveris）をこのPCで動かし、Chopin the Ⅲから使えるようにします。

使い方:
    python pkm_omr_helper.py            # http://127.0.0.1:8765 で待ち受け（初回は必要な部品を自動インストール）
    python pkm_omr_helper.py --port 9000
    python pkm_omr_helper.py --audiveris "C:\\path\\to\\Audiveris.exe"   # Audiveris の場所を指定

エンジン:
    homr       … いちばんおすすめ。Chopin the Ⅲの画面の「homr を準備する」から初回だけインストール（約600MB）
    Audiveris  … 印刷楽譜のスキャン向け。https://github.com/Audiveris/audiveris/releases から別途インストール
    oemer      … Python 3.10〜3.13 のときに自動インストール

このPCの中（127.0.0.1）からの接続だけを受け付けます。
"""
import argparse
import glob
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

VERSION = "2.4"
LOCK = threading.Lock()          # 読み取りは1枚ずつ（どのエンジンもメモリを多く使うため）
LAST_ACTIVITY = [0.0]           # 最後にアプリから接続があった時刻（--idle-exit 用）
MAX_BYTES = 30 * 1024 * 1024
TIMEOUT_SEC = 20 * 60
AUDIVERIS_OVERRIDE = None
# homr の導入状態  state: checking | not_installed | installing | ready | error
HOMR_STATE = {"state": "checking", "percent": 0, "phase": "", "error": "", "hint": "", "started": 0.0}
HOMR_EXPECTED_MB = 750          # 初回にダウンロード・展開される量の目安（部品＋読み取りモデル）
DATA_DIR = os.path.join(os.path.expanduser("~"), ".pkm_omr")
HOMR_MARKER = os.path.join(DATA_DIR, "homr_ready.json")

# oemer の動作確認済みの組み合わせ（oemer の依存関係どおりに入れると新しすぎる部品が入り動かないため）
OEMER_DEPS = ["onnxruntime==1.20.1", "opencv-python-headless<5", "matplotlib", "pillow", "scipy", "scikit-learn>=1.2", "typing-extensions"]
HOMR_CMD = ["tool", "run", "--python", "3.12", "--from", "homr[cpu]", "homr"]
import re
import time


def say(msg):
    print(msg, flush=True)


def py_ok_for_oemer():
    return (3, 10) <= sys.version_info[:2] <= (3, 13)


def pip_install(args):
    base = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]
    say("  > pip install " + " ".join(args))
    if subprocess.run(base + args).returncode == 0:
        return True
    # 書き込み権限がない環境では --user で再試行
    return subprocess.run(base + ["--user"] + args).returncode == 0


# ---------------- oemer ----------------
def oemer_ok():
    try:
        for mod in ("oemer.ete", "onnxruntime", "cv2", "sklearn", "scipy", "matplotlib", "typing_extensions"):
            importlib.import_module(mod)
        return True
    except Exception:
        return False


def find_oemer():
    if not oemer_ok():
        return None
    exe = shutil.which("oemer")
    if exe:
        return [exe]
    return [sys.executable, "-c", "import sys; from oemer.ete import main; sys.argv[0] = 'oemer'; main()"]


# ---------------- homr（uv 経由） ----------------
def uv_cmd():
    try:
        importlib.import_module("uv")
        return [sys.executable, "-m", "uv"]
    except Exception:
        exe = shutil.which("uv")
        return [exe] if exe else None


def _dir_mb(paths):
    total = 0
    for root_dir in paths:
        for root, _dirs, files in os.walk(root_dir):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    return total / 1048576


def _uv_dirs(uv):
    dirs = []
    for args in (["cache", "dir"], ["python", "dir"], ["tool", "dir"]):
        try:
            r = subprocess.run(uv + args, capture_output=True, text=True, timeout=30)
            d = (r.stdout or "").strip().splitlines()
            if r.returncode == 0 and d and os.path.isdir(d[-1]):
                dirs.append(d[-1])
        except Exception:
            pass
    return dirs


def _explain_error(text):
    """よくある失敗の原因を、やさしい日本語の対処法にする"""
    t = text.lower()
    if any(k in t for k in ("no space left", "os error 112", "os error 28", "disk full", "not enough space")):
        return "PCの空き容量が足りません。2GB以上空けてから「もう一度試す」を押してください。"
    if any(k in t for k in ("access is denied", "os error 5", "permission denied", "being used by another process", "os error 32")):
        return "ファイルの書き込みが止められました。ウイルス対策ソフトが止めている可能性があります。少し待ってから「もう一度試す」を押してください。"
    if any(k in t for k in ("timed out", "timeout", "connect", "dns", "resolve", "network", "ssl", "certificate", "tls", "failed to fetch", "error sending request", "connection")):
        return "インターネットからダウンロードできませんでした。インターネットにつながっているか確認して、「もう一度試す」を押してください（会社や学校のネットワークでは止められることがあります）。"
    return "準備に失敗しました。PCを再起動してから「もう一度試す」を押してください。"


def _set(**kw):
    HOMR_STATE.update(kw)


def install_homr():
    """homr の部品と読み取りモデルをダウンロードする（初回のみ・数分〜十数分）"""
    if HOMR_STATE["state"] == "installing":
        return
    uv = uv_cmd()
    if not uv:
        _set(state="error", error="uv が見つかりません", hint="補助プログラムを起動し直してください。")
        return
    _set(state="installing", percent=1, phase="準備を始めています…", error="", hint="", started=time.time())
    say("homr のインストールを始めます（初回のみ）")
    dirs = _uv_dirs(uv)
    base_mb = _dir_mb(dirs)
    stop = threading.Event()
    model = {"active": False, "done": 0, "count": 3}

    def watch():
        while not stop.wait(1.5):
            if model["active"]:
                continue
            grown = max(0.0, _dir_mb(dirs) - base_mb)
            pct = min(85, 2 + grown / HOMR_EXPECTED_MB * 85)
            if pct > HOMR_STATE["percent"]:
                _set(percent=round(pct), phase="読み取りソフトの部品をダウンロード中（%d MB）" % grown)
    threading.Thread(target=watch, daemon=True).start()
    tail = []
    try:
        proc = subprocess.Popen(uv + HOMR_CMD + ["--init"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", bufsize=1)
        buf = ""
        while True:
            ch = proc.stdout.read(1)
            if not ch:
                break
            if ch not in "\r\n)":
                buf += ch
                continue
            line = (buf + (ch if ch == ")" else "")).strip()
            buf = ""
            if not line:
                continue
            m = re.search(r"Downloading (\d+) models", line)
            if m:
                model.update(active=True, count=int(m.group(1)), done=0)
            m = re.search(r"Downloaded (\d+) of (\d+) MB \((\d+)%\)", line)
            if m:
                model["active"] = True
                frac = (model["done"] + int(m.group(3)) / 100) / max(1, model["count"])
                _set(percent=max(HOMR_STATE["percent"], round(86 + frac * 12)),
                     phase="読み取りモデルをダウンロード中（%d / %d 個目）" % (model["done"] + 1, model["count"]))
                if m.group(3) == "100":
                    model["done"] += 1
                continue
            tail.append(line)
            tail[:] = tail[-30:]
            if "Init finished" in line:
                _set(percent=99, phase="仕上げ中…")
        rc = proc.wait()
        stop.set()
        if rc == 0:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(HOMR_MARKER, "w", encoding="utf-8") as f:
                json.dump({"version": VERSION, "time": time.time()}, f)
            _set(state="ready", percent=100, phase="準備完了")
            say("homr の準備ができました。")
        else:
            err = "\n".join(tail[-8:])
            _set(state="error", error=err[-500:], hint=_explain_error(err))
            say("※ homr の準備に失敗しました: " + err[-300:])
    except Exception as e:  # noqa: BLE001
        stop.set()
        _set(state="error", error=str(e), hint=_explain_error(str(e)))


def check_homr():
    """起動時：以前に準備が終わっているか確かめる（ネットにはつながない）"""
    uv = uv_cmd()
    if not uv:
        _set(state="error", error="uv が見つかりません", hint="補助プログラムを起動し直してください。")
        return
    if not os.path.exists(HOMR_MARKER):
        _set(state="not_installed")
        return
    try:
        r = subprocess.run(uv + ["--offline"] + HOMR_CMD + ["--init"], capture_output=True, text=True, timeout=300)
        _set(state="ready" if r.returncode == 0 else "not_installed", percent=100 if r.returncode == 0 else 0)
    except Exception:
        _set(state="not_installed")


# ---------------- Audiveris ----------------
# Windows では「Audiveris をインストールしますか？」→ はい で、ここから自動で入れられる。
# 公式の .msi（Java も同梱）をダウンロードし、管理者の許可がいらない「展開」（msiexec /a）で
# %USERPROFILE%\.pkm_omr\audiveris に取り出す。展開できなかったときだけ、通常のインストール
# （Windows の「変更を許可しますか？」が1回出る）を行う。
AUD_DIR = os.path.join(DATA_DIR, "audiveris")
AUD_FALLBACK = ("5.11.0", "https://github.com/Audiveris/audiveris/releases/download/5.11.0/Audiveris-5.11.0-windows-x86_64.msi")
AUD_STATE = {"state": "idle", "percent": 0, "phase": "", "error": "", "hint": ""}


def _aud_set(**kw):
    AUD_STATE.update(kw)


def _latest_audiveris_msi():
    """GitHub から最新版の Windows 用 .msi の URL を調べる（失敗したら既知の版）"""
    import urllib.request
    try:
        req = urllib.request.Request("https://api.github.com/repos/Audiveris/audiveris/releases/latest",
                                     headers={"User-Agent": "pkm-omr-helper", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            rel = json.loads(r.read().decode("utf-8"))
        assets = rel.get("assets") or []
        # コンソール付きでない、64bit Windows 用の .msi
        for a in assets:
            n = a.get("name", "")
            if re.search(r"windows.*x86_64\.msi$", n, re.I) and "console" not in n.lower():
                return rel.get("tag_name", "?"), a["browser_download_url"]
        for a in assets:
            n = a.get("name", "")
            if re.search(r"windows.*\.msi$", n, re.I):
                return rel.get("tag_name", "?"), a["browser_download_url"]
    except Exception as e:  # noqa: BLE001
        say("Audiveris の最新版を調べられませんでした（%s）。既知の版を使います" % e)
    return AUD_FALLBACK


def install_audiveris():
    if AUD_STATE["state"] == "installing":
        return
    if os.name != "nt":
        _aud_set(state="error", error="自動インストールは Windows だけです",
                 hint="https://github.com/Audiveris/audiveris/releases から、お使いのOS用のものをインストールしてください。")
        return
    import urllib.request
    _aud_set(state="installing", percent=1, phase="最新版を調べています…", error="", hint="")
    say("Audiveris のインストールを始めます")
    msi = os.path.join(DATA_DIR, "audiveris-setup.msi")
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        ver, url = _latest_audiveris_msi()
        _aud_set(percent=3, phase="Audiveris %s をダウンロード中…" % ver)
        req = urllib.request.Request(url, headers={"User-Agent": "pkm-omr-helper"})
        with urllib.request.urlopen(req, timeout=60) as r, open(msi, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if total:
                    _aud_set(percent=3 + round(got / total * 77),
                             phase="Audiveris %s をダウンロード中（%d / %d MB）" % (ver, got >> 20, total >> 20))
        _aud_set(percent=82, phase="展開しています（1〜2分）…")
        shutil.rmtree(AUD_DIR, ignore_errors=True)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(["msiexec", "/a", msi, "/qn", "TARGETDIR=" + AUD_DIR], timeout=900, creationflags=flags)
        if not find_audiveris():
            # 展開できなかった → 通常のインストール（Windows の許可の確認が出ます）
            _aud_set(percent=90, phase="インストールしています（「このアプリがデバイスに変更を加えることを許可しますか？」が出たら「はい」を押してください）…")
            subprocess.run(["msiexec", "/i", msi, "/qb"], timeout=1800)
        if find_audiveris():
            _aud_set(state="ready", percent=100, phase="準備完了")
            say("Audiveris のインストールが終わりました: %s" % find_audiveris()[0])
        else:
            _aud_set(state="error", error="Audiveris を入れられませんでした",
                     hint="https://github.com/Audiveris/audiveris/releases から手動でインストールしてください。")
    except Exception as e:  # noqa: BLE001
        say("Audiveris のインストールに失敗: %s" % e)
        _aud_set(state="error", error=str(e), hint=_explain_error(str(e)))
    finally:
        try:
            os.remove(msi)
        except OSError:
            pass


# ---------------- 自分自身の更新（2.4 から） ----------------
# アプリから「新しくして」と頼まれたら、アプリの公式サイトから新しい補助プログラムを取ってきて
# 置き換え、起動し直す。取ってくる場所は決まったURLだけ（頼む側から中身を受け取ることはしない）。
UPDATE_BASE = "https://hirosak514.github.io/PianoKeyMarker/helper/"
UPDATE_STATE = {"state": "idle", "error": ""}


def _ver_tuple(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def self_update():
    """新しい補助プログラム（.py と 起動用 .bat）を取ってきて置き換え、起動し直す（Windows のブラウザ版用）"""
    import urllib.request
    UPDATE_STATE.update(state="updating", error="")
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        bat = os.path.join(here, "helper.bat")
        if os.name != "nt" or not os.path.isfile(bat):
            raise RuntimeError("この補助プログラムは自動で更新できません（Windowsアプリ版はアプリの更新で新しくなります）")
        def get(name):
            req = urllib.request.Request(UPDATE_BASE + name + "?t=%d" % int(time.time()), headers={"User-Agent": "pkm-omr-helper"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        new_bat = get("launcher.bat")
        text = new_bat.decode("utf-8", "replace")
        m = re.search(r'VERSION = "([0-9.]+)"', text)
        if "PKM-HELPER-PY BEGIN" not in text or not m:
            raise RuntimeError("更新用のファイルが正しくありません")
        if _ver_tuple(m.group(1)) <= _ver_tuple(VERSION):
            UPDATE_STATE.update(state="latest")
            return
        with open(bat + ".new", "wb") as f:
            f.write(new_bat)
        os.replace(bat + ".new", bat)
        say("補助プログラムを %s に更新しました。起動し直します…" % m.group(1))
        UPDATE_STATE.update(state="restarting")
        # 新しい起動用ファイルを最小化で起動する（起動時に、この古い補助プログラムを終了させる）
        subprocess.Popen(["cmd", "/c", "start", "PianoKeyMarker", "/min", bat, "--protocol"],
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    except Exception as e:  # noqa: BLE001
        say("補助プログラムの更新に失敗: %s" % e)
        UPDATE_STATE.update(state="error", error=str(e))


def find_audiveris():
    cands = []
    if AUDIVERIS_OVERRIDE:
        cands.append(AUDIVERIS_OVERRIDE)
    if os.environ.get("PKM_AUDIVERIS"):
        cands.append(os.environ["PKM_AUDIVERIS"])
    for name in ("Audiveris", "audiveris"):
        w = shutil.which(name)
        if w:
            cands.append(w)
    if os.name == "nt":
        for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                cands += [os.path.join(base, "Audiveris", "Audiveris.exe"), os.path.join(base, "Programs", "Audiveris", "Audiveris.exe")]
        cands.append(os.path.expanduser(r"~\scoop\apps\audiveris\current\Audiveris.exe"))
        # この補助プログラムが展開したもの（install_audiveris）
        cands += sorted(glob.glob(os.path.join(AUD_DIR, "**", "Audiveris.exe"), recursive=True))
    elif sys.platform == "darwin":
        for base in ("/Applications", os.path.expanduser("~/Applications")):
            cands += glob.glob(os.path.join(base, "Audiveris*.app", "Contents", "MacOS", "Audiveris*"))
    else:
        cands += ["/opt/audiveris/bin/Audiveris", "/usr/bin/audiveris", "/usr/local/bin/audiveris"]
    for c in cands:
        if c and os.path.isfile(c):
            return [c]
    # Linux の Flatpak 版
    if shutil.which("flatpak"):
        try:
            r = subprocess.run(["flatpak", "info", "org.audiveris.audiveris"], capture_output=True, timeout=10)
            if r.returncode == 0:
                return ["flatpak", "run", "org.audiveris.audiveris"]
        except Exception:
            pass
    return None


def engines_status():
    hs = HOMR_STATE["state"]
    homr_note = {"checking": "確認中", "not_installed": "まだインストールされていません", "installing": "インストール中 %d%%" % HOMR_STATE["percent"],
                 "error": "インストールに失敗しました", "ready": ""}.get(hs, "")
    return {
        "homr": {"available": hs == "ready", "ready": hs == "ready", "installable": bool(uv_cmd()), "note": homr_note,
                 "label": "homr（いちばんおすすめ）", "install": {k: HOMR_STATE[k] for k in ("state", "percent", "phase", "error", "hint")},
                 "elapsed": round(time.time() - HOMR_STATE["started"]) if hs == "installing" else 0},
        "audiveris": {"available": find_audiveris() is not None,
                      "note": "" if find_audiveris() else ("インストール中 %d%%" % AUD_STATE["percent"] if AUD_STATE["state"] == "installing" else "Audiveris がインストールされていません"),
                      "label": "Audiveris（スキャン・印刷楽譜向け）",
                      "installable": os.name == "nt",
                      "install": dict(AUD_STATE)},
        "oemer": {"available": find_oemer() is not None, "note": "" if find_oemer() else ("Python 3.10〜3.13 が必要です" if not py_ok_for_oemer() else "インストールされていません"), "label": "oemer"},
    }


def read_musicxml_from(folder):
    """出力フォルダから MusicXML の文字列を取り出す（.mxl は展開）"""
    xmls = glob.glob(os.path.join(folder, "**", "*.musicxml"), recursive=True) + \
        [p for p in glob.glob(os.path.join(folder, "**", "*.xml"), recursive=True) if not p.endswith("container.xml")]
    if xmls:
        with open(sorted(xmls)[0], "rb") as f:
            return f.read()
    for mxl in sorted(glob.glob(os.path.join(folder, "**", "*.mxl"), recursive=True)):
        with zipfile.ZipFile(mxl) as z:
            root = None
            if "META-INF/container.xml" in z.namelist():
                import xml.etree.ElementTree as ET
                c = ET.fromstring(z.read("META-INF/container.xml"))
                for el in c.iter():
                    if el.tag.endswith("rootfile") and el.get("full-path"):
                        root = el.get("full-path")
                        break
            if not root:
                root = next((n for n in z.namelist() if not n.startswith("META-INF") and n.endswith(".xml")), None)
            if root:
                return z.read(root)
    return None


def run_engine(engine, src, work):
    out = os.path.join(work, "out")
    os.makedirs(out, exist_ok=True)
    if engine == "oemer":
        cmd = find_oemer()
        if not cmd:
            raise RuntimeError("oemer が使えません（Python 3.10〜3.13 で補助プログラムを起動してください）")
        proc = subprocess.run(cmd + [src, "-o", out], capture_output=True, text=True, timeout=TIMEOUT_SEC)
    elif engine == "homr":
        uv = uv_cmd()
        if not uv:
            raise RuntimeError("homr を動かす uv が入っていません。補助プログラムを起動し直してください")
        # homr は画像と同じ場所に結果を書き出す
        img = os.path.join(out, os.path.basename(src))
        shutil.copy(src, img)
        proc = subprocess.run(uv + HOMR_CMD + [img], capture_output=True, text=True, timeout=TIMEOUT_SEC, cwd=out)
    elif engine == "audiveris":
        cmd = find_audiveris()
        if not cmd:
            raise RuntimeError("Audiveris が見つかりません。https://github.com/Audiveris/audiveris/releases からインストールしてください（入れた場所が特殊な場合は --audiveris で指定）")
        proc = subprocess.run(cmd + ["-batch", "-transcribe", "-export", "-output", out, src], capture_output=True, text=True, timeout=TIMEOUT_SEC)
    else:
        raise RuntimeError("不明なエンジンです: " + engine)
    xml = read_musicxml_from(out)
    if xml is None:
        tail = (proc.stderr or proc.stdout or "")[-600:]
        hint = ""
        if proc.returncode < 0 or proc.returncode in (137, -9):
            hint = "（メモリ不足で止まった可能性があります。ほかのアプリを閉じてもう一度お試しください）"
        elif proc.returncode == 0:
            hint = "（楽譜を見つけられなかった可能性があります。画像を大きく・まっすぐにして試してください）"
        raise RuntimeError(f"{engine} の読み取りに失敗しました（終了コード {proc.returncode}）{hint}: {tail}")
    return xml


class Handler(BaseHTTPRequestHandler):
    server_version = "pkm-omr-helper/" + VERSION

    def log_message(self, fmt, *args):
        sys.stderr.write("[helper] " + (fmt % args) + "\n")

    def cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def reply(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_one_request(self):
        LAST_ACTIVITY[0] = time.time()
        return super().handle_one_request()

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/")
        if path in ("", "/health"):
            eng = engines_status()
            self.reply(200, {"ok": True, "version": VERSION, "engines": eng, "selfUpdate": UPDATE_STATE,
                             "available": any(e["available"] for e in eng.values()), "engine": "multi"})
        else:
            self.reply(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path.rstrip("/") == "/self-update":
            if UPDATE_STATE["state"] not in ("updating", "restarting"):
                threading.Thread(target=self_update, daemon=True).start()
            return self.reply(200, {"ok": True})
        if u.path.rstrip("/") == "/audiveris/install":
            if AUD_STATE["state"] != "installing" and not find_audiveris():
                threading.Thread(target=install_audiveris, daemon=True).start()
            return self.reply(200, {"ok": True})
        if u.path.rstrip("/") == "/homr/install":
            if HOMR_STATE["state"] != "installing":
                threading.Thread(target=install_homr, daemon=True).start()
            return self.reply(200, {"ok": True})
        if u.path.rstrip("/") != "/omr":
            return self.reply(404, {"error": "not found"})
        engine0 = (parse_qs(u.query).get("engine") or ["oemer"])[0].lower()
        if engine0 == "homr" and HOMR_STATE["state"] != "ready":
            return self.reply(409, {"error": "homr はまだインストールされていません。「homr を準備する」からインストールしてください", "code": "homr_not_ready"})
        engine = (parse_qs(u.query).get("engine") or ["oemer"])[0].lower()
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BYTES:
            return self.reply(400, {"error": "画像が空か、大きすぎます"})
        data = self.rfile.read(n)
        ctype = (self.headers.get("Content-Type") or "").lower()
        ext = ".png" if "png" in ctype else ".jpg"
        work = tempfile.mkdtemp(prefix="pkm-omr-")
        try:
            src = os.path.join(work, "page" + ext)
            with open(src, "wb") as f:
                f.write(data)
            say(f"[{engine}] 読み取り中…")
            with LOCK:
                xml = run_engine(engine, src, work)
            say(f"[{engine}] 完了")
            return self.reply(200, xml, "application/vnd.recordare.musicxml+xml")
        except subprocess.TimeoutExpired:
            return self.reply(504, {"error": "時間がかかりすぎたため中止しました"})
        except Exception as e:  # noqa: BLE001
            say(f"[{engine}] 失敗: {e}")
            return self.reply(500, {"error": str(e)})
        finally:
            shutil.rmtree(work, ignore_errors=True)


def ensure_setup():
    """初回だけ必要な部品をインストールする"""
    need = []
    if not uv_cmd():
        need.append(("homr 用の uv", ["uv"]))
    if py_ok_for_oemer() and not oemer_ok():
        need.append(("oemer", None))
    if not need:
        return
    say("初回のみ：必要な部品をインストールします（数分かかります）…")
    for name, pkgs in need:
        if pkgs:
            ok = pip_install(pkgs)
        else:
            ok = pip_install(["--no-deps", "oemer"]) and pip_install(OEMER_DEPS)
        if not ok:
            say(f"※ {name} のインストールに失敗しました。インターネット接続を確認して、もう一度起動してください。")
    importlib.invalidate_caches()


def _console_utf8():
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _idle_watch(srv, limit):
    """アプリ（ブラウザ）から一定時間接続がなければ終了する。
    アプリは開いている間、定期的に /health へ接続してくる。ブラウザやタブを閉じると接続が止まる。
    読み取り中・homr のインストール中は終了しない。"""
    while True:
        time.sleep(5)
        idle = time.time() - LAST_ACTIVITY[0]
        busy = LOCK.locked() or HOMR_STATE.get("state") == "installing" or AUD_STATE.get("state") == "installing"
        if idle >= limit and not busy:
            say("Chopin the Ⅲの画面が閉じられたため、補助プログラムを終了します。")
            try:
                srv.shutdown()
            except Exception:
                pass
            return


def main():
    global AUDIVERIS_OVERRIDE
    _console_utf8()
    ap = argparse.ArgumentParser(description="Chopin the Ⅲ 補助プログラム")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--audiveris", help="Audiveris の実行ファイルの場所")
    ap.add_argument("--no-setup", action="store_true", help="インストールの確認をしない")
    ap.add_argument("--no-homr-prepare", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--install-homr", action="store_true", help="起動と同時に homr をインストールする")
    ap.add_argument("--idle-exit", type=int, default=0,
                    help="アプリからの接続がこの秒数ないとき自動で終了する（ブラウザから起動した場合。0=終了しない）")
    args = ap.parse_args()
    AUDIVERIS_OVERRIDE = args.audiveris
    say("Chopin the Ⅲ 補助プログラム " + VERSION)
    if not py_ok_for_oemer():
        say("※ この Python（%d.%d）では oemer は使えません（homr・Audiveris は使えます）。" % sys.version_info[:2])
    if not args.no_setup:
        ensure_setup()
    st = engines_status()
    for key, e in st.items():
        if key == "homr":
            say("  ・homr（いちばんおすすめ）：インストール済みか確認しています")
            continue
        mark = "使えます" if e["available"] else "使えません（" + e["note"] + "）"
        say(f"  ・{e['label']}：{mark}")
    threading.Thread(target=check_homr, daemon=True).start()
    if args.install_homr:
        threading.Thread(target=install_homr, daemon=True).start()
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:
        # すでに補助プログラムが動いている（同じ番号を使っている）: そちらを使うので、ここは静かに終わる
        say("補助プログラムはすでに起動しています。このウィンドウは閉じてかまいません。")
        return
    if args.idle_exit > 0:
        LAST_ACTIVITY[0] = time.time()
        threading.Thread(target=_idle_watch, args=(srv, args.idle_exit), daemon=True).start()
        say(f"Chopin the Ⅲの画面を閉じると、{args.idle_exit // 60}分ほどで自動的に終了します。")
    say(f"Chopin the Ⅲ 補助プログラムを起動しました： http://127.0.0.1:{args.port}")
    say("このウィンドウを開いている間、Chopin the Ⅲから専用エンジンを使えます。終了は Ctrl+C。")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
