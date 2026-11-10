#!/bin/sh
# Первичная установка Centaur на SberPortal (с нуля или после сброса).
# Запускать с компьютера, когда портал уже настроен (приложение «Салют»),
# ADB включён через developers.sber.ru и получен постоянный root
# (см. sberportal-root) — скрипт только проверяет `adb root`.
#
#   IP=192.168.1.x ./restore_after_reset.sh centaur-voice-patched.apk ./duomax-alisa-model [./identity]
#
# identity — каталог с приватным ключом и device_id вашей Яндекс Станции:
#   identity/private.pem      (RSA 2048, /yak/private.pem с устройства)
#   identity/device_id        (строка вида <platform>_<номер>)
# Пара уникальна для конкретной Станции; без неё Centaur не зарегистрируется.
#
# ВАЖНО: никогда не отключать ru.sberdevices.services (staros) —
# это persistent-сервис, его disable приводит к бесконечной перезагрузке.
set -e
IP=${IP:?укажи IP портала: IP=192.168.1.x}
APK=${1:?путь к centaur-voice-patched.apk}
MODEL=${2:?путь к каталогу с моделью (acoustic_model.nnet flags.txt lda.mat words.txt)}
IDENTITY=${3:-}

[ -z "$IDENTITY" ] || {
  [ -f "$IDENTITY/private.pem" ] || { echo "нет $IDENTITY/private.pem" >&2; exit 1; }
  [ -f "$IDENTITY/device_id" ]   || { echo "нет $IDENTITY/device_id" >&2; exit 1; }
}
A="adb -s $IP:5555"
PKG=ru.yandex.quasar.centaur_app
DIR=/data/data/$PKG/files/system/spotter_models/activation/alisa

$A connect "$IP:5555" >/dev/null 2>&1 || true
$A wait-for-device
$A root >/dev/null 2>&1 || true
sleep 3
$A connect "$IP:5555" >/dev/null 2>&1 || true

echo "[1/6] установка патченного Centaur"
$A install -r "$APK" || {
  echo "подпись не совпала — удаляю стоковый и ставлю заново (данные Centaur будут потеряны)"
  $A shell pm uninstall $PKG || true
  $A install "$APK"
}

echo "[1a/6] WRITE_SETTINGS для Centaur (яркость/авто-яркость)"
# APK переподписан debug-ключом и не является системным, поэтому без этого
# appop `Settings.System.putInt` падает с SecurityException:
# BrightnessManager: can't update brightness ... not granted WRITE_SETTINGS.
$A shell "cmd appops set $PKG WRITE_SETTINGS allow" || true

echo "[1b/6] identity: device_id + private.pem (в APK ключ-заглушка, нужна своя пара)"
if [ -n "$IDENTITY" ]; then
  $A push "$IDENTITY/private.pem" /data/local/tmp/private.pem >/dev/null
  $A shell "PKG=$PKG; D=/data/data/\$PKG/files/system; \
    OWN=\$(stat -c %u:%g /data/data/\$PKG); \
    mkdir -p \$D; chown \$OWN \$D; \
    cp /data/local/tmp/private.pem \$D/private.pem; \
    chown \$OWN \$D/private.pem; chmod 600 \$D/private.pem"
  DID=$(tr -d '\r\n' < "$IDENTITY/device_id")
  $A shell "mkdir -p /sdcard/Download; printf '%s\n' '$DID' > /sdcard/Download/centaur_device_id; \
    chmod 644 /sdcard/Download/centaur_device_id; cat /sdcard/Download/centaur_device_id"
else
  echo "  identity не передан — в APK останется ключ-заглушка, регистрация не пройдёт."
  echo "  Передайте третьим аргументом каталог с private.pem и device_id (README, шаг 3a)."
fi

echo "[2/6] модель «Алиса»"
$A shell "am force-stop $PKG; rm -rf $DIR; mkdir -p $DIR"
for f in acoustic_model.nnet flags.txt lda.mat words.txt; do
  $A push "$MODEL/$f" "$DIR/$f" >/dev/null
done
$A shell "OWN=\$(stat -c %u /data/data/$PKG); chown -R \$OWN:\$OWN $DIR; chmod 700 $DIR"

echo "[3/6] выключаю лишнее у Sber (staros НЕ трогаем!)"
for p in \
  ru.sberdevices.assistant ru.sberdevices.music ru.sberdevices.startube \
  ru.sberdevices.videos ru.sberdevices.tv ru.sberdevices.sberplay \
  ru.sberdevices.starmarket ru.sberdevices.telegramcalls ru.sberdevices.cv \
  ru.sberdevices.gesturesGuide ru.sberdevices.biometryapp ru.sberdevices.newswidget \
  ru.sberdevices.trafficwidget ru.sberdevices.smarthome.promo ru.sberdevices.starcleaner \
  ru.sberdevices.starprofile ru.sberdevices.huaweicast ru.sberdevices.gamepad.service \
  ru.sberdevices.CleanupStub ru.sberdevices.bugreporter com.banda.sberuyshki \
  com.sberdevices.chudoknizhki com.salute.star ru.sberdevices.visor \
  ru.sberdevices.specialwidgets ru.sberdevices.starscreensaver \
  ru.sberdevices.starlauncher ; do
  $A shell "am force-stop $p; pm disable-user --user 0 $p" >/dev/null 2>&1 || true
done

echo "[4/6] запрет микрофона ассистенту Sber"
$A shell 'cmd appops set ru.sberdevices.services RECORD_AUDIO deny' || true

echo "[5/6] запуск Centaur"
$A shell "am start -n $PKG/.MainActivity"
sleep 30
$A shell 'logcat -d | grep -E "AliceBridge|configured=1|onPhraseSpotterStarted" | tail -5'

echo "[6/6] готово. Осталось:"
echo "  - войти в Яндекс-аккаунт в Centaur;"
echo "  - проверить голосом: «Алиса» → «включи группу Кино»."
echo "  - по желанию: клавиатура Яндекса вместо Sber (README, шаг 6)."
echo
echo "Watcher шторки (CentaurSwipeWatcher) ставится отдельно: см. sberportal-centaur/TOP_SHEET_ROOT_WATCHER.md"
