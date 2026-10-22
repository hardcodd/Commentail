<div align="center">

# Commentail

**Комментарии для Wagtail CMS на вашем сервере**

Модерация обсуждений, подтверждённые гости и ответы рядом с комментарием — в стиле вашего сайта.

**Текущая версия: [1.3.1](https://github.com/hardcodd/Commentail/releases/tag/v1.3.1)** · [PyPI](https://pypi.org/project/commentail/1.3.1/)

[1.3.1 — обновление безопасности](docs/releases/1.3.1.md). Обновление требует
необратимой миграции отпечатков; заранее проверьте рекомендации о резервной
копии, остановке записи и лимитах выдачи форм.

[![Tests and distributions](https://github.com/hardcodd/Commentail/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/hardcodd/Commentail/actions/workflows/tests.yml)
[![Django Packages · Commentail](https://img.shields.io/badge/Django%20Packages-Commentail-0C4B33.svg)](https://djangopackages.org/packages/p/commentail/)

[English](README.md) · Русский

[Начать работу](#быстрый-старт) · [Скриншоты](#скриншоты) · [Документация](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Home.md) · [Wiki](https://github.com/hardcodd/Commentail/wiki) · [Поддержать](#поддержать-commentail)

<img src="https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/commentail-preview.png" alt="Commentail — синяя птица на облачке комментария" width="100%">

</div>

Commentail — библиотека комментариев Django для **Wagtail 7.4 LTS и 8.0**.
Добавьте шаблонный тег Django в статью, модерируйте обсуждения внутри Wagtail
и храните контент, учётные записи и отправку почты в своём приложении.

Виджет наследует шрифты и цвета сайта. CSS-переменные, заменяемые шаблоны и
Python callbacks позволяют адаптировать его без фронтенд-фреймворка или
внешней платформы комментариев.

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

Документированные контракты интеграции подчиняются [правилам стабильного API и совместимости](docs/wiki/Stability.md).

## Скриншоты

Снято на Commentail **1.1.0**, установленной с PyPI в изолированном демо
с Wagtail 8.0.1 и Django 6.1.2. Имена и обсуждения — демонстрационные данные.
У публичной страницы собственная тема сайта; виджет и административные экраны
взяты из выпущенного пакета без переопределения шаблонов.

**На сайте:** обсуждение Wagtail, шаблонов Django и постепенного улучшения
интерфейса, с вложенным ответом и выделением редактора.

![Обсуждение статьи на Wagtail: вопрос читателя и ответ редактора](https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/screenshots/public-discussion.jpg)

**Внутри Wagtail:** очередь модерации, раскрытые фильтры сайта/страницы, статуса
и дат, а также два комментария, выбранных для массового действия.

![Очередь модерации Wagtail с раскрытыми фильтрами и выбором комментариев](https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/screenshots/moderation-filters.jpg)

<details>
<summary>Гостевая форма, встроенный ответ, модерация и настройки сайта/страницы</summary>

**Гостевая форма.** Закрытый от других читателей email, уведомление о подтверждении
адреса и локальная арифметическая задача. На снимке — неотправленный черновик.

![Гостевая форма с примером черновика и уведомлением о подтверждении email](https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/screenshots/guest-form.jpg)

**Встроенный ответ.** Форма открывается под выбранным комментарием и показывает
адресата. На снимке также неотправленный черновик.

![Встроенная форма ответа читателю рядом с существующим обсуждением](https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/screenshots/inline-reply.jpg)

**Модерация комментария.** Исходный текст, доступные действия и история решений.

![Карточка комментария в ожидании модерации с действиями и историей](https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/screenshots/comment-moderation.jpg)

**Настройки сайта.** Доступ к обсуждению, политика модерации, выделение сотрудников,
кликабельные ссылки и параметры писем.

![Настройки комментариев сайта в Wagtail: модерация, оформление и письма](https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/screenshots/site-settings.jpg)

**Настройки страницы.** Наследование политики сайта или её изменение для отдельного
обсуждения.

![Настройки обсуждения страницы с наследованием конфигурации сайта](https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/screenshots/page-settings.jpg)

</details>

## Совместимость

| Компонент | Версия / требование |
| --- | --- |
| Python | 3.12–3.14 |
| Wagtail / Django | 7.4.3+ в ветке 7.4 / Django 5.2 или 6.0; 8.0.x / Django 5.2, 6.0 или 6.1 |
| База данных | Файловая SQLite или PostgreSQL 16 |
| Языки интерфейса и писем | Английский, русский, немецкий, французский, испанский и бразильский португальский |
| Фронтенд | Шаблоны Django, необязательный JavaScript для постепенного улучшения интерфейса |
| Лицензия | [MIT](https://github.com/hardcodd/Commentail/blob/main/LICENSE) |

CI определяет все пять пар фреймворков на Python 3.12, 3.13 и 3.14 с обеими базами данных — всего 30 сочетаний.
Границы зависимостей пакета: `Wagtail>=7.4.3,<8.1` и `Django>=5.2,<6.2`;
поддерживаются только перечисленные пары. Wagtail 7.4 с Django 6.1 не входит
в эту матрицу. Wagtail 8.1 и новее требуют отдельной проверки перед объявлением поддержки.

Для ветки Wagtail 8 матрица CI выбирает 8.0.1 или более новый патч в пределах 8.0.

Для гостей нужны настроенная доставка писем Django и фоновая обработка по
расписанию. Используйте SMTP или другой `EMAIL_BACKEND` Django и запускайте
команду либо `commentail.background.process_pending()` через очередь проекта.
Зарегистрированные пользователи могут комментировать без адреса почты, но не
получают писем. Вход и регистрацию предоставляет ваш сайт. Обязательных внешних
CDN и CAPTCHA-сервисов нет. См. [настройку писем](docs/wiki/Email-and-worker.md).

Защита гостей включает скрытые проверки формы, лимиты попыток и сигналы модерации
для повторяющегося длинного текста и множества ссылок, включая гостевые правки. Google reCAPTCHA v2
и Яндекс SmartCaptcha подключаются по желанию; внешним виджетам нужен JavaScript,
запасного сценария без него нет.
См. [подключение и другие провайдеры](docs/wiki/Callbacks.md#ready-to-use-providers)
и [защиту гостей](docs/wiki/Security-and-privacy.md#low-friction-guest-checks).

### Языки

Английский (`en`), русский (`ru`), немецкий (`de`), французский (`fr`),
испанский (`es`) и бразильский португальский (`pt-br`) доступны для публичного интерфейса,
модерации, настроек и всех писем. Активный язык выбирает сайт средствами Django;
отложенные письма используют сохранённый язык получателя. Тексты комментариев
и причины отклонения автоматически не переводятся. Подробные руководства написаны
на английском, README — на русском и английском.
[Настройка языков →](docs/wiki/Configuration.md#languages)

## Быстрый старт

### 1. Установка

В виртуальном окружении существующего сайта Wagtail установите опубликованный выпуск:

```sh
python -m pip install commentail==1.3.1
```

Для необязательного драйвера PostgreSQL используйте
`python -m pip install 'commentail[postgres]==1.3.1'`.
Для существующей установки следуйте [инструкции обновления](docs/wiki/Installation.md#upgrading-and-restoring)
до нужной версии.

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

### 4. Почта и очистка

Настройте почтовый backend Django и запускайте команду раз в минуту:

```sh
python manage.py process_commentail
```

Команда отправляет очередь писем и удаляет просроченные временные записи. Гости
подтверждают email до модерации. При включённой почте авторы с email подписываются
на уведомления о прямых ответах; каждое такое письмо содержит отписку для комментария.

Можно настроить почтовый backend Django с доставкой через
API и запускать `commentail.background.process_pending()` в очереди проекта
вместо отдельной команды по расписанию. Выберите один способ запуска. Принятие
письма backend’ом ещё не доказывает доставку во входящие.
[Настройка backend’а, расписания и проверка →](docs/wiki/Email-and-worker.md)

### 5. Проверка интеграции

Отправьте комментарий из учётной записи, одобрите его в **Comments**, затем
проверьте ответ и доступную правку. В отдельной сессии браузера отправьте гостевой
комментарий и подтвердите email. Проверьте тему, права доступа и доставку на своём сайте.
[Проверки перед развёртыванием →](docs/wiki/Deployment.md#host-acceptance)

## Последние комментарии в других местах сайта

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

## Адаптация под сайт

Виджет имеет прозрачный фон, наследует шрифт и цвет текста контейнера и
следует светлой или тёмной теме сайта. Для стандартного оформления CSS-переменные
не требуются. При необходимости подключайте переопределения после его CSS:

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
| Эксплуатация | [Почта и фоновая обработка](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Email-and-worker.md) · [Развёртывание](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Deployment.md) · [Безопасность и приватность](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Security-and-privacy.md) |
| Диагностика | [Решение проблем / FAQ](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Troubleshooting.md) · [Пример и тестирование](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Example-and-testing.md) · [Производительность и нагрузочные проверки](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Performance.md) |

## Проверки и ограничения

Изменения между версиями описаны в [changelog](CHANGELOG.md) и
[инструкциях обновления](docs/wiki/Installation.md#upgrading-and-restoring).
Архив исходников включает запускаемый
пример Wagtail, тесты и руководства; wheel содержит исполняемый код, переводы,
шаблоны и статические файлы.

CI определяет 30 сочетаний фреймворков, Python и БД, проверки JavaScript,
линтеров, изменений моделей без миграций, переводов и установки из исходников/wheel.
Локальные проверки и размещённый CI — разные результаты; смотрите запуск для
используемой ревизии. Покрытие браузеров и доступности с его ограничениями
описано в [руководстве по тестированию](docs/wiki/Example-and-testing.md#acceptance-boundaries).

Нет отдельного REST API, редактора форматированного текста, загрузки
файлов, лайков, жалоб и обновлений в реальном времени. Повторные попытки отправки
могут дублировать письма после неопределённого результата backend’а. Темы сайта,
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
