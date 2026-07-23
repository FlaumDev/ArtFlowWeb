# Безопасность ArtFlowWeb

ArtFlowWeb является публичным read-only сайтом. Он читает только опубликованные
конкурсы и FAQ, не принимает заявки и не должен иметь доступ к таблицам участников.

## Production settings

В Railway задаются как минимум:

```text
APP_ENV=production
APP_TIMEZONE=Asia/Almaty
BASE_URL=https://REAL_DOMAIN
ALLOWED_HOSTS=REAL_DOMAIN,RAILWAY_PUBLIC_DOMAIN
ENABLE_DOCS=false
ENABLE_SECURITY_HEADERS=true
```

`ALLOWED_HOSTS` содержит только имена хостов без схемы, порта и пути. Значение `*`,
`localhost` и loopback-адреса в production запрещены. Публичный домен из `BASE_URL`
обязательно входит в allow-list. Локальная проверка без подключения к БД:

```powershell
python -m scripts.check_production_settings
```

Скрипт намеренно не печатает DSN, пароли или полный environment.

## Railway, Host и reverse proxy

- `RAILWAY_PUBLIC_DOMAIN` берётся из Settings сервиса Railway, пользовательский домен
  берётся из фактически подключённого домена проекта.
- Railway и пользовательский домен добавляются в `ALLOWED_HOSTS`; `*` не используется.
- `127.0.0.1`, `localhost` и `testserver` разрешены приложением только вне production.
- TLS может завершаться на Railway proxy. Forwarded headers следует принимать только
  от доверенной сети платформы; не задавайте доверие ко всем адресам без проверки.
- HTTPS redirect настраивается на платформе после проверки `X-Forwarded-Proto`.
  `HTTPSRedirectMiddleware` в приложении не включается вслепую, чтобы не создать loop.
- После деплоя неизвестный `Host` должен возвращать `400`, а публичный HTTPS URL не
  должен перенаправляться обратно на HTTP.

## Read-only роль PostgreSQL

Команды ниже выполняет владелец БД вручную. Приложение их не запускает. Замените
`DATABASE_NAME`, `SCHEMA_OWNER` и роли записи фактическими именами. Пароль задайте
интерактивно через `\password artflow_web` или секрет-хранилище, не вставляйте его в
SQL-файл, shell history или Git.

```sql
CREATE ROLE artflow_web
    LOGIN
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOINHERIT
    NOREPLICATION
    NOBYPASSRLS;

REVOKE ALL PRIVILEGES ON DATABASE DATABASE_NAME FROM artflow_web;
GRANT CONNECT ON DATABASE DATABASE_NAME TO artflow_web;

REVOKE ALL PRIVILEGES ON SCHEMA public FROM artflow_web;
GRANT USAGE ON SCHEMA public TO artflow_web;

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM artflow_web;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM artflow_web;
GRANT SELECT ON TABLE public.competitions, public.faq TO artflow_web;

ALTER DEFAULT PRIVILEGES FOR ROLE SCHEMA_OWNER IN SCHEMA public
    REVOKE ALL PRIVILEGES ON TABLES FROM artflow_web;
ALTER DEFAULT PRIVILEGES FOR ROLE SCHEMA_OWNER IN SCHEMA public
    REVOKE ALL PRIVILEGES ON SEQUENCES FROM artflow_web;

ALTER ROLE artflow_web SET default_transaction_read_only = on;
ALTER ROLE artflow_web SET statement_timeout = '5s';
ALTER ROLE artflow_web SET lock_timeout = '2s';
ALTER ROLE artflow_web SET search_path = public, pg_catalog;
```

Права, выданные `PUBLIC`, нельзя запретить только одной роли. Сначала проверьте их.
Если `PUBLIC` имеет `CREATE` на `public` или `TEMPORARY` на БД, владелец должен
осознанно отозвать эти общие права и вернуть их только ролям миграций/записи:

