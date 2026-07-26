# ArtFlowWeb

Публичный сайт ArtFlow на FastAPI и Jinja2. Сайт читает опубликованные конкурсы и FAQ из общей PostgreSQL-базы и формирует Telegram deep links для перехода к выбранному конкурсу.

## Возможности

- главная страница с тремя ближайшими опубликованными конкурсами;
- список всех опубликованных конкурсов;
- подробная страница конкурса с видимыми breadcrumbs и связанными событиями;
- страницы «О проекте» и «Как принять участие»;
- главная подборка и отдельная страница FAQ;
- безопасные пустые состояния и HTML-страницы при недоступной БД;
- отдельные проверки работоспособности приложения и PostgreSQL;
- адаптивный frontend на HTML, CSS и Vanilla JavaScript.

## Стек

- Python;
- FastAPI;
- Jinja2;
- HTML, CSS, Vanilla JavaScript;
- PostgreSQL;
- psycopg 3 (`psycopg[binary,pool]`);
- python-dotenv.

ORM, SQLAlchemy и Alembic не используются. Каждый экземпляр FastAPI владеет своим небольшим асинхронным пулом и runtime-cache через `app.state`.

## Маршруты

| Маршрут | Назначение |
|---|---|
| `/` | Главная страница и три ближайших конкурса |
| `/competitions` | Все опубликованные конкурсы |
| `/competitions/{competition_id}` | Опубликованный конкурс по ID |
| `/faq` | Все частые вопросы из PostgreSQL |
| `/about` | Фактическое описание проекта и возможностей сайта |
| `/how-to-participate` | Инструкция по выбору конкурса и переходу к заявке |
| `/health` | Проверка FastAPI без обращения к БД |
| `/health/db` | Проверка PostgreSQL через `SELECT 1` |
| `/robots.txt` | Правила индексации и ссылка на sitemap для public HTTPS origin |
| `/sitemap.xml` | Публичные страницы и опубликованные конкурсы |

## Локальный запуск

1. Создать и активировать виртуальное окружение.
2. Установить зависимости:

```powershell
py -m pip install -r requirements.txt
```

3. Создать локальный `.env` по структуре `.env.example` и заполнить его вне Git.
4. Запустить приложение:

```powershell
py -m uvicorn app.main:app --reload
```

Сайт будет доступен по адресу `http://127.0.0.1:8000`.

Для production устанавливается проверенный lock-файл:

```powershell
py -m pip install -r requirements.lock
```

Рекомендуемый Railway Start Command сначала проверяет fail-closed production
settings и запускает сервер только при успешной проверке:

```text
python -m scripts.check_production_settings && python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"
```

Даже если `ENABLE_DOCS=true` задан ошибочно, production-приложение не создаёт
маршруты `/docs`, `/redoc` и `/openapi.json`. Проверка настроек всё равно требует
явного `ENABLE_DOCS=false` и завершает Start Command с ошибкой при нарушении.

## Тесты

Установить зависимости для разработки:

```powershell
py -m pip install -r requirements-dev.lock
```

Запустить unit-тесты без Docker:

```powershell
python -m pytest -q
```

Измерить покрытие только unit-тестами и применить RC-порог 85%:

```powershell
python -m pytest -q --cov=app --cov-report=term-missing --cov-fail-under=85
```

Запустить integration-тесты с изолированной PostgreSQL из Docker Compose:

```powershell
python -m pytest -m integration
```

Установить Chromium и запустить изолированные browser-тесты на mock-данных:

```powershell
py -m pip install -r requirements-e2e.lock
py -m playwright install chromium
python -m pytest -m e2e
```

Проверить код и зависимости:

```powershell
python -m bandit -r app
python -m pip check
python -m pip_audit -r requirements.lock
```

Проверить production-конфигурацию без подключения к БД и затем публичный deployment:

```powershell
python -m scripts.check_production_settings
python -m scripts.verify_production https://REAL_DOMAIN --competition-id PUBLISHED_OPEN_ID
```

