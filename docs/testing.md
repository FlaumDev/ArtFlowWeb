# Тестирование ArtFlowWeb

## Unit

Unit-тесты не требуют Docker, Railway, Telegram или сетевого доступа:

```powershell
python -m pip install -r requirements-dev.lock
python -m pytest -q
```

Маркеры `integration` и `e2e` исключены из обычного запуска через `pytest.ini`.
`requirements-dev.lock` включает runtime lock, pytest, pytest-cov, Bandit,
pip-audit, Pillow и их проверенные транзитивные зависимости.

Coverage измеряется только на unit-наборе; подтверждённый RC-порог составляет 85%:

```powershell
python -m pytest -q --cov=app --cov-report=term-missing --cov-fail-under=85
```

## PostgreSQL integration

Integration-набор использует только локальную тестовую базу из `compose.integration.yml`. Он не читает `.env`, не использует production DSN и создаёт минимальные таблицы `competitions` и `faq` внутри одноразового контейнера.

Требования:

- установленный Docker с Compose;
- свободный локальный порт `55432`;
- возможность получить образ `postgres:17-alpine`.

Запуск:

```powershell
python -m pytest -m integration
```

Fixture запускает Compose, ждёт healthcheck и после тестов удаляет только integration-контейнер и его временный volume. Если Docker CLI или daemon недоступен, тесты пропускаются с явным сообщением.

Проверяются pool, опубликованные конкурсы, конкурс по ID, FAQ, преобразование `DATE`/`TIMESTAMP`, недоступная БД, read-only режим, statement timeout и отсутствие write SQL в repositories.

## Browser E2E

E2E-набор использует отдельное FastAPI-приложение из `tests/e2e/mock_app.py`.
Конкурсы и FAQ задаются mock-данными, параметры PostgreSQL принудительно очищаются,
а ссылки Telegram только проверяются и не открываются.

Установка:

```powershell
python -m pip install -r requirements-e2e.lock
python -m playwright install chromium
```

Запуск:

```powershell
python -m pytest -m e2e
```

Проверяются главная, меню, каталог и фильтры, страница конкурса, deep link,
FAQ, fallback афиши, sticky CTA, error pages, console errors, базовая доступность
и отсутствие горизонтального overflow на ширинах 320, 375, 768 и 1440 px.
Если Python-пакеты Playwright не установлены, тесты пропускаются с явной причиной.
Если пакет установлен, но Chromium отсутствует, Playwright завершит запуск ошибкой с
командой установки браузера.

`requirements-e2e.lock` расширяет dev lock проверенными версиями Playwright,
pytest-playwright и их транзитивных зависимостей. Незакреплённые `requirements-dev.txt`
и `requirements-e2e.txt` используются только как входные списки при осознанном
обновлении lock-файлов.

## Проверки backend

```powershell
python -m compileall app scripts
python -m bandit -r app scripts
python -m pip check
python -m pip_audit -r requirements.lock
```

Security-скрипты:

```powershell
python -m scripts.check_production_settings
python -m scripts.verify_production https://REAL_DOMAIN --competition-id PUBLISHED_OPEN_ID
```

Первый скрипт читает только настройки окружения и не подключается к БД. Второй
предназначен для уже опубликованного HTTPS deployment, выполняет только безопасные
same-origin `GET` и никогда не открывает внешние ссылки.

## GitHub Actions

`.github/workflows/ci.yml` запускается на `push` и `pull_request` и разделяет:

- unit, compileall, Bandit, `pip check`, `pip-audit` и production settings;
- Gitleaks по полной доступной Git-истории с redacted output;
- integration-тесты с отдельным PostgreSQL service container;
- E2E с локальным mock-приложением и Chromium.

Workflow имеет только `contents: read`, не получает Railway/Telegram secrets и не
выполняет deploy. Integration credentials являются локальными тестовыми значениями и
не используются за пределами одноразовой CI-базы.
