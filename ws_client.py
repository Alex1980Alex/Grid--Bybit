"""
Модуль для работы с WebSocket API Bybit V5
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
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 5  # секунд
        
        # Словарь с обработчиками событий
        self.handlers: Dict[str, List[Callable[[Dict[str, Any]], Awaitable[None]]]] = {
            "order": [],  # обработчики для событий ордеров
            "execution": [],  # обработчики для событий исполнения ордеров
            "wallet": [],  # обработчики для событий кошелька
            "position": [],  # обработчики для событий позиций
        }
        
        logger.info(f"Инициализирован WebSocket клиент для Bybit")
    
    def _generate_signature(self, expires: int) -> str:
        """
        Генерирует HMAC-SHA256 подпись для аутентификации WebSocket согласно документации Bybit V5
        
        Формула для V5: timestamp + api_key + recv_window
        
        Args:
            expires: Время истечения подписи в миллисекундах
            
        Returns:
            Строка с подписью
        """
        # Формируем строку для подписи (аналогично REST API)
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
            await self._authenticate()
            await self._subscribe_topics()
            
            # Запускаем пинг для поддержания соединения
            self.ping_task = asyncio.create_task(self._ping_loop())
            
            logger.info("Установлено соединение с WebSocket API Bybit")
            self.reconnect_attempts = 0
            
        except Exception as e:
            logger.error(f"Ошибка при установке соединения с WebSocket: {str(e)}")
            await self._try_reconnect()
    
    async def _authenticate(self):
        """Аутентифицируется на WebSocket API"""
        if not self.ws:
            logger.error("Невозможно выполнить аутентификацию: соединение не установлено")
            return
        
        expires = int(time.time() * 1000)  # Текущее время в миллисекундах
        signature = self._generate_signature(expires)
        
        # V5 требует [apiKey, timestamp, signature, recvWindow] в args
        auth_message = {
            "op": "auth",
            "args": [self.api_key, expires, signature, RECV_WINDOW]
        }
        
        await self.ws.send(json.dumps(auth_message))
        response = await self.ws.recv()
        response_data = json.loads(response)
        
        if not response_data.get("success", False):
            error_msg = response_data.get("ret_msg", "Unknown error")
            logger.error(f"Ошибка аутентификации на WebSocket: {error_msg}")
            raise Exception(f"Ошибка аутентификации: {error_msg}")
        
        logger.info("Аутентификация на WebSocket API успешна")
    
    async def _subscribe_topics(self):
        """Подписывается на необходимые топики"""
        if not self.ws:
            logger.error("Невозможно подписаться на топики: соединение не установлено")
            return
        
        # В V5 топики именуются с добавлением категории: order.spot, execution.spot
        subscribe_message = {
            "op": "subscribe",
            "args": ["order.spot", "execution.spot"]
        }
        
        await self.ws.send(json.dumps(subscribe_message))
        response = await self.ws.recv()
        response_data = json.loads(response)
        
        if not response_data.get("success", False):
            error_msg = response_data.get("ret_msg", "Unknown error")
            logger.error(f"Ошибка подписки на топики: {error_msg}")
            raise Exception(f"Ошибка подписки: {error_msg}")
        
        logger.info("Подписка на топики WebSocket API успешна")
    
    async def _ping_loop(self):
        """Отправляет пинг-сообщения для поддержания соединения"""
        try:
            while self.ws and not self.ws.closed:
                ping_message = {"op": "ping"}
                await self.ws.send(json.dumps(ping_message))
                await asyncio.sleep(20)  # Пинг каждые 20 секунд
        except Exception as e:
            logger.error(f"Ошибка в пинг-цикле: {str(e)}")
            if self.ws and not self.ws.closed:
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
        if self.ws and not self.ws.closed:
            await self.ws.close()
        
        # Отменяем пинг-задачу, если она запущена
        if self.ping_task and not self.ping_task.done():
            self.ping_task.cancel()
        
        # Пытаемся подключиться заново
        await self.connect()
    
    async def listen(self):
        """
        Слушает сообщения от WebSocket API и вызывает соответствующие обработчики
        
        Этот метод должен быть запущен после успешного connect()
        """
        if not self.ws:
            logger.error("Невозможно слушать сообщения: соединение не установлено")
            return
        
        try:
            async for message in self.ws:
                try:
                    data = json.loads(message)
                    
                    # Проверяем, является ли сообщение пингом/понгом
                    if "op" in data and data["op"] in ["ping", "pong"]:
                        # Bybit шлет {"op":"pong"} без поля success, просто игнорируем
                        continue
                    
                    # Проверяем на наличие ошибки в ответе
                    if "success" in data and not data["success"]:
                        logger.error(f"Ошибка от WebSocket: {data.get('ret_msg', 'Unknown error')}")
                        continue
                    
                    # Обрабатываем данные событий
                    if "topic" in data and "data" in data:
                        topic = data["topic"]
                        event_data = data["data"]
                        
                        # Определяем тип события (для order.spot и execution.spot)
                        event_type = None
                        if topic.startswith("order"):
                            event_type = "order"
                        elif topic.startswith("execution"):
                            event_type = "execution"
                        elif topic.startswith("wallet"):
                            event_type = "wallet"
                        elif topic.startswith("position"):
                            event_type = "position"
                        
                        # Вызываем все зарегистрированные обработчики для данного типа события
                        if event_type and event_type in self.handlers:
                            for handler in self.handlers[event_type]:
                                await handler(event_data)
                    
                except json.JSONDecodeError:
                    logger.error(f"Получено некорректное JSON-сообщение: {message}")
                except Exception as e:
                    logger.error(f"Ошибка при обработке сообщения WebSocket: {str(e)}")
        
        except ConnectionClosed as e:
            logger.warning(f"Соединение с WebSocket закрыто: {str(e)}")
            await self._try_reconnect()
        except Exception as e:
            logger.error(f"Ошибка при прослушивании WebSocket: {str(e)}")
            await self._try_reconnect()
    
    def add_handler(self, event_type: str, handler: Callable[[Dict[str, Any]], Awaitable[None]]):
        """
        Добавляет обработчик для определенного типа события
        
        Args:
            event_type: Тип события ('order', 'execution', 'wallet', 'position')
            handler: Асинхронная функция-обработчик, принимающая словарь с данными события
        """
        if event_type not in self.handlers:
            self.handlers[event_type] = []
        
        self.handlers[event_type].append(handler)
        logger.info(f"Добавлен обработчик для события '{event_type}'")
    
    async def close(self):
        """Закрывает соединение с WebSocket API"""
        if self.ping_task and not self.ping_task.done():
            self.ping_task.cancel()
        
        if self.ws and not self.ws.closed:
            await self.ws.close()
            logger.info("Соединение с WebSocket API закрыто") 