CI на `push` и `pull_request` отдельно запускает unit/security, Gitleaks по
Git-истории, PostgreSQL integration и browser E2E. Workflow не выполняет deploy и не
использует production secrets.

Для обновления lock создают чистое виртуальное окружение, устанавливают в него
только `requirements.txt`, выполняют тесты, а затем фиксируют реально
проверенное окружение:

```powershell
py -m pip freeze | Out-File -Encoding utf8 requirements.lock
```

Lock не обновляется догадками и `pip-audit --fix` не запускается автоматически.
Если Windows-путь содержит кириллицу и `pip-api` сообщает об ошибке декодирования,
перед аудитом можно установить `$env:PYTHONUTF8 = "1"`.

`requirements.lock`, `requirements-dev.lock` и `requirements-e2e.lock` содержат
фактически установленные и проверенные версии. Файлы `requirements*.txt` остаются
входными списками для осознанного обновления; CI и повторяемые локальные проверки
устанавливают соответствующий lock-файл.

Создать проверенный release ZIP без `.env`, `.git`, локального окружения, кэшей,
логов и тестовых артефактов:

```powershell
python -m scripts.create_release_archive
```

Архив создаётся в `dist/ArtFlowWeb-release.zip`, сохраняет `.env.example`, после
записи повторно проверяет запрещённые пути и выводит итоговый путь и размер.

## Переменные окружения

- `DATABASE_URL` - полный DSN PostgreSQL; используется в приоритете.
- `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_PORT` - отдельные параметры подключения, если `DATABASE_URL` не задан.
- `BOT_USERNAME` - имя Telegram-бота с ведущим `@` или без него.
- `APP_ENV` - `development`, `test` или `production`.
- `APP_TIMEZONE` - IANA timezone для бизнес-даты дедлайна; по умолчанию `Asia/Almaty`.
- `BASE_URL` - публичный адрес; canonical и HSTS требуют HTTPS production URL.
- `ALLOWED_HOSTS` - разрешённые Host через запятую. В production указываются реальный домен и Railway-домен.
- `ENABLE_DOCS` - включает `/docs`, `/redoc` и `/openapi.json`; в production по умолчанию выключено.
- `ENABLE_SECURITY_HEADERS` - включает CSP и остальные защитные заголовки.

Если параметры PostgreSQL отсутствуют, приложение запускается, но маршруты с конкурсами и `/health/db` возвращают контролируемый статус `503` без раскрытия параметров подключения.

## SEO и индексация

Канонический origin текущего production-сайта — `https://artflowfest.com`.
Единственным источником origin для canonical, Open Graph, JSON-LD, `robots.txt` и
`sitemap.xml` служит валидный production `BASE_URL`; домен не дублируется в
шаблонах. Query string и fragment в canonical не включаются.

Индексируются только полезные HTML-ответы со статусом `200`:

- `/`;
- `/competitions`;
- `/faq`;
- `/about`;
- `/how-to-participate`;
- `/competitions/{competition_id}` для опубликованного конкурса.

Страницы `404`, `500`, `503`, отсутствующие или неопубликованные конкурсы получают
`noindex, nofollow` и не имеют canonical. `/health` и `/health/db` передают тот же
запрет через `X-Robots-Tag`. Production docs физически отсутствуют независимо от
ошибочного `ENABLE_DOCS=true`.

Title и description статических страниц задаются их route-контекстом. Для конкурса
title использует фактическое название, а description — очищенное краткое или полное
описание и только реально заполненные дату и город. Главная содержит `WebSite` и
минимальный `Organization`; страница конкурса — `BreadcrumbList` и, при наличии
фактических названия, описания, даты и места, `Event`. В `Event` намеренно не
выдумываются `endDate`, статус, формат присутствия, предложения, рейтинги, отзывы и
исполнители. Поле `organizer` также не выводится: в текущем PostgreSQL-контракте
нет подтверждённого организатора каждого опубликованного события. Если обязательных
реальных данных недостаточно, `Event` не выводится.

