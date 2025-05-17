"""
Тесты для WebSocket клиента Bybit
"""
import pytest
import json
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
import websockets
from websockets.exceptions import ConnectionClosed

from ws_client import BybitWebsocket

@pytest.fixture
def ws_client():
    """Fixture для создания WebSocket клиента"""
    return BybitWebsocket("test_api_key", "test_api_secret")

@pytest.mark.asyncio
async def test_authentication(ws_client):
    """Тест аутентификации на WebSocket"""
    # Создаем мок для websockets.connect
    mock_ws = AsyncMock()
    mock_ws.send = AsyncMock()
    mock_ws.recv = AsyncMock(return_value=json.dumps({
        "success": True,
        "ret_msg": "OK",
        "conn_id": "test_conn_id"
    }))
    
    with patch('websockets.connect', return_value=AsyncMock(return_value=mock_ws)), \
         patch('time.time', return_value=1625000.0):
        # Вызываем _authenticate
        await ws_client._authenticate()
        
        # Проверяем, что был отправлен правильный запрос
        mock_ws.send.assert_called_once()
        args = mock_ws.send.call_args[0][0]
        auth_message = json.loads(args)
        
        assert auth_message["op"] == "auth"
        assert len(auth_message["args"]) == 4
        assert auth_message["args"][0] == "test_api_key"
        assert isinstance(auth_message["args"][2], str)  # signature

@pytest.mark.asyncio
async def test_subscribe_topics(ws_client):
    """Тест подписки на топики"""
    # Создаем мок для websocket
    mock_ws = AsyncMock()
    mock_ws.send = AsyncMock()
    mock_ws.recv = AsyncMock(return_value=json.dumps({
        "success": True,
        "ret_msg": "OK",
        "conn_id": "test_conn_id"
    }))
    
    # Устанавливаем мок в клиенте
    ws_client.ws = mock_ws
    
    # Вызываем _subscribe_topics
    await ws_client._subscribe_topics()
    
    # Проверяем, что был отправлен правильный запрос
    mock_ws.send.assert_called_once()
    args = mock_ws.send.call_args[0][0]
    subscribe_message = json.loads(args)
    
    assert subscribe_message["op"] == "subscribe"
    assert "order.spot" in subscribe_message["args"]
    assert "execution.spot" in subscribe_message["args"]

@pytest.mark.asyncio
async def test_handle_order_event(ws_client):
    """Тест обработки события ордера"""
    # Имитация ордера
    order_data = {
        "orderId": "1234567890",
        "symbol": "BTCUSDT",
        "side": "Buy",
        "orderStatus": "Filled",
        "price": "50000",
        "qty": "0.001"
    }
    
    # Создаем мок обработчика
    mock_handler = AsyncMock()
    ws_client.handlers["order"].append(mock_handler)
    
    # Вызываем обработчик
    await ws_client._process_message({
        "topic": "order",
        "data": [order_data]
    })
    
    # Проверяем, что обработчик был вызван с правильными данными
    mock_handler.assert_called_once_with([order_data])

@pytest.mark.asyncio
async def test_ping_loop(ws_client):
    """Тест цикла отправки пингов"""
    # Создаем мок для websocket
    mock_ws = AsyncMock()
    mock_ws.send = AsyncMock()
    ws_client.ws = mock_ws
    ws_client.is_connected = True
    
    # Имитируем один цикл ping_loop
    with patch('asyncio.sleep', new=AsyncMock()) as mock_sleep:
        # Запускаем ping_loop и прерываем его после одной итерации
        ping_task = asyncio.create_task(ws_client._ping_loop())
        await asyncio.sleep(0.1)  # Даем время на выполнение первой итерации
        
        # Имитируем потерю соединения
        ws_client.is_connected = False
        await asyncio.sleep(0.1)  # Даем время на завершение задачи
        
        # Проверяем, что был отправлен ping
        mock_ws.send.assert_called_once()
        args = mock_ws.send.call_args[0][0]
        ping_message = json.loads(args)
        
        assert ping_message["op"] == "ping"
        
        # Проверяем, что была вызвана функция sleep
        mock_sleep.assert_called_once()
        
        # Отменяем задачу, если она еще выполняется
        if not ping_task.done():
            ping_task.cancel()

@pytest.mark.asyncio
async def test_reconnect_on_connection_closed(ws_client):
    """Тест попытки переподключения при потере соединения"""
    # Создаем мок для websocket, который выбрасывает исключение при вызове recv
    mock_ws = AsyncMock()
    mock_ws.recv = AsyncMock(side_effect=ConnectionClosed(1000, "Connection closed"))
    ws_client.ws = mock_ws
    ws_client.is_connected = True
    
    # Мокаем _try_reconnect
    ws_client._try_reconnect = AsyncMock()
    
    # Запускаем listen_loop
    listen_task = asyncio.create_task(ws_client._listen_loop())
    await asyncio.sleep(0.1)  # Даем время на выполнение
    
    # Проверяем, что ws_client._try_reconnect был вызван
    ws_client._try_reconnect.assert_called_once()
    
    # Отменяем задачу
    if not listen_task.done():
        listen_task.cancel() 