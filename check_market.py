"""
Проверка доступа к публичному API Bybit
"""
import requests
import json

def check_bybit_connection():
    """
    Проверяет подключение к публичному API Bybit, 
    получая информацию о текущих ценах BTC/USDT
    """
    # Основная сеть Bybit
    main_url = "https://api.bybit.com/v5/market/tickers?category=spot&symbol=BTCUSDT"
    
    # Тестовая сеть Bybit
    test_url = "https://api-testnet.bybit.com/v5/market/tickers?category=spot&symbol=BTCUSDT"
    
    print("Проверка подключения к публичному API Bybit (не требует аутентификации)...\n")
    
    # Проверяем основную сеть
    print("1. Проверка основной сети Bybit")
    print(f"URL: {main_url}")
    
    try:
        response = requests.get(main_url)
        result = response.json()
        
        print(f"Код статуса HTTP: {response.status_code}")
        if response.status_code == 200 and result.get("retCode") == 0:
            print("Подключение к основной сети успешно!")
            btc_price = result.get("result", {}).get("list", [{}])[0].get("lastPrice", "N/A")
            print(f"Текущая цена BTC/USDT: {btc_price}")
        else:
            print(f"Ошибка: {result.get('retMsg', 'Неизвестная ошибка')}")
        
        print("\n" + "-" * 50 + "\n")
    except Exception as e:
        print(f"Исключение при подключении к основной сети: {str(e)}\n")
    
    # Проверяем тестовую сеть
    print("2. Проверка тестовой сети Bybit")
    print(f"URL: {test_url}")
    
    try:
        response = requests.get(test_url)
        result = response.json()
        
        print(f"Код статуса HTTP: {response.status_code}")
        if response.status_code == 200 and result.get("retCode") == 0:
            print("Подключение к тестовой сети успешно!")
            btc_price = result.get("result", {}).get("list", [{}])[0].get("lastPrice", "N/A")
            print(f"Текущая цена BTC/USDT в тестовой сети: {btc_price}")
        else:
            print(f"Ошибка: {result.get('retMsg', 'Неизвестная ошибка')}")
    except Exception as e:
        print(f"Исключение при подключении к тестовой сети: {str(e)}")
    
    print("\nВывод:")
    print("Если подключение к публичному API успешно, но с API ключами возникают проблемы,")
    print("значит проблема именно в ключах, а не в сетевом соединении или доступности серверов Bybit.")

if __name__ == "__main__":
    check_bybit_connection() 