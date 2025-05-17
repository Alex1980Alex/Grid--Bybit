"""
Тесты для асинхронного API-клиента Bybit
"""
import pytest
import time
import json
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
import aiohttp
from aiohttp.client_reqrep import ClientResponse
from aiohttp import StreamReader
import hmac
import hashlib

from bybit_api_async import BybitAsyncAPI, BybitAPIError
from config import RECV_WINDOW

@pytest.fixture
def api_client():
    """Fixture для создания API-клиента"""
    return BybitAsyncAPI("test_api_key", "test_api_secret")

def test_generate_signature():
    """Тест генерации подписи HMAC-SHA256"""
    api_client = BybitAsyncAPI("test_api_key", "test_api_secret")
    timestamp = 1625000000000
    params = {"symbol": "BTCUSDT", "orderType": "Limit", "side": "Buy", "qty": "0.001", "price": "50000"}
    
    # Используем внутренний метод для тестирования подписи
    signature = api_client._generate_signature(params, timestamp)
    
    # Проверяем, что подпись является строкой hex
    assert isinstance(signature, str)
    assert len(signature) == 64  # SHA256 hex длина
    
    # Проверка формата - проверяем, что это hex-строка
    assert all(c in "0123456789abcdef" for c in signature.lower())
    
    # Тестируем подпись с пустыми параметрами
    empty_signature = api_client._generate_signature({}, timestamp)
    assert isinstance(empty_signature, str)
    assert len(empty_signature) == 64
    
    # Подписи для разных параметров должны отличаться
    assert signature != empty_signature
    
    # Проверяем алгоритм подписи вручную
    query_string = ""
    for key in sorted(params.keys()):
        query_string += f"{key}={params[key]}&"
    query_string += f"timestamp={timestamp}&recvWindow={RECV_WINDOW}"
    
    expected_signature = hmac.new(
        bytes("test_api_secret", "utf-8"),
        bytes(query_string, "utf-8"),
        hashlib.sha256
    ).hexdigest()
    
    assert signature == expected_signature

@pytest.fixture
def mock_response():
    """Fixture для создания моканного ответа aiohttp"""
    mock = AsyncMock(spec=ClientResponse)
    mock.status = 200
    mock.json = AsyncMock(return_value={
        "retCode": 0,
        "retMsg": "OK",
        "result": {"price": "50000"}
    })
    return mock

@pytest.mark.asyncio
async def test_request_get(api_client, mock_response):
    """Тест GET-запроса с корректными заголовками и параметрами"""
    # Создаем полный мок сессии
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_response)
    mock_session.close = AsyncMock()
    
    # Создаем мок контекстного менеджера для ClientSession
    mock_client_session = AsyncMock()
    mock_client_session.__aenter__.return_value = mock_session
    mock_client_session.__aexit__.return_value = None
    
    # Патчим aiohttp.ClientSession, чтобы не создавался реальный
    with patch('aiohttp.ClientSession', return_value=mock_client_session):
        # Вместо доступа к внутреннему session, создаем новую сессию в тесте
        api_client.session = None
        
        # Фиксируем время для детерминированного теста
        timestamp = 1625000000000
        with patch('time.time', return_value=timestamp/1000):
            result = await api_client._request("GET", "/v5/market/tickers", {"symbol": "BTCUSDT"})
        
        # Проверяем, что запрос был выполнен с правильными параметрами
        mock_session.get.assert_called_once()
        args, kwargs = mock_session.get.call_args
        
        # URL должен содержать endpoint
        assert "/v5/market/tickers" in args[0]
        
        # Проверяем параметры
        params = kwargs['params']
        assert params['symbol'] == "BTCUSDT"
        
        # Проверяем результат
        assert result == {"price": "50000"}

