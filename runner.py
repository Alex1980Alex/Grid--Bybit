"""
Grid-бот для Bybit: Основной файл запуска
"""
import time
import logging
import argparse
import threading
import sys
import signal
import os
from logging.handlers import RotatingFileHandler
import json
from typing import List, Dict, Any, Optional

from bybit_api import BybitAPI
from ws_client import BybitWebsocket
from grid import build_grid, calculate_initial_orders, calculate_mirror_order, find_grid_level
from db import GridBotDB

# Настройка логгера
logger = logging.getLogger("grid_bot")
logger.setLevel(logging.INFO)

# Вывод логов в консоль
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_format)
logger.addHandler(console_handler)

# Вывод логов в файл с ротацией
file_handler = RotatingFileHandler(
    filename="grid_bot.log",
    maxBytes=5*1024*1024,  # 5MB
    backupCount=3,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)
file_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_format)
logger.addHandler(file_handler)

class GridBot:
    """
    Grid-бот для торговли на Bybit
    
    Создаёт сетку ордеров Buy и Sell между указанными ценовыми уровнями
    и отслеживает их исполнение через WebSocket API.
    """
    
    def __init__(self, symbol: str, low_price: float, high_price: float, 
                 grid_levels: int, qty: float, test_mode: bool = False):
        """
        Инициализация бота
        
        Args:
            symbol: Торговая пара (например, BTCUSDT)
            low_price: Нижняя граница сетки
            high_price: Верхняя граница сетки
            grid_levels: Количество уровней в сетке
            qty: Количество базовой валюты для каждого ордера
            test_mode: Запуск в тестовом режиме без доступа к API (default: False)
        """
        self.symbol = symbol
        self.low_price = low_price
        self.high_price = high_price
        self.grid_levels = grid_levels
        self.qty = qty
        self.test_mode = test_mode
        
        # API-клиент для Bybit
        if not test_mode:
            self.api = BybitAPI()
        else:
            self.api = None
            logger.info("Бот запущен в тестовом режиме без доступа к API")
        
        # WebSocket-клиент для получения событий
        self.ws = None
        
        # База данных для хранения информации о сделках
        self.db = GridBotDB()
        
        # Сетка цен - инициализируем только если заданы границы диапазона
        self.grid_prices = None
        if low_price > 0 and high_price > 0 and low_price < high_price:
            self.grid_prices = build_grid(low_price, high_price, grid_levels)
        
        # Активные ордера: order_id -> order_info
        self.active_orders = {}
        
        # Флаг работы бота
        self.is_running = False
        
        # Блокировка для обработки событий WebSocket
        self.ws_lock = threading.Lock()
        
        logger.info(f"Инициализирован Grid-бот для {symbol} с {grid_levels} уровнями")
    
    def start(self):
        """
        Запуск бота: создание начальных ордеров и подключение к WebSocket
        """
        if self.is_running:
            logger.warning("Бот уже запущен")
            return
            
        self.is_running = True
        
        try:
            # Получаем текущую цену через API или используем тестовые данные
            current_price = self._get_current_price()
            
            # Если заданы границы диапазона, используем их,
            # иначе определяем автоматически на основе текущей цены и волатильности
            if self.low_price == 0 or self.high_price == 0 or self.grid_prices is None:
                self._set_price_range_from_volatility(current_price)
                logger.info(f"Автоматически определен диапазон цен: {self.low_price} - {self.high_price}")
            
            # Рассчитываем начальные ордера для сетки
            buy_orders, sell_orders = calculate_initial_orders(
                self.grid_prices, current_price, self.qty
            )
            
            logger.info(f"Выставляем начальные ордера: {len(buy_orders)} Buy, {len(sell_orders)} Sell")
            
            # Выставляем ордера и получаем их ID
            if not self.test_mode:
                for order in buy_orders + sell_orders:
                    response = self.api.place_order(
                        symbol=self.symbol,
                        side=order["side"],
                        order_type=order["order_type"],
                        qty=order["qty"],
                        price=order["price"]
                    )
                    
                    if response.get("retCode") == 0:
                        order_id = response["result"]["orderId"]
                        self.active_orders[order_id] = {
                            "symbol": self.symbol,
                            "side": order["side"],
                            "price": order["price"],
                            "qty": order["qty"],
                            "status": "New"
                        }
                        logger.info(f"Создан ордер {order['side']} {order['qty']} {self.symbol} по цене {order['price']}")
                    else:
                        logger.error(f"Ошибка при создании ордера: {response}")
            else:
                # В тестовом режиме симулируем создание ордеров
                for i, order in enumerate(buy_orders + sell_orders):
                    order_id = f"test_order_{i}"
                    self.active_orders[order_id] = {
                        "symbol": self.symbol,
                        "side": order["side"],
                        "price": order["price"],
                        "qty": order["qty"],
                        "status": "New"
                    }
                    logger.info(f"[ТЕСТ] Создан ордер {order['side']} {order['qty']} {self.symbol} по цене {order['price']}")
            
            logger.info(f"Начальные ордера выставлены: {len(self.active_orders)} активных ордеров")
            
            # Запуск WebSocket в отдельном потоке для получения обновлений ордеров
            if not self.test_mode:
                self.start_websocket()
            else:
                # В тестовом режиме симулируем обработку событий
                logger.info("Тестовый режим: WebSocket не запускается")
                
                # Симулируем исполнение нескольких ордеров
                threading.Thread(target=self.simulate_order_execution).start()
            
            logger.info(f"Grid-бот запущен для {self.symbol}")
        
        except Exception as e:
            self.is_running = False
            logger.error(f"Ошибка при запуске бота: {str(e)}")
            self.stop()
            raise
    
    def _get_current_price(self) -> float:
        """
        Получает текущую цену торговой пары
        
        Returns:
            Текущая цена
        """
        if not self.test_mode:
            try:
                ticker = self.api.get_ticker(self.symbol)
                current_price = float(ticker["result"]["list"][0]["lastPrice"])
                logger.info(f"Текущая цена {self.symbol}: {current_price}")
                return current_price
            except Exception as e:
                logger.error(f"Ошибка при получении текущей цены: {str(e)}")
                # В случае ошибки используем тестовое значение
                if self.symbol == "BTCUSDT":
                    return 103932.00
                return (self.high_price + self.low_price) / 2
        else:
            # В тестовом режиме используем текущую цену BTC/USDT со скриншота
            if self.symbol == "BTCUSDT":
                current_price = 103932.00
            else:
                # Для других пар используем среднее значение заданного диапазона
                current_price = (self.high_price + self.low_price) / 2
            
            logger.info(f"Тестовый режим: используем цену {current_price}")
            return current_price
    
    def _set_price_range_from_volatility(self, current_price: float):
        """
        Определяет диапазон цен на основе текущей цены и волатильности
        
        Args:
            current_price: Текущая цена торговой пары
        """
        # Определяем размер диапазона как процент от текущей цены
        # Для тестов используем 2% вверх и вниз от текущей цены
        range_percent = 0.02
        
        if not self.test_mode:
            try:
                # Получаем волатильность за последний день
                # Используем 24-часовую волатильность как основу для диапазона
                ticker = self.api.get_ticker(self.symbol)
                high_price_24h = float(ticker["highPrice24h"])
                low_price_24h = float(ticker["lowPrice24h"])
                
                # Волатильность как процент от средней цены
                volatility = (high_price_24h - low_price_24h) / current_price
                
                # Используем половину суточной волатильности для определения диапазона
                range_percent = max(0.005, volatility / 2)  # Минимум 0.5%
                logger.info(f"Определена волатильность: {volatility:.2%}, диапазон: {range_percent:.2%}")
            except Exception as e:
                logger.warning(f"Ошибка при определении волатильности: {str(e)}")
                # Используем стандартное значение в случае ошибки
                range_percent = 0.02
        
        # Устанавливаем диапазон цен
        self.low_price = current_price * (1 - range_percent)
        self.high_price = current_price * (1 + range_percent)
        
        # Округляем границы для более читаемых значений
        if current_price > 10000:
            self.low_price = round(self.low_price, -2)   # Округляем до сотен
            self.high_price = round(self.high_price, -2)
        elif current_price > 1000:
            self.low_price = round(self.low_price, -1)   # Округляем до десятков
            self.high_price = round(self.high_price, -1)
        elif current_price > 100:
            self.low_price = round(self.low_price, 0)    # Округляем до единиц
            self.high_price = round(self.high_price, 0)
        else:
            self.low_price = round(self.low_price, 2)    # Округляем до сотых
            self.high_price = round(self.high_price, 2)
        
        # Перестраиваем сетку цен с новыми границами
        self.grid_prices = build_grid(self.low_price, self.high_price, self.grid_levels)
    
    def start_websocket(self):
        """
        Запускает WebSocket-соединение для получения обновлений по ордерам
        """
        def on_order_update(message):
            with self.ws_lock:
                try:
                    if not message or not isinstance(message, dict):
                        return
                        
                    data = message.get("data")
                    if not data:
                        return
                    
                    # Проверяем, что это наш ордер и он исполнен
                    if (data.get("symbol") == self.symbol and 
                        data.get("orderId") in self.active_orders and
                        data.get("orderStatus") == "Filled"):
                        
                        order_id = data.get("orderId")
                        filled_order = {
                            "symbol": self.symbol,
                            "side": data.get("side"),
                            "price": data.get("price"),
                            "qty": data.get("qty"),
                            "order_id": order_id,
                            "status": "Filled"
                        }
                        
                        self.handle_order_execution(filled_order)
                except Exception as e:
                    logger.error(f"Ошибка при обработке события WebSocket: {str(e)}")
        
        # Инициализация WebSocket
        try:
            self.ws = BybitWebsocket()
            
            # Подписка на события ордеров
            self.ws.subscribe_order(on_order_update)
            logger.info("WebSocket подключен, подписка на события ордеров активирована")
        except Exception as e:
            logger.error(f"Ошибка при запуске WebSocket: {str(e)}")
    
    def simulate_order_execution(self):
        """
        Симулирует исполнение ордеров в тестовом режиме
        """
        if not self.test_mode:
            return
            
        logger.info("Запуск симуляции исполнения ордеров")
        
        # Симулируем исполнение нескольких ордеров с интервалом
        for i, (order_id, order) in enumerate(list(self.active_orders.items())):
            # Исполняем только часть ордеров для демонстрации
            if i % 2 == 0:
                time.sleep(2)  # Пауза между исполнениями
                
                with self.ws_lock:
                    # Создаем событие исполнения ордера
                    filled_order = {
                        "symbol": self.symbol,
                        "side": order["side"],
                        "price": order["price"],
                        "qty": order["qty"],
                        "order_id": order_id,
                        "status": "Filled"
                    }
                    
                    logger.info(f"[ТЕСТ] Исполнен ордер {order['side']} по цене {order['price']}")
                    
                    # Обрабатываем исполнение
                    self.handle_order_execution(filled_order)
    
    def handle_order_execution(self, filled_order: Dict[str, Any]):
        """
        Обработка исполнения ордера и создание зеркального ордера
        
        Args:
            filled_order: Данные об исполненном ордере
        """
        try:
            order_id = filled_order.get("order_id")
            
            # Проверяем, что это наш активный ордер
            if order_id not in self.active_orders:
                logger.warning(f"Получено событие для неизвестного ордера: {order_id}")
                return
            
            # Обновляем статус ордера
            self.active_orders[order_id]["status"] = "Filled"
            
            # Логируем исполнение
            side = filled_order.get("side")
            price = filled_order.get("price")
            qty = filled_order.get("qty")
            
            logger.info(f"Исполнен ордер {side} {qty} {self.symbol} по цене {price}")
            
            # Сохраняем в базу данных
            self.db.add_trade(
                symbol=self.symbol,
                side=side,
                price=float(price),
                qty=float(qty),
                order_id=order_id
            )
            
            # Рассчитываем зеркальный ордер
            mirror_order = calculate_mirror_order(
                filled_order, 
                self.grid_prices, 
                self.qty,
                [order for order in self.active_orders.values() if order["status"] == "New"]
            )
            
            # Если зеркальный ордер не создан (например, граничный уровень)
            if not mirror_order:
                logger.info(f"Зеркальный ордер для {side} по цене {price} не создан")
                return
            
            # Выставляем зеркальный ордер
            if not self.test_mode:
                response = self.api.place_order(
                    symbol=self.symbol,
                    side=mirror_order["side"],
                    order_type=mirror_order["order_type"],
                    qty=mirror_order["qty"],
                    price=mirror_order["price"]
                )
                
                if response.get("retCode") == 0:
                    new_order_id = response["result"]["orderId"]
                    self.active_orders[new_order_id] = {
                        "symbol": self.symbol,
                        "side": mirror_order["side"],
                        "price": mirror_order["price"],
                        "qty": mirror_order["qty"],
                        "status": "New"
                    }
                    logger.info(f"Создан зеркальный ордер {mirror_order['side']} {mirror_order['qty']} по цене {mirror_order['price']}")
                else:
                    logger.error(f"Ошибка при создании зеркального ордера: {response}")
            else:
                # В тестовом режиме симулируем создание зеркального ордера
                new_order_id = f"test_mirror_{order_id}"
                self.active_orders[new_order_id] = {
                    "symbol": self.symbol,
                    "side": mirror_order["side"],
                    "price": mirror_order["price"],
                    "qty": mirror_order["qty"],
                    "status": "New"
                }
                logger.info(f"[ТЕСТ] Создан зеркальный ордер {mirror_order['side']} {mirror_order['qty']} по цене {mirror_order['price']}")
        
        except Exception as e:
            logger.error(f"Ошибка при обработке исполнения ордера: {str(e)}")
    
    def stop(self):
        """
        Остановка бота и закрытие соединений
        """
        if not self.is_running:
            logger.warning("Бот уже остановлен")
            return
            
        self.is_running = False
        
        try:
            logger.info("Отменяем все активные ордера...")
            
            # Отмена активных ордеров
            if not self.test_mode:
                for order_id, order in self.active_orders.items():
                    if order["status"] == "New":
                        try:
                            self.api.cancel_order(self.symbol, order_id)
                            logger.info(f"Отменен ордер {order_id}")
                        except Exception as e:
                            logger.error(f"Ошибка при отмене ордера {order_id}: {str(e)}")
                            
                # Закрытие WebSocket
                if self.ws:
                    self.ws.close()
            else:
                logger.info("[ТЕСТ] Отмена всех ордеров и закрытие соединений")
                
            # Закрываем базу данных
            self.db.close()
            
            logger.info("Ресурсы успешно очищены, бот завершил работу")
        
        except Exception as e:
            logger.error(f"Ошибка при остановке бота: {str(e)}")
    
    def get_active_orders_count(self) -> int:
        """
        Получает количество активных ордеров
        
        Returns:
            Количество активных ордеров
        """
        return sum(1 for order in self.active_orders.values() if order["status"] == "New")
    
    def get_filled_orders_count(self) -> int:
        """
        Получает количество исполненных ордеров
        
        Returns:
            Количество исполненных ордеров
        """
        return sum(1 for order in self.active_orders.values() if order["status"] == "Filled")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получает текущую статистику бота
        
        Returns:
            Статистика работы бота
        """
        active_count = self.get_active_orders_count()
        filled_count = self.get_filled_orders_count()
        
        # Получаем статистику из БД
        trades = self.db.get_trades(self.symbol)
        
        buy_volume = sum(trade["qty"] for trade in trades if trade["side"] == "Buy")
        sell_volume = sum(trade["qty"] for trade in trades if trade["side"] == "Sell")
        
        # Расчет примерной прибыли (не учитывает комиссии)
        total_spent = sum(trade["price"] * trade["qty"] for trade in trades if trade["side"] == "Buy")
        total_earned = sum(trade["price"] * trade["qty"] for trade in trades if trade["side"] == "Sell")
        
        return {
            "symbol": self.symbol,
            "active_orders": active_count,
            "filled_orders": filled_count,
            "buy_volume": buy_volume,
            "sell_volume": sell_volume,
            "estimated_profit": total_earned - total_spent
        }

def signal_handler(sig, frame):
    """
    Обработчик сигналов для корректного завершения
    """
    global bot
    logger.info("Получен сигнал остановки. Останавливаем бота...")
    if bot:
        bot.stop()
    sys.exit(0)

if __name__ == "__main__":
    # Настройка обработчика сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Глобальная переменная для доступа из обработчика сигналов
    bot = None
    
    # Парсинг аргументов командной строки
    parser = argparse.ArgumentParser(description='Grid-бот для торговли на Bybit')
    parser.add_argument('--symbol', required=True, help='Торговая пара (например, BTCUSDT)')
    parser.add_argument('--low', type=float, default=0, help='Нижняя граница сетки (опционально, определяется автоматически)')
    parser.add_argument('--high', type=float, default=0, help='Верхняя граница сетки (опционально, определяется автоматически)')
    parser.add_argument('--grids', required=True, type=int, help='Количество уровней в сетке')
    parser.add_argument('--qty', required=True, type=float, help='Количество базовой валюты для каждого ордера')
    parser.add_argument('--test', action='store_true', help='Запуск в тестовом режиме без доступа к API')
    
    args = parser.parse_args()
    
    # Проверка параметров
    if args.low != 0 and args.high != 0 and args.low >= args.high:
        logger.error("Нижняя граница должна быть меньше верхней границы")
        sys.exit(1)
        
    if args.grids < 2:
        logger.error("Количество сеток должно быть не менее 2")
        sys.exit(1)
        
    if args.qty <= 0:
        logger.error("Количество должно быть положительным числом")
        sys.exit(1)
    
    # Инициализация и запуск бота
    bot = GridBot(
        symbol=args.symbol,
        low_price=args.low,
        high_price=args.high,
        grid_levels=args.grids,
        qty=args.qty,
        test_mode=args.test
    )
    
    logger.info(f"Запуск Grid-бота для {args.symbol}")
    logger.info(f"Параметры: нижняя граница={args.low}, верхняя граница={args.high}, уровней={args.grids}, количество={args.qty}")
    if args.test:
        logger.info("Режим: ТЕСТОВЫЙ (без доступа к API)")
    
    try:
        bot.start()
        
        # Основной цикл для вывода статистики
        while bot.is_running:
            time.sleep(60)  # Обновление каждую минуту
            
            stats = bot.get_stats()
            logger.info(f"Статистика: активных ордеров={stats['active_orders']}, "
                      f"исполнено={stats['filled_orders']}, "
                      f"объем покупок={stats['buy_volume']:.6f}, "
                      f"объем продаж={stats['sell_volume']:.6f}, "
                      f"ориентировочная прибыль={stats['estimated_profit']:.6f}")
    
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
        bot.stop()
    
    except Exception as e:
        logger.error(f"Необработанная ошибка: {str(e)}")
        if bot:
            bot.stop()
        sys.exit(1) 