"""
Grid-бот для торговли на споте биржи Bybit
"""
import os
import sys
import json
import signal
import asyncio
import logging
import argparse
from typing import Dict, List, Any, Optional
from decimal import Decimal
import numpy as np
import pandas as pd
from dotenv import load_dotenv

from bybit_api import BybitAPI
from ws_client import BybitWebsocket
from grid import build_grid, calculate_initial_orders, calculate_mirror_order, find_grid_level
from db import GridBotDB

# Настройка логгера
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("grid_bot.log")
    ]
)
logger = logging.getLogger("grid_bot")

class GridBot:
    """Класс реализации Grid-бота для торговли на споте Bybit"""
    
    def __init__(
        self,
        symbol: str,
        low: float,
        high: float,
        grids: int,
        qty: float
    ):
        """
        Инициализирует Grid-бота
        
        Args:
            symbol: Торговая пара (например, 'BTCUSDT')
            low: Нижняя граница сетки
            high: Верхняя граница сетки
            grids: Количество уровней в сетке
            qty: Количество базовой валюты для каждого ордера
        """
        # Загружаем переменные окружения
        load_dotenv()
        
        api_key = os.getenv("BYBIT_API_KEY")
        api_secret = os.getenv("BYBIT_API_SECRET")
        
        if not api_key or not api_secret:
            raise ValueError("API ключи не найдены. Создайте файл .env с BYBIT_API_KEY и BYBIT_API_SECRET")
        
        # Инициализируем параметры бота
        self.symbol = symbol
        self.low = low
        self.high = high
        self.grids = grids
        self.qty = qty
        
        # Инициализируем клиенты API
        self.api = BybitAPI(api_key, api_secret)
        self.ws = BybitWebsocket(api_key, api_secret)
        self.db = GridBotDB()
        
        # Инициализируем переменные для работы бота
        self.grid_prices = None
        self.active_orders = {}
        self.is_running = False
        self.shutdown_event = asyncio.Event()
        
        logger.info(f"Инициализирован Grid-бот для {symbol} с {grids} уровнями: от {low} до {high}")
    
    async def initialize(self):
        """Инициализирует бота: получает рыночные данные, создает сетку и выставляет начальные ордера"""
        try:
            # Получаем текущую цену
            ticker = self.api.get_ticker(self.symbol)
            current_price = float(ticker["lastPrice"])
            
            logger.info(f"Текущая цена {self.symbol}: {current_price}")
            
            # Создаем сетку цен
            self.grid_prices = build_grid(self.low, self.high, self.grids)
            
            # Проверяем, находится ли текущая цена в пределах сетки
            if current_price < self.low or current_price > self.high:
                logger.warning(f"Текущая цена {current_price} находится вне границ сетки [{self.low}, {self.high}]")
                proceed = input("Продолжить? (y/n): ").lower()
                if proceed != 'y':
                    logger.info("Инициализация бота отменена пользователем")
                    return False
            
            # Рассчитываем начальные ордера
            buy_orders, sell_orders = calculate_initial_orders(
                self.grid_prices, current_price, self.qty
            )
            
            # Выставляем начальные ордера
            await self._place_initial_orders(buy_orders, sell_orders)
            
            # Регистрируем обработчик событий ордеров
            self.ws.add_handler("order", self._handle_order_event)
            
            return True
        
        except Exception as e:
            logger.error(f"Ошибка при инициализации бота: {str(e)}")
            return False
    
    async def _place_initial_orders(self, buy_orders: List[Dict[str, Any]], sell_orders: List[Dict[str, Any]]):
        """
        Выставляет начальные ордера на покупку и продажу
        
        Args:
            buy_orders: Список ордеров на покупку
            sell_orders: Список ордеров на продажу
        """
        logger.info(f"Выставляем начальные ордера: {len(buy_orders)} Buy, {len(sell_orders)} Sell")
        
        for order in buy_orders + sell_orders:
            try:
                response = self.api.place_order(
                    symbol=self.symbol,
                    side=order["side"],
                    order_type=order["order_type"],
                    qty=order["qty"],
                    price=order["price"],
                )
                
                order_id = response.get("orderId")
                if order_id:
                    # Сохраняем информацию об ордере
                    self.active_orders[order_id] = {
                        "orderId": order_id,
                        "symbol": self.symbol,
                        "side": order["side"],
                        "price": order["price"],
                        "qty": order["qty"],
                    }
                    
                    # Сохраняем в БД
                    grid_level = find_grid_level(float(order["price"]), self.grid_prices)
                    self.db.record_active_order(self.active_orders[order_id], grid_level)
                    
                    # Логируем
                    self.db.log_event(
                        "order", 
                        f"Выставлен ордер {order['side']} по цене {order['price']}", 
                        self.symbol
                    )
                    
                    # Небольшая пауза между размещением ордеров, чтобы не перегружать API
                    await asyncio.sleep(0.2)
                
            except Exception as e:
                logger.error(f"Ошибка при выставлении начального ордера {order['side']} {order['price']}: {str(e)}")
        
        logger.info(f"Начальные ордера выставлены: {len(self.active_orders)} активных ордеров")
    
    async def _handle_order_event(self, data: Dict[str, Any]):
        """
        Обработчик события ордера из WebSocket
        
        Args:
            data: Данные о событии ордера
        """
        # Обрабатываем массив данных
        if isinstance(data, list):
            for order_data in data:
                await self._process_order_update(order_data)
        # Обрабатываем одиночное событие
        else:
            await self._process_order_update(data)
    
    async def _process_order_update(self, order_data: Dict[str, Any]):
        """
        Обрабатывает обновление статуса ордера
        
        Args:
            order_data: Данные об обновлении ордера
        """
        try:
            order_id = order_data.get("orderId")
            order_status = order_data.get("orderStatus")
            
            if not order_id or not order_status:
                return
            
            # Если ордер был исполнен (Filled)
            if order_status == "Filled":
                logger.info(f"Ордер {order_id} исполнен: {order_data.get('side')} по цене {order_data.get('price')}")
                
                # Записываем сделку в БД
                self.db.record_fill(order_data)
                
                # Удаляем ордер из активных
                if order_id in self.active_orders:
                    del self.active_orders[order_id]
                
                # Удаляем запись из таблицы активных ордеров в БД
                self.db.remove_active_order(order_id)
                
                # Создаем зеркальный ордер
                mirror_order = calculate_mirror_order(order_data, self.grid_prices, self.qty)
                
                if mirror_order:
                    # Выставляем зеркальный ордер
                    response = self.api.place_order(
                        symbol=self.symbol,
                        side=mirror_order["side"],
                        order_type=mirror_order["order_type"],
                        qty=mirror_order["qty"],
                        price=mirror_order["price"],
                    )
                    
                    new_order_id = response.get("orderId")
                    if new_order_id:
                        # Сохраняем информацию о новом ордере
                        self.active_orders[new_order_id] = {
                            "orderId": new_order_id,
                            "symbol": self.symbol,
                            "side": mirror_order["side"],
                            "price": mirror_order["price"],
                            "qty": mirror_order["qty"],
                        }
                        
                        # Сохраняем в БД
                        grid_level = find_grid_level(float(mirror_order["price"]), self.grid_prices)
                        self.db.record_active_order(self.active_orders[new_order_id], grid_level)
                        
                        # Логируем
                        self.db.log_event(
                            "order", 
                            f"Выставлен зеркальный ордер {mirror_order['side']} по цене {mirror_order['price']}", 
                            self.symbol
                        )
        
        except Exception as e:
            logger.error(f"Ошибка при обработке обновления ордера: {str(e)}")
    
    async def start(self):
        """Запускает Grid-бота"""
        try:
            # Инициализируем бота
            initialized = await self.initialize()
            if not initialized:
                logger.error("Не удалось инициализировать бота")
                return
            
            self.is_running = True
            logger.info(f"Grid-бот запущен для {self.symbol}")
            
            # Устанавливаем обработчики сигналов для корректного завершения
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop = asyncio.get_running_loop()
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
            
            # Подключаемся к WebSocket
            connect_task = asyncio.create_task(self.ws.connect())
            await connect_task
            
            # Запускаем прослушивание WebSocket
            listen_task = asyncio.create_task(self.ws.listen())
            
            # Ожидаем сигнала завершения
            await self.shutdown_event.wait()
            
            # Отменяем задачи
            listen_task.cancel()
            
        except Exception as e:
            logger.error(f"Ошибка при запуске бота: {str(e)}")
        finally:
            # Завершаем работу бота
            await self.cleanup()
    
    async def shutdown(self):
        """Корректно завершает работу бота"""
        if not self.is_running:
            return
        
        logger.info("Получен сигнал завершения работы бота")
        self.is_running = False
        self.shutdown_event.set()
    
    async def cleanup(self):
        """Очищает ресурсы при завершении работы бота"""
        try:
            logger.info("Отменяем все активные ордера...")
            
            # Отменяем все активные ордера
            self.api.cancel_all_orders(self.symbol)
            
            # Закрываем WebSocket соединение
            await self.ws.close()
            
            # Закрываем соединение с БД
            self.db.close()
            
            logger.info("Ресурсы успешно очищены, бот завершил работу")
            
        except Exception as e:
            logger.error(f"Ошибка при очистке ресурсов: {str(e)}")


async def main():
    """Основная функция для запуска Grid-бота"""
    # Разбор аргументов командной строки
    parser = argparse.ArgumentParser(description="Grid-бот для торговли на Bybit")
    parser.add_argument("--symbol", required=True, help="Торговая пара (например, BTCUSDT)")
    parser.add_argument("--low", type=float, required=True, help="Нижняя граница сетки")
    parser.add_argument("--high", type=float, required=True, help="Верхняя граница сетки")
    parser.add_argument("--grids", type=int, required=True, help="Количество уровней в сетке")
    parser.add_argument("--qty", type=float, required=True, help="Количество базовой валюты для каждого ордера")
    
    args = parser.parse_args()
    
    # Создаем и запускаем бота
    bot = GridBot(
        symbol=args.symbol,
        low=args.low,
        high=args.high,
        grids=args.grids,
        qty=args.qty
    )
    
    await bot.start()


if __name__ == "__main__":
    asyncio.run(main()) 