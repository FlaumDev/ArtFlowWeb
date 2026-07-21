# ArtFlowWeb

Публичный сайт ArtFlow на FastAPI и Jinja2. Сайт читает опубликованные конкурсы и FAQ из общей PostgreSQL-базы и формирует Telegram deep links для перехода к выбранному конкурсу.

## Возможности

- главная страница с тремя ближайшими опубликованными конкурсами;
- список всех опубликованных конкурсов;
- подробная страница конкурса;
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

ORM, SQLAlchemy и Alembic не используются. PostgreSQL-соединения обслуживает небольшой асинхронный пул уровня процесса.

## Маршруты

| Маршрут | Назначение |
|---|---|
| `/` | Главная страница и три ближайших конкурса |
| `/competitions` | Все опубликованные конкурсы |
| `/competitions/{competition_id}` | Опубликованный конкурс по ID |
| `/faq` | Все частые вопросы из PostgreSQL |
| `/health` | Проверка FastAPI без обращения к БД |
| `/health/db` | Проверка PostgreSQL через `SELECT 1` |

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

## Тесты

Установить зависимости для разработки:

```powershell
py -m pip install -r requirements-dev.txt
```

Запустить тесты:

```powershell
py -m pytest
```

Проверить код и зависимости:

```powershell
py -m bandit -r app
py -m pip_audit -r requirements.lock
```

Для обновления lock создают чистое виртуальное окружение, устанавливают в него
только `requirements.txt`, выполняют тесты, а затем фиксируют реально
проверенное окружение:

```powershell
py -m pip freeze | Out-File -Encoding utf8 requirements.lock
```

Lock не обновляется догадками и `pip-audit --fix` не запускается автоматически.
Если Windows-путь содержит кириллицу и `pip-api` сообщает об ошибке декодирования,
перед аудитом можно установить `$env:PYTHONUTF8 = "1"`.

## Переменные окружения

- `DATABASE_URL` - полный DSN PostgreSQL; используется в приоритете.
- `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_PORT` - отдельные параметры подключения, если `DATABASE_URL` не задан.
- `BOT_USERNAME` - имя Telegram-бота с ведущим `@` или без него.
- `APP_ENV` - `development` или `production`.
- `BASE_URL` - публичный адрес; canonical и HSTS требуют HTTPS production URL.
- `ALLOWED_HOSTS` - разрешённые Host через запятую. В production указываются реальный домен и Railway-домен.
- `ENABLE_DOCS` - включает `/docs`, `/redoc` и `/openapi.json`; в production по умолчанию выключено.
- `ENABLE_SECURITY_HEADERS` - включает CSP и остальные защитные заголовки.

Если параметры PostgreSQL отсутствуют, приложение запускается, но маршруты с конкурсами и `/health/db` возвращают контролируемый статус `503` без раскрытия параметров подключения.

## Доступ к данным

ArtFlowWeb выполняет только `SELECT`: читает опубликованные записи таблицы `competitions` и записи таблицы `faq`. Сайт не запускает миграции, не изменяет схему и не обращается к таблицам заявок, участников, пользователей или администраторов.

Repository и `/health/db` получают соединения из одного `AsyncConnectionPool` с ограниченным временем ожидания.

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

## Безопасность

- `.env` исключён из Git;
- параметры подключения и traceback не показываются посетителю;
- SQL использует явные списки столбцов и параметры;
- внешние ссылки на афиши и положения в production принимаются только с `https://`;
- значения из БД экранируются Jinja2.

В development документация API доступна по `/docs`. В production FastAPI не
создаёт маршруты документации, если `ENABLE_DOCS` явно не включён.