@pytest.mark.asyncio
async def test_request_post(api_client, mock_response):
    """Тест POST-запроса с корректными заголовками и телом запроса"""
    # Создаем полный мок сессии
    mock_session = AsyncMock()
    mock_session.post = AsyncMock(return_value=mock_response)
    mock_session.close = AsyncMock()
    
    # Создаем мок контекстного менеджера для ClientSession
    mock_client_session = AsyncMock()
    mock_client_session.__aenter__.return_value = mock_session
    mock_client_session.__aexit__.return_value = None
    
    # Патчим aiohttp.ClientSession, чтобы не создавался реальный
    with patch('aiohttp.ClientSession', return_value=mock_client_session):
        # Вместо доступа к внутреннему session, создаем новую сессию в тесте
        api_client.session = None
        
        # Фиксируем время для детерминированного теста
        timestamp = 1625000000000
        with patch('time.time', return_value=timestamp/1000):
            result = await api_client._request("POST", "/v5/order/create", {
                "symbol": "BTCUSDT",
                "side": "Buy",
                "orderType": "Limit",
                "qty": "0.001",
                "price": "50000",
                "timeInForce": "GTC"
            })
        
        # Проверяем, что запрос был выполнен с правильными параметрами
        mock_session.post.assert_called_once()
        args, kwargs = mock_session.post.call_args
        
        # URL должен содержать endpoint
        assert "/v5/order/create" in args[0]
        
        # Проверяем тело запроса
        json_data = kwargs['json']
        assert json_data['symbol'] == "BTCUSDT"
        assert json_data['side'] == "Buy"
        assert json_data['orderType'] == "Limit"
        
        # Проверяем результат
        assert result == {"price": "50000"}

@pytest.mark.asyncio
async def test_error_handling(api_client):
    """Тест обработки ошибок от API"""
    # Создаем ответ с ошибкой
    error_response = AsyncMock(spec=ClientResponse)
    error_response.status = 200
    error_response.json = AsyncMock(return_value={
        "retCode": 10001,
        "retMsg": "Invalid API key"
    })
    
    # Создаем полный мок сессии
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=error_response)
    mock_session.close = AsyncMock()
    
    # Создаем мок контекстного менеджера для ClientSession
    mock_client_session = AsyncMock()
    mock_client_session.__aenter__.return_value = mock_session
    mock_client_session.__aexit__.return_value = None
    
    # Патчим aiohttp.ClientSession, чтобы не создавался реальный
    with patch('aiohttp.ClientSession', return_value=mock_client_session):
        # Вместо доступа к внутреннему session, создаем новую сессию в тесте
        api_client.session = None
        
        # Ожидаем ошибку при вызове метода
        with pytest.raises(BybitAPIError) as excinfo:
            await api_client._request("GET", "/v5/market/tickers", {"symbol": "BTCUSDT"})
        
        # Проверяем детали ошибки
        assert excinfo.value.status_code == 200
        assert excinfo.value.error_code == 10001
        assert "Invalid API key" in excinfo.value.message

@pytest.mark.asyncio
async def test_retry_mechanism(api_client):
    """Тест механизма повторных попыток при ошибках"""
    # Создаем два разных ответа: сначала ошибка, затем успех
    error_response = AsyncMock(spec=ClientResponse)
    error_response.status = 200
    error_response.json = AsyncMock(return_value={
        "retCode": 10002,  # код ошибки из RETRY_ERROR_CODES
        "retMsg": "Request rate limit exceeded"
    })
    
    success_response = AsyncMock(spec=ClientResponse)
    success_response.status = 200
    success_response.json = AsyncMock(return_value={
        "retCode": 0,
        "retMsg": "OK",
        "result": {"success": True}
    })
    
    # Создаем полный мок сессии с последовательностью ответов
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(side_effect=[error_response, success_response])
    mock_session.close = AsyncMock()
    
    # Создаем мок контекстного менеджера для ClientSession
    mock_client_session = AsyncMock()
    mock_client_session.__aenter__.return_value = mock_session
    mock_client_session.__aexit__.return_value = None
    
    # Патч для уменьшения времени ожидания между повторами
    with patch('bybit_api_async.wait_exponential', return_value=0.01):
        # Патчим aiohttp.ClientSession, чтобы не создавался реальный
        with patch('aiohttp.ClientSession', return_value=mock_client_session):
            # Вместо доступа к внутреннему session, создаем новую сессию в тесте
            api_client.session = None
            
            # Вызываем метод
            result = await api_client._request("GET", "/v5/market/tickers", {"symbol": "BTCUSDT"})
            
            # Проверяем, что метод был вызван дважды (после ошибки произошла повторная попытка)
            assert mock_session.get.call_count == 2
            
            # Проверяем, что в итоге получен успешный результат
            assert result == {"success": True} 