# Безопасность ArtFlowWeb

## Переменные production

В Railway задаются `APP_ENV=production`, `ENABLE_DOCS=false`,
`ENABLE_SECURITY_HEADERS=true`, `BASE_URL=https://REAL_DOMAIN` и
`ALLOWED_HOSTS=REAL_DOMAIN,RAILWAY_DOMAIN`. Вместо примеров используются только
реальные домены проекта и Railway без схемы и пути. Production без allow-list
закрыт по умолчанию, а `*` автоматически не добавляется.

TLS может завершаться на proxy Railway. HTTPS redirect следует включать на
платформе после проверки forwarded headers, чтобы не создать цикл редиректов.
HSTS приложение добавляет только при production и валидном HTTPS `BASE_URL`.

## Read-only роль PostgreSQL

ArtFlowWeb должен использовать отдельного PostgreSQL-пользователя, отличного
от владельца базы и пользователя ArtFlowBot. Ниже приведена ручная инструкция
с placeholders. Приложение её не выполняет.

```sql
CREATE ROLE artflow_web LOGIN PASSWORD 'CHANGE_ME';
GRANT CONNECT ON DATABASE DATABASE_NAME TO artflow_web;
GRANT USAGE ON SCHEMA public TO artflow_web;
GRANT SELECT ON TABLE public.competitions TO artflow_web;
GRANT SELECT ON TABLE public.faq TO artflow_web;
ALTER ROLE artflow_web SET default_transaction_read_only = on;
ALTER ROLE artflow_web SET statement_timeout = '5s';
```

Нельзя использовать владельца базы или DB-пользователя Telegram-бота. Роли
ArtFlowWeb не выдаются доступ к таблице заявок и права `INSERT`, `UPDATE`,
`DELETE`, `CREATE`, `ALTER` или `DROP`. Пароль хранится только в Railway
Variables. На уровне соединения приложение дополнительно устанавливает
`default_transaction_read_only=on` и `statement_timeout=5000` через параметры,
поддерживаемые psycopg, не изменяя `DATABASE_URL`.

## Нагрузка и проверки

Публичные SELECT для конкурсов и FAQ кешируются в процессе примерно на 30
секунд; результат `/health/db` - на 5 секунд. Основной Railway healthcheck
следует направлять на `/health`, если доступность БД не обязательна для запуска
контейнера. Глобальный rate limiting лучше настраивать на Railway, reverse proxy
или CDN, где доступны общий счётчик и реальный IP клиента.

Проверки зависимостей и Python-кода:

```powershell
py -m bandit -r app
py -m pip_audit -r requirements.lock
```

`pip-audit --fix` автоматически не запускается. Результат аудита считается
достоверным только при успешном доступе к базе уязвимостей.

## Передача проекта

ZIP-архив для передачи не должен содержать `.git`, `.env`, `.venv`,
`__pycache__`, IDE-файлы и логи. `.dockerignore` исключает эти данные из будущего
контекста сборки; `.gitignore` продолжает защищать локальный `.env`.

## Приватность

Контакты в `content/site_content.json` публичны, поэтому там допустимы только
контакты, разрешённые владельцами для публикации. Фотографии детей публикуются
только при наличии согласия; перед загрузкой из файлов удаляются EXIF и GPS.
Номера документов, даты рождения и данные заявок нельзя добавлять в публичный
сайт. ArtFlowWeb не должен обращаться к таблицам заявок.
