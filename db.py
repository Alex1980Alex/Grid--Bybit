"""
Модуль для работы с базой данных SQLite
"""
import sqlite3
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import os

from config import DB_PATH

# Настройка логгера
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("db")

class GridBotDB:
    """Класс для работы с базой данных SQLite для хранения сделок и логов бота"""
    
    def __init__(self, db_path: str = DB_PATH):
        """
        Инициализирует соединение с базой данных и создает таблицы, если они не существуют
        
        Args:
            db_path: Путь к файлу базы данных
        """
        self.db_path = db_path
        
        # Проверяем, существует ли директория для базы данных
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
        
        # Создаем соединение и таблицы
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()
        
        logger.info(f"Инициализирована база данных: {db_path}")
    
    def create_tables(self):
        """Создает необходимые таблицы в базе данных, если они не существуют"""
        cursor = self.conn.cursor()
        
        # Таблица для хранения сделок (fills)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS fills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                order_link_id TEXT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                qty REAL NOT NULL,
                fee REAL,
                fee_currency TEXT,
                timestamp INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        ''')
        
        # Таблица для хранения активных ордеров
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS active_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL UNIQUE,
                order_link_id TEXT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                qty REAL NOT NULL,
                grid_level INTEGER,
                created_at TEXT NOT NULL
            )
        ''')
        
        # Таблица для хранения логов работы бота
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bot_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                symbol TEXT,
                message TEXT NOT NULL,
                details TEXT,
                timestamp INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        ''')
        
        self.conn.commit()
        logger.info("Таблицы базы данных созданы/проверены")
    
    def close(self):
        """Закрывает соединение с базой данных"""
        if self.conn:
            self.conn.close()
            logger.info("Соединение с базой данных закрыто")
    
    def record_fill(self, order_data: Dict[str, Any]):
        """
        Записывает информацию о заполненном ордере (сделке) в базу данных
        
        Args:
            order_data: Данные о заполненном ордере из API Bybit
        """
        cursor = self.conn.cursor()
        
        now = datetime.now().isoformat()
        timestamp = int(datetime.now().timestamp() * 1000)
        
        cursor.execute('''
            INSERT INTO fills (
                order_id, order_link_id, symbol, side, price, qty, 
                fee, fee_currency, timestamp, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            order_data.get('orderId', ''),
            order_data.get('orderLinkId', ''),
            order_data.get('symbol', ''),
            order_data.get('side', ''),
            float(order_data.get('price', 0)),
            float(order_data.get('qty', 0)),
            float(order_data.get('fee', 0)),
            order_data.get('feeCurrency', ''),
            order_data.get('timestamp', timestamp),
            now
        ))
        
        self.conn.commit()
        logger.info(f"Записана сделка в БД: {order_data.get('symbol')} {order_data.get('side')} {order_data.get('price')}")
    
    def add_trade(self, symbol: str, side: str, price: float, qty: float, order_id: str):
        """
        Добавляет запись о сделке в базу данных
        
        Args:
            symbol: Символ торговой пары
            side: Сторона сделки (Buy/Sell)
            price: Цена исполнения
            qty: Количество
            order_id: ID ордера
        """
        cursor = self.conn.cursor()
        
        now = datetime.now().isoformat()
        timestamp = int(datetime.now().timestamp() * 1000)
        
        cursor.execute('''
            INSERT INTO fills (
                order_id, symbol, side, price, qty, timestamp, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            order_id,
            symbol,
            side,
            price,
            qty,
            timestamp,
            now
        ))
        
        self.conn.commit()
        logger.info(f"Добавлена сделка: {symbol} {side} по цене {price}")
    
    def get_trades(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Получает список всех сделок для указанного символа
        
        Args:
            symbol: Символ торговой пары
            
        Returns:
            Список сделок
        """
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM fills WHERE symbol = ? ORDER BY timestamp DESC', (symbol,))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    
    def record_active_order(self, order_data: Dict[str, Any], grid_level: Optional[int] = None):
        """
        Записывает информацию об активном ордере в базу данных
        
        Args:
            order_data: Данные об ордере из API Bybit
            grid_level: Уровень сетки, на котором находится ордер
        """
        cursor = self.conn.cursor()
        
        now = datetime.now().isoformat()
        
        cursor.execute('''
            INSERT OR REPLACE INTO active_orders (
                order_id, order_link_id, symbol, side, price, qty, grid_level, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            order_data.get('orderId', ''),
            order_data.get('orderLinkId', ''),
            order_data.get('symbol', ''),
            order_data.get('side', ''),
            float(order_data.get('price', 0)),
            float(order_data.get('qty', 0)),
            grid_level,
            now
        ))
        
        self.conn.commit()
        logger.debug(f"Записан активный ордер: {order_data.get('symbol')} {order_data.get('side')} {order_data.get('price')}")
    
    def remove_active_order(self, order_id: str):
        """
        Удаляет активный ордер из базы данных по его ID
        
        Args:
            order_id: ID ордера для удаления
        """
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM active_orders WHERE order_id = ?', (order_id,))
        self.conn.commit()
        logger.debug(f"Удален активный ордер с ID: {order_id}")
    
    def get_active_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Получает список активных ордеров из базы данных
        
        Args:
            symbol: Фильтр по символу (опционально)
            
        Returns:
            Список активных ордеров
        """
        cursor = self.conn.cursor()
        
        if symbol:
            cursor.execute('SELECT * FROM active_orders WHERE symbol = ?', (symbol,))
        else:
            cursor.execute('SELECT * FROM active_orders')
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    
    def log_event(self, event_type: str, message: str, symbol: Optional[str] = None, details: Optional[str] = None):
        """
        Записывает лог события работы бота
        
        Args:
            event_type: Тип события (order, trade, grid, error и т.д.)
            message: Описание события
            symbol: Символ торговой пары (опционально)
            details: Дополнительные детали в формате JSON (опционально)
        """
        if not details:
            details = "{}"
            
        cursor = self.conn.cursor()
        
        now = datetime.now().isoformat()
        timestamp = int(datetime.now().timestamp() * 1000)
        
        cursor.execute('''
            INSERT INTO bot_logs (
                event_type, symbol, message, details, timestamp, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            event_type,
            symbol,
            message,
            details,
            timestamp,
            now
        ))
        
        self.conn.commit()
        logger.debug(f"Записан лог: {event_type} - {message}")
    
    def get_profit_stats(self, symbol: str) -> Dict[str, Any]:
        """
        Вычисляет статистику прибыли на основе записанных сделок
        
        Args:
            symbol: Символ торговой пары
            
        Returns:
            Словарь со статистикой прибыли
        """
        cursor = self.conn.cursor()
        
        # Получаем общее количество сделок
        cursor.execute('SELECT COUNT(*) as total_fills FROM fills WHERE symbol = ?', (symbol,))
        total_fills = cursor.fetchone()['total_fills']
        
        # Получаем количество покупок и продаж
        cursor.execute('SELECT COUNT(*) as buy_count FROM fills WHERE symbol = ? AND side = "Buy"', (symbol,))
        buy_count = cursor.fetchone()['buy_count']
        
        cursor.execute('SELECT COUNT(*) as sell_count FROM fills WHERE symbol = ? AND side = "Sell"', (symbol,))
        sell_count = cursor.fetchone()['sell_count']
        
        # Вычисляем среднюю цену покупки и продажи
        cursor.execute('''
            SELECT AVG(price) as avg_buy_price
            FROM fills
            WHERE symbol = ? AND side = "Buy"
        ''', (symbol,))
        avg_buy_price = cursor.fetchone()['avg_buy_price'] or 0
        
        cursor.execute('''
            SELECT AVG(price) as avg_sell_price
            FROM fills
            WHERE symbol = ? AND side = "Sell"
        ''', (symbol,))
        avg_sell_price = cursor.fetchone()['avg_sell_price'] or 0
        
        # Вычисляем общее количество купленных и проданных монет
        cursor.execute('''
            SELECT SUM(qty) as total_buy_qty
            FROM fills
            WHERE symbol = ? AND side = "Buy"
        ''', (symbol,))
        total_buy_qty = cursor.fetchone()['total_buy_qty'] or 0
        
        cursor.execute('''
            SELECT SUM(qty) as total_sell_qty
            FROM fills
            WHERE symbol = ? AND side = "Sell"
        ''', (symbol,))
        total_sell_qty = cursor.fetchone()['total_sell_qty'] or 0
        
        # Вычисляем общую сумму потраченную на покупки и полученную от продаж
        cursor.execute('''
            SELECT SUM(price * qty) as total_spent
            FROM fills
            WHERE symbol = ? AND side = "Buy"
        ''', (symbol,))
        total_spent = cursor.fetchone()['total_spent'] or 0
        
        cursor.execute('''
            SELECT SUM(price * qty) as total_earned
            FROM fills
            WHERE symbol = ? AND side = "Sell"
        ''', (symbol,))
        total_earned = cursor.fetchone()['total_earned'] or 0
        
        # Вычисляем общие комиссии
        cursor.execute('''
            SELECT SUM(fee) as total_fees
            FROM fills
            WHERE symbol = ?
        ''', (symbol,))
        total_fees = cursor.fetchone()['total_fees'] or 0
        
        # Вычисляем приблизительную прибыль
        # Формула: (доход от продаж - затраты на покупки - комиссии)
        estimated_profit = total_earned - total_spent - total_fees
        
        return {
            "symbol": symbol,
            "total_fills": total_fills,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "avg_buy_price": avg_buy_price,
            "avg_sell_price": avg_sell_price,
            "total_buy_qty": total_buy_qty,
            "total_sell_qty": total_sell_qty,
            "total_spent": total_spent,
            "total_earned": total_earned,
            "total_fees": total_fees,
            "estimated_profit": estimated_profit
        } 