```sql
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE TEMPORARY ON DATABASE DATABASE_NAME FROM PUBLIC;

-- Примеры восстановления только тем ролям, которым это действительно нужно:
GRANT CREATE ON SCHEMA public TO SCHEMA_OWNER;
GRANT TEMPORARY ON DATABASE DATABASE_NAME TO SCHEMA_OWNER;
```

Перед выдачей DSN убедитесь, что `artflow_web` не состоит в других ролях. Если запрос
ниже возвращает строки, отзовите каждое членство отдельной командой
`REVOKE parent_role FROM artflow_web`.

```sql
SELECT parent.rolname AS inherited_role
FROM pg_auth_members membership
JOIN pg_roles parent ON parent.oid = membership.roleid
JOIN pg_roles member ON member.oid = membership.member
WHERE member.rolname = 'artflow_web';
```

Проверка эффективных прав после настройки:

```sql
SELECT
    has_database_privilege('artflow_web', 'DATABASE_NAME', 'CONNECT') AS can_connect,
    has_database_privilege('artflow_web', 'DATABASE_NAME', 'CREATE') AS can_create_db,
    has_database_privilege('artflow_web', 'DATABASE_NAME', 'TEMPORARY') AS can_temp;

SELECT
    has_schema_privilege('artflow_web', 'public', 'USAGE') AS can_use_schema,
    has_schema_privilege('artflow_web', 'public', 'CREATE') AS can_create_in_schema;

SELECT table_schema, table_name, privilege_type
FROM information_schema.role_table_grants
WHERE grantee = 'artflow_web'
ORDER BY table_schema, table_name, privilege_type;

SELECT private_table,
       has_table_privilege('artflow_web', 'public.' || private_table, 'SELECT') AS can_read,
       has_table_privilege('artflow_web', 'public.' || private_table, 'INSERT,UPDATE,DELETE') AS can_write
FROM unnest(ARRAY['artflow_bid', 'participants', 'users', 'admins']) AS private_table;

SELECT current_setting('default_transaction_read_only') AS read_only,
       current_setting('statement_timeout') AS statement_timeout,
       current_setting('lock_timeout') AS lock_timeout;
```

Ожидается: `CONNECT=true`, `USAGE=true`, `SELECT` только для `competitions` и `faq`;
`CREATE`, `TEMPORARY`, запись и доступ к приватным таблицам равны `false`.

## Security headers

| Ответ | Заголовки |
|---|---|
| Любой HTTP-ответ, включая CSS/JS/изображения | `X-Content-Type-Options: nosniff` |
| HTML и JSON | CSP, `Referrer-Policy`, `X-Frame-Options`, `Permissions-Policy`, `nosniff` |
| Production при валидном HTTPS `BASE_URL` | дополнительно `Strict-Transport-Security: max-age=31536000` |

Публичный CSP не содержит `unsafe-inline`, `unsafe-eval` и `data:`. Development Swagger
получает отдельный CSP с минимальными исключениями, необходимыми FastAPI docs;
в production `/docs`, `/redoc` и `/openapi.json` отсутствуют. HSTS не использует
`preload` и `includeSubDomains`.

## Внешние URL

- `poster_url` и `rules_url`: только `http/https` в development и только `https` в
  production; обязательны hostname, корректный port и отсутствие userinfo/control chars.
  В production дополнительно отклоняются loopback/private/unspecified IP, `localhost`
  и hostname без публичного доменного имени. Development и test сохраняют локальные URL.
- Telegram deep link формируется только как `competition_{id}` и только для
  валидного имени бота.
- Контакты принимают только `https://t.me`, `https://wa.me`/`api.whatsapp.com` и
  `https://instagram.com`/`www.instagram.com`.
- `javascript:`, `data:`, URL с username/password, malformed port и посторонним social
  host отбрасываются.
- Backend никогда не выполняет `GET` или `HEAD` к афишам, положениям или соцсетям.
- Внешние ссылки с новой вкладкой используют `rel="noopener noreferrer"`, а внешние
  афиши — `referrerpolicy="no-referrer"`.

