"""
Модуль для расчёта и построения сетки цен для Grid-бота
"""
import logging
import numpy as np
from typing import List, Dict, Any, Tuple, Optional

# Настройка логгера
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("grid")

def build_grid(low: float, high: float, grids: int) -> np.ndarray:
    """
    Создаёт равномерную сетку цен между минимальной и максимальной ценой
    
    Args:
        low: Нижняя граница сетки
        high: Верхняя граница сетки
        grids: Количество ценовых уровней в сетке
        
    Returns:
        Массив цен сетки от низкой к высокой
    """
    if low >= high:
        raise ValueError("Нижняя граница должна быть меньше верхней границы")
    
    if grids < 2:
        raise ValueError("Количество сеток должно быть не менее 2")
    
    # Создаём равномерную сетку с grids+1 уровнями (grids разрывов между уровнями)
    # Это даст нам именно grids торговых уровней (линий)
    grid_prices = np.linspace(low, high, grids + 1)
    
    # Округляем цены до соответствующей точности в зависимости от диапазона
    price_range = high - low
    
    if price_range > 10000:
        # Если диапазон большой, округляем до целых чисел
        grid_prices = np.round(grid_prices, 0)
    elif price_range > 1000:
        # Округляем до 1 знака после запятой
        grid_prices = np.round(grid_prices, 1)
    elif price_range > 100:
        # Округляем до 2 знаков после запятой
        grid_prices = np.round(grid_prices, 2)
    else:
        # Округляем до 4 знаков после запятой
        grid_prices = np.round(grid_prices, 4)
    
    logger.info(f"Построена сетка с {len(grid_prices)} ценовыми уровнями: от {grid_prices[0]} до {grid_prices[-1]}")
    return grid_prices

def calculate_initial_orders(grid_prices: np.ndarray, mid_price: float, qty: float) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Рассчитывает начальные ордера для сетки на основе текущей рыночной цены
    
    Args:
        grid_prices: Массив цен сетки
        mid_price: Текущая рыночная цена
        qty: Количество базовой валюты для каждого ордера
        
    Returns:
        Кортеж из (buy_orders, sell_orders)
    """
    buy_orders = []
    sell_orders = []
    
    for price in grid_prices:
        order = {
            "price": str(price),
            "qty": str(qty),
            "order_type": "Limit",
        }
        
        if price < mid_price:
            order["side"] = "Buy"
            buy_orders.append(order)
        elif price > mid_price:
            order["side"] = "Sell"
            sell_orders.append(order)
        # Если цена равна mid_price, не создаём ордер на этом уровне
    
    logger.info(f"Рассчитаны начальные ордера: {len(buy_orders)} Buy, {len(sell_orders)} Sell")
    return buy_orders, sell_orders

def calculate_mirror_order(filled_order: Dict[str, Any], grid_prices: np.ndarray, qty: float, active_orders: List[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Создаёт зеркальный ордер для заполненного ордера на соседнем уровне
    
    Args:
        filled_order: Информация о заполненном ордере
        grid_prices: Массив цен сетки
        qty: Количество базовой валюты для каждого ордера
        active_orders: Список активных ордеров для проверки на конфликты
        
    Returns:
        Данные для создания зеркального ордера или None, если не удалось создать
    """
    try:
        # Получаем цену и сторону исполненного ордера
        price = float(filled_order["price"])
        side = filled_order["side"]
        
        # Находим индекс ближайшей цены в сетке
        idx = np.abs(grid_prices - price).argmin()
        
        # Определяем зеркальную сторону и новую цену
        if side == "Buy":
            # Если был исполнен ордер на покупку, выставляем ордер на продажу на уровень выше
            mirror_side = "Sell"
            idx_new = idx + 1
        else:
            # Если был исполнен ордер на продажу, выставляем ордер на покупку на уровень ниже
            mirror_side = "Buy"
            idx_new = idx - 1
        
        # Проверяем, что индекс в пределах массива
        if idx_new < 0 or idx_new >= len(grid_prices):
            logger.warning(f"Невозможно создать зеркальный ордер: выход за границы сетки")
            return None
        
        mirror_price = grid_prices[idx_new]
        
        # Проверяем, нет ли уже активного ордера на этом уровне
        if active_orders:
            for order in active_orders:
                if (float(order.get("price", 0)) == mirror_price and 
                    order.get("side") == mirror_side):
                    logger.warning(f"На уровне {mirror_price} уже существует активный ордер {mirror_side}")
                    return None
        
        mirror_order = {
            "side": mirror_side,
            "price": str(mirror_price),
            "qty": str(qty),
            "order_type": "Limit",
        }
        
        logger.info(f"Создан зеркальный ордер: {mirror_side} по цене {mirror_price}")
        return mirror_order
    
    except Exception as e:
        logger.error(f"Ошибка при создании зеркального ордера: {str(e)}")
        return None

def find_grid_level(price: float, grid_prices: np.ndarray) -> int:
    """
    Находит ближайший уровень сетки для заданной цены
    
    Args:
        price: Цена для поиска
        grid_prices: Массив цен сетки
        
    Returns:
        Индекс ближайшего уровня сетки
    """
    return np.abs(grid_prices - price).argmin() 