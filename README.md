# Telegram Music Stream Bot (VPS-ready)

Бот ищет музыку по названию и стримит ее в голосовой чат Telegram через `yt-dlp`.

## Возможности

- `/play <название>`: поиск и добавление трека в очередь
- `/skip`: пропустить текущий трек
- `/queue`: показать очередь
- `/now`: текущий трек
- `/stop`: остановить и очистить очередь
- `/ping`: проверка, что бот жив

## Архитектура

- `BOT_TOKEN` (бот) принимает команды в группе
- userbot-сессия (обычный Telegram-аккаунт) подключается к voice chat и стримит аудио

Это ограничение Telegram: бот сам по себе не может стримить в звонок без user-сессии.

## Файлы проекта

- `bot.py` - основной бот
- `create_session.py` - одноразовое создание user-сессии
- `docker-compose.yml` - прод-запуск в контейнере
- `deploy/tgstream.service` - вариант запуска через `systemd`

## 1) Подготовка переменных

1. Получите `API_ID` и `API_HASH` на `https://my.telegram.org`
2. Создайте бота через `@BotFather`, получите `BOT_TOKEN`
3. Создайте `.env`:

```env
API_ID=123456
API_HASH=your_api_hash
BOT_TOKEN=123456:ABCDEF
SESSION_NAME=music_user
SESSION_DIR=data/sessions
LOG_LEVEL=INFO
```

Можно скопировать из `.env.example`.

## 2) Рекомендуемый деплой на VPS через Docker

Ниже команды для Ubuntu 22.04/24.04.

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin
sudo systemctl enable --now docker

mkdir -p /opt/tgstream
cd /opt/tgstream
# скопируйте сюда файлы проекта
```

### Первый запуск: создать user-сессию

```bash
cd /opt/tgstream
cp .env.example .env
# заполните .env своими значениями

sudo docker compose run --rm auth
```

Команда попросит номер телефона, код Telegram и (если включено) 2FA-пароль.  
После этого в `data/sessions` появится файл сессии.

### Запуск бота

```bash
cd /opt/tgstream
sudo docker compose up -d --build bot
sudo docker compose logs -f bot
```

### Обновление

```bash
cd /opt/tgstream
# обновите файлы проекта
sudo docker compose up -d --build bot
```

## 3) Альтернатива: systemd + venv (без Docker)

```bash
sudo apt update
sudo apt install -y python3 python3-venv ffmpeg

sudo useradd -r -m -d /opt/tgstream -s /usr/sbin/nologin tgstream || true
sudo mkdir -p /opt/tgstream
sudo chown -R tgstream:tgstream /opt/tgstream
```

Далее в `/opt/tgstream`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
cp .env.example .env
# заполните .env
python create_session.py
```

Установка сервиса:

```bash
sudo cp deploy/tgstream.service /etc/systemd/system/tgstream.service
sudo systemctl daemon-reload
sudo systemctl enable --now tgstream
sudo systemctl status tgstream
sudo journalctl -u tgstream -f
```

## Подготовка в Telegram-группе

1. Добавьте бота в группу
2. Добавьте userbot-аккаунт в группу
3. Дайте userbot право входить в голосовой чат
4. Запустите voice chat в группе
5. Используйте `/play <название>`

## Частые проблемы

- `Failed to start playback`: обычно voice chat не запущен или userbot не имеет права в него зайти
- Не создается сессия: проверьте `API_ID`/`API_HASH` и входные данные Telegram
- Нет звука: проверьте, что на VPS установлен `ffmpeg` (в Docker уже включен)
