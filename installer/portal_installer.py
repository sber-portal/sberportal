#!/usr/bin/env python3
"""
SberPortal → Яндекс Centaur (Дуо Макс): установщик.

Делает всё по шагам: проверяет ADB и identity, получает постоянный root,
ставит патченный Centaur, модель «Алиса», обвязку top sheet, отключает Sber,
проверяет результат и убирает за собой временные файлы.

Требуется: Python 3.8+, adb (platform-tools), доступ в интернет.
Репозитории публичные, токен не нужен. Если вы форкнули их в приватные —
нужен fine-grained PAT с правом Contents: Read на свои копии.

Запуск:
    python3 portal_installer.py                 # интерактивно
    python3 portal_installer.py --ip 192.168.1.50
    GITHUB_TOKEN=... python3 portal_installer.py --yes

Ключи и id НЕ вшиваются в APK: identity (device_id + private.pem) кладётся
в данные приложения уже после установки.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zlib
import zipfile

VERSION = "1.0"
OWNER = "sber-portal"
REPO_MAIN = "sberportal"
REPO_ROOT = "sberportal-root"
REPO_CENTAUR = "sberportal-centaur"
RELEASE_TAG = "v1"

APK_NAME = "centaur-voice-patched.apk"
MODEL_NAME = "duomax-alisa-model.zip"
KEYBOARD_NAME = "yandex-keyboard-centaur-signed.apk"

PKG = "ru.yandex.quasar.centaur_app"

# Холст шелл-кода эксплойта. vmalloc вызывается редко, поэтому payload в нём не
# ловит мусорные аргументы; дефолт VERIFY=13 (__alloc_page_frag) роняет ядро.
EXPLOIT_ENV = "SP_FUNC=0x19bbf0 SP_FUNC_ABS=0xffffff800921bbf0"

DISABLE_APPS = """
ru.sberdevices.startube ru.sberdevices.videos ru.sberdevices.tv
ru.sberdevices.sberplay ru.sberdevices.starmarket ru.sberdevices.telegramcalls
ru.sberdevices.cv ru.sberdevices.gesturesGuide ru.sberdevices.biometryapp
ru.sberdevices.newswidget ru.sberdevices.trafficwidget ru.sberdevices.smarthome.promo
ru.sberdevices.starcleaner ru.sberdevices.starprofile ru.sberdevices.huaweicast
ru.sberdevices.gamepad.service ru.sberdevices.CleanupStub ru.sberdevices.bugreporter
com.salute.star ru.sberdevices.visor com.banda.sberuyshki com.sberdevices.chudoknizhki
ru.sberdevices.specialwidgets ru.sberdevices.starscreensaver ru.sberdevices.webview
""".split()

PREBOOT = (
    "setenv EnableSelinux permissive;setenv rabbith_has_adb_root yes;"
    "run bcb_cmd; run init_display;run factory_reset_key;run storeargs;"
    "forceupdate;bcb uboot-command;run check_sdts_mode;run switch_bootmode;"
    "setenv bootargs ${bootargs} androidboot.rabbith.adb_root=1;"
)


# ---------------------------------------------------------------- UI helpers

class Fail(Exception):
    pass


def say(msg: str = "") -> None:
    print(msg, flush=True)


def step(n: str, msg: str) -> None:
    say(f"\n=== {n}. {msg}")


def ok(msg: str) -> None:
    say(f"  OK  {msg}")


def warn(msg: str) -> None:
    say(f"  !   {msg}")


def ask(msg: str, default: bool = True) -> bool:
    if AUTO_YES:
        return default
    suffix = " [Y/n] " if default else " [y/N] "
    ans = input(msg + suffix).strip().lower()
    if not ans:
        return default
    return ans in ("y", "yes", "д", "да")


AUTO_YES = False
SKIP_ROOT = False


# ---------------------------------------------------------------- processes

def run(cmd, timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def adb(serial: str, *args: str, timeout: int | None = None) -> str:
    p = run(["adb", "-s", serial, *args], timeout=timeout)
    if p.returncode != 0:
        raise Fail(f"adb {' '.join(args)}: {p.stderr.strip() or p.stdout.strip()}")
    return p.stdout


def adb_shell(serial: str, cmd: str, timeout: int | None = None) -> str:
    return adb(serial, "shell", cmd, timeout=timeout)


def adb_try(serial: str, *args: str) -> bool:
    return run(["adb", "-s", serial, *args]).returncode == 0


# ---------------------------------------------------------------- GitHub

class GitHub:
    """Репозитории могут быть публичными (токен не нужен) или приватными (нужен PAT)."""

    HINT_PRIVATE = ("файл недоступен. Если репозитории приватные, нужен GitHub-токен "
                    "с Contents: Read (--token или GITHUB_TOKEN).")

    def __init__(self, token: str | None):
        self.token = token

    def _request(self, url: str, accept: str = "application/vnd.github+json"):
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"sberportal-installer/{VERSION}",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return urllib.request.Request(url, headers=headers)

    def json(self, url: str):
        try:
            with urllib.request.urlopen(self._request(url), timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise Fail("GitHub: токен не принят (401). Проверьте GITHUB_TOKEN.")
            if e.code == 404:
                raise Fail(f"GitHub: 404. {self.HINT_PRIVATE}")
            if e.code == 403:
                raise Fail("GitHub: 403 — лимит запросов. Задайте токен (лимит выше) "
                           "или повторите позже.")
            raise Fail(f"GitHub: HTTP {e.code} для {url}")

    def _download(self, url: str, dest: str, total: int | None = None) -> None:
        tmp = dest + ".part"
        try:
            with urllib.request.urlopen(self._request(url, accept="application/octet-stream"),
                                        timeout=120) as r, open(tmp, "wb") as f:
                total = total or int(r.headers.get("Content-Length") or 0)
                got = 0
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if total > 20 * 1048576:
                        sys.stdout.write(f"\r      {got * 100 // total:3d}%")
                        sys.stdout.flush()
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                raise Fail(f"{e.code}: {self.HINT_PRIVATE}")
            raise Fail(f"загрузка не удалась: HTTP {e.code} ({url})")
        os.replace(tmp, dest)
        if total and total > 20 * 1048576:
            say("")

    def repo_file(self, repo: str, path: str, dest: str, ref: str = "main") -> None:
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        if self.token:
            data = self.json(f"https://api.github.com/repos/{OWNER}/{repo}/contents/{path}?ref={ref}")
            if data.get("encoding") != "base64":
                raise Fail(f"неожиданный ответ для {repo}/{path}")
            blob = base64.b64decode(data["content"])
            with open(dest, "wb") as f:
                f.write(blob)
            name = data["name"]
        else:
            url = f"https://raw.githubusercontent.com/{OWNER}/{repo}/{ref}/{path}"
            self._download(url, dest)
            name = os.path.basename(path)
        os.chmod(dest, 0o755 if name.endswith((".sh", ".py", ".exp")) else 0o644)

    def release_asset(self, repo: str, name: str, dest: str) -> None:
        say(f"  … качаю {name}")
        if self.token:
            rel = self.json(f"https://api.github.com/repos/{OWNER}/{repo}/releases/tags/{RELEASE_TAG}")
            asset = next((a for a in rel.get("assets", []) if a["name"] == name), None)
            if not asset:
                raise Fail(f"в релизе {repo}@{RELEASE_TAG} нет файла {name}")
            self._download(asset["url"], dest, asset["size"])
        else:
            self._download(
                f"https://github.com/{OWNER}/{repo}/releases/download/{RELEASE_TAG}/{name}",
                dest,
            )


# ---------------------------------------------------------------- identity

def find_identity(explicit: str | None, base: str) -> tuple[str | None, str | None]:
    """Возвращает (private.pem, device_id)."""
    candidates = [explicit] if explicit else []
    candidates += [os.path.join(base, "identity"), os.path.join(os.getcwd(), "identity")]
    for d in candidates:
        if not d or not os.path.isdir(d):
            continue
        key = os.path.join(d, "private.pem")
        did = None
        for name in ("device_id", "device_id.txt"):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                did = open(p, encoding="utf-8").read().strip()
                break
        if os.path.isfile(key):
            return key, did
    return None, None


def validate_identity(key_path: str | None, device_id: str | None) -> list[str]:
    problems = []
    if not key_path:
        problems.append("нет private.pem")
    else:
        body = open(key_path, encoding="utf-8", errors="replace").read()
        if "PRIVATE KEY-----" not in body:
            problems.append("private.pem не похож на PEM-ключ")
    if not device_id:
        problems.append("нет device_id")
    elif not re.fullmatch(r"[A-Za-z0-9_.:-]{3,64}", device_id):
        problems.append("device_id выглядит подозрительно")
    return problems


# ---------------------------------------------------------------- device ops

def pick_serial(ip: str | None, gh: GitHub, work: str) -> str:
    if ip:
        serial = ip if ":" in ip else f"{ip}:5555"
        say(f"  подключаюсь к {serial}")
        run(["adb", "connect", serial])
        if not adb_try(serial, "get-state"):
            raise Fail(
                "нет связи по adb.\n"
                "  1) Портал должен быть настроен через приложение «Салют» (язык, Wi-Fi, аккаунт).\n"
                "  2) Включите ADB: https://developers.sber.ru/studio/settings/devices → добавить серийный номер.\n"
                "  3) Проверьте, что компьютер и портал в одной сети, и повторите с --ip."
            )
        return serial

    p = run(["adb", "devices"])
    lines = [l.split()[0] for l in p.stdout.splitlines()[1:] if l.strip() and "\tdevice" in l]
    if len(lines) == 1:
        say(f"  найден adb-девайс: {lines[0]}")
        return lines[0]
    if len(lines) > 1:
        say("  найдено несколько устройств:")
        for i, l in enumerate(lines, 1):
            say(f"    {i}) {l}")
        idx = input("  выберите номер: ").strip()
        try:
            return lines[int(idx) - 1]
        except (ValueError, IndexError):
            raise Fail("неверный выбор устройства")

    say("\n  adb-устройств не найдено. Введите IP портала (можно узнать в роутере):")
    ip = input("  IP: ").strip()
    if not ip:
        raise Fail("IP не указан")
    return pick_serial(ip, gh, work)


def wait_device(serial: str, timeout: int = 90) -> None:
    say("  жду устройство…")
    end = time.time() + timeout
    while time.time() < end:
        if adb_try(serial, "get-state"):
            return
        time.sleep(2)
    raise Fail("устройство не появилось в adb")


def wait_boot_completed(serial: str, timeout: int = 180) -> None:
    """Ждать sys.boot_completed=1: adb появляется раньше, чем adbd готов к root."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            if adb_shell(serial, "getprop sys.boot_completed").strip() == "1":
                return
        except Fail:
            pass
        time.sleep(3)
    raise Fail("портал не завершил загрузку за отведённое время")


