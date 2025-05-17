"""
Асинхронная обёртка над REST API Bybit V5
"""
import time
import json
import hmac
import hashlib
import urllib.parse
import logging
import asyncio
from typing import Dict, List, Optional, Any, Union, Tuple

import aiohttp
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential, AsyncRetrying, RetryError

from config import BASE_URL, REQUEST_TIMEOUT, MAX_RETRIES, RETRY_ERROR_CODES, RECV_WINDOW

# Настройка логгера
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("bybit_api_async")

class BybitAPIError(Exception):
    """Исключение для ошибок API Bybit"""
    def __init__(self, status_code: int, message: str, error_code: Optional[int] = None):
        self.status_code = status_code
        self.message = message
        self.error_code = error_code
        super().__init__(f"Bybit API Error (code: {error_code}, status: {status_code}): {message}")


def is_bybit_error_retryable(exception: Exception) -> bool:
    """
    Проверяет, нужно ли повторить запрос при данной ошибке
    
    Args:
        exception: Исключение, которое нужно проверить
        
    Returns:
        True, если запрос следует повторить
    """
    if not isinstance(exception, BybitAPIError):
        return False
    
    # Повторяем запрос только для определенных кодов ошибок
    return exception.error_code in RETRY_ERROR_CODES


class BybitAsyncAPI:
    """Класс для работы с REST API Bybit V5 через асинхронные запросы"""
    
    def __init__(self, api_key: str, api_secret: str):
        """
        Инициализирует клиент API Bybit
        
        Args:
            api_key: API ключ
            api_secret: API секрет
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = BASE_URL
        self.session = None
        logger.info(f"Инициализирован BybitAsyncAPI")
    
    async def create_session(self):
        """Создает новую сессию aiohttp если она не существует"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            )
    
    async def close_session(self):
        """Закрывает сессию aiohttp"""
        if self.session and not self.session.closed:
            await self.session.close()
    
    def _generate_signature(self, params: Dict[str, Any], timestamp: int) -> str:
        """
        Генерирует HMAC-SHA256 подпись для запроса согласно документации Bybit V5
        
        Формула: timestamp + api_key + recv_window + query
        
        Args:
            params: Параметры запроса
            timestamp: Метка времени в миллисекундах
            
        Returns:
            Строка с HMAC-SHA256 подписью
        """
        # Для POST-запросов параметры должны быть отсортированы лексикографически по ключам
        sorted_params = dict(sorted(params.items())) if params else {}
        
        # Для GET-запросов строка запроса строится из URL-кодированных параметров
        # Для POST-запросов используем JSON-строку без пробелов
        if isinstance(sorted_params, dict) and sorted_params:
            query_string = urllib.parse.urlencode(sorted_params)
        else:
            query_string = ""
        
        # Формируем строку для подписи: timestamp + api_key + recv_window + query
        sign_str = f"{timestamp}{self.api_key}{RECV_WINDOW}{query_string}"
        
        # Генерируем HMAC-SHA256 подпись
        signature = hmac.new(
            bytes(self.api_secret, "utf-8"),
            bytes(sign_str, "utf-8"),
            digestmod=hashlib.sha256
        ).hexdigest()
        
        return signature
    
    def _get_headers(self, params: Optional[Dict[str, Any]] = None, is_post: bool = False) -> Dict[str, str]:
        """
        Формирует заголовки для запроса с авторизацией
        
        Args:
            params: Параметры запроса
            is_post: Флаг, указывающий является ли запрос POST
            
        Returns:
            Словарь заголовков
        """
        timestamp = int(time.time() * 1000)
        
        # Для POST-запросов сортируем параметры лексикографически
        sorted_params = dict(sorted(params.items())) if params and is_post else params
        
        signature = self._generate_signature(sorted_params if sorted_params else {}, timestamp)
        
        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": str(timestamp),
            "X-BAPI-SIGN": signature,
            "X-BAPI-RECV-WINDOW": str(RECV_WINDOW)
        }
        
        # Для POST-запросов добавляем Content-Type: application/json
        if is_post:
            headers["Content-Type"] = "application/json"
        
        return headers

    async def _handle_response(self, response: aiohttp.ClientResponse) -> Dict[str, Any]:
        """
        Обрабатывает ответ от API
        
        Args:
            response: Ответ от API
            
        Returns:
            Результат запроса
            
        Raises:
            BybitAPIError: при ошибке API
        """
        data = await response.json()
        
        if response.status != 200 or data.get("retCode") != 0:
            error_code = data.get("retCode", 0)
            error_msg = data.get("retMsg", "Unknown error")
            raise BybitAPIError(response.status, error_msg, error_code)
        
        return data.get("result", {})
    
    async def _request(self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Выполняет запрос к API с автоматическим повтором при определенных ошибках
        
        Args:
            method: HTTP метод (GET, POST)
            endpoint: Эндпоинт API
            params: Параметры запроса
            
        Returns:
            Результат запроса
            
        Raises:
            BybitAPIError: при ошибке API
        """
        # Создаем сессию если она не существует
        await self.create_session()
        
        url = f"{self.base_url}{endpoint}"
        is_post = method.lower() == "post"
        params = params or {}
        
        # Для POST-запросов параметры должны быть отсортированы перед формированием подписи
        sorted_params = dict(sorted(params.items())) if is_post else params
        
        # Используем асинхронный retry
        async for attempt in AsyncRetrying(
            retry=retry_if_exception(is_bybit_error_retryable),
            wait=wait_exponential(multiplier=1, min=1, max=60),
            stop=stop_after_attempt(MAX_RETRIES),
            reraise=True,
            before_sleep=lambda retry_state: logger.warning(
                f"Повторная попытка {retry_state.attempt_number}/{MAX_RETRIES} после ошибки. "
                f"Ожидание {retry_state.seconds_since_start:.1f} сек."
            )
        ):
            try:
                with attempt:
                    headers = self._get_headers(sorted_params, is_post)
                    
                    try:
                        if is_post:
                            # В POST запросе параметры отправляются как JSON в теле запроса
                            async with self.session.post(
                                url, headers=headers, json=sorted_params
                            ) as response:
                                logger.debug(f"POST {endpoint} {json.dumps(sorted_params)}")
                                return await self._handle_response(response)
                        else:
                            # В GET запросе параметры добавляются к URL
                            async with self.session.get(
                                url, headers=headers, params=params
                            ) as response:
                                logger.debug(f"GET {endpoint} {params}")
                                return await self._handle_response(response)
                    
                    except aiohttp.ClientError as e:
                        logger.error(f"Ошибка сети при запросе {endpoint}: {str(e)}")
                        raise BybitAPIError(500, f"Ошибка сети: {str(e)}")
            
            except RetryError as e:
                # Если все попытки исчерпаны, пробрасываем исходную ошибку
                if e.last_attempt:
                    raise e.last_attempt.exception()
                raise e
    
    # ===== Методы для работы с рыночными данными =====
    
    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """
        Получает информацию о текущей цене и объеме для символа
        
        Args:
            symbol: Символ (торговая пара)
            
        Returns:
            Информация о тикере
            
        Raises:
            BybitAPIError: при ошибке API
        """
        endpoint = "/v5/market/tickers"
        params = {"category": "spot", "symbol": symbol}
        data = await self._request("GET", endpoint, params)
        
        if not data.get("list") or len(data["list"]) == 0:
            raise BybitAPIError(404, f"Символ {symbol} не найден")
        
        return data["list"][0]
    
    async def get_kline(self, symbol: str, interval: str, limit: int = 200) -> List[Dict[str, Any]]:
        """
        Получает исторические свечи (Kline/Candlestick)
        
        Args:
            symbol: Символ (торговая пара)
            interval: Интервал времени свечи
            limit: Максимальное количество свечей
            
        Returns:
            Список исторических свечей
            
        Raises:
            BybitAPIError: при ошибке API
        """
        endpoint = "/v5/market/kline"
        params = {
            "category": "spot",
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
        data = await self._request("GET", endpoint, params)
        return data.get("list", [])
    
    # ===== Методы для управления ордерами =====
    
    async def place_order(
        self, 
        symbol: str, 
        side: str, 
        order_type: str,
        qty: str,
        price: Optional[str] = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
        order_link_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Размещает новый ордер
        
        Args:
            symbol: Символ (торговая пара)
            side: Сторона (Buy, Sell)
            order_type: Тип ордера (Limit, Market)
            qty: Количество
            price: Цена (для Limit ордеров)
            time_in_force: Время жизни ордера (GTC, IOC, FOK)
            reduce_only: Флаг уменьшения позиции
            order_link_id: Пользовательский ID ордера
            
        Returns:
            Информация о созданном ордере
            
        Raises:
            BybitAPIError: при ошибке API
        """
        endpoint = "/v5/order/create"
        params = {
            "category": "spot",
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "qty": qty,
            "timeInForce": time_in_force,
        }
        
        if price is not None:
            params["price"] = price
            
        if reduce_only:
            params["reduceOnly"] = True
            
        if order_link_id:
            params["orderLinkId"] = order_link_id
        
        return await self._request("POST", endpoint, params)
    
    async def cancel_order(self, symbol: str, order_id: Optional[str] = None, order_link_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Отменяет существующий ордер по order_id или order_link_id
        
        Args:
            symbol: Символ (торговая пара)
            order_id: ID ордера от биржи
            order_link_id: Пользовательский ID ордера
            
        Returns:
            Информация об отмененном ордере
            
        Raises:
            BybitAPIError: при ошибке API
            ValueError: если не указан ни order_id, ни order_link_id
        """
        endpoint = "/v5/order/cancel"
        params = {
            "category": "spot",
            "symbol": symbol
        }
        
        if order_id:
            params["orderId"] = order_id
        elif order_link_id:
            params["orderLinkId"] = order_link_id
        else:
            raise ValueError("Необходимо указать либо order_id, либо order_link_id")
        
        return await self._request("POST", endpoint, params)
    
    async def cancel_all_orders(self, symbol: str) -> Dict[str, Any]:
        """
        Отменяет все активные ордера для указанного символа
        
        Args:
            symbol: Символ (торговая пара)
            
        Returns:
            Результат отмены ордеров
            
        Raises:
            BybitAPIError: при ошибке API
        """
        endpoint = "/v5/order/cancel-all"
        params = {
            "category": "spot",
            "symbol": symbol
        }
        
        return await self._request("POST", endpoint, params)
    
    async def get_active_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Получает список активных ордеров для указанного символа
        
        Args:
            symbol: Символ (торговая пара)
            
        Returns:
            Список активных ордеров
            
        Raises:
            BybitAPIError: при ошибке API
        """
        endpoint = "/v5/order/realtime"
        params = {
            "category": "spot",
            "symbol": symbol
        }
        
        data = await self._request("GET", endpoint, params)
        return data.get("list", [])
    
    async def get_order_history(self, symbol: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Получает историю ордеров для указанного символа
        
        Args:
            symbol: Символ (торговая пара)
            limit: Максимальное количество записей
            
        Returns:
            Список ордеров
            
        Raises:
            BybitAPIError: при ошибке API
        """
        endpoint = "/v5/order/history"
        params = {
            "category": "spot",
            "symbol": symbol,
            "limit": limit
        }
        
        data = await self._request("GET", endpoint, params)
        return data.get("list", [])
    
    # ===== Методы для получения информации об аккаунте =====
    
    async def get_wallet_balance(self, coin: Optional[str] = None) -> Dict[str, Any]:
        """
        Получает информацию о балансе кошелька
        
        Args:
            coin: Валюта (опционально)
            
        Returns:
            Информация о балансе
            
        Raises:
            BybitAPIError: при ошибке API
        """
        endpoint = "/v5/account/wallet-balance"
        params = {"accountType": "SPOT"}
        
        if coin:
            params["coin"] = coin
        
        data = await self._request("GET", endpoint, params)
        return data.get("list", [])[0] if data.get("list") else {} 