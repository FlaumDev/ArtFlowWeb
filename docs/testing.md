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

Проверяются главная, меню, каталог и фильтры, страницы `/about` и
`/how-to-participate`, breadcrumbs, переход к связанному конкурсу, страница конкурса,
deep link, FAQ, fallback афиши, sticky CTA, error pages, console errors, базовая
доступность и отсутствие горизонтального overflow на ширинах 320, 375, 768 и
1440 px.
Если Python-пакеты Playwright не установлены, тесты пропускаются с явной причиной.
Если пакет установлен, но Chromium отсутствует, Playwright завершит запуск ошибкой с
командой установки браузера.

`requirements-e2e.lock` расширяет dev lock проверенными версиями Playwright,
pytest-playwright и их транзитивных зависимостей. Незакреплённые `requirements-dev.txt`
и `requirements-e2e.txt` используются только как входные списки при осознанном
обновлении lock-файлов.

## Performance audit

Инструмент использует установленный Python Playwright и локальный Chromium. Он не
подключается к production без явного `--base-url`, по умолчанию блокирует сторонние
resources и не отправляет формы или Telegram deep links:

```powershell
python -m scripts.performance_audit audit --base-url http://127.0.0.1:8000 --json-output dist/performance.json --markdown-output dist/performance.md
python -m scripts.performance_audit structural-checks --report dist/performance.json
python -m scripts.performance_audit compare dist/before.json dist/after.json --fail-on-regression --markdown-output dist/compare.md
```

Точные timing-значения не являются unit-test assertions. Детерминированные budgets
для CSS, JavaScript, HTML, requests, DOM и fallback описаны в
`docs/performance-budget.md`.

## Проверки backend

```powershell
python -m compileall app scripts
python -m bandit -r app scripts
python -m pip check
python -m pip_audit -r requirements.lock
```

## SEO

Технический SEO-набор не использует сеть или production PostgreSQL:

```powershell
python -m pytest -q tests/test_seo.py
```

Он проверяет title/description, canonical и social metadata всех публичных страниц,
`noindex` для ошибок и healthcheck, безопасный JSON-LD, фактический `Event`,
`BreadcrumbList`, соответствие видимых breadcrumbs JSON-LD, внутренние ссылки,
ограниченный блок связанных опубликованных конкурсов, `robots.txt`, sitemap и
соответствие каждого sitemap URL каноническому URL страницы. Тестовый production
origin равен
`https://artflowfest.com`; старый Railway hostname не допускается в HTML и XML.

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
