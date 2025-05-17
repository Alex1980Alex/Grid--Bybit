"""
Утилиты для работы с API ключами Bybit
"""
import time
import hmac
import hashlib
import urllib.parse
import json
import logging
from typing import Tuple, Dict, Any, Optional
import requests

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("key_utils")

def _make_bybit_request(api_key: str, api_secret: str, endpoint: str, params: Dict[str, Any], 
                      testnet: bool = True) -> Tuple[int, Dict[str, Any]]:
    """
    Выполняет запрос к API Bybit с аутентификацией
    
    Args:
        api_key: API ключ Bybit
        api_secret: API секрет Bybit
        endpoint: Эндпоинт API (начинается с /)
        params: Параметры запроса
        testnet: Использовать тестовую сеть
        
    Returns:
        Tuple[int, Dict[str, Any]]: (HTTP код, ответ API)
    """
    # Выбор URL в зависимости от сети
    base_url = "https://api-testnet.bybit.com" if testnet else "https://api.bybit.com"
    
    # Подготовка запроса
    timestamp = int(time.time() * 1000)
    recv_window = 5000
    
    # Формируем строку для подписи
    param_str = urllib.parse.urlencode(params)
    sign_str = f"{timestamp}{api_key}{recv_window}{param_str}"
    
    # Генерируем HMAC-SHA256 подпись
    signature = hmac.new(
        bytes(api_secret, "utf-8"),
        bytes(sign_str, "utf-8"),
        digestmod=hashlib.sha256
    ).hexdigest()
    
    # Заголовки запроса
    headers = {
        "X-BAPI-API-KEY": api_key,
        "X-BAPI-TIMESTAMP": str(timestamp),
        "X-BAPI-SIGN": signature,
        "X-BAPI-RECV-WINDOW": str(recv_window)
    }
    
    # Полный URL с параметрами
    url = f"{base_url}{endpoint}?{param_str}"
    
    try:
        # Выполняем GET-запрос
        response = requests.get(url, headers=headers, timeout=10)
        return response.status_code, response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка сетевого запроса: {str(e)}")
        return 500, {"retCode": -1, "retMsg": f"Ошибка запроса: {str(e)}"}
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка декодирования JSON: {str(e)}")
        return 500, {"retCode": -1, "retMsg": "Ошибка декодирования ответа"}

def validate_key(api_key: str, api_secret: str, testnet: bool = True) -> Tuple[bool, str]:
    """
    Проверяет валидность API ключей Bybit
    
    Args:
        api_key: API ключ Bybit
        api_secret: API секрет Bybit
        testnet: Использовать тестовую сеть (по умолчанию True)
        
    Returns:
        Tuple[bool, str]: (is_valid, message)
            - is_valid: True если ключи валидны, False в противном случае
            - message: Сообщение о результате проверки
    """
    if not api_key or not api_secret:
        return False, "API ключ или секрет не указаны"
    
    # Проверка через запрос баланса кошелька
    status_code, response = _make_bybit_request(
        api_key=api_key,
        api_secret=api_secret,
        endpoint="/v5/account/wallet-balance",
        params={"accountType": "UNIFIED"},
        testnet=testnet
    )
    
    # Логируем результат
    network_type = "тестовой" if testnet else "основной"
    logger.debug(f"Проверка ключа в {network_type} сети, статус: {status_code}, ответ: {json.dumps(response)}")
    
    # Анализируем ответ
    if status_code == 200 and response.get("retCode") == 0:
        # Ключи валидны - проверим наличие баланса
        coins = []
        try:
            coins_data = response.get("result", {}).get("list", [{}])[0].get("coin", [])
            coins = [f"{coin['coin']}: {coin['walletBalance']}" for coin in coins_data 
                    if float(coin.get("walletBalance", 0)) > 0]
        except (KeyError, IndexError, ValueError) as e:
            logger.warning(f"Ошибка при обработке информации о балансе: {str(e)}")
        
        if coins:
            balances_str = ", ".join(coins)
            return True, f"Ключи действительны. Баланс: {balances_str}"
        else:
            return True, "Ключи действительны, но баланс пуст"
    else:
        # Ключи невалидны - анализируем причину
        ret_code = response.get("retCode")
        ret_msg = response.get("retMsg", "Неизвестная ошибка")
        
        if ret_code == 10003:
            return False, "Недействительный API ключ"
        elif status_code == 401:
            return False, "Ошибка аутентификации (401 Unauthorized)"
        else:
            return False, f"Ошибка API: {ret_msg} (код {ret_code})"

