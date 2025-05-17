"""
Клиент для WebSocket API Bybit V5
"""
import json
import time
import hmac
import hashlib
import asyncio
import logging
from typing import Dict, List, Any, Optional, Callable, Awaitable, Union
import websockets
from websockets.exceptions import ConnectionClosed

from config import WS_URL, RECV_WINDOW

# Настройка логгера
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ws_client")

class BybitWebsocket:
    """Класс для работы с WebSocket API Bybit V5"""
    
    def __init__(self, api_key: str, api_secret: str):
        """
        Инициализирует WebSocket клиент для Bybit
        
        Args:
            api_key: API ключ
            api_secret: API секрет
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.ws_url = WS_URL
        self.ws = None
        self.ping_task = None
        self.listen_task = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 5  # Начальная задержка перед переподключением в секундах
        self.is_connected = False
        
        # Словарь с обработчиками событий
        self.handlers = {
            "order": [],  # обработчики для событий ордеров
            "execution": [],  # обработчики для событий исполнения ордеров
            "wallet": [],  # обработчики для событий кошелька
            "position": [],  # обработчики для событий позиций
        }
        
        logger.info(f"Инициализирован WebSocket клиент для Bybit")
    
    def _generate_signature(self, expires: int) -> str:
        """
        Генерирует HMAC-SHA256 подпись для аутентификации WebSocket согласно документации Bybit V5
        
        Формула: expires + api_key + recv_window
        
        Args:
            expires: Время истечения подписи в миллисекундах
            
        Returns:
            Строка с подписью
        """
        # Формируем строку для подписи
        # Для V5 WebSocket API формула: expires + api_key + recv_window
        sign_str = f"{expires}{self.api_key}{RECV_WINDOW}"
        
        # Генерируем HMAC-SHA256 подпись
        signature = hmac.new(
            bytes(self.api_secret, "utf-8"),
            bytes(sign_str, "utf-8"),
            digestmod=hashlib.sha256
        ).hexdigest()
        
        return signature
    
    async def connect(self):
        """Устанавливает соединение с WebSocket API"""
        try:
            self.ws = await websockets.connect(self.ws_url)
            self.is_connected = True
            await self._authenticate()
            await self._subscribe_topics()
            
            # Запускаем пинг для поддержания соединения
            self.ping_task = asyncio.create_task(self._ping_loop())
            
            # Запускаем задачу прослушивания
            self.listen_task = asyncio.create_task(self._listen_loop())
            
            logger.info("Установлено соединение с WebSocket API Bybit")
            self.reconnect_attempts = 0
            
        except Exception as e:
            logger.error(f"Ошибка при установке соединения с WebSocket: {str(e)}")
            self.is_connected = False
            await self._try_reconnect()
    
    async def _authenticate(self):
        """Аутентифицируется на WebSocket API"""
        if not self.ws:
            logger.error("Невозможно выполнить аутентификацию: соединение не установлено")
            return
        
        # Время истечения в миллисекундах
        expires = int(time.time() * 1000)
        signature = self._generate_signature(expires)
        
        # Формирование сообщения аутентификации для V5 API
        auth_message = {
            "op": "auth",
            "args": [
                self.api_key,
                str(expires),
                signature,
                str(RECV_WINDOW)
            ]
        }
        
        logger.info(f"Отправка запроса аутентификации на WebSocket")
        logger.debug(f"Auth message: {auth_message}")
        
        await self.ws.send(json.dumps(auth_message))
        response = await self.ws.recv()
        response_data = json.loads(response)
        
        logger.debug(f"Ответ аутентификации: {response_data}")
        
        if "success" not in response_data or not response_data["success"]:
            error_msg = response_data.get("ret_msg", "Unknown error")
            logger.error(f"Ошибка аутентификации на WebSocket: {error_msg}")
            raise Exception(f"Ошибка аутентификации: {error_msg}")
        
        logger.info("Аутентификация на WebSocket API успешна")
    
    async def _subscribe_topics(self):
        """Подписывается на необходимые топики"""
        if not self.ws:
            logger.error("Невозможно подписаться на топики: соединение не установлено")
            return
        
        # Для V5 топики именуются с добавлением категории: order.spot, execution.spot
        topics = ["order.spot", "execution.spot"]
        
        subscribe_message = {
            "op": "subscribe",
            "args": topics
        }
        
        logger.info(f"Подписка на топики: {topics}")
        logger.debug(f"Subscribe message: {subscribe_message}")
        
        await self.ws.send(json.dumps(subscribe_message))
        response = await self.ws.recv()
        response_data = json.loads(response)
        
        logger.debug(f"Ответ подписки: {response_data}")
        
        if "success" not in response_data or not response_data["success"]:
            error_msg = response_data.get("ret_msg", "Unknown error")
            logger.error(f"Ошибка подписки на топики: {error_msg}")
            raise Exception(f"Ошибка подписки: {error_msg}")
        
        logger.info("Подписка на топики WebSocket API успешна")
    
    async def _ping_loop(self):
        """Отправляет пинг-сообщения для поддержания соединения"""
        try:
            while self.is_connected and self.ws:
                try:
                    ping_message = {"op": "ping"}
                    await self.ws.send(json.dumps(ping_message))
                    logger.debug("Отправлен ping")
                    await asyncio.sleep(20)  # Пинг каждые 20 секунд
                except Exception as e:
                    logger.error(f"Ошибка при отправке пинга: {str(e)}")
                    self.is_connected = False
                    break
        except Exception as e:
            logger.error(f"Ошибка в пинг-цикле: {str(e)}")
            self.is_connected = False
        
        # Если соединение потеряно, пытаемся переподключиться
        if not self.is_connected:
            await self._try_reconnect()
    
    async def _listen_loop(self):
        """Слушает WebSocket-соединение и обрабатывает сообщения"""
        try:
            while self.is_connected and self.ws:
                try:
                    message = await self.ws.recv()
                    data = json.loads(message)
                    
                    logger.debug(f"Получено сообщение: {data}")
                    
                    # Обработка пингов/понгов
                    if "op" in data and data["op"] in ["ping", "pong"]:
                        continue
                    
                    # Проверка на ошибки
                    if "success" in data and not data["success"]:
                        logger.warning(f"Ошибка в сообщении WebSocket: {data.get('ret_msg', 'Unknown error')}")
                        continue
                    
                    # Обработка данных событий
                    if "topic" in data and "data" in data:
                        topic = data["topic"]
                        event_data = data["data"]
                        
                        # Определяем тип события
                        event_type = None
                        if topic.startswith("order"):
                            event_type = "order"
                        elif topic.startswith("execution"):
                            event_type = "execution"
                        elif topic.startswith("wallet"):
                            event_type = "wallet"
                        elif topic.startswith("position"):
                            event_type = "position"
                        
                        # Вызываем обработчики
                        if event_type and event_type in self.handlers:
                            for handler in self.handlers[event_type]:
                                await handler(event_data)
                    
                except json.JSONDecodeError as e:
                    logger.error(f"Ошибка декодирования JSON: {str(e)}")
                except Exception as e:
                    logger.error(f"Ошибка при обработке сообщения: {str(e)}")
                    
        except ConnectionClosed as e:
            logger.warning(f"WebSocket соединение закрыто: {str(e)}")
            self.is_connected = False
        except Exception as e:
            logger.error(f"Ошибка в цикле прослушивания: {str(e)}")
            self.is_connected = False
        
        # Если соединение потеряно, пытаемся переподключиться
        if not self.is_connected:
            await self._try_reconnect()
    
    async def _try_reconnect(self):
        """Пытается переподключиться к WebSocket API после ошибки"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error(f"Достигнуто максимальное количество попыток переподключения ({self.max_reconnect_attempts})")
            return
        
        self.reconnect_attempts += 1
        delay = self.reconnect_delay * self.reconnect_attempts
        
        logger.info(f"Попытка переподключения {self.reconnect_attempts}/{self.max_reconnect_attempts} через {delay} секунд")
        await asyncio.sleep(delay)
        
        # Закрываем текущее соединение, если оно есть
        await self.close()
        
        # Пытаемся подключиться заново
        await self.connect()
    
    def add_handler(self, event_type: str, handler: Callable[[Any], Awaitable[None]]):
        """
        Добавляет обработчик для определенного типа события
        
        Args:
            event_type: Тип события ('order', 'execution', 'wallet', 'position')
            handler: Асинхронная функция-обработчик, принимающая данные события
        """
        if event_type not in self.handlers:
            self.handlers[event_type] = []
        
        self.handlers[event_type].append(handler)
        logger.info(f"Добавлен обработчик для события '{event_type}'")
    
    async def close(self):
        """Закрывает соединение с WebSocket API"""
        self.is_connected = False
        
        # Отменяем задачи прослушивания и пинга
        if self.ping_task and not self.ping_task.done():
            self.ping_task.cancel()
            
        if self.listen_task and not self.listen_task.done():
            self.listen_task.cancel()
            
        # Закрываем соединение
        try:
            if self.ws:
                await self.ws.close()
                logger.info("Соединение с WebSocket API закрыто")
        except Exception as e:
            logger.error(f"Ошибка при закрытии WebSocket: {str(e)}")
            
        self.ws = None
    
    async def listen(self):
        """
        Ожидает завершения цикла прослушивания
        
        Этот метод можно использовать для блокировки основного потока
        """
        if self.listen_task:
            try:
                await self.listen_task
            except asyncio.CancelledError:
                pass 