def is_root(serial: str) -> bool:
    try:
        return adb_shell(serial, "id -u").strip() == "0"
    except Fail:
        return False


def exploit_with_cmd(serial: str, cmd: str = "", attempts: int = 30) -> str:
    """Прогон raven_sber с SP_CMD; повтор до `uid=0`.

    Нужен до того, как заработает `adb root`: эксплойт поднимает привилегии
    только своему процессу, поэтому привилегированные шаги (u-boot env) идут
    через SP_CMD. Возвращает лог прогона (с выводом команды).
    """
    log = "/data/local/tmp/root.log"
    for attempt in range(1, attempts + 1):
        if not adb_try(serial, "get-state"):
            warn(f"[{attempt}] устройство offline — ждём загрузку")
            time.sleep(20)
            run(["adb", "connect", serial])
            continue
        # не через adb_shell(): при крахе ядра adb вернёт ошибку, а нам нужен
        # повтор, а не аварийное завершение всего установщика.
        run(["adb", "-s", serial, "shell",
             "pidof hog >/dev/null || (nohup /data/local/tmp/hog 900 >/dev/null 2>&1 &)"])
        run(["adb", "-s", serial, "shell",
             f"rm -f {log}; cd /data/local/tmp && "
             f"timeout 180 env RAVEN_VERIFY=13 {EXPLOIT_ENV} "
             f"SP_CMD='{cmd}' ./raven_sber > {log} 2>&1"], timeout=240)
        p = run(["adb", "-s", serial, "shell", f"cat {log} 2>/dev/null"])
        out = p.stdout if p.returncode == 0 else ""
        if "uid=0 euid=0" in out:
            return out
        warn(f"[{attempt}] не вышло, пробую ещё")
    raise Fail("root не получен за 30 попыток — перезагрузите портал и запустите установщик снова")