def check_key_permissions(api_key: str, api_secret: str, testnet: bool = True) -> Dict[str, bool]:
    """
    Проверяет разрешения API ключей
    
    Args:
        api_key: API ключ Bybit
        api_secret: API секрет Bybit
        testnet: Использовать тестовую сеть
        
    Returns:
        Dict[str, bool]: Словарь разрешений
            - read_balance: Чтение баланса кошелька
            - read_orders: Чтение ордеров
            - place_orders: Размещение ордеров
    """
    permissions = {
        "read_balance": False,
        "read_orders": False,
        "place_orders": False
    }
    
    # Проверяем возможность чтения баланса
    status_code, response = _make_bybit_request(
        api_key=api_key,
        api_secret=api_secret,
        endpoint="/v5/account/wallet-balance",
        params={"accountType": "UNIFIED"},
        testnet=testnet
    )
    permissions["read_balance"] = (status_code == 200 and response.get("retCode") == 0)
    
    # Проверяем возможность чтения ордеров
    status_code, response = _make_bybit_request(
        api_key=api_key,
        api_secret=api_secret,
        endpoint="/v5/order/realtime",
        params={"category": "spot", "symbol": "BTCUSDT"},
        testnet=testnet
    )
    permissions["read_orders"] = (status_code == 200 and response.get("retCode") == 0)
    
    # Проверяем возможность размещения ордеров (без фактического создания)
    # Только проверяем ответ на эндпоинте, который требует разрешения на создание ордеров
    status_code, response = _make_bybit_request(
        api_key=api_key,
        api_secret=api_secret,
        endpoint="/v5/order/create",  # Проверяем только доступ к эндпоинту
        params={"category": "spot"},  # Недостаточные параметры для создания ордера
        testnet=testnet
    )
    
    # Если ошибка связана с неверными параметрами (а не с отсутствием прав)
    # то права на создание ордеров есть
    permissions["place_orders"] = (status_code == 200 and 
                                  response.get("retCode") != 10003 and  # Не invalid API key
                                  response.get("retCode") != 10004 and  # Не permission denied
                                  response.get("retCode") != 10016)      # Не no permission
    
    return permissions

def get_available_networks(api_key: str, api_secret: str) -> Dict[str, bool]:
    """
    Определяет, в каких сетях работают ключи
    
    Args:
        api_key: API ключ Bybit
        api_secret: API секрет Bybit
        
    Returns:
        Dict[str, bool]: Словарь доступных сетей
            - mainnet: Основная сеть
            - testnet: Тестовая сеть
    """
    networks = {
        "mainnet": False,
        "testnet": False
    }
    
    # Проверяем основную сеть
    is_valid, _ = validate_key(api_key, api_secret, testnet=False)
    networks["mainnet"] = is_valid
    
    # Проверяем тестовую сеть
    is_valid, _ = validate_key(api_key, api_secret, testnet=True)
    networks["testnet"] = is_valid
    
    return networks

if __name__ == "__main__":
    # Пример использования
    import sys
    
    if len(sys.argv) != 3:
        print("Использование: python key_utils.py <api_key> <api_secret>")
        sys.exit(1)
    
    api_key = sys.argv[1]
    api_secret = sys.argv[2]
    
    # Проверка ключей в обеих сетях
    print("=== Проверка ключей ===")
    
    # Проверка в основной сети
    valid, message = validate_key(api_key, api_secret, testnet=False)
    print(f"Основная сеть: {'✅ Валидно' if valid else '❌ Невалидно'} - {message}")
    
    # Проверка в тестовой сети
    valid, message = validate_key(api_key, api_secret, testnet=True)
    print(f"Тестовая сеть: {'✅ Валидно' if valid else '❌ Невалидно'} - {message}")
    
    # Если ключи валидны хотя бы в одной из сетей, проверяем разрешения
    networks = get_available_networks(api_key, api_secret)
    if networks["mainnet"] or networks["testnet"]:
        print("\n=== Проверка разрешений ===")
        testnet = not networks["mainnet"]  # Используем тестовую сеть, если основная недоступна
        permissions = check_key_permissions(api_key, api_secret, testnet=testnet)
        
        network_name = "тестовой" if testnet else "основной"
        print(f"Разрешения в {network_name} сети:")
        print(f"- Чтение баланса: {'✅ Есть' if permissions['read_balance'] else '❌ Нет'}")
        print(f"- Чтение ордеров: {'✅ Есть' if permissions['read_orders'] else '❌ Нет'}")
        print(f"- Создание ордеров: {'✅ Есть' if permissions['place_orders'] else '❌ Нет'}")
        
        # Выводим рекомендации по использованию
        print("\n=== Рекомендации ===")
        if networks["mainnet"]:
            print("✅ Ключи работают в основной сети Bybit")
        if networks["testnet"]:
            print("✅ Ключи работают в тестовой сети Bybit")
            
        if permissions["read_balance"] and permissions["read_orders"] and permissions["place_orders"]:
            print("✅ Ключи имеют все необходимые разрешения для Grid-бота")
        else:
            print("⚠️ Обнаружены ограничения в разрешениях:")
            if not permissions["read_balance"]:
                print("  - Отсутствует доступ к балансу кошелька")
            if not permissions["read_orders"]:
                print("  - Отсутствует доступ к чтению ордеров")
            if not permissions["place_orders"]:
                print("  - Отсутствует доступ к созданию ордеров")
                
            print("\nСоздайте новые ключи API с необходимыми разрешениями в панели управления Bybit")
    else:
        print("\n⚠️ Ключи не работают ни в одной из сетей.")
        print("Рекомендации:")
        print("1. Проверьте правильность ключей")
        print("2. Убедитесь, что ключи активны в панели управления Bybit")
        print("3. Создайте новые ключи API с необходимыми разрешениями") 