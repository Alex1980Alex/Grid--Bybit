import os
import sys
from pybit.unified_trading import HTTP

def check_api_keys():
    # Указываем ключи явно
    api_key = "SiayVXsjJYRooFjrc3"
    api_secret = "SbiXaBTIASUBDoXuiHr2tbVDOqYNQtsGS2Do"
    
    print(f"Проверка подключения к тестовой сети Bybit с ключом: {api_key[:5]}...")
    
    try:
        # Создание клиента Bybit с testnet=True для тестовой сети
        client = HTTP(
            api_key=api_key,
            api_secret=api_secret,
            testnet=True  # Используем тестовую сеть
        )
        
        # Попытка получить баланс кошелька
        wallet_balance = client.get_wallet_balance(accountType="UNIFIED")
        
        # Проверка статуса ответа
        if wallet_balance["retCode"] == 0:
            print("Подключение успешно установлено!")
            print("Информация о кошельке:")
            
            # Вывод баланса по активам
            for coin in wallet_balance["result"]["list"][0]["coin"]:
                if float(coin["walletBalance"]) > 0:
                    print(f"  {coin['coin']}: {coin['walletBalance']}")
            
            return True
        else:
            print(f"Ошибка: {wallet_balance['retMsg']}")
            return False
        
    except Exception as e:
        print(f"Ошибка при подключении к тестовой сети Bybit: {str(e)}")
        return False

if __name__ == "__main__":
    check_api_keys() 