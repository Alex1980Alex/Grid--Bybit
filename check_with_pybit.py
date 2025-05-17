"""
Проверка API ключей Bybit с использованием официальной библиотеки pybit
"""
from pybit.unified_trading import HTTP

def check_api_keys(api_key, api_secret, is_testnet=False):
    """
    Проверка API ключей с использованием библиотеки pybit
    
    Args:
        api_key: API ключ Bybit
        api_secret: API секрет Bybit
        is_testnet: Использовать тестовую сеть
    """
    print(f"Проверка ключей через pybit в {'тестовой' if is_testnet else 'основной'} сети...")
    print(f"API ключ: {api_key}")
    
    try:
        # Создание экземпляра клиента API Bybit
        client = HTTP(
            api_key=api_key,
            api_secret=api_secret,
            testnet=is_testnet
        )
        
        # Попытка получить баланс кошелька
        response = client.get_wallet_balance(accountType="UNIFIED")
        
        print("Ответ API:")
        print(f"Status: {response.get('retCode')} - {response.get('retMsg')}")
        
        if response.get("retCode") == 0:
            print("✅ Подключение успешно!")
            # Вывод баланса если есть
            if response.get("result", {}).get("list"):
                coins = response["result"]["list"][0].get("coin", [])
                if coins:
                    print("\nИнформация о балансе:")
                    for coin in coins:
                        if float(coin.get("walletBalance", 0)) > 0:
                            print(f"  {coin.get('coin')}: {coin.get('walletBalance')}")
            return True
        else:
            print(f"❌ Ошибка: {response.get('retMsg')}")
            return False
            
    except Exception as e:
        print(f"❌ Исключение: {str(e)}")
        return False
    finally:
        print("")

def main():
    """Основная функция для проверки ключей"""
    # Старые ключи
    old_api_key = "SiayVXsjJYRooFjrc3"
    old_api_secret = "SbiXaBTIASUBDoXuiHr2tbVDOqYNQtsGS2Do"
    
    # Новые ключи
    new_api_key = "eTU3FQEKxBYH13DdxV"
    new_api_secret = "Uq18paemn5iqcuFrhYdQbEQWXVd7ocE5nBLO"
    
    print("=== Проверка старых ключей ===\n")
    mainnet_old = check_api_keys(old_api_key, old_api_secret, is_testnet=False)
    testnet_old = check_api_keys(old_api_key, old_api_secret, is_testnet=True)
    
    print("=== Проверка новых ключей ===\n")
    mainnet_new = check_api_keys(new_api_key, new_api_secret, is_testnet=False)
    testnet_new = check_api_keys(new_api_key, new_api_secret, is_testnet=True)
    
    print("=== ИТОГИ ПРОВЕРКИ ===")
    print("Старые ключи:")
    print(f"  Основная сеть: {'✅ Работают' if mainnet_old else '❌ Не работают'}")
    print(f"  Тестовая сеть: {'✅ Работают' if testnet_old else '❌ Не работают'}")
    
    print("Новые ключи:")
    print(f"  Основная сеть: {'✅ Работают' if mainnet_new else '❌ Не работают'}")
    print(f"  Тестовая сеть: {'✅ Работают' if testnet_new else '❌ Не работают'}")
    
    if not (mainnet_old or testnet_old or mainnet_new or testnet_new):
        print("\nОба набора ключей недействительны.")
        print("Рекомендации:")
        print("1. Убедитесь, что ключи скопированы без лишних пробелов.")
        print("2. Создайте новые ключи API в панели управления Bybit.")
        print("3. При создании ключей предоставьте все необходимые разрешения:")
        print("   - Чтение баланса кошелька")
        print("   - Управление ордерами")

if __name__ == "__main__":
    main() 