## Secret scanning и зависимости

CI запускает Gitleaks по полной Git-истории с `--redact`, unit coverage,
integration/E2E, Bandit, `pip check`, `pip-audit` runtime lock-файла и проверку
production settings. Все jobs устанавливают соответствующий runtime/dev/E2E lock.
Workflow не имеет
production secrets и использует `permissions: contents: read`. Тестовые PostgreSQL
credentials изолированы и перечислены в узкой regex allow-list; целые директории не
исключаются из secret scan.

Локально:

```powershell
python -m bandit -r app scripts
python -m pip check
python -m pip_audit -r requirements.lock
```

`pip-audit --fix` автоматически не запускается. При CVE обновляется только затронутый
пакет после проверки совместимости и полного тестового прогона.

## DoS и rate limiting

Не добавляйте глобальный in-memory limiter: несколько worker-процессов не разделяют
его состояние. Ограничения задаются на Railway edge, reverse proxy или Cloudflare/CDN.
Стартовые значения, которые нужно уточнить по реальному трафику:

- HTML/JSON страницы: `60 requests/minute/IP`, burst `20`;
- `/health/db`: `6 requests/minute/IP`, burst `2`; platform monitoring лучше
  allow-list, основной Railway healthcheck направляется на `/health`;
- статические файлы: `300 requests/minute/IP`, burst `100` и CDN/browser cache;
- `/health`: отдельная allow-list для probes либо мягкий лимит `60/minute/IP`.

TTL-cache и небольшой pool уже уменьшают нагрузку на PostgreSQL. Ответы с ошибками БД
не кешируются надолго, а `/health/db` кеширует результат на 5 секунд.

## Privacy checklist

Перед публикацией фотографий несовершеннолетних владелец подтверждает:

- есть согласие законного представителя на публикацию;
- удалены EXIF, GPS и другие встроенные метаданные;
- в кадре нет документов, анкет, списков участников, адресов или экранов устройств;
- подпись не раскрывает дату рождения, медицинские или иные чувствительные сведения;
- публичные email, телефоны и social handles явно согласованы с владельцами;
- сайт и PostgreSQL-роль не читают заявки, документы и персональные данные участников.

## Проверка после деплоя

Скрипт выполняет только безопасные `GET` к указанному origin. Он не открывает внешние
афиши/положения, не обращается к Telegram/WhatsApp/Instagram и не отправляет заявки:

```powershell
python -m scripts.verify_production https://REAL_DOMAIN --competition-id PUBLISHED_OPEN_ID
```

Проверяются HTTPS, `/health`, отключённые docs, security headers, HSTS, неизвестный
`Host`, 404 без traceback, `/robots.txt`, static `nosniff`, внешний link policy и
Telegram deep link `competition_{id}`. Ненулевой exit code означает, что deployment
не прошёл проверку.

## Обязательный production checklist

1. Создать отдельного PostgreSQL-пользователя ArtFlowWeb.
2. Выдать `SELECT` только на `public.competitions` и `public.faq`.
3. Не выдавать доступ к таблицам заявок и участников.
4. Настроить Railway variables и не переносить их значения в Git или логи.
5. Указать реальный домен и Railway hostname в `ALLOWED_HOSTS`.
6. Отключить `/docs`, `/redoc` и `/openapi.json`.
7. Проверить HTTPS на публичном origin.
8. Использовать `/health` для Railway healthcheck.
9. Настроить rate limiting на Railway edge, reverse proxy или CDN.
10. Запустить `python -m scripts.verify_production` для реального origin.
11. Запустить Lighthouse вручную и сохранить фактический отчёт.
12. Подтвердить согласие на публикацию фотографий несовершеннолетних.
13. Подтвердить разрешение владельцев на публикацию контактов.
14. Проверить резервное копирование общей PostgreSQL и восстановление из копии.

SQL из раздела о read-only роли выполняется владельцем БД вручную. Приложение и
скрипты проекта не подключаются к Railway и не выполняют production deploy.
