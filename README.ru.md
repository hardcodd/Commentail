<div align="center">

# Commentail

**Комментарии для Wagtail CMS на вашем сервере**

Модерация обсуждений, подтверждённые гости и ответы рядом с комментарием — в стиле вашего сайта.

[![Tests and distributions](https://github.com/hardcodd/Commentail/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/hardcodd/Commentail/actions/workflows/tests.yml)
[![Django Packages · Commentail](https://img.shields.io/badge/Django%20Packages-Commentail-0C4B33.svg)](https://djangopackages.org/packages/p/commentail/)

[English](README.md) · Русский

[Начать работу](#быстрый-старт) · [Документация](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Home.md) · [Wiki](https://github.com/hardcodd/Commentail/wiki) · [Поддержать](#поддержать-commentail)

<img src="https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/commentail-preview.png" alt="Commentail — синяя птица на облачке комментария" width="100%">

</div>

Commentail — библиотека комментариев Django для **Wagtail 7.4 LTS и 8.0**.
Добавьте шаблонный тег Django в статью, модерируйте обсуждения внутри Wagtail
и храните контент, учётные записи и отправку почты в своём приложении.

Виджет наследует шрифты и цвета сайта. CSS-переменные, заменяемые шаблоны и
Python callbacks позволяют адаптировать его без фронтенд-фреймворка или
внешней платформы комментариев.

> **0.2.0 Beta:** последние комментарии,
> шесть языков, HTML-письма и оптимизация запросов с новыми индексами.
> [Изменения между версиями](https://github.com/hardcodd/Commentail/blob/main/CHANGELOG.md) · [Планы развития](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Roadmap.md).
> [Изменения и обновление](https://github.com/hardcodd/Commentail/blob/main/docs/releases/0.2.0.md).

## Зачем Commentail?

| Для читателей | Для редакторов | Для разработчиков |
| --- | --- | --- |
| Подтверждение почты гостя или существующая учётная запись сайта | Четыре политики модерации | Один шаблонный тег для Pages и зарегистрированных объектов |
| Ответы рядом с комментарием и редактирование автором | Настройки сайта и переопределения для Pages | CSS-переменные и переопределение шаблонов |
| Уведомления о прямых ответах с отпиской | Правила слов и фраз, импорт/экспорт CSV | Заменяемые аватары, имена и CAPTCHA |
| Адаптивная вёрстка и работа на обычном HTML | Групповые права в пределах сайта | Очередь писем в БД; Redis/Celery не требуются |

Комментарии — обычный текст с настраиваемым ограничением: по умолчанию 5000
символов. Необязательные кликабельные HTTP(S)-ссылки используют безопасные
атрибуты. Ответить можно на любое видимое сообщение, сохраняя один визуальный
уровень вложенности. Модераторы одобряют, отклоняют, скрывают, восстанавливают
или стирают текст; они не переписывают чужие слова.

Опубликованные комментарии включают **микроразметку Schema.org Comment и JSON-LD**
с видимым текстом и именем автора. В Python можно выбрать один формат или
отключить вывод.
[Руководство по структурированным данным →](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Structured-data.md)

## Совместимость

| Компонент | Версия / требование |
| --- | --- |
| Python | 3.12–3.14 |
| Wagtail / Django | 7.4.3+ в ветке 7.4 / Django 5.2 или 6.0; 8.0.x / Django 5.2, 6.0 или 6.1 |
| База данных | Файловая SQLite или PostgreSQL 16 |
| Языки интерфейса и писем | Английский, русский, немецкий, французский, испанский и бразильский португальский |
| Фронтенд | Шаблоны Django, необязательный JavaScript для постепенного улучшения интерфейса |
| Лицензия | [MIT](https://github.com/hardcodd/Commentail/blob/main/LICENSE) |

Таблица описывает выпуск 0.2.0 Beta. CI определяет все пять пар фреймворков
на Python 3.12, 3.13 и 3.14 с обеими базами данных — всего 30 сочетаний.
Границы зависимостей пакета: `Wagtail>=7.4.3,<8.1` и `Django>=5.2,<6.2`;
поддерживаются только перечисленные пары. Wagtail 7.4 с Django 6.1 не входит
в эту матрицу. Wagtail 8.1 и новее требуют отдельной проверки перед объявлением поддержки.

Для гостевых комментариев нужны настроенный SMTP и запуск обработчика по
расписанию. Зарегистрированные пользователи могут комментировать без адреса
почты, но не получают писем. Вход и регистрацию предоставляет ваш сайт.
Обязательных внешних CDN и CAPTCHA-сервисов нет.

### Языки

В 0.2.0 помимо английского и русского доступны немецкий (`de`), французский (`fr`),
испанский (`es`) и бразильский португальский (`pt-br`): публичный интерфейс,
модерация, настройки и все письма. Активный язык выбирает сайт средствами Django;
отложенные письма используют сохранённый язык получателя. Тексты комментариев
и причины отклонения автоматически не переводятся. Документация остаётся
на русском и английском.
[Настройка языков →](docs/wiki/Configuration.md#languages)

## Быстрый старт

### 1. Установка

В виртуальном окружении сайта установите выпуск:

```sh
python -m pip install commentail==0.2.0
```

Для необязательного драйвера PostgreSQL используйте
`python -m pip install 'commentail[postgres]==0.2.0'`.
Также можно распаковать исходный архив и выполнить `python -m pip install .` в его корне.
При обновлении с 0.1.1 прочитайте
[инструкцию по обновлению](https://github.com/hardcodd/Commentail/blob/main/docs/releases/0.2.0.md),
включая миграцию `0014_reading_indexes` и переопределения писем. Для более старых
установок также прочитайте [примечания к 0.1.1](docs/releases/0.1.1.md). Пакет 0.1.0 сохраняет
исходные ограничения Wagtail 7.4 и Django 5.2.

### 2. Подключение Django и Wagtail

- Добавьте `commentail` и `wagtail.contrib.settings` в существующий `INSTALLED_APPS`.
- Для PostgreSQL также добавьте `django.contrib.postgres` — это требуется проверкам Django 6.x.
- Разместите `commentail.middleware.CapabilityHeadersMiddleware` перед CSRF middleware.
- Сохраните middleware сессий, аутентификации и сообщений сайта, а также контекстный процессор request для шаблонов.
- Подключите URL Commentail **перед** маршрутом Wagtail, перехватывающим остальные адреса:

```python
path("commentail/", include("commentail.urls")),
```

Выполните `python manage.py migrate`, `python manage.py check` и обычную сборку
статики. [Полное руководство по установке](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Installation.md)
описывает настройки, импорты URL, восстановление черновика после ошибки CSRF и развёртывание.

### 3. Добавление виджета

```django
{% load commentail_tags %}
{% commentail_css %}
{% commentail_js %}
{% commentail page %}
```

Добавьте теги ресурсов один раз в базовый шаблон, а виджет — в статью.
Шаблон определяет, где доступны комментарии к Pages; редактор соответствующей
Page получает вкладку Comments. Настройте параметры сайта, затем наследуйте
или переопределите их на отдельных Pages. Начальная политика модерации —
**Review all**: проверять все комментарии.

### Последние комментарии в других местах сайта

Добавьте тег последних комментариев на главную страницу, в боковую панель или другой шаблон:

```django
{% load commentail_tags %}
{% commentail_recent limit=5 as recent_comments %}
{% for comment in recent_comments %}
  <a href="{{ comment.url }}">{{ comment.author_name }}: {{ comment.text|truncatechars:120 }}</a>
{% endfor %}
```

Добавьте `page=page` для одной Page и `include_replies=False`, чтобы исключить
ответы. Список учитывает доступ текущего посетителя и Site, требует `request`
в контексте и не должен попадать в общий кеш. CSS и JavaScript виджета не нужны.
[Поля, фильтры и кеширование →](docs/wiki/Recent-comments.md)

### 4. Почта и очистка

В 0.2.0 добавлено минимальное HTML-оформление писем: название сайта, понятные
действия и равноценная текстовая версия. Шаблоны писем сайта имеют приоритет.

Настройте SMTP в Django и запускайте раз в минуту:

```sh
python manage.py process_commentail
```

Обработчик отправляет очередь писем из БД и удаляет просроченные временные
записи. Гости подтверждают почту до модерации. При включённой почте авторы
публичных отправок с адресом email автоматически подписываются на уведомления
о прямых ответах; каждое письмо с ответом содержит отписку от уведомлений для
конкретного комментария.
[Настройка и поведение почты →](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Email-and-worker.md)

## Адаптация под сайт

Виджет имеет прозрачный фон, наследует шрифт и цвет текста контейнера и
следует светлой или тёмной теме сайта. Подключайте переопределения после его CSS:

```css
.commentail {
  --commentail-color-accent: var(--brand-link, #245a86);
  --commentail-border-radius: .5rem;
  --commentail-max-width: 100%;
}
```

Используйте `GET_AVATAR` для возврата URL изображения профиля или возвращайте
`None` для автоматически созданных инициалов. Регистрируйте обычные модели
Django через `OBJECT_ADAPTERS`. Технические настройки хранятся в одном словаре
`COMMENTAIL` с `default` и переопределениями для hostname.

## Документация по задачам

[Wiki](https://github.com/hardcodd/Commentail/wiki) и
[руководства в репозитории](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Home.md)
охватывают одни и те же темы. Руководства доступны на английском. Начните с нужной задачи:

| Область | Руководства |
| --- | --- |
| Подключение | [Установка](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Installation.md) · [Запускаемый пример](https://github.com/hardcodd/Commentail/blob/main/example/README.md) |
| Настройка | [Параметры сайта, Page и Python](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Configuration.md) · [Модерация](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Moderation.md) · [Правила CSV](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Rules-and-CSV.md) |
| Поведение для читателей | [Гости](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Guest-comments.md) · [Ответы и редактирование](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Replies-and-editing.md) |
| Адаптация | [CSS и темы](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Styling.md) · [Шаблоны и письма](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Templates.md) · [Python callbacks](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Callbacks.md) · [Адаптеры моделей Django](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Object-adapters.md) |
| Эксплуатация | [SMTP и обработчик](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Email-and-worker.md) · [Развёртывание](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Deployment.md) · [Безопасность и приватность](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Security-and-privacy.md) |
| Диагностика | [Решение проблем / FAQ](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Troubleshooting.md) · [Пример и тестирование](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Example-and-testing.md) · [Производительность и нагрузочные проверки](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Performance.md) |

## Границы выпуска и проверок

[Примечания к выпуску 0.2.0 Beta](https://github.com/hardcodd/Commentail/blob/main/docs/releases/0.2.0.md)
описывают изменения и обновление;
[примечания к 0.1.0](https://github.com/hardcodd/Commentail/blob/main/docs/releases/0.1.0.md)
сохраняют исходный контракт выпуска. Архив исходников включает запускаемый
пример Wagtail, тесты и руководства; wheel содержит исполняемый код, переводы,
шаблоны и статические файлы.

CI определяет 30 сочетаний фреймворков, Python и БД, проверки JavaScript,
линтеров, изменений моделей без миграций, переводов и установки из исходников/wheel.
Браузерные проверки охватили установленные Safari, Chrome, Яндекс Браузер и
Firefox с JavaScript и без него, отдельные сценарии VoiceOver и телефон.
Предыдущие основные версии браузеров не проверены; это не исчерпывающая
сертификация доступности или устройств.

В 0.2.0 нет отдельного REST API, редактора форматированного текста, загрузки
файлов, лайков, жалоб и обновлений в реальном времени. Повторные попытки SMTP
могут дублировать письма после неопределённого результата доставки. Темы сайта,
правила доступа и доставка почты требуют собственной приёмки.

## Поддержать Commentail

Если Commentail помогает вашему проекту, можно поддержать сопровождение,
документацию и работу над совместимостью. Поддержка добровольная.

**[Поддержать через CloudTips](https://pay.cloudtips.ru/p/f92ee349)**

<a href="https://pay.cloudtips.ru/p/f92ee349"><img src="https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/support-qr.png" alt="Отсканируйте QR-код, чтобы поддержать Commentail через CloudTips" width="180"></a>

По вопросам и воспроизводимым ошибкам сначала прочитайте
[FAQ](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Troubleshooting.md),
затем откройте [GitHub issue](https://github.com/hardcodd/Commentail/issues).
Не включайте учётные данные, приватные комментарии и защищённые ссылки из писем.
