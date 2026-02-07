# Telegram Music Stream Bot (voice chat, VPS-ready)

Бот ищет музыку по названию и стримит ее в групповой звонок Telegram.
English version: README.en.md

## Принцип работы

1. Команды принимает обычный бот (Bot API) через `BOT_TOKEN`.
2. За воспроизведение отвечает userbot-сессия (обычный аккаунт Telegram), именно она подключается к голосовому чату.
3. При `/play <название>` бот:
   - ищет трек через `yt-dlp`,
   - ставит его в очередь,
   - если ничего не играет — начинает стрим в голосовой чат.
4. Очередь ведется на уровне чата, поэтому несколько групп не мешают друг другу.
5. `/pause` и `/resume` управляют текущим стримом, `/skip` переключает на следующий, `/stop` очищает очередь и выходит из звонка.

## Важный момент

Полноценный стрим в voice chat нельзя сделать только через Bot API.  
Рабочая схема для звонка: бот для команд + userbot-сессия для подключения к звонку.

В этом проекте это уже реализовано:
- `BOT_TOKEN` принимает команды
- userbot (обычный аккаунт Telegram) заходит в голосовой чат и стримит аудио

## Где взять API_ID, API_HASH и BOT_TOKEN

### API_ID и API_HASH (Telegram API)

1. Открой сайт разработчиков Telegram.

```
https://my.telegram.org
```

2. Войди под своим Telegram-аккаунтом.
3. Открой раздел `API development tools`.
4. Создай приложение: укажи `App title` и `Short name` (любые понятные значения).
5. Сохрани `API_ID` и `API_HASH` — они нужны в `.env`.

### BOT_TOKEN (бот для команд)

1. В Telegram открой @BotFather.
2. Отправь команду `/newbot`.
3. Задай имя и username бота.
4. Скопируй выданный `BOT_TOKEN` и добавь в `.env`.

### Userbot (обычный аккаунт Telegram)

1. Используй обычный аккаунт Telegram, который будет заходить в голосовой чат.
2. Добавь этот аккаунт в группу.
3. Дай ему право входить в голосовой чат (и желательно `Manage video chats`).
4. При первом запуске нужно создать сессию для этого аккаунта.

## Как создать userbot-сессию

Вариант 1. Через Docker (рекомендуется для VPS):

```bash
sudo docker-compose run --rm auth
```

Введи номер телефона, код Telegram и пароль 2FA (если включен).  
Сессия сохранится в `data/sessions`.

Вариант 2. Локально через Python:

```bash
python create_session.py
```

Требуется установленный Python и заполненный `.env`.

## Команды

- `/play <название>` - поиск и добавление в очередь
- `/pause` - пауза
- `/resume` или `/unpause` - продолжить
- `/skip` - пропустить текущий трек
- `/reconnect` - вручную запустить реконнект
- `/queue` - показать очередь
- `/now` - текущий трек
- `/stop` - остановить и очистить очередь
- `/ping` - healthcheck
- `/POMOGITE` - помощь и список команд

Пауза/продолжение работают только в группе, когда уже есть активное воспроизведение.

## Переменные окружения

Создай `.env`:

```env
API_ID=123456
API_HASH=your_api_hash
BOT_TOKEN=123456:ABCDEF
SESSION_NAME=music_user
SESSION_DIR=data/sessions
LOG_LEVEL=INFO
PRIVILEGED_USER_IDS=123456789,987654321
RECONNECT_DELAY_SECONDS=8
RECONNECT_MAX_ATTEMPTS=0
```

`PRIVILEGED_USER_IDS` - список user id через запятую, которым разрешены `/skip` и `/reconnect`.  
Админы группы тоже могут использовать `/skip` и `/reconnect`.  
`RECONNECT_MAX_ATTEMPTS=0` означает бесконечные попытки реконнекта.

## Деплой на VPS через Docker

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin
sudo systemctl enable --now docker

mkdir -p /opt/tgstream
cd /opt/tgstream
# скопируйте сюда файлы проекта

cp .env.example .env
# заполните .env
```

### 1. Создать user-сессию (один раз)

```bash
sudo docker-compose run --rm auth
```

Введи номер телефона, код Telegram и 2FA-пароль (если включен).  
После этого сессия сохранится в `data/sessions`.

### 2. Запустить бота

```bash
sudo docker-compose up -d --build bot
sudo docker-compose logs -f bot
```

## Обновление

```bash
cd /opt/tgstream
# обновите файлы проекта
sudo docker-compose up -d --build bot
```

## Подготовка группы

1. Добавь бота в группу
2. Добавь userbot-аккаунт (которым создана сессия) в эту же группу
3. Дай userbot право входить в голосовой чат
4. Запусти голосовой чат
5. Запусти `/play <название>`

