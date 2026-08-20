# Events Aggregator

FastAPI-сервис хранит локальную копию мероприятий из Events Provider API в
PostgreSQL, быстро отдаёт каталог и синхронно регистрирует посетителей во внешнем
сервисе.

## Возможности

- `GET /api/health` — readiness-проверка приложения и PostgreSQL;
- ежедневная и ручная (`POST /api/sync/trigger`) инкрементальная синхронизация;
- локальный список с SQL-фильтром `date_from` и пагинацией;
- локальная карточка события;
- актуальные места из Provider API с in-memory TTL-кэшем на 30 секунд;
- регистрация и отмена регистрации с сохранением локальной записи;
- PostgreSQL advisory lock от параллельной синхронизации в нескольких репликах;
- Alembic-миграции, Docker Compose, unit-тесты, Ruff и GitHub Actions.

Документация OpenAPI после запуска доступна на `/docs`.

## Архитектура

```text
HTTP API (FastAPI)
        |
Application use cases (не знают о FastAPI и PostgreSQL)
        |
Domain protocols
       / \
SQLAlchemy repositories   EventsProviderClient + EventsPaginator
        |                              |
   PostgreSQL                 Events Provider API
```

Внешние HTTP-вызовы сосредоточены в `EventsProviderClient`. Сериализация API не
содержит бизнес-логики. Репозитории реализуют доменные протоколы, поэтому use cases
тестируются через `unittest.mock` без сети и базы данных.

## Быстрый запуск

Требуются Docker и Docker Compose:

```bash
docker compose up --build
```

Приложение будет доступно на `http://localhost:8000`. В Compose синхронизация по
умолчанию отключена, пока не задан рабочий `EVENTS_PROVIDER_API_KEY`. Для её
включения скопируйте `.env.example` в `.env`, добавьте ключ и установите
`SYNC_ENABLED=true`.

Проверка:

```bash
curl http://localhost:8000/api/health
curl -X POST http://localhost:8000/api/sync/trigger
curl "http://localhost:8000/api/events?date_from=2026-01-01&page=1&page_size=20"
```

## Локальная разработка с uv

```bash
uv sync --all-groups
uv run alembic upgrade head
uv run uvicorn events_aggregator.main:app --reload
```

Перед отправкой изменений:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

## Конфигурация

| Переменная | Значение по умолчанию | Назначение |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://events:events@localhost:5432/events` | PostgreSQL DSN; также принимается `POSTGRES_CONNECTION_STRING` |
| `EVENTS_PROVIDER_BASE_URL` | `https://events-provider.dev-2.python-labs.ru` | URL внешнего API |
| `EVENTS_PROVIDER_API_KEY` | пусто | Значение заголовка `X-API-Key` |
| `EVENTS_PROVIDER_AUTH_MODE` | `api_key` | Режим `api_key` (`X-API-Key`), `token` или `bearer` |
| `EVENTS_PROVIDER_EVENTS_PATH` | `/api/events/` | Базовый путь мероприятий Provider API |
| `SYNC_ENABLED` | `true` | Запуск lifespan worker |
| `SYNC_RUN_ON_STARTUP` | `true` | Catch-up при старте |
| `SYNC_INTERVAL_SECONDS` | `86400` | Интервал успешных синхронизаций |
| `SYNC_BATCH_SIZE` | `100` | Размер пакета PostgreSQL upsert |
| `SYNC_OVERLAP_SECONDS` | `1` | Перекрытие watermark; Provider принимает дату, поэтому фактическое безопасное перекрытие — календарный день |
| `SEATS_CACHE_TTL_SECONDS` | `30` | TTL списка мест в памяти процесса |

Секреты и `.env` не должны попадать в Git. В production следует использовать secret
store платформы и один ASGI worker на контейнер. Advisory lock допускает несколько
контейнеров, но in-memory кэш мест у каждого из них независимый.

## Синхронизация

При первом запуске Provider API вызывается с `changed_at=2000-01-01`. Следующие
запуски читают `last_changed_at` из `sync_metadata`; для безопасной границы запрос
сдвигается назад и передаётся как дата. Поэтому фактически повторно читается граничный
календарный день, а PostgreSQL upsert остаётся идемпотентным.

События пишутся пакетами. Watermark продвигается только после полного успешного
обхода cursor-pagination. При ошибке уже записанные пакеты безопасны, прежний
watermark сохраняется, статус становится `failed`, а worker повторяет попытку.
Миграции и сама синхронизация используют разные PostgreSQL advisory locks, поэтому
одновременный старт нескольких реплик не запускает эти операции параллельно.

## CI/CD

Workflow имеет обязательную цепочку `lint -> test -> build-and-push -> deploy`.
Ruff (`check` и `format --check`) запускается первым, тесты выполняются на Python 3.9
и 3.13 с PostgreSQL 17, а `deploy` явно зависит от всех предыдущих jobs. Поэтому
образ не публикуется и запрос на деплой не выполняется при ошибке PEP8/lint.

Для production-деплоя в GitHub нужны:

- secret `LMS_API_KEY`;
- permission на публикацию пакета в GHCR;
- protected environment `production` и required checks для lint/test.

Автодеплой самой платформы по push следует отключить: единственным разрешённым
путём должен оставаться GitHub Actions после успешных проверок.
