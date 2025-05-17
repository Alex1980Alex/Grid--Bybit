"""
Модуль для безопасной записи в БД SQLite из разных потоков через очередь
"""
import sqlite3
import queue
import threading
import atexit
import pathlib
import logging
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List, Union

from config import DB_PATH

# Настройка логгера
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("db_writer")

# Очередь для хранения SQL-запросов и их параметров
queue_events: queue.Queue[Tuple[str, Tuple]] = queue.Queue()
_STOP = object()  # Сигнал для остановки потока

def _writer(db_path: str) -> None:
    """
    Функция потока для записи в базу данных
    
    Args:
        db_path: Путь к файлу базы данных
    """
    # Создаем директорию для БД, если нужно
    db_dir = pathlib.Path(db_path).parent
    if not db_dir.exists():
        db_dir.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(db_path, check_same_thread=True)
    conn.row_factory = sqlite3.Row
    
    # Создаем таблицы, если их еще нет
    _create_tables(conn)
    
    logger.info(f"Запущен поток записи в БД: {db_path}")
    
    while True:
        task = queue_events.get()
        if task is _STOP:
            break
        
        try:
            sql, params = task
            cur = conn.cursor()
            cur.execute(sql, params)
            conn.commit()
            logger.debug(f"Выполнен SQL-запрос: {sql[:50]}...")
        except Exception as e:
            logger.error(f"Ошибка при выполнении SQL-запроса: {str(e)}")
        finally:
            queue_events.task_done()
    
    conn.close()
    logger.info("Поток записи в БД остановлен")

def _create_tables(conn: sqlite3.Connection) -> None:
    """
    Создает необходимые таблицы в базе данных, если они не существуют
    
    Args:
        conn: Соединение с базой данных
    """
    cursor = conn.cursor()
    
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
    
    conn.commit()
    logger.info("Таблицы базы данных созданы/проверены")

# Запускаем поток-писатель как daemon
writer_thread = threading.Thread(target=_writer, args=(DB_PATH,), daemon=True)
writer_thread.start()

# ---- Функции для других модулей ----

def add_trade(symbol: str, side: str, price: float, qty: float, order_id: str) -> None:
    """
    Асинхронно добавляет запись о сделке в очередь
    
    Args:
        symbol: Символ торговой пары
        side: Сторона сделки (Buy/Sell)
        price: Цена исполнения
        qty: Количество
        order_id: ID ордера
    """
    now = datetime.now().isoformat()
    timestamp = int(datetime.now().timestamp() * 1000)
    
    queue_events.put((
        '''
        INSERT INTO fills (
            order_id, symbol, side, price, qty, timestamp, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''',
        (order_id, symbol, side, price, qty, timestamp, now)
    ))
    
    logger.info(f"Добавлена сделка в очередь: {symbol} {side} по цене {price}")

def record_active_order(order_data: Dict[str, Any], grid_level: Optional[int] = None) -> None:
    """
    Асинхронно записывает информацию об активном ордере в базу данных
    
    Args:
        order_data: Данные об ордере
        grid_level: Уровень сетки, на котором находится ордер
    """
    now = datetime.now().isoformat()
    
    queue_events.put((
        '''
        INSERT OR REPLACE INTO active_orders (
            order_id, order_link_id, symbol, side, price, qty, grid_level, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            order_data.get('orderId', ''),
            order_data.get('orderLinkId', ''),
            order_data.get('symbol', ''),
            order_data.get('side', ''),
            float(order_data.get('price', 0)),
            float(order_data.get('qty', 0)),
            grid_level,
            now
        )
    ))
    
    logger.debug(f"Записан активный ордер: {order_data.get('symbol')} {order_data.get('side')} {order_data.get('price')}")

def remove_active_order(order_id: str) -> None:
    """
    Асинхронно удаляет активный ордер из базы данных по его ID
    
    Args:
        order_id: ID ордера для удаления
    """
    queue_events.put((
        'DELETE FROM active_orders WHERE order_id = ?',
        (order_id,)
    ))
    
    logger.debug(f"Удален активный ордер с ID: {order_id}")

def log_event(event_type: str, message: str, symbol: Optional[str] = None, details: Optional[str] = None) -> None:
    """
    Асинхронно записывает лог события работы бота
    
    Args:
        event_type: Тип события (order, trade, grid, error и т.д.)
        message: Описание события
        symbol: Символ торговой пары (опционально)
        details: Дополнительные детали в формате JSON (опционально)
    """
    if not details:
        details = "{}"
        
    now = datetime.now().isoformat()
    timestamp = int(datetime.now().timestamp() * 1000)
    
    queue_events.put((
        '''
        INSERT INTO bot_logs (
            event_type, symbol, message, details, timestamp, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ''',
        (event_type, symbol, message, details, timestamp, now)
    ))
    
    logger.debug(f"Записан лог: {event_type} - {message}")

def get_trades(symbol: str) -> List[Dict[str, Any]]:
    """
    Получает список всех сделок для указанного символа
    Примечание: для чтения данных создаем отдельное соединение
    
    Args:
        symbol: Символ торговой пары
            
    Returns:
        Список сделок
    """
    # Для чтения используем отдельное соединение
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT * FROM fills WHERE symbol = ? ORDER BY timestamp DESC', (symbol,))
        rows = cursor.fetchall()
        result = [dict(row) for row in rows]
    finally:
        conn.close()
    
    return result

def get_active_orders(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Получает список активных ордеров из базы данных
    Примечание: для чтения данных создаем отдельное соединение
    
    Args:
        symbol: Фильтр по символу (опционально)
            
    Returns:
        Список активных ордеров
    """
    # Для чтения используем отдельное соединение
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        if symbol:
            cursor.execute('SELECT * FROM active_orders WHERE symbol = ?', (symbol,))
        else:
            cursor.execute('SELECT * FROM active_orders')
        
        rows = cursor.fetchall()
        result = [dict(row) for row in rows]
    finally:
        conn.close()
    
    return result

def get_profit_stats(symbol: str) -> Dict[str, Any]:
    """
    Вычисляет статистику прибыли на основе записанных сделок
    Примечание: для чтения данных создаем отдельное соединение
    
    Args:
        symbol: Символ торговой пары
            
    Returns:
        Словарь со статистикой прибыли
    """
    # Для чтения используем отдельное соединение
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
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
    finally:
        conn.close()

def shutdown_writer() -> None:
    """Функция для корректного завершения при exit."""
    queue_events.put(_STOP)
    logger.info("Отправлен сигнал остановки для потока записи в БД")

# Регистрируем функцию для корректного завершения
atexit.register(shutdown_writer) 