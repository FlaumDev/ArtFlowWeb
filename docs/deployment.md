# Backend deployment ArtFlowWeb

## Обязательные настройки

Для production задаются:

```text
APP_ENV=production
APP_TIMEZONE=Asia/Almaty
BASE_URL=https://REAL_DOMAIN
ALLOWED_HOSTS=REAL_DOMAIN,RAILWAY_DOMAIN
ENABLE_DOCS=false
ENABLE_SECURITY_HEADERS=true
```

PostgreSQL настраивается через `DATABASE_URL` либо отдельные `DB_*` переменные. Значения не записываются в Git и не выводятся в application logs.

До запуска без подключения к production БД проверьте конфигурацию:

```powershell
python -m scripts.check_production_settings
```

Проверка требует `APP_ENV=production`, HTTPS origin в `BASE_URL`, выключенные docs,
включённые security headers и явный allow-list хостов, содержащий публичный домен.

## Railway, домены и proxy

- В `ALLOWED_HOSTS` указываются фактический пользовательский домен и Railway public
  hostname без `https://`, порта и пути.
- `*`, `localhost` и loopback не используются в production.
- TLS может завершаться на Railway proxy. Forwarded headers принимаются только от
  доверенной сети платформы; доверие ко всем источникам не включается автоматически.
- HTTPS redirect включается на платформе только после проверки forwarded protocol,
  чтобы исключить redirect loop.
- Railway healthcheck направляется на `/health`; `/health/db` остаётся ограниченной
  диагностикой PostgreSQL.

## Lifespan и healthcheck

Pool создаётся lifespan приложения, сохраняется в `app.state.database_pool` и закрывается при остановке экземпляра FastAPI. Отсутствующая или временно недоступная БД не мешает liveness приложения.

Основной Railway healthcheck направляется на:

```text
/health
```

`/health/db` является отдельной диагностикой PostgreSQL и кеширует результат на 5 секунд, чтобы частые проверки не исчерпывали pool.

## Логи

В production application access logs имеют JSON-формат. Каждый обычный HTTP-запрос получает request ID; лог содержит route template, status code и duration. `/health` и `/health/db` исключены из application access logs. Дублирующий `uvicorn.access` отключён, но `uvicorn.error` продолжает работать. Не следует включать в сообщения DSN, пароли, environment dump, query string или пользовательские данные.

## Запуск

Development:

```powershell
py -m uvicorn app.main:app --reload
```

Рекомендуемый Railway Start Command:

```text
python -m scripts.check_production_settings && python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"
```

Первая команда требует `APP_ENV=production`, `ENABLE_DOCS=false`,
`ENABLE_SECURITY_HEADERS=true`, public HTTPS `BASE_URL` и корректный
`ALLOWED_HOSTS`. Uvicorn запускается только после успешной проверки. Дополнительно
само production-приложение никогда не создаёт маршруты docs, даже если
`ENABLE_DOCS=true` попал в окружение по ошибке.

Каждый worker создаёт собственные pool и TTL-cache; общий Redis для текущего
публичного read-only сайта не требуется.

Локальный release archive создаётся перед передачей владельцу deployment:

```powershell
python -m scripts.create_release_archive
```

Скрипт не меняет исходные файлы и валидирует, что ZIP не содержит `.env`, `.git`,
виртуальное окружение, кэши, IDE/логи, тестовые скриншоты и сам созданный архив.
`.env.example` остаётся в составе.

## Проверка после деплоя

Для опубликованного конкурса с открытой регистрацией выполните:

```powershell
python -m scripts.verify_production https://REAL_DOMAIN --competition-id PUBLISHED_OPEN_ID
```

Скрипт не отправляет заявки и не делает запросы к внешним URL. Он проверяет HTTPS,
health, отключённые docs, CSP/HSTS и остальные headers, неизвестный Host, 404,
`robots.txt`, static `nosniff`, внешние ссылки и формат `competition_{id}`. Все пункты
ручного production checklist приведены в `docs/security.md`.

## Обязательный production checklist

Перед первым production deployment владелец вручную подтверждает каждый пункт:

1. Создан отдельный PostgreSQL-пользователь ArtFlowWeb.
2. Ему выдан `SELECT` только на `public.competitions` и `public.faq`.
3. У него нет доступа к таблицам заявок и участников.
4. В Railway настроены только необходимые variables без сохранения секретов в Git.
5. Реальный домен и Railway hostname перечислены в `ALLOWED_HOSTS`.
6. `/docs`, `/redoc` и `/openapi.json` отключены.
7. Публичный origin работает только через HTTPS.
8. Railway healthcheck использует `/health`, а не обязательную проверку БД.
9. На edge/reverse proxy/CDN настроен инфраструктурный rate limiting.
10. Выполнен `python -m scripts.verify_production` для реального HTTPS origin.
11. Lighthouse запущен вручную, а фактические результаты сохранены владельцем.
12. Подтверждено согласие на публикацию фотографий несовершеннолетних.
13. Владельцы разрешили публикацию всех показанных контактов.
14. Проверено резервное копирование общей PostgreSQL и процедура восстановления.

Этот checklist не выполняет SQL, не подключается к Railway и не запускает deploy
автоматически.
