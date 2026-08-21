# Shorts Creator Bot

Telegram-бот на Python, который принимает ссылку на видео или видеофайл и собирает вертикальные Shorts/Reels: выделяет удачные фрагменты, кадрирует видео в 9:16 и добавляет субтитры.

Реализован первый сквозной MVP: бот принимает ссылку или файл, запрашивает длительность, ставит задачу в Redis/Celery, а воркер транскрибирует, выбирает фрагменты, рендерит их и отправляет обратно в чат.

## Возможности MVP

- Приём ссылок на YouTube, VK и Rutube, а также загруженных видео.
- Диалог выбора длительности ролика: 15-30, 30-60 или 60-90 секунд.
- Очередь до 30 активных ссылок на пользователя; новые ссылки можно отправлять во время обработки.
- Пакетная отправка ссылок одним сообщением: формат и длительность выбираются один раз для всего списка.
- Фоновая обработка заданий через Celery и Redis.
- Скачивание через `yt-dlp`, распознавание речи с `faster-whisper`.
- Поиск фрагментов LLM с ответом в строгом JSON-формате.
- Рендер вертикального ролика 9:16 и одного стиля ASS-субтитров с помощью FFmpeg.
- Хранение заданий и их статусов в PostgreSQL.
- Whitelist пользователей и админка `/admin` с управлением доступом, баннером и памятью.
- В админке раздел «Память» показывает размер `jobs`, `uploads` и баннера. Очистка удаляет обработанные и загруженные видео, но сохраняет баннер.
- На стартовом экране есть режим «Спросить у ИИ» и пустой раздел настроек. Режим ИИ закрывается командой `/close`.

Пока промежуточные и итоговые файлы хранятся в общей Docker-папке `./media`; MinIO включён в окружение для следующего этапа переноса артефактов в S3.

## Требования

- Python 3.11 или новее.
- Установленный FFmpeg с поддержкой `libass`.
- Docker и Docker Compose для PostgreSQL, Redis и MinIO.
- Токен Telegram-бота.
- Ключ LLM с OpenAI-совместимым API. Для Anthropic потребуется добавить пакет `anthropic` и отдельный клиент.

Для обработки видео также потребуется достаточно места на диске и память, соответствующая выбранной модели Whisper.

## Установка

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Проверьте, что FFmpeg доступен:

```bash
ffmpeg -version
```

## Конфигурация

Создайте `.env` на основе `.env.example`. При локальном запуске без Docker замените хосты `redis` и `postgres` на `localhost`:

```dotenv
TELEGRAM_BOT_TOKEN=
ADMIN_ID=123456789
DATABASE_URL=postgresql+asyncpg://shorts:shorts@localhost:5432/shorts
REDIS_URL=redis://localhost:6379/0

S3_ENDPOINT_URL=http://localhost:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET=shorts

LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=
LLM_API_STYLE=chat_completions
WHISPER_MODEL=small
```

Не добавляйте `.env` и реальные ключи в Git.

После обновления уже существующей базы примените миграцию:

```bash
docker compose exec -T postgres psql -U shorts -d shorts < migrations/002_part2.sql
```

`ADMIN_ID` должен быть числовым Telegram ID владельца бота. Администратор автоматически получает доступ, остальные пользователи добавляются через `/admin`.

### vibecode.moe

У этого провайдера используется OpenAI Responses API, поэтому задайте в `.env`:

```dotenv
LLM_API_KEY=vk-...
LLM_BASE_URL=https://vibecode.moe/v1
LLM_MODEL=gpt-5.5
LLM_API_STYLE=responses
```

Это отдельная конфигурация для бота; файл `~/.codex/config.toml` из скрипта относится только к Codex CLI и боту не нужен.

## Планируемая структура

```text
shorts_bot/
  bot/          # aiogram: handlers, FSM, keyboards
  worker/       # Celery tasks
  pipeline/     # download, ASR, LLM, crop, subtitles, render
  db/           # SQLAlchemy models and Alembic migrations
  storage/      # S3 client
  config.py
docker-compose.yml
requirements.txt
```

## Запуск

```bash
docker compose up -d postgres redis minio
celery -A shorts_bot.worker.celery_app worker --loglevel=INFO
python -m shorts_bot.bot
```

В Docker Compose бот и воркер стартуют одной командой:

```bash
cp .env.example .env
# Заполните TELEGRAM_BOT_TOKEN и LLM_API_KEY.
docker compose up --build
```

Worker настроен на последовательную обработку: одна ссылка обрабатывается за раз, остальные ждут в очереди. После изменений обновляйте контейнеры так:

```bash
docker compose up -d --build --force-recreate bot worker
```

Если `LLM_API_KEY` не задан, воркер создаёт один ролик из начала распознанной речи. Это полезно для проверки пайплайна без LLM.

## Ограничения

- Максимальный размер входного файла: 2 ГБ. Размер ссылочных видео нужно проверять по метаданным до скачивания, когда источник это позволяет.
- Все тяжёлые операции выполняются только worker-процессом, а не обработчиком Telegram.
- Промежуточные артефакты (транскрипт и найденные сегменты) должны сохраняться, чтобы поддержать повторный рендер без повторной загрузки и ASR.
