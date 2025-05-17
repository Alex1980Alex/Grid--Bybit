"""
Тесты для модуля grid.py
"""
import pytest
import numpy as np
from grid import build_grid, calculate_initial_orders, calculate_mirror_order, find_grid_level

class TestGridCalculation:
    """Тесты для функций расчета сеток"""
    
    def test_build_grid(self):
        """Тест построения сетки цен"""
        # Тест равномерной сетки
        low_price = 1000
        high_price = 2000
        num_grids = 5
        
        grid = build_grid(low_price, high_price, num_grids)
        
        assert len(grid) == num_grids + 1
        assert grid[0] == low_price
        assert grid[-1] == high_price
        assert np.allclose(grid, np.array([1000, 1200, 1400, 1600, 1800, 2000]))
        
        # Тест с некорректными параметрами
        with pytest.raises(ValueError):
            build_grid(2000, 1000, 5)  # low_price > high_price
            
        with pytest.raises(ValueError):
            build_grid(1000, 2000, 1)  # num_grids < 2
    
    def test_calculate_initial_orders(self):
        """Тест расчета начальных ордеров"""
        grid_prices = np.array([1000, 1200, 1400, 1600, 1800, 2000])
        current_price = 1500
        qty = 0.01
        
        buy_orders, sell_orders = calculate_initial_orders(grid_prices, current_price, qty)
        
        # Проверяем, что ордера на покупку имеют цены ниже текущей
        assert all(float(order["price"]) < current_price for order in buy_orders)
        
        # Проверяем, что ордера на продажу имеют цены выше текущей
        assert all(float(order["price"]) > current_price for order in sell_orders)
        
        # Проверяем количество ордеров
        assert len(buy_orders) + len(sell_orders) == len(grid_prices) - 1
    
    def test_calculate_mirror_order(self):
        """Тест создания зеркального ордера"""
        grid_prices = np.array([1000, 1200, 1400, 1600, 1800, 2000])
        qty = 0.01
        
        # Тест создания зеркального ордера для Buy
        filled_buy_order = {
            "side": "Buy",
            "price": "1200",
            "qty": "0.01",
        }
        
        mirror_order = calculate_mirror_order(filled_buy_order, grid_prices, qty)
        
        assert mirror_order is not None
        assert mirror_order["side"] == "Sell"
        assert float(mirror_order["price"]) == 1400
        
        # Тест создания зеркального ордера для Sell
        filled_sell_order = {
            "side": "Sell",
            "price": "1600",
            "qty": "0.01",
        }
        
        mirror_order = calculate_mirror_order(filled_sell_order, grid_prices, qty)
        
        assert mirror_order is not None
        assert mirror_order["side"] == "Buy"
        assert float(mirror_order["price"]) == 1400
        
        # Тест для ордера на границе сетки
        boundary_order = {
            "side": "Sell",
            "price": "2000",
            "qty": "0.01",
        }
        
        mirror_order = calculate_mirror_order(boundary_order, grid_prices, qty)
        assert mirror_order is None
    
    def test_find_grid_level(self):
        """Тест поиска уровня сетки для заданной цены"""
        grid_prices = np.array([1000, 1200, 1400, 1600, 1800, 2000])
        
        # Точное соответствие
        assert find_grid_level(1200, grid_prices) == 1
        
        # Ближайший уровень
        assert find_grid_level(1300, grid_prices) == 1  # Ближе к 1200
        assert find_grid_level(1350, grid_prices) == 2  # Ближе к 1400 