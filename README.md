# SberPortal: что с ним можно сделать

**SberPortal** (`stargate`, Amlogic A311D, Android 9, StarOS) — смарт-экран Сбера
с камерой и микрофоном. После получения root у него есть два независимых пути,
и они не мешают друг другу: это разные проекты со своими репозиториями.

| | **Centaur** | **OpenStation** |
| --- | --- | --- |
| что получается | родной яндекс-интерфейс «Дуо Макс» с Алисой | свой ТВ-лаунчер с Gemini Live-ассистентом |
| что нужно кроме root | **оригинальные `device_id` и `private.pem`** Яндекс Станции | ничего, кроме root |
| репозиторий | [sberportal-centaur](https://github.com/sber-portal/sberportal-centaur) | [sberportal-openstation](https://github.com/sber-portal/sberportal-openstation) |

---

## Подготовка (общая для обоих вариантов)

1. **Привязать портал к приложению «Салют»** (Sber) — оно проводит первичную
   настройку: язык, Wi-Fi, аккаунт. Без этого портал остаётся в мастере настройки
   и ADB не поднимается.
2. **Включить ADB** через портал разработчика Sber:
   <https://developers.sber.ru/studio/settings/devices> — добавить серийный номер
   портала (или войти тем же аккаунтом, к которому привязано устройство). После
   этого adbd слушает `:5555`.
3. **Получить постоянный root** — [sberportal-root](https://github.com/sber-portal/sberportal-root)
   (`scripts/persistent_root.sh`; одноразовый пролёт эксплойтом CVE-2022-38181).

Проверка:

```bash
adb connect <IP портала>:5555
adb root
adb shell id        # uid=0(root)
```

Дальше выбирайте вариант: они ставятся независимо, и оба обратимы.

---

## Вариант 1 — Centaur (Алиса Яндекса)

Портал превращается в аналог **Яндекс Станции Дуо Макс**: штатный яндекс-лаунчер
Centaur, wake word «Алиса», музыка и ответы Яндекса, шторка по свайпу сверху.
Ассистент Сбер и СберЗвук при этом отключаются.

**Обязательное условие:** нужна identity настоящей Яндекс Станции —
`device_id` и `private.pem` из её данных. Centaur регистрируется в Яндексе только
с этой парой; без неё он установится, но не заработает как ассистент.
`device_id`/`private.pem` не выдаются сообществом и не генерируются — это именно
данные вашей Станции (файлы из `files/system` её приложения).

Всё остальное — готовый установщик, патченный APK, модель «Алиса», патчи голоса и
шторки, блокировка OTA — в **[sberportal-centaur](https://github.com/sber-portal/sberportal-centaur)**
(там же релиз `v1` с APK и установщиком под Linux/macOS/Windows).

---

## Вариант 2 — OpenStation (Gemini Live)

Портал становится самостоятельным ТВ-экраном на форке
[OPENSTATION](https://github.com/Olegu621/OPENSTATION): свой лаунчер, голосовой
ассистент на Gemini Live (wake word «Алиса»), Яндекс Музыка, Кинопоиск и YouTube
по голосу, веб-пульт с телефона, автояркость с ночным режимом и крупными часами.

Яндекс-аккаунт Станции не нужен. Sber-сервисы, root и загрузчик не затрагиваются —
проект работает поверх них.

Установка, сборка и откат — в **[sberportal-openstation](https://github.com/sber-portal/sberportal-openstation)**.

---

## Важное предупреждение

Не отключайте `ru.sberdevices.services`:

```bash
# НЕЛЬЗЯ: pm disable-user ru.sberdevices.services
```

Это persistent-сервис платформы: после отключения портал уходит в бесконечную
перезагрузку, и восстановить его можно только сбросом к заводским настройкам.
Если нужно, чтобы ассистент Сбер молчал, закрывайте ему микрофон точечно:

```bash
adb shell cmd appops set ru.sberdevices.services RECORD_AUDIO deny
```

---

## Ссылки

- [sberportal-root](https://github.com/sber-portal/sberportal-root) — постоянный root.
- [sberportal-centaur](https://github.com/sber-portal/sberportal-centaur) — Centaur: голос, шторка, подавление Sber, установщик.
- [sberportal-openstation](https://github.com/sber-portal/sberportal-openstation) — OpenStation: свой лаунчер, Gemini Live, Кинопоиск, YouTube.