Sitemap доступен по `https://artflowfest.com/sitemap.xml` и содержит только
канонические статические страницы и опубликованные конкурсы. `lastmod`, `priority` и
`changefreq` не добавляются без надёжного источника. HTML-страницы отдельно не
кешируются; SEO формируется из тех же данных конкурса, что и страница, включая
существующий ограниченный TTL-cache.

Header, footer и главная связывают каталог, `/about`, `/how-to-participate` и FAQ
обычными HTML-ссылками. На внутренних страницах видимые breadcrumbs соответствуют
`BreadcrumbList`. Страница конкурса получает максимум три связанных опубликованных
события одним параметризованным `SELECT`: сначала тот же город, затем ближайшие
будущие даты и остальные записи в стабильном порядке. Результат живёт не дольше
общего TTL публичного cache.

Локальная проверка SEO:

```powershell
python -m pytest -q tests/test_seo.py
```

После deployment владелец добавляет `https://artflowfest.com` в Google Search
Console и Яндекс Вебмастер, подтверждает права и отправляет в обе панели
`https://artflowfest.com/sitemap.xml`. Это ручные операции: приложение не содержит
аналитику, счётчики или токены поисковых систем.

## Доступ к данным

ArtFlowWeb выполняет только `SELECT`: читает опубликованные записи таблицы `competitions` и записи таблицы `faq`. Сайт не запускает миграции, не изменяет схему и не обращается к таблицам заявок, участников, пользователей или администраторов.

Repository и `/health/db` получают явно переданный `AsyncConnectionPool` текущего экземпляра FastAPI с ограниченным временем ожидания. Pool создаётся и закрывается lifespan приложения; глобального изменяемого pool нет.

Статус регистрации вычисляется по календарной дате `APP_TIMEZONE`, а не по локальному времени сервера. Значения PostgreSQL `DATE` при этом не преобразуются и не изменяются.

Каждый HTTP-ответ получает `X-Request-ID`. Application access-log содержит только route template, status code и duration; `/health` и `/health/db` не записываются этим middleware. В development формат читаемый, в production — JSON.

Поток данных:

```text
route -> service -> repository -> PostgreSQL
```

Для конкурса с ID `7` сайт формирует ссылку вида:

```text
https://t.me/BOT_USERNAME?start=competition_7
```

ArtFlowWeb формирует ссылку, а ArtFlowBot обрабатывает параметр /start competition_{id}, проверяет конкурс и открывает выбранную карточку.

## Почему афиша может не отображаться

`poster_url` должен вести прямо на публичное изображение. Ссылка на обычную HTML-страницу может иметь красивое превью в Telegram, но тег `<img>` в браузере не сможет показать такую страницу как картинку. В этом случае, а также при недоступном или отсутствующем URL, сайт оставляет клиентский placeholder ArtFlow. Backend не скачивает и не проверяет внешние ссылки.

## Документация

- [Архитектура системы](docs/architecture.md)
- [Контракт базы данных](docs/database_contract.md)
- [Карта страниц](docs/sitemap.md)
- [Пользовательские сценарии](docs/user_flows.md)
- [Требования к контенту](docs/content_requirements.md)
- [Контракт Telegram deep link](docs/telegram_deep_link_contract.md)
- [Безопасность и production](docs/security.md)
- [Deployment backend](docs/deployment.md)
- [Тестирование](docs/testing.md)
- [Бюджеты производительности](docs/performance.md)
- [Карта SEO-контента и внутренних ссылок](docs/seo-content-map.md)

## Безопасность

- `.env` исключён из Git;
- параметры подключения и traceback не показываются посетителю;
- SQL использует явные списки столбцов и параметры;
- внешние ссылки на афиши и положения в production принимаются только с `https://`;
- значения из БД экранируются Jinja2.

В development документация API доступна по `/docs`, когда `ENABLE_DOCS=true`.
В production FastAPI никогда не создаёт маршруты документации, даже если
`ENABLE_DOCS=true` попал в окружение по ошибке.
