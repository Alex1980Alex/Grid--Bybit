"""
Утилиты для работы с API ключами Bybit
"""
import time
import hmac
import hashlib
import urllib.parse
import json
import logging
import argparse
import os
from typing import Tuple, Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv
import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Настройка логирования
logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)
logger = logging.getLogger("key_utils")

class RateLimitExceeded(Exception):
    """Исключение, возникающее при превышении лимита запросов к API"""
    pass

# Вспомогательная функция для определения, нужно ли повторять запрос
def is_rate_limit_error(exception):
    """Проверяет, является ли исключение ошибкой превышения лимита запросов"""
    if isinstance(exception, RateLimitExceeded):
        return True
    return False

@retry(
    retry=retry_if_exception_type(RateLimitExceeded),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=lambda retry_state: logger.warning(
        f"Превышен лимит запросов к API (попытка {retry_state.attempt_number}/3). Ожидание {retry_state.next_action.sleep} сек..."
    )
)
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
        
    Raises:
        RateLimitExceeded: В случае превышения лимита запросов (код 10018)
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
        
        # Проверяем ответ как JSON
        response_data = response.json()
        
        # Обработка ошибки превышения лимита запросов
        if response.status_code == 200 and response_data.get("retCode") == 10018:
            error_msg = response_data.get("retMsg", "IP rate limit exceeded")
            logger.error(f"Rate limit exceeded: {error_msg}")
            
            # Извлекаем информацию о лимите из заголовков, если доступна
            rate_limit_info = ""
            if 'X-Bapi-Limit' in response.headers and 'X-Bapi-Limit-Reset-Timestamp' in response.headers:
                limit = response.headers.get('X-Bapi-Limit')
                reset_time = int(response.headers.get('X-Bapi-Limit-Reset-Timestamp', 0)) / 1000
                reset_seconds = max(0, reset_time - time.time())
                rate_limit_info = f", лимит: {limit}, сброс через {reset_seconds:.0f} сек"
            
            # Выбрасываем исключение для retry-механизма
            raise RateLimitExceeded(f"Rate limit exceeded{rate_limit_info}")
        
        return response.status_code, response_data
    
    except RateLimitExceeded:
        # Пробрасываем дальше для обработки retry-декоратором
        raise
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
    
    try:
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
            elif ret_code == 10018:
                return False, f"Превышен лимит запросов API. {ret_msg}"
            elif ret_code == 10004:
                return False, "Отказано в доступе, недостаточно прав"
            elif ret_code == 10016:
                return False, "Нет разрешений для данной операции"
            elif status_code == 401:
                return False, "Ошибка аутентификации (401 Unauthorized)"
            else:
                return False, f"Ошибка API: {ret_msg} (код {ret_code})"
                
    except RateLimitExceeded as e:
        return False, f"Превышен лимит запросов API: {str(e)}"

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
            
    Raises:
        RateLimitExceeded: если достигнут лимит запросов
    """
    permissions = {
        "read_balance": False,
        "read_orders": False,
        "place_orders": False
    }
    
    try:
        # Проверяем возможность чтения баланса
        status_code, response = _make_bybit_request(
            api_key=api_key,
            api_secret=api_secret,
            endpoint="/v5/account/wallet-balance",
            params={"accountType": "UNIFIED"},
            testnet=testnet
        )
        permissions["read_balance"] = (status_code == 200 and response.get("retCode") == 0)
        
        # Если первый запрос показал ошибку лимита запросов, прерываем
        if status_code == 200 and response.get("retCode") == 10018:
            logger.warning("Достигнут лимит запросов API при проверке чтения баланса")
            return permissions
        
        # Проверяем возможность чтения ордеров
        status_code, response = _make_bybit_request(
            api_key=api_key,
            api_secret=api_secret,
            endpoint="/v5/order/realtime",
            params={"category": "spot", "symbol": "BTCUSDT"},
            testnet=testnet
        )
        permissions["read_orders"] = (status_code == 200 and response.get("retCode") == 0)
        
        # Если второй запрос показал ошибку лимита запросов, прерываем
        if status_code == 200 and response.get("retCode") == 10018:
            logger.warning("Достигнут лимит запросов API при проверке чтения ордеров")
            return permissions
        
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
        
    except RateLimitExceeded as e:
        logger.error(f"Проверка прав прервана из-за ограничения запросов: {str(e)}")
        # Сохраняем текущее состояние прав и возвращаем его
    
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
    try:
        is_valid, _ = validate_key(api_key, api_secret, testnet=False)
        networks["mainnet"] = is_valid
    except RateLimitExceeded:
        logger.warning("Проверка основной сети пропущена из-за превышения лимита запросов")
        # Оставляем значение False для основной сети
    
    # Проверяем тестовую сеть, только если не достигнут лимит запросов на основной
    try:
        is_valid, _ = validate_key(api_key, api_secret, testnet=True)
        networks["testnet"] = is_valid
    except RateLimitExceeded:
        logger.warning("Проверка тестовой сети пропущена из-за превышения лимита запросов")
        # Оставляем значение False для тестовой сети
    
    return networks

def load_keys_from_env(env_path: str = ".env") -> Tuple[str, str]:
    """
    Загружает API ключи из .env файла
    
    Args:
        env_path: Путь к .env файлу
        
    Returns:
        Tuple[str, str]: (api_key, api_secret)
    """
    # Проверка существования файла
    env_file = Path(env_path)
    if not env_file.exists():
        logger.error(f"Файл {env_path} не найден")
        return "", ""
    
    # Загрузка переменных из файла
    load_dotenv(env_path)
    
    # Получение ключей
    api_key = os.getenv("BYBIT_API_KEY", "")
    api_secret = os.getenv("BYBIT_API_SECRET", "")
    
    if not api_key or not api_secret:
        logger.warning(f"API ключи не найдены в файле {env_path}")
    
    return api_key, api_secret

def run_validation(env_path: str = ".env", verbose: bool = False, 
                   api_key: str = "", api_secret: str = "") -> bool:
    """
    Запускает проверку API ключей и выводит результаты
    
    Args:
        env_path: Путь к .env файлу (если api_key и api_secret не указаны)
        verbose: Включить подробный вывод
        api_key: API ключ Bybit (если указан, env_path игнорируется)
        api_secret: API секрет Bybit (если указан, env_path игнорируется)
        
    Returns:
        bool: True если ключи валидны, False в противном случае
    """
    # Настройка уровня логирования
    if verbose:
        logger.setLevel(logging.DEBUG)
        for handler in logger.handlers:
            handler.setLevel(logging.DEBUG)
    
    # Получаем ключи
    if not api_key or not api_secret:
        api_key, api_secret = load_keys_from_env(env_path)
    
    # Если ключи все еще не указаны, выходим
    if not api_key or not api_secret:
        logger.error("API ключи не указаны")
        return False
    
    # Проверка ключей в обеих сетях
    print("=== Проверка ключей ===")
    
    # Флаг для отслеживания превышения лимита запросов
    rate_limit_exceeded = False
    
    # Проверка в основной сети
    try:
        valid_mainnet, message_mainnet = validate_key(api_key, api_secret, testnet=False)
        print(f"Основная сеть: {'✅ Валидно' if valid_mainnet else '❌ Невалидно'} - {message_mainnet}")
    except RateLimitExceeded as e:
        valid_mainnet = False
        message_mainnet = f"Превышен лимит запросов API: {str(e)}"
        print(f"Основная сеть: ⚠️ Невозможно проверить - {message_mainnet}")
        rate_limit_exceeded = True
    
    # Проверка в тестовой сети
    try:
        valid_testnet, message_testnet = validate_key(api_key, api_secret, testnet=True)
        print(f"Тестовая сеть: {'✅ Валидно' if valid_testnet else '❌ Невалидно'} - {message_testnet}")
    except RateLimitExceeded as e:
        valid_testnet = False
        message_testnet = f"Превышен лимит запросов API: {str(e)}"
        print(f"Тестовая сеть: ⚠️ Невозможно проверить - {message_testnet}")
        rate_limit_exceeded = True
    
    # Если превышен лимит запросов, показываем соответствующее сообщение
    if rate_limit_exceeded:
        print("\n⚠️ Превышен лимит запросов к API Bybit")
        print("Рекомендации:")
        print("1. Подождите несколько минут и повторите попытку")
        print("2. Используйте VPN для изменения IP-адреса (если возможно)")
        print("3. Уменьшите частоту запросов к API")
        return False
    
    # Если ключи валидны хотя бы в одной из сетей, проверяем разрешения
    networks = get_available_networks(api_key, api_secret)
    if networks["mainnet"] or networks["testnet"]:
        print("\n=== Проверка разрешений ===")
        testnet = not networks["mainnet"]  # Используем тестовую сеть, если основная недоступна
        
        try:
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
                
        except RateLimitExceeded as e:
            print(f"⚠️ Невозможно проверить разрешения: {str(e)}")
            print("Повторите попытку позже или используйте другой IP-адрес")
    else:
        print("\n⚠️ Ключи не работают ни в одной из сетей.")
        print("Рекомендации:")
        print("1. Проверьте правильность ключей")
        print("2. Убедитесь, что ключи активны в панели управления Bybit")
        print("3. Создайте новые ключи API с необходимыми разрешениями")
    
    return valid_mainnet or valid_testnet

if __name__ == "__main__":
    # Парсинг аргументов командной строки
    parser = argparse.ArgumentParser(description="Утилита для проверки API ключей Bybit")
    parser.add_argument('--env', default='.env', help='Путь к .env файлу с API ключами')
    parser.add_argument('--verbose', action='store_true', help='Включить подробный вывод')
    parser.add_argument('--key', help='API ключ Bybit (если указан, --env игнорируется)')
    parser.add_argument('--secret', help='API секрет Bybit (если указан, --env игнорируется)')
    parser.add_argument('--testnet', action='store_true', help='Проверять только в тестовой сети')
    parser.add_argument('--mainnet', action='store_true', help='Проверять только в основной сети')
    args = parser.parse_args()
    
    # Если указаны позиционные аргументы, используем их как ключи
    api_key = args.key or ""
    api_secret = args.secret or ""
    
    # Запускаем проверку
    success = run_validation(
        env_path=args.env,
        verbose=args.verbose,
        api_key=api_key,
        api_secret=api_secret
    )
    
    # Выход с соответствующим кодом
    import sys
    sys.exit(0 if success else 1) 