"""
Обёртка над REST API Bybit V5
"""
import time
import json
import hmac
import hashlib
import urllib.parse
import logging
from typing import Dict, List, Optional, Any, Union, Tuple
import requests
from tenacity import retry, wait_fixed, stop_after_attempt, retry_if_exception

from config import BASE_URL, REQUEST_TIMEOUT, MAX_RETRIES, RETRY_WAIT_TIME, RETRY_ERROR_CODES, RECV_WINDOW

# Настройка логгера
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("bybit_api")

class BybitAPIError(Exception):
    """Исключение для ошибок API Bybit"""
    def __init__(self, status_code: int, message: str, error_code: Optional[int] = None):
        self.status_code = status_code
        self.message = message
        self.error_code = error_code
        super().__init__(f"Bybit API Error (code: {error_code}, status: {status_code}): {message}")


def is_bybit_error_retryable(exception: Exception) -> bool:
    """Проверяет, следует ли повторить запрос при данной ошибке"""
    if isinstance(exception, BybitAPIError) and exception.error_code in RETRY_ERROR_CODES:
        return True
    return False


class BybitAPI:
    """Класс для работы с REST API Bybit V5"""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = BASE_URL
        logger.info(f"Инициализирован BybitAPI")
    
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
        # Сортируем параметры, чтобы гарантировать последовательный порядок
        query = ""
        if params:
            # Конвертируем параметры в URL-кодированную строку запроса
            query = urllib.parse.urlencode(sorted(params.items()))
        
        # Формируем строку для подписи: timestamp + api_key + recv_window + query
        sign_str = f"{timestamp}{self.api_key}{RECV_WINDOW}{query}"
        
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
        signature = self._generate_signature(params if params else {}, timestamp)
        
        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": str(timestamp),
            "X-BAPI-SIGN": signature,
            "X-BAPI-RECV-WINDOW": str(RECV_WINDOW),
            "Content-Type": "application/json"  # Всегда ставим Content-Type: application/json
        }
        
        return headers

    def _handle_response(self, response: requests.Response) -> Dict[str, Any]:
        """Обрабатывает ответ от API"""
        data = response.json()
        
        if response.status_code != 200 or data.get("retCode") != 0:
            error_code = data.get("retCode", 0)
            error_msg = data.get("retMsg", "Unknown error")
            raise BybitAPIError(response.status_code, error_msg, error_code)
        
        return data.get("result", {})
    
    @retry(
        retry=retry_if_exception(is_bybit_error_retryable),
        wait=wait_fixed(RETRY_WAIT_TIME),
        stop=stop_after_attempt(MAX_RETRIES),
    )
    def _request(self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Выполняет запрос к API с автоматическим повтором при определенных ошибках"""
        url = f"{self.base_url}{endpoint}"
        
        is_post = method.lower() == "post"
        headers = self._get_headers(params, is_post)
        
        try:
            if is_post:
                response = requests.post(url, headers=headers, json=params, timeout=REQUEST_TIMEOUT)
            else:
                response = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
            
            return self._handle_response(response)
        except requests.RequestException as e:
            logger.error(f"Ошибка сети при запросе {endpoint}: {str(e)}")
            raise BybitAPIError(500, f"Ошибка сети: {str(e)}")
    
    # ===== Методы для работы с рыночными данными =====
    
    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """Получает информацию о текущей цене и объеме для символа"""
        endpoint = "/v5/market/tickers"
        params = {"category": "spot", "symbol": symbol}
        data = self._request("GET", endpoint, params)
        
        if not data.get("list") or len(data["list"]) == 0:
            raise BybitAPIError(404, f"Символ {symbol} не найден")
        
        return data["list"][0]
    
    def get_kline(self, symbol: str, interval: str, limit: int = 200) -> List[Dict[str, Any]]:
        """Получает исторические свечи (Kline/Candlestick)"""
        endpoint = "/v5/market/kline"
        params = {
            "category": "spot",
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
        data = self._request("GET", endpoint, params)
        return data.get("list", [])
    
    # ===== Методы для управления ордерами =====
    
    def place_order(
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
        """Размещает новый ордер"""
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
        
        return self._request("POST", endpoint, params)
    
    def cancel_order(self, symbol: str, order_id: Optional[str] = None, order_link_id: Optional[str] = None) -> Dict[str, Any]:
        """Отменяет существующий ордер по order_id или order_link_id"""
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
        
        return self._request("POST", endpoint, params)
    
    def cancel_all_orders(self, symbol: str) -> Dict[str, Any]:
        """Отменяет все активные ордера для указанного символа"""
        endpoint = "/v5/order/cancel-all"
        params = {
            "category": "spot",
            "symbol": symbol
        }
        
        return self._request("POST", endpoint, params)
    
    def get_active_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """Получает список активных ордеров для указанного символа"""
        endpoint = "/v5/order/realtime"
        params = {
            "category": "spot",
            "symbol": symbol
        }
        
        data = self._request("GET", endpoint, params)
        return data.get("list", [])
    
    def get_order_history(self, symbol: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Получает историю ордеров для указанного символа"""
        endpoint = "/v5/order/history"
        params = {
            "category": "spot",
            "symbol": symbol,
            "limit": limit
        }
        
        data = self._request("GET", endpoint, params)
        return data.get("list", [])
    
    # ===== Методы для получения информации об аккаунте =====
    
    def get_wallet_balance(self, coin: Optional[str] = None) -> Dict[str, Any]:
        """Получает информацию о балансе кошелька"""
        endpoint = "/v5/account/wallet-balance"
        params = {"accountType": "SPOT"}
        
        if coin:
            params["coin"] = coin
        
        data = self._request("GET", endpoint, params)
        return data.get("list", [])[0] if data.get("list") else {} 