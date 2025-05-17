"""
Тесты для модуля bybit_api.py
"""
import pytest
import time
from unittest.mock import patch, MagicMock
from bybit_api import BybitAPI, BybitAPIError
from config import RECV_WINDOW

class TestBybitAPI:
    """Тесты для API-клиента Bybit"""
    
    def setup_method(self):
        """Подготовка перед каждым тестом"""
        self.api_key = "test_api_key"
        self.api_secret = "test_api_secret"
        self.api = BybitAPI(self.api_key, self.api_secret)
    
    def test_generate_signature(self):
        """Тест генерации подписи HMAC-SHA256"""
        timestamp = 1625000000000
        params = {"symbol": "BTCUSDT", "orderType": "Limit", "side": "Buy", "qty": "0.001", "price": "50000"}
        
        # Используем внутренний метод для тестирования подписи
        signature = self.api._generate_signature(params, timestamp)
        
        # Проверяем, что подпись является строкой hex
        assert isinstance(signature, str)
        assert len(signature) == 64  # SHA256 hex длина
        
        # Проверка формата - проверяем, что это hex-строка
        assert all(c in "0123456789abcdef" for c in signature.lower())
        
        # Тестируем подпись с пустыми параметрами
        empty_signature = self.api._generate_signature({}, timestamp)
        assert isinstance(empty_signature, str)
        assert len(empty_signature) == 64
        
        # Подписи для разных параметров должны отличаться
        assert signature != empty_signature

    @patch('requests.get')
    def test_request_get(self, mock_get):
        """Тест GET-запроса с корректными заголовками и параметрами"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "retCode": 0,
            "retMsg": "OK",
            "result": {"price": "50000"}
        }
        mock_get.return_value = mock_response
        
        # Фиксируем время
        timestamp = int(time.time() * 1000)
        with patch('time.time', return_value=timestamp/1000):
            result = self.api._request("GET", "/v5/market/tickers", {"symbol": "BTCUSDT"})
        
        # Проверяем, что запрос был выполнен с правильными параметрами
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        
        # URL должен содержать endpoint
        assert "/v5/market/tickers" in args[0]
        
        # Проверяем заголовки
        headers = kwargs['headers']
        assert headers['X-BAPI-API-KEY'] == self.api_key
        assert headers['X-BAPI-TIMESTAMP'] == str(timestamp)
        assert headers['X-BAPI-SIGN'] is not None
        assert headers['X-BAPI-RECV-WINDOW'] == str(RECV_WINDOW)
        
        # Проверяем параметры
        params = kwargs['params']
        assert params['symbol'] == "BTCUSDT"
        
        # Проверяем результат
        assert result == {"price": "50000"}
    
    @patch('requests.post')
    def test_request_post(self, mock_post):
        """Тест POST-запроса с корректными заголовками и телом запроса"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "retCode": 0,
            "retMsg": "OK",
            "result": {"orderId": "123456"}
        }
        mock_post.return_value = mock_response
        
        # Фиксируем время
        timestamp = int(time.time() * 1000)
        with patch('time.time', return_value=timestamp/1000):
            result = self.api._request("POST", "/v5/order/create", {
                "symbol": "BTCUSDT",
                "side": "Buy",
                "orderType": "Limit",
                "qty": "0.001",
                "price": "50000",
                "timeInForce": "GTC"
            })
        
        # Проверяем, что запрос был выполнен с правильными параметрами
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        
        # URL должен содержать endpoint
        assert "/v5/order/create" in args[0]
        
        # Проверяем заголовки
        headers = kwargs['headers']
        assert headers['X-BAPI-API-KEY'] == self.api_key
        assert headers['X-BAPI-TIMESTAMP'] == str(timestamp)
        assert headers['X-BAPI-SIGN'] is not None
        assert headers['X-BAPI-RECV-WINDOW'] == str(RECV_WINDOW)
        assert headers['Content-Type'] == "application/json"
        
        # Проверяем тело запроса
        json_data = kwargs['json']
        assert json_data['symbol'] == "BTCUSDT"
        assert json_data['side'] == "Buy"
        assert json_data['orderType'] == "Limit"
        
        # Проверяем результат
        assert result == {"orderId": "123456"}
    
    @patch('requests.get')
    def test_error_handling(self, mock_get):
        """Тест обработки ошибок от API"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "retCode": 10001,
            "retMsg": "Invalid API key"
        }
        mock_get.return_value = mock_response
        
        # Ожидаем ошибку при вызове метода
        with pytest.raises(BybitAPIError) as excinfo:
            self.api._request("GET", "/v5/market/tickers", {"symbol": "BTCUSDT"})
        
        # Проверяем детали ошибки
        assert excinfo.value.status_code == 200
        assert excinfo.value.error_code == 10001
        assert "Invalid API key" in excinfo.value.message 