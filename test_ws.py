import asyncio
import os
import logging
from dotenv import load_dotenv
from ws_client import BybitWebsocket

# Настройка логгера с уровнем DEBUG для отладки
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_ws")

# Загружаем переменные окружения из .env файла
load_dotenv()

# Вывод ключевых параметров для отладки
api_key = os.getenv('BYBIT_API_KEY')
api_secret = os.getenv('BYBIT_API_SECRET')
logger.debug(f"API KEY: {api_key}")
logger.debug(f"API SECRET: {api_secret[:3]}...")

async def handle_order_event(event_data):
    """Обработчик событий ордеров"""
    logger.info(f"Получено событие ордера: {event_data}")

async def handle_execution_event(event_data):
    """Обработчик событий исполнения ордеров"""
    logger.info(f"Получено событие исполнения: {event_data}")

async def test_websocket():
    """Тестирует подключение к WebSocket API Bybit"""
    api_key = os.getenv('BYBIT_API_KEY')
    api_secret = os.getenv('BYBIT_API_SECRET')
    
    if not api_key or not api_secret:
        logger.error("API ключи не найдены в .env файле")
        return
    
    logger.info(f"Используется API ключ: {api_key}")
    ws = BybitWebsocket(api_key, api_secret)
    
    # Добавляем обработчики событий
    ws.add_handler("order", handle_order_event)
    ws.add_handler("execution", handle_execution_event)
    
    try:
        # Подключаемся к WebSocket API
        await ws.connect()
        
        # Ждем 30 секунд, прослушивая события
        logger.info("Начинаем прослушивание событий...")
        await asyncio.sleep(30)
        
        # Закрываем соединение
        logger.info("Завершаем тест...")
        await ws.close()
        logger.info("Тест завершен успешно")
    except Exception as e:
        logger.error(f"Ошибка при тестировании WebSocket: {str(e)}")
        # Пытаемся корректно закрыть соединение при ошибке
        try:
            if ws.is_connected:
                await ws.close()
        except:
            pass
        raise

if __name__ == "__main__":
    try:
        asyncio.run(test_websocket())
    except KeyboardInterrupt:
        logger.info("Тест прерван пользователем")
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {str(e)}") 