def ensure_root(serial: str, gh: GitHub, work: str) -> None:
    if is_root(serial):
        ok("root уже есть")
        return

    if SKIP_ROOT:
        warn("--skip-root: продолжаю без root (большинство шагов не сработает)")
        return

    say("\n  Root: эксплойт CVE-2022-38181 (Mali) + постоянная запись u-boot env.")
    warn("Эксплойт флаки: при неудаче устройство может перезагрузиться — это нормально.")
    if not ask("Продолжить получение root?", True):
        raise Fail("root обязателен для установки Centaur")

    d = os.path.join(work, "root")
    for name in ("prebuilt/raven_sber", "prebuilt/hog", "prebuilt/adbroot.apk"):
        gh.repo_file(REPO_ROOT, name, os.path.join(d, name))

    adb(serial, "push", os.path.join(d, "prebuilt/raven_sber"), "/data/local/tmp/raven_sber")
    adb(serial, "push", os.path.join(d, "prebuilt/hog"), "/data/local/tmp/hog")
    adb_shell(serial, "chmod 755 /data/local/tmp/raven_sber /data/local/tmp/hog")
    adb_shell(serial, "nohup /data/local/tmp/hog 900 >/dev/null 2>&1 &")

    exploit_with_cmd(serial)
    ok("root получен")

    make_persistent_root(serial, gh, work)
    install_adbroot(serial, gh, work)


def patch_env(blob: bytes) -> bytes:
    if len(blob) != 0x10000:
        raise Fail(f"env: ожидался блок 65536 байт, получено {len(blob)}")
    data = blob[4:]
    marker = b"preboot="
    pos = data.find(marker)
    if pos < 0:
        raise Fail("в env нет preboot")
    end = data.find(b"\x00", pos)
    entries = []
    for chunk in data.split(b"\x00"):
        if not chunk or b"=" not in chunk:
            break
        entries.append(chunk)
    replaced = False
    for i, e in enumerate(entries):
        if e.startswith(marker):
            entries[i] = marker + PREBOOT.encode()
            replaced = True
            break
    if not replaced:
        entries.append(marker + PREBOOT.encode())
    body = b"\x00".join(entries) + b"\x00"
    if len(body) > 0xFFFC:
        raise Fail("env: preboot не помещается")
    body += b"\x00" * (0xFFFC - len(body))
    return struct.pack("<I", zlib.crc32(body) & 0xFFFFFFFF) + body


def make_persistent_root(serial: str, gh: GitHub, work: str) -> None:
    say("\n  Постоянный root: правка preboot в u-boot env (переживает перезагрузку).")
    say("  adb root ещё не работает — env правим двумя прогонами эксплойта через SP_CMD.")

    d = os.path.join(work, "root")
    os.makedirs(d, exist_ok=True)
    dump_sh = os.path.join(d, "env_dump.sh")
    write_sh = os.path.join(d, "env_write.sh")
    open(dump_sh, "w").write(
        "#!/system/bin/sh\n"
        "dd if=/dev/block/env of=/data/local/tmp/env_orig.bin bs=4096 count=16\n"
        "sync\n"
        "sha256sum /data/local/tmp/env_orig.bin\n"
        "chmod 644 /data/local/tmp/env_orig.bin\n"
        "echo ENV_DUMP_OK\n")
    open(write_sh, "w").write(
        "#!/system/bin/sh\n"
        "dd if=/data/local/tmp/env_new.bin of=/dev/block/env bs=4096\n"
        "sync\n"
        "dd if=/dev/block/env of=/data/local/tmp/env_chk.bin bs=4096 count=16\n"
        "sync\n"
        "if cmp -s /data/local/tmp/env_new.bin /data/local/tmp/env_chk.bin; then\n"
        "  echo ENV_OK\n"
        "else\n"
        "  echo ENV_MISMATCH\n"
        "fi\n"
        "chmod 644 /data/local/tmp/env_chk.bin\n")
    adb(serial, "push", dump_sh, "/data/local/tmp/sber_env_dump.sh")
    adb(serial, "push", write_sh, "/data/local/tmp/sber_env_write.sh")
    adb_shell(serial, "chmod 755 /data/local/tmp/sber_env_dump.sh /data/local/tmp/sber_env_write.sh")

    say("  проход 1: снимаю /dev/block/env")
    out = exploit_with_cmd(serial, "sh /data/local/tmp/sber_env_dump.sh")
    if "ENV_DUMP_OK" not in out:
        raise Fail("не удалось снять env под root — повторите запуск")
    local = os.path.join(work, "env_orig.bin")
    adb(serial, "pull", "/data/local/tmp/env_orig.bin", local)

    patched = patch_env(open(local, "rb").read())
    local_new = os.path.join(work, "env_new.bin")
    open(local_new, "wb").write(patched)
    adb(serial, "push", local_new, "/data/local/tmp/env_new.bin")
    adb_shell(serial, "chmod 644 /data/local/tmp/env_new.bin")

    say("  проход 2: записываю env")
    out = exploit_with_cmd(serial, "sh /data/local/tmp/sber_env_write.sh")
    if "ENV_OK" not in out:
        raise Fail("env записан с ошибкой — прерываю, устройство не перезагружаю "
                   f"(бэкап: {local})")
    ok("env записан, перезагружаю")
    adb(serial, "reboot")
    time.sleep(10)
    wait_device(serial, 180)
    wait_boot_completed(serial, 180)
    run(["adb", "connect", serial])
    adb_try(serial, "root")
    for _ in range(20):
        if is_root(serial):
            ok("постоянный root работает")
            return
        time.sleep(3)
    raise Fail("после перезагрузки нет root — проверьте preboot в env")


