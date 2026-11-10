# SberPortal → Яндекс (Centaur / «Дуо»)

Превращаем **SberPortal** (`stargate`, Amlogic A311D, Android 9, StarOS) в
колонку с **Алисой Яндекса**: говорите «Алиса» — портал слушает, команда уходит
в Яндекс, музыка/ответы играют и показываются в **Centaur** (штатный
яндекс-лаунчер на портале). Ассистент Sber и СберЗвук при этом отключены.

Проверено на живом устройстве:
`«Алиса» → «включи группу Кино» → играет «Кино — Легенда» в плеере Centaur`,
ASR приходит из Яндекса (`Vins.VoiceInput`).

---

## Что понадобится

- SberPortal (root поставит установщик; вручную — **[sberportal-root](https://github.com/sber-portal/sberportal-root)**).
- `adb` на компьютере.
- Из **[Releases v1](https://github.com/sber-portal/sberportal/releases/tag/v1)**:
  - `centaur-voice-patched.apk` (334 МБ, Centaur 4.16.1 + патчи, debug-подпись)
  - `duomax-alisa-model.zip` (модель «Алиса» из прошивки Яндекс Дуо Макс)
  - `yandex-keyboard-centaur-signed.apk` (клавиатура Яндекса из прошивки Дуо Макс,
    переподписана — для шага 6, по желанию)
- **identity вашей Яндекс Станции**: `device_id` и `private.pem` — они нужны
  Centaur для регистрации (см. шаг 3a).

Технические детали, зачем каждый патч и как он сделан —
**[sberportal-centaur](https://github.com/sber-portal/sberportal-centaur)**
(`patch/README.md`, `VOICE.md`, `TOP_SHEET.md`, `SBER_GUARD.md`).

---

## Установщик (один файл)

Всё ниже можно сделать вручную, но есть готовый установщик:
[`installer/`](installer/) — один Python-файл (или бинарник для Linux/macOS/Windows).
Он спрашивает IP портала, проверяет `identity/` (`private.pem` + `device_id`),
проверяет ADB и объясняет, как его включить, получает root, скачивает и ставит
Centaur с моделью, top sheet и клавиатуру (по желанию), а в конце предлагает
удалить временные файлы.

```bash
python3 installer/portal_installer.py            # или ./installer/run-macos.command
# репозитории публичные — токен не нужен
```

Подробно — [`installer/README.md`](installer/README.md). Готовые бинарники — в релизе:
`sberportal-installer-macos-arm64`, `sberportal-installer-linux-x86_64`,
`sberportal-installer-windows-x86_64.exe`. Пересобрать — workflow
`.github/workflows/github-workflow-installer.yml` (Actions → installer → Run workflow)
или локально `pyinstaller`.

## Шаг 0. Первые шаги: с нуля или после сброса

Это **самое начало** превращения портала в Дуо Макс — выполняется до установки
Centaur, потому что без root ставить его нет смысла.

1. **Добавить устройство в приложение «Салют»** (Sber). Оно проводит первичную
   настройку: язык, Wi-Fi, привязка устройства к аккаунту. Без этого шага
   портал остаётся в мастере настройки и ADB не поднимется.
2. **Включить ADB** через портал разработчика Sber:
   <https://developers.sber.ru/studio/settings/devices> — добавить серийный номер
   портала (или авторизоваться тем же аккаунтом, к которому привязано устройство).
   После этого adbd начинает слушать `:5555`.
3. **Получить постоянный root** — [sberportal-root](https://github.com/sber-portal/sberportal-root)
   (`scripts/persistent_root.sh`; одноразовый пролёт эксплойтом CVE-2022-38181).
   Дальше все шаги требуют `adb root` → `uid=0`.

После этого переходите к шагу 1; вход в Яндекс-аккаунт — в самом конце (шаг 9).

## Шаг 1. Root (обязательно)

```bash
adb connect <IP портала>:5555
adb root
adb shell id        # должно быть uid=0(root)
```

Если `adb root` не работает — сначала пройдите **[sberportal-root](https://github.com/sber-portal/sberportal-root)**.

## Шаг 2. Патченный Centaur

Скачайте из Releases `centaur-voice-patched.apk` (официальный Centaur 4.16.1
с патчами: аудио-путь, автозапуск настройки споттера, приёмник для отладки).

Centaur на SberPortal с завода нет — ставим его впервые, никаких подписей
Яндекса на устройстве не было. APK подписан debug-ключом:

```bash
adb install -r centaur-voice-patched.apk
```

Шаги 2–4 (установка, модель, отключение Sber, appop для яркости) можно сделать
одним скриптом из этого репозитория:

```bash
IP=192.168.1.x ./scripts/restore_after_reset.sh centaur-voice-patched.apk ./duomax-alisa-model ./identity
```

Если на устройстве уже стоит сборка Centaur с **другой** подписью (например,
из более раннего эксперимента), обновление «поверх» не пройдёт — удалите её
(`adb shell pm uninstall ru.yandex.quasar.centaur_app`) и поставьте заново;
данные при этом теряются — заранее сохраните `files/system` приложения
(`adb pull /data/data/ru.yandex.quasar.centaur_app/files/system`).

Проверка, что приложение живое:

```bash
adb shell am start -n ru.yandex.quasar.centaur_app/.MainActivity
adb logcat | grep -E "AliceBridge|configured=|onPhraseSpotterStarted"
# ожидаем: AliceBridge: spotterfix loaded
#          activation_spotter_capability.cpp:40 start, configured=1
#          onPhraseSpotterStarted
```

## Шаг 3. Модель «Алиса»

Возьмите из Releases `duomax-alisa-model.zip` — это модель из прошивки
**Яндекс Станция Дуо Макс** (файлы `acoustic_model.nnet`, `flags.txt`,
`lda.mat`, `words.txt`).

```bash
adb push duomax-alisa-model/. /data/local/tmp/alisa/
adb shell '
  M=/data/data/ru.yandex.quasar.centaur_app/files/system/spotter_models/activation/alisa
  OWNER=$(stat -c "%u:%g" /data/data/ru.yandex.quasar.centaur_app)
  am force-stop ru.yandex.quasar.centaur_app
  rm -rf $M && mkdir -p $M
  cp /data/local/tmp/alisa/* $M/
  chown -R $OWNER $M
  chmod 700 $M; chmod 600 $M/*
'
adb shell am start -n ru.yandex.quasar.centaur_app/.MainActivity
```

> UID приложения после переустановки может отличаться — `OWNER` берётся из
> самого каталога данных, поэтому команда работает на любом устройстве.

## Шаг 3a. Identity устройства: `device_id` и `private.pem`

Каждой колонке Яндекс присваивает **уникальную пару**:

- `device_id` — идентификатор экземпляра в аккаунте (строка вида `<platform>_<номер>`);
- `private.pem` — приватный ключ устройства (RSA 2048), которым подписывается запрос
  регистрации. `public.pem` — соответствующая открытая часть.

Эти два значения связаны между собой и уникальны для конкретной Яндекс Станции.
**Centaur работает только со «своей» парой**: без неё `/register` отвечает
404 `Device not found` (если `device_id` не тот) или `AUTH_TOKEN_INVALID`
(если ключ не тот). Сгенерировать новую пару нельзя — она выдаётся устройству.

В релизном APK ключ — **заглушка**, поэтому после установки положите свою пару:

```bash
adb push private.pem /data/local/tmp/private.pem
adb shell '
  PKG=ru.yandex.quasar.centaur_app
  D=/data/data/$PKG/files/system
  OWNER=$(stat -c "%u:%g" /data/data/$PKG)
  mkdir -p $D; chown $OWNER $D
  cp /data/local/tmp/private.pem $D/private.pem
  chown $OWNER $D/private.pem; chmod 600 $D/private.pem
  printf "%s\n" "<DEVICE_ID>" > /sdcard/Download/centaur_device_id
  chmod 644 /sdcard/Download/centaur_device_id
'
adb shell am force-stop ru.yandex.quasar.centaur_app
```

Где взять: `device_id` и `/yak/private.pem` из раздела/дампа вашей Станции
(или из её файловой системы под root). **Не публикуйте пару** — она даёт доступ
к вашему устройству в аккаунте.

> Мы тестировали связку на `device_id` от колонки **LG Boom** (LG XBOOM WK7Y,
> platform `wk7y`) — конкретное значение здесь не публикуем: это идентификатор
> аккаунта. Для своей колонки используйте её собственную пару.

Проверка: после запуска Centaur в логах `registration_in_backend_is_completed=true`.

## Шаг 4. Выключить Sber

```bash
adb shell '
  # ассистент Sber
  pm disable-user --user 0 ru.sberdevices.assistant
  # СберЗвук (иначе иногда перехватывает музыку)
  am force-stop ru.sberdevices.music
  pm uninstall -k --user 0 ru.sberdevices.music
  # лишаем сервис Sber микрофона (иначе он тоже слышит «Алису» и отвечает)
  cmd appops set ru.sberdevices.services RECORD_AUDIO deny
  kill -9 $(pidof ru.sberdevices.services)
'
```

Через ~30 секунд сервис Sber поднимется без доступа к микрофону — это нормально.

## Шаг 5. Проверка

Скажите вслух: **«Алиса»**, затем (после экрана прослушивания) —
**«включи группу Кино»**.

Ожидаемо: Centaur показывает прослушивание, затем открывает плеер и играет
«Кино». В логах:

```bash
adb logcat | grep -E "onStartVoiceInput|asrText"
```

## Шаг 6. Клавиатура Яндекса вместо Sber (по желанию)

На портале единственная клавиатура — `ru.sberdevices.app.starkeyboard`.
Её можно заменить клавиатурой из прошивки Дуо Макс
(`yandex-keyboard-centaur-signed.apk` из Releases):

```bash
adb install -r yandex-keyboard-centaur-signed.apk
adb shell '
  ime enable ru.yandex.androidkeyboard.centaur/ru.yandex.androidkeyboard.inputmethod.YandexCentaurLatinIme
  ime set    ru.yandex.androidkeyboard.centaur/ru.yandex.androidkeyboard.inputmethod.YandexCentaurLatinIme
'
# только после того, как новая клавиатура выбрана:
adb shell pm disable-user --user 0 ru.sberdevices.app.starkeyboard
```

Проверено: APK ставится (нужна переподпись — в Releases уже
переподписанный), выбирается как IME и остаётся активным после отключения
клавиатуры Sber.

Откат:

```bash
adb shell '
  pm enable ru.sberdevices.app.starkeyboard
  ime set ru.sberdevices.app.starkeyboard/.StarInputMethodService
  ime disable ru.yandex.androidkeyboard.centaur/ru.yandex.androidkeyboard.inputmethod.YandexCentaurLatinIme
  pm uninstall ru.yandex.androidkeyboard.centaur
'
```

## Шаг 7. Удалить лишние приложения Sber (по желанию)

Проверено: после отключения этих пакетов портал работает, Centaur и голос — тоже.

**Выключайте, а не удаляйте.** Часть предустановленных приложений staros умеет
«восстанавливаться» (`SPS/SmartAppWidgetManager`), а `pm disable-user` держится
после перезагрузки. Обратимо: `pm enable <pkg>`.

```bash
for p in \
  ru.sberdevices.startube ru.sberdevices.videos ru.sberdevices.tv \
  ru.sberdevices.sberplay ru.sberdevices.starmarket ru.sberdevices.telegramcalls \
  ru.sberdevices.cv ru.sberdevices.gesturesGuide ru.sberdevices.biometryapp \
  ru.sberdevices.newswidget ru.sberdevices.trafficwidget ru.sberdevices.smarthome.promo \
  ru.sberdevices.starcleaner ru.sberdevices.starprofile ru.sberdevices.huaweicast \
  ru.sberdevices.gamepad.service ru.sberdevices.CleanupStub ru.sberdevices.bugreporter \
  com.salute.star ru.sberdevices.visor \
  com.banda.sberuyshki com.sberdevices.chudoknizhki ; do
  adb shell pm disable-user --user 0 $p
done
```

Уже сняты и проверены (шторка, голос и Centaur работают):

- `ru.sberdevices.assistant` — ассистент Sber (шаг 4);
- `ru.sberdevices.music` — СберЗвук (шаг 4);
- `ru.sberdevices.specialwidgets` (7 МБ) — виджеты Sber-лончера;
- `ru.sberdevices.starscreensaver` (22 МБ) — звёздная заставка с часами
  (в простое её просто нет);
- `ru.sberdevices.webview` — альтернативный WebView-провайдер Sber; системный
  провайдер — `org.chromium.chrome`, он и используется (проверено `dumpsys webviewupdate`);
- `ru.sberdevices.starlauncher` — лончер Sber, отключается отдельно (шаг 8).

**Оставить (система):**

| пакет | зачем |
|---|---|
| `ru.sberdevices.services` (staros) | persistent-сервис платформы; отключение = bootloop |
| `ru.sberdevices.SberDevicesServiceSystem` | системный слой платформы |
| `ru.sberdevices.systemui` | шторка/уведомления платформы (нативный слой StarOS) |
| `ru.sberdevices.settings` | StarSettings: Wi-Fi, Bluetooth, язык, «О устройстве». Единственный экран, с которого можно вернуть сеть, если ADB по Wi-Fi отвалится |
| `ru.sberdevices.app.setup` | мастер первичной настройки (язык/Wi-Fi/привязка); на настроенном устройстве просто простаивает |
| `ru.sberdevices.location.provider` | провайдер геолокации `network` (проверено `dumpsys location`); на нём же держится `fused` — из него Centaur берёт координаты для погоды, времени и часового пояса |
| `ru.sberdevices.app.starkeyboard` | единственная клавиатура; оставляем, если не поставили клавиатуру Яндекса (шаг 6) |

## Шаг 8. Лончер Sber (по желанию)

Centaur уже является домашним экраном (default home), поэтому лончер Sber можно
отключить:

```bash
adb shell 'pm disable-user --user 0 ru.sberdevices.starlauncher; am force-stop ru.sberdevices.starlauncher'
adb shell input keyevent 3     # HOME → должен открыться Centaur
```

Проверено: HOME уходит в Centaur, ошибок в логах нет. Вернуть:
`pm enable ru.sberdevices.starlauncher`.
Если после перезагрузки получите чёрный экран — верните лончер по adb
(adb продолжает работать).

## Шаг 9. Вход в Яндекс-аккаунт

Откройте Centaur и войдите в аккаунт Яндекса — после этого работают музыка,
ответы и сценарии. Если регистрация не проходит, см. «Регистрация устройства»
ниже.

---

## Как это работает (коротко)

```
микрофон
  └─ Centaur (AudioRecord 16 кГц) → SDK AudioSource
       ├─ споттер: модель activation/alisa  → «Алиса»
       └─ диалог: Vins.VoiceInput → uniproxy Яндекса → музыка/ответы в Centaur
```

Что именно менялось в APK — **[sberportal-centaur](https://github.com/sber-portal/sberportal-centaur)**:
`patch/README.md` (аудио-путь, споттер, загрузка `.so`, отладочный TextReceiver)
и `VOICE.md`. Здесь не дублируем, чтобы инструкция не расходилась с кодом.

## Громкость (голосом и в top sheet)

Голосовое управление громкостью работает: «громкость пятьдесят», «громче»,
«тише», «выключи звук». Директива Яндекса `sound_set_level` обрабатывается
нативным `volume_manager` внутри Centaur.

Шкала громкости — **0..10**, как в интерфейсе Дуо Макс. «10» соответствует
максимальной системной громкости (16 шагов AudioManager), поэтому громкость
не теряется.

Правки APK, которые это включают (подробно — `scripts/patch_centaur_volume.sh`
в `sberportal-centaur`):

1. `YandexIoServiceImpl.j()` снова вызывает `VolumeManager.register()`
   (в этой сборке метод был заглушён `return-void`, из-за чего не было
   обработчика громкости, а top sheet показывал «звук отключён»).
2. Тост громкости защищён `try/catch` от `WindowManager$BadTokenException`.

## Яркость экрана

Если ползунок яркости в top sheet двигается, но экран не меняется — у
переподписанного Centaur нет разрешения на запись системных настроек.
Лечится один раз (нужен root/ADB):

```sh
adb shell cmd appops set ru.yandex.quasar.centaur_app WRITE_SETTINGS allow
```

После этого работают и ползунок, и кнопка авто-яркости.
`scripts/restore_after_reset.sh` выставляет это автоматически.

## Вылеты после голосовой команды

Исправлено в APK из релиза. Причина: нативный код Centaur делал
`CHECK(getValue().hasValue())` для поля `time`; в голосовых ответах этого
поля нет, и приложение падало с `SIGABRT` (поток `VoiceService`).
Патч (`sberportal-centaur/scripts/patch_centaur_crashfix.sh`) делает
fatal-хелпер в `libquasar_daemons.so` возвратом: проверка больше не убивает
процесс, диалог и TTS продолжают работать.

Файл в релизе обновлён; отдельно ставить ничего не нужно.

## Ночной режим

Когда в комнате темно, Centaur сворачивает интерфейс и показывает время на
чёрном фоне. В этой сборке ночной режим исправлен патчем
(`sberportal-centaur/scripts/patch_centaur_night_mode.sh`): бэкенд не
присылает секцию `centaur`/`brightness_settings` для нашего `device_id`,
поэтому приложение берёт разумные значения по умолчанию и всё равно
регистрирует датчик света.

Настройка «Ночной режим» должна быть включена (она включена по умолчанию).
Чтобы проверить днём — закройте датчик света на верхней панели портала:
экран должен погаснуть и показать часы; откройте — вернётся обычный вид.

## Шторка (top sheet)

Свайп сверху вниз открывает шторку Centaur. На свежей установке её нужно
поставить отдельно — watcher и bootstarter из `sberportal-centaur`
(`TOP_SHEET.md`, `scripts/install_top_sheet.sh`). Требуется root.

## Сборка APK Centaur своими руками

Готовый патченный APK лежит в релизе; собирать его нужно только если хотите
сделать патчи под свою версию Centaur.

**Ключ и `device_id` в сборке не участвуют.** APK не содержит вашу identity:
в `assets/quasar/private.pem` лежит заглушка, а рабочая пара кладётся в данные
приложения после установки (шаг 3a). Поэтому один APK подходит для любого
портала — пересобирать под каждое устройство не нужно.

Что нужно:

1. Стоковый APK Centaur **4.16.1** (`armeabi-v7a`) — из прошивки Дуо Макса или
   собственного дампа. Другая версия не подойдёт: смещения в патчах привязаны к ней.
2. `apktool` 3.x, `zipalign`, `apksigner`, Android NDK r26, debug-keystore.
3. Патчи из `sberportal-centaur`:

```bash
git clone https://github.com/sber-portal/sberportal-centaur
cd sberportal-centaur

# libspotterfix.so (включает родной споттер)
$NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin/armv7a-linux-androideabi30-clang++ \
  -shared -fPIC -O2 -std=c++17 -static-libstdc++ \
  -o libspotterfix.so spotterfix/spotterfix.cpp

# smali-патчи + перепаковка + подпись
./scripts/patch_centaur_top_sheet.sh    stock-centaur-4.16.1.apk
./scripts/patch_centaur_volume.sh       patched.apk
./scripts/patch_centaur_night_mode.sh   patched.apk
./scripts/patch_centaur_crashfix.sh     patched.apk
```

Точный список правок и требования к перепаковке (`extractNativeLibs=true`,
`zipalign -p`, лимит 65536 методов в `classes4.dex`) — в
`sberportal-centaur/patch/README.md`.

После сборки поставьте APK и выполните шаг 3a (своя identity) — больше ничего
в APK менять не нужно.

## Известные ограничения

- Centaur иногда падает с `SIGABRT` сразу после **речевого** ответа (TTS),
  приложение само перезапускается за ~5-10 с. В tombstone записи нет; ловится
  только по `Zygote: Process ... exited due to signal (6)`. На музыку
  (без TTS) не влияет.
- Магазина приложений на портале нет — Centaur обновляется только
  переустановкой APK из релиза; сам он не обновится и патч не потеряет.
- APK/модель — проприетарные; выложены как есть для личного использования.

## Откат

```bash
adb shell '
  cmd appops set ru.sberdevices.services RECORD_AUDIO allow
  pm enable ru.sberdevices.assistant
  cmd package install-existing ru.sberdevices.music
'
# и вернуть стоковый Centaur (данные — из сохранённого files/system)
```

## НЕЛЬЗЯ отключать `ru.sberdevices.services`

Это persistent-сервис платформы. `pm disable-user ru.sberdevices.services`
приводит к **бесконечной перезагрузке** («Выключение» сразу после старта),
и восстановить можно только сбросом к заводским настройкам.
Микрофон ему закрывайте только через `cmd appops set ru.sberdevices.services
RECORD_AUDIO deny` — этого достаточно, чтобы Sber не отвечал.
