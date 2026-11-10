# Установщик

Один файл, который проводит портал от «включён в розетку» до рабочей Алисы:
проверяет ADB и identity, получает постоянный root, ставит Centaur с патчами,
модель «Алиса», top sheet и убирает за собой временные файлы.

## Быстрый запуск

```bash
export GITHUB_TOKEN=<fine-grained PAT, Contents: Read>
python3 portal_installer.py
```

Или готовым бинарником из релиза (Linux / macOS / Windows) — артефакты собирает
GitHub Actions — workflow лежит в `.github/workflows/github-workflow-installer.yml`
(Actions → installer → Run workflow; готовые файлы появятся в артефактах запуска).
Локально:

```bash
pip install pyinstaller
pyinstaller --onefile --name sberportal-installer installer/portal_installer.py
```

Обёртки: `./run-macos.command` (двойной клик), `./run-linux.sh`,
`run-windows.bat` (нужен Python 3.8+).

## Что спросит

| шаг | что делает |
|---|---|
| 1 | IP портала (или возьмёт единственное adb-устройство), проверяет связь |
| 2 | ищет `identity/` рядом со скриптом: `private.pem` + `device_id`; если нет — предупредит и предложит продолжить без регистрации |
| 3 | проверяет root; если нет — эксплойт CVE-2022-38181, запись u-boot env, авто-root APK |
| 4 | скачивает и ставит APK Centaur, модель «Алиса», кладёт identity в данные приложения |
| 5 | отключает ассистента и СберЗвук, закрывает микрофон сервису Sber, выключает лишние приложения |
| 6 | ставит top sheet (watcher + bootstarter + homeproxy + guard) — можно пропустить |
| 7 | по желанию меняет клавиатуру Sber на клавиатуру Яндекса |

В конце спрашивает, удалить ли скачанные файлы. Identity в приложении и
`/sdcard/Download/centaur_device_id` не удаляются.

Если `adb root` на портале ещё не работает (первый запуск), root-шаг правит
u-boot env **двумя** прогонами эксплойта через `SP_CMD`: снять `/dev/block/env`
→ `patch_env()` (только `preboot`, CRC32) → записать обратно → проверить
побайтово (`ENV_OK`) → перезагрузить. После перезагрузки `adb root` уже
работает, и установщик ставит `adbroot.apk` для авто-root при следующих
загрузках.

## Токен

**Репозитории публичные — токен не нужен.** Установщик качает файлы через
`raw.githubusercontent.com` и прямые ссылки релизов, без GitHub API.

Токен нужен только для приватных репозиториев (fine-grained PAT):

1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained.
2. Repository access: `sber-portal/sberportal`, `sber-portal/sberportal-root`, `sber-portal/sberportal-centaur`.
3. Permissions: **Contents: Read-only**.
4. `export GITHUB_TOKEN=...` или флаг `--token`.

Без токена установщик тоже работает: при 404 он прямо скажет, что репозиторий,
скорее всего, приватный.

## Identity

`device_id` и `private.pem` — уникальная пара вашей Яндекс Станции. Полож­ите рядом
со скриптом:

```
identity/
  private.pem
  device_id
```

Или укажите `--identity /path/to/identity`. Подробно — в `research-notes/identity/README.md`.

**Ключ и id не вшиваются в APK.** APK в релизе содержит ключ-заглушку; установщик
кладёт вашу пару в `/data/data/ru.yandex.quasar.centaur_app/files/system/` уже после
установки. Поэтому пересобирать APK под каждое устройство не нужно.

## Полезные флаги

| флаг | что |
|---|---|
| `--ip 192.168.1.50` | без интерактива по устройству |
| `--apk /path/app.apk` | локальный APK вместо скачивания (334 МБ) |
| `--model /path/model` | локальная модель вместо скачивания |
| `--skip-root` | root уже есть |
| `--skip-top-sheet` | не ставить шторку |
| `--with-keyboard` | заменить клавиатуру |
| `--no-cleanup` | оставить временные файлы |
| `--yes` | не задавать вопросов (кроме токена, если не задан) |

## Если что-то пошло не так

| симптом | что делать |
|---|---|
| `adb` не видит портал | приложение «Салют» → первичная настройка; ADB включить на developers.sber.ru; проверить, что одна сеть |
| 401/404 от GitHub | токен просрочен или нет доступа к одному из трёх репозиториев |
| эксплойт не срабатывает | подождать загрузку, повторить: `python3 portal_installer.py --skip-top-sheet` |
| после перезагрузки нет root | проверить `adb shell getprop ro.boot.rabbith.adb_root` (должно быть `1`) |
| Centaur не регистрируется | проверить identity: `files/system/private.pem` и `/sdcard/Download/centaur_device_id` |
| голос молчит | `adb logcat \| grep -E "AliceBridge\|configured=\|asrText"` |

Требования: Python 3.8+, `adb` в PATH, свободное место ~1 ГБ (APK 334 МБ),
стабильная сеть (APK качается через GitHub API).