def install_adbroot(serial: str, gh: GitHub, work: str) -> None:
    apk = os.path.join(work, "root/prebuilt/adbroot.apk")
    if not os.path.exists(apk):
        gh.repo_file(REPO_ROOT, "prebuilt/adbroot.apk", apk)
    adb(serial, "install", "-r", apk)
    adb_shell(serial, "am start -n com.user.adbroot/.MainActivity")
    time.sleep(3)
    ok("авто-root при загрузке установлен")


# ---------------------------------------------------------------- Centaur

def install_centaur(serial: str, gh: GitHub, work: str,
                    apk_path: str | None, model_dir: str | None,
                    key_path: str | None, device_id: str | None) -> None:
    d = os.path.join(work, "centaur")
    os.makedirs(d, exist_ok=True)

    apk = apk_path or os.path.join(d, APK_NAME)
    if not apk_path:
        gh.release_asset(REPO_MAIN, APK_NAME, apk)
    say(f"  ставлю {os.path.basename(apk)}")
    adb(serial, "install", "-r", "-g", apk)
    ok("Centaur установлен")

    adb_shell(serial, f"cmd appops set {PKG} WRITE_SETTINGS allow")
    ok("WRITE_SETTINGS выдан (яркость)")

    if key_path and device_id:
        say("  кладу identity (device_id + private.pem)")
        adb(serial, "push", key_path, "/data/local/tmp/private.pem")
        adb_shell(serial,
                  f"PKG={PKG}; D=/data/data/$PKG/files/system; "
                  "OWN=$(stat -c %u:%g /data/data/$PKG); "
                  "mkdir -p $D; chown $OWN $D; "
                  "cp /data/local/tmp/private.pem $D/private.pem; "
                  "chown $OWN $D/private.pem; chmod 600 $D/private.pem")
        seed = os.path.join(work, "device_id.txt")
        open(seed, "w").write(device_id + "\n")
        adb(serial, "push", seed, "/data/local/tmp/device_id.txt")
        adb_shell(serial,
                  "mkdir -p /sdcard/Download; cp /data/local/tmp/device_id.txt "
                  "/sdcard/Download/centaur_device_id; chmod 644 /sdcard/Download/centaur_device_id")
        ok("identity на месте")
    else:
        warn("identity не передана: регистрация в Яндексе не пройдёт")

    if not model_dir:
        zip_path = os.path.join(d, MODEL_NAME)
        gh.release_asset(REPO_MAIN, MODEL_NAME, zip_path)
        model_dir = os.path.join(d, "model")
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(model_dir)
        # модель может лежать как в корне архива, так и в подкаталоге
        for root, _, files in os.walk(model_dir):
            if "acoustic_model.nnet" in files:
                model_dir = root
                break
    say("  ставлю модель «Алиса»")
    dst = f"/data/data/{PKG}/files/system/spotter_models/activation/alisa"
    adb_shell(serial, f"am force-stop {PKG}; rm -rf {dst}; mkdir -p {dst}")
    for name in ("acoustic_model.nnet", "flags.txt", "lda.mat", "words.txt"):
        src = os.path.join(model_dir, name)
        if not os.path.exists(src):
            raise Fail(f"в модели нет файла {name} ({model_dir})")
        adb(serial, "push", src, f"{dst}/{name}")
    adb_shell(serial,
              f"OWN=$(stat -c %u:%g /data/data/{PKG}); "
              f"chown -R $OWN {dst}; chmod 700 {dst}; chmod 600 {dst}/*")
    ok("модель установлена")
    adb_shell(serial, f"am force-stop {PKG}; am start -n {PKG}/.MainActivity >/dev/null")
    ok("Centaur запущен")


