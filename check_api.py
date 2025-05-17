#!/usr/bin/env python3
"""
Утилита для проверки API ключей Bybit в CI-среде
"""
import argparse
import logging
import sys
from key_utils import validate_key, load_keys_from_env

# Настройка логирования
logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)
logger = logging.getLogger("check_api")

def main():
    # Парсинг аргументов командной строки
    parser = argparse.ArgumentParser(description="Проверка API ключей Bybit для CI")
    parser.add_argument('--env', default='.env', help='Путь к .env файлу с API ключами')
    parser.add_argument('--verbose', action='store_true', help='Включить подробный вывод')
    parser.add_argument('--skip-real', action='store_true', 
                        help='Пропустить проверку в реальной сети, проверять только формат ключей')
    args = parser.parse_args()
    
    # Настройка логирования для подробного вывода
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        for handler in logging.getLogger().handlers:
            handler.setLevel(logging.DEBUG)
    
    # Загрузка ключей из .env файла
    api_key, api_secret = load_keys_from_env(args.env)
    
    # Проверка наличия ключей
    if not api_key or not api_secret:
        logger.error(f"API ключи не найдены в файле {args.env}")
        sys.exit(1)
    
    # Проверка формата ключей (базовая валидация)
    if len(api_key) < 10 or len(api_secret) < 10:
        logger.error("API ключи имеют некорректный формат")
        sys.exit(1)
    
    logger.info(f"API ключи найдены в файле {args.env}")
    
    # Если указан флаг --skip-real, пропускаем проверку в реальных сетях
    if args.skip_real:
        logger.info("Проверка в реальной сети пропущена (--skip-real)")
        sys.exit(0)
    
    # Проверка в тестовой сети
    valid_testnet, message_testnet = validate_key(api_key, api_secret, testnet=True)
    logger.info(f"Тестовая сеть: {'✅ Валидно' if valid_testnet else '❌ Невалидно'} - {message_testnet}")
    
    # Проверка в основной сети
    valid_mainnet, message_mainnet = validate_key(api_key, api_secret, testnet=False)
    logger.info(f"Основная сеть: {'✅ Валидно' if valid_mainnet else '❌ Невалидно'} - {message_mainnet}")
    
    # Выход с кодом 0, если хотя бы одна проверка успешна
    if valid_testnet or valid_mainnet:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main() 