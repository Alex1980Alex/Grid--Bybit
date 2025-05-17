"""
Конфигурационный файл с константами для Grid-бота Bybit
"""
from typing import Dict, Any, Optional

# Базовый URL для API Bybit
BASE_URL = "https://api.bybit.com"

# WebSocket URL для API Bybit
WS_URL = "wss://stream.bybit.com/v5/private"

# Таймаут для HTTP-запросов (в секундах)
REQUEST_TIMEOUT = 10

# Максимальное количество попыток повторного запроса при ошибке
MAX_RETRIES = 5

# Время ожидания между повторными попытками (в секундах)
RETRY_WAIT_TIME = 2

# Период времени жизни ордера (в минут): 0 - GTC (Good Till Cancel)
TIME_IN_FORCE = "GTC"

# Путь к файлу базы данных SQLite
DB_PATH = "grid_bot.db"

# Коды ошибок Bybit, для которых следует повторять запрос
RETRY_ERROR_CODES = [10006, 10016]

# Окно получения для API запросов (в миллисекундах)
RECV_WINDOW = 5000

# Логируемые события
LOG_EVENTS = {
    "order": True,  # Логировать события ордеров
    "trade": True,  # Логировать события сделок
    "grid": True,   # Логировать события изменения сетки
} 