def silence_sber(serial: str) -> None:
    say("  отключаю ассистента и СберЗвук, закрываю микрофон сервису Sber")
    adb_shell(serial, "pm disable-user --user 0 ru.sberdevices.assistant || true")
    adb_shell(serial, f"am force-stop ru.sberdevices.music; pm uninstall -k --user 0 ru.sberdevices.music || true")
    adb_shell(serial, "cmd appops set ru.sberdevices.services RECORD_AUDIO deny || true")
    adb_shell(serial, "kill -9 $(pidof ru.sberdevices.services) 2>/dev/null || true")


def cleanup_sber_apps(serial: str) -> None:
    say("  выключаю лишние приложения Sber")
    for pkg in DISABLE_APPS:
        adb_shell(serial, f"pm disable-user --user 0 {pkg} >/dev/null 2>&1 || true")


# ---------------------------------------------------------------- top sheet

def install_top_sheet(serial: str, gh: GitHub, work: str) -> None:
    d = os.path.join(work, "centaur-tools")
    files = {
        "centaur_fix/centaur_watcher.dex": 0o644,
        "centaur_fix/ns_mount": 0o755,
        "sber_guard.sh": 0o755,
        "bootstarter/RavnBootStarter.apk": 0o644,
        "homeproxy/RavnHomeProxy.apk": 0o644,
    }
    for path in files:
        gh.repo_file(REPO_CENTAUR, path, os.path.join(d, path))

    adb(serial, "push", os.path.join(d, "centaur_fix/centaur_watcher.dex"),
        "/data/local/tmp/centaur_watcher.dex")
    adb(serial, "push", os.path.join(d, "centaur_fix/ns_mount"), "/data/local/tmp/centaur_ns_mount")
    adb(serial, "push", os.path.join(d, "sber_guard.sh"), "/data/local/tmp/sber_guard.sh")
    adb_shell(serial, "chmod 755 /data/local/tmp/centaur_ns_mount /data/local/tmp/sber_guard.sh")

    adb(serial, "install", "-r", "-g", os.path.join(d, "homeproxy/RavnHomeProxy.apk"))
    adb_shell(serial, "cmd package set-home-activity com.ravn.homeproxy/.HomeActivity || true")
    adb(serial, "install", "-r", "-g", os.path.join(d, "bootstarter/RavnBootStarter.apk"))

    adb_shell(serial, "killall app_process 2>/dev/null; rm -rf /data/local/tmp/oat; "
                      "rm -f /data/local/tmp/centaur_watcher.lock /data/local/tmp/centaur_watcher.log; "
                      "nohup env CLASSPATH=/data/local/tmp/centaur_watcher.dex "
                      "app_process /system/bin CentaurSwipeWatcher >/dev/null 2>&1 </dev/null &")
    time.sleep(4)
    ps = adb_shell(serial, "ps -A | grep -c app_process || true").strip()
    if ps in ("", "0"):
        warn("watcher не поднялся — смотрите /data/local/tmp/centaur_watcher.log")
    else:
        ok("watcher запущен (шторка по свайпу сверху)")


# ---------------------------------------------------------------- main

def main() -> int:
    global AUTO_YES, SKIP_ROOT

    ap = argparse.ArgumentParser(description="SberPortal → Centaur (Дуо Макс), установщик")
    ap.add_argument("--ip", help="IP портала (можно без :5555)")
    ap.add_argument("--identity", help="каталог с private.pem и device_id")
    ap.add_argument("--token", help="GitHub token (или GITHUB_TOKEN)")
    ap.add_argument("--apk", help="локальный патченный APK (иначе скачать из релиза)")
    ap.add_argument("--model", help="каталог с моделью alisa (иначе скачать из релиза)")
    ap.add_argument("--adb", help="путь к adb")
    ap.add_argument("--skip-root", action="store_true", help="не получать root (он уже есть)")
    ap.add_argument("--skip-top-sheet", action="store_true", help="не ставить шторку")
    ap.add_argument("--with-keyboard", action="store_true", help="заменить клавиатуру Sber")
    ap.add_argument("--no-cleanup", action="store_true", help="оставить скачанные файлы")
    ap.add_argument("--yes", "-y", action="store_true", help="не спрашивать подтверждений")
    ap.add_argument("--version", action="version", version=VERSION)
    args = ap.parse_args()

    AUTO_YES = args.yes
    SKIP_ROOT = args.skip_root

    if args.adb:
        os.environ["PATH"] = os.path.dirname(os.path.abspath(args.adb)) + os.pathsep + os.environ.get("PATH", "")

    say(f"SberPortal → Centaur, установщик v{VERSION}")
    say("=" * 56)

    if not shutil.which("adb"):
        say("\nНе найден adb. Установите Android platform-tools:")
        say("  macOS:   brew install --cask android-platform-tools")
        say("  Linux:   sudo apt install adb      # или из developer.android.com/tools/releases/platform-tools")
        say("  Windows: https://developer.android.com/tools/releases/platform-tools (распаковать, добавить в PATH)")
        return 2

    token = args.token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        say("\nGitHub: используем токен (для приватных репозиториев).")
    else:
        say("\nGitHub: токен не задан — качаем как аноним.")
        say("  Подходит, если репозитории публичные.")
        say("  Если приватные, создайте fine-grained PAT (Contents: Read) для:")
        say(f"    {OWNER}/{REPO_MAIN}, {OWNER}/{REPO_ROOT}, {OWNER}/{REPO_CENTAUR}")
        say("  и передайте в GITHUB_TOKEN или --token.")

    gh = GitHub(token)

    work = tempfile.mkdtemp(prefix="sberportal-install-")
    say(f"\nВременный каталог: {work}")

    try:
        step("1/7", "Портал и ADB")
        serial = pick_serial(args.ip, gh, work)
        wait_device(serial)
        ok(f"устройство {serial} на связи")

        step("2/7", "Identity (device_id + private.pem)")
        key, did = find_identity(args.identity, os.path.dirname(os.path.abspath(__file__)))
        problems = validate_identity(key, did)
        if problems:
            warn("identity не найдена или неполная: " + ", ".join(problems))
            say("  Это уникальные идентификаторы вашей Яндекс Станции.")
            say("  Без них Centaur установится, но не зарегистрируется в аккаунте.")
            if not ask("Продолжить без identity?", False):
                raise Fail("добавьте каталог identity (private.pem + device_id) и запустите снова")
            key = did = None
        else:
            ok(f"identity найдена: device_id={did[:4]}…, ключ {os.path.getsize(key)} Б")

        step("3/7", "Root")
        ensure_root(serial, gh, work)

        step("4/7", "Centaur: APK, identity, модель")
        install_centaur(serial, gh, work, args.apk, args.model, key, did)

        step("5/7", "Отключаю Sber")
        silence_sber(serial)
        cleanup_sber_apps(serial)

        step("6/7", "Top sheet")
        if args.skip_top_sheet:
            warn("пропущено по --skip-top-sheet")
        elif ask("Установить шторку Centaur (свайп сверху)?", True):
            install_top_sheet(serial, gh, work)
        else:
            warn("шторка не установлена")

        if args.with_keyboard:
            step("7/7", "Клавиатура Яндекса")
            kb = os.path.join(work, KEYBOARD_NAME)
            gh.release_asset(REPO_MAIN, KEYBOARD_NAME, kb)
            adb(serial, "install", "-r", kb)
            adb_shell(serial, "ime enable ru.yandex.androidkeyboard.centaur/"
                              "ru.yandex.androidkeyboard.inputmethod.YandexCentaurLatinIme")
            adb_shell(serial, "ime set ru.yandex.androidkeyboard.centaur/"
                              "ru.yandex.androidkeyboard.inputmethod.YandexCentaurLatinIme")
            if ask("Отключить клавиатуру Sber?", True):
                adb_shell(serial, "pm disable-user --user 0 ru.sberdevices.app.starkeyboard")
            ok("клавиатура заменена")
        else:
            step("7/7", "Клавиатура — пропущено (--with-keyboard чтобы заменить)")

        say("\n" + "=" * 56)
        say("Готово. Что проверить вручную:")
        say("  1. Откройте Centaur и войдите в Яндекс-аккаунт.")
        say("  2. Скажите «Алиса», затем «включи группу Кино» — должна заиграть музыка.")
        say("  3. Свайп сверху вниз — шторка Centaur.")
        say("\nЕсли голос молчит: adb logcat | grep -E 'AliceBridge|configured=|asrText'")

        if not args.no_cleanup and ask("\nУдалить скачанные временные файлы?", True):
            shutil.rmtree(work, ignore_errors=True)
            adb_shell(serial,
                      "rm -f /data/local/tmp/raven_sber /data/local/tmp/hog /data/local/tmp/root.log "
                      "/data/local/tmp/env_orig.bin /data/local/tmp/env_new.bin /data/local/tmp/env_chk.bin "
                      "/data/local/tmp/sber_env_dump.sh /data/local/tmp/sber_env_write.sh "
                      "/data/local/tmp/private.pem /data/local/tmp/device_id.txt")
            ok("временные файлы удалены (identity в приложении и device_id на /sdcard оставлены)")
        else:
            say(f"  файлы оставлены: {work}")

        return 0
    except Fail as e:
        say(f"\nОШИБКА: {e}")
        say(f"Временные файлы: {work}")
        return 1
    except KeyboardInterrupt:
        say("\nПрервано пользователем.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
