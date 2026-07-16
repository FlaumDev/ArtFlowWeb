# Database Contract

Документ описывает действующий контракт общей PostgreSQL-базы между ArtFlowBot и ArtFlowWeb.

## 1. Правила контракта

- ArtFlowBot и ArtFlowWeb используют одну PostgreSQL-базу.
- Миграция публичных полей таблицы `competitions` уже выполнена.
- ArtFlowWeb выполняет только `SELECT` и не запускает миграции.
- ArtFlowWeb не импортирует `database.py` или другой код ArtFlowBot.
- SQL сайта использует параметры и явные списки столбцов, без `SELECT *`.
- Все запросы получают соединение из одного `AsyncConnectionPool` процесса FastAPI.
- Значения подключения, пароли и traceback не возвращаются посетителю.

## 2. Публичная таблица `competitions`

Таблица хранит конкурсы, которыми управляет ArtFlowBot и которые публикует ArtFlowWeb.

### Фактическая схема

| Поле | PostgreSQL-тип | Использование ArtFlowWeb |
|---|---|---|
| `id` | `INTEGER` | ID страницы и Telegram deep link |
| `name` | `TEXT` | Название конкурса |
| `description` | `TEXT` | Полное описание |
| `document` | `TEXT` | Не используется: это локальный путь ArtFlowBot |
| `date` | `TEXT` | Fallback, если `event_date` отсутствует |
| `place` | `TEXT` | Место и fallback для города |
| `price` | `TEXT` | Стоимость участия |
| `create_at` | `TIMESTAMP` | Сайтом не запрашивается |
| `event_date` | `DATE` | Дата события и сортировка |
| `application_deadline` | `DATE` | Срок подачи и статус регистрации |
| `city` | `TEXT` | Город проведения |
| `short_description` | `TEXT` | Краткий текст карточки |
| `directions` | `TEXT` | Направления, разделённые запятыми, точками с запятой или переносами строк |
| `poster_url` | `TEXT` | Публичная ссылка на афишу |
| `rules_url` | `TEXT` | Публичная ссылка на положение |
| `is_published` | `BOOLEAN` | Разрешение показа на сайте |
| `updated_at` | `TIMESTAMP` | Время последнего обновления |

`directions` имеет тип `TEXT`, а не `TEXT[]`. Поля `poster_url` и `rules_url` могут быть `NULL`. Сайт принимает эти ссылки только с протоколом `http://` или `https://`.

### Правила чтения

- сайт показывает только `is_published = TRUE`;
- список сортируется по `event_date ASC NULLS LAST`, затем по `id ASC`;
- главная страница использует параметризованный `LIMIT`;
- страница конкурса использует параметризованный `id` и тот же фильтр публикации;
- отрицательный или нулевой ID не отправляется в PostgreSQL;
- `date` и `place` используются только как fallback;
- `document` не выбирается и не публикуется.

## 3. Разрешённые SELECT-операции

Проверка подключения:

```sql
SELECT 1
```

Список опубликованных конкурсов выбирает только необходимые столбцы из `competitions`:

```sql
... FROM competitions
WHERE is_published = TRUE
ORDER BY event_date ASC NULLS LAST, id ASC
```

Для главной страницы к этому запросу добавляется параметризованный `LIMIT %s`.

Один конкурс выбирается по параметру:

```sql
... FROM competitions
WHERE id = %s AND is_published = TRUE
```

В ArtFlowWeb нет `INSERT`, `UPDATE`, `DELETE`, DDL-команд или миграций при старте.

## 4. Приватные таблицы

ArtFlowWeb не должен подключаться к следующим таблицам:

| Таблица | Доступ сайта |
|---|---|
| `artflow_bid` | Запрещён |
| `participants` | Запрещён |
| `users` | Запрещён |
| `admins` | Запрещён |

Рекомендуемая PostgreSQL-роль сайта получает `SELECT` только на публичные таблицы, необходимые frontend.

## 5. Deep-link контракт

Формат параметра:

```text
competition_<integer id>
```

Полная ссылка:

```text
https://t.me/BOT_USERNAME?start=competition_7
```

ArtFlowWeb формирует ссылку только при наличии `BOT_USERNAME`. ArtFlowBot должен отдельно реализовать разбор параметра, проверить ID, существование и доступность конкурса и только затем продолжить подачу заявки.
