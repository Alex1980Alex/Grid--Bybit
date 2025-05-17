"""
Проверка API ключей Bybit в основной и тестовой сети
"""
import os
import requests
import time
import hmac
import hashlib
import urllib.parse
import json

def test_bybit_api(api_key, api_secret, testnet=False, account_type="SPOT"):
    """
    Проверяет подключение к API Bybit с указанными ключами
    
    Args:
        api_key: API ключ Bybit
        api_secret: API секрет Bybit
        testnet: Использовать тестовую сеть
        account_type: Тип аккаунта (SPOT, UNIFIED, CONTRACT и др.)
        
    Returns:
        bool: True если подключение успешно
    """
    # Выбор URL в зависимости от сети
    base_url = "https://api-testnet.bybit.com" if testnet else "https://api.bybit.com"
    
    # Формируем запрос на получение баланса кошелька
    endpoint = "/v5/account/wallet-balance"
    timestamp = int(time.time() * 1000)
    recv_window = 5000
    params = {"accountType": account_type}
    
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
    
    print(f"Проверка подключения к {'тестовой' if testnet else 'основной'} сети Bybit...")
    print(f"URL: {url}")
    print(f"API ключ: {api_key}")
    print(f"Тип аккаунта: {account_type}")
    
    try:
        # Выполняем GET-запрос
        response = requests.get(url, headers=headers)
        
        # Разбираем ответ
        result = response.json()
        
        # Выводим результат
        print(f"Код статуса HTTP: {response.status_code}")
        print(f"Ответ API: {json.dumps(result, indent=2)}")
        
        if response.status_code == 200 and result.get("retCode") == 0:
            print("Подключение успешно!\n")
            return True
        else:
            print(f"Ошибка подключения: {result.get('retMsg', 'Неизвестная ошибка')}\n")
            return False
            
    except Exception as e:
        print(f"Исключение при подключении: {str(e)}\n")
        return False

def main():
    # Проверяемые API ключи
    api_key = "SiayVXsjJYRooFjrc3"
    api_secret = "SbiXaBTIASUBDoXuiHr2tbVDOqYNQtsGS2Do"
    
    # Проверяем разные типы аккаунтов в основной сети
    account_types = ["SPOT", "UNIFIED", "CONTRACT", "FUND"]
    
    for acc_type in account_types:
        test_bybit_api(api_key, api_secret, testnet=False, account_type=acc_type)
    
    # Проверяем тестовую сеть с разными типами аккаунтов
    for acc_type in account_types:
        test_bybit_api(api_key, api_secret, testnet=True, account_type=acc_type)
    
    print("\nПроверка завершена.")
    print("Если ни один из запросов не был успешным, API ключи либо недействительны, либо имеют недостаточные права.")
    print("Рекомендации:")
    print("1. Создайте новую пару ключей в панели управления Bybit")
    print("2. Убедитесь, что предоставлены все необходимые разрешения")

if __name__ == "__main__